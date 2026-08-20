# Gabia 배포 준비

기준 서버는 가비아 Ubuntu 22.04 LTS + SSH, API 단일 worker, Supabase Managed
PostgreSQL이다. 이 디렉터리는 Docker Compose와 Nginx 구성을 고정하지만, 실제
서버 접속·secret 입력·domain/TLS 발급은 배포 직전에 수행한다.

## 구성

```text
Nginx :80
  ├─ /             Kiosk static frontend
  ├─ /manager/     Manager static frontend
  ├─ /media/       /srv/mcm/media (Range 지원)
  ├─ /api/         FastAPI :8000
  └─ /vision/      Vision Gateway WebSocket :8765

Eye worker :8766  (Compose private network only, Python 3.12.10)
Supabase            (application IPv4 session pooler)
```

## 서버 최초 준비

```bash
sudo mkdir -p /srv/mcm/{media,models,backups}
sudo chown -R "$USER":"$USER" /srv/mcm
git clone <private-repository-url> /srv/mcm/app
cd /srv/mcm/app
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
```

`deploy/.env.example`을 복사한 runtime 파일에는 `OPENAI_API_KEY`, `DATABASE_URL`
session pooler URL, `VISION_STREAM_TOKEN_SECRET`만 직접 입력한다. direct DB credential은
별도 `deploy/.env.admin.example` 형식을 사용하고 Compose/Vite에는 전달하지 않는다. key와
password는 Git, 채팅, image layer에 넣지 않는다.

Supabase migration은 IPv4 session pooler가 아닌 direct connection으로 실행한다.

```bash
export MIGRATION_DATABASE_URL='<Supabase direct PostgreSQL URL>'
uv run --project apps/api python -m apps.api.scripts.db_migrate --dry-run
uv run --project apps/api python -m apps.api.scripts.db_migrate --execute
uv run --project apps/api python -m apps.api.scripts.db_seed_catalog --dry-run
uv run --project apps/api python -m apps.api.scripts.db_seed_catalog --execute
unset MIGRATION_DATABASE_URL
```

기존 `0001`, `0002`, `0003`은 수정하지 않고 `0004`(catalog PDP 상태), `0005`(backend RLS)까지
순서대로 적용한다. seed는 기존 승인 행을
덮어쓰지 않으며 불일치하면 실패한다. 그 다음 application `DATABASE_URL`은 IPv4 session
pooler를 사용한다. API startup은 catalog가 정확히 10개인지 확인하고, 남은
`pending|running` job은 `service_restart` 실패로 정리한다. observation/frame/timeline은
DB에서 복구하지 않는다.

### 기존 migration marker가 다른 경우

이전 환경에 `0004_supabase_backend_rls` marker만 있고
`0004_catalog_pdp_source_status`, `0005_supabase_backend_rls` marker가 없을 수 있다.
이 경우 marker를 직접 rename·insert·delete하지 않는다. 그렇게 하면 공식 product page가
검증된 catalog 상태를 허용하는 constraint가 빠진 채 readiness를 가장할 수 있다.

direct PostgreSQL connection으로 backup을 먼저 만든 뒤, 위의 일반 `db_migrate --execute`
명령을 그대로 실행한다. 모든 migration은 idempotent하게 작성되어 있으므로 기존 table·RLS
policy를 재생성하고 누락된 catalog constraint와 두 현재 marker를 함께 맞춘다. 그 다음
`db_seed_catalog --execute`가 새 canonical catalog version의 정확히 10개 행을 insert하고
동일 key의 기존 행은 덮어쓰지 않는다. 마지막으로 runtime session pooler를 사용한 API의
`/readyz`가 200이 되는지 확인한다.

direct URL이 연결되지 않거나 `db_migrate`가 실패하면 marker를 수동 수정하지 말고 중단한다.
그 상태에서는 runtime pooler가 연결되어 있어도 deployment readiness는 완료가 아니다.

## DB 보존·cleanup과 backup/restore

DB에는 catalog와 최소 final job/decision metadata만 남는다. 기본 보유 기간은 terminal
metadata 24시간, active orphan 30분이다. 단일 API worker의 maintenance task가 정리하며,
동일 범위를 payload나 job ID 출력 없이 수동 실행할 수 있다.

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml run --rm --no-deps api \
  python -m apps.api.scripts.db_cleanup --dry-run
docker compose --env-file deploy/.env -f deploy/docker-compose.yml run --rm --no-deps api \
  python -m apps.api.scripts.db_cleanup --execute
```

Backup은 direct connection으로 custom-format 파일을 만들고 권한 정보를 제외한다. 이 명령은
production DB를 수정하지 않는다.

```bash
export MIGRATION_DATABASE_URL='<Supabase direct PostgreSQL URL>'
pg_dump --format=custom --no-owner --no-acl \
  --file "/srv/mcm/backups/mcm-$(date +%Y%m%dT%H%M%S).dump" \
  "$MIGRATION_DATABASE_URL"
unset MIGRATION_DATABASE_URL
```

Restore는 production이 아닌 **새 빈 검증 project/database**의 direct URL만 사용한다.
`--clean`, `DROP DATABASE` 또는 production URL 대상 restore는 사용하지 않는다.

```bash
export RESTORE_DATABASE_URL='<separate empty verification DB direct URL>'
pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
  --dbname "$RESTORE_DATABASE_URL" /srv/mcm/backups/<selected-backup>.dump
psql "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -c \
  "SELECT migration_id FROM mcm_schema_migration ORDER BY migration_id;"
psql "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -c \
  "SELECT catalog_version, count(*) FROM recommendation_catalog_v2 GROUP BY catalog_version ORDER BY catalog_version;"
unset RESTORE_DATABASE_URL
```

복구 확인은 canonical revision이 정확히 10행인지 확인한 뒤, 검증 project의 session pooler를
임시 API `DATABASE_URL`로 사용해 `/readyz=200`인지 확인한다. credential이 없으면 위 명령은
문서/dry-run으로만 남기며 성공으로 보고하지 않는다.

## 영상·모델 자산

개발 PC에서 먼저 검증한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stage_lookbook_media.ps1
```

이 명령은 `C:\Users\andyw\Desktop\mcm 동영상.mp4`를 Git에 넣지 않고
`apps/kiosk/public/media/mcm-lookbook-v2.mp4`에 복사한다. 배포 시에는 별도로
다음 위치에 복사한다.

staging 직후 exact identity를 다시 확인한다. 성공 기준은 SHA-256
`dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89`, 5,754,164 bytes,
33,500ms, 1280×720, 24FPS다. script는 값을 자동 수정하지 않고 불일치 시 실패한다.

```powershell
uv run --project apps/api python -m apps.api.scripts.verify_lookbook_media
```

```bash
install -m 0644 /path/to/mcm-lookbook-v2.mp4 /srv/mcm/media/mcm-lookbook-v2.mp4
uv run --project services/eye python services/eye/scripts/prepare_eyetrax_model.py \
  --model-path /srv/mcm/models/face_landmarker.task --offline
```

Eye asset의 SHA-256은 `services/eye`의 고정 검증 로직을 통과해야 한다. 상품 이미지와
QR은 `/srv/mcm/media/products/`와 `/srv/mcm/media/qr/`에 두며, official URL·SHA-256·회사
허가 note를 `recommendation_catalog_asset_v2`에 기록한 뒤 catalog의 approved asset을
갱신한다.

## Luna synthetic canary

API와 DB를 기동하지 않고 production Luna adapter를 정확히 한 번 검증한다. 아래 세
flag는 모두 필수이며, command에는 재시도 loop가 없다. 출력은 성공 여부, 선택 상품 ID,
검증 코드와 호출 횟수만 포함한다. provider가 요청을 거절하면 raw body 대신
`provider_http_<status>`와 allowlist된 `error.type`, `error.code`, `error.param`만 추가로
출력한다. provider message와 raw body는 출력하지 않는다.

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml build api
docker compose --env-file deploy/.env -f deploy/docker-compose.yml run --rm --no-deps api \
  python -m apps.api.scripts.luna_canary --live --synthetic-only --max-calls 1
```

실패 시 mock 성공이나 임의 상품으로 대체하지 않는다. 두 번째 실호출은 별도의 명시적
승인 없이는 실행하지 않는다.

## 실행

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
curl -f http://127.0.0.1/healthz
curl -f http://127.0.0.1/readyz
```

현재 Nginx template은 HTTP 기준이다. public domain을 확정한 뒤에만 인증서 발급,
HTTP→HTTPS redirect, `wss://` 원격 camera E2E를 추가한다. public IP만으로는 고객
브라우저 camera 운영을 acceptance로 보지 않는다.

## GitHub main 자동 배포

[`deploy-production.yml`](../.github/workflows/deploy-production.yml)은 `main` push와
수동 실행을 production deployment로 기록한다. Frontend test·lint·build, Contract
검증과 Backend contract·integration test가 모두 통과한 뒤에만 Gabia 서버로 정확한
Git commit archive를 전송한다.

GitHub repository Actions secrets에는 다음 값만 등록한다.

- `DEPLOY_HOST`: Gabia public host
- `DEPLOY_USER`: 전용 공개키가 등록된 SSH 사용자
- `DEPLOY_SSH_KEY`: GitHub Actions 배포 전용 private key
- `DEPLOY_KNOWN_HOSTS`: 신뢰한 서버의 pinned SSH host key

운영 `OPENAI_API_KEY`, `DATABASE_URL`, `VISION_STREAM_TOKEN_SECRET`은 GitHub로
전송하지 않는다. 서버의 `/srv/mcm/shared/deploy.env`에 권한 `0600`으로 보관하고
새 릴리스가 이를 복사해 사용한다. Migration과 seed는 자동 배포에서 실행하지 않는다.

서버의 [`deploy-release.sh`](deploy-release.sh)는
`/srv/mcm/releases/<commit-run-attempt>`에 새 릴리스를 만들고 commit별 Docker image를
모두 빌드한 뒤에만 `/srv/mcm/current`를 전환한다. 공개 `/readyz`, Kiosk root, 영상
Range 응답과 모든 Compose service를 검증한다. 전환 뒤 검증이 실패하면 보존된 이전
릴리스 symlink와 image로 자동 복구하며 기존 릴리스는 자동 삭제하지 않는다.

## 배포 전 확인

- `npm test`, `npm run lint`, `npm run build`를 Node 24.19.0에서 실행
- API·Face·Eye·Vision·Contract·Integration 테스트 통과
- video `Range` 응답과 `/media/` static path 확인
- camera 권한 → calibration → Eye → Gateway → API → 정확히 10개 중 Top 1 확인
  (`VISION_EXPRESSION_MODE=disabled`인 현재 배포에서는 표정을 `not_observed`로 유지)
- actual AOI metadata를 담당자가 `approved`로 고정하고 Vision 3-B
  (valid gaze → video time/point → product/component/tag → aggregate evidence) 통과
- cancel, insufficient-data, provider failure, duplicate complete와 30분 orphan cleanup 확인
- Supabase backup/restore를 direct connection으로 한 번 검증

현재 actual AOI revision은 `pending_review`이므로 첫 유효 영상 좌표에서
`aoi_metadata_unapproved`가 정상 결과다. 이 상태는 Vision 3-A 완료를 뜻하지만 위 3-B와
Top 1 실제 영상 acceptance는 아직 통과한 것이 아니다.

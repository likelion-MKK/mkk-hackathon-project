# 가비아 배포 운영 기록 (yangyu.cloud)

2026-08-19/20에 실제로 수행한 배포 절차와, 팀원이 코드를 고쳐 다시 올리는 방법을 적는다.
`deploy/README.md`가 설계 기준이라면 이 문서는 **실제 서버에서 돌아간 명령**과 그 과정에서
드러난 함정을 남긴 운영 기록이다.

## 1. 서버 현황

| 항목 | 값 |
|---|---|
| 도메인 | `https://yangyu.cloud` |
| 공인 IP | `1.201.116.174` |
| OS | Ubuntu 24.04.4 LTS |
| 사양 | 2 vCore / 4GB RAM / 96GB disk |
| SSH 계정 | `ubuntu` (PEM key) |
| Docker | Docker CE 29.7.2 + Compose v5.5.0 |
| swap | 2GB (`/swapfile`, `/etc/fstab` 등록됨) |
| 공개 포트 | 22, 80, 443 만 (보안 그룹) |

서버 안에서만 도는 것: API `8000`, Vision Gateway `8765`, Eye worker `8766`,
Nginx `8080`. 외부에는 Caddy(80/443)만 노출된다.

```
인터넷 ──▶ Caddy :443 (Let's Encrypt 자동 갱신)
             └─▶ Nginx :8080
                   ├─ /                    Kiosk 정적 파일
                   ├─ /manager/            Manager 정적 파일
                   ├─ /media/              공유 볼륨 (룩북 영상)
                   ├─ /assets/products/    공유 볼륨 (상품 이미지)
                   ├─ /api/  /healthz  /readyz   FastAPI :8000
                   └─ /vision/             Vision Gateway :8765 (WebSocket)
Eye worker :8766   Compose 내부 네트워크 전용
Supabase           IPv4 session pooler (외부 관리형 DB)
```

## 2. 디렉터리 배치

```
/srv/mcm/
├── current -> releases/<timestamp>/     # 활성 릴리즈 심볼릭 링크
├── releases/
│   └── 20260820013359/                  # git archive HEAD 결과 + 덮어쓴 수정 파일
│       ├── deploy/.env                  # 권한 600, secret 보관
│       └── ...
└── shared/                              # 릴리즈 교체와 무관하게 유지
    ├── media/
    │   ├── mcm-lookbook-v2.mp4
    │   └── products/<product_id>/<product_id>.jpeg   # 10개
    ├── models/face_landmarker.task
    └── admin.env                        # 권한 600, MIGRATION_DATABASE_URL
```

`shared/`는 릴리즈를 갈아끼워도 지우지 않는다. secret·영상·모델·상품 이미지는 전부 여기 있다.

## 3. 최초 구축 절차 (이미 완료됨)

기록용이며 서버를 새로 만들 때만 다시 필요하다.

```bash
# 3-1. swap 2GB — 4GB RAM에서 npm/mediapipe 빌드가 OOM으로 죽는 것을 막는다
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 3-2. Docker CE + Compose plugin
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu

# 3-3. 디렉터리
sudo mkdir -p /srv/mcm/{releases,shared/media/products,shared/models,shared/backups}
sudo chown -R ubuntu:ubuntu /srv/mcm
```

가비아 콘솔에서 **보안 그룹 인바운드 80/443 TCP `0.0.0.0/0`** 을 열고,
**DNS A 레코드 `yangyu.cloud` → `1.201.116.174`** 를 설정해야 Let's Encrypt HTTP-01
인증이 통과한다. 둘 중 하나라도 빠지면 Caddy가 인증서를 못 받는다.

## 4. 자산 스테이징

릴리즈와 분리해서 `shared/`에 올린다. 값은 SHA-256으로 검증한다.

```bash
# 룩북 영상 — 반드시 아래 해시/크기와 일치해야 한다
#   sha256 dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89
#   5,754,164 bytes / 33,500ms / 1280x720 / 24fps
scp -i "$PEM" apps/kiosk/public/media/mcm-lookbook-v2.mp4 \
    ubuntu@1.201.116.174:/srv/mcm/shared/media/

# Eye 모델
scp -i "$PEM" services/eye/.cache/face_landmarker.task \
    ubuntu@1.201.116.174:/srv/mcm/shared/models/

# 상품 이미지 10개 — 반드시 product_id 하위 디렉터리 구조여야 한다
#   /srv/mcm/shared/media/products/<product_id>/<product_id>.jpeg
```

> **함정**: catalog의 `image_asset_path`는 스키마가
> `assets/products/<name>/<file>` 형태를 강제한다(첫 세그먼트에 점 불가).
> `assets/products/<id>.jpeg` 처럼 평평하게 두면 `load_canonical_catalog`가
> 10개 상품 전부 ValidationError로 거부한다. 그래서 이미지도 상품별 하위
> 디렉터리에 넣고, Nginx `/assets/products/`가 공유 볼륨을 alias한다.

## 5. 릴리즈 배포

```bash
export PEM="/path/to/SSH_KeyPair-260819023919.pem"
export SRV="ubuntu@1.201.116.174"
TS=$(date +%Y%m%d%H%M%S)

# 5-1. 커밋된 트리만 번들로 만든다 (작업 중인 dirty 변경은 제외)
git archive HEAD --format=tar.gz -o /tmp/repo.tar.gz

# 5-2. 업로드 후 전개
ssh -i "$PEM" "$SRV" "mkdir -p /srv/mcm/releases/$TS"
scp -i "$PEM" /tmp/repo.tar.gz "$SRV:/srv/mcm/releases/$TS/"
ssh -i "$PEM" "$SRV" "cd /srv/mcm/releases/$TS && tar xzf repo.tar.gz && rm repo.tar.gz"

# 5-3. 환경파일 (secret은 화면에 찍지 말고 파일째 전송)
scp -i "$PEM" ./deploy/.env.server "$SRV:/srv/mcm/releases/$TS/deploy/.env"
ssh -i "$PEM" "$SRV" "chmod 600 /srv/mcm/releases/$TS/deploy/.env"

# 5-4. 활성 링크를 원자적으로 교체
ssh -i "$PEM" "$SRV" "
  ln -sfn /srv/mcm/releases/$TS /srv/mcm/current.next &&
  mv -Tf /srv/mcm/current.next /srv/mcm/current"

# 5-5. 빌드 후 기동
ssh -i "$PEM" "$SRV" '
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps'
```

전체 빌드는 2 vCore 기준 8~15분 걸린다. 한 서비스만 고쳤다면 그 서비스만
`build <service>` 하면 1~2분이면 끝난다.

## 6. 배포 검증

```bash
curl -sS -o /dev/null -w "healthz %{http_code}\n" https://yangyu.cloud/healthz   # 200
curl -sS -o /dev/null -w "readyz  %{http_code}\n" https://yangyu.cloud/readyz    # 200
curl -sS -o /dev/null -w "image   %{http_code} %{content_type}\n" \
  https://yangyu.cloud/assets/products/mcm-toni-medium-disco-visetos/mcm-toni-medium-disco-visetos.jpeg
# 200 image/jpeg 여야 한다. text/html 이면 SPA fallback으로 샌 것이다.
```

세션 생성 → signed token → WSS `ready` 까지 확인하는 종단 점검:

```bash
ssh -i "$PEM" "$SRV" '
cd /srv/mcm/current
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T vision-gateway python3 - <<PY
import asyncio, json, httpx, websockets
async def main():
    async with httpx.AsyncClient(base_url="https://yangyu.cloud") as c:
        r = await c.post("/api/v1/sessions", json={"kiosk_id":"probe",
            "lookbook_id":"mcm-lookbook-v2","consent_version":"v1"},
            headers={"Origin":"https://yangyu.cloud"})
        sid = r.json()["session_id"]
        t = (await c.post(f"/api/v1/sessions/{sid}/vision-stream-token", json={},
            headers={"Origin":"https://yangyu.cloud"})).json()
    async with websockets.connect("wss://yangyu.cloud/vision/v1/stream",
            additional_headers={"Origin":"https://yangyu.cloud"}) as ws:
        await ws.send(json.dumps({"type":"hello","protocol_version":"1.0",
            "session_id":t["session_id"],"video_id":t["video_id"],
            "stream_token":t["stream_token"],"offered_frame_encodings":["image/jpeg"]}))
        print(json.loads(await ws.recv())["type"])   # ready
asyncio.run(main())
PY'
```

## 7. 팀원이 코드를 고쳐 배포하는 방법

### 7-1. 준비 (최초 1회)

PEM 키를 받아 권한을 잠그고 접속을 확인한다. 키 내용은 채팅·이슈·PR에 붙여넣지 않는다.

```bash
chmod 600 ~/keys/SSH_KeyPair-260819023919.pem
ssh -i ~/keys/SSH_KeyPair-260819023919.pem ubuntu@1.201.116.174 'echo OK'
```

### 7-2. 로컬에서 고치고 반드시 먼저 검증한다

```bash
# Kiosk / Manager 를 고쳤다면
npm run lint --workspace apps/kiosk
npm test --workspace apps/kiosk

# API 를 고쳤다면
uv run --project apps/api python -m pytest apps/api/tests -q
```

서버에서 빌드가 깨지면 되돌리는 데 10분 이상 쓰게 된다. 로컬 검증이 훨씬 싸다.

### 7-3. 고친 파일만 올려서 해당 서비스만 다시 빌드한다

전체 재배포 없이 반복 수정할 때 쓰는 가장 빠른 경로다.

```bash
PEM=~/keys/SSH_KeyPair-260819023919.pem
SRV=ubuntu@1.201.116.174
REL=$(ssh -i $PEM $SRV 'readlink -f /srv/mcm/current')

# 예: 키오스크 화면 문구를 고친 경우
scp -i $PEM apps/kiosk/src/App.tsx $SRV:$REL/apps/kiosk/src/App.tsx

ssh -i $PEM $SRV "
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build web
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d web"
```

파일 → 다시 빌드할 서비스 대응표:

| 고친 곳 | 빌드할 서비스 |
|---|---|
| `apps/kiosk/**`, `apps/manager/**`, `deploy/nginx.conf` | `web` |
| `apps/api/**`, `services/recommendation/**`, `data/products/**`, `experiments/recommendation/prompts/**` | `api` |
| `apps/vision_gateway/**`, `apps/common/**`, `services/face/**` | `vision-gateway` |
| `services/eye/**` | `eye-worker` |
| `deploy/Caddyfile` | `caddy` (`restart`만 해도 됨) |

`deploy/.env`만 바꿨다면 빌드 없이 `up -d <service>`로 재생성하면 된다.

### 7-4. 확인과 되돌리기

```bash
ssh -i $PEM $SRV 'cd /srv/mcm/current &&
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps'
ssh -i $PEM $SRV 'cd /srv/mcm/current &&
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail=50 api'
```

문제가 생기면 직전 릴리즈로 링크를 되돌리고 다시 기동한다.

```bash
ssh -i $PEM $SRV '
  ls -1 /srv/mcm/releases | sort | tail -3          # 직전 timestamp 확인
  ln -sfn /srv/mcm/releases/<이전timestamp> /srv/mcm/current.next
  mv -Tf /srv/mcm/current.next /srv/mcm/current
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d'
```

### 7-5. 지켜야 할 선

- `deploy/.env`와 `shared/admin.env`는 권한 600을 유지하고 값을 화면에 출력하지 않는다.
  전송은 `scp`로 파일째 한다.
- `apps/api/migrations/*.sql`은 수정하지 않는다. 번호는 `[1..N]` 연속이어야 하며
  중복 번호가 생기면 `db_migrate`가 아예 실행을 거부한다.
- 상품 catalog를 승격할 때는 기존 행을 덮어쓰지 말고 **새 `catalog_version`**으로
  넣는다. seed는 `ON CONFLICT DO NOTHING` 후 DB와 JSON을 대조 검증하므로,
  같은 버전에 다른 내용을 넣으려 하면 실패한다.
- 로컬 개발 포트 8000/8765는 서버 포트와 무관하다. 서버 서비스는 Compose가 관리한다.

## 8. 배포하며 실제로 밟은 함정

다시 만나면 시간을 아끼기 위해 남긴다.

**Eye worker 빌드 실패** — `services/face`는 Python 3.13.15를 고정 요구하는데
`Dockerfile.eye`의 베이스는 3.12.10이었다. eye worker 코드는 `services/face`를
import하지 않으므로 해당 설치를 제거했다.

**Eye worker 기동 후 `eye_not_connected`** — `eyetrax`가 GUI판 `opencv-python`을
끌고 오는데 slim 이미지에 `libGL.so.1`이 없어 모델 초기화가 조용히 실패했다.
`libgl1`, `libglib2.0-0`을 설치해 해결했다. 증상 확인은
`GET http://127.0.0.1:8766/health`의 `failure_reason` 필드로 한다.

**Vision Gateway `ModuleNotFoundError: starlette`** — `local_server.py`가 starlette를
직접 import하는데 설치 목록에서 빠져 있었다.

**API 기동 거부 `CENTRAL_AI_PROMPT_VERSION must match approved`** — `.env`의 프롬프트
버전이 코드 상수와 다르면 부팅 자체를 거부한다. 프롬프트를 새로 만들면
`APPROVED_PROMPT_VERSION`, `LUNA_PROMPT_SHA256`, `LUNA_PROMPT_PATH`, 그리고 `.env`를
함께 갱신해야 한다. 프롬프트 파일은 SHA-256으로 고정되어 있다.

**Supabase direct 연결 불가** — `db.<ref>.supabase.co`는 AAAA(IPv6) 레코드만 있고
가비아 서버에는 IPv6 경로가 없다. migration/seed를 서버에서 direct URL로 돌릴 수
없으므로, catalog seed는 Supabase 대시보드 SQL Editor에서 수행했다. 런타임은 IPv4
session pooler를 쓰므로 영향 없다.

**추천이 즉시 실패하고 DB에 기록도 안 남음** — `decision_request_id`가
`sha256(session_id)`로만 만들어지는데 세션 ID는 메모리 카운터라 API를 재시작하면
`session-0001`부터 다시 시작한다. 그래서 이전 실행의 행과 primary key가 충돌해
`save_pending`이 실패하고, job이 시작조차 못 한 채 `model_unavailable`로 끝났다.
digest에 프로세스별 run scope를 섞어 해결했다(`v2_store.py`). 재시작이 잦은
데모 환경에서는 반드시 필요한 수정이다.

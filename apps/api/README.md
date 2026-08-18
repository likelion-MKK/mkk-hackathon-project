# API App

## 소유자

박형진(PM·BE). REST·polling·PostgreSQL migration과 공용 계약 변경을 직렬로 관리한다.

## 현재 기준

운영 방향은 Contract v2의 hosted Luna 중앙 추천 AI와 단일 상품 Top 1이다. 기존
`/api/v1`의 Mock/`gaze-score-v0` Top 2는 회귀 호환과 replay 연구용 baseline으로만
남아 있으며 운영 추천 품질을 뜻하지 않는다.

v2 흐름은 다음과 같다.

1. actual session 생성 시 `lookbook_id=mcm-lookbook-v2`를 사용하고
   `/api/v2/lookbooks/{lookbook_id}/manifest`를 조회한다.
2. Kiosk가 같은 `frame_id`의 파생 시선·영상 좌표·관찰 가능한 얼굴 동작과 연속성 feature를
   `POST /api/v2/sessions/{session_id}/observations`에 bounded batch로 보낸다.
3. Backend만 승인 AOI metadata를 조회해 캡처 시점 `video_time_ms + video_x_norm/y_norm`을
   상품·부위·controlled visual tag로 변환한다. Kiosk가 product candidate를 보내면 거절한다.
4. `POST /api/v2/sessions/{session_id}/complete`는 동일 요청에 같은 job ID를 반환한다.
   Kiosk는 `GET /api/v2/sessions/{session_id}/recommendation`을 polling한다. 처리 중에는
   202 `pending`, 종료 후에는 200 `completed|insufficient_data|failed`다.
5. 중앙 모델은 canonical catalog의 정확히 10개 후보를 모두 받는다. 결과는 정확히 한
   상품 ID, allowlist reason/style code와 실제 evidence window ID만 통과한다.
6. 고객이 명시적으로 요청했을 때만
   `POST /api/v2/sessions/{session_id}/manager-product-requests`가 발생한다. Manager는
   `/api/v2/manager/events`와 `/api/v2/products/{product_id}`를 사용한다.

원본 frame·영상·image bytes·base64·얼굴 embedding·원본 경로는 모든 REST 모델,
DB, cache, queue와 로그에서 금지한다. v2 frame timeline은 프로세스 메모리에만 최대
512개를 두며 complete/cancel/fail/TTL 시 즉시 폐기한다. PostgreSQL에는 정확히 10개
상품 catalog와 job metadata, 검증된 최종 decision만 저장한다.

## PostgreSQL

Supabase 연결은 역할별로 분리한다.

- 실행 중 API의 `DATABASE_URL`: IPv4 session pooler 전용
- migration·catalog seed·backup/restore의 `MIGRATION_DATABASE_URL`: direct PostgreSQL 전용
- direct URL은 Docker Compose, Vite 또는 브라우저 환경에 주입하지 않는다.

기존 `0001`, `0002`, `0003`은 수정하지 않는다. `0003_api_db_operations.sql`은 내부 job 상태
`pending|running|completed|failed|cancelled|insufficient_data`, 원자적 claim, active-session
unique index, migration marker와 cleanup index를 추가한다. `0004_supabase_backend_rls.sql`은
browser-facing `anon`/`authenticated` role의 public table 접근을 차단하고 backend role만
허용한다. observation/timeline 테이블은
의도적으로 없으며 이전 revision이 저장했을 수 있는 자유형 explanation/evidence/style/
data_quality도 정확히 `recommendation_job_v2`에서 비운다.

credential 없이 migration과 canonical 10개 seed 입력을 먼저 검증한다. 아래 운영
스크립트 명령은 Python package 경계가 보존되도록 **저장소 루트에서** 실행한다.

```powershell
uv run --project apps/api --locked python -m apps.api.scripts.db_migrate --dry-run
uv run --project apps/api --locked python -m apps.api.scripts.db_seed_catalog --dry-run
```

실제 관리 작업은 direct URL을 process 환경변수로만 주입한 shell에서 명시적으로 실행한다.

```powershell
$env:MIGRATION_DATABASE_URL='<Supabase direct PostgreSQL URL>'
uv run --project apps/api --locked python -m apps.api.scripts.db_migrate --execute
uv run --project apps/api --locked python -m apps.api.scripts.db_seed_catalog --execute
Remove-Item Env:MIGRATION_DATABASE_URL
```

Seed는 `ON CONFLICT DO NOTHING`만 사용한다. 이미 존재하는 동일 revision 행을 덮어쓰지 않고,
DB의 product ID·controlled tag·reviewed field를 canonical JSON과 비교한다. 9개, 11개,
다른 revision, 알 수 없는 ID나 tag 불일치는 자동 보정하지 않고 readiness 실패다.

API startup은 DB가 준비됐을 때만 기존 `pending|running`을 `failed + service_restart`로
종료한다. evidence는 복구하거나 재실행하지 않는다. DB 장애가 있어도 `/healthz`는 200을
유지할 수 있지만 `/readyz`는 제한된 reason code와 HTTP 503을 반환하고 새 durable 추천
job은 받지 않는다. DB 없는 local memory adapter의 `/readyz=503 database_not_configured`도
production readiness를 가장하지 않기 위한 정상 동작이다.

Actual `mcm-lookbook-v2` media identity는 SHA-256
`dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89`, 5,754,164 bytes,
33,500ms, 1280×720, 24FPS로 고정했다. 현재 actual AOI revision은 `pending_review`라서
영상 안의 유효 좌표가 도착하면 `aoi_metadata_unapproved`로 fail-closed한다. 60초
`mcm-central-ai-replay-v2`는 승인된 synthetic contract fixture일 뿐 actual media가 아니다.

## 환경 변수

- `DATABASE_URL`: 실행 API의 Supabase IPv4 **session pooler** URL(기본 포트 `5432`)만 허용한다.
- `MIGRATION_DATABASE_URL`: migration·seed·backup/restore shell에서만 쓰는 Supabase **direct** URL(기본 포트 `5432`)만 허용한다.
- `DB_CONNECT_TIMEOUT_SECONDS`: readiness 연결 제한, 기본 5초.
- `CENTRAL_AI_PROVIDER`: production은 `openai_luna`로 고정한다. 미설정은 mock 성공이 아니라
  `model_unavailable`로 종료한다.
- `OPENAI_API_KEY`: process secret으로만 주입하며 request body·raw response와 함께 로그에 남기지 않는다.
- `CENTRAL_AI_MODEL_ID`, `CENTRAL_AI_MODEL_REVISION`, `CENTRAL_AI_PROMPT_VERSION`: Luna 결과 version 기록.
- `CENTRAL_AI_REASONING_EFFORT=max`, `CENTRAL_AI_REASONING_CONTEXT=current_turn`, `CENTRAL_AI_INPUT_VARIANT=C`.
- `VISION_STREAM_TOKEN_SECRET`, `VISION_EYE_WORKER_URL`: API·Vision Gateway shared token과 private Eye worker 경계.
- `LOOKBOOK_VIDEO_PATH`, `REQUIRE_LOOKBOOK_MEDIA_READINESS`: actual MP4의 exact SHA/byte readiness. 배포 Compose는 검증을 필수로 한다.
- `KIOSK_CORS_ORIGINS`: 쉼표로 구분한 명시적 origin. wildcard는 거부한다.
- `V2_COLLECTING_TTL_SECONDS`, `V2_PENDING_TTL_SECONDS`, `V2_DECISION_TTL_SECONDS`:
  메모리 수명, 기본 300/1800/900초. `V2_PENDING_TTL_SECONDS`는 orphan 기준보다 길게
  설정할 수 없으므로 pending evidence가 DB orphan cleanup 뒤에도 메모리에 남지 않는다.
- `V2_ORPHAN_JOB_SECONDS`: DB `pending|running` orphan 기준, 기본 1800초.
- `V2_JOB_RETENTION_SECONDS`: terminal job metadata 보유 기간, 기본 86400초(24시간).
- `V2_MAINTENANCE_INTERVAL_SECONDS`: 단일 API worker cleanup 주기, 기본 60초.
- `RECOMMENDATION_ENGINE`: v1 전용 `mock|research_version` compatibility 설정.

Luna 호출은 Responses API, `store=false`, tools/web/conversation 없음, max output token
미설정, timeout 없음, retry 0이다. 기존 self-hosted endpoint는 migration compatibility
seam으로만 남긴다. API 코드는 중앙 AI request/response body를 logging하지 않으며 reverse
proxy·APM·access-log에서도 request body capture를 꺼야 한다.

DB에는 catalog와 job status/timestamp, 선택 상품, controlled reason/version만 남긴다.
raw frame/image/video, token, 개별 gaze 좌표, frame timeline, 원본 evidence, 자유형 모델
explanation/input/output은 저장하지 않는다. cancel 뒤 늦은 결과는 메모리 job ID와 DB의
조건부 terminal transition을 모두 통과할 수 없어 폐기된다.

## Health, cleanup과 단일 worker

- `GET /healthz`: DB와 분리된 process liveness
- `GET /readyz`: DB, `0004` migration, canonical catalog 10개와 job intake readiness
- `GET /api/v1/health`: 호환용 deprecated combined view

Compose와 Dockerfile은 API `--workers 1`, 중앙 job concurrency 2로 고정한다. DB claim은
`UPDATE ... WHERE status='pending' RETURNING`이고 active-session unique index도 있어 같은
job의 중복 claim을 막는다. 메모리 evidence 구조 때문에 실제 다중 API process 운영은
이번 배포 범위가 아니다.

내부 maintenance task와 같은 범위의 cleanup을 수동으로 미리 보거나 실행할 수 있다.

```powershell
uv run --project apps/api --locked python -m apps.api.scripts.db_cleanup --dry-run
# 실제 실행은 DATABASE_URL을 주입한 운영 shell에서만 수행한다.
uv run --project apps/api --locked python -m apps.api.scripts.db_cleanup --execute
```

출력은 처리 count만 포함하며 job ID나 payload/evidence를 기록하지 않는다. backup/restore의
격리 DB 검증 순서는 [`deploy/README.md`](../../deploy/README.md)에 있다.

## 실행과 검증

```powershell
Set-Location apps/api
uv sync --locked
uv run uvicorn app.main:app --reload
uv run --locked pytest
```

실제 영상 readiness는 저장소 루트에서 검증한다.

```powershell
uv run --project apps/api python -m apps.api.scripts.verify_lookbook_media
```

계약을 함께 바꿨다면 저장소 루트에서 `python scripts/validate_contracts.py`도 실행한다.

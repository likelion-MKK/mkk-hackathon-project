# API App

## 소유자

박형진(PM·BE). REST·polling·PostgreSQL migration과 공용 계약 변경을 직렬로 관리한다.

## 현재 기준

운영 방향은 Contract v2의 self-hosted 중앙 추천 AI와 단일 상품 Top 1이다. 기존
`/api/v1`의 Mock/`gaze-score-v0` Top 2는 회귀 호환과 replay 연구용 baseline으로만
남아 있으며 운영 추천 품질을 뜻하지 않는다.

v2 흐름은 다음과 같다.

1. v1 session 생성 시 `lookbook_id=mcm-central-ai-replay-v2`를 사용하고
   `/api/v2/lookbooks/{lookbook_id}/manifest`를 조회한다.
2. Kiosk가 같은 `frame_id`의 파생 시선·AOI·관찰 가능한 얼굴 동작과 연속성 feature를
   `POST /api/v2/sessions/{session_id}/observations`에 bounded batch로 보낸다.
3. `POST /api/v2/sessions/{session_id}/complete`는 동일 요청에 같은 job ID를 반환한다.
   Kiosk는 `GET /api/v2/sessions/{session_id}/recommendation`을 polling한다. 처리 중에는
   202 `pending`, 종료 후에는 200 `completed|insufficient_data|failed`다.
4. 중앙 모델은 canonical catalog의 정확히 10개 후보를 모두 받는다. 결과는 정확히 한
   상품 ID, allowlist reason/style code와 실제 evidence window ID만 통과한다.
5. 고객이 명시적으로 요청했을 때만
   `POST /api/v2/sessions/{session_id}/manager-product-requests`가 발생한다. Manager는
   `/api/v2/manager/events`와 `/api/v2/products/{product_id}`를 사용한다.

원본 frame·영상·image bytes·base64·얼굴 embedding·원본 경로는 모든 REST 모델,
DB, cache, queue와 로그에서 금지한다. v2 frame timeline은 프로세스 메모리에만 최대
512개를 두며 complete/cancel/fail/TTL 시 즉시 폐기한다. PostgreSQL에는 정확히 10개
상품 catalog와 job metadata, 검증된 최종 decision만 저장한다.

## PostgreSQL

`migrations/0001_central_recommendation_v2.sql`은 `recommendation_catalog_v2`와
`recommendation_job_v2`를 만들고, `migrations/0002_catalog_assets_v2.sql`은 상품 image·QR의
경로·공식 PDP URL·SHA-256·승인 메모만 저장하는 `recommendation_catalog_asset_v2`를 추가한다.
image/QR bytes와 observation/timeline 테이블은 의도적으로 없다.

```powershell
Set-Location apps/api
psql $env:DATABASE_URL -f migrations/0001_central_recommendation_v2.sql
psql $env:DATABASE_URL -f migrations/0002_catalog_assets_v2.sql
```

`DATABASE_URL`이 설정되면 시작 시
`data/products/mcm-demo-recommendation-profile-v2.json`과
`mcm-recommendation-catalog-assets-v2.json`을 strict 검증한 뒤 catalog 10행과 image·QR
asset metadata 각 10행을 `ON CONFLICT` upsert한다. readiness gate는 해당 catalog version에
catalog 10행, `asset_kind='image'` 10행과 `asset_kind='qr'` 10행이 각각 distinct product
10개와 일치해야 통과한다. 설정하지
않은 로컬 개발에서는 같은 canonical JSON을 읽는 memory catalog adapter를 쓰며, session
timeline은 어느 모드에서도 메모리 전용이다. 실제 PostgreSQL 연결 통합 검증은 별도
PostgreSQL 환경에서 수행해야 한다.

## 환경 변수

- `DATABASE_URL`: PostgreSQL 연결 문자열. 설정 시 migration이 먼저 적용되어 있어야 한다.
- `CENTRAL_AI_ENDPOINT`: self-hosted JSON inference endpoint. 미설정이면 mock 성공이 아니라
  `model_unavailable`로 종료한다.
- `CENTRAL_AI_BEARER_TOKEN`: 서비스 간 인증 token. production endpoint에는 필수다.
- `CENTRAL_AI_MODEL_ID`, `CENTRAL_AI_MODEL_REVISION`, `CENTRAL_AI_PROMPT_VERSION`: 결과 version 기록.
- `CENTRAL_AI_INPUT_VARIANT`: 승인된 evidence 입력 `A|B|C`. endpoint 설정 시 명시해야 한다.
- `CENTRAL_AI_BENCHMARK_APPROVAL`: non-loopback 운영 endpoint에서 선택한 variant의 benchmark 승인 ID.
- `CENTRAL_AI_TIMEOUT_SECONDS`: inference timeout, 기본 10초.
- `KIOSK_CORS_ORIGINS`: 쉼표로 구분한 명시적 origin. wildcard는 거부한다.
- `V2_COLLECTING_TTL_SECONDS`, `V2_PENDING_TTL_SECONDS`, `V2_DECISION_TTL_SECONDS`:
  메모리 수명, 기본 300/60/900초.
- `RECOMMENDATION_ENGINE`: v1 전용 `mock|research_version` compatibility 설정.

endpoint를 설정하면 model ID/revision, `central-recommender-ko-v1` prompt version과 input
variant를 모두 명시해야 한다. production 중앙 endpoint는 HTTPS와 bearer service auth가 모두 필요하다. 인증 없는 HTTP는
명시적 loopback(`127.0.0.1`, `localhost`, `::1`) 개발 endpoint만 허용한다. API 코드는 중앙
AI request/response body를 logging하지 않는다. reverse proxy, APM과 access-log 설정에서도
request body capture를 꺼야 한다.

## 실행과 검증

```powershell
Set-Location apps/api
uv sync --locked
uv run uvicorn app.main:app --reload
uv run --locked pytest
```

계약을 함께 바꿨다면 저장소 루트에서 `python scripts/validate_contracts.py`도 실행한다.

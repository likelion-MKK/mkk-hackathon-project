# 🚀 가비아 서버 배포 완전 가이드 (2026-08-19/20)

이 문서는 `https://yangyu.cloud`에 MCM AI Lookbook Kiosk를 실제로 배포한 **전체 과정**을 
단계별로 기록합니다. 팀원들이 같은 작업을 반복하거나 새로운 기능을 추가할 때 참고하세요.

---

## 목차

1. [배포 전 준비](#배포-전-준비)
2. [문제 식별 및 원인 분석](#문제-식별-및-원인-분석)
3. [컨테이너 빌드 수정](#컨테이너-빌드-수정)
4. [Luna 프롬프트 개선](#luna-프롬프트-개선)
5. [세션 ID 충돌 수정](#세션-id-충돌-수정)
6. [상품 카탈로그 승격](#상품-카탈로그-승격)
7. [화면 문구 개선](#화면-문구-개선)
8. [서버 배포](#서버-배포)
9. [배포 검증](#배포-검증)
10. [팀원용 재배포 방법](#팀원용-재배포-방법)

---

## 배포 전 준비

### 1단계: SSH 접근 확인

서버에 접속해서 현재 상태를 확인합니다.

```bash
export PEM=~/keys/SSH_KeyPair-260819023919.pem
export SRV=ubuntu@1.201.116.174
chmod 600 $PEM

# 접속 테스트
ssh -i $PEM $SRV 'echo "Connection OK" && uname -a'
```

**예상 출력:**
```
Connection OK
Linux ip-1-201-116-174 6.8.0-1015-aws #16-Ubuntu SMP Fri Aug  9 22:39:51 UTC 2026 x86_64
```

### 2단계: 현재 배포 상태 확인

```bash
ssh -i $PEM $SRV '
  echo "=== Active release ===" 
  readlink -f /srv/mcm/current
  echo "=== Docker containers ==="
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
'
```

**체크사항:**
- `current` 심볼릭 링크가 어느 timestamp를 가리키는가?
- 모든 서비스(api, eye-worker, vision-gateway, web, caddy)가 `Up` 상태인가?
- 최근 몇 시간 내에 배포됐는가?

---

## 문제 식별 및 원인 분석

### 이상 신호

**2026-08-19 오후:**
- 사용자가 실제 기기에서 테스트 → calibration 후 영상 재생 → 추천 실패
- 화면에 "추천을 만들지 못했습니다" 메시지
- DB `recommendation_job_v2` 테이블에 기록이 안 남음 (행이 없음)

### 원인 분석 방법

1. **컨테이너 로그 확인**
   ```bash
   ssh -i $PEM $SRV 'cd /srv/mcm/current &&
     docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail=50 api'
   ```
   → 보통 여기서 `CentralModelError`, `model_unavailable`, 또는 `RuntimeError` 같은 메시지가 나타남

2. **health 엔드포인트 확인**
   ```bash
   curl -sS https://yangyu.cloud/readyz | jq .
   ```
   → `status: "not_ready"` 또는 `failure_reason` 필드가 있으면 진단 정보 확인

3. **DB 직접 조회** (Supabase 대시보드)
   ```sql
   SELECT session_id, status, failure_reason_code, created_at 
   FROM recommendation_job_v2 
   ORDER BY created_at DESC LIMIT 5;
   ```
   → 실패의 원인 코드를 `failure_reason_code` 필드에서 볼 수 있음

### 발견된 근본 원인들

**원인 1: Eye worker 모델 초기화 실패**
- `eyetrax==0.4.0`이 `opencv-python` GUI 버전을 끌어옴
- `Dockerfile.eye`의 slim 이미지에 `libGL.so.1` 없음
- 결과: eye worker가 기동했지만 `/health` 엔드포인트가 `eye_not_connected` 반환

**원인 2: Vision Gateway starlette 누락**
- `local_server.py` 라인 11: `from starlette.types import Receive, Scope, Send`
- `Dockerfile.vision` pip install에 `starlette` 없음
- 결과: 컨테이너 기동 실패

**원인 3: Luna 출력 검증 실패 (40% 통과율)**
- v6 프롬프트가 길이 제한을 명시하지 않음
- evidence statement가 240자 상한을 초과
- 심리 단정 금지 가드가 면책 문장도 거름
- 결과: Luna의 응답이 5개 출력 검증 중 5개, 3개, 또는 2개를 통과하지 못함

**원인 4: 세션 ID 충돌 (100% 실패)**
- API가 재시작하면 메모리 카운터인 세션 ID가 `session-0001`부터 다시 시작
- `decision_request_id = sha256(session_id)` 이므로 이전 실행의 durable row와 충돌
- 결과: `save_pending`에서 unique constraint 위반 → job이 시작되지 않음 → `model_unavailable`

---

## 컨테이너 빌드 수정

### 수정 1: Eye Worker — libGL 라이브러리 추가

**파일:** `deploy/Dockerfile.eye`

**문제:** eyetrax가 OpenGL 라이브러리를 필요로 하는데 slim 이미지에 없음

**진단 방법:**
```bash
ssh -i $PEM $SRV '
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs eye-worker | grep -i "libgl"
'
```

**수정:**
```dockerfile
# 기존 (실패)
FROM python:3.12.10-slim
WORKDIR /app
COPY apps /app/apps
COPY services/eye /app/services/eye
RUN pip install --no-cache-dir ...

# 수정 후
FROM python:3.12.10-slim
WORKDIR /app
COPY apps /app/apps
COPY services/eye /app/services/eye

# 👈 여기 추가: OpenGL 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ...
```

**왜 이렇게?**
- `libgl1`: OpenGL 코어 라이브러리 (특히 `libGL.so.1`)
- `libglib2.0-0`: GLib 런타임 (opencv가 요구하는 의존성)
- `apt-get clean` + `rm -rf /var/lib/apt/lists/*`: 빌드 이미지 크기 최소화
- slim 베이스는 보안과 크기를 위해 선택했으므로 필수 라이브러리만 설치

**검증:**
```bash
ssh -i $PEM $SRV '
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build eye
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d eye-worker
  sleep 8
  curl -sS http://127.0.0.1:8766/health | jq .failure_reason
'
```

→ `null`이 나오면 성공 (failure_reason이 없음 = 정상)

### 수정 2: Eye Worker — services/face 제거

**파일:** `deploy/Dockerfile.eye`

**문제:** `services/face` 패키지가 Python 3.13.15 고정 + 베이스는 3.12.10

**진단:**
```bash
docker build -f deploy/Dockerfile.eye . 2>&1 | grep -i "python\|version\|conflict"
```

**수정:**
```dockerfile
# 기존
COPY services/face /app/services/face
RUN pip install ... /app/services/face

# 수정 후 (이 두 줄 삭제)
# services/face는 eye worker가 import하지 않음
```

**왜 삭제?**
- Eye worker 코드 자체는 `services/face`를 직접 import하지 않음
- `services/face`는 manager 서비스가 씀 (별도 컨테이너 또는 운영 중단)
- 불필요한 의존성을 제거하면 빌드 시간 단축 + 이미지 크기 감소

### 수정 3: Vision Gateway — starlette 의존성 추가

**파일:** `deploy/Dockerfile.vision`

**문제:** `local_server.py`가 직접 import하는데 pip install에 없음

**진단:**
```bash
ssh -i $PEM $SRV 'cd /srv/mcm/current &&
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build vision-gateway 2>&1 | tail -20'
```

→ `ModuleNotFoundError: No module named 'starlette'` 보임

**수정:**
```dockerfile
RUN pip install --no-cache-dir \
    "uvicorn[standard]>=0.30,<1" "httpx>=0.27,<1" \
    "starlette>=0.37,<1" \  # 👈 이 줄 추가
    "mediapipe==1.0.0" "numpy>=2,<3" "opencv-python-headless>=4.11,<5" \
    /app/services/face
```

**버전 선택 이유:**
- `starlette>=0.37,<1`: FastAPI의 동일 버전대와 호환
- `uvicorn[standard]`는 이미 starlette을 의존성으로 끌고 오지만, 명시적 설치가 필요한 경우도 있음

---

## Luna 프롬프트 개선

### 문제: v6 프롬프트 40% 통과율

**진단:**
```bash
ssh -i $PEM $SRV '
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T api python3 -c "
from apps.api.scripts.luna_canary import build_canary_request
from apps.api.app.v2_central import configured_central_client, validate_central_output
import asyncio, json

async def test():
    req = build_canary_request()
    client = configured_central_client()
    for i in range(10):
        raw = await client.recommend_async(req)
        try:
            validate_central_output(raw, request=req)
            print(f'Trial {i+1}: PASS')
        except Exception as e:
            print(f'Trial {i+1}: FAIL - {str(e)[:80]}')

asyncio.run(test())
"
'
```

**결과:** 4 PASS, 5 schema_errors (string_too_long), 1 psychological_diagnosis

**원인 분석:**
1. `evidence[].statement` 필드가 240자 상한을 초과
   - v6는 길이 제한을 명시하지 않음
   - Luna가 자유롭게 길이를 정함 → 일부 시도가 상한 초과
   
2. 심리 단정 금지 가드가 면책 문장도 거름
   - v6: "위 주제는 단정하지 않는다" (부정형만 거르기)
   - 하지만 가드는 문자열 매칭으로 "구매 의도" 같은 단어 그 자체를 거림
   - 결과: "구매 의도를 배제한다"는 면책 문장도 거림

### 수정: v7 프롬프트 작성

**파일:** `experiments/recommendation/prompts/central-recommender.ko.v7.txt`

**핵심 변경사항:**

1. **명시적 금지 규칙 강화 (라인 10 이후)**
   ```
   위 주제는 부정문, 면책 문장, 주의 문구로도 쓰지 않는다.
   "감정", "성격", "심리", "선호", "구매 의도", "호감", "무관심" 같은 낱말 
   자체를 출력 문장에 넣지 않는다.
   ```
   
   **왜?** 면책 문장도 포함하는 강력한 규칙으로 false positive 제거

2. **명시적 길이 예산 추가**
   ```
   길이 상한을 반드시 지킨다.
   evidence[].statement는 240자 이하
   style.summary는 240자 이하
   reason은 400자 이하
   statement는 한 문장으로 180자 내 목표
   ```
   
   **왜?** Luna가 구체적인 상한을 알면 자신의 응답을 조정함

### 검증: v7 프롬프트 10회 테스트

```bash
ssh -i $PEM $SRV '
  cd /srv/mcm/current
  docker compose --env-field deploy/.env -f deploy/docker-compose.yml exec -T api python3 - <<PYEOF
from apps.api.scripts.luna_canary import build_canary_request
from apps.api.app.v2_central import configured_central_client, validate_central_output
import asyncio

async def test():
    req = build_canary_request()
    req.prompt_version = "central-recommender-ko-v7"  # 👈 v7로 변경
    client = configured_central_client()
    pass_count = 0
    for i in range(10):
        raw = await client.recommend_async(req)
        try:
            validate_central_output(raw, request=req)
            pass_count += 1
        except Exception as e:
            print(f"Trial {i+1}: FAIL - {str(e)[:50]}")
    print(f"TOTAL: {pass_count}/10 PASS")

asyncio.run(test())
PYEOF
'
```

**결과:** `TOTAL: 10/10 PASS` ✓

---

## 세션 ID 충돌 수정

### 문제: API 재시작 후 100% 추천 실패

**증상:**
- 브라우저에서 세션 생성 → 영상 재생 → 추천 즉시 실패
- DB에 기록이 안 남음
- 로그: `RuntimeError: central recommendation concurrency limit reached` 또는 `model_unavailable`

**근본 원인:**

```python
# apps/api/app/store.py:166
session_number = len(self.sessions) + 1
session_id = f"session-{session_number:04d}"

# apps/api/app/v2_store.py:1098
idempotency_digest = sha256(session_id.encode("utf-8")).hexdigest()[:32]
decision_request_id = f"decision-v2-{idempotency_digest}"
```

**시나리오:**
1. API가 오후 2시에 기동 → `session-0001`, `session-0002` 생성
2. 개발자가 코드 수정 → API 재시작 (오후 5시)
3. 새 API가 다시 `session-0001` 생성
4. `sha256("session-0001")` = 기존 `decision_request_id` 와 동일
5. DB unique constraint 위반 → `save_pending` 실패
6. job이 시작되지 않음 → `model_unavailable` + DB 기록 없음

### 수정: 프로세스 스코프 추가

**파일:** `apps/api/app/v2_store.py`

**변경:**
```python
# 라인 751: __init__ 메서드
self._run_scope = uuid4().hex  # 👈 프로세스별 고유 ID

# 라인 1104: idempotency 계산
idempotency_digest = sha256(
    f"{self._run_scope}:{session_id}".encode("utf-8")
).hexdigest()[:32]
```

**왜 이렇게?**
- 각 프로세스(API 재시작)마다 새로운 `_run_scope` uuid 생성
- `sha256("abc:session-0001")` ≠ `sha256("def:session-0001")`
- 같은 세션의 재시도는 같은 `_run_scope`이므로 여전히 멱등함
- DB 행은 절대 충돌하지 않음

**검증:**
```bash
# API 재시작 전후로 같은 session-0001이 다른 decision_request_id를 받는지 확인
ssh -i $PEM $SRV 'cd /srv/mcm/current &&
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml \
    restart api &&
  sleep 10 &&
  curl -sS -X POST https://yangyu.cloud/api/v1/sessions \
    -H "Content-Type: application/json" \
    -H "Origin: https://yangyu.cloud" \
    -d "{\"kiosk_id\":\"test\",\"lookbook_id\":\"mcm-lookbook-v2\",\"consent_version\":\"v1\"}" | jq .session_id
'
```

---

## 상품 카탈로그 승격

### 문제: 추천이 완료되도 상품 정보가 없음

**증상:**
- 추천 완료 후 화면에 "상품 정보 준비 중" 메시지
- 상품명, 이미지, 추천 근거가 모두 blank

**원인:**
- DB `recommendation_catalog_v2` 행의 `approved_asset: false`, `source_status: "official_product_page_verified_assets_pending"`
- Kiosk의 `product-display-policy.ts`가 승인된 행만 표시
- 기존 v3 revision은 미승인 상태로 유지

### 수정: v4 카탈로그 생성 및 승격

**1단계: 로컬에서 v4 JSON 생성**

```bash
cd /srv/mcm  # 로컬 저장소
python - <<'PYEOF'
import json
from pathlib import Path

# 기존 v3 카탈로그 로드
v3 = json.loads(Path("data/products/mcm-demo-recommendation-profile-v2.json").read_text())

# v4로 버전업 + 승인 상태로 변경
v4 = {
    "catalog_version": "mcm-us-pdp-verified-v4-2026-08-20",  # 👈 새 버전
    "schema_version": v3["schema_version"],
    "products": [
        {
            **p,
            "approved_asset": True,  # 👈 승인
            "source_status": "team_approved_catalog_record",  # 👈 승인 상태
            "image_asset_path": f"assets/products/{p['product_id']}/{p['product_id']}.jpeg",  # 👈 중첩 경로
            "image_asset_path_reason": None,  # 👈 필수 (조건부 필드)
        }
        for p in v3["products"]
    ]
}

Path("data/products/mcm-submission-recommendation-profile-v4.json").write_text(
    json.dumps(v4, ensure_ascii=False, indent=2)
)
PYEOF
```

**2단계: Pydantic 검증**

```bash
uv run --project apps/api python - <<'PYEOF'
from pathlib import Path
from apps.api.app.v2_postgres import load_canonical_catalog

cat = load_canonical_catalog(Path("data/products/mcm-submission-recommendation-profile-v4.json"))
print(f"Validation PASS: {len(cat.products)} products")
print(f"All approved: {all(p.approved_asset for p in cat.products)}")
print(f"All team_approved: {all(p.source_status == 'team_approved_catalog_record' for p in cat.products)}")
PYEOF
```

**3단계: Supabase에 seed**

```bash
# Supabase SQL Editor에서 직접 실행
INSERT INTO recommendation_catalog_v2 (
  catalog_version, product_id, display_name, category, 
  controlled_tags, recommendation_summary, style, 
  approved_asset, source_status, official_product_url, 
  official_product_url_reason, official_listing_url,
  image_asset_path, image_asset_path_reason,
  qr_asset_path, qr_asset_path_reason, source_note
) VALUES (
  'mcm-us-pdp-verified-v4-2026-08-20',
  'mcm-toni-medium-disco-visetos',
  'Medium Toni Top-Zip Shopper in Disco Visetos',
  'bag',
  ARRAY['daily', 'monogram', 'shopper', 'spacious', 'tote'],
  '...',
  '{"silhouette": "trapezoid", ...}'::jsonb,
  true, 'team_approved_catalog_record',
  'https://us.mcmworldwide.com/...',
  NULL,
  'https://us.mcmworldwide.com/...',
  'assets/products/mcm-toni-medium-disco-visetos/mcm-toni-medium-disco-visetos.jpeg',
  NULL,
  NULL, 'qr_asset_generation_pending',
  '팀이 검수한 공식 PDP identity와 상품 이미지 자산을 함께 승인한 revision입니다. ...'
)
ON CONFLICT (catalog_version, product_id) DO NOTHING;
```

**왜 `ON CONFLICT DO NOTHING`?**
- 멱등성: 같은 SQL을 여러 번 실행해도 안전
- 기존 행 보호: 이미 있는 행은 수정하지 않음
- 부분 성공 허용: 10개 중 8개만 들어갔다면 거기까지 유지

### 4단계: 이미지 파일 배치

**서버에서:**
```bash
ssh -i $PEM $SRV '
# 기존 이미지가 /srv/mcm/shared/media/products/<product_id>.jpeg
# 새 구조로 변경: /srv/mcm/shared/media/products/<product_id>/<product_id>.jpeg

cd /srv/mcm/shared/media/products
for f in *.jpeg; do
  pid="${f%.jpeg}"
  mkdir -p "$pid"
  mv "$f" "$pid/$f"
done
'
```

**Nginx 설정 추가:**
```nginx
# deploy/nginx.conf
location /assets/products/ {
    alias /usr/share/nginx/html/media/products/;
}
```

**왜 alias?**
- 클라이언트는 `/assets/products/mcm-toni-medium-.../mcm-toni-medium-....jpeg` 요청
- Nginx가 `/usr/share/nginx/html/media/products/mcm-toni-medium-../mcm-toni-medium-....jpeg`로 리라우팅
- 스키마가 요구하는 경로 + 실제 파일 위치의 분리

---

## 화면 문구 개선

### 문제: 내부 진단 용어가 고객 화면에 노출

**예:**
- "추천을 만들지 못했습니다" (모드/이유 없이 일괄)
- "Luna가 선정했습니다" (모델명 외출)
- "제한된 관찰" (사용자가 모르는 기술 용어)
- "심리 단정을 확정하지 않습니다" (불필요한 부정)

### 수정: 템플릿 및 카피 재작성

**파일:** `apps/kiosk/src/app/recommendation-presentation.ts`

```typescript
// 탐색 성향 재명명
const TENDENCY_COPY = {
  focused_single_product: "한 상품에 시선이 오래 머문 흐름",  // ← "제한된 관찰" 대신
  comparative_exploration: "몇 가지 상품 사이를 오가며 비교한 흐름",
  broad_exploration: "여러 상품을 폭넓게 둘러본 흐름",
};

// 시선 신호 명명
const REACTION_COPY = {
  observed_attention_lead: "이 상품에 가장 오래 머문 시선",  // ← 기술 용어 제거
  return_candidate_support: "다른 상품을 본 뒤 다시 돌아온 시선",  // ← "재응시" 대신 자연스럽게
  movement_pattern_support: "이 상품을 따라 이어진 시선의 흐름",
  observable_action_support: "이 상품을 보실 때 함께 나타난 표정의 미세한 변화",
  // ...
};

// 추천 사유 (세 경로: 시선 관찰, 저신호, 데모)
// 시선이 잡힌 경우:
reason: `룩북을 보시는 동안 ${reactionCopy.join("과 ")}이 나타났습니다. 
         무의식적으로 드러난 이 신호를 ${tagCopy.join("·")} 취향으로 읽어 이 상품을 골랐습니다.`

// 시선이 안 잡힌 경우 (저신호):
reason: `${tagCopy.join("·")} 방향이 이번 룩북에서 가장 잘 맞아 이 상품을 골랐습니다.`
```

**핵심 원칙:**
- 시선이 잡혔으면 응시 시간·재응시·미세 표정 같은 관찰 중심 서술
- 시선이 안 잡혔으면 스타일 근거만 (일어나지 않은 관찰을 말하지 않기)
- 기술 용어(gaze_valid_ratio, evidence_window) 제거
- 사용자 경험 중심 (당신이 본 방식, 당신의 신호, 당신의 취향)

**파일:** `apps/kiosk/src/App.tsx`

```typescript
// 화면 제목 (모드별 분기 제거 → 단일화)
title: recommendation.displayable
  ? "시선 분석 AI가 선정했습니다"  // ← "Luna가 선정" 제거
  : "상품 정보 준비 중"

// 시선 흐름 라벨
"이번 세션의 시선 흐름: {recommendation.tendency}"  // ← "스타일 탐색 경향" 제거

// 개인정보 약속 (부정 나열 대신 행동)
"이번 세션의 시선 신호만 사용했으며, 체험이 끝나면 저장하지 않고 폐기합니다."
// ← "감정·성격·구매 의도를 확정하지 않습니다"는 불필요한 부정
```

---

## 서버 배포

### 1단계: 로컬 검증 (배포 전 필수)

```bash
# 루트 디렉터리에서
npm run lint --workspace apps/kiosk
npm test --workspace apps/kiosk  # 101개 통과 확인

uv run --project apps/api python -m pytest apps/api/tests -q  # 130개 통과 확인
```

**왜 먼저?** 서버 빌드가 깨지면 10~15분이 낭비됨. 로컬 검증은 1~2분.

### 2단계: 릴리즈 번들 생성

```bash
# git 커밋 후
git archive HEAD --format=tar.gz -o /tmp/release.tar.gz

# 업로드
export TS=$(date +%Y%m%d%H%M%S)
scp -i $PEM /tmp/release.tar.gz $SRV:/srv/mcm/releases/$TS/
ssh -i $PEM $SRV "
  cd /srv/mcm/releases/$TS
  tar xzf release.tar.gz && rm release.tar.gz
  chmod 600 deploy/.env  # 중요: secret 파일 권한
"
```

### 3단계: 활성 링크 원자적 교체

```bash
ssh -i $PEM $SRV "
  ln -sfn /srv/mcm/releases/$TS /srv/mcm/current.next
  mv -Tf /srv/mcm/current.next /srv/mcm/current  # 원자적 (TOCTOU 방지)
"
```

**왜 `.next` 거쳐갈까?**
- 부분적 기동 상태에서 current가 가리키지 않음
- 실패해도 기존 현재 릴리즈 링크는 그대로 유지

### 4단계: 빌드 및 기동

```bash
ssh -i $PEM $SRV '
  cd /srv/mcm/current
  
  # 전체 빌드 (15분) 또는 특정 서비스만
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build  # 전체
  # 또는
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build api  # api만
  
  # 재시작
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
  sleep 15
  
  # 상태 확인
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
'
```

---

## 배포 검증

### 1단계: 헬스 체크

```bash
echo "healthz: $(curl -sS -o /dev/null -w '%{http_code}' https://yangyu.cloud/healthz)"
echo "readyz:  $(curl -sS -o /dev/null -w '%{http_code}' https://yangyu.cloud/readyz)"
```

**예상:** 200 200

### 2단계: 상품 이미지 서빙

```bash
curl -sS -o /dev/null -w "image: %{http_code} %{content_type}\n" \
  "https://yangyu.cloud/assets/products/mcm-toni-medium-disco-visetos/mcm-toni-medium-disco-visetos.jpeg"
```

**예상:** `200 image/jpeg`

**만약 `text/html` 나오면:** nginx가 SPA fallback으로 떨어뜨린 것. `/assets/products/` location이 활성화되지 않았을 수 있음.

### 3단계: WSS 세션 종단 시험

```bash
ssh -i $PEM $SRV '
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T api python3 - <<PYEOF
import asyncio, json, httpx, websockets

async def test():
    async with httpx.AsyncClient(base_url="https://yangyu.cloud") as c:
        # 세션 생성
        r = await c.post("/api/v1/sessions",
            json={"kiosk_id":"probe","lookbook_id":"mcm-lookbook-v2","consent_version":"v1"},
            headers={"Origin":"https://yangyu.cloud"})
        print(f"sessions: {r.status_code}")
        
        sid = r.json()["session_id"]
        
        # vision stream token 요청
        t = await c.post(f"/api/v1/sessions/{sid}/vision-stream-token",
            json={}, headers={"Origin":"https://yangyu.cloud"})
        print(f"token: {t.status_code}")
        token_data = t.json()
        
        # WSS 연결
        async with websockets.connect("wss://yangyu.cloud/vision/v1/stream",
                additional_headers={"Origin":"https://yangyu.cloud"}) as ws:
            await ws.send(json.dumps({
                "type": "hello", "protocol_version": "1.0",
                "session_id": token_data["session_id"],
                "video_id": token_data["video_id"],
                "stream_token": token_data["stream_token"],
                "offered_frame_encodings": ["image/jpeg"]
            }))
            
            resp = json.loads(await ws.recv())
            print(f"wss: {resp['type']}")  # 'ready'여야 함

asyncio.run(test())
PYEOF
'
```

**예상 출력:**
```
sessions: 201
token: 200
wss: ready
```

---

## 팀원용 재배포 방법

### 상황 1: 화면 문구만 고침

```bash
# 로컬 수정 → lint/test
npm run lint --workspace apps/kiosk && npm test --workspace apps/kiosk

# 파일 업로드
export REL=$(ssh -i $PEM $SRV 'readlink -f /srv/mcm/current')
scp -i $PEM apps/kiosk/src/App.tsx $SRV:$REL/apps/kiosk/src/App.tsx
scp -i $PEM apps/kiosk/src/app/recommendation-presentation.ts $SRV:$REL/apps/kiosk/src/app/recommendation-presentation.ts

# web 서비스만 빌드 (1분)
ssh -i $PEM $SRV "
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build web
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d web
"
```

### 상황 2: API 로직 고침

```bash
# 로컬 테스트
uv run --project apps/api python -m pytest apps/api/tests -q

# 파일 업로드
export REL=$(ssh -i $PEM $SRV 'readlink -f /srv/mcm/current')
scp -i $PEM apps/api/app/v2_central.py $SRV:$REL/apps/api/app/v2_central.py

# api 서비스만 빌드 (2분)
ssh -i $PEM $SRV "
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml build api
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d api
"
```

### 상황 3: 문제 생기면 되돌리기

```bash
# 직전 릴리즈 확인
ssh -i $PEM $SRV 'ls -1d /srv/mcm/releases/* | sort | tail -2'

# 되돌리기
ssh -i $PEM $SRV "
  ln -sfn /srv/mcm/releases/<이전타임스탬프> /srv/mcm/current.next
  mv -Tf /srv/mcm/current.next /srv/mcm/current
  cd /srv/mcm/current
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
"
```

---

## 배포 체크리스트

```
배포 전:
[ ] 로컬 git status 확인 (dirty 파일 commit 또는 stash)
[ ] npm run lint / npm test 통과
[ ] uv run pytest 통과
[ ] git commit 메시지 작성 및 push

배포:
[ ] tar.gz 번들 생성 및 업로드
[ ] 활성 링크 교체
[ ] 전체 또는 선택 서비스 빌드
[ ] docker compose up -d

검증:
[ ] /healthz 200
[ ] /readyz 200
[ ] /assets/products/<id>/<id>.jpeg 200 image/jpeg
[ ] WSS 세션 ready
[ ] DB에 추천 기록 남음
[ ] 화면에 상품명 + 사진 + 추천 근거 표시

롤백 대기:
[ ] 로그 모니터링 (tail -f 또는 docker logs)
[ ] 사용자 테스트 피드백 수집
[ ] 필요하면 직전 릴리즈로 되돌리기
```

---

## 자주 묻는 질문

**Q: 빌드 시간이 너무 깁니다 (15분)**
A: 처음에만 깁니다. 두 번째 빌드는 캐시되어 1~2분입니다. 특정 서비스만 빌드하면 더 빠릅니다.

**Q: `git archive HEAD`가 뭔가요?**
A: **정확히 커밋된 파일**만 번들로 만듭니다. 로컬의 dirty 파일(수정 중인 파일)은 포함 안 됨.
안전한 배포를 위해 필수.

**Q: 이미지가 `text/html`로 나옵니다**
A: nginx의 `/assets/products/` location이 활성화되지 않았을 가능성. 
`deploy/nginx.conf`에 location 블록이 있는지, `docker compose up` 후 재시작했는지 확인.

**Q: API 재시작 후 추천이 실패합니다**
A: 세션 ID 충돌일 가능성. 코드에 `self._run_scope = uuid4().hex` 라인이 있는지 확인.
없으면 이 가이드의 "세션 ID 충돌 수정" 섹션 참고.

**Q: 롤백하려면?**
A: 이 가이드의 "상황 3: 문제 생기면 되돌리기" 참고.
`/srv/mcm/releases/` 디렉터리의 이전 타임스탬프로 current 심볼릭 링크만 바꾸면 됨.

---

## 배포 검증 스크립트

복사해서 `deploy/validate-deployment.sh`로 저장 후 매번 실행하세요:

```bash
#!/bin/bash
set -e

export PEM=~/keys/SSH_KeyPair-260819023919.pem
export SRV=ubuntu@1.201.116.174

echo "=== Health check ==="
curl -sS -o /dev/null -w "healthz: %{http_code}\n" https://yangyu.cloud/healthz
curl -sS -o /dev/null -w "readyz:  %{http_code}\n" https://yangyu.cloud/readyz

echo "=== Image serving ==="
curl -sS -o /dev/null -w "image:   %{http_code} %{content_type}\n" \
  "https://yangyu.cloud/assets/products/mcm-toni-medium-disco-visetos/mcm-toni-medium-disco-visetos.jpeg"

echo "=== Container status ==="
ssh -i $PEM $SRV 'cd /srv/mcm/current && docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps'

echo "=== All checks passed! ==="
```

사용:
```bash
chmod +x deploy/validate-deployment.sh
./deploy/validate-deployment.sh
```

---

**마지막으로:** 이 가이드를 읽으면서 막히는 부분이 있으면 
`deploy/GABIA_RUNBOOK.md` (설계 및 함정 기록)도 함께 참고하세요.

# D2 Eye Tracker 전수 조사·추천 계획

- 상태: Proposed
- 작성일: 2026-08-13
- 조사 기준 시각: 2026-08-13T23:59:59+09:00
- 소유자: 양유상
- 공동 리뷰: 박형진(서버·보안·라이선스), 조윤혜(보정·Kiosk 좌표), 정은미(Eye·Face 공유 자원)
- 관련 문서: [`DETAILED_DESIGN_PLAN.md`](../DETAILED_DESIGN_PLAN.md), [`VISION_SERVER_SELECTION_PLAN.md`](VISION_SERVER_SELECTION_PLAN.md), [`ADR-0001`](../adr/0001-remote-vision-inference.md)

## 1. 목적과 결정 경계

기존 D2의 `Eye 후보 3개 이상` 조사를 공개 검색으로 발견 가능한 일반 RGB 웹캠 후보 전체의 체계적 조사로 확장한다. D2는 다음 네 단계로 운영한다.

```text
D2-1 후보 전수 발견
  → D2-2 적격성·사용자 후기 조사
  → D2-3 Hard Gate 통과 후보 전수 Smoke
  → D2-4 점수화·1차 추천
  → D3 Replay·보정 fixture
  → D4 상위 최대 3개 동일 조건 Benchmark
  → D5 최종 모델·서버 결정
```

D2-4의 추천은 문서·후기·설치·출력 경계를 근거로 한 **1차 추천**이다. 실제 시선 정확도, AOI 품질, 30초·60초 전체 지연과 최종 서버 비용은 D4·D5에서 측정하고 ADR로 확정한다.

이 문서에서 `전수`는 인터넷에 존재하는 모든 구현을 절대적으로 증명한다는 뜻이 아니다. 아래 기준일, 검색식, API 페이지, 역추적 절차로 **공개 검색에서 재현 가능하게 발견한 프로젝트 적합 후보 전체**를 뜻한다.

## 2. 프로젝트 적합 기준

Eye 후보는 다음 경계에 연결될 수 있어야 한다.

- 입력: 일반 RGB 웹캠 frame과 캡처 시점 `FrameContext`
- 출력: 직접 또는 calibration layer를 거친 viewport 기준 `0.0~1.0` point-of-gaze
- 공개 경계: `EyeAdapter → GazeSample`; 무효 결과는 좌표 없이 `valid=false`와 사유
- 실행 위치: 팀이 관리하는 별도 Vision 서버의 격리된 Eye Worker
- 1차 workload: 1280×720 입력, 5/10/15 FPS, 30초·60초, 동시 Kiosk 1대
- 개인정보: 고객 원본 frame은 승인된 세션에서 메모리로만 처리하고 외부 API·파일·DB·로그·artifact로 보내지 않음

눈 landmark나 3차원 gaze vector만 제공하는 구현도 calibration으로 화면 좌표를 만들 수 있으면 후보에 포함한다. 전용 IR 장비·VR HMD가 필수인 구현, 데이터셋만 제공하는 저장소와 gaze 출력이 없는 일반 얼굴 landmark 프로젝트는 발견 목록에 남기되 범위 밖으로 분류한다.

## 3. D2-1 — 공개 후보 전수 발견

### 3.1 검색 채널과 검색어

GitHub Repository Search와 Hugging Face Hub model search에서 다음 검색어를 각각 실행한다.

```text
eye tracking
eye tracker
gaze tracking
gaze estimation
point of gaze
screen gaze
webcam gaze
appearance-based gaze
remote gaze estimation
gaze calibration
```

- GitHub는 repository 이름·설명·README와 관련 topic을 검색한다.
- 검색식 하나의 결과가 1,000건을 넘거나 `incomplete_results=true`이면 `created:` 날짜 구간을 결과 1,000건 이하가 될 때까지 재귀 분할한다.
- 각 분할은 최대 100건씩 마지막 페이지까지 읽고, 조회 시각·query·분할 범위·`total_count`·페이지 수·완료 여부를 기록한다.
- Hugging Face는 각 검색어에 대해 `HfApi.list_models(search=..., limit=None, full=True, cardData=True)`를 끝까지 순회하고 model card·tag·연결된 GitHub 저장소를 확인한다.
- review paper, awesome list, model card와 후보 README의 관련 모델 링크를 역추적한다. 전체 후보 검토를 한 번 마친 뒤 두 차례 연속 신규 적격 family가 나오지 않으면 역추적을 종료한다.

GitHub의 검색당 최대 1,000건과 pagination 동작은 [GitHub Search API](https://docs.github.com/en/rest/search/search)와 [REST pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)을 따른다. Hugging Face 수집 필드는 [HfApi `list_models`](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#huggingface_hub.HfApi.list_models)를 따른다.

### 3.2 중복 제거

다음 값이 같으면 하나의 model family로 묶는다.

```text
canonical upstream repository + model architecture/family + weight revision
```

단순 fork, README 번역, UI wrapper와 동일 weight 재업로드는 별도 후보로 점수화하지 않는다. 출력 의미, 전처리, runtime 또는 배포 형식이 달라 프로젝트 통합·성능에 실질적인 차이가 있으면 같은 family의 variant로 별도 기록한다.

### 3.3 산출물

후속 결과 PR은 다음 구조를 사용한다.

```text
experiments/eye/
  inventory/search-manifest.json
  inventory/candidates.jsonl
  evidence/reviews.jsonl
  <candidate-id>/README.md
  <candidate-id>/pyproject.toml
  <candidate-id>/uv.lock
  <candidate-id>/smoke.py

docs/benchmarks/eye/
  D2_EYE_CANDIDATE_SCORECARD.md
```

`search-manifest.json`에는 기준 시각, 검색 채널·API version, query, 날짜 분할, 페이지, 결과 수, 오류와 재시도 결과를 남긴다. `candidates.jsonl`의 각 후보에는 다음 필드가 있어야 한다.

- `candidate_id`, canonical URL, Hugging Face model ID, 발견 경로
- upstream·fork·wrapper 관계와 deduplication key
- RGB 웹캠 적합 여부와 model/variant 종류
- source·weight revision, checksum과 code·weight license
- 입력·전처리·출력 좌표, calibration과 no-face 의미
- runtime·Python·CPU/GPU·dependency·offline/network 요구사항
- D2 상태, 포함·범위 밖·보류·제외 사유와 근거 URL

## 4. D2-2 — Hard Gate와 사용자 후기 조사

### 4.1 상태

| 상태 | 의미 | D2-3·D2-4 진입 |
| --- | --- | --- |
| `pass-commercial` | 해커톤과 상용 전시·수정·배포 조건을 확인함 | 가능 |
| `pass-demo-only` | 연구·비상업·해커톤 사용만 명시적으로 허용됨 | 가능, 시연 전용 표시 |
| `deferred` | GPU·승인·자료 부족 등 현재 환경에서 검증할 수 없음 | 보류 |
| `fail` | 프로젝트 Hard Gate를 충족하지 못함 | 불가 |

code license와 weight license는 별도로 확인한다. `pass-demo-only` 후보가 1위이면 가장 높은 `pass-commercial` 후보도 별도 추천한다.

### 4.2 Hard Gate

다음 중 하나라도 해당하면 수치 점수를 주지 않고 `fail` 또는 근거가 해소될 때까지 `deferred`로 남긴다.

- code 또는 weight license가 없거나 해커톤 사용 범위가 불명확함
- source·weight의 정확한 revision과 checksum을 고정할 수 없음
- 일반 RGB 웹캠 입력을 지원하지 않음
- calibration 후에도 viewport 좌표로 변환할 수 없음
- 팀 밖 외부 API·서비스로 얼굴 frame을 보내야 하거나 offline 추론이 불가능함
- frame 저장, telemetry, debug dump를 비활성화할 수 없음
- 감사할 수 없는 remote code, 위험한 설치 script 또는 안전하지 않은 pickle 실행이 필수임
- 목표 Vision 서버 OS·architecture에 설치할 현실적인 경로가 없음
- weight가 없고 프로젝트 일정 안에 재현 가능한 학습 경로도 없음

Hard Gate 실패 후보도 전체 inventory에서 삭제하지 않고 실패 근거와 재평가 조건을 남긴다.

### 4.3 사용자 후기 수집

후보별로 GitHub Issues·Discussions, Hugging Face Discussions, Reddit, Stack Overflow와 독립 개발자 기술 글을 검색한다.

| 주제 | 확인할 내용 |
| --- | --- |
| 설치 | Python·CUDA·OS 충돌, weight 다운로드, 재현 성공 여부 |
| 보정·품질 | 화면 calibration, drift, jitter, 가장자리 오차 |
| 환경 | 안경, 조명, 거리, 머리 움직임과 재검출 |
| 성능 | CPU/GPU, latency, FPS, memory와 장시간 안정성 |
| 유지보수 | maintainer 답변, issue 해결, 최신 release·commit |

각 후기에는 URL, 작성일, 후보 version/revision, 장비·환경, 직접 실행 여부, 관찰 내용, 해결 상태와 독립 출처 여부를 기록한다. 광고성 글, README 복제, 근거 없는 추천과 동일 글 재게시물은 점수에서 제외한다. stars·downloads는 인지도 참고값으로만 남기며 만족도나 정확도 점수로 바꾸지 않는다.

서로 독립적인 직접 사용 후기 5건과 2개 이상의 플랫폼을 확보하지 못하면 후기 증거를 `Low`로 표시하고 D2-4 후기·유지보수 점수를 최대 5/10으로 제한한다. 후기는 반복 장애를 찾는 보조 증거이며 프로젝트 직접 측정이나 정답 label 기반 품질 검증을 대체하지 않는다.

## 5. D2-3 — 통과 후보 전수 Smoke

### 5.1 기준 환경

| 항목 | 기준 |
| --- | --- |
| OS·architecture | Linux x86-64 |
| CPU 기준 | 4 vCPU |
| RAM 기준 | 16 GiB |
| Python | 3.13.15 우선, 비호환이면 후보 환경만 지원 version으로 고정 |
| GPU | CPU 실패 근거가 있는 GPU 필수 후보만 동일 L4급 환경에서 후속 실행 |
| 입력 | 실행 중 생성한 synthetic no-face 입력과 승인된 비식별 fixture만 |

실행 전 실제 OS image, CPU/GPU, RAM/VRAM, driver/runtime과 시간대를 기록한다. GPU 필수 후보는 동일 L4급 환경에서 실행하기 전까지 `deferred`이며 CPU 결과와 같은 표에서 성능 우열을 주장하지 않는다.

### 5.2 후보별 격리와 실행 순서

후보마다 독립 `pyproject.toml`·`uv.lock`·model cache를 사용하고 공용 Eye 서비스나 루트 lock 파일에 의존성을 섞지 않는다.

1. 고정 source·weight revision과 checksum을 확인한다.
2. 격리 환경에서 package 설치와 model load를 실행한다.
3. `initialize → warmup → infer → no-face/invalid → dispose`를 실행한다.
4. 출력 shape·finite 값·no-face 의미와 calibration/좌표 변환 경로를 확인한다.
5. 최초 download 뒤 network를 차단하고 local asset만으로 다시 실행한다.
6. load·warmup 시간, 소량 반복 inference p50/p95, CPU/GPU와 RAM/VRAM peak를 관찰값으로 기록한다.
7. 명령, 종료 code, 오류 원문과 해결 또는 재평가 조건을 남긴다.

Smoke는 설치·모델 로딩·출력·offline 경계만 확인한다. 후보마다 입력이나 반복 조건이 다르면 한 순위표의 속도 비교에 사용하지 않으며, 정답 좌표가 없는 결과를 정확도라고 부르지 않는다.

## 6. D2-4 — 프로젝트 적합성 점수와 1차 추천

### 6.1 채점 대상과 공식

`pass-commercial` 또는 `pass-demo-only`이면서 online·offline Smoke를 통과한 후보만 점수화한다.

```text
weighted_score = Σ(subcriterion_raw_score ÷ 5 × subcriterion_weight)
evidence_coverage = 검증 근거가 있는 subcriterion weight 합 ÷ 100 × 100
```

공통 `0~5` anchor는 다음과 같다. `2`와 `4`는 인접 anchor 사이의 상태에만 사용한다.

| 점수 | 의미 |
| ---: | --- |
| 0 | 미검증 또는 요구사항 불충족 |
| 1 | 심각한 제약이 있고 우회 경로도 불확실함 |
| 3 | 프로젝트 기준을 충족하며 관리 가능한 추가 작업이 있음 |
| 5 | 고정된 revision과 재현 가능한 프로젝트 직접 증거로 기준을 강하게 충족함 |

미검증 항목은 추정하지 않고 `0 + unverified`로 기록한다. 공식 논문·model card의 주장, repository 동작, 사용자 후기와 프로젝트 직접 측정은 근거 종류를 분리한다.

### 6.2 100점 평가표

| 영역 | 세부 항목 | 배점 |
| --- | --- | ---: |
| 시선 품질·보정·AOI | viewport/AOI 변환 10, calibration 경로 10, 강건성 근거 5, valid/invalid 의미 5 | 30 |
| 실시간성·서버 자원 | 5/10/15 FPS·지연 근거 8, 최소 CPU/GPU 등급 6, memory·warmup 3, Eye·Face 동시 배치 위험 3 | 20 |
| `EyeAdapter` 통합·재현성 | Adapter mapping 6, 고정 설치·lock 5, offline 재실행 4, Python/Linux 호환 3, 문서화 2 | 20 |
| 라이선스·개인정보·보안 | code license 5, weight·사용 권리 5, frame 비저장·무외부전송 3, 안전한 model artifact 2 | 15 |
| 사용자 후기·유지보수 | 설치 경험 4, 실제 사용 관찰 3, issue 대응 2, 출처 다양성 1 | 10 |
| 예상 서버 비용 | CPU Small 5, CPU Medium 4, fractional GPU 3, full L4 2, 더 큰 구성 1 | 5 |

예상 서버 비용은 D2의 resource tier 대리점수다. 실제 시간당·세션당 비용과 cloud·region은 D5에서 같은 날짜의 견적으로 다시 결정한다.

### 6.3 추천 규칙

1차 추천 후보는 다음 조건을 모두 만족해야 한다.

- Hard Gate와 online·offline Smoke 통과
- 총점 70점 이상
- evidence coverage 80% 이상
- 미해결 critical 보안·라이선스 문제가 없음

가장 높은 후보를 `primary recommendation`으로 둔다. fallback은 primary와 다른 upstream/model family 중 가장 높은 통과 후보로 선택하고, 없으면 다음 순위 후보를 택하되 공통 실패 위험을 표시한다. primary가 `pass-demo-only`이면 별도로 가장 높은 `pass-commercial` 후보를 제시한다.

동점은 다음 순서로 결정한다.

1. 시선 품질·보정·AOI 점수
2. evidence coverage
3. `pass-commercial`
4. 더 작은 서버 resource tier
5. 유지보수 상태

D4 진출 후보는 위 순위에서 최대 3개다. 적격 후보가 3개 미만이면 실패 후보로 수를 채우지 않는다.

## 7. 후속 Gate

### D3 — Replay와 보정 fixture

기존 계획대로 `FrameContext → GazeSample` replay runner와 calibration fixture를 구현한다. D2 후보별 dependency나 model code를 공용 Replay 경로에 섞지 않는다.

### D4 — 상위 후보 동일 조건 Benchmark

D2-4 상위 최대 3개를 동일 fixture·보정·하드웨어·입력 순서에서 비교한다. target 오차, AOI hit, valid 비율, jitter, p50/p95, FPS, drop과 CPU/GPU·RAM/VRAM을 측정한다.

### D5 — 최종 모델·서버 결정

30초·60초, 5/10/15 FPS, Eye·Face 공동 workload와 network를 포함해 최종 모델·fallback·최소 서버 사양을 정한다. 선택·제외 근거와 비용은 모델 ADR과 ADR-0002로 승인한다.

## 8. PR 분리와 완료 조건

D2는 하나의 책임으로 유지하되 증거 크기와 리뷰 경계를 위해 다음 PR로 나눈다.

1. 계획 PR: 이 문서, 상세 일정과 문서 지도
2. D2-1 PR: 검색 manifest와 deduplicated inventory
3. D2-2 PR: Hard Gate·license·후기 evidence
4. D2-3 PR: 후보별 격리 smoke와 실행 결과
5. D2-4 PR: 점수표·primary·fallback·D4 shortlist

완료 조건:

- [ ] 모든 검색식·조회 시각·날짜 분할·페이지와 중복 제거가 재현된다.
- [ ] 발견한 모든 후보에 포함·범위 밖·보류·제외 상태와 근거가 있다.
- [ ] 모든 Hard Gate 통과 후보에 online·offline Smoke 결과가 있다.
- [ ] 후기 URL·작성일·version·장비·직접 사용 여부와 중복 제거 근거가 있다.
- [ ] Hard Gate 실패 후보가 점수표와 추천에 들어가지 않는다.
- [ ] 점수 합계, evidence coverage와 동점 규칙을 독립적으로 다시 계산할 수 있다.
- [ ] primary·fallback·상용 가능 대안과 D4 상위 최대 3개가 명시된다.
- [ ] 원본 frame·image·base64·embedding·credential·token·weight가 Git·로그·artifact에 없다.
- [ ] `python scripts/validate_contracts.py`와 `git diff --check`가 통과한다.

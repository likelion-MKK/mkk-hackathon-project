# 문서 지도와 에이전트 읽기 순서

- 문서 상태: 팀 공통 진입점 v1
- 목적: 사람과 AI 에이전트가 현재 작업에 필요한 문서만 읽고 같은 기준으로 개발하도록 안내한다.
- 적용 범위: 기획, 설계, 구현, 실험, 테스트, PR과 인계

이 문서는 새로운 요구사항을 정의하지 않는다. 요구사항·결정·계약·작업 규칙이 어느 파일에 있는지 연결하는 지도다.

## 1. 처음 들어온 팀원이 읽는 순서

```text
README.md
  → AGENTS.md
  → docs/D1_TECHNICAL_DECISIONS.md
  → 자신의 작업에 맞는 아래 최소 읽기 묶음
  → 담당 디렉터리 README와 계약 fixture
```

프로젝트 전체 구조를 이해해야 할 때만 `docs/OVERALL_DESIGN.md`를 읽고, 스프린트·통합 순서를 확인할 때만 `docs/DETAILED_DESIGN_PLAN.md`를 읽는다. 매일 작업할 때 두 긴 문서를 반복해서 전부 읽을 필요는 없다.

## 2. 공식 문서와 역할

| 문서 | 언제 읽는가 | 이 문서가 답하는 질문 |
| --- | --- | --- |
| [`README.md`](../README.md) | 프로젝트 첫 진입 | 무엇을 만들고 왜 만드는가? |
| [`AGENTS.md`](../AGENTS.md) | 모든 AI 작업 시작 | 어떤 범위·우선순위·안전 규칙으로 일하는가? |
| [`D1_TECHNICAL_DECISIONS.md`](D1_TECHNICAL_DECISIONS.md) | 구현 환경·공통 기본값 확인 | 팀장이 미리 정한 값과 검증 후 확정할 값은 무엇인가? |
| [`OVERALL_DESIGN.md`](OVERALL_DESIGN.md) | 전체 파이프라인과 데이터 수명주기 확인 | 시스템 구성요소가 어떻게 연결되는가? |
| [`DETAILED_DESIGN_PLAN.md`](DETAILED_DESIGN_PLAN.md) | 병렬 개발·통합 계획 확인 | 팀별 경계, 계약과 일별 Gate는 무엇인가? |
| [`contracts/README.md`](../contracts/README.md) | API·event 작업 | 데이터 형식, 좌표·시간·무효 신호 규칙은 무엇인가? |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | branch·PR·병합 | 어떤 순서와 크기로 PR을 만드는가? |
| [`docs/adr/README.md`](adr/README.md) | 기술·모델 결정을 바꿀 때 | 결정 근거와 대안을 어디에 남기는가? |
| [`ADR-0001 원격 Eye·Face 추론 서버 전환`](adr/0001-remote-vision-inference.md) | AI 실행 위치·실시간 frame transport·서버 배포 작업 | Kiosk와 서버의 책임, 비저장 경계, 장애·승인 Gate는 무엇인가? |
| [`docs/benchmarks/README.md`](benchmarks/README.md) | Eye·Face 후보 평가 | 비교 결과와 재현 방법을 어디에 남기는가? |
| [`Face D4 후보 benchmark`](benchmarks/face/README.md) | Face 후보 1차 성능·label 비교 | 동일 synthetic workload의 실행 방법과 D4 결과는 무엇인가? |
| [`Vision 추론 서버 선정·비용 결정 계획`](benchmarks/VISION_SERVER_SELECTION_PLAN.md) | 목표 서버·region·CPU/GPU·비용 결정 | workload와 모델을 고정한 뒤 어떤 Gate 순서로 cloud와 instance를 선택하는가? |
| [`docs/sjf/README.md`](sjf/README.md) | 과거 협업 자료가 필요할 때만 | 참고 자료는 어디에 있는가? |

각 `apps/`, `services/`, `experiments/`, `tests/` 디렉터리의 `README.md`는 해당 영역의 입력·출력·소유자·금지사항을 설명한다.

## 3. 기준이 충돌할 때

| 판단 대상 | 공식 기준 |
| --- | --- |
| 사용자의 최신 요구 | 현재 사용자 요청과 승인된 결정 |
| 기술·운영 기본값 | 승인된 ADR, `D1_TECHNICAL_DECISIONS.md` |
| REST API | `contracts/openapi.yaml` |
| event·manifest 형식 | `contracts/**/*.schema.json` |
| 정상·경계 예시 | `contracts/examples/`, 단 schema와 일치할 때만 |
| 병렬 개발과 통합 순서 | `DETAILED_DESIGN_PLAN.md`, `CONTRIBUTING.md` |
| 서비스 설명 | `README.md`, `OVERALL_DESIGN.md` |

하위 설명 문서가 계약과 다르면 계약을 몰래 바꾸지 않는다. 충돌을 보고하고 `계약 PR → 생산자 PR → 소비자 PR` 순서로 수정한다. 이 지도에 연결되지 않은 초안·개인 메모는 공식 기준이 아니다.

## 4. 작업별 최소 읽기 묶음

아래 파일만 먼저 읽고, 막힐 때 관련 문서를 추가한다.

| 작업 | 먼저 읽을 문서·계약 |
| --- | --- |
| 프로젝트 설명·발표 | `README.md` → `OVERALL_DESIGN.md` |
| Kiosk S01-S04 UI | `D1_TECHNICAL_DECISIONS.md`의 Frontend·Kiosk 항목 → `apps/kiosk/README.md` → `contracts/openapi.yaml` → 필요한 event example |
| Manager UI | `D1_TECHNICAL_DECISIONS.md`의 알림 항목 → `apps/manager/README.md` → `manager-event.schema.json` → `recommendation-result.schema.json` |
| FastAPI·세션·DB | `apps/api/README.md` → `contracts/openapi.yaml` → 관련 schema/example → `D1_TECHNICAL_DECISIONS.md`의 PostgreSQL 항목 |
| Eye Adapter·보정 | `services/eye/README.md` → `gaze-sample.schema.json` → `lookbook-manifest.schema.json` → `D1_TECHNICAL_DECISIONS.md`의 보정·실행 위치 항목 |
| AOI Mapper·룩북 | `services/eye/README.md` → `lookbook-manifest.schema.json`과 example → `product-attention-event.schema.json` → 실제 `data/lookbooks/<version>/manifest.json` |
| Face Adapter | `services/face/README.md` → `expression-sample.schema.json`과 example → `D1_TECHNICAL_DECISIONS.md`의 실행 위치 항목 |
| 원격 Vision Gateway·배포 | `adr/0001-remote-vision-inference.md` → `benchmarks/VISION_SERVER_SELECTION_PLAN.md` → `D1_TECHNICAL_DECISIONS.md`의 D1-05 → `apps/kiosk/README.md` → Eye·Face Adapter 계약 → 승인 후 추가할 Vision Stream v1 |
| 추천 엔진 | `services/recommendation/README.md` → `product-attention-event.schema.json` → `recommendation-result.schema.json` → 알고리즘 ADR |
| 상품·QR | `product-catalog.schema.json`과 example → `data/products/` → `contracts/openapi.yaml` |
| Contract 변경 | `contracts/README.md` → 대상 schema와 정상·invalid example → 생산자·소비자 README → `CONTRIBUTING.md` |
| 모델 후보 조사 | `experiments/<eye 또는 face>/README.md` → `docs/benchmarks/README.md` → `docs/benchmarks/VISION_SERVER_SELECTION_PLAN.md` → 대상 서비스 Adapter 계약 → 관련 ADR |
| 통합·E2E | `DETAILED_DESIGN_PLAN.md`의 Gate·Contract 항목 → `tests/integration/README.md` 또는 `tests/e2e/README.md` → 관련 example |
| PR·릴리스 | `CONTRIBUTING.md` → `.github/PULL_REQUEST_TEMPLATE.md` → 변경 영역 README |

파일명이 표에 짧게 적힌 schema는 모두 `contracts/` 아래에서 찾는다. 먼저 `rg --files contracts` 또는 `rg "필드명" contracts`로 대상 파일을 좁힌다.

## 5. 팀원별 기본 진입점

| 팀원 | 첫 작업 경로 | 기본 문서 묶음 |
| --- | --- | --- |
| 박형진 | `apps/api/`, `services/recommendation/`, `contracts/` | API·DB 또는 추천 최소 묶음 + `CONTRIBUTING.md` |
| 양유상 | `services/eye/`, `experiments/eye/`, `data/lookbooks/` | Eye·보정 또는 AOI 최소 묶음 + benchmark/ADR |
| 정은미 | `services/face/`, `experiments/face/` | Face 최소 묶음 + benchmark/ADR |
| 조윤혜 | `apps/kiosk/`, `apps/manager/` | Kiosk 또는 Manager 최소 묶음 + 필요한 API/event example |

담당자는 다른 팀의 내부 구현보다 자신의 입력·출력 계약을 우선 확인한다. 상대 팀 구현이 없어도 `contracts/examples/`의 fixture와 fake/replay Adapter로 개발을 계속한다.

## 6. 에이전트 병렬 작업 운영

팀장 또는 주 에이전트는 작업을 배정할 때 다음 다섯 가지를 고정한다.

1. 한 문장 목표
2. 수정 가능한 디렉터리와 금지 경로
3. 읽어야 할 최소 문서·계약
4. 결과물과 검증 명령
5. 범위 밖 항목과 다음 담당자

예시:

```text
목표: FakeEyeAdapter가 gaze-sample v1 fixture를 재생하게 한다.
허용 경로: services/eye/adapters/fake/, tests/contract/eye/
읽기: services/eye/README.md, gaze-sample schema와 valid example
완료 조건: valid/invalid sample contract test 통과
범위 밖: 실제 모델 선정, AOI scoring, contract 수정
검증: 해당 unit test + python scripts/validate_contracts.py
```

동시에 움직이는 에이전트끼리 같은 공용 파일을 맡기지 않는다. 계약·migration·lock file·CI·루트 문서 변경은 한 작업으로 따로 떼어 먼저 합친다. 에이전트의 최종 인계는 변경 파일, 검증 결과, 결정/TBD와 다음 담당자만 남긴다.

## 7. 토큰 절약 규칙

- 최초에는 작업별 최소 묶음 2~4개만 읽는다.
- 긴 파일은 먼저 제목을 검색하고 필요한 절만 읽는다.
- schema는 대상 event만 열고 모든 schema를 한 번에 붙여 넣지 않는다.
- 전체 대화 대신 확정 결정 ID, 파일 경로와 contract version을 전달한다.
- 이전 작업 결과는 긴 서술 대신 commit/PR, 변경 파일과 테스트 결과로 인계한다.
- 같은 프로젝트 설명을 새 문서에 반복하지 않고 공식 문서로 링크한다.
- 불확실한 값을 추측해 문맥을 늘리지 말고 `TBD`, 확인자와 결정 Gate를 기록한다.

토큰을 줄이기 위해 검증을 생략하지 않는다. 읽을 범위를 줄이고 contract fixture와 자동 테스트로 사실을 확인한다.

## 8. 문서 수명주기

| 상태 | 처리 방식 |
| --- | --- |
| 공식 | `main`에 있고 이 문서 또는 공식 README에서 연결됨 |
| 제안 | `docs/adr/`에서 `Proposed` 상태로 검토하며 확정값처럼 구현하지 않음 |
| 대체됨 | 새 문서나 ADR을 가리키고 `Superseded` 상태와 이유를 남김 |
| 개인 초안 | 공식 링크에 넣지 않으며 계약·구현의 근거로 사용하지 않음 |

공식 문서를 추가하거나 위치를 바꾸면 이 지도, 관련 README와 링크 검사를 함께 갱신한다. 같은 내용을 여러 문서에서 수정해야 하는 구조가 보이면 하나를 기준 문서로 정하고 나머지는 링크와 짧은 요약만 남긴다.

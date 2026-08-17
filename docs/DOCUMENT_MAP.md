# 문서 지도와 에이전트 읽기 순서

- 상태: **Current canonical map**
- 갱신일: 2026-08-16
- 기준선: `dev` commit `a6eb3d78f47ce38da9d0b2be9b0794479986e280`

이 문서는 새 요구사항을 만들지 않는다. 현재 제품 방향, 승인 결정, 구현 계약, 작업 규칙과 역사 자료의 위치를 구분해 연결한다.

## 1. 기본 읽기 순서

```text
README.md
  → AGENTS.md
  → docs/OVERALL_DESIGN.md
  → docs/IMPLEMENTATION_PLAN.md의 자기 workstream
  → 해당 ADR·Contract·영역 README·fixture
```

중앙 추천 방향을 다루면 [`ADR-0006`](adr/0006-central-recommendation-ai.md)을 반드시 읽는다. 원격 Vision, Face 생산자, Eye 생산자 결정을 바꿀 때만 각각 ADR-0001·0003·0004를 추가한다. Superseded 문서를 현재 기준처럼 읽지 않는다.

## 2. 활성 공식 문서

| 문서 | 역할 | 언제 읽는가 |
| --- | --- | --- |
| [`README.md`](../README.md) | 서비스 목적, 고정 MVP 방향, 사용자 흐름과 현재 상태 | 첫 진입 |
| [`AGENTS.md`](../AGENTS.md) | 우선순위, 소유권, 개인정보·작업 안전 규칙 | 모든 AI 작업 시작 |
| [`OVERALL_DESIGN.md`](OVERALL_DESIGN.md) | canonical 구성요소·데이터 흐름·수명·고객 문구 | 전체 구조·경계 변경 |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | 현재 Contract와 목표의 차이, owner·PR 순서·완료 Gate | 구현·스프린트·인계 |
| [`ADR-0006`](adr/0006-central-recommendation-ai.md) | derived-only self-hosted 중앙 판단, 1회 호출, 가방 10개·Top 1, evidence 폐기 | 추천·DB·프롬프트·결과 UI |
| [`ADR-0007`](adr/0007-central-recommendation-model-selection.md) | 중앙 추천 model·artifact·runtime·variant 선정용 Proposed benchmark 결정 초안 | 후보 provenance·실행·사람 검토·선택 승인 |
| [`ADR-0008`](adr/0008-openai-luna-central-recommendation.md) | Luna Max·max·variant C·prompt v4 선택과 hosted provider 통합 Gate | OpenAI 중앙 추천 선택·timeout·latency·실패 경계 |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | `dev` 기반 branch·PR·Contract First | 작업 시작·PR 준비 |
| [`contracts/README.md`](../contracts/README.md) | 현재 구현 인터페이스, 좌표·시간·invalid 규칙 | producer·consumer·API 변경 |
| [`중앙 추천 self-hosted benchmark`](../experiments/recommendation/README.md) | Google Colab GPU 7개 후보, A/B/C·12개 합성 case, 심리학적 보조 신호 grounding, smoke/full provenance·자원·안전 Gate | 중앙 model·runtime·input variant 평가 |
| [`ADR 목록`](adr/README.md) | ADR 상태·관할과 번호 | 기술 결정 확인·변경 |
| [`2026-08-16 dev 문서·브랜치 감사`](audits/2026-08-16-dev-document-branch-audit.md) | 기준 commit, PR 상태, 문서 정리 범위와 남은 차이 | 이번 방향 전환 근거 확인 |

우선순위는 `현재 사용자 결정 → Accepted ADR → 현재 Contract → OVERALL_DESIGN → IMPLEMENTATION_PLAN → README`다. 목표 문서와 Contract가 다르면 구현 완료로 간주하지 않고 구현 계획의 호환성 차이로 처리한다.

## 3. ADR 관할

| ADR | 상태 | 현재 관할 | 중앙 추천과 관계 |
| --- | --- | --- | --- |
| [`ADR-0001 원격 Eye·Face 추론`](adr/0001-remote-vision-inference.md) | Proposed | 고객 frame의 WSS 전송, Vision Gateway, 원본 비저장·장애·배포 Gate | 추천 AI 입력·파생 수명은 ADR-0006이 관할; frame은 중앙 AI에 전달하지 않음 |
| [`ADR-0003 Face 모델·taxonomy·fallback`](adr/0003-face-model-taxonomy-fallback.md) | Proposed | Face 관찰 신호 생산자, invalid·fallback·lifecycle | 이전 추천 weight 문구는 ADR-0006이 대체 |
| [`ADR-0004 EyeTrax MVP 선택`](adr/0004-eyetrax-mvp-selection.md) | Accepted (해커톤 MVP) | Eye 모델·보정·좌표 생산자와 재평가 Gate | dwell·revisit·최종 Top 1은 ADR-0006 경계 |
| [`ADR-0006 중앙 판단 추천 AI`](adr/0006-central-recommendation-ai.md) | Accepted (방향·경계) | evidence 결합·수명, 중앙 AI, 상품 10개, 결과·설명, Deferred feedback | 현재 추천 architecture의 권위 결정 |
| [`ADR-0007 중앙 추천 모델 선정`](adr/0007-central-recommendation-model-selection.md) | Proposed | 후보 revision·license·checksum, self-hosted runtime, 합성 benchmark·블라인드 검토와 최종 선택 | 실제 결과와 세 명의 리뷰 전에는 model 미선정 |
| [`ADR-0008 OpenAI Luna 중앙 추천 모델 선택`](adr/0008-openai-luna-central-recommendation.md) | Proposed — selected pending integration reviews | Luna Max·max·variant C·prompt v4, latency 기록 전용, hosted provider 경계 | Accepted 전에는 ADR-0006 self-hosted 원칙이 우선 |

## 4. 작업별 최소 읽기 묶음

### 중앙 판단 모델·프롬프트 — 양유상

1. [`ADR-0006`](adr/0006-central-recommendation-ai.md)
2. 모델·runtime을 평가하면 [`ADR-0007`](adr/0007-central-recommendation-model-selection.md), OpenAI 선택은 [`ADR-0008`](adr/0008-openai-luna-central-recommendation.md)과 [`benchmark README`](../experiments/recommendation/README.md)
3. [`IMPLEMENTATION_PLAN`](IMPLEMENTATION_PLAN.md)의 W0·W4
4. [`services/recommendation/README.md`](../services/recommendation/README.md)
5. [`contracts/README.md`](../contracts/README.md)
6. 후보를 실제 평가할 때만 관련 model card·license·runtime 문서

완료 기준은 정확한 model revision·license·checksum, self-hosted 재현, strict output·안전 eval과 versioned system prompt다. 모델 선택 자체는 이 문서 최신화 PR의 완료 조건이 아니다.

### Evidence Contract·Builder — 박형진·정은미, 양유상 리뷰

1. [`OVERALL_DESIGN`](OVERALL_DESIGN.md)의 RecommendationEvidence·수명
2. [`IMPLEMENTATION_PLAN`](IMPLEMENTATION_PLAN.md)의 W1·W2
3. [`contracts/README.md`](../contracts/README.md)와 관련 schema·example
4. [`services/recommendation/README.md`](../services/recommendation/README.md)
5. producer별로 [`Eye README`](../services/eye/README.md) 또는 [`Face README`](../services/face/README.md)

공유 JSON은 Contract PR에서 먼저 승인한다. 현재 v1의 결과 수와 새 Top 1 목표의 차이를 producer 코드에서 임의로 해소하지 않는다.

### Eye 생산자·보정 — 양유상

1. [`ADR-0004`](adr/0004-eyetrax-mvp-selection.md)
2. [`services/eye/README.md`](../services/eye/README.md)
3. [`experiments/eye/README.md`](../experiments/eye/README.md)
4. [`EyeTrax 실험 README`](../experiments/eye/eyetrax/README.md)
5. AOI 작업이면 [`lookbook example`](../data/lookbooks/example/README.md)

Eye는 좌표·유효성·capture context와 AOI 사실을 생산한다. 최종 순위·고객 유형 판단을 Adapter에 넣지 않는다.

### Face 생산자·taxonomy — 정은미

1. [`ADR-0003`](adr/0003-face-model-taxonomy-fallback.md)
2. [`services/face/README.md`](../services/face/README.md)
3. [`experiments/face/README.md`](../experiments/face/README.md)
4. [`Face benchmark README`](benchmarks/face/README.md)
5. [`observable taxonomy`](adr/face-observable-actions-v1.json)

Face는 관찰 가능한 신호·품질·invalid reason을 생산한다. 실제 감정·성격·구매 의도로 변환하지 않는다.

### 상품 Catalog·API — 박형진, 양유상 내용 리뷰

1. [`ADR-0006`](adr/0006-central-recommendation-ai.md)
2. [`IMPLEMENTATION_PLAN`](IMPLEMENTATION_PLAN.md)의 W3·W5
3. [`apps/api/README.md`](../apps/api/README.md)
4. [`data/products/README.md`](../data/products/README.md)
5. [`contracts/README.md`](../contracts/README.md)

이 작업 브랜치에는 10개 profile JSON과 PostgreSQL migration·기동 시 seed/readiness
adapter가 있다. live PostgreSQL에서 migration·정확히 10행·재시작을 검증하고 개별 URL,
이미지·QR과 tag를 승인하기 전에는 production readiness가 충족되지 않는다.

### Kiosk·Manager 통합 — 조윤혜

1. [`OVERALL_DESIGN`](OVERALL_DESIGN.md)의 사용자·Manager 흐름
2. [`IMPLEMENTATION_PLAN`](IMPLEMENTATION_PLAN.md)의 W5
3. [`apps/kiosk/README.md`](../apps/kiosk/README.md)
4. [`apps/manager/README.md`](../apps/manager/README.md)
5. [`apps/api/README.md`](../apps/api/README.md)와 [`contracts/README.md`](../contracts/README.md)

S04는 Top 1·관찰 근거·분석 불가 상태를 다루고, 매니저 요청은 고객 버튼으로만 만든다.

### Vision Gateway·원격 추론 — 박형진 관리

1. [`ADR-0001`](adr/0001-remote-vision-inference.md)
2. [`apps/vision_gateway/README.md`](../apps/vision_gateway/README.md)
3. [`Vision 서버 선정 계획`](benchmarks/VISION_SERVER_SELECTION_PLAN.md)
4. [`Vision Stream v1 계약`](../contracts/vision-stream-v1/README.md)과 Eye·Face producer README

ADR-0001이 Proposed인 동안 실제 고객 frame 원격 전송은 승인된 운영 구현이 아니다. synthetic·Fake·Replay로 transport를 검증한다.

### 테스트·검증

- 계약: [`tests/contract/README.md`](../tests/contract/README.md)
- replay: [`tests/replay/README.md`](../tests/replay/README.md)
- integration: [`tests/integration/README.md`](../tests/integration/README.md)
- E2E: [`tests/e2e/README.md`](../tests/e2e/README.md)
- 전체: [`tests/README.md`](../tests/README.md)

고객 원본 얼굴·영상을 Git fixture나 CI artifact로 사용하지 않는다.

## 5. 보존 자료와 비권위 문서

| 위치 | 분류 | 사용 원칙 |
| --- | --- | --- |
| [`archive/D1_TECHNICAL_DECISIONS.md`](archive/D1_TECHNICAL_DECISIONS.md) | Superseded 역사 스냅샷 | 당시 기본값·결정 경위를 추적할 때만 읽음 |
| [`archive/DETAILED_DESIGN_PLAN.md`](archive/DETAILED_DESIGN_PLAN.md) | Superseded 역사 스냅샷 | 당시 10일 계획·병렬 경계를 추적할 때만 읽음 |
| [`benchmarks/`](benchmarks/) | 모델·환경별 근거 | 측정 범위를 넘겨 production 요구사항으로 일반화하지 않음 |
| [`sjf/README.md`](sjf/README.md) | 외부 협업·평가 참고 | 외부 제출·branch 규칙을 저장소 현재 workflow와 혼동하지 않음 |

Eye·Face benchmark와 SJF 자료는 삭제하지 않는다. archive의 오래된 `main`, 복수 추천, fixed weight, 파생 저장과 conversion 문구는 역사적 내용이며 활성 기준이 아니다.

## 6. 문서 변경 규칙

- 공식 방향 변경은 관련 ADR, `OVERALL_DESIGN`, `IMPLEMENTATION_PLAN`, `DOCUMENT_MAP`과 root README를 같은 변경에서 정합화한다.
- 문서를 대체할 때는 삭제보다 Superseded 배너와 archive 이동을 우선해 결정 경위를 보존한다.
- 이동한 Markdown의 상대 링크를 수정하고 전체 상대 링크 검사를 통과시킨다.
- benchmark 결과에는 환경·명령·revision·license·checksum·수치와 한계를 남긴다.
- fixture·example은 요구사항을 새로 정의하지 않으며 schema 검증 근거로만 사용한다.

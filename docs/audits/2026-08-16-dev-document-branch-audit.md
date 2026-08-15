# 2026-08-16 dev 문서·브랜치 감사

- 상태: 문서 방향 전환 감사 기록
- 감사 기준일: 2026-08-16
- 저장소 기준: `dev` commit `9d5881bdafc0aecc8013c2cc5a4de6a72791dd96`
- 작업 branch: `docs/central-ai-direction-refresh`
- 범위: root 문서, `docs/`의 공식 설계·ADR·문서 지도와 GitHub PR 상태 읽기
- 제외: Contract, application/service code, DB migration, product data, PR·branch 상태 변경과 모델 선정

## 1. 감사 목적

기존 문서에는 gaze 중심 연구 추천, 복수 상품 결과, 파생 reaction의 저장, 구매 전환 MVP, 자동 Manager 알림과 서로 다른 branch 기준이 섞여 있었다. 승인된 새 방향을 하나의 canonical 흐름으로 만들고, 구현된 사실과 목표를 구분하며, 역사·benchmark 자료를 삭제하지 않고 권위를 재분류했다.

새 방향은 다음과 같다.

- 원본 frame이 아닌 정형화한 시선·표정 파생 JSON만 중앙 판단 AI에 전달
- self-hosted 중앙 AI를 룩북 종료 후 세션당 한 번 호출
- DB의 검수된 MCM 가방 정확히 10개 중 Top 1 추천
- frame 단위 파생 evidence는 session memory에서 사용 후 폐기
- 고객 설명은 이 세션의 관찰 사실만 말하고 감정·성격·구매 의도를 단정하지 않음
- 구매·호감 feedback과 재학습은 Deferred

## 2. 기준선과 PR 상태

로컬 HEAD와 `origin/dev`가 감사 시작 시 동일한 `9d5881b`임을 확인했다. GitHub connector로 다음 상태를 읽었으며 이 문서 작업은 PR 상태를 바꾸지 않았다.

| PR | 2026-08-16 상태 | base → head | 감사 처리 |
| --- | --- | --- | --- |
| [#25](https://github.com/likelion-MKK/mkk-hackathon-project/pull/25) | Open, Draft | `dev` ← `feat/eye/d02-candidate-evaluation` | 수정·rebase·close·merge하지 않음 |
| [#33](https://github.com/likelion-MKK/mkk-hackathon-project/pull/33) | Open, Ready | `dev` ← `codex/mvp-face-response-score` | 수정·rebase·close·merge하지 않음. fixed-weight 내용은 새 production 결정이 아니라 연구 baseline으로만 분류 |
| [#38](https://github.com/likelion-MKK/mkk-hackathon-project/pull/38) | **Merged** | `dev` ← `feat/face/d06-camera-worker-slice` | merge commit `9d5881b`; 현재 문서 기준선에 포함 |
| [#39](https://github.com/likelion-MKK/mkk-hackathon-project/pull/39) | Open, Ready | `dev` ← `style/kiosk/redesign` | 수정·rebase·close·merge하지 않음. 새 Top 1 UI 이행 여부는 소유자 별도 검토 |

Open PR의 새 방향 적합성과 통합 순서는 각 PR 소유자가 별도 판단한다. 이 감사는 기존 PR을 자동 승인·폐기하거나 새 base로 재작성하는 권한을 부여하지 않는다.

## 3. 문서별 판정과 조치

| 문서·영역 | 발견한 충돌·중복 | 판정·조치 |
| --- | --- | --- |
| [`README.md`](../../README.md) | Top 2, 추천 알고리즘 미정, 최종 전환 저장과 이전 역할표 | 새 사용자 흐름·AI 경계·수명·역할·구현 gap의 concise 진입점으로 개정 |
| [`AGENTS.md`](../../AGENTS.md) | D1·상세 계획 우선, 최신 `main`, 이전 추천 소유권·전환 저장 | ADR-0006/현재 Contract/active docs 우선, `dev` workflow, 새 owner·privacy invariant로 개정 |
| [`CONTRIBUTING.md`](../../CONTRIBUTING.md) | `main` 기반 branch·merge, 중앙 AI contract 순서 부재 | `dev` 기반 PR, central AI Contract-first 단계와 privacy·copy check 추가 |
| [`OVERALL_DESIGN.md`](../OVERALL_DESIGN.md) | gaze 중심 aggregate, 복수 결과, 파생 event 저장과 conversion MVP 혼재 | 중앙 Evidence Builder → self-hosted AI 1회 → Top 1 → evidence 폐기의 canonical 설계로 대체 |
| [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md) | 현재 이행 문서 부재 | owner, Contract gap, PR 순서, validation과 Deferred 진입 조건을 새로 작성 |
| [`ADR-0006`](../adr/0006-central-recommendation-ai.md) | 중앙 추천·retention 권위 결정 부재 | 방향·경계를 Accepted로 기록; 구체 모델·prompt revision은 benchmark 후속 결정으로 남김 |
| [`ADR-0001`](../adr/0001-remote-vision-inference.md) | PostgreSQL에 파생 반응·전환 저장으로 읽히는 문구 | Vision producer·transport 결정 보존, 추천 evidence 수명은 ADR-0006으로 위임 |
| [`ADR-0003`](../adr/0003-face-model-taxonomy-fallback.md) | Eye-primary·Face-low-weight production 방향처럼 읽힘 | Face taxonomy·invalid·lifecycle 보존, weight 문구는 historical research baseline으로 명시 |
| [`ADR-0004`](../adr/0004-eyetrax-mvp-selection.md) | Eye Adapter 경계에 이전 최종 결과 개수 표현 | Eye 모델·보정 결정 보존, feature·Top 1 판단은 ADR-0006으로 위임 |
| `D1_TECHNICAL_DECISIONS.md` | 이전 기본값과 active 문서가 충돌하며 긴 상세 계획과 중복 | 삭제하지 않고 [`archive`](../archive/D1_TECHNICAL_DECISIONS.md)로 이동, Superseded 배너 추가 |
| `DETAILED_DESIGN_PLAN.md` | 10일 계획, 이전 역할·완료 기준·저장 정책이 current로 보임 | 삭제하지 않고 [`archive`](../archive/DETAILED_DESIGN_PLAN.md)로 이동, Superseded 배너 추가 |
| Eye·Face benchmark | 모델·환경·실패 근거로 유효 | 유지. production 요구사항이 아닌 측정 근거로 분류 |
| [`docs/sjf`](../sjf/README.md) | 외부 평가·협업 branch 문맥이 저장소 workflow와 다름 | 유지. 외부 협업 참고자료로 분류 |

## 4. Canonical 문서 구조

```text
README.md                         서비스 목적·현재 방향
AGENTS.md                         작업 우선순위·소유·안전 규칙
CONTRIBUTING.md                   dev 기반 PR·Contract First
docs/
  DOCUMENT_MAP.md                공식 지도와 최소 읽기 묶음
  OVERALL_DESIGN.md              현재 canonical architecture
  IMPLEMENTATION_PLAN.md         현재→목표 이행·owner·Gate
  adr/
    0001                         Vision transport (Proposed)
    0003                         Face producer (Proposed)
    0004                         Eye producer (Accepted for hackathon MVP)
    0006                         Central recommendation (Accepted direction)
  audits/                        기준선·충돌·정리 근거
  archive/                       Superseded 역사 스냅샷
  benchmarks/                    재현 가능한 모델·환경 근거
  sjf/                           외부 협업 참고
```

현재 제품 질문은 `README → AGENTS → OVERALL_DESIGN → IMPLEMENTATION_PLAN → 관련 ADR·Contract` 순서로 판단한다. archive·benchmark·SJF 문구가 active 결정과 다르면 active 결정이 우선한다.

## 5. 삭제하지 않고 Superseded로 보존한 이유

기존 D1과 상세 설계에는 실행 환경, 당시 owner, Vision 이동 검토, benchmark Gate와 초기 계약 분리 근거가 남아 있다. 이 정보는 왜 현재 구조가 생겼는지 추적하는 데 유용하지만, 새 방향과 섞으면 구현자가 이전 완료 기준을 따를 위험이 있다. 따라서:

1. 원문을 archive로 이동한다.
2. 맨 위에 날짜·대체 문서·비권위 상태를 표시한다.
3. 이동으로 깨지는 상대 링크를 고친다.
4. 공식 지도에서는 역사 자료로만 연결한다.

## 6. 구현으로 남은 차이

이 문서 변경은 다음을 구현하지 않는다.

- 새 `RecommendationEvidence` schema·example·producer/consumer
- 현재 두-item result Contract에서 Top 1 목표로의 호환 또는 major migration
- MCM 가방 10개 catalog·seed·DB migration
- self-hosted 모델 선정, weight, runtime과 versioned system prompt
- central output validator, API orchestration과 Kiosk 화면 연결
- evidence session-memory 폐기 E2E와 최종 결과 보유·삭제 정책

따라서 active 문서의 “MCM 가방 10개·Top 1·central AI”는 승인된 목표이고 현재 코드 완료 사실이 아니다. 구현 순서는 [`IMPLEMENTATION_PLAN`](../IMPLEMENTATION_PLAN.md)을 따른다.

## 7. 최종 검증 기록

- Markdown 상대 링크: **통과** — tracked Markdown과 이번 새 문서·archive를 합친 67개 파일에서 깨진 상대 링크 0개
- 활성 문서 stale positive assertion 감사: **통과** — 이전 기준 branch, 운영 복수 추천, 표정의 감정 단정, reaction의 DB 영속 저장, 자동 Manager 호출과 MVP feedback 수집을 의미하는 표적 패턴 0개
- 넓은 stale term 수동 검토: 금지 상태를 부정하는 문장, Deferred 표시, Contract 호환성·감사 역사와 ADR-0001의 Vision WebSocket 문맥만 남음을 확인
- trailing whitespace: **통과** — 활성 문서와 archive에서 0건
- `git diff --check`: **통과** — 이번 tracked 문서 변경에 whitespace error 없음. 출력의 LF→CRLF 안내는 기존 Windows checkout line-ending 경고임
- Contract·code test: 문서 전용 변경이고 Contract·code를 건드리지 않아 이번 감사 범위 밖

archive, benchmark와 SJF는 역사·근거·외부 문맥 때문에 이전 표현이 남을 수 있다. stale phrase 검사는 활성 canonical 문서와 수정한 ADR을 대상으로 하고, 호환성 차이를 명시한 문장은 예외 근거와 함께 검토한다.

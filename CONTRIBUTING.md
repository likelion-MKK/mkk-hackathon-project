# 개발 및 PR 운영 규칙

이 저장소는 `dev` 기반의 짧은 branch, 작은 PR과 Contract First를 기본으로 한다.

## 문서와 Agent 시작점

- 작업 전 [`AGENTS.md`](AGENTS.md)와 [`문서 지도`](docs/DOCUMENT_MAP.md)의 최소 읽기 묶음을 확인한다.
- 중앙 판단 AI 관련 작업은 [`ADR-0006`](docs/adr/0006-central-recommendation-ai.md)과 [`구현 계획`](docs/IMPLEMENTATION_PLAN.md)을 함께 읽는다.
- 새 공식 문서를 추가·이동·대체하면 같은 PR에서 문서 지도와 관련 README 링크를 갱신한다.
- [`docs/archive/`](docs/archive/)의 Superseded 문서와 지도에 연결되지 않은 개인 초안은 현재 구현의 공식 근거로 사용하지 않는다.

## 작업 시작

1. 원격 `dev`와 현재 checkout의 branch·HEAD·작업 트리를 확인한다.
2. 최신 `dev`에서 하루 안에 끝낼 수 있는 한 책임의 branch를 만든다.
3. 생산자·소비자가 공유하는 형식을 바꾸면 구현보다 Contract PR을 먼저 만든다.

Branch 이름 예시:

```text
feat/recommendation/evidence-contract
feat/recommendation/central-ai-runtime
feat/api/product-catalog
feat/kiosk/top1-result
docs/central-ai-direction
fix/contracts/recommendation-example
```

PR은 기본적으로 `dev`를 base로 한다. `main`은 검증된 `dev`를 release로 승격할 때만 사용하며 일반 기능 branch의 출발점이나 일상 병합 대상이 아니다.

## 소유 경계

| 영역 | 주 담당 |
| --- | --- |
| 공식 문서, 중앙 모델·시스템 프롬프트 | 양유상 |
| `apps/kiosk/`, `apps/manager/` | 조윤혜, Backend 접점은 박형진 리뷰 |
| `apps/api/`, DB·migration | 박형진 |
| `services/recommendation/` | 박형진 구현, 양유상 모델·프롬프트 리뷰 |
| 시선 evidence 의미·정형화 | 박형진·양유상 |
| 표정 evidence 의미·정형화 | 정은미·박형진 |
| `services/eye/` | 양유상 |
| `services/face/` | 정은미 |
| `contracts/`, 공통 CI | 박형진 관리, 생산자·소비자 공동 리뷰 |
| `data/lookbooks/` | 양유상 작성, 박형진·조윤혜 리뷰 |

공용 lock file, CI, Contract와 migration은 기능 PR에 섞지 않는다.

## 중앙 AI 변경 순서

```text
Decision·Contract·example PR
  → Eye·Face Producer PR
  → Evidence Builder PR
  → 상품 10개 Catalog·DB PR
  → Central AI Runtime PR
  → Kiosk·API Consumer PR
  → Wiring·E2E PR
```

- 후보 상품은 검수된 MCM 가방 정확히 10개, 고객 결과는 Top 1이라는 목표를 유지한다.
- 현재 Contract와 목표가 다르면 기존 필드 의미를 조용히 바꾸지 않는다. 호환 계층이나 새 major version을 먼저 승인한다.
- schema가 바뀌면 정상·경계·invalid example과 contract test를 함께 갱신한다.
- generated type은 직접 고치지 않고 schema에서 다시 생성한다.
- frame 단위 파생값을 DB에 저장하는 방식으로 임시 통합하지 않는다. bounded session memory와 종료 시 폐기를 검증한다.

## PR 크기와 병합

- 한 PR은 한 책임만 다룬다.
- 목표 크기는 non-generated 변경 약 100–300줄이다. 큰 계약 이행은 위 단계로 나눈다.
- Draft PR을 일찍 열어 계약과 통합 방향을 먼저 확인한다.
- CI 성공, unresolved review 0건, 최신 `dev` 반영 후 squash merge한다.
- 이미 병합된 PostgreSQL migration은 수정하지 않고 새 migration을 추가한다.
- 기존 open PR을 새 방향에 맞춰 rebase·close·merge할지는 각 PR 소유자가 별도로 결정한다. 문서 PR이 자동으로 상태를 바꾸지 않는다.

## 외부 AI 모델

- 모델 탐색·benchmark와 production Adapter/runtime를 같은 PR에 섞지 않는다.
- 모델 URL, exact commit 또는 revision, code·weight license, SHA256과 재현 명령을 기록한다.
- 중앙 판단 모델은 self-hosted 후보만 production Gate에 올린다. 원본 frame을 모델 또는 외부 API로 보내지 않는다.
- 시스템 프롬프트에는 허용 입력, 금지 추론, 10개 후보 제한, strict JSON 출력과 근거 문구 규칙을 version으로 고정한다.
- 모델 출력은 schema와 후보 ID allowlist를 통과해야 하며 제품 사실은 DB 카탈로그로 grounding한다.
- 최종 선택은 benchmark·안전 평가와 ADR 근거를 검토한 뒤 runtime에 반영한다.
- 모델 weight와 고객 원본 영상은 Git에 올리지 않는다.

## 개인정보·설명 확인

PR 작성자는 다음을 확인한다.

- 원본 frame·영상·base64·얼굴 embedding이 일반 API, 추천 입력, 파일, DB, 로그, cache, queue와 APM에 없음
- 파생 evidence가 세션 범위를 벗어나 영속화되지 않고 성공·실패·취소·timeout 때 폐기됨
- 무효 신호를 `(0, 0)`, 중립 표정이나 무관심으로 바꾸지 않음
- 고객 문구가 실제 감정·성격·심리 유형·구매 의도를 단정하지 않고 세션 관찰 사실만 설명함
- 중앙 AI가 후보 밖 ID, 복수 상품, 자유형 제품 사실을 반환하면 fail-closed 처리함
- 구매·호감 피드백 수집이나 재학습이 MVP 경로에 포함되지 않음
- 세션 종료와 오류 경로에서 camera·frame buffer·derived evidence가 해제됨

## 검증

Contract 변경 시:

```powershell
python -m pip install -r requirements-contracts.txt
python scripts/validate_contracts.py
```

문서 변경 시 Markdown 상대 링크와 Superseded 문서의 공식 지도 분리를 검사하고, 이전 기준 branch, 복수 추천, 감정·성격 단정, 파생 timeline 영속 저장, 자동 Manager 알림과 MVP feedback 수집 표현이 활성 문서에 남지 않았는지 검색한다.

실제 AI 모델 전체 benchmark는 일반 PR CI에서 실행하지 않고 수동 또는 scheduled lane에서 수행한다.

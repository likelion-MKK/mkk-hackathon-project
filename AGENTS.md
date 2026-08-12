# MCM AI Lookbook Kiosk 에이전트 작업 규칙

이 파일은 저장소 전체에 적용되는 공통 작업 규칙이다. 프로젝트 설명을 이 파일에 반복해서 복사하지 말고, 작업에 필요한 문서만 [문서 지도](docs/DOCUMENT_MAP.md)에서 골라 읽는다.

## 1. 작업 시작 순서

1. 사용자의 현재 요청과 작업 범위를 확인한다.
2. `README.md`로 서비스 목적과 현재 단계를 확인한다.
3. `docs/DOCUMENT_MAP.md`에서 작업 종류에 맞는 최소 읽기 묶음을 선택한다.
4. 해당 디렉터리의 `README.md`, 계약과 fixture만 추가로 읽는다.
5. 코드를 바꾸기 전에 `git status`로 사용자 변경사항을 확인한다.

전체 `docs/`, `contracts/` 또는 저장소를 습관적으로 모두 읽지 않는다. 먼저 `rg`로 관련 제목·필드·파일을 찾고 필요한 범위만 연다.

## 2. 문서와 계약의 우선순위

충돌이 있을 때는 다음 순서로 판단한다.

1. 사용자의 현재 요청과 명시적으로 승인된 결정
2. 승인된 ADR과 `docs/D1_TECHNICAL_DECISIONS.md`
3. `contracts/openapi.yaml`과 `contracts/**/*.schema.json`
4. `docs/DETAILED_DESIGN_PLAN.md`
5. `docs/OVERALL_DESIGN.md`
6. `README.md`

`contracts/examples/`와 `data/`의 예제는 계약을 검증하는 fixture이며 독립적인 요구사항 문서가 아니다. [문서 지도](docs/DOCUMENT_MAP.md)에 연결되지 않은 초안은 공식 기준으로 간주하지 않는다. 문서가 서로 충돌하면 임의로 섞지 말고 충돌 위치와 영향 범위를 먼저 보고한다.

## 3. 팀 소유 경계

| 영역 | 주 담당 | 주요 책임 |
| --- | --- | --- |
| `apps/kiosk/` | 조윤혜 | S01-S04, 영상·웹캠 orchestration, 터치 UI |
| `apps/manager/` | 조윤혜, 박형진 | 매니저 UI와 Backend 이벤트 연결 |
| `apps/api/` | 박형진 | FastAPI, 세션, PostgreSQL, QR, Manager polling |
| `services/recommendation/` | 박형진 | feature 집계와 추천 엔진 경계 |
| `services/eye/`, `experiments/eye/` | 양유상 | Eye Adapter, 보정, 시선 좌표, AOI 매핑·평가 |
| `services/face/`, `experiments/face/` | 정은미 | Face Adapter, 출력 정규화·평가 |
| `contracts/`, migration, 공통 CI | 박형진 관리 | 생산자와 소비자 공동 리뷰가 필요한 공유 경계 |
| `data/lookbooks/` | 양유상 작성 | 박형진이 상품 ID, 조윤혜가 영상 시간·좌표 검토 |

다른 담당자의 영역을 수정해야 하면 PR 설명에 이유와 영향을 적고 해당 담당자의 리뷰를 받는다.

## 4. 에이전트와 토큰 관리

- 한 작업은 한 가지 결과와 한 명의 주 소유자를 가진다.
- 에이전트에게는 전체 대화 대신 `목표`, `허용 경로`, `입력 계약`, `완료 조건`, `범위 밖`만 전달한다.
- 최초 읽기 묶음은 이 파일, 문서 지도와 작업별 핵심 문서 2~4개로 제한한다. 추가 문서는 막힌 근거가 있을 때만 연다.
- 긴 문서를 다시 전달하지 말고 파일 경로와 필요한 제목을 지정한다.
- 여러 에이전트가 같은 파일을 동시에 수정하지 않는다. `contracts/`, lock file, migration, CI와 루트 문서는 한 명이 직렬로 관리한다.
- 병렬 작업은 Adapter, Producer, Consumer처럼 독립 계약 경계로 나눈다. 공유 계약 변경은 먼저 별도 PR로 병합한다.
- 진행 보고는 새 사실, 결정, 위험 또는 검증 결과가 있을 때만 간결하게 남긴다.
- 하위 `AGENTS.md`는 해당 영역의 규칙이 실제로 달라질 때만 추가한다. 기존 내용을 복제하는 하위 파일은 만들지 않는다.

에이전트 작업 요청에는 다음 형식을 권장한다.

```text
목표:
허용 경로:
읽을 문서/계약:
완료 조건:
범위 밖:
검증 명령:
```

## 5. 구현과 PR 규칙

- 최신 `main`에서 하루 안에 리뷰 가능한 작은 branch를 만든다.
- 한 PR에는 한 책임만 넣고 계약 변경, 구현 변경과 대규모 정리를 섞지 않는다.
- Contract 변경 순서는 `Contract·example → Producer → Consumer → Wiring`이다.
- v1 계약의 필드 삭제·이름 변경·의미 변경은 금지하며 새 major version으로 다룬다.
- 병합된 PostgreSQL migration은 수정하지 않고 새 migration을 추가한다.
- 모델 weight, 대형 binary와 고객 원본 입력은 Git에 넣지 않는다.
- 사용자가 요청하지 않은 commit, push, PR 생성 또는 merge는 수행하지 않는다.
- 기존 사용자 변경과 관련 없는 파일은 수정·삭제하지 않는다.

Contract 변경 또는 통합 작업 후 저장소 루트에서 다음 검증을 실행한다.

```powershell
python scripts/validate_contracts.py
```

영역별 실행 명령이 생기면 해당 디렉터리 `README.md`를 기준으로 한다.

## 6. 개인정보와 AI 출력 원칙

- 웹캠 원본 프레임·영상, image bytes, base64, 얼굴 embedding과 원본 파일 경로를 파일·DB·API·로그에 저장하지 않는다.
- 고객 동의를 받은 파생 신호, 추천 결과와 구매 전환 결과만 정해진 계약으로 처리한다.
- 무효 신호를 `(0, 0)`, 중립 표정 또는 무관심으로 바꾸지 않고 `valid=false`와 사유를 유지한다.
- 표정·시선 신호를 실제 감정, 성격 또는 구매 의도의 확정값으로 표현하지 않는다.
- 외부 Eye·Face 모델은 URL, 정확한 commit/revision, code·weight license와 checksum을 기록한 뒤 선택한다.
- 원본 프레임을 외부 서비스로 전송하는 모델은 별도 개인정보·네트워크 승인 전 사용하지 않는다.

## 7. 작업 종료와 인계

최종 보고에는 다음만 남긴다.

```text
완료한 결과:
변경 파일:
Contract/DB 영향:
실행한 검증과 결과:
남은 결정 또는 위험:
다음 담당자:
```

새 공식 문서를 추가·이동·폐기했다면 같은 변경에서 `docs/DOCUMENT_MAP.md`와 필요한 README 링크를 갱신한다.

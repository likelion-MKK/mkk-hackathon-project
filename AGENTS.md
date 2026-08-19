# MCM AI Lookbook Kiosk 에이전트 작업 규칙

이 파일은 저장소 전체에 적용되는 공통 규칙이다. 프로젝트 설명은 반복하지 않고 [문서 지도](docs/DOCUMENT_MAP.md)에서 작업에 필요한 최소 문서만 고른다.

## 1. 작업 시작 순서

1. 사용자의 현재 요청, 허용 경로와 범위 밖 항목을 확인한다.
2. `git status --short --branch`와 `git rev-parse HEAD`로 checkout·사용자 변경을 확인한다.
3. `README.md`와 `docs/DOCUMENT_MAP.md`에서 서비스 방향과 최소 읽기 묶음을 확인한다.
4. 해당 영역의 README, 계약과 fixture만 추가로 읽는다.
5. 코드나 계약을 바꾸기 전에 소유자·완료 조건·검증 명령을 적는다.

전체 저장소를 습관적으로 읽지 않는다. 먼저 `rg`로 관련 제목·필드·파일을 찾고, 사용할 수 없으면 PowerShell `Get-ChildItem`과 `Select-String`으로 같은 범위를 좁힌다.

## 2. 문서와 계약의 우선순위

충돌이 있을 때는 다음 순서로 판단한다.

1. 사용자의 현재 요청과 명시적으로 승인된 결정
2. Accepted ADR. 중앙 추천 방향은 [`ADR-0006`](docs/adr/0006-central-recommendation-ai.md)을 따른다.
3. 현재 구현 인터페이스인 `contracts/openapi.yaml`과 `contracts/**/*.schema.json`
4. 현재 구조인 `docs/OVERALL_DESIGN.md`
5. 이행 순서인 `docs/IMPLEMENTATION_PLAN.md`
6. `README.md`

목표 문서와 기존 Contract가 다르면 문서만 보고 구현된 것으로 간주하지 않는다. [`IMPLEMENTATION_PLAN`](docs/IMPLEMENTATION_PLAN.md)의 호환성 차이로 기록하고 `Contract·example → Producer → Consumer → Wiring` 순서로 해소한다.

`contracts/examples/`와 `data/`의 예제는 계약 검증 fixture이지 독립 요구사항이 아니다. [`docs/archive/`](docs/archive/)의 Superseded 문서, benchmark 결과와 [`docs/sjf/`](docs/sjf/) 자료는 역사·근거·협업 참고자료이며 현재 제품 요구사항을 덮어쓰지 않는다. 문서 충돌을 임의로 섞지 말고 위치와 영향부터 보고한다.

## 3. 현재 제품 불변조건

- 중앙 판단 AI에는 원본 frame·영상·image bytes·base64·embedding·원본 경로를 보내지 않고 정형화한 시선·표정 파생 JSON만 보낸다.
- 중앙 판단 AI는 팀이 통제하는 self-hosted runtime에서 실행한다.
- 룩북이 끝난 뒤 세션당 한 번만 호출한다.
- 후보군은 DB의 검수된 MCM 가방 정확히 10개이며 결과는 Top 1이다.
- frame 단위 파생값과 결합 evidence는 세션 메모리에만 두고 추천 성공·실패·취소 뒤 폐기한다. DB에는 상품 카탈로그와 필요한 최소 최종 추천만 저장한다.
- 구매·호감 피드백 수집, 재학습과 개인화 가중치 갱신은 MVP 범위가 아니라 Deferred다.
- 고객 설명은 이번 세션에서 관찰된 행동과 상품 장면만 말한다. 표정·시선을 실제 감정, 성격, 심리 유형이나 구매 의도의 확정값으로 표현하지 않는다.
- 유효 신호가 부족하면 중립·무관심 또는 임의 추천으로 바꾸지 않고 `valid=false`의 사유와 분석 불가 상태를 보존한다.

## 4. 팀 소유 경계

| 영역 | 주 담당 | 주요 책임 |
| --- | --- | --- |
| 공식 설계 문서, 중앙 모델·프롬프트 결정 | 양유상 | 문서 정합성, 후보 revision·license·benchmark, 시스템 프롬프트, 출력·설명 기준 |
| `apps/kiosk/`, `apps/manager/` | 조윤혜 | S01–S04, 영상·웹캠 orchestration, Backend 연결, 명시적 매니저 요청 UI |
| `apps/api/`, DB·migration | 박형진 | 세션, evidence ingest, 상품 10개 카탈로그, 최종 추천, QR, REST polling |
| `services/recommendation/` | 박형진 구현, 양유상 모델·프롬프트 | Evidence Builder, self-hosted 중앙 AI 경계, strict 출력 검증 |
| 시선 파생 evidence | 박형진·양유상 | frame·capture time·video time·좌표·이동·AOI·체류·재방문 의미와 정형화 |
| 표정 파생 evidence | 정은미·박형진 | 관찰 신호·변화율·지속성·품질·무효 사유 정형화와 시간 결합 |
| `services/eye/`, `experiments/eye/` | 양유상 | Eye Adapter, 보정, 좌표와 AOI 생산자 검증 |
| `services/face/`, `experiments/face/` | 정은미 | Face Adapter, 관찰 신호 taxonomy·정규화·생산자 검증 |
| `apps/vision_gateway/` | 박형진 관리, 생산자·Kiosk 공동 리뷰 | ADR-0001 승인 이후 WSS ingress·flow control·fan-out·원본 비저장 경계 |
| `contracts/`, 공통 CI | 박형진 관리 | 생산자·소비자 공동 리뷰가 필요한 공유 경계 |
| `data/lookbooks/` | 양유상 작성 | 박형진이 상품 ID, 조윤혜가 영상 시간·좌표를 검토 |

다른 담당자의 영역을 바꾸면 PR 설명에 이유·영향을 적고 그 담당자의 리뷰를 받는다. 계약, migration, lock file, CI와 루트 문서는 한 명이 직렬로 관리한다.

## 5. 병렬 작업 규칙

- 한 작업은 한 결과와 한 주 소유자를 가진다.
- 에이전트 요청에는 `목표`, `허용 경로`, `입력 계약`, `완료 조건`, `범위 밖`, `검증 명령`을 전달한다.
- Adapter·Producer·Consumer처럼 독립 계약 경계만 병렬화한다. 공유 계약 변경은 먼저 별도 PR로 합의한다.
- 여러 작업자가 같은 파일을 동시에 수정하지 않는다.
- 새 사실, 결정, 위험 또는 검증 결과가 있을 때만 진행 보고를 남긴다.
- 하위 `AGENTS.md`는 실제로 다른 규칙이 있을 때만 추가한다.

## 6. 구현과 PR 규칙

- 최신 `dev`에서 하루 안에 리뷰 가능한 `feat/`, `fix/`, `docs/` branch를 만든다. `main`은 release 승격 대상이며 일상 feature 기준 branch가 아니다.
- PR base는 기본적으로 `dev`다. 한 PR에는 한 책임만 넣고 계약, 구현과 대규모 문서 정리를 섞지 않는다.
- Contract v1 필드 삭제·이름·의미 변경은 호환 변경으로 가장하지 않고 새 major version 또는 명시된 migration으로 다룬다.
- 병합된 PostgreSQL migration은 수정하지 않고 새 migration을 추가한다.
- 모델 weight, 대형 binary와 고객 원본 입력은 Git에 넣지 않는다.
- 외부 모델은 URL, exact commit/revision, code·weight license, checksum과 benchmark 근거를 기록한 뒤 선택한다.
- 사용자가 요청하지 않은 commit, push, PR 생성·수정 또는 merge를 수행하지 않는다.
- 기존 사용자 변경과 관련 없는 파일은 수정·삭제하지 않는다.

Contract 변경 또는 통합 작업 후 저장소 루트에서 실행한다.

```powershell
python scripts/validate_contracts.py
```

영역별 검증은 해당 디렉터리 README를 따른다.

## 7. 개인정보와 AI 출력

- 웹캠 원본 frame은 [`ADR-0001`](docs/adr/0001-remote-vision-inference.md)의 승인 조건을 지킨 Vision 추론 경계에서만 일시 처리한다. Proposed인 동안 실제 고객 frame 원격 전송은 운영하지 않는다.
- 원본 frame을 팀 관리 Vision 서버 밖 제3자 API나 중앙 추천 모델로 전송하지 않는다.
- 중앙 추천 입력에는 allowlist된 파생 필드, 익명 세션 상관값, 상품 프로필만 포함한다. 직접 식별자와 자유형 원본 payload를 넣지 않는다.
- 파생 evidence를 로그·APM·DB·브라우저 저장소·queue에 복제하지 않으며 오류 경로에서도 세션 메모리를 정리한다.
- 모델 출력의 상품 ID가 10개 후보에 없거나 schema가 맞지 않으면 실패 처리한다. 모델이 만든 제품 사실을 그대로 표시하지 않고 DB의 검수된 설명으로 grounding한다.

## 8. 작업 종료와 인계

최종 보고에는 다음을 남긴다.

```text
완료한 결과:
변경 파일:
Contract/DB 영향:
실행한 검증과 결과:
남은 결정 또는 위험:
다음 담당자:
```

새 공식 문서를 추가·이동·폐기했다면 같은 변경에서 `docs/DOCUMENT_MAP.md`와 관련 README 링크를 갱신한다.

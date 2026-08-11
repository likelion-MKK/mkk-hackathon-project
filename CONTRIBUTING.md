# 개발 및 PR 운영 규칙

이 저장소는 Contract First, 짧은 feature branch와 작은 PR을 기본으로 사용합니다.

## 문서와 Agent 시작점

- 사람과 AI Agent 모두 작업 전에 [`AGENTS.md`](AGENTS.md)의 공통 규칙을 확인합니다.
- 작업에 필요한 문서만 [`docs/DOCUMENT_MAP.md`](docs/DOCUMENT_MAP.md)의 최소 읽기 묶음에서 선택합니다.
- 새 공식 문서를 추가·이동·대체하면 같은 PR에서 문서 지도와 관련 README 링크를 갱신합니다.
- 문서 지도에 연결되지 않은 개인 초안은 구현·리뷰의 공식 근거로 사용하지 않습니다.

## 작업 시작

1. 최신 `main`을 반영합니다.
2. 하루 안에 끝낼 수 있는 한 가지 책임으로 branch를 만듭니다.
3. 생산자·소비자가 공유하는 형식을 바꿔야 한다면 구현보다 Contract PR을 먼저 만듭니다.

Branch 이름 예시:

```text
feat/eye/d03-gaze-adapter
feat/face/d03-expression-adapter
feat/kiosk/d03-video-context
feat/api/d03-reaction-ingest
docs/adr-eye-model-selection
fix/contracts-reaction-example
```

## 소유 경계

| 영역 | 주 담당 |
| --- | --- |
| `apps/kiosk/`, `apps/manager/` | 조윤혜, UI 접점은 박형진 리뷰 |
| `apps/api/`, `services/recommendation/` | 박형진 |
| `services/eye/` | 양유상 |
| `services/face/` | 정은미 |
| `contracts/`, migration, CI | 박형진 관리, 생산자·소비자 공동 리뷰 |
| `data/lookbooks/` | 양유상 작성, 박형진·조윤혜 리뷰 |

공용 lock 파일, CI, Contract와 migration은 기능 PR에 섞지 않습니다.

## Contract 변경 순서

```text
Contract·example PR
  → Producer PR
  → Consumer PR
  → Wiring PR
```

- Contract v1은 optional field 추가처럼 호환 가능한 변경만 허용합니다.
- 필드 삭제·이름 변경·의미 변경은 새 major version으로 처리합니다.
- schema가 바뀌면 정상·경계 example과 contract test를 함께 갱신합니다.
- generated type이 생기면 직접 고치지 않고 schema에서 다시 생성합니다.

## PR 크기와 병합

- 한 PR은 한 책임만 다룹니다.
- 목표 크기는 non-generated 변경 약 100~300줄입니다.
- Draft PR을 일찍 열어 계약과 통합 방향을 먼저 확인합니다.
- CI 성공, unresolved review 0건, 최신 `main` 반영 후 squash merge합니다.
- 이미 병합된 PostgreSQL migration은 수정하지 않고 새 migration을 추가합니다.

## 외부 AI 모델

- 후보 실험과 production Adapter를 같은 PR에 섞지 않습니다.
- 모델 URL, 정확한 commit 또는 revision, code·weight license와 SHA256을 기록합니다.
- 모델 weight와 고객 원본 영상은 Git에 올리지 않습니다.
- 원본 프레임을 외부 서비스로 보내야 하는 후보는 별도 승인 전 사용하지 않습니다.
- 최종 선택은 benchmark와 ADR이 병합된 뒤 production Adapter에 반영합니다.

## 개인정보 확인

PR 작성자는 다음을 확인합니다.

- 원본 프레임·영상·base64·얼굴 embedding이 파일, DB, API와 로그에 없음
- 무효 신호를 `(0, 0)`, 중립 표정이나 무관심으로 바꾸지 않음
- 파생 데이터 example에 이름·전화번호 등 직접 식별자가 없음
- 세션 종료와 오류 경로에서 카메라·frame buffer가 해제됨

## Contract 검증

```powershell
python -m pip install -r requirements-contracts.txt
python scripts/validate_contracts.py
```

실제 AI 모델 전체 benchmark는 일반 PR CI에서 실행하지 않고 수동 또는 scheduled lane에서 수행합니다.

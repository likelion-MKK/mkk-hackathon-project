# API App

## 소유자

박형진(PM·BE). REST·polling·DB migration과 공용 계약 변경을 직렬로 관리한다.

## 입력

- 세션 생성·완료 요청, 동의 version
- `event_id`와 `sequence`를 포함한 파생 신호 `ReactionBatch`
- 추천 후 매니저가 기록한 `ConversionOutcome`

## 출력

- 세션·상품·룩북 manifest·추천 상태 API 응답
- 추천 인터페이스가 만든 `RecommendationResult`
- 고객의 S04 제품 요청 `ManagerEvent`와 polling 이벤트 조회

## 금지사항

- 원본 이미지·영상·base64·얼굴 embedding 또는 그 파일 경로를 받거나 저장하지 않는다.
- 원격 Eye·Face frame ingress는 별도 Vision Gateway 책임이다. 일반 REST middleware·DB·request log로 우회 수신하지 않는다.
- 매 프레임마다 HTTP 요청을 요구하지 않는다. 소량 batch와 종료·장면 전환 flush를 지원한다.
- 특정 Eye/Face 모델의 입력 형식이나 라이브러리를 API 계약에 노출하지 않는다.
- 재전송된 `event_id`를 중복 저장하지 않는다.

## 현재 vertical slice

현재 구현은 Contract v1을 기준으로 세션 생성, 예제 manifest·상품 조회,
파생 `ReactionBatch` 수신과 멱등 처리, 결정적인 Mock 추천, Manager 이벤트를
연결하는 개발용 FastAPI scaffold다. 저장소는 PostgreSQL/Alembic으로 교체할 수
있도록 API 경계 뒤에 있으며, 이 단계에서는 원본 미디어를 받지 않는 메모리
store를 사용한다. Mock 결과는 실제 추천 품질을 의미하지 않는다.

## 실행

```powershell
Set-Location apps/api
uv sync --locked
uv run uvicorn app.main:app --reload
```

테스트는 저장소 루트에서 다음처럼 실행한다.

```powershell
Set-Location apps/api
uv run --locked pytest
```

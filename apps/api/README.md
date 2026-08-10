# API App

## 소유자

박형진(PM·BE). REST·WebSocket·DB migration과 공용 계약 변경을 직렬로 관리한다.

## 입력

- 세션 생성·완료 요청, 동의 version
- `event_id`와 `sequence`를 포함한 파생 신호 `ReactionBatch`
- 추천 후 매니저가 기록한 `ConversionOutcome`

## 출력

- 세션·상품·룩북 manifest·추천 상태 API 응답
- 추천 인터페이스가 만든 `RecommendationResult`
- 사용 시작·추천 완료 `ManagerEvent`와 연결 복구용 이벤트 조회

## 금지사항

- 원본 이미지·영상·base64·얼굴 embedding 또는 그 파일 경로를 받거나 저장하지 않는다.
- 매 프레임마다 HTTP 요청을 요구하지 않는다. 소량 batch와 종료·장면 전환 flush를 지원한다.
- 특정 Eye/Face 모델의 입력 형식이나 라이브러리를 API 계약에 노출하지 않는다.
- 재전송된 `event_id`를 중복 저장하지 않는다.

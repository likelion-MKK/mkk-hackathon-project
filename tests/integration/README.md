# Integration Tests

## 소유와 입력

연결되는 양쪽 영역의 소유자가 공동 리뷰한다. Fake/Replay 파생 fixture, manifest, 상품 catalog와 테스트 DB를 입력으로 사용한다.

## 검증 결과

FrameContext→Eye/Face 파생 신호, gaze→AOI, batch ingest→추천 경계, RecommendationResult→Kiosk/Manager 연결과 중복 제거·재연결 동작을 검증한다.

## 금지사항

실제 고객 원본 프레임이나 외부 네트워크에 의존하지 않으며, Backend 지연이 영상 재생을 멈추게 하는 구성을 정상으로 간주하지 않는다.

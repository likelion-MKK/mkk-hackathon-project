# Kiosk App

## 소유자

조윤혜(FE). Eye·Face 실행 경계나 API 계약을 바꿀 때는 해당 소유자와 함께 리뷰한다. 프런트엔드 기술 스택과 모델 실행 위치는 D1 확인 전까지 고정하지 않는다.

## 책임

- S01 대기 화면부터 S04 분석 결과 화면까지의 상태 전이를 관리한다.
- 웹캠은 한 번만 열고 캡처 순간의 `FrameContext`와 메모리 프레임 참조를 Eye·Face 경계에 fan-out한다.
- 룩북 재생 시각, `playback_epoch`, viewport와 실제 영상 표시 영역을 캡처 시점에 고정한다.
- 개발 모드에서만 시선·AOI·품질 overlay를 표시하고, 세션 종료 시 카메라와 버퍼를 해제한다.

## 입력

- `LookbookManifest`, 상품 정보, 세션·동의 API 응답
- Eye/Face Adapter가 만든 파생 신호와 추천 상태·`RecommendationResult`
- Fake/Replay Adapter 선택과 debug 표시를 위한 실행 설정

## 출력

- `FrameContext`, `VideoLayout`, 화면 상태와 사용자 이벤트
- 파생 이벤트를 담은 `ReactionBatch`, 세션 완료 요청
- S04의 Top 2 상품 카드와 사전 생성된 상품별 QR 표시

## 금지사항

- 원본 프레임을 직렬화하거나 네트워크·파일·로그·브라우저 저장소에 보관하지 않는다.
- 추론 완료 시점의 영상 시간을 캡처 시각 대신 사용하지 않는다.
- Eye/Face 신호가 없을 때 `(0, 0)` 또는 중립 표정으로 대체하지 않는다.
- Kiosk가 추천 가중치나 최종 Top 2를 계산하지 않는다.

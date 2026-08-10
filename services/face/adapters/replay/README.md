# Replay Face Adapter

## 목적

승인된 파생 이벤트 fixture를 캡처 시각과 sequence 규칙에 따라 다시 내보내 결측·지연을 포함한 통합·회귀 테스트를 재현한다.

## 입력과 출력

개인 식별 정보와 원본 미디어가 없는 `ExpressionSample` fixture와 replay clock 설정을 입력받아 같은 계약의 이벤트 stream을 출력한다.

## 경계

- 실제 고객의 얼굴 영상·이미지·base64 fixture를 읽지 않는다.
- 결측 score를 중립값으로 채우거나 fixture에 없는 label을 추정하지 않는다.
- drop·timeout·순서 역전은 scenario에 명시하고 원래 frame·capture time을 보존한다.

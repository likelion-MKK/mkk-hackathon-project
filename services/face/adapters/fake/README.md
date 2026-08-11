# Fake Face Adapter

## 목적

모델 설치 없이 Kiosk·추천 경계·API가 `ExpressionSample` 계약을 개발하고 CI에서 결정적으로 검증하도록 한다.

## 입력과 출력

`FrameContext`와 명시적인 seed/scenario를 입력받아 계약에 맞는 score·quality·유효성 결과를 출력한다. 같은 입력은 항상 같은 순서와 값을 만들어야 한다.

## 경계

- 실제 카메라·모델·weight·네트워크를 사용하지 않는다.
- 실제 감정·정확도·구매 의도를 대표한다고 주장하지 않는다.
- no-face, multi-face, unknown label, 낮은 quality와 timeout scenario를 명시적으로 제공한다.

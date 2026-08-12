# Fake Eye Adapter

## 목적

모델 설치 없이 Kiosk·AOI·API가 `GazeSample` 계약을 개발하고 CI에서 결정적으로 검증하도록 한다.

## 입력과 출력

`FrameContext`와 명시적인 seed/scenario를 입력받아 계약에 맞는 유효·무효 `GazeSample`을 출력한다. 같은 입력은 항상 같은 값을 만들어야 한다.

추론 실패 scenario와 전달 실패 scenario는 분리한다. `FakeEyeAdapter`는 입력의 `sequence`,
`frame_id`, 캡처 시각을 보존하고, `FakeGazeDelivery`의 `out_of_order` 모드가 인접한 두
샘플을 두 번째→첫 번째 순서로 전달한다. 홀수 번째 마지막 샘플은 `flush()`로 손실 없이
전달한다.

## 경계

- 실제 카메라·모델·weight·네트워크를 사용하지 않는다.
- 정확도나 실제 사용자 반응을 대표한다고 주장하지 않는다.
- 화면 밖, 낮은 confidence, no-face, 지연 같은 추론 실패 scenario를 명시적으로 제공한다.
- 순서 역전은 샘플 필드를 바꾸지 않고 Fake 전달 계층에서만 재현한다.
- Fake calibration은 ID 전달용 placeholder이며 실제 오차나 성공률을 대표하지 않는다.

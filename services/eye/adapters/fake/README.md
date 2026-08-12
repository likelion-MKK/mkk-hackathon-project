# Fake Eye Adapter

## 목적

모델 설치 없이 Kiosk·AOI·API가 `GazeSample` 계약을 개발하고 CI에서 결정적으로 검증하도록 한다.

## 입력과 출력

`FrameContext`와 명시적인 seed/scenario를 입력받아 계약에 맞는 유효·무효 `GazeSample`을 출력한다. 같은 입력은 항상 같은 순서와 값을 만들어야 한다.

## 경계

- 실제 카메라·모델·weight·네트워크를 사용하지 않는다.
- 정확도나 실제 사용자 반응을 대표한다고 주장하지 않는다.
- 화면 밖, 낮은 confidence, no-face, 지연·순서 역전 같은 실패 scenario를 명시적으로 제공한다.

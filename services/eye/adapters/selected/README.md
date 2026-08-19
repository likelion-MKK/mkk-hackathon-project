# Selected Eye Adapter

## 상태

EyeTrax `0.4.0`을 해커톤 MVP 구현 후보로 선택했고 실제 Adapter와 로컬 카메라 데모를
`services/eye/src/mcm_eye/adapters/eyetrax.py`에 둔다. 아직 Kiosk `VisionClient`에는 연결하지
않았으며 production 최종 모델을 뜻하지 않는다. weight는 Git에 포함하지 않는다.

## 연결 조건

- ADR-0004에 EyeTrax revision, FaceLandmarker URL·SHA256, 실행 환경과 알려진 한계가 있다.
- Dense5 학습, 별도 8점 세션 Gate와 `GazeSample` Contract test를 통과한다.
- 검은 프레임 smoke와 사용자 본인의 실제 카메라 1회 데모를 확인한다.
- FaceLandmarker `.task` bundle license는 미확인 상태이며 박형진의 해커톤 예외 승인을
  받기 전에는 라이선스 확인 완료나 Selected 연결 완료로 표현하지 않는다.

## 경계

모델 교체와 전처리·후처리는 이 슬롯 내부에서만 일어난다. Adapter는 전달받은 BGR frame을
메모리에서 처리하고 frame·landmark·프레임별 좌표를 출력·로그·파일에 남기지 않는다.
Kiosk 연결과 AOI 판정은 후속 작업으로 분리한다.

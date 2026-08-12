# Face Candidate Experiments

## 소유자

정은미. 후보별 하위 디렉터리는 `<candidate-id>/`로 분리한다.

## D2 후보 inventory

아래 표는 2026-08-13 기준의 실험 후보 목록이다. 후보 등록은 모델 선택을 의미하지 않으며, D4 동일 조건 benchmark와 D5 ADR 전까지 production Adapter에 연결하지 않는다.

| 후보 | 출력 성격 | Python package | Hard Gate | Smoke |
| --- | --- | --- | --- | --- |
| [MediaPipe Face Landmarker](mediapipe-face-landmarker/README.md) | 52개 얼굴 blendshape 계수 | `mediapipe==1.0.0` | `pending` | `not_run` |
| [OpenVINO emotions-recognition-retail-0003](openvino-emotions-retail-0003/README.md) | 5개 분류 점수 | `openvino==2026.3.0` | `pending` | `not_run` |
| [HSEmotion enet_b0_8_best_afew](hsemotion-enet-b0-8-best-afew/README.md) | 8개 분류 점수 | `hsemotion==0.3.0` | `pending` | `not_run` |

공통 조사 기준은 정확한 source revision, code·weight license, 모델 SHA256, Python 3.13.15 설치 가능성, 로컬 CPU 추론, 모델 다운로드 후 offline 재실행이다. 실제 얼굴 대신 코드에서 생성한 synthetic 입력만 사용한다.

## 입력과 출력

고정된 비식별 fixture·하드웨어 조건과 정확한 URL/revision/license를 입력으로 사용한다. 출력은 label mapping, 검증 label이 있을 때의 macro-F1·class recall, score 안정성, p50/p95 지연·FPS, 자원 사용량, 실패 사례와 재현 명령이다.

## 금지사항

- 실제 고객 원본 영상, credential, model weight를 Git에 넣지 않는다.
- 라이선스·revision 고정·offline 실행 Hard Gate를 통과하지 못한 후보를 점수만으로 선택하지 않는다.
- 관찰 점수를 실제 감정·성격·구매 의도 검증으로 표현하지 않는다.
- 실험 의존성을 공용 서비스나 루트 lock 파일에 섞지 않는다.

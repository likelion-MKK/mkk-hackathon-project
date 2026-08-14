# ADR-0004 EyeTrax 해커톤 MVP 선정

- 상태: Accepted (해커톤 MVP 한정)
- 결정일: 2026-08-15
- 결정 소유자: 양유상
- 관련 결정: `D1-01 시선 보정과 AOI`, `D1-03 Python·Node와 설치 방식`
- 관련 ADR: [`ADR-0001 원격 Eye·Face 추론 서버 전환`](0001-remote-vision-inference.md)
- 근거: [EyeTrax LG 노트북 dense5 baseline 판정](../../experiments/eye/eyetrax/results/2026-08-15-lg-laptop-live-report-dense5.md)

## 1. 결정 범위

해커톤 MVP에서 화면의 좌·우 상품 AOI를 구분하는 Eye 모델로 EyeTrax를 사용한다. 이
결정은 사용자 1명의 LG 개발 노트북 실측에 근거한 **해커톤 구현 선택**이다. 실제 Kiosk
장비·다중 사용자·운영 환경의 정확도를 확인한 최종 production 모델 선택이나 Kiosk D5
완료를 뜻하지 않는다.

EyeTrax는 사용자별 보정을 거쳐 viewport 기준 `(x, y)` 좌표를 직접 만들 수 있어, 3차원
시선 방향부터 화면 좌표 변환을 새로 구현해야 하는 후보보다 남은 해커톤 기간에
`GazeSample`을 연결하기 적합하다.

## 2. 선택한 구성

| 항목 | 고정값 |
| --- | --- |
| EyeTrax | `0.4.0` |
| source revision | `84e13a16af168ac7c383f7d50ec901cd6c0ad61d` |
| Python | Eye 서비스만 `3.12.10` |
| MediaPipe | `1.0.0` |
| NumPy / OpenCV | `1.26.4` / `4.11.0.86` |
| FaceLandmarker | MediaPipe `float16/1` |
| 모델 URL | <https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task> |
| 모델 SHA256 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| 라이선스 기록 | EyeTrax code `MIT`; FaceLandmarker `.task` bundle은 미확인, 박형진 해커톤 예외 승인 대기 |
| 출력 좌표 | viewport `0.0~1.0`, 좌상단 원점 |
| smoothing | 없음 |

`.task` archive에서 `face_detector.tflite`, `face_landmarks_detector.tflite`,
`geometry_pipeline_metadata_landmarks.binarypb`, `face_blendshapes.tflite`가 포함된 사실만
확인했다. 파일명만으로 각 weight가 외부 component model card와 정확히 같은 artifact라고
추정하지 않는다. 라이선스는 박형진의 명시적 해커톤 예외 승인 전까지 미확인 상태로
유지하며, 구현은 진행하되 라이선스 확인 완료나 production 연결 완료라고 표현하지 않는다.
모델 파일과 사용자별 보정 모델은 Git에 넣지 않는다.

## 3. 보정과 실패 처리

보정은 화면의 `10%·30%·50%·70%·90%` 위치로 구성한 5×5 Dense5 grid를 serpentine
순서로 진행한다. 점마다 1초 적응 후 1초 동안 특징을 모으고 최소 15개의 유효 sample을
요구한다. 부족하면 전체 보정을 한 번만 다시 시도한다.

Ridge alpha는 `0.001`, `0.01`, `0.1`, `1.0`, `10.0`을 보정점만 사용한
leave-one-calibration-point-out 방식으로 비교한다. 픽셀 오차 p50이 가장 작은 값을
선택하고 동률이면 p95를 사용한다. 검증점은 alpha 선택에 사용하지 않는다.

학습 완료 후 현재 예제 룩북의 좌·우 상품 영역 안에 둔 별도 8점을 각각 0.75초 적응,
1초 수집으로 검증한다. 모든 유효 frame의 오차를 하나의 배열에 합쳐 NumPy percentile을
계산하며, 이 해커톤 구현에서는 지점별 가중 percentile을 사용하지 않는다.

```text
valid 비율 = 8개 검증 구간의 유효 frame / 전체 정상 형식 frame
오차율 = 예측·표적 픽셀 거리 / 논리 viewport 대각선
세션 Gate = valid >= 90%, 오차 p50 <= 10%, 오차 p95 <= 25%
```

`no_face`, `blink`, 비유효한 예측과 viewport 밖 예측은 invalid로 세고 valid 비율의 분모에
포함한다. 이 세션 Gate는 아래의 모델 선정 Gate와 별개이며 전체 viewport 정확도를
주장하지 않는다. sample 부족 또는 세션 Gate 실패 시 Dense5 학습부터 전체를 한 번만
재시도하고, 두 번째 실패 뒤에는 `gaze_unavailable`을 반환한다.

한 번의 재시도 후에도 보정할 수 없으면 다른 모델 결과를 자동 생성하지 않고
`gaze_unavailable`로 처리한다. 화면 밖 예측은 clamp하거나 상품 AOI에 연결하지 않는다.
OpenVINO는 이 경우의 자동 runtime fallback이 아니라 후속 재평가 후보로만 남긴다.

## 4. 검증 Gate와 결과

### Gate

세 번의 독립 baseline 실행이 각각 다음 조건을 모두 만족해야 한다.

- valid 비율 `>= 90%`
- 유효 예측의 AOI hit `>= 80%`
- capture-to-result p95 `<= 100ms`
- no-face 구간 무효 판정 `>= 95%`
- crash, checksum 불일치 또는 카메라 해제 실패 없음

### 환경

- 참가자: 본인 1명, baseline 3회
- OS: Windows 11 `10.0.26200`
- 화면: 논리 1536×864, 물리 1920×1080, 배율 125%
- 카메라: `LGE Camera`, index 0, 1280×720·30 FPS, DSHOW
- benchmark Git head: `6d0550abc0af4f117b6324541770f0e2496c0984`

### Dense5 실측

| Run | valid | AOI hit | 오차 p50 / p95 | 지연 p50 / p95 | FPS | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 100.00% | 94.74% | 118.78 / 293.30 px | 28.17 / 49.26 ms | 17.49 | 통과 |
| 2 | 100.00% | 89.52% | 88.33 / 241.18 px | 28.11 / 47.58 ms | 17.53 | 통과 |
| 3 | 100.00% | 87.10% | 74.23 / 373.92 px | 29.07 / 47.99 ms | 17.51 | 통과 |

no-face는 준비 확인 후 `36/36` frame을 무효로 판정했고 카메라도 정상 해제했다. peak RSS는
259.4~261.1 MiB, process CPU 평균은 176.24~183.25%였다. 원본 frame·영상·이미지,
embedding과 프레임별 gaze 좌표는 저장하지 않았다.

재현 명령과 frame별 정보를 포함하지 않은 집계 원본은
[`2026-08-15-lg-laptop-live-summary-dense5.json`](../../experiments/eye/eyetrax/results/2026-08-15-lg-laptop-live-summary-dense5.json)에
고정한다.

## 5. 실패한 방식과 대안

| 선택지 | 판단 | 근거 |
| --- | --- | --- |
| EyeTrax 9점 보정 | 사용하지 않음 | 예측이 화면 중앙으로 수축해 세 실행 모두 AOI Gate 실패 |
| EyeTrax Dense5 | **해커톤 MVP 채택** | Gate를 완화하지 않고 세 실행이 모두 통과했으며 화면 좌표 보정 경로가 있음 |
| OpenVINO gaze-estimation | 재평가 후보 | 3차원 gaze vector에서 화면 좌표를 만들기 위한 얼굴·눈·머리 각도 전처리와 별도 보정 구현이 추가로 필요 |
| 그 밖의 D2 후보 | 이번 결정에서 보류 | 동일한 live ground-truth 검증을 끝내지 않았으므로 정확도 우열을 주장하지 않음 |

9점 보정 실패 뒤 AOI polygon이나 Gate 수치를 완화하지 않았다. 보정 범위를 Dense5로 넓히고
alpha를 보정점 교차 검증으로 선택한 뒤 같은 Gate를 다시 적용했다. 세 실행 모두
`alpha=10.0`이 선택됐다.

## 6. 영향과 경계

- 후속 EyeTrax Adapter는 Eye 서비스 전용 Python `3.12.10` 환경에서 구현한다. API·Face와
  다른 Python 환경은 변경하지 않는다.
- 공개 `EyeAdapter`, `GazeSample`과 Contract v1 필드·의미는 변경하지 않는다.
- 원본 frame은 전달받은 메모리 참조로만 처리하고 출력·예외·로그·파일·DB·cache에 넣지
  않는다.
- ADR-0001은 계속 별도 결정이다. 이 ADR은 실제 고객 frame의 원격 전송이나 Vision 서버
  배포를 승인하지 않는다.
- AOI hit는 모델 선택 근거일 뿐 dwell·재시선·Top 2 계산을 Eye Adapter에 추가하지 않는다.
- MediaPipe 공식 개인정보 안내는 입력 자체는 기기에서 처리하지만 성능·사용 지표 전송
  가능성을 알린다. 이번 해커톤 브랜치에서는 자동 network 차단 검증을 구현하지 않고
  잔여 위험으로 남긴다.
  <https://github.com/google-ai-edge/mediapipe#privacy-notice>

## 7. 알려진 한계와 재평가 조건

- 참가자 1명과 LG 노트북 RGB 카메라에서만 측정했다.
- 실제 Kiosk, 다른 사용자·카메라, 머리 움직임, 조도 변화, 다중 얼굴과 장시간 안정성은
  검증하지 않았다.
- 현재 예제 룩북의 큰 좌·우 상품 AOI 구분을 통과한 결과다. Run 3 오차 p95가 373.92px이므로
  작고 정밀한 영역의 point-of-gaze 정확도로 해석하지 않는다.
- 25개 점 보정의 실제 Kiosk UX와 완료 시간은 검증하지 않았다.
- 지연은 개발 PC의 local capture-to-result다. WSS·Vision Gateway·network 왕복 지연을
  포함하지 않는다.

실제 Kiosk 또는 배포 대상 환경에서 valid 90%, AOI hit 80%, 지연 p95 100ms, no-face 95%
중 하나라도 충족하지 못하거나 Dense5 보정 시간이 사용자 흐름에 맞지 않으면 이 결정을
재평가한다. 그때는 수치를 완화하지 않고 OpenVINO를 다음 후보로 같은 조건에서 평가한다.

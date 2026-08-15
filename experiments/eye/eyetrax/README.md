# EyeTrax Live Benchmark

## 목적과 상태

이 도구는 사용자 본인 한 명이 개발 PC 카메라를 보며 EyeTrax의 화면 보정, 좌·우 상품
AOI 구분과 처리 지연을 확인하는 D4 실험이다. 결과는 **단일 사용자·개발 PC 관찰값**이며
실제 Kiosk 정확도나 D5 최종 모델 선택을 뜻하지 않는다.

## 고정 후보와 환경

| 항목 | 값 |
| --- | --- |
| EyeTrax | `0.4.0`, source `84e13a16af168ac7c383f7d50ec901cd6c0ad61d`, MIT |
| Python | `3.12.10` 전용 환경 |
| FaceLandmarker | MediaPipe `float16/1`, 아래 URL과 SHA256 고정 |
| 화면 | Windows 논리 viewport와 물리 해상도·배율을 함께 기록 |
| 카메라 | 기본 index `0`, `LGE Camera`, 1280×720·30FPS 요청 |
| smoothing | 없음, EyeTrax raw Ridge 예측 |

- 모델 URL: <https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task>
- SHA256: `64184E229B263107BC2B804C6625DB1341FF2BB731874B0BCC2FE6544E0BC9FF`

model 파일은 `.cache/`, 가상환경은 `.venv/`에만 두며 둘 다 Git에 넣지 않는다. 보정
Ridge 모델도 저장하지 않고 각 실행이 끝나면 메모리에서 폐기한다.
Windows의 MediaPipe가 한글 경로를 열지 못하는 경우 검증된 model을 영문 임시 경로로
복사해 실행하고, 모든 estimator를 닫은 직후 임시 복사본을 삭제한다.

## 개인정보 경계

- 사용자가 `Space`를 눌러야 카메라 측정을 시작하며 `Esc`로 즉시 중단할 수 있다.
- 원본 frame, 이미지, 영상, base64, embedding, 프레임별 gaze 좌표를 저장하지 않는다.
- 결과 JSON에는 집계 지표, 환경, 고정 revision/checksum과 `participant_count=1`만 남긴다.
- 카메라는 예외·취소·정상 종료 모두에서 release하고 OpenCV 창을 닫는다.

## 설치와 실행

이 디렉터리에서 실행한다.

```powershell
uv sync --locked
uv run python live_accuracy.py --prepare-model
uv run python live_accuracy.py --prepare-model --offline
uv run pytest
uv run python live_accuracy.py --camera 0 --runs 3 --condition baseline
uv run python live_accuracy.py --camera 0 --runs 1 --condition baseline --calibration dense5 --output results/dense5-diagnostic.json
uv run python live_accuracy.py --camera 0 --runs 3 --condition baseline --calibration dense5 --offline --output results/2026-08-15-lg-laptop-live-summary-dense5.json
```

첫 `--prepare-model`은 공식 URL에서 모델을 내려받아 SHA256을 검증한다. 두 번째 명령은
network 없이 같은 모델을 다시 검증한다. 라이브 실행 중에는 화면 점을 바라본다. 마지막
`STEP OUT OR COVER` 안내가 나오면 키를 누르지 말고 20초 안에 카메라 화면 밖으로 이동하거나
RGB 렌즈를 손·불투명한 종이로 가린다. 도구가 no-face 10프레임을 연속 확인한 뒤 자동 측정
3초를 시작하므로 그동안 그대로 있는다.

기본 `9p`는 최초 승인 protocol을 재현한다. `dense5`는 9점 Ridge 진단에서 중앙 수축과
검증점 일반화 실패가 확인된 뒤 추가한 5×5 serpentine 보정 비교 모드이며 Gate 기준은
변경하지 않는다.

기본 결과 경로는 `results/<KST 날짜>-lg-laptop-live-summary.json`이다. 기존 결과가 있으면
덮어쓰지 않고 종료하므로 추가 참고 실행은 `--output`으로 새 파일명을 명시한다.

## 채택 Gate

세 번의 독립 실행이 각각 `valid ≥ 90%`, `AOI hit ≥ 80%`, capture-to-result
`p95 ≤ 100ms`를 만족하고, no-face 구간의 `no_face ≥ 95%`이며 카메라가 정상 해제되어야
통과한다. 통과해도 `eyetrax_provisional_priority`, 실패하면
`eyetrax_deferred_openvino_next`로만 기록한다.

안경은 사용자의 평상시 상태를 baseline으로 삼는다. `glasses`와 `head-motion` condition은
별도 참고 실행용이며 자동 채택 Gate에는 사용하지 않는다.

## 현재 실측 결과

- 최초 9점 보정: [집계 JSON](results/2026-08-15-lg-laptop-live-summary.json),
  [판정 보고서](results/2026-08-15-lg-laptop-live-report.md) — `EyeTrax deferred`
- AOI 원인 진단 뒤 5×5 보정: [집계 JSON](results/2026-08-15-lg-laptop-live-summary-dense5.json),
  [판정 보고서](results/2026-08-15-lg-laptop-live-report-dense5.md) —
  `EyeTrax provisional priority`
- 실제 키오스크 장비가 없어 D5 재검증은 생략한다. 두 결과 모두 사용자 1명의 LG 개발
  노트북 실측이며, 현재 판정은 개발 MVP의 우선 후보를 뜻할 뿐 실제 키오스크 정확도나
  최종 채택 결과가 아니다.

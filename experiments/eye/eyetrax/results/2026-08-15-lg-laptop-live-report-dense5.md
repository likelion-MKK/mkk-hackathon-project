# EyeTrax LG 노트북 dense5 baseline 판정

## 결론

`EyeTrax provisional priority`로 판정한다. AOI 기준이나 Gate를 완화하지 않은 상태에서
5×5 serpentine 보정 baseline 세 번이 각각 모든 Gate를 통과했다. 따라서 EyeTrax를 현재
개발 MVP의 우선 후보로 유지한다. 실제 키오스크 장비가 없어 D5 재검증은 생략한다. 이
결과는 사용자 1명의 개발 PC 실측이며 EyeTrax의 최종 채택이나 실제 키오스크 정확도
판정이 아니다.

## AOI 실패 원인과 조치

최초 9점 보정에서는 검증점 예측이 화면 중앙으로 수축하여 좌·우 상품 AOI의 경계 안에
안정적으로 들어가지 못했다. 좌표축 반전이나 AOI polygon 오류가 아니라, 이 사용자·카메라
조합에서 보정점의 공간 범위가 부족해 Ridge 모델이 보정에 쓰지 않은 점으로 일반화하지
못한 것이 진단상 주된 원인으로 판단됐다.

Gate와 AOI polygon은 그대로 두고 다음만 변경했다.

- 보정점을 10%·30%·50%·70%·90%의 5×5 serpentine grid로 늘렸다.
- 검증점은 모델 선택에 쓰지 않고, 보정점만 leave-one-point-out 방식으로 평가하여 Ridge
  alpha를 선택했다. 세 실행 모두 `alpha=10.0`이 선택됐다.
- no-face는 사용자가 이동하거나 RGB 렌즈를 가린 뒤 10프레임 연속 미검출을 확인하고
  3초간 측정하도록 시작 조건을 추가했다.

## 실측 결과

| Run | valid | AOI hit | 오차 p50 / p95 | 지연 p50 / p95 | FPS | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 100.00% | 94.74% | 118.78 / 293.30 px | 28.17 / 49.26 ms | 17.49 | 통과 |
| 2 | 100.00% | 89.52% | 88.33 / 241.18 px | 28.11 / 47.58 ms | 17.53 | 통과 |
| 3 | 100.00% | 87.10% | 74.23 / 373.92 px | 29.07 / 47.99 ms | 17.51 | 통과 |

- no-face: 준비 확인 후 `36/36` 무효 판정, 100%; 카메라 정상 해제
- 카메라: `LGE Camera`, index 0, 요청값과 적용값 모두 1280×720·30 FPS, DSHOW
- 화면: 논리 viewport 1536×864, 물리 해상도 1920×1080, 배율 125%
- 자원: peak RSS 259.4–261.1 MiB, process CPU 평균 176.24–183.25%
- 개인정보: 원본 frame, 영상, 이미지, embedding과 프레임별 gaze 좌표를 저장하지 않았다.

Run 3의 픽셀 오차 p95는 373.92 px로 여전히 큰 꼬리가 있으므로 정밀한 작은 영역의 시선
좌표로 해석해서는 안 된다. 다만 이번 MVP Gate의 목적은 현재 예제 룩북의 좌·우 상품 AOI
구분이며, 세 실행의 유효 예측 AOI hit가 모두 80% 이상이므로 해당 기준은 통과했다.

## 재현 정보

- 집계 JSON: [`2026-08-15-lg-laptop-live-summary-dense5.json`](2026-08-15-lg-laptop-live-summary-dense5.json)
- Git head: `6d0550abc0af4f117b6324541770f0e2496c0984`
- branch: `feat/eye/d04-eyetrax-live-benchmark`
- Python 3.12.10, EyeTrax 0.4.0
- FaceLandmarker SHA256:
  `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`

```powershell
uv sync --locked
uv run pytest
uv run python live_accuracy.py --camera 0 --runs 3 --condition baseline --calibration dense5 --offline --output results/2026-08-15-lg-laptop-live-summary-dense5.json
```

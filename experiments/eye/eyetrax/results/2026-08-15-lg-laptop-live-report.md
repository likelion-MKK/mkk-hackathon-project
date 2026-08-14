# EyeTrax LG 노트북 baseline 판정

## 결론

`EyeTrax deferred`로 판정한다. 세 번의 baseline 실행 중 Gate를 통과한 실행이 없으므로
임계값을 완화하거나 선택적으로 재실행하지 않고 OpenVINO 평가로 전환한다. 이 결과는
사용자 1명의 개발 PC 실측이며 실제 키오스크 D5 최종 판정이 아니다.

## 실측 결과

| Run | valid | AOI hit | 오차 p50 / p95 | 지연 p50 / p95 | FPS | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 88.71% | 58.64% | 287.87 / 766.09 px | 26.35 / 43.51 ms | 17.55 | 실패 |
| 2 | 90.32% | 74.11% | 229.62 / 595.39 px | 26.33 / 43.60 ms | 17.58 | 실패 |
| 3 | 29.84% | 31.08% | 564.91 / 1258.26 px | 25.93 / 42.22 ms | 17.51 | 실패 |

- 9점 보정: 세 실행 모두 1회에 완료, 각 점 유효 sample 최소 21·28·24개
- no-face: `0/91` 무효 판정, 0%로 Gate 실패
- 카메라: `LGE Camera`, index 0, 요청값과 적용값 모두 1280×720·30 FPS, DSHOW
- 화면: 실행기는 물리 해상도 1920×1080 좌표를 사용했다. 실행 후 확인한 Windows 논리
  viewport는 계획과 같은 1536×864로 배율은 125%였다. 정규화 AOI 판정에는 영향이 없지만
  위 픽셀 오차는 물리 pixel 기준이다. 이후 실행기는 두 좌표계를 분리 기록하도록 수정했다.
- 자원: peak RSS 252.85–255.17 MiB, process CPU 평균 162.98–173.38%
- 개인정보: 원본 frame, 영상, 이미지, embedding과 프레임별 gaze 좌표를 저장하지 않았다.

사용자가 이 실행의 no-face 안내 때 이동하지 못해 카메라 시야에 남아 있었다고 확인했다.
따라서 `0/91`은 EyeTrax의 no-face 검출 실패 증거가 아니라 절차 미수행으로 해석한다. 다만
AOI와 valid Gate가 이미 실패했으므로 이 9점 실행의 deferred 판정에는 영향이 없다.

## 재현 정보

- 집계 JSON: [`2026-08-15-lg-laptop-live-summary.json`](2026-08-15-lg-laptop-live-summary.json)
- Git head: `6d0550abc0af4f117b6324541770f0e2496c0984`
- branch: `feat/eye/d04-eyetrax-live-benchmark`
- Python 3.12.10, EyeTrax 0.4.0
- FaceLandmarker SHA256:
  `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`

```powershell
uv sync --locked
uv run pytest
uv run python live_accuracy.py --camera 0 --runs 3 --condition baseline --offline
```

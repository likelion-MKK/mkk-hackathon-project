# Face D4 Candidate Benchmark

이 디렉터리는 Face 후보의 동일 조건 synthetic benchmark 방법과 요약 결과를 기록한다. 실제 고객 이미지·영상·base64·embedding을 사용하지 않으며, 정답 label이 없는 결과를 실제 정확도로 표현하지 않는다.

## 고정 workload

- fixture: `face-synthetic-d4-v1`, seed `20260815`
- 입력 순서: `no_face`, `synthetic_crop` 반복
- 세션: `N=1`, CPU
- cold: 새 프로세스 3회, asset 확인 → model load → warmup → 첫 추론
- warm: 모델을 유지하고 30초 분량을 3 FPS(90 frame), 5 FPS(150 frame)로 가속 실행
- 측정: load·warmup·첫 추론, p50/p95, 처리 capacity FPS, deadline miss, failure, output shape·label·score 유한성, 반복 출력 안정성, process RAM
- 원본 입력은 메모리에서만 생성하고 artifact·stdout·로그에 저장하지 않는다.

warm workload는 failure, deadline miss, 측정 샘플 누락 또는 불안정한 출력이 하나라도 있으면 `status=fail`이다. 개별 frame timeout을 측정한 것처럼 기록하지 않으며, 격리 worker의 180초 process timeout이 발생하면 `reason=worker_timeout`, 실패 단계와 제한 시간을 artifact에 남긴다.

가속 실행은 30초의 frame 수와 순서를 재현하지만 실제 30초 동안 sleep하지 않는다. 따라서 `capacity_fps`는 로컬 추론 처리량이며 network를 포함한 capture-to-result FPS가 아니다.

## 실행

각 명령은 후보의 독립 `uv` 환경에서 실행한다. online run은 고정 URL에서 누락 asset을 받아 checksum을 확인하고, offline run은 로컬 asset만 허용한다. 결과 JSON은 Git에서 ignored된 후보별 `artifacts/`에 저장된다.

```powershell
Set-Location experiments/face/mediapipe-face-landmarker
uv sync --locked
uv run python ../../../scripts/face_candidate_benchmark.py run mediapipe-face-landmarker --online
uv run python ../../../scripts/face_candidate_benchmark.py run mediapipe-face-landmarker --offline

Set-Location ../openvino-emotions-retail-0003
uv sync --locked
uv run python ../../../scripts/face_candidate_benchmark.py run openvino-emotions-retail-0003 --online
uv run python ../../../scripts/face_candidate_benchmark.py run openvino-emotions-retail-0003 --offline

Set-Location ../hsemotion-enet-b0-8-best-afew
uv sync --locked
uv run python ../../../scripts/face_candidate_benchmark.py run hsemotion-enet-b0-8-best-afew --online
uv run python ../../../scripts/face_candidate_benchmark.py run hsemotion-enet-b0-8-best-afew --offline
```

HSEmotion 명령은 checksum까지만 검증한다. 안전한 loader가 없는 동안 실제 model import·추론·latency 측정을 실행하지 않고 `hard_gate=fail`, `status=excluded`를 기록한다.

Harness 단위 테스트에는 synthetic fixture 생성을 위한 NumPy가 필요하다. 별도 루트 dependency를 추가하지 않고 MediaPipe 후보의 잠긴 `uv` 환경에서 실행한다.

```powershell
Set-Location experiments/face/mediapipe-face-landmarker
uv sync --locked
uv run python ../../../tests/test_face_candidate_benchmark.py
```

## 결과 해석

- `quality_evaluation: not_available_without_ground_truth`
- `stability_observation: pass|fail`
- `latency_measurement: measured|not_measured_hard_gate_exclusion`
- `accuracy_claim: none`

모델 weight는 후보별 ignored `models/`, raw metrics는 ignored `artifacts/`에만 둔다. 이 benchmark는 synthetic 입력의 실행 가능성·출력 안정성·지연 관찰이며 최종 모델 선정 문서가 아니다.

## 2026-08-15 결과

- [후보 비교와 임시 label mapping](2026-08-15-candidate-comparison.md)
- [MediaPipe Face Landmarker](2026-08-15-mediapipe-face-landmarker.md)
- [OpenVINO emotions-recognition-retail-0003](2026-08-15-openvino-emotions-retail-0003.md)
- [HSEmotion enet_b0_8_best_afew](2026-08-15-hsemotion-enet-b0-8-best-afew.md)

# OpenVINO emotions-recognition-retail-0003 D4 Benchmark

## 결론과 범위

- 실행일: 2026-08-15 01:55 KST
- Hard Gate: `pass`
- online asset 다운로드·검증과 offline 재실행: `pass`
- synthetic 출력 안정성: `pass`
- `quality_evaluation: not_available_without_ground_truth`
- `latency_measurement: measured`
- `accuracy_claim: none`

이 후보는 얼굴 crop 분류기다. benchmark의 synthetic tensor 출력은 실행 가능성·안정성·지연만 보여 주며 실제 감정 정확도를 의미하지 않는다.

## 실행 환경과 고정 정보

| 항목 | 값 |
|---|---|
| OS | Microsoft Windows 11 Home 64-bit, `10.0.26200` |
| CPU | Intel Core Ultra 7 155H, 16 cores / 22 logical processors |
| GPU | Intel Arc Graphics, driver `32.0.101.8424`; 사용하지 않음 |
| RAM | 15.59 GiB |
| Python | CPython `3.13.15` |
| package | `openvino==2026.3.0`, `numpy==2.5.2` |
| device | OpenVINO CPU |
| source | `https://github.com/openvinotoolkit/open_model_zoo` |
| source revision | tag `2023.3.0`, commit `cf08c4915cde7513bc1970484a8901ac37df8283` |
| code license | Apache-2.0 |
| weight license | Apache-2.0 — Open Model Zoo manifest 기준 |
| XML SHA256 | `11768c788fdf242ac93fa749504674878e3c797a5dce5b1d874e387a6b88f1fc` |
| BIN SHA256 | `faaef5507627692057ac3b4dcd465de23568d59677f0f71c36d06bb9947904da` |
| fixture | `face-synthetic-d4-v1`, seed `20260815` |
| input digest | no-face `3381de4c…ec9e`, synthetic crop `abbf415b…399b` |

D4 시작 시 XML·BIN이 없었으며 첫 online harness가 고정 URL에서 다운로드해 SHA256 검증 후 `models/FP32/`에 확정했다. 이후 final online·offline run은 local asset만 다시 검증했다.

## 입력·전처리·출력

- 공통 `256×256×3` RGB synthetic 입력을 nearest-neighbor로 `64×64`로 줄인다.
- BGR 순서, `float32`, `1×3×64×64` tensor로 변환한다.
- 출력 shape: `1×5×1×1`.
- 원본 label 순서: `neutral`, `happy`, `sad`, `surprise`, `anger`.
- 5개 score는 모두 유한하며 반복 output signature가 동일했다.
- 임시 mapping은 각각 `neutral_like`, `happy_like`, `sad_like`, `surprise_like`, `anger_like`다. 최종 taxonomy가 아니다.

이 모델에는 얼굴 detector가 없다. no-face synthetic tensor에도 5개 score를 반환하므로 `no_face_validation=not_supported_classifier_requires_face_crop`이다. production 사용 시 upstream detector와 invalid 의미가 별도로 필요하며 D4에서 구현하지 않는다.

## 측정 결과

Cold는 새 프로세스 3회다. 표의 load·warmup·first는 3회 중앙값이며 asset checksum 시간은 별도다.

| mode | asset 확인 3회(ms) | model load 중앙값(ms) | warmup 중앙값(ms) | first inference 중앙값(ms) |
|---|---:|---:|---:|---:|
| online | 20.178, 22.416, 18.553 | 557.658 | 4.407 | 4.929 |
| offline | 17.474, 22.322, 20.943 | 581.774 | 6.314 | 5.132 |

Offline warm 결과:

| 요청 workload | frame 수 | p50(ms) | p95(ms) | 처리 capacity FPS | deadline miss | failure |
|---|---:|---:|---:|---:|---:|---:|
| 30초 × 3 FPS | 90 | 4.124 | 6.883 | 238.670 | 0 | 0 |
| 30초 × 5 FPS | 150 | 3.827 | 6.512 | 252.186 | 0 | 0 |

- 반복 입력별 output signature 안정성: `pass`
- offline warm process peak working set: 105.348 MiB
- VRAM: 사용하지 않음
- 3 FPS·5 FPS frame interval 내 deadline miss: 모두 `0`
- worker process timeout: 발생하지 않음

`capacity_fps`는 crop 생성과 로컬 CPU 분류 처리량이다. 얼굴 검출, encode·network·Gateway·동시 세션을 포함하지 않는다.

## 실행 명령과 artifact

```powershell
Set-Location experiments/face/openvino-emotions-retail-0003
uv sync --locked
uv run python ../../../scripts/face_candidate_benchmark.py run openvino-emotions-retail-0003 --online
uv run python ../../../scripts/face_candidate_benchmark.py run openvino-emotions-retail-0003 --offline
```

- raw metrics: ignored `experiments/face/openvino-emotions-retail-0003/artifacts/d4-online.json`
- raw metrics: ignored `experiments/face/openvino-emotions-retail-0003/artifacts/d4-offline.json`
- model assets: ignored `experiments/face/openvino-emotions-retail-0003/models/FP32/`

## 알려진 제한과 D5 확인

- no-face를 직접 판단하지 못하며 얼굴 crop 이전 단계가 필요하다.
- 정면 얼굴, 약 ±15도 yaw·pitch, 최소 64px라는 원 모델 제한이 있다.
- Open Model Zoo maintenance mode의 유지보수 위험이 있다.
- 실제 label 품질, detector 포함 총지연과 공통 taxonomy는 D5에서 결정한다.

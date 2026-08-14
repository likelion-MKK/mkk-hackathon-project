# HSEmotion enet_b0_8_best_afew D4 Gate Report

## 결론

- 실행일: 2026-08-15 01:55 KST
- Hard Gate: `fail`
- 실제 추론 benchmark: `excluded`
- 실패 단계: 안전한 모델 loading
- 이유: `unsafe_legacy_pickle_blocked`
- `quality_evaluation: not_available_without_ground_truth`
- `stability_observation: not_measured_hard_gate_exclusion`
- `latency_measurement: not_measured_hard_gate_exclusion`
- `accuracy_claim: none`

`weights_only=False`를 사용하거나 pickle 보안 검사를 우회하지 않았다. 따라서 load·warmup·first inference·p50·p95·FPS·RAM/VRAM은 측정하지 않았다.

## 환경과 고정 정보

| 항목 | 값 |
|---|---|
| OS | Microsoft Windows 11 Home 64-bit, `10.0.26200` |
| CPU | Intel Core Ultra 7 155H, 16 cores / 22 logical processors |
| GPU | Intel Arc Graphics, driver `32.0.101.8424`; 사용하지 않음 |
| RAM | 15.59 GiB |
| Python | CPython `3.13.15` |
| package | `hsemotion==0.3.0`, `torch==2.13.0`, `timm==1.0.28`, `numpy==2.5.2` |
| source | `https://github.com/av-savchenko/hsemotion` |
| source revision | `2546ff6fd09f911c0619354523293ff621b31ba2` |
| weight revision | `520a051c64cd191521e5934655314e769a319684` |
| code license | Apache-2.0 |
| weight license | Apache-2.0 — weight source repository 기준 |
| model SHA256 | `47c1423f3e6f50e3750bf7b0eda7db947c9ce0c2637e1766bf2187eddc652b17` |
| expected input | `224×224×3` RGB crop, ImageNet normalize |
| expected labels | Anger, Contempt, Disgust, Fear, Happiness, Neutral, Sadness, Surprise |

D4 시작 시 weight가 없었으며 첫 online gate check가 고정 revision URL에서 다운로드해 `.download` 상태에서 SHA256을 검증한 뒤 ignored `models/`에 확정했다. offline gate check도 동일 checksum을 확인했다. checksum 이후에는 model runtime을 import하거나 pickle을 load하지 않았다.

## 재현 명령과 오류 요약

```powershell
Set-Location experiments/face/hsemotion-enet-b0-8-best-afew
uv sync --locked
uv run python ../../../scripts/face_candidate_benchmark.py run hsemotion-enet-b0-8-best-afew --online
uv run python ../../../scripts/face_candidate_benchmark.py run hsemotion-enet-b0-8-best-afew --offline
```

두 명령 모두 asset checksum을 통과한 뒤 다음 상태를 기록한다.

```text
status=excluded
hard_gate=fail
reason=unsafe_legacy_pickle_blocked
inference_benchmark=excluded
```

- raw metrics: ignored `experiments/face/hsemotion-enet-b0-8-best-afew/artifacts/d4-online.json`
- raw metrics: ignored `experiments/face/hsemotion-enet-b0-8-best-afew/artifacts/d4-offline.json`
- model asset: ignored `experiments/face/hsemotion-enet-b0-8-best-afew/models/enet_b0_8_best_afew.pt`

## label 비교와 D5 재확인 조건

원본 8개 label은 삭제하지 않고 소문자 `_like` 임시 이름으로만 inventory한다. 실제 출력, no-face, output shape, score 유한성, 반복 안정성은 안전 로딩 실패로 검증하지 못했다.

D5에서 다시 검토하려면 다음 중 하나가 고정 revision·license·checksum과 함께 제공되어야 한다.

- 안전하게 load 가능한 순수 `state_dict`
- 검증 가능한 ONNX 등 pickle이 아닌 배포 형식
- 공식적으로 문서화된 안전 loader와 변환 절차

조건이 충족되기 전에는 benchmark나 production 후보로 되살리지 않는다.

# MediaPipe Face Landmarker D4 Benchmark

## 결론과 범위

- 실행일: 2026-08-15 01:55 KST
- Hard Gate: `pass`
- online asset 확인과 offline 재실행: `pass`
- synthetic 출력 안정성: `pass`
- `quality_evaluation: not_available_without_ground_truth`
- `latency_measurement: measured`
- `accuracy_claim: none`

이 결과는 synthetic no-face와 코드로 생성한 face-like crop의 실행 가능성·출력·지연 관찰이다. 실제 얼굴 정확도, 감정, 성격 또는 구매 의도를 검증하지 않는다.

## 실행 환경과 고정 정보

| 항목 | 값 |
|---|---|
| OS | Microsoft Windows 11 Home 64-bit, `10.0.26200` |
| CPU | Intel Core Ultra 7 155H, 16 cores / 22 logical processors |
| GPU | Intel Arc Graphics, driver `32.0.101.8424`; 사용하지 않음 |
| RAM | 15.59 GiB |
| Python | CPython `3.13.15` |
| package | `mediapipe==1.0.0`, `numpy==2.5.2` |
| device | CPU |
| source | `https://github.com/google-ai-edge/mediapipe` |
| source revision | `493c90e5f3eb40b9080606964fc18528a99962f0` |
| code license | Apache-2.0 |
| model URL | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` |
| weight license | Apache-2.0 — D2 구성 모델 공식 model card 기준 |
| model SHA256 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| fixture | `face-synthetic-d4-v1`, seed `20260815` |
| input digest | no-face `3381de4c…ec9e`, synthetic crop `abbf415b…399b` |

모델 asset은 D2 실행에서 이미 `models/`에 존재했다. D4 online·offline run 모두 로드 전에 같은 SHA256을 검증했으며 추가 다운로드는 발생하지 않았다.

## 입력·전처리·출력

- 공통 `256×256×3` RGB `uint8` synthetic 입력을 사용한다.
- no-face는 검은 frame, face-like crop은 코드로만 생성한 고정 도형이며 파일로 저장하지 않는다.
- MediaPipe `Image`로 변환하고 `num_faces=1`, blendshape 출력을 활성화한다.
- no-face: `face_count=0`, landmark·blendshape group `0`, score `0` — 검증 `pass`.
- face-like crop: `face_count=1`, landmark group `1`, blendshape group `1`, 유한한 score `52개`.
- 원본 52개 이름을 보존한다. `_neutral`은 `unmapped`, 나머지는 이름 기반 `<blendshape>_like` 임시 신호로만 비교한다.

## 측정 결과

Cold는 새 프로세스 3회다. 표의 load·warmup·first는 3회 중앙값이며 asset checksum 시간은 별도다.

| mode | asset 확인 3회(ms) | model load 중앙값(ms) | warmup 중앙값(ms) | first inference 중앙값(ms) |
|---|---:|---:|---:|---:|
| online | 9.088, 8.468, 7.031 | 1384.556 | 4.204 | 18.388 |
| offline | 6.514, 9.196, 7.113 | 1361.140 | 5.814 | 20.538 |

Offline warm 결과:

| 요청 workload | frame 수 | p50(ms) | p95(ms) | 처리 capacity FPS | deadline miss | failure | timeout |
|---|---:|---:|---:|---:|---:|---:|---:|
| 30초 × 3 FPS | 90 | 4.723 | 20.222 | 96.475 | 0 | 0 | 0 |
| 30초 × 5 FPS | 150 | 5.361 | 19.651 | 96.280 | 0 | 0 | 0 |

- 반복 입력별 output signature 안정성: `pass`
- offline warm process peak working set: 138.020 MiB
- VRAM: 사용하지 않음
- 3 FPS·5 FPS frame interval 내 deadline miss: 모두 `0`

`capacity_fps`는 sleep 없이 실행한 로컬 CPU 추론 처리량이다. encode·network·Gateway·동시 세션을 포함한 capture-to-result FPS가 아니다.

## 실행 명령과 artifact

```powershell
Set-Location experiments/face/mediapipe-face-landmarker
uv sync --locked
uv run python ../../../scripts/face_candidate_benchmark.py run mediapipe-face-landmarker --online
uv run python ../../../scripts/face_candidate_benchmark.py run mediapipe-face-landmarker --offline
```

- raw metrics: ignored `experiments/face/mediapipe-face-landmarker/artifacts/d4-online.json`
- raw metrics: ignored `experiments/face/mediapipe-face-landmarker/artifacts/d4-offline.json`
- model asset: ignored `experiments/face/mediapipe-face-landmarker/models/face_landmarker.task`

## 알려진 제한과 D5 확인

- cartoon-like synthetic crop 검출은 실제 얼굴 품질 또는 label 정확도 증거가 아니다.
- 52개 blendshape를 감정 label로 단정하지 않는다.
- 좌우 blendshape 집계 여부와 공통 taxonomy는 D5 ADR에서 결정한다.
- 실제 목표 서버·approved fixture·network 조건에서 RAM과 capture-to-result를 다시 측정한다.

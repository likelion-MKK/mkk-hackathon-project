# Face D4 Candidate Comparison

> 이 문서는 최종 모델 선정 문서가 아니다. D4 synthetic workload의 실행 가능성·출력·안정성·지연과 임시 label mapping을 비교하며, 선택·fallback·production mapping은 D5 ADR에서 결정한다.

## 공통 조건

- 실행일: 2026-08-15 01:55 KST
- 환경: Windows 11 Home `10.0.26200`, Intel Core Ultra 7 155H, RAM 15.59 GiB
- 실행 device: CPU; Intel Arc GPU·VRAM은 사용하지 않음
- Python: `3.13.15`, 후보별 독립 `uv.lock`
- fixture: `face-synthetic-d4-v1`, seed `20260815`
- 입력: 코드 생성 no-face와 고정 face-like crop, 동일 순서
- cold: 새 프로세스 3회
- warm: 30초 분량 3 FPS 90 frame, 5 FPS 150 frame
- quality: `not_available_without_ground_truth`
- accuracy claim: `none`

## 후보 비교

아래 지연·메모리는 offline warm run 기준이다. load·first는 cold 3회 중앙값이다.

| 후보 | 실제 추론 | Gate | load(ms) | first(ms) | 3 FPS p50/p95(ms) | 5 FPS p50/p95(ms) | capacity FPS(3/5) | peak RAM | 안정성 | no-face |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| MediaPipe Face Landmarker | 측정 | pass | 1361.140 | 20.538 | 4.723 / 20.222 | 5.361 / 19.651 | 96.475 / 96.280 | 138.020 MiB | pass | 빈 검출·빈 score, pass |
| OpenVINO emotions-retail-0003 | 측정 | pass | 581.774 | 5.132 | 4.124 / 6.883 | 3.827 / 6.512 | 238.670 / 252.186 | 105.348 MiB | pass | 미지원; crop classifier |
| HSEmotion enet_b0_8_best_afew | 제외 | fail | — | — | — | — | — | — | 미측정 | 미측정 |

- MediaPipe와 OpenVINO 모두 failure·3/5 FPS deadline miss가 `0`이었고 worker process timeout은 발생하지 않았다.
- MediaPipe는 face-like crop에서 52 blendshape를, no-face에서 빈 결과를 반환했다.
- OpenVINO는 입력마다 5개 유한 score를 반환했지만 detector가 없어 no-face를 구분하지 못했다.
- HSEmotion은 checksum·license·package 설치까지 확인했지만 안전한 loader가 없어 추론하지 않았다.
- 처리 capacity는 로컬 inference loop 값이며 detector·encode·network·Gateway·동시 세션을 포함하지 않는다.

## license·revision·checksum

| 후보 | source revision | code / weight license | SHA256 상태 | offline |
|---|---|---|---|---|
| MediaPipe | `493c90e5…62f0` | Apache-2.0 / Apache-2.0 | task `64184e22…c9ff`, pass | pass |
| OpenVINO | OMZ `2023.3.0`, `cf08c491…d3` | Apache-2.0 / Apache-2.0 | XML `11768c78…f1fc`, BIN `faaef550…04da`, pass | pass |
| HSEmotion | code `2546ff6f…ba2`, weight `520a051c…684` | Apache-2.0 / Apache-2.0 | PT `47c1423f…2b17`, pass | checksum pass, inference excluded |

## label 정규화 비교

모든 원본 label을 보존한다. 아래 mapping은 D4 비교용이며 Contract·production taxonomy가 아니다.

| 후보 | 원본 label | 임시 공통 label | 매핑 근거 | 불확실성 | 최종 확정 여부 |
|---|---|---|---|---|---|
| mediapipe-face-landmarker | `_neutral` | `unmapped` | baseline category이며 감정 의미를 추론하지 않음 | 높음 | 아니오 |
| mediapipe-face-landmarker | `browDownLeft` | `brow_down_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `browDownRight` | `brow_down_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `browInnerUp` | `brow_inner_up_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `browOuterUpLeft` | `brow_outer_up_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `browOuterUpRight` | `brow_outer_up_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `cheekPuff` | `cheek_puff_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `cheekSquintLeft` | `cheek_squint_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `cheekSquintRight` | `cheek_squint_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeBlinkLeft` | `eye_blink_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeBlinkRight` | `eye_blink_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookDownLeft` | `eye_look_down_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookDownRight` | `eye_look_down_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookInLeft` | `eye_look_in_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookInRight` | `eye_look_in_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookOutLeft` | `eye_look_out_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookOutRight` | `eye_look_out_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookUpLeft` | `eye_look_up_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeLookUpRight` | `eye_look_up_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeSquintLeft` | `eye_squint_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeSquintRight` | `eye_squint_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeWideLeft` | `eye_wide_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `eyeWideRight` | `eye_wide_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `jawForward` | `jaw_forward_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `jawLeft` | `jaw_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `jawOpen` | `jaw_open_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `jawRight` | `jaw_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthClose` | `mouth_close_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthDimpleLeft` | `mouth_dimple_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthDimpleRight` | `mouth_dimple_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthFrownLeft` | `mouth_frown_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthFrownRight` | `mouth_frown_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthFunnel` | `mouth_funnel_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthLeft` | `mouth_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthLowerDownLeft` | `mouth_lower_down_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthLowerDownRight` | `mouth_lower_down_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthPressLeft` | `mouth_press_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthPressRight` | `mouth_press_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthPucker` | `mouth_pucker_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthRight` | `mouth_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthRollLower` | `mouth_roll_lower_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthRollUpper` | `mouth_roll_upper_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthShrugLower` | `mouth_shrug_lower_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthShrugUpper` | `mouth_shrug_upper_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthSmileLeft` | `mouth_smile_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthSmileRight` | `mouth_smile_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthStretchLeft` | `mouth_stretch_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthStretchRight` | `mouth_stretch_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthUpperUpLeft` | `mouth_upper_up_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `mouthUpperUpRight` | `mouth_upper_up_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `noseSneerLeft` | `nose_sneer_left_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| mediapipe-face-landmarker | `noseSneerRight` | `nose_sneer_right_like` | 관찰 가능한 원본 blendshape 이름 보존 | 높음 | 아니오 |
| openvino-emotions-retail-0003 | `neutral` | `neutral_like` | 원본 5-class 이름에 `_like`만 부여 | 중간 | 아니오 |
| openvino-emotions-retail-0003 | `happy` | `happy_like` | 원본 5-class 이름에 `_like`만 부여 | 중간 | 아니오 |
| openvino-emotions-retail-0003 | `sad` | `sad_like` | 원본 5-class 이름에 `_like`만 부여 | 중간 | 아니오 |
| openvino-emotions-retail-0003 | `surprise` | `surprise_like` | 원본 5-class 이름에 `_like`만 부여 | 중간 | 아니오 |
| openvino-emotions-retail-0003 | `anger` | `anger_like` | 원본 5-class 이름에 `_like`만 부여 | 중간 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Anger` | `anger_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Contempt` | `contempt_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Disgust` | `disgust_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Fear` | `fear_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Happiness` | `happiness_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Neutral` | `neutral_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Sadness` | `sadness_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |
| hsemotion-enet-b0-8-best-afew | `Surprise` | `surprise_like` | 원본 8-class 이름 보존; 추론 제외 | 높음 | 아니오 |

## 후보별 no-face·output 차이

- MediaPipe: detector와 blendshape가 결합돼 no-face를 직접 빈 결과로 표현한다.
- OpenVINO: 분류기만 있으므로 어떤 `1×3×64×64` 입력에도 5개 class score를 반환한다. detector 실패를 중립 score로 바꾸면 안 된다.
- HSEmotion: 안전 로딩 실패로 no-face와 output shape를 실제 검증하지 못했다.

## D5에서 결정할 항목

- 실제 모델과 fallback 선정
- MediaPipe 52개 신호의 채택 범위와 좌우 집계 방식
- OpenVINO 사용 시 upstream detector·invalid 처리 비용과 총지연
- 공통 taxonomy·mapping version과 미매핑 정책
- 승인된 labeled fixture에서의 품질 지표와 재평가 기준
- 목표 Vision 서버·network·동시 세션의 capture-to-result p50/p95
- HSEmotion 안전 배포 형식이 새로 제공될 때만 재진입할 조건

세부 보고서:

- [MediaPipe Face Landmarker](2026-08-15-mediapipe-face-landmarker.md)
- [OpenVINO emotions-recognition-retail-0003](2026-08-15-openvino-emotions-retail-0003.md)
- [HSEmotion enet_b0_8_best_afew](2026-08-15-hsemotion-enet-b0-8-best-afew.md)

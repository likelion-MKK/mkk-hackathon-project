# ADR-0003 Face 모델·taxonomy·fallback 선정

- 상태: Proposed
- 작성일: 2026-08-15
- 결정 소유자: 정은미(Face)
- 공동 리뷰: 박형진(Vision Gateway·Contract), 양유상(Eye), 조윤혜(Kiosk)
- 관련 결정: `D1-05 Eye·Face 모델 실행 위치`, ADR-0001
- 관련 작업: Face D2 후보 inventory, D3 Replay 의미, D4 후보 benchmark

## 1. Context

Face Worker는 하나의 frame과 `FaceFrameContext`를 받아 Contract v1의
`ExpressionSample`을 생성해야 한다. 결과는 얼굴에서 관찰 가능한 신호이며 실제
감정, 성격 또는 구매 의도를 확정하지 않는다. no-face와 처리 실패를 정상 또는
중립 표정으로 바꾸지 않고, 원본 frame은 추론 수명 밖에 저장하지 않아야 한다.

D2는 후보의 revision·license·checksum·실행 경계를 조사했고 D4는 동일한 synthetic
입력으로 로컬 CPU 실행 가능성, 지연과 출력 안정성을 비교했다. D4에는 실제 얼굴
정답 label이 없으므로 실제 정확도나 demographic 강건성의 근거로 사용할 수 없다.

근거 문서:

- [Face D2 후보 inventory](../../experiments/face/README.md)
- [Face D4 후보 비교](../benchmarks/face/2026-08-15-candidate-comparison.md)
- [MediaPipe D4 결과](../benchmarks/face/2026-08-15-mediapipe-face-landmarker.md)
- [OpenVINO D4 결과](../benchmarks/face/2026-08-15-openvino-emotions-retail-0003.md)
- [HSEmotion D4 Gate 결과](../benchmarks/face/2026-08-15-hsemotion-enet-b0-8-best-afew.md)
- [ExpressionSample v1](../../contracts/events/expression-sample.schema.json)

## 2. 후보 결정

| 후보 | 선택 상태 | Hard Gate | detector | 출력 의미 | no-face | runtime·offline | license·checksum | 알려진 위험 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MediaPipe Face Landmarker | **1차 선택안** | pass | 포함 | 52개 blendshape 얼굴 동작 계수 | 빈 face·score로 구분 가능 | Python 3.13.15, CPU, offline pass | code·weight Apache-2.0, SHA256 고정 | 실제 얼굴 정확도·quality 기준 미검증, 감정 label이 아님 |
| OpenVINO emotions-recognition-retail-0003 | 보류, fallback 아님 | pass | 없음 | neutral/happy/sad/surprise/anger 5-class crop 분류 | 단독 구분 불가; no-face에도 score 반환 | Python 3.13.15, CPU, offline pass | code·weight Apache-2.0, XML·BIN checksum 고정 | detector 비용, 출력 의미 차이, Open Model Zoo 유지보수 위험 |
| HSEmotion enet_b0_8_best_afew | 제외 | fail | 없음 | 문서상 8-class crop 분류 | 실제 추론 미검증 | 설치·checksum pass, 추론 제외 | code·weight Apache-2.0, SHA256 고정 | `unsafe_legacy_pickle_blocked` |

MediaPipe는 D4 offline workload에서 3 FPS p95 20.222 ms, 5 FPS p95 19.651 ms로
deadline miss 없이 실행됐다. OpenVINO가 더 빨랐지만 detector가 없고 출력 의미가
감정 유사 class이므로 MediaPipe와 자동 교체 가능한 구현이 아니다. 이 수치는 로컬
synthetic inference 처리량이며 network, Gateway, 동시 세션 또는 정확도를 포함하지
않는다.

## 3. Decision

### 선택 모델

MediaPipe Face Landmarker를 D6 `SelectedFaceAdapter`의 1차 구현 대상으로 제안한다.

- source: `https://github.com/google-ai-edge/mediapipe`
- source revision: `493c90e5f3eb40b9080606964fc18528a99962f0`
- package: `mediapipe==1.0.0`
- model asset revision: `face_landmarker/float16/1`
- model URL: `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`
- model SHA256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`
- code license: Apache-2.0
- weight license: Apache-2.0, D2에서 구성 모델의 공식 model card로 확인

이 결정은 모델·taxonomy 선택안이며 deployment 승인이 아니다. ADR-0001과 후속
ADR-0002가 요구하는 개인정보, 목표 서버, network, 동시 세션과 운영 Gate는 별도로
남아 있다.

### taxonomy

taxonomy version은 `face-observable-actions-v1`이다. machine-readable 원본은
[`face-observable-actions-v1.json`](face-observable-actions-v1.json)으로 관리한다.

- MediaPipe 원본 52개 category를 누락 없이 추적한다.
- `_neutral`을 실제 neutral 감정으로 승격하지 않는다. source baseline으로만
  추적하고 `ExpressionSample.scores`에서는 제외한다.
- 나머지 원본 label은 의미를 확대하지 않고 snake_case 얼굴 동작 신호로 정규화한다.
- 좌우 신호를 그대로 보존하며 평균, 최대값 또는 합으로 자동 집계하지 않는다.
- 모든 signal은 `observable_face_action`이고 `emotion_label=false`다.
- no-face는 taxonomy score label이 아니다.
- 예상하지 못한 source label 하나는 `unknown`으로 전달하고 의미를 추측하지 않는다.
  unknown이 여러 개이거나 label 누락·중복, 비유한 score가 있으면 전체 측정을
  `malformed_output`으로 무효화한다.

ADR과 taxonomy가 Accepted되기 전에는 `status=proposed`, label `final=false`를
유지한다.

### no-face와 invalid 의미

no-face는 이벤트는 존재하지만 측정은 무효인 관측 실패다.

| 상황 | `face_detected` | `face_count` | `valid` | `scores` | `reason` |
| --- | --- | ---: | --- | --- | --- |
| no-face | false | 0 | false | `{}` | `no_face` |
| 여러 얼굴 | true | 2 이상 | false | `{}` | `multi_face` |
| 낮은 품질 | true | 1 | false | `{}` | `low_quality` |
| 추론 timeout | 관측된 값 | 관측된 값 | false | `{}` | `timeout` |
| 모델 load·runtime 불가 | false | 0 | false | `{}` | `model_unavailable` |
| label·shape·score 오류 | 관측된 값 | 관측된 값 | false | `{}` | `malformed_output` |

no-face, timeout과 실패를 이전·다음 frame의 score, neutral score 또는 0점짜리 정상
결과로 보간하지 않는다. no-face와 model unavailable의 `quality`·`confidence`는
`0.0`을 사용한다. low-quality는 실제로 계산된 정규화 값을 보존한다. valid sample의
quality·confidence 계산식과 threshold는 실제 labeled fixture 근거가 없어 아직
고정하지 않는다.

### fallback

- production에서 OpenVINO, HSEmotion, Fake 또는 Replay로 자동 전환하지 않는다.
- 모델이 없거나 실패하면 명시적인 invalid 결과와 reason을 전달한다.
- Face 결과가 없어도 Eye 처리를 막지 않으며 downstream은 유효 sample만 사용한다.
- 유효 신호가 부족하면 추천·화면 계층은 `insufficient_data` 흐름을 사용한다.
- OpenVINO는 detector 결합, 동일 labeled fixture 품질, 전체 지연과 유지보수 검토가
  승인된 별도 ADR 없이는 fallback으로 추가하지 않는다.
- HSEmotion은 안전한 순수 `state_dict`, ONNX 또는 공식 안전 loader가 고정 revision,
  license와 checksum으로 제공되기 전까지 재검토하지 않는다. `weights_only=False`로
  보안 Gate를 우회하지 않는다.

## 4. Selected Adapter 경계

### metadata

| 필드 | 고정값 |
| --- | --- |
| `adapter_id` | `mediapipe-face-landmarker-adapter` |
| `model_id` | `mediapipe-face-landmarker` |
| `model_revision` | `face-landmarker-float16-v1` |
| `taxonomy_version` | `face-observable-actions-v1` |
| `runtime` | `python-mediapipe` |
| `source_labels` | 고정 원본 52개, taxonomy JSON과 동일 순서 |

입력은 Vision Gateway가 메모리에서 decode한 frame 참조와 Kiosk 캡처 시점의 전체
`FaceFrameContext`다. 출력은 해당 context를 그대로 보존한 `ExpressionSample v1`
하나다. Contract v1, example과 일반 REST API는 변경하지 않는다.

### lifecycle

1. `metadata`는 모델 load 전에도 고정값을 반환한다.
2. `initialize`는 `.download` asset의 SHA256을 확인한 뒤에만 최종 경로로 확정하고
   모델을 load한다. 실행 중 반복 호출은 자원과 retry cache를 유지하는 no-op이다.
3. `warmup`은 ready 상태에서 synthetic 입력으로만 수행한다.
4. `infer`는 frame을 추론 중에만 사용하고 성공·실패 모두 `finally`에서 frame과
   tensor 참조를 해제한다. 원본을 cache, 예외 또는 로그에 넣지 않는다.
5. `dispose`는 반복 호출에 안전하며 모델, tensor, 파생 retry cache를 해제한다.
   dispose 후 재초기화는 새 실행으로 시작한다.

초기화 실패는 비식별 typed error와 readiness 실패로 알린다. `FaceFrameContext`가
있는 infer 실패는 Contract-valid invalid sample로 반환한다.

### event ID와 retry

`event_id`는 adapter·model·taxonomy metadata와 `session_id`, `sequence`, `frame_id`,
`captured_at_mono_ms`, `video_id`, `video_time_ms`, `playback_epoch` 전체의 결정적
hash로 만든다. 동일 context 재호출은 파생 `ExpressionSample` cache를 재사용해 같은
payload와 event ID를 반환하며 모델을 다시 실행하지 않는다. cache에는 frame이나
tensor를 저장하지 않고 session 종료·dispose 때 비운다. downstream은 event ID로
재전송을 중복 제거한다.

## 5. 관찰 가능성과 보안

- 모델 load·warmup·infer latency와 timeout 수를 구분해 기록한다.
- `reason`별 실패 수, no-face 비율과 전체 invalid 비율을 집계한다.
- Gateway에서 capture-to-result p50/p95, drop과 worker restart를 별도로 측정한다.
- log·metric에는 frame, score payload, image bytes, base64, embedding, token, 원문
  session ID와 파일 경로를 넣지 않는다.
- immutable URL과 SHA256을 load 전에 검증하고 mismatch asset은 모델 library에
  전달하지 않는다.
- weight는 ignored `models/`, raw 검증 결과는 ignored `artifacts/`에만 둔다.
- 외부 API나 제3자 서비스로 frame을 전송하지 않는다.

## 6. Consequences와 대안

### 긍정적 결과

- detector와 얼굴 동작 신호가 한 runtime에 있어 no-face 의미가 D3와 일치한다.
- offline CPU 실행과 asset 무결성을 재현할 수 있다.
- 감정 분류를 주장하지 않는 관찰 신호로 Contract v1을 유지한다.

### 비용과 제한

- OpenVINO보다 D4 synthetic 지연이 크다.
- 52개 신호를 소비자가 직접 감정으로 해석하지 않도록 taxonomy 통제가 필요하다.
- 실제 얼굴 품질, quality·confidence 계산과 목표 서버 운영 성능이 미검증이다.

### 기각·보류한 대안

- **OpenVINO 1차 선택/자동 fallback:** 빠르지만 detector가 없고 출력 의미가 달라
  조용한 대체가 불가능하다.
- **HSEmotion:** unsafe legacy pickle Hard Gate를 통과하지 못했다.
- **모델 실패 시 Fake/Replay:** 고객에게 가짜 분석을 제시하므로 개발·CI 전용이다.
- **blendshape를 감정으로 변환:** labeled 품질 근거가 없어 선택하지 않는다.

## 7. Rollout Gate와 rollback

ADR을 Accepted로 바꾸고 production-ready로 표시하려면 다음을 모두 충족해야 한다.

- 승인된 비고객 labeled fixture에서 각도, 조명, 거리, 안경, 가림과 demographic
  조건별 valid·no-face·false-positive와 재검출을 측정한다.
- valid `quality`·`confidence` 계산식, low-quality threshold와 timeout budget을
  근거와 함께 고정한다.
- 목표 서버와 network에서 encode·upload·queue·infer·return을 포함한
  capture-to-result p50/p95, 3/5 FPS, drop, RAM과 10분 이상 안정성을 통과한다.
- 동시 세션 수와 worker restart·network 단절 회복을 검증한다.
- ADR-0001 개인정보·WSS Gate와 ADR-0002 서버·운영 Gate가 승인된다.
- proxy, Gateway, Worker, APM, 파일, DB, cache와 artifact에 frame이 남지 않음을
  확인한다.

운영 회귀 시 이전 미승인 모델로 전환하지 않는다. Face feature flag를 끄고 worker를
unready로 만들며 `model_unavailable` 또는 상위 `insufficient_data`로 종료한다. 이미
승인된 이전 MediaPipe asset revision이 생긴 뒤에는 checksum·taxonomy 호환성과
rollback owner가 기록된 경우에만 그 revision으로 되돌린다.

## 8. D6 handoff와 미검증 항목

D6는 이 ADR이 승인된 뒤 selected 슬롯 내부에 MediaPipe runtime, 전처리, strict
output validation, taxonomy mapping, lifecycle와 derived retry cache를 구현한다.
모델 weight와 원본 fixture는 커밋하지 않는다. OpenVINO 조합, Vision Stream,
Gateway, 카메라와 deployment는 별도 책임이다.

아직 검증되지 않은 항목:

- 실제 얼굴에서의 action 품질과 정확도
- demographic·조명·각도·거리·안경·가림 조건
- valid quality·confidence 공식과 threshold
- 목표 서버·network 포함 capture-to-result와 timeout 수치
- 동시 세션, 장시간 안정성, worker restart 후 복구
- 실제 labeled fixture와 consumer 유용성

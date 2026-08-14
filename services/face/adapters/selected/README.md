# Selected Face Adapter

## 상태

[`ADR-0003`](../../../../docs/adr/0003-face-model-taxonomy-fallback.md)의
`Proposed` 결정을 D6에서 구현할 production 연결 슬롯이다. 팀 승인 전에는
production-ready 또는 Accepted로 표시하지 않으며 실제 모델 코드나 weight를 이
문서 PR에 포함하지 않는다.

## D6 구현 대상

1차 선택안은 MediaPipe Face Landmarker다.

| 항목 | 고정값 |
| --- | --- |
| package | `mediapipe==1.0.0` |
| source revision | `493c90e5f3eb40b9080606964fc18528a99962f0` |
| asset revision | `face_landmarker/float16/1` |
| asset SHA256 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| `adapter_id` | `mediapipe-face-landmarker-adapter` |
| `model_id` | `mediapipe-face-landmarker` |
| `model_revision` | `face-landmarker-float16-v1` |
| `taxonomy_version` | `face-observable-actions-v1` |
| `runtime` | `python-mediapipe` |

`source_labels`는
[`face-observable-actions-v1.json`](../../../../docs/adr/face-observable-actions-v1.json)의
52개 `source_label`을 같은 순서로 사용한다. taxonomy는 감정 분류가 아니라 관찰
가능한 얼굴 동작 신호다.

## 입력과 출력

- 입력: Vision Gateway가 메모리에서 decode한 frame 참조와 전체
  `FaceFrameContext`.
- 출력: 입력 context의 식별자·capture time·video time·playback epoch을 그대로
  보존한 Contract v1 `ExpressionSample` 하나.
- `_neutral`은 source baseline으로만 추적하고 `scores`에 넣지 않는다.
- 나머지 51개 blendshape는 taxonomy의 snake_case canonical name으로 전달한다.
- 좌우 signal을 합산하지 않는다.
- 예상하지 못한 source label 하나는 `scores.unknown`으로 의미 추론 없이 전달한다.
  복수 unknown, label 누락·중복, shape 오류와 비유한 score는
  `reason=malformed_output`인 invalid sample로 만든다.
- frame, tensor, image bytes, base64, embedding과 원본 경로는 결과·예외·로그·cache에
  포함하지 않는다.

## invalid와 fallback

| 상황 | 결과 |
| --- | --- |
| no-face | `face_detected=false`, `face_count=0`, `valid=false`, `scores={}`, `reason=no_face` |
| multi-face | `face_detected=true`, `face_count>=2`, `valid=false`, `scores={}`, `reason=multi_face` |
| low quality | 얼굴 count 보존, `valid=false`, `scores={}`, `reason=low_quality` |
| inference timeout | `valid=false`, `scores={}`, `reason=timeout` |
| asset·runtime unavailable | `valid=false`, `scores={}`, `reason=model_unavailable` |
| 잘못된 model output | `valid=false`, `scores={}`, `reason=malformed_output` |

실패를 neutral score나 이전 frame 값으로 대체하지 않는다. OpenVINO, HSEmotion,
Fake와 Replay는 production fallback이 아니다. Face가 unavailable이면 성공한 Eye
흐름은 계속하고 downstream은 유효 Face sample 부족을 `insufficient_data`로
처리한다.

## lifecycle과 retry

- `metadata`: model load 전에도 위 고정값을 반환한다.
- `initialize`: 임시 다운로드 asset의 SHA256을 모델 load 전에 확인한다. checksum이
  맞을 때만 최종 ignored `models/` 경로로 이동한다. ready 상태의 반복 호출은
  자원·cache를 유지하는 no-op이다.
- `warmup`: ready 상태에서 실행 중 생성한 synthetic 입력만 사용한다.
- `infer`: frame을 추론 중에만 사용하고 `finally`에서 frame·tensor 참조를 해제한다.
- `dispose`: 반복 호출에 안전하며 모델·buffer·파생 retry cache를 해제한다.

`event_id`는 adapter·model·taxonomy metadata와 전체 `FaceFrameContext`를 사용해
결정적으로 생성한다. 같은 context 재시도는 cache의 파생 `ExpressionSample`을
반환해 payload와 event ID를 유지하고 모델을 다시 실행하지 않는다. cache에는
frame이나 tensor를 저장하지 않으며 session 종료와 dispose 때 비운다.

## 구현 전 Gate

- ADR-0003이 Accepted되어야 한다.
- valid quality·confidence 계산식, low-quality threshold와 timeout 수치가 실제
  labeled fixture와 목표 서버 측정으로 고정되어야 한다.
- no-face·multi-face·unknown·malformed·timeout, retry와 dispose 오류 경로가
  Contract test를 통과해야 한다.
- 목표 server·network에서 capture-to-result p50/p95, 3/5 FPS, 장시간·동시 세션과
  worker restart를 검증해야 한다.
- 원본 frame 비저장과 log·APM·proxy 비수집 Gate를 통과해야 한다.

## 경계

모델 교체, 전처리와 label 정규화는 이 슬롯 내부에서만 일어난다. Contract,
Vision Stream, Gateway, 카메라와 추천 로직을 함께 변경하지 않는다. weight는 Git에
넣지 않고 승인된 재현 절차와 무결성 정보만 문서화한다.

# Replay Face Adapter

## 목적

승인된 파생 이벤트 fixture를 호출 순서에 따라 다시 내보내 결측·seek·replay를 포함한 통합·회귀 테스트를 결정적으로 재현한다.

## Fixture 형식

fixture root는 revision과 순서가 있는 record 배열만 가진다. 각 record에는 Face의 파생 관측값 7개만 허용한다.

```json
{
  "fixture_revision": "face-expression-replay-d3-v1",
  "records": [
    {
      "face_detected": true,
      "face_count": 1,
      "scores": {
        "smile_like": 0.72
      },
      "quality": 0.9,
      "valid": true,
      "confidence": 0.88,
      "reason": null
    }
  ]
}
```

- `fixture_revision`은 Replay metadata의 `model_revision`으로 전달한다.
- 배열 위치가 재생 순서이며 처음 보는 `FaceFrameContext`의 `infer` 한 번에 record 하나를 소비한다.
- `session_id`, `sequence`, `frame_id`, `captured_at_mono_ms`, `video_id`, `video_time_ms`, `playback_epoch`은 fixture에 넣지 않고 호출 시점의 `FaceFrameContext`에서 가져온다.
- `producer_id`, `model_revision`, `taxonomy_version`은 Adapter metadata에서 만든다.
- fixture에 없는 label이나 score를 추측하거나 중립값으로 채우지 않는다.
- root나 record의 누락·추가 필드, 빈 records와 Contract에 맞지 않는 조합은 초기 모델 실행 전에 거부한다.

## 실행과 생명주기

```python
from mcm_face import ReplayFaceAdapter


adapter = ReplayFaceAdapter.from_fixture("tests/fixtures/expression-replay.d3.json")
adapter.initialize()
adapter.warmup()
sample = adapter.infer(frame=frame_reference, context=frame_context)
adapter.dispose()
```

- `warmup`과 `infer`는 초기화 전 또는 dispose 후 호출하면 명확한 lifecycle 오류를 발생시킨다.
- 동일 context의 `infer` 재시도는 cached `ExpressionSample`을 반환한다. 같은 fixture record와 결정적인 `event_id`를 재사용하며 cursor를 추가로 소비하지 않는다.
- `event_id`는 downstream이 같은 sample의 재전송을 중복 제거하는 키다.
- 실행 중 반복 `initialize`는 안전한 no-op이며 현재 cursor와 context cache를 유지한다.
- 첫 initialize 또는 dispose 후 재초기화는 cursor를 첫 record로 되돌리고 이전 실행의 cache를 비운다.
- 마지막 record 이후 처음 보는 context에는 순환 없이 `ReplayExhaustedError`를 발생시키며, 이미 처리한 context는 같은 결과로 재시도할 수 있다.

## no-face 의미

no-face는 얼굴을 관측하지 못했다는 유효한 이벤트 기록이지만 측정 결과로는 무효다. 정상 표정, 중립 감정 또는 무관심으로 해석하지 않는다.

```json
{
  "face_detected": false,
  "face_count": 0,
  "scores": {},
  "quality": 0.22,
  "valid": false,
  "confidence": 0.18,
  "reason": "no_face"
}
```

quality와 confidence는 fixture 값을 보존하고 `ExpressionSample` 이벤트를 생략하지 않는다. 연속 no-face 전후의 정상 score를 복사하거나 보간하지 않으며, 이후 정상 record가 나오면 그 record의 score로 회복한다.

## pause·seek·replay

Replay Adapter는 영상 시각을 재계산하지 않는다. Kiosk가 pause·seek·replay를 구분해 `playback_epoch`을 증가시키면 해당 값과 캡처 순간의 `video_time_ms`를 그대로 전달한다. 따라서 seek로 `video_time_ms`가 감소해도 epoch이 변경된 정상 입력으로 보존한다.

## 개인정보와 실행 경계

- 실제 고객의 얼굴 영상·이미지·base64 fixture를 읽지 않는다.
- 원본 frame, image bytes, embedding과 원본 파일 경로를 fixture·결과·예외·로그에 저장하지 않는다.
- 전달된 frame 참조는 읽거나 보관하지 않고 capture context만 결과에 복사한다.
- 재시도 cache에는 파생 `ExpressionSample`만 저장하고 원본 frame이나 미디어는 저장하지 않는다.
- 결측 score를 중립값으로 채우거나 fixture에 없는 label을 추정하지 않는다.
- drop·timeout·순서 역전은 fixture record와 호출 순서로 명시하고 원래 capture time을 보존한다.

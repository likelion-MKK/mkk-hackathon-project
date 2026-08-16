# D8 Development Camera Vertical Slice

D8은 실제 개발 PC의 video-only OpenCV camera와 MediaPipe Face Landmarker를 D7의
in-process 이벤트·API 경계에 연결한다. production Vision Stream, 감정 판정 또는 실제
선호도 알고리즘이 아니다.

```text
OpenCV video frame
  → MediaPipe Face Landmarker
  → SelectedFaceAdapter → FaceWorker → ExpressionSample
  → D7 ReplayEyePort + ObservationJoiner + AOI mapper
  → ReactionBatch → FastAPI ingest
  → MockRecommendationEngine (mock로 명시)
```

실제 Kiosk video가 없으므로 `video_time_ms`는 요청 FPS로 만든 synthetic playback
clock이다. 실제 브라우저 재생 시각이나 capture-to-server latency 검증으로 해석하지
않는다.

## 실행

기본 API·Face 테스트는 camera extra를 설치하지 않으며 Fake/Replay를 유지한다. 실제
camera smoke만 Python `3.13.15`, 모델 asset과 camera가 있는 개발 PC에서 실행한다.

```powershell
Set-Location C:\Users\eunmi\Desktop\해커톤\mkk-hackathon-project
uv sync --project apps/api --locked --extra camera
uv run --project apps/api --extra camera python -m apps.vision_gateway.d8_live `
  --model-path experiments/face/mediapipe-face-landmarker/models/face_landmarker.task `
  --device 0 --width 640 --height 480 --fps 5 --frames 30 --timeout-ms 500
```

camera 또는 모델을 사용할 수 없으면 구조화된 fail-closed diagnostics를 출력하고
non-zero로 종료한다. 모델을 자동 download하거나 Git에 추가하지 않는다.

## Technical quality proxy

quality는 감정·반응 정확도가 아니라 기술적 signal usability다. MediaPipe가 모든
landmark에 완전한 `presence` 또는 `visibility`를 제공하면 그 평균을 우선 사용한다.
그렇지 않으면 finite `x/y/z`를 확인한 뒤 다음 값을 사용한다.

```text
min(1,
    in_frame_ratio / 0.90,
    face_bbox_width / 0.10,
    face_bbox_height / 0.10)
```

기본 low-quality threshold는 `0.80`이며 ratio와 threshold는 adapter 생성 시 변경할 수
있다. 정확히 하나의 blendshape group과 전체 source taxonomy가 없거나 score가 잘못되면
`low_quality`가 아니라 `malformed_output`이다.

## 비영속 D8 반응 taxonomy

`face-observable-actions-v1`의 51개 canonical signal은 변경하지 않는다. 다음 값은
유효한 Face·Gaze·단일 AOI 결합에서만 메모리 diagnostics로 계산한다.

- `smile_like`: 좌우 `mouth_smile` 평균
- `brow_raise_like`: `brow_inner_up`과 좌우 `brow_outer_up` 평균
- `eye_blink_like`: 좌우 `eye_blink` 평균
- `attention_like`: 단일 AOI를 가리킨 gaze confidence
- `uncertain`: `1 - min(face quality, face confidence, gaze confidence)`

이 값은 감정 label, neutral score, 선호도 또는 구매 의도가 아니다. invalid 입력에는
score를 만들지 않으며 ExpressionSample, ReactionBatch, API store와 mock 추천에 넣지
않는다.

## 단계 구분

- D6: SelectedFaceAdapter, MediaPipeBackend, FaceWorker, OpenCV Face-only smoke 기반
- D7: synthetic/replay Gateway → ReactionBatch → API → mock Top 2
- D8: 실제 개발 camera·MediaPipe를 D7 경계에 연결하고 diagnostics·cleanup 검증
- D9/운영: 실제 Eye, browser camera, WSS/TLS/auth, 실제 playback, 목표 server/network,
  장시간·동시 session, labeled 품질과 실제 선호도 알고리즘

원본 BGR frame은 Gateway pending slot에 들어가지 않는다. dispatch 때만 읽고
`EphemeralCameraFrame`이 소유하며, RGB copy와 close를 lock으로 직렬화한다. frame,
RGB, landmark와 원본 blendshape object는 로그·DB·파일·cache·queue·artifact에 쓰지
않는다.

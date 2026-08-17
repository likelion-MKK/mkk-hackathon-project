# Vision Gateway: Vision Stream v1 + D7 harness

## Current stream boundary

`server.py` provides `/vision/v1/stream`, validates a one-time token, receives the
v1 binary frame envelope, and returns only derived Eye/Face samples. When
`VISION_EYE_WORKER_URL` is configured, the encoded frame is sent once over the
private bounded loopback/container boundary to the Python 3.12 Eye worker. If
that worker is absent, timed out or not calibrated, `gaze_sample` stays `null`
with an explicit reason; no neutral coordinate or replay coordinate is created.
Calibration keeps accepting bounded browser frames while EyeTrax runs, and a
user stop cancels the in-memory calibration job instead of waiting for it.
Every Eye and Face result must repeat the original session, video, frame,
sequence, monotonic capture time, capture-time video time and playback epoch.
The Gateway drops a mismatched result and never creates an AOI or product ID.

## 브라우저 localhost Eye + Face live 개발

`local_server.py`는 개발용 local token을 유지하고, `VISION_STREAM_TOKEN_SECRET`가
설정되면 API가 발급한 signed one-time token을 검증한다. Backend token endpoint는
`/api/v1/sessions/{session_id}/vision-stream-token`이며 token은 URL·로그·파일에
기록하지 않는다.

```powershell
Set-Location apps/api
uv sync --locked
Set-Location ../..
uv run --project apps/api --with "mediapipe==1.0.0" python -m uvicorn `
  apps.vision_gateway.local_server:app --host 127.0.0.1 --port 8765
```

개발 중 local token mode는 localhost에서만 사용한다. 배포 build는 backend token
mode와 same-origin `/vision/v1/stream`을 사용한다. Domain/TLS 전에는 원격
camera E2E를 공식 acceptance로 보지 않는다.

The D7 in-process harness bounds its wait for a timed-out adapter completion.
If that bound is exceeded, `dispatch_next()` returns the fail-closed observation
while retaining `in_flight` and the frame until the adapter completion callback;
it does not wait indefinitely for a blocking adapter.

Tests inject `LocalVisionTokenIssuer` and `FakeFaceAdapter`. A real MediaPipe
worker can be injected with `selected_face_worker_factory(model_path)`. The Eye
worker uses `/srv/mcm/models/face_landmarker.task`; its browser calibration-frame
stream is implemented with bounded in-memory frames; physical camera calibration
and the real server model asset remain deployment acceptance gates.

수신 rate는 `max_fps`로 제한하고 decoder·inference deadline 초과는 terminal
`drop`으로 반환한다. timeout된 decoder 또는 Face adapter의 실제 underlying 작업이
늦게 끝나면 완료 시점까지 frame과 in-flight 상태를 유지한 뒤 닫으며, worker close는
별도 bounded cleanup으로 처리한다.

이 디렉터리는 D7 Replay E2E, D8 개발 camera smoke와 Vision Stream transport
경계를 함께 둔다. 운영 domain/TLS와 Eye calibration acceptance가 끝나기 전에는
public customer traffic에 연결하지 않는다.

## 데이터 흐름

```text
synthetic metadata / derived replay
  → InProcessVisionGateway
  → ReplayEyePort + D6 FaceWorker
  → D7 observation joiner
  → ReactionBatch
  → FastAPI TestClient
  → MockRecommendationEngine
```

- pending slot에는 `FrameEnvelope` metadata만 둔다. synthetic frame 객체는 dispatch
  순간 생성하고 `finally`에서 닫는다.
- 같은 `frame_id`를 우선 결합하고, 동일 세션·playback epoch에서 캡처 시각 차이가
  100ms 이내인 경우에만 capture-time fallback을 허용한다.
- Face invalid·timeout·model unavailable은 neutral이나 이전 결과로 대체하지 않는다.
  Eye와 ProductAttentionEvent 흐름은 계속된다.
- frame context에는 짝수 sequence를 사용하고 파생 ProductAttentionEvent에는 바로 다음
  홀수 sequence를 사용한다.
- 추천은 기존 `MockRecommendationEngine`만 사용하며 결과의 `engine_mode`는 `mock`이다.

## 실행

API 테스트 환경에서 실행한다.

```powershell
Set-Location apps/api
uv sync --locked
uv run pytest -c pyproject.toml --rootdir . ../../tests/e2e/test_d7_replay_e2e.py

Set-Location ../..
uv run --project apps/api python -m apps.vision_gateway.demo --mode synthetic
uv run --project apps/api python -m apps.vision_gateway.demo --mode replay
```

위 명령은 synthetic/replay 기본 모드이며 실제 고객 frame을 사용하지 않는다. live
카메라 모드는 별도 `.env`와 signed backend token, Eye model asset을 설정한 뒤
localhost에서 opt-in으로 검증한다.

D8의 opt-in 실제 개발 camera 경로와 quality·diagnostics 의미는
[`D8_README.md`](D8_README.md)를 따른다. D7 명령과 기본 모드는 camera extra를
요구하지 않는다.

## 현재 배포 경계

[`Vision Stream v1 계약`](../../contracts/vision-stream-v1/README.md)은 정의됐고,
binary WebSocket serialization, one-time signed auth, frame limit, in-flight/drop,
Browser `getUserMedia` frame capture, EyeTrax calibration/inference fan-out과
cleanup 경계를 구현한다. Production domain/TLS/WSS와 현장 live 검증은 별도
배포 acceptance gate다.

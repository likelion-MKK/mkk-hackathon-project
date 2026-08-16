# Vision Gateway: D7 harness + local Vision Stream v1

## Current local Face-only implementation

`server.py` now provides a localhost ASGI WebSocket at `/vision/v1/stream`.
It validates a one-time in-memory token, receives the v1 binary frame envelope,
and returns only a derived `ExpressionSample`. Until EyeTrax is connected,
`gaze_sample` is explicitly `null` with `gaze_reason=eye_not_connected`.

Tests inject `LocalVisionTokenIssuer` and `FakeFaceAdapter`. A real MediaPipe
worker can be injected with `selected_face_worker_factory(model_path)`. TLS,
the Backend token endpoint, browser `getUserMedia`, and EyeTrax fan-out remain
separate follow-up work.

수신 rate는 `max_fps`로 제한하고 decoder·inference deadline 초과는 terminal
`drop`으로 반환한다. timeout된 decoder·worker가 늦게 끝나면 그 시점까지
frame을 유지한 뒤 닫으며, worker close는 별도 bounded cleanup으로 처리한다.

이 디렉터리는 D7 Replay E2E와 D8 개발 camera smoke, localhost Face-only
Vision Stream을 위한 테스트 가능한 transport 경계다. 운영 인증·TLS와
원격 고객 frame 전송을 포함하지 않으므로 production-ready로 사용하지 않는다.

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

실제 카메라, 실제 고객 frame, MediaPipe 선택 모델, 브라우저 `getUserMedia`와 외부
네트워크를 사용하지 않는다.

D8의 opt-in 실제 개발 camera 경로와 quality·diagnostics 의미는
[`D8_README.md`](D8_README.md)를 따른다. D7 명령과 기본 모드는 camera extra를
요구하지 않는다.

## D8 경계

[`Vision Stream v1 계약`](../../contracts/vision-stream-v1/README.md)은 정의됐지만,
이 브랜치에서 개발용 binary WebSocket serialization, one-time in-memory auth,
frame limit, in-flight/drop, cleanup 경계를 구현한다. Production TLS/WSS 배포,
Backend token endpoint, Kiosk-to-server getUserMedia 연결, EyeTrax fan-out과
현장 live 검증은 별도 작업이다.

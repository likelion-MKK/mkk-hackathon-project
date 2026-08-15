# D7 In-process Vision Gateway Harness

이 디렉터리는 D7 Replay E2E를 위한 테스트 가능한 transport 경계다. 실제 WebSocket,
Vision Stream v1, 운영 인증·TLS 구현이 아니며 production-ready로 사용하지 않는다.

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

## D8 경계

Vision Stream v1 계약, binary WSS serialization, auth/origin/limit, TLS 배포,
Kiosk-to-server capture-to-result 측정, 실제 Eye Worker process와 현장 live 검증은 D8
이후 별도 작업이다.

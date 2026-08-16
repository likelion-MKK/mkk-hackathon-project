from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from apps.vision_gateway.local_server import LocalVisionGatewayApp


def make_app() -> LocalVisionGatewayApp:
    return LocalVisionGatewayApp(
        model_path=Path("experiments/face/mediapipe-face-landmarker/models/face_landmarker.task")
    )


def test_local_token_bootstrap_is_cors_scoped_and_one_time() -> None:
    app = make_app()

    with TestClient(app) as client:
        response = client.post(
            "/vision/v1/local-token",
            json={"session_id": "session-live-001", "video_id": "mcm-lookbook-live-v1"},
            headers={"Origin": "http://127.0.0.1:5173"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    token = response.json()
    assert token["protocol_version"] == "1.0"
    assert token["session_id"] == "session-live-001"
    assert token["video_id"] == "mcm-lookbook-live-v1"
    assert token["websocket_path"] == "/vision/v1/stream"
    assert len(token["stream_token"]) == 43
    assert app.token_issuer.consume(token["stream_token"]) is not None
    assert app.token_issuer.consume(token["stream_token"]) is None


def test_local_token_bootstrap_rejects_unknown_origin_and_invalid_body() -> None:
    app = make_app()

    with TestClient(app) as client:
        origin_response = client.post(
            "/vision/v1/local-token",
            json={"session_id": "session-live-001", "video_id": "mcm-lookbook-live-v1"},
            headers={"Origin": "http://evil.test"},
        )
        invalid_response = client.post(
            "/vision/v1/local-token",
            json={"session_id": "../raw", "video_id": "mcm-lookbook-live-v1"},
            headers={"Origin": "http://127.0.0.1:5173"},
        )

    assert origin_response.status_code == 403
    assert invalid_response.status_code == 400

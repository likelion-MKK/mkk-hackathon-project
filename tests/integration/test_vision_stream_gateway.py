from __future__ import annotations

import threading
from typing import Any

from mcm_face import FakeFaceAdapter, FaceWorker
from starlette.testclient import TestClient

from apps.vision_gateway.server import LocalVisionTokenIssuer, VisionStreamApp
from apps.vision_gateway.vision_stream import encode_binary_frame


def frame_metadata(
    *,
    frame_id: str = "frame-0001",
    sequence: int = 1,
    byte_length: int = 4,
) -> dict[str, object]:
    return {
        "type": "frame",
        "protocol_version": "1.0",
        "session_id": "session-local-001",
        "video_id": "mcm-lookbook-example-v1",
        "frame_id": frame_id,
        "sequence": sequence,
        "captured_at_mono_ms": float(sequence * 250),
        "video_time_ms": sequence * 250,
        "playback_epoch": 0,
        "layout": {
            "viewport_width_px": 1920,
            "viewport_height_px": 1080,
            "source_width_px": 1080,
            "source_height_px": 1920,
            "object_fit": "contain",
            "element_rect": {"x_px": 660, "y_px": 0, "width_px": 600, "height_px": 1080},
            "content_rect": {
                "x_px": 660,
                "y_px": 6.666667,
                "width_px": 600,
                "height_px": 1066.666667,
            },
        },
        "camera_frame": {
            "encoding": "image/jpeg",
            "width_px": 640,
            "height_px": 480,
            "byte_length": byte_length,
        },
    }


def hello(token: str) -> dict[str, object]:
    return {
        "type": "hello",
        "protocol_version": "1.0",
        "session_id": "session-local-001",
        "video_id": "mcm-lookbook-example-v1",
        "stream_token": token,
        "offered_frame_encodings": ["image/jpeg"],
    }


def make_app(
    decoder: Any,
    *,
    issuer: LocalVisionTokenIssuer | None = None,
) -> tuple[VisionStreamApp, LocalVisionTokenIssuer]:
    token_issuer = issuer or LocalVisionTokenIssuer()
    app = VisionStreamApp(
        token_verifier=token_issuer,
        face_worker_factory=lambda: FaceWorker(FakeFaceAdapter()),
        frame_decoder=decoder,
    )
    return app, token_issuer


def test_face_only_stream_returns_expression_and_closes_frame() -> None:
    closed: list[bool] = []

    class EphemeralTestFrame:
        def close(self) -> None:
            closed.append(True)

    def decoder(image_bytes: bytes, _metadata: object) -> EphemeralTestFrame:
        assert image_bytes == b"\xff\xd8\xff\xd9"
        return EphemeralTestFrame()

    app, issuer = make_app(decoder)
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            assert ready["limits"]["in_flight_limit"] == 1

            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "control-start-1",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True

            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            result = websocket.receive_json()
            assert result["type"] == "result"
            assert result["gaze_sample"] is None
            assert result["gaze_reason"] == "eye_not_connected"
            assert result["expression_sample"]["frame_id"] == "frame-0001"
            assert result["expression_sample"]["valid"] is True

            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            duplicate = websocket.receive_json()
            assert duplicate["type"] == "drop"
            assert duplicate["reason"] == "duplicate_frame"

            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "control-stop-1",
                    "action": "stop_session",
                }
            )
            assert websocket.receive_json()["type"] == "control_result"
            assert websocket.receive_json()["type"] == "close"

    assert closed == [True]


def test_second_frame_is_dropped_while_first_is_in_flight() -> None:
    started = threading.Event()
    release = threading.Event()
    closed: list[str] = []

    class EphemeralTestFrame:
        def __init__(self, frame_id: str) -> None:
            self.frame_id = frame_id

        def close(self) -> None:
            closed.append(self.frame_id)

    def decoder(_image_bytes: bytes, metadata: Any) -> EphemeralTestFrame:
        started.set()
        release.wait(timeout=2)
        return EphemeralTestFrame(metadata.context.frame_id)

    app, issuer = make_app(decoder)
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "control-start-2",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(
                    frame_metadata(frame_id="frame-0001", sequence=1),
                    b"\xff\xd8\xff\xd9",
                )
            )
            assert started.wait(timeout=2)
            websocket.send_bytes(
                encode_binary_frame(
                    frame_metadata(frame_id="frame-0002", sequence=2),
                    b"\xff\xd8\xff\xd9",
                )
            )
            dropped = websocket.receive_json()
            assert dropped["type"] == "drop"
            assert dropped["frame_id"] == "frame-0002"
            assert dropped["reason"] == "in_flight"
            release.set()
            assert websocket.receive_json()["type"] == "result"

    assert closed == ["frame-0001"]


def test_calibration_requires_contract_payload_and_reports_eye_boundary() -> None:
    app, issuer = make_app(lambda _image_bytes, _metadata: object())
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "calibration-invalid",
                    "action": "start_calibration",
                }
            )
            assert websocket.receive_json()["code"] == "invalid_message"
            assert websocket.receive_json()["type"] == "close"

    app, issuer = make_app(lambda _image_bytes, _metadata: object())
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]
    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "calibration-valid",
                    "action": "start_calibration",
                    "payload": {
                        "pattern_id": "nine-point-v1",
                        "points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]],
                    },
                }
            )
            result = websocket.receive_json()
            assert result == {
                "type": "control_result",
                "protocol_version": "1.0",
                "request_id": "calibration-valid",
                "action": "start_calibration",
                "valid": False,
                "reason": "eye_not_connected",
                "calibration_id": "calibration-unavailable-calibration-valid",
            }

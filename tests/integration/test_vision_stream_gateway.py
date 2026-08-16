from __future__ import annotations

from dataclasses import replace
import threading
from typing import Any

from mcm_face import FakeFaceAdapter, FaceWorker
from starlette.testclient import TestClient

from apps.vision_gateway.server import LocalVisionTokenIssuer, VisionStreamApp
from apps.vision_gateway.vision_stream import (
    VisionStreamProtocolError,
    encode_binary_frame,
)


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
    face_worker_factory: Any = None,
    **gateway_kwargs: Any,
) -> tuple[VisionStreamApp, LocalVisionTokenIssuer]:
    token_issuer = issuer or LocalVisionTokenIssuer()
    app = VisionStreamApp(
        token_verifier=token_issuer,
        face_worker_factory=face_worker_factory or (lambda: FaceWorker(FakeFaceAdapter())),
        frame_decoder=decoder,
        **gateway_kwargs,
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


def test_inference_timeout_keeps_in_flight_and_closes_frame_after_worker_returns() -> None:
    started = threading.Event()
    release = threading.Event()
    frame_closed = threading.Event()
    worker_closed = threading.Event()

    class EphemeralTestFrame:
        def close(self) -> None:
            frame_closed.set()

    class BlockingWorker:
        def __init__(self) -> None:
            self.delegate = FaceWorker(FakeFaceAdapter())

        def start(self) -> None:
            self.delegate.start()

        def process(self, frame: Any, context: Any) -> Any:
            started.set()
            release.wait(timeout=2)
            return self.delegate.process(frame, context)

        def close(self) -> None:
            worker_closed.set()
            self.delegate.close()

    worker = BlockingWorker()

    app, issuer = make_app(
        lambda _image_bytes, _metadata: EphemeralTestFrame(),
        face_worker_factory=lambda: worker,
        inference_timeout_ms=20,
        worker_cleanup_timeout_ms=500,
    )
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "timeout-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            assert started.wait(timeout=1)
            timeout = websocket.receive_json()
            assert timeout["type"] == "drop"
            assert timeout["reason"] == "inference_timeout"
            assert not frame_closed.is_set()

            websocket.send_bytes(
                encode_binary_frame(
                    frame_metadata(frame_id="frame-0002", sequence=2),
                    b"\xff\xd8\xff\xd9",
                )
            )
            assert websocket.receive_json()["reason"] == "in_flight"

            release.set()
            assert frame_closed.wait(timeout=1)
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "timeout-stop",
                    "action": "stop_session",
                }
            )
            assert websocket.receive_json()["type"] == "control_result"
            assert websocket.receive_json()["type"] == "close"

    assert worker_closed.wait(timeout=1)


def test_decoder_timeout_closes_a_late_decoded_frame() -> None:
    started = threading.Event()
    release = threading.Event()
    frame_closed = threading.Event()

    class EphemeralTestFrame:
        def close(self) -> None:
            frame_closed.set()

    def decoder(_image_bytes: bytes, _metadata: Any) -> EphemeralTestFrame:
        started.set()
        release.wait(timeout=2)
        return EphemeralTestFrame()

    app, issuer = make_app(
        decoder,
        decode_timeout_ms=20,
        worker_cleanup_timeout_ms=500,
    )
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "decode-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            assert started.wait(timeout=1)
            timeout = websocket.receive_json()
            assert timeout["type"] == "drop"
            assert timeout["reason"] == "decode_timeout"
            assert not frame_closed.is_set()

            release.set()
            assert frame_closed.wait(timeout=1)
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "decode-stop",
                    "action": "stop_session",
                }
            )
            assert websocket.receive_json()["type"] == "control_result"
            assert websocket.receive_json()["type"] == "close"


def test_worker_result_must_preserve_all_frame_context_fields() -> None:
    class ContextMismatchWorker:
        def __init__(self) -> None:
            self.delegate = FaceWorker(FakeFaceAdapter())

        def start(self) -> None:
            self.delegate.start()

        def process(self, frame: Any, context: Any) -> Any:
            observation = self.delegate.process(frame, context)
            mismatched = replace(
                observation.sample,
                video_id="wrong-video-id",
                sequence=context.sequence + 1,
                captured_at_mono_ms=context.captured_at_mono_ms + 1,
                video_time_ms=context.video_time_ms + 1,
                playback_epoch=context.playback_epoch + 1,
            )
            return replace(observation, sample=mismatched)

        def close(self) -> None:
            self.delegate.close()

    worker = ContextMismatchWorker()
    app, issuer = make_app(
        lambda _image_bytes, _metadata: object(),
        face_worker_factory=lambda: worker,
    )
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "context-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "vision_unavailable"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "context-stop",
                    "action": "stop_session",
                }
            )
            assert websocket.receive_json()["type"] == "control_result"
            assert websocket.receive_json()["type"] == "close"


def test_max_fps_is_enforced_at_frame_ingress() -> None:
    app, issuer = make_app(
        lambda _image_bytes, _metadata: object(),
        max_fps=0.01,
    )
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "rate-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            assert websocket.receive_json()["type"] == "result"
            websocket.send_bytes(
                encode_binary_frame(
                    frame_metadata(frame_id="frame-0002", sequence=2),
                    b"\xff\xd8\xff\xd9",
                )
            )
            fps_limited = websocket.receive_json()
            assert fps_limited["type"] == "drop"
            assert fps_limited["reason"] == "fps_limited"


def test_late_worker_exception_still_closes_deferred_frame() -> None:
    started = threading.Event()
    release = threading.Event()
    frame_closed = threading.Event()
    worker_closed = threading.Event()

    class EphemeralTestFrame:
        def close(self) -> None:
            frame_closed.set()

    class LateRaisingWorker:
        def start(self) -> None:
            pass

        def process(self, _frame: Any, _context: Any) -> Any:
            started.set()
            release.wait(timeout=2)
            raise RuntimeError("late worker failure")

        def close(self) -> None:
            worker_closed.set()

    worker = LateRaisingWorker()
    app, issuer = make_app(
        lambda _image_bytes, _metadata: EphemeralTestFrame(),
        face_worker_factory=lambda: worker,
        inference_timeout_ms=20,
        worker_cleanup_timeout_ms=500,
    )
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "late-error-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            assert started.wait(timeout=1)
            assert websocket.receive_json()["reason"] == "inference_timeout"
            assert not frame_closed.is_set()

            release.set()
            assert frame_closed.wait(timeout=1)
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "late-error-stop",
                    "action": "stop_session",
                }
            )
            assert websocket.receive_json()["type"] == "control_result"
            assert websocket.receive_json()["type"] == "close"

    assert worker_closed.wait(timeout=1)


def test_face_worker_internal_timeout_releases_gateway_frame_after_return() -> None:
    started = threading.Event()
    release = threading.Event()
    frame_closed = threading.Event()
    worker_closed = threading.Event()

    class BlockingAdapter:
        def __init__(self) -> None:
            self.delegate = FakeFaceAdapter()

        def metadata(self) -> Any:
            return self.delegate.metadata()

        def initialize(self) -> None:
            self.delegate.initialize()

        def warmup(self) -> None:
            self.delegate.warmup()

        def infer(self, frame: Any, context: Any) -> Any:
            started.set()
            release.wait(timeout=2)
            return self.delegate.infer(frame, context)

        def dispose(self) -> None:
            self.delegate.dispose()

    class EphemeralTestFrame:
        def close(self) -> None:
            frame_closed.set()

    class TrackingWorker:
        def __init__(self) -> None:
            self.delegate = FaceWorker(BlockingAdapter(), timeout_ms=50)

        def start(self) -> None:
            self.delegate.start()

        def process(self, frame: Any, context: Any) -> Any:
            return self.delegate.process(frame, context)

        def close(self) -> None:
            worker_closed.set()
            self.delegate.close()

    worker = TrackingWorker()
    app, issuer = make_app(
        lambda _image_bytes, _metadata: EphemeralTestFrame(),
        face_worker_factory=lambda: worker,
        inference_timeout_ms=10,
        worker_cleanup_timeout_ms=500,
    )
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "face-timeout-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            assert started.wait(timeout=1)
            assert websocket.receive_json()["reason"] == "inference_timeout"
            assert not frame_closed.is_set()

            # FaceWorker returns its own invalid timeout before the adapter's
            # blocked call is released. The Gateway must close the frame only
            # after that worker call has returned to the Gateway boundary.
            assert frame_closed.wait(timeout=1)
            release.set()
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "face-timeout-stop",
                    "action": "stop_session",
                }
            )
            assert websocket.receive_json()["type"] == "control_result"
            assert websocket.receive_json()["type"] == "close"

    assert worker_closed.wait(timeout=1)


def test_decoder_error_uses_contract_error_code() -> None:
    def decoder(_image_bytes: bytes, _metadata: Any) -> object:
        raise VisionStreamProtocolError("invalid image")

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
                    "request_id": "decoder-error-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "invalid_message"
            assert error["frame"]["frame_id"] == "frame-0001"

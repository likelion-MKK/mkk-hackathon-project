from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import asyncio
import threading
from typing import Any

from mcm_face import FakeFaceAdapter, FaceWorker
import pytest
from starlette.testclient import TestClient

from apps.vision_gateway.server import LocalVisionTokenIssuer, VisionStreamApp
from apps.vision_gateway.eye_client import EyeInferenceResult
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


def test_gaze_only_stream_skips_face_decode_and_marks_expression_not_observed() -> None:
    decode_calls: list[bytes] = []

    class GazeOnlyEyeWorker:
        async def start_calibration(self, **_: object) -> tuple[bool, str | None]:
            return True, None

        async def infer(self, frame: Any) -> EyeInferenceResult:
            context = frame.metadata.context
            return EyeInferenceResult(
                {
                    "schema_version": "1.0",
                    "session_id": context.session_id,
                    "event_id": f"gaze-{context.frame_id}",
                    "sequence": context.sequence,
                    "frame_id": context.frame_id,
                    "captured_at_mono_ms": context.captured_at_mono_ms,
                    "video_id": context.video_id,
                    "video_time_ms": context.video_time_ms,
                    "playback_epoch": context.playback_epoch,
                    "producer_id": "eye-gaze-only-test",
                    "model_revision": "eye-gaze-only-v1",
                    "calibration_id": "calibration-gaze-only-v1",
                    "valid": True,
                    "confidence": 0.9,
                    "reason": None,
                    "screen_x_norm": 0.25,
                    "screen_y_norm": 0.5,
                },
                None,
            )

        async def close(self) -> None:
            return None

    def decoder(image_bytes: bytes, _metadata: object) -> object:
        decode_calls.append(image_bytes)
        raise AssertionError("gaze-only mode must not decode a Face frame")

    issuer = LocalVisionTokenIssuer()
    app = VisionStreamApp(
        token_verifier=issuer,
        face_worker_factory=None,
        frame_decoder=decoder,
        eye_worker=GazeOnlyEyeWorker(),
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
                    "request_id": "gaze-only-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            result = websocket.receive_json()
            assert result["type"] == "result"
            assert result["gaze_sample"]["frame_id"] == "frame-0001"
            assert result["gaze_reason"] is None
            assert result["expression_sample"] is None
            assert result["expression_reason"] == "not_observed"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "gaze-only-stop",
                    "action": "stop_session",
                }
            )
            assert websocket.receive_json()["type"] == "control_result"
            assert websocket.receive_json()["type"] == "close"

    assert decode_calls == []


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


@pytest.mark.parametrize("bad_request_id", ["bad id", "r" * 129])
def test_control_request_id_uses_contract_id_limits(bad_request_id: str) -> None:
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
                    "request_id": bad_request_id,
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["code"] == "invalid_message"
            assert websocket.receive_json()["type"] == "close"


@pytest.mark.parametrize("bad_pattern_id", ["bad pattern", "p" * 129])
def test_calibration_pattern_id_uses_contract_id_limits(bad_pattern_id: str) -> None:
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
                    "request_id": "calibration-invalid-id",
                    "action": "start_calibration",
                    "payload": {
                        "pattern_id": bad_pattern_id,
                        "points": [[0.1, 0.1]],
                    },
                }
            )
            assert websocket.receive_json()["code"] == "invalid_message"
            assert websocket.receive_json()["type"] == "close"


def test_long_request_id_keeps_generated_calibration_id_within_contract() -> None:
    app, issuer = make_app(lambda _image_bytes, _metadata: object())
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]
    request_id = "r" * 128

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": request_id,
                    "action": "start_calibration",
                    "payload": {
                        "pattern_id": "nine-point-v1",
                        "points": [[0.1, 0.1]],
                    },
                }
            )
            result = websocket.receive_json()
            assert result["type"] == "control_result"
            assert len(result["request_id"]) == 128
            assert len(result["calibration_id"]) <= 128
            assert result["calibration_id"].startswith("calibration-unavailable-")


def test_calibration_keeps_accepting_bounded_frames_until_eye_finishes() -> None:
    started = threading.Event()
    release = threading.Event()

    class DelayedEyeWorker:
        async def start_calibration(self, **_: object) -> tuple[bool, str | None]:
            started.set()
            await asyncio.to_thread(release.wait, 2)
            return True, None

        async def infer(self, _frame: object) -> EyeInferenceResult:
            return EyeInferenceResult(None, "calibration_in_progress")

        async def close(self) -> None:
            release.set()

    app, issuer = make_app(
        lambda _image_bytes, _metadata: object(),
        eye_worker=DelayedEyeWorker(),
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
                    "request_id": "calibration-stream",
                    "action": "start_calibration",
                    "payload": {
                        "pattern_id": "dense5-validation-v1",
                        "points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]],
                    },
                }
            )
            assert started.wait(timeout=1)
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(), b"\xff\xd8\xff\xd9")
            )
            frame_result = websocket.receive_json()
            assert frame_result["type"] == "result"
            assert frame_result["gaze_sample"] is None
            assert frame_result["expression_sample"] is None
            assert frame_result["expression_reason"] == "calibration_in_progress"

            release.set()
            calibration_result = websocket.receive_json()
            assert calibration_result["valid"] is True
            assert calibration_result["calibration_id"] == "calibration-calibration-stream"

            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "calibration-stream-inference",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True


def test_stop_session_cancels_in_progress_calibration() -> None:
    started = threading.Event()
    cancelled = threading.Event()

    class CancellableEyeWorker:
        async def start_calibration(self, **_: object) -> tuple[bool, str | None]:
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return True, None

        async def infer(self, _frame: object) -> EyeInferenceResult:
            return EyeInferenceResult(None, "calibration_in_progress")

        async def close(self) -> None:
            return None

    app, issuer = make_app(
        lambda _image_bytes, _metadata: object(),
        eye_worker=CancellableEyeWorker(),
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
                    "request_id": "calibration-cancel",
                    "action": "start_calibration",
                    "payload": {
                        "pattern_id": "dense5-validation-v1",
                        "points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]],
                    },
                }
            )
            assert started.wait(timeout=1)
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "calibration-cancel-stop",
                    "action": "stop_session",
                }
            )
            stop_result = websocket.receive_json()
            assert stop_result["type"] == "control_result"
            assert stop_result["request_id"] == "calibration-cancel-stop"
            assert stop_result["valid"] is True
            assert websocket.receive_json()["type"] == "close"

    assert cancelled.wait(timeout=1)


def test_oversized_frame_closes_with_contract_code_and_reason() -> None:
    app, issuer = make_app(
        lambda _image_bytes, _metadata: object(),
        max_frame_bytes=4,
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
                    "request_id": "oversized-start",
                    "action": "start_inference",
                }
            )
            assert websocket.receive_json()["valid"] is True
            websocket.send_bytes(
                encode_binary_frame(frame_metadata(byte_length=5), b"12345")
            )
            assert websocket.receive_json() == {
                "type": "close",
                "protocol_version": "1.0",
                "code": 1009,
                "reason": "frame_too_large",
                "retryable": False,
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


@pytest.mark.parametrize(
    ("field_name", "replacement_value"),
    [
        ("session_id", "session-other-001"),
        ("video_id", "wrong-video-id"),
        ("frame_id", "frame-other-001"),
        ("sequence", 2),
        ("captured_at_mono_ms", 251.0),
        ("video_time_ms", 251),
        ("playback_epoch", 1),
    ],
)
def test_face_worker_result_must_preserve_each_frame_context_field(
    field_name: str,
    replacement_value: object,
) -> None:
    class ContextMismatchWorker:
        def __init__(self) -> None:
            self.delegate = FaceWorker(FakeFaceAdapter())

        def start(self) -> None:
            self.delegate.start()

        def process(self, frame: Any, context: Any) -> Any:
            observation = self.delegate.process(frame, context)
            mismatched = replace(
                observation.sample, **{field_name: replacement_value}
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


@pytest.mark.parametrize(
    ("field_name", "replacement_value"),
    [
        ("session_id", "session-other-001"),
        ("video_id", "wrong-video-id"),
        ("frame_id", "frame-other-001"),
        ("sequence", 2),
        ("captured_at_mono_ms", 251.0),
        ("video_time_ms", 251),
        ("playback_epoch", 1),
    ],
)
def test_eye_worker_result_must_preserve_each_frame_context_field(
    field_name: str,
    replacement_value: object,
) -> None:
    class ContextMismatchEyeWorker:
        async def start_calibration(self, **_: object) -> tuple[bool, str | None]:
            return True, None

        async def infer(self, frame: Any) -> EyeInferenceResult:
            context = frame.metadata.context
            sample: dict[str, object] = {
                "schema_version": "1.0",
                "session_id": context.session_id,
                "event_id": f"gaze-{context.frame_id}",
                "sequence": context.sequence,
                "frame_id": context.frame_id,
                "captured_at_mono_ms": context.captured_at_mono_ms,
                "video_id": context.video_id,
                "video_time_ms": context.video_time_ms,
                "playback_epoch": context.playback_epoch,
                "producer_id": "eye-context-test",
                "model_revision": "eye-context-v1",
                "calibration_id": "calibration-context-v1",
                "valid": True,
                "confidence": 0.9,
                "reason": None,
                "screen_x_norm": 0.25,
                "screen_y_norm": 0.5,
            }
            sample[field_name] = replacement_value
            return EyeInferenceResult(sample, None)

        async def close(self) -> None:
            return None

    app, issuer = make_app(
        lambda _image_bytes, _metadata: object(),
        eye_worker=ContextMismatchEyeWorker(),
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
                    "request_id": "eye-context-start",
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
            assert result["gaze_reason"] == "gaze_context_mismatch"
            assert result["expression_sample"]["frame_id"] == "frame-0001"
            websocket.send_json(
                {
                    "type": "control",
                    "protocol_version": "1.0",
                    "request_id": "eye-context-stop",
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
    worker_returned = threading.Event()
    adapter_read_frame = threading.Event()
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
            frame.assert_open()
            adapter_read_frame.set()
            return self.delegate.infer(frame, context)

        def dispose(self) -> None:
            self.delegate.dispose()

    class EphemeralTestFrame:
        def assert_open(self) -> None:
            if frame_closed.is_set():
                raise RuntimeError("adapter read a closed frame")

        def close(self) -> None:
            frame_closed.set()

    class TrackingWorker:
        def __init__(self) -> None:
            self.delegate = FaceWorker(BlockingAdapter(), timeout_ms=50)

        def start(self) -> None:
            self.delegate.start()

        def process(self, frame: Any, context: Any) -> Any:
            observation = self.delegate.process(frame, context)
            worker_returned.set()
            return observation

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

            # FaceWorker may return its timeout observation while the adapter's
            # ThreadPool task is still running. The frame remains valid until
            # that underlying adapter task has actually finished reading it.
            assert worker_returned.wait(timeout=1)
            assert not frame_closed.is_set()
            websocket.send_bytes(
                encode_binary_frame(
                    frame_metadata(frame_id="frame-0002", sequence=2),
                    b"\xff\xd8\xff\xd9",
                )
            )
            in_flight = websocket.receive_json()
            assert in_flight["type"] == "drop"
            assert in_flight["reason"] == "in_flight"
            release.set()
            assert adapter_read_frame.wait(timeout=1)
            assert frame_closed.wait(timeout=1)
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


def test_hello_rejects_unknown_fields() -> None:
    app, issuer = make_app(lambda _image_bytes, _metadata: object())
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]
    payload = hello(token)
    payload["unexpected"] = True

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(payload)
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "invalid_message"
            assert websocket.receive_json()["type"] == "close"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload["layout"].update({"unexpected": True}),
        lambda payload: payload["layout"]["element_rect"].update({"unexpected": True}),
        lambda payload: payload["camera_frame"].update({"unexpected": True}),
    ],
    ids=("frame", "layout", "rect", "camera-frame"),
)
def test_frame_metadata_rejects_unknown_fields(mutate: Any) -> None:
    metadata = deepcopy(frame_metadata())
    mutate(metadata)
    app, issuer = make_app(lambda _image_bytes, _metadata: object())
    token = issuer.issue("session-local-001", "mcm-lookbook-example-v1")["stream_token"]

    with TestClient(app) as client:
        with client.websocket_connect("/vision/v1/stream") as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(encode_binary_frame(metadata, b"\xff\xd8\xff\xd9"))
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "invalid_message"
            assert websocket.receive_json()["type"] == "close"


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

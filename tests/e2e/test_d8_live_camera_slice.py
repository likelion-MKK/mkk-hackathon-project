from __future__ import annotations

import gc
import json
from pathlib import Path
from threading import Event, Thread
from time import sleep
from types import SimpleNamespace
import weakref

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.vision_gateway.d8_live import D8LiveConfig, D8LiveSessionRunner, EphemeralCameraFrame
from apps.vision_gateway.runner import HttpBackendPort
from mcm_face import (
    CameraDiagnostics,
    CameraPermissionDenied,
    CameraUnavailable,
    FaceInference,
    FaceWorker,
    SelectedFaceAdapter,
)
from mcm_face.adapters.selected import SOURCE_LABELS


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = (
    "image_bytes",
    "image_base64",
    "base64",
    "embedding",
    "file_path",
    "webcam image",
    "pixel_data",
    "landmark object",
    "model asset bytes",
)


class PixelFrame:
    pass


class FakeCamera:
    def __init__(
        self,
        *,
        open_error: Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.open_error = open_error
        self.read_error = read_error
        self.closed = False
        self.read_count = 0
        self.frame_references: list[weakref.ReferenceType[PixelFrame]] = []

    def open(self) -> CameraDiagnostics:
        if self.open_error is not None:
            raise self.open_error
        return CameraDiagnostics(0, "granted", 640, 480, 5.0, 1280, 720, 30.0)

    def read(self) -> PixelFrame:
        self.read_count += 1
        if self.read_error is not None:
            raise self.read_error
        frame = PixelFrame()
        self.frame_references.append(weakref.ref(frame))
        return frame

    def close(self) -> None:
        self.closed = True


class FaceBackend:
    def __init__(
        self,
        result: FaceInference | None = None,
        *,
        initialize_error: Exception | None = None,
        inference_error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.result = result or FaceInference(1, (blendshapes(),), 0.9)
        self.initialize_error = initialize_error
        self.inference_error = inference_error
        self.delay = delay
        self.disposed = False

    def initialize(self) -> None:
        if self.initialize_error is not None:
            raise self.initialize_error

    def infer(self, _frame: object) -> FaceInference:
        sleep(self.delay)
        if self.inference_error is not None:
            raise self.inference_error
        return self.result

    def dispose(self) -> None:
        self.disposed = True


def blendshapes() -> dict[str, float]:
    return {label: index / len(SOURCE_LABELS) for index, label in enumerate(SOURCE_LABELS)}


def worker_factory(backend: FaceBackend, *, timeout_ms: int = 50):
    return lambda: FaceWorker(SelectedFaceAdapter(backend=backend), timeout_ms=timeout_ms)


def config() -> D8LiveConfig:
    return D8LiveConfig(model_path=Path("ignored-in-injected-tests.task"), frames=2)


def make_client() -> tuple[TestClient, MemoryStore]:
    store = MemoryStore(ROOT)
    return TestClient(create_app(store)), store


def make_runner(
    client: TestClient,
    camera: FakeCamera,
    backend: FaceBackend,
    *,
    timeout_ms: int = 50,
    backend_port: HttpBackendPort | None = None,
) -> D8LiveSessionRunner:
    return D8LiveSessionRunner(
        backend=backend_port
        or HttpBackendPort(
            client,
            kiosk_id="kiosk-d8-development",
            consent_version="consent-d8-development-camera",
        ),
        config=config(),
        camera_source=camera,
        device_lister=lambda: [0],
        face_worker_factory=worker_factory(backend, timeout_ms=timeout_ms),
        clock=lambda: 123.456,
    )


def test_live_slice_reuses_d7_gateway_and_ingests_mock_recommendation() -> None:
    client, store = make_client()
    camera = FakeCamera()
    backend = FaceBackend()
    with client:
        runner = make_runner(client, camera, backend)
        session_id = runner.start()
        first, accepted = runner.process_frame(0)
        second, _ = runner.process_frame(1)
        recommendation = runner.close()

    assert accepted["status"] == "accepted"
    assert first.face.valid is True
    assert first.face.frame_id == first.gaze.frame_id == "frame-d8-00000"
    assert second.face.sequence == second.gaze.sequence == 2
    assert recommendation["engine_mode"] == "mock"
    assert [item["product_id"] for item in recommendation["items"]] == ["P001", "P002"]
    diagnostics = runner.diagnostics()
    assert diagnostics["face_mode"] == "selected_mediapipe"
    assert diagnostics["eye_mode"] == "replay"
    assert diagnostics["recommendation_mode"] == "mock"
    assert diagnostics["preference_algorithm"] == "not_configured"
    assert diagnostics["transport"] == "d8-development-in-process"
    assert diagnostics["actual_width"] == 1280
    assert diagnostics["actual_height"] == 720
    assert diagnostics["actual_fps"] == 30.0
    assert diagnostics["frames_processed"] == 2
    assert diagnostics["valid_face_ratio"] == 1.0
    assert diagnostics["processing_latency_ms_p95"] is not None
    assert camera.closed is True and backend.disposed is True
    assert store.sessions[session_id].reaction_features is None
    assert not hasattr(store.sessions[session_id], "events")
    assert "mouth_smile_left" not in repr(store.sessions[session_id])


def test_d8_taxonomy_is_derived_in_memory_only() -> None:
    client, _ = make_client()
    camera = FakeCamera()
    backend = FaceBackend()
    with client:
        runner = make_runner(client, camera, backend)
        runner.start()
        observation, _ = runner.process_frame(0)
        signals = runner.latest_reaction_signals
        assert signals is not None and signals.valid is True
        assert signals.scores["smile_like"] == pytest.approx(
            (observation.face.scores["mouth_smile_left"] + observation.face.scores["mouth_smile_right"])
            / 2
        )
        assert signals.scores["brow_raise_like"] == pytest.approx(
            (
                observation.face.scores["brow_inner_up"]
                + observation.face.scores["brow_outer_up_left"]
                + observation.face.scores["brow_outer_up_right"]
            )
            / 3
        )
        assert signals.scores["eye_blink_like"] == pytest.approx(
            (observation.face.scores["eye_blink_left"] + observation.face.scores["eye_blink_right"])
            / 2
        )
        assert signals.scores["attention_like"] == observation.gaze.confidence
        assert signals.scores["uncertain"] == pytest.approx(0.1)
        assert all("smile_like" not in repr(batch) for batch in runner.runner.batches)
        runner.cancel()


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (FaceInference(0, (), 0.0), "no_face"),
        (FaceInference(2, (blendshapes(), blendshapes()), 0.9), "multi_face"),
        (FaceInference(1, (blendshapes(),), 0.2), "low_quality"),
    ],
)
def test_invalid_face_keeps_eye_aoi_ingest_and_has_no_d8_scores(
    result: FaceInference, reason: str
) -> None:
    client, _ = make_client()
    camera = FakeCamera()
    with client:
        runner = make_runner(client, camera, FaceBackend(result))
        runner.start()
        observation, accepted = runner.process_frame(0)
        assert observation.face.reason == reason
        assert observation.gaze.valid is True
        assert accepted["status"] == "accepted"
        assert runner.latest_reaction_signals is not None
        assert runner.latest_reaction_signals.valid is False
        assert runner.latest_reaction_signals.scores == {}
        runner.cancel()


@pytest.mark.parametrize("stage", ["initialize", "infer"])
def test_model_errors_fail_closed_while_eye_ingest_continues(stage: str) -> None:
    backend = FaceBackend(
        initialize_error=RuntimeError("initialize") if stage == "initialize" else None,
        inference_error=RuntimeError("infer") if stage == "infer" else None,
    )
    client, _ = make_client()
    camera = FakeCamera()
    with client:
        runner = make_runner(client, camera, backend)
        runner.start()
        observation, accepted = runner.process_frame(0)
        assert observation.face.reason == "model_unavailable"
        assert accepted["status"] == "accepted"
        assert observation.gaze.valid is True
        runner.cancel()
    assert camera.closed is True and backend.disposed is True


def test_worker_timeout_is_counted_and_resources_are_released() -> None:
    client, _ = make_client()
    camera = FakeCamera()
    backend = FaceBackend(delay=0.03)
    with client:
        runner = make_runner(client, camera, backend, timeout_ms=1)
        runner.start()
        observation, accepted = runner.process_frame(0)
        assert observation.face.reason == "timeout"
        assert observation.gaze.valid is True
        assert accepted["status"] == "accepted"
        runner.cancel()
    assert runner.diagnostics()["timeout_count"] == 1
    assert camera.closed is True and backend.disposed is True


@pytest.mark.parametrize(
    ("error", "permission"),
    [
        (CameraPermissionDenied("secret OS detail"), "denied"),
        (CameraUnavailable("secret device detail"), "unavailable"),
    ],
)
def test_camera_open_errors_are_structured_and_release_resources(
    error: Exception, permission: str
) -> None:
    client, _ = make_client()
    camera = FakeCamera(open_error=error)
    with client:
        runner = make_runner(client, camera, FaceBackend())
        with pytest.raises(type(error)):
            runner.start()
        diagnostics = runner.diagnostics()
    assert diagnostics["permission"] == permission
    assert diagnostics["frames_processed"] == 0
    assert camera.closed is True
    assert "secret" not in json.dumps(diagnostics)


def test_camera_read_error_clears_gateway_in_flight_and_cancels_session() -> None:
    client, _ = make_client()
    camera = FakeCamera(read_error=CameraUnavailable("private read detail"))
    with client:
        runner = make_runner(client, camera, FaceBackend())
        runner.start()
        with pytest.raises(CameraUnavailable):
            runner.process_frame(0)
        assert runner.runner.gateway.public_state()["in_flight"] is False
        assert runner.runner.gateway.public_state()["state"] == "cancelled"
    assert camera.closed is True


def test_cancel_and_normal_close_both_release_camera_and_worker() -> None:
    client, _ = make_client()
    with client:
        cancel_camera = FakeCamera()
        cancel_backend = FaceBackend()
        cancelled = make_runner(client, cancel_camera, cancel_backend)
        cancelled.start()
        cancelled.cancel()
        assert cancel_camera.closed is True and cancel_backend.disposed is True

        close_camera = FakeCamera()
        close_backend = FaceBackend()
        closed = make_runner(client, close_camera, close_backend)
        closed.start()
        closed.process_frame(0)
        closed.close()
        assert close_camera.closed is True and close_backend.disposed is True


class FailingIngestPort(HttpBackendPort):
    def ingest(self, session_id: str, batch: object) -> object:
        del session_id, batch
        raise RuntimeError("private API failure")


def test_api_error_releases_frame_camera_and_worker() -> None:
    client, _ = make_client()
    camera = FakeCamera()
    backend = FaceBackend()
    with client:
        port = FailingIngestPort(client)
        runner = make_runner(client, camera, backend, backend_port=port)
        runner.start()
        with pytest.raises(RuntimeError, match="private API failure"):
            runner.process_frame(0)
    gc.collect()
    assert camera.closed is True and backend.disposed is True
    assert camera.frame_references[0]() is None


def test_ephemeral_frame_is_redacted_collected_and_close_is_idempotent() -> None:
    pixel = PixelFrame()
    pixel_reference = weakref.ref(pixel)
    frame = EphemeralCameraFrame("frame-d8-private", pixel)
    assert "PixelFrame" not in repr(frame)
    del pixel
    frame.close()
    frame.close()
    gc.collect()
    assert frame.closed is True
    assert pixel_reference() is None


def test_rgb_copy_and_timeout_close_are_serialized() -> None:
    copy_started = Event()
    allow_copy = Event()

    class View:
        def copy(self) -> object:
            copy_started.set()
            assert allow_copy.wait(timeout=1)
            return object()

    class BlockingPixels:
        def __getitem__(self, _key: object) -> View:
            return View()

    frame = EphemeralCameraFrame("frame-race", BlockingPixels())
    copied: list[object] = []
    converter = Thread(target=lambda: copied.append(frame.to_rgb_copy()))
    converter.start()
    assert copy_started.wait(timeout=1)
    closer = Thread(target=frame.close)
    closer.start()
    assert closer.is_alive()
    allow_copy.set()
    converter.join(timeout=1)
    closer.join(timeout=1)
    assert copied and frame.closed is True


def test_runtime_outputs_contain_no_media_or_model_material() -> None:
    client, store = make_client()
    camera = FakeCamera()
    with client:
        runner = make_runner(client, camera, FaceBackend())
        session_id = runner.start()
        observation, _ = runner.process_frame(0)
        diagnostics = runner.diagnostics()
        required_flag = diagnostics.pop("raw_frame_persisted")
        runtime_values = (
            observation.face.to_payload(),
            observation.gaze.to_payload(),
            diagnostics,
            repr(store.sessions[session_id]),
        )
        runner.cancel()
    assert required_flag is False
    rendered = json.dumps(runtime_values, default=str).lower()
    assert all(term not in rendered for term in FORBIDDEN)

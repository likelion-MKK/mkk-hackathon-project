from __future__ import annotations

from dataclasses import dataclass
import time

import pytest

from mcm_face import FaceInference, FaceWorker, SelectedFaceAdapter
from mcm_face.adapters.selected import SOURCE_LABELS


@dataclass(frozen=True)
class Context:
    session_id: str = "session-d6"
    sequence: int = 1
    frame_id: str = "frame-d6-0001"
    captured_at_mono_ms: float = 100.0
    video_id: str = "video-d6"
    video_time_ms: int = 90
    playback_epoch: int = 0


class Backend:
    def __init__(self, result: FaceInference | Exception, *, delay: float = 0.0) -> None:
        self.result = result
        self.delay = delay
        self.initialized = False
        self.disposed = False

    def initialize(self) -> None:
        if isinstance(self.result, RuntimeError) and str(self.result) == "initialize":
            raise self.result
        self.initialized = True

    def infer(self, frame: object) -> FaceInference:
        time.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def dispose(self) -> None:
        self.disposed = True


def blendshapes() -> dict[str, float]:
    return {label: index / len(SOURCE_LABELS) for index, label in enumerate(SOURCE_LABELS)}


def run(result: FaceInference, *, threshold: float = 0.5):
    backend = Backend(result)
    adapter = SelectedFaceAdapter(backend=backend, low_quality_threshold=threshold)
    adapter.initialize()
    return adapter.infer(object(), Context())


def test_valid_face_returns_only_canonical_derived_scores() -> None:
    sample = run(FaceInference(1, (blendshapes(),), 0.9))
    assert sample.valid is True
    assert sample.face_count == 1
    assert "mouth_smile_left" in sample.scores
    assert "_neutral" not in sample.scores
    assert sample.frame_id == Context.frame_id


@pytest.mark.parametrize(
    ("result", "reason", "count"),
    [
        (FaceInference(0, (), 0.0), "no_face", 0),
        (FaceInference(2, (blendshapes(), blendshapes()), 0.9), "multi_face", 2),
        (FaceInference(1, (blendshapes(),), 0.2), "low_quality", 1),
    ],
)
def test_fail_closed_face_states(result: FaceInference, reason: str, count: int) -> None:
    sample = run(result)
    assert sample.valid is False
    assert sample.reason == reason
    assert sample.face_count == count
    assert sample.scores == {}


def test_model_unavailable_is_not_neutral_or_mock_output() -> None:
    adapter = SelectedFaceAdapter(backend=Backend(RuntimeError("inference")))
    adapter.initialize()
    sample = adapter.infer(object(), Context())
    assert sample.reason == "model_unavailable"
    assert sample.scores == {}
    assert sample.producer_id != "mock-vision-client-face"


def test_uninitialized_adapter_fails_closed() -> None:
    sample = SelectedFaceAdapter(backend=Backend(FaceInference(0, (), 0))).infer(object(), Context())
    assert sample.reason == "model_unavailable"


def test_model_initialization_failure_keeps_worker_fail_closed() -> None:
    backend = Backend(RuntimeError("initialize"))
    worker = FaceWorker(SelectedFaceAdapter(backend=backend))
    worker.start()
    sample = worker.process(object(), Context()).sample
    worker.close()
    assert sample.reason == "model_unavailable"
    assert worker.error_count >= 2
    assert backend.disposed is True


def test_worker_timeout_is_explicit_and_cleanup_disposes_resources() -> None:
    backend = Backend(FaceInference(1, (blendshapes(),), 0.9), delay=0.03)
    worker = FaceWorker(SelectedFaceAdapter(backend=backend), timeout_ms=5)
    worker.start()
    sample = worker.process(object(), Context()).sample
    worker.close()
    assert sample.reason == "timeout"
    assert worker.timeout_count == 1
    assert backend.disposed is True


def test_worker_context_manager_cleans_up_after_error() -> None:
    backend = Backend(RuntimeError("inference"))
    with FaceWorker(SelectedFaceAdapter(backend=backend)) as worker:
        sample = worker.process(object(), Context()).sample
        assert sample.reason == "model_unavailable"
    assert backend.disposed is True


def test_payload_cannot_expose_frame_bytes_or_recommendation() -> None:
    sample = run(FaceInference(1, (blendshapes(),), 0.9))
    payload = sample.to_payload()
    rendered = repr(payload).lower()
    assert all(term not in rendered for term in ("raw_frame", "image_bytes", "base64", "recommendation"))

from __future__ import annotations

from dataclasses import dataclass, replace
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
        self.infer_count = 0

    def initialize(self) -> None:
        if isinstance(self.result, RuntimeError) and str(self.result) == "initialize":
            raise self.result
        self.initialized = True

    def infer(self, frame: object) -> FaceInference:
        self.infer_count += 1
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


def test_missing_landmark_quality_fails_closed() -> None:
    sample = run(FaceInference(1, (blendshapes(),), None))
    assert sample.valid is False
    assert sample.reason == "low_quality"
    assert sample.quality == 0.0
    assert sample.confidence == 0.0
    assert sample.scores == {}


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


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_same_full_context_reuses_cached_canonical_sample_without_inference() -> None:
    backend = Backend(FaceInference(1, (blendshapes(),), 0.9))
    adapter = SelectedFaceAdapter(backend=backend)
    adapter.initialize()
    first = adapter.infer(object(), Context())
    second = adapter.infer(object(), Context())
    assert second is first
    assert second.event_id == first.event_id
    assert backend.infer_count == 1


def test_every_context_field_participates_in_retry_cache_key() -> None:
    fields = {
        "session_id": "session-other",
        "sequence": 2,
        "frame_id": "frame-other",
        "captured_at_mono_ms": 101.0,
        "video_id": "video-other",
        "video_time_ms": 91,
        "playback_epoch": 1,
    }
    for field, value in fields.items():
        backend = Backend(FaceInference(1, (blendshapes(),), 0.9))
        adapter = SelectedFaceAdapter(backend=backend)
        adapter.initialize()
        adapter.infer(object(), Context())
        adapter.infer(object(), replace(Context(), **{field: value}))
        assert backend.infer_count == 2, field


def test_cache_is_bounded_and_evicts_least_recently_used_sample() -> None:
    backend = Backend(FaceInference(1, (blendshapes(),), 0.9))
    adapter = SelectedFaceAdapter(backend=backend, cache_max_entries=2)
    adapter.initialize()
    first = Context()
    second = replace(first, sequence=2, frame_id="frame-d6-0002")
    third = replace(first, sequence=3, frame_id="frame-d6-0003")
    adapter.infer(object(), first)
    adapter.infer(object(), second)
    adapter.infer(object(), first)  # first becomes most recently used
    adapter.infer(object(), third)  # second is evicted
    adapter.infer(object(), second)
    assert backend.infer_count == 4


def test_expired_cache_entry_is_removed_and_recomputed() -> None:
    clock = Clock()
    backend = Backend(FaceInference(1, (blendshapes(),), 0.9))
    adapter = SelectedFaceAdapter(backend=backend, cache_ttl_seconds=5.0, clock=clock)
    adapter.initialize()
    adapter.infer(object(), Context())
    clock.now = 104.9
    adapter.infer(object(), Context())
    clock.now = 105.0
    adapter.infer(object(), Context())
    assert backend.infer_count == 2


def test_ready_initialize_preserves_cache_but_dispose_clears_it() -> None:
    backend = Backend(FaceInference(1, (blendshapes(),), 0.9))
    adapter = SelectedFaceAdapter(backend=backend)
    adapter.initialize()
    adapter.infer(object(), Context())
    adapter.initialize()
    adapter.infer(object(), Context())
    assert backend.infer_count == 1
    adapter.dispose()
    adapter.initialize()
    adapter.infer(object(), Context())
    assert backend.infer_count == 2


def test_actual_mediapipe_landmark_with_unset_quality_is_unverified() -> None:
    mediapipe = pytest.importorskip("mediapipe")
    del mediapipe
    from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark
    from mcm_face.adapters.selected import _quality_from_landmarks

    landmark = NormalizedLandmark(x=0.1, y=0.2, z=0.3)
    assert landmark.presence is None
    assert landmark.visibility is None
    assert _quality_from_landmarks(((landmark,),), face_count=1) is None


def test_quality_requires_a_complete_supported_landmark_channel() -> None:
    from types import SimpleNamespace
    from mcm_face.adapters.selected import _quality_from_landmarks

    partial = (
        SimpleNamespace(presence=0.9, visibility=None),
        SimpleNamespace(presence=None, visibility=None),
    )
    complete = (
        SimpleNamespace(presence=0.8, visibility=None),
        SimpleNamespace(presence=1.0, visibility=None),
    )
    assert _quality_from_landmarks((partial,), face_count=1) is None
    assert _quality_from_landmarks((complete,), face_count=1) == pytest.approx(0.9)

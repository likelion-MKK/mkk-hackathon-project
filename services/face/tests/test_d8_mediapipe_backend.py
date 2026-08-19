from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from mcm_face import FaceInference, SelectedFaceAdapter
from mcm_face.adapters import selected
from mcm_face.adapters.selected import MediaPipeBackend, SOURCE_LABELS, _quality_from_landmarks


class FakeLandmarker:
    created_options: object | None = None
    closed = False

    @classmethod
    def create_from_options(cls, options: object) -> "FakeLandmarker":
        cls.created_options = options
        return cls()

    def close(self) -> None:
        type(self).closed = True


def fake_mediapipe() -> object:
    class BaseOptions:
        def __init__(self, *, model_asset_buffer: bytes) -> None:
            self.model_asset_buffer = model_asset_buffer

    class Options:
        def __init__(self, **values: object) -> None:
            self.__dict__.update(values)

    return SimpleNamespace(
        tasks=SimpleNamespace(
            BaseOptions=BaseOptions,
            vision=SimpleNamespace(
                FaceLandmarkerOptions=Options,
                RunningMode=SimpleNamespace(IMAGE="IMAGE"),
                FaceLandmarker=FakeLandmarker,
            ),
        )
    )


def test_mediapipe_initialization_uses_pinned_d8_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_bytes = b"d8-test-model-not-a-real-weight"
    model_path = tmp_path / "face_landmarker.task"
    model_path.write_bytes(model_bytes)
    FakeLandmarker.created_options = None
    FakeLandmarker.closed = False
    monkeypatch.setitem(sys.modules, "mediapipe", fake_mediapipe())
    monkeypatch.setattr(selected, "MODEL_SHA256", hashlib.sha256(model_bytes).hexdigest())

    backend = MediaPipeBackend(model_path)
    backend.initialize()

    options = FakeLandmarker.created_options
    assert options is not None
    assert options.num_faces == 2
    assert options.output_face_blendshapes is True
    assert options.running_mode == "IMAGE"
    assert options.base_options.model_asset_buffer == model_bytes
    backend.dispose()
    assert FakeLandmarker.closed is True


@pytest.mark.parametrize("asset", ["missing", "checksum_mismatch"])
def test_bad_model_asset_never_creates_landmarker(
    asset: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "face_landmarker.task"
    if asset == "checksum_mismatch":
        model_path.write_bytes(b"wrong")
    FakeLandmarker.created_options = None
    monkeypatch.setitem(sys.modules, "mediapipe", fake_mediapipe())

    with pytest.raises(RuntimeError, match="unavailable|checksum mismatch"):
        MediaPipeBackend(model_path).initialize()
    assert FakeLandmarker.created_options is None


def point(
    x: float,
    y: float,
    z: float = 0.0,
    *,
    presence: float | None = None,
    visibility: float | None = None,
) -> object:
    return SimpleNamespace(
        x=x,
        y=y,
        z=z,
        presence=presence,
        visibility=visibility,
    )


def test_technical_quality_proxy_formula_and_boundary() -> None:
    full = ((point(0.40, 0.40), point(0.60, 0.60)),)
    boundary = ((point(0.46, 0.46), point(0.54, 0.54)),)
    assert _quality_from_landmarks(full, face_count=1) == 1.0
    assert _quality_from_landmarks(boundary, face_count=1) == pytest.approx(0.8)


def test_nonfinite_landmark_fails_technical_quality_proxy() -> None:
    landmarks = ((point(float("nan"), 0.4), point(0.6, 0.6)),)
    assert _quality_from_landmarks(landmarks, face_count=1) == 0.0


def test_complete_presence_channel_takes_precedence_over_geometry_proxy() -> None:
    landmarks = (
        (
            point(0.50, 0.50, presence=0.6),
            point(0.51, 0.51, presence=0.8),
        ),
    )
    assert _quality_from_landmarks(landmarks, face_count=1) == pytest.approx(0.7)


class Backend:
    def __init__(self, result: FaceInference) -> None:
        self.result = result

    def initialize(self) -> None: ...
    def infer(self, _frame: object) -> FaceInference:
        return self.result
    def dispose(self) -> None: ...


def test_incomplete_source_taxonomy_is_malformed_before_quality() -> None:
    values = {label: 0.5 for label in SOURCE_LABELS}
    del values["eyeBlinkLeft"]
    adapter = SelectedFaceAdapter(backend=Backend(FaceInference(1, (values,), 0.9)))
    adapter.initialize()
    context = SimpleNamespace(
        session_id="session-d8",
        sequence=0,
        frame_id="frame-d8",
        captured_at_mono_ms=1.0,
        video_id="video-d8",
        video_time_ms=0,
        playback_epoch=0,
    )
    sample = adapter.infer(object(), context)
    assert sample.reason == "malformed_output"
    assert sample.scores == {}

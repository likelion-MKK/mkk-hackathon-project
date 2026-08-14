from __future__ import annotations

import gc
import hashlib
import io
import json
import weakref
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import numpy as np
import pytest

import mcm_eye.adapters.eyetrax as eyetrax_module
from mcm_eye.adapters.eyetrax import (
    CalibrationCancelled,
    CalibrationCapture,
    CalibrationPhase,
    EyeTraxAdapter,
    EyeTraxConfig,
    EyeTraxModelError,
    prepare_face_model,
)
from mcm_eye.contracts import AdapterStateError, CalibrationRequest

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class FrameContext:
    session_id: str = "session-eyetrax-test"
    sequence: int = 7
    frame_id: str = "frame-00000007"
    captured_at_mono_ms: float = 1234.5
    video_id: str = "mcm-lookbook-example-v1"
    video_time_ms: int = 4200
    playback_epoch: int = 0


class IdentityRidge:
    def __init__(self, alpha: float) -> None:
        self.alpha = alpha
        self.train_features: np.ndarray | None = None
        self.train_targets: np.ndarray | None = None

    def train(self, features: np.ndarray, targets: np.ndarray) -> None:
        self.train_features = np.asarray(features).copy()
        self.train_targets = np.asarray(targets).copy()

    def predict(self, features: np.ndarray) -> np.ndarray:
        values = np.asarray(features, dtype=np.float64)
        return values[:, :2]


class FakeEstimator:
    def __init__(self) -> None:
        self.model: IdentityRidge = IdentityRidge(1.0)
        self.extract_calls = 0
        self.close_calls = 0

    def extract_features(self, image: np.ndarray):
        self.extract_calls += 1
        if not np.any(image):
            return None, False
        flag = int(image[0, 0, 2])
        if flag == 1:
            return None, False
        features = np.asarray(
            [float(image[0, 0, 0]), float(image[0, 0, 1])],
            dtype=np.float64,
        )
        if flag == 3:
            features[0] = np.nan
        return features, flag == 2

    def train(self, features: np.ndarray, targets: np.ndarray) -> None:
        self.model.train(features, targets)

    def predict(self, features: np.ndarray) -> np.ndarray:
        return self.model.predict(features)

    def close(self) -> None:
        self.close_calls += 1


class FixedCalibrationSource:
    def __init__(
        self,
        *,
        training_counts: dict[int, int] | None = None,
        validation_shift_px: dict[int, int] | None = None,
        validation_invalid_frames: int = 0,
    ) -> None:
        self.training_counts = training_counts or {1: 15, 2: 15}
        self.validation_shift_px = validation_shift_px or {1: 0, 2: 0}
        self.validation_invalid_frames = validation_invalid_frames
        self.calls: list[CalibrationCapture] = []

    def __call__(self, capture: CalibrationCapture):
        self.calls.append(capture)
        if capture.phase is CalibrationPhase.TRAINING:
            count = self.training_counts[capture.attempt]
            shift = 0
        else:
            count = 20
            shift = self.validation_shift_px[capture.attempt]
        x = int(capture.target_x_norm * 100) + shift
        y = int(capture.target_y_norm * 100)
        for index in range(count):
            flag = 1 if capture.phase is CalibrationPhase.VALIDATION and index < self.validation_invalid_frames else 0
            yield make_frame(x, y, flag)


def make_frame(x: int, y: int, flag: int = 0) -> np.ndarray:
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    frame[0, 0] = (x, y, flag)
    return frame


@pytest.fixture(autouse=True)
def fake_ridge_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        eyetrax_module,
        "_create_ridge_model",
        lambda alpha: IdentityRidge(alpha),
    )


def model_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, unicode: bool = False) -> Path:
    directory = tmp_path / ("모델" if unicode else "model")
    directory.mkdir(parents=True)
    path = directory / "face_landmarker.task"
    data = b"pinned-face-landmarker-test"
    path.write_bytes(data)
    monkeypatch.setattr(
        eyetrax_module,
        "FACE_MODEL_SHA256",
        hashlib.sha256(data).hexdigest(),
    )
    return path


def initialized_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: FixedCalibrationSource,
):
    path = model_file(tmp_path, monkeypatch)
    estimator = FakeEstimator()
    native_paths: list[Path] = []

    def factory(native_path: Path):
        native_paths.append(native_path)
        return estimator

    adapter = EyeTraxAdapter(
        EyeTraxConfig(100, 100, path),
        source,
        estimator_factory=factory,
    )
    adapter.initialize()
    adapter.warmup()
    return adapter, estimator, native_paths


def calibrate(adapter: EyeTraxAdapter, calibration_id: str = "calibration-test"):
    return adapter.calibrate(CalibrationRequest(calibration_id))


def test_initialize_and_warmup_are_separate_and_dispose_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = FixedCalibrationSource()
    path = model_file(tmp_path, monkeypatch)
    estimator = FakeEstimator()
    adapter = EyeTraxAdapter(
        EyeTraxConfig(100, 100, path),
        source,
        estimator_factory=lambda _path: estimator,
    )

    adapter.initialize()
    assert estimator.extract_calls == 0
    adapter.warmup()
    assert estimator.extract_calls == 1  # black-frame no_face is a successful warmup
    adapter.dispose()
    adapter.dispose()
    assert estimator.close_calls == 1
    assert path.exists()


def test_non_ascii_model_is_copied_to_ascii_until_dispose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = model_file(tmp_path, monkeypatch, unicode=True)
    estimator = FakeEstimator()
    native_paths: list[Path] = []
    adapter = EyeTraxAdapter(
        EyeTraxConfig(100, 100, path),
        FixedCalibrationSource(),
        estimator_factory=lambda native_path: native_paths.append(native_path) or estimator,
    )

    adapter.initialize()
    assert len(native_paths) == 1
    runtime_path = native_paths[0]
    assert runtime_path != path
    assert str(runtime_path).isascii()
    assert runtime_path.exists()
    adapter.dispose()

    assert path.exists()
    assert not runtime_path.exists()


def test_warmup_failure_closes_estimator_and_removes_owned_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = model_file(tmp_path, monkeypatch, unicode=True)

    class FailingEstimator(FakeEstimator):
        def extract_features(self, _image: np.ndarray):
            raise RuntimeError("native warmup failed")

    estimator = FailingEstimator()
    native_paths: list[Path] = []
    adapter = EyeTraxAdapter(
        EyeTraxConfig(100, 100, path),
        FixedCalibrationSource(),
        estimator_factory=lambda native_path: native_paths.append(native_path) or estimator,
    )
    adapter.initialize()

    with pytest.raises(RuntimeError, match="warmup failed"):
        adapter.warmup()
    assert estimator.close_calls == 1
    assert not native_paths[0].exists()
    assert path.exists()


def test_checksum_mismatch_stops_before_estimator_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "face_landmarker.task"
    path.write_bytes(b"wrong")
    monkeypatch.setattr(eyetrax_module, "FACE_MODEL_SHA256", "0" * 64)
    factory_called = False

    def factory(_path: Path):
        nonlocal factory_called
        factory_called = True
        return FakeEstimator()

    adapter = EyeTraxAdapter(
        EyeTraxConfig(100, 100, path),
        FixedCalibrationSource(),
        estimator_factory=factory,
    )

    with pytest.raises(EyeTraxModelError, match="checksum mismatch"):
        adapter.initialize()
    assert factory_called is False


def test_model_download_verifies_before_atomic_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"downloaded-pinned-model"
    monkeypatch.setattr(
        eyetrax_module,
        "FACE_MODEL_SHA256",
        hashlib.sha256(data).hexdigest(),
    )

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(
        eyetrax_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(data),
    )
    destination = tmp_path / "cache" / "face_landmarker.task"

    assert prepare_face_model(destination) == destination.resolve()
    assert destination.read_bytes() == data
    assert not list(destination.parent.glob("*.tmp"))


def test_offline_prepare_requires_existing_model(tmp_path: Path) -> None:
    with pytest.raises(EyeTraxModelError, match="offline mode"):
        prepare_face_model(tmp_path / "missing.task", offline=True)


def test_infer_before_calibration_request_is_lifecycle_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    try:
        with pytest.raises(AdapterStateError, match="calibrated before inference"):
            adapter.infer(make_frame(50, 50), FrameContext())
    finally:
        adapter.dispose()


def test_dense5_training_excludes_validation_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = FixedCalibrationSource()
    adapter, estimator, _ = initialized_adapter(tmp_path, monkeypatch, source)
    try:
        result = calibrate(adapter)
        assert result.valid is True
        assert estimator.model.train_targets is not None
        assert len(estimator.model.train_targets) == 25 * 15
        training_targets = {tuple(value) for value in estimator.model.train_targets.tolist()}
        assert (20.0, 70.0) not in training_targets
        assert sum(call.phase is CalibrationPhase.VALIDATION for call in source.calls) == 8
    finally:
        adapter.dispose()


def test_insufficient_training_retries_the_full_calibration_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = FixedCalibrationSource(training_counts={1: 14, 2: 15})
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, source)
    try:
        result = calibrate(adapter)
        assert result.valid is True
        assert sum(call.attempt == 1 for call in source.calls) == 25
        assert sum(call.attempt == 2 for call in source.calls) == 33
    finally:
        adapter.dispose()


def test_quality_gate_failure_retries_once_then_returns_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = FixedCalibrationSource(validation_shift_px={1: 15, 2: 15})
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, source)
    try:
        result = calibrate(adapter)
        assert result.valid is False
        assert result.reason == "quality_gate_failed"
        assert sum(call.attempt == 1 for call in source.calls) == 33
        assert sum(call.attempt == 2 for call in source.calls) == 33
        unavailable = adapter.infer(make_frame(50, 50), FrameContext())
        assert unavailable.valid is False
        assert unavailable.reason == "gaze_unavailable"
        assert unavailable.calibration_id == "calibration-test"
    finally:
        adapter.dispose()


def test_participant_cancel_does_not_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[CalibrationCapture] = []

    def cancelled_source(capture: CalibrationCapture):
        calls.append(capture)
        raise CalibrationCancelled("cancelled")
        yield make_frame(10, 10)  # pragma: no cover

    path = model_file(tmp_path, monkeypatch)
    estimator = FakeEstimator()
    adapter = EyeTraxAdapter(
        EyeTraxConfig(100, 100, path),
        cancelled_source,
        estimator_factory=lambda _path: estimator,
    )
    adapter.initialize()
    adapter.warmup()
    try:
        result = calibrate(adapter)
        assert result.valid is False
        assert result.reason == "calibration_cancelled"
        assert len(calls) == 1
    finally:
        adapter.dispose()


def test_simple_percentile_gate_includes_boundary_and_rejects_larger_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passing = FixedCalibrationSource(validation_shift_px={1: 14, 2: 14})
    adapter, _, _ = initialized_adapter(tmp_path / "pass", monkeypatch, passing)
    try:
        assert calibrate(adapter).valid is True
    finally:
        adapter.dispose()

    failing = FixedCalibrationSource(validation_shift_px={1: 15, 2: 15})
    adapter, _, _ = initialized_adapter(tmp_path / "fail", monkeypatch, failing)
    try:
        assert calibrate(adapter).valid is False
    finally:
        adapter.dispose()


def test_valid_ratio_counts_no_face_frames_as_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passing = FixedCalibrationSource(validation_invalid_frames=2)
    adapter, _, _ = initialized_adapter(tmp_path / "pass", monkeypatch, passing)
    try:
        assert calibrate(adapter).valid is True  # exactly 90 percent valid
    finally:
        adapter.dispose()

    failing = FixedCalibrationSource(validation_invalid_frames=3)
    adapter, _, _ = initialized_adapter(tmp_path / "fail", monkeypatch, failing)
    try:
        result = calibrate(adapter)
        assert result.valid is False
        assert result.reason == "quality_gate_failed"
    finally:
        adapter.dispose()


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (make_frame(50, 50, 1), "no_face"),
        (make_frame(50, 50, 2), "blink"),
        (make_frame(120, 50), "outside_viewport"),
        (make_frame(50, 50, 3), "invalid_prediction"),
    ],
)
def test_inference_maps_invalid_results_without_coordinates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frame: np.ndarray,
    reason: str,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    try:
        assert calibrate(adapter).valid is True
        sample = adapter.infer(frame, FrameContext())
        assert sample.valid is False
        assert sample.confidence == 0.0
        assert sample.reason == reason
        assert sample.screen_x_norm is None
        assert sample.screen_y_norm is None
    finally:
        adapter.dispose()


def test_valid_inference_preserves_context_and_matches_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    context = FrameContext()
    try:
        assert calibrate(adapter).valid is True
        sample = adapter.infer(make_frame(25, 75), context)
        duplicate = adapter.infer(make_frame(25, 75), context)
        assert sample.valid is True
        assert sample.confidence == 1.0
        assert sample.screen_x_norm == 0.25
        assert sample.screen_y_norm == 0.75
        assert sample.frame_id == context.frame_id
        assert sample.captured_at_mono_ms == context.captured_at_mono_ms
        assert sample.video_time_ms == context.video_time_ms
        assert sample.event_id == duplicate.event_id

        schema = json.loads(
            (REPO_ROOT / "contracts" / "events" / "gaze-sample.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.validate(sample.to_payload(), schema)
    finally:
        adapter.dispose()


def test_recalibration_changes_event_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    context = FrameContext()
    try:
        assert calibrate(adapter, "calibration-one").valid is True
        first = adapter.infer(make_frame(50, 50), context)
        assert calibrate(adapter, "calibration-two").valid is True
        second = adapter.infer(make_frame(50, 50), context)
        assert first.event_id != second.event_id
        assert second.calibration_id == "calibration-two"
    finally:
        adapter.dispose()


def test_frame_is_not_retained_or_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    try:
        assert calibrate(adapter).valid is True
        frame = make_frame(50, 50)
        frame_reference = weakref.ref(frame)
        payload = adapter.infer(frame, FrameContext()).to_payload()
        del frame
        gc.collect()
        assert frame_reference() is None
        assert all(key not in payload for key in ("frame", "image", "base64", "embedding"))
        assert caplog.records == []
    finally:
        adapter.dispose()


def test_invalid_frame_error_does_not_include_frame_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    try:
        assert calibrate(adapter).valid is True
        with pytest.raises(ValueError) as error:
            adapter.infer(np.asarray([[123456]], dtype=np.int64), FrameContext())
        assert "123456" not in str(error.value)
        assert "dtype=int64" in str(error.value)
    finally:
        adapter.dispose()

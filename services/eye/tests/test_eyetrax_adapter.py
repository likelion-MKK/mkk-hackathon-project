from __future__ import annotations

import gc
import hashlib
import io
import json
import weakref
from dataclasses import dataclass, replace
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
    GazeAbObservation,
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
        validation_counts_by_point: dict[tuple[int, int], int] | None = None,
    ) -> None:
        self.training_counts = training_counts or {1: 15, 2: 15}
        self.validation_shift_px = validation_shift_px or {1: 0, 2: 0}
        self.validation_invalid_frames = validation_invalid_frames
        self.validation_counts_by_point = validation_counts_by_point or {}
        self.calls: list[CalibrationCapture] = []

    def __call__(self, capture: CalibrationCapture):
        self.calls.append(capture)
        if capture.phase is CalibrationPhase.TRAINING:
            count = self.training_counts[capture.attempt]
            shift = 0
        else:
            count = self.validation_counts_by_point.get(
                (capture.attempt, capture.point_index),
                20,
            )
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
    *,
    smoothing_mode: str = "kalman_ema",
    observation_sink=None,
):
    path = model_file(tmp_path, monkeypatch)
    estimator = FakeEstimator()
    native_paths: list[Path] = []

    def factory(native_path: Path):
        native_paths.append(native_path)
        return estimator

    adapter = EyeTraxAdapter(
        EyeTraxConfig(100, 100, path, smoothing_mode=smoothing_mode),
        source,
        estimator_factory=factory,
        observation_sink=observation_sink,
    )
    adapter.initialize()
    adapter.warmup()
    return adapter, estimator, native_paths


def calibrate(adapter: EyeTraxAdapter, calibration_id: str = "calibration-test"):
    return adapter.calibrate(CalibrationRequest(calibration_id))


def test_config_defaults_and_validation(tmp_path: Path) -> None:
    config = EyeTraxConfig(100, 100, tmp_path / "model.task")
    assert config.smoothing_mode == "raw"
    assert config.ema_alpha == 0.25

    with pytest.raises(ValueError, match="smoothing_mode"):
        EyeTraxConfig(100, 100, smoothing_mode="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="fixed at 0.25"):
        EyeTraxConfig(100, 100, ema_alpha=0.5)


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


def test_missing_validation_points_retry_once_then_fail_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_counts = {
        (attempt, point_index): 20 if point_index == 1 else 0
        for attempt in (1, 2)
        for point_index in range(1, 9)
    }
    source = FixedCalibrationSource(validation_counts_by_point=validation_counts)
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, source)
    try:
        result = calibrate(adapter)
        assert result.valid is False
        assert result.reason == "quality_gate_failed"
        assert sum(call.attempt == 1 for call in source.calls) == 33
        assert sum(call.attempt == 2 for call in source.calls) == 33
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
    adapter, estimator, _ = initialized_adapter(
        tmp_path,
        monkeypatch,
        FixedCalibrationSource(),
    )
    context = FrameContext()
    try:
        assert calibrate(adapter).valid is True
        extract_calls_before_inference = estimator.extract_calls
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
        assert duplicate is sample
        assert estimator.extract_calls == extract_calls_before_inference + 1

        schema = json.loads(
            (REPO_ROOT / "contracts" / "events" / "gaze-sample.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.validate(sample.to_payload(), schema)
    finally:
        adapter.dispose()


def test_raw_and_stabilized_modes_have_distinct_revisions_and_event_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, _, _ = initialized_adapter(
        tmp_path / "raw",
        monkeypatch,
        FixedCalibrationSource(),
        smoothing_mode="raw",
    )
    stabilized, _, _ = initialized_adapter(
        tmp_path / "stabilized",
        monkeypatch,
        FixedCalibrationSource(),
    )
    context = FrameContext()
    try:
        assert calibrate(raw).valid is True
        assert calibrate(stabilized).valid is True
        raw_sample = raw.infer(make_frame(25, 75), context)
        stabilized_sample = stabilized.infer(make_frame(25, 75), context)

        assert raw_sample.model_revision.endswith("+raw-v1")
        assert stabilized_sample.model_revision.endswith("+gaze-filter-v1")
        assert raw.metadata().model_revision == raw_sample.model_revision
        assert stabilized.metadata().model_revision == stabilized_sample.model_revision
        assert raw_sample.event_id != stabilized_sample.event_id
    finally:
        raw.dispose()
        stabilized.dispose()


def test_out_of_order_event_does_not_run_estimator_and_is_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, estimator, _ = initialized_adapter(
        tmp_path,
        monkeypatch,
        FixedCalibrationSource(),
    )
    try:
        assert calibrate(adapter).valid is True
        latest = replace(
            FrameContext(),
            sequence=10,
            frame_id="frame-00000010",
            captured_at_mono_ms=2000.0,
        )
        assert adapter.infer(make_frame(20, 50), latest).valid is True
        extract_calls = estimator.extract_calls

        older = replace(
            latest,
            sequence=9,
            frame_id="frame-00000009",
            captured_at_mono_ms=1900.0,
        )
        rejected = adapter.infer(make_frame(80, 50), older)
        duplicate = adapter.infer(make_frame(80, 50), older)
        assert rejected.valid is False
        assert rejected.reason == "out_of_order"
        assert duplicate is rejected
        assert estimator.extract_calls == extract_calls
    finally:
        adapter.dispose()


def test_rapid_shift_waits_for_next_valid_frame_within_120ms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    base = replace(
        FrameContext(),
        sequence=1,
        frame_id="frame-00000001",
        captured_at_mono_ms=1000.0,
    )
    try:
        assert calibrate(adapter).valid is True
        assert adapter.infer(make_frame(10, 50), base).valid is True

        candidate_context = replace(
            base,
            sequence=2,
            frame_id="frame-00000002",
            captured_at_mono_ms=1100.0,
        )
        candidate = adapter.infer(make_frame(80, 50), candidate_context)
        assert candidate.valid is False
        assert candidate.confidence == 0.0
        assert candidate.reason == "rapid_shift_pending"

        blink = adapter.infer(
            make_frame(80, 50, 2),
            replace(
                base,
                sequence=3,
                frame_id="frame-00000003",
                captured_at_mono_ms=1140.0,
            ),
        )
        no_face = adapter.infer(
            make_frame(80, 50, 1),
            replace(
                base,
                sequence=4,
                frame_id="frame-00000004",
                captured_at_mono_ms=1180.0,
            ),
        )
        assert blink.reason == "blink"
        assert no_face.reason == "no_face"

        confirmed_context = replace(
            base,
            sequence=5,
            frame_id="frame-00000005",
            captured_at_mono_ms=1220.0,
        )
        confirmed = adapter.infer(make_frame(80, 50), confirmed_context)
        assert confirmed.valid is True
        assert confirmed.screen_x_norm == 0.8
        assert confirmed.event_id != candidate.event_id
        assert confirmed.frame_id == confirmed_context.frame_id
        assert confirmed.captured_at_mono_ms == confirmed_context.captured_at_mono_ms
    finally:
        adapter.dispose()


def test_one_frame_jump_does_not_emit_coordinates_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    base = replace(
        FrameContext(),
        sequence=1,
        frame_id="frame-00000001",
        captured_at_mono_ms=1000.0,
    )
    try:
        assert calibrate(adapter).valid is True
        assert adapter.infer(make_frame(10, 50), base).valid is True
        jump = adapter.infer(
            make_frame(80, 50),
            replace(
                base,
                sequence=2,
                frame_id="frame-00000002",
                captured_at_mono_ms=1100.0,
            ),
        )
        returned = adapter.infer(
            make_frame(10, 50),
            replace(
                base,
                sequence=3,
                frame_id="frame-00000003",
                captured_at_mono_ms=1150.0,
            ),
        )
        assert jump.valid is False
        assert jump.reason == "rapid_shift_pending"
        assert jump.screen_x_norm is None
        assert returned.valid is True
        assert returned.screen_x_norm == 0.1
    finally:
        adapter.dispose()


@pytest.mark.parametrize(
    "changed_context",
    [
        {"session_id": "session-new"},
        {"video_id": "lookbook-new"},
        {"playback_epoch": 1},
    ],
)
def test_stream_identity_change_resets_pending_filter_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_context: dict[str, object],
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    base = replace(
        FrameContext(),
        sequence=1,
        frame_id="frame-00000001",
        captured_at_mono_ms=1000.0,
    )
    try:
        assert calibrate(adapter).valid is True
        assert adapter.infer(make_frame(10, 50), base).valid is True
        pending = adapter.infer(
            make_frame(80, 50),
            replace(
                base,
                sequence=2,
                frame_id="frame-00000002",
                captured_at_mono_ms=1100.0,
            ),
        )
        assert pending.reason == "rapid_shift_pending"

        changed = replace(
            base,
            sequence=1,
            frame_id="frame-new-stream",
            captured_at_mono_ms=1150.0,
            **changed_context,
        )
        accepted = adapter.infer(make_frame(80, 50), changed)
        assert accepted.valid is True
        assert accepted.screen_x_norm == 0.8
    finally:
        adapter.dispose()


def test_observation_sink_receives_same_raw_point_without_frame_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[GazeAbObservation] = []
    adapter, _, _ = initialized_adapter(
        tmp_path,
        monkeypatch,
        FixedCalibrationSource(),
        observation_sink=observations.append,
    )
    try:
        assert calibrate(adapter).valid is True
        sample = adapter.infer(make_frame(25, 75), FrameContext())
        live = [item for item in observations if item.phase == "live"]
        assert sample.valid is True
        assert len(live) == 1
        assert live[0].raw_x_norm == 0.25
        assert live[0].raw_y_norm == 0.75
        assert live[0].stabilized_x_norm == sample.screen_x_norm
        assert live[0].stabilized_y_norm == sample.screen_y_norm
        assert not hasattr(live[0], "frame")
        assert not hasattr(live[0], "image")
    finally:
        adapter.dispose()


@pytest.mark.parametrize(
    ("smoothing_mode", "expected_valid", "expected_reason"),
    [
        ("raw", True, None),
        ("kalman_ema", False, "gaze_unavailable"),
    ],
)
def test_filter_failure_isolated_by_selected_output_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    smoothing_mode: str,
    expected_valid: bool,
    expected_reason: str | None,
) -> None:
    observations: list[GazeAbObservation] = []
    adapter, _, _ = initialized_adapter(
        tmp_path,
        monkeypatch,
        FixedCalibrationSource(),
        smoothing_mode=smoothing_mode,
        observation_sink=observations.append,
    )

    class FailingStabilizer:
        def __init__(self) -> None:
            self.reset_calls = 0

        def process_valid(self, *_args: object) -> None:
            raise RuntimeError("filter failed")

        def reset(self) -> None:
            self.reset_calls += 1

    failing = FailingStabilizer()
    try:
        assert calibrate(adapter).valid is True
        first_context = replace(
            FrameContext(),
            sequence=6,
            frame_id="frame-00000006",
            captured_at_mono_ms=1200.0,
        )
        assert adapter.infer(make_frame(25, 75), first_context).valid is True
        adapter._stabilizer = failing  # type: ignore[assignment]
        sample = adapter.infer(make_frame(25, 75), FrameContext())
        live = [item for item in observations if item.phase == "live"]

        assert sample.valid is expected_valid
        assert sample.reason == expected_reason
        assert failing.reset_calls == 1
        if smoothing_mode == "raw":
            assert sample.screen_x_norm == 0.25
            assert sample.screen_y_norm == 0.75
        else:
            assert sample.screen_x_norm is None
            assert sample.screen_y_norm is None
        assert len(live) == 2
        assert live[-1].raw_valid is True
        assert live[-1].stabilized_valid is False
        assert live[-1].stabilized_reason == "gaze_unavailable"
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


def test_recalibration_clears_pending_and_filter_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _ = initialized_adapter(tmp_path, monkeypatch, FixedCalibrationSource())
    base = replace(
        FrameContext(),
        sequence=1,
        frame_id="frame-00000001",
        captured_at_mono_ms=1000.0,
    )
    try:
        assert calibrate(adapter, "calibration-one").valid is True
        assert adapter.infer(make_frame(10, 50), base).valid is True
        pending = adapter.infer(
            make_frame(80, 50),
            replace(
                base,
                sequence=2,
                frame_id="frame-00000002",
                captured_at_mono_ms=1100.0,
            ),
        )
        assert pending.reason == "rapid_shift_pending"

        assert calibrate(adapter, "calibration-two").valid is True
        after_recalibration = adapter.infer(
            make_frame(80, 50),
            replace(
                base,
                sequence=3,
                frame_id="frame-00000003",
                captured_at_mono_ms=1150.0,
            ),
        )
        assert after_recalibration.valid is True
        assert after_recalibration.screen_x_norm == 0.8
        assert after_recalibration.calibration_id == "calibration-two"
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

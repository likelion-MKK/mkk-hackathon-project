"""EyeTrax-backed Eye Adapter for the hackathon MVP.

The adapter owns model lifecycle and gaze normalization. A caller-provided
calibration source owns the camera and target UI, so frames never need to be
stored by this module.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import tempfile
import time
import urllib.request
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
from numpy.typing import NDArray

from ..contracts import (
    AdapterMetadata,
    AdapterStateError,
    CalibrationRequest,
    CalibrationResult,
    GazeFrameContext,
    GazeSample,
)
from .gaze_stabilizer import GazeStabilizer, StabilizerDecision

BgrFrame = NDArray[np.uint8]

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
EYETRAX_SOURCE_REVISION = "84e13a16af168ac7c383f7d50ec901cd6c0ad61d"

SERVICE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FACE_MODEL_PATH = SERVICE_ROOT / ".cache" / "face_landmarker.task"

DENSE_GRID_AXIS = (0.10, 0.30, 0.50, 0.70, 0.90)
FULLSCREEN_TRAINING_POINTS = tuple(
    (x, y)
    for row, y in enumerate(DENSE_GRID_AXIS)
    for x in (DENSE_GRID_AXIS if row % 2 == 0 else tuple(reversed(DENSE_GRID_AXIS)))
)
VALIDATION_POINTS = (
    (0.20, 0.30),
    (0.38, 0.30),
    (0.20, 0.70),
    (0.42, 0.70),
    (0.80, 0.30),
    (0.62, 0.30),
    (0.80, 0.70),
    (0.58, 0.70),
)

TRAINING_ADAPT_SECONDS = 1.0
TRAINING_COLLECT_SECONDS = 1.0
VALIDATION_ADAPT_SECONDS = 0.75
VALIDATION_COLLECT_SECONDS = 1.0
CALIBRATION_MAX_ATTEMPTS = 1
CALIBRATION_ATTEMPT_SECONDS = (
    len(FULLSCREEN_TRAINING_POINTS) * (TRAINING_ADAPT_SECONDS + TRAINING_COLLECT_SECONDS)
    + len(VALIDATION_POINTS) * (VALIDATION_ADAPT_SECONDS + VALIDATION_COLLECT_SECONDS)
)
MIN_TRAINING_SAMPLES_PER_POINT = 10
MIN_VALIDATION_FRAMES_PER_POINT = 10
RIDGE_ALPHA_CANDIDATES = (0.001, 0.01, 0.1, 1.0, 10.0)
# Diagnostic-only thresholds for the physical-camera run. They are still
# reported by the validation path but do not block the best-effort model.
VALID_RATIO_GATE = 0.50
ERROR_DIAGONAL_P50_GATE = 0.50
ERROR_DIAGONAL_P95_GATE = 0.50


class EyeTraxModelError(RuntimeError):
    """Raised when the pinned FaceLandmarker asset is missing or invalid."""


class EyeTraxRuntimeError(RuntimeError):
    """Raised when EyeTrax cannot initialize or complete a lifecycle call."""


class CalibrationCancelled(RuntimeError):
    """Raised by a calibration source when the participant cancels."""


class CalibrationPhase(str, Enum):
    TRAINING = "training"
    VALIDATION = "validation"


@dataclass(frozen=True, slots=True)
class CalibrationCapture:
    """One fixed MVP target that the external camera/UI source must capture."""

    phase: CalibrationPhase
    attempt: int
    point_index: int
    point_count: int
    target_x_norm: float
    target_y_norm: float
    adaptation_seconds: float
    collection_seconds: float


CalibrationFrameSource = Callable[[CalibrationCapture], Iterable[BgrFrame]]


@dataclass(frozen=True, slots=True)
class EyeTraxConfig:
    viewport_width_px: int
    viewport_height_px: int
    face_model_path: Path = DEFAULT_FACE_MODEL_PATH
    smoothing_mode: Literal["raw", "kalman_ema"] = "raw"
    ema_alpha: float = 0.25

    def __post_init__(self) -> None:
        for name, value in (
            ("viewport_width_px", self.viewport_width_px),
            ("viewport_height_px", self.viewport_height_px),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.smoothing_mode not in ("raw", "kalman_ema"):
            raise ValueError("smoothing_mode must be 'raw' or 'kalman_ema'")
        if (
            isinstance(self.ema_alpha, bool)
            or not isinstance(self.ema_alpha, (int, float))
            or not math.isfinite(float(self.ema_alpha))
            or float(self.ema_alpha) != 0.25
        ):
            raise ValueError("ema_alpha must be fixed at 0.25 for gaze-filter-v1")
        object.__setattr__(self, "face_model_path", Path(self.face_model_path).resolve())
        object.__setattr__(self, "ema_alpha", float(self.ema_alpha))


@dataclass(frozen=True, slots=True)
class GazeAbObservation:
    """Ephemeral raw/stabilized values for same-frame summary metrics only."""

    phase: Literal["validation", "live"]
    captured_at_mono_ms: float
    target_x_norm: float | None
    target_y_norm: float | None
    raw_valid: bool
    raw_reason: str | None
    raw_x_norm: float | None
    raw_y_norm: float | None
    stabilized_valid: bool
    stabilized_reason: str | None
    stabilized_x_norm: float | None
    stabilized_y_norm: float | None
    raw_aoi_hit: bool | None
    stabilized_aoi_hit: bool | None
    inference_latency_ms: float
    filter_latency_ms: float


GazeAbObservationSink = Callable[[GazeAbObservation], None]
ValidationAoiEvaluator = Callable[
    [tuple[float, float], tuple[float, float]],
    bool,
]


class _RidgeModel(Protocol):
    def train(self, features: np.ndarray, targets: np.ndarray) -> None: ...

    def predict(self, features: np.ndarray) -> np.ndarray: ...


class _GazeEstimator(Protocol):
    model: _RidgeModel

    def extract_features(self, image: BgrFrame) -> tuple[Any | None, bool]: ...

    def train(self, features: np.ndarray, targets: np.ndarray) -> None: ...

    def predict(self, features: np.ndarray) -> np.ndarray: ...

    def close(self) -> None: ...


EstimatorFactory = Callable[[Path], _GazeEstimator]


@dataclass(frozen=True, slots=True)
class _ValidationMetrics:
    total_frames: int
    valid_frames: int
    frames_per_point: tuple[int, ...]
    valid_ratio: float
    error_diagonal_p50: float | None
    error_diagonal_p95: float | None

    @property
    def passed(self) -> bool:
        return (
            self.total_frames > 0
            and len(self.frames_per_point) == len(VALIDATION_POINTS)
            and min(self.frames_per_point, default=0)
            >= MIN_VALIDATION_FRAMES_PER_POINT
            and self.valid_ratio >= VALID_RATIO_GATE
            and self.error_diagonal_p50 is not None
            and self.error_diagonal_p50 <= ERROR_DIAGONAL_P50_GATE
            and self.error_diagonal_p95 is not None
            and self.error_diagonal_p95 <= ERROR_DIAGONAL_P95_GATE
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_face_model(path: Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise EyeTraxModelError(f"FaceLandmarker model is missing: {resolved}")
    actual = sha256_file(resolved)
    if actual != FACE_MODEL_SHA256:
        raise EyeTraxModelError(
            "FaceLandmarker checksum mismatch: "
            f"expected {FACE_MODEL_SHA256}, got {actual}"
        )
    return resolved


def prepare_face_model(path: Path = DEFAULT_FACE_MODEL_PATH, *, offline: bool = False) -> Path:
    """Download the pinned model atomically, or only verify it in offline mode."""

    destination = Path(path).resolve()
    if destination.exists():
        return verify_face_model(destination)
    if offline:
        raise EyeTraxModelError(f"FaceLandmarker model is missing in offline mode: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="face-landmarker-",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    request = urllib.request.Request(FACE_MODEL_URL, headers={"User-Agent": "mcm-eye"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open(
            "wb"
        ) as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        verify_face_model(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return verify_face_model(destination)


def _default_estimator_factory(model_path: Path) -> _GazeEstimator:
    from eyetrax import GazeEstimator

    return GazeEstimator(face_landmarker_model=model_path)


def _create_ridge_model(alpha: float) -> _RidgeModel:
    from eyetrax.models import create_model

    return create_model("ridge", alpha=alpha)


def _validate_bgr_frame(frame: Any) -> BgrFrame:
    if not isinstance(frame, np.ndarray):
        raise TypeError("frame must be a numpy.ndarray with uint8 HxWx3 BGR data")
    if (
        frame.dtype != np.uint8
        or frame.ndim != 3
        or frame.shape[0] <= 0
        or frame.shape[1] <= 0
        or frame.shape[2] != 3
    ):
        raise ValueError(
            "frame must use uint8 HxWx3 BGR data; "
            f"got dtype={frame.dtype}, shape={frame.shape}"
        )
    return frame


def _normalize_prediction(
    prediction: Sequence[float] | np.ndarray,
    width: int,
    height: int,
) -> tuple[tuple[float, float] | None, str | None]:
    try:
        values = np.asarray(prediction, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return None, "invalid_prediction"
    if values.size < 2 or not np.all(np.isfinite(values[:2])):
        return None, "invalid_prediction"
    x_norm = float(values[0]) / width
    y_norm = float(values[1]) / height
    if not 0.0 <= x_norm <= 1.0 or not 0.0 <= y_norm <= 1.0:
        return None, "outside_viewport"
    return (x_norm, y_norm), None


def _select_ridge_alpha(
    features: np.ndarray,
    targets: np.ndarray,
    samples_per_point: Sequence[int],
) -> float:
    if sum(samples_per_point) != len(features) or len(features) != len(targets):
        raise ValueError("Calibration feature, target and point counts do not match")
    non_empty_group_count = sum(count > 0 for count in samples_per_point)
    if non_empty_group_count < 2:
        return 1.0
    groups = np.concatenate(
        [
            np.full(count, point_index, dtype=np.int32)
            for point_index, count in enumerate(samples_per_point)
        ]
    )
    candidate_scores: list[tuple[float, float, float]] = []
    for alpha in RIDGE_ALPHA_CANDIDATES:
        errors: list[float] = []
        for held_out, held_out_count in enumerate(samples_per_point):
            if held_out_count == 0:
                continue
            train_mask = groups != held_out
            test_mask = ~train_mask
            model = _create_ridge_model(alpha)
            model.train(features[train_mask], targets[train_mask])
            predicted = model.predict(features[test_mask])
            errors.extend(np.linalg.norm(predicted - targets[test_mask], axis=1).tolist())
        p50, p95 = np.percentile(np.asarray(errors, dtype=np.float64), [50, 95])
        candidate_scores.append((float(p50), float(p95), alpha))
    return min(candidate_scores)[2]


class EyeTraxAdapter:
    """Single-session EyeTrax Adapter with the fixed hackathon calibration."""

    PRODUCER_ID = "eyetrax-eye-adapter"
    MODEL_REVISION = f"{EYETRAX_SOURCE_REVISION}+raw-v1"
    _SAMPLE_CACHE_LIMIT = 64

    def __init__(
        self,
        config: EyeTraxConfig,
        calibration_source: CalibrationFrameSource,
        *,
        estimator_factory: EstimatorFactory | None = None,
        observation_sink: GazeAbObservationSink | None = None,
        validation_aoi_evaluator: ValidationAoiEvaluator | None = None,
    ) -> None:
        if not callable(calibration_source):
            raise TypeError("calibration_source must be callable")
        self._config = config
        self._calibration_source = calibration_source
        self._estimator_factory = estimator_factory or _default_estimator_factory
        self._observation_sink = observation_sink
        self._validation_aoi_evaluator = validation_aoi_evaluator
        revision_suffix = (
            "raw-v1" if config.smoothing_mode == "raw" else "gaze-filter-v1"
        )
        self._model_revision = f"{EYETRAX_SOURCE_REVISION}+{revision_suffix}"
        self._stabilizer = GazeStabilizer(
            config.viewport_width_px,
            config.viewport_height_px,
            ema_alpha=config.ema_alpha,
        )
        self._estimator: _GazeEstimator | None = None
        self._owned_model_copy: Path | None = None
        self._initialized = False
        self._warmed = False
        self._calibrating = False
        self._calibrated = False
        self._calibration_id: str | None = None
        self._stream_identity: tuple[str, str, int] | None = None
        self._last_order: tuple[float, int] | None = None
        self._sample_cache: dict[str, GazeSample] = {}

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_id=self.PRODUCER_ID,
            model_id="eyetrax",
            model_revision=self._model_revision,
            runtime="python-3.12.10/eyetrax-0.4.0/mediapipe-1.0.0",
            calibration_supported=True,
        )

    def initialize(self) -> None:
        if self._initialized:
            return
        source_model = verify_face_model(self._config.face_model_path)
        native_model = source_model
        owned_copy: Path | None = None
        try:
            if not str(source_model).isascii():
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix="mcm-face-landmarker-",
                    suffix=".task",
                )
                os.close(descriptor)
                owned_copy = Path(temporary_name).resolve()
                if not str(owned_copy).isascii():
                    raise EyeTraxModelError(
                        "MediaPipe runtime model path must contain ASCII characters only"
                    )
                shutil.copyfile(source_model, owned_copy)
                verify_face_model(owned_copy)
                native_model = owned_copy
            estimator = self._estimator_factory(native_model)
        except (EyeTraxModelError, EyeTraxRuntimeError):
            if owned_copy is not None:
                owned_copy.unlink(missing_ok=True)
            raise
        except Exception as error:
            if owned_copy is not None:
                owned_copy.unlink(missing_ok=True)
            raise EyeTraxRuntimeError(
                f"EyeTrax initialization failed ({type(error).__name__})"
            ) from None

        self._owned_model_copy = owned_copy
        self._estimator = estimator
        self._initialized = True
        self._warmed = False
        self._calibrated = False
        self._calibration_id = None
        self._reset_runtime_state()

    def warmup(self) -> None:
        self._require_initialized()
        if self._warmed:
            return
        estimator = self._require_estimator()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        try:
            estimator.extract_features(black_frame)
        except Exception as error:
            self.dispose()
            raise EyeTraxRuntimeError(
                f"EyeTrax warmup failed ({type(error).__name__})"
            ) from None
        self._warmed = True

    def calibrate(self, request: CalibrationRequest) -> CalibrationResult:
        self._require_warmed()
        self._reset_runtime_state()
        self._calibration_id = request.calibration_id
        self._calibrated = False
        self._calibrating = True
        final_reason = "calibration_failed"
        try:
            attempt = 1
            self._require_estimator().model = _create_ridge_model(1.0)
            if not self._train_once(attempt):
                final_reason = "no_face"
            else:
                # Keep the validation run and its p50/p95/ratio observations,
                # but use the trained model whenever at least one face feature
                # was captured during the full calibration.
                self._validate_once(attempt)
                self._calibrated = True
                return CalibrationResult(
                    calibration_id=request.calibration_id,
                    valid=True,
                    reason=None,
                )
        except CalibrationCancelled:
            final_reason = "calibration_cancelled"
        except Exception:
            final_reason = "calibration_error"
        finally:
            self._calibrating = False

        return CalibrationResult(
            calibration_id=request.calibration_id,
            valid=False,
            reason=final_reason,
        )

    def infer(self, frame_ref: BgrFrame, context: GazeFrameContext) -> GazeSample:
        self._require_warmed()
        if self._calibration_id is None:
            raise AdapterStateError("EyeTraxAdapter must be calibrated before inference")

        event_id = self._event_id(context)
        cached = self._sample_cache.get(event_id)
        if cached is not None:
            return cached

        stream_identity = (context.session_id, context.video_id, context.playback_epoch)
        if self._stream_identity != stream_identity:
            self._reset_runtime_state()
            self._stream_identity = stream_identity

        order = (context.captured_at_mono_ms, context.sequence)
        if self._last_order is not None:
            last_captured_at_ms, last_sequence = self._last_order
            if (
                context.captured_at_mono_ms < last_captured_at_ms
                or context.sequence < last_sequence
            ):
                return self._cache_sample(
                    event_id,
                    self._invalid_sample(context, event_id, "out_of_order"),
                )
        self._last_order = order

        if self._calibrating or not self._calibrated:
            return self._cache_sample(
                event_id,
                self._invalid_sample(context, event_id, "gaze_unavailable"),
            )

        frame = _validate_bgr_frame(frame_ref)
        estimator = self._require_estimator()
        inference_started = time.perf_counter_ns()
        try:
            features, blink = estimator.extract_features(frame)
            if features is None:
                return self._invalid_runtime_sample(
                    context,
                    event_id,
                    "no_face",
                    inference_started,
                )
            if blink:
                return self._invalid_runtime_sample(
                    context,
                    event_id,
                    "blink",
                    inference_started,
                )
            prediction = estimator.predict(np.asarray([features]))[0]
            normalized, reason = _normalize_prediction(
                prediction,
                self._config.viewport_width_px,
                self._config.viewport_height_px,
            )
            if normalized is None:
                return self._invalid_runtime_sample(
                    context,
                    event_id,
                    reason or "invalid_prediction",
                    inference_started,
                )
        except Exception:
            return self._invalid_runtime_sample(
                context,
                event_id,
                "inference_error",
                inference_started,
            )

        inference_latency_ms = (time.perf_counter_ns() - inference_started) / 1_000_000.0
        if self._filter_path_enabled:
            filter_started = time.perf_counter_ns()
            try:
                decision = self._stabilizer.process_valid(
                    normalized[0] * self._config.viewport_width_px,
                    normalized[1] * self._config.viewport_height_px,
                    context.captured_at_mono_ms,
                )
                stabilized = self._normalized_decision(decision)
            except Exception:
                self._reset_stabilizer_after_error()
                decision = StabilizerDecision(
                    valid=False,
                    reason="gaze_unavailable",
                )
                stabilized = (None, decision.reason)
            filter_latency_ms = (
                time.perf_counter_ns() - filter_started
            ) / 1_000_000.0
        else:
            decision = StabilizerDecision(
                valid=True,
                reason=None,
                x_px=int(round(normalized[0] * self._config.viewport_width_px)),
                y_px=int(round(normalized[1] * self._config.viewport_height_px)),
            )
            stabilized = self._normalized_decision(decision)
            filter_latency_ms = 0.0

        if self._config.smoothing_mode == "raw":
            sample = GazeSample(
                **self._common_fields(context, event_id),
                valid=True,
                confidence=1.0,
                reason=None,
                screen_x_norm=normalized[0],
                screen_y_norm=normalized[1],
            )
        elif stabilized[0] is None:
            sample = self._invalid_sample(
                context,
                event_id,
                stabilized[1] or "invalid_prediction",
            )
        else:
            sample = GazeSample(
                **self._common_fields(context, event_id),
                valid=True,
                confidence=1.0,
                reason=None,
                screen_x_norm=stabilized[0][0],
                screen_y_norm=stabilized[0][1],
            )

        self._emit_observation(
            GazeAbObservation(
                phase="live",
                captured_at_mono_ms=context.captured_at_mono_ms,
                target_x_norm=None,
                target_y_norm=None,
                raw_valid=True,
                raw_reason=None,
                raw_x_norm=normalized[0],
                raw_y_norm=normalized[1],
                stabilized_valid=stabilized[0] is not None,
                stabilized_reason=stabilized[1],
                stabilized_x_norm=None if stabilized[0] is None else stabilized[0][0],
                stabilized_y_norm=None if stabilized[0] is None else stabilized[0][1],
                raw_aoi_hit=None,
                stabilized_aoi_hit=None,
                inference_latency_ms=inference_latency_ms,
                filter_latency_ms=filter_latency_ms,
            )
        )
        return self._cache_sample(event_id, sample)

    def dispose(self) -> None:
        estimator = self._estimator
        owned_copy = self._owned_model_copy
        self._estimator = None
        self._owned_model_copy = None
        self._initialized = False
        self._warmed = False
        self._calibrating = False
        self._calibrated = False
        self._calibration_id = None
        self._reset_runtime_state()

        close_error: Exception | None = None
        try:
            if estimator is not None:
                estimator.close()
        except Exception as error:
            close_error = error
        finally:
            if owned_copy is not None:
                owned_copy.unlink(missing_ok=True)
        if close_error is not None:
            raise EyeTraxRuntimeError(
                f"EyeTrax dispose failed ({type(close_error).__name__})"
            ) from None

    def _train_once(self, attempt: int) -> bool:
        estimator = self._require_estimator()
        all_features: list[np.ndarray] = []
        all_targets: list[list[float]] = []
        samples_per_point: list[int] = []
        for index, (x_norm, y_norm) in enumerate(FULLSCREEN_TRAINING_POINTS, start=1):
            capture = CalibrationCapture(
                phase=CalibrationPhase.TRAINING,
                attempt=attempt,
                point_index=index,
                point_count=len(FULLSCREEN_TRAINING_POINTS),
                target_x_norm=x_norm,
                target_y_norm=y_norm,
                adaptation_seconds=TRAINING_ADAPT_SECONDS,
                collection_seconds=TRAINING_COLLECT_SECONDS,
            )
            point_features: list[np.ndarray] = []
            for frame in self._calibration_source(capture):
                features, blink = estimator.extract_features(_validate_bgr_frame(frame))
                if features is not None and not blink:
                    point_features.append(np.asarray(features))
            target = [
                float(int(x_norm * self._config.viewport_width_px)),
                float(int(y_norm * self._config.viewport_height_px)),
            ]
            samples_per_point.append(len(point_features))
            all_features.extend(point_features)
            all_targets.extend([target] * len(point_features))

        if not all_features:
            return False

        feature_matrix = np.asarray(all_features)
        target_matrix = np.asarray(all_targets, dtype=np.float64)
        selected_alpha = _select_ridge_alpha(
            feature_matrix,
            target_matrix,
            samples_per_point,
        )
        estimator.model = _create_ridge_model(selected_alpha)
        estimator.train(feature_matrix, target_matrix)
        return True

    def _validate_once(self, attempt: int) -> _ValidationMetrics:
        estimator = self._require_estimator()
        comparison_stabilizer = (
            GazeStabilizer(
                self._config.viewport_width_px,
                self._config.viewport_height_px,
                ema_alpha=self._config.ema_alpha,
            )
            if self._observation_sink is not None
            else None
        )
        total_frames = 0
        valid_frames = 0
        frames_per_point: list[int] = []
        diagonal_errors: list[float] = []
        diagonal = math.hypot(
            self._config.viewport_width_px,
            self._config.viewport_height_px,
        )

        for index, (x_norm, y_norm) in enumerate(VALIDATION_POINTS, start=1):
            capture = CalibrationCapture(
                phase=CalibrationPhase.VALIDATION,
                attempt=attempt,
                point_index=index,
                point_count=len(VALIDATION_POINTS),
                target_x_norm=x_norm,
                target_y_norm=y_norm,
                adaptation_seconds=VALIDATION_ADAPT_SECONDS,
                collection_seconds=VALIDATION_COLLECT_SECONDS,
            )
            target_x = float(int(x_norm * self._config.viewport_width_px))
            target_y = float(int(y_norm * self._config.viewport_height_px))
            point_frames = 0
            for frame in self._calibration_source(capture):
                point_frames += 1
                total_frames += 1
                captured_at_mono_ms = time.perf_counter_ns() / 1_000_000.0
                inference_started = time.perf_counter_ns()
                features, blink = estimator.extract_features(_validate_bgr_frame(frame))
                if features is None or blink:
                    if comparison_stabilizer is not None:
                        reason = "no_face" if features is None else "blink"
                        self._observe_validation_invalid(
                            comparison_stabilizer,
                            captured_at_mono_ms=captured_at_mono_ms,
                            target=(x_norm, y_norm),
                            reason=reason,
                            inference_started_ns=inference_started,
                        )
                    continue
                prediction = estimator.predict(np.asarray([features]))[0]
                normalized, prediction_reason = _normalize_prediction(
                    prediction,
                    self._config.viewport_width_px,
                    self._config.viewport_height_px,
                )
                if normalized is None:
                    if comparison_stabilizer is not None:
                        self._observe_validation_invalid(
                            comparison_stabilizer,
                            captured_at_mono_ms=captured_at_mono_ms,
                            target=(x_norm, y_norm),
                            reason=prediction_reason or "invalid_prediction",
                            inference_started_ns=inference_started,
                        )
                    continue
                if comparison_stabilizer is not None:
                    self._observe_validation_valid(
                        comparison_stabilizer,
                        captured_at_mono_ms=captured_at_mono_ms,
                        target=(x_norm, y_norm),
                        raw=normalized,
                        inference_started_ns=inference_started,
                    )
                valid_frames += 1
                predicted_x = normalized[0] * self._config.viewport_width_px
                predicted_y = normalized[1] * self._config.viewport_height_px
                diagonal_errors.append(
                    math.hypot(predicted_x - target_x, predicted_y - target_y) / diagonal
                )
            frames_per_point.append(point_frames)

        valid_ratio = valid_frames / total_frames if total_frames else 0.0
        if diagonal_errors:
            p50, p95 = np.percentile(
                np.asarray(diagonal_errors, dtype=np.float64),
                [50, 95],
            )
            p50_value: float | None = float(p50)
            p95_value: float | None = float(p95)
        else:
            p50_value = p95_value = None
        return _ValidationMetrics(
            total_frames=total_frames,
            valid_frames=valid_frames,
            frames_per_point=tuple(frames_per_point),
            valid_ratio=valid_ratio,
            error_diagonal_p50=p50_value,
            error_diagonal_p95=p95_value,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise AdapterStateError("EyeTraxAdapter must be initialized before use")

    def _require_warmed(self) -> None:
        self._require_initialized()
        if not self._warmed:
            raise AdapterStateError("EyeTraxAdapter must be warmed before use")

    def _require_estimator(self) -> _GazeEstimator:
        if self._estimator is None:
            raise AdapterStateError("EyeTrax estimator is not initialized")
        return self._estimator

    def _event_id(self, context: GazeFrameContext) -> str:
        identity = "\x1f".join(
            (
                self.PRODUCER_ID,
                self._model_revision,
                self._calibration_id or "calibration-missing",
                context.session_id,
                str(context.sequence),
                context.frame_id,
                str(context.captured_at_mono_ms),
                context.video_id,
                str(context.video_time_ms),
                str(context.playback_epoch),
            )
        )
        return f"gaze-{uuid.uuid5(uuid.NAMESPACE_URL, identity)}"

    def _common_fields(
        self,
        context: GazeFrameContext,
        event_id: str,
    ) -> dict[str, object]:
        assert self._calibration_id is not None
        return {
            "schema_version": "1.0",
            "session_id": context.session_id,
            "event_id": event_id,
            "sequence": context.sequence,
            "frame_id": context.frame_id,
            "captured_at_mono_ms": context.captured_at_mono_ms,
            "video_id": context.video_id,
            "video_time_ms": context.video_time_ms,
            "playback_epoch": context.playback_epoch,
            "producer_id": self.PRODUCER_ID,
            "model_revision": self._model_revision,
            "calibration_id": self._calibration_id,
        }

    def _invalid_sample(
        self,
        context: GazeFrameContext,
        event_id: str,
        reason: str,
    ) -> GazeSample:
        return GazeSample(
            **self._common_fields(context, event_id),
            valid=False,
            confidence=0.0,
            reason=reason,
        )

    def _invalid_runtime_sample(
        self,
        context: GazeFrameContext,
        event_id: str,
        reason: str,
        inference_started_ns: int,
    ) -> GazeSample:
        inference_latency_ms = (time.perf_counter_ns() - inference_started_ns) / 1_000_000.0
        if self._filter_path_enabled:
            filter_started = time.perf_counter_ns()
            try:
                decision = self._stabilizer.observe_invalid(
                    context.captured_at_mono_ms,
                    reason,
                )
            except Exception:
                self._reset_stabilizer_after_error()
                decision = StabilizerDecision(
                    valid=False,
                    reason="gaze_unavailable",
                )
            filter_latency_ms = (
                time.perf_counter_ns() - filter_started
            ) / 1_000_000.0
        else:
            decision = StabilizerDecision(valid=False, reason=reason)
            filter_latency_ms = 0.0
        self._emit_observation(
            GazeAbObservation(
                phase="live",
                captured_at_mono_ms=context.captured_at_mono_ms,
                target_x_norm=None,
                target_y_norm=None,
                raw_valid=False,
                raw_reason=reason,
                raw_x_norm=None,
                raw_y_norm=None,
                stabilized_valid=False,
                stabilized_reason=decision.reason,
                stabilized_x_norm=None,
                stabilized_y_norm=None,
                raw_aoi_hit=None,
                stabilized_aoi_hit=None,
                inference_latency_ms=inference_latency_ms,
                filter_latency_ms=filter_latency_ms,
            )
        )
        return self._cache_sample(
            event_id,
            self._invalid_sample(context, event_id, reason),
        )

    def _normalized_decision(
        self,
        decision: StabilizerDecision,
    ) -> tuple[tuple[float, float] | None, str | None]:
        if not decision.valid:
            return None, decision.reason
        assert decision.x_px is not None and decision.y_px is not None
        return _normalize_prediction(
            (decision.x_px, decision.y_px),
            self._config.viewport_width_px,
            self._config.viewport_height_px,
        )

    def _cache_sample(self, event_id: str, sample: GazeSample) -> GazeSample:
        self._sample_cache[event_id] = sample
        if len(self._sample_cache) > self._SAMPLE_CACHE_LIMIT:
            self._sample_cache.pop(next(iter(self._sample_cache)))
        return sample

    def _reset_runtime_state(self) -> None:
        self._stabilizer.reset()
        self._stream_identity = None
        self._last_order = None
        self._sample_cache.clear()

    def _reset_stabilizer_after_error(self) -> None:
        try:
            self._stabilizer.reset()
        except Exception:
            # A broken optional filter must not replace a usable raw result.
            pass

    @property
    def _filter_path_enabled(self) -> bool:
        return self._config.smoothing_mode == "kalman_ema" or self._observation_sink is not None

    def _emit_observation(self, observation: GazeAbObservation) -> None:
        if self._observation_sink is not None:
            try:
                self._observation_sink(observation)
            except Exception:
                # Optional metrics must never change gaze or calibration outcomes.
                pass

    def _observe_validation_invalid(
        self,
        stabilizer: GazeStabilizer,
        *,
        captured_at_mono_ms: float,
        target: tuple[float, float],
        reason: str,
        inference_started_ns: int,
    ) -> None:
        try:
            inference_latency_ms = (
                time.perf_counter_ns() - inference_started_ns
            ) / 1_000_000.0
            filter_started = time.perf_counter_ns()
            decision = stabilizer.observe_invalid(captured_at_mono_ms, reason)
            filter_latency_ms = (
                time.perf_counter_ns() - filter_started
            ) / 1_000_000.0
            self._emit_validation_observation(
                captured_at_mono_ms=captured_at_mono_ms,
                target=target,
                raw=None,
                raw_reason=reason,
                stabilized=decision,
                inference_latency_ms=inference_latency_ms,
                filter_latency_ms=filter_latency_ms,
            )
        except Exception:
            pass

    def _observe_validation_valid(
        self,
        stabilizer: GazeStabilizer,
        *,
        captured_at_mono_ms: float,
        target: tuple[float, float],
        raw: tuple[float, float],
        inference_started_ns: int,
    ) -> None:
        try:
            inference_latency_ms = (
                time.perf_counter_ns() - inference_started_ns
            ) / 1_000_000.0
            filter_started = time.perf_counter_ns()
            decision = stabilizer.process_valid(
                raw[0] * self._config.viewport_width_px,
                raw[1] * self._config.viewport_height_px,
                captured_at_mono_ms,
            )
            filter_latency_ms = (
                time.perf_counter_ns() - filter_started
            ) / 1_000_000.0
            self._emit_validation_observation(
                captured_at_mono_ms=captured_at_mono_ms,
                target=target,
                raw=raw,
                raw_reason=None,
                stabilized=decision,
                inference_latency_ms=inference_latency_ms,
                filter_latency_ms=filter_latency_ms,
            )
        except Exception:
            pass

    def _emit_validation_observation(
        self,
        *,
        captured_at_mono_ms: float,
        target: tuple[float, float],
        raw: tuple[float, float] | None,
        raw_reason: str | None,
        stabilized: StabilizerDecision,
        inference_latency_ms: float,
        filter_latency_ms: float,
    ) -> None:
        stabilized_normalized = self._normalized_decision(stabilized)
        raw_aoi_hit = self._validation_aoi_hit(target, raw)
        stabilized_aoi_hit = self._validation_aoi_hit(
            target,
            stabilized_normalized[0],
        )
        self._emit_observation(
            GazeAbObservation(
                phase="validation",
                captured_at_mono_ms=captured_at_mono_ms,
                target_x_norm=target[0],
                target_y_norm=target[1],
                raw_valid=raw is not None,
                raw_reason=raw_reason,
                raw_x_norm=None if raw is None else raw[0],
                raw_y_norm=None if raw is None else raw[1],
                stabilized_valid=stabilized_normalized[0] is not None,
                stabilized_reason=stabilized_normalized[1],
                stabilized_x_norm=(
                    None if stabilized_normalized[0] is None else stabilized_normalized[0][0]
                ),
                stabilized_y_norm=(
                    None if stabilized_normalized[0] is None else stabilized_normalized[0][1]
                ),
                raw_aoi_hit=raw_aoi_hit,
                stabilized_aoi_hit=stabilized_aoi_hit,
                inference_latency_ms=inference_latency_ms,
                filter_latency_ms=filter_latency_ms,
            )
        )

    def _validation_aoi_hit(
        self,
        target: tuple[float, float],
        prediction: tuple[float, float] | None,
    ) -> bool | None:
        if prediction is None or self._validation_aoi_evaluator is None:
            return None
        return bool(self._validation_aoi_evaluator(target, prediction))


__all__ = [
    "CALIBRATION_ATTEMPT_SECONDS",
    "CALIBRATION_MAX_ATTEMPTS",
    "CalibrationCancelled",
    "CalibrationCapture",
    "CalibrationFrameSource",
    "CalibrationPhase",
    "DEFAULT_FACE_MODEL_PATH",
    "EyeTraxAdapter",
    "EyeTraxConfig",
    "GazeAbObservation",
    "GazeAbObservationSink",
    "ValidationAoiEvaluator",
    "EyeTraxModelError",
    "EyeTraxRuntimeError",
    "FACE_MODEL_SHA256",
    "FACE_MODEL_URL",
    "FULLSCREEN_TRAINING_POINTS",
    "VALIDATION_POINTS",
    "prepare_face_model",
    "sha256_file",
    "verify_face_model",
]

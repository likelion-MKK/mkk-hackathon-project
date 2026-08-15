"""Selected MediaPipe Face Landmarker adapter for the D6 worker slice."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
from math import isfinite
from pathlib import Path
import re
from threading import RLock
from time import monotonic
from typing import Any, Protocol

from mcm_face.models import AdapterMetadata, ExpressionSample, FaceFrameContext
from mcm_face.result import event_id, invalid_sample

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


@dataclass(frozen=True, slots=True)
class FaceInference:
    """Transient normalized view of one model result."""

    face_count: int
    blendshapes: tuple[Mapping[str, float], ...]
    quality: float | None


@dataclass(frozen=True, slots=True)
class _CachedDerivedSample:
    """Context-free fields needed to rebuild one canonical sample."""

    expires_at: float
    face_detected: bool
    face_count: int
    scores: tuple[tuple[str, float], ...]
    quality: float
    valid: bool
    confidence: float
    reason: str | None

    @classmethod
    def from_sample(
        cls,
        sample: ExpressionSample,
        *,
        expires_at: float,
    ) -> _CachedDerivedSample:
        return cls(
            expires_at=expires_at,
            face_detected=sample.face_detected,
            face_count=sample.face_count,
            scores=tuple(sample.scores.items()),
            quality=sample.quality,
            valid=sample.valid,
            confidence=sample.confidence,
            reason=sample.reason,
        )


class FaceInferenceBackend(Protocol):
    def initialize(self) -> None: ...
    def infer(self, frame: Any) -> FaceInference: ...
    def dispose(self) -> None: ...


SOURCE_LABELS = (
    "_neutral", "browDownLeft", "browDownRight", "browInnerUp",
    "browOuterUpLeft", "browOuterUpRight", "cheekPuff", "cheekSquintLeft",
    "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight", "eyeLookDownLeft",
    "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft",
    "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight", "eyeSquintLeft",
    "eyeSquintRight", "eyeWideLeft", "eyeWideRight", "jawForward", "jawLeft",
    "jawOpen", "jawRight", "mouthClose", "mouthDimpleLeft", "mouthDimpleRight",
    "mouthFrownLeft", "mouthFrownRight", "mouthFunnel", "mouthLeft",
    "mouthLowerDownLeft", "mouthLowerDownRight", "mouthPressLeft",
    "mouthPressRight", "mouthPucker", "mouthRight", "mouthRollLower",
    "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft",
    "mouthSmileRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight",
)


def _canonical_label(source_label: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", source_label).lower()


CANONICAL_LABELS = {
    source_label: _canonical_label(source_label)
    for source_label in SOURCE_LABELS
    if source_label != "_neutral"
}


def _quality_from_landmarks(
    face_landmarks: Sequence[Sequence[Any]],
    *,
    face_count: int,
    min_in_frame_ratio: float = 0.90,
    min_face_width_ratio: float = 0.10,
    min_face_height_ratio: float = 0.10,
) -> float | None:
    """Return technical signal usability, not emotion or reaction accuracy.

    MediaPipe presence/visibility is preferred when it is completely available.
    Otherwise a conservative geometry proxy checks finite coordinates, the share
    of landmarks inside the image, and normalized face bounding-box extent.
    """

    for name, value in (
        ("min_in_frame_ratio", min_in_frame_ratio),
        ("min_face_width_ratio", min_face_width_ratio),
        ("min_face_height_ratio", min_face_height_ratio),
    ):
        if not 0.0 < value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
    if face_count == 0:
        return 0.0
    points = [point for landmarks in face_landmarks for point in landmarks]
    if not points:
        return None
    supported_channels: list[list[float]] = []
    for attribute in ("presence", "visibility"):
        raw_values = [getattr(point, attribute, None) for point in points]
        if all(value is not None for value in raw_values):
            try:
                values = [float(value) for value in raw_values]
            except (TypeError, ValueError):
                return 0.0
            if not all(isfinite(value) and 0.0 <= value <= 1.0 for value in values):
                return 0.0
            supported_channels.append(values)
    if not supported_channels:
        coordinates: list[tuple[float, float, float]] = []
        try:
            for point in points:
                coordinates.append((float(point.x), float(point.y), float(point.z)))
        except (AttributeError, TypeError, ValueError):
            return 0.0
        if not all(isfinite(value) for coordinate in coordinates for value in coordinate):
            return 0.0
        in_frame = sum(
            1 for x, y, _ in coordinates if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        ) / len(coordinates)
        x_values = [coordinate[0] for coordinate in coordinates]
        y_values = [coordinate[1] for coordinate in coordinates]
        width = max(x_values) - min(x_values)
        height = max(y_values) - min(y_values)
        return min(
            1.0,
            in_frame / min_in_frame_ratio,
            width / min_face_width_ratio,
            height / min_face_height_ratio,
        )
    values = [value for channel in supported_channels for value in channel]
    return sum(values) / len(values)


class MediaPipeBackend:
    """Optional MediaPipe runtime. Model bytes live only for adapter lifetime."""

    def __init__(
        self,
        model_path: Path,
        *,
        min_in_frame_ratio: float = 0.90,
        min_face_width_ratio: float = 0.10,
        min_face_height_ratio: float = 0.10,
    ) -> None:
        self._model_path = model_path
        self._min_in_frame_ratio = min_in_frame_ratio
        self._min_face_width_ratio = min_face_width_ratio
        self._min_face_height_ratio = min_face_height_ratio
        self._landmarker: Any | None = None
        self._mp: Any | None = None

    def initialize(self) -> None:
        try:
            import mediapipe as mp
        except ImportError as error:
            raise RuntimeError("mediapipe runtime is unavailable") from error
        if not self._model_path.is_file():
            raise RuntimeError("pinned face model asset is unavailable")
        model_bytes = self._model_path.read_bytes()
        actual = hashlib.sha256(model_bytes).hexdigest()
        if not hmac.compare_digest(actual, MODEL_SHA256):
            del model_bytes
            raise RuntimeError("pinned face model checksum mismatch")
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=model_bytes),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=2,
            output_face_blendshapes=True,
        )
        self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self._mp = mp
        del model_bytes

    def infer(self, frame: Any) -> FaceInference:
        if self._landmarker is None or self._mp is None:
            raise RuntimeError("mediapipe backend is not initialized")
        # Camera frames are BGR numpy arrays. The conversion creates a bounded,
        # in-memory RGB buffer which is released before this method returns.
        rgb_copy = getattr(frame, "to_rgb_copy", None)
        rgb = rgb_copy() if callable(rgb_copy) else frame[:, :, ::-1].copy()
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._landmarker.detect(image)
            count = len(result.face_landmarks)
            groups: list[Mapping[str, float]] = []
            for group in result.face_blendshapes:
                values: dict[str, float] = {}
                for category in group:
                    label = category.category_name
                    if label in values:
                        raise ValueError("duplicate blendshape label")
                    values[label] = float(category.score)
                groups.append(values)
            quality = _quality_from_landmarks(
                result.face_landmarks,
                face_count=count,
                min_in_frame_ratio=self._min_in_frame_ratio,
                min_face_width_ratio=self._min_face_width_ratio,
                min_face_height_ratio=self._min_face_height_ratio,
            )
            return FaceInference(count, tuple(groups), quality)
        finally:
            del image
            del rgb

    def dispose(self) -> None:
        landmarker, self._landmarker = self._landmarker, None
        self._mp = None
        if landmarker is not None:
            landmarker.close()


class SelectedFaceAdapter:
    """ADR-0003 selected adapter; failures become explicit invalid samples."""

    def __init__(
        self,
        *,
        model_path: str | Path = "models/face_landmarker.task",
        low_quality_threshold: float = 0.8,
        min_in_frame_ratio: float = 0.90,
        min_face_width_ratio: float = 0.10,
        min_face_height_ratio: float = 0.10,
        backend: FaceInferenceBackend | None = None,
        cache_max_entries: int = 256,
        cache_ttl_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not 0.0 <= low_quality_threshold <= 1.0:
            raise ValueError("low_quality_threshold must be between 0 and 1")
        for name, value in (
            ("min_in_frame_ratio", min_in_frame_ratio),
            ("min_face_width_ratio", min_face_width_ratio),
            ("min_face_height_ratio", min_face_height_ratio),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if cache_max_entries <= 0:
            raise ValueError("cache_max_entries must be positive")
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        self._backend = backend or MediaPipeBackend(
            Path(model_path),
            min_in_frame_ratio=min_in_frame_ratio,
            min_face_width_ratio=min_face_width_ratio,
            min_face_height_ratio=min_face_height_ratio,
        )
        self._threshold = low_quality_threshold
        self._cache_max_entries = cache_max_entries
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        # Use the deterministic event ID as the retry key so raw context values
        # (especially session_id) are never retained in cache keys.
        self._cache: OrderedDict[str, _CachedDerivedSample] = OrderedDict()
        self._lock = RLock()
        self._ready = False

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_id="mediapipe-face-landmarker-adapter",
            model_id="mediapipe-face-landmarker",
            model_revision="face-landmarker-float16-v1",
            taxonomy_version="face-observable-actions-v1",
            runtime="python-mediapipe",
            source_labels=SOURCE_LABELS,
        )

    def initialize(self) -> None:
        with self._lock:
            if not self._ready:
                self._cache.clear()
                self._backend.initialize()
                self._ready = True

    def warmup(self) -> None:
        with self._lock:
            if not self._ready:
                raise RuntimeError("adapter must be initialized before warmup")

    def infer(self, frame: Any, context: FaceFrameContext) -> ExpressionSample:
        with self._lock:
            metadata = self.metadata()
            if not self._ready:
                del frame
                return invalid_sample(metadata, context, reason="model_unavailable")
            key = event_id(metadata, context)
            now = self._clock()
            self._prune_expired(now)
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                del frame
                return self._sample_from_cache(metadata, context, key, cached)
            result: FaceInference | None = None
            try:
                result = self._backend.infer(frame)
                sample = self._to_sample(metadata, context, result)
            except (KeyError, TypeError, ValueError):
                sample = invalid_sample(metadata, context, reason="malformed_output")
            except Exception:
                sample = invalid_sample(metadata, context, reason="model_unavailable")
            finally:
                result = None
                del frame
            self._cache[key] = _CachedDerivedSample.from_sample(
                sample,
                expires_at=now + self._cache_ttl_seconds,
            )
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max_entries:
                self._cache.popitem(last=False)
            return sample

    def _to_sample(
        self,
        metadata: AdapterMetadata,
        context: FaceFrameContext,
        result: FaceInference,
    ) -> ExpressionSample:
        quality = result.quality
        if result.face_count == 0:
            return invalid_sample(metadata, context, reason="no_face")
        if result.face_count >= 2:
            return invalid_sample(
                metadata,
                context,
                reason="multi_face",
                face_count=result.face_count,
                quality=quality if quality is not None else 0.0,
            )
        if len(result.blendshapes) != 1:
            return invalid_sample(metadata, context, reason="malformed_output", face_count=1)
        try:
            scores = self._normalize(result.blendshapes[0])
        except (TypeError, ValueError):
            return invalid_sample(metadata, context, reason="malformed_output", face_count=1)
        if quality is None or quality < self._threshold:
            return invalid_sample(
                metadata,
                context,
                reason="low_quality",
                face_count=1,
                quality=quality if quality is not None else 0.0,
            )
        return ExpressionSample(
            schema_version="1.0", session_id=context.session_id,
            event_id=event_id(metadata, context), sequence=context.sequence,
            frame_id=context.frame_id, captured_at_mono_ms=context.captured_at_mono_ms,
            video_id=context.video_id, video_time_ms=context.video_time_ms,
            playback_epoch=context.playback_epoch, producer_id=metadata.adapter_id,
            model_revision=metadata.model_revision, taxonomy_version=metadata.taxonomy_version,
            face_detected=True, face_count=1, scores=scores, quality=quality,
            valid=True, confidence=quality, reason=None,
        )

    @staticmethod
    def _sample_from_cache(
        metadata: AdapterMetadata,
        context: FaceFrameContext,
        cached_event_id: str,
        cached: _CachedDerivedSample,
    ) -> ExpressionSample:
        return ExpressionSample(
            schema_version="1.0",
            session_id=context.session_id,
            event_id=cached_event_id,
            sequence=context.sequence,
            frame_id=context.frame_id,
            captured_at_mono_ms=context.captured_at_mono_ms,
            video_id=context.video_id,
            video_time_ms=context.video_time_ms,
            playback_epoch=context.playback_epoch,
            producer_id=metadata.adapter_id,
            model_revision=metadata.model_revision,
            taxonomy_version=metadata.taxonomy_version,
            face_detected=cached.face_detected,
            face_count=cached.face_count,
            scores=dict(cached.scores),
            quality=cached.quality,
            valid=cached.valid,
            confidence=cached.confidence,
            reason=cached.reason,
        )

    def _prune_expired(self, now: float) -> None:
        expired = [key for key, cached in self._cache.items() if cached.expires_at <= now]
        for key in expired:
            del self._cache[key]

    def _normalize(self, values: Mapping[str, float]) -> dict[str, float]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate blendshape labels")
        missing = set(SOURCE_LABELS) - set(values)
        unknown = set(values) - set(SOURCE_LABELS)
        if missing or len(unknown) > 1:
            raise ValueError("unexpected blendshape taxonomy")
        normalized: dict[str, float] = {}
        for source, value in values.items():
            score = float(value)
            if not 0.0 <= score <= 1.0:
                raise ValueError("blendshape score is outside 0..1")
            if source == "_neutral":
                continue
            normalized[CANONICAL_LABELS.get(source, "unknown")] = score
        if not normalized:
            raise ValueError("no emitted blendshape scores")
        return normalized

    def dispose(self) -> None:
        with self._lock:
            try:
                self._backend.dispose()
            finally:
                self._cache.clear()
                self._ready = False

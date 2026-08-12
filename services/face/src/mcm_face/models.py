"""Typed values shared by Face Adapter implementations."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
import re
from types import MappingProxyType
from typing import Protocol, runtime_checkable


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_REASON_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_string(
    value: object,
    name: str,
    *,
    max_length: int = 128,
    pattern: re.Pattern[str] | None = None,
) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= max_length:
        raise ValueError(f"{name} must be a non-empty string up to {max_length} characters")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid format")


def _validate_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _validate_number(value: object, name: str, *, normalized: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if normalized and not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")


@runtime_checkable
class FaceFrameContext(Protocol):
    """Capture-time fields Face needs from the richer Kiosk FrameContext."""

    session_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int


@dataclass(frozen=True, slots=True)
class AdapterMetadata:
    """Pinned identity needed to reproduce adapter output."""

    adapter_id: str
    model_id: str
    model_revision: str
    taxonomy_version: str
    runtime: str
    source_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_string(self.adapter_id, "adapter_id", pattern=_ID_PATTERN)
        _validate_string(self.model_id, "model_id")
        _validate_string(self.model_revision, "model_revision")
        _validate_string(self.taxonomy_version, "taxonomy_version")
        _validate_string(self.runtime, "runtime")

        labels = tuple(self.source_labels)
        if len(labels) != len(set(labels)):
            raise ValueError("source_labels must not contain duplicates")
        for label in labels:
            _validate_string(label, "source label")
        object.__setattr__(self, "source_labels", labels)


@dataclass(frozen=True, slots=True)
class ExpressionSample:
    """Face Adapter output matching ExpressionSample contract v1."""

    schema_version: str
    session_id: str
    event_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int
    producer_id: str
    model_revision: str
    taxonomy_version: str
    face_detected: bool
    face_count: int
    scores: Mapping[str, float]
    quality: float
    valid: bool
    confidence: float
    reason: str | None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("schema_version must be '1.0'")

        for name in (
            "session_id",
            "event_id",
            "frame_id",
            "video_id",
            "producer_id",
        ):
            _validate_string(getattr(self, name), name, pattern=_ID_PATTERN)
        _validate_string(self.model_revision, "model_revision")
        _validate_string(self.taxonomy_version, "taxonomy_version")

        for name in ("sequence", "video_time_ms", "playback_epoch", "face_count"):
            _validate_integer(getattr(self, name), name)
        _validate_number(self.captured_at_mono_ms, "captured_at_mono_ms")
        if self.captured_at_mono_ms < 0:
            raise ValueError("captured_at_mono_ms must be non-negative")
        _validate_number(self.quality, "quality", normalized=True)
        _validate_number(self.confidence, "confidence", normalized=True)

        if not isinstance(self.face_detected, bool):
            raise ValueError("face_detected must be a boolean")
        if not isinstance(self.valid, bool):
            raise ValueError("valid must be a boolean")
        if not isinstance(self.scores, Mapping):
            raise ValueError("scores must be a mapping")

        scores = dict(self.scores)
        for label, score in scores.items():
            _validate_string(label, "score label", max_length=64, pattern=_LABEL_PATTERN)
            _validate_number(score, f"score '{label}'", normalized=True)
        object.__setattr__(self, "scores", MappingProxyType(scores))

        if self.reason is not None:
            _validate_string(self.reason, "reason", pattern=_REASON_PATTERN)

        if self.face_detected:
            if self.face_count < 1:
                raise ValueError("face_detected=true requires face_count of at least 1")
        elif self.face_count != 0:
            raise ValueError("face_detected=false requires face_count=0")

        if self.valid:
            if not self.face_detected or self.face_count != 1:
                raise ValueError("valid samples require exactly one detected face")
            if not scores:
                raise ValueError("valid samples require at least one score")
            if self.reason is not None:
                raise ValueError("valid samples cannot have a reason")
        else:
            if scores:
                raise ValueError("invalid samples cannot contain scores")
            if self.reason is None:
                raise ValueError("invalid samples require a reason")

    def to_payload(self) -> dict[str, object]:
        """Return the public JSON-compatible payload without any frame data."""

        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "frame_id": self.frame_id,
            "captured_at_mono_ms": self.captured_at_mono_ms,
            "video_id": self.video_id,
            "video_time_ms": self.video_time_ms,
            "playback_epoch": self.playback_epoch,
            "producer_id": self.producer_id,
            "model_revision": self.model_revision,
            "taxonomy_version": self.taxonomy_version,
            "face_detected": self.face_detected,
            "face_count": self.face_count,
            "scores": dict(self.scores),
            "quality": self.quality,
            "valid": self.valid,
            "confidence": self.confidence,
            "reason": self.reason,
        }

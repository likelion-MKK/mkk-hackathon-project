"""Language-local representations of the public Eye service contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, runtime_checkable

FrameT = TypeVar("FrameT")


class AdapterStateError(RuntimeError):
    """Raised when an adapter lifecycle method is called out of order."""


@dataclass(frozen=True, slots=True)
class AdapterMetadata:
    adapter_id: str
    model_id: str
    model_revision: str
    runtime: str
    calibration_supported: bool


@dataclass(frozen=True, slots=True)
class CalibrationRequest:
    calibration_id: str

    def __post_init__(self) -> None:
        if not self.calibration_id:
            raise ValueError("calibration_id must not be empty")


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    calibration_id: str
    valid: bool
    reason: str | None

    def __post_init__(self) -> None:
        if not self.calibration_id:
            raise ValueError("calibration_id must not be empty")
        if self.valid and self.reason is not None:
            raise ValueError("a valid calibration result cannot have a reason")
        if not self.valid and not self.reason:
            raise ValueError("an invalid calibration result requires a reason")


@runtime_checkable
class GazeFrameContext(Protocol):
    """The capture-time fields Eye needs from the richer Kiosk FrameContext."""

    session_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int


@dataclass(frozen=True, slots=True)
class GazeSample:
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
    calibration_id: str
    valid: bool
    confidence: float
    reason: str | None
    screen_x_norm: float | None = None
    screen_y_norm: float | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("schema_version must be '1.0'")
        if self.sequence < 0 or self.video_time_ms < 0 or self.playback_epoch < 0:
            raise ValueError("sequence and video time fields must be non-negative")
        if self.captured_at_mono_ms < 0:
            raise ValueError("captured_at_mono_ms must be non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        coordinates = (self.screen_x_norm, self.screen_y_norm)
        if self.valid:
            if any(value is None for value in coordinates):
                raise ValueError("valid gaze samples require both screen coordinates")
            if self.reason is not None:
                raise ValueError("valid gaze samples cannot have a reason")
            if any(not 0.0 <= value <= 1.0 for value in coordinates if value is not None):
                raise ValueError("screen coordinates must be between 0.0 and 1.0")
        else:
            if any(value is not None for value in coordinates):
                raise ValueError("invalid gaze samples cannot contain screen coordinates")
            if not self.reason:
                raise ValueError("invalid gaze samples require a reason")

    def to_payload(self) -> dict[str, object]:
        """Return the exact JSON shape accepted by gaze-sample Contract v1."""

        payload: dict[str, object] = {
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
            "calibration_id": self.calibration_id,
            "valid": self.valid,
            "confidence": self.confidence,
            "reason": self.reason,
        }
        if self.valid:
            payload["screen_x_norm"] = self.screen_x_norm
            payload["screen_y_norm"] = self.screen_y_norm
        return payload


@runtime_checkable
class EyeAdapter(Protocol, Generic[FrameT]):
    def metadata(self) -> AdapterMetadata: ...

    def initialize(self) -> None: ...

    def warmup(self) -> None: ...

    def calibrate(self, request: CalibrationRequest) -> CalibrationResult: ...

    def infer(self, frame_ref: FrameT, context: GazeFrameContext) -> GazeSample: ...

    def dispose(self) -> None: ...

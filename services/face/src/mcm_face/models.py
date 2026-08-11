"""Typed values shared by Face Adapter implementations."""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class FrameContext:
    """Capture-time metadata supplied by the Kiosk FrameSource."""

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
    model_revision: str
    taxonomy_version: str
    runtime: str


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

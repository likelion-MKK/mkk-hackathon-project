"""Fail-closed ExpressionSample construction shared by D6 components."""

from __future__ import annotations

import hashlib

from mcm_face.models import AdapterMetadata, ExpressionSample, FaceFrameContext


def event_id(metadata: AdapterMetadata, context: FaceFrameContext) -> str:
    material = "|".join(
        (
            metadata.adapter_id,
            metadata.model_revision,
            metadata.taxonomy_version,
            context.session_id,
            str(context.sequence),
            context.frame_id,
            str(context.captured_at_mono_ms),
            context.video_id,
            str(context.video_time_ms),
            str(context.playback_epoch),
        )
    )
    return f"expression-{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def invalid_sample(
    metadata: AdapterMetadata,
    context: FaceFrameContext,
    *,
    reason: str,
    face_count: int = 0,
    quality: float = 0.0,
    confidence: float = 0.0,
) -> ExpressionSample:
    """Create an explicit invalid sample without raw-frame information."""

    return ExpressionSample(
        schema_version="1.0",
        session_id=context.session_id,
        event_id=event_id(metadata, context),
        sequence=context.sequence,
        frame_id=context.frame_id,
        captured_at_mono_ms=context.captured_at_mono_ms,
        video_id=context.video_id,
        video_time_ms=context.video_time_ms,
        playback_epoch=context.playback_epoch,
        producer_id=metadata.adapter_id,
        model_revision=metadata.model_revision,
        taxonomy_version=metadata.taxonomy_version,
        face_detected=face_count > 0,
        face_count=face_count,
        scores={},
        quality=max(0.0, min(1.0, quality)),
        valid=False,
        confidence=max(0.0, min(1.0, confidence)),
        reason=reason,
    )

"""Deterministic Face Adapter used for development and contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Generic, TypeVar

from mcm_face.models import AdapterMetadata, ExpressionSample, FaceFrameContext


FrameT = TypeVar("FrameT")


class FakeFaceScenario(StrEnum):
    """Explicit fake outcomes supported by the deterministic adapter."""

    VALID_FACE = "valid_face"
    NO_FACE = "no_face"
    MULTI_FACE = "multi_face"
    UNKNOWN_LABEL = "unknown_label"
    LOW_QUALITY = "low_quality"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class _ScenarioResult:
    face_detected: bool
    face_count: int
    scores: dict[str, float]
    quality: float
    valid: bool
    confidence: float
    reason: str | None


class FakeFaceAdapter(Generic[FrameT]):
    """Produce repeatable ExpressionSample values without a model or camera."""

    _METADATA = AdapterMetadata(
        adapter_id="fake-face-adapter",
        model_id="fake-face-model",
        model_revision="fake-face-model-v1",
        taxonomy_version="fake-face-taxonomy-v1",
        runtime="python",
        source_labels=("smile_like", "brow_raise_like", "unmapped_fixture_label"),
    )

    def __init__(
        self,
        *,
        seed: int = 0,
        scenario: FakeFaceScenario | str = FakeFaceScenario.VALID_FACE,
    ) -> None:
        self._seed = seed
        self._scenario = FakeFaceScenario(scenario)
        self._initialized = False
        self._disposed = False

    def metadata(self) -> AdapterMetadata:
        return self._METADATA

    def initialize(self) -> None:
        """Enter the ready state; calling it repeatedly is safe."""

        self._initialized = True
        self._disposed = False

    def warmup(self) -> None:
        """Validate readiness without loading any model resources."""

        self._require_ready()

    def infer(self, frame: FrameT, context: FaceFrameContext) -> ExpressionSample:
        """Return a derived sample and never retain or inspect the frame object."""

        self._require_ready()
        del frame

        result = self._scenario_result(context)
        metadata = self.metadata()
        return ExpressionSample(
            schema_version="1.0",
            session_id=context.session_id,
            event_id=self._event_id(context),
            sequence=context.sequence,
            frame_id=context.frame_id,
            captured_at_mono_ms=context.captured_at_mono_ms,
            video_id=context.video_id,
            video_time_ms=context.video_time_ms,
            playback_epoch=context.playback_epoch,
            producer_id=metadata.adapter_id,
            model_revision=metadata.model_revision,
            taxonomy_version=metadata.taxonomy_version,
            face_detected=result.face_detected,
            face_count=result.face_count,
            scores=result.scores,
            quality=result.quality,
            valid=result.valid,
            confidence=result.confidence,
            reason=result.reason,
        )

    def dispose(self) -> None:
        """Enter the disposed state; calling it repeatedly is safe."""

        self._initialized = False
        self._disposed = True

    def _require_ready(self) -> None:
        if not self._initialized or self._disposed:
            raise RuntimeError("FakeFaceAdapter is not initialized")

    def _event_id(self, context: FaceFrameContext) -> str:
        material = "|".join(
            (
                str(self._seed),
                self._scenario.value,
                context.session_id,
                str(context.sequence),
                context.frame_id,
                str(context.captured_at_mono_ms),
                context.video_id,
                str(context.video_time_ms),
                str(context.playback_epoch),
            )
        )
        digest = sha256(material.encode("utf-8")).hexdigest()[:24]
        return f"expression-fake-{digest}"

    def _scenario_result(self, context: FaceFrameContext) -> _ScenarioResult:
        primary = self._normalized_value(context, "primary", lower=0.55, upper=0.9)
        secondary = round(1.0 - primary, 6)

        if self._scenario is FakeFaceScenario.VALID_FACE:
            return _ScenarioResult(
                face_detected=True,
                face_count=1,
                scores={"smile_like": primary, "brow_raise_like": secondary},
                quality=self._normalized_value(context, "quality", lower=0.75, upper=0.95),
                valid=True,
                confidence=self._normalized_value(
                    context, "confidence", lower=0.7, upper=0.95
                ),
                reason=None,
            )

        if self._scenario is FakeFaceScenario.UNKNOWN_LABEL:
            return _ScenarioResult(
                face_detected=True,
                face_count=1,
                scores={"unknown": primary},
                quality=self._normalized_value(context, "quality", lower=0.6, upper=0.85),
                valid=True,
                confidence=self._normalized_value(
                    context, "confidence", lower=0.5, upper=0.8
                ),
                reason=None,
            )

        if self._scenario is FakeFaceScenario.NO_FACE:
            return self._invalid_result(False, 0, 0.0, 0.0, "no_face")
        if self._scenario is FakeFaceScenario.MULTI_FACE:
            return self._invalid_result(True, 2, 0.5, 0.8, "multi_face")
        if self._scenario is FakeFaceScenario.LOW_QUALITY:
            return self._invalid_result(True, 1, 0.1, 0.2, "low_quality")
        return self._invalid_result(False, 0, 0.0, 0.0, "timeout")

    @staticmethod
    def _invalid_result(
        face_detected: bool,
        face_count: int,
        quality: float,
        confidence: float,
        reason: str,
    ) -> _ScenarioResult:
        return _ScenarioResult(
            face_detected=face_detected,
            face_count=face_count,
            scores={},
            quality=quality,
            valid=False,
            confidence=confidence,
            reason=reason,
        )

    def _normalized_value(
        self,
        context: FaceFrameContext,
        name: str,
        *,
        lower: float,
        upper: float,
    ) -> float:
        material = (
            f"{self._seed}|{self._scenario.value}|{context.session_id}|"
            f"{context.frame_id}|{context.sequence}|{name}"
        )
        digest = sha256(material.encode("utf-8")).digest()
        ratio = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
        return round(lower + ((upper - lower) * ratio), 6)

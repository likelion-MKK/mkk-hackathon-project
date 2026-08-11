"""Deterministic Eye Adapter for local development and CI."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable
from enum import Enum
from typing import Generic, TypeVar

from ..contracts import (
    AdapterMetadata,
    AdapterStateError,
    CalibrationRequest,
    CalibrationResult,
    GazeFrameContext,
    GazeSample,
)

FrameT = TypeVar("FrameT")
Sleeper = Callable[[float], None]


class FakeScenario(str, Enum):
    NORMAL = "normal"
    NO_FACE = "no_face"
    LOW_CONFIDENCE = "low_confidence"
    OUTSIDE_VIEWPORT = "outside_viewport"
    DELAYED = "delayed"
    OUT_OF_ORDER = "out_of_order"


class FakeEyeAdapter(Generic[FrameT]):
    PRODUCER_ID = "fake-eye-adapter"
    MODEL_REVISION = "fixture-v1"
    DEFAULT_CALIBRATION_ID = "fake-calibration-default"

    _METADATA = AdapterMetadata(
        adapter_id=PRODUCER_ID,
        model_id="fake-eye-model",
        model_revision=MODEL_REVISION,
        runtime="python",
        calibration_supported=True,
    )

    def __init__(
        self,
        scenario: FakeScenario | str = FakeScenario.NORMAL,
        *,
        seed: int = 0,
        delay_ms: int = 0,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an integer")
        if isinstance(delay_ms, bool) or not isinstance(delay_ms, int):
            raise TypeError("delay_ms must be an integer")
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")

        self._scenario = FakeScenario(scenario)
        self._seed = seed
        self._delay_ms = delay_ms
        self._sleeper = sleeper
        self._initialized = False
        self._calibration_id = self.DEFAULT_CALIBRATION_ID

    def metadata(self) -> AdapterMetadata:
        return self._METADATA

    def initialize(self) -> None:
        if not self._initialized:
            self._calibration_id = self.DEFAULT_CALIBRATION_ID
            self._initialized = True

    def warmup(self) -> None:
        self._require_initialized()

    def calibrate(self, request: CalibrationRequest) -> CalibrationResult:
        self._require_initialized()
        self._calibration_id = request.calibration_id
        return CalibrationResult(
            calibration_id=request.calibration_id,
            valid=True,
            reason=None,
        )

    def infer(self, frame_ref: FrameT, context: GazeFrameContext) -> GazeSample:
        self._require_initialized()
        del frame_ref  # The fake never stores, serializes, or logs the frame reference.

        if self._scenario is FakeScenario.DELAYED and self._delay_ms:
            self._sleeper(self._delay_ms / 1000.0)

        output_sequence = (
            context.sequence ^ 1
            if self._scenario is FakeScenario.OUT_OF_ORDER
            else context.sequence
        )
        event_id = self._event_id(context, output_sequence)

        if self._scenario is FakeScenario.NO_FACE:
            return self._invalid_sample(context, event_id, output_sequence, 0.0, "no_face")
        if self._scenario is FakeScenario.LOW_CONFIDENCE:
            return self._invalid_sample(
                context,
                event_id,
                output_sequence,
                0.2,
                "low_confidence",
            )
        if self._scenario is FakeScenario.OUTSIDE_VIEWPORT:
            return self._invalid_sample(
                context,
                event_id,
                output_sequence,
                0.0,
                "outside_viewport",
            )

        screen_x_norm, screen_y_norm = self._coordinates(context)
        return GazeSample(
            **self._common_fields(context, event_id, output_sequence),
            valid=True,
            confidence=0.9,
            reason=None,
            screen_x_norm=screen_x_norm,
            screen_y_norm=screen_y_norm,
        )

    def dispose(self) -> None:
        self._initialized = False
        self._calibration_id = self.DEFAULT_CALIBRATION_ID

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise AdapterStateError("FakeEyeAdapter must be initialized before use")

    def _identity(self, context: GazeFrameContext, output_sequence: int) -> str:
        return "\x1f".join(
            (
                self.PRODUCER_ID,
                self._scenario.value,
                str(self._seed),
                context.session_id,
                context.frame_id,
                str(context.captured_at_mono_ms),
                context.video_id,
                str(context.video_time_ms),
                str(context.playback_epoch),
                str(output_sequence),
            )
        )

    def _event_id(self, context: GazeFrameContext, output_sequence: int) -> str:
        deterministic_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            self._identity(context, output_sequence),
        )
        return f"gaze-{deterministic_id}"

    def _coordinates(self, context: GazeFrameContext) -> tuple[float, float]:
        digest = hashlib.sha256(
            self._identity(context, context.sequence).encode("utf-8")
        ).digest()
        denominator = float((1 << 64) - 1)
        screen_x_norm = int.from_bytes(digest[:8], "big") / denominator
        screen_y_norm = int.from_bytes(digest[8:16], "big") / denominator
        return screen_x_norm, screen_y_norm

    def _common_fields(
        self,
        context: GazeFrameContext,
        event_id: str,
        output_sequence: int,
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "session_id": context.session_id,
            "event_id": event_id,
            "sequence": output_sequence,
            "frame_id": context.frame_id,
            "captured_at_mono_ms": context.captured_at_mono_ms,
            "video_id": context.video_id,
            "video_time_ms": context.video_time_ms,
            "playback_epoch": context.playback_epoch,
            "producer_id": self.PRODUCER_ID,
            "model_revision": self.MODEL_REVISION,
            "calibration_id": self._calibration_id,
        }

    def _invalid_sample(
        self,
        context: GazeFrameContext,
        event_id: str,
        output_sequence: int,
        confidence: float,
        reason: str,
    ) -> GazeSample:
        return GazeSample(
            **self._common_fields(context, event_id, output_sequence),
            valid=False,
            confidence=confidence,
            reason=reason,
        )

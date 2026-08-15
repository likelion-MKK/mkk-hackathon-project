"""Deterministic replay adapter for derived GazeSample fixtures."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Generic, TypeVar

from ..contracts import (
    AdapterMetadata,
    CalibrationRequest,
    CalibrationResult,
    GazeFrameContext,
    GazeSample,
)


FrameT = TypeVar("FrameT")
_ContextKey = tuple[str, int, str, float, str, int, int]

_FIXTURE_FIELDS = frozenset(("fixture_revision", "records"))
_RECORD_FIELDS = frozenset(
    (
        "screen_x_norm",
        "screen_y_norm",
        "valid",
        "confidence",
        "reason",
    )
)


class ReplayExhaustedError(RuntimeError):
    """Raised when every replay gaze record has already been consumed."""


@dataclass(frozen=True, slots=True)
class ReplayGazeRecord:
    """One immutable, derived gaze result without capture context or frames."""

    screen_x_norm: float | None
    screen_y_norm: float | None
    valid: bool
    confidence: float
    reason: str | None

    def __post_init__(self) -> None:
        try:
            validated = GazeSample(
                schema_version="1.0",
                session_id="replay-validation-session",
                event_id="replay-validation-event",
                sequence=0,
                frame_id="replay-validation-frame",
                captured_at_mono_ms=0.0,
                video_id="replay-validation-video",
                video_time_ms=0,
                playback_epoch=0,
                producer_id="replay-eye-adapter",
                model_revision="replay-validation-revision",
                calibration_id="replay-validation-calibration",
                valid=self.valid,
                confidence=self.confidence,
                reason=self.reason,
                screen_x_norm=self.screen_x_norm,
                screen_y_norm=self.screen_y_norm,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(str(error)) from None

        object.__setattr__(self, "screen_x_norm", validated.screen_x_norm)
        object.__setattr__(self, "screen_y_norm", validated.screen_y_norm)


class ReplayEyeAdapter(Generic[FrameT]):
    """Replay gaze records in fixture order without retaining frame data."""

    _ADAPTER_ID = "replay-eye-adapter"
    _MODEL_ID = "replay-gaze-fixture"
    _RUNTIME = "python"

    def __init__(
        self,
        *,
        fixture_revision: str,
        records: Iterable[ReplayGazeRecord],
    ) -> None:
        prepared_records = tuple(records)
        if not fixture_revision:
            raise ValueError("fixture_revision must not be empty")
        if not prepared_records:
            raise ValueError("records must contain at least one replay record")
        for index, record in enumerate(prepared_records):
            if not isinstance(record, ReplayGazeRecord):
                raise ValueError(f"records[{index}] must be a ReplayGazeRecord")

        self._records = prepared_records
        self._metadata = AdapterMetadata(
            adapter_id=self._ADAPTER_ID,
            model_id=self._MODEL_ID,
            model_revision=fixture_revision,
            runtime=self._RUNTIME,
            calibration_supported=True,
        )
        self._cursor = 0
        self._samples_by_context: dict[_ContextKey, GazeSample] = {}
        self._initialized = False
        self._disposed = False
        self._calibration_id = "replay-calibration-default"

    @classmethod
    def from_fixture(cls, path: str | Path) -> ReplayEyeAdapter[Any]:
        """Load and validate a derived-only JSON replay fixture."""

        fixture_path = Path(path)
        try:
            document = json.loads(fixture_path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ValueError(f"could not read replay fixture: {error}") from None
        except json.JSONDecodeError as error:
            raise ValueError(
                f"invalid replay fixture JSON at line {error.lineno}, column {error.colno}"
            ) from None

        if not isinstance(document, dict):
            raise ValueError("replay fixture root must be an object")
        cls._validate_fields(document, _FIXTURE_FIELDS, "replay fixture root")

        fixture_revision = document["fixture_revision"]
        if not isinstance(fixture_revision, str) or not fixture_revision:
            raise ValueError("fixture_revision must be a non-empty string")

        raw_records = document["records"]
        if not isinstance(raw_records, list) or not raw_records:
            raise ValueError("records must be a non-empty array")

        records: list[ReplayGazeRecord] = []
        for index, raw_record in enumerate(raw_records):
            location = f"records[{index}]"
            if not isinstance(raw_record, dict):
                raise ValueError(f"{location} must be an object")
            cls._validate_fields(raw_record, _RECORD_FIELDS, location)
            try:
                records.append(ReplayGazeRecord(**raw_record))
            except (TypeError, ValueError) as error:
                raise ValueError(f"{location} is invalid: {error}") from None

        return cls(fixture_revision=fixture_revision, records=records)

    @staticmethod
    def _validate_fields(
        value: Mapping[str, object], expected: frozenset[str], location: str
    ) -> None:
        actual = set(value)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing:
            raise ValueError(f"{location} is missing fields: {', '.join(missing)}")
        if unexpected:
            raise ValueError(f"{location} contains unexpected fields: {', '.join(unexpected)}")

    def metadata(self) -> AdapterMetadata:
        return self._metadata

    def initialize(self) -> None:
        if self._initialized and not self._disposed:
            return
        self._cursor = 0
        self._samples_by_context.clear()
        self._calibration_id = "replay-calibration-default"
        self._initialized = True
        self._disposed = False

    def warmup(self) -> None:
        self._require_ready()

    def calibrate(self, request: CalibrationRequest) -> CalibrationResult:
        self._require_ready()
        self._calibration_id = request.calibration_id
        return CalibrationResult(
            calibration_id=request.calibration_id,
            valid=True,
            reason=None,
        )

    def infer(self, frame: FrameT, context: GazeFrameContext) -> GazeSample:
        """Replay one record idempotently for each capture-time context."""

        del frame
        self._require_ready()

        context_key = self._context_key(context)
        cached_sample = self._samples_by_context.get(context_key)
        if cached_sample is not None:
            return cached_sample

        if self._cursor >= len(self._records):
            raise ReplayExhaustedError(
                f"ReplayEyeAdapter exhausted after {len(self._records)} records"
            )

        record_index = self._cursor
        record = self._records[record_index]
        sample = GazeSample(
            schema_version="1.0",
            session_id=context.session_id,
            event_id=self._event_id(record_index, context),
            sequence=context.sequence,
            frame_id=context.frame_id,
            captured_at_mono_ms=context.captured_at_mono_ms,
            video_id=context.video_id,
            video_time_ms=context.video_time_ms,
            playback_epoch=context.playback_epoch,
            producer_id=self._metadata.adapter_id,
            model_revision=self._metadata.model_revision,
            calibration_id=self._calibration_id,
            valid=record.valid,
            confidence=record.confidence,
            reason=record.reason,
            screen_x_norm=record.screen_x_norm,
            screen_y_norm=record.screen_y_norm,
        )
        self._samples_by_context[context_key] = sample
        self._cursor += 1
        return sample

    def dispose(self) -> None:
        self._samples_by_context.clear()
        self._initialized = False
        self._disposed = True

    def _require_ready(self) -> None:
        if not self._initialized or self._disposed:
            raise RuntimeError("ReplayEyeAdapter is not initialized")

    @staticmethod
    def _context_key(context: GazeFrameContext) -> _ContextKey:
        return (
            context.session_id,
            context.sequence,
            context.frame_id,
            context.captured_at_mono_ms,
            context.video_id,
            context.video_time_ms,
            context.playback_epoch,
        )

    def _event_id(self, record_index: int, context: GazeFrameContext) -> str:
        material = "|".join(
            (
                self._metadata.adapter_id,
                self._metadata.model_id,
                self._metadata.model_revision,
                self._calibration_id,
                str(record_index),
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
        return f"gaze-replay-{digest}"

"""Deterministic replay adapter for derived Face observation fixtures."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from mcm_face.models import AdapterMetadata, ExpressionSample, FaceFrameContext


FrameT = TypeVar("FrameT")
_ContextKey = tuple[str, int, str, float, str, int, int]

_FIXTURE_FIELDS = frozenset(("fixture_revision", "records"))
_RECORD_FIELDS = frozenset(
    (
        "face_detected",
        "face_count",
        "scores",
        "quality",
        "valid",
        "confidence",
        "reason",
    )
)


class ReplayExhaustedError(RuntimeError):
    """Raised when every replay fixture record has already been consumed."""


@dataclass(frozen=True, slots=True)
class ReplayFaceRecord:
    """One immutable, derived Face observation without capture context."""

    face_detected: bool
    face_count: int
    scores: Mapping[str, float]
    quality: float
    valid: bool
    confidence: float
    reason: str | None

    def __post_init__(self) -> None:
        scores = dict(self.scores) if isinstance(self.scores, Mapping) else self.scores
        try:
            validated = ExpressionSample(
                schema_version="1.0",
                session_id="replay-validation-session",
                event_id="replay-validation-event",
                sequence=0,
                frame_id="replay-validation-frame",
                captured_at_mono_ms=0.0,
                video_id="replay-validation-video",
                video_time_ms=0,
                playback_epoch=0,
                producer_id="replay-face-adapter",
                model_revision="replay-validation-revision",
                taxonomy_version="replay-face-taxonomy-v1",
                face_detected=self.face_detected,
                face_count=self.face_count,
                scores=scores,
                quality=self.quality,
                valid=self.valid,
                confidence=self.confidence,
                reason=self.reason,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(str(error)) from None

        if self.reason == "no_face" and (
            self.face_detected
            or self.face_count != 0
            or self.valid
            or bool(validated.scores)
        ):
            raise ValueError("reason=no_face requires an undetected, invalid empty-score record")

        object.__setattr__(self, "scores", MappingProxyType(dict(validated.scores)))


class ReplayFaceAdapter(Generic[FrameT]):
    """Replay derived Face records in fixture order without retaining frames."""

    _ADAPTER_ID = "replay-face-adapter"
    _MODEL_ID = "replay-expression-fixture"
    _TAXONOMY_VERSION = "replay-face-taxonomy-v1"
    _RUNTIME = "python"

    def __init__(
        self,
        *,
        fixture_revision: str,
        records: Iterable[ReplayFaceRecord],
    ) -> None:
        prepared_records = tuple(records)
        if not prepared_records:
            raise ValueError("records must contain at least one replay record")
        for index, record in enumerate(prepared_records):
            if not isinstance(record, ReplayFaceRecord):
                raise ValueError(f"records[{index}] must be a ReplayFaceRecord")

        source_labels = tuple(
            sorted({label for record in prepared_records for label in record.scores})
        )
        try:
            metadata = AdapterMetadata(
                adapter_id=self._ADAPTER_ID,
                model_id=self._MODEL_ID,
                model_revision=fixture_revision,
                taxonomy_version=self._TAXONOMY_VERSION,
                runtime=self._RUNTIME,
                source_labels=source_labels,
            )
        except ValueError as error:
            raise ValueError(f"fixture_revision is invalid: {error}") from None

        self._records = prepared_records
        self._metadata = metadata
        self._cursor = 0
        self._samples_by_context: dict[_ContextKey, ExpressionSample] = {}
        self._initialized = False
        self._disposed = False

    @classmethod
    def from_fixture(cls, path: str | Path) -> ReplayFaceAdapter[Any]:
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
        raw_records = document["records"]
        if not isinstance(raw_records, list) or not raw_records:
            raise ValueError("records must be a non-empty array")

        records: list[ReplayFaceRecord] = []
        for index, raw_record in enumerate(raw_records):
            location = f"records[{index}]"
            if not isinstance(raw_record, dict):
                raise ValueError(f"{location} must be an object")
            cls._validate_fields(raw_record, _RECORD_FIELDS, location)
            try:
                records.append(ReplayFaceRecord(**raw_record))
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
            raise ValueError(
                f"{location} contains unexpected fields: {', '.join(unexpected)}"
            )

    def metadata(self) -> AdapterMetadata:
        return self._metadata

    def initialize(self) -> None:
        """Enter ready state, resetting only on first or post-dispose initialization."""

        if self._initialized and not self._disposed:
            return
        self._cursor = 0
        self._samples_by_context.clear()
        self._initialized = True
        self._disposed = False

    def warmup(self) -> None:
        """Validate readiness without consuming a fixture record."""

        self._require_ready()

    def infer(self, frame: FrameT, context: FaceFrameContext) -> ExpressionSample:
        """Replay one record idempotently for each capture-time context."""

        del frame
        self._require_ready()

        context_key = self._context_key(context)
        cached_sample = self._samples_by_context.get(context_key)
        if cached_sample is not None:
            return cached_sample

        if self._cursor >= len(self._records):
            raise ReplayExhaustedError(
                f"ReplayFaceAdapter exhausted after {len(self._records)} records"
            )

        record_index = self._cursor
        record = self._records[record_index]
        metadata = self.metadata()
        sample = ExpressionSample(
            schema_version="1.0",
            session_id=context.session_id,
            event_id=self._event_id(record_index, context),
            sequence=context.sequence,
            frame_id=context.frame_id,
            captured_at_mono_ms=context.captured_at_mono_ms,
            video_id=context.video_id,
            video_time_ms=context.video_time_ms,
            playback_epoch=context.playback_epoch,
            producer_id=metadata.adapter_id,
            model_revision=metadata.model_revision,
            taxonomy_version=metadata.taxonomy_version,
            face_detected=record.face_detected,
            face_count=record.face_count,
            scores=record.scores,
            quality=record.quality,
            valid=record.valid,
            confidence=record.confidence,
            reason=record.reason,
        )
        self._samples_by_context[context_key] = sample
        self._cursor += 1
        return sample

    def dispose(self) -> None:
        """Enter disposed state; repeated calls are safe."""

        self._samples_by_context.clear()
        self._initialized = False
        self._disposed = True

    def _require_ready(self) -> None:
        if not self._initialized or self._disposed:
            raise RuntimeError("ReplayFaceAdapter is not initialized")

    @staticmethod
    def _context_key(context: FaceFrameContext) -> _ContextKey:
        return (
            context.session_id,
            context.sequence,
            context.frame_id,
            context.captured_at_mono_ms,
            context.video_id,
            context.video_time_ms,
            context.playback_epoch,
        )

    def _event_id(self, record_index: int, context: FaceFrameContext) -> str:
        metadata = self.metadata()
        material = "|".join(
            (
                metadata.adapter_id,
                metadata.model_id,
                metadata.model_revision,
                metadata.taxonomy_version,
                metadata.runtime,
                ",".join(metadata.source_labels),
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
        return f"expression-replay-{digest}"

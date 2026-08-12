"""Pydantic models for the Contract v1 API boundary.

The public JSON contracts remain the source of truth. These models provide
request-time validation and deliberately reject fields that are not part of
the public boundary.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Self, TypeAlias
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
REASON_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
LABEL_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"

Identifier = str
Revision = str
Reason = str


class ContractModel(BaseModel):
    """Base model that keeps API payloads closed by default."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validate_identifier(value: str, *, field_name: str = "identifier") -> str:
    if not 1 <= len(value) <= 128 or re.fullmatch(IDENTIFIER_PATTERN, value) is None:
        raise ValueError(f"{field_name} must match {IDENTIFIER_PATTERN}")
    return value


def _validate_reason(value: str) -> str:
    if not 1 <= len(value) <= 128 or re.fullmatch(REASON_PATTERN, value) is None:
        raise ValueError("reason must use lowercase letters, digits, underscores or hyphens")
    return value


class SessionCreate(ContractModel):
    kiosk_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    lookbook_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    consent_version: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)


class SessionCreated(ContractModel):
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    display_code: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    status: Literal["created", "collecting"]
    created_at: datetime


class Product(ContractModel):
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    display_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    image_url: str
    product_url: str
    qr_asset_path: str = Field(min_length=1, max_length=500)

    @field_validator("product_id")
    @classmethod
    def product_id_is_valid(cls, value: str) -> str:
        return _validate_identifier(value, field_name="product_id")

    @field_validator("image_url", "product_url")
    @classmethod
    def url_is_reference(cls, value: str, info: Any) -> str:
        parsed = urlparse(value)
        if parsed.scheme == "data":
            raise ValueError("inline data URLs are not accepted as product assets")
        if info.field_name == "product_url" and parsed.scheme not in {"http", "https"}:
            raise ValueError("product_url must be an HTTP or HTTPS URL")
        if info.field_name == "image_url" and not value:
            raise ValueError("image_url must not be empty")
        return value

    @field_validator("qr_asset_path")
    @classmethod
    def qr_asset_is_png(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*\.png", value):
            raise ValueError("qr_asset_path must point to a PNG asset")
        return value


class ProductCatalog(ContractModel):
    schema_version: Literal["1.0"]
    catalog_version: Revision = Field(min_length=1, max_length=64)
    products: list[Product] = Field(min_length=1)

    @model_validator(mode="after")
    def product_ids_are_unique(self) -> Self:
        ids = [product.product_id for product in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("product_id values must be unique")
        return self


class ManifestExposureShape(ContractModel):
    type: Literal["polygon"]
    points: list[tuple[float, float]] = Field(min_length=3)

    @field_validator("points")
    @classmethod
    def points_are_normalized(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for x, y in value:
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise ValueError("manifest polygon points must be normalized to 0..1")
        return value


class ManifestExposure(ContractModel):
    exposure_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=1)
    priority: int = Field(ge=0)
    shape: ManifestExposureShape

    @model_validator(mode="after")
    def time_range_is_forward(self) -> Self:
        if self.start_ms >= self.end_ms:
            raise ValueError("manifest exposure start_ms must be less than end_ms")
        return self


class LookbookManifest(ContractModel):
    schema_version: Literal["1.0"]
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    manifest_version: Revision = Field(min_length=1, max_length=64)
    coordinate_space: Literal["video_normalized"]
    exposures: list[ManifestExposure]

    @model_validator(mode="after")
    def exposure_ids_are_unique(self) -> Self:
        ids = [exposure.exposure_id for exposure in self.exposures]
        if len(ids) != len(set(ids)):
            raise ValueError("exposure_id values must be unique")
        return self


class ExpressionSample(ContractModel):
    schema_version: Literal["1.0"]
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    event_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    sequence: int = Field(ge=0)
    frame_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    captured_at_mono_ms: float = Field(ge=0)
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    video_time_ms: int = Field(ge=0)
    playback_epoch: int = Field(ge=0)
    producer_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    model_revision: Revision = Field(min_length=1, max_length=128)
    taxonomy_version: Revision = Field(min_length=1, max_length=128)
    face_detected: bool
    face_count: int = Field(ge=0)
    scores: dict[str, float]
    quality: float = Field(ge=0, le=1)
    valid: bool
    confidence: float = Field(ge=0, le=1)
    reason: Reason | None

    @field_validator("scores")
    @classmethod
    def score_labels_are_taxonomy_keys(cls, value: dict[str, float]) -> dict[str, float]:
        for label, score in value.items():
            if re.fullmatch(LABEL_PATTERN, label) is None:
                raise ValueError("expression score labels must be lowercase taxonomy keys")
            if not 0 <= score <= 1:
                raise ValueError("expression scores must be normalized to 0..1")
        return value

    @field_validator("reason")
    @classmethod
    def reason_is_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def preserve_face_and_validity_semantics(self) -> Self:
        if not self.face_detected and self.face_count != 0:
            raise ValueError("face_count must be 0 when face_detected is false")
        if self.face_detected and self.face_count < 1:
            raise ValueError("face_count must be at least 1 when a face is detected")
        if self.valid:
            if not self.face_detected or self.face_count != 1:
                raise ValueError("a valid expression sample requires exactly one detected face")
            if not self.scores or self.reason is not None:
                raise ValueError("a valid expression sample needs scores and a null reason")
        elif self.scores or self.reason is None:
            raise ValueError("an invalid expression sample needs empty scores and a reason")
        return self


class ProductAttentionCandidate(ContractModel):
    exposure_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    priority: int = Field(ge=0)


class ProductAttentionEvent(ContractModel):
    schema_version: Literal["1.0"]
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    event_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    sequence: int = Field(ge=0)
    frame_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    captured_at_mono_ms: float = Field(ge=0)
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    video_time_ms: int = Field(ge=0)
    playback_epoch: int = Field(ge=0)
    producer_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    model_revision: Revision = Field(min_length=1, max_length=128)
    manifest_version: Revision = Field(min_length=1, max_length=128)
    source_gaze_event_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    outside_video: bool
    video_x_norm: float | None = Field(default=None, ge=0, le=1)
    video_y_norm: float | None = Field(default=None, ge=0, le=1)
    candidates: list[ProductAttentionCandidate] = Field(max_length=32)
    valid: bool
    confidence: float = Field(ge=0, le=1)
    reason: Reason | None

    @field_validator("reason")
    @classmethod
    def reason_is_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def preserve_attention_semantics(self) -> Self:
        if self.valid and self.reason is not None:
            raise ValueError("a valid attention event must have a null reason")
        if not self.valid:
            if self.video_x_norm is not None or self.video_y_norm is not None or self.candidates:
                raise ValueError("an invalid attention event cannot carry coordinates or candidates")
            if self.reason is None:
                raise ValueError("an invalid attention event needs a reason")
        if self.outside_video:
            if self.video_x_norm is not None or self.video_y_norm is not None or self.candidates:
                raise ValueError("an outside-video event cannot carry video coordinates or candidates")
        if self.valid and not self.outside_video:
            if self.video_x_norm is None or self.video_y_norm is None:
                raise ValueError("an in-video valid attention event needs video coordinates")
        return self


ReactionEvent: TypeAlias = ExpressionSample | ProductAttentionEvent


class ReactionBatch(ContractModel):
    schema_version: Literal["1.0"]
    batch_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    batch_sequence: int = Field(ge=0)
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    events: list[ReactionEvent] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def envelope_matches_events(self) -> Self:
        event_sessions = {event.session_id for event in self.events}
        event_videos = {event.video_id for event in self.events}
        event_ids = [event.event_id for event in self.events]
        sequences = [event.sequence for event in self.events]
        if event_sessions != {self.session_id}:
            raise ValueError("all event session_id values must match the batch envelope")
        if event_videos != {self.video_id}:
            raise ValueError("all event video_id values must match the batch envelope")
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event_id values must be unique within a batch")
        if len(sequences) != len(set(sequences)):
            raise ValueError("event sequence values must be unique within a batch")
        return self


class ReactionBatchAccepted(ContractModel):
    batch_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    status: Literal["accepted", "duplicate"]


class Health(ContractModel):
    status: Literal["ok", "degraded"]
    database: Literal["up", "down"]


class ErrorResponse(ContractModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)

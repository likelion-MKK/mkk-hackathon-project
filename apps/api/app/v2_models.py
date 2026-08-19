"""Closed Pydantic models mirroring the derived-signal v2 JSON contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator

from apps.api.app.schemas import (
    IDENTIFIER_PATTERN,
    LABEL_PATTERN,
    ContractModel,
    Identifier,
    Revision,
    ProductPart,
    _validate_reason,
)


ControlledTag = Literal[
    "backpack", "bold", "boston", "classic", "compact", "crossbody", "daily",
    "evening", "hobo", "leather", "lightweight", "minimal", "modern",
    "monogram", "neutral", "recycled_material", "shoulder", "shopper", "soft",
    "spacious", "sporty", "structured", "tambourine", "top_handle", "tote",
    "travel", "triangle", "weekender", "work",
]


def _unique(values: list[str], field_name: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} values must be unique")
    return values


class GazeObservationV2(ContractModel):
    screen_x_norm: StrictFloat = Field(ge=0, le=1)
    screen_y_norm: StrictFloat = Field(ge=0, le=1)
    confidence: StrictFloat = Field(ge=0, le=1)
    producer_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    model_revision: Revision = Field(min_length=1, max_length=128)
    calibration_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)


class ExpressionObservationV2(ContractModel):
    scores: dict[str, StrictFloat] = Field(min_length=1)
    quality: StrictFloat = Field(ge=0, le=1)
    confidence: StrictFloat = Field(ge=0, le=1)
    producer_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    model_revision: Revision = Field(min_length=1, max_length=128)
    taxonomy_version: Revision = Field(min_length=1, max_length=128)

    @field_validator("scores")
    @classmethod
    def scores_are_normalized(cls, value: dict[str, StrictFloat]) -> dict[str, StrictFloat]:
        for label, score in value.items():
            if re.fullmatch(LABEL_PATTERN, label) is None:
                raise ValueError("expression labels must be lowercase taxonomy keys")
            if not 0 <= score <= 1:
                raise ValueError("expression scores must be normalized to 0..1")
        return value


class AttentionCandidateV2(ContractModel):
    exposure_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    product_part: ProductPart | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    priority: StrictInt = Field(ge=0)


class AttentionObservationV2(ContractModel):
    outside_video: StrictBool
    video_x_norm: StrictFloat | None = Field(default=None, ge=0, le=1)
    video_y_norm: StrictFloat | None = Field(default=None, ge=0, le=1)
    confidence: StrictFloat = Field(ge=0, le=1)
    producer_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    model_revision: Revision = Field(min_length=1, max_length=128)
    manifest_version: Revision = Field(min_length=1, max_length=128)
    candidates: list[AttentionCandidateV2] = Field(max_length=32)

    @model_validator(mode="after")
    def preserve_coordinate_semantics(self) -> Self:
        if self.outside_video:
            if (
                "video_x_norm" in self.model_fields_set
                or "video_y_norm" in self.model_fields_set
                or self.candidates
            ):
                raise ValueError("outside-video attention cannot carry video coordinates or candidates")
        elif self.video_x_norm is None or self.video_y_norm is None:
            raise ValueError("in-video attention requires normalized video coordinates")
        return self


class GazeMovementV2(ContractModel):
    distance_norm: StrictFloat = Field(ge=0)
    speed_norm_per_s: StrictFloat = Field(ge=0)


class GazeDerivedV2(ContractModel):
    movement: GazeMovementV2 | None
    movement_reason: str | None
    continuous_observation_ms: StrictFloat = Field(ge=0)
    return_candidate: StrictBool | None
    return_candidate_reason: str | None

    @field_validator("movement_reason", "return_candidate_reason")
    @classmethod
    def reasons_are_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def require_value_xor_reason(self) -> Self:
        for value_name, reason_name in (
            ("movement", "movement_reason"),
            ("return_candidate", "return_candidate_reason"),
        ):
            if (getattr(self, value_name) is None) == (getattr(self, reason_name) is None):
                raise ValueError(f"derived gaze {value_name} must have a value or {reason_name}")
        return self


class SustainedActionV2(ContractModel):
    signal: str = Field(pattern=LABEL_PATTERN)
    duration_ms: StrictFloat = Field(ge=0)


class ExpressionDerivedV2(ContractModel):
    score_changes: dict[str, StrictFloat] | None
    score_change_rates_per_s: dict[str, StrictFloat] | None
    change_reason: str | None
    sustained_actions: list[SustainedActionV2] = Field(max_length=64)

    @field_validator("score_changes")
    @classmethod
    def score_changes_are_valid(cls, value: dict[str, StrictFloat] | None) -> dict[str, StrictFloat] | None:
        return None if value is None else ExpressionSummaryV2._validate_actions(value, lower=-1, upper=1)

    @field_validator("score_change_rates_per_s")
    @classmethod
    def score_rates_are_valid(cls, value: dict[str, StrictFloat] | None) -> dict[str, StrictFloat] | None:
        return None if value is None else ExpressionSummaryV2._validate_actions(value, lower=-1000, upper=1000)

    @field_validator("change_reason")
    @classmethod
    def change_reason_is_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def changes_have_joint_presence(self) -> Self:
        if (self.score_changes is None) != (self.score_change_rates_per_s is None):
            raise ValueError("expression change maps must be present or absent together")
        if (self.score_changes is None) == (self.change_reason is None):
            raise ValueError("expression changes must have maps or a change_reason")
        return self


class DerivedObservationV2(ContractModel):
    gaze: GazeDerivedV2 | None
    gaze_reason: str | None
    expression: ExpressionDerivedV2 | None
    expression_reason: str | None

    @field_validator("gaze_reason", "expression_reason")
    @classmethod
    def reasons_are_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def require_derived_xor_reason(self) -> Self:
        for value_name, reason_name in (("gaze", "gaze_reason"), ("expression", "expression_reason")):
            if (getattr(self, value_name) is None) == (getattr(self, reason_name) is None):
                raise ValueError(f"derived {value_name} must have a value or {reason_name}")
        return self


class FrameObservationV2(ContractModel):
    schema_version: Literal["2.0"]
    frame_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    sequence: StrictInt = Field(ge=0)
    captured_at_mono_ms: StrictFloat = Field(ge=0)
    session_offset_ms: StrictFloat = Field(ge=0)
    video_time_ms: StrictInt = Field(ge=0)
    playback_epoch: StrictInt = Field(ge=0)
    gaze: GazeObservationV2 | None
    gaze_reason: str | None
    attention: AttentionObservationV2 | None
    attention_reason: str | None
    expression: ExpressionObservationV2 | None
    expression_reason: str | None
    derived: DerivedObservationV2 | None
    derived_reason: str | None

    @field_validator("gaze_reason", "expression_reason", "attention_reason", "derived_reason")
    @classmethod
    def reasons_are_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def require_value_xor_reason(self) -> Self:
        for value_name, reason_name in (
            ("gaze", "gaze_reason"),
            ("attention", "attention_reason"),
            ("expression", "expression_reason"),
            ("derived", "derived_reason"),
        ):
            if (getattr(self, value_name) is None) == (getattr(self, reason_name) is None):
                raise ValueError(f"{value_name} must have exactly one of a value or {reason_name}")
        return self


class ObservationBatchV2(ContractModel):
    schema_version: Literal["2.0"]
    batch_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    batch_sequence: StrictInt = Field(ge=0)
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    observations: list[FrameObservationV2] = Field(min_length=1, max_length=256)


class ObservationBatchAcceptedV2(ContractModel):
    batch_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    status: Literal["accepted", "duplicate"]


class EyeSignalVersionV2(ContractModel):
    producer_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    model_revision: Revision = Field(min_length=1, max_length=128)


class FaceSignalVersionV2(EyeSignalVersionV2):
    taxonomy_version: Revision = Field(min_length=1, max_length=128)


class SignalVersionsV2(ContractModel):
    eye: EyeSignalVersionV2 | None
    eye_reason: str | None
    face: FaceSignalVersionV2 | None
    face_reason: str | None
    aoi_mapper_revision: Revision = Field(min_length=1, max_length=128)

    @field_validator("eye_reason", "face_reason")
    @classmethod
    def reasons_are_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def require_version_xor_reason(self) -> Self:
        for value_name, reason_name in (("eye", "eye_reason"), ("face", "face_reason")):
            if (getattr(self, value_name) is None) == (getattr(self, reason_name) is None):
                raise ValueError(f"{value_name} must have exactly one of a value or {reason_name}")
        return self


class RecommendationDataQualityV2(ContractModel):
    expected_observation_count: StrictInt = Field(ge=0)
    gaze_valid_ratio: StrictFloat = Field(ge=0, le=1)
    expression_valid_ratio: StrictFloat = Field(ge=0, le=1)
    matched_frame_ratio: StrictFloat = Field(ge=0, le=1)
    ambiguous_product_ratio: StrictFloat = Field(ge=0, le=1)


class GazeSummaryV2(ContractModel):
    valid_observation_count: StrictInt = Field(ge=0)
    observed_attention_ms: StrictFloat = Field(ge=0)
    attention_ratio: StrictFloat = Field(ge=0, le=1)
    average_confidence: StrictFloat = Field(ge=0, le=1)
    return_candidate_count: StrictInt | None = Field(ge=0)
    return_candidate_reason: str | None
    movement_distance_norm: StrictFloat | None = Field(ge=0)
    mean_speed_norm_per_s: StrictFloat | None = Field(ge=0)
    movement_reason: str | None

    @field_validator("return_candidate_reason", "movement_reason")
    @classmethod
    def reasons_are_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def unavailable_comparisons_have_reasons(self) -> Self:
        if (self.return_candidate_count is None) == (self.return_candidate_reason is None):
            raise ValueError("return_candidate_count must have a value or reason")
        movement_missing = self.movement_distance_norm is None
        if movement_missing != (self.mean_speed_norm_per_s is None):
            raise ValueError("movement distance and speed must be present or absent together")
        if movement_missing == (self.movement_reason is None):
            raise ValueError("movement summary must have values or a reason")
        return self


class ExpressionSummaryV2(ContractModel):
    matched_observation_count: StrictInt = Field(ge=0)
    valid_coverage: StrictFloat = Field(ge=0, le=1)
    action_changes: dict[str, StrictFloat] | None = Field(min_length=1)
    action_change_rates_per_s: dict[str, StrictFloat] | None = Field(min_length=1)
    change_reason: str | None
    sustained_actions: list[SustainedActionV2] = Field(max_length=64)

    @field_validator("action_changes")
    @classmethod
    def action_changes_are_valid(
        cls, value: dict[str, StrictFloat] | None
    ) -> dict[str, StrictFloat] | None:
        return None if value is None else cls._validate_actions(value, lower=-1, upper=1)

    @field_validator("action_change_rates_per_s")
    @classmethod
    def action_rates_are_valid(
        cls, value: dict[str, StrictFloat] | None
    ) -> dict[str, StrictFloat] | None:
        return None if value is None else cls._validate_actions(value, lower=-1000, upper=1000)

    @field_validator("change_reason")
    @classmethod
    def change_reason_is_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def unavailable_changes_have_reason(self) -> Self:
        if (self.action_changes is None) != (self.action_change_rates_per_s is None):
            raise ValueError("expression change maps must be present or absent together")
        if (self.action_changes is None) == (self.change_reason is None):
            raise ValueError("expression changes must have maps or a reason")
        return self

    @staticmethod
    def _validate_actions(
        value: dict[str, StrictFloat], *, lower: float, upper: float
    ) -> dict[str, StrictFloat]:
        for label, score in value.items():
            if re.fullmatch(LABEL_PATTERN, label) is None or not lower <= score <= upper:
                raise ValueError("face-action summary contains an invalid label or value")
        return value


class ProductEvidenceSummaryV2(ContractModel):
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    exposure_duration_ms: StrictFloat = Field(ge=0)
    gaze: GazeSummaryV2 | None
    gaze_reason: str | None
    expression: ExpressionSummaryV2 | None
    expression_reason: str | None

    @field_validator("gaze_reason", "expression_reason")
    @classmethod
    def reasons_are_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @model_validator(mode="after")
    def require_summary_xor_reason(self) -> Self:
        for value_name, reason_name in (("gaze", "gaze_reason"), ("expression", "expression_reason")):
            if (getattr(self, value_name) is None) == (getattr(self, reason_name) is None):
                raise ValueError(f"{value_name} must have exactly one of a value or {reason_name}")
        return self


EvidenceCode = Literal[
    "observed_attention", "return_candidate", "gaze_movement",
    "face_action_change", "data_quality",
]


class EvidenceWindowV2(ContractModel):
    window_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    product_part: ProductPart | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    start_offset_ms: StrictFloat = Field(ge=0)
    end_offset_ms: StrictFloat = Field(ge=0)
    video_start_ms: StrictInt = Field(ge=0)
    video_end_ms: StrictInt = Field(ge=0)
    playback_epoch: StrictInt = Field(ge=0)
    evidence_codes: list[EvidenceCode] = Field(min_length=1)

    @field_validator("evidence_codes")
    @classmethod
    def evidence_codes_are_unique(cls, value: list[str]) -> list[str]:
        return _unique(value, "evidence_codes")

    @model_validator(mode="after")
    def ranges_are_forward(self) -> Self:
        if self.end_offset_ms < self.start_offset_ms or self.video_end_ms < self.video_start_ms:
            raise ValueError("evidence window ranges must be forward")
        return self


class RecommendationEvidenceV2(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    decision_request_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    input_variant: Literal["A", "B", "C"]
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    manifest_version: Revision = Field(min_length=1, max_length=128)
    catalog_version: Revision = Field(min_length=1, max_length=128)
    feature_version: Revision = Field(min_length=1, max_length=128)
    signal_versions: SignalVersionsV2
    data_quality: RecommendationDataQualityV2
    summary: list[ProductEvidenceSummaryV2] = Field(min_length=1, max_length=10)
    evidence_windows: list[EvidenceWindowV2] | None = Field(default=None, min_length=1, max_length=128)
    timeline: list[FrameObservationV2] | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def variant_has_expected_payload(self) -> Self:
        expected = {"A": (True, True), "B": (False, True), "C": (True, False)}[
            self.input_variant
        ]
        actual = (self.evidence_windows is not None, self.timeline is not None)
        if actual != expected:
            raise ValueError("input_variant does not match evidence_windows/timeline presence")
        return self


class ProductStyleV2(ContractModel):
    silhouette: Literal["boxy", "cylindrical", "rounded", "slouchy", "trapezoid", "triangular"]
    visual_tone: Literal["bold", "casual", "classic", "minimal", "refined", "sporty"]
    use_cases: list[Literal["daily", "evening", "travel", "weekend", "work"]] = Field(
        min_length=1, max_length=5
    )

    @field_validator("use_cases")
    @classmethod
    def use_cases_are_unique(cls, value: list[str]) -> list[str]:
        return _unique(value, "use_cases")


class ProductRecommendationItemV2(ContractModel):
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    display_name: str = Field(min_length=1, max_length=160)
    category: Literal["bag"]
    controlled_tags: list[ControlledTag] = Field(min_length=3, max_length=12)
    recommendation_summary: str = Field(min_length=1, max_length=500)
    style: ProductStyleV2
    approved_asset: StrictBool
    source_status: Literal[
        "demo_placeholder",
        "official_listing_name_verified_assets_pending",
        "team_approved_catalog_record",
    ]
    official_product_url: str | None = Field(max_length=500)
    official_product_url_reason: str | None
    official_listing_url: str = Field(max_length=500)
    image_asset_path: str | None = Field(default=None, max_length=300)
    image_asset_path_reason: str | None
    qr_asset_path: str | None = Field(default=None, max_length=300)
    qr_asset_path_reason: str | None
    source_note: str = Field(min_length=1, max_length=500)

    @field_validator("controlled_tags")
    @classmethod
    def controlled_tags_are_unique(cls, value: list[str]) -> list[str]:
        return _unique(value, "controlled_tags")

    @field_validator(
        "official_product_url_reason",
        "image_asset_path_reason",
        "qr_asset_path_reason",
    )
    @classmethod
    def asset_reasons_are_normalized(cls, value: str | None) -> str | None:
        return None if value is None else _validate_reason(value)

    @field_validator("official_product_url", "official_listing_url")
    @classmethod
    def official_urls_are_http(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("official URLs must use HTTP or HTTPS")
        return value

    @field_validator("image_asset_path")
    @classmethod
    def image_asset_path_is_scoped(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(
            r"assets/products/[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9]+|/[A-Za-z0-9][A-Za-z0-9._-]*)*",
            value,
        ) is None:
            raise ValueError("image_asset_path must use the reviewed product asset directory")
        return value

    @field_validator("qr_asset_path")
    @classmethod
    def qr_asset_path_is_scoped(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(
            r"assets/qr/[A-Za-z0-9][A-Za-z0-9_-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*",
            value,
        ) is None:
            raise ValueError("qr_asset_path must use the reviewed QR asset directory")
        return value

    @model_validator(mode="after")
    def placeholder_is_not_approved(self) -> Self:
        if self.source_status in {
            "demo_placeholder",
            "official_listing_name_verified_assets_pending",
        } and self.approved_asset:
            raise ValueError("pending catalog records cannot use approved assets")
        for value_name, reason_name in (
            ("official_product_url", "official_product_url_reason"),
            ("image_asset_path", "image_asset_path_reason"),
            ("qr_asset_path", "qr_asset_path_reason"),
        ):
            if (getattr(self, value_name) is None) == (getattr(self, reason_name) is None):
                raise ValueError(f"{value_name} must have a value or {reason_name}")
        return self


class ProductRecommendationProfileV2(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    catalog_version: Revision = Field(min_length=1, max_length=128)
    products: list[ProductRecommendationItemV2] = Field(min_length=10, max_length=10)


class CentralRecommendationRequestV2(ContractModel):
    """Self-hosted transport envelope over reviewed, derived-only contracts.

    ``source_visual_evidence`` and ``matching_products`` are kept as closed JSON
    objects here to avoid a circular import with the authoritative AOI mapper.
    The store and central output gate revalidate them with their dedicated
    Pydantic models before use.
    """

    schema_version: Literal["2.0"] = "2.0"
    decision_request_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    prompt_version: Revision = Field(min_length=1, max_length=128)
    evidence_version: Revision = Field(min_length=1, max_length=128)
    evidence: RecommendationEvidenceV2
    products: list[ProductRecommendationItemV2] = Field(min_length=1, max_length=10)
    source_visual_evidence: dict[str, object] | None = None
    matching_products: list[dict[str, object]] | None = Field(default=None, min_length=10, max_length=10)

    @model_validator(mode="after")
    def source_matching_payloads_have_joint_presence(self) -> Self:
        if (self.source_visual_evidence is None) != (self.matching_products is None):
            raise ValueError(
                "source_visual_evidence and matching_products must be present or absent together"
            )
        return self


class EvidenceReferenceV2(ContractModel):
    kind: Literal["window", "frame"]
    ref_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)


class DecisionEvidenceItemV2(ContractModel):
    code: Literal[
        "observed_attention", "return_candidate", "gaze_movement",
        "face_action_change", "product_tag_match", "data_quality",
    ]
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    evidence_refs: list[EvidenceReferenceV2] = Field(min_length=1, max_length=12)
    statement: str = Field(min_length=1, max_length=240)

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_are_unique(
        cls, value: list[EvidenceReferenceV2]
    ) -> list[EvidenceReferenceV2]:
        keys = [(ref.kind, ref.ref_id) for ref in value]
        if len(keys) != len(set(keys)):
            raise ValueError("evidence_refs values must be unique")
        return value


class RecommendationStyleV2(ContractModel):
    matched_tags: list[ControlledTag] = Field(min_length=1, max_length=8)
    summary: str = Field(min_length=1, max_length=240)

    @field_validator("matched_tags")
    @classmethod
    def matched_tags_are_unique(cls, value: list[str]) -> list[str]:
        return _unique(value, "matched_tags")


class CentralRecommendationOutputV2(ContractModel):
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    reason: str = Field(min_length=1, max_length=400)
    reason_codes: list[Literal[
        "observed_attention_lead",
        "return_candidate_support",
        "movement_pattern_support",
        "observable_action_support",
        "catalog_tag_alignment",
        "sufficient_data_quality",
    ]] = Field(min_length=1, max_length=6)
    evidence: list[DecisionEvidenceItemV2] = Field(min_length=1, max_length=12)
    style: RecommendationStyleV2
    exploration_tendency_code: Literal[
        "focused_single_product", "comparative_exploration", "broad_exploration"
    ]

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_unique(cls, value: list[str]) -> list[str]:
        return _unique(value, "reason_codes")


class DecisionReasonV2(ContractModel):
    code: Literal[
        "grounded_product_match", "insufficient_valid_signal", "no_eligible_product",
        "model_unavailable", "invalid_model_output", "catalog_mismatch",
    ]
    explanation: str = Field(min_length=1, max_length=400)


class RecommendationVersionV2(ContractModel):
    model_id: str = Field(min_length=1, max_length=128)
    model_revision: Revision = Field(min_length=1, max_length=128)
    prompt_version: Revision = Field(min_length=1, max_length=128)
    feature_version: Revision = Field(min_length=1, max_length=128)
    catalog_version: Revision = Field(min_length=1, max_length=128)
    input_variant: Literal["A", "B", "C"]
    deployment_mode: Literal["self_hosted"]


class RecommendationDecisionV2(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    recommendation_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    decision_request_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    status: Literal["completed", "insufficient_data", "failed"]
    selected_product_id: Identifier | None = Field(
        default=None, min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN
    )
    reason: DecisionReasonV2
    reason_codes: list[Literal[
        "observed_attention_lead",
        "return_candidate_support",
        "movement_pattern_support",
        "observable_action_support",
        "catalog_tag_alignment",
        "sufficient_data_quality",
    ]] = Field(max_length=6)
    evidence: list[DecisionEvidenceItemV2] = Field(max_length=12)
    style: RecommendationStyleV2 | None
    exploration_tendency_code: Literal[
        "focused_single_product", "comparative_exploration", "broad_exploration"
    ] | None
    data_quality: RecommendationDataQualityV2
    version: RecommendationVersionV2

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_unique(cls, value: list[str]) -> list[str]:
        return _unique(value, "reason_codes")

    @model_validator(mode="after")
    def enforce_top_one(self) -> Self:
        if self.status == "completed":
            if (
                self.selected_product_id is None
                or self.reason.code != "grounded_product_match"
                or not self.reason_codes
                or not self.evidence
                or self.style is None
                or self.exploration_tendency_code is None
            ):
                raise ValueError("completed decisions require exactly one grounded product")
        elif (
            self.selected_product_id is not None
            or self.reason_codes
            or self.evidence
            or self.style is not None
            or self.exploration_tendency_code is not None
        ):
            raise ValueError("non-completed decisions cannot expose a product or style")
        if self.status == "insufficient_data" and self.reason.code not in {
            "insufficient_valid_signal", "no_eligible_product",
        }:
            raise ValueError("insufficient_data has an incompatible reason code")
        if self.status == "failed" and self.reason.code not in {
            "model_unavailable", "invalid_model_output", "catalog_mismatch",
        }:
            raise ValueError("failed has an incompatible reason code")
        expected_ref_kind = "frame" if self.version.input_variant == "B" else "window"
        if any(
            ref.kind != expected_ref_kind
            for item in self.evidence
            for ref in item.evidence_refs
        ):
            raise ValueError("evidence_refs kind does not match version.input_variant")
        return self


class RecommendationAcceptedV2(ContractModel):
    recommendation_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    decision_request_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    status: Literal["pending"]


class ManagerProductRequestV2(ContractModel):
    schema_version: Literal["2.0"]
    request_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    recommendation_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    selected_product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    intent: Literal["view_recommended_product"]


class ManagerEventPayloadV2(ContractModel):
    recommendation_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    selected_product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    intent: Literal["view_recommended_product"]


class ManagerEventV2(ContractModel):
    schema_version: Literal["2.0"]
    event_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    sequence: StrictInt = Field(ge=0)
    session_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    kiosk_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    event_type: Literal["customer_product_request"]
    emitted_at: datetime
    payload: ManagerEventPayloadV2

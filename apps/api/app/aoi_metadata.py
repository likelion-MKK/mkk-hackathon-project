"""Approved source-AOI metadata, authoritative hit testing, and feature evidence."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from pydantic import Field, StrictFloat, StrictInt, field_validator, model_validator

from apps.api.app.schemas import (
    IDENTIFIER_PATTERN,
    ContractModel,
    Identifier,
    LookbookManifest,
    ManifestExposure,
    Revision,
)
from apps.api.app.v2_models import FrameObservationV2


ColorFamily = Literal["beige", "black", "brown", "metallic", "pink", "unknown"]
Silhouette = Literal[
    "backpack",
    "boston",
    "east_west_shoulder",
    "pouch",
    "shopper",
    "tambourine",
    "tote",
    "vanity_case",
    "weekender",
]
CategoryType = Literal[
    "backpack",
    "crossbody_bag",
    "pouch",
    "shoulder_bag",
    "top_handle_bag",
    "tote_bag",
    "travel_bag",
    "vanity_case",
]
Pattern = Literal["crystal", "grained_leather", "monogram", "solid", "studded", "unknown"]
BagAccessory = Literal[
    "front_pocket",
    "lock",
    "logo_plaque",
    "shoulder_strap",
    "side_studs",
    "tag",
    "top_handle",
    "zipper",
]
ApprovalStatus = Literal["approved", "pending"]


class VisualFeaturesV1(ContractModel):
    color_primary: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    color_family: ColorFamily
    silhouette: Silhouette
    category_type: CategoryType
    patterns: list[Pattern] = Field(min_length=1, max_length=6)
    bag_accessories: list[BagAccessory] = Field(max_length=8)

    @field_validator("patterns", "bag_accessories")
    @classmethod
    def values_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("visual feature values must be unique")
        return value


class AoiApprovalV1(ContractModel):
    status: ApprovalStatus
    approved_by: str | None = Field(default=None, max_length=128)
    approved_at: str | None = Field(default=None, max_length=64)
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def approved_metadata_has_provenance(self) -> "AoiApprovalV1":
        if self.status == "approved" and (not self.approved_by or not self.approved_at):
            raise ValueError("approved AOI metadata requires approved_by and approved_at")
        if self.status == "pending" and (self.approved_by is not None or self.approved_at is not None):
            raise ValueError("pending AOI metadata cannot claim approval provenance")
        return self


class SourceAoiDefinitionV1(ContractModel):
    source_aoi_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    exposure_id_prefixes: list[str] = Field(min_length=1, max_length=32)
    visual_features: VisualFeaturesV1

    @field_validator("exposure_id_prefixes")
    @classmethod
    def prefixes_are_safe_and_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("exposure_id_prefixes must be unique")
        if any(not prefix or len(prefix) > 128 or not prefix.endswith(".") for prefix in value):
            raise ValueError("exposure_id_prefixes must be non-empty part prefixes ending in '.'")
        return value


class SourceAoiMetadataV1(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    manifest_version: Revision = Field(min_length=1, max_length=128)
    metadata_version: Revision = Field(min_length=1, max_length=128)
    feature_taxonomy_version: Revision = Field(min_length=1, max_length=128)
    approval: AoiApprovalV1
    source_aois: list[SourceAoiDefinitionV1] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def source_ids_and_prefixes_are_unique(self) -> "SourceAoiMetadataV1":
        source_ids = [item.source_aoi_id for item in self.source_aois]
        prefixes = [prefix for item in self.source_aois for prefix in item.exposure_id_prefixes]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_aoi_id values must be unique")
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("exposure prefixes must be globally unique")
        return self


class ProductMatchingItemV1(ContractModel):
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    display_name: str = Field(min_length=1, max_length=160)
    brand: Literal["MCM"]
    official_product_url: str = Field(min_length=1, max_length=500)
    recommendation_profile: VisualFeaturesV1
    controlled_tags: list[str] = Field(min_length=1, max_length=16)

    @field_validator("official_product_url")
    @classmethod
    def official_url_is_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("official_product_url must use HTTP or HTTPS")
        return value

    @field_validator("controlled_tags")
    @classmethod
    def tags_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("controlled_tags must be unique")
        return value


class ProductMatchingCatalogV1(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    catalog_version: Revision = Field(min_length=1, max_length=128)
    feature_taxonomy_version: Revision = Field(min_length=1, max_length=128)
    products: list[ProductMatchingItemV1] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def product_ids_are_unique(self) -> "ProductMatchingCatalogV1":
        ids = [product.product_id for product in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("matching catalog product_id values must be unique")
        return self


@dataclass(frozen=True, slots=True)
class BoundSourceAoi:
    exposure: ManifestExposure
    definition: SourceAoiDefinitionV1


@dataclass(frozen=True, slots=True)
class ResolvedSourceAoiHit:
    source_aoi_id: str
    exposure_ids: tuple[str, ...]
    product_parts: tuple[str, ...]
    visual_features: VisualFeaturesV1


class FeatureScoreV1(ContractModel):
    value: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    score: StrictInt = Field(ge=1)
    attention_ms: StrictFloat = Field(ge=0)
    source_aoi_ids: list[Identifier] = Field(min_length=1, max_length=64)


class SourceAoiEvidenceSummaryV1(ContractModel):
    source_aoi_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    hit_count: StrictInt = Field(ge=1)
    attention_ms: StrictFloat = Field(ge=0)
    return_count: StrictInt = Field(ge=0)
    frame_ids: list[Identifier] = Field(min_length=1, max_length=512)
    visual_features: VisualFeaturesV1


class SourceVisualEvidenceV1(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    metadata_version: Revision = Field(min_length=1, max_length=128)
    feature_taxonomy_version: Revision = Field(min_length=1, max_length=128)
    total_hit_count: StrictInt = Field(ge=1)
    ambiguous_frame_count: StrictInt = Field(ge=0)
    source_aois: list[SourceAoiEvidenceSummaryV1] = Field(min_length=1, max_length=64)
    color_primary_scores: list[FeatureScoreV1] = Field(min_length=1, max_length=32)
    color_family_scores: list[FeatureScoreV1] = Field(min_length=1, max_length=16)
    silhouette_scores: list[FeatureScoreV1] = Field(min_length=1, max_length=16)
    category_type_scores: list[FeatureScoreV1] = Field(min_length=1, max_length=16)
    pattern_scores: list[FeatureScoreV1] = Field(min_length=1, max_length=32)
    bag_accessory_scores: list[FeatureScoreV1] = Field(max_length=32)

    @property
    def grounded_frame_ids(self) -> frozenset[str]:
        return frozenset(frame_id for item in self.source_aois for frame_id in item.frame_ids)


@dataclass(slots=True)
class _MutableSourceSummary:
    definition: SourceAoiDefinitionV1
    frame_ids: list[str]
    attention_ms: float = 0.0
    return_count: int = 0


def load_source_aoi_metadata(repository_root: Path, video_id: str) -> SourceAoiMetadataV1 | None:
    path = repository_root / "data" / "lookbooks" / video_id / "aoi-metadata-v1.json"
    if not path.is_file():
        return None
    return SourceAoiMetadataV1.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_product_matching_catalog(repository_root: Path) -> ProductMatchingCatalogV1:
    path = repository_root / "data" / "products" / "mcm-recommendation-matching-profiles-v1.json"
    return ProductMatchingCatalogV1.model_validate(json.loads(path.read_text(encoding="utf-8")))


def bind_source_aois(
    manifest: LookbookManifest,
    metadata: SourceAoiMetadataV1,
) -> tuple[BoundSourceAoi, ...]:
    if metadata.video_id != manifest.video_id or metadata.manifest_version != manifest.manifest_version:
        raise ValueError("source AOI metadata does not match the lookbook manifest")
    bindings: list[BoundSourceAoi] = []
    for exposure in manifest.exposures:
        matches = [
            definition
            for definition in metadata.source_aois
            if any(exposure.exposure_id.startswith(prefix) for prefix in definition.exposure_id_prefixes)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"manifest exposure '{exposure.exposure_id}' must match exactly one source AOI"
            )
        bindings.append(BoundSourceAoi(exposure=exposure, definition=matches[0]))
    return tuple(bindings)


def _point_is_on_segment(
    x: float,
    y: float,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> bool:
    epsilon = 1e-9
    cross = (x - start_x) * (end_y - start_y) - (y - start_y) * (end_x - start_x)
    if abs(cross) > epsilon:
        return False
    return (
        min(start_x, end_x) - epsilon <= x <= max(start_x, end_x) + epsilon
        and min(start_y, end_y) - epsilon <= y <= max(start_y, end_y) + epsilon
    )


def point_is_inside_polygon(x: float, y: float, points: list[tuple[float, float]]) -> bool:
    inside = False
    previous = len(points) - 1
    for current, (current_x, current_y) in enumerate(points):
        previous_x, previous_y = points[previous]
        if _point_is_on_segment(x, y, previous_x, previous_y, current_x, current_y):
            return True
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            intersection_x = (
                (previous_x - current_x) * (y - current_y) / (previous_y - current_y)
                + current_x
            )
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def resolve_source_aoi_hits(
    observation: FrameObservationV2,
    bindings: tuple[BoundSourceAoi, ...],
) -> tuple[ResolvedSourceAoiHit, ...]:
    attention = observation.attention
    if attention is None or attention.outside_video:
        return ()
    assert attention.video_x_norm is not None and attention.video_y_norm is not None
    grouped: dict[str, list[BoundSourceAoi]] = defaultdict(list)
    for binding in bindings:
        exposure = binding.exposure
        if not (exposure.start_ms <= observation.video_time_ms < exposure.end_ms):
            continue
        if point_is_inside_polygon(
            attention.video_x_norm,
            attention.video_y_norm,
            exposure.shape.points,
        ):
            grouped[binding.definition.source_aoi_id].append(binding)
    return tuple(
        ResolvedSourceAoiHit(
            source_aoi_id=source_aoi_id,
            exposure_ids=tuple(sorted(item.exposure.exposure_id for item in items)),
            product_parts=tuple(
                sorted({item.exposure.product_part for item in items if item.exposure.product_part})
            ),
            visual_features=items[0].definition.visual_features,
        )
        for source_aoi_id, items in sorted(grouped.items())
    )


def build_source_visual_evidence(
    observations: Iterable[FrameObservationV2],
    resolved_hits: dict[tuple[int, str], tuple[ResolvedSourceAoiHit, ...]],
    metadata: SourceAoiMetadataV1,
) -> SourceVisualEvidenceV1 | None:
    ordered = sorted(
        observations,
        key=lambda item: (item.playback_epoch, item.captured_at_mono_ms, item.sequence, item.frame_id),
    )
    summaries: dict[str, _MutableSourceSummary] = {}
    ambiguous_frame_count = 0
    previous_frame: FrameObservationV2 | None = None
    previous_source_id: str | None = None
    seen_source_ids: set[str] = set()

    for frame in ordered:
        hits = resolved_hits.get((frame.playback_epoch, frame.frame_id), ())
        discontinuity = (
            previous_frame is None
            or frame.playback_epoch != previous_frame.playback_epoch
            or frame.video_time_ms < previous_frame.video_time_ms
            or frame.sequence <= previous_frame.sequence
            or frame.captured_at_mono_ms - previous_frame.captured_at_mono_ms <= 0
            or frame.captured_at_mono_ms - previous_frame.captured_at_mono_ms > 1_000
        )
        if discontinuity:
            previous_source_id = None
            seen_source_ids = set()
        if len(hits) > 1:
            ambiguous_frame_count += 1
            previous_source_id = None
            previous_frame = frame
            continue
        if len(hits) == 1:
            hit = hits[0]
            summary = summaries.setdefault(
                hit.source_aoi_id,
                _MutableSourceSummary(
                    definition=next(
                        item for item in metadata.source_aois if item.source_aoi_id == hit.source_aoi_id
                    ),
                    frame_ids=[],
                ),
            )
            summary.frame_ids.append(frame.frame_id)
            if previous_source_id == hit.source_aoi_id and previous_frame is not None and not discontinuity:
                summary.attention_ms += frame.captured_at_mono_ms - previous_frame.captured_at_mono_ms
            elif hit.source_aoi_id in seen_source_ids:
                summary.return_count += 1
            seen_source_ids.add(hit.source_aoi_id)
            previous_source_id = hit.source_aoi_id
        else:
            previous_source_id = None
        previous_frame = frame

    if not summaries:
        return None

    source_summaries = [
        SourceAoiEvidenceSummaryV1(
            source_aoi_id=source_id,
            hit_count=len(summary.frame_ids),
            attention_ms=summary.attention_ms,
            return_count=summary.return_count,
            frame_ids=summary.frame_ids,
            visual_features=summary.definition.visual_features,
        )
        for source_id, summary in sorted(summaries.items())
    ]

    def feature_scores(values: Iterable[tuple[str, SourceAoiEvidenceSummaryV1]]) -> list[FeatureScoreV1]:
        score_by_value: dict[str, int] = defaultdict(int)
        attention_by_value: dict[str, float] = defaultdict(float)
        source_ids_by_value: dict[str, set[str]] = defaultdict(set)
        for value, summary in values:
            score_by_value[value] += summary.hit_count
            attention_by_value[value] += summary.attention_ms
            source_ids_by_value[value].add(summary.source_aoi_id)
        return [
            FeatureScoreV1(
                value=value,
                score=score_by_value[value],
                attention_ms=attention_by_value[value],
                source_aoi_ids=sorted(source_ids_by_value[value]),
            )
            for value in sorted(score_by_value, key=lambda item: (-score_by_value[item], item))
        ]

    return SourceVisualEvidenceV1(
        metadata_version=metadata.metadata_version,
        feature_taxonomy_version=metadata.feature_taxonomy_version,
        total_hit_count=sum(item.hit_count for item in source_summaries),
        ambiguous_frame_count=ambiguous_frame_count,
        source_aois=source_summaries,
        color_primary_scores=feature_scores(
            (item.visual_features.color_primary, item) for item in source_summaries
        ),
        color_family_scores=feature_scores(
            (item.visual_features.color_family, item) for item in source_summaries
        ),
        silhouette_scores=feature_scores(
            (item.visual_features.silhouette, item) for item in source_summaries
        ),
        category_type_scores=feature_scores(
            (item.visual_features.category_type, item) for item in source_summaries
        ),
        pattern_scores=feature_scores(
            (value, item)
            for item in source_summaries
            for value in item.visual_features.patterns
        ),
        bag_accessory_scores=feature_scores(
            (value, item)
            for item in source_summaries
            for value in item.visual_features.bag_accessories
        ),
    )


def product_feature_match_score(
    product: ProductMatchingItemV1,
    evidence: SourceVisualEvidenceV1,
) -> tuple[float, tuple[str, ...]]:
    profile = product.recommendation_profile
    categories = (
        (profile.color_primary, evidence.color_primary_scores, 2.0),
        (profile.color_family, evidence.color_family_scores, 3.0),
        (profile.silhouette, evidence.silhouette_scores, 4.0),
        (profile.category_type, evidence.category_type_scores, 2.0),
    )
    score = 0.0
    matched: set[str] = set()
    for value, values, weight in categories:
        observed = next((item for item in values if item.value == value), None)
        if observed is not None and value != "unknown":
            score += observed.score * weight
            matched.add(value)
    for value in profile.patterns:
        observed = next((item for item in evidence.pattern_scores if item.value == value), None)
        if observed is not None and value != "unknown":
            score += observed.score * 2.0
            matched.add(value)
    for value in profile.bag_accessories:
        observed = next((item for item in evidence.bag_accessory_scores if item.value == value), None)
        if observed is not None:
            score += observed.score
            matched.add(value)
    return score, tuple(sorted(matched))

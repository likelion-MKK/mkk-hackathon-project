from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.v2_aoi import (
    load_aoi_metadata,
    map_frame_to_aoi,
    validate_aoi_metadata_for_catalog,
)
from apps.api.app.v2_evidence import summarize_observations
from apps.api.app.v2_models import FrameObservationV2
from apps.api.app.v2_postgres import load_canonical_catalog
from apps.api.app.store import MemoryStore
from apps.api.app.v2_store import configured_recommendation_repository


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VIDEO_ID = "mcm-lookbook-v2"
MANIFEST_VERSION = "mcm-lookbook-v2-grid-details-v2-2026-08-19"
PENDING_METADATA = load_aoi_metadata(
    REPOSITORY_ROOT / "data" / "lookbooks" / VIDEO_ID / "aoi-metadata-v2.json"
)
DEMO_METADATA = load_aoi_metadata(
    REPOSITORY_ROOT
    / "data"
    / "lookbooks"
    / VIDEO_ID
    / "aoi-metadata-v2-demo-static-assumptions.json"
)
CATALOG = load_canonical_catalog(
    REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
)


def _frame(
    *,
    video_time_ms: int,
    video_x: float,
    video_y: float,
    frame_id: str = "demo-static-frame",
    sequence: int = 1,
    captured_at_mono_ms: float = 100.0,
    session_offset_ms: float = 100.0,
) -> FrameObservationV2:
    return FrameObservationV2.model_validate(
        {
            "schema_version": "2.0",
            "frame_id": frame_id,
            "sequence": sequence,
            "captured_at_mono_ms": captured_at_mono_ms,
            "session_offset_ms": session_offset_ms,
            "video_time_ms": video_time_ms,
            "playback_epoch": 0,
            "gaze": {
                "screen_x_norm": 0.25,
                "screen_y_norm": 0.25,
                "confidence": 0.9,
                "producer_id": "demo-eye",
                "model_revision": "demo-eye-v1",
                "calibration_id": "demo-calibration",
            },
            "gaze_reason": None,
            "expression": None,
            "expression_reason": "not_observed",
            "attention": {
                "video_x_norm": video_x,
                "video_y_norm": video_y,
                "outside_video": False,
                "confidence": 0.9,
                "producer_id": "demo-kiosk",
                "model_revision": "demo-video-context-v1",
                "manifest_version": MANIFEST_VERSION,
                "candidates": [],
            },
            "attention_reason": None,
            "derived": None,
            "derived_reason": "invalid_or_missing_modality",
        }
    )


def test_demo_static_fixture_is_catalog_valid_but_isolated_from_default_pending_metadata() -> None:
    assert PENDING_METADATA.approval_status == "pending_review"
    assert PENDING_METADATA.exposures == []
    assert DEMO_METADATA.approval_status == "approved"
    assert len(DEMO_METADATA.exposures) == 8
    assert DEMO_METADATA.media_identity == PENDING_METADATA.media_identity
    validate_aoi_metadata_for_catalog(
        DEMO_METADATA,
        CATALOG.products,
        manifest_version=MANIFEST_VERSION,
    )
    assert map_frame_to_aoi(
        _frame(video_time_ms=6_000, video_x=0.25, video_y=0.25),
        PENDING_METADATA,
    ).status == "aoi_metadata_unapproved"


@pytest.mark.parametrize(
    ("video_time_ms", "video_x", "video_y", "product_id", "tags"),
    [
        (6_000, 0.25, 0.25, "mcm-toni-medium-disco-visetos", {"monogram", "shopper", "tote"}),
        (6_000, 0.75, 0.25, "mcm-toni-medium-disco-visetos", {"monogram", "shopper", "tote"}),
        (6_000, 0.25, 0.75, "mcm-toni-medium-disco-visetos", {"monogram", "shopper", "tote"}),
        (6_000, 0.75, 0.75, "mcm-toni-medium-disco-visetos", {"monogram", "shopper", "tote"}),
        (17_000, 0.25, 0.25, "mcm-ella-small-disco-visetos", {"boston", "monogram", "top_handle"}),
        (17_000, 0.75, 0.25, "mcm-aren-east-west-shoulder-visetos", {"monogram", "shoulder", "structured"}),
        (17_000, 0.25, 0.80, "mcm-pina-vanity-case-studded-calfskin", {"compact", "structured"}),
        (17_000, 0.75, 0.75, "mcm-stark-side-studs-backpack-gold-crystal-visetos", {"backpack", "monogram"}),
    ],
)
def test_demo_static_fixture_maps_only_the_explicit_assumptions(
    video_time_ms: int,
    video_x: float,
    video_y: float,
    product_id: str,
    tags: set[str],
) -> None:
    result = map_frame_to_aoi(
        _frame(video_time_ms=video_time_ms, video_x=video_x, video_y=video_y),
        DEMO_METADATA,
    )
    assert result.status == "matched"
    assert result.product_id == product_id
    assert result.component_codes == ("whole_product",)
    assert set(result.observed_visual_tag_ids) == tags


def test_demo_static_fixture_keeps_transitions_and_grid_gaps_fail_closed() -> None:
    assert map_frame_to_aoi(
        _frame(video_time_ms=12_500, video_x=0.25, video_y=0.25),
        DEMO_METADATA,
    ).status == "no_aoi_match"
    assert map_frame_to_aoi(
        _frame(video_time_ms=6_000, video_x=0.50, video_y=0.50),
        DEMO_METADATA,
    ).status == "no_aoi_match"
    assert map_frame_to_aoi(
        _frame(video_time_ms=24_000, video_x=0.25, video_y=0.25),
        DEMO_METADATA,
    ).status == "no_aoi_match"


def test_demo_static_fixture_aggregates_all_static_products_as_variant_c_only() -> None:
    samples = [
        (5_500, 0.25, 0.25),
        (6_000, 0.75, 0.25),
        (6_500, 0.25, 0.75),
        (7_000, 0.75, 0.75),
        (15_000, 0.25, 0.25),
        (15_200, 0.25, 0.25),
        (16_000, 0.75, 0.25),
        (16_200, 0.75, 0.25),
        (17_000, 0.25, 0.80),
        (17_200, 0.25, 0.80),
        (18_000, 0.75, 0.75),
        (18_200, 0.75, 0.75),
    ]
    observations = [
        _frame(
            video_time_ms=video_time_ms,
            video_x=video_x,
            video_y=video_y,
            frame_id=f"demo-static-frame-{index:02d}",
            sequence=index,
            captured_at_mono_ms=float(index * 100),
            session_offset_ms=float(index * 100),
        )
        for index, (video_time_ms, video_x, video_y) in enumerate(samples, start=1)
    ]

    result = summarize_observations(
        observations,
        decision_request_id="demo-static-decision",
        session_id="demo-static-session",
        video_id=VIDEO_ID,
        manifest_version=MANIFEST_VERSION,
        catalog_version=CATALOG.catalog_version,
        aoi_metadata=DEMO_METADATA,
        product_ids=[product.product_id for product in CATALOG.products],
        input_variant="C",
    )

    expected_tags = {
        "mcm-toni-medium-disco-visetos": {"monogram", "shopper", "tote"},
        "mcm-ella-small-disco-visetos": {"boston", "monogram", "top_handle"},
        "mcm-aren-east-west-shoulder-visetos": {
            "monogram",
            "shoulder",
            "structured",
        },
        "mcm-pina-vanity-case-studded-calfskin": {"compact", "structured"},
        "mcm-stark-side-studs-backpack-gold-crystal-visetos": {
            "backpack",
            "monogram",
        },
    }
    observed = {
        item.product_id: item
        for item in result.evidence.summary
        if item.gaze is not None
    }

    assert result.evidence.input_variant == "C"
    assert result.evidence.timeline is None
    assert set(result.eligible_product_ids) == set(expected_tags)
    assert set(observed) == set(expected_tags)
    for product_id, tags in expected_tags.items():
        summary = observed[product_id]
        assert summary.exposure_duration_ms > 0
        assert summary.observed_component_codes == ["whole_product"]
        assert set(summary.observed_visual_tag_ids) == tags
        assert summary.expression is None
        assert summary.expression_reason == "no_matched_expression"

    variant_c_payload = result.evidence.model_dump_json()
    for raw_field in (
        '"frame_id"',
        '"screen_x_norm"',
        '"screen_y_norm"',
        '"video_x_norm"',
        '"video_y_norm"',
        '"captured_at_mono_ms"',
        '"token"',
    ):
        assert raw_field not in variant_c_payload


def test_demo_static_fixture_requires_the_explicit_local_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOOKBOOK_VIDEO_PATH", raising=False)
    monkeypatch.delenv("REQUIRE_LOOKBOOK_MEDIA_READINESS", raising=False)
    monkeypatch.delenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", raising=False)

    default_repository = configured_recommendation_repository(MemoryStore(REPOSITORY_ROOT))
    assert (
        default_repository._aoi_metadata[VIDEO_ID].metadata_revision
        == PENDING_METADATA.metadata_revision
    )

    monkeypatch.setenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", "1")
    demo_repository = configured_recommendation_repository(MemoryStore(REPOSITORY_ROOT))
    assert (
        demo_repository._aoi_metadata[VIDEO_ID].metadata_revision
        == DEMO_METADATA.metadata_revision
    )

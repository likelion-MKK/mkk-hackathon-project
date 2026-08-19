"""Tests for the first deterministic, gaze-only scoring implementation."""

from __future__ import annotations

import pytest

from services.recommendation.engine.features import ProductFeatureAccumulator
from services.recommendation.engine.interface import ContractRecord, RecommendationFeatures
from services.recommendation.engine.research_gaze import (
    GazeScoreWeights,
    ResearchGazeScoreEngine,
)


def product(product_id: str) -> ContractRecord:
    return {"product_id": product_id}


def attention(
    event_id: str,
    sequence: int,
    video_time_ms: int,
    candidates: list[str],
    *,
    confidence: float = 0.8,
    playback_epoch: int = 0,
    valid: bool = True,
    outside_video: bool = False,
) -> ContractRecord:
    return {
        "event_id": event_id,
        "sequence": sequence,
        "video_time_ms": video_time_ms,
        "playback_epoch": playback_epoch,
        "source_gaze_event_id": f"gaze-{event_id}",
        "outside_video": outside_video,
        "candidates": [
            {
                "exposure_id": f"exposure-{product_id}",
                "product_id": product_id,
                "priority": 0,
            }
            for product_id in candidates
        ],
        "valid": valid,
        "confidence": confidence,
    }


def features(*events: ContractRecord) -> RecommendationFeatures:
    accumulator = ProductFeatureAccumulator({"P001", "P002", "P003"})
    for event in events:
        accumulator.accept(event)
    return accumulator.snapshot()


def run(features_value: RecommendationFeatures):
    return ResearchGazeScoreEngine().run(
        recommendation_id="recommendation-test-0001",
        session_id="session-test-0001",
        video_id="video-test-0001",
        manifest_version="manifest-v1",
        features=features_value,
        products=[product("P001"), product("P002"), product("P003")],
    )


def test_attention_duration_uses_video_time_buckets_not_sample_count() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"], confidence=0.8),
        attention("attention-2", 2, 101, ["P001"], confidence=0.7),
        attention("attention-3", 3, 200, ["P002"], confidence=0.5),
        attention("attention-4", 4, 300, ["P002"], confidence=0.5),
    )
    by_product = {feature.product_id: feature for feature in snapshot.product_attention}

    assert by_product["P001"].valid_attention_count == 2
    assert by_product["P001"].attention_duration_ms == 100
    assert by_product["P001"].confidence_weighted_attention_ms == pytest.approx(80)
    assert by_product["P002"].attention_duration_ms == 200
    assert by_product["P002"].average_attention_confidence() == pytest.approx(0.5)


def test_same_bucket_candidate_changes_keep_total_duration_within_one_bucket() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"], confidence=0.8),
        attention("attention-2", 2, 101, ["P001", "P002"], confidence=0.6),
    )
    by_product = {feature.product_id: feature for feature in snapshot.product_attention}

    assert by_product["P001"].attention_duration_ms == pytest.approx(200 / 3)
    assert by_product["P002"].attention_duration_ms == pytest.approx(100 / 3)
    assert sum(feature.attention_duration_ms for feature in snapshot.product_attention) == pytest.approx(
        100
    )
    assert by_product["P001"].confidence_total == pytest.approx(1.1)
    assert by_product["P002"].confidence_total == pytest.approx(0.3)


def test_attention_duration_splits_an_ambiguous_observation_between_products() -> None:
    snapshot = features(attention("attention-1", 1, 100, ["P001", "P002"], confidence=0.8))
    by_product = {feature.product_id: feature for feature in snapshot.product_attention}

    assert by_product["P001"].attention_duration_ms == pytest.approx(50)
    assert by_product["P002"].attention_duration_ms == pytest.approx(50)
    assert by_product["P001"].confidence_weighted_attention_ms == pytest.approx(40)
    assert by_product["P002"].confidence_weighted_attention_ms == pytest.approx(40)
    assert by_product["P001"].confidence_total == pytest.approx(0.4)
    assert by_product["P002"].confidence_total == pytest.approx(0.4)


def test_attention_deduplicates_multiple_aoi_candidates_for_the_same_product() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001", "P001", "P002"], confidence=0.8)
    )
    by_product = {feature.product_id: feature for feature in snapshot.product_attention}

    assert by_product["P001"].valid_attention_count == 1
    assert by_product["P002"].valid_attention_count == 1
    assert by_product["P001"].attention_duration_ms == pytest.approx(50)
    assert by_product["P002"].attention_duration_ms == pytest.approx(50)


def test_observation_run_candidate_increases_after_a_missing_frame() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"]),
        attention("attention-2", 2, 600, ["P001"]),
    )

    assert snapshot.product_attention[0].revisit_count == 1


def test_attention_revisit_count_tolerates_a_250ms_capture_cadence() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"]),
        attention("attention-2", 2, 350, ["P001"]),
        attention("attention-3", 3, 600, ["P001"]),
    )

    assert snapshot.product_attention[0].revisit_count == 0


def test_observation_run_candidate_increases_after_other_product_then_return() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"]),
        attention("attention-2", 2, 350, ["P002"]),
        attention("attention-3", 3, 600, ["P001"]),
    )

    assert snapshot.product_attention[0].revisit_count == 1


def test_observation_run_candidate_increases_after_empty_aoi_then_return() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"]),
        attention("attention-2", 2, 350, []),
        attention("attention-3", 3, 600, ["P001"]),
    )

    assert snapshot.product_attention[0].revisit_count == 1


def test_observation_run_candidate_increases_after_invalid_sample_then_return() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"]),
        attention("attention-2", 2, 350, ["P001"], valid=False),
        attention("attention-3", 3, 600, ["P001"]),
    )

    assert snapshot.product_attention[0].revisit_count == 1


@pytest.mark.parametrize(
    ("first_time_ms", "second_time_ms", "expected_runs"),
    [
        pytest.param(100, 399, 0, id="299ms"),
        pytest.param(100, 400, 0, id="300ms"),
        pytest.param(100, 401, 0, id="301ms-same-bucket-position"),
        pytest.param(199, 500, 1, id="301ms-crosses-bucket-boundary"),
    ],
)
def test_observation_run_candidate_exposes_bucket_boundary_heuristic(
    first_time_ms: int,
    second_time_ms: int,
    expected_runs: int,
) -> None:
    snapshot = features(
        attention("attention-1", 1, first_time_ms, ["P001"]),
        attention("attention-2", 2, second_time_ms, ["P001"]),
    )

    assert snapshot.product_attention[0].revisit_count == expected_runs


def test_observation_run_candidate_resets_across_seek_epoch() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"], playback_epoch=0),
        attention("attention-2", 2, 100, ["P001"], playback_epoch=1),
    )

    assert snapshot.product_attention[0].revisit_count == 1


def test_confidence_is_an_initial_research_signal_when_values_differ() -> None:
    result = run(
        features(
            attention("attention-1", 1, 100, ["P001"], confidence=0.9),
            attention("attention-2", 2, 100, ["P002"], confidence=0.4),
        )
    )

    assert [(item.rank, item.product_id) for item in result.items] == [
        (1, "P001"),
        (2, "P002"),
    ]


def test_algorithm_revision_captures_weight_changes() -> None:
    default_engine = ResearchGazeScoreEngine()
    custom_engine = ResearchGazeScoreEngine(
        GazeScoreWeights(attention_duration=0.5, attention_confidence=0.4, revisit_count=0.1)
    )

    assert default_engine.algorithm_version == "gaze-score-v0-b100-g300-w0p65-c0p25-r0p1"
    assert custom_engine.algorithm_version == "gaze-score-v0-b100-g300-w0p5-c0p4-r0p1"


def test_gaze_score_prefers_longer_observed_attention_over_short_high_confidence_attention() -> None:
    result = run(
        features(
            attention("attention-1", 1, 100, ["P001"], confidence=0.65),
            attention("attention-2", 2, 200, ["P001"], confidence=0.65),
            attention("attention-3", 3, 300, ["P001"], confidence=0.65),
            attention("attention-4", 4, 400, ["P001"], confidence=0.65),
            attention("attention-5", 5, 100, ["P002"], confidence=0.95),
            attention("attention-6", 6, 200, ["P002"], confidence=0.95),
        )
    )

    assert result.status == "completed"
    assert [(item.rank, item.product_id) for item in result.items] == [
        (1, "P001"),
        (2, "P002"),
    ]
    assert result.engine_mode == "research_version"
    assert result.algorithm_version == "gaze-score-v0-b100-g300-w0p65-c0p25-r0p1"


def test_gaze_score_uses_first_observation_as_a_deterministic_tie_breaker() -> None:
    result = run(
        features(
            attention("attention-1", 2, 100, ["P001"], confidence=0.8),
            attention("attention-2", 1, 100, ["P002"], confidence=0.8),
        )
    )

    assert [(item.rank, item.product_id) for item in result.items] == [
        (1, "P002"),
        (2, "P001"),
    ]


def test_gaze_score_requires_two_products_with_time_based_attention() -> None:
    result = run(features(attention("attention-1", 1, 100, ["P001"])))

    assert result.status == "insufficient_data"
    assert result.items == ()
    assert result.reason == "not_enough_scored_attention"

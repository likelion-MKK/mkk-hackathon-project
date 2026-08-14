"""Tests for the first deterministic, gaze-only scoring implementation."""

from __future__ import annotations

import pytest

from services.recommendation.engine.features import ProductFeatureAccumulator
from services.recommendation.engine.interface import ContractRecord, RecommendationFeatures
from services.recommendation.engine.research_gaze import ResearchGazeScoreEngine


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


def test_attention_duration_splits_an_ambiguous_observation_between_products() -> None:
    snapshot = features(attention("attention-1", 1, 100, ["P001", "P002"], confidence=0.8))
    by_product = {feature.product_id: feature for feature in snapshot.product_attention}

    assert by_product["P001"].attention_duration_ms == pytest.approx(50)
    assert by_product["P002"].attention_duration_ms == pytest.approx(50)
    assert by_product["P001"].confidence_weighted_attention_ms == pytest.approx(40)
    assert by_product["P002"].confidence_weighted_attention_ms == pytest.approx(40)


def test_attention_revisit_count_uses_separate_video_time_runs() -> None:
    snapshot = features(
        attention("attention-1", 1, 100, ["P001"]),
        attention("attention-2", 2, 200, ["P001"]),
        attention("attention-3", 3, 500, ["P001"]),
    )

    assert snapshot.product_attention[0].revisit_count == 1


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
    assert result.algorithm_version == "gaze-score-v0"


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

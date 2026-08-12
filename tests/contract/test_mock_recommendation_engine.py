"""Contract-level tests for the deterministic development recommendation engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.schemas import RecommendationItem as ApiRecommendationItem
from apps.api.app.schemas import RecommendationResult
from services.recommendation.engine.interface import ContractRecord
from services.recommendation.mock.engine import MockRecommendationEngine


def product(product_id: str) -> ContractRecord:
    return {"product_id": product_id}


def attention(
    event_id: str,
    product_id: str,
    sequence: int,
    *,
    valid: bool = True,
    outside_video: bool = False,
) -> ContractRecord:
    return {
        "event_id": event_id,
        "sequence": sequence,
        "source_gaze_event_id": f"gaze-{sequence}",
        "outside_video": outside_video,
        "candidates": [{"exposure_id": f"exposure-{sequence}", "product_id": product_id, "priority": 0}],
        "valid": valid,
    }


def test_mock_engine_returns_first_two_distinct_valid_candidates() -> None:
    result = MockRecommendationEngine().run(
        recommendation_id="recommendation-test-0001",
        session_id="session-test-0001",
        video_id="video-test-0001",
        manifest_version="manifest-v1",
        events=[attention("attention-1", "P001", 1), attention("attention-2", "P002", 2)],
        products=[product("P001"), product("P002")],
    )

    assert result.status == "completed"
    assert [(item.rank, item.product_id) for item in result.items] == [(1, "P001"), (2, "P002")]
    assert RecommendationResult.model_validate(result.to_payload()).status == "completed"


def test_mock_engine_preserves_insufficient_data_when_only_one_product_is_valid() -> None:
    result = MockRecommendationEngine().run(
        recommendation_id="recommendation-test-0002",
        session_id="session-test-0001",
        video_id="video-test-0001",
        manifest_version="manifest-v1",
        events=[attention("attention-1", "P001", 1)],
        products=[product("P001"), product("P002")],
    )

    assert result.status == "insufficient_data"
    assert result.items == ()
    assert result.reason == "not_enough_valid_attention"


def test_mock_engine_uses_event_sequence_not_batch_arrival_order() -> None:
    result = MockRecommendationEngine().run(
        recommendation_id="recommendation-test-0003",
        session_id="session-test-0001",
        video_id="video-test-0001",
        manifest_version="manifest-v1",
        events=[attention("attention-2", "P002", 2), attention("attention-1", "P001", 1)],
        products=[product("P001"), product("P002")],
    )

    assert [(item.rank, item.product_id) for item in result.items] == [(1, "P001"), (2, "P002")]


def test_mock_engine_ignores_invalid_outside_and_unknown_candidates() -> None:
    result = MockRecommendationEngine().run(
        recommendation_id="recommendation-test-0004",
        session_id="session-test-0001",
        video_id="video-test-0001",
        manifest_version="manifest-v1",
        events=[
            attention("attention-1", "P003", 1, valid=False),
            attention("attention-2", "P003", 2, outside_video=True),
            attention("attention-3", "UNKNOWN", 3),
            attention("attention-4", "P001", 4),
            attention("attention-5", "P002", 5),
        ],
        products=[product("P001"), product("P002"), product("P003")],
    )

    assert [(item.rank, item.product_id) for item in result.items] == [(1, "P001"), (2, "P002")]


def test_api_recommendation_rank_rejects_string_coercion() -> None:
    with pytest.raises(ValidationError):
        ApiRecommendationItem(rank="1", product_id="P001")

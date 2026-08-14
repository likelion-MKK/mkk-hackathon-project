"""Deterministic, gaze-only scoring for research and replay evaluation.

This engine is deliberately separate from the default development mock.  It
uses only session-local, privacy-minimized product aggregates and never
receives a frame, coordinate, timestamp, or expression score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from services.recommendation.engine.interface import (
    ContractRecord,
    ProductAttentionFeature,
    RecommendationItem,
    RecommendationFeatures,
    RecommendationRun,
)


@dataclass(frozen=True, slots=True)
class GazeScoreWeights:
    """The initial, adjustable share of each gaze-only signal."""

    attention_duration: float = 0.65
    attention_confidence: float = 0.25
    revisit_count: float = 0.10

    def __post_init__(self) -> None:
        values = (self.attention_duration, self.attention_confidence, self.revisit_count)
        if not all(isfinite(value) and value >= 0 for value in values):
            raise ValueError("gaze score weights must be finite non-negative numbers")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("gaze score weights must add up to 1")


class ResearchGazeScoreEngine:
    """Rank products by observed gaze time, quality, and repeat visits.

    The weights are a development hypothesis, not a claim of recommendation
    quality.  Callers must keep this engine distinguishable from the Mock
    engine through ``engine_mode`` and ``algorithm_version``.
    """

    mode = "research_version"
    algorithm_version = "gaze-score-v0"

    def __init__(self, weights: GazeScoreWeights | None = None) -> None:
        self._weights = weights or GazeScoreWeights()

    def run(
        self,
        *,
        recommendation_id: str,
        session_id: str,
        video_id: str,
        manifest_version: str,
        features: RecommendationFeatures,
        products: Sequence[ContractRecord],
    ) -> RecommendationRun:
        known_products = {
            product_id
            for product in products
            if isinstance(product_id := product.get("product_id"), str)
        }
        candidates = [
            feature
            for feature in features.product_attention
            if feature.product_id in known_products and feature.attention_duration_ms > 0
        ]

        if len(candidates) < 2:
            return RecommendationRun(
                recommendation_id=recommendation_id,
                session_id=session_id,
                video_id=video_id,
                manifest_version=manifest_version,
                algorithm_version=self.algorithm_version,
                engine_mode=self.mode,
                status="insufficient_data",
                items=(),
                reason="not_enough_scored_attention",
            )

        max_duration = max(feature.attention_duration_ms for feature in candidates)
        max_revisit_count = max(feature.revisit_count for feature in candidates)
        ranked = sorted(
            candidates,
            key=lambda feature: (
                -self._score(feature, max_duration, max_revisit_count),
                feature.first_seen_key(),
            ),
        )

        return RecommendationRun(
            recommendation_id=recommendation_id,
            session_id=session_id,
            video_id=video_id,
            manifest_version=manifest_version,
            algorithm_version=self.algorithm_version,
            engine_mode=self.mode,
            status="completed",
            items=tuple(
                RecommendationItem(rank=rank, product_id=feature.product_id)
                for rank, feature in enumerate(ranked[:2], start=1)
            ),
            reason=None,
        )

    def _score(
        self,
        feature: ProductAttentionFeature,
        max_duration: float,
        max_revisit_count: int,
    ) -> float:
        duration_score = feature.attention_duration_ms / max_duration
        confidence_score = feature.average_attention_confidence()
        revisit_score = (
            feature.revisit_count / max_revisit_count if max_revisit_count else 0.0
        )
        return (
            self._weights.attention_duration * duration_score
            + self._weights.attention_confidence * confidence_score
            + self._weights.revisit_count * revisit_score
        )

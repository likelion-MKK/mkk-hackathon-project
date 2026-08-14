"""Deterministic recommendation boundary for development and CI.

This intentionally does not claim recommendation quality. It selects the first
two distinct valid AOI candidates from privacy-minimized attention aggregates
and returns ``insufficient_data`` otherwise.
"""

from __future__ import annotations

from collections.abc import Sequence

from services.recommendation.engine.interface import (
    ContractRecord,
    RecommendationItem,
    RecommendationFeatures,
    RecommendationRun,
)


class MockRecommendationEngine:
    mode = "mock"
    algorithm_version = "mock-v1"

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
            feature.product_id
            for feature in sorted(features.product_attention, key=lambda feature: feature.first_seen_key())
            if feature.product_id in known_products
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
                reason="not_enough_valid_attention",
            )

        return RecommendationRun(
            recommendation_id=recommendation_id,
            session_id=session_id,
            video_id=video_id,
            manifest_version=manifest_version,
            algorithm_version=self.algorithm_version,
            engine_mode=self.mode,
            status="completed",
            items=(
                RecommendationItem(rank=1, product_id=candidates[0]),
                RecommendationItem(rank=2, product_id=candidates[1]),
            ),
            reason=None,
        )

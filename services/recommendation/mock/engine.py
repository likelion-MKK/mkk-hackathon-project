"""Deterministic recommendation boundary for development and CI.

This intentionally does not claim recommendation quality. It selects the first
two distinct valid AOI candidates observed in the derived event stream and
returns ``insufficient_data`` otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from services.recommendation.engine.interface import (
    ContractRecord,
    RecommendationItem,
    RecommendationRun,
)


class MockRecommendationEngine:
    mode = "mock"
    algorithm_version = "mock-v1"

    @staticmethod
    def _sequence_key(event: ContractRecord) -> int:
        """Sort public events by their session ordering invariant."""

        sequence = event.get("sequence")
        return sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else 0

    @staticmethod
    def _is_valid_attention(event: ContractRecord) -> bool:
        """Identify a valid, in-video ProductAttentionEvent payload."""

        return (
            isinstance(event.get("source_gaze_event_id"), str)
            and event.get("valid") is True
            and event.get("outside_video") is False
        )

    @staticmethod
    def _candidate_product_ids(event: ContractRecord) -> Sequence[str]:
        candidates = event.get("candidates")
        if not isinstance(candidates, (list, tuple)):
            return ()

        product_ids: list[str] = []
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                product_id = candidate.get("product_id")
                if isinstance(product_id, str):
                    product_ids.append(product_id)
        return product_ids

    def run(
        self,
        *,
        recommendation_id: str,
        session_id: str,
        video_id: str,
        manifest_version: str,
        events: Sequence[ContractRecord],
        products: Sequence[ContractRecord],
    ) -> RecommendationRun:
        known_products = {
            product_id
            for product in products
            if isinstance(product_id := product.get("product_id"), str)
        }
        candidates: list[str] = []

        for event in sorted(events, key=self._sequence_key):
            if not self._is_valid_attention(event):
                continue
            for product_id in self._candidate_product_ids(event):
                if product_id in known_products and product_id not in candidates:
                    candidates.append(product_id)

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

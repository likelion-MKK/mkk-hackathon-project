"""Privacy-minimized aggregation for the recommendation engine boundary."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from services.recommendation.engine.interface import (
    ContractRecord,
    ProductAttentionFeature,
    RecommendationFeatures,
)


@dataclass(slots=True)
class _MutableProductAttentionFeature:
    valid_attention_count: int
    confidence_total: float
    first_attention_sequence: int
    first_candidate_index: int


class ProductFeatureAccumulator:
    """Aggregate valid attention events without retaining their payloads.

    Expression samples are deliberately ignored at this boundary until their
    product attribution, taxonomy, and evaluation policy are approved.
    """

    def __init__(self, known_product_ids: Collection[str]) -> None:
        self._known_product_ids = frozenset(known_product_ids)
        self._features: dict[str, _MutableProductAttentionFeature] = {}

    @staticmethod
    def _is_valid_attention(event: ContractRecord) -> bool:
        return (
            isinstance(event.get("source_gaze_event_id"), str)
            and event.get("valid") is True
            and event.get("outside_video") is False
        )

    @staticmethod
    def _sequence(event: ContractRecord) -> int | None:
        sequence = event.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            return None
        return sequence

    @staticmethod
    def _confidence(event: ContractRecord) -> float:
        confidence = event.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return 0.0
        return float(confidence)

    def accept(self, event: ContractRecord) -> None:
        """Fold one validated public event into product-level features."""

        if not self._is_valid_attention(event):
            return

        sequence = self._sequence(event)
        candidates = event.get("candidates")
        if sequence is None or not isinstance(candidates, (list, tuple)):
            return

        confidence = self._confidence(event)
        product_ids_in_event: set[str] = set()
        for candidate_index, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping):
                continue
            product_id = candidate.get("product_id")
            if (
                not isinstance(product_id, str)
                or product_id not in self._known_product_ids
                or product_id in product_ids_in_event
            ):
                continue

            product_ids_in_event.add(product_id)
            feature = self._features.get(product_id)
            if feature is None:
                self._features[product_id] = _MutableProductAttentionFeature(
                    valid_attention_count=1,
                    confidence_total=confidence,
                    first_attention_sequence=sequence,
                    first_candidate_index=candidate_index,
                )
                continue

            feature.valid_attention_count += 1
            feature.confidence_total += confidence
            if (sequence, candidate_index) < (
                feature.first_attention_sequence,
                feature.first_candidate_index,
            ):
                feature.first_attention_sequence = sequence
                feature.first_candidate_index = candidate_index

    def snapshot(self) -> RecommendationFeatures:
        """Return a deterministic, payload-free engine input snapshot."""

        return RecommendationFeatures(
            product_attention=tuple(
                ProductAttentionFeature(
                    product_id=product_id,
                    valid_attention_count=feature.valid_attention_count,
                    confidence_total=feature.confidence_total,
                    first_attention_sequence=feature.first_attention_sequence,
                    first_candidate_index=feature.first_candidate_index,
                )
                for product_id, feature in sorted(self._features.items())
            )
        )

    def clear(self) -> None:
        """Discard all active-session aggregate state after completion."""

        self._features.clear()

"""Stable public-contract boundary for replaceable recommendation engines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias


ContractRecord: TypeAlias = Mapping[str, object]
RecommendationStatus = Literal["pending", "completed", "insufficient_data", "failed"]


@dataclass(frozen=True, slots=True)
class RecommendationItem:
    """A product selected by a recommendation engine."""

    rank: int
    product_id: str

    def to_payload(self) -> dict[str, object]:
        return {"rank": self.rank, "product_id": self.product_id}


@dataclass(frozen=True, slots=True)
class ProductAttentionFeature:
    """A privacy-minimized aggregate for one catalog product.

    The feature intentionally contains no event, frame, coordinate, timestamp,
    or expression payload. It keeps only the information needed by the
    development recommendation boundary.
    """

    product_id: str
    valid_attention_count: int
    # Confidence summed after each event's candidate share is applied.
    confidence_total: float
    attention_duration_ms: float
    confidence_weighted_attention_ms: float
    revisit_count: int
    first_attention_sequence: int
    first_candidate_index: int

    def first_seen_key(self) -> tuple[int, int, str]:
        """Return the deterministic order used by the development mock."""

        return (self.first_attention_sequence, self.first_candidate_index, self.product_id)

    def average_attention_confidence(self) -> float:
        """Return the time-weighted confidence for scored gaze observations.

        A product with no time-bucketed observation has no usable gaze score,
        even if a caller retained a legacy count-only aggregate.
        """

        if self.attention_duration_ms <= 0:
            return 0.0
        return self.confidence_weighted_attention_ms / self.attention_duration_ms


@dataclass(frozen=True, slots=True)
class RecommendationFeatures:
    """Sanitized, session-local input for a recommendation engine.

    API adapters build this value while batches arrive and discard the original
    derived-event payloads. It is not a public JSON contract.
    """

    product_attention: tuple[ProductAttentionFeature, ...]


@dataclass(frozen=True, slots=True)
class RecommendationRun:
    """Engine output to be validated by the API against RecommendationResult."""

    recommendation_id: str
    session_id: str
    video_id: str
    manifest_version: str
    algorithm_version: str
    engine_mode: Literal["mock", "research_version"]
    status: RecommendationStatus
    items: tuple[RecommendationItem, ...]
    reason: str | None

    def to_payload(self) -> dict[str, object]:
        """Return the public RecommendationResult payload shape."""

        return {
            "schema_version": "1.0",
            "recommendation_id": self.recommendation_id,
            "session_id": self.session_id,
            "video_id": self.video_id,
            "manifest_version": self.manifest_version,
            "algorithm_version": self.algorithm_version,
            "engine_mode": self.engine_mode,
            "status": self.status,
            "items": [item.to_payload() for item in self.items],
            "reason": self.reason,
        }


class RecommendationEngine(Protocol):
    """An engine consumes sanitized aggregate features and catalog payloads."""

    mode: str
    algorithm_version: str

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
        """Return a result for an API adapter to validate against the contract."""

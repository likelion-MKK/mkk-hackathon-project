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
    """An engine consumes public derived-event and catalog payloads only."""

    mode: str
    algorithm_version: str

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
        """Return a result for an API adapter to validate against the contract."""

"""Privacy-minimized aggregation for the recommendation engine boundary."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from services.recommendation.engine.interface import (
    ContractRecord,
    ProductAttentionFeature,
    RecommendationFeatures,
)


DEFAULT_ATTENTION_BUCKET_MS = 100
DEFAULT_REVISIT_GAP_MS = 300
# These are research-v0 defaults. If either value changes, the emitted
# recommendation algorithm revision must change with it.


@dataclass(slots=True)
class _AttentionBucket:
    """One session-local, product-level slice of observed video time."""

    attention_share: float
    confidence_share: float


@dataclass(slots=True)
class _MutableProductAttentionFeature:
    valid_attention_count: int
    confidence_total: float
    first_attention_sequence: int
    first_candidate_index: int
    attention_buckets: dict[tuple[int, int], _AttentionBucket] = field(default_factory=dict)


class ProductFeatureAccumulator:
    """Aggregate valid attention events without retaining their payloads.

    The current Mock deliberately ignores expression samples. A separate
    research-engine implementation will add only the product-attributed,
    privacy-minimized Face feature required by ADR-0005.
    """

    def __init__(
        self,
        known_product_ids: Collection[str],
        *,
        attention_bucket_ms: int = DEFAULT_ATTENTION_BUCKET_MS,
        revisit_gap_ms: int = DEFAULT_REVISIT_GAP_MS,
    ) -> None:
        if isinstance(attention_bucket_ms, bool) or not isinstance(attention_bucket_ms, int):
            raise TypeError("attention_bucket_ms must be an integer")
        if attention_bucket_ms <= 0:
            raise ValueError("attention_bucket_ms must be positive")
        if isinstance(revisit_gap_ms, bool) or not isinstance(revisit_gap_ms, int):
            raise TypeError("revisit_gap_ms must be an integer")
        if revisit_gap_ms < attention_bucket_ms:
            raise ValueError("revisit_gap_ms must be at least attention_bucket_ms")

        self._known_product_ids = frozenset(known_product_ids)
        self._attention_bucket_ms = attention_bucket_ms
        # A 250ms capture cadence can span three 100ms buckets after floor
        # division. Keep that continuous observation from becoming a revisit.
        self._max_contiguous_bucket_gap = (
            revisit_gap_ms + attention_bucket_ms - 1
        ) // attention_bucket_ms
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

    @staticmethod
    def _non_negative_int(event: ContractRecord, field_name: str) -> int | None:
        value = event.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def _attention_bucket_key(self, event: ContractRecord) -> tuple[int, int] | None:
        """Return a stable video-time bucket without retaining raw events."""

        video_time_ms = self._non_negative_int(event, "video_time_ms")
        playback_epoch = self._non_negative_int(event, "playback_epoch")
        if video_time_ms is None or playback_epoch is None:
            return None
        return (playback_epoch, video_time_ms // self._attention_bucket_ms)

    @staticmethod
    def _record_first_attention(
        feature: _MutableProductAttentionFeature,
        sequence: int,
        candidate_index: int,
    ) -> None:
        if (sequence, candidate_index) < (
            feature.first_attention_sequence,
            feature.first_candidate_index,
        ):
            feature.first_attention_sequence = sequence
            feature.first_candidate_index = candidate_index

    @staticmethod
    def _record_attention_bucket(
        feature: _MutableProductAttentionFeature,
        bucket_key: tuple[int, int],
        *,
        attention_share: float,
        confidence_share: float,
    ) -> None:
        existing = feature.attention_buckets.get(bucket_key)
        if existing is None:
            feature.attention_buckets[bucket_key] = _AttentionBucket(
                attention_share=attention_share,
                confidence_share=confidence_share,
            )
            return

        # Several samples can arrive during one bucket. Keeping the largest
        # contribution prevents a higher capture FPS from inflating a score.
        existing.attention_share = max(existing.attention_share, attention_share)
        existing.confidence_share = max(existing.confidence_share, confidence_share)

    def _bucket_scales(self) -> dict[tuple[int, int], float]:
        """Return a scale that caps all product shares in one time bucket.

        Candidate attribution can change between samples inside one bucket.
        The per-product maximum is useful for resisting capture-rate noise, but
        it can make the product totals exceed one physical bucket. A shared
        scale preserves the relative product contributions while keeping the
        total observed time bounded by ``attention_bucket_ms``.
        """

        bucket_totals: dict[tuple[int, int], float] = {}
        for feature in self._features.values():
            for bucket_key, observation in feature.attention_buckets.items():
                bucket_totals[bucket_key] = (
                    bucket_totals.get(bucket_key, 0.0) + observation.attention_share
                )

        return {
            bucket_key: 1.0 if total <= 1.0 else 1.0 / total
            for bucket_key, total in bucket_totals.items()
        }

    def _summarize_attention_buckets(
        self,
        feature: _MutableProductAttentionFeature,
        bucket_scales: Mapping[tuple[int, int], float],
    ) -> tuple[float, float, int]:
        """Summarize duration, confidence, and v0 observation-run candidates.

        ``revisit_count`` is deliberately a candidate signal. A new run can
        be caused by a real product departure, an invalid sample, or a dropped
        frame, so it is not a validated count of user revisits.
        """

        duration_ms = 0.0
        confidence_weighted_duration_ms = 0.0
        buckets_by_epoch: dict[int, list[int]] = {}

        for (playback_epoch, bucket_index), observation in feature.attention_buckets.items():
            bucket_scale = bucket_scales[(playback_epoch, bucket_index)]
            duration_ms += (
                self._attention_bucket_ms * observation.attention_share * bucket_scale
            )
            confidence_weighted_duration_ms += (
                self._attention_bucket_ms * observation.confidence_share * bucket_scale
            )
            buckets_by_epoch.setdefault(playback_epoch, []).append(bucket_index)

        observation_runs = 0
        for bucket_indexes in buckets_by_epoch.values():
            previous_bucket: int | None = None
            for bucket_index in sorted(bucket_indexes):
                if (
                    previous_bucket is None
                    or bucket_index - previous_bucket > self._max_contiguous_bucket_gap
                ):
                    observation_runs += 1
                previous_bucket = bucket_index

        return duration_ms, confidence_weighted_duration_ms, max(0, observation_runs - 1)

    def accept(self, event: ContractRecord) -> None:
        """Fold one validated public event into product-level features."""

        if not self._is_valid_attention(event):
            return

        sequence = self._sequence(event)
        candidates = event.get("candidates")
        if sequence is None or not isinstance(candidates, (list, tuple)):
            return

        confidence = self._confidence(event)
        bucket_key = self._attention_bucket_key(event)
        candidate_products: list[tuple[str, int]] = []
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
            candidate_products.append((product_id, candidate_index))

        if not candidate_products:
            return

        # An overlap can name more than one product. Until the AOI layer has a
        # final winner rule, one gaze observation is split evenly rather than
        # counted in full for every candidate.
        attention_share = 1.0 / len(candidate_products)
        confidence_share = confidence * attention_share
        for product_id, candidate_index in candidate_products:
            feature = self._features.get(product_id)
            if feature is None:
                feature = _MutableProductAttentionFeature(
                    valid_attention_count=1,
                    confidence_total=confidence_share,
                    first_attention_sequence=sequence,
                    first_candidate_index=candidate_index,
                )
                self._features[product_id] = feature
            else:
                feature.valid_attention_count += 1
                feature.confidence_total += confidence_share
                self._record_first_attention(feature, sequence, candidate_index)

            if bucket_key is not None:
                self._record_attention_bucket(
                    feature,
                    bucket_key,
                    attention_share=attention_share,
                    confidence_share=confidence_share,
                )

    def snapshot(self) -> RecommendationFeatures:
        """Return a deterministic, payload-free engine input snapshot."""

        bucket_scales = self._bucket_scales()
        product_attention: list[ProductAttentionFeature] = []
        for product_id, feature in sorted(self._features.items()):
            (
                attention_duration_ms,
                confidence_weighted_attention_ms,
                revisit_count,
            ) = self._summarize_attention_buckets(feature, bucket_scales)
            product_attention.append(
                ProductAttentionFeature(
                    product_id=product_id,
                    valid_attention_count=feature.valid_attention_count,
                    confidence_total=feature.confidence_total,
                    attention_duration_ms=attention_duration_ms,
                    confidence_weighted_attention_ms=confidence_weighted_attention_ms,
                    revisit_count=revisit_count,
                    first_attention_sequence=feature.first_attention_sequence,
                    first_candidate_index=feature.first_candidate_index,
                )
            )

        return RecommendationFeatures(product_attention=tuple(product_attention))

    def clear(self) -> None:
        """Discard all active-session aggregate state after completion."""

        self._features.clear()

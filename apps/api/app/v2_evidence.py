"""Deterministic, diagnosis-free aggregation for RecommendationEvidenceV2."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean
from typing import Iterable, Literal

from apps.api.app.v2_models import (
    EvidenceWindowV2,
    ExpressionSummaryV2,
    EyeSignalVersionV2,
    FaceSignalVersionV2,
    FrameObservationV2,
    GazeSummaryV2,
    ProductEvidenceSummaryV2,
    RecommendationDataQualityV2,
    RecommendationEvidenceV2,
    SignalVersionsV2,
    SustainedActionV2,
)


FEATURE_VERSION = "central-evidence-v2-demo-1"
MAX_CONTINUOUS_GAP_MS = 1_000.0


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    evidence: RecommendationEvidenceV2
    eligible_product_ids: frozenset[str]
    continuity_reset_count: int
    missing_gaze_count: int
    missing_expression_count: int
    ambiguous_attention_count: int

    @property
    def data_quality(self) -> RecommendationDataQualityV2:
        return self.evidence.data_quality


def _ordered(observations: Iterable[FrameObservationV2]) -> list[FrameObservationV2]:
    return sorted(
        observations,
        key=lambda item: (
            item.playback_epoch,
            item.captured_at_mono_ms,
            item.sequence,
            item.frame_id,
        ),
    )


def _data_quality(
    ordered: list[FrameObservationV2],
    *,
    expected_observation_count: int | None,
) -> RecommendationDataQualityV2:
    observed = len(ordered)
    if expected_observation_count is None:
        epoch_sequences: dict[int, list[int]] = defaultdict(list)
        for frame in ordered:
            epoch_sequences[frame.playback_epoch].append(frame.sequence)
        expected = sum(max(values) - min(values) + 1 for values in epoch_sequences.values())
    else:
        expected = expected_observation_count
    expected = max(observed, expected)
    denominator = expected or 1
    gaze_count = sum(frame.gaze is not None for frame in ordered)
    expression_count = sum(frame.expression is not None for frame in ordered)
    matched_count = sum(
        frame.gaze is not None and frame.expression is not None for frame in ordered
    )
    ambiguous_count = sum(
        frame.attention is not None and len(frame.attention.candidates) > 1
        for frame in ordered
    )
    return RecommendationDataQualityV2(
        expected_observation_count=expected,
        gaze_valid_ratio=gaze_count / denominator,
        expression_valid_ratio=expression_count / denominator,
        matched_frame_ratio=matched_count / denominator,
        ambiguous_product_ratio=ambiguous_count / denominator,
    )


def _signal_versions(ordered: list[FrameObservationV2]) -> SignalVersionsV2:
    eye_versions = {
        (frame.gaze.producer_id, frame.gaze.model_revision)
        for frame in ordered
        if frame.gaze is not None
    }
    face_versions = {
        (
            frame.expression.producer_id,
            frame.expression.model_revision,
            frame.expression.taxonomy_version,
        )
        for frame in ordered
        if frame.expression is not None
    }
    aoi_versions = {
        frame.attention.model_revision
        for frame in ordered
        if frame.attention is not None
    }
    eye = (
        EyeSignalVersionV2(producer_id=next(iter(eye_versions))[0], model_revision=next(iter(eye_versions))[1])
        if len(eye_versions) == 1
        else None
    )
    face = (
        FaceSignalVersionV2(
            producer_id=next(iter(face_versions))[0],
            model_revision=next(iter(face_versions))[1],
            taxonomy_version=next(iter(face_versions))[2],
        )
        if len(face_versions) == 1
        else None
    )
    return SignalVersionsV2(
        eye=eye,
        eye_reason=None if eye is not None else ("no_valid_gaze" if not eye_versions else "mixed_eye_versions"),
        face=face,
        face_reason=None if face is not None else ("no_valid_expression" if not face_versions else "mixed_face_versions"),
        aoi_mapper_revision=next(iter(aoi_versions)) if len(aoi_versions) == 1 else ("unavailable" if not aoi_versions else "mixed"),
    )


def summarize_observations(
    observations: Iterable[FrameObservationV2],
    *,
    decision_request_id: str = "decision-summary",
    session_id: str = "session-summary",
    video_id: str = "video-summary",
    manifest_version: str = "manifest-summary",
    catalog_version: str = "catalog-summary",
    product_ids: Iterable[str] | None = None,
    expected_observation_count: int | None = None,
    max_continuous_gap_ms: float = MAX_CONTINUOUS_GAP_MS,
    input_variant: Literal["A", "B", "C"] = "C",
) -> EvidenceSummary:
    """Aggregate only exact singleton AOI ownership and reset untrusted edges."""

    ordered = _ordered(observations)
    if not ordered:
        raise ValueError("at least one observation is required to build v2 evidence")
    if len(ordered) > 512:
        raise ValueError("v2 evidence timeline is bounded to 512 observations")

    inferred_ids = {
        candidate.product_id
        for frame in ordered
        if frame.attention is not None
        for candidate in frame.attention.candidates
    }
    catalog_ids = sorted(set(product_ids or inferred_ids))
    if not catalog_ids:
        raise ValueError("at least one catalog product is required to build v2 evidence")
    if len(catalog_ids) > 10:
        raise ValueError("v2 evidence supports at most 10 catalog products")

    frames_by_product: dict[str, list[FrameObservationV2]] = defaultdict(list)
    dwell_ms: dict[str, float] = defaultdict(float)
    movement: dict[str, list[float]] = defaultdict(list)
    speeds: dict[str, list[float]] = defaultdict(list)
    returns: dict[str, int] = defaultdict(int)
    return_comparisons: dict[str, int] = defaultdict(int)
    confidences: dict[str, list[float]] = defaultdict(list)
    changes: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    change_rates: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    sustained: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    windows_raw: list[
        tuple[str, str | None, FrameObservationV2, FrameObservationV2, set[str]]
    ] = []

    previous: FrameObservationV2 | None = None
    previous_product: str | None = None
    window_key: tuple[str, str | None] | None = None
    window_start: FrameObservationV2 | None = None
    window_end: FrameObservationV2 | None = None
    window_codes: set[str] = set()
    continuity_reset_count = 0

    def close_window() -> None:
        nonlocal window_key, window_start, window_end, window_codes
        if window_key is not None and window_start is not None and window_end is not None:
            windows_raw.append(
                (window_key[0], window_key[1], window_start, window_end, set(window_codes))
            )
        window_key = None
        window_start = None
        window_end = None
        window_codes = set()

    for frame in ordered:
        discontinuity = False
        if previous is not None:
            elapsed = frame.captured_at_mono_ms - previous.captured_at_mono_ms
            discontinuity = (
                frame.playback_epoch != previous.playback_epoch
                or frame.video_time_ms < previous.video_time_ms
                or frame.sequence <= previous.sequence
                or elapsed < 0
                or elapsed > max_continuous_gap_ms
            )
            if discontinuity:
                continuity_reset_count += 1
                previous_product = None
                close_window()

        attention = frame.attention
        candidate = (
            attention.candidates[0]
            if attention is not None and len(attention.candidates) == 1
            else None
        )
        product_id = None if candidate is None else candidate.product_id
        product_part = None if candidate is None else candidate.product_part
        if attention is not None and len(attention.candidates) > 1:
            close_window()
            previous_product = None

        if product_id is not None:
            frames_by_product[product_id].append(frame)
            if frame.gaze is not None:
                confidences[product_id].append(frame.gaze.confidence)
            if previous_product == product_id and previous is not None and not discontinuity:
                dwell_ms[product_id] += frame.captured_at_mono_ms - previous.captured_at_mono_ms

            derived = frame.derived
            if derived is not None and derived.gaze is not None and not discontinuity:
                if derived.gaze.movement is not None:
                    movement[product_id].append(derived.gaze.movement.distance_norm)
                    speeds[product_id].append(derived.gaze.movement.speed_norm_per_s)
                if derived.gaze.return_candidate is not None:
                    return_comparisons[product_id] += 1
                    if derived.gaze.return_candidate is True:
                        returns[product_id] += 1
            if derived is not None and derived.expression is not None and not discontinuity:
                if derived.expression.score_changes is not None:
                    for signal, value in derived.expression.score_changes.items():
                        changes[product_id][signal].append(value)
                    assert derived.expression.score_change_rates_per_s is not None
                    for signal, value in derived.expression.score_change_rates_per_s.items():
                        change_rates[product_id][signal].append(value)
                for action in derived.expression.sustained_actions:
                    # Producer values are cumulative since the action began. Summing
                    # each frame would count the same interval repeatedly.
                    sustained[product_id][action.signal] = max(
                        sustained[product_id][action.signal], action.duration_ms
                    )

            codes = {"observed_attention"}
            if returns[product_id]:
                codes.add("return_candidate")
            if movement[product_id]:
                codes.add("gaze_movement")
            if changes[product_id]:
                codes.add("face_action_change")
            current_window_key = (product_id, product_part)
            if window_key != current_window_key:
                close_window()
                window_key = current_window_key
                window_start = frame
            window_end = frame
            window_codes.update(codes)
        else:
            close_window()
        previous_product = product_id
        previous = frame
    close_window()

    unambiguous_count = sum(len(frames) for frames in frames_by_product.values())
    summaries: list[ProductEvidenceSummaryV2] = []
    eligible: set[str] = set()
    for product_id in catalog_ids:
        product_frames = frames_by_product[product_id]
        gaze_frames = [frame for frame in product_frames if frame.gaze is not None]
        expression_frames = [frame for frame in product_frames if frame.expression is not None]
        gaze_summary = None
        if gaze_frames:
            eligible.add(product_id)
            movement_available = bool(movement[product_id])
            return_available = return_comparisons[product_id] > 0
            gaze_summary = GazeSummaryV2(
                valid_observation_count=len(gaze_frames),
                observed_attention_ms=float(dwell_ms[product_id]),
                attention_ratio=len(product_frames) / (unambiguous_count or 1),
                average_confidence=fmean(confidences[product_id]),
                return_candidate_count=(returns[product_id] if return_available else None),
                return_candidate_reason=(
                    None if return_available else "no_comparable_gaze_observation"
                ),
                movement_distance_norm=(
                    float(sum(movement[product_id])) if movement_available else None
                ),
                mean_speed_norm_per_s=(
                    fmean(speeds[product_id]) if movement_available else None
                ),
                movement_reason=(
                    None if movement_available else "no_comparable_gaze_observation"
                ),
            )
        expression_summary = None
        if expression_frames:
            has_changes = bool(changes[product_id])
            expression_summary = ExpressionSummaryV2(
                matched_observation_count=len(expression_frames),
                valid_coverage=len(expression_frames) / (len(product_frames) or 1),
                action_changes={
                    signal: fmean(values) for signal, values in sorted(changes[product_id].items())
                } if has_changes else None,
                action_change_rates_per_s={
                    signal: fmean(values)
                    for signal, values in sorted(change_rates[product_id].items())
                } if has_changes else None,
                change_reason=None if has_changes else "no_comparable_expression_observation",
                sustained_actions=[
                    SustainedActionV2(signal=signal, duration_ms=duration)
                    for signal, duration in sorted(sustained[product_id].items())
                ],
            )
        summaries.append(
            ProductEvidenceSummaryV2(
                product_id=product_id,
                exposure_duration_ms=float(dwell_ms[product_id]),
                gaze=gaze_summary,
                gaze_reason=None if gaze_summary is not None else "no_valid_gaze_for_product",
                expression=expression_summary,
                expression_reason=(
                    None if expression_summary is not None else "no_matched_expression"
                ),
            )
        )

    windows = [
        EvidenceWindowV2(
            window_id=f"window-{index:04d}",
            product_id=product_id,
            product_part=product_part,
            start_offset_ms=start.session_offset_ms,
            end_offset_ms=end.session_offset_ms,
            video_start_ms=start.video_time_ms,
            video_end_ms=end.video_time_ms,
            playback_epoch=start.playback_epoch,
            evidence_codes=sorted(codes),
        )
        for index, (product_id, product_part, start, end, codes) in enumerate(
            windows_raw, start=1
        )
    ]
    quality = _data_quality(ordered, expected_observation_count=expected_observation_count)
    # No central call is made when there is no product window; B remains a
    # contract-valid diagnostic snapshot for the insufficient-data result.
    variant = input_variant if windows else "B"
    evidence_windows = windows if variant in {"A", "C"} else None
    timeline = [frame.model_copy(deep=True) for frame in ordered] if variant in {"A", "B"} else None
    evidence = RecommendationEvidenceV2(
        decision_request_id=decision_request_id,
        input_variant=variant,
        session_id=session_id,
        video_id=video_id,
        manifest_version=manifest_version,
        catalog_version=catalog_version,
        feature_version=FEATURE_VERSION,
        signal_versions=_signal_versions(ordered),
        data_quality=quality,
        summary=summaries,
        evidence_windows=evidence_windows,
        timeline=timeline,
    )
    return EvidenceSummary(
        evidence=evidence,
        eligible_product_ids=frozenset(eligible),
        continuity_reset_count=continuity_reset_count,
        missing_gaze_count=sum(frame.gaze is None for frame in ordered),
        missing_expression_count=sum(frame.expression is None for frame in ordered),
        ambiguous_attention_count=sum(
            frame.attention is not None and len(frame.attention.candidates) > 1
            for frame in ordered
        ),
    )

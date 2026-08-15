from __future__ import annotations

from collections import Counter
import copy

import numpy as np
import pytest

from live_accuracy import (
    AOI_HIT_GATE,
    LATENCY_P95_GATE_MS,
    NO_FACE_GATE,
    VALID_RATIO_GATE,
    assert_privacy_safe_summary,
    calibration_points_for,
    evaluate_overall_gate,
    evaluate_run_gate,
    extraction_failure_reason,
    get_screen_geometry,
    metric_stats,
    normalize_prediction,
    point_in_polygon,
    provisional_recommendation,
    select_ridge_alpha,
    summarize_target_metrics,
)


def passing_run() -> dict:
    run = {
        "calibration": {"completed": True},
        "valid_ratio": VALID_RATIO_GATE,
        "aoi_hit_ratio": AOI_HIT_GATE,
        "capture_to_result_ms": {"p95": LATENCY_P95_GATE_MS},
    }
    run["gate"] = evaluate_run_gate(run)
    return run


def test_prediction_normalization_does_not_clamp_outside_values() -> None:
    assert normalize_prediction((960, 540), 1920, 1080) == ((0.5, 0.5), None)
    assert normalize_prediction((-1, 540), 1920, 1080) == (None, "outside_viewport")
    assert normalize_prediction((float("nan"), 540), 1920, 1080) == (None, "invalid_prediction")


def test_no_face_and_blink_have_distinct_reasons() -> None:
    assert extraction_failure_reason(None, False) == "no_face"
    assert extraction_failure_reason([1.0], True) == "blink"
    assert extraction_failure_reason([1.0], False) is None


def test_point_in_polygon_includes_edges() -> None:
    polygon = ((0.1, 0.2), (0.4, 0.2), (0.4, 0.8), (0.1, 0.8))
    assert point_in_polygon((0.2, 0.4), polygon)
    assert point_in_polygon((0.1, 0.5), polygon)
    assert not point_in_polygon((0.5, 0.5), polygon)


def test_metric_stats_and_run_gate_boundaries() -> None:
    assert metric_stats([]) == {"count": 0, "mean": None, "p50": None, "p95": None}
    assert metric_stats([1.0, 2.0, 3.0])["p50"] == 2.0
    assert evaluate_run_gate(passing_run())["passed"] is True

    failed = passing_run()
    failed["valid_ratio"] = VALID_RATIO_GATE - 0.0001
    assert evaluate_run_gate(failed)["passed"] is False


def test_screen_geometry_uses_a_positive_logical_viewport() -> None:
    screen = get_screen_geometry()
    assert screen["coordinate_space"] == "logical_pixels"
    assert screen["width"] > 0
    assert screen["height"] > 0
    assert screen["physical_width"] > 0
    assert screen["physical_height"] > 0


def test_target_summary_exposes_aggregates_not_per_frame_coordinates() -> None:
    summary = summarize_target_metrics(
        target_index=1,
        product_id="P001",
        target_normalized=(0.2, 0.3),
        predictions_normalized=((0.2, 0.3), (0.3, 0.4)),
        total_frames=3,
        aoi_hits=2,
        failures=Counter({"blink": 1}),
        polygon=((0.08, 0.18), (0.46, 0.18), (0.46, 0.88), (0.08, 0.88)),
        width=1000,
        height=500,
    )
    assert summary["valid_ratio"] == pytest.approx(2 / 3, abs=0.0001)
    assert summary["median_predicted_normalized"] == {"x": 0.25, "y": 0.35}
    assert summary["median_aoi_hit"] is True
    assert "predictions" not in summary
    assert_privacy_safe_summary(summary)


def test_ridge_alpha_selection_uses_calibration_groups_only() -> None:
    features = np.asarray(
        [[-1.0], [-1.1], [-0.9], [0.0], [0.1], [-0.1], [1.0], [1.1], [0.9]],
        dtype=np.float64,
    )
    targets = np.column_stack((features[:, 0] * 100 + 500, features[:, 0] * 50 + 300))
    selected, summary = select_ridge_alpha(
        features,
        targets,
        samples_per_point=(3, 3, 3),
        candidates=(0.001, 1.0, 10.0),
    )
    assert selected == 0.001
    assert summary["method"] == "leave_one_calibration_point_out"
    assert [item["alpha"] for item in summary["candidates"]] == [0.001, 1.0, 10.0]


def test_dense_calibration_is_unique_serpentine_five_by_five() -> None:
    points = calibration_points_for("dense5")
    assert len(points) == 25
    assert len(set(points)) == 25
    assert points[:5] == tuple((x, 0.1) for x in (0.1, 0.3, 0.5, 0.7, 0.9))
    assert points[5:10] == tuple((x, 0.3) for x in (0.9, 0.7, 0.5, 0.3, 0.1))


def test_overall_gate_requires_three_passing_runs_and_no_face() -> None:
    runs = [passing_run(), passing_run(), passing_run()]
    no_face = {"no_face_ratio": NO_FACE_GATE, "camera_released": True}
    assert evaluate_overall_gate(runs, no_face)["passed"] is True

    runs[1]["gate"]["passed"] = False
    assert evaluate_overall_gate(runs, no_face)["passed"] is False


def test_only_three_run_baseline_can_drive_recommendation() -> None:
    assert provisional_recommendation("baseline", 3, True) == "eyetrax_provisional_priority"
    assert provisional_recommendation("baseline", 3, False) == "eyetrax_deferred_openvino_next"
    assert provisional_recommendation("head-motion", 3, True) == "diagnostic_only"
    assert provisional_recommendation("baseline", 1, True) == "diagnostic_only"


def test_privacy_check_allows_aggregate_flags_but_rejects_media() -> None:
    safe = {
        "privacy": {"raw_frame_saved": False, "per_frame_gaze_saved": False},
        "metrics": {"valid_ratio": 0.95},
        "preflight": {"frame_count": 90},
    }
    assert_privacy_safe_summary(safe)

    unsafe_key = copy.deepcopy(safe)
    unsafe_key["image"] = "not-even-bytes"
    with pytest.raises(ValueError, match="Privacy-unsafe result key"):
        assert_privacy_safe_summary(unsafe_key)

    unsafe_frames = copy.deepcopy(safe)
    unsafe_frames["frames"] = [{"x": 1}]
    with pytest.raises(ValueError, match="Privacy-unsafe result key"):
        assert_privacy_safe_summary(unsafe_frames)

    unsafe_path = copy.deepcopy(safe)
    unsafe_path["artifact"] = "participant.png"
    with pytest.raises(ValueError, match="Privacy-unsafe media path"):
        assert_privacy_safe_summary(unsafe_path)

    unsafe_identity = copy.deepcopy(safe)
    unsafe_identity["participant_name"] = "example"
    with pytest.raises(ValueError, match="Privacy-unsafe result key"):
        assert_privacy_safe_summary(unsafe_identity)

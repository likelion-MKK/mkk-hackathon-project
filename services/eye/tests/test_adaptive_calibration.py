"""Deterministic calibration control tests; these do not measure human gaze accuracy."""
from collections import Counter
import queue
import threading

import numpy as np
import pytest

from mcm_eye.calibration import (
    CHECK_POINTS, DENSE_POINTS, FINAL_POINTS, MIN_SAMPLES, SPARSE_POINTS, QUALITY_POLICY_ID,
    CalibrationFailure, Samples, SessionCalibration, evaluate,
)
from mcm_eye.calibration_capture import CalibrationPacket, SynchronizedCapture
from mcm_eye.face_positioning import FacePlacement


class Estimator:
    def predict(self, features):
        return features[:, :2]

    def extract_features(self, frame):
        return frame, False

    def extract_positioning(self, frame):
        roll = float(frame[-1]) if frame.size > 3 else 0
        return frame, False, FacePlacement(.5, .5, .3, .6, 0, 0, roll, True)


class Source:
    viewport = (1000, 500)

    def __init__(self, *, missing=(), bad=(), final_bad=False, cancel_after=None):
        self.calls = []
        self.buffers = []
        self.missing, self.bad = missing, bad
        self.final_bad, self.cancel_after = final_bad, cancel_after
        self.total_targets = 0

    def check_cancelled(self):
        if self.cancel_after is not None and len(self.calls) >= self.cancel_after:
            raise CalibrationFailure("calibration_cancelled")

    def set_fitting(self):
        pass

    def capture(self, point, phase):
        self.check_cancelled()
        self.calls.append((point, phase))
        empty = phase == "training" and point in self.missing
        wrong = (phase == "validation" and point in self.bad) or (phase == "verification" and self.final_bad)
        coordinates = [0, 0] if wrong else np.array(point) * self.viewport
        features = [np.array(coordinates) for _ in range(0 if empty else MIN_SAMPLES)]
        self.buffers.append(features)
        return Samples(features, len(features))


def engine(source, profile="adaptive-dense5-v2"):
    fits = []
    runner = SessionCalibration(Estimator(), source,
        lambda features, targets, counts: fits.append((targets.copy(), list(counts))),
        profile_id=profile)
    return runner, fits


@pytest.mark.parametrize("profile,points", [
    ("adaptive-dense5-v2", DENSE_POINTS), ("adaptive-sparse16-v2", SPARSE_POINTS),
    ("fixed-dense5-v2", DENSE_POINTS),
])
def test_profiles_keep_validation_out_of_training_and_release_samples(profile, points):
    source = Source()
    runner, fits = engine(source, profile)
    summary = runner.run()
    assert summary["valid"] and summary["repair_points"] == 0
    assert summary["quality_policy_id"] == QUALITY_POLICY_ID
    assert summary["quality_limits"] == {
        "session": {"valid_ratio_min": .85, "error_p50_max": .15, "error_p95_max": .30},
        "point": {"valid_ratio_min": .70, "error_p50_max": .25, "error_p95_max": .40},
    }
    assert Counter(phase for _, phase in source.calls) == {"positioning": 1, "training": len(points), "validation": 8}
    assert len(fits) == 1 and sum(fits[0][1]) == len(points) * MIN_SAMPLES
    assert set(map(tuple, fits[0][0])) == {tuple(np.array(p) * source.viewport) for p in points}
    assert all(not buffer for buffer in source.buffers)


def test_only_missing_training_point_is_repeated():
    source = Source(missing=(DENSE_POINTS[2],))
    runner, fits = engine(source)
    assert runner.run()["repair_points"] == 1
    assert [p for p, phase in source.calls if phase == "repair"] == [DENSE_POINTS[2]]
    assert fits[0][1] == [15] * 25


def test_local_error_repair_requires_fresh_validation_coordinates():
    source = Source(bad=(CHECK_POINTS[3],))
    runner, fits = engine(source)
    assert runner.run()["valid"]
    assert len(fits) == 2 and len(fits[1][1]) == 26
    assert [p for p, phase in source.calls if phase == "verification"] == list(FINAL_POINTS)
    assert all(tuple(np.array(p) * source.viewport) not in set(map(tuple, fits[1][0])) for p in CHECK_POINTS + FINAL_POINTS)
    assert all(not buffer for buffer in source.buffers)


@pytest.mark.parametrize("source,reason", [
    (Source(missing=DENSE_POINTS[:5]), "insufficient_calibration_samples"),
    (Source(bad=CHECK_POINTS), "validation_accuracy_failed"),
    (Source(bad=(CHECK_POINTS[3],), final_bad=True), "validation_accuracy_failed"),
    (Source(cancel_after=4), "calibration_cancelled"),
])
def test_failure_and_cancel_do_not_repeat_full_calibration(source, reason):
    runner, _ = engine(source)
    with pytest.raises(CalibrationFailure, match=reason):
        runner.run()
    assert not runner.summary["valid"]
    assert sum(phase == "training" for _, phase in source.calls) <= 25
    assert sum(phase == "repair" for _, phase in source.calls) <= 4
    assert all(not buffer for buffer in source.buffers)


def test_valid_ratio_and_coverage_cannot_be_hidden_by_good_average():
    good = Samples([np.array([500, 250])] * 17, 20)
    assert evaluate(Estimator(), [good], [(.5, .5)], 1000, 500).passed
    assert not evaluate(Estimator(), [Samples(good.features[:16], 20)], [(.5, .5)], 1000, 500).passed
    assert not evaluate(Estimator(), [good, Samples([], 0)], [(.5, .5), (.1, .1)], 1000, 500).passed


@pytest.mark.parametrize("lost,last_lost,passed,total", [(2, 1, True, 135), (3, 3, False, 144)])
def test_relaxed_signal_gate_keeps_denominator_and_avoids_unnecessary_retraining(lost, last_lost, passed, total):
    class GappySource(Source):
        def capture(self, point, phase):
            sample = super().capture(point, phase)
            if phase == "validation":
                missing = last_lost if point == CHECK_POINTS[-1] else lost
                sample.total += missing
                sample.invalid_counts = {"blink": missing}
                # A roughly 12% location error now passes along with 88.9% availability.
                for feature in sample.features:
                    feature[0] += 130
            return sample

    source = GappySource()
    runner, fits = engine(source)
    if passed:
        assert runner.run()["valid"]
    else:
        with pytest.raises(CalibrationFailure, match="^validation_signal_insufficient$"):
            runner.run()
    assert runner.summary["valid_ratio"] == pytest.approx(120 / total)
    assert runner.summary["error_diagonal_p50"] == pytest.approx(130 / np.hypot(1000, 500))
    assert runner.summary["failed_checks"] == ([] if passed else ["valid_ratio"])
    assert runner.summary["invalid_counts"] == {"blink": total - 120}
    assert runner.summary["valid_samples"] == 120
    assert runner.summary["total_samples"] == total
    assert len(runner.summary["point_results"]) == 8
    assert len(fits) == 1
    assert all(phase not in ("repair", "verification") for _, phase in source.calls)
    assert all(not buffer for buffer in source.buffers)
    # The summary is JSON-safe aggregate counts/errors, not retained features.
    import json
    assert "features" not in json.dumps(runner.summary, allow_nan=False)


def test_local_error_is_reported_even_when_global_error_passes():
    points = [(.5, .5)] * 8
    samples = [Samples([np.array([500, 250])] * 15, 15) for _ in points]
    samples[-1] = Samples([np.array([800, 250])] * 15, 15)
    quality = evaluate(Estimator(), samples, points, 1000, 500)
    assert quality.p50 <= .15 and quality.p95 <= .30
    assert quality.failure_reason == "validation_accuracy_failed"
    assert quality.bad_points == (7,)
    assert quality.point_results[-1]["failed_checks"] == ["median_error"]


def error_samples(errors, total=None):
    # Viewport diagonal is exactly 5000, so these are normalized distance errors.
    return Samples([np.array([300 + error * 5000, 2000]) for error in errors],
                   len(errors) if total is None else total)


@pytest.mark.parametrize("errors,expected", [
    ([.15] * 20, True), ([.1501] * 20, False),
    ([.05] * 16 + [.30] * 4, True), ([.05] * 16 + [.3001] * 4, False),
])
def test_relaxed_global_error_boundaries(errors, expected):
    quality = evaluate(Estimator(), [error_samples(errors)], [(.1, .5)], 3000, 4000)
    assert quality.passed is expected


@pytest.mark.parametrize("last,expected", [
    (error_samples([0.] * 14, 20), True), (error_samples([0.] * 13, 20), False),
    (error_samples([.25] * 20), True), (error_samples([.2501] * 20), False),
    (error_samples([0.] * 18 + [.40] * 2), True),
    (error_samples([0.] * 18 + [.4001] * 2), False),
    (Samples([], 20, {"no_face": 20}), False),
])
def test_relaxed_point_floor_allows_noise_but_rejects_a_blind_or_badly_mapped_region(last, expected):
    samples = [error_samples([0.] * 20) for _ in range(7)] + [last]
    quality = evaluate(Estimator(), samples, [(.1, .5)] * 8, 3000, 4000)
    assert quality.valid_ratio >= .85 and quality.p50 <= .15 and quality.p95 <= .30
    assert quality.passed is expected
    assert quality.bad_points == (() if expected else (7,))


def test_missing_observations_and_mixed_failures_have_distinct_reasons():
    incomplete = evaluate(Estimator(), [], [(.5, .5)], 1000, 500)
    assert not incomplete.passed
    assert incomplete.failure_reason == "validation_samples_insufficient"
    assert incomplete.bad_points == (0,)
    mixed = evaluate(Estimator(), [Samples([np.array([0, 0])] * 15, 18)], [(.5, .5)], 1000, 500)
    assert mixed.failure_reason == "validation_signal_and_accuracy_failed"


def test_invalid_prediction_causes_are_counted_without_clamping_coordinates():
    features = [np.array([500, 250])] * 15 + [np.array([float("nan"), 0]), np.array([-1, 250])]
    sample = Samples(features, 20, {"no_face": 1, "blink": 1, "invalid_features": 1})
    quality = evaluate(Estimator(), [sample], [(.5, .5)], 1000, 500)
    assert quality.valid_ratio == .75
    assert quality.point_results[0]["invalid_counts"] == {
        "no_face": 1, "blink": 1, "invalid_features": 1, "invalid_prediction": 1, "outside_viewport": 1,
    }


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


class Packets:
    """Queue fixture advances one camera frame or one empty wait at a time."""
    def __init__(self, clock, packets):
        self.clock, self.packets = clock, list(packets)

    def get(self, timeout):
        self.clock.now += .05
        if not self.packets:
            raise queue.Empty
        packet = self.packets.pop(0)
        packet.received_at = self.clock.now
        return packet

    def get_nowait(self):
        if not self.packets:
            raise queue.Empty
        return self.packets.pop(0)


def packets(n=60, *, marker_id="target-1", viewport=(1000, 500), pose=False):
    return [CalibrationPacket(np.array([500, 250, 0, 0, 0] if pose else [500, 250], dtype=float),
        {"calibration_id": "cal-test", "target_id": marker_id, "presented_at_mono_ms": 0},
        i * 50, 0, viewport) for i in range(n)]


def capture_fixture(values, profile="adaptive-dense5-v2"):
    clock = Clock()
    source = SynchronizedCapture(Estimator(), Packets(clock, values), threading.Event(), "cal-test", profile, clock=clock)
    return source, clock


def test_adaptive_capture_finishes_on_valid_samples_before_fixed_reference():
    fast, fast_clock = capture_fixture(packets())
    fixed, fixed_clock = capture_fixture(packets(), "fixed-dense5-v2")
    assert len(fast.capture((.5, .5), "training").features) == 15
    assert len(fixed.capture((.5, .5), "training").features) >= 15
    assert fast_clock.now < fixed_clock.now < 3.5
    fast.close(); fixed.close()


class GappyEstimator(Estimator):
    def extract_features(self, frame):
        if frame[0] == -1:
            return None, True
        return super().extract_features(frame)


@pytest.mark.parametrize("phase", ["validation", "verification"])
@pytest.mark.parametrize("blink_count", [2, 3])
def test_blink_tolerance_matches_relaxed_gate_without_erasing_failures(phase, blink_count):
    values = packets()
    for index in range(15, 15 + blink_count):
        values[index].frame[0] = -1
    source, clock = capture_fixture(values)
    source.estimator = GappyEstimator()
    result = source.capture((.5, .5), phase)
    required = 30 if blink_count == 3 else 15
    assert result.extended is (blink_count == 3)
    assert len(result.features) == required
    assert result.total == required + blink_count and result.invalid_counts == {"blink": blink_count}
    assert source.progress()["required_samples"] == required
    assert source.progress()["accepted_samples"] == required
    assert evaluate(Estimator(), [result], [(.5, .5)], 1000, 500).passed
    assert clock.now < 3.5
    source.close()
    assert all(packet.frame is None for packet in values)


def test_persistent_detection_gaps_fail_after_one_extra_block():
    values = packets()
    for index in range(12, len(values), 4):
        values[index].frame[0] = -1
    source, clock = capture_fixture(values)
    source.estimator = GappyEstimator()
    result = source.capture((.5, .5), "validation")
    assert result.extended and len(result.features) == 30
    assert result.total == len(result.features) + result.invalid_counts["blink"]
    assert not evaluate(Estimator(), [result], [(.5, .5)], 1000, 500).passed
    assert clock.now < 3.5
    source.close()


def test_slow_camera_extension_still_respects_target_deadline():
    values = packets()
    for index in (15, 16, 17):
        values[index].frame[0] = -1
    # Deliver enough for the first block, then stop the camera.
    values = values[:25]
    source, clock = capture_fixture(values)
    source.estimator = GappyEstimator()
    result = source.capture((.5, .5), "validation")
    assert result.extended and len(result.features) < 30
    assert 3.5 <= clock.now <= 3.6
    assert result.invalid_counts["blink"] == 3
    source.close()


def test_validation_pose_change_keeps_previous_observations_in_quality_counts():
    values = packets(pose=True)
    values[15].frame[0] = -1
    for packet in values[19:]:
        packet.frame[-1] = .1
    source, _ = capture_fixture(values)
    source.estimator = GappyEstimator()
    result = source.capture((.5, .5), "validation")
    assert result.invalid_counts["blink"] == 1
    assert result.invalid_counts["stabilizing"] > 0
    assert any(f[-1] == 0 for f in result.features)
    assert any(f[-1] == .1 for f in result.features)
    assert result.total == len(result.features) + sum(result.invalid_counts.values())
    source.close()


def test_capture_extension_does_not_peek_at_gaze_error_or_change_fixed_reference():
    class NoPredictionEstimator(GappyEstimator):
        def predict(self, _features):
            raise AssertionError("Capture must not select frames using the validation error")

    for profile, phase, gaps, expected_extended in (
        ("adaptive-dense5-v2", "validation", False, False),
        ("adaptive-dense5-v2", "validation", True, True),
        ("adaptive-dense5-v2", "training", True, False),
        ("fixed-dense5-v2", "validation", True, False),
    ):
        values = packets()
        if gaps:
            for index in (18, 19, 20):
                values[index].frame[0] = -1
        source, _ = capture_fixture(values, profile)
        source.estimator = NoPredictionEstimator()
        result = source.capture((.5, .5), phase)
        assert result.extended is expected_extended
        source.close()


def test_wrong_target_stale_marker_and_duplicate_timestamps_never_train():
    wrong = packets(8, marker_id="target-99")
    valid = packets()
    valid[9].marker["presented_at_mono_ms"] = 1
    valid[10].captured_ms = 400  # older than the previous capture
    source, _ = capture_fixture(wrong + valid)
    result = source.capture((.5, .5), "training")
    assert len(result.features) == 15
    assert all(packet.frame is None for packet in wrong)
    source.close()
    assert all(packet.frame is None for packet in valid)


def test_viewport_change_fails_instead_of_mixing_coordinate_scales():
    values = packets()
    values[18].viewport = (500, 1000)
    source, _ = capture_fixture(values)
    with pytest.raises(CalibrationFailure, match="viewport_changed"):
        source.capture((.5, .5), "validation")
    source.close()
    assert all(p.frame is None for p in values)


def test_cancel_and_session_deadline_release_queued_frames():
    for cancelled in (True, False):
        values = packets()
        source, _ = capture_fixture(values)
        if cancelled:
            source.cancel.set()
        else:
            source.deadline = 0
        with pytest.raises(CalibrationFailure, match="calibration_cancelled" if cancelled else "calibration_timed_out"):
            source.capture((.5, .5), "training")
        source.close()
        assert all(p.frame is None for p in values)


def test_slow_head_drift_does_not_pass_stability_by_small_per_frame_changes():
    values = packets(pose=True)
    for i, packet in enumerate(values):
        packet.frame[-1] = i * .02
    source, _ = capture_fixture(values)
    with pytest.raises(CalibrationFailure, match="face_position_not_ready"):
        source.capture((.5, .5), "positioning")
    source.close()


def test_positioning_requires_a_full_stable_second_before_training_can_start():
    values = packets(50)
    source, clock = capture_fixture(values)
    samples = source.capture((.5, .5), "positioning")
    assert len(samples.features) >= 15
    assert source.progress()["positioning"]["stable_ms"] == 1000
    assert clock.now >= 1.2
    source.close()
    assert all(p.frame is None for p in values)


def test_positioning_does_not_pass_with_many_samples_over_less_than_one_second():
    values = packets(100)
    for i, value in enumerate(values):
        value.captured_ms = 200 + i * 5
    source, _ = capture_fixture(values)
    with pytest.raises(CalibrationFailure, match="face_position_not_ready"):
        source.capture((.5, .5), "positioning")
    source.close()
    assert all(p.frame is None for p in values)


def test_blink_during_positioning_requires_a_new_stable_second():
    values = packets(55)
    values[15].frame[0] = -1
    source, clock = capture_fixture(values)
    class BlinkingEstimator(Estimator):
        def extract_positioning(self, frame):
            return frame, frame[0] == -1, FacePlacement(.5, .5, .3, .6, 0, 0, 0, True)
    source.estimator = BlinkingEstimator()
    samples = source.capture((.5, .5), "positioning")
    assert len(samples.features) >= 15
    assert clock.now >= 1.8
    assert all(feature[0] >= 0 for feature in samples.features)
    source.close()

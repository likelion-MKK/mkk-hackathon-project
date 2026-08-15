from __future__ import annotations

import math
import time

import numpy as np

from mcm_eye.adapters.gaze_stabilizer import GazeStabilizer


class PassthroughSmoother:
    def step(self, x: int, y: int) -> tuple[int, int]:
        return x, y


def passthrough_factory(_x: int, _y: int, _alpha: float) -> PassthroughSmoother:
    return PassthroughSmoother()


def stabilizer() -> GazeStabilizer:
    # 600-800-1000 gives exact diagonal percentage boundaries in integer pixels.
    return GazeStabilizer(600, 800, smoother_factory=passthrough_factory)


def test_rapid_shift_distance_and_speed_boundaries_are_inclusive() -> None:
    state = stabilizer()
    assert state.process_valid(100, 400, 0.0).valid is True

    # 350 px is exactly 35% of the 1000 px diagonal, and dt makes speed 3.0/s.
    boundary = state.process_valid(450, 400, 350.0 / 3.0)
    assert boundary.valid is False
    assert boundary.reason == "rapid_shift_pending"

    below = stabilizer()
    assert below.process_valid(100, 400, 0.0).valid is True
    assert below.process_valid(449, 400, 100.0).valid is True

    slow = stabilizer()
    assert slow.process_valid(100, 400, 0.0).valid is True
    assert slow.process_valid(450, 400, 117.0).valid is True


def test_confirmation_accepts_exact_120ms_and_12_percent_boundaries() -> None:
    state = stabilizer()
    assert state.process_valid(100, 400, 0.0).valid is True
    assert state.process_valid(450, 400, 100.0).reason == "rapid_shift_pending"

    confirmed = state.process_valid(570, 400, 220.0)
    assert confirmed.valid is True
    assert (confirmed.x_px, confirmed.y_px) == (570, 400)
    assert state.has_pending_shift is False


def test_blink_and_no_face_do_not_replace_pending_candidate() -> None:
    state = stabilizer()
    assert state.process_valid(100, 400, 0.0).valid is True
    assert state.process_valid(450, 400, 100.0).reason == "rapid_shift_pending"

    assert state.observe_invalid(140.0, "blink").reason == "blink"
    assert state.observe_invalid(180.0, "no_face").reason == "no_face"
    confirmed = state.process_valid(450, 400, 220.0)
    assert confirmed.valid is True
    assert (confirmed.x_px, confirmed.y_px) == (450, 400)


def test_one_frame_jump_is_discarded_when_gaze_returns() -> None:
    state = stabilizer()
    assert state.process_valid(100, 400, 0.0).valid is True
    candidate = state.process_valid(500, 400, 100.0)
    assert candidate.reason == "rapid_shift_pending"

    returned = state.process_valid(100, 400, 150.0)
    assert returned.valid is True
    assert (returned.x_px, returned.y_px) == (100, 400)


def test_expired_candidate_is_discarded_and_current_point_is_reevaluated() -> None:
    state = stabilizer()
    assert state.process_valid(0, 0, 0.0).valid is True
    assert state.process_valid(350, 0, 100.0).reason == "rapid_shift_pending"

    reevaluated = state.process_valid(600, 800, 221.0)
    assert reevaluated.valid is False
    assert reevaluated.reason == "rapid_shift_pending"
    assert state.has_pending_shift is True


def test_invalid_gap_over_500ms_resets_pending_and_smoother() -> None:
    state = stabilizer()
    assert state.process_valid(100, 400, 0.0).valid is True
    assert state.process_valid(450, 400, 100.0).reason == "rapid_shift_pending"
    state.observe_invalid(601.0, "no_face")

    after_gap = state.process_valid(450, 400, 602.0)
    assert after_gap.valid is True
    assert (after_gap.x_px, after_gap.y_px) == (450, 400)


def test_explicit_reset_discards_pending_state() -> None:
    state = stabilizer()
    assert state.process_valid(100, 400, 0.0).valid is True
    assert state.process_valid(450, 400, 100.0).reason == "rapid_shift_pending"
    state.reset()

    accepted = state.process_valid(450, 400, 101.0)
    assert accepted.valid is True
    assert state.has_pending_shift is False


def test_kalman_overshoot_is_not_clamped() -> None:
    class OvershootingSmoother:
        def step(self, _x: int, _y: int) -> tuple[int, int]:
            return 601, 400

    state = GazeStabilizer(
        600,
        800,
        smoother_factory=lambda _x, _y, _alpha: OvershootingSmoother(),
    )
    result = state.process_valid(300, 400, 0.0)
    assert result.valid is False
    assert result.reason == "outside_viewport"
    assert result.x_px is None
    assert result.y_px is None


def test_synthetic_fixed_point_meets_mvp_jitter_error_and_latency_gates() -> None:
    state = GazeStabilizer(600, 800, ema_alpha=0.25)
    target = np.asarray([300.0, 400.0])
    offsets = (
        (-30, 20),
        (30, -20),
        (-25, 15),
        (25, -15),
        (-20, 10),
        (20, -10),
    ) * 20
    raw_points: list[np.ndarray] = []
    filtered_points: list[np.ndarray] = []
    latencies_ms: list[float] = []

    for index, offset in enumerate(offsets):
        point = target + np.asarray(offset, dtype=np.float64)
        raw_points.append(point)
        started = time.perf_counter_ns()
        result = state.process_valid(point[0], point[1], index * (1000.0 / 30.0))
        latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        assert result.valid is True
        assert result.x_px is not None and result.y_px is not None
        filtered_points.append(np.asarray([result.x_px, result.y_px], dtype=np.float64))

    raw_jitter = np.linalg.norm(np.diff(np.asarray(raw_points), axis=0), axis=1)
    filtered_jitter = np.linalg.norm(np.diff(np.asarray(filtered_points), axis=0), axis=1)
    filtered_error_ratio = (
        np.linalg.norm(np.asarray(filtered_points) - target, axis=1) / 1000.0
    )

    assert float(np.percentile(filtered_jitter, 95)) <= 0.80 * float(
        np.percentile(raw_jitter, 95)
    )
    assert float(np.percentile(filtered_error_ratio, 95)) <= 0.25
    assert len(filtered_points) / len(raw_points) >= 0.90
    assert float(np.percentile(np.asarray(latencies_ms), 95)) <= 5.0


def test_non_finite_and_outside_inputs_are_invalid() -> None:
    state = stabilizer()
    assert state.process_valid(math.nan, 1.0, 0.0).reason == "invalid_prediction"
    assert state.process_valid(601.0, 1.0, 1.0).reason == "outside_viewport"

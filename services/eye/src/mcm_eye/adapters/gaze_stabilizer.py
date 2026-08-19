"""Runtime-only gaze stabilization for the EyeTrax selected Adapter.

Calibration quality is intentionally measured before this policy.  The state
below only decides which live raw points are safe to expose and then applies
EyeTrax's Kalman+EMA smoother.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

RAPID_SHIFT_DISTANCE_DIAGONAL = 0.35
RAPID_SHIFT_SPEED_DIAGONAL_PER_SECOND = 3.0
RAPID_SHIFT_CONFIRM_DISTANCE_DIAGONAL = 0.12
RAPID_SHIFT_CONFIRM_WINDOW_MS = 120.0
INVALID_RESET_GAP_MS = 500.0


class _PixelSmoother(Protocol):
    def step(self, x: int, y: int) -> tuple[int, int]: ...


class _SmootherFactory(Protocol):
    def __call__(self, x: int, y: int, ema_alpha: float) -> _PixelSmoother: ...


@dataclass(frozen=True, slots=True)
class StabilizerDecision:
    """One live-policy result; invalid results never carry coordinates."""

    valid: bool
    reason: str | None
    x_px: int | None = None
    y_px: int | None = None

    def __post_init__(self) -> None:
        if self.valid:
            if self.reason is not None or self.x_px is None or self.y_px is None:
                raise ValueError("valid stabilizer decisions require coordinates only")
        elif self.reason is None or self.x_px is not None or self.y_px is not None:
            raise ValueError("invalid stabilizer decisions require a reason only")


@dataclass(frozen=True, slots=True)
class _RapidShiftCandidate:
    x_px: int
    y_px: int
    captured_at_mono_ms: float


def _default_smoother_factory(
    x: int,
    y: int,
    ema_alpha: float,
) -> _PixelSmoother:
    from eyetrax.filters import KalmanEMASmoother, make_kalman

    initial_state = np.asarray([x, y, 0.0, 0.0], dtype=np.float32)
    return KalmanEMASmoother(
        make_kalman(dt=1.0 / 30.0, init_state=initial_state),
        ema_alpha=ema_alpha,
    )


class GazeStabilizer:
    """Confirm implausibly fast jumps, then apply EyeTrax Kalman+EMA."""

    def __init__(
        self,
        viewport_width_px: int,
        viewport_height_px: int,
        *,
        ema_alpha: float = 0.25,
        smoother_factory: _SmootherFactory | None = None,
    ) -> None:
        if viewport_width_px <= 0 or viewport_height_px <= 0:
            raise ValueError("viewport dimensions must be positive")
        if not math.isfinite(ema_alpha) or not 0.0 <= ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be between 0.0 and 1.0")
        self._width = viewport_width_px
        self._height = viewport_height_px
        self._diagonal = math.hypot(viewport_width_px, viewport_height_px)
        self._ema_alpha = float(ema_alpha)
        self._smoother_factory = smoother_factory or _default_smoother_factory
        self._smoother: _PixelSmoother | None = None
        self._pending: _RapidShiftCandidate | None = None
        self._last_confirmed_point: tuple[int, int] | None = None
        self._last_confirmed_at_ms: float | None = None
        self._last_valid_input_at_ms: float | None = None

    @property
    def has_pending_shift(self) -> bool:
        return self._pending is not None

    def reset(self) -> None:
        self._smoother = None
        self._pending = None
        self._last_confirmed_point = None
        self._last_confirmed_at_ms = None
        self._last_valid_input_at_ms = None

    def observe_invalid(self, captured_at_mono_ms: float, reason: str) -> StabilizerDecision:
        """Advance only expiry/reset clocks; never update the filter or candidate."""

        self._validate_timestamp(captured_at_mono_ms)
        if (
            self._pending is not None
            and captured_at_mono_ms - self._pending.captured_at_mono_ms
            > RAPID_SHIFT_CONFIRM_WINDOW_MS
        ):
            self._pending = None
        if (
            self._last_valid_input_at_ms is not None
            and captured_at_mono_ms - self._last_valid_input_at_ms > INVALID_RESET_GAP_MS
        ):
            self.reset()
        return StabilizerDecision(valid=False, reason=reason)

    def process_valid(
        self,
        x_px: float,
        y_px: float,
        captured_at_mono_ms: float,
    ) -> StabilizerDecision:
        """Process one raw point already associated with a valid EyeTrax face result."""

        self._validate_timestamp(captured_at_mono_ms)
        if not math.isfinite(x_px) or not math.isfinite(y_px):
            return StabilizerDecision(valid=False, reason="invalid_prediction")
        if not 0.0 <= x_px <= self._width or not 0.0 <= y_px <= self._height:
            return StabilizerDecision(valid=False, reason="outside_viewport")

        if (
            self._last_valid_input_at_ms is not None
            and captured_at_mono_ms < self._last_valid_input_at_ms
        ):
            return StabilizerDecision(valid=False, reason="out_of_order")
        if (
            self._last_valid_input_at_ms is not None
            and captured_at_mono_ms - self._last_valid_input_at_ms > INVALID_RESET_GAP_MS
        ):
            self.reset()

        point = (int(round(x_px)), int(round(y_px)))
        self._last_valid_input_at_ms = captured_at_mono_ms

        pending = self._pending
        if pending is not None:
            elapsed_ms = captured_at_mono_ms - pending.captured_at_mono_ms
            confirms_pending = (
                elapsed_ms <= RAPID_SHIFT_CONFIRM_WINDOW_MS
                and self._less_than_or_equal(
                    self._distance_ratio(point, (pending.x_px, pending.y_px)),
                    RAPID_SHIFT_CONFIRM_DISTANCE_DIAGONAL,
                )
            )
            self._pending = None
            if confirms_pending:
                return self._accept(point, captured_at_mono_ms, reinitialize=True)

        return self._evaluate_from_confirmed(point, captured_at_mono_ms)

    def _evaluate_from_confirmed(
        self,
        point: tuple[int, int],
        captured_at_mono_ms: float,
    ) -> StabilizerDecision:
        if self._last_confirmed_point is None or self._last_confirmed_at_ms is None:
            return self._accept(point, captured_at_mono_ms, reinitialize=True)

        distance_ratio = self._distance_ratio(point, self._last_confirmed_point)
        elapsed_ms = captured_at_mono_ms - self._last_confirmed_at_ms
        speed = math.inf if elapsed_ms <= 0.0 else distance_ratio / (elapsed_ms / 1000.0)
        if (
            self._greater_than_or_equal(
                distance_ratio,
                RAPID_SHIFT_DISTANCE_DIAGONAL,
            )
            and self._greater_than_or_equal(
                speed,
                RAPID_SHIFT_SPEED_DIAGONAL_PER_SECOND,
            )
        ):
            self._pending = _RapidShiftCandidate(
                x_px=point[0],
                y_px=point[1],
                captured_at_mono_ms=captured_at_mono_ms,
            )
            return StabilizerDecision(valid=False, reason="rapid_shift_pending")
        return self._accept(point, captured_at_mono_ms, reinitialize=False)

    def _accept(
        self,
        point: tuple[int, int],
        captured_at_mono_ms: float,
        *,
        reinitialize: bool,
    ) -> StabilizerDecision:
        self._last_confirmed_point = point
        self._last_confirmed_at_ms = captured_at_mono_ms
        if reinitialize or self._smoother is None:
            self._smoother = self._smoother_factory(point[0], point[1], self._ema_alpha)
        filtered_x, filtered_y = self._smoother.step(*point)
        if not 0 <= filtered_x <= self._width or not 0 <= filtered_y <= self._height:
            return StabilizerDecision(valid=False, reason="outside_viewport")
        return StabilizerDecision(
            valid=True,
            reason=None,
            x_px=int(filtered_x),
            y_px=int(filtered_y),
        )

    def _distance_ratio(
        self,
        first: tuple[int, int],
        second: tuple[int, int],
    ) -> float:
        return math.hypot(first[0] - second[0], first[1] - second[1]) / self._diagonal

    @staticmethod
    def _validate_timestamp(captured_at_mono_ms: float) -> None:
        if not math.isfinite(captured_at_mono_ms) or captured_at_mono_ms < 0.0:
            raise ValueError("captured_at_mono_ms must be a finite non-negative value")

    @staticmethod
    def _greater_than_or_equal(value: float, boundary: float) -> bool:
        return value > boundary or math.isclose(value, boundary, rel_tol=1e-12, abs_tol=1e-12)

    @staticmethod
    def _less_than_or_equal(value: float, boundary: float) -> bool:
        return value < boundary or math.isclose(value, boundary, rel_tol=1e-12, abs_tol=1e-12)


__all__ = [
    "GazeStabilizer",
    "INVALID_RESET_GAP_MS",
    "RAPID_SHIFT_CONFIRM_DISTANCE_DIAGONAL",
    "RAPID_SHIFT_CONFIRM_WINDOW_MS",
    "RAPID_SHIFT_DISTANCE_DIAGONAL",
    "RAPID_SHIFT_SPEED_DIAGONAL_PER_SECOND",
    "StabilizerDecision",
]

"""Bounded session calibration. Validation frames never train the estimator."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
import time
from typing import Callable

import numpy as np

DENSE_POINTS = tuple((x, y) for row, y in enumerate((.1, .3, .5, .7, .9))
                     for x in ((.1, .3, .5, .7, .9) if row % 2 == 0 else (.9, .7, .5, .3, .1)))
SPARSE_POINTS = tuple((x, y) for row, y in enumerate((.1, .366667, .633333, .9))
                      for x in ((.1, .366667, .633333, .9) if row % 2 == 0 else (.9, .633333, .366667, .1)))
CHECK_POINTS = ((.2, .3), (.38, .3), (.2, .7), (.42, .7),
                (.8, .3), (.62, .3), (.8, .7), (.58, .7))
# Used only AFTER error-guided repair; these coordinates never select repair or alpha.
FINAL_POINTS = ((.15, .2), (.35, .4), (.15, .8), (.45, .6),
                (.85, .2), (.65, .4), (.85, .8), (.55, .6))
MIN_SAMPLES = 15
MAX_REPAIR_POINTS = 4
SESSION_DEADLINE_SECONDS = 120
QUALITY_POLICY_ID = "webcam-relaxed-v1"


@dataclass(frozen=True)
class QualityLimits:
    valid_ratio_min: float
    error_p50_max: float
    error_p95_max: float


# User-approved local webcam tolerance, not a measured accuracy improvement.
# A separate point floor still rejects an unobserved or badly mapped region.
SESSION_LIMITS = QualityLimits(.85, .15, .30)
POINT_LIMITS = QualityLimits(.70, .25, .40)


class CalibrationFailure(RuntimeError):
    pass


@dataclass
class Samples:
    features: list[np.ndarray]
    total: int
    invalid_counts: dict[str, int] = field(default_factory=dict)
    extended: bool = False


@dataclass(frozen=True)
class Quality:
    valid_ratio: float
    p50: float
    p95: float
    bad_points: tuple[int, ...]
    sufficient: bool
    failed_checks: tuple[str, ...]
    point_results: tuple[dict[str, object], ...]

    @property
    def passed(self) -> bool:
        return (self.sufficient and self.valid_ratio >= SESSION_LIMITS.valid_ratio_min
                and self.p50 <= SESSION_LIMITS.error_p50_max
                and self.p95 <= SESSION_LIMITS.error_p95_max and not self.bad_points)

    @property
    def failure_reason(self) -> str:
        if "sample_coverage" in self.failed_checks:
            return "validation_samples_insufficient"
        signal_failed = "valid_ratio" in self.failed_checks
        accuracy_failed = any(check in self.failed_checks for check in ("median_error", "tail_error"))
        if signal_failed and accuracy_failed:
            return "validation_signal_and_accuracy_failed"
        if signal_failed:
            return "validation_signal_insufficient"
        return "validation_accuracy_failed" if accuracy_failed else "quality_gate_failed"


def _failed_checks(total, valid, p50, p95, limits: QualityLimits):
    checks = []
    if total < MIN_SAMPLES:
        checks.append("sample_coverage")
    if valid / max(1, total) < limits.valid_ratio_min:
        checks.append("valid_ratio")
    # No predictions means no measured accuracy, rather than an infinite error.
    if valid:
        if p50 > limits.error_p50_max:
            checks.append("median_error")
        if p95 > limits.error_p95_max:
            checks.append("tail_error")
    return checks


def evaluate(estimator, samples: list[Samples], points, width: int, height: int) -> Quality:
    errors: list[float] = []
    valid = 0
    total = sum(s.total for s in samples)
    bad: list[int] = []
    point_results = []
    failed_checks = set()
    sufficient = len(samples) == len(points)
    diagonal = math.hypot(width, height)
    for index, target in enumerate(points):
        sample = samples[index] if index < len(samples) else Samples([], 0)
        sufficient = sufficient and sample.total >= MIN_SAMPLES
        local: list[float] = []
        invalid_counts = Counter(sample.invalid_counts)
        unclassified = sample.total - len(sample.features) - sum(invalid_counts.values())
        if unclassified > 0:
            invalid_counts["unavailable_features"] += unclassified
        predictions = estimator.predict(np.asarray(sample.features)) if sample.features else []
        if len(predictions) < len(sample.features):
            invalid_counts["invalid_prediction"] += len(sample.features) - len(predictions)
        for prediction in predictions:
            p = np.asarray(prediction).reshape(-1)
            if len(p) != 2 or not np.isfinite(p).all():
                invalid_counts["invalid_prediction"] += 1
                continue
            if not (0 <= p[0] <= width and 0 <= p[1] <= height):
                invalid_counts["outside_viewport"] += 1
                continue
            valid += 1
            local.append(float(np.linalg.norm(p - np.array(target) * [width, height]) / diagonal))
        errors.extend(local)
        local_p50, local_p95 = np.percentile(local, [50, 95]) if local else (math.inf, math.inf)
        checks = _failed_checks(sample.total, len(local), local_p50, local_p95, POINT_LIMITS)
        if checks:
            bad.append(index)
        failed_checks.update(checks)
        point_results.append({
            "point_index": index + 1, "total_samples": sample.total, "valid_samples": len(local),
            "valid_ratio": len(local) / max(1, sample.total),
            "error_diagonal_p50": float(local_p50) if local else None,
            "error_diagonal_p95": float(local_p95) if local else None,
            "failed_checks": checks, "invalid_counts": dict(invalid_counts), "extended": sample.extended,
        })
    p50, p95 = np.percentile(errors, [50, 95]) if errors else (math.inf, math.inf)
    failed_checks.update(_failed_checks(total, valid, p50, p95, SESSION_LIMITS))
    if not sufficient:
        failed_checks.add("sample_coverage")
    return Quality(valid / max(1, total), float(p50), float(p95), tuple(bad), sufficient,
                   tuple(sorted(failed_checks)), tuple(point_results))


class SessionCalibration:
    def __init__(self, estimator, source, fit: Callable, *, profile_id: str, clock=time.monotonic,
                 repair_accuracy: bool = True):
        if profile_id not in ("adaptive-dense5-v2", "adaptive-sparse16-v2", "fixed-dense5-v2"):
            raise CalibrationFailure("invalid_calibration_request")
        self.estimator, self.source, self.fit = estimator, source, fit
        self.profile_id, self.clock = profile_id, clock
        self.repair_accuracy = repair_accuracy
        self.model_fitted = False
        self.started = clock()
        self.source.deadline = self.started + SESSION_DEADLINE_SECONDS
        self.summary: dict[str, object] = {
            "profile_id": profile_id, "quality_policy_id": QUALITY_POLICY_ID,
            "quality_limits": {
                "session": dict(vars(SESSION_LIMITS)), "point": dict(vars(POINT_LIMITS)),
            },
            "valid": False, "repair_points": 0,
        }

    def _check(self):
        if self.clock() - self.started > SESSION_DEADLINE_SECONDS:
            raise CalibrationFailure("calibration_timed_out")
        self.source.check_cancelled()

    def run(self) -> dict[str, object]:
        points = SPARSE_POINTS if self.profile_id == "adaptive-sparse16-v2" else DENSE_POINTS
        self.source.total_targets = 1 + len(points) + len(CHECK_POINTS)
        training: list[Samples] = []
        training_points = list(points)
        try:
            self._check()
            ready = self.source.capture((.5, .5), "positioning")
            try:
                if len(ready.features) < MIN_SAMPLES:
                    raise CalibrationFailure("unstable_head" if ready.features else "no_face")
            finally:
                # Readiness samples are never silently labelled as training.
                ready.features.clear()
            missing_count = 0
            empty_streak = 0
            for point in points:
                self._check()
                sample = self.source.capture(point, "training")
                training.append(sample)
                missing_count += len(sample.features) < MIN_SAMPLES
                empty_streak = empty_streak + 1 if not sample.features else 0
                if missing_count > MAX_REPAIR_POINTS or empty_streak >= 2:
                    raise CalibrationFailure("insufficient_calibration_samples")
            missing = [i for i, sample in enumerate(training) if len(sample.features) < MIN_SAMPLES]
            if len(missing) > MAX_REPAIR_POINTS:
                raise CalibrationFailure("insufficient_calibration_samples")
            self.source.total_targets += len(missing)
            for index in missing:
                self._check()
                self.summary["repair_points"] = int(self.summary["repair_points"]) + 1
                replacement = self.source.capture(points[index], "repair")
                training[index].features.clear()
                training[index] = replacement
                if len(replacement.features) < MIN_SAMPLES:
                    raise CalibrationFailure("insufficient_calibration_samples")
            self._fit(training, training_points)
            quality = self._validate(CHECK_POINTS, "validation")
            repairs = len(missing)
            # Gross/global failures do not trigger another complete calibration.
            if not quality.passed:
                if not self.repair_accuracy:
                    # Keep the measured failure; the adapter may use the fitted
                    # model with reduced confidence without another repair loop.
                    raise CalibrationFailure(quality.failure_reason)
                remaining = MAX_REPAIR_POINTS - repairs
                # More training cannot repair missing detections. Require reliable
                # observations before selecting extra training from measured errors.
                if (not quality.sufficient or "valid_ratio" in quality.failed_checks
                        or not quality.bad_points or len(quality.bad_points) > remaining):
                    raise CalibrationFailure(quality.failure_reason)
                extra = [(max(.05, min(.95, CHECK_POINTS[i][0] + .025)),
                          max(.05, min(.95, CHECK_POINTS[i][1] + .025))) for i in quality.bad_points]
                self.source.total_targets += len(extra) + len(FINAL_POINTS)
                for point in extra:
                    self._check()
                    self.summary["repair_points"] = int(self.summary["repair_points"]) + 1
                    sample = self.source.capture(point, "repair")
                    training.append(sample)
                    if len(sample.features) < MIN_SAMPLES:
                        raise CalibrationFailure("insufficient_calibration_samples")
                    training_points.append(point)
                repairs += len(extra)
                self._fit(training, training_points)
                quality = self._validate(FINAL_POINTS, "verification")
                if not quality.passed:
                    raise CalibrationFailure(quality.failure_reason)
            self.summary.update(valid=True, repair_points=repairs)
            return self.summary
        finally:
            self.summary["elapsed_ms"] = round((self.clock() - self.started) * 1000)
            for sample in training:
                sample.features.clear()
            training.clear()

    def _fit(self, samples, points):
        self._check()
        self.source.set_fitting()
        width, height = self.source.viewport
        features = np.asarray([f for s in samples for f in s.features])
        targets = np.asarray([np.array(point) * [width, height]
                              for point, sample in zip(points, samples) for _ in sample.features])
        try:
            self.model_fitted = False
            self.fit(features, targets, [len(s.features) for s in samples])
            self.model_fitted = True
        finally:
            del features, targets
        self._check()

    def _validate(self, points, phase):
        samples = []
        try:
            for point in points:
                self._check()
                samples.append(self.source.capture(point, phase))
            quality = evaluate(self.estimator, samples, points, *self.source.viewport)
            invalid_counts = Counter()
            for point in quality.point_results:
                invalid_counts.update(point["invalid_counts"])
            self.summary.update(valid_ratio=quality.valid_ratio,
                                error_diagonal_p50=quality.p50 if math.isfinite(quality.p50) else None,
                                error_diagonal_p95=quality.p95 if math.isfinite(quality.p95) else None,
                                checked_points=len(points),
                                total_samples=sum(s.total for s in samples),
                                valid_samples=sum(p["valid_samples"] for p in quality.point_results),
                                invalid_counts=dict(invalid_counts),
                                failed_checks=list(quality.failed_checks),
                                point_results=list(quality.point_results),
                                extended_points=sum(s.extended for s in samples))
            return quality
        finally:
            for sample in samples:
                sample.features.clear()

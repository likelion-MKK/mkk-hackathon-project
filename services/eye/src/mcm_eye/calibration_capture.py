"""Match bounded camera frames to the target actually presented by the browser."""

from __future__ import annotations

from collections import Counter
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from .calibration import CalibrationFailure, MIN_SAMPLES, SESSION_LIMITS, Samples
from .face_positioning import PositioningGate, POSITIONING_HOLD_MS, POSITIONING_TIMEOUT_SECONDS


@dataclass
class CalibrationPacket:
    frame: object
    marker: dict[str, object] | None
    captured_ms: float
    received_at: float
    viewport: tuple[int, int]


class SynchronizedCapture:
    def __init__(self, estimator, frame_queue, cancel, calibration_id, profile_id, *, clock=time.monotonic):
        self.estimator, self.queue, self.cancel = estimator, frame_queue, cancel
        self.calibration_id, self.profile_id, self.clock = calibration_id, profile_id, clock
        self.deadline = float("inf")
        self.viewport: tuple[int, int] | None = None
        self.total_targets = 34
        self.completed = 0
        self.serial = 0
        self.lock = threading.Lock()
        self._progress = None

    def check_cancelled(self):
        if self.clock() >= self.deadline:
            raise CalibrationFailure("calibration_timed_out")
        if self.cancel.is_set():
            raise CalibrationFailure("calibration_cancelled")

    def progress(self):
        with self.lock:
            return dict(self._progress) if self._progress else None

    def _update(self, **changes):
        with self.lock:
            if self._progress:
                self._progress.update(changes, total_targets=self.total_targets)

    def set_fitting(self):
        self._update(phase="fitting", hint="fitting")

    def capture(self, target, phase) -> Samples:
        self.check_cancelled()
        self.serial += 1
        target_id = f"target-{self.serial}"
        with self.lock:
            self._progress = {
                "calibration_id": self.calibration_id, "profile_id": self.profile_id,
                "phase": phase, "target_id": target_id, "target": list(target),
                "accepted_samples": 0, "required_samples": MIN_SAMPLES,
                "completed_targets": self.completed, "total_targets": self.total_targets,
                "hint": "follow_target",
            }
        started = self.clock()
        validation = phase in ("validation", "verification")
        fixed = self.profile_id == "fixed-dense5-v2" and phase != "positioning"
        settle_ms = (750 if phase in ("validation", "verification") else 1000) if fixed else 350
        limit = POSITIONING_TIMEOUT_SECONDS if phase == "positioning" else 3.5
        positioning_gate = PositioningGate() if phase == "positioning" else None
        positioned = False
        features = []
        total = 0
        invalid_counts = Counter()
        required_samples = MIN_SAMPLES
        extended = False
        presented_ms = None
        first_sample_ms = None
        last_captured = -1.0
        pose_anchor = None
        stable_since = None
        try:
            while self.clock() - started < limit:
                self.check_cancelled()
                try:
                    packet = self.queue.get(timeout=.05)
                except queue.Empty:
                    continue
                try:
                    marker = packet.marker
                    if (marker is None or marker["calibration_id"] != self.calibration_id
                            or marker["target_id"] != target_id
                            or self.clock() - packet.received_at > .25
                            or packet.captured_ms <= last_captured):
                        continue
                    last_captured = packet.captured_ms
                    if presented_ms is None:
                        presented_ms = float(marker["presented_at_mono_ms"])
                    if marker["presented_at_mono_ms"] != presented_ms:
                        continue
                    if self.viewport is None:
                        self.viewport = packet.viewport
                    elif self.viewport != packet.viewport:
                        raise CalibrationFailure("viewport_changed")
                    age_ms = packet.captured_ms - presented_ms
                    if age_ms < max(0, settle_ms - 150) or age_ms > limit * 1000:
                        continue
                    # A browser timestamp selects the interval; server arrival time never labels a target.
                    if positioning_gate is not None:
                        extract_positioning = getattr(self.estimator, "extract_positioning", None)
                        if not callable(extract_positioning):
                            raise CalibrationFailure("face_position_unavailable")
                        values, blink, placement = extract_positioning(packet.frame)
                        usable = values is not None and not blink and np.asarray(values).ndim == 1 and np.isfinite(values).all()
                        hint, state = positioning_gate.observe(placement, packet.captured_ms, usable=usable)
                        if blink and hint == "eyes_visible":
                            hint = "blink"
                        if state["stable_ms"] == 0:
                            features.clear()
                            total = 0
                        if hint == "position_ready":
                            features.append(np.asarray(values, dtype=np.float64).copy())
                            total += 1
                        self._update(hint=hint, positioning=state, accepted_samples=min(MIN_SAMPLES, len(features)))
                        if state["stable_ms"] >= POSITIONING_HOLD_MS and len(features) >= MIN_SAMPLES:
                            positioned = True
                            break
                        continue
                    values, blink = self.estimator.extract_features(packet.frame)
                    if values is None or blink:
                        if age_ms >= settle_ms:
                            total += 1
                            invalid_counts["blink" if blink else "no_face"] += 1
                        self._update(hint="blink" if blink else "no_face")
                        # Missing eyes alone do not establish head movement. In
                        # validation, compare the next pose with the same anchor.
                        if not validation:
                            stable_since = None
                        continue
                    values = np.asarray(values, dtype=np.float64)
                    if values.ndim != 1 or not np.isfinite(values).all():
                        if age_ms >= settle_ms:
                            total += 1
                            invalid_counts["invalid_features"] += 1
                        continue
                    pose = values[-3:] if values.size > 3 else None
                    if pose is not None and pose_anchor is not None and np.max(np.abs(pose - pose_anchor)) > .06:
                        if not validation:
                            features.clear()
                            first_sample_ms = None
                            total = 0
                            invalid_counts.clear()
                        stable_since = None
                        pose_anchor = None
                        self._update(accepted_samples=min(required_samples, len(features)), hint="hold_still")
                    if pose_anchor is None and pose is not None:
                        pose_anchor = pose.copy()
                    if stable_since is None:
                        stable_since = packet.captured_ms
                    if age_ms < settle_ms or packet.captured_ms - stable_since < 150:
                        # Check stability during settling, without labelling those frames.
                        if validation and age_ms >= settle_ms:
                            total += 1
                            invalid_counts["stabilizing"] += 1
                        continue
                    if first_sample_ms is None:
                        first_sample_ms = packet.captured_ms
                    total += 1
                    features.append(values.copy())
                    span = packet.captured_ms - first_sample_ms
                    # One fixed extra block for short detection gaps, decided only
                    # from feature availability, never from predicted gaze/error.
                    # Keep every earlier invalid observation in the denominator.
                    if (validation and not fixed and not extended
                            and len(features) >= MIN_SAMPLES and span >= 500
                            and len(features) / max(1, total) < SESSION_LIMITS.valid_ratio_min):
                        required_samples = MIN_SAMPLES * 2
                        extended = True
                    self._update(accepted_samples=min(required_samples, len(features)),
                                 required_samples=required_samples, hint="more_samples")
                    if fixed:
                        if span >= 1000 or len(features) >= 30:
                            break
                    elif len(features) >= required_samples and span >= 500:
                        break
                finally:
                    packet.frame = None
            if positioning_gate is not None and not positioned:
                raise CalibrationFailure("face_position_not_ready")
            self.completed += 1
            self._update(completed_targets=self.completed)
            return Samples(features, total, dict(invalid_counts), extended)
        except BaseException:
            features.clear()
            raise

    def close(self):
        with self.lock:
            self._progress = None
        while True:
            try:
                self.queue.get_nowait().frame = None
            except queue.Empty:
                break

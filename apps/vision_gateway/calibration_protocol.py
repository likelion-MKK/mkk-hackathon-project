"""Allowlisted, ephemeral calibration UI messages (no measured gaze or images)."""

from __future__ import annotations

import math
import re
from typing import Mapping

PROFILES = ("adaptive-dense5-v2", "adaptive-sparse16-v2", "fixed-dense5-v2")
PHASES = ("positioning", "training", "validation", "repair", "verification", "fitting")
HINTS = ("follow_target", "hold_still", "no_face", "blink", "more_samples", "fitting",
         "center_face", "move_closer", "move_back", "face_forward", "eyes_visible", "position_ready")
POSITIONING_FLAGS = ("face_detected", "eyes_visible", "centered", "distance_ok", "facing_forward")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _id(value: object) -> bool:
    return isinstance(value, str) and ID.fullmatch(value) is not None


def _number(value: object, lower: float, upper: float) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and lower <= value <= upper)


def validate_target_marker(value: object) -> dict[str, object]:
    fields = {"calibration_id", "target_id", "presented_at_mono_ms"}
    if (not isinstance(value, Mapping) or set(value) != fields
            or not _id(value.get("calibration_id")) or not _id(value.get("target_id"))
            or not _number(value.get("presented_at_mono_ms"), 0, 1e15)):
        raise ValueError("invalid calibration target marker")
    return dict(value)


def validate_progress(value: object) -> dict[str, object]:
    fields = {"calibration_id", "profile_id", "phase", "target_id", "target",
              "accepted_samples", "required_samples", "completed_targets", "total_targets", "hint"}
    if not isinstance(value, Mapping) or not fields <= set(value) or set(value) - fields - {"positioning"}:
        raise ValueError("invalid calibration progress fields")
    if (not _id(value.get("calibration_id")) or not _id(value.get("target_id"))
            or value.get("profile_id") not in PROFILES or value.get("phase") not in PHASES
            or value.get("hint") not in HINTS):
        raise ValueError("invalid calibration progress identity")
    target = value.get("target")
    if not isinstance(target, (list, tuple)) or len(target) != 2 or not all(_number(v, 0, 1) for v in target):
        raise ValueError("invalid calibration target")
    for field in ("accepted_samples", "required_samples", "completed_targets", "total_targets"):
        if not isinstance(value.get(field), int) or not _number(value[field], 0, 128):
            raise ValueError("invalid calibration progress count")
    if (value["required_samples"] < 1 or value["accepted_samples"] > value["required_samples"]
            or value["completed_targets"] > value["total_targets"]):
        raise ValueError("inconsistent calibration progress")
    if "positioning" in value:
        positioning = value["positioning"]
        if (value["phase"] != "positioning" or not isinstance(positioning, Mapping)
                or set(positioning) != {*POSITIONING_FLAGS, "stable_ms"}
                or any(type(positioning[key]) is not bool for key in POSITIONING_FLAGS)
                or type(positioning["stable_ms"]) is not int
                or not 0 <= positioning["stable_ms"] <= 1000
                or (positioning["stable_ms"] > 0 and not all(positioning[key] for key in POSITIONING_FLAGS))):
            raise ValueError("invalid face positioning progress")
    return {**value, "target": list(target)}

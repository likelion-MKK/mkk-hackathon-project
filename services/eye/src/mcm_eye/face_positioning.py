"""Session-only face placement heuristics, not identity or gaze estimates."""

from dataclasses import dataclass
import math

import numpy as np

POSITIONING_HOLD_MS = 1000
POSITIONING_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class FacePlacement:
    center_x: float
    center_y: float
    width: float
    height: float
    yaw: float
    pitch: float
    roll: float
    eyes_visible: bool

    def vector(self):
        return np.array([self.center_x, self.center_y, self.width, self.height,
                         self.yaw, self.pitch, self.roll])


def placement_from_landmarks(landmarks, image_width: int, image_height: int) -> FacePlacement | None:
    """Reduce the existing MediaPipe result to coarse geometry, then discard it.

    Angles are face-axis proxies. Face size is relative to the camera image,
    not a measurement in centimetres. All thresholds need hardware validation.
    """
    if len(landmarks) < 455 or image_width <= 0 or image_height <= 0:
        return None
    points = np.asarray([(p.x, p.y, p.z) for p in landmarks], dtype=float)
    if not np.isfinite(points).all():
        return None
    bounds = points[[10, 152, 234, 454], :2]
    lo, hi = bounds.min(axis=0), bounds.max(axis=0)
    pixels = points * [image_width, image_height, image_width]
    across = pixels[263] - pixels[33]
    upward = pixels[10] - (pixels[33] + pixels[263]) / 2
    across_norm = np.linalg.norm(across)
    if across_norm < 1 or np.linalg.norm(upward) < 1:
        return None
    x_axis = across / across_norm
    upward -= np.dot(upward, x_axis) * x_axis
    yaw = math.atan2(across[2], math.hypot(across[0], across[1]))
    pitch = math.atan2(upward[2], math.hypot(upward[0], upward[1]))
    roll = math.atan2(across[1], across[0])
    eyes_visible = True
    for outer, inner, top, bottom in ((33, 133, 159, 145), (263, 362, 386, 374)):
        eye = points[[outer, inner, top, bottom], :2]
        width = np.linalg.norm(pixels[outer, :2] - pixels[inner, :2])
        opening = np.linalg.norm(pixels[top, :2] - pixels[bottom, :2])
        eyes_visible = eyes_visible and bool(
            np.all((eye > .02) & (eye < .98)) and width >= 8 and opening / max(1, width) >= .12
        )
    return FacePlacement(float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2),
                         float(hi[0] - lo[0]), float(hi[1] - lo[1]), yaw, pitch, roll, eyes_visible)


class PositioningGate:
    def __init__(self):
        self.reset()

    def reset(self):
        self.anchor = None
        self.started_ms = None
        self.last_ms = None

    def observe(self, placement: FacePlacement | None, captured_ms: float, *, usable: bool):
        state = dict(face_detected=False, eyes_visible=False, centered=False,
                     distance_ok=False, facing_forward=False, stable_ms=0)
        if placement is None or not np.isfinite(placement.vector()).all():
            self.reset()
            return "no_face", state
        p = placement
        state.update(face_detected=True, eyes_visible=bool(p.eyes_visible and usable),
                     centered=abs(p.center_x - .5) <= .12 and abs(p.center_y - .5) <= .14,
                     distance_ok=.32 <= p.height <= .78 and .12 <= p.width <= .65,
                     facing_forward=abs(p.yaw) <= .45 and abs(p.pitch) <= .55 and abs(p.roll) <= .25)
        if not all(state[key] for key in ("eyes_visible", "centered", "distance_ok", "facing_forward")):
            self.reset()
            hint = ("move_closer" if p.height < .32 or p.width < .12 else
                    "move_back" if not state["distance_ok"] else
                    "center_face" if not state["centered"] else
                    "face_forward" if not state["facing_forward"] else "eyes_visible")
            return hint, state
        vector = p.vector()
        drift = self.anchor is not None and np.any(np.abs(vector - self.anchor) > [.025, .035, .035, .045, .06, .06, .06])
        gap = self.last_ms is not None and not 0 < captured_ms - self.last_ms <= 250
        if self.anchor is None or drift or gap:
            self.anchor, self.started_ms = vector, captured_ms
        self.last_ms = captured_ms
        state["stable_ms"] = min(POSITIONING_HOLD_MS, max(0, round(captured_ms - self.started_ms)))
        return "position_ready", state

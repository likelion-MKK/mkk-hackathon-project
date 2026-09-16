from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from mcm_eye.face_positioning import FacePlacement, PositioningGate, placement_from_landmarks

GOOD = FacePlacement(.5, .5, .3, .6, 0, .1, 0, True)


@pytest.mark.parametrize("placement,hint", [
    (None, "no_face"), (replace(GOOD, center_x=.75), "center_face"),
    (replace(GOOD, height=.2), "move_closer"), (replace(GOOD, height=.9), "move_back"),
    (replace(GOOD, yaw=.6), "face_forward"), (replace(GOOD, pitch=.7), "face_forward"),
    (replace(GOOD, roll=.3), "face_forward"), (replace(GOOD, eyes_visible=False), "eyes_visible"),
    (replace(GOOD, center_x=float("nan")), "no_face"),
])
def test_misalignment_restarts_the_hold(placement, hint):
    gate = PositioningGate()
    for timestamp in range(0, 901, 100):
        gate.observe(GOOD, timestamp, usable=True)
    actual, state = gate.observe(placement, 1000, usable=True)
    assert actual == hint and state["stable_ms"] == 0
    assert gate.observe(GOOD, 1100, usable=True)[1]["stable_ms"] == 0


def test_frame_gaps_blinks_and_slow_translation_do_not_count_as_a_stable_second():
    gate = PositioningGate()
    gate.observe(GOOD, 0, usable=True)
    assert gate.observe(GOOD, 100, usable=True)[1]["stable_ms"] == 100
    assert gate.observe(GOOD, 900, usable=True)[1]["stable_ms"] == 0
    assert gate.observe(GOOD, 1000, usable=False)[1]["stable_ms"] == 0
    for i in range(30):
        _, state = gate.observe(replace(GOOD, center_x=.5 + i * .004), 1100 + i * 50, usable=True)
        assert state["stable_ms"] < 1000


def face_landmarks():
    points = [SimpleNamespace(x=.5, y=.5, z=0.) for _ in range(478)]
    for index, (x, y) in {
        10:(.5,.2), 152:(.5,.8), 234:(.32,.5), 454:(.68,.5),
        33:(.37,.4), 133:(.44,.4), 159:(.405,.39), 145:(.405,.41),
        263:(.63,.4), 362:(.56,.4), 386:(.595,.39), 374:(.595,.41),
    }.items():
        points[index] = SimpleNamespace(x=x, y=y, z=0.)
    return points


def test_geometry_uses_both_eyes_and_camera_aspect_ratio():
    points = face_landmarks()
    placement = placement_from_landmarks(points, 1280, 720)
    assert placement is not None and placement.eyes_visible
    assert placement.center_x == pytest.approx(.5)
    assert placement.height == pytest.approx(.6)
    assert PositioningGate().observe(placement, 0, usable=True)[0] == "position_ready"
    points[374] = points[386]  # One closed eye must not be hidden by the other.
    assert not placement_from_landmarks(points, 1280, 720).eyes_visible
    assert placement_from_landmarks(points[:200], 1280, 720) is None


def test_guided_estimator_reuses_detector_and_does_not_keep_landmarks(monkeypatch):
    from mcm_eye.guided_estimator import GuidedGazeEstimator, _PositioningLandmarker
    from eyetrax import GazeEstimator
    result = SimpleNamespace(face_landmarks=[face_landmarks()])
    calls = []
    class Detector:
        def detect_for_video(self, image, timestamp):
            calls.append(timestamp)
            return result
        def close(self):
            pass
    estimator = object.__new__(GuidedGazeEstimator)
    observer = _PositioningLandmarker(Detector())
    estimator._face_landmarker = observer
    def extract(self, image):
        self._face_landmarker.detect_for_video(None, 1)
        return np.zeros(6), False
    monkeypatch.setattr(GazeEstimator, "extract_features", extract)
    _, _, placement = estimator.extract_positioning(np.zeros((720, 1280, 3)))
    assert placement.eyes_visible and len(calls) == 1
    assert observer.placement is None and observer.image_size is None
    result.face_landmarks = []
    assert estimator.extract_positioning(np.zeros((720, 1280, 3)))[2] is None
    estimator.close()

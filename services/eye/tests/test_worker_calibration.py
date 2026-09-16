from pathlib import Path
import queue
import threading

import numpy as np

import mcm_eye.worker as worker
from mcm_eye.calibration import DENSE_POINTS
from mcm_eye.calibration_capture import SynchronizedCapture
from apps.vision_gateway.vision_stream import decode_binary_frame, encode_binary_frame


class Adapter:
    discarded = False
    def __init__(self, *_args):
        pass
    def initialize(self):
        pass
    def warmup(self):
        pass
    def _require_estimator(self):
        return self
    def extract_features(self, frame):
        return frame, False
    def discard_calibration(self):
        self.discarded = True
    def dispose(self):
        pass


def runtime(monkeypatch):
    monkeypatch.setattr(worker, "EyeTraxAdapter", Adapter)
    return worker.EyeWorkerRuntime(model_path=Path("unused-fixture.task"))


def binary(sequence, *, session="session-test", marker="target-1"):
    import json
    root = Path(__file__).resolve().parents[3]
    value = json.loads((root / "contracts/examples/vision-stream-calibration-frame.valid.json").read_text(encoding="utf-8"))
    value.update(session_id=session, video_id="video-test", sequence=sequence,
                 frame_id=f"frame-{sequence}", captured_at_mono_ms=sequence * 50.)
    value["calibration_target"].update(calibration_id="cal-test", target_id=marker)
    return decode_binary_frame(encode_binary_frame(value, b"\xff\xd8\xff\xd9"), max_frame_bytes=524288)


def test_worker_rejects_unknown_profiles_and_mismatched_training_coordinates(monkeypatch):
    app = runtime(monkeypatch)
    for pattern in ({"pattern_id": "unknown", "points": []},
                    {"pattern_id": "adaptive-dense5-v2", "points": [[.5, .5]]}):
        assert not app.run_calibration({"calibration_id": "cal-test", "pattern": pattern})["valid"]
    assert app._calibration_queue is None


def test_worker_keeps_only_four_current_frames_and_enforces_session_order(monkeypatch):
    app = runtime(monkeypatch)
    app._binding = ("session-test", "video-test")
    app._calibration_queue = queue.Queue(maxsize=worker.CALIBRATION_QUEUE_SIZE)
    source = SynchronizedCapture(Adapter(), app._calibration_queue, threading.Event(), "cal-test", "adaptive-dense5-v2")
    app._synchronized_source = source
    class Decoded:
        value = np.array([1., 2.])
    monkeypatch.setattr(worker, "default_frame_decoder", lambda *_: Decoded())
    for i in range(10):
        assert app.infer(binary(i))["gaze_reason"] == "calibration_in_progress"
    assert app._calibration_queue.qsize() == 4
    assert app.infer(binary(9))["gaze_reason"] == "gaze_context_mismatch"
    assert app.infer(binary(11, session="another-session"))["gaze_reason"] == "gaze_context_mismatch"
    queued = list(app._calibration_queue.queue)
    assert [p.captured_ms for p in queued] == [300., 350., 400., 450.]
    app.close()
    assert all(p.frame is None for p in queued)


def test_end_session_cannot_discard_another_customer_model(monkeypatch):
    app = runtime(monkeypatch)
    app.calibrated = True
    app.calibration_id = "cal-test"
    app._calibrated_binding = ("session-test", "video-test")
    app.last_calibration_summary = {"valid": True}
    app.end_session("different", "video-test")
    assert app.calibrated and not app._adapter.discarded
    app.end_session("session-test", "video-test")
    assert not app.calibrated and app.calibration_id is None
    assert app._adapter.discarded and app.last_calibration_summary is None


def test_cancellation_cannot_be_overwritten_by_late_success(monkeypatch):
    app = runtime(monkeypatch)
    class Result:
        valid = True
        reason = None
    def late_success(*_):
        app.cancel_calibration()
        app._adapter.calibration_summary = {"valid": True}
        return Result()
    app._adapter.calibrate_synchronized = late_success
    result = app.run_calibration({"calibration_id": "cal-test", "session_id": "session-test", "video_id": "video-test",
                                  "pattern": {"pattern_id": "adaptive-dense5-v2", "points": [list(p) for p in DENSE_POINTS]}})
    assert result == {"valid": False, "reason": "calibration_cancelled"}
    assert not app.calibrated and app._calibration_queue is None and app._synchronized_source is None


def test_cancel_request_with_reused_calibration_id_cannot_cancel_another_session(monkeypatch):
    app = runtime(monkeypatch)
    app.calibration_id = "cal-test"
    app._binding = ("new-session", "video-test")
    app.cancel_matching_calibration({"calibration_id": "cal-test", "session_id": "old-session", "video_id": "video-test"})
    assert not app._calibration_cancel.is_set()
    app.cancel_matching_calibration({"calibration_id": "cal-test", "session_id": "new-session", "video_id": "video-test"})
    assert app._calibration_cancel.is_set()


def test_worker_binds_weak_fitted_model_without_marking_quality_passed(monkeypatch):
    from mcm_eye.contracts import CalibrationResult
    app = runtime(monkeypatch)
    def weak_result(*_):
        app._adapter.calibration_summary = {"valid": False, "inference_ready": True}
        app._adapter.inference_ready = True
        return CalibrationResult("cal-test", False, "validation_accuracy_failed")
    app._adapter.calibrate_synchronized = weak_result
    result = app.run_calibration({"calibration_id": "cal-test", "session_id": "session-test", "video_id": "video-test",
                                 "pattern": {"pattern_id": "adaptive-dense5-v2", "points": [list(p) for p in DENSE_POINTS]}})
    assert result == {"valid": False, "reason": "validation_accuracy_failed"}
    assert not app.calibrated and app.inference_ready
    assert app._calibrated_binding == ("session-test", "video-test")
    assert app.infer(binary(10, session="another-session"))["gaze_reason"] == "gaze_context_mismatch"
    app.end_session("session-test", "video-test")
    assert not app.inference_ready and app._adapter.discarded
    assert app.infer(binary(11))["gaze_sample"] is None

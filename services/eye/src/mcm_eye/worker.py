"""Private Python 3.12 Eye worker process.

The Gateway owns the WebSocket and Face worker. This process owns EyeTrax and
the pinned FaceLandmarker asset. Frames are decoded only in this process and
are either consumed by the bounded calibration queue or immediately converted
to one derived ``GazeSample``. No frame is written to disk or returned over
the worker boundary.
"""

from __future__ import annotations

import contextlib
import asyncio
import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from apps.vision_gateway.vision_stream import (
    DecodedBinaryFrame,
    VisionStreamProtocolError,
    decode_binary_frame,
    default_frame_decoder,
)
from mcm_eye.adapters.eyetrax import (
    CalibrationCancelled,
    EyeTraxAdapter,
    EyeTraxConfig,
)
from mcm_eye.contracts import CalibrationRequest


MAX_BODY_BYTES = 524_288
CALIBRATION_QUEUE_SIZE = 4


@dataclass(frozen=True, slots=True)
class _Context:
    session_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int


class _QueueCalibrationFrames:
    """Adapt the async ingress queue to EyeTrax's synchronous frame source."""

    def __init__(
        self,
        queue_getter: Callable[[], queue.Queue[Any] | None],
        cancel_event: threading.Event,
    ) -> None:
        self._queue_getter = queue_getter
        self._cancel_event = cancel_event

    def __call__(self, capture: Any) -> Iterable[Any]:
        frame_queue = self._queue_getter()
        if frame_queue is None:
            return

        started_at = time.monotonic()
        collect_at = started_at + float(capture.adaptation_seconds)
        deadline = collect_at + float(capture.collection_seconds)
        while time.monotonic() < deadline:
            if self._cancel_event.is_set():
                raise CalibrationCancelled()
            remaining = max(0.01, deadline - time.monotonic())
            try:
                frame = frame_queue.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if time.monotonic() < collect_at:
                # The adapter deliberately discards adaptation frames. The
                # target is held by the browser during this interval.
                del frame
                continue
            yield frame


class EyeWorkerRuntime:
    def __init__(self, *, model_path: Path, width_px: int = 640, height_px: int = 480) -> None:
        self.model_path = model_path
        self.ready = False
        self.calibrated = False
        self.inference_ready = False
        self.calibration_id: str | None = None
        self.failure_reason: str | None = None
        self._adapter: EyeTraxAdapter | None = None
        self._state_lock = threading.RLock()
        self._adapter_call_lock = threading.RLock()
        self._calibration_queue: queue.Queue[Any] | None = None
        self._calibration_cancel = threading.Event()
        self._synchronized_source = None
        self._binding = None
        self._calibrated_binding = None
        self._summary_binding = None
        self._last_calibration_sequence = -1
        self.last_calibration_summary = None
        calibration_source = _QueueCalibrationFrames(
            lambda: self._calibration_queue,
            self._calibration_cancel,
        )
        try:
            adapter = EyeTraxAdapter(
                EyeTraxConfig(
                    viewport_width_px=width_px,
                    viewport_height_px=height_px,
                    face_model_path=model_path,
                    smoothing_mode="raw",
                ),
                calibration_source,
            )
            adapter.initialize()
            adapter.warmup()
            self._adapter = adapter
            self.ready = True
        except Exception as exc:
            self.failure_reason = f"eye_model_unavailable:{type(exc).__name__}"

    def run_calibration(self, payload: Mapping[str, object]) -> dict[str, object]:
        calibration_id = payload.get("calibration_id")
        pattern = payload.get("pattern")
        if not isinstance(calibration_id, str) or not isinstance(pattern, Mapping):
            return {"valid": False, "reason": "invalid_calibration_request"}

        from apps.vision_gateway.calibration_protocol import PROFILES
        from mcm_eye.calibration import DENSE_POINTS, SPARSE_POINTS
        profile_id = pattern.get("pattern_id")
        synchronized = profile_id in PROFILES
        if synchronized:
            expected = SPARSE_POINTS if profile_id == "adaptive-sparse16-v2" else DENSE_POINTS
            if pattern.get("points") != [list(p) for p in expected]:
                return {"valid": False, "reason": "invalid_calibration_request"}
            if not isinstance(payload.get("session_id"), str) or not isinstance(payload.get("video_id"), str):
                return {"valid": False, "reason": "invalid_calibration_request"}
        elif profile_id != "dense5-validation-v1":
            return {"valid": False, "reason": "unsupported_calibration_profile"}

        with self._state_lock:
            adapter = self._adapter
            if not self.ready or adapter is None:
                return {"valid": False, "reason": "eye_not_connected"}
            if self._calibration_queue is not None:
                return {"valid": False, "reason": "calibration_in_progress"}
            self.calibrated = False
            self.inference_ready = False
            self.last_calibration_summary = None
            self._calibrated_binding = None
            self.calibration_id = calibration_id
            self._calibration_cancel.clear()
            self._calibration_queue = queue.Queue(maxsize=CALIBRATION_QUEUE_SIZE)
            self._binding = (payload.get("session_id"), payload.get("video_id"))
            self._summary_binding = self._binding
            self._last_calibration_sequence = -1
            if synchronized:
                from mcm_eye.calibration_capture import SynchronizedCapture
                self._synchronized_source = SynchronizedCapture(
                    adapter._require_estimator(), self._calibration_queue,
                    self._calibration_cancel, calibration_id, profile_id)


        result_valid = False
        inference_ready = False
        result_reason = "calibration_failed"
        calibration_queue: queue.Queue[Any] | None = None
        try:
            with self._adapter_call_lock:
                if synchronized:
                    result = adapter.calibrate_synchronized(CalibrationRequest(calibration_id), self._synchronized_source, profile_id)
                    self.last_calibration_summary = adapter.calibration_summary
                else:
                    result = adapter.calibrate(CalibrationRequest(calibration_id))
            result_valid = result.valid
            # Do not retain a fitted-but-failed mapping.  The Kiosk must restart
            # calibration instead of turning a failed quality check into gaze
            # events with a lower confidence label.
            inference_ready = result_valid
            result_reason = result.reason or "calibration_failed"
        except Exception as exc:
            result_reason = f"calibration_error:{type(exc).__name__}"
        finally:
            with self._adapter_call_lock, self._state_lock:
                if self._calibration_cancel.is_set():
                    result_valid = False
                    inference_ready = False
                    result_reason = "calibration_cancelled"
                    adapter.discard_calibration()
                    if self.last_calibration_summary is not None:
                        self.last_calibration_summary.update(valid=False, reason=result_reason, inference_ready=False,
                                                             confidence_weight=0.0)
                if not result_valid:
                    adapter.discard_calibration()
                    if self.last_calibration_summary is not None:
                        self.last_calibration_summary.update(
                            valid=False,
                            reason=result_reason,
                            inference_ready=False,
                            confidence_weight=0.0,
                        )
                self.calibrated = result_valid
                self.inference_ready = inference_ready
                self.calibration_id = calibration_id if inference_ready else None
                self._calibrated_binding = self._binding if inference_ready else None
                calibration_queue = self._calibration_queue
                self._calibration_queue = None
                self._synchronized_source = None
                self._binding = None
            self._drain_calibration_queue(calibration_queue)

        return {
            "valid": result_valid,
            "reason": None if result_valid else result_reason,
        }

    def cancel_calibration(self) -> None:
        self._calibration_cancel.set()

    def cancel_matching_calibration(self, payload: Mapping[str, object]) -> None:
        with self._state_lock:
            if (payload.get("calibration_id") == self.calibration_id
                    and self._binding == (payload.get("session_id"), payload.get("video_id"))):
                self._calibration_cancel.set()

    def infer(self, binary: DecodedBinaryFrame) -> dict[str, object]:
        with self._state_lock:
            adapter = self._adapter
            calibration_queue = self._calibration_queue
            calibrated = self.inference_ready
            ready = self.ready
            synchronized = self._synchronized_source
            binding = self._binding
            calibrated_binding = self._calibrated_binding

        if not ready or adapter is None:
            return {"gaze_sample": None, "gaze_reason": "eye_not_connected"}

        if calibration_queue is not None:
            # Calibration frames are decoded in the private Eye process and
            # queued as BGR arrays only for the current target interval.
            decoded = default_frame_decoder(binary.image_bytes, binary.metadata)
            frame = decoded.value
            decoded.value = None
            if synchronized is not None:
                from mcm_eye.calibration_capture import CalibrationPacket
                context = binary.metadata.context
                with self._state_lock:
                    accepted = (self._calibration_queue is calibration_queue
                                and (context.session_id, context.video_id) == binding
                                and context.playback_epoch == 0
                                and context.sequence > self._last_calibration_sequence)
                    if accepted:
                        self._last_calibration_sequence = context.sequence
                if not accepted:
                    del frame
                    return {"gaze_sample": None, "gaze_reason": "gaze_context_mismatch"}
                frame = CalibrationPacket(frame, binary.metadata.calibration_target,
                    context.captured_at_mono_ms, time.monotonic(),
                    (int(binary.metadata.layout["viewport_width_px"]), int(binary.metadata.layout["viewport_height_px"])))
            with self._state_lock:
                if self._calibration_queue is not calibration_queue:
                    if synchronized is not None:
                        frame.frame = None
                    return {"gaze_sample": None, "gaze_reason": "gaze_unavailable"}
                try:
                    calibration_queue.put_nowait(frame)
                except queue.Full:
                    # Keep a small current backlog; stale frames never train another target.
                    with contextlib.suppress(queue.Empty):
                        old = calibration_queue.get_nowait()
                        if synchronized is not None:
                            old.frame = None
                    calibration_queue.put_nowait(frame)
            progress = synchronized.progress() if synchronized is not None else None
            return {"gaze_sample": None, "gaze_reason": "calibration_in_progress",
                    **({"calibration_progress": progress} if progress is not None else {})}

        if not calibrated:
            return {"gaze_sample": None, "gaze_reason": "gaze_unavailable"}

        context = binary.metadata.context
        if calibrated_binding != (context.session_id, context.video_id):
            return {"gaze_sample": None, "gaze_reason": "gaze_context_mismatch"}
        decoded = default_frame_decoder(binary.image_bytes, binary.metadata)
        gaze_context = _Context(
            session_id=context.session_id,
            sequence=context.sequence,
            frame_id=context.frame_id,
            captured_at_mono_ms=context.captured_at_mono_ms,
            video_id=context.video_id,
            video_time_ms=context.video_time_ms,
            playback_epoch=context.playback_epoch,
        )
        try:
            with self._adapter_call_lock:
                sample = adapter.infer(decoded.value, gaze_context)
            return {
                "gaze_sample": sample.to_payload(),
                "gaze_reason": None if sample.valid else sample.reason,
            }
        finally:
            decoded.close()

    def _drain_calibration_queue(self, frame_queue: queue.Queue[Any] | None = None) -> None:
        frame_queue = frame_queue or self._calibration_queue
        if frame_queue is None:
            return
        while True:
            try:
                item = frame_queue.get_nowait()
                if hasattr(item, "frame"):
                    item.frame = None
            except queue.Empty:
                return

    def end_session(self, session_id: str, video_id: str) -> None:
        binding = (session_id, video_id)
        with self._state_lock:
            if binding not in (self._binding, self._calibrated_binding, self._summary_binding):
                return
            self._calibration_cancel.set()
        with self._adapter_call_lock:
            with self._state_lock:
                if binding not in (self._binding, self._calibrated_binding, self._summary_binding):
                    return
                if self._binding not in (binding, None):
                    return
                self.calibrated = False
                self.inference_ready = False
                self.calibration_id = None
                self._calibrated_binding = None
                self.last_calibration_summary = None
                self._summary_binding = None
                if self._adapter is not None:
                    self._adapter.discard_calibration()

    def close(self) -> None:
        self.cancel_calibration()
        with self._adapter_call_lock:
            with self._state_lock:
                adapter = self._adapter
                calibration_queue = self._calibration_queue
                self._adapter = None
                self.ready = False
                self._synchronized_source = None
                self._binding = None
                self._calibrated_binding = None
                self._summary_binding = None
                self.last_calibration_summary = None
                self.calibrated = False
                self.inference_ready = False
                self._calibration_queue = None
            self._drain_calibration_queue(calibration_queue)
            if adapter is not None:
                adapter.dispose()


def _model_path() -> Path:
    return Path(
        os.getenv(
            "EYE_FACE_MODEL_PATH",
            "/srv/mcm/models/face_landmarker.task",
        )
    )


def create_app() -> Starlette:
    runtime = EyeWorkerRuntime(model_path=_model_path())

    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok" if runtime.ready else "failed",
                "model_path": str(runtime.model_path),
                "calibrated": runtime.calibrated,
                "inference_ready": runtime.inference_ready,
                "failure_reason": runtime.failure_reason,
            },
            status_code=200 if runtime.ready else 503,
        )

    async def calibrate(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"valid": False, "reason": "invalid_request"}, status_code=400)
        if not isinstance(payload, Mapping):
            return JSONResponse({"valid": False, "reason": "invalid_request"}, status_code=400)
        try:
            result = await asyncio.to_thread(runtime.run_calibration, payload)
        except asyncio.CancelledError:
            runtime.cancel_matching_calibration(payload)
            raise
        return JSONResponse(result)

    async def cancel(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            return JSONResponse({"valid": False}, status_code=400)
        if isinstance(payload, Mapping):
            runtime.cancel_matching_calibration(payload)
        return JSONResponse({"valid": True})

    async def summary(_: Request) -> JSONResponse:
        # Aggregate diagnostics only, held in memory for local A/B/C measurements.
        return JSONResponse(runtime.last_calibration_summary or {"valid": False, "reason": "not_available"})

    async def end_session(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            return JSONResponse({"valid": False}, status_code=400)
        if not isinstance(payload, Mapping) or not all(isinstance(payload.get(k), str) for k in ("session_id", "video_id")):
            return JSONResponse({"valid": False}, status_code=400)
        await asyncio.to_thread(runtime.end_session, payload["session_id"], payload["video_id"])
        return JSONResponse({"valid": True})

    async def infer(request: Request) -> Response:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(
                {"gaze_sample": None, "gaze_reason": "eye_frame_too_large"},
                status_code=413,
            )
        try:
            binary = decode_binary_frame(body, max_frame_bytes=MAX_BODY_BYTES)
        except (VisionStreamProtocolError, ValueError):
            return JSONResponse(
                {"gaze_sample": None, "gaze_reason": "invalid_frame"},
                status_code=400,
            )
        try:
            return JSONResponse(await asyncio.to_thread(runtime.infer, binary))
        except (VisionStreamProtocolError, ValueError):
            return JSONResponse(
                {"gaze_sample": None, "gaze_reason": "invalid_frame"},
                status_code=400,
            )
        finally:
            del binary

    async def shutdown() -> None:
        runtime.close()

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/internal/eye/v1/calibrate", calibrate, methods=["POST"]),
            Route("/internal/eye/v1/infer", infer, methods=["POST"]),
            Route("/internal/eye/v1/cancel", cancel, methods=["POST"]),
            Route("/internal/eye/v1/calibration-summary", summary, methods=["GET"]),
            Route("/internal/eye/v1/session/end", end_session, methods=["POST"]),
        ],
        on_shutdown=[shutdown],
    )


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("EYE_WORKER_HOST", "127.0.0.1"),
        port=int(os.getenv("EYE_WORKER_PORT", "8766")),
    )

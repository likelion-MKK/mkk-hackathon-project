"""Private Python 3.12 Eye worker process.

The Gateway owns the WebSocket and Face worker. This process owns EyeTrax and
the pinned FaceLandmarker asset. Frames are decoded only in this process and
are either consumed by the bounded calibration queue or immediately converted
to one derived ``GazeSample``. No frame is written to disk or returned over
the worker boundary.
"""

from __future__ import annotations

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
CALIBRATION_QUEUE_SIZE = 64


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
        self.calibration_id: str | None = None
        self.failure_reason: str | None = None
        self._adapter: EyeTraxAdapter | None = None
        self._state_lock = threading.RLock()
        self._adapter_call_lock = threading.RLock()
        self._calibration_queue: queue.Queue[Any] | None = None
        self._calibration_cancel = threading.Event()
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

        with self._state_lock:
            adapter = self._adapter
            if not self.ready or adapter is None:
                return {"valid": False, "reason": "eye_not_connected"}
            if self._calibration_queue is not None:
                return {"valid": False, "reason": "calibration_in_progress"}
            self.calibrated = False
            self.calibration_id = calibration_id
            self._calibration_cancel.clear()
            self._calibration_queue = queue.Queue(maxsize=CALIBRATION_QUEUE_SIZE)

        result_valid = False
        result_reason = "calibration_failed"
        calibration_queue: queue.Queue[Any] | None = None
        try:
            with self._adapter_call_lock:
                result = adapter.calibrate(CalibrationRequest(calibration_id))
            result_valid = result.valid
            result_reason = result.reason or "calibration_failed"
        except Exception as exc:
            result_reason = f"calibration_error:{type(exc).__name__}"
        finally:
            with self._state_lock:
                self.calibrated = result_valid
                self.calibration_id = calibration_id if result_valid else None
                calibration_queue = self._calibration_queue
                self._calibration_queue = None
            self._drain_calibration_queue(calibration_queue)

        return {
            "valid": result_valid,
            "reason": None if result_valid else result_reason,
        }

    def cancel_calibration(self) -> None:
        self._calibration_cancel.set()

    def infer(self, binary: DecodedBinaryFrame) -> dict[str, object]:
        with self._state_lock:
            adapter = self._adapter
            calibration_queue = self._calibration_queue
            calibrated = self.calibrated
            ready = self.ready

        if not ready or adapter is None:
            return {"gaze_sample": None, "gaze_reason": "eye_not_connected"}

        if calibration_queue is not None:
            # Calibration frames are decoded in the private Eye process and
            # queued as BGR arrays only for the current target interval.
            decoded = default_frame_decoder(binary.image_bytes, binary.metadata)
            frame = decoded.value
            decoded.value = None
            try:
                calibration_queue.put_nowait(frame)
            except queue.Full:
                del frame
            return {"gaze_sample": None, "gaze_reason": "calibration_in_progress"}

        if not calibrated:
            return {"gaze_sample": None, "gaze_reason": "gaze_unavailable"}

        decoded = default_frame_decoder(binary.image_bytes, binary.metadata)
        context = binary.metadata.context
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
                frame_queue.get_nowait()
            except queue.Empty:
                return

    def close(self) -> None:
        self.cancel_calibration()
        with self._adapter_call_lock:
            with self._state_lock:
                adapter = self._adapter
                calibration_queue = self._calibration_queue
                self._adapter = None
                self.ready = False
                self.calibrated = False
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
            runtime.cancel_calibration()
            raise
        return JSONResponse(result)

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

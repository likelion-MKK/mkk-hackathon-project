"""Localhost ASGI Vision Stream v1 Gateway, Face-only vertical slice."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Mapping, Protocol

from mcm_face import FaceWorker, SelectedFaceAdapter
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect

from apps.common.vision_token import VisionTokenClaims
from apps.vision_gateway.eye_client import (
    EyeInferenceResult,
    EyeWorkerClient,
    UnavailableEyeWorkerClient,
)
from apps.vision_gateway.vision_stream import (
    DecodedBinaryFrame,
    FrameDecoder,
    StreamFrameContext,
    VisionStreamFrameTooLargeError,
    VisionStreamProtocolError,
    decode_binary_frame,
    default_frame_decoder,
)


_CONTROL_ACTIONS = frozenset(
    {"start_calibration", "start_inference", "stop_inference", "stop_session"}
)
_CONTROL_FIELDS = frozenset(
    {"type", "protocol_version", "request_id", "action", "payload"}
)
_HELLO_FIELDS = frozenset(
    {
        "type",
        "protocol_version",
        "session_id",
        "video_id",
        "stream_token",
        "offered_frame_encodings",
    }
)
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MEDIA_TYPE_PATTERN = re.compile(r"^image/[a-z0-9][a-z0-9.+-]{0,63}$")
_CALIBRATION_UNAVAILABLE_PREFIX = "calibration-unavailable-"
_CALIBRATION_MAX_FPS = 20.0


def _close_frame(frame: Any) -> None:
    close = getattr(frame, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def _finish_worker_frame(
    observation: Any,
    frame: Any,
    state: "_StreamState",
) -> None:
    adapter_completion = getattr(observation, "adapter_completion", None)
    if adapter_completion is not None:
        state.track_adapter_completion(adapter_completion)
    if not getattr(observation, "frame_cleanup_deferred", False):
        _close_frame(frame)


def _calibration_unavailable_id(request_id: str) -> str:
    suffix_limit = 128 - len(_CALIBRATION_UNAVAILABLE_PREFIX)
    if len(request_id) <= suffix_limit:
        return f"{_CALIBRATION_UNAVAILABLE_PREFIX}{request_id}"
    # Keep the generated placeholder a contract-valid ID without allowing a
    # long but valid request_id to overflow the calibration_id limit.
    digest = hashlib.sha256(request_id.encode("ascii")).hexdigest()[:16]
    return f"{_CALIBRATION_UNAVAILABLE_PREFIX}{digest}"


def _consume_task(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(BaseException):
        task.result()


def _same_frame_context(
    sample: Any,
    context: StreamFrameContext,
    *,
    session_id: str,
) -> bool:
    return all(
        (
            sample.session_id == session_id,
            sample.session_id == context.session_id,
            sample.video_id == context.video_id,
            sample.frame_id == context.frame_id,
            sample.sequence == context.sequence,
            sample.captured_at_mono_ms == context.captured_at_mono_ms,
            sample.video_time_ms == context.video_time_ms,
            sample.playback_epoch == context.playback_epoch,
        )
    )


def _same_gaze_payload_context(
    sample: Mapping[str, object],
    context: StreamFrameContext,
    *,
    session_id: str,
) -> bool:
    return all(
        sample.get(name) == value
        for name, value in (
            ("session_id", session_id),
            ("video_id", context.video_id),
            ("frame_id", context.frame_id),
            ("sequence", context.sequence),
            ("captured_at_mono_ms", context.captured_at_mono_ms),
            ("video_time_ms", context.video_time_ms),
            ("playback_epoch", context.playback_epoch),
        )
    )


class VisionTokenVerifier(Protocol):
    def consume(self, token: str) -> "VisionTokenClaims | None": ...


class VisionAuthorizationError(VisionStreamProtocolError):
    """A hello token cannot authorize the requested session and video."""


class LocalVisionTokenIssuer:
    """Development-only one-time token store; no token is written to disk or logs."""

    def __init__(self, *, ttl_seconds: int = 60) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._tokens: dict[str, VisionTokenClaims] = {}

    def issue(self, session_id: str, video_id: str) -> dict[str, str]:
        expires_at = datetime.now(timezone.utc) + self._ttl
        token = secrets.token_urlsafe(32)
        self._tokens[token] = VisionTokenClaims(session_id, video_id, expires_at)
        return {
            "protocol_version": "1.0",
            "session_id": session_id,
            "video_id": video_id,
            "stream_token": token,
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "websocket_path": "/vision/v1/stream",
        }

    def consume(self, token: str) -> VisionTokenClaims | None:
        claims = self._tokens.pop(token, None)
        if claims is None or claims.expires_at <= datetime.now(timezone.utc):
            return None
        return claims


FaceWorkerFactory = Callable[[], FaceWorker]


def selected_face_worker_factory(
    model_path: str | Path,
    *,
    timeout_ms: int = 500,
) -> FaceWorkerFactory:
    """Build the real MediaPipe worker lazily when a stream is accepted."""

    def factory() -> FaceWorker:
        return FaceWorker(SelectedFaceAdapter(model_path=model_path), timeout_ms=timeout_ms)

    return factory


@dataclass(frozen=True, slots=True)
class _FrameOutcome:
    kind: str
    payload: Mapping[str, object]


class VisionStreamApp:
    """ASGI app exposing only the localhost `/vision/v1/stream` WebSocket."""

    def __init__(
        self,
        *,
        token_verifier: VisionTokenVerifier,
        face_worker_factory: FaceWorkerFactory,
        frame_decoder: FrameDecoder = default_frame_decoder,
        max_frame_bytes: int = 524_288,
        max_fps: float = 4.0,
        decode_timeout_ms: int = 250,
        inference_timeout_ms: int = 500,
        worker_cleanup_timeout_ms: int = 250,
        eye_worker: EyeWorkerClient | None = None,
    ) -> None:
        if (
            max_frame_bytes <= 0
            or max_fps <= 0
            or decode_timeout_ms <= 0
            or inference_timeout_ms <= 0
            or worker_cleanup_timeout_ms <= 0
        ):
            raise ValueError("Vision Stream limits must be positive")
        self.token_verifier = token_verifier
        self.face_worker_factory = face_worker_factory
        self.frame_decoder = frame_decoder
        self.max_frame_bytes = max_frame_bytes
        self.max_fps = max_fps
        self.decode_timeout_ms = decode_timeout_ms
        self.inference_timeout_ms = inference_timeout_ms
        self.worker_cleanup_timeout_ms = worker_cleanup_timeout_ms
        self.eye_worker = eye_worker or UnavailableEyeWorkerClient()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope.get("type") != "websocket":
            await self._http_not_found(scope, receive, send)
            return
        websocket = WebSocket(scope, receive=receive, send=send)
        if scope.get("path") != "/vision/v1/stream":
            await websocket.accept()
            await self._send_close(websocket, code=1008, reason="unauthorized")
            return
        await self._handle(websocket)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            event = await receive()
            if event.get("type") == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event.get("type") == "lifespan.shutdown":
                await self.eye_worker.close()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _http_not_found(self, scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"not found"})

    async def _handle(self, websocket: WebSocket) -> None:
        await websocket.accept()
        worker: FaceWorker | None = None
        process_task: asyncio.Task[_FrameOutcome] | None = None
        calibration_task: asyncio.Task[tuple[bool, str | None]] | None = None
        calibration_request: tuple[str, str] | None = None
        receive_task: asyncio.Task[dict[str, Any]] | None = None
        state: _StreamState | None = None
        close_requested: tuple[str, str] | None = None
        try:
            first = await websocket.receive()
            if first.get("type") == "websocket.disconnect":
                return
            try:
                hello = self._json_message(first)
                claims = self._authenticate_hello(hello)
                selected_encoding = self._select_encoding(hello)
            except VisionAuthorizationError:
                await self._send_error(websocket, "unauthorized", retryable=False)
                await self._send_close(websocket, code=1008, reason="unauthorized")
                return
            except VisionStreamProtocolError:
                await self._send_error(websocket, "invalid_message", retryable=False)
                await self._send_close(websocket, code=1002, reason="protocol_error")
                return
            worker = self.face_worker_factory()
            await asyncio.to_thread(worker.start)
            await websocket.send_json(
                {
                    "type": "ready",
                    "protocol_version": "1.0",
                    "session_id": claims.session_id,
                    "video_id": claims.video_id,
                    "selected_frame_encoding": selected_encoding,
                    "limits": {
                        "in_flight_limit": 1,
                        "max_frame_bytes": self.max_frame_bytes,
                        "max_fps": self.max_fps,
                        "decode_timeout_ms": self.decode_timeout_ms,
                        "inference_timeout_ms": self.inference_timeout_ms,
                    },
                }
            )
            state = _StreamState(claims, selected_encoding, max_fps=self.max_fps)
            receive_task = asyncio.create_task(websocket.receive())
            while True:
                wait_for: set[asyncio.Task[Any]] = {receive_task}
                if process_task is not None:
                    wait_for.add(process_task)
                if calibration_task is not None:
                    wait_for.add(calibration_task)
                done, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)

                if calibration_task is not None and calibration_task in done:
                    request = calibration_request
                    try:
                        valid, reason = calibration_task.result()
                    except Exception:
                        valid, reason = False, "eye_worker_unavailable"
                    calibration_task = None
                    calibration_request = None
                    state.calibration_started = False
                    state.max_fps = self.max_fps
                    if request is not None:
                        request_id, calibration_id = request
                        await self._send_control_result(
                            websocket,
                            request_id=request_id,
                            action="start_calibration",
                            valid=valid,
                            reason=reason if not valid else None,
                            calibration_id=(
                                calibration_id
                                if valid
                                else _calibration_unavailable_id(request_id)
                            ),
                        )
                    if close_requested is not None and process_task is None:
                        request_id, action = close_requested
                        await self._send_control_result(
                            websocket,
                            request_id=request_id,
                            action=action,
                            valid=True,
                            reason=None,
                        )
                        await self._send_close(websocket, code=1000, reason="normal")
                        return

                if process_task is not None and process_task in done:
                    outcome = process_task.result()
                    process_task = None
                    await websocket.send_json(dict(outcome.payload))
                    if close_requested is not None:
                        request_id, action = close_requested
                        await self._send_control_result(
                            websocket,
                            request_id=request_id,
                            action=action,
                            valid=True,
                            reason=None,
                        )
                        await self._send_close(websocket, code=1000, reason="normal")
                        return

                if receive_task not in done:
                    continue
                event = receive_task.result()
                receive_task = asyncio.create_task(websocket.receive())
                event_type = event.get("type")
                if event_type == "websocket.disconnect":
                    break
                if event_type == "websocket.receive" and isinstance(event.get("bytes"), bytes):
                    try:
                        binary = decode_binary_frame(
                            event["bytes"], max_frame_bytes=self.max_frame_bytes
                        )
                        state.validate(binary)
                    except VisionStreamFrameTooLargeError:
                        await self._send_close(
                            websocket,
                            code=1009,
                            reason="frame_too_large",
                        )
                        return
                    except VisionStreamProtocolError as error:
                        del error
                        await self._send_error(websocket, "invalid_message", retryable=False)
                        await self._send_close(websocket, code=1002, reason="protocol_error")
                        return
                    rejection = state.rejection_reason(binary.metadata.context)
                    if rejection is not None:
                        await websocket.send_json(
                            self._drop(binary.metadata.context, rejection, retryable=True)
                        )
                        event = {}
                        continue
                    if process_task is not None or state.has_pending_work:
                        await websocket.send_json(
                            self._drop(binary.metadata.context, "in_flight", retryable=True)
                        )
                        event = {}
                        continue
                    rate_rejection = state.rate_rejection_reason()
                    if rate_rejection is not None:
                        await websocket.send_json(
                            self._drop(binary.metadata.context, rate_rejection, retryable=True)
                        )
                        event = {}
                        continue
                    if not state.inference_started and not state.calibration_started:
                        await websocket.send_json(
                            self._drop(binary.metadata.context, "session_closing", retryable=True)
                        )
                        event = {}
                        continue
                    state.accept(binary.metadata.context)
                    if state.calibration_started and not state.inference_started:
                        process_task = asyncio.create_task(
                            self._process_calibration_frame(binary, state, claims.session_id)
                        )
                    else:
                        process_task = asyncio.create_task(
                            self._process_frame(binary, worker, state, claims.session_id)
                        )
                    del binary
                    event = {}
                    continue
                if event_type == "websocket.receive" and isinstance(event.get("text"), str):
                    try:
                        request_id, action, payload = self._control_message(event)
                    except VisionStreamProtocolError:
                        await self._send_error(websocket, "invalid_message", retryable=False)
                        await self._send_close(websocket, code=1002, reason="protocol_error")
                        return
                    if action == "start_inference":
                        if state.calibration_started:
                            await self._send_control_result(
                                websocket,
                                request_id=request_id,
                                action=action,
                                valid=False,
                                reason="calibration_in_progress",
                            )
                        else:
                            state.inference_started = True
                            await self._send_control_result(
                                websocket,
                                request_id=request_id,
                                action=action,
                                valid=True,
                                reason=None,
                            )
                    elif action == "stop_inference":
                        state.inference_started = False
                        await self._send_control_result(
                            websocket,
                            request_id=request_id,
                            action=action,
                            valid=True,
                            reason=None,
                        )
                    elif action == "start_calibration":
                        assert payload is not None
                        if calibration_task is not None:
                            await self._send_control_result(
                                websocket,
                                request_id=request_id,
                                action=action,
                                valid=False,
                                reason="calibration_in_progress",
                                calibration_id=_calibration_unavailable_id(request_id),
                            )
                            continue
                        calibration_id = f"calibration-{request_id}"
                        state.calibration_started = True
                        state.max_fps = max(self.max_fps, _CALIBRATION_MAX_FPS)
                        calibration_request = (request_id, calibration_id)
                        calibration_task = asyncio.create_task(
                            self.eye_worker.start_calibration(
                            session_id=claims.session_id,
                            video_id=claims.video_id,
                            calibration_id=calibration_id,
                            pattern=payload,
                            )
                        )
                    elif action == "stop_session":
                        if calibration_task is not None:
                            # A user cancellation must not wait for a long
                            # EyeTrax calibration to finish. The worker's
                            # cancellation path only releases in-memory
                            # frames and calibration state.
                            calibration_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await calibration_task
                            calibration_task = None
                            calibration_request = None
                            state.calibration_started = False
                            state.max_fps = self.max_fps
                        if process_task is None:
                            await self._send_control_result(
                                websocket,
                                request_id=request_id,
                                action=action,
                                valid=True,
                                reason=None,
                            )
                            await self._send_close(websocket, code=1000, reason="normal")
                            return
                        close_requested = (request_id, action)
                    else:
                        await self._send_error(websocket, "invalid_message", retryable=False)
                        await self._send_close(websocket, code=1002, reason="protocol_error")
                        return
        except (WebSocketDisconnect, VisionStreamProtocolError):
            with contextlib.suppress(Exception):
                await self._send_close(websocket, code=1002, reason="protocol_error")
        finally:
            if receive_task is not None:
                receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receive_task
            if process_task is not None:
                with contextlib.suppress(Exception):
                    await process_task
            if calibration_task is not None:
                calibration_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await calibration_task
            if worker is not None:
                await self._cleanup_worker(worker, state)

    async def _process_calibration_frame(
        self,
        binary: DecodedBinaryFrame,
        state: "_StreamState",
        session_id: str,
    ) -> _FrameOutcome:
        """Forward a calibration frame to Eye without invoking Face."""

        context = binary.metadata.context
        eye_task = asyncio.create_task(self.eye_worker.infer(binary))
        try:
            try:
                eye_result = await asyncio.wait_for(
                    asyncio.shield(eye_task),
                    timeout=self.inference_timeout_ms / 1000,
                )
            except asyncio.TimeoutError:
                state.defer_cleanup(eye_task, lambda _result: None)
                return _FrameOutcome(
                    "drop", self._drop(context, "inference_timeout", retryable=True)
                )
            except asyncio.CancelledError:
                if not eye_task.done():
                    state.defer_cleanup(eye_task, lambda _result: None)
                raise
            except Exception:
                return _FrameOutcome(
                    "result",
                    {
                        "type": "result",
                        "protocol_version": "1.0",
                        **context.as_payload(),
                        "gaze_sample": None,
                        "gaze_reason": "eye_worker_unavailable",
                        "expression_sample": None,
                        "expression_reason": "calibration_in_progress",
                    },
                )

            candidate = eye_result.gaze_sample
            gaze_sample: Mapping[str, object] | None = None
            gaze_reason = eye_result.reason or "calibration_in_progress"
            if candidate is not None:
                if not _same_gaze_payload_context(
                    candidate, context, session_id=session_id
                ):
                    gaze_reason = "gaze_context_mismatch"
                elif not isinstance(candidate.get("valid"), bool):
                    gaze_reason = "eye_worker_invalid_response"
                else:
                    gaze_sample = candidate
                    gaze_reason = None
            return _FrameOutcome(
                "result",
                {
                    "type": "result",
                    "protocol_version": "1.0",
                    **context.as_payload(),
                    "gaze_sample": gaze_sample,
                    "gaze_reason": gaze_reason,
                    "expression_sample": None,
                    "expression_reason": "calibration_in_progress",
                },
            )
        finally:
            del binary

    async def _process_frame(
        self,
        binary: DecodedBinaryFrame,
        worker: FaceWorker,
        state: "_StreamState",
        session_id: str,
    ) -> _FrameOutcome:
        metadata = binary.metadata
        context = metadata.context
        frame: Any | None = None
        frame_cleanup_deferred = False
        decode_task: asyncio.Task[Any] | None = None
        worker_task: asyncio.Task[Any] | None = None
        eye_task: asyncio.Task[EyeInferenceResult] | None = None

        def defer_eye_cleanup() -> None:
            if eye_task is not None and not eye_task.done():
                state.defer_cleanup(eye_task, lambda _result: None)

        try:
            if not state.inference_started:
                return _FrameOutcome(
                    "drop", self._drop(context, "session_closing", retryable=False)
                )
            try:
                decode_task = asyncio.create_task(
                    asyncio.to_thread(self.frame_decoder, binary.image_bytes, metadata)
                )
                frame = await asyncio.wait_for(
                    asyncio.shield(decode_task),
                    timeout=self.decode_timeout_ms / 1000,
                )
            except asyncio.TimeoutError:
                assert decode_task is not None
                state.defer_cleanup(decode_task, _close_frame)
                decode_task = None
                return _FrameOutcome(
                    "drop", self._drop(context, "decode_timeout", retryable=True)
                )
            except asyncio.CancelledError:
                if decode_task is not None and not decode_task.done():
                    state.defer_cleanup(decode_task, _close_frame)
                    decode_task = None
                raise
            except VisionStreamProtocolError:
                return _FrameOutcome(
                    "error",
                    self._error("invalid_message", retryable=False, frame=context),
                )
            except Exception:
                return _FrameOutcome(
                    "error",
                    self._error("invalid_message", retryable=False, frame=context),
                )
            try:
                eye_task = asyncio.create_task(self.eye_worker.infer(binary))
                worker_task = asyncio.create_task(
                    asyncio.to_thread(worker.process, frame, context)
                )
                observation = await asyncio.wait_for(
                    asyncio.shield(worker_task),
                    timeout=self.inference_timeout_ms / 1000,
                )
            except asyncio.TimeoutError:
                assert worker_task is not None
                defer_eye_cleanup()
                captured_frame = frame
                state.defer_cleanup(
                    worker_task,
                    lambda result: _finish_worker_frame(result, captured_frame, state),
                )
                frame_cleanup_deferred = True
                worker_task = None
                return _FrameOutcome(
                    "drop", self._drop(context, "inference_timeout", retryable=True)
                )
            except asyncio.CancelledError:
                defer_eye_cleanup()
                if worker_task is not None and not worker_task.done():
                    captured_frame = frame
                    state.defer_cleanup(
                        worker_task,
                        lambda result: _finish_worker_frame(result, captured_frame, state),
                    )
                    worker_task = None
                    frame_cleanup_deferred = True
                raise
            except Exception:
                defer_eye_cleanup()
                return _FrameOutcome(
                    "error",
                    self._error("vision_unavailable", retryable=True, frame=context),
                )
            frame_cleanup_deferred = bool(
                getattr(observation, "frame_cleanup_deferred", False)
            )
            adapter_completion = getattr(observation, "adapter_completion", None)
            if adapter_completion is not None:
                state.track_adapter_completion(adapter_completion)
            sample = observation.sample
            if not _same_frame_context(sample, context, session_id=session_id):
                return _FrameOutcome(
                    "error",
                    self._error("vision_unavailable", retryable=True, frame=context),
                )
            if sample.reason == "timeout":
                defer_eye_cleanup()
                return _FrameOutcome(
                    "drop", self._drop(context, "inference_timeout", retryable=True)
                )
            gaze_sample: Mapping[str, object] | None = None
            gaze_reason: str | None = "eye_not_connected"
            if eye_task is not None:
                try:
                    eye_result = await asyncio.wait_for(
                        asyncio.shield(eye_task),
                        timeout=self.inference_timeout_ms / 1000,
                    )
                    candidate = eye_result.gaze_sample
                    if candidate is None:
                        gaze_reason = eye_result.reason or "gaze_unavailable"
                    elif not _same_gaze_payload_context(
                        candidate, context, session_id=session_id
                    ):
                        gaze_reason = "gaze_context_mismatch"
                    elif not isinstance(candidate.get("valid"), bool):
                        gaze_reason = "eye_worker_invalid_response"
                    else:
                        gaze_sample = candidate
                        gaze_reason = None
                except asyncio.TimeoutError:
                    state.defer_cleanup(eye_task, lambda _result: None)
                    gaze_reason = "eye_worker_timeout"
                except asyncio.CancelledError:
                    if eye_task is not None and not eye_task.done():
                        state.defer_cleanup(eye_task, lambda _result: None)
                    raise
                except Exception:
                    gaze_reason = "eye_worker_unavailable"
            return _FrameOutcome(
                "result",
                {
                    "type": "result",
                    "protocol_version": "1.0",
                    **context.as_payload(),
                    "gaze_sample": gaze_sample,
                    "gaze_reason": gaze_reason,
                    "expression_sample": sample.to_payload(),
                    "expression_reason": None,
                },
            )
        finally:
            if frame is not None and not frame_cleanup_deferred:
                _close_frame(frame)
            del frame
            del binary

    async def _cleanup_worker(
        self,
        worker: FaceWorker,
        state: "_StreamState | None",
    ) -> None:
        if state is not None:
            pending = state.pending_tasks_snapshot()
            if pending:
                pending_group = asyncio.gather(*pending, return_exceptions=True)
                try:
                    await asyncio.wait_for(
                        asyncio.shield(pending_group),
                        timeout=self.worker_cleanup_timeout_ms / 1000,
                    )
                except asyncio.TimeoutError:
                    cleanup_task = asyncio.create_task(
                        self._close_worker_after(worker, pending_group)
                    )
                    cleanup_task.add_done_callback(_consume_task)
                    return
        await self._close_worker_with_deadline(worker)

    async def _close_worker_after(self, worker: FaceWorker, pending: Any) -> None:
        with contextlib.suppress(BaseException):
            await pending
        await self._close_worker_with_deadline(worker)

    async def _close_worker_with_deadline(self, worker: FaceWorker) -> None:
        close_task = asyncio.create_task(asyncio.to_thread(worker.close))
        try:
            await asyncio.wait_for(
                asyncio.shield(close_task),
                timeout=self.worker_cleanup_timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            close_task.add_done_callback(_consume_task)
        except Exception:
            with contextlib.suppress(BaseException):
                close_task.result()

    def _authenticate_hello(self, hello: Mapping[str, object]) -> VisionTokenClaims:
        if set(hello) != _HELLO_FIELDS:
            raise VisionStreamProtocolError("hello fields are invalid")
        if hello.get("type") != "hello" or hello.get("protocol_version") != "1.0":
            raise VisionStreamProtocolError("hello is invalid")
        session_id = hello.get("session_id")
        video_id = hello.get("video_id")
        token = hello.get("stream_token")
        if not all(
            isinstance(value, str) and _ID_PATTERN.fullmatch(value)
            for value in (session_id, video_id)
        ):
            raise VisionStreamProtocolError("hello identifiers are invalid")
        if not isinstance(token, str) or not 32 <= len(token) <= 2048:
            raise VisionStreamProtocolError("hello credentials are invalid")
        offered = hello.get("offered_frame_encodings")
        if (
            not isinstance(offered, list)
            or not 1 <= len(offered) <= 8
            or any(
                not isinstance(encoding, str)
                or _MEDIA_TYPE_PATTERN.fullmatch(encoding) is None
                for encoding in offered
            )
            or len(set(offered)) != len(offered)
        ):
            raise VisionStreamProtocolError("offered frame encodings are invalid")
        claims = self.token_verifier.consume(token)
        if claims is None or claims.session_id != session_id or claims.video_id != video_id:
            raise VisionAuthorizationError("hello authorization failed")
        return claims

    def _select_encoding(self, hello: Mapping[str, object]) -> str:
        offered = hello.get("offered_frame_encodings")
        if not isinstance(offered, list):
            raise VisionStreamProtocolError("offered frame encodings are required")
        for encoding in offered:
            if encoding in ("image/jpeg", "image/webp"):
                return encoding
        raise VisionStreamProtocolError("no supported frame encoding was offered")

    @classmethod
    def _control_message(
        cls, event: Mapping[str, object]
    ) -> tuple[str, str, Mapping[str, object] | None]:
        control = cls._json_message(event)
        if set(control) - _CONTROL_FIELDS:
            raise VisionStreamProtocolError("control message has unknown fields")
        if control.get("type") != "control" or control.get("protocol_version") != "1.0":
            raise VisionStreamProtocolError("control message is invalid")
        request_id = control.get("request_id")
        action = control.get("action")
        if not isinstance(request_id, str) or _ID_PATTERN.fullmatch(request_id) is None:
            raise VisionStreamProtocolError("control request_id is invalid")
        if not isinstance(action, str) or action not in _CONTROL_ACTIONS:
            raise VisionStreamProtocolError("control action is invalid")
        if action == "start_calibration":
            payload = control.get("payload")
            cls._validate_calibration_payload(payload)
            assert isinstance(payload, Mapping)
            return request_id, action, payload
        elif "payload" in control:
            raise VisionStreamProtocolError("control payload is not allowed")
        return request_id, action, None

    @staticmethod
    def _validate_calibration_payload(payload: object) -> None:
        if not isinstance(payload, Mapping) or set(payload) != {"pattern_id", "points"}:
            raise VisionStreamProtocolError("calibration payload is invalid")
        pattern_id = payload.get("pattern_id")
        points = payload.get("points")
        if not isinstance(pattern_id, str) or _ID_PATTERN.fullmatch(pattern_id) is None:
            raise VisionStreamProtocolError("calibration pattern_id is invalid")
        if not isinstance(points, list) or not 1 <= len(points) <= 64:
            raise VisionStreamProtocolError("calibration points are invalid")
        for point in points:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= value <= 1
                    for value in point
                )
            ):
                raise VisionStreamProtocolError("calibration points are invalid")

    @staticmethod
    def _json_message(event: Mapping[str, object]) -> Mapping[str, object]:
        text = event.get("text")
        if not isinstance(text, str):
            raise VisionStreamProtocolError("expected a text JSON message")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise VisionStreamProtocolError("text message is not valid JSON") from error
        if not isinstance(value, Mapping):
            raise VisionStreamProtocolError("text message must be an object")
        return value

    @staticmethod
    async def _send_control_result(
        websocket: WebSocket,
        *,
        request_id: str,
        action: str,
        valid: bool,
        reason: str | None,
        calibration_id: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "type": "control_result",
            "protocol_version": "1.0",
            "request_id": request_id,
            "action": action,
            "valid": valid,
            "reason": reason,
        }
        if calibration_id is not None:
            payload["calibration_id"] = calibration_id
        await websocket.send_json(payload)

    @staticmethod
    async def _send_error(
        websocket: WebSocket,
        code: str,
        *,
        retryable: bool,
        frame: StreamFrameContext | None = None,
    ) -> None:
        await websocket.send_json(VisionStreamApp._error(code, retryable=retryable, frame=frame))

    @staticmethod
    def _error(
        code: str,
        *,
        retryable: bool,
        frame: StreamFrameContext | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": "error",
            "protocol_version": "1.0",
            "code": code,
            "retryable": retryable,
        }
        if frame is not None:
            payload["frame"] = frame.as_payload()
        return payload

    @staticmethod
    def _drop(
        context: StreamFrameContext,
        reason: str,
        *,
        retryable: bool,
    ) -> dict[str, object]:
        return {
            "type": "drop",
            "protocol_version": "1.0",
            **context.as_payload(),
            "reason": reason,
            "retryable": retryable,
        }

    @staticmethod
    async def _send_close(websocket: WebSocket, *, code: int, reason: str) -> None:
        await websocket.send_json(
            {
                "type": "close",
                "protocol_version": "1.0",
                "code": code,
                "reason": reason,
                "retryable": code in (1011, 1013),
            }
        )
        await websocket.close(code=code, reason=reason)


@dataclass(slots=True)
class _StreamState:
    claims: VisionTokenClaims
    selected_encoding: str
    max_fps: float
    inference_started: bool = False
    calibration_started: bool = False
    current_epoch: int | None = None
    last_sequence: int = -1
    last_received_at: float | None = None
    frame_keys: set[tuple[int, str]] | None = None
    frame_order: deque[tuple[int, str]] | None = None
    pending_tasks: set[asyncio.Future[Any]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.frame_keys = set()
        self.frame_order = deque(maxlen=512)

    def validate(self, binary: DecodedBinaryFrame) -> None:
        context = binary.metadata.context
        if context.session_id != self.claims.session_id or context.video_id != self.claims.video_id:
            raise VisionStreamProtocolError("frame session binding does not match hello")
        if binary.metadata.encoding != self.selected_encoding:
            raise VisionStreamProtocolError("frame encoding does not match ready")

    def rejection_reason(self, context: StreamFrameContext) -> str | None:
        key = (context.playback_epoch, context.frame_id)
        if key in (self.frame_keys or set()):
            return "duplicate_frame"
        if self.current_epoch is not None and context.playback_epoch < self.current_epoch:
            return "stale_epoch"
        if context.sequence <= self.last_sequence:
            return "out_of_order"
        return None

    @property
    def has_pending_work(self) -> bool:
        return bool(self.pending_tasks)

    def rate_rejection_reason(self) -> str | None:
        if self.last_received_at is None:
            return None
        if monotonic() - self.last_received_at < 1.0 / self.max_fps:
            return "fps_limited"
        return None

    def defer_cleanup(
        self,
        task: asyncio.Future[Any],
        cleanup: Callable[[Any], None],
    ) -> None:
        self.pending_tasks.add(task)

        def on_done(done: asyncio.Future[Any]) -> None:
            self.pending_tasks.discard(done)
            try:
                result = done.result()
            except BaseException:
                result = None
            with contextlib.suppress(Exception):
                cleanup(result)

        task.add_done_callback(on_done)

    def track_adapter_completion(self, completion: Any) -> None:
        wrapped = asyncio.wrap_future(completion)
        self.pending_tasks.add(wrapped)

        def on_done(done: asyncio.Future[Any]) -> None:
            self.pending_tasks.discard(done)
            with contextlib.suppress(BaseException):
                done.result()

        wrapped.add_done_callback(on_done)

    def pending_tasks_snapshot(self) -> tuple[asyncio.Future[Any], ...]:
        return tuple(self.pending_tasks)

    def accept(self, context: StreamFrameContext) -> None:
        self.last_received_at = monotonic()
        self.current_epoch = max(self.current_epoch or context.playback_epoch, context.playback_epoch)
        self.last_sequence = context.sequence
        key = (context.playback_epoch, context.frame_id)
        assert self.frame_keys is not None and self.frame_order is not None
        if len(self.frame_order) == self.frame_order.maxlen:
            self.frame_keys.discard(self.frame_order.popleft())
        self.frame_order.append(key)
        self.frame_keys.add(key)

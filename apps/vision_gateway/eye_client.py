"""Bounded loopback client for the Python 3.12 Eye worker."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Mapping, Protocol

from apps.vision_gateway.vision_stream import DecodedBinaryFrame, encode_binary_frame


@dataclass(frozen=True, slots=True)
class EyeInferenceResult:
    gaze_sample: Mapping[str, object] | None
    reason: str | None


class EyeWorkerClient(Protocol):
    async def start_calibration(
        self,
        *,
        session_id: str,
        video_id: str,
        calibration_id: str,
        pattern: Mapping[str, object],
    ) -> tuple[bool, str | None]: ...

    async def infer(self, frame: DecodedBinaryFrame) -> EyeInferenceResult: ...

    async def close(self) -> None: ...


class UnavailableEyeWorkerClient:
    """Fail-closed local default; it never fabricates a neutral gaze."""

    async def start_calibration(
        self,
        *,
        session_id: str,
        video_id: str,
        calibration_id: str,
        pattern: Mapping[str, object],
    ) -> tuple[bool, str | None]:
        del session_id, video_id, calibration_id, pattern
        return False, "eye_not_connected"

    async def infer(self, frame: DecodedBinaryFrame) -> EyeInferenceResult:
        del frame
        return EyeInferenceResult(None, "eye_not_connected")

    async def close(self) -> None:
        return None


@dataclass(slots=True)
class HttpEyeWorkerClient:
    """Send one bounded in-memory frame at a time over loopback HTTP."""

    base_url: str
    timeout_seconds: float = 0.5
    max_body_bytes: int = 524_288
    calibration_timeout_seconds: float | None = None
    _semaphore: asyncio.Semaphore = field(init=False, repr=False)
    _calibration_semaphore: asyncio.Semaphore = field(init=False, repr=False)
    _client: object | None = field(default=None, init=False, repr=False)
    _calibration_client: object | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://127.0.0.1", "http://localhost", "http://eye-worker")):
            raise ValueError("Eye worker URL must stay on the private loopback/container network")
        if self.timeout_seconds <= 0 or self.max_body_bytes <= 0:
            raise ValueError("Eye worker limits must be positive")
        self._semaphore = asyncio.Semaphore(1)
        self._calibration_semaphore = asyncio.Semaphore(1)

    async def _http_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False)
        return self._client

    async def _calibration_http_client(self):
        if self._calibration_client is None:
            import httpx

            self._calibration_client = httpx.AsyncClient(
                timeout=self.calibration_timeout_seconds,
                follow_redirects=False,
            )
        return self._calibration_client

    async def start_calibration(
        self,
        *,
        session_id: str,
        video_id: str,
        calibration_id: str,
        pattern: Mapping[str, object],
    ) -> tuple[bool, str | None]:
        payload = {
            "session_id": session_id,
            "video_id": video_id,
            "calibration_id": calibration_id,
            "pattern": dict(pattern),
        }
        try:
            # EyeTrax's fixed full-viewport training/validation calibration is a
            # user-driven operation and intentionally has no inference
            # deadline. It uses a separate connection/semaphore so frame
            # ingress can continue while this request waits for completion.
            async with self._calibration_semaphore:
                client = await self._calibration_http_client()
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/internal/eye/v1/calibrate",
                    json=payload,
                )
            if response.status_code != 200:
                return False, "eye_worker_unavailable"
            body = response.json()
            if not isinstance(body, Mapping) or not isinstance(body.get("valid"), bool):
                return False, "eye_worker_invalid_response"
            reason = body.get("reason")
            return body["valid"], reason if isinstance(reason, str) else None
        except asyncio.CancelledError:
            raise
        except Exception:
            return False, "eye_worker_unavailable"

    async def infer(self, frame: DecodedBinaryFrame) -> EyeInferenceResult:
        body = encode_binary_frame(frame.metadata.as_payload(), frame.image_bytes)
        if len(body) > self.max_body_bytes:
            return EyeInferenceResult(None, "eye_frame_too_large")
        try:
            async with self._semaphore:
                client = await self._http_client()
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/internal/eye/v1/infer",
                    content=body,
                    headers={"Content-Type": "application/octet-stream"},
                )
            if response.status_code != 200:
                return EyeInferenceResult(None, "eye_worker_unavailable")
            value = response.json()
            if not isinstance(value, Mapping):
                return EyeInferenceResult(None, "eye_worker_invalid_response")
            sample = value.get("gaze_sample")
            reason = value.get("gaze_reason")
            return EyeInferenceResult(
                sample if isinstance(sample, Mapping) else None,
                reason if isinstance(reason, str) else None,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return EyeInferenceResult(None, "eye_worker_unavailable")

    async def close(self) -> None:
        client = self._client
        if client is not None:
            close = getattr(client, "aclose", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()
            self._client = None
        calibration_client = self._calibration_client
        if calibration_client is not None:
            close = getattr(calibration_client, "aclose", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()
            self._calibration_client = None

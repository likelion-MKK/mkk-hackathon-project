"""Development-only HTTP bootstrap plus localhost Vision Stream WebSocket."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from starlette.types import Receive, Scope, Send

from apps.common.vision_token import SignedVisionTokenIssuer
from apps.vision_gateway.server import (
    LocalVisionTokenIssuer,
    VisionStreamApp,
    selected_face_worker_factory,
)
from apps.vision_gateway.eye_client import HttpEyeWorkerClient, UnavailableEyeWorkerClient


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOKEN_PATH = "/vision/v1/local-token"
_DEFAULT_ORIGINS = frozenset(
    {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }
)
_EXPRESSION_MODES = frozenset({"disabled", "selected"})


def _configured_origins() -> frozenset[str]:
    raw = os.getenv("VISION_GATEWAY_ALLOWED_ORIGINS", "")
    if not raw.strip():
        return _DEFAULT_ORIGINS
    origins = frozenset(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
    if not origins or "*" in origins:
        raise ValueError("VISION_GATEWAY_ALLOWED_ORIGINS must contain explicit origins")
    return origins


def _default_model_path() -> Path:
    repository_root = Path(__file__).resolve().parents[2]
    return repository_root / "experiments/face/mediapipe-face-landmarker/models/face_landmarker.task"


def _expression_mode() -> str:
    mode = os.getenv("VISION_EXPRESSION_MODE", "disabled").strip().lower()
    if mode not in _EXPRESSION_MODES:
        raise ValueError("VISION_EXPRESSION_MODE must be disabled or selected")
    return mode


async def _read_body(receive: Receive, *, limit: int = 8_192) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        event = await receive()
        if event.get("type") == "http.disconnect":
            raise ValueError("request disconnected")
        if event.get("type") != "http.request":
            raise ValueError("invalid HTTP request")
        chunk = event.get("body", b"")
        if not isinstance(chunk, bytes):
            raise ValueError("request body is invalid")
        total += len(chunk)
        if total > limit:
            raise OverflowError("request body is too large")
        chunks.append(chunk)
        if not event.get("more_body", False):
            return b"".join(chunks)


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


async def _send_json(
    send: Send,
    status: int,
    payload: dict[str, object],
    *,
    origin: str | None = None,
    allow_methods: bool = False,
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if origin is not None:
        headers.extend(
            [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"vary", b"Origin"),
            ]
        )
    if allow_methods:
        headers.extend(
            [
                (b"access-control-allow-methods", b"POST, OPTIONS"),
                (b"access-control-allow-headers", b"content-type"),
            ]
        )
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class LocalVisionGatewayApp:
    """Expose a non-production token bootstrap beside the localhost WebSocket."""

    def __init__(
        self,
        *,
        model_path: Path | None = None,
        expression_mode: str = "selected",
        allowed_origins: frozenset[str] = _DEFAULT_ORIGINS,
        token_issuer: Any | None = None,
    ) -> None:
        if expression_mode not in _EXPRESSION_MODES:
            raise ValueError("expression_mode must be disabled or selected")
        if expression_mode == "selected" and model_path is None:
            raise ValueError("selected expression mode requires a model_path")
        self.allowed_origins = allowed_origins
        self.token_issuer = token_issuer or LocalVisionTokenIssuer()
        self.local_token_enabled = isinstance(self.token_issuer, LocalVisionTokenIssuer)
        self.expression_mode = expression_mode
        eye_worker_url = os.getenv("VISION_EYE_WORKER_URL", "").strip()
        eye_worker = (
            HttpEyeWorkerClient(eye_worker_url)
            if eye_worker_url
            else UnavailableEyeWorkerClient()
        )
        self.stream_app = VisionStreamApp(
            token_verifier=self.token_issuer,
            face_worker_factory=(
                selected_face_worker_factory(model_path)
                if expression_mode == "selected" and model_path is not None
                else None
            ),
            eye_worker=eye_worker,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "websocket":
            request_origin = _headers(scope).get("origin")
            if request_origin is None or request_origin.rstrip("/") not in self.allowed_origins:
                await send({"type": "websocket.close", "code": 4403, "reason": "origin_not_allowed"})
                return
            await self.stream_app(scope, receive, send)
            return
        if scope.get("type") != "http" or scope.get("path") != _TOKEN_PATH:
            await self.stream_app(scope, receive, send)
            return

        request_headers = _headers(scope)
        request_origin = request_headers.get("origin")
        if request_origin is not None and request_origin.rstrip("/") not in self.allowed_origins:
            await _send_json(send, 403, {"code": "origin_not_allowed"})
            return
        origin = request_origin.rstrip("/") if request_origin else None

        if scope.get("method") == "OPTIONS":
            await _send_json(send, 204, {}, origin=origin, allow_methods=True)
            return
        if scope.get("method") != "POST":
            await _send_json(send, 405, {"code": "method_not_allowed"}, origin=origin)
            return

        if not self.local_token_enabled:
            await _send_json(send, 404, {"code": "not_found"}, origin=origin)
            return

        try:
            raw_body = await _read_body(receive)
            payload = json.loads(raw_body.decode("utf-8"))
            if (
                not isinstance(payload, dict)
                or set(payload) != {"session_id", "video_id"}
                or not isinstance(payload["session_id"], str)
                or not isinstance(payload["video_id"], str)
                or _ID_PATTERN.fullmatch(payload["session_id"]) is None
                or _ID_PATTERN.fullmatch(payload["video_id"]) is None
            ):
                raise ValueError("token request fields are invalid")
            token = self.token_issuer.issue(payload["session_id"], payload["video_id"])
        except OverflowError:
            await _send_json(send, 413, {"code": "request_too_large"}, origin=origin)
            return
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
            await _send_json(send, 400, {"code": "invalid_request"}, origin=origin)
            return

        # The credential is returned only in this response and is never put in
        # a URL, log message, persistent store, or WebSocket query string.
        await _send_json(send, 200, token, origin=origin)


def create_app() -> LocalVisionGatewayApp:
    expression_mode = _expression_mode()
    model_path = (
        Path(os.getenv("VISION_FACE_MODEL_PATH", str(_default_model_path())))
        if expression_mode == "selected"
        else None
    )
    secret = os.getenv("VISION_STREAM_TOKEN_SECRET", "").strip()
    token_issuer = SignedVisionTokenIssuer(secret, ttl_seconds=60) if secret else None
    return LocalVisionGatewayApp(
        model_path=model_path,
        expression_mode=expression_mode,
        allowed_origins=_configured_origins(),
        token_issuer=token_issuer,
    )


app: Any = create_app()

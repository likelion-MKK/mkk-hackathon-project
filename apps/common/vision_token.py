"""Signed, one-time Vision Stream credentials.

The API issues a token and the Vision Gateway consumes it. The token contains
only an anonymous session/video binding and expiry; raw camera data is never
part of the credential.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True, slots=True)
class VisionTokenClaims:
    session_id: str
    video_id: str
    expires_at: datetime


class SignedVisionTokenIssuer:
    """HMAC token issuer/verifier with in-memory one-time consumption."""

    def __init__(self, secret: str, *, ttl_seconds: int = 60) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("VISION_STREAM_TOKEN_SECRET must be at least 32 bytes")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._secret = secret.encode("utf-8")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._consumed: dict[str, datetime] = {}
        self._lock = RLock()

    def issue(self, session_id: str, video_id: str) -> dict[str, str]:
        if _ID_PATTERN.fullmatch(session_id) is None or _ID_PATTERN.fullmatch(video_id) is None:
            raise ValueError("Vision token identifiers are invalid")
        expires_at = datetime.now(timezone.utc) + self._ttl
        payload = {
            "sid": session_id,
            "vid": video_id,
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
        encoded_payload = _encode(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        signature = _encode(hmac.new(self._secret, encoded_payload.encode("ascii"), hashlib.sha256).digest())
        token = f"{encoded_payload}.{signature}"
        return {
            "protocol_version": "1.0",
            "session_id": session_id,
            "video_id": video_id,
            "stream_token": token,
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "websocket_path": "/vision/v1/stream",
        }

    def consume(self, token: str) -> VisionTokenClaims | None:
        if not isinstance(token, str) or len(token) > 2048:
            return None
        parts = token.split(".")
        if len(parts) != 2:
            return None
        encoded_payload, encoded_signature = parts
        try:
            expected = hmac.new(
                self._secret, encoded_payload.encode("ascii"), hashlib.sha256
            ).digest()
            actual = _decode(encoded_signature)
            if not hmac.compare_digest(expected, actual):
                return None
            payload = json.loads(_decode(encoded_payload).decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        session_id = payload.get("sid")
        video_id = payload.get("vid")
        expires_epoch = payload.get("exp")
        if (
            not isinstance(session_id, str)
            or not isinstance(video_id, str)
            or _ID_PATTERN.fullmatch(session_id) is None
            or _ID_PATTERN.fullmatch(video_id) is None
            or not isinstance(expires_epoch, int)
        ):
            return None
        expires_at = datetime.fromtimestamp(expires_epoch, tz=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
        with self._lock:
            now = datetime.now(timezone.utc)
            self._consumed = {
                consumed_token: consumed_expiry
                for consumed_token, consumed_expiry in self._consumed.items()
                if consumed_expiry > now
            }
            if token in self._consumed:
                return None
            self._consumed[token] = expires_at
        return VisionTokenClaims(session_id, video_id, expires_at)

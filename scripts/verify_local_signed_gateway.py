#!/usr/bin/env python3
"""Verify the local signed Vision Stream flow without printing credentials."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import websockets


API_BASE = "http://127.0.0.1:18000"
GATEWAY_URL = "ws://127.0.0.1:18765/vision/v1/stream"
ORIGIN = "http://127.0.0.1:15173"


async def _create_session(client: httpx.AsyncClient, suffix: str) -> str:
    response = await client.post(
        f"{API_BASE}/api/v1/sessions",
        json={
            "kiosk_id": f"signed-gateway-check-{suffix}",
            "lookbook_id": "mcm-lookbook-v2",
            "consent_version": "signed-gateway-check-v1",
        },
    )
    response.raise_for_status()
    return str(response.json()["session_id"])


async def _issue(client: httpx.AsyncClient, session_id: str) -> tuple[int, dict[str, str]]:
    response = await client.post(
        f"{API_BASE}/api/v1/sessions/{session_id}/vision-stream-token"
    )
    status = response.status_code
    response.raise_for_status()
    payload = response.json()
    return status, {key: str(value) for key, value in payload.items()}


async def _first_type(
    credential: dict[str, str],
    *,
    session_id: str | None = None,
    video_id: str | None = None,
) -> str:
    async with websockets.connect(GATEWAY_URL, origin=ORIGIN) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol_version": "1.0",
                    "session_id": session_id or credential["session_id"],
                    "video_id": video_id or credential["video_id"],
                    "stream_token": credential["stream_token"],
                    "offered_frame_encodings": ["image/jpeg"],
                },
                separators=(",", ":"),
            )
        )
        first = json.loads(await websocket.recv())
        return str(first.get("type", "missing"))


async def main() -> int:
    sessions: list[str] = []
    results: dict[str, object] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results["healthz"] = (await client.get(f"{API_BASE}/healthz")).status_code
            results["readyz"] = (await client.get(f"{API_BASE}/readyz")).status_code

            primary = await _create_session(client, "primary")
            other = await _create_session(client, "other")
            sessions.extend([primary, other])

            token_status, ready_credential = await _issue(client, primary)
            results["signed_token_status"] = token_status
            results["gateway_first_type"] = await _first_type(ready_credential)

            _, session_mismatch = await _issue(client, primary)
            results["session_mismatch_first_type"] = await _first_type(
                session_mismatch,
                session_id=other,
            )

            _, video_mismatch = await _issue(client, primary)
            results["video_mismatch_first_type"] = await _first_type(
                video_mismatch,
                video_id="mcm-lookbook-mismatch-v1",
            )

            _, expired = await _issue(client, primary)
            expires_at = datetime.fromisoformat(expired["expires_at"].replace("Z", "+00:00"))
            wait_seconds = max(
                0.0,
                (expires_at - datetime.now(timezone.utc)).total_seconds() + 1.25,
            )
            await asyncio.sleep(wait_seconds)
            results["expired_first_type"] = await _first_type(expired)

            for session_id in sessions:
                await client.delete(f"{API_BASE}/api/v2/sessions/{session_id}")
    except Exception:
        results["verification"] = "failed"
        print(json.dumps(results, separators=(",", ":"), sort_keys=True))
        return 1

    results["verification"] = "passed"
    print(json.dumps(results, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

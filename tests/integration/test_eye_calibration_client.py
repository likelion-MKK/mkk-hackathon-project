import asyncio
import json
from pathlib import Path

import httpx
import pytest

from apps.vision_gateway.eye_client import HttpEyeWorkerClient
from apps.vision_gateway.vision_stream import decode_binary_frame, encode_binary_frame

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts/examples"


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture", ["vision-stream-calibration-progress.valid.json", "vision-stream-face-positioning.valid.json"])
def test_private_http_boundary_preserves_marker_and_validates_progress(fixture):
    async def run():
        value = example("vision-stream-calibration-frame.valid.json")
        progress = example(fixture)["calibration_progress"]
        async def handler(request):
            decoded = decode_binary_frame(request.content, max_frame_bytes=524288)
            assert decoded.metadata.calibration_target == value["calibration_target"]
            return httpx.Response(200, json={"gaze_sample": None, "gaze_reason": "calibration_in_progress", "calibration_progress": progress})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = HttpEyeWorkerClient("http://127.0.0.1:8766")
            client._client = http
            frame = decode_binary_frame(encode_binary_frame(value, b"\xff\xd8\xff\xd9"), max_frame_bytes=524288)
            result = await client.infer(frame)
            assert result.calibration_progress == progress and result.gaze_sample is None
            progress["accepted_samples"] = 99
            rejected = await client.infer(frame)
            assert rejected.calibration_progress is None and rejected.gaze_sample is None
    asyncio.run(run())


def test_http_disconnect_sends_explicit_worker_cancellation():
    async def run():
        started = asyncio.Event()
        calls = []
        async def handler(request):
            calls.append((request.url.path, json.loads(request.content)))
            if request.url.path.endswith("/calibrate"):
                started.set()
                await asyncio.Event().wait()
            return httpx.Response(200, json={"valid": True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = HttpEyeWorkerClient("http://127.0.0.1:8766")
            client._client = http
            client._calibration_client = http
            pending = asyncio.create_task(client.start_calibration(session_id="session-test", video_id="video-test",
                calibration_id="cal-test", pattern={"pattern_id": "adaptive-dense5-v2", "points": []}))
            await asyncio.wait_for(started.wait(), 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert calls[-1] == ("/internal/eye/v1/cancel", {"calibration_id": "cal-test", "session_id": "session-test", "video_id": "video-test"})
            await client.end_session("session-test", "video-test")
            assert calls[-1] == ("/internal/eye/v1/session/end", {"session_id": "session-test", "video_id": "video-test"})
    asyncio.run(run())


@pytest.mark.parametrize("reason", [
    "validation_signal_insufficient", "validation_accuracy_failed",
    "validation_signal_and_accuracy_failed", "validation_samples_insufficient",
])
def test_private_http_boundary_preserves_specific_calibration_failure(reason):
    async def run():
        async def handler(_request):
            return httpx.Response(200, json={"valid": False, "reason": reason})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = HttpEyeWorkerClient("http://127.0.0.1:8766")
            client._calibration_client = http
            valid, received_reason = await client.start_calibration(
                session_id="session-test", video_id="video-test", calibration_id="cal-test",
                pattern={"pattern_id": "adaptive-dense5-v2", "points": []},
            )
            assert not valid and received_reason == reason
    asyncio.run(run())

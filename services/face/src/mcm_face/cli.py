"""Opt-in local camera smoke command; never emits pixels or image bytes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean
from time import monotonic

from mcm_face.adapters.selected import SelectedFaceAdapter
from mcm_face.camera import CameraError, OpenCVCameraSource, list_camera_devices
from mcm_face.worker import FaceWorker


@dataclass(frozen=True, slots=True)
class _Context:
    session_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str = "camera-smoke"
    video_time_ms: int = 0
    playback_epoch: int = 0


def camera_smoke_main() -> None:
    parser = argparse.ArgumentParser(description="Development-only D6 Face camera smoke test")
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--timeout-ms", type=int, default=500)
    args = parser.parse_args()

    source = OpenCVCameraSource(
        device_index=args.device, width=args.width, height=args.height, fps=args.fps
    )
    adapter = SelectedFaceAdapter(model_path=args.model_path)
    worker = FaceWorker(adapter, timeout_ms=args.timeout_ms)
    counts: dict[str, int] = {}
    face_counts: list[int] = []
    latencies: list[float] = []
    diagnostics: dict[str, object] = {
        "available_devices": list_camera_devices(),
        "permission": "unknown",
    }
    try:
        diagnostics.update(source.open().to_payload())
        worker.start()
        for sequence in range(args.frames):
            frame = source.read()
            context = _Context(
                session_id="camera-smoke-session",
                sequence=sequence,
                frame_id=f"camera-smoke-{sequence:05d}",
                captured_at_mono_ms=monotonic() * 1000,
            )
            observation = worker.process(frame, context)
            del frame
            sample = observation.sample
            key = "valid" if sample.valid else str(sample.reason)
            counts[key] = counts.get(key, 0) + 1
            face_counts.append(sample.face_count)
            latencies.append(observation.latency_ms)
    except CameraError as error:
        diagnostics["permission"] = "denied" if error.reason == "camera_permission_denied" else "unavailable"
        counts[error.reason] = 1
    finally:
        source.close()
        worker.close()

    total = max(1, sum(counts.values()))
    payload = {
        "mode": "camera-smoke-development-only",
        "camera": diagnostics,
        "frames_processed": len(latencies),
        "face_count_latest": face_counts[-1] if face_counts else None,
        "no_face_ratio": counts.get("no_face", 0) / total,
        "multi_face_ratio": counts.get("multi_face", 0) / total,
        "latency_ms_mean": mean(latencies) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
        "timeout_count": worker.timeout_count,
        "error_count": worker.error_count + counts.get("model_unavailable", 0),
        "outcomes": counts,
        "raw_frame_persisted": False,
        "recommendation_mode": "none",
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def camera_preview_main() -> None:
    """Show a development-only video preview without persisting frames."""

    parser = argparse.ArgumentParser(description="Development-only video camera preview")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    try:
        import cv2
    except ImportError as error:
        raise SystemExit("camera extra is required: uv sync --extra camera") from error

    source = OpenCVCameraSource(
        device_index=args.device,
        width=args.width,
        height=args.height,
    )
    title = "MCM Camera Preview - Q or Esc to close"
    try:
        diagnostics = source.open()
        print(
            f"camera={diagnostics.device_index} permission={diagnostics.permission} "
            f"resolution={diagnostics.actual_width}x{diagnostics.actual_height} "
            f"fps={diagnostics.actual_fps:.1f}"
        )
        print("Raw frames are displayed in memory only and are not persisted.")
        while True:
            frame = source.read()
            try:
                cv2.imshow(title, frame)
                key = cv2.waitKey(1) & 0xFF
            finally:
                del frame
            if key in (27, ord("q"), ord("Q")):
                break
    except CameraError as error:
        raise SystemExit(error.reason) from None
    finally:
        source.close()
        cv2.destroyAllWindows()

"""Development-only D8 camera → MediaPipe → D7 event/API vertical slice."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from math import ceil
from pathlib import Path
from statistics import mean
from threading import RLock
from time import monotonic, perf_counter
from typing import Any, Protocol

from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.vision_gateway.d8_signals import D8ReactionSignals, derive_d8_reaction_signals
from apps.vision_gateway.gateway import FrameEnvelope, InProcessVisionGateway, ReplayEyePort
from apps.vision_gateway.runner import D7RunConfig, D7SessionRunner, BackendPort, HttpBackendPort
from mcm_face import CameraDiagnostics, FaceWorker, OpenCVCameraSource, SelectedFaceAdapter
from mcm_face.camera import CameraError, list_camera_devices


class CameraSource(Protocol):
    def open(self) -> CameraDiagnostics: ...
    def read(self) -> Any: ...
    def close(self) -> None: ...


class EphemeralCameraFrame:
    """Own one BGR camera frame until Gateway dispatch finishes.

    The lock serializes the one RGB copy with close(), preventing a timeout
    cleanup from invalidating the BGR array while the worker is converting it.
    """

    __slots__ = ("frame_id", "_frame", "_lock", "closed", "__weakref__")

    def __init__(self, frame_id: str, frame: Any) -> None:
        self.frame_id = frame_id
        self._frame = frame
        self._lock = RLock()
        self.closed = False

    def to_rgb_copy(self) -> Any:
        with self._lock:
            if self._frame is None:
                raise RuntimeError("ephemeral camera frame is closed")
            return self._frame[:, :, ::-1].copy()

    def close(self) -> None:
        with self._lock:
            self._frame = None
            self.closed = True

    def __repr__(self) -> str:
        state = "closed" if self.closed else "open"
        return f"<EphemeralCameraFrame frame_id={self.frame_id!r} state={state}>"


@dataclass(frozen=True, slots=True)
class D8LiveConfig:
    model_path: Path
    device_index: int = 0
    requested_width: int = 640
    requested_height: int = 480
    requested_fps: float = 5.0
    frames: int = 30
    timeout_ms: int = 500
    video_id: str = "mcm-lookbook-example-v1"
    low_quality_threshold: float = 0.80
    min_in_frame_ratio: float = 0.90
    min_face_width_ratio: float = 0.10
    min_face_height_ratio: float = 0.10

    def __post_init__(self) -> None:
        if self.device_index < 0:
            raise ValueError("device_index must be non-negative")
        if self.requested_width <= 0 or self.requested_height <= 0:
            raise ValueError("requested camera dimensions must be positive")
        if self.requested_fps <= 0 or self.frames <= 0 or self.timeout_ms <= 0:
            raise ValueError("fps, frames, and timeout must be positive")
        for name, value in (
            ("low_quality_threshold", self.low_quality_threshold),
            ("min_in_frame_ratio", self.min_in_frame_ratio),
            ("min_face_width_ratio", self.min_face_width_ratio),
            ("min_face_height_ratio", self.min_face_height_ratio),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


WorkerFactory = Callable[[], FaceWorker]
DeviceLister = Callable[[], list[int]]


class D8LiveSessionRunner:
    """Reuse the D7 transport and ingest path with an opt-in live frame factory."""

    def __init__(
        self,
        *,
        backend: BackendPort,
        config: D8LiveConfig,
        camera_source: CameraSource | None = None,
        device_lister: DeviceLister = list_camera_devices,
        face_worker_factory: WorkerFactory | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.backend = backend
        self.config = config
        self.camera_source = camera_source or OpenCVCameraSource(
            device_index=config.device_index,
            width=config.requested_width,
            height=config.requested_height,
            fps=config.requested_fps,
        )
        self.device_lister = device_lister
        self.face_worker_factory = face_worker_factory or (
            lambda: FaceWorker(
                SelectedFaceAdapter(
                    model_path=config.model_path,
                    low_quality_threshold=config.low_quality_threshold,
                    min_in_frame_ratio=config.min_in_frame_ratio,
                    min_face_width_ratio=config.min_face_width_ratio,
                    min_face_height_ratio=config.min_face_height_ratio,
                ),
                timeout_ms=config.timeout_ms,
            )
        )
        self.clock = clock
        self.available_devices: list[int] = []
        self.camera_diagnostics: CameraDiagnostics | None = None
        self.runner: D7SessionRunner | None = None
        self.frames_attempted = 0
        self.frames_processed = 0
        self.error_count = 0
        self.outcomes: dict[str, int] = {}
        self.latest_face_count: int | None = None
        self.latest_reaction_signals: D8ReactionSignals | None = None
        self._latencies_ms: list[float] = []
        self._permission = "unknown"
        self._closed = False
        self._recommendation: Mapping[str, object] | None = None

    def start(self) -> str:
        if self.runner is not None and self.runner.session_id is not None:
            return self.runner.session_id
        try:
            self.available_devices = self.device_lister()
            self.camera_diagnostics = self.camera_source.open()
            self._permission = self.camera_diagnostics.permission
            self.runner = D7SessionRunner(
                backend=self.backend,
                face_worker_factory=self.face_worker_factory,
                config=D7RunConfig(
                    input_mode="camera_development",
                    recommendation_mode="mock",
                    video_id=self.config.video_id,
                    capture_step_ms=self._playback_step_ms,
                ),
                gateway_factory=self._gateway_factory,
            )
            return self.runner.start()
        except CameraError as error:
            self._permission = (
                "denied" if error.reason == "camera_permission_denied" else "unavailable"
            )
            self.error_count += 1
            self.camera_source.close()
            raise
        except Exception:
            self.error_count += 1
            self.cancel()
            raise

    def process_frame(self, index: int) -> tuple[object, Mapping[str, object]]:
        if self.runner is None or self.runner.session_id is None:
            raise RuntimeError("D8 live session has not started")
        if self._closed:
            raise RuntimeError("D8 live session is closed")
        self.frames_attempted += 1
        envelope = FrameEnvelope(
            session_id=self.runner.session_id,
            video_id=self.config.video_id,
            frame_id=f"frame-d8-{index:05d}",
            sequence=index * 2,
            captured_at_mono_ms=self.clock() * 1000,
            video_time_ms=index * self._playback_step_ms,
            playback_epoch=0,
        )
        started = perf_counter()
        try:
            observation, accepted = self.runner.process_envelope(envelope)
        except Exception:
            self.error_count += 1
            self.cancel()
            raise
        self._latencies_ms.append((perf_counter() - started) * 1000)
        self.frames_processed += 1
        self.latest_face_count = observation.face.face_count
        outcome = "valid" if observation.face.valid else str(observation.face.reason)
        self.outcomes[outcome] = self.outcomes.get(outcome, 0) + 1
        batch = self.runner.batches[-1]
        events = batch.get("events")
        if not isinstance(events, list) or len(events) != 2 or not isinstance(events[1], Mapping):
            self.error_count += 1
            self.cancel()
            raise RuntimeError("D8 expected the shared D7 Face/AOI batch shape")
        self.latest_reaction_signals = derive_d8_reaction_signals(observation, events[1])
        return observation, accepted

    def close(self) -> Mapping[str, object]:
        if self.runner is None:
            raise RuntimeError("D8 live session has not started")
        if self._closed:
            return self._recommendation or {}
        try:
            self._recommendation = self.runner.close()
            return self._recommendation
        except Exception:
            self.error_count += 1
            raise
        finally:
            self.camera_source.close()
            self._closed = True

    def cancel(self) -> None:
        if self._closed:
            return
        try:
            if self.runner is not None:
                self.runner.cancel()
        finally:
            self.camera_source.close()
            self._closed = True

    def diagnostics(self) -> dict[str, object]:
        processed = self.frames_processed
        gateway = self.runner.gateway if self.runner is not None else None
        gateway_state = gateway.public_state() if gateway is not None else {}
        return {
            "available_devices": list(self.available_devices),
            "permission": self._permission,
            "requested_width": self.config.requested_width,
            "requested_height": self.config.requested_height,
            "requested_fps": self.config.requested_fps,
            "actual_width": self.camera_diagnostics.actual_width if self.camera_diagnostics else None,
            "actual_height": self.camera_diagnostics.actual_height if self.camera_diagnostics else None,
            "actual_fps": self.camera_diagnostics.actual_fps if self.camera_diagnostics else None,
            "frames_attempted": self.frames_attempted,
            "frames_processed": processed,
            "latest_face_count": self.latest_face_count,
            "valid_face_ratio": self._ratio("valid", processed),
            "no_face_ratio": self._ratio("no_face", processed),
            "multi_face_ratio": self._ratio("multi_face", processed),
            "low_quality_ratio": self._ratio("low_quality", processed),
            "processing_latency_ms_mean": mean(self._latencies_ms) if self._latencies_ms else None,
            "processing_latency_ms_p50": _nearest_rank(self._latencies_ms, 0.50),
            "processing_latency_ms_p95": _nearest_rank(self._latencies_ms, 0.95),
            "processing_latency_ms_max": max(self._latencies_ms) if self._latencies_ms else None,
            "timeout_count": gateway_state.get("worker_timeout_count", 0),
            "error_count": self.error_count + int(gateway_state.get("worker_error_count", 0)),
            "dropped_frame_count": gateway_state.get("drop_count", 0),
            "outcomes": dict(self.outcomes),
            "latest_reaction_signals": (
                self.latest_reaction_signals.to_diagnostics()
                if self.latest_reaction_signals is not None
                else None
            ),
            "face_mode": "selected_mediapipe",
            "eye_mode": "replay",
            "recommendation_mode": "mock",
            "preference_algorithm": "not_configured",
            "transport": "d8-development-in-process",
            "synthetic_playback_clock": True,
            "technical_quality_proxy": {
                "low_quality_threshold": self.config.low_quality_threshold,
                "min_in_frame_ratio": self.config.min_in_frame_ratio,
                "min_face_width_ratio": self.config.min_face_width_ratio,
                "min_face_height_ratio": self.config.min_face_height_ratio,
            },
            "raw_frame_persisted": False,
        }

    @property
    def _playback_step_ms(self) -> int:
        return max(1, round(1000 / self.config.requested_fps))

    def _gateway_factory(self, _session_id: str, _video_id: str) -> InProcessVisionGateway:
        return InProcessVisionGateway(
            face_worker_factory=self.face_worker_factory,
            eye_port=ReplayEyePort(),
            frame_factory=self._capture_frame,
        )

    def _capture_frame(self, frame_id: str) -> EphemeralCameraFrame:
        frame = self.camera_source.read()
        try:
            return EphemeralCameraFrame(frame_id, frame)
        except Exception:
            del frame
            raise

    def _ratio(self, key: str, total: int) -> float:
        return self.outcomes.get(key, 0) / total if total else 0.0


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description="Development-only D8 camera/API smoke test")
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--timeout-ms", type=int, default=500)
    parser.add_argument("--low-quality-threshold", type=float, default=0.80)
    parser.add_argument("--min-in-frame-ratio", type=float, default=0.90)
    parser.add_argument("--min-face-width-ratio", type=float, default=0.10)
    parser.add_argument("--min-face-height-ratio", type=float, default=0.10)
    args = parser.parse_args()
    config = D8LiveConfig(
        model_path=args.model_path,
        device_index=args.device,
        requested_width=args.width,
        requested_height=args.height,
        requested_fps=args.fps,
        frames=args.frames,
        timeout_ms=args.timeout_ms,
        low_quality_threshold=args.low_quality_threshold,
        min_in_frame_ratio=args.min_in_frame_ratio,
        min_face_width_ratio=args.min_face_width_ratio,
        min_face_height_ratio=args.min_face_height_ratio,
    )
    store = MemoryStore(Path(__file__).resolve().parents[2])
    exit_code = 0
    failure_reason: str | None = None
    with TestClient(create_app(store)) as client:
        runner = D8LiveSessionRunner(
            backend=HttpBackendPort(
                client,
                kiosk_id="kiosk-d8-development",
                consent_version="consent-d8-development-camera",
            ),
            config=config,
        )
        try:
            runner.start()
            for index in range(config.frames):
                runner.process_frame(index)
            recommendation = runner.close()
            if recommendation.get("engine_mode") != "mock":
                failure_reason = "recommendation_mode_mismatch"
                exit_code = 4
            elif runner.outcomes.get("model_unavailable", 0):
                failure_reason = "model_unavailable"
                exit_code = 3
        except CameraError as error:
            failure_reason = error.reason
            exit_code = 2
        except Exception:
            failure_reason = "live_session_error"
            exit_code = 4
        finally:
            runner.cancel()
        payload = runner.diagnostics()
        payload["run_status"] = "completed" if exit_code == 0 else "failed"
        payload["failure_reason"] = failure_reason
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

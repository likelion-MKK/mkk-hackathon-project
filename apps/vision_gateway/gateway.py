"""Memory-only D7 transport boundary for synthetic and replay E2E tests."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import RLock
from typing import Callable, Literal, Mapping, Protocol, Sequence

from mcm_face import ExpressionSample, FaceWorker


TransportMode = Literal["synthetic", "replay", "camera_development"]


class TransientFrame(Protocol):
    """Memory-only frame whose resources can be released deterministically."""

    def close(self) -> None: ...


class GatewayStateError(RuntimeError):
    """Lifecycle error that never includes frame content."""


@dataclass(frozen=True, slots=True)
class VisionHandshake:
    session_id: str
    video_id: str
    mode: TransportMode = "synthetic"

    def __post_init__(self) -> None:
        if not self.session_id or not self.video_id:
            raise ValueError("session_id and video_id are required")
        if self.mode not in ("synthetic", "replay", "camera_development"):
            raise ValueError("vision harness mode must be synthetic, replay, or camera_development")


@dataclass(frozen=True, slots=True)
class FrameEnvelope:
    session_id: str
    video_id: str
    frame_id: str
    sequence: int
    captured_at_mono_ms: float
    video_time_ms: int
    playback_epoch: int

    def __post_init__(self) -> None:
        if not self.session_id or not self.video_id or not self.frame_id:
            raise ValueError("frame envelope identifiers are required")
        if self.sequence < 0 or self.sequence % 2:
            raise ValueError("D7 frame sequence must be a non-negative even integer")
        if self.captured_at_mono_ms < 0 or self.video_time_ms < 0 or self.playback_epoch < 0:
            raise ValueError("frame envelope time fields must be non-negative")


class SyntheticFrame:
    """Ephemeral runtime marker; it deliberately has no pixel or byte payload."""

    __slots__ = ("frame_id", "closed", "__weakref__")

    def __init__(self, frame_id: str) -> None:
        self.frame_id = frame_id
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def __repr__(self) -> str:
        return "SyntheticFrame(<redacted>)"


@dataclass(frozen=True, slots=True)
class D7GazeSample:
    schema_version: str
    session_id: str
    event_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int
    producer_id: str
    model_revision: str
    calibration_id: str
    screen_x_norm: float | None
    screen_y_norm: float | None
    valid: bool
    confidence: float
    reason: str | None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "frame_id": self.frame_id,
            "captured_at_mono_ms": self.captured_at_mono_ms,
            "video_id": self.video_id,
            "video_time_ms": self.video_time_ms,
            "playback_epoch": self.playback_epoch,
            "producer_id": self.producer_id,
            "model_revision": self.model_revision,
            "calibration_id": self.calibration_id,
            "valid": self.valid,
            "confidence": self.confidence,
            "reason": self.reason,
        }
        if self.valid:
            payload["screen_x_norm"] = self.screen_x_norm
            payload["screen_y_norm"] = self.screen_y_norm
        return payload


class ReplayEyePort:
    """Derived gaze replay port used because D7 has no server Eye Worker transport."""

    def __init__(self, coordinates: Sequence[tuple[float, float]] | None = None) -> None:
        self._coordinates = tuple(coordinates or ((0.25, 0.5), (0.75, 0.5)))
        if not self._coordinates:
            raise ValueError("at least one derived gaze replay coordinate is required")
        for x, y in self._coordinates:
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise ValueError("gaze replay coordinates must be normalized")
        self._cursor = 0
        self._closed = False

    def infer(self, frame: TransientFrame, context: FrameEnvelope) -> D7GazeSample:
        if self._closed:
            raise GatewayStateError("Eye replay port is closed")
        del frame
        x, y = self._coordinates[self._cursor % len(self._coordinates)]
        self._cursor += 1
        material = "|".join(
            (context.session_id, context.frame_id, str(context.sequence), str(x), str(y))
        )
        event_id = f"gaze-d7-{sha256(material.encode()).hexdigest()[:24]}"
        return D7GazeSample(
            schema_version="1.0",
            session_id=context.session_id,
            event_id=event_id,
            sequence=context.sequence,
            frame_id=context.frame_id,
            captured_at_mono_ms=context.captured_at_mono_ms,
            video_id=context.video_id,
            video_time_ms=context.video_time_ms,
            playback_epoch=context.playback_epoch,
            producer_id="d7-replay-eye-port",
            model_revision="d7-derived-gaze-replay-v1",
            calibration_id="d7-replay-calibration-v1",
            screen_x_norm=x,
            screen_y_norm=y,
            valid=True,
            confidence=0.9,
            reason=None,
        )

    def close(self) -> None:
        self._closed = True


@dataclass(frozen=True, slots=True)
class DerivedObservation:
    gaze: D7GazeSample
    face: ExpressionSample
    matched_by: Literal["frame_id", "capture_time"]
    face_latency_ms: float


class ObservationJoiner:
    """Join derived outputs without retaining frame references."""

    def __init__(self, *, tolerance_ms: float = 100.0) -> None:
        if tolerance_ms < 0:
            raise ValueError("tolerance_ms must be non-negative")
        self._tolerance_ms = tolerance_ms
        self._gaze: dict[str, D7GazeSample] = {}
        self._face: dict[str, tuple[ExpressionSample, float]] = {}

    def push_gaze(self, sample: D7GazeSample) -> DerivedObservation | None:
        matching_face = self._face.pop(sample.frame_id, None)
        if matching_face is not None:
            face, latency = matching_face
            return DerivedObservation(sample, face, "frame_id", latency)
        self._gaze[sample.frame_id] = sample
        return None

    def push_face(self, sample: ExpressionSample, *, latency_ms: float) -> DerivedObservation | None:
        matching_gaze = self._gaze.pop(sample.frame_id, None)
        if matching_gaze is not None:
            return DerivedObservation(matching_gaze, sample, "frame_id", latency_ms)
        self._face[sample.frame_id] = (sample, latency_ms)
        return None

    def flush_nearest(self) -> DerivedObservation | None:
        """Use capture-time fallback only after exact frame matches had a chance."""

        best: tuple[float, str, str, D7GazeSample, ExpressionSample, float] | None = None
        for gaze_key, gaze in self._gaze.items():
            fallback = self._nearest_face(gaze)
            if fallback is None:
                continue
            face_key, face, latency = fallback
            candidate = (
                abs(face.captured_at_mono_ms - gaze.captured_at_mono_ms),
                gaze_key,
                face_key,
                gaze,
                face,
                latency,
            )
            if best is None or candidate[:3] < best[:3]:
                best = candidate
        if best is None:
            return None
        _, gaze_key, face_key, gaze, face, latency = best
        del self._gaze[gaze_key]
        del self._face[face_key]
        return DerivedObservation(gaze, face, "capture_time", latency)

    def _nearest_face(
        self, gaze: D7GazeSample
    ) -> tuple[str, ExpressionSample, float] | None:
        candidates = [
            (key, face, latency)
            for key, (face, latency) in self._face.items()
            if face.session_id == gaze.session_id
            and face.playback_epoch == gaze.playback_epoch
            and abs(face.captured_at_mono_ms - gaze.captured_at_mono_ms) <= self._tolerance_ms
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: abs(item[1].captured_at_mono_ms - gaze.captured_at_mono_ms))

    def clear(self) -> None:
        self._gaze.clear()
        self._face.clear()

    def pending_count(self) -> int:
        return len(self._gaze) + len(self._face)


@dataclass(frozen=True, slots=True)
class DropNotice:
    frame_id: str
    reason: Literal["superseded", "cancelled", "disconnected"]


FaceWorkerFactory = Callable[[], FaceWorker]
FrameFactory = Callable[[str], TransientFrame]


class InProcessVisionGateway:
    """D7 harness with metadata-only pending state and one worker in flight."""

    def __init__(
        self,
        *,
        face_worker_factory: FaceWorkerFactory,
        eye_port: ReplayEyePort | None = None,
        frame_factory: FrameFactory = SyntheticFrame,
        delivery_order: Literal["eye_first", "face_first"] = "eye_first",
    ) -> None:
        self._face_worker_factory = face_worker_factory
        self._eye_port = eye_port or ReplayEyePort()
        self._frame_factory = frame_factory
        self._delivery_order = delivery_order
        self._worker: FaceWorker | None = None
        self._handshake: VisionHandshake | None = None
        self._pending: FrameEnvelope | None = None
        self._in_flight = False
        self._state: Literal["new", "connected", "disconnected", "cancelled", "closed"] = "new"
        self._restart_pending = False
        self._joiner = ObservationJoiner()
        self._lock = RLock()
        self.drop_notices: list[DropNotice] = []
        self.timeout_count = 0
        self.error_count = 0

    def connect(self, handshake: VisionHandshake) -> None:
        with self._lock:
            if self._state in ("cancelled", "closed"):
                raise GatewayStateError("closed D7 Gateway cannot connect")
            if self._handshake is not None and (
                handshake.session_id != self._handshake.session_id
                or handshake.video_id != self._handshake.video_id
                or handshake.mode != self._handshake.mode
            ):
                raise GatewayStateError("reconnect handshake does not match the active session")
            if self._state == "connected":
                return
            self._handshake = handshake
            self._worker = self._face_worker_factory()
            self._worker.start()
            self.error_count += self._worker.error_count
            self._state = "connected"

    def offer(self, envelope: FrameEnvelope) -> DropNotice | None:
        with self._lock:
            self._require_connected(envelope)
            dropped = None
            if self._pending is not None:
                dropped = DropNotice(self._pending.frame_id, "superseded")
                self.drop_notices.append(dropped)
            self._pending = envelope
            return dropped

    def dispatch_next(self) -> DerivedObservation | None:
        with self._lock:
            if self._state != "connected":
                raise GatewayStateError("D7 Gateway is not connected")
            if self._in_flight or self._pending is None:
                return None
            envelope, self._pending = self._pending, None
            self._in_flight = True
        frame: TransientFrame | None = None
        frame_cleanup_deferred = False
        adapter_completion: object | None = None
        try:
            frame = self._frame_factory(envelope.frame_id)
            gaze = self._eye_port.infer(frame, envelope)
            worker = self._worker
            if worker is None:
                raise GatewayStateError("Face worker is unavailable")
            timeout_count_before = worker.timeout_count
            error_count_before = worker.error_count
            face_observation = worker.process(frame, envelope)
            frame_cleanup_deferred = face_observation.frame_cleanup_deferred
            adapter_completion = face_observation.adapter_completion
            if adapter_completion is not None:
                # The legacy in-process harness is synchronous. Preserve that
                # boundary while still keeping the frame alive until the
                # timed-out adapter call has actually stopped using it.
                try:
                    adapter_completion.result()
                except Exception:
                    pass
            if self._restart_pending:
                self._restart_pending = False
                worker.start()
            self.timeout_count += worker.timeout_count - timeout_count_before
            self.error_count += worker.error_count - error_count_before
            if self._delivery_order == "face_first":
                joined = self._joiner.push_face(
                    face_observation.sample, latency_ms=face_observation.latency_ms
                )
                joined = self._joiner.push_gaze(gaze) or joined
            else:
                joined = self._joiner.push_gaze(gaze)
                joined = self._joiner.push_face(
                    face_observation.sample, latency_ms=face_observation.latency_ms
                ) or joined
            return joined or self._joiner.flush_nearest()
        finally:
            if frame is not None and not frame_cleanup_deferred:
                frame.close()
                del frame
            if frame_cleanup_deferred and adapter_completion is not None:
                adapter_completion.add_done_callback(
                    lambda _done: self._release_in_flight()
                )
            else:
                self._release_in_flight()

    def _release_in_flight(self) -> None:
        with self._lock:
            self._in_flight = False

    def process(self, envelope: FrameEnvelope) -> DerivedObservation:
        self.offer(envelope)
        observation = self.dispatch_next()
        if observation is None:
            raise GatewayStateError("frame was not dispatched")
        return observation

    def restart_worker(self) -> None:
        with self._lock:
            if self._state != "connected":
                raise GatewayStateError("worker restart requires a connected session")
            if self._worker is not None:
                self._worker.close()
            self._worker = self._face_worker_factory()
            # The first affected frame is explicit model_unavailable. The fresh
            # worker starts immediately after that fail-closed observation.
            self._restart_pending = True

    def disconnect(self) -> None:
        with self._lock:
            if self._pending is not None:
                notice = DropNotice(self._pending.frame_id, "disconnected")
                self.drop_notices.append(notice)
                self._pending = None
            worker, self._worker = self._worker, None
            self._joiner.clear()
            self._state = "disconnected"
        if worker is not None:
            worker.close()

    def cancel(self) -> None:
        self._finish("cancelled")

    def close(self) -> None:
        self._finish("closed")

    def _finish(self, state: Literal["cancelled", "closed"]) -> None:
        with self._lock:
            if self._state == state:
                return
            if self._pending is not None:
                notice = DropNotice(self._pending.frame_id, "cancelled")
                self.drop_notices.append(notice)
                self._pending = None
            worker, self._worker = self._worker, None
            self._joiner.clear()
            self._state = state
        if worker is not None:
            worker.close()
        self._eye_port.close()

    def _require_connected(self, envelope: FrameEnvelope) -> None:
        if self._state != "connected" or self._handshake is None:
            raise GatewayStateError("D7 Gateway is not connected")
        if envelope.session_id != self._handshake.session_id or envelope.video_id != self._handshake.video_id:
            raise GatewayStateError("frame envelope does not match the D7 handshake")

    def public_state(self) -> Mapping[str, object]:
        """Metadata-only diagnostics safe for tests and logs."""
        return {
            "transport": "d7-in-process-harness",
            "state": self._state,
            "in_flight": self._in_flight,
            "pending_frame_id": self._pending.frame_id if self._pending else None,
            "joiner_pending": self._joiner.pending_count(),
            "drop_count": len(self.drop_notices),
            "worker_timeout_count": self.timeout_count,
            "worker_error_count": self.error_count,
        }


def point_in_polygon(x: float, y: float, points: Sequence[Sequence[float]]) -> bool:
    inside = False
    previous = len(points) - 1
    for current, point in enumerate(points):
        current_x, current_y = float(point[0]), float(point[1])
        previous_x, previous_y = float(points[previous][0]), float(points[previous][1])
        if (current_y > y) != (previous_y > y):
            boundary_x = ((previous_x - current_x) * (y - current_y)) / (previous_y - current_y) + current_x
            if x < boundary_x:
                inside = not inside
        previous = current
    return inside


def attention_event(gaze: D7GazeSample, manifest: Mapping[str, object]) -> dict[str, object]:
    sequence = gaze.sequence + 1
    candidates: list[dict[str, object]] = []
    exposures = manifest.get("exposures")
    if gaze.valid and isinstance(exposures, Sequence):
        for exposure in exposures:
            if not isinstance(exposure, Mapping):
                continue
            shape = exposure.get("shape")
            if not isinstance(shape, Mapping) or shape.get("type") != "polygon":
                continue
            if not (
                isinstance(exposure.get("start_ms"), int)
                and isinstance(exposure.get("end_ms"), int)
                and exposure["start_ms"] <= gaze.video_time_ms < exposure["end_ms"]
            ):
                continue
            points = shape.get("points")
            if (
                gaze.screen_x_norm is not None
                and gaze.screen_y_norm is not None
                and isinstance(points, Sequence)
                and point_in_polygon(gaze.screen_x_norm, gaze.screen_y_norm, points)
            ):
                candidates.append(
                    {
                        "exposure_id": exposure["exposure_id"],
                        "product_id": exposure["product_id"],
                        "priority": exposure["priority"],
                    }
                )
    valid = gaze.valid and bool(candidates)
    material = f"{gaze.session_id}|{gaze.frame_id}|{sequence}|d7-attention"
    event: dict[str, object] = {
        "schema_version": "1.0",
        "session_id": gaze.session_id,
        "event_id": f"attention-d7-{sha256(material.encode()).hexdigest()[:24]}",
        "sequence": sequence,
        "frame_id": gaze.frame_id,
        "captured_at_mono_ms": gaze.captured_at_mono_ms,
        "video_id": gaze.video_id,
        "video_time_ms": gaze.video_time_ms,
        "playback_epoch": gaze.playback_epoch,
        "producer_id": "d7-replay-aoi-mapper",
        "model_revision": "d7-replay-aoi-v1",
        "manifest_version": manifest["manifest_version"],
        "source_gaze_event_id": gaze.event_id,
        "outside_video": False,
        "candidates": candidates,
        "valid": valid,
        "confidence": gaze.confidence if valid else 0.0,
        "reason": None if valid else (gaze.reason or "no_product_hit"),
    }
    if valid:
        event["video_x_norm"] = gaze.screen_x_norm
        event["video_y_norm"] = gaze.screen_y_norm
    return event

"""Reusable D7 synthetic/replay session runner wired to the existing API."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Literal, Mapping, Protocol

from mcm_face import FaceWorker

from apps.vision_gateway.gateway import (
    DerivedObservation,
    FrameEnvelope,
    InProcessVisionGateway,
    ReplayEyePort,
    VisionHandshake,
    attention_event,
)


class BackendPort(Protocol):
    def create_session(self) -> str: ...
    def manifest(self) -> Mapping[str, object]: ...
    def ingest(self, session_id: str, batch: Mapping[str, object]) -> Mapping[str, object]: ...
    def complete(self, session_id: str) -> None: ...
    def recommendation(self, session_id: str) -> Mapping[str, object]: ...


class HttpBackendPort:
    """Adapter around FastAPI TestClient without coupling the Gateway to FastAPI."""

    def __init__(
        self,
        client: Any,
        *,
        kiosk_id: str = "kiosk-d7-replay",
        consent_version: str = "consent-d7-synthetic",
    ) -> None:
        self._client = client
        self._kiosk_id = kiosk_id
        self._consent_version = consent_version

    def create_session(self) -> str:
        response = self._client.post(
            "/api/v1/sessions",
            json={
                "kiosk_id": self._kiosk_id,
                "lookbook_id": "mcm-lookbook-example-v1",
                "consent_version": self._consent_version,
            },
        )
        response.raise_for_status()
        return str(response.json()["session_id"])

    def manifest(self) -> Mapping[str, object]:
        response = self._client.get("/api/v1/lookbooks/mcm-lookbook-example-v1/manifest")
        response.raise_for_status()
        return response.json()

    def ingest(self, session_id: str, batch: Mapping[str, object]) -> Mapping[str, object]:
        response = self._client.post(
            f"/api/v1/sessions/{session_id}/reaction-batches", json=dict(batch)
        )
        response.raise_for_status()
        return response.json()

    def complete(self, session_id: str) -> None:
        response = self._client.post(f"/api/v1/sessions/{session_id}/complete")
        response.raise_for_status()

    def recommendation(self, session_id: str) -> Mapping[str, object]:
        response = self._client.get(f"/api/v1/sessions/{session_id}/recommendations")
        response.raise_for_status()
        return response.json()


@dataclass(frozen=True, slots=True)
class D7RunConfig:
    input_mode: Literal["synthetic", "replay", "camera_development"] = "synthetic"
    recommendation_mode: Literal["mock"] = "mock"
    video_id: str = "mcm-lookbook-example-v1"
    capture_step_ms: int = 250


GatewayFactory = Callable[[str, str], InProcessVisionGateway]


class D7SessionRunner:
    def __init__(
        self,
        *,
        backend: BackendPort,
        face_worker_factory: Callable[[], FaceWorker],
        config: D7RunConfig = D7RunConfig(),
        eye_port_factory: Callable[[], ReplayEyePort] = ReplayEyePort,
        gateway_factory: GatewayFactory | None = None,
    ) -> None:
        if config.recommendation_mode != "mock":
            raise ValueError("D7 supports mock recommendation only")
        self.backend = backend
        self.face_worker_factory = face_worker_factory
        self.config = config
        self.eye_port_factory = eye_port_factory
        self.gateway_factory = gateway_factory
        self.session_id: str | None = None
        self.gateway: InProcessVisionGateway | None = None
        self._manifest: Mapping[str, object] | None = None
        self._batches: list[dict[str, object]] = []
        self._cancelled = False
        self._closed = False

    def start(self) -> str:
        if self.session_id is not None:
            return self.session_id
        self.session_id = self.backend.create_session()
        self._manifest = self.backend.manifest()
        if self.gateway_factory is None:
            self.gateway = InProcessVisionGateway(
                face_worker_factory=self.face_worker_factory,
                eye_port=self.eye_port_factory(),
            )
        else:
            self.gateway = self.gateway_factory(self.session_id, self.config.video_id)
        self.gateway.connect(
            VisionHandshake(self.session_id, self.config.video_id, self.config.input_mode)
        )
        return self.session_id

    def process_frame(self, index: int) -> tuple[DerivedObservation, Mapping[str, object]]:
        if self.session_id is None or self.gateway is None or self._manifest is None:
            raise RuntimeError("D7 session has not started")
        if self._cancelled or self._closed:
            raise RuntimeError("D7 session is no longer active")
        context = FrameEnvelope(
            session_id=self.session_id,
            video_id=self.config.video_id,
            frame_id=f"frame-d7-{index:05d}",
            sequence=index * 2,
            captured_at_mono_ms=float(index * self.config.capture_step_ms),
            video_time_ms=index * self.config.capture_step_ms,
            playback_epoch=0,
        )
        return self.process_envelope(context)

    def process_envelope(
        self, context: FrameEnvelope
    ) -> tuple[DerivedObservation, Mapping[str, object]]:
        """Process an already-captured context through the shared D7 event path."""

        if self.session_id is None or self.gateway is None or self._manifest is None:
            raise RuntimeError("D7 session has not started")
        if self._cancelled or self._closed:
            raise RuntimeError("D7 session is no longer active")
        observation = self.gateway.process(context)
        accepted = self._ingest_observation(observation)
        return observation, accepted

    def retry_last_batch(self, *, new_batch_id: bool = False) -> Mapping[str, object]:
        if self.session_id is None or not self._batches:
            raise RuntimeError("there is no D7 batch to retry")
        batch = dict(self._batches[-1])
        if new_batch_id:
            batch["batch_id"] = f"{batch['batch_id']}-retry"
        return self.backend.ingest(self.session_id, batch)

    def disconnect(self) -> None:
        if self.gateway is None:
            raise RuntimeError("D7 session has not started")
        self.gateway.disconnect()

    def reconnect(self) -> None:
        if self.gateway is None or self.session_id is None:
            raise RuntimeError("D7 session has not started")
        self.gateway.connect(
            VisionHandshake(self.session_id, self.config.video_id, self.config.input_mode)
        )

    def restart_worker(self) -> None:
        if self.gateway is None:
            raise RuntimeError("D7 session has not started")
        self.gateway.restart_worker()

    def cancel(self) -> None:
        if self.gateway is not None:
            self.gateway.cancel()
        self._cancelled = True
        self._batches.clear()

    def close(self) -> Mapping[str, object]:
        if self.session_id is None or self.gateway is None:
            raise RuntimeError("D7 session has not started")
        if self._cancelled:
            raise RuntimeError("cancelled D7 sessions cannot complete recommendation")
        if not self._closed:
            if self.gateway.public_state()["state"] == "connected":
                pending = self.gateway.dispatch_next()
                if pending is not None:
                    self._ingest_observation(pending)
            self.gateway.close()
            self.backend.complete(self.session_id)
            self._closed = True
        recommendation = self.backend.recommendation(self.session_id)
        if recommendation.get("engine_mode") != "mock":
            raise RuntimeError("D7 recommendation must remain mock")
        return recommendation

    def _ingest_observation(self, observation: DerivedObservation) -> Mapping[str, object]:
        assert self.session_id is not None
        batch = self._build_batch(observation)
        accepted = self.backend.ingest(self.session_id, batch)
        self._batches.append(batch)
        return accepted

    def _build_batch(self, observation: DerivedObservation) -> dict[str, object]:
        assert self.session_id is not None and self._manifest is not None
        attention = attention_event(observation.gaze, self._manifest)
        material = f"{self.session_id}|{observation.gaze.frame_id}|{observation.gaze.sequence}"
        batch_id = f"batch-d7-{sha256(material.encode()).hexdigest()[:24]}"
        return {
            "schema_version": "1.0",
            "batch_id": batch_id,
            "batch_sequence": observation.gaze.sequence // 2,
            "session_id": self.session_id,
            "video_id": self.config.video_id,
            "events": [observation.face.to_payload(), attention],
        }

    @property
    def batches(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._batches)

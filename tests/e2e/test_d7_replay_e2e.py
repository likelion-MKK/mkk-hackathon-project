from __future__ import annotations

import copy
import gc
import json
import logging
from pathlib import Path
from time import sleep
import weakref

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.vision_gateway import (
    D7RunConfig,
    D7SessionRunner,
    FrameEnvelope,
    HttpBackendPort,
    InProcessVisionGateway,
    ObservationJoiner,
    ReplayEyePort,
    SyntheticFrame,
    VisionHandshake,
)
from apps.vision_gateway.gateway import D7GazeSample
from mcm_face import (
    FaceWorker,
    FakeFaceAdapter,
    FakeFaceScenario,
    FaceFrameContext,
    ReplayFaceAdapter,
    SelectedFaceAdapter,
)


ROOT = Path(__file__).resolve().parents[2]
FACE_REPLAY = ROOT / "services" / "face" / "tests" / "fixtures" / "expression-replay.d3.json"
FORBIDDEN = (
    "raw_frame",
    "image_bytes",
    "base64",
    "embedding",
    "file_path",
    "webcam image",
)


def fake_worker_factory(
    scenario: FakeFaceScenario = FakeFaceScenario.VALID_FACE,
):
    return lambda: FaceWorker(FakeFaceAdapter(scenario=scenario), timeout_ms=50)


def replay_worker_factory():
    return lambda: FaceWorker(ReplayFaceAdapter.from_fixture(FACE_REPLAY), timeout_ms=50)


class DelayedFakeFaceAdapter(FakeFaceAdapter[object]):
    def infer(self, frame: object, context: FaceFrameContext):
        sleep(0.02)
        return super().infer(frame, context)


def make_client() -> tuple[TestClient, MemoryStore]:
    store = MemoryStore(ROOT)
    return TestClient(create_app(store)), store


def make_runner(
    client: TestClient,
    *,
    factory=None,
    mode: str = "synthetic",
) -> D7SessionRunner:
    return D7SessionRunner(
        backend=HttpBackendPort(client),
        face_worker_factory=factory or fake_worker_factory(),
        config=D7RunConfig(input_mode=mode),
    )


def run_completed_session(*, factory=None, mode: str = "synthetic"):
    client, store = make_client()
    with client:
        runner = make_runner(client, factory=factory, mode=mode)
        runner.start()
        first, _ = runner.process_frame(0)
        second, _ = runner.process_frame(1)
        recommendation = runner.close()
        return first, second, recommendation, runner, store


def assert_private(value: object) -> None:
    rendered = json.dumps(value, default=str, ensure_ascii=False).lower()
    assert all(term not in rendered for term in FORBIDDEN)


def test_synthetic_session_reaches_deterministic_mock_top_two() -> None:
    first, second, recommendation, runner, _ = run_completed_session()
    assert first.face.valid is True
    assert second.face.valid is True
    assert first.gaze.frame_id == first.face.frame_id == "frame-d7-00000"
    assert second.gaze.frame_id == second.face.frame_id == "frame-d7-00001"
    assert recommendation["engine_mode"] == "mock"
    assert recommendation["algorithm_version"] == "mock-v1"
    assert recommendation["status"] == "completed"
    assert recommendation["items"] == [
        {"rank": 1, "product_id": "P001"},
        {"rank": 2, "product_id": "P002"},
    ]
    assert [event["sequence"] for batch in runner.batches for event in batch["events"]] == [0, 1, 2, 3]
    gateway_state = runner.gateway.public_state()
    assert gateway_state["state"] == "closed"
    assert gateway_state["in_flight"] is False
    assert gateway_state["pending_frame_id"] is None
    assert gateway_state["joiner_pending"] == 0
    assert gateway_state["drop_count"] == 0


def test_replay_fixture_runs_through_face_worker_and_api() -> None:
    first, second, recommendation, _, _ = run_completed_session(
        factory=replay_worker_factory(), mode="replay"
    )
    assert first.face.valid is True
    assert first.face.model_revision == "face-expression-replay-d3-v1"
    assert second.face.valid is False
    assert second.face.reason == "no_face"
    assert recommendation["engine_mode"] == "mock"
    assert [item["product_id"] for item in recommendation["items"]] == ["P001", "P002"]


def test_no_product_hit_omits_coordinates_and_is_accepted_by_api() -> None:
    client, _ = make_client()
    with client:
        runner = D7SessionRunner(
            backend=HttpBackendPort(client),
            face_worker_factory=fake_worker_factory(),
            eye_port_factory=lambda: ReplayEyePort(coordinates=((0.99, 0.99),)),
        )
        session_id = runner.start()
        _, accepted = runner.process_frame(0)
        attention = runner.batches[-1]["events"][1]

        assert accepted["status"] == "accepted"
        assert attention["valid"] is False
        assert attention["reason"] == "no_product_hit"
        assert attention["candidates"] == []
        assert "video_x_norm" not in attention
        assert "video_y_norm" not in attention

        retry = client.post(
            f"/api/v1/sessions/{session_id}/reaction-batches",
            json=runner.batches[-1],
        )
        assert retry.status_code == 202
        assert retry.json()["status"] == "duplicate"
        runner.cancel()


@pytest.mark.parametrize(
    ("scenario", "reason", "face_count"),
    [
        (FakeFaceScenario.NO_FACE, "no_face", 0),
        (FakeFaceScenario.MULTI_FACE, "multi_face", 2),
        (FakeFaceScenario.LOW_QUALITY, "low_quality", 1),
        (FakeFaceScenario.TIMEOUT, "timeout", 0),
    ],
)
def test_face_invalid_does_not_stop_eye_or_mock_recommendation(
    scenario: FakeFaceScenario, reason: str, face_count: int
) -> None:
    first, second, recommendation, _, _ = run_completed_session(
        factory=fake_worker_factory(scenario)
    )
    assert first.face.valid is False and first.face.reason == reason
    assert first.face.face_count == face_count
    assert first.gaze.valid is True and second.gaze.valid is True
    assert recommendation["status"] == "completed"
    assert recommendation["engine_mode"] == "mock"


def test_worker_deadline_timeout_is_fail_closed_while_eye_continues() -> None:
    factory = lambda: FaceWorker(DelayedFakeFaceAdapter(), timeout_ms=1)
    first, _, recommendation, runner, _ = run_completed_session(factory=factory)
    assert first.face.reason == "timeout"
    assert first.face.valid is False
    assert first.gaze.valid is True
    assert runner.gateway.timeout_count >= 1
    assert recommendation["status"] == "completed"


def test_model_unavailable_is_fail_closed_while_eye_continues(tmp_path: Path) -> None:
    factory = lambda: FaceWorker(
        SelectedFaceAdapter(model_path=tmp_path / "missing.task"), timeout_ms=20
    )
    first, _, recommendation, _, _ = run_completed_session(factory=factory)
    assert first.face.reason == "model_unavailable"
    assert first.face.scores == {}
    assert first.gaze.valid is True
    assert recommendation["status"] == "completed"


def test_worker_restart_marks_one_face_unavailable_then_recovers() -> None:
    client, _ = make_client()
    with client:
        runner = make_runner(client)
        runner.start()
        runner.process_frame(0)
        runner.restart_worker()
        during_restart, _ = runner.process_frame(1)
        recovered, _ = runner.process_frame(2)
        assert during_restart.face.reason == "model_unavailable"
        assert during_restart.gaze.valid is True
        assert recovered.face.valid is True
        runner.cancel()


def test_disconnect_reconnect_and_duplicate_retry_are_idempotent() -> None:
    client, _ = make_client()
    with client:
        runner = make_runner(client)
        runner.start()
        _, accepted = runner.process_frame(0)
        assert accepted["status"] == "accepted"
        runner.disconnect()
        with pytest.raises(RuntimeError, match="not connected"):
            runner.process_frame(1)
        runner.reconnect()
        assert runner.retry_last_batch()["status"] == "duplicate"
        assert runner.retry_last_batch(new_batch_id=True)["status"] == "duplicate"
        runner.process_frame(1)
        assert runner.close()["status"] == "completed"


def test_pending_metadata_is_superseded_without_allocating_a_frame() -> None:
    created: list[str] = []
    gateway = InProcessVisionGateway(
        face_worker_factory=fake_worker_factory(),
        frame_factory=lambda frame_id: (created.append(frame_id) or SyntheticFrame(frame_id)),
    )
    gateway.connect(VisionHandshake("session-d7", "mcm-lookbook-example-v1"))
    first = FrameEnvelope("session-d7", "mcm-lookbook-example-v1", "frame-00000", 0, 0.0, 0, 0)
    second = FrameEnvelope("session-d7", "mcm-lookbook-example-v1", "frame-00001", 2, 250.0, 250, 0)
    assert gateway.offer(first) is None
    dropped = gateway.offer(second)
    assert dropped is not None and dropped.frame_id == first.frame_id
    assert dropped.reason == "superseded"
    assert created == []
    observation = gateway.dispatch_next()
    assert observation is not None and observation.gaze.frame_id == second.frame_id
    assert created == [second.frame_id]
    gateway.close()


def test_cancel_and_close_release_pending_state_and_differ_on_completion() -> None:
    client, store = make_client()
    with client:
        runner = make_runner(client)
        session_id = runner.start()
        runner.gateway.offer(
            FrameEnvelope(session_id, runner.config.video_id, "frame-cancel", 0, 0.0, 0, 0)
        )
        runner.cancel()
        assert runner.gateway.public_state()["state"] == "cancelled"
        assert runner.gateway.public_state()["pending_frame_id"] is None
        assert store.sessions[session_id].completed is False
        with pytest.raises(RuntimeError, match="cannot complete"):
            runner.close()


def test_close_flushes_pending_metadata_before_completion() -> None:
    client, _ = make_client()
    with client:
        runner = make_runner(client)
        session_id = runner.start()
        runner.gateway.offer(
            FrameEnvelope(session_id, runner.config.video_id, "frame-flush", 0, 0.0, 0, 0)
        )
        recommendation = runner.close()
        assert len(runner.batches) == 1
        assert [event["sequence"] for event in runner.batches[0]["events"]] == [0, 1]
        assert recommendation["status"] == "insufficient_data"
        assert recommendation["engine_mode"] == "mock"
        assert runner.gateway.public_state()["pending_frame_id"] is None


def test_out_of_order_derived_results_join_by_frame_then_capture_time() -> None:
    gateway = InProcessVisionGateway(
        face_worker_factory=fake_worker_factory(), delivery_order="face_first"
    )
    gateway.connect(VisionHandshake("session-d7", "mcm-lookbook-example-v1"))
    context = FrameEnvelope("session-d7", "mcm-lookbook-example-v1", "frame-same", 0, 100.0, 100, 0)
    assert gateway.process(context).matched_by == "frame_id"
    gateway.close()

    eye = ReplayEyePort()
    frame = SyntheticFrame("frame-gaze")
    gaze = eye.infer(
        frame,
        FrameEnvelope("session-d7", "mcm-lookbook-example-v1", "frame-gaze", 0, 100.0, 100, 0),
    )
    adapter = FakeFaceAdapter()
    adapter.initialize()
    face_frame = SyntheticFrame("frame-face")
    face = adapter.infer(
        face_frame,
        FrameEnvelope("session-d7", "mcm-lookbook-example-v1", "frame-face", 0, 150.0, 100, 0),
    )
    joiner = ObservationJoiner(tolerance_ms=100)
    assert joiner.push_face(face, latency_ms=1.0) is None
    assert joiner.push_gaze(gaze) is None
    fallback = joiner.flush_nearest()
    assert fallback is not None and fallback.matched_by == "capture_time"
    adapter.dispose()
    eye.close()
    frame.close()
    face_frame.close()


def test_duplicate_sequence_with_new_event_id_is_rejected() -> None:
    client, _ = make_client()
    with client:
        runner = make_runner(client)
        session_id = runner.start()
        runner.process_frame(0)
        conflicting = copy.deepcopy(runner.batches[-1])
        conflicting["batch_id"] = "batch-d7-conflicting-sequence"
        conflicting["events"][0]["event_id"] = "expression-d7-conflict"
        response = client.post(
            f"/api/v1/sessions/{session_id}/reaction-batches", json=conflicting
        )
        assert response.status_code == 400
        assert response.json()["code"] == "duplicate_event_sequence"
        runner.cancel()


def test_same_fixture_in_fresh_store_produces_same_events_and_top_two() -> None:
    first_run = run_completed_session()
    second_run = run_completed_session()
    assert first_run[3].batches == second_run[3].batches
    assert first_run[2] == second_run[2]


def test_synthetic_frames_are_closed_collected_and_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    references: list[weakref.ReferenceType[SyntheticFrame]] = []
    closed: list[bool] = []

    # Slots make close read-only, so use a subclass for lifecycle tracking.
    class TrackedFrame(SyntheticFrame):
        def close(self) -> None:
            super().close()
            closed.append(self.closed)

    def tracked_factory(frame_id: str) -> SyntheticFrame:
        frame = TrackedFrame(frame_id)
        references.append(weakref.ref(frame))
        return frame

    caplog.set_level(logging.DEBUG)
    gateway = InProcessVisionGateway(
        face_worker_factory=fake_worker_factory(), frame_factory=tracked_factory
    )
    gateway.connect(VisionHandshake("session-d7", "mcm-lookbook-example-v1"))
    observation = gateway.process(
        FrameEnvelope("session-d7", "mcm-lookbook-example-v1", "frame-private", 0, 0.0, 0, 0)
    )
    gateway.close()
    gc.collect()
    assert closed == [True]
    assert references[0]() is None
    assert_private(observation.face.to_payload())
    assert_private(observation.gaze.to_payload())
    assert_private(gateway.public_state())
    assert_private(caplog.text)


def test_backend_retains_aggregates_and_ids_not_event_payloads_or_face_scores() -> None:
    client, store = make_client()
    with client:
        runner = make_runner(client)
        session_id = runner.start()
        observation, _ = runner.process_frame(0)
        session = store.sessions[session_id]
        assert session.reaction_features is not None
        assert not hasattr(session, "events")
        assert observation.face.event_id in session.event_ids
        retained = repr(session).lower()
        assert "smile_like" not in retained
        assert_private(retained)
        runner.process_frame(1)
        recommendation = runner.close()
        assert_private(recommendation)
        assert "scores" not in recommendation

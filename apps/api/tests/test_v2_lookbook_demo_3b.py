"""Demo-only Vision 3-B coverage for the explicitly enabled static AOI fixture."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.api.app.v2_central import DeterministicCentralStub, ManualJobDispatcher
from apps.api.app.v2_models import CentralRecommendationRequestV2


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VIDEO_ID = "mcm-lookbook-v2"
MANIFEST_VERSION = "mcm-lookbook-v2-grid-details-v2-2026-08-19"
TONI_PRODUCT_ID = "mcm-toni-medium-disco-visetos"


class CapturingStub(DeterministicCentralStub):
    """Test double that sees only the aggregate CentralRecommendationRequestV2."""

    def __init__(self) -> None:
        self.requests: list[CentralRecommendationRequestV2] = []

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        self.requests.append(request)
        return super().recommend(request)


def _configure_local_memory(monkeypatch: pytest.MonkeyPatch, *, demo: bool) -> None:
    for name in (
        "DATABASE_URL",
        "LOOKBOOK_VIDEO_PATH",
        "REQUIRE_LOOKBOOK_MEDIA_READINESS",
        "CENTRAL_AI_ENDPOINT",
        "CENTRAL_AI_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CENTRAL_AI_INPUT_VARIANT", "C")
    monkeypatch.setenv("RECOMMENDATION_ENGINE", "mock")
    if demo:
        monkeypatch.setenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", "1")
    else:
        monkeypatch.delenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", raising=False)


def _gaze() -> dict[str, object]:
    return {
        "screen_x_norm": 0.25,
        "screen_y_norm": 0.25,
        "confidence": 0.9,
        "producer_id": "demo-3b-eye",
        "model_revision": "demo-3b-eye-v1",
        "calibration_id": "demo-3b-calibration",
    }


def _frame(
    sequence: int,
    *,
    video_time_ms: int,
    video_x: float,
    video_y: float,
) -> dict[str, object]:
    captured_at_mono_ms = float(sequence * 100)
    return {
        "schema_version": "2.0",
        "frame_id": f"demo-3b-frame-{sequence:02d}",
        "sequence": sequence,
        "captured_at_mono_ms": captured_at_mono_ms,
        "session_offset_ms": captured_at_mono_ms,
        "video_time_ms": video_time_ms,
        "playback_epoch": 0,
        "gaze": _gaze(),
        "gaze_reason": None,
        "expression": None,
        "expression_reason": "not_observed",
        "attention": {
            "video_x_norm": video_x,
            "video_y_norm": video_y,
            "outside_video": False,
            "confidence": 0.9,
            "producer_id": "demo-3b-kiosk",
            "model_revision": "demo-3b-video-context-v1",
            "manifest_version": MANIFEST_VERSION,
            "candidates": [],
        },
        "attention_reason": None,
        "derived": None,
        "derived_reason": "invalid_or_missing_modality",
    }


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "kiosk_id": "demo-3b-kiosk",
            "lookbook_id": VIDEO_ID,
            "consent_version": "consent-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def _post_observations(
    client: TestClient,
    session_id: str,
    observations: list[dict[str, object]],
) -> None:
    response = client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json={
            "schema_version": "2.0",
            "batch_id": "demo-3b-static-batch",
            "batch_sequence": 0,
            "session_id": session_id,
            "video_id": VIDEO_ID,
            "observations": observations,
        },
    )
    assert response.status_code == 202, response.text


@pytest.fixture()
def demo_static_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, ManualJobDispatcher, CapturingStub]:
    _configure_local_memory(monkeypatch, demo=True)
    dispatcher = ManualJobDispatcher()
    model = CapturingStub()
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=model,
        job_dispatcher=dispatcher,
    )
    with TestClient(app) as client:
        yield client, dispatcher, model


def test_demo_static_3b_reaches_grounded_variant_c_top_one_from_api_boundary(
    demo_static_client: tuple[TestClient, ManualJobDispatcher, CapturingStub],
) -> None:
    client, dispatcher, model = demo_static_client
    session_id = _create_session(client)
    _post_observations(
        client,
        session_id,
        [
            _frame(1, video_time_ms=5_500, video_x=0.25, video_y=0.25),
            _frame(2, video_time_ms=6_000, video_x=0.75, video_y=0.25),
            _frame(3, video_time_ms=6_500, video_x=0.25, video_y=0.75),
            _frame(4, video_time_ms=7_000, video_x=0.75, video_y=0.75),
            _frame(5, video_time_ms=15_000, video_x=0.25, video_y=0.25),
            _frame(6, video_time_ms=15_200, video_x=0.25, video_y=0.25),
            _frame(7, video_time_ms=16_000, video_x=0.75, video_y=0.25),
            _frame(8, video_time_ms=16_200, video_x=0.75, video_y=0.25),
            _frame(9, video_time_ms=17_000, video_x=0.25, video_y=0.80),
            _frame(10, video_time_ms=17_200, video_x=0.25, video_y=0.80),
            _frame(11, video_time_ms=18_000, video_x=0.75, video_y=0.75),
            _frame(12, video_time_ms=18_200, video_x=0.75, video_y=0.75),
        ],
    )

    completion = client.post(f"/api/v2/sessions/{session_id}/complete")
    assert completion.status_code == 202
    assert client.app.state.v2_store.buffered_observation_count(session_id) == 0
    assert client.get(f"/api/v2/sessions/{session_id}/recommendation").status_code == 202

    dispatcher.run_next()
    decision = client.get(f"/api/v2/sessions/{session_id}/recommendation")
    assert decision.status_code == 200
    assert decision.json()["status"] == "completed"
    assert decision.json()["selected_product_id"] == TONI_PRODUCT_ID
    assert len(model.requests) == 1

    request = model.requests[0]
    assert request.video_id == VIDEO_ID
    assert len(request.products) == 10
    assert request.evidence.input_variant == "C"
    assert request.evidence.timeline is None
    assert request.evidence.signal_versions.face is None
    assert request.evidence.signal_versions.face_reason == "no_valid_expression"

    expected_tags = {
        "mcm-toni-medium-disco-visetos": {"monogram", "shopper", "tote"},
        "mcm-ella-small-disco-visetos": {"boston", "monogram", "top_handle"},
        "mcm-aren-east-west-shoulder-visetos": {
            "monogram",
            "shoulder",
            "structured",
        },
        "mcm-pina-vanity-case-studded-calfskin": {"compact", "structured"},
        "mcm-stark-side-studs-backpack-gold-crystal-visetos": {
            "backpack",
            "monogram",
        },
    }
    observed = {
        item.product_id: item
        for item in request.evidence.summary
        if item.gaze is not None
    }
    assert set(observed) == set(expected_tags)
    for product_id, tags in expected_tags.items():
        summary = observed[product_id]
        assert summary.gaze is not None
        assert summary.gaze.observed_attention_ms > 0
        assert summary.observed_component_codes == ["whole_product"]
        assert set(summary.observed_visual_tag_ids) == tags
        assert summary.expression is None
        assert summary.expression_reason == "no_matched_expression"

    assert request.evidence.evidence_windows is not None
    toni_window = next(
        window
        for window in request.evidence.evidence_windows
        if window.product_id == TONI_PRODUCT_ID
    )
    assert (toni_window.video_start_ms, toni_window.video_end_ms) == (5_500, 7_000)
    assert toni_window.playback_epoch == 0
    assert decision.json()["evidence"][0]["evidence_refs"][0]["kind"] == "window"

    variant_c_payload = request.model_dump_json()
    for raw_field in (
        '"frame_id"',
        '"screen_x_norm"',
        '"screen_y_norm"',
        '"video_x_norm"',
        '"video_y_norm"',
        '"captured_at_mono_ms"',
        '"token"',
    ):
        assert raw_field not in variant_c_payload


def test_demo_static_3b_opt_in_absent_uses_approved_canonical_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_local_memory(monkeypatch, demo=False)
    dispatcher = ManualJobDispatcher()
    model = CapturingStub()
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=model,
        job_dispatcher=dispatcher,
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        response = client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json={
                "schema_version": "2.0",
                "batch_id": "demo-3b-default-approved-source",
                "batch_sequence": 0,
                "session_id": session_id,
                "video_id": VIDEO_ID,
                "observations": [
                    _frame(1, video_time_ms=6_000, video_x=0.25, video_y=0.25)
                ],
            },
        )
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"

    assert dispatcher.jobs == []
    assert model.requests == []

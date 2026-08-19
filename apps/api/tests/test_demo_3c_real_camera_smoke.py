"""Demo 3-C API test-instance coverage.

These tests use synthetic *derived* observations to verify the API/AOI/evidence
boundary.  They deliberately do not claim physical-camera success; that is the
separate manual runbook in ``apps/kiosk/DEMO_3C_REAL_CAMERA_SMOKE.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.demo_3c_test_app import create_demo_3c_test_app
from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.api.app.v2_central import DeterministicCentralStub, ManualJobDispatcher
from apps.api.app.v2_models import CentralRecommendationRequestV2


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VIDEO_ID = "mcm-lookbook-v2"
MANIFEST_VERSION = "mcm-lookbook-v2-grid-details-v2-2026-08-19"
TONI_PRODUCT_ID = "mcm-toni-medium-disco-visetos"


class CapturingDeterministicStub(DeterministicCentralStub):
    """Inspect only the already-aggregated, test-only Variant C request."""

    def __init__(self) -> None:
        self.requests: list[CentralRecommendationRequestV2] = []

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        self.requests.append(request)
        return super().recommend(request)


def _clear_live_service_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "CENTRAL_AI_PROVIDER",
        "CENTRAL_AI_ENDPOINT",
        "LOOKBOOK_VIDEO_PATH",
        "REQUIRE_LOOKBOOK_MEDIA_READINESS",
    ):
        monkeypatch.delenv(name, raising=False)


def _gaze() -> dict[str, object]:
    return {
        "screen_x_norm": 0.25,
        "screen_y_norm": 0.25,
        "confidence": 0.9,
        "producer_id": "demo-3c-eye",
        "model_revision": "demo-3c-eye-v1",
        "calibration_id": "demo-3c-calibration",
    }


def _observation(sequence: int, *, video_time_ms: int) -> dict[str, object]:
    captured_at_mono_ms = float(sequence * 250)
    return {
        "schema_version": "2.0",
        "frame_id": f"demo-3c-frame-{sequence:02d}",
        "sequence": sequence,
        "captured_at_mono_ms": captured_at_mono_ms,
        "session_offset_ms": captured_at_mono_ms,
        "video_time_ms": video_time_ms,
        "playback_epoch": 0,
        "gaze": _gaze(),
        "gaze_reason": None,
        # Demo 3-C intentionally does not use the Face modality.
        "expression": None,
        "expression_reason": "not_observed",
        "attention": {
            "video_x_norm": 0.25,
            "video_y_norm": 0.25,
            "outside_video": False,
            "confidence": 0.9,
            "producer_id": "demo-3c-kiosk",
            "model_revision": "demo-3c-video-context-v1",
            "manifest_version": MANIFEST_VERSION,
            # Browser code never makes an AOI or product candidate.
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
            "kiosk_id": "demo-3c-kiosk",
            "lookbook_id": VIDEO_ID,
            "consent_version": "consent-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def _post_gaze_only_observations(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json={
            "schema_version": "2.0",
            "batch_id": "demo-3c-gaze-only-batch",
            "batch_sequence": 0,
            "session_id": session_id,
            "video_id": VIDEO_ID,
            "observations": [
                _observation(1, video_time_ms=5_500),
                _observation(2, video_time_ms=6_000),
            ],
        },
    )
    assert response.status_code == 202, response.text


def test_demo_3c_real_camera_smoke_test_instance_reaches_variant_c_top_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_live_service_environment(monkeypatch)
    monkeypatch.setenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", "1")
    dispatcher = ManualJobDispatcher()
    model = CapturingDeterministicStub()
    app = create_demo_3c_test_app(
        central_client=model,
        job_dispatcher=dispatcher,
    )

    with TestClient(app) as client:
        session_id = _create_session(client)
        _post_gaze_only_observations(client, session_id)

        completion = client.post(f"/api/v2/sessions/{session_id}/complete")
        assert completion.status_code == 202
        assert client.app.state.v2_store.buffered_observation_count(session_id) == 0
        assert client.get(f"/api/v2/sessions/{session_id}/recommendation").status_code == 202

        dispatcher.run_next()
        decision = client.get(f"/api/v2/sessions/{session_id}/recommendation")

    assert decision.status_code == 200
    payload = decision.json()
    assert payload["status"] == "completed"
    assert payload["selected_product_id"] == TONI_PRODUCT_ID
    assert payload["data_quality"]["gaze_valid_ratio"] > 0
    # This ratio means gaze+Face co-occurrence, not AOI mapping. Demo 3-C
    # intentionally omits Face, so an AOI window must prove the mapping instead.
    assert payload["data_quality"]["matched_frame_ratio"] == 0
    assert payload["evidence"][0]["product_id"] == TONI_PRODUCT_ID
    assert payload["evidence"][0]["evidence_refs"][0]["kind"] == "window"
    assert len(model.requests) == 1

    request = model.requests[0]
    assert request.evidence.input_variant == "C"
    assert request.evidence.timeline is None
    assert request.evidence.signal_versions.face is None
    assert request.evidence.signal_versions.face_reason == "no_valid_expression"

    toni = next(item for item in request.evidence.summary if item.product_id == TONI_PRODUCT_ID)
    assert toni.gaze is not None
    assert toni.gaze.valid_observation_count == 2
    assert toni.observed_component_codes == ["whole_product"]
    assert set(toni.observed_visual_tag_ids) == {"monogram", "shopper", "tote"}
    assert toni.expression is None
    assert toni.expression_reason == "no_matched_expression"

    variant_c_payload = request.model_dump_json()
    assert '"timeline":null' in variant_c_payload
    rendered_values = (variant_c_payload, json.dumps(payload, sort_keys=True))
    for rendered in rendered_values:
        for forbidden in (
            '"frame_id"',
            '"screen_x_norm"',
            '"screen_y_norm"',
            '"video_x_norm"',
            '"video_y_norm"',
            '"captured_at_mono_ms"',
            '"token"',
        ):
            assert forbidden not in rendered


def test_demo_3c_canonical_approved_source_metadata_reaches_top_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_live_service_environment(monkeypatch)
    monkeypatch.delenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", raising=False)
    dispatcher = ManualJobDispatcher()
    model = CapturingDeterministicStub()
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=model,
        job_dispatcher=dispatcher,
        central_input_variant="C",
    )

    with TestClient(app) as client:
        session_id = _create_session(client)
        response = client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json={
                "schema_version": "2.0",
                "batch_id": "demo-3c-default-pending-batch",
                "batch_sequence": 0,
                "session_id": session_id,
                "video_id": VIDEO_ID,
                "observations": [_observation(1, video_time_ms=6_000)],
            },
        )

        assert response.status_code == 202, response.text
        completion = client.post(f"/api/v2/sessions/{session_id}/complete")
        assert completion.status_code == 202, completion.text
        dispatcher.run_next()
        decision = client.get(f"/api/v2/sessions/{session_id}/recommendation")

    assert decision.status_code == 200
    assert decision.json()["status"] == "completed"
    assert decision.json()["selected_product_id"] in {
        product.product_id for product in model.requests[0].products
    }
    assert len(model.requests) == 1
    assert model.requests[0].source_visual_evidence is not None


def test_demo_3c_test_app_requires_opt_in_and_rejects_live_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_live_service_environment(monkeypatch)
    monkeypatch.delenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", raising=False)
    with pytest.raises(RuntimeError, match="MCM_LOOKBOOK_DEMO_STATIC_AOI=1"):
        create_demo_3c_test_app()

    monkeypatch.setenv("MCM_LOOKBOOK_DEMO_STATIC_AOI", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-a-real-demo-db")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_demo_3c_test_app()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CENTRAL_AI_PROVIDER", "openai_luna")
    with pytest.raises(RuntimeError, match="deterministic stub"):
        create_demo_3c_test_app()

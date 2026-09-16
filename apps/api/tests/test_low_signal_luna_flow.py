"""Exercise the real Luna adapter with synthetic data and an offline HTTP transport."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.api.app.v2_central import ManualJobDispatcher, OpenAILunaCentralClient
from apps.api.app.v2_postgres import load_canonical_catalog
from apps.api.app.source_aoi import load_product_matching_catalog
from apps.api.app.v2_store import MemoryStoreRecommendationRepository, V2RecommendationStore


ROOT = Path(__file__).resolve().parents[3]
FRAME_ID = "synthetic-weak-frame-1"


def _frame(kind: str) -> dict:
    gaze = {
        "screen_x_norm": 0.5, "screen_y_norm": 0.5, "confidence": 0.35,
        "producer_id": "synthetic-eye", "model_revision": "synthetic-low-confidence",
        "calibration_id": "synthetic-calibration",
    } if kind == "weak_gaze" else None
    expression = {
        "scores": {"neutral": 0.6, "happy": 0.4}, "quality": 0.2, "confidence": 0.2,
        "producer_id": "synthetic-face", "model_revision": "synthetic-face-v1",
        "taxonomy_version": "synthetic-v1",
    } if kind == "expression_only" else None
    return {
        "schema_version": "2.0", "frame_id": FRAME_ID, "sequence": 0,
        "captured_at_mono_ms": 100.0, "session_offset_ms": 0.0,
        "video_time_ms": 1500, "playback_epoch": 0,
        "gaze": gaze, "gaze_reason": None if gaze else "gaze_unavailable",
        "attention": None, "attention_reason": "layout_unavailable",
        "expression": expression, "expression_reason": None if expression else "not_observed",
        "derived": None, "derived_reason": "invalid_or_missing_modality",
    }


@pytest.fixture
def flow(monkeypatch):
    memory = MemoryStore(ROOT)
    catalog = load_canonical_catalog(ROOT / "data/products/mcm-submission-recommendation-profile-v4.json")
    matching = load_product_matching_catalog(
        ROOT, path=ROOT / "data/products/mcm-submission-matching-profiles-v4.json",
    )
    repository = MemoryStoreRecommendationRepository(memory, catalog=catalog, matching_catalog=matching)
    store = V2RecommendationStore(repository)
    dispatcher = ManualJobDispatcher()
    # The model's answer deliberately selects a non-first item.
    product = catalog.products[3]
    calls = []
    behavior = {"mode": "success"}
    original = httpx.AsyncClient

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if behavior["mode"] == "unavailable":
            return httpx.Response(503, json={"error": {"message": "synthetic failure"}})
        output = {
            "product_id": product.product_id,
            "reason": "제한적인 관측과 상품 특징을 비교한 추천입니다.",
            "reason_codes": ["catalog_tag_alignment"],
            "evidence": [{
                "code": "data_quality", "product_id": product.product_id,
                "evidence_refs": [{"kind": "frame", "ref_id": FRAME_ID}],
                "statement": "관측 품질과 상품 연결 결측을 유지했습니다.",
            }],
            "style": {"matched_tags": [product.controlled_tags[0]], "summary": "검수 태그 비교"},
            "exploration_tendency_code": "focused_single_product",
        }
        if behavior["mode"] == "invented_reference":
            output["evidence"][0]["evidence_refs"][0]["ref_id"] = "not-observed"
        return httpx.Response(200, json={
            "status": "completed", "model": "gpt-5.6-luna",
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(output)},
            ]}],
        })

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    app = create_app(
        memory, v2_store=store, central_client=OpenAILunaCentralClient(api_key="synthetic-test-key"),
        job_dispatcher=dispatcher,
    )
    with TestClient(app) as client:
        response = client.post("/api/v1/sessions", json={
            "kiosk_id": "synthetic-test", "lookbook_id": "mcm-lookbook-v2", "consent_version": "consent-v1",
        })
        assert response.status_code == 201
        session_id = response.json()["session_id"]
        yield client, store, dispatcher, session_id, calls, behavior, product


def _ingest(client, session_id, kind):
    response = client.post(f"/api/v2/sessions/{session_id}/observations", json={
        "schema_version": "2.0", "batch_id": "synthetic-batch", "batch_sequence": 0,
        "session_id": session_id, "video_id": "mcm-lookbook-v2", "observations": [_frame(kind)],
    })
    assert response.status_code == 202, response.text


@pytest.mark.parametrize("kind", ["weak_gaze", "expression_only", "quality_only"])
def test_one_observation_calls_luna_once_and_preserves_its_selection(flow, kind):
    client, store, dispatcher, session_id, calls, _, product = flow
    _ingest(client, session_id, kind)
    path = f"/api/v2/sessions/{session_id}"
    accepted = client.post(f"{path}/complete")
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "pending"
    assert store.buffered_observation_count(session_id) == 0
    assert client.post(f"{path}/complete").json() == accepted.json()
    assert len(dispatcher.jobs) == 1
    dispatcher.run_next()
    result = client.get(f"{path}/recommendation").json()
    assert result["status"] == "completed", result
    assert result["selected_product_id"] == product.product_id
    assert result["version"]["model_id"] == "gpt-5.6-luna"
    assert result["version"]["prompt_version"] == "central-recommender-ko-v8"
    assert len(calls) == 1
    request = json.loads(calls[0]["input"][1]["content"])
    assert calls[0]["reasoning"]["effort"] == "medium"
    assert calls[0]["store"] is False
    assert request["evidence"]["input_variant"] == "B"
    assert len(request["products"]) == 10
    frame = request["evidence"]["timeline"][0]
    assert frame["frame_id"] == FRAME_ID
    assert frame["attention_reason"] == "layout_unavailable"
    assert not frame.get("attention")
    if kind == "weak_gaze":
        assert frame["gaze"]["confidence"] == 0.35
        assert frame["gaze"]["screen_x_norm"] == 0.5
        assert result["data_quality"]["gaze_valid_ratio"] == 1
    else:
        assert frame["gaze_reason"] == "gaze_unavailable"
        assert result["data_quality"]["gaze_valid_ratio"] == 0
    assert store.buffered_observation_count(session_id) == 0
    assert client.delete(path).status_code == 204


def test_zero_observations_does_not_invent_a_recommendation(flow):
    client, store, dispatcher, session_id, calls, _, _ = flow
    path = f"/api/v2/sessions/{session_id}"
    assert client.post(f"{path}/complete").status_code == 202
    result = client.get(f"{path}/recommendation").json()
    assert result["status"] == "insufficient_data"
    assert result["selected_product_id"] is None
    assert not calls and not dispatcher.jobs
    assert store.buffered_observation_count(session_id) == 0


@pytest.mark.parametrize("mode", ["unavailable", "invented_reference"])
def test_provider_failure_does_not_substitute_a_collection_item(flow, mode):
    client, store, dispatcher, session_id, calls, behavior, _ = flow
    behavior["mode"] = mode
    _ingest(client, session_id, "weak_gaze")
    path = f"/api/v2/sessions/{session_id}"
    assert client.post(f"{path}/complete").status_code == 202
    dispatcher.run_next()
    result = client.get(f"{path}/recommendation").json()
    assert result["status"] == "failed"
    assert result["selected_product_id"] is None
    assert len(calls) == 1
    assert store.buffered_observation_count(session_id) == 0


def test_cancelled_weak_session_never_calls_luna(flow):
    client, store, dispatcher, session_id, calls, _, _ = flow
    _ingest(client, session_id, "weak_gaze")
    path = f"/api/v2/sessions/{session_id}"
    assert client.post(f"{path}/complete").status_code == 202
    assert client.delete(path).status_code == 204
    dispatcher.run_next()
    assert not calls
    assert store.buffered_observation_count(session_id) == 0

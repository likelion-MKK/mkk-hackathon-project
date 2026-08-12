"""Integration coverage for manager-entered conversion outcomes."""

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REACTION_FIXTURE = REPOSITORY_ROOT / "contracts" / "examples" / "reaction-batch.valid.json"


def create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"kiosk_id": "kiosk-test-01", "lookbook_id": "mcm-lookbook-example-v1", "consent_version": "consent-v1"},
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def reaction_batch(session_id: str) -> dict:
    body = json.loads(REACTION_FIXTURE.read_text(encoding="utf-8"))
    body["session_id"] = session_id
    for event in body["events"]:
        event["session_id"] = session_id
    second_attention = copy.deepcopy(body["events"][1])
    second_attention.update(event_id="attention-example-0002", sequence=4, candidates=[{"exposure_id": "scene-01-product-02", "product_id": "P002", "priority": 0}])
    body["events"].append(second_attention)
    return body


def conversion_body(session_id: str, recommendation_id: str, outcome_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "outcome_id": outcome_id,
        "session_id": session_id,
        "recommendation_id": recommendation_id,
        "product_id": "P001",
        "outcome_type": "tried_on",
        "source": "manager_input",
        "recorded_at": "2026-08-11T09:00:00+09:00",
    }


def test_conversion_requires_a_completed_recommended_product() -> None:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as client:
        session_id = create_session(client)
        assert client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=reaction_batch(session_id)).status_code == 202
        assert client.post(f"/api/v1/sessions/{session_id}/complete").status_code == 202
        recommendation = client.get(f"/api/v1/sessions/{session_id}/recommendations").json()
        body = conversion_body(session_id, recommendation["recommendation_id"], "outcome-test-0001")
        response = client.post("/api/v1/conversions", json=body)
        assert response.status_code == 201
        assert response.json()["outcome_id"] == body["outcome_id"]


def test_conversion_retries_are_idempotent_but_reused_ids_conflict() -> None:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as client:
        session_id = create_session(client)
        assert client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=reaction_batch(session_id)).status_code == 202
        assert client.post(f"/api/v1/sessions/{session_id}/complete").status_code == 202
        recommendation = client.get(f"/api/v1/sessions/{session_id}/recommendations").json()
        body = conversion_body(session_id, recommendation["recommendation_id"], "outcome-test-0002")

        assert client.post("/api/v1/conversions", json=body).status_code == 201
        duplicate = client.post("/api/v1/conversions", json=body)
        assert duplicate.status_code == 201
        assert duplicate.json() == body

        conflicting = {**body, "outcome_type": "purchased"}
        response = client.post("/api/v1/conversions", json=conflicting)
        assert response.status_code == 409
        assert response.json()["code"] == "outcome_id_conflict"

        second_session_id = create_session(client)
        assert client.post(f"/api/v1/sessions/{second_session_id}/reaction-batches", json=reaction_batch(second_session_id)).status_code == 202
        assert client.post(f"/api/v1/sessions/{second_session_id}/complete").status_code == 202
        second_recommendation = client.get(f"/api/v1/sessions/{second_session_id}/recommendations").json()
        cross_session = client.post(
            "/api/v1/conversions",
            json=conversion_body(second_session_id, second_recommendation["recommendation_id"], body["outcome_id"]),
        )
        assert cross_session.status_code == 409
        assert cross_session.json()["code"] == "outcome_id_conflict"


def test_conversion_returns_not_found_and_conflict_for_invalid_state() -> None:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as client:
        missing_session = client.post(
            "/api/v1/conversions",
            json=conversion_body("session-missing", "recommendation-session-missing-001", "outcome-test-0003"),
        )
        assert missing_session.status_code == 404
        assert missing_session.json()["code"] == "session_not_found"

        session_id = create_session(client)
        unready = client.post(
            "/api/v1/conversions",
            json=conversion_body(session_id, f"recommendation-{session_id}-001", "outcome-test-0004"),
        )
        assert unready.status_code == 409
        assert unready.json()["code"] == "recommendation_not_ready"

        completed_session_id = create_session(client)
        assert client.post(
            f"/api/v1/sessions/{completed_session_id}/reaction-batches",
            json=reaction_batch(completed_session_id),
        ).status_code == 202
        assert client.post(f"/api/v1/sessions/{completed_session_id}/complete").status_code == 202
        recommendation = client.get(f"/api/v1/sessions/{completed_session_id}/recommendations").json()

        mismatched_recommendation = client.post(
            "/api/v1/conversions",
            json=conversion_body(completed_session_id, "recommendation-other", "outcome-test-0005"),
        )
        assert mismatched_recommendation.status_code == 400
        assert mismatched_recommendation.json()["code"] == "recommendation_mismatch"

        not_recommended = client.post(
            "/api/v1/conversions",
            json={
                **conversion_body(completed_session_id, recommendation["recommendation_id"], "outcome-test-0006"),
                "product_id": "P003",
            },
        )
        assert not_recommended.status_code == 400
        assert not_recommended.json()["code"] == "product_not_recommended"

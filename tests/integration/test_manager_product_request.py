"""Integration coverage for explicit S04 manager product requests."""

import copy
import json
from pathlib import Path

import pytest
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
    second_attention.update(
        event_id="attention-example-0002",
        sequence=4,
        candidates=[{"exposure_id": "scene-01-product-02", "product_id": "P002", "priority": 0}],
    )
    body["events"].append(second_attention)
    return body


def test_manager_product_request_is_explicit_and_idempotent() -> None:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as client:
        session_id = create_session(client)
        assert client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=reaction_batch(session_id)).status_code == 202
        assert client.post(f"/api/v1/sessions/{session_id}/complete").status_code == 202
        recommendation = client.get(f"/api/v1/sessions/{session_id}/recommendations").json()
        assert client.get("/api/v1/manager/events").json() == []

        body = {"request_id": "manager-request-test-0001", "recommendation_id": recommendation["recommendation_id"]}
        assert client.post(f"/api/v1/sessions/{session_id}/manager-product-requests", json=body).json()["status"] == "accepted"
        assert client.post(f"/api/v1/sessions/{session_id}/manager-product-requests", json=body).json()["status"] == "duplicate"

        event = client.get("/api/v1/manager/events").json()[0]
        assert event["event_type"] == "customer_product_request"
        assert event["payload"]["intent"] == "view_recommended_products"
        assert event["payload"]["items"] == [{"rank": 1, "product_id": "P001"}, {"rank": 2, "product_id": "P002"}]
        assert client.get(f"/api/v1/manager/events?after_sequence={event['sequence']}").json() == []


@pytest.mark.parametrize("session_id", ["not valid!", "s" * 129])
def test_manager_product_request_path_identifier_is_validated(session_id: str) -> None:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as client:
        response = client.post(
            f"/api/v1/sessions/{session_id}/manager-product-requests",
            json={"request_id": "manager-request-test-0002", "recommendation_id": "recommendation-test-0001"},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"

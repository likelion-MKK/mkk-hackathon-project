"""Integration coverage for the API session and reaction foundation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REACTION_FIXTURE = REPOSITORY_ROOT / "contracts" / "examples" / "reaction-batch.valid.json"


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as test_client:
        yield test_client


def create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "kiosk_id": "kiosk-test-01",
            "lookbook_id": "mcm-lookbook-example-v1",
            "consent_version": "consent-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def reaction_batch(session_id: str) -> dict:
    body = json.loads(REACTION_FIXTURE.read_text(encoding="utf-8"))
    body["session_id"] = session_id
    for event in body["events"]:
        event["session_id"] = session_id
    return body


def test_session_manifest_product_and_reaction_batch(client: TestClient) -> None:
    session_id = create_session(client)

    manifest = client.get("/api/v1/lookbooks/mcm-lookbook-example-v1/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["video_id"] == "mcm-lookbook-example-v1"

    product = client.get("/api/v1/products/P001")
    assert product.status_code == 200
    assert product.json()["product_id"] == "P001"

    batch = reaction_batch(session_id)
    accepted = client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=batch)
    assert accepted.status_code == 202
    assert accepted.json() == {"batch_id": batch["batch_id"], "status": "accepted"}

    duplicate_batch = copy.deepcopy(batch)
    duplicate_batch["batch_id"] = "batch-example-0002"
    duplicate = client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=duplicate_batch)
    assert duplicate.status_code == 202
    assert duplicate.json() == {"batch_id": "batch-example-0002", "status": "duplicate"}


def test_raw_frame_payload_is_rejected(client: TestClient) -> None:
    session_id = create_session(client)
    body = reaction_batch(session_id)
    body["events"][0]["frame"] = {"bytes": "not-allowed"}

    response = client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=body)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"

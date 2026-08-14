"""Integration coverage for recommendation completion and retrieval."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Never

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.schemas import SessionCreate
from apps.api.app.store import MemoryStore
from services.recommendation.engine.research_gaze import ResearchGazeScoreEngine
from services.recommendation.mock.engine import MockRecommendationEngine


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REACTION_FIXTURE = REPOSITORY_ROOT / "contracts" / "examples" / "reaction-batch.valid.json"


class FailingRecommendationEngine:
    def run(self, **_: object) -> Never:
        raise RuntimeError("recommendation engine unavailable")


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


def test_complete_session_returns_mock_top_two_without_manager_event() -> None:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as client:
        session_id = create_session(client)
        assert client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=reaction_batch(session_id)).status_code == 202

        complete = client.post(f"/api/v1/sessions/{session_id}/complete")
        assert complete.status_code == 202
        assert complete.json() == {"session_id": session_id, "status": "pending"}

        recommendation = client.get(f"/api/v1/sessions/{session_id}/recommendations")
        assert recommendation.status_code == 200
        assert recommendation.json()["status"] == "completed"
        assert recommendation.json()["items"] == [{"rank": 1, "product_id": "P001"}, {"rank": 2, "product_id": "P002"}]
        assert client.get("/api/v1/manager/events").json() == []


def test_complete_session_without_valid_attention_returns_insufficient_data() -> None:
    with TestClient(create_app(MemoryStore(REPOSITORY_ROOT))) as client:
        session_id = create_session(client)
        assert client.post(f"/api/v1/sessions/{session_id}/complete").status_code == 202

        recommendation = client.get(f"/api/v1/sessions/{session_id}/recommendations")
        assert recommendation.json()["status"] == "insufficient_data"
        assert recommendation.json()["reason"] == "not_enough_valid_attention"


def test_complete_session_can_use_the_research_gaze_score_engine() -> None:
    with TestClient(
        create_app(MemoryStore(REPOSITORY_ROOT), ResearchGazeScoreEngine())
    ) as client:
        session_id = create_session(client)
        assert client.post(
            f"/api/v1/sessions/{session_id}/reaction-batches",
            json=reaction_batch(session_id),
        ).status_code == 202

        assert client.post(f"/api/v1/sessions/{session_id}/complete").status_code == 202
        recommendation = client.get(f"/api/v1/sessions/{session_id}/recommendations")

    assert recommendation.status_code == 200
    assert recommendation.json()["engine_mode"] == "research_version"
    assert recommendation.json()["algorithm_version"] == "gaze-score-v0"
    assert recommendation.json()["items"] == [
        {"rank": 1, "product_id": "P001"},
        {"rank": 2, "product_id": "P002"},
    ]


def test_completed_session_discards_active_event_deduplication_and_features() -> None:
    store = MemoryStore(REPOSITORY_ROOT)
    with TestClient(create_app(store)) as client:
        session_id = create_session(client)
        assert client.post(f"/api/v1/sessions/{session_id}/reaction-batches", json=reaction_batch(session_id)).status_code == 202

        session = store.sessions[session_id]
        assert not hasattr(session, "events")
        assert session.reaction_features is not None
        snapshot = session.reaction_features.snapshot()
        assert [(item.product_id, item.valid_attention_count) for item in snapshot.product_attention] == [("P001", 1), ("P002", 1)]

        assert client.post(f"/api/v1/sessions/{session_id}/complete").status_code == 202

        assert session.reaction_features is None
        assert session.event_ids == set()
        assert session.event_sequences == set()
        assert session.batch_ids == set()


def test_engine_failure_keeps_session_retryable() -> None:
    store = MemoryStore(REPOSITORY_ROOT)
    session = store.create_session(
        SessionCreate(
            kiosk_id="kiosk-test-01",
            lookbook_id="mcm-lookbook-example-v1",
            consent_version="consent-v1",
        )
    )

    with pytest.raises(RuntimeError, match="recommendation engine unavailable"):
        store.complete_session(session.session_id, FailingRecommendationEngine())

    assert store.get_recommendation(session.session_id).status == "pending"
    accepted = store.complete_session(session.session_id, MockRecommendationEngine())
    assert accepted.status == "pending"
    assert store.get_recommendation(session.session_id).status == "insufficient_data"

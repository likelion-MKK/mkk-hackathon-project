from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import _configured_input_variant, create_app
from apps.api.app.schemas import SessionCreate
from apps.api.app.store import MemoryStore
from apps.api.app.v2_central import (
    APPROVED_PROMPT_VERSION,
    CentralModelError,
    DeterministicCentralStub,
    ManualJobDispatcher,
    SelfHostedHttpCentralClient,
    configured_central_client,
    validate_central_output,
)
from apps.api.app.v2_evidence import summarize_observations
from apps.api.app.v2_models import (
    CentralRecommendationRequestV2,
    FrameObservationV2,
    ObservationBatchV2,
)
from apps.api.app.v2_store import MemoryStoreRecommendationRepository, V2RecommendationStore
from apps.api.app.v2_postgres import load_canonical_catalog, seed_catalog


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_1 = "mcm-toni-medium-disco-visetos"
PRODUCT_2 = "mcm-diamant-3d-small-calfskin"
VIDEO_ID = "mcm-central-ai-replay-v2"
MANIFEST_VERSION = "mcm-central-ai-replay-v2-2026-08-16"
EXPOSURES = {
    PRODUCT_1: "replay-scene-01-toni",
    PRODUCT_2: "replay-scene-02-diamant",
}


def _gaze(x: float = 0.25) -> dict[str, object]:
    return {
        "screen_x_norm": x,
        "screen_y_norm": 0.5,
        "confidence": 0.9,
        "producer_id": "eye-test",
        "model_revision": "eye-v1",
        "calibration_id": "calibration-test",
    }


def _expression(happy: float = 0.2) -> dict[str, object]:
    return {
        "scores": {"happy": happy, "neutral": 1.0 - happy},
        "quality": 0.9,
        "confidence": 0.8,
        "producer_id": "face-test",
        "model_revision": "face-v1",
        "taxonomy_version": "taxonomy-v1",
    }


def _attention(*product_ids: str, outside_video: bool = False) -> dict[str, object]:
    return {
        "outside_video": outside_video,
        "video_x_norm": None if outside_video else 0.25,
        "video_y_norm": None if outside_video else 0.5,
        "confidence": 0.9,
        "producer_id": "aoi-test",
        "model_revision": "aoi-v1",
        "manifest_version": MANIFEST_VERSION,
        "candidates": [
            {
                "exposure_id": EXPOSURES.get(product_id, f"exposure-{product_id}"),
                "product_id": product_id,
                "priority": index,
            }
            for index, product_id in enumerate(product_ids)
        ],
    }


def _frame(
    sequence: int,
    captured_ms: float,
    *,
    frame_id: str | None = None,
    epoch: int = 0,
    video_time_ms: int | None = None,
    gaze: dict[str, object] | None = None,
    gaze_reason: str | None = None,
    expression: dict[str, object] | None = None,
    expression_reason: str | None = None,
    attention: dict[str, object] | None = None,
    attention_reason: str | None = None,
) -> dict[str, object]:
    derived = None
    derived_reason = "invalid_or_missing_modality"
    if gaze is not None and expression is not None:
        has_previous = sequence > 0
        derived = {
            "gaze": {
                "movement": (
                    {"distance_norm": 0.01, "speed_norm_per_s": 0.1}
                    if has_previous
                    else None
                ),
                "movement_reason": None if has_previous else "no_previous_observation",
                "continuous_observation_ms": captured_ms,
                "return_candidate": False if has_previous else None,
                "return_candidate_reason": (
                    None if has_previous else "no_previous_observation"
                ),
            },
            "gaze_reason": None,
            "expression": {
                "score_changes": {"happy": 0.01} if has_previous else None,
                "score_change_rates_per_s": {"happy": 0.1} if has_previous else None,
                "change_reason": None if has_previous else "no_previous_observation",
                "sustained_actions": [],
            },
            "expression_reason": None,
        }
        derived_reason = None
    return {
        "schema_version": "2.0",
        "frame_id": frame_id or f"frame-{sequence}",
        "sequence": sequence,
        "captured_at_mono_ms": captured_ms,
        "session_offset_ms": captured_ms,
        "video_time_ms": sequence * 100 if video_time_ms is None else video_time_ms,
        "playback_epoch": epoch,
        "gaze": gaze,
        "gaze_reason": gaze_reason if gaze is None else None,
        "expression": expression,
        "expression_reason": expression_reason if expression is None else None,
        "attention": attention,
        "attention_reason": attention_reason if attention is None else None,
        "derived": derived,
        "derived_reason": derived_reason,
    }


def _valid_frame(sequence: int, captured_ms: float, *, product_id: str = PRODUCT_1, **kwargs: object) -> dict[str, object]:
    return _frame(
        sequence,
        captured_ms,
        gaze=_gaze(0.2 + (sequence % 20) * 0.01),
        expression=_expression(0.2 + (sequence % 20) * 0.01),
        attention=_attention(product_id),
        **kwargs,
    )


def _batch(session_id: str, batch_id: str, batch_sequence: int, frames: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "session_id": session_id,
        "video_id": VIDEO_ID,
        "observations": frames,
    }


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "kiosk_id": "kiosk-v2-test",
            "lookbook_id": VIDEO_ID,
            "consent_version": "consent-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


@pytest.fixture()
def v2_client() -> tuple[TestClient, ManualJobDispatcher]:
    dispatcher = ManualJobDispatcher()
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=DeterministicCentralStub(),
        job_dispatcher=dispatcher,
    )
    with TestClient(app) as client:
        yield client, dispatcher


def test_same_frame_join_and_out_of_order_batches_complete_asynchronously(
    v2_client: tuple[TestClient, ManualJobDispatcher],
) -> None:
    client, dispatcher = v2_client
    session_id = _create_session(client)
    late_partial = _frame(
        2,
        200.0,
        frame_id="joined-frame",
        gaze=_gaze(),
        expression=None,
        expression_reason="face_not_detected",
        attention=_attention(PRODUCT_1),
    )
    early = _valid_frame(1, 100.0)
    assert client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "batch-2", 2, [late_partial]),
    ).status_code == 202
    assert client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "batch-1", 1, [early]),
    ).status_code == 202

    completed_partial = _frame(
        2,
        200.0,
        frame_id="joined-frame",
        gaze=None,
        gaze_reason="join_pending",
        expression=_expression(0.4),
        attention=_attention(PRODUCT_1),
    )
    joined = client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "batch-3", 3, [completed_partial]),
    )
    assert joined.status_code == 202, joined.text

    accepted = client.post(f"/api/v2/sessions/{session_id}/complete")
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "pending"
    assert client.app.state.v2_store.buffered_observation_count(session_id) == 0
    pending = client.get(f"/api/v2/sessions/{session_id}/recommendation")
    assert pending.status_code == 202
    dispatcher.run_next()
    result = client.get(f"/api/v2/sessions/{session_id}/recommendation")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    assert result.json()["selected_product_id"] == PRODUCT_1
    assert result.json()["version"]["input_variant"] == "C"


def test_missing_no_face_gap_and_seek_reset_continuity() -> None:
    observations = [
        FrameObservationV2.model_validate(_valid_frame(0, 0.0)),
        FrameObservationV2.model_validate(
            _frame(
                1,
                100.0,
                gaze=None,
                gaze_reason="gaze_unavailable",
                expression=None,
                expression_reason="face_not_detected",
                attention=_attention(PRODUCT_1),
            )
        ),
        FrameObservationV2.model_validate(_valid_frame(2, 2_000.0)),
        FrameObservationV2.model_validate(
            _valid_frame(3, 2_100.0, epoch=1, video_time_ms=0)
        ),
    ]

    summary = summarize_observations(observations)

    assert summary.missing_gaze_count == 1
    assert summary.missing_expression_count == 1
    assert summary.continuity_reset_count >= 2
    signal = next(item for item in summary.evidence.summary if item.product_id == PRODUCT_1)
    assert signal.gaze is not None
    assert signal.gaze.movement_distance_norm is None
    assert signal.gaze.mean_speed_norm_per_s is None
    assert signal.gaze.movement_reason == "no_comparable_gaze_observation"
    assert signal.exposure_duration_ms == 100.0


def test_multi_aoi_is_not_attributed_to_a_product_or_expression() -> None:
    ambiguous = FrameObservationV2.model_validate(
        _frame(
            0,
            0.0,
            gaze=_gaze(),
            expression=_expression(),
            attention=_attention(PRODUCT_1, PRODUCT_2),
        )
    )

    summary = summarize_observations([ambiguous])

    assert summary.ambiguous_attention_count == 1
    assert summary.eligible_product_ids == frozenset()


def test_cumulative_sustained_action_uses_max_and_first_frame_motion_is_unknown() -> None:
    observations: list[FrameObservationV2] = []
    for sequence, duration_ms in enumerate((250.0, 500.0, 750.0)):
        frame = _valid_frame(sequence, sequence * 250.0)
        assert isinstance(frame["derived"], dict)
        expression = frame["derived"]["expression"]
        assert isinstance(expression, dict)
        expression["sustained_actions"] = [
            {"signal": "happy", "duration_ms": duration_ms}
        ]
        observations.append(FrameObservationV2.model_validate(frame))

    summary = summarize_observations(observations)
    signal = next(item for item in summary.evidence.summary if item.product_id == PRODUCT_1)
    assert signal.expression is not None
    assert signal.expression.sustained_actions[0].duration_ms == 750.0

    first_only = summarize_observations([observations[0]])
    first_signal = next(
        item for item in first_only.evidence.summary if item.product_id == PRODUCT_1
    )
    assert first_signal.gaze is not None
    assert first_signal.gaze.movement_distance_norm is None
    assert first_signal.gaze.movement_reason == "no_comparable_gaze_observation"
    assert first_signal.gaze.return_candidate_count is None
    assert first_signal.gaze.return_candidate_reason == "no_comparable_gaze_observation"


def _central_request(
    *, input_variant: str = "C"
) -> CentralRecommendationRequestV2:
    repository = MemoryStoreRecommendationRepository(MemoryStore(REPOSITORY_ROOT))
    products = list(repository._catalog.products)
    summary = summarize_observations(
        [FrameObservationV2.model_validate(_valid_frame(0, 0.0))],
        decision_request_id="decision-test",
        session_id="session-test",
        video_id=VIDEO_ID,
        manifest_version=MANIFEST_VERSION,
        catalog_version=repository._catalog.catalog_version,
        product_ids=[product.product_id for product in products],
        input_variant=input_variant,
    )
    return CentralRecommendationRequestV2(
        decision_request_id="decision-test",
        session_id="session-test",
        video_id=VIDEO_ID,
        prompt_version="prompt-v1",
        evidence_version="feature-v1",
        evidence=summary.evidence,
        products=products,
    )


@pytest.mark.parametrize(
    ("raw", "reason_code"),
    [
        ("not-json-object", "invalid_model_output"),
        (
            {
                "product_id": "P999",
                "reason": "관찰된 반응에 따른 추천입니다.",
                "reason_codes": ["observed_attention_lead"],
                "evidence": [
                    {
                        "code": "observed_attention",
                        "product_id": "P999",
                        "evidence_refs": [{"kind": "window", "ref_id": "window-0001"}],
                        "statement": "관찰 근거가 있습니다.",
                    }
                ],
                "style": {"matched_tags": ["daily"], "summary": "요약"},
                "exploration_tendency_code": "focused_single_product",
            },
            "catalog_mismatch",
        ),
        (
            {
                "product_id": PRODUCT_1,
                "reason": "고객은 내향적인 성격이므로 추천합니다.",
                "reason_codes": ["observed_attention_lead"],
                "evidence": [
                    {
                        "code": "observed_attention",
                        "product_id": PRODUCT_1,
                        "evidence_refs": [{"kind": "window", "ref_id": "window-0001"}],
                        "statement": "관찰 근거가 있습니다.",
                    }
                ],
                "style": {"matched_tags": ["daily"], "summary": "요약"},
                "exploration_tendency_code": "focused_single_product",
            },
            "invalid_model_output",
        ),
    ],
)
def test_invalid_model_outputs_are_rejected(raw: object, reason_code: str) -> None:
    with pytest.raises(CentralModelError) as exc_info:
        validate_central_output(raw, request=_central_request())
    assert exc_info.value.reason_code == reason_code


def test_http_timeout_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise TimeoutError

    monkeypatch.setattr("apps.api.app.v2_central.urlopen", timeout)
    client = SelfHostedHttpCentralClient(endpoint="http://127.0.0.1:9999/infer")
    with pytest.raises(CentralModelError) as exc_info:
        client.recommend(_central_request())
    assert exc_info.value.reason_code == "model_unavailable"
    assert "session-test" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("input_variant", "has_windows", "has_timeline"),
    [("A", True, True), ("B", False, True), ("C", True, False)],
)
def test_configured_evidence_variant_has_exact_payload(
    input_variant: str,
    has_windows: bool,
    has_timeline: bool,
) -> None:
    request = _central_request(input_variant=input_variant)
    assert request.evidence.input_variant == input_variant
    assert (request.evidence.evidence_windows is not None) is has_windows
    assert (request.evidence.timeline is not None) is has_timeline


def test_variant_b_uses_only_grounded_frame_references() -> None:
    request = _central_request(input_variant="B")
    raw = DeterministicCentralStub().recommend(request)
    output = validate_central_output(raw, request=request)
    assert output.evidence[0].evidence_refs[0].kind == "frame"

    assert isinstance(raw, dict)
    raw["evidence"][0]["evidence_refs"] = [
        {"kind": "window", "ref_id": "window-0001"}
    ]
    with pytest.raises(CentralModelError, match="frame evidence"):
        validate_central_output(raw, request=request)


@pytest.mark.parametrize(
    "unsafe_phrase",
    [
        "고객이 행복해 보여 추천합니다.",
        "이 제품에 호감을 느끼고 좋아합니다.",
        "스트레스를 받고 있어 구매하려 합니다.",
        "The customer is angry and wants to buy this bag.",
        "The customer likes this product.",
    ],
)
def test_psychological_and_purchase_intent_assertions_are_rejected(
    unsafe_phrase: str,
) -> None:
    request = _central_request()
    raw = DeterministicCentralStub().recommend(request)
    assert isinstance(raw, dict)
    raw["reason"] = unsafe_phrase
    with pytest.raises(CentralModelError) as exc_info:
        validate_central_output(raw, request=request)
    assert exc_info.value.reason_code == "invalid_model_output"


def test_endpoint_config_requires_pinned_model_prompt_variant_and_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CENTRAL_AI_ENDPOINT", "http://127.0.0.1:9000/infer")
    for name in (
        "CENTRAL_AI_MODEL_ID",
        "CENTRAL_AI_MODEL_REVISION",
        "CENTRAL_AI_PROMPT_VERSION",
        "CENTRAL_AI_INPUT_VARIANT",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="CENTRAL_AI_MODEL_ID"):
        configured_central_client()

    monkeypatch.setenv("CENTRAL_AI_MODEL_ID", "model-reviewed")
    monkeypatch.setenv("CENTRAL_AI_MODEL_REVISION", "revision-reviewed")
    monkeypatch.setenv("CENTRAL_AI_PROMPT_VERSION", "stale-prompt")
    with pytest.raises(ValueError, match="approved"):
        configured_central_client()
    monkeypatch.setenv("CENTRAL_AI_PROMPT_VERSION", APPROVED_PROMPT_VERSION)
    assert configured_central_client().prompt_version == APPROVED_PROMPT_VERSION
    with pytest.raises(ValueError, match="INPUT_VARIANT"):
        _configured_input_variant()

    monkeypatch.setenv("CENTRAL_AI_INPUT_VARIANT", "C")
    assert _configured_input_variant() == "C"
    monkeypatch.setenv("CENTRAL_AI_ENDPOINT", "https://central.internal/infer")
    monkeypatch.delenv("CENTRAL_AI_BENCHMARK_APPROVAL", raising=False)
    with pytest.raises(ValueError, match="BENCHMARK_APPROVAL"):
        _configured_input_variant()
    monkeypatch.setenv("CENTRAL_AI_BENCHMARK_APPROVAL", "benchmark-decision-2026-08-16")
    assert _configured_input_variant() == "C"


def test_manager_development_origin_is_allowed_by_default() -> None:
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=DeterministicCentralStub(),
        job_dispatcher=ManualJobDispatcher(),
    )
    with TestClient(app) as client:
        response = client.options(
            "/api/v2/manager/events",
            headers={
                "Origin": "http://localhost:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"


def test_failure_cancel_and_ttl_clear_transient_state() -> None:
    now = [100.0]
    memory = MemoryStore(REPOSITORY_ROOT)
    session_id = memory.create_session(
        SessionCreate(
            kiosk_id="kiosk-direct",
            lookbook_id=VIDEO_ID,
            consent_version="consent-v1",
        )
    ).session_id
    store = V2RecommendationStore(
        MemoryStoreRecommendationRepository(memory),
        clock=lambda: now[0],
        collecting_ttl_seconds=5.0,
        pending_ttl_seconds=5.0,
        decision_ttl_seconds=5.0,
    )
    batch = ObservationBatchV2.model_validate(
        _batch(session_id, "batch-direct", 0, [_valid_frame(0, 0.0)])
    )
    store.append_batch(session_id, batch)
    assert store.buffered_observation_count(session_id) == 1
    now[0] = 106.0
    assert store.cleanup_expired() == 1
    assert store.buffered_observation_count(session_id) == 0

    now[0] = 200.0
    store.append_batch(session_id, batch.model_copy(update={"batch_id": "batch-cancel"}))
    store.cancel(session_id)
    assert store.buffered_observation_count(session_id) == 0


def test_pending_persistence_failure_is_terminal_and_never_dispatched() -> None:
    class FailingPersistence:
        def __init__(self) -> None:
            self.pending_attempts = 0
            self.decision_attempts = 0

        def save_pending(self, *args: object) -> None:
            del args
            self.pending_attempts += 1
            raise RuntimeError("database unavailable")

        def save_decision(self, *args: object) -> None:
            del args
            self.decision_attempts += 1
            raise RuntimeError("database unavailable")

    memory = MemoryStore(REPOSITORY_ROOT)
    persistence = FailingPersistence()
    v2_store = V2RecommendationStore(
        MemoryStoreRecommendationRepository(memory, persistence=persistence)
    )
    dispatcher = ManualJobDispatcher()
    app = create_app(
        memory,
        central_client=DeterministicCentralStub(),
        job_dispatcher=dispatcher,
        v2_store=v2_store,
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        accepted = client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json=_batch(session_id, "batch-db-failure", 0, [_valid_frame(0, 0.0)]),
        )
        assert accepted.status_code == 202
        complete = client.post(f"/api/v2/sessions/{session_id}/complete")
        assert complete.status_code == 202
        assert dispatcher.jobs == []
        assert v2_store.buffered_observation_count(session_id) == 0
        decision = client.get(f"/api/v2/sessions/{session_id}/recommendation")
        assert decision.status_code == 200
        assert decision.json()["status"] == "failed"
        assert decision.json()["reason"]["code"] == "model_unavailable"
    assert persistence.pending_attempts == 1
    assert persistence.decision_attempts == 1


def test_variant_b_completion_records_variant_and_frame_reference() -> None:
    dispatcher = ManualJobDispatcher()
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=DeterministicCentralStub(),
        job_dispatcher=dispatcher,
        central_input_variant="B",
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json=_batch(session_id, "batch-variant-b", 0, [_valid_frame(0, 0.0)]),
        )
        client.post(f"/api/v2/sessions/{session_id}/complete")
        dispatcher.run_next()
        decision = client.get(f"/api/v2/sessions/{session_id}/recommendation").json()
        assert decision["status"] == "completed"
        assert decision["version"]["input_variant"] == "B"
        assert decision["evidence"][0]["evidence_refs"][0]["kind"] == "frame"


def test_complete_is_idempotent_and_sends_all_ten_catalog_candidates() -> None:
    class CapturingStub(DeterministicCentralStub):
        def __init__(self) -> None:
            self.requests: list[CentralRecommendationRequestV2] = []

        def recommend(self, request: CentralRecommendationRequestV2) -> object:
            self.requests.append(request)
            return super().recommend(request)

    model = CapturingStub()
    dispatcher = ManualJobDispatcher()
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=model,
        job_dispatcher=dispatcher,
        central_input_variant="A",
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        response = client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json=_batch(session_id, "batch-idempotent", 0, [_valid_frame(0, 0.0)]),
        )
        assert response.status_code == 202, response.text
        first = client.post(f"/api/v2/sessions/{session_id}/complete")
        second = client.post(f"/api/v2/sessions/{session_id}/complete")
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()
        assert len(dispatcher.jobs) == 1
        dispatcher.run_next()
        third = client.post(f"/api/v2/sessions/{session_id}/complete")
        assert third.json() == first.json()
        assert len(model.requests) == 1
        assert len(model.requests[0].products) == 10
        assert {product.product_id for product in model.requests[0].products} == {
            product.product_id for product in load_canonical_catalog(
                REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
            ).products
        }


def test_production_central_endpoint_requires_https_and_service_auth() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        SelfHostedHttpCentralClient(endpoint="http://central.internal/infer", bearer_token="token")
    with pytest.raises(ValueError, match="authentication"):
        SelfHostedHttpCentralClient(endpoint="https://central.internal/infer")
    with pytest.raises(ValueError, match="HTTPS"):
        SelfHostedHttpCentralClient(endpoint="http://localhost.evil/infer")
    local = SelfHostedHttpCentralClient(endpoint="http://127.0.0.1:9000/infer")
    assert local.bearer_token is None


def test_manager_v2_bridge_emits_only_explicit_exact_top_one_request(
    v2_client: tuple[TestClient, ManualJobDispatcher],
) -> None:
    client, dispatcher = v2_client
    session_id = _create_session(client)
    client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "batch-manager", 0, [_valid_frame(0, 0.0)]),
    )
    accepted = client.post(f"/api/v2/sessions/{session_id}/complete").json()
    assert client.get("/api/v2/manager/events").json() == []
    dispatcher.run_next()
    wrong = client.post(
        f"/api/v2/sessions/{session_id}/manager-product-requests",
        json={
            "schema_version": "2.0",
            "request_id": "manager-request-wrong",
            "recommendation_id": accepted["recommendation_id"],
            "selected_product_id": PRODUCT_2,
            "intent": "view_recommended_product",
        },
    )
    assert wrong.status_code == 400

    body = {
        "schema_version": "2.0",
        "request_id": "manager-request-1",
        "recommendation_id": accepted["recommendation_id"],
        "selected_product_id": PRODUCT_1,
        "intent": "view_recommended_product",
    }
    first = client.post(
        f"/api/v2/sessions/{session_id}/manager-product-requests", json=body
    )
    duplicate = client.post(
        f"/api/v2/sessions/{session_id}/manager-product-requests", json=body
    )
    assert first.json() == {"request_id": "manager-request-1", "status": "accepted"}
    assert duplicate.json() == {"request_id": "manager-request-1", "status": "duplicate"}
    events = client.get("/api/v2/manager/events").json()
    assert len(events) == 1
    assert events[0]["payload"] == {
        "recommendation_id": accepted["recommendation_id"],
        "selected_product_id": PRODUCT_1,
        "intent": "view_recommended_product",
    }
    assert "items" not in events[0]["payload"]
    assert "engine_mode" not in events[0]["payload"]


def test_v2_manifest_and_product_routes_use_canonical_ids(
    v2_client: tuple[TestClient, ManualJobDispatcher],
) -> None:
    client, _ = v2_client
    manifest = client.get(f"/api/v2/lookbooks/{VIDEO_ID}/manifest")
    product = client.get(f"/api/v2/products/{PRODUCT_1}")
    assert manifest.status_code == product.status_code == 200
    assert manifest.json()["exposures"][0]["product_id"] == PRODUCT_1
    assert product.json()["product_id"] == PRODUCT_1
    assert product.json()["official_product_url"] is None
    assert product.json()["official_product_url_reason"]


def test_unknown_evidence_window_reference_is_rejected() -> None:
    request = _central_request()
    profile = request.products[0]
    raw = DeterministicCentralStub().recommend(request)
    assert isinstance(raw, dict)
    raw["evidence"][0]["evidence_refs"] = [
        {"kind": "window", "ref_id": "window-not-provided"}
    ]
    raw["style"]["matched_tags"] = [profile.controlled_tags[0]]
    with pytest.raises(CentralModelError) as exc_info:
        validate_central_output(raw, request=request)
    assert exc_info.value.reason_code == "invalid_model_output"


def test_postgres_seed_is_exactly_ten_and_idempotent_sql() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.rows: list[tuple[object, ...]] = []
            self.queries: list[str] = []

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def executemany(self, query: str, rows: list[tuple[object, ...]]) -> None:
            self.queries.append(query)
            self.rows.extend(rows)

        def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
            del params
            self.queries.append(query)

        def fetchone(self) -> tuple[object, ...]:
            return (10,)

    class FakeConnection:
        def __init__(self) -> None:
            self.fake_cursor = FakeCursor()

        def cursor(self) -> FakeCursor:
            return self.fake_cursor

    catalog = load_canonical_catalog(
        REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
    )
    connection = FakeConnection()
    seed_catalog(connection, catalog)
    seed_catalog(connection, catalog)
    assert len(connection.fake_cursor.rows) == 20
    assert len({row[1] for row in connection.fake_cursor.rows}) == 10
    assert "ON CONFLICT (catalog_version, product_id) DO UPDATE" in connection.fake_cursor.queries[0]

    migration = (
        REPOSITORY_ROOT
        / "apps"
        / "api"
        / "migrations"
        / "0001_central_recommendation_v2.sql"
    ).read_text(encoding="utf-8").lower()
    assert "create table if not exists recommendation_catalog_v2" in migration
    assert "create table if not exists recommendation_job_v2" in migration
    assert "create table if not exists frame" not in migration
    assert "create table if not exists observation" not in migration
    assert "request_body" not in migration


def test_canonical_sixty_second_replay_produces_one_top1_and_clears_timeline() -> None:
    class CapturingStub(DeterministicCentralStub):
        def __init__(self) -> None:
            self.request: CentralRecommendationRequestV2 | None = None

        def recommend(self, request: CentralRecommendationRequestV2) -> object:
            self.request = request
            return super().recommend(request)

    model = CapturingStub()
    dispatcher = ManualJobDispatcher()
    app = create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=model,
        job_dispatcher=dispatcher,
        central_input_variant="A",
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        manifest = client.get(f"/api/v2/lookbooks/{VIDEO_ID}/manifest").json()
        frames: list[dict[str, object]] = []
        for sequence, video_time_ms in enumerate(range(0, 60_000, 250)):
            exposure = next(
                item
                for item in manifest["exposures"]
                if item["start_ms"] <= video_time_ms < item["end_ms"]
            )
            frame = _valid_frame(
                sequence,
                float(video_time_ms),
                product_id=exposure["product_id"],
                video_time_ms=video_time_ms,
            )
            frame["attention"]["candidates"][0]["exposure_id"] = exposure["exposure_id"]
            frames.append(frame)
        assert len(frames) == 240
        response = client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json=_batch(session_id, "batch-full-sixty-second-replay", 0, frames),
        )
        assert response.status_code == 202, response.text
        complete = client.post(f"/api/v2/sessions/{session_id}/complete")
        assert complete.status_code == 202
        assert client.app.state.v2_store.buffered_observation_count(session_id) == 0
        dispatcher.run_next()
        decision = client.get(f"/api/v2/sessions/{session_id}/recommendation").json()
        assert decision["status"] == "completed"
        assert decision["version"]["input_variant"] == "A"
        assert isinstance(decision["selected_product_id"], str)
        assert decision["selected_product_id"] in {
            item["product_id"] for item in manifest["exposures"]
        }
        assert model.request is not None
        assert len(model.request.products) == 10
        assert model.request.evidence.timeline is not None
        assert len(model.request.evidence.timeline) == 240
        assert client.app.state.v2_store.buffered_observation_count(session_id) == 0

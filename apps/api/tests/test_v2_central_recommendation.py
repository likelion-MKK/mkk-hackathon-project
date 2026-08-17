from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import _configured_input_variant, create_app
from apps.api.app.schemas import SessionCreate
from apps.api.app.store import MemoryStore
from apps.api.app.v2_aoi import LookbookAoiMetadataV2, load_aoi_metadata
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
from apps.api.app.v2_postgres import (
    DatabaseReadiness,
    catalog_readiness_rows,
    load_canonical_catalog,
    seed_catalog,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_1 = "mcm-toni-medium-disco-visetos"
PRODUCT_2 = "mcm-diamant-3d-small-calfskin"
VIDEO_ID = "mcm-central-ai-replay-v2"
MANIFEST_VERSION = "mcm-central-ai-replay-v2-2026-08-16"
ACTUAL_VIDEO_ID = "mcm-lookbook-v2"
ACTUAL_MANIFEST_VERSION = "mcm-lookbook-v2-2026-08-18"
EXPOSURES = {
    PRODUCT_1: "replay-scene-01-toni",
    PRODUCT_2: "replay-scene-02-diamant",
}
CATALOG = load_canonical_catalog(
    REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
)
CATALOG_IDS = [product.product_id for product in CATALOG.products]
SYNTHETIC_AOI_METADATA = load_aoi_metadata(
    REPOSITORY_ROOT
    / "data"
    / "lookbooks"
    / VIDEO_ID
    / "aoi-metadata-v2.json"
)


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


def _attention(
    *product_ids: str,
    outside_video: bool = False,
    manifest_version: str = MANIFEST_VERSION,
) -> dict[str, object]:
    # Product arguments remain accepted so older test call sites stay readable,
    # but a production Kiosk is forbidden from assigning AOIs or products.
    del product_ids
    return {
        "outside_video": outside_video,
        "video_x_norm": None if outside_video else 0.25,
        "video_y_norm": None if outside_video else 0.5,
        "confidence": 0.9,
        "producer_id": "kiosk-video-coordinate-v1",
        "model_revision": "video-content-rect-v1",
        "manifest_version": manifest_version,
        "candidates": [],
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


def _batch(
    session_id: str,
    batch_id: str,
    batch_sequence: int,
    frames: list[dict[str, object]],
    *,
    video_id: str = VIDEO_ID,
) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "session_id": session_id,
        "video_id": video_id,
        "observations": frames,
    }


def _create_session(client: TestClient, *, video_id: str = VIDEO_ID) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "kiosk_id": "kiosk-v2-test",
            "lookbook_id": video_id,
            "consent_version": "consent-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def _summarize(
    observations: list[FrameObservationV2],
    *,
    aoi_metadata: LookbookAoiMetadataV2 = SYNTHETIC_AOI_METADATA,
    **kwargs: object
) -> object:
    return summarize_observations(
        observations,
        aoi_metadata=aoi_metadata,
        product_ids=CATALOG_IDS,
        **kwargs,
    )


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
        attention=None,
        attention_reason="join_pending",
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
                attention=None,
                attention_reason="source_gaze_unavailable",
            )
        ),
        FrameObservationV2.model_validate(_valid_frame(2, 2_000.0)),
        FrameObservationV2.model_validate(
            _valid_frame(3, 2_100.0, epoch=1, video_time_ms=0)
        ),
    ]

    summary = _summarize(observations)

    assert summary.missing_gaze_count == 1
    assert summary.missing_expression_count == 1
    assert summary.continuity_reset_count >= 2
    signal = next(item for item in summary.evidence.summary if item.product_id == PRODUCT_1)
    assert signal.gaze is not None
    assert signal.gaze.movement_distance_norm is None
    assert signal.gaze.mean_speed_norm_per_s is None
    assert signal.gaze.movement_reason == "no_comparable_gaze_observation"
    assert signal.exposure_duration_ms == 0.0


def test_different_product_aoi_overlap_is_not_attributed() -> None:
    metadata_payload = SYNTHETIC_AOI_METADATA.model_dump(mode="json")
    metadata_payload["metadata_revision"] = "ambiguous-products-test-v1"
    metadata_payload["exposures"].append(
        {
            "aoi_id": "overlap-diamant",
            "parent_aoi_id": None,
            "specificity_rank": 0,
            "start_ms": 0,
            "end_ms": 6000,
            "shape": {
                "type": "polygon",
                "points": [[0, 0], [1, 0], [1, 1], [0, 1]],
            },
            "product_id": PRODUCT_2,
            "component_code": "whole_product",
            "observed_visual_tag_ids": ["leather", "shoulder"],
        }
    )
    ambiguous_metadata = LookbookAoiMetadataV2.model_validate(metadata_payload)
    ambiguous = FrameObservationV2.model_validate(
        _frame(
            0,
            0.0,
            gaze=_gaze(),
            expression=_expression(),
            attention=_attention(),
        )
    )

    summary = _summarize([ambiguous], aoi_metadata=ambiguous_metadata)

    assert summary.ambiguous_attention_count == 1
    assert summary.eligible_product_ids == frozenset()


def test_same_product_parent_and_child_overlap_are_all_aggregated() -> None:
    metadata_payload = SYNTHETIC_AOI_METADATA.model_dump(mode="json")
    metadata_payload["metadata_revision"] = "same-product-hierarchy-test-v1"
    metadata_payload["exposures"].append(
        {
            "aoi_id": "toni-handle",
            "parent_aoi_id": EXPOSURES[PRODUCT_1],
            "specificity_rank": 1,
            "start_ms": 0,
            "end_ms": 6000,
            "shape": {
                "type": "polygon",
                "points": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]],
            },
            "product_id": PRODUCT_1,
            "component_code": "handle",
            "observed_visual_tag_ids": ["shopper"],
        }
    )
    metadata = LookbookAoiMetadataV2.model_validate(metadata_payload)
    frame = FrameObservationV2.model_validate(_valid_frame(0, 0.0))

    summary = _summarize([frame], aoi_metadata=metadata)

    signal = next(item for item in summary.evidence.summary if item.product_id == PRODUCT_1)
    assert signal.observed_component_codes == ["handle", "whole_product"]
    assert signal.observed_visual_tag_ids == ["monogram", "shopper"]
    assert summary.eligible_product_ids == frozenset({PRODUCT_1})


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

    summary = _summarize(observations)
    signal = next(item for item in summary.evidence.summary if item.product_id == PRODUCT_1)
    assert signal.expression is not None
    assert signal.expression.sustained_actions[0].duration_ms == 750.0

    first_only = _summarize([observations[0]])
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
    products = list(CATALOG.products)
    summary = summarize_observations(
        [FrameObservationV2.model_validate(_valid_frame(0, 0.0))],
        decision_request_id="decision-test",
        session_id="session-test",
        video_id=VIDEO_ID,
        manifest_version=MANIFEST_VERSION,
        catalog_version=CATALOG.catalog_version,
        aoi_metadata=SYNTHETIC_AOI_METADATA,
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


def test_variant_c_never_contains_raw_frame_token_or_individual_gaze_coordinates() -> None:
    request = _central_request(input_variant="C")
    payload = request.model_dump_json()

    assert request.evidence.timeline is None
    assert "video_x_norm" not in payload
    assert "video_y_norm" not in payload
    assert "screen_x_norm" not in payload
    assert "screen_y_norm" not in payload
    assert "frame_id" not in payload
    assert "calibration_id" not in payload
    assert "vision_stream_token" not in payload


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


def test_gaze_only_observation_can_complete_without_expression() -> None:
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
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        gaze_only = _frame(
            0,
            0.0,
            gaze=_gaze(),
            expression=None,
            expression_reason="not_observed",
            attention=_attention(PRODUCT_1),
        )
        assert client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json=_batch(session_id, "batch-gaze-only", 0, [gaze_only]),
        ).status_code == 202
        assert client.post(f"/api/v2/sessions/{session_id}/complete").status_code == 202
        dispatcher.run_next()
        decision = client.get(
            f"/api/v2/sessions/{session_id}/recommendation"
        ).json()

    assert decision["status"] == "completed"
    assert len(model.requests) == 1
    assert model.requests[0].evidence.data_quality.expression_valid_ratio == 0.0


def test_cancelled_job_discards_late_result_and_marks_durable_status_once() -> None:
    class LifecyclePersistence:
        def __init__(self) -> None:
            self.cancelled: list[str] = []
            self.decisions: list[object] = []

        def initialize_runtime(self, _catalog: object) -> DatabaseReadiness:
            return DatabaseReadiness(True)

        def check_readiness(self, _catalog: object) -> DatabaseReadiness:
            return DatabaseReadiness(True)

        def save_pending(self, *_args: object) -> bool:
            return True

        def claim_job(self, _decision_request_id: str) -> bool:
            return True

        def save_decision(self, _session_id: str, decision: object) -> bool:
            self.decisions.append(decision)
            return True

        def mark_cancelled(self, decision_request_id: str) -> bool:
            self.cancelled.append(decision_request_id)
            return True

        def fail_job(self, *_args: object) -> bool:
            return True

        def cleanup_orphan_jobs(self, _seconds: float) -> int:
            return 0

        def cleanup_retention(self, _seconds: float) -> int:
            return 0

    class CapturingStub(DeterministicCentralStub):
        def __init__(self) -> None:
            self.calls = 0

        def recommend(self, request: CentralRecommendationRequestV2) -> object:
            self.calls += 1
            return super().recommend(request)

    memory = MemoryStore(REPOSITORY_ROOT)
    persistence = LifecyclePersistence()
    repository = MemoryStoreRecommendationRepository(
        memory,
        persistence=persistence,
        database_required=True,
    )
    model = CapturingStub()
    dispatcher = ManualJobDispatcher()
    app = create_app(
        memory,
        central_client=model,
        job_dispatcher=dispatcher,
        v2_store=V2RecommendationStore(repository),
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json=_batch(session_id, "batch-cancel-late", 0, [_valid_frame(0, 0.0)]),
        )
        accepted = client.post(f"/api/v2/sessions/{session_id}/complete").json()
        assert len(dispatcher.jobs) == 1
        assert client.delete(f"/api/v2/sessions/{session_id}").status_code == 204
        dispatcher.run_next()

    assert persistence.cancelled == [accepted["decision_request_id"]]
    assert persistence.decisions == []
    assert model.calls == 0


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


def test_backend_rejects_client_supplied_product_candidates(
    v2_client: tuple[TestClient, ManualJobDispatcher],
) -> None:
    client, _ = v2_client
    session_id = _create_session(client)
    frame = _valid_frame(0, 0.0)
    assert isinstance(frame["attention"], dict)
    frame["attention"]["candidates"] = [
        {
            "exposure_id": EXPOSURES[PRODUCT_1],
            "product_id": PRODUCT_1,
            "priority": 0,
        }
    ]

    response = client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "batch-client-attribution", 0, [frame]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "client_product_attribution_forbidden"
    assert client.app.state.v2_store.buffered_observation_count(session_id) == 0


def test_actual_video_without_approved_aoi_fails_closed_at_backend(
    v2_client: tuple[TestClient, ManualJobDispatcher],
) -> None:
    client, _ = v2_client
    session_id = _create_session(client, video_id=ACTUAL_VIDEO_ID)
    frame = _frame(
        0,
        0.0,
        video_time_ms=1_000,
        gaze=_gaze(),
        expression=_expression(),
        attention=_attention(manifest_version=ACTUAL_MANIFEST_VERSION),
    )

    response = client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(
            session_id,
            "batch-actual-pending-aoi",
            0,
            [frame],
            video_id=ACTUAL_VIDEO_ID,
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "aoi_metadata_unapproved"
    assert client.app.state.v2_store.buffered_observation_count(session_id) == 0


def test_video_identity_time_and_epoch_context_mismatches_are_rejected(
    v2_client: tuple[TestClient, ManualJobDispatcher],
) -> None:
    client, _ = v2_client

    video_session = _create_session(client)
    video_mismatch = client.post(
        f"/api/v2/sessions/{video_session}/observations",
        json=_batch(
            video_session,
            "batch-video-mismatch",
            0,
            [_valid_frame(0, 0.0)],
            video_id=ACTUAL_VIDEO_ID,
        ),
    )
    assert video_mismatch.status_code == 400
    assert video_mismatch.json()["code"] == "video_mismatch"

    regression_session = _create_session(client)
    first = _valid_frame(0, 0.0, video_time_ms=500)
    second = _valid_frame(1, 100.0, video_time_ms=400)
    assert client.post(
        f"/api/v2/sessions/{regression_session}/observations",
        json=_batch(regression_session, "batch-time-first", 0, [first]),
    ).status_code == 202
    regression = client.post(
        f"/api/v2/sessions/{regression_session}/observations",
        json=_batch(regression_session, "batch-time-regression", 1, [second]),
    )
    assert regression.status_code == 400
    assert regression.json()["code"] == "video_time_regression"

    epoch_session = _create_session(client)
    assert client.post(
        f"/api/v2/sessions/{epoch_session}/observations",
        json=_batch(
            epoch_session,
            "batch-new-epoch",
            0,
            [_valid_frame(1, 100.0, epoch=1, video_time_ms=100)],
        ),
    ).status_code == 202
    stale = client.post(
        f"/api/v2/sessions/{epoch_session}/observations",
        json=_batch(
            epoch_session,
            "batch-stale-epoch",
            1,
            [_valid_frame(2, 200.0, epoch=0, video_time_ms=200)],
        ),
    )
    assert stale.status_code == 400
    assert stale.json()["code"] == "stale_playback_epoch"


def test_same_frame_snapshot_cannot_change_after_first_ingest(
    v2_client: tuple[TestClient, ManualJobDispatcher],
) -> None:
    client, _ = v2_client
    session_id = _create_session(client)
    first = _frame(
        1,
        100.0,
        frame_id="immutable-frame",
        video_time_ms=100,
        gaze=_gaze(),
        expression=None,
        expression_reason="join_pending",
        attention=_attention(),
    )
    changed = _frame(
        1,
        100.0,
        frame_id="immutable-frame",
        video_time_ms=101,
        gaze=None,
        gaze_reason="join_pending",
        expression=_expression(),
        attention=None,
        attention_reason="join_pending",
    )
    assert client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "batch-frame-first", 0, [first]),
    ).status_code == 202

    response = client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "batch-frame-changed", 1, [changed]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "frame_context_conflict"


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
            self.last_query = ""

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
            self.last_query = query

        def fetchone(self) -> tuple[object, ...]:
            return (10,)

        def fetchall(self) -> list[tuple[object, ...]]:
            if "DISTINCT catalog_version" in self.last_query:
                return [(CATALOG.catalog_version,)]
            return catalog_readiness_rows(CATALOG)

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
    assert "ON CONFLICT (catalog_version, product_id) DO NOTHING" in connection.fake_cursor.queries[0]
    assert "DO UPDATE" not in connection.fake_cursor.queries[0]

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

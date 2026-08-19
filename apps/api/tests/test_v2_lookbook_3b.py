"""Vision 3-B coverage for the one human-approved actual-lookbook AOI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.api.app.v2_aoi import (
    LookbookAoiMetadataV2,
    load_aoi_metadata,
    map_frame_to_aoi,
    validate_aoi_metadata_for_catalog,
)
from apps.api.app.v2_central import DeterministicCentralStub, ManualJobDispatcher
from apps.api.app.v2_evidence import summarize_observations
from apps.api.app.v2_models import FrameObservationV2
from apps.api.app.v2_postgres import load_canonical_catalog
from apps.api.app.v2_store import MemoryStoreRecommendationRepository, V2RecommendationStore


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VIDEO_ID = "mcm-lookbook-v2"
MANIFEST_VERSION = "mcm-lookbook-v2-grid-details-v2-2026-08-19"
PRODUCT_ID = "mcm-toni-medium-disco-visetos"
APPROVED_METADATA_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "lookbooks"
    / VIDEO_ID
    / "aoi-metadata-v2-r3-approved.json"
)
PENDING_METADATA_PATH = (
    REPOSITORY_ROOT / "data" / "lookbooks" / VIDEO_ID / "aoi-metadata-v2.json"
)
APPROVED_METADATA = load_aoi_metadata(APPROVED_METADATA_PATH)
PENDING_METADATA = load_aoi_metadata(PENDING_METADATA_PATH)
CATALOG = load_canonical_catalog(
    REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
)


def _gaze() -> dict[str, object]:
    """Synthetic test signal only; it is never written to a log, DB, or model request."""

    return {
        "screen_x_norm": 0.25,
        "screen_y_norm": 0.25,
        "confidence": 0.9,
        "producer_id": "eye-3b-test",
        "model_revision": "eye-3b-test-v1",
        "calibration_id": "calibration-3b-test",
    }


def _attention(
    *,
    video_x: float | None = 0.25,
    video_y: float | None = 0.25,
    outside_video: bool = False,
    manifest_version: str = MANIFEST_VERSION,
    candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "outside_video": outside_video,
        "confidence": 0.9,
        "producer_id": "kiosk-video-coordinate-3b-test",
        "model_revision": "video-content-rect-3b-test-v1",
        "manifest_version": manifest_version,
        "candidates": candidates or [],
    }
    if not outside_video:
        payload["video_x_norm"] = video_x
        payload["video_y_norm"] = video_y
    return payload


def _frame(
    sequence: int,
    captured_ms: float,
    *,
    frame_id: str | None = None,
    playback_epoch: int = 0,
    video_time_ms: int = 6_000,
    gaze: dict[str, object] | None = None,
    gaze_reason: str | None = None,
    attention: dict[str, object] | None = None,
    attention_reason: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "frame_id": frame_id or f"3b-frame-{sequence}",
        "sequence": sequence,
        "captured_at_mono_ms": captured_ms,
        "session_offset_ms": captured_ms,
        "video_time_ms": video_time_ms,
        "playback_epoch": playback_epoch,
        "gaze": gaze,
        "gaze_reason": None if gaze is not None else gaze_reason,
        "expression": None,
        "expression_reason": "not_observed",
        "attention": attention,
        "attention_reason": None if attention is not None else attention_reason,
        "derived": None,
        "derived_reason": "invalid_or_missing_modality",
    }


def _batch(
    session_id: str,
    batch_id: str,
    batch_sequence: int,
    observations: list[dict[str, object]],
    *,
    video_id: str = VIDEO_ID,
) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "session_id": session_id,
        "video_id": video_id,
        "observations": observations,
    }


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "kiosk_id": "kiosk-3b-test",
            "lookbook_id": VIDEO_ID,
            "consent_version": "consent-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


class CapturingStub(DeterministicCentralStub):
    """Test-only provider: captures only the already-aggregated variant-C request."""

    def __init__(self) -> None:
        self.requests = []

    def recommend(self, request: object) -> object:
        self.requests.append(request)
        return super().recommend(request)  # type: ignore[arg-type]


@pytest.fixture()
def approved_actual_client() -> tuple[TestClient, ManualJobDispatcher, CapturingStub]:
    dispatcher = ManualJobDispatcher()
    model = CapturingStub()
    memory = MemoryStore(REPOSITORY_ROOT)
    repository = MemoryStoreRecommendationRepository(
        memory,
        aoi_metadata_paths={VIDEO_ID: APPROVED_METADATA_PATH},
        # This fixture exercises the older, explicitly approved R3
        # product-AOI path in isolation. Source-AOI approval and matching are
        # covered separately with a test-only approved source fixture.
        source_aoi_enabled=False,
    )
    app = create_app(
        memory,
        central_client=model,
        job_dispatcher=dispatcher,
        v2_store=V2RecommendationStore(repository, input_variant="C"),
    )
    with TestClient(app) as client:
        yield client, dispatcher, model


def _validated_frame(**overrides: object) -> FrameObservationV2:
    values: dict[str, object] = {
        "sequence": 1,
        "captured_ms": 100.0,
        "gaze": _gaze(),
        "attention": _attention(),
    }
    values.update(overrides)
    payload = _frame(**values)
    return FrameObservationV2.model_validate(payload)


def test_r3_approved_metadata_is_one_signed_toni_whole_product() -> None:
    assert PENDING_METADATA.approval_status == "pending_review"
    assert PENDING_METADATA.exposures == []
    assert APPROVED_METADATA.approval_status == "approved"
    assert APPROVED_METADATA.media_identity == PENDING_METADATA.media_identity
    assert len(APPROVED_METADATA.exposures) == 1

    exposure = APPROVED_METADATA.exposures[0]
    assert exposure.aoi_id == "mcm-lookbook-v2-toni-grid-top-left"
    assert exposure.parent_aoi_id is None
    assert exposure.specificity_rank == 0
    assert (exposure.start_ms, exposure.end_ms) == (5_000, 12_000)
    assert exposure.product_id == PRODUCT_ID
    assert exposure.component_code == "whole_product"
    assert set(exposure.observed_visual_tag_ids) == {"monogram", "shopper", "tote"}
    validate_aoi_metadata_for_catalog(
        APPROVED_METADATA,
        CATALOG.products,
        manifest_version=MANIFEST_VERSION,
    )


def test_approved_toni_gaze_reaches_variant_c_evidence_without_frame_data(
    approved_actual_client: tuple[TestClient, ManualJobDispatcher, CapturingStub],
) -> None:
    client, dispatcher, model = approved_actual_client
    session_id = _create_session(client)
    frames = [
        _frame(
            1,
            100.0,
            frame_id="3b-capture-a",
            playback_epoch=2,
            video_time_ms=6_000,
            gaze=_gaze(),
            attention=_attention(video_x=0.25, video_y=0.25),
        ),
        _frame(
            2,
            550.0,
            frame_id="3b-capture-b",
            playback_epoch=2,
            video_time_ms=6_500,
            gaze=_gaze(),
            attention=_attention(video_x=0.25, video_y=0.25),
        ),
    ]
    accepted = client.post(
        f"/api/v2/sessions/{session_id}/observations",
        json=_batch(session_id, "3b-approved-toni", 0, frames),
    )
    assert accepted.status_code == 202, accepted.text

    completion = client.post(f"/api/v2/sessions/{session_id}/complete")
    assert completion.status_code == 202
    assert client.app.state.v2_store.buffered_observation_count(session_id) == 0
    dispatcher.run_next()

    decision = client.get(f"/api/v2/sessions/{session_id}/recommendation")
    assert decision.status_code == 200
    assert decision.json()["status"] == "completed"
    assert decision.json()["selected_product_id"] == PRODUCT_ID
    assert len(model.requests) == 1

    request = model.requests[0]
    assert request.video_id == VIDEO_ID
    assert request.evidence.input_variant == "C"
    assert request.evidence.timeline is None
    assert request.evidence.signal_versions.face is None
    assert request.evidence.signal_versions.face_reason == "no_valid_expression"
    toni = next(item for item in request.evidence.summary if item.product_id == PRODUCT_ID)
    assert toni.gaze is not None
    assert toni.expression is None
    assert toni.expression_reason == "no_matched_expression"
    assert toni.gaze.observed_attention_ms == pytest.approx(450.0)
    assert set(toni.observed_component_codes) == {"whole_product"}
    assert set(toni.observed_visual_tag_ids) == {"monogram", "shopper", "tote"}
    assert request.evidence.evidence_windows is not None
    assert len(request.evidence.evidence_windows) == 1
    window = request.evidence.evidence_windows[0]
    assert window.product_id == PRODUCT_ID
    assert (window.video_start_ms, window.video_end_ms, window.playback_epoch) == (
        6_000,
        6_500,
        2,
    )
    assert set(window.observed_component_codes) == {"whole_product"}
    assert set(window.observed_visual_tag_ids) == {"monogram", "shopper", "tote"}

    payload = request.model_dump_json()
    for forbidden in (
        '"frame_id"',
        '"screen_x_norm"',
        '"screen_y_norm"',
        '"video_x_norm"',
        '"video_y_norm"',
        '"captured_at_mono_ms"',
        '"token"',
    ):
        assert forbidden not in payload


@pytest.mark.parametrize(
    ("frame", "expected_status"),
    [
        (
            _validated_frame(video_time_ms=12_000),
            "no_aoi_match",
        ),
        (
            _validated_frame(attention=_attention(video_x=0.55, video_y=0.25)),
            "no_aoi_match",
        ),
        (
            _validated_frame(attention=_attention(outside_video=True)),
            "outside_video",
        ),
        (
            _validated_frame(
                gaze=None,
                gaze_reason="gaze_unavailable",
                attention=None,
                attention_reason="source_gaze_unavailable",
            ),
            "gaze_unavailable",
        ),
    ],
    ids=("time-outside-approved-interval", "aoi-outside", "letterbox-or-pillarbox", "gaze-unavailable"),
)
def test_r3_direct_mapper_fails_closed_for_unmatched_or_invalid_signal(
    frame: FrameObservationV2,
    expected_status: str,
) -> None:
    assert map_frame_to_aoi(frame, PENDING_METADATA).status == "aoi_metadata_unapproved"
    assert map_frame_to_aoi(frame, APPROVED_METADATA).status == expected_status


def test_r3_approved_backend_returns_no_product_for_outside_aoi_or_time(
    approved_actual_client: tuple[TestClient, ManualJobDispatcher, CapturingStub],
) -> None:
    client, dispatcher, model = approved_actual_client
    for index, frame in enumerate(
        [
            _frame(
                1,
                100.0,
                video_time_ms=6_000,
                gaze=_gaze(),
                attention=_attention(video_x=0.55, video_y=0.25),
            ),
            _frame(
                1,
                100.0,
                video_time_ms=12_000,
                gaze=_gaze(),
                attention=_attention(video_x=0.25, video_y=0.25),
            ),
            _frame(
                1,
                100.0,
                video_time_ms=6_000,
                gaze=_gaze(),
                attention=_attention(outside_video=True),
            ),
        ]
    ):
        session_id = _create_session(client)
        accepted = client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json=_batch(session_id, f"3b-no-match-{index}", 0, [frame]),
        )
        assert accepted.status_code == 202, accepted.text
        assert client.post(f"/api/v2/sessions/{session_id}/complete").status_code == 202
        decision = client.get(f"/api/v2/sessions/{session_id}/recommendation")
        assert decision.status_code == 200
        assert decision.json()["status"] == "insufficient_data"
        assert decision.json()["selected_product_id"] is None
    assert dispatcher.jobs == []
    assert model.requests == []


def test_r3_backend_rejects_context_conflicts_and_client_attribution(
    approved_actual_client: tuple[TestClient, ManualJobDispatcher, CapturingStub],
) -> None:
    client, _, _ = approved_actual_client

    video_session = _create_session(client)
    video_mismatch = client.post(
        f"/api/v2/sessions/{video_session}/observations",
        json=_batch(
            video_session,
            "3b-video-mismatch",
            0,
            [_frame(1, 100.0, gaze=_gaze(), attention=_attention())],
            video_id="mcm-central-ai-replay-v2",
        ),
    )
    assert video_mismatch.status_code == 400
    assert video_mismatch.json()["code"] == "video_mismatch"

    manifest_session = _create_session(client)
    manifest_mismatch = client.post(
        f"/api/v2/sessions/{manifest_session}/observations",
        json=_batch(
            manifest_session,
            "3b-manifest-mismatch",
            0,
            [
                _frame(
                    1,
                    100.0,
                    gaze=_gaze(),
                    attention=_attention(manifest_version="wrong-manifest"),
                )
            ],
        ),
    )
    assert manifest_mismatch.status_code == 400
    assert manifest_mismatch.json()["code"] == "manifest_mismatch"

    epoch_session = _create_session(client)
    assert client.post(
        f"/api/v2/sessions/{epoch_session}/observations",
        json=_batch(
            epoch_session,
            "3b-epoch-current",
            0,
            [
                _frame(
                    1,
                    100.0,
                    playback_epoch=1,
                    gaze=_gaze(),
                    attention=_attention(),
                )
            ],
        ),
    ).status_code == 202
    stale_epoch = client.post(
        f"/api/v2/sessions/{epoch_session}/observations",
        json=_batch(
            epoch_session,
            "3b-epoch-stale",
            1,
            [
                _frame(
                    2,
                    200.0,
                    playback_epoch=0,
                    gaze=_gaze(),
                    attention=_attention(),
                )
            ],
        ),
    )
    assert stale_epoch.status_code == 400
    assert stale_epoch.json()["code"] == "stale_playback_epoch"

    frame_session = _create_session(client)
    first = _frame(
        1,
        100.0,
        frame_id="3b-immutable-frame",
        video_time_ms=6_000,
        gaze=_gaze(),
        attention=_attention(),
    )
    assert client.post(
        f"/api/v2/sessions/{frame_session}/observations",
        json=_batch(frame_session, "3b-frame-first", 0, [first]),
    ).status_code == 202
    frame_conflict = client.post(
        f"/api/v2/sessions/{frame_session}/observations",
        json=_batch(
            frame_session,
            "3b-frame-conflict",
            1,
            [
                _frame(
                    1,
                    100.0,
                    frame_id="3b-immutable-frame",
                    video_time_ms=6_001,
                    gaze=_gaze(),
                    attention=_attention(),
                )
            ],
        ),
    )
    assert frame_conflict.status_code == 400
    assert frame_conflict.json()["code"] == "frame_context_conflict"

    sequence_session = _create_session(client)
    assert client.post(
        f"/api/v2/sessions/{sequence_session}/observations",
        json=_batch(
            sequence_session,
            "3b-sequence-first",
            0,
            [_frame(1, 100.0, gaze=_gaze(), attention=_attention())],
        ),
    ).status_code == 202
    sequence_conflict = client.post(
        f"/api/v2/sessions/{sequence_session}/observations",
        json=_batch(
            sequence_session,
            "3b-sequence-conflict",
            1,
            [
                _frame(
                    1,
                    200.0,
                    frame_id="3b-different-frame",
                    gaze=_gaze(),
                    attention=_attention(),
                )
            ],
        ),
    )
    assert sequence_conflict.status_code == 400
    assert sequence_conflict.json()["code"] == "observation_sequence_conflict"

    candidate_session = _create_session(client)
    forbidden_candidate = client.post(
        f"/api/v2/sessions/{candidate_session}/observations",
        json=_batch(
            candidate_session,
            "3b-client-candidate",
            0,
            [
                _frame(
                    1,
                    100.0,
                    gaze=_gaze(),
                    attention=_attention(
                        candidates=[
                            {
                                "exposure_id": "unapproved-client-candidate",
                                "product_id": "mcm-ella-small-disco-visetos",
                                "priority": 0,
                            }
                        ]
                    ),
                )
            ],
        ),
    )
    assert forbidden_candidate.status_code == 400
    assert forbidden_candidate.json()["code"] == "client_product_attribution_forbidden"

    gaze_session = _create_session(client)
    gaze_mismatch = client.post(
        f"/api/v2/sessions/{gaze_session}/observations",
        json=_batch(
            gaze_session,
            "3b-gaze-unavailable",
            0,
            [
                _frame(
                    1,
                    100.0,
                    gaze=None,
                    gaze_reason="gaze_unavailable",
                    attention=_attention(),
                )
            ],
        ),
    )
    assert gaze_mismatch.status_code == 400
    assert gaze_mismatch.json()["code"] == "gaze_attention_mismatch"


def test_r3_ambiguous_product_frame_never_becomes_evidence() -> None:
    payload = APPROVED_METADATA.model_dump(mode="json")
    payload["metadata_revision"] = "mcm-lookbook-v2-aoi-r3-ambiguous-test"
    payload["exposures"].append(
        {
            "aoi_id": "mcm-lookbook-v2-r3-overlapping-ella",
            "parent_aoi_id": None,
            "specificity_rank": 0,
            "start_ms": 5_000,
            "end_ms": 12_000,
            "shape": {
                "type": "polygon",
                "points": [[0.08, 0.02], [0.42, 0.02], [0.42, 0.49], [0.08, 0.49]],
            },
            "product_id": "mcm-ella-small-disco-visetos",
            "component_code": "whole_product",
            "observed_visual_tag_ids": ["boston", "monogram"],
        }
    )
    ambiguous_metadata = LookbookAoiMetadataV2.model_validate(payload)
    validate_aoi_metadata_for_catalog(
        ambiguous_metadata,
        CATALOG.products,
        manifest_version=MANIFEST_VERSION,
    )
    frame = _validated_frame(video_time_ms=6_000)
    assert map_frame_to_aoi(frame, ambiguous_metadata).status == "ambiguous_product"
    evidence = summarize_observations(
        [frame],
        decision_request_id="3b-ambiguous-decision",
        session_id="3b-ambiguous-session",
        video_id=VIDEO_ID,
        manifest_version=MANIFEST_VERSION,
        catalog_version=CATALOG.catalog_version,
        aoi_metadata=ambiguous_metadata,
        product_ids=[product.product_id for product in CATALOG.products],
        input_variant="C",
    )
    assert evidence.eligible_product_ids == frozenset()
    assert evidence.ambiguous_attention_count == 1
    assert all(item.gaze is None for item in evidence.evidence.summary)

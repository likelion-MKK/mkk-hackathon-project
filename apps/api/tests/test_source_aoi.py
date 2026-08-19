from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.schemas import LookbookManifest
from apps.api.app.source_aoi import (
    SourceAoiMetadataV1,
    bind_source_aois,
    build_source_visual_evidence,
    load_product_matching_catalog,
    product_feature_match_score,
    resolve_source_aoi_hits,
)
from apps.api.app.v2_models import FrameObservationV2
from apps.api.app.v2_central import (
    DeterministicCentralStub,
    ManualJobDispatcher,
    _instructions_for_request,
    _openai_output_schema,
)
from apps.api.app.v2_models import CentralRecommendationRequestV2
from apps.api.app.v2_store import (
    MemoryStoreRecommendationRepository,
    V2RecommendationStore,
)
from apps.api.app.store import MemoryStore


ROOT = Path(__file__).resolve().parents[3]
LOOKBOOK_DIR = ROOT / "data" / "lookbooks" / "mcm-lookbook-v2"
MANIFEST = LookbookManifest.model_validate(
    json.loads((LOOKBOOK_DIR / "manifest.json").read_text(encoding="utf-8"))
)
SOURCE_METADATA = SourceAoiMetadataV1.model_validate(
    json.loads(
        (LOOKBOOK_DIR / "source-aoi-metadata-v1.json").read_text(encoding="utf-8")
    )
)
BINDINGS = bind_source_aois(MANIFEST, SOURCE_METADATA)


def _frame(
    sequence: int,
    video_time_ms: int,
    video_x_norm: float,
    video_y_norm: float,
    *,
    playback_epoch: int = 0,
) -> FrameObservationV2:
    return FrameObservationV2.model_validate(
        {
            "schema_version": "2.0",
            "frame_id": f"frame-source-{sequence:04d}",
            "sequence": sequence,
            "captured_at_mono_ms": float(sequence * 250),
            "session_offset_ms": float(sequence * 250),
            "video_time_ms": video_time_ms,
            "playback_epoch": playback_epoch,
            "gaze": {
                "screen_x_norm": video_x_norm,
                "screen_y_norm": video_y_norm,
                "confidence": 1.0,
                "producer_id": "eye-source-test",
                "model_revision": "eye-source-test-v1",
                "calibration_id": "calibration-source-test",
            },
            "gaze_reason": None,
            "expression": None,
            "expression_reason": "not_observed",
            "attention": {
                "outside_video": False,
                "video_x_norm": video_x_norm,
                "video_y_norm": video_y_norm,
                "confidence": 1.0,
                "producer_id": "kiosk-video-coordinate-v1",
                "model_revision": "video-content-rect-v1",
                "manifest_version": MANIFEST.manifest_version,
                "candidates": [],
            },
            "attention_reason": None,
            "derived": None,
            "derived_reason": "invalid_or_missing_modality",
        }
    )


def test_canonical_source_aoi_records_explicit_demo_approval() -> None:
    assert MANIFEST.video_id == SOURCE_METADATA.video_id == "mcm-lookbook-v2"
    assert MANIFEST.manifest_version == SOURCE_METADATA.manifest_version
    assert MANIFEST.coordinate_space == "video_normalized"
    assert len(MANIFEST.exposures) == 86
    assert len(SOURCE_METADATA.source_aois) == 10
    assert SOURCE_METADATA.approval.status == "approved"
    assert SOURCE_METADATA.approval.approved_by == "andyw-explicit-demo-approval"
    assert SOURCE_METADATA.approval.approved_at == "2026-08-19T20:41:27+09:00"
    assert len(BINDINGS) == len(MANIFEST.exposures)


@pytest.mark.parametrize(
    ("video_time_ms", "x", "y", "expected_source"),
    [
        (9_000, 0.25, 0.35, "source-scene-01-toni-cognac-top"),
        (17_000, 0.20, 0.35, "source-scene-02-boston-top-left"),
        (21_200, 0.18, 0.72, "source-scene-03-toni-brown"),
        (21_700, 0.68, 0.72, "source-scene-03-toni-black"),
    ],
)
def test_backend_resolves_representative_source_hits_from_capture_video_time(
    video_time_ms: int,
    x: float,
    y: float,
    expected_source: str,
) -> None:
    hits = resolve_source_aoi_hits(_frame(1, video_time_ms, x, y), BINDINGS)

    assert [hit.source_aoi_id for hit in hits] == [expected_source]


@pytest.mark.parametrize(
    ("video_time_ms", "x", "y"),
    [
        (0, 0.25, 0.35),
        (4_999, 0.25, 0.35),
        (9_000, 0.50, 0.50),
        (17_000, 0.50, 0.50),
        (21_200, 0.50, 0.50),
        (29_400, 0.18, 0.72),
        (33_499, 0.18, 0.72),
    ],
)
def test_intentional_no_aoi_ranges_and_polygon_outside_do_not_match(
    video_time_ms: int,
    x: float,
    y: float,
) -> None:
    assert resolve_source_aoi_hits(_frame(2, video_time_ms, x, y), BINDINGS) == ()


def test_scene_and_fast_cut_intervals_are_half_open() -> None:
    before_scene_change = resolve_source_aoi_hits(
        _frame(3, 12_999, 0.20, 0.35),
        BINDINGS,
    )
    after_scene_change = resolve_source_aoi_hits(
        _frame(4, 13_000, 0.20, 0.35),
        BINDINGS,
    )
    before_fast_cut = resolve_source_aoi_hits(
        _frame(5, 21_499, 0.18, 0.72),
        BINDINGS,
    )
    after_fast_cut = resolve_source_aoi_hits(
        _frame(6, 21_500, 0.68, 0.72),
        BINDINGS,
    )

    assert before_scene_change[0].source_aoi_id == (
        "source-scene-01-toni-cognac-top"
    )
    assert after_scene_change[0].source_aoi_id == (
        "source-scene-02-boston-top-left"
    )
    assert before_fast_cut[0].source_aoi_id == "source-scene-03-toni-brown"
    assert after_fast_cut[0].source_aoi_id == "source-scene-03-toni-black"


def test_manifest_version_mismatch_fails_before_any_hit_test() -> None:
    mismatched = SOURCE_METADATA.model_copy(
        update={"manifest_version": "different-manifest"}
    )
    with pytest.raises(ValueError, match="does not match"):
        bind_source_aois(MANIFEST, mismatched)


def test_source_features_are_compared_to_all_ten_catalog_products() -> None:
    frames = (
        _frame(10, 9_000, 0.25, 0.35),
        _frame(11, 9_250, 0.25, 0.35),
        _frame(12, 9_500, 0.25, 0.35),
    )
    resolved = {
        (frame.playback_epoch, frame.frame_id): resolve_source_aoi_hits(
            frame,
            BINDINGS,
        )
        for frame in frames
    }
    evidence = build_source_visual_evidence(
        frames,
        resolved,
        SOURCE_METADATA,
    )
    assert evidence is not None
    catalog = load_product_matching_catalog(ROOT)
    ranked = sorted(
        (
            product_feature_match_score(product, evidence)[0],
            product.product_id,
        )
        for product in catalog.products
    )

    assert len(ranked) == 10
    assert ranked[-1][0] > 0
    assert evidence.source_aois[0].visual_features.color_primary == "cognac"
    assert evidence.source_aois[0].visual_features.silhouette == "shopper"


def test_approved_source_path_reaches_test_stub_without_client_product_authority(
    tmp_path: Path,
) -> None:
    payload = SOURCE_METADATA.model_dump(mode="json")
    approved_path = tmp_path / "approved-source-aoi.json"
    approved_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class CapturingStub(DeterministicCentralStub):
        request: CentralRecommendationRequestV2 | None = None

        def recommend(self, request: CentralRecommendationRequestV2) -> object:
            self.request = request
            return super().recommend(request)

    memory = MemoryStore(ROOT)
    repository = MemoryStoreRecommendationRepository(
        memory,
        source_aoi_metadata_paths={"mcm-lookbook-v2": approved_path},
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
        created = client.post(
            "/api/v1/sessions",
            json={
                "kiosk_id": "source-aoi-test-kiosk",
                "lookbook_id": "mcm-lookbook-v2",
                "consent_version": "source-aoi-test-consent",
            },
        )
        assert created.status_code == 201
        session_id = created.json()["session_id"]
        frames = [
            _frame(20, 9_000, 0.25, 0.35),
            _frame(21, 9_250, 0.25, 0.35),
            _frame(22, 9_500, 0.25, 0.35),
        ]
        accepted = client.post(
            f"/api/v2/sessions/{session_id}/observations",
            json={
                "schema_version": "2.0",
                "batch_id": "source-aoi-approved-batch",
                "batch_sequence": 0,
                "session_id": session_id,
                "video_id": "mcm-lookbook-v2",
                "observations": [
                    frame.model_dump(mode="json") for frame in frames
                ],
            },
        )
        assert accepted.status_code == 202, accepted.text
        completing = client.post(f"/api/v2/sessions/{session_id}/complete")
        assert completing.status_code == 202, completing.text
        dispatcher.run_next()
        decision = client.get(
            f"/api/v2/sessions/{session_id}/recommendation"
        )

    assert decision.status_code == 200
    assert decision.json()["status"] == "completed"
    assert model.request is not None
    assert model.request.source_visual_evidence is not None
    assert model.request.matching_products is not None
    assert len(model.request.matching_products) == 10
    assert model.request.evidence.timeline is not None
    schema = _openai_output_schema(model.request)
    evidence_schema = schema["properties"]["evidence"]["items"]["properties"]
    assert evidence_schema["code"]["enum"] == [
        "observed_attention",
        "return_candidate",
        "gaze_movement",
        "product_tag_match",
        "data_quality",
    ]
    assert evidence_schema["evidence_refs"]["items"]["properties"]["kind"]["enum"] == [
        "frame"
    ]
    assert "승인된 source AOI 경로" in _instructions_for_request(model.request)
    assert all(
        frame.attention is None or frame.attention.candidates == []
        for frame in model.request.evidence.timeline
    )

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from apps.api.app.v2_aoi import (
    LookbookAoiMetadataV2,
    MediaIdentityV2,
    load_aoi_metadata,
    map_frame_to_aoi,
    probe_mp4_media,
    validate_aoi_metadata_for_catalog,
    verify_media_file,
)
from apps.api.app.v2_models import FrameObservationV2
from apps.api.app.v2_postgres import load_canonical_catalog


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VIDEO_ID = "mcm-central-ai-replay-v2"
PRODUCT_1 = "mcm-toni-medium-disco-visetos"
PRODUCT_2 = "mcm-pina-vanity-case-studded-calfskin"
APPROVED_METADATA = load_aoi_metadata(
    REPOSITORY_ROOT / "data" / "lookbooks" / VIDEO_ID / "aoi-metadata-v2.json"
)
PENDING_METADATA = load_aoi_metadata(
    REPOSITORY_ROOT
    / "data"
    / "lookbooks"
    / "mcm-lookbook-v2"
    / "aoi-metadata-v2.json"
)
CATALOG = load_canonical_catalog(
    REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
)


def _mp4_box(kind: bytes, payload: bytes) -> bytes:
    return pack(">I4s", len(payload) + 8, kind) + payload


def _minimal_video_mp4(
    *,
    duration_ms: int = 33_500,
    width_px: int = 1_280,
    height_px: int = 720,
    fps: int = 24,
) -> bytes:
    """Small ISO BMFF fixture containing the boxes our readiness probe needs."""

    frame_count = duration_ms * fps // 1_000
    if frame_count * 1_000 != duration_ms * fps:
        raise ValueError("fixture duration must align to its FPS")

    mvhd = bytearray(20)
    pack_into(">I", mvhd, 12, 1_000)
    pack_into(">I", mvhd, 16, duration_ms)

    tkhd = bytearray(84)
    pack_into(">I", tkhd, 76, width_px << 16)
    pack_into(">I", tkhd, 80, height_px << 16)

    hdlr = bytearray(12)
    hdlr[8:12] = b"vide"

    mdhd = bytearray(24)
    pack_into(">I", mdhd, 12, fps)
    pack_into(">I", mdhd, 16, frame_count)

    stts = bytearray(16)
    pack_into(">I", stts, 4, 1)
    pack_into(">I", stts, 8, frame_count)
    pack_into(">I", stts, 12, 1)

    stbl = _mp4_box(b"stbl", _mp4_box(b"stts", bytes(stts)))
    minf = _mp4_box(b"minf", stbl)
    mdia = _mp4_box(
        b"mdia",
        _mp4_box(b"hdlr", bytes(hdlr))
        + _mp4_box(b"mdhd", bytes(mdhd))
        + minf,
    )
    trak = _mp4_box(b"trak", _mp4_box(b"tkhd", bytes(tkhd)) + mdia)
    return _mp4_box(b"ftyp", b"isom\x00\x00\x02\x00isom") + _mp4_box(
        b"moov", _mp4_box(b"mvhd", bytes(mvhd)) + trak
    )


def _frame(
    *,
    video_time_ms: int = 1_000,
    video_x: float | None = 0.25,
    video_y: float | None = 0.5,
    outside_video: bool = False,
    valid_gaze: bool = True,
) -> FrameObservationV2:
    gaze = (
        {
            "screen_x_norm": 0.25,
            "screen_y_norm": 0.5,
            "confidence": 0.9,
            "producer_id": "eye-test",
            "model_revision": "eye-v1",
            "calibration_id": "calibration-test",
        }
        if valid_gaze
        else None
    )
    attention = None
    if valid_gaze:
        attention = {
            "outside_video": outside_video,
            "confidence": 0.9,
            "producer_id": "kiosk-video-coordinate-v1",
            "model_revision": "video-content-rect-v1",
            "manifest_version": APPROVED_METADATA.manifest_version,
            "candidates": [],
        }
        if not outside_video:
            attention["video_x_norm"] = video_x
            attention["video_y_norm"] = video_y
    return FrameObservationV2.model_validate(
        {
            "schema_version": "2.0",
            "frame_id": "frame-aoi-0001",
            "sequence": 1,
            "captured_at_mono_ms": 100.0,
            "session_offset_ms": 100.0,
            "video_time_ms": video_time_ms,
            "playback_epoch": 0,
            "gaze": gaze,
            "gaze_reason": None if valid_gaze else "gaze_unavailable",
            "expression": None,
            "expression_reason": "not_observed",
            "attention": attention,
            "attention_reason": None if valid_gaze else "source_gaze_unavailable",
            "derived": None,
            "derived_reason": "invalid_or_missing_modality",
        }
    )


def _metadata_with_exposures(exposures: list[dict[str, object]]) -> LookbookAoiMetadataV2:
    payload = APPROVED_METADATA.model_dump(mode="json")
    payload["metadata_revision"] = "aoi-unit-test-v1"
    payload["exposures"] = exposures
    return LookbookAoiMetadataV2.model_validate(payload)


def test_approved_aoi_maps_only_from_video_time_and_video_coordinates() -> None:
    result = map_frame_to_aoi(_frame(), APPROVED_METADATA)

    assert result.status == "matched"
    assert result.product_id == PRODUCT_1
    assert result.aoi_ids == ("replay-scene-01-toni",)
    assert result.component_codes == ("whole_product",)
    assert result.observed_visual_tag_ids == ("monogram", "shopper")


@pytest.mark.parametrize(
    ("video_x", "video_y"),
    [(None, 0.5), (0.25, None)],
    ids=("missing-x", "missing-y"),
)
def test_in_video_attention_rejects_partial_coordinates(
    video_x: float | None,
    video_y: float | None,
) -> None:
    with pytest.raises(ValidationError, match="in-video attention requires"):
        _frame(video_x=video_x, video_y=video_y)


def test_pending_outside_invalid_and_out_of_range_inputs_fail_closed() -> None:
    assert map_frame_to_aoi(_frame(), PENDING_METADATA).status == "aoi_metadata_unapproved"
    assert (
        map_frame_to_aoi(_frame(outside_video=True), APPROVED_METADATA).status
        == "outside_video"
    )
    assert (
        map_frame_to_aoi(_frame(valid_gaze=False), APPROVED_METADATA).status
        == "gaze_unavailable"
    )
    assert (
        map_frame_to_aoi(_frame(video_time_ms=60_000), APPROVED_METADATA).status
        == "video_time_out_of_range"
    )


def test_actual_video_identity_remains_bound_to_the_inspected_file() -> None:
    assert PENDING_METADATA.video_id == "mcm-lookbook-v2"
    assert PENDING_METADATA.media_identity.model_dump() == {
        "source_kind": "video_file",
        "sha256": "dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89",
        "byte_length": 5_754_164,
        "duration_ms": 33_500,
        "width_px": 1_280,
        "height_px": 720,
        "fps": 24.0,
    }


def test_same_product_overlap_preserves_all_aoi_but_other_product_is_ambiguous() -> None:
    root = APPROVED_METADATA.exposures[0].model_dump(mode="json")
    child = {
        "aoi_id": "toni-handle",
        "parent_aoi_id": root["aoi_id"],
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
    same_product = _metadata_with_exposures([root, child])

    same_result = map_frame_to_aoi(_frame(), same_product)

    assert same_result.status == "matched"
    assert same_result.aoi_ids == ("replay-scene-01-toni", "toni-handle")
    assert same_result.component_codes == ("handle", "whole_product")

    other_product = {
        **root,
        "aoi_id": "pina-vanity-overlap",
        "product_id": PRODUCT_2,
        "observed_visual_tag_ids": ["leather", "shoulder"],
    }
    ambiguous = _metadata_with_exposures([root, other_product])
    assert map_frame_to_aoi(_frame(), ambiguous).status == "ambiguous_product"


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_id",
        "unknown_parent",
        "cross_product_parent",
        "child_rank_not_greater",
        "unknown_component",
    ],
)
def test_invalid_aoi_hierarchy_rejects_the_entire_revision(mutation: str) -> None:
    root = APPROVED_METADATA.exposures[0].model_dump(mode="json")
    child = {
        **root,
        "aoi_id": "child-aoi",
        "parent_aoi_id": root["aoi_id"],
        "specificity_rank": 1,
    }
    if mutation == "duplicate_id":
        child["aoi_id"] = root["aoi_id"]
    elif mutation == "unknown_parent":
        child["parent_aoi_id"] = "missing-parent"
    elif mutation == "cross_product_parent":
        child["product_id"] = PRODUCT_2
        child["observed_visual_tag_ids"] = ["leather", "shoulder"]
    elif mutation == "child_rank_not_greater":
        child["specificity_rank"] = 0
    elif mutation == "unknown_component":
        child["component_code"] = "invented_component"

    with pytest.raises(ValidationError):
        _metadata_with_exposures([root, child])


def test_unknown_catalog_product_or_visual_tag_rejects_metadata() -> None:
    unknown_product = APPROVED_METADATA.model_copy(deep=True)
    unknown_product.exposures[0].product_id = "unknown-product"
    with pytest.raises(RuntimeError, match="outside the canonical catalog"):
        validate_aoi_metadata_for_catalog(
            unknown_product,
            CATALOG.products,
            manifest_version=unknown_product.manifest_version,
        )

    unknown_tag = APPROVED_METADATA.model_copy(deep=True)
    unknown_tag.exposures[0].observed_visual_tag_ids = ["not-a-catalog-tag"]
    with pytest.raises(RuntimeError, match="outside the product profile"):
        validate_aoi_metadata_for_catalog(
            unknown_tag,
            CATALOG.products,
            manifest_version=unknown_tag.manifest_version,
        )


def test_media_readiness_requires_exact_file_and_stream_metadata() -> None:
    with TemporaryDirectory(prefix="mcm-aoi-test-") as temp_directory:
        media = Path(temp_directory) / "lookbook.mp4"
        content = _minimal_video_mp4()
        media.write_bytes(content)
        identity = MediaIdentityV2(
            source_kind="video_file",
            sha256=sha256(content).hexdigest(),
            byte_length=len(content),
            duration_ms=33_500,
            width_px=1_280,
            height_px=720,
            fps=24,
        )

        verify_media_file(media, identity)
        probe = probe_mp4_media(media)
        assert probe.duration_ms == 33_500
        assert (probe.width_px, probe.height_px) == (1_280, 720)
        assert probe.fps == pytest.approx(24.0)

        wrong_fps = identity.model_copy(update={"fps": 30})
        with pytest.raises(RuntimeError, match="duration, resolution or FPS"):
            verify_media_file(media, wrong_fps)

        media.write_bytes(content + b"changed")
        with pytest.raises(RuntimeError, match="byte length"):
            verify_media_file(media, identity)

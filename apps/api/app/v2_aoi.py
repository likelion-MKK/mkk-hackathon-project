"""Approved lookbook AOI validation, media identity checks and fail-closed mapping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from struct import unpack_from
from typing import Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from apps.api.app.schemas import IDENTIFIER_PATTERN, ContractModel, Identifier, Revision
from apps.api.app.v2_models import (
    AttentionCandidateV2,
    ComponentCodeV2,
    ControlledTag,
    FrameObservationV2,
    ProductRecommendationItemV2,
)


ApprovalStatusV2 = Literal["pending_review", "approved"]
MediaSourceKindV2 = Literal["video_file", "synthetic_fixture"]
MappingStatusV2 = Literal[
    "matched",
    "aoi_metadata_unapproved",
    "gaze_unavailable",
    "video_point_unavailable",
    "outside_video",
    "video_time_out_of_range",
    "no_aoi_match",
    "ambiguous_product",
]


class MediaIdentityV2(ContractModel):
    source_kind: MediaSourceKindV2
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_length: StrictInt = Field(ge=1)
    duration_ms: StrictInt = Field(ge=1)
    width_px: StrictInt = Field(ge=1)
    height_px: StrictInt = Field(ge=1)
    fps: float = Field(gt=0)


class AoiShapeV2(ContractModel):
    type: Literal["polygon"]
    points: list[tuple[float, float]] = Field(min_length=3, max_length=64)

    @field_validator("points")
    @classmethod
    def polygon_is_normalized_and_non_degenerate(
        cls, value: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        for x, y in value:
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise ValueError("AOI polygon points must be normalized to 0..1")
        twice_area = abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(value, value[1:] + value[:1])
            )
        )
        if twice_area <= 1e-12:
            raise ValueError("AOI polygon must have a non-zero area")
        return value


class AoiExposureV2(ContractModel):
    aoi_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    parent_aoi_id: Identifier | None = Field(
        default=None, min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN
    )
    specificity_rank: StrictInt = Field(ge=0, le=32)
    start_ms: StrictInt = Field(ge=0)
    end_ms: StrictInt = Field(ge=1)
    shape: AoiShapeV2
    product_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    component_code: ComponentCodeV2
    observed_visual_tag_ids: list[ControlledTag] = Field(min_length=1, max_length=32)

    @field_validator("observed_visual_tag_ids")
    @classmethod
    def visual_tags_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("observed_visual_tag_ids values must be unique")
        return value

    @model_validator(mode="after")
    def time_range_is_forward(self) -> Self:
        if self.start_ms >= self.end_ms:
            raise ValueError("AOI start_ms must be less than end_ms")
        return self


class LookbookAoiMetadataV2(ContractModel):
    schema_version: Literal["2.0"]
    video_id: Identifier = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    manifest_version: Revision = Field(min_length=1, max_length=128)
    metadata_revision: Revision = Field(min_length=1, max_length=128)
    approval_status: ApprovalStatusV2
    coordinate_space: Literal["video_normalized"]
    component_taxonomy_version: Revision = Field(min_length=1, max_length=128)
    media_identity: MediaIdentityV2
    exposures: list[AoiExposureV2] = Field(max_length=512)

    @model_validator(mode="after")
    def validate_approval_and_hierarchy(self) -> Self:
        if self.approval_status == "pending_review" and self.exposures:
            raise ValueError("pending AOI metadata cannot contain unreviewed exposures")
        if self.approval_status == "approved" and not self.exposures:
            raise ValueError("approved AOI metadata requires at least one exposure")

        by_id = {exposure.aoi_id: exposure for exposure in self.exposures}
        if len(by_id) != len(self.exposures):
            raise ValueError("aoi_id values must be unique")
        for exposure in self.exposures:
            if exposure.end_ms > self.media_identity.duration_ms:
                raise ValueError("AOI time range exceeds the canonical media duration")
            if exposure.parent_aoi_id is None:
                if exposure.specificity_rank != 0:
                    raise ValueError("root AOI specificity_rank must be zero")
                continue
            parent = by_id.get(exposure.parent_aoi_id)
            if parent is None:
                raise ValueError("parent_aoi_id must reference an AOI in the same revision")
            if parent.product_id != exposure.product_id:
                raise ValueError("parent and child AOIs must reference the same product")
            if parent.specificity_rank >= exposure.specificity_rank:
                raise ValueError("child AOI specificity_rank must be greater than its parent")
            if parent.start_ms > exposure.start_ms or parent.end_ms < exposure.end_ms:
                raise ValueError("parent AOI time range must contain the child range")

        for exposure in self.exposures:
            seen: set[str] = set()
            current = exposure
            while current.parent_aoi_id is not None:
                if current.aoi_id in seen:
                    raise ValueError("AOI parent hierarchy cannot contain a cycle")
                seen.add(current.aoi_id)
                current = by_id[current.parent_aoi_id]
        return self


@dataclass(frozen=True, slots=True)
class AoiMappingResultV2:
    status: MappingStatusV2
    product_id: str | None = None
    aoi_ids: tuple[str, ...] = ()
    component_codes: tuple[ComponentCodeV2, ...] = ()
    observed_visual_tag_ids: tuple[ControlledTag, ...] = ()
    candidates: tuple[AttentionCandidateV2, ...] = ()

    @property
    def matched(self) -> bool:
        return self.status == "matched"


@dataclass(frozen=True, slots=True)
class MediaProbeV2:
    """Container metadata read from the canonical MP4 without decoding frames."""

    duration_ms: int
    width_px: int
    height_px: int
    fps: float


@dataclass(frozen=True, slots=True)
class _Mp4Box:
    kind: bytes
    payload_start: int
    end: int


def _mp4_error() -> RuntimeError:
    return RuntimeError("canonical lookbook media stream metadata is unavailable")


def _mp4_boxes(payload: bytes, start: int, end: int) -> list[_Mp4Box]:
    """Read a bounded ISO BMFF box list, rejecting malformed atom lengths."""

    boxes: list[_Mp4Box] = []
    offset = start
    while offset < end:
        if end - offset < 8:
            raise _mp4_error()
        size = unpack_from(">I", payload, offset)[0]
        kind = payload[offset + 4 : offset + 8]
        header_size = 8
        if size == 1:
            if end - offset < 16:
                raise _mp4_error()
            size = unpack_from(">Q", payload, offset + 8)[0]
            header_size = 16
        elif size == 0:
            size = end - offset

        box_end = offset + size
        if size < header_size or box_end > end:
            raise _mp4_error()
        boxes.append(_Mp4Box(kind=kind, payload_start=offset + header_size, end=box_end))
        offset = box_end
    if offset != end:
        raise _mp4_error()
    return boxes


def _mp4_child(payload: bytes, parent: _Mp4Box, kind: bytes) -> _Mp4Box | None:
    return next(
        (box for box in _mp4_boxes(payload, parent.payload_start, parent.end) if box.kind == kind),
        None,
    )


def _mp4_children(payload: bytes, parent: _Mp4Box, kind: bytes) -> list[_Mp4Box]:
    return [box for box in _mp4_boxes(payload, parent.payload_start, parent.end) if box.kind == kind]


def _u32(payload: bytes, offset: int, end: int) -> int:
    if offset < 0 or end - offset < 4:
        raise _mp4_error()
    return unpack_from(">I", payload, offset)[0]


def _u64(payload: bytes, offset: int, end: int) -> int:
    if offset < 0 or end - offset < 8:
        raise _mp4_error()
    return unpack_from(">Q", payload, offset)[0]


def _duration_from_mvhd(payload: bytes, box: _Mp4Box) -> tuple[int, int]:
    if box.payload_start >= box.end:
        raise _mp4_error()
    version = payload[box.payload_start]
    if version == 0:
        time_scale = _u32(payload, box.payload_start + 12, box.end)
        duration = _u32(payload, box.payload_start + 16, box.end)
    elif version == 1:
        time_scale = _u32(payload, box.payload_start + 20, box.end)
        duration = _u64(payload, box.payload_start + 24, box.end)
    else:
        raise _mp4_error()
    if time_scale <= 0 or duration <= 0:
        raise _mp4_error()
    return time_scale, duration


def _duration_from_mdhd(payload: bytes, box: _Mp4Box) -> tuple[int, int]:
    if box.payload_start >= box.end:
        raise _mp4_error()
    version = payload[box.payload_start]
    if version == 0:
        time_scale = _u32(payload, box.payload_start + 12, box.end)
        duration = _u32(payload, box.payload_start + 16, box.end)
    elif version == 1:
        time_scale = _u32(payload, box.payload_start + 20, box.end)
        duration = _u64(payload, box.payload_start + 24, box.end)
    else:
        raise _mp4_error()
    if time_scale <= 0 or duration <= 0:
        raise _mp4_error()
    return time_scale, duration


def _video_dimensions_from_tkhd(payload: bytes, box: _Mp4Box) -> tuple[int, int]:
    if box.payload_start >= box.end:
        raise _mp4_error()
    version = payload[box.payload_start]
    if version == 0:
        width_offset = box.payload_start + 76
        height_offset = box.payload_start + 80
    elif version == 1:
        width_offset = box.payload_start + 88
        height_offset = box.payload_start + 92
    else:
        raise _mp4_error()
    width = _u32(payload, width_offset, box.end) / 65_536
    height = _u32(payload, height_offset, box.end) / 65_536
    if width <= 0 or height <= 0:
        raise _mp4_error()
    return round(width), round(height)


def _is_video_handler(payload: bytes, box: _Mp4Box) -> bool:
    return box.end - box.payload_start >= 12 and payload[
        box.payload_start + 8 : box.payload_start + 12
    ] == b"vide"


def _fps_from_stts(payload: bytes, box: _Mp4Box, time_scale: int) -> float:
    entry_count = _u32(payload, box.payload_start + 4, box.end)
    offset = box.payload_start + 8
    total_samples = 0
    total_ticks = 0
    for _ in range(entry_count):
        sample_count = _u32(payload, offset, box.end)
        sample_delta = _u32(payload, offset + 4, box.end)
        offset += 8
        if sample_count <= 0 or sample_delta <= 0:
            raise _mp4_error()
        total_samples += sample_count
        total_ticks += sample_count * sample_delta
    if total_samples <= 0 or total_ticks <= 0 or time_scale <= 0:
        raise _mp4_error()
    return total_samples * time_scale / total_ticks


def probe_mp4_media(path: Path) -> MediaProbeV2:
    """Read duration, dimensions and average FPS from a normal ISO BMFF MP4.

    This deliberately avoids a platform-specific `ffprobe` dependency: media
    readiness has to work in the API image as well as on a Windows developer
    machine. The canonical file is size-bounded before it is read by
    ``verify_media_file``.
    """

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise _mp4_error() from exc

    roots = _mp4_boxes(payload, 0, len(payload))
    moov = next((box for box in roots if box.kind == b"moov"), None)
    if moov is None:
        raise _mp4_error()
    mvhd = _mp4_child(payload, moov, b"mvhd")
    if mvhd is None:
        raise _mp4_error()
    movie_time_scale, movie_duration = _duration_from_mvhd(payload, mvhd)

    candidates: list[tuple[int, int, int, float]] = []
    for track in _mp4_children(payload, moov, b"trak"):
        tkhd = _mp4_child(payload, track, b"tkhd")
        mdia = _mp4_child(payload, track, b"mdia")
        if tkhd is None or mdia is None:
            continue
        hdlr = _mp4_child(payload, mdia, b"hdlr")
        mdhd = _mp4_child(payload, mdia, b"mdhd")
        minf = _mp4_child(payload, mdia, b"minf")
        stbl = _mp4_child(payload, minf, b"stbl") if minf is not None else None
        stts = _mp4_child(payload, stbl, b"stts") if stbl is not None else None
        if hdlr is None or mdhd is None or stts is None or not _is_video_handler(payload, hdlr):
            continue
        width, height = _video_dimensions_from_tkhd(payload, tkhd)
        track_time_scale, track_duration = _duration_from_mdhd(payload, mdhd)
        fps = _fps_from_stts(payload, stts, track_time_scale)
        candidates.append((width, height, track_duration * 1_000 // track_time_scale, fps))

    if not candidates:
        raise _mp4_error()
    width, height, _track_duration_ms, fps = max(
        candidates,
        key=lambda item: item[0] * item[1],
    )
    return MediaProbeV2(
        duration_ms=round(movie_duration * 1_000 / movie_time_scale),
        width_px=width,
        height_px=height,
        fps=fps,
    )


def load_aoi_metadata(path: Path) -> LookbookAoiMetadataV2:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return LookbookAoiMetadataV2.model_validate(payload)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"lookbook AOI metadata is invalid: {path}") from exc


def validate_aoi_metadata_for_catalog(
    metadata: LookbookAoiMetadataV2,
    products: tuple[ProductRecommendationItemV2, ...] | list[ProductRecommendationItemV2],
    *,
    manifest_version: str,
) -> None:
    if metadata.manifest_version != manifest_version:
        raise RuntimeError("AOI metadata manifest_version does not match the playback manifest")
    product_tags = {product.product_id: set(product.controlled_tags) for product in products}
    for exposure in metadata.exposures:
        allowed = product_tags.get(exposure.product_id)
        if allowed is None:
            raise RuntimeError("AOI metadata references a product outside the canonical catalog")
        if not set(exposure.observed_visual_tag_ids) <= allowed:
            raise RuntimeError("AOI metadata contains a visual tag outside the product profile")


def verify_media_file(path: Path, identity: MediaIdentityV2) -> None:
    """Bind reviewed file, duration, dimensions and FPS to one exact MP4."""

    if identity.source_kind != "video_file":
        raise RuntimeError("only video_file media identities can be checked against a file")
    try:
        stat = path.stat()
    except OSError as exc:
        raise RuntimeError("canonical lookbook media is unavailable") from exc
    if not path.is_file() or stat.st_size != identity.byte_length:
        raise RuntimeError("canonical lookbook media byte length does not match metadata")

    digest = sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeError("canonical lookbook media could not be verified") from exc
    if digest.hexdigest() != identity.sha256:
        raise RuntimeError("canonical lookbook media SHA-256 does not match metadata")
    probe = probe_mp4_media(path)
    if (
        probe.duration_ms != identity.duration_ms
        or probe.width_px != identity.width_px
        or probe.height_px != identity.height_px
        or abs(probe.fps - identity.fps) > 0.001
    ):
        raise RuntimeError(
            "canonical lookbook media duration, resolution or FPS does not match metadata"
        )


def _point_on_segment(
    point_x: float,
    point_y: float,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> bool:
    epsilon = 1e-9
    cross = (point_y - start_y) * (end_x - start_x) - (point_x - start_x) * (
        end_y - start_y
    )
    if abs(cross) > epsilon:
        return False
    return (
        min(start_x, end_x) - epsilon <= point_x <= max(start_x, end_x) + epsilon
        and min(start_y, end_y) - epsilon <= point_y <= max(start_y, end_y) + epsilon
    )


def _point_in_polygon(point_x: float, point_y: float, points: list[tuple[float, float]]) -> bool:
    inside = False
    previous_x, previous_y = points[-1]
    for current_x, current_y in points:
        if _point_on_segment(
            point_x,
            point_y,
            previous_x,
            previous_y,
            current_x,
            current_y,
        ):
            return True
        if (current_y > point_y) != (previous_y > point_y):
            crossing_x = (previous_x - current_x) * (point_y - current_y) / (
                previous_y - current_y
            ) + current_x
            if point_x < crossing_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def map_frame_to_aoi(
    frame: FrameObservationV2,
    metadata: LookbookAoiMetadataV2,
) -> AoiMappingResultV2:
    if metadata.approval_status != "approved":
        return AoiMappingResultV2("aoi_metadata_unapproved")
    if frame.gaze is None:
        return AoiMappingResultV2("gaze_unavailable")
    attention = frame.attention
    if attention is None:
        return AoiMappingResultV2("video_point_unavailable")
    if attention.outside_video:
        return AoiMappingResultV2("outside_video")
    if attention.video_x_norm is None or attention.video_y_norm is None:
        return AoiMappingResultV2("video_point_unavailable")
    if frame.video_time_ms >= metadata.media_identity.duration_ms:
        return AoiMappingResultV2("video_time_out_of_range")

    matches = [
        exposure
        for exposure in metadata.exposures
        if exposure.start_ms <= frame.video_time_ms < exposure.end_ms
        and _point_in_polygon(
            attention.video_x_norm,
            attention.video_y_norm,
            exposure.shape.points,
        )
    ]
    if not matches:
        return AoiMappingResultV2("no_aoi_match")
    product_ids = {exposure.product_id for exposure in matches}
    if len(product_ids) != 1:
        return AoiMappingResultV2("ambiguous_product")

    ordered = sorted(matches, key=lambda item: (item.specificity_rank, item.aoi_id))
    product_id = next(iter(product_ids))
    component_codes = tuple(sorted({item.component_code for item in ordered}))
    visual_tags = tuple(
        sorted({tag for exposure in ordered for tag in exposure.observed_visual_tag_ids})
    )
    candidates = tuple(
        AttentionCandidateV2(
            exposure_id=exposure.aoi_id,
            product_id=exposure.product_id,
            priority=0,
            parent_aoi_id=exposure.parent_aoi_id,
            specificity_rank=exposure.specificity_rank,
            component_code=exposure.component_code,
            observed_visual_tag_ids=list(exposure.observed_visual_tag_ids),
        )
        for exposure in ordered
    )
    return AoiMappingResultV2(
        "matched",
        product_id=product_id,
        aoi_ids=tuple(item.aoi_id for item in ordered),
        component_codes=component_codes,
        observed_visual_tag_ids=visual_tags,
        candidates=candidates,
    )


def enrich_frame_with_aoi(
    frame: FrameObservationV2,
    result: AoiMappingResultV2,
) -> FrameObservationV2:
    if frame.attention is None:
        return frame.model_copy(deep=True)
    candidates = list(result.candidates) if result.matched else []
    attention = frame.attention.model_copy(update={"candidates": candidates})
    return frame.model_copy(update={"attention": attention}, deep=True)

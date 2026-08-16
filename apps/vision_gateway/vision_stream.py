"""Local Vision Stream v1 binary framing and ephemeral frame decoding."""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass
from typing import Any, Callable, Mapping


MAGIC = b"MCM1"
PREFIX = struct.Struct(">4sI")
MAX_METADATA_BYTES = 65_535
_FRAME_FIELDS = frozenset(
    {
        "type",
        "protocol_version",
        "session_id",
        "video_id",
        "frame_id",
        "sequence",
        "captured_at_mono_ms",
        "video_time_ms",
        "playback_epoch",
        "layout",
        "camera_frame",
    }
)
_LAYOUT_FIELDS = frozenset(
    {
        "viewport_width_px",
        "viewport_height_px",
        "source_width_px",
        "source_height_px",
        "object_fit",
        "element_rect",
        "content_rect",
    }
)
_RECT_FIELDS = frozenset({"x_px", "y_px", "width_px", "height_px"})
_CAMERA_FRAME_FIELDS = frozenset(
    {"encoding", "width_px", "height_px", "byte_length"}
)
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MEDIA_TYPE_PATTERN = re.compile(r"^image/[a-z0-9][a-z0-9.+-]{0,63}$")


class VisionStreamProtocolError(ValueError):
    """A malformed or unsupported wire message without frame content in its text."""


@dataclass(frozen=True, slots=True)
class StreamFrameContext:
    session_id: str
    video_id: str
    frame_id: str
    sequence: int
    captured_at_mono_ms: float
    video_time_ms: int
    playback_epoch: int

    def as_payload(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "video_id": self.video_id,
            "frame_id": self.frame_id,
            "sequence": self.sequence,
            "captured_at_mono_ms": self.captured_at_mono_ms,
            "video_time_ms": self.video_time_ms,
            "playback_epoch": self.playback_epoch,
        }


@dataclass(frozen=True, slots=True)
class FrameMetadata:
    context: StreamFrameContext
    layout: Mapping[str, object]
    encoding: str
    width_px: int
    height_px: int
    byte_length: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "FrameMetadata":
        if set(payload) != _FRAME_FIELDS:
            raise VisionStreamProtocolError("frame metadata fields are invalid")
        if payload.get("type") != "frame" or payload.get("protocol_version") != "1.0":
            raise VisionStreamProtocolError("unsupported frame message")
        _reject_embedded_media(payload)
        context = StreamFrameContext(
            session_id=_identifier(payload, "session_id"),
            video_id=_identifier(payload, "video_id"),
            frame_id=_identifier(payload, "frame_id"),
            sequence=_non_negative_int(payload, "sequence"),
            captured_at_mono_ms=_non_negative_number(payload, "captured_at_mono_ms"),
            video_time_ms=_non_negative_int(payload, "video_time_ms"),
            playback_epoch=_non_negative_int(payload, "playback_epoch"),
        )
        layout = payload.get("layout")
        if not isinstance(layout, Mapping):
            raise VisionStreamProtocolError("frame layout is required")
        _validate_layout(layout)
        camera = payload.get("camera_frame")
        if not isinstance(camera, Mapping):
            raise VisionStreamProtocolError("camera_frame metadata is required")
        if set(camera) != _CAMERA_FRAME_FIELDS:
            raise VisionStreamProtocolError("camera_frame fields are invalid")
        encoding = camera.get("encoding")
        if (
            not isinstance(encoding, str)
            or _MEDIA_TYPE_PATTERN.fullmatch(encoding) is None
        ):
            raise VisionStreamProtocolError("camera frame encoding is invalid")
        width_px = _positive_int(camera, "width_px")
        height_px = _positive_int(camera, "height_px")
        byte_length = _positive_int(camera, "byte_length")
        return cls(
            context=context,
            layout=dict(layout),
            encoding=encoding,
            width_px=width_px,
            height_px=height_px,
            byte_length=byte_length,
        )


@dataclass(slots=True)
class DecodedFrame:
    """A bounded frame object handed to FaceWorker for one call only."""

    value: Any

    def close(self) -> None:
        value = self.value
        if value is not None:
            release = getattr(value, "close", None)
            if callable(release):
                release()
        self.value = None

    def __getitem__(self, item: object) -> object:
        if self.value is None:
            raise RuntimeError("decoded frame is closed")
        return self.value[item]  # type: ignore[index]

    def to_rgb_copy(self) -> Any:
        if self.value is None:
            raise RuntimeError("decoded frame is closed")
        return self.value[:, :, ::-1].copy()


@dataclass(frozen=True, slots=True)
class DecodedBinaryFrame:
    metadata: FrameMetadata
    image_bytes: bytes


FrameDecoder = Callable[[bytes, FrameMetadata], Any]


def decode_binary_frame(message: bytes, *, max_frame_bytes: int) -> DecodedBinaryFrame:
    if not isinstance(message, bytes) or len(message) < PREFIX.size:
        raise VisionStreamProtocolError("binary frame prefix is invalid")
    magic, metadata_length = PREFIX.unpack_from(message)
    if magic != MAGIC:
        raise VisionStreamProtocolError("binary frame magic is invalid")
    if metadata_length > MAX_METADATA_BYTES:
        raise VisionStreamProtocolError("frame metadata is too large")
    header_end = PREFIX.size + metadata_length
    if header_end > len(message):
        raise VisionStreamProtocolError("binary frame metadata is truncated")
    image_bytes = message[header_end:]
    if len(image_bytes) > max_frame_bytes:
        raise VisionStreamProtocolError("binary frame is too large")
    try:
        raw_metadata = json.loads(message[PREFIX.size:header_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisionStreamProtocolError("binary frame metadata is not valid JSON") from error
    if not isinstance(raw_metadata, Mapping):
        raise VisionStreamProtocolError("binary frame metadata must be an object")
    metadata = FrameMetadata.from_payload(raw_metadata)
    if metadata.byte_length != len(image_bytes):
        raise VisionStreamProtocolError("binary frame payload length does not match metadata")
    return DecodedBinaryFrame(metadata, image_bytes)


def encode_binary_frame(metadata: Mapping[str, object], image_bytes: bytes) -> bytes:
    """Test and local harness helper; production browser code sends the same layout."""

    header = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    if len(header) > MAX_METADATA_BYTES:
        raise VisionStreamProtocolError("frame metadata is too large")
    return PREFIX.pack(MAGIC, len(header)) + header + image_bytes


def default_frame_decoder(image_bytes: bytes, metadata: FrameMetadata) -> DecodedFrame:
    """Decode JPEG/WebP in memory for the selected MediaPipe adapter."""

    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise VisionStreamProtocolError("image decoder runtime is unavailable") from error
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    del encoded
    if decoded is None:
        raise VisionStreamProtocolError("image bytes could not be decoded")
    actual_height, actual_width = decoded.shape[:2]
    if actual_width != metadata.width_px or actual_height != metadata.height_px:
        del decoded
        raise VisionStreamProtocolError("decoded image dimensions do not match metadata")
    return DecodedFrame(decoded)


def _identifier(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise VisionStreamProtocolError(f"{name} is required")
    return value


def _non_negative_int(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisionStreamProtocolError(f"{name} must be a non-negative integer")
    return value


def _positive_int(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VisionStreamProtocolError(f"{name} must be a positive integer")
    return value


def _non_negative_number(payload: Mapping[str, object], name: str) -> float:
    value = payload.get(name)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise VisionStreamProtocolError(f"{name} must be a non-negative number")
    return float(value)


def _validate_layout(layout: Mapping[str, object]) -> None:
    required = (
        "viewport_width_px",
        "viewport_height_px",
        "source_width_px",
        "source_height_px",
        "object_fit",
        "element_rect",
        "content_rect",
    )
    if set(layout) != _LAYOUT_FIELDS or layout.get("object_fit") != "contain":
        raise VisionStreamProtocolError("lookbook layout is invalid")
    for name in required[:4]:
        value = layout.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise VisionStreamProtocolError("lookbook layout dimensions are invalid")
    for name in ("element_rect", "content_rect"):
        rect = layout.get(name)
        if not isinstance(rect, Mapping):
            raise VisionStreamProtocolError("lookbook layout rectangle is invalid")
        if set(rect) != _RECT_FIELDS:
            raise VisionStreamProtocolError("lookbook layout rectangle fields are invalid")
        for field in ("x_px", "y_px", "width_px", "height_px"):
            value = rect.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise VisionStreamProtocolError("lookbook layout rectangle is invalid")
            if field in ("width_px", "height_px") and value <= 0:
                raise VisionStreamProtocolError("lookbook layout rectangle is invalid")


def _reject_embedded_media(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).replace("_", "").lower()
            media_name = "image" in normalized or "frame" in normalized
            payload_name = any(
                word in normalized
                for word in ("base64", "binary", "blob", "bytes", "content", "data", "payload", "raw")
            )
            if normalized == "base64" or (media_name and payload_name):
                raise VisionStreamProtocolError("raw media must not be in frame metadata")
            _reject_embedded_media(child)
    elif isinstance(value, list):
        for child in value:
            _reject_embedded_media(child)

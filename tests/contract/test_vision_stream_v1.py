from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"
MAGIC = b"MCM1"
PREFIX = struct.Struct(">4sI")
MAX_METADATA_BYTES = 65_535
CONTEXT_FIELDS = (
    "session_id",
    "video_id",
    "frame_id",
    "sequence",
    "captured_at_mono_ms",
    "video_time_ms",
    "playback_epoch",
)


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def encode_frame(metadata: dict, image_bytes: bytes) -> bytes:
    if metadata["camera_frame"]["byte_length"] != len(image_bytes):
        raise ValueError("camera_frame.byte_length does not match binary payload")
    header = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    if len(header) > MAX_METADATA_BYTES:
        raise ValueError("frame metadata exceeds 65,535 bytes")
    return PREFIX.pack(MAGIC, len(header)) + header + image_bytes


def decode_frame(message: bytes) -> tuple[dict, bytes]:
    if len(message) < PREFIX.size:
        raise ValueError("binary frame is shorter than its prefix")
    magic, header_length = PREFIX.unpack_from(message)
    if magic != MAGIC:
        raise ValueError("invalid Vision Stream magic")
    if header_length > MAX_METADATA_BYTES or PREFIX.size + header_length > len(message):
        raise ValueError("invalid frame metadata length")
    header_end = PREFIX.size + header_length
    metadata = json.loads(message[PREFIX.size:header_end].decode("utf-8"))
    image_bytes = message[header_end:]
    if metadata["camera_frame"]["byte_length"] != len(image_bytes):
        raise ValueError("camera_frame.byte_length does not match binary payload")
    return metadata, image_bytes


def test_synthetic_binary_frame_round_trip() -> None:
    metadata = load_example("vision-stream-frame-metadata.valid.json")
    synthetic_jpeg = bytes((0xFF, 0xD8, 0xFF, 0xD9))

    decoded_metadata, decoded_image = decode_frame(encode_frame(metadata, synthetic_jpeg))

    assert decoded_metadata == metadata
    assert decoded_image == synthetic_jpeg
    assert "image_bytes" not in decoded_metadata
    assert "image_base64" not in decoded_metadata


def test_binary_frame_rejects_bad_magic_and_length() -> None:
    metadata = load_example("vision-stream-frame-metadata.valid.json")
    message = encode_frame(metadata, bytes((0xFF, 0xD8, 0xFF, 0xD9)))

    with pytest.raises(ValueError, match="magic"):
        decode_frame(b"BAD1" + message[4:])
    with pytest.raises(ValueError, match="byte_length"):
        decode_frame(message[:-1])


def test_negotiation_and_single_in_flight_limit_match() -> None:
    hello = load_example("vision-stream-hello.valid.json")
    ready = load_example("vision-stream-ready.valid.json")

    assert ready["selected_frame_encoding"] in hello["offered_frame_encodings"]
    assert ready["limits"]["in_flight_limit"] == 1


def test_result_preserves_frame_capture_context() -> None:
    frame = load_example("vision-stream-frame-metadata.valid.json")
    result = load_example("vision-stream-result.valid.json")

    expected = {field: frame[field] for field in CONTEXT_FIELDS}
    assert {field: result[field] for field in CONTEXT_FIELDS} == expected
    assert {field: result["gaze_sample"][field] for field in CONTEXT_FIELDS} == expected
    assert {field: result["expression_sample"][field] for field in CONTEXT_FIELDS} == expected


def test_calibration_frame_roundtrip_and_progress_validation():
    from apps.vision_gateway.vision_stream import decode_binary_frame, encode_binary_frame, VisionStreamProtocolError
    from apps.vision_gateway.calibration_protocol import validate_progress
    metadata = load_example("vision-stream-calibration-frame.valid.json")
    binary = encode_binary_frame(metadata, b"\xff\xd8\xff\xd9")
    assert decode_binary_frame(binary, max_frame_bytes=524288).metadata.as_payload() == metadata
    progress = load_example("vision-stream-calibration-progress.valid.json")["calibration_progress"]
    assert validate_progress(progress) == progress
    for change in ({"accepted_samples": 16}, {"required_samples": 0}, {"target": [float("nan"), .1]},
                   {"completed_targets": 35}, {"raw_image": "not allowed"}, {"profile_id": "unknown"}):
        with pytest.raises(ValueError):
            validate_progress({**progress, **change})
    metadata["calibration_target"]["presented_at_mono_ms"] = -1
    with pytest.raises(VisionStreamProtocolError):
        decode_binary_frame(encode_binary_frame(metadata, b"\xff\xd8\xff\xd9"), max_frame_bytes=524288)


def test_calibration_progress_schema_does_not_allow_preference_evidence():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in (ROOT / "contracts").rglob("*.schema.json")]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in documents)
    schema = json.loads((ROOT / "contracts/vision-stream-v1/vision-stream-message.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)
    result = load_example("vision-stream-calibration-progress.valid.json")
    assert validator.is_valid(result)
    result["gaze_sample"] = load_example("vision-stream-result.valid.json")["gaze_sample"]
    result["gaze_reason"] = None
    assert not validator.is_valid(result)


def test_face_positioning_progress_is_optional_and_strictly_limited_to_readiness():
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    from apps.vision_gateway.calibration_protocol import validate_progress
    schema = json.loads((ROOT / "contracts/vision-stream-v1/vision-stream-message.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema["$defs"]["calibrationProgress"])
    progress = load_example("vision-stream-face-positioning.valid.json")["calibration_progress"]
    assert validate_progress(progress) == progress
    assert validator.is_valid(progress)
    for change in ({"phase": "training"}, {"positioning": None},
                   {"positioning": {**progress["positioning"], "stable_ms": 1001}},
                   {"positioning": {**progress["positioning"], "stable_ms": True}},
                   {"positioning": {**progress["positioning"], "eyes_visible": False}},
                   {"positioning": {**progress["positioning"], "landmarks": []}}):
        invalid = {**deepcopy(progress), **change}
        assert not validator.is_valid(invalid)
        with pytest.raises(ValueError):
            validate_progress(invalid)

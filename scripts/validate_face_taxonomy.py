"""Validate the proposed D5 Face observable-action taxonomy artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY_PATH = (
    REPOSITORY_ROOT / "docs" / "adr" / "face-observable-actions-v1.json"
)
EXPECTED_VERSION = "face-observable-actions-v1"
EXPECTED_SOURCE_LABELS = (
    "_neutral",
    "browDownLeft",
    "browDownRight",
    "browInnerUp",
    "browOuterUpLeft",
    "browOuterUpRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeWideLeft",
    "eyeWideRight",
    "jawForward",
    "jawLeft",
    "jawOpen",
    "jawRight",
    "mouthClose",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthFunnel",
    "mouthLeft",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthPucker",
    "mouthRight",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "noseSneerLeft",
    "noseSneerRight",
)
EXPECTED_SOURCE_MODEL = {
    "model_id": "mediapipe-face-landmarker",
    "source_revision": "493c90e5f3eb40b9080606964fc18528a99962f0",
    "asset_revision": "face_landmarker/float16/1",
    "asset_sha256": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
}
TOP_LEVEL_FIELDS = {
    "taxonomy_version",
    "status",
    "additional_properties",
    "source_model",
    "labels",
    "neutral_policy",
    "unknown_label_policy",
    "no_face_policy",
}
LABEL_FIELDS = {
    "source_label",
    "canonical_signal_name",
    "signal_kind",
    "emotion_label",
    "laterality",
    "score_policy",
    "final",
}
CANONICAL_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SENSITIVE_KEYS = {
    "image",
    "image_bytes",
    "raw_image",
    "base64",
    "embedding",
    "credential",
    "password",
    "secret",
    "token",
    "private_key",
}
SENSITIVE_VALUE_MARKERS = (
    "data:image",
    "begin private key",
    "begin rsa private key",
    "begin openssh private key",
)


def _expect_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _expect_exact_fields(value: dict[str, Any], fields: set[str], path: str) -> None:
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise ValueError(f"{path} fields mismatch: missing={missing}, extra={extra}")


def _snake_case(source_label: str) -> str:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", source_label.lstrip("_")).lower()
    return re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")


def _expected_laterality(source_label: str) -> str:
    if source_label.endswith("Left"):
        return "left"
    if source_label.endswith("Right"):
        return "right"
    return "none"


def _reject_sensitive_payload(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in SENSITIVE_KEYS:
                raise ValueError(f"{path} contains forbidden field: {key}")
            _reject_sensitive_payload(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_payload(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        lowered = value.casefold()
        if any(marker in lowered for marker in SENSITIVE_VALUE_MARKERS):
            raise ValueError(f"{path} contains forbidden payload")


def validate_taxonomy(document: Any) -> dict[str, Any]:
    root = _expect_object(document, "root")
    _expect_exact_fields(root, TOP_LEVEL_FIELDS, "root")
    _reject_sensitive_payload(root)

    if root["taxonomy_version"] != EXPECTED_VERSION:
        raise ValueError("taxonomy_version is not the approved D5 version")
    if root["status"] != "proposed":
        raise ValueError("taxonomy status must remain proposed before team approval")
    if root["additional_properties"] != "forbidden":
        raise ValueError("additional properties policy must be forbidden")
    if root["source_model"] != EXPECTED_SOURCE_MODEL:
        raise ValueError("source model revision or checksum does not match ADR-0003")

    labels = root["labels"]
    if not isinstance(labels, list) or len(labels) != len(EXPECTED_SOURCE_LABELS):
        raise ValueError("labels must contain exactly 52 MediaPipe source labels")

    source_labels: list[str] = []
    canonical_names: list[str] = []
    for index, raw_entry in enumerate(labels):
        entry = _expect_object(raw_entry, f"labels[{index}]")
        _expect_exact_fields(entry, LABEL_FIELDS, f"labels[{index}]")

        source_label = entry["source_label"]
        canonical_name = entry["canonical_signal_name"]
        if not isinstance(source_label, str) or not isinstance(canonical_name, str):
            raise ValueError(f"labels[{index}] names must be strings")
        if not CANONICAL_PATTERN.fullmatch(canonical_name):
            raise ValueError(f"labels[{index}] has an invalid canonical signal name")
        if entry["signal_kind"] != "observable_face_action":
            raise ValueError(f"labels[{index}] must be an observable face action")
        if entry["emotion_label"] is not False:
            raise ValueError(f"labels[{index}] cannot be an emotion label")
        if entry["final"] is not False:
            raise ValueError(f"labels[{index}] cannot be final while status is proposed")
        if entry["laterality"] != _expected_laterality(source_label):
            raise ValueError(f"labels[{index}] does not preserve source laterality")

        expected_name = (
            "source_neutral_baseline"
            if source_label == "_neutral"
            else _snake_case(source_label)
        )
        expected_score_policy = "exclude" if source_label == "_neutral" else "emit"
        if canonical_name != expected_name or entry["score_policy"] != expected_score_policy:
            raise ValueError(f"labels[{index}] mapping does not match the D5 policy")

        source_labels.append(source_label)
        canonical_names.append(canonical_name)

    if tuple(source_labels) != EXPECTED_SOURCE_LABELS:
        raise ValueError("MediaPipe source labels are missing, duplicated, or reordered")
    if len(set(source_labels)) != len(source_labels):
        raise ValueError("source labels must be unique")
    if len(set(canonical_names)) != len(canonical_names):
        raise ValueError("canonical signal names must be unique")

    expected_neutral = {
        "source_label": "_neutral",
        "canonical_signal_name": "source_neutral_baseline",
        "interpretation": "source_baseline_not_neutral_emotion",
        "score_policy": "exclude",
    }
    if root["neutral_policy"] != expected_neutral:
        raise ValueError("_neutral must remain an excluded non-emotion source baseline")

    expected_unknown = {
        "canonical_signal_name": "unknown",
        "single_unknown": "emit_without_semantic_inference",
        "multiple_unknown": "invalidate_as_malformed_output",
    }
    if root["unknown_label_policy"] != expected_unknown:
        raise ValueError("unknown label policy is missing or has changed")

    expected_no_face = {
        "event_emitted": True,
        "face_detected": False,
        "face_count": 0,
        "valid": False,
        "scores": {},
        "reason": "no_face",
        "score_label": False,
    }
    if root["no_face_policy"] != expected_no_face:
        raise ValueError("no-face policy must be an emitted invalid empty-score event")
    if "no_face" in source_labels or "no_face" in canonical_names:
        raise ValueError("no-face cannot be a taxonomy score label")

    return {
        "status": "pass",
        "taxonomy_version": root["taxonomy_version"],
        "label_count": len(labels),
        "emitted_signal_count": sum(
            entry["score_policy"] == "emit" for entry in labels
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_TAXONOMY_PATH)
    args = parser.parse_args()

    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
        result = validate_taxonomy(document)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "fail", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

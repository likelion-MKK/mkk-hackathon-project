"""Validate D4 Face source labels and provisional non-production mappings."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MEDIAPIPE = "mediapipe-face-landmarker"
OPENVINO = "openvino-emotions-retail-0003"
HSEMOTION = "hsemotion-enet-b0-8-best-afew"
CANDIDATES = (MEDIAPIPE, OPENVINO, HSEMOTION)

SOURCE_LABELS: dict[str, tuple[str, ...]] = {
    MEDIAPIPE: (
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
    ),
    OPENVINO: ("neutral", "happy", "sad", "surprise", "anger"),
    HSEMOTION: (
        "Anger",
        "Contempt",
        "Disgust",
        "Fear",
        "Happiness",
        "Neutral",
        "Sadness",
        "Surprise",
    ),
}


@dataclass(frozen=True)
class MappingEntry:
    candidate: str
    source_label: str
    provisional_common_label: str
    rationale: str
    uncertainty: str
    final: bool = False


def snake_case(value: str) -> str:
    without_prefix = value.lstrip("_")
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", without_prefix).lower()
    return re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")


def provisional_label(candidate: str, source_label: str) -> tuple[str, str, str]:
    if candidate == MEDIAPIPE:
        if source_label == "_neutral":
            return (
                "unmapped",
                "MediaPipe baseline category; no emotion meaning is inferred",
                "high",
            )
        return (
            f"{snake_case(source_label)}_like",
            "original observable blendshape name preserved as a provisional signal",
            "high",
        )
    if candidate == OPENVINO:
        return (
            f"{source_label}_like",
            "original five-class model label with a provisional _like suffix",
            "medium",
        )
    if candidate == HSEMOTION:
        return (
            f"{snake_case(source_label)}_like",
            "original eight-class model label retained for comparison only",
            "high",
        )
    raise ValueError(f"unknown candidate: {candidate}")


def mapping_catalog() -> list[MappingEntry]:
    entries: list[MappingEntry] = []
    for candidate in CANDIDATES:
        for source_label in SOURCE_LABELS[candidate]:
            common_label, rationale, uncertainty = provisional_label(
                candidate, source_label
            )
            entries.append(
                MappingEntry(
                    candidate=candidate,
                    source_label=source_label,
                    provisional_common_label=common_label,
                    rationale=rationale,
                    uncertainty=uncertainty,
                )
            )
    return entries


def validate_catalog(entries: list[MappingEntry]) -> None:
    expected_count = sum(len(labels) for labels in SOURCE_LABELS.values())
    if len(entries) != expected_count:
        raise ValueError("mapping catalog dropped or added source labels")
    observed = {(entry.candidate, entry.source_label) for entry in entries}
    expected = {
        (candidate, source_label)
        for candidate, labels in SOURCE_LABELS.items()
        for source_label in labels
    }
    if observed != expected:
        raise ValueError("mapping catalog does not preserve every original label")
    if any(entry.final for entry in entries):
        raise ValueError("D4 provisional mappings cannot be marked final")
    if any(
        entry.provisional_common_label != "unmapped"
        and not entry.provisional_common_label.endswith("_like")
        for entry in entries
    ):
        raise ValueError("provisional labels must be unmapped or end in _like")


def validate_benchmark_artifact(candidate: str, artifact: dict[str, Any]) -> dict[str, Any]:
    if artifact.get("candidate") != candidate:
        raise ValueError("benchmark artifact candidate does not match")
    if artifact.get("accuracy_claim") != "none":
        raise ValueError("synthetic benchmark must not claim accuracy")
    if artifact.get("quality_evaluation") != "not_available_without_ground_truth":
        raise ValueError("synthetic benchmark must identify missing ground truth")

    if candidate == HSEMOTION:
        if artifact.get("hard_gate") != "fail":
            raise ValueError("HSEmotion must remain a Hard Gate failure")
        if artifact.get("inference_benchmark") != "excluded":
            raise ValueError("HSEmotion inference benchmark must be excluded")
        if artifact.get("reason") != "unsafe_legacy_pickle_blocked":
            raise ValueError("HSEmotion exclusion reason is missing")
        return {
            "candidate": candidate,
            "hard_gate": "fail",
            "label_count": len(SOURCE_LABELS[candidate]),
            "no_face_validation": "not_measured_hard_gate_exclusion",
            "output_validation": "not_measured_hard_gate_exclusion",
            "stability_observation": "not_measured_hard_gate_exclusion",
        }

    if artifact.get("hard_gate") != "pass" or artifact.get("status") != "pass":
        raise ValueError("benchmark candidate did not pass its execution gate")
    cold_runs = artifact.get("cold_runs")
    if not isinstance(cold_runs, list) or not cold_runs:
        raise ValueError("benchmark artifact has no cold runs")
    for run in cold_runs:
        for output_name in ("first_output", "no_face_output"):
            output = run.get(output_name, {})
            if output.get("scores_finite") is not True:
                raise ValueError(f"{output_name} contains non-finite scores")

    first_output = cold_runs[0]["first_output"]
    if candidate == OPENVINO:
        if tuple(first_output.get("labels", ())) != SOURCE_LABELS[candidate]:
            raise ValueError("OpenVINO output labels are not in the documented order")
        if first_output.get("output_shape") != [1, 5, 1, 1]:
            raise ValueError("OpenVINO output shape is unexpected")
        no_face_validation = "not_supported_classifier_requires_face_crop"
    else:
        no_face_output = cold_runs[0]["no_face_output"]
        if no_face_output.get("face_count") != 0 or no_face_output.get("score_count") != 0:
            raise ValueError("MediaPipe no-face output is not empty")
        no_face_validation = "pass"

    stability = artifact.get("stability_observation")
    if stability not in ("pass", "fail"):
        raise ValueError("stability observation is missing")
    return {
        "candidate": candidate,
        "hard_gate": "pass",
        "label_count": len(SOURCE_LABELS[candidate]),
        "no_face_validation": no_face_validation,
        "output_validation": "pass",
        "stability_observation": stability,
    }


def build_report(validations: list[dict[str, Any]]) -> dict[str, Any]:
    entries = mapping_catalog()
    validate_catalog(entries)
    return {
        "accuracy_claim": "none",
        "candidates": validations,
        "final_taxonomy": False,
        "mapping_count": len(entries),
        "mappings": [asdict(entry) for entry in entries],
        "status": "comparison_only",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact",
        action="append",
        nargs=2,
        metavar=("CANDIDATE", "PATH"),
        required=True,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "face-label-normalization.json",
    )
    args = parser.parse_args()

    validations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate, raw_path in args.artifact:
        if candidate not in CANDIDATES:
            raise SystemExit(f"unknown candidate: {candidate}")
        if candidate in seen:
            raise SystemExit(f"duplicate candidate: {candidate}")
        seen.add(candidate)
        artifact = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        validations.append(validate_benchmark_artifact(candidate, artifact))
    if seen != set(CANDIDATES):
        raise SystemExit("artifacts for all three candidates are required")

    report = build_report(validations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": len(validations),
                "mapping_count": report["mapping_count"],
                "output": str(args.output),
                "status": report["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "face_label_normalization.py"
SPEC = importlib.util.spec_from_file_location("face_label_normalization", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
NORMALIZATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = NORMALIZATION
SPEC.loader.exec_module(NORMALIZATION)


def passing_artifact(candidate: str) -> dict[str, object]:
    if candidate == NORMALIZATION.HSEMOTION:
        return {
            "accuracy_claim": "none",
            "candidate": candidate,
            "hard_gate": "fail",
            "inference_benchmark": "excluded",
            "quality_evaluation": "not_available_without_ground_truth",
            "reason": "unsafe_legacy_pickle_blocked",
        }
    first_output = {
        "face_count": 0,
        "labels": [],
        "output_shape": {
            "face_landmark_groups": 0,
            "blendshape_groups": 0,
            "blendshape_count": 0,
        },
        "score_count": 0,
        "scores_finite": True,
    }
    if candidate == NORMALIZATION.OPENVINO:
        first_output = {
            "face_count": None,
            "labels": list(NORMALIZATION.SOURCE_LABELS[candidate]),
            "output_shape": [1, 5, 1, 1],
            "score_count": 5,
            "scores_finite": True,
        }
    return {
        "accuracy_claim": "none",
        "candidate": candidate,
        "cold_runs": [
            {
                "first_output": first_output,
                "no_face_output": {
                    "face_count": 0 if candidate == NORMALIZATION.MEDIAPIPE else None,
                    "labels": [],
                    "output_shape": [],
                    "score_count": 0,
                    "scores_finite": True,
                },
            }
        ],
        "hard_gate": "pass",
        "quality_evaluation": "not_available_without_ground_truth",
        "stability_observation": "pass",
        "status": "pass",
    }


class FaceLabelNormalizationTests(unittest.TestCase):
    def test_all_source_labels_are_preserved_and_provisional(self) -> None:
        entries = NORMALIZATION.mapping_catalog()

        NORMALIZATION.validate_catalog(entries)
        self.assertEqual(len(NORMALIZATION.SOURCE_LABELS[NORMALIZATION.MEDIAPIPE]), 52)
        self.assertEqual(len(NORMALIZATION.SOURCE_LABELS[NORMALIZATION.OPENVINO]), 5)
        self.assertEqual(len(NORMALIZATION.SOURCE_LABELS[NORMALIZATION.HSEMOTION]), 8)
        self.assertTrue(all(entry.final is False for entry in entries))

    def test_mediapipe_labels_are_not_promoted_to_emotions(self) -> None:
        entries = [
            entry
            for entry in NORMALIZATION.mapping_catalog()
            if entry.candidate == NORMALIZATION.MEDIAPIPE
        ]

        self.assertTrue(all(entry.uncertainty == "high" for entry in entries))
        self.assertEqual(entries[0].provisional_common_label, "unmapped")
        self.assertEqual(
            next(
                entry.provisional_common_label
                for entry in entries
                if entry.source_label == "mouthSmileLeft"
            ),
            "mouth_smile_left_like",
        )

    def test_openvino_output_shape_and_labels_validate(self) -> None:
        result = NORMALIZATION.validate_benchmark_artifact(
            NORMALIZATION.OPENVINO, passing_artifact(NORMALIZATION.OPENVINO)
        )

        self.assertEqual(result["output_validation"], "pass")
        self.assertEqual(
            result["no_face_validation"],
            "not_supported_classifier_requires_face_crop",
        )

    def test_mediapipe_no_face_requires_empty_scores(self) -> None:
        artifact = passing_artifact(NORMALIZATION.MEDIAPIPE)
        artifact["cold_runs"][0]["no_face_output"]["score_count"] = 1

        with self.assertRaisesRegex(ValueError, "no-face output is not empty"):
            NORMALIZATION.validate_benchmark_artifact(
                NORMALIZATION.MEDIAPIPE, artifact
            )

    def test_non_finite_output_summary_fails_validation(self) -> None:
        artifact = passing_artifact(NORMALIZATION.OPENVINO)
        artifact["cold_runs"][0]["first_output"]["scores_finite"] = False

        with self.assertRaisesRegex(ValueError, "non-finite"):
            NORMALIZATION.validate_benchmark_artifact(
                NORMALIZATION.OPENVINO, artifact
            )

    def test_hsemotion_remains_excluded_by_hard_gate(self) -> None:
        result = NORMALIZATION.validate_benchmark_artifact(
            NORMALIZATION.HSEMOTION, passing_artifact(NORMALIZATION.HSEMOTION)
        )

        self.assertEqual(result["hard_gate"], "fail")
        self.assertEqual(result["output_validation"], "not_measured_hard_gate_exclusion")


if __name__ == "__main__":
    unittest.main()

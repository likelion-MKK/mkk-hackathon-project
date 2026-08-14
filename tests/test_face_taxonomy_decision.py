from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "validate_face_taxonomy.py"
TAXONOMY_PATH = REPOSITORY_ROOT / "docs" / "adr" / "face-observable-actions-v1.json"
SPEC = importlib.util.spec_from_file_location("validate_face_taxonomy", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def taxonomy_document() -> dict[str, object]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


class FaceTaxonomyDecisionTests(unittest.TestCase):
    def test_committed_taxonomy_passes(self) -> None:
        result = VALIDATOR.validate_taxonomy(taxonomy_document())

        self.assertEqual(result["taxonomy_version"], "face-observable-actions-v1")
        self.assertEqual(result["label_count"], 52)
        self.assertEqual(result["emitted_signal_count"], 51)

    def test_source_and_canonical_labels_are_complete_and_unique(self) -> None:
        document = taxonomy_document()
        labels = document["labels"]

        self.assertEqual(
            tuple(entry["source_label"] for entry in labels),
            VALIDATOR.EXPECTED_SOURCE_LABELS,
        )
        self.assertEqual(
            len({entry["canonical_signal_name"] for entry in labels}),
            52,
        )

    def test_neutral_is_not_an_emotion_or_emitted_score(self) -> None:
        neutral = taxonomy_document()["labels"][0]

        self.assertEqual(neutral["source_label"], "_neutral")
        self.assertEqual(neutral["canonical_signal_name"], "source_neutral_baseline")
        self.assertIs(neutral["emotion_label"], False)
        self.assertEqual(neutral["score_policy"], "exclude")

    def test_all_signals_are_non_final_observable_actions(self) -> None:
        for entry in taxonomy_document()["labels"]:
            self.assertEqual(entry["signal_kind"], "observable_face_action")
            self.assertIs(entry["emotion_label"], False)
            self.assertIs(entry["final"], False)

    def test_laterality_is_preserved_without_aggregation(self) -> None:
        entries = {
            entry["source_label"]: entry for entry in taxonomy_document()["labels"]
        }

        self.assertEqual(entries["eyeBlinkLeft"]["laterality"], "left")
        self.assertEqual(entries["eyeBlinkRight"]["laterality"], "right")
        self.assertNotEqual(
            entries["eyeBlinkLeft"]["canonical_signal_name"],
            entries["eyeBlinkRight"]["canonical_signal_name"],
        )

    def test_unknown_and_no_face_are_explicit_non_emotion_policies(self) -> None:
        document = taxonomy_document()

        self.assertEqual(
            document["unknown_label_policy"]["canonical_signal_name"], "unknown"
        )
        self.assertEqual(document["no_face_policy"]["scores"], {})
        self.assertIs(document["no_face_policy"]["valid"], False)
        self.assertIs(document["no_face_policy"]["score_label"], False)
        canonical = {
            entry["canonical_signal_name"] for entry in document["labels"]
        }
        self.assertNotIn("no_face", canonical)

    def test_missing_duplicate_and_reordered_source_labels_are_rejected(self) -> None:
        missing = taxonomy_document()
        missing["labels"].pop()
        with self.assertRaisesRegex(ValueError, "exactly 52"):
            VALIDATOR.validate_taxonomy(missing)

        duplicate = taxonomy_document()
        duplicate["labels"][1]["source_label"] = "_neutral"
        with self.assertRaisesRegex(ValueError, "laterality"):
            VALIDATOR.validate_taxonomy(duplicate)

        reordered = taxonomy_document()
        reordered["labels"][1], reordered["labels"][2] = (
            reordered["labels"][2],
            reordered["labels"][1],
        )
        with self.assertRaisesRegex(ValueError, "reordered"):
            VALIDATOR.validate_taxonomy(reordered)

    def test_duplicate_canonical_name_is_rejected(self) -> None:
        document = taxonomy_document()
        document["labels"][2]["canonical_signal_name"] = document["labels"][1][
            "canonical_signal_name"
        ]

        with self.assertRaisesRegex(ValueError, "mapping does not match"):
            VALIDATOR.validate_taxonomy(document)

    def test_neutral_emotion_or_laterality_changes_are_rejected(self) -> None:
        emotion = taxonomy_document()
        emotion["labels"][0]["emotion_label"] = True
        with self.assertRaisesRegex(ValueError, "cannot be an emotion"):
            VALIDATOR.validate_taxonomy(emotion)

        laterality = taxonomy_document()
        laterality["labels"][1]["laterality"] = "none"
        with self.assertRaisesRegex(ValueError, "laterality"):
            VALIDATOR.validate_taxonomy(laterality)

    def test_additional_fields_are_rejected_at_every_level(self) -> None:
        root_extra = taxonomy_document()
        root_extra["note"] = "not allowed"
        with self.assertRaisesRegex(ValueError, "extra=\\['note'\\]"):
            VALIDATOR.validate_taxonomy(root_extra)

        label_extra = taxonomy_document()
        label_extra["labels"][0]["note"] = "not allowed"
        with self.assertRaisesRegex(ValueError, "extra=\\['note'\\]"):
            VALIDATOR.validate_taxonomy(label_extra)

    def test_sensitive_payload_fields_and_values_are_rejected(self) -> None:
        field_payload = taxonomy_document()
        field_payload["labels"][0]["embedding"] = [0.1]
        with self.assertRaisesRegex(ValueError, "forbidden field: embedding"):
            VALIDATOR.validate_taxonomy(field_payload)

        value_payload = deepcopy(taxonomy_document())
        value_payload["neutral_policy"]["interpretation"] = "data:image/png;base64,secret"
        with self.assertRaisesRegex(ValueError, "forbidden payload"):
            VALIDATOR.validate_taxonomy(value_payload)


if __name__ == "__main__":
    unittest.main()

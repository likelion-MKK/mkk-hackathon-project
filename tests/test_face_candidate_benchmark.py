from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "face_candidate_benchmark.py"
SPEC = importlib.util.spec_from_file_location("face_candidate_benchmark", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
BENCHMARK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BENCHMARK
SPEC.loader.exec_module(BENCHMARK)


class FaceCandidateBenchmarkTests(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self) -> None:
        values = [float(value) for value in range(1, 101)]

        self.assertEqual(BENCHMARK.percentile(values, 50), 50.0)
        self.assertEqual(BENCHMARK.percentile(values, 95), 95.0)

    def test_synthetic_fixture_is_deterministic_and_distinct(self) -> None:
        first = BENCHMARK.synthetic_input_sha256()
        second = BENCHMARK.synthetic_input_sha256()

        self.assertEqual(first, second)
        self.assertNotEqual(first["no_face"], first["synthetic_crop"])
        self.assertEqual(
            BENCHMARK.synthetic_rgb("synthetic_crop", 0).tobytes(),
            BENCHMARK.synthetic_rgb("synthetic_crop", 99).tobytes(),
        )

    def test_process_memory_is_available_on_windows(self) -> None:
        memory = BENCHMARK.process_memory()

        if BENCHMARK.os.name == "nt":
            self.assertIsNotNone(memory["rss_mib"])
            self.assertIsNotNone(memory["peak_working_set_mib"])

    def test_output_summary_keeps_metrics_only(self) -> None:
        output = {
            "face_count": 1,
            "labels": ["example"],
            "output_shape": [1],
            "scores": {"example": 0.5},
        }

        summary = BENCHMARK.summarize_output(output)

        self.assertNotIn("scores", summary)
        self.assertEqual(summary["score_count"], 1)
        self.assertTrue(summary["scores_finite"])

    def test_non_finite_score_is_rejected_by_summary(self) -> None:
        output = {
            "face_count": 1,
            "labels": ["example"],
            "output_shape": [1],
            "scores": {"example": math.inf},
        }

        self.assertFalse(BENCHMARK.summarize_output(output)["scores_finite"])

    def test_artifact_contains_no_media_payload(self) -> None:
        result = {
            "candidate": BENCHMARK.HSEMOTION,
            "hard_gate": "fail",
            "offline": True,
            "status": "excluded",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = BENCHMARK.write_artifact(
                BENCHMARK.HSEMOTION, result, Path(directory) / "result.json"
            )
            serialized = path.read_text(encoding="utf-8").lower()

        self.assertNotIn("base64", serialized)
        self.assertNotIn("image_bytes", serialized)
        self.assertEqual(json.loads(serialized)["status"], "excluded")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


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

    def test_warm_worker_fails_when_every_inference_fails(self) -> None:
        calls = 0

        def infer(_kind: str, _frame_index: int) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"scores": {}}
            raise RuntimeError("synthetic inference failure")

        session = BENCHMARK.RuntimeSession(
            infer=infer,
            close=lambda: None,
            model_load_ms=1.0,
            asset_access_ms=1.0,
            model_sha256={},
        )
        with mock.patch.object(BENCHMARK, "load_runtime", return_value=session):
            result = BENCHMARK.warm_worker(
                BENCHMARK.MEDIAPIPE,
                offline=True,
                duration_seconds=1,
                fps_values=(2,),
            )

        workload = result["workloads"]["2"]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(workload["status"], "fail")
        self.assertEqual(workload["failure_count"], 2)
        self.assertEqual(workload["measured_sample_count"], 0)
        self.assertEqual(workload["stability_observation"], "fail")
        self.assertNotIn("timeout_count", workload)

    def test_deadline_miss_marks_workload_failed(self) -> None:
        status = BENCHMARK.warm_workload_status(
            frame_count=3,
            measured_sample_count=3,
            failure_count=0,
            deadline_miss_count=1,
            stability_observation="pass",
        )

        self.assertEqual(status, "fail")

    def test_warm_failure_marks_top_level_benchmark_failed(self) -> None:
        cold = {
            "no_face_output": {"face_count": 0},
        }
        warm = {
            "model_sha256": {},
            "status": "fail",
            "workloads": {
                "3": {
                    "stability_observation": "fail",
                    "status": "fail",
                }
            },
        }
        args = argparse.Namespace(
            candidate=BENCHMARK.MEDIAPIPE,
            offline=True,
            cold_runs=1,
            duration_seconds=1,
            fps=[3],
        )
        with mock.patch.object(BENCHMARK, "run_child", side_effect=[cold, warm]):
            result = BENCHMARK.run_benchmark(args)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "warm_workload_failed")
        self.assertEqual(result["inference_benchmark"], "failed")

    def test_worker_timeout_becomes_explicit_failed_benchmark(self) -> None:
        timeout = BENCHMARK.BenchmarkWorkerTimeoutError(["_warm"], 180)
        args = argparse.Namespace(
            candidate=BENCHMARK.MEDIAPIPE,
            offline=True,
            cold_runs=1,
            duration_seconds=1,
            fps=[1],
        )
        with mock.patch.object(BENCHMARK, "run_child", side_effect=timeout):
            result = BENCHMARK.run_benchmark(args)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "worker_timeout")
        self.assertEqual(result["timeout_stage"], "warm")
        self.assertEqual(result["worker_timeout_seconds"], 180)

    def test_run_child_converts_subprocess_timeout(self) -> None:
        expired = subprocess.TimeoutExpired(cmd=["worker"], timeout=7)
        with mock.patch.object(BENCHMARK.subprocess, "run", side_effect=expired):
            with self.assertRaises(
                BENCHMARK.BenchmarkWorkerTimeoutError
            ) as raised:
                BENCHMARK.run_child(["_cold", BENCHMARK.MEDIAPIPE], timeout_seconds=7)

        self.assertEqual(raised.exception.stage, "cold")
        self.assertEqual(raised.exception.timeout_seconds, 7)

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

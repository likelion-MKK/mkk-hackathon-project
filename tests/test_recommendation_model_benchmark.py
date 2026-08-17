from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "experiments" / "recommendation" / "benchmark.py"
SPEC = importlib.util.spec_from_file_location("recommendation_model_benchmark", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load recommendation benchmark module")
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class DeterministicAdapter:
    def __init__(self) -> None:
        self.generate_count = 0

    def count_tokens(self, messages):
        return 256

    def generate(self, messages):
        self.generate_count += 1
        payload = json.loads(messages[-1]["content"])
        target = payload["evidence"]["summary"][0]["product_id"]
        return json.dumps(
            benchmark._valid_stub_output(payload, target),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class TimeoutAdapter:
    def count_tokens(self, messages):
        return 100

    def generate(self, messages):
        raise benchmark.InferenceTimeout("timeout")


class MalformedAdapter:
    def count_tokens(self, messages):
        return 100

    def generate(self, messages):
        return "```json\n{not-json}\n```"


class OversizedInputAdapter:
    def __init__(self) -> None:
        self.generate_count = 0

    def count_tokens(self, messages):
        return 3585

    def generate(self, messages):
        self.generate_count += 1
        return "{}"


def load_registry():
    return benchmark.load_json(benchmark.REGISTRY_PATH)


def load_suite():
    return benchmark.load_json(benchmark.CASES_PATH)


def ready_preparation(candidate_id: str):
    return {
        "candidates": [
            {
                "candidate_id": candidate_id,
                "status": "ready",
                "artifact_manifest": {"manifest_sha256": "a" * 64},
            }
        ]
    }


def passing_run(candidate):
    suite = load_suite()
    rows = []
    for case in suite["cases"]:
        if case["should_call_model"]:
            for variant in ("A", "B", "C"):
                for repeat_index in range(5):
                    rows.append(
                        {
                            "phase": "correctness",
                            "variant": variant,
                            "case_id": case["case_id"],
                            "repeat_index": repeat_index,
                            "status": "completed",
                            "selected_product_id": case["expected_product_id"],
                            "expected_product_id": case["expected_product_id"],
                            "input_tokens": 512,
                            "strict_json_schema": True,
                            "validation": {
                                "catalog_membership": True,
                                "exactly_one_product": True,
                                "expected_winner_match": True,
                                "evidence_grounded": True,
                                "catalog_tags_grounded": True,
                                "psychology_auxiliary_signal_grounded": True,
                                "psychological_assertion_count": 0,
                                "unsupported_product_fact_count": 0,
                                "prompt_injection_followed_count": 0,
                            },
                        }
                    )
        else:
            rows.append(
                {
                    "phase": "no_call",
                    "variant": "preflight",
                    "case_id": case["case_id"],
                    "status": "insufficient_data",
                    "selected_product_id": None,
                    "model_called": False,
                    "failure_reason": case["expected_failure_reason"],
                }
            )
    for repeat_index in range(3):
        rows.append(
            {
                "phase": "warmup",
                "variant": "C",
                "case_id": "normal-gaze-dominant",
                "status": "completed",
                "latency_ms": 1400 + repeat_index,
            }
        )
    for repeat_index in range(30):
        rows.append(
            {
                "phase": "measurement",
                "variant": "C",
                "case_id": "normal-gaze-dominant",
                "status": "completed",
                "latency_ms": 1200 + repeat_index,
            }
        )
    return {
        "run_version": "recommendation-benchmark-run-v1",
        "synthetic_only": True,
        "candidate_id": candidate["candidate_id"],
        "model_id": candidate["model_id"],
        "model_revision": candidate["revision"],
        "profile": candidate["execution_lane"],
        "preparation_status": "ready",
        "preparation_manifest_sha256": "a" * 64,
        "runtime": candidate["runtime"],
        "cpu_threads": 2,
        "results": rows,
        "cold_start_ms": [2100.0, 2050.0, 2080.0],
        "resources": {
            "runtime_pid_monitored": True,
            "gpu_inventory": [{"name": "Test GPU", "vram_total_bytes": 16 * 1024**3}],
            "peak_vram_bytes": 8 * 1024**3,
            "memory_limit_bytes": 2_684_354_560,
            "peak_rss_bytes": 2_000_000_000,
            "persistent_swap_growth_bytes": 0,
            "oom_count": 0,
            "process_restart_count": 0,
            "host_available_bytes_at_start": 800_000_000,
        },
        "stub_results": [
            {"scenario": name, "fail_closed": True, "selected_product_id": None}
            for name in load_suite()["stub_failures"]
        ],
        "external_provider_used": False,
        "selected_model": None,
    }


class RecommendationModelBenchmarkTests(unittest.TestCase):
    def test_registry_and_suite_are_pinned_and_unselected(self):
        registry_result = benchmark.validate_registry(load_registry())
        suite_result = benchmark.validate_case_suite(load_suite())
        self.assertEqual(registry_result["candidate_count"], 7)
        self.assertEqual(registry_result["colab_candidate_count"], 7)
        self.assertIsNone(registry_result["selected_model"])
        self.assertEqual(suite_result["case_count"], 12)
        self.assertEqual(suite_result["planned_correctness_calls_per_candidate"], 135)
        self.assertEqual(suite_result["psychology_auxiliary_case_count"], 9)
        self.assertEqual(suite_result["smoke_case_count"], 5)
        self.assertEqual(suite_result["smoke_callable_case_count"], 4)
        self.assertEqual(benchmark.PROMPT_PATH.name, "central-recommender.ko.v2.txt")

    def test_registry_drift_is_rejected(self):
        registry = load_registry()
        registry["candidates"][0]["revision"] = "main"
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.validate_registry(registry)

    def test_checksum_mismatch_is_reported(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Qwen3-0.6B-Q8_0.gguf"
            path.write_bytes(b"not-the-reviewed-weight")
            result = benchmark.verify_candidate_artifacts(candidate, Path(temp_dir))
        self.assertFalse(result["verified"])
        self.assertIn("checksum_mismatch:Qwen3-0.6B-Q8_0.gguf", result["errors"])

    def test_huggingface_internal_cache_is_not_in_manifest(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Qwen3-0.6B-Q8_0.gguf").write_bytes(b"not-reviewed-weight")
            (root / "LICENSE").write_text("license", encoding="utf-8")
            (root / ".cache" / "huggingface").mkdir(parents=True)
            (root / ".cache" / "huggingface" / "metadata.json").write_text("cache", encoding="utf-8")
            result = benchmark.verify_candidate_artifacts(candidate, root)
        self.assertTrue(all(not item["path"].startswith(".cache/") for item in result["files"]))

    def test_recorded_local_checksum_mismatch_is_reported(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        candidate = copy.deepcopy(candidate)
        candidate["artifact"]["files"] = [
            {
                "path": "Qwen3-0.6B-Q8_0.gguf",
                "hub_sha256": None,
                "sha256": "0" * 64,
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "Qwen3-0.6B-Q8_0.gguf").write_bytes(b"local-weight")
            result = benchmark.verify_candidate_artifacts(candidate, Path(temp_dir))
        self.assertFalse(result["verified"])
        self.assertIn("checksum_mismatch:Qwen3-0.6B-Q8_0.gguf", result["errors"])

    def test_hyperclovax_requires_exact_license_approval(self):
        candidate = next(
            item
            for item in load_registry()["candidates"]
            if item["candidate_id"] == "hyperclovax-seed-05b-q4km"
        )
        approved, reason = benchmark._license_approved(candidate, None)
        self.assertFalse(approved)
        self.assertEqual(reason, "license_rejected")
        approvals = {
            "approvals": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "revision": candidate["revision"],
                    "license_url": candidate["license"]["url"],
                    "accepted": True,
                    "approved_by": "benchmark-owner",
                    "approved_at": "2026-08-16T00:00:00+09:00",
                    "notice_display_plan": "README and runtime notice",
                }
            ]
        }
        approved, reason = benchmark._license_approved(candidate, approvals)
        self.assertTrue(approved)
        self.assertIsNone(reason)

    def test_unapproved_conversion_is_blocked_before_checkout_or_download(self):
        registry = load_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = benchmark.prepare_candidates(
                registry,
                ["hyperclovax-seed-05b-q4km"],
                Path(temp_dir) / "models",
                approvals=None,
                download=False,
                convert=True,
                llama_cpp_root=Path(temp_dir) / "missing-checkout",
            )
        candidate = result["candidates"][0]
        self.assertEqual(candidate["status"], "license_rejected")
        self.assertFalse(candidate["download_executed"])
        self.assertFalse(candidate["conversion_executed"])

    def test_prepare_without_download_handles_non_conversion_candidate(self):
        registry = load_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = benchmark.prepare_candidates(
                registry,
                ["qwen3-06b-q8"],
                Path(temp_dir) / "models",
                approvals=None,
                download=False,
                convert=False,
            )
        candidate = result["candidates"][0]
        self.assertEqual(candidate["status"], "blocked")
        self.assertFalse(candidate["download_executed"])
        self.assertEqual(candidate["conversion_commands"], [])

    def test_secret_and_absolute_path_are_removed(self):
        value = {
            "HF_TOKEN": "hf_should_never_persist",
            "authorization": "Bearer super-secret",
            "log": "HF_TOKEN=hf_inline_secret",
            "host_path": "C:\\Users\\private-user\\models\\weight.gguf",
        }
        rendered = json.dumps(benchmark.scrub_sensitive(value), ensure_ascii=False)
        self.assertNotIn("hf_should_never_persist", rendered)
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn("hf_inline_secret", rendered)
        self.assertNotIn("private-user", rendered)

    def test_resource_parsers(self):
        memory = benchmark.parse_proc_meminfo(
            "MemTotal:       4096000 kB\nMemAvailable:    800000 kB\nSwapTotal:      1024000 kB\nSwapFree:       1000000 kB\n"
        )
        self.assertEqual(memory["MemTotal"], 4096000 * 1024)
        gpu = benchmark.parse_nvidia_smi_csv("Test GPU, 8192, 256, 600.01\n")
        self.assertEqual(gpu[0]["vram_total_bytes"], 8192 * 1024 * 1024)

    def test_stub_failures_all_fail_closed(self):
        results = benchmark.run_stub_checks()
        self.assertEqual(len(results), 6)
        self.assertTrue(all(row["fail_closed"] for row in results))
        self.assertTrue(all(row["selected_product_id"] is None for row in results))

    def test_timeout_and_malformed_output_do_not_select(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        case = load_suite()["cases"][0]
        payload = benchmark.build_case_payloads(case)["C"]
        with tempfile.TemporaryDirectory() as temp_dir:
            timeout = benchmark._call_record(
                TimeoutAdapter(), candidate, case, "C", payload, "correctness", 0, Path(temp_dir), 3584
            )
            malformed = benchmark._call_record(
                MalformedAdapter(), candidate, case, "C", payload, "correctness", 0, Path(temp_dir), 3584
            )
        self.assertEqual(timeout["failure_reason"], "timeout")
        self.assertIsNone(timeout["selected_product_id"])
        self.assertEqual(malformed["failure_reason"], "malformed_json")
        self.assertIsNone(malformed["selected_product_id"])

    def test_auxiliary_signal_must_be_grounded_by_allowlisted_codes(self):
        case = load_suite()["cases"][0]
        payload = benchmark.build_case_payloads(case)["C"]
        output = benchmark._valid_stub_output(payload, case["expected_product_id"])
        output["reason_codes"] = ["catalog_tag_alignment"]
        output["evidence"] = [
            {
                "code": "product_tag_match",
                "product_id": case["expected_product_id"],
                "evidence_refs": output["evidence"][0]["evidence_refs"],
                "statement": "검수된 catalog tag만 사용했습니다.",
            }
        ]
        validation = benchmark.validate_model_output(output, payload, case)
        self.assertFalse(validation["passed"])
        self.assertFalse(validation["psychology_auxiliary_signal_grounded"])
        self.assertIn("psychology_auxiliary_signal_not_grounded", validation["violations"])

    def test_input_too_large_never_calls_model(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        case = load_suite()["cases"][0]
        payload = benchmark.build_case_payloads(case)["C"]
        adapter = OversizedInputAdapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            row = benchmark._call_record(
                adapter, candidate, case, "C", payload, "correctness", 0, Path(temp_dir), 3584
            )
        self.assertEqual(row["failure_reason"], "input_too_large")
        self.assertFalse(row["model_called"])
        self.assertEqual(adapter.generate_count, 0)

    def test_run_plan_makes_135_correctness_calls_and_zero_blocked_calls(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        inventory = {
            "os": "linux",
            "architecture": "x86_64",
            "ram_available_bytes": 900_000_000,
            "gpus": [{"name": "Test GPU", "vram_total_bytes": 16 * 1024**3}],
        }
        adapter = DeterministicAdapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            run = benchmark.run_suite(
                registry,
                load_suite(),
                candidate,
                "colab-gpu",
                adapter,
                Path(temp_dir),
                inventory,
                ready_preparation(candidate["candidate_id"]),
                cold_start_ms=[2000.0, 2100.0, 2050.0],
            )
        correctness = [row for row in run["results"] if row["phase"] == "correctness"]
        no_calls = [row for row in run["results"] if row["phase"] == "no_call"]
        self.assertEqual(len(correctness), 135)
        self.assertEqual(len(no_calls), 3)
        self.assertTrue(all(not row["model_called"] for row in no_calls))
        self.assertEqual(adapter.generate_count, 168)  # 135 correctness + 3 warmup + 30 measured

    def test_smoke_mode_is_fast_triage_and_never_selection_eligible(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        inventory = {
            "os": "linux",
            "architecture": "x86_64",
            "ram_available_bytes": 900_000_000,
            "gpus": [{"name": "Test GPU", "vram_total_bytes": 16 * 1024**3}],
        }
        adapter = DeterministicAdapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            run = benchmark.run_suite(
                registry,
                load_suite(),
                candidate,
                "colab-gpu",
                adapter,
                Path(temp_dir),
                inventory,
                ready_preparation(candidate["candidate_id"]),
                cold_start_ms=[2000.0],
                run_mode="smoke",
            )
        run["resources"]["persistent_swap_growth_bytes"] = 0
        run["resources"].update(
            {
                "runtime_pid_monitored": True,
                "gpu_inventory": [{"name": "Test GPU", "vram_total_bytes": 16 * 1024**3}],
                "peak_vram_bytes": 8 * 1024**3,
                "memory_limit_bytes": 2_684_354_560,
                "peak_rss_bytes": 2_000_000_000,
                "process_restart_count": 0,
            }
        )
        correctness = [row for row in run["results"] if row["phase"] == "correctness"]
        no_calls = [row for row in run["results"] if row["phase"] == "no_call"]
        self.assertEqual(len(correctness), 4)
        self.assertEqual(len(no_calls), 1)
        self.assertEqual(adapter.generate_count, 4)
        score = benchmark.score_run(run, registry)
        self.assertTrue(score["smoke_gate"]["passed"])
        self.assertFalse(score["smoke_gate"]["selection_eligible"])
        self.assertEqual(score["automatic_hard_gate"]["eligible_combinations"], [])
        self.assertIsNone(score["selected_model"])

    def test_non_colab_profile_is_rejected(self):
        registry = load_registry()
        candidate = next(
            item
            for item in registry["candidates"]
            if item["candidate_id"] == "qwen35-9b-colab-ref"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(benchmark.BenchmarkError):
                benchmark.run_suite(
                    registry,
                    load_suite(),
                    candidate,
                    "gabia-cpu",
                    DeterministicAdapter(),
                    Path(temp_dir),
                    {"os": "linux", "architecture": "x86_64", "ram_available_bytes": 900_000_000},
                    ready_preparation(candidate["candidate_id"]),
                    cold_start_ms=[2000.0],
                    run_mode="smoke",
                )

    def test_replay_instability_and_no_call_violation_close_gate(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        good = benchmark.score_run(passing_run(candidate), registry)
        self.assertTrue(
            all(row["hard_gate_passed"] for row in good["automatic_hard_gate"]["combinations"])
        )
        unstable_run = passing_run(candidate)
        unstable_run["results"][0]["selected_product_id"] = "mcm-pina-vanity-case-studded-calfskin"
        unstable = benchmark.score_run(unstable_run, registry)
        variant_a = unstable["automatic_hard_gate"]["combinations"][0]
        self.assertFalse(variant_a["checks"]["replay_stability_5_of_5"])
        self.assertFalse(variant_a["hard_gate_passed"])

        bad_no_call_run = passing_run(candidate)
        no_call = next(row for row in bad_no_call_run["results"] if row["phase"] == "no_call")
        no_call["model_called"] = True
        no_call["selected_product_id"] = candidate["model_id"]
        bad_no_call = benchmark.score_run(bad_no_call_run, registry)
        self.assertTrue(
            all(
                not row["checks"]["no_call_gate_3_of_3"]
                for row in bad_no_call["automatic_hard_gate"]["combinations"]
            )
        )
        self.assertIsNone(bad_no_call["selected_model"])

    def test_only_loopback_runtime_endpoints_are_allowed(self):
        benchmark.ensure_loopback_url("http://127.0.0.1:8080/v1/chat/completions")
        benchmark.ensure_loopback_url("http://[::1]:8080/tokenize")
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.ensure_loopback_url("https://example.com/v1/chat/completions")

    def test_hf_commands_never_contain_token_argument(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-17b-q8"
        )
        commands = benchmark.hf_command_plan(candidate, Path("models") / candidate["candidate_id"])
        rendered = " ".join(part for command in commands for part in command).lower()
        self.assertIn("--revision", rendered)
        self.assertIn("--dry-run", rendered)
        self.assertIn("cache verify", rendered)
        self.assertNotIn("--token", rendered)
        self.assertNotIn("hf_token", rendered)

    def test_report_never_claims_selection(self):
        registry = load_registry()
        candidate = next(
            item for item in registry["candidates"] if item["candidate_id"] == "qwen3-06b-q8"
        )
        score = benchmark.score_run(passing_run(candidate), registry)
        report = benchmark.render_report(score, registry)
        self.assertIsNone(score["selected_model"])
        self.assertIn("selected_model=null", report)
        self.assertIn("블라인드", report)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "experiments" / "recommendation"
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

import openai_benchmark


class ApproxCounter:
    def count_text(self, text: str) -> int:
        return max(1, len(text) // 4)


class FixedCounter:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def count_text(self, text: str) -> int:
        return self.tokens


class DeterministicResponsesClient:
    def __init__(self) -> None:
        self.calls = 0
        self.bodies: list[Mapping[str, Any]] = []

    def create(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        self.bodies.append(body)
        payload = json.loads(body["input"][1]["content"])
        product_id = payload["evidence"]["summary"][0]["product_id"]
        output = openai_benchmark.base._valid_stub_output(payload, product_id)
        summary = next(
            item for item in payload["evidence"]["summary"] if item["product_id"] == product_id
        )
        if summary.get("gaze", {}).get("return_candidate_count", 0) > 0:
            output["reason_codes"].insert(1, "return_candidate_support")
            output["evidence"].append(
                {
                    "code": "return_candidate",
                    "product_id": product_id,
                    "evidence_refs": output["evidence"][0]["evidence_refs"],
                    "statement": "합성 입력에서 같은 상품으로 돌아온 관찰이 기록되었습니다.",
                }
            )
        return {
            "status": "completed",
            "model": "gpt-5.6-luna",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(output, ensure_ascii=False),
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 3000,
                "output_tokens": 400,
                "output_tokens_details": {"reasoning_tokens": 180},
            },
        }


class IncompleteResponsesClient:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        return {
            "status": "incomplete",
            "model": "gpt-5.6-luna",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
            "usage": {"input_tokens": 3000, "output_tokens": 4096},
        }


def load_config() -> dict[str, Any]:
    config = openai_benchmark.load_config()
    config["price_snapshot"]["as_of"] = dt.date.today().isoformat()
    return config


def all_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_keys(child)


class OpenAIRecommendationBenchmarkTests(unittest.TestCase):
    def test_versioned_text_hash_is_stable_across_line_endings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lf = Path(temp_dir) / "lf.txt"
            crlf = Path(temp_dir) / "crlf.txt"
            lf.write_bytes(b"one\ntwo\n")
            crlf.write_bytes(b"one\r\ntwo\r\n")
            self.assertEqual(
                openai_benchmark.sha256_file(lf),
                openai_benchmark.sha256_file(crlf),
            )
        self.assertEqual(
            openai_benchmark.sha256_file(openai_benchmark.PROMPT_PATH),
            "bc1186d1e3f1e908e8a865ae8f89c35f7e6c3172ccd010018101141d5a350149",
        )

    def test_selected_v4_prompt_makes_conflict_and_return_grounding_mandatory(self):
        self.assertEqual(openai_benchmark.PROMPT_PATH.name, "central-recommender.ko.v4.txt")
        prompt = openai_benchmark.PROMPT_PATH.read_text(encoding="utf-8")
        self.assertIn("gaze와 expression이 충돌", prompt)
        self.assertIn("위 네 코드를 모두 넣는다", prompt)
        self.assertIn("return_candidate_count가 1 이상", prompt)
        self.assertIn("감정, 성격, 심리 상태", prompt)

    def test_fixed_configuration_and_request_envelope(self):
        config = load_config()
        result = openai_benchmark.validate_config(config)
        self.assertEqual(result["model_id"], "gpt-5.6-luna")
        self.assertEqual(result["reasoning_effort"], "max")
        case = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)["cases"][0]
        payload = openai_benchmark.base.build_case_payloads(case)["C"]
        body = openai_benchmark.build_request(payload, config)
        self.assertEqual(body["reasoning"], {"effort": "max", "context": "current_turn"})
        self.assertFalse(body["store"])
        self.assertNotIn("max_output_tokens", body)
        self.assertIsNone(config["timeout_seconds"])
        self.assertEqual(config["latency_gate"], {"enforced": False, "record_only": True})
        self.assertNotIn("tools", body)
        self.assertNotIn("previous_response_id", body)
        self.assertNotIn("conversation", body)
        self.assertTrue(body["text"]["format"]["strict"])

    def test_request_sends_validated_full_variant_c_payload(self):
        config = load_config()
        case = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)["cases"][0]
        payload = openai_benchmark.base.build_case_payloads(case)["C"]
        body = openai_benchmark.build_request(payload, config)
        sent = json.loads(body["input"][1]["content"])
        self.assertEqual(sent, payload)
        self.assertEqual(sent["evidence"]["input_variant"], "C")
        self.assertNotIn("timeline", sent["evidence"])

    def test_diagnostic_request_omits_provider_output_token_cap(self):
        config = load_config()
        config["maximum_output_tokens"] = None
        config["maximum_output_text_tokens"] = None
        case = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)["cases"][0]
        payload = openai_benchmark.base.build_case_payloads(case)["C"]
        body = openai_benchmark.build_request(payload, config)
        self.assertNotIn("max_output_tokens", body)
        self.assertLess(
            openai_benchmark._maximum_call_cost({**config, "model_max_output_tokens": 128_000}),
            0.2,
        )

    def test_dynamic_schema_pins_catalog_windows_and_tags(self):
        suite = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)
        case = suite["cases"][0]
        payload = openai_benchmark.base.build_case_payloads(case)["C"]
        schema = openai_benchmark.dynamic_output_schema(payload)
        product_ids = [product["product_id"] for product in payload["products"]]
        self.assertEqual(schema["properties"]["product_id"]["enum"], product_ids)
        evidence = schema["properties"]["evidence"]["items"]["properties"]
        self.assertEqual(evidence["product_id"]["enum"], product_ids)
        refs = evidence["evidence_refs"]["items"]["properties"]
        self.assertEqual(refs["kind"]["enum"], ["window"])
        self.assertEqual(
            refs["ref_id"]["enum"],
            [window["window_id"] for window in payload["evidence"]["evidence_windows"]],
        )
        self.assertNotIn("$schema", set(all_keys(schema)))
        self.assertNotIn("uniqueItems", set(all_keys(schema)))

    def test_only_variant_c_without_timeline_is_allowed(self):
        config = load_config()
        case = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)["cases"][0]
        payloads = openai_benchmark.base.build_case_payloads(case)
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "only_variant_c"):
            openai_benchmark.build_request(payloads["A"], config)
        bad = copy.deepcopy(payloads["C"])
        bad["evidence"]["timeline"] = []
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "timeline"):
            openai_benchmark.build_request(bad, config)

    def test_offline_validation_covers_nine_calls_and_three_blocks(self):
        result = openai_benchmark.validate_offline(load_config(), ApproxCounter())
        self.assertEqual(result["offline_validation"], "passed")
        self.assertEqual(len(result["callable_input_tokens"]), 9)
        self.assertEqual(result["suite"]["no_call_case_count"], 3)
        self.assertLessEqual(result["maximum_estimated_input_tokens"], 6000)
        self.assertLess(result["maximum_planned_cost_usd"], 5.0)

    def test_oversized_input_never_calls_client(self):
        config = load_config()
        suite = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)
        case = suite["cases"][0]
        payload = openai_benchmark.base.build_case_payloads(case)["C"]
        client = DeterministicResponsesClient()
        tracker = openai_benchmark.BudgetTracker(5.0)
        row = openai_benchmark.call_case(
            client, FixedCounter(6001), tracker, config, case, payload, 0
        )
        self.assertFalse(row["model_called"])
        self.assertEqual(row["failure_reason"], "input_too_large")
        self.assertEqual(client.calls, 0)
        self.assertEqual(tracker.calls, 0)

    def test_smoke_then_full_uses_exactly_27_calls(self):
        client = DeterministicResponsesClient()
        result = openai_benchmark.run_evaluation(
            client, ApproxCounter(), load_config(), 5.0, "baseline"
        )
        self.assertEqual(client.calls, 27)
        self.assertEqual(result["live_call_count"], 27)
        self.assertTrue(result["smoke_passed"])
        self.assertTrue(result["gate"]["quality_passed"])
        self.assertTrue(result["gate"]["replay_stability_3_of_3"])
        self.assertTrue(result["gate"]["exact_replay_stability"])
        self.assertTrue(result["gate"]["no_call_gate_3_of_3"])
        self.assertFalse(result["gate"]["latency_gate_enforced"])
        self.assertIsNone(result["gate"]["latency_passed"])
        self.assertTrue(result["gate"]["passed"])
        no_calls = [row for row in result["results"] if row["variant"] == "preflight"]
        self.assertEqual(len(no_calls), 3)
        self.assertTrue(all(not row["model_called"] for row in no_calls))
        for body in client.bodies:
            self.assertEqual(body["model"], "gpt-5.6-luna")
            self.assertEqual(body["reasoning"]["effort"], "max")
        probes = {row["semantic_probe"] for row in result["results"] if row["model_called"]}
        self.assertIn("catalog_order_permutation", probes)
        self.assertIn("return_candidate_ablation", probes)

    def test_diagnostic_smoke_uses_four_calls_without_relaxing_production_gate(self):
        client = DeterministicResponsesClient()
        config = load_config()
        result = openai_benchmark.run_diagnostic_smoke(
            client, ApproxCounter(), config, 5.0, 30.0
        )
        self.assertEqual(client.calls, 4)
        self.assertEqual(result["live_call_count"], 4)
        self.assertTrue(result["smoke_passed"])
        self.assertEqual(result["timeout_seconds"], 30.0)
        self.assertIsNone(result["production_timeout_seconds"])
        self.assertFalse(result["gate"]["production_latency_gate_evaluated"])
        self.assertTrue(result["production_status"].startswith("diagnostic_smoke"))

    def test_diagnostic_full_uses_27_calls_and_no_request_token_cap(self):
        client = DeterministicResponsesClient()
        result = openai_benchmark.run_diagnostic_full(
            client, ApproxCounter(), load_config(), 5.0, 90.0
        )
        self.assertEqual(client.calls, 27)
        self.assertEqual(result["live_call_count"], 27)
        self.assertTrue(result["smoke_passed"])
        self.assertTrue(result["gate"]["quality_passed"])
        self.assertTrue(result["gate"]["diagnostic_passed"])
        self.assertTrue(result["gate"]["replay_stability_3_of_3"])
        self.assertTrue(result["gate"]["exact_replay_stability"])
        self.assertLess(result["maximum_planned_cost_usd"], 5.0)
        self.assertTrue(all("max_output_tokens" not in body for body in client.bodies))

    def test_diagnostic_timeout_bounds_are_fail_closed(self):
        config = load_config()
        no_timeout_result = openai_benchmark.run_diagnostic_smoke(
            DeterministicResponsesClient(), ApproxCounter(), config, 5.0, None
        )
        self.assertIsNone(no_timeout_result["timeout_seconds"])
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "diagnostic_timeout"):
            openai_benchmark.run_diagnostic_smoke(
                DeterministicResponsesClient(), ApproxCounter(), config, 5.0, 10.0
            )
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "diagnostic_timeout"):
            openai_benchmark.run_diagnostic_smoke(
                DeterministicResponsesClient(), ApproxCounter(), config, 5.0, 121.0
            )

    def test_diagnostic_cli_no_timeout_is_explicit_and_exclusive(self):
        args = openai_benchmark.parse_args(
            [
                "diagnostic-full",
                "--live",
                "--synthetic-only",
                "--budget-usd",
                "5",
                "--no-timeout",
                "--output",
                "artifacts/recommendation/openai-luna-max/test.json",
            ]
        )
        self.assertTrue(args.no_timeout)
        with self.assertRaises(SystemExit):
            openai_benchmark.parse_args(
                [
                    "diagnostic-full",
                    "--live",
                    "--synthetic-only",
                    "--budget-usd",
                    "5",
                    "--no-timeout",
                    "--timeout-seconds",
                    "90",
                    "--output",
                    "artifacts/recommendation/openai-luna-max/test.json",
                ]
            )

    def test_output_token_limit_is_removed_but_byte_limit_remains(self):
        config = load_config()
        response = {
            "status": "completed",
            "model": "gpt-5.6-luna",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "x" * 3000}],
                }
            ],
            "usage": {"input_tokens": 3000, "output_tokens": 400},
        }
        extracted = openai_benchmark.extract_response(response, config, ApproxCounter())
        self.assertEqual(len(extracted["text"]), 3000)
        oversized = copy.deepcopy(response)
        oversized["output"][0]["content"][0]["text"] = "x" * 17000
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "oversized_json"):
            openai_benchmark.extract_response(oversized, config, ApproxCounter())

    def test_incomplete_smoke_fails_closed_and_stops_after_four_calls(self):
        client = IncompleteResponsesClient()
        result = openai_benchmark.run_evaluation(
            client, ApproxCounter(), load_config(), 5.0, "baseline"
        )
        self.assertEqual(client.calls, 4)
        self.assertFalse(result["smoke_passed"])
        self.assertEqual(result["production_status"], "benchmark_failed")
        called = [row for row in result["results"] if row["model_called"]]
        self.assertTrue(all(row["selected_product_id"] is None for row in called))
        self.assertTrue(
            all(row["failure_reason"] == "incomplete:max_output_tokens" for row in called)
        )

    def test_return_candidate_ablation_must_change_grounding(self):
        config = load_config()
        suite = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)
        case = next(item for item in suite["cases"] if item["case_id"] == "normal-gaze-dominant")
        payload = openai_benchmark.base.build_case_payloads(case)["C"]
        ablated, probe = openai_benchmark.payload_for_repeat(case, payload, 2)
        output = openai_benchmark.base._valid_stub_output(ablated, case["expected_product_id"])
        output["reason_codes"].append("return_candidate_support")
        output["evidence"].append(
            {
                "code": "return_candidate",
                "product_id": case["expected_product_id"],
                "evidence_refs": output["evidence"][0]["evidence_refs"],
                "statement": "존재하지 않는 재방문을 주장합니다.",
            }
        )

        class StaleGroundingClient:
            def create(self, body):
                return {
                    "status": "completed",
                    "model": "gpt-5.6-luna",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(output, ensure_ascii=False),
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 3000, "output_tokens": 300},
                }

        row = openai_benchmark.call_case(
            StaleGroundingClient(),
            ApproxCounter(),
            openai_benchmark.BudgetTracker(5.0),
            config,
            case,
            ablated,
            2,
            probe,
        )
        self.assertFalse(row["passed"])
        self.assertIsNone(row["selected_product_id"])
        self.assertIn("ablated_return_candidate_still_claimed", row["validation"]["violations"])

    def test_validation_artifact_records_required_and_observed_codes(self):
        config = load_config()
        suite = openai_benchmark.base.load_json(openai_benchmark.base.CASES_PATH)
        case = next(
            item for item in suite["cases"] if item["case_id"] == "normal-conflicting-signals"
        )
        payload = openai_benchmark.base.build_case_payloads(case)["C"]
        row = openai_benchmark.call_case(
            DeterministicResponsesClient(),
            ApproxCounter(),
            openai_benchmark.BudgetTracker(5.0),
            config,
            case,
            payload,
            0,
        )
        self.assertEqual(
            row["validation"]["required_reason_codes"],
            ["observable_action_support", "observed_attention_lead"],
        )
        self.assertEqual(
            row["validation"]["required_evidence_codes"],
            ["face_action_change", "observed_attention"],
        )
        self.assertIn("observed_attention_lead", row["validation"]["observed_reason_codes"])
        self.assertIn("face_action_change", row["validation"]["observed_evidence_codes"])

    def test_refusal_and_multiple_output_text_are_rejected(self):
        config = load_config()
        counter = ApproxCounter()
        refusal = {
            "status": "completed",
            "model": "gpt-5.6-luna",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "refusal"):
            openai_benchmark.extract_response(refusal, config, counter)
        multiple = copy.deepcopy(refusal)
        multiple["output"][0]["content"] = [
            {"type": "output_text", "text": "{}"},
            {"type": "output_text", "text": "{}"},
        ]
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "output_text_count"):
            openai_benchmark.extract_response(multiple, config, counter)

    def test_budget_and_artifact_path_are_fail_closed(self):
        config = load_config()
        with self.assertRaisesRegex(openai_benchmark.OpenAIBenchmarkError, "planned_budget"):
            openai_benchmark.run_evaluation(
                DeterministicResponsesClient(), ApproxCounter(), config, 0.01, "baseline"
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = Path(temp_dir) / "run.json"
            with self.assertRaisesRegex(
                openai_benchmark.OpenAIBenchmarkError, "artifact_root"
            ):
                openai_benchmark._artifact_output_path(str(outside))

    def test_optimized_attempt_is_disabled_when_latency_is_not_a_gate(self):
        config = load_config()
        with self.assertRaisesRegex(
            openai_benchmark.OpenAIBenchmarkError, "latency_not_a_gate"
        ):
            openai_benchmark.validate_optimized_attempt({}, config, ApproxCounter())

    def test_live_cli_requires_explicit_flags_before_key(self):
        output = openai_benchmark.ARTIFACT_ROOT / "test.json"
        with mock.patch.dict("os.environ", {}, clear=True):
            code = openai_benchmark.main(
                ["run", "--synthetic-only", "--budget-usd", "5", "--output", str(output)]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()

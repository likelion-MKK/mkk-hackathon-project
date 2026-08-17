"""Fail-closed synthetic benchmark for the fixed OpenAI Luna Max configuration.

The live command is deliberately gated by explicit flags and OPENAI_API_KEY.
It never sends customer evidence and never retries a provider request.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONFIG_PATH = HERE / "openai-luna-max.v2.json"
PROMPT_PATH = HERE / "prompts" / "central-recommender.ko.v4.txt"
ARTIFACT_ROOT = ROOT / "artifacts" / "recommendation" / "openai-luna-max"


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location(
        "mcm_recommendation_self_hosted_benchmark", HERE / "benchmark.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could_not_load_base_benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()


class OpenAIBenchmarkError(RuntimeError):
    """Expected fail-closed benchmark error with a non-secret reason code."""


class TokenCounter(Protocol):
    def count_text(self, text: str) -> int: ...


class ResponsesClient(Protocol):
    def create(self, body: Mapping[str, Any]) -> Mapping[str, Any]: ...


class TiktokenCounter:
    def __init__(self, encoding_name: str) -> None:
        try:
            import tiktoken
        except ImportError as exc:
            raise OpenAIBenchmarkError("tokenizer_unavailable") from exc
        self._encoding = tiktoken.get_encoding(encoding_name)

    def count_text(self, text: str) -> int:
        return len(self._encoding.encode(text))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    """Hash versioned UTF-8 text with LF line endings on every platform."""
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_config() -> dict[str, Any]:
    value = load_json(CONFIG_PATH)
    if not isinstance(value, dict):
        raise OpenAIBenchmarkError("config_root_not_object")
    return value


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "config_version": "openai-luna-max-production-candidate-v2",
        "model_id": "gpt-5.6-luna",
        "input_variant": "C",
        "store": False,
        "maximum_output_tokens": None,
        "model_max_output_tokens": 128_000,
        "maximum_output_text_tokens": None,
        "maximum_output_text_bytes": 16384,
        "target_input_tokens": 4000,
        "maximum_input_tokens": 6000,
        "timeout_seconds": None,
        "retries": 0,
        "callable_case_repeats": 3,
        "maximum_live_calls": 27,
        "budget_usd": 5.0,
        "data_scope": "synthetic_only",
        "selection_status": "selected_pending_integration",
        "production_approved": False,
    }
    for key, wanted in expected.items():
        if config.get(key) != wanted:
            raise OpenAIBenchmarkError(f"config_drift:{key}")
    if config.get("reasoning") != {"effort": "max", "context": "current_turn"}:
        raise OpenAIBenchmarkError("config_drift:reasoning")
    if config.get("api", {}).get("url") != "https://api.openai.com/v1/responses":
        raise OpenAIBenchmarkError("config_drift:api_url")
    latency = config.get("latency_gate", {})
    if latency != {"enforced": False, "record_only": True}:
        raise OpenAIBenchmarkError("config_drift:latency_gate")
    price = config.get("price_snapshot", {})
    required_price_fields = {
        "as_of",
        "maximum_age_days",
        "input_usd_per_million_tokens",
        "cached_input_usd_per_million_tokens",
        "output_usd_per_million_tokens",
        "source_url",
    }
    if set(price) != required_price_fields or price.get("source_url") != (
        "https://developers.openai.com/api/docs/models/gpt-5.6-luna"
    ):
        raise OpenAIBenchmarkError("price_snapshot_invalid")
    if any(
        not isinstance(price.get(key), (int, float)) or price[key] < 0
        for key in (
            "input_usd_per_million_tokens",
            "cached_input_usd_per_million_tokens",
            "output_usd_per_million_tokens",
        )
    ):
        raise OpenAIBenchmarkError("price_snapshot_invalid")
    return {
        "config_valid": True,
        "model_id": config["model_id"],
        "reasoning_effort": config["reasoning"]["effort"],
        "maximum_live_calls": config["maximum_live_calls"],
    }


def validate_price_snapshot(config: Mapping[str, Any], today: dt.date | None = None) -> None:
    snapshot = config["price_snapshot"]
    try:
        as_of = dt.date.fromisoformat(snapshot["as_of"])
    except (TypeError, ValueError) as exc:
        raise OpenAIBenchmarkError("price_snapshot_invalid") from exc
    current = today or dt.date.today()
    age = (current - as_of).days
    if age < 0 or age > snapshot["maximum_age_days"]:
        raise OpenAIBenchmarkError("price_snapshot_stale")


def _strip_api_unsupported_keywords(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_api_unsupported_keywords(child)
            for key, child in value.items()
            if key not in {"$schema", "uniqueItems"}
        }
    if isinstance(value, list):
        return [_strip_api_unsupported_keywords(child) for child in value]
    return value


def dynamic_output_schema(payload: Mapping[str, Any]) -> dict[str, Any]:
    products = payload.get("products")
    if not isinstance(products, list) or len(products) != 10:
        raise OpenAIBenchmarkError("catalog_must_contain_exactly_ten")
    product_ids = [item.get("product_id") for item in products if isinstance(item, dict)]
    if len(product_ids) != 10 or len(set(product_ids)) != 10 or any(not item for item in product_ids):
        raise OpenAIBenchmarkError("catalog_must_contain_exactly_ten")
    tags = sorted(
        {
            tag
            for product in products
            for tag in product.get("controlled_tags", [])
            if isinstance(tag, str) and tag
        }
    )
    if not tags:
        raise OpenAIBenchmarkError("catalog_tags_missing")
    windows = payload.get("evidence", {}).get("evidence_windows") or []
    window_ids = [item.get("window_id") for item in windows if isinstance(item, dict)]
    if not window_ids or any(not item for item in window_ids):
        raise OpenAIBenchmarkError("evidence_windows_missing")

    schema = _strip_api_unsupported_keywords(copy.deepcopy(base.RAW_OUTPUT_SCHEMA))
    schema["properties"]["product_id"] = {"type": "string", "enum": product_ids}
    evidence_properties = schema["properties"]["evidence"]["items"]["properties"]
    evidence_properties["product_id"] = {"type": "string", "enum": product_ids}
    reference_properties = evidence_properties["evidence_refs"]["items"]["properties"]
    reference_properties["kind"] = {"type": "string", "enum": ["window"]}
    reference_properties["ref_id"] = {"type": "string", "enum": window_ids}
    schema["properties"]["style"]["properties"]["matched_tags"]["items"] = {
        "type": "string",
        "enum": tags,
    }
    return schema


def build_request(payload: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("evidence", {}).get("input_variant") != "C":
        raise OpenAIBenchmarkError("only_variant_c_is_allowed")
    if payload.get("evidence", {}).get("timeline") is not None:
        raise OpenAIBenchmarkError("timeline_must_not_be_sent")
    privacy = list(base._variant_module().privacy_violations(payload))
    if privacy:
        raise OpenAIBenchmarkError("privacy_boundary_violation")
    body = {
        "model": config["model_id"],
        "input": [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {"role": "user", "content": canonical_json(payload)},
        ],
        "reasoning": dict(config["reasoning"]),
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "mcm_central_recommendation_v1",
                "strict": True,
                "schema": dynamic_output_schema(payload),
            }
        },
    }
    if config.get("maximum_output_tokens") is not None:
        body["max_output_tokens"] = config["maximum_output_tokens"]
    return body


def estimate_request_tokens(
    body: Mapping[str, Any], counter: TokenCounter, config: Mapping[str, Any]
) -> int:
    tokens = counter.count_text(canonical_json(body))
    if tokens > config["maximum_input_tokens"]:
        raise OpenAIBenchmarkError("input_too_large")
    return tokens


def _maximum_call_cost(config: Mapping[str, Any]) -> float:
    price = config["price_snapshot"]
    output_token_ceiling = config.get("maximum_output_tokens")
    if output_token_ceiling is None:
        output_token_ceiling = config.get("model_max_output_tokens", 128_000)
    return (
        config["maximum_input_tokens"] * price["input_usd_per_million_tokens"]
        + output_token_ceiling * price["output_usd_per_million_tokens"]
    ) / 1_000_000


def _usage_cost(usage: Mapping[str, Any], config: Mapping[str, Any]) -> float:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if not isinstance(input_tokens, int) or input_tokens < 0:
        raise OpenAIBenchmarkError("provider_usage_invalid")
    if not isinstance(output_tokens, int) or output_tokens < 0:
        raise OpenAIBenchmarkError("provider_usage_invalid")
    price = config["price_snapshot"]
    return (
        input_tokens * price["input_usd_per_million_tokens"]
        + output_tokens * price["output_usd_per_million_tokens"]
    ) / 1_000_000


@dataclass
class BudgetTracker:
    limit_usd: float
    spent_usd: float = 0.0
    calls: int = 0

    def ensure_next_call(self, worst_call_usd: float, maximum_calls: int) -> None:
        if self.calls >= maximum_calls:
            raise OpenAIBenchmarkError("maximum_live_calls_exceeded")
        if self.spent_usd + worst_call_usd > self.limit_usd + 1e-12:
            raise OpenAIBenchmarkError("budget_would_be_exceeded")

    def record(self, cost_usd: float) -> None:
        self.calls += 1
        self.spent_usd += cost_usd
        if self.spent_usd > self.limit_usd + 1e-12:
            raise OpenAIBenchmarkError("budget_exceeded")


class OpenAIResponsesHTTPClient:
    def __init__(self, api_key: str, config: Mapping[str, Any]) -> None:
        if not api_key.strip():
            raise OpenAIBenchmarkError("missing_openai_api_key")
        self._api_key = api_key
        self._url = config["api"]["url"]
        self._timeout = config["timeout_seconds"]
        self._maximum_bytes = config["maximum_response_envelope_bytes"]

    def create(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        request = urllib.request.Request(
            self._url,
            data=canonical_json(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read(self._maximum_bytes + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise OpenAIBenchmarkError("provider_http_429") from exc
            if 500 <= exc.code <= 599:
                raise OpenAIBenchmarkError("provider_http_5xx") from exc
            raise OpenAIBenchmarkError(f"provider_http_{exc.code}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise OpenAIBenchmarkError("timeout") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise OpenAIBenchmarkError("timeout") from exc
            raise OpenAIBenchmarkError("provider_unavailable") from exc
        if len(raw) > self._maximum_bytes:
            raise OpenAIBenchmarkError("response_envelope_too_large")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenAIBenchmarkError("provider_envelope_invalid") from exc
        if not isinstance(value, dict):
            raise OpenAIBenchmarkError("provider_envelope_invalid")
        return value


def extract_response(
    response: Mapping[str, Any], config: Mapping[str, Any], counter: TokenCounter
) -> dict[str, Any]:
    status = response.get("status")
    if status == "incomplete":
        reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
        raise OpenAIBenchmarkError(f"incomplete:{reason}")
    if status != "completed":
        raise OpenAIBenchmarkError("provider_response_not_completed")
    response_model = response.get("model")
    if not isinstance(response_model, str) or not (
        response_model == config["model_id"]
        or response_model.startswith(config["model_id"] + "-")
    ):
        raise OpenAIBenchmarkError("unexpected_response_model")
    texts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                raise OpenAIBenchmarkError("refusal")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if len(texts) != 1:
        raise OpenAIBenchmarkError("output_text_count_invalid")
    text = texts[0]
    if len(text.encode("utf-8")) > config["maximum_output_text_bytes"]:
        raise OpenAIBenchmarkError("oversized_json")
    maximum_output_text_tokens = config.get("maximum_output_text_tokens")
    if (
        maximum_output_text_tokens is not None
        and counter.count_text(text) > maximum_output_text_tokens
    ):
        raise OpenAIBenchmarkError("output_text_too_large")
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise OpenAIBenchmarkError("provider_usage_invalid")
    return {
        "text": text,
        "usage": usage,
        "response_model": response_model,
        "cost_usd": _usage_cost(usage, config),
    }


def _failure_row(case: Mapping[str, Any], repeat_index: int, reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "variant": "C",
        "repeat_index": repeat_index,
        "semantic_probe": "base",
        "status": "failed",
        "selected_product_id": None,
        "model_called": False,
        "failure_reason": reason,
        "passed": False,
    }


def payload_for_repeat(
    case: Mapping[str, Any], payload: Mapping[str, Any], repeat_index: int
) -> tuple[dict[str, Any], str]:
    value = copy.deepcopy(payload)
    if case["case_id"] == "normal-close-fixed-winner" and repeat_index == 1:
        value["products"] = list(reversed(value["products"]))
        return value, "catalog_order_permutation"
    if case["case_id"] == "normal-gaze-dominant" and repeat_index == 2:
        target = case["expected_product_id"]
        row = next(item for item in value["evidence"]["summary"] if item["product_id"] == target)
        row["gaze"]["return_candidate_count"] = 0
        return value, "return_candidate_ablation"
    return value, "exact_replay"


def semantic_probe_violations(
    output: Mapping[str, Any], case: Mapping[str, Any], repeat_index: int
) -> list[str]:
    if case["case_id"] != "normal-gaze-dominant":
        return []
    reason_codes = set(output.get("reason_codes", []))
    evidence_codes = {item.get("code") for item in output.get("evidence", [])}
    has_return_grounding = (
        "return_candidate_support" in reason_codes and "return_candidate" in evidence_codes
    )
    if repeat_index == 2 and has_return_grounding:
        return ["ablated_return_candidate_still_claimed"]
    if repeat_index != 2 and not has_return_grounding:
        return ["observed_return_candidate_not_grounded"]
    return []


def call_case(
    client: ResponsesClient,
    counter: TokenCounter,
    tracker: BudgetTracker,
    config: Mapping[str, Any],
    case: Mapping[str, Any],
    payload: Mapping[str, Any],
    repeat_index: int,
    semantic_probe: str = "base",
) -> dict[str, Any]:
    row = _failure_row(case, repeat_index, "unstarted")
    row["semantic_probe"] = semantic_probe
    row["payload_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    try:
        body = build_request(payload, config)
        input_tokens = estimate_request_tokens(body, counter, config)
    except OpenAIBenchmarkError as exc:
        row["failure_reason"] = str(exc)
        return row
    worst_cost = _maximum_call_cost(config)
    try:
        tracker.ensure_next_call(worst_cost, config["maximum_live_calls"])
    except OpenAIBenchmarkError as exc:
        row["failure_reason"] = str(exc)
        return row

    started = time.perf_counter()
    row["model_called"] = True
    cost_recorded = False
    try:
        response = client.create(body)
        latency_ms = (time.perf_counter() - started) * 1000
        extracted = extract_response(response, config, counter)
        cost_recorded = True
        tracker.record(extracted["cost_usd"])
        output = base.parse_strict_output(
            extracted["text"], maximum_bytes=config["maximum_output_text_bytes"]
        )
        validation = copy.deepcopy(base.validate_model_output(output, payload, case))
        auxiliary_spec = case.get("psychology_auxiliary_signal") or {}
        validation.update(
            {
                "required_reason_codes": sorted(
                    auxiliary_spec.get("required_reason_codes", [])
                ),
                "observed_reason_codes": sorted(set(output.get("reason_codes", []))),
                "required_evidence_codes": sorted(
                    auxiliary_spec.get("required_evidence_codes", [])
                ),
                "observed_evidence_codes": sorted(
                    {item.get("code") for item in output.get("evidence", [])}
                ),
            }
        )
        probe_violations = semantic_probe_violations(output, case, repeat_index)
        if probe_violations:
            validation["violations"] = sorted(set(validation["violations"] + probe_violations))
            validation["passed"] = False
        usage_within_limits = (
            extracted["usage"]["input_tokens"] <= config["maximum_input_tokens"]
            and (
                config.get("maximum_output_tokens") is None
                or extracted["usage"]["output_tokens"] <= config["maximum_output_tokens"]
            )
        )
        if not usage_within_limits:
            validation["violations"] = sorted(
                set(validation["violations"] + ["provider_usage_exceeded_limits"])
            )
            validation["passed"] = False
        row.update(
            {
                "latency_ms": round(latency_ms, 3),
                "input_tokens_estimated": input_tokens,
                "input_tokens": extracted["usage"]["input_tokens"],
                "output_tokens": extracted["usage"]["output_tokens"],
                "reasoning_tokens": (
                    extracted["usage"].get("output_tokens_details") or {}
                ).get("reasoning_tokens"),
                "cost_usd": extracted["cost_usd"],
                "response_model": extracted["response_model"],
                "observed_product_id": output.get("product_id"),
                "validation": validation,
                "failure_reason": None if validation["passed"] else "invalid_model_output",
                "status": "completed" if validation["passed"] else "failed",
                "selected_product_id": output.get("product_id") if validation["passed"] else None,
                "passed": validation["passed"],
            }
        )
    except (OpenAIBenchmarkError, base.BenchmarkError) as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        if not cost_recorded:
            tracker.record(worst_cost)
        row.update({"latency_ms": round(latency_ms, 3), "failure_reason": str(exc)})
    return row


def _preflight_rows(suite: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in suite["cases"]:
        if case["should_call_model"]:
            continue
        payload = base.build_case_payloads(case)["C"]
        reason = base.preflight_reason(payload)
        if reason != case["expected_failure_reason"]:
            raise OpenAIBenchmarkError(f"preflight_reason_drift:{case['case_id']}")
        rows.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "variant": "preflight",
                "repeat_index": 0,
                "status": case["expected_status"],
                "selected_product_id": None,
                "model_called": False,
                "failure_reason": reason,
                "passed": True,
            }
        )
    if len(rows) != 3:
        raise OpenAIBenchmarkError("preflight_case_count_invalid")
    return rows


def _percentile95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def evaluate_gate(
    rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any], full_run: bool
) -> dict[str, Any]:
    calls = [row for row in rows if row.get("model_called")]
    no_calls = [row for row in rows if row.get("variant") == "preflight"]
    latencies = [float(row["latency_ms"]) for row in calls if "latency_ms" in row]
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    exact_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in calls:
        grouped[str(row["case_id"])].append(row)
        exact_groups[(str(row["case_id"]), str(row.get("payload_sha256")))].append(row)
    stable = full_run and len(grouped) == 9 and all(
        len(case_rows) == 3
        and len({row.get("selected_product_id") for row in case_rows}) == 1
        and all(row.get("passed") is True for row in case_rows)
        for case_rows in grouped.values()
    )
    exact_replay_stable = full_run and all(
        len({row.get("selected_product_id") for row in case_rows}) == 1
        and all(row.get("passed") is True for row in case_rows)
        for case_rows in exact_groups.values()
        if len(case_rows) >= 2
    ) and sum(1 for case_rows in exact_groups.values() if len(case_rows) >= 2) == 9
    quality = (
        full_run
        and len(calls) == 27
        and all(row.get("passed") is True for row in calls)
        and len(no_calls) == 3
        and all(row.get("model_called") is False and row.get("passed") is True for row in no_calls)
        and stable
        and exact_replay_stable
    )
    p95 = _percentile95(latencies)
    maximum = max(latencies) if latencies else None
    latency_enforced = config["latency_gate"]["enforced"]
    latency_passed = None
    return {
        "quality_passed": quality,
        "replay_stability_3_of_3": stable,
        "exact_replay_stability": exact_replay_stable,
        "no_call_gate_3_of_3": len(no_calls) == 3
        and all(row.get("model_called") is False for row in no_calls),
        "live_call_count": len(calls),
        "p95_latency_ms": p95,
        "maximum_latency_ms": maximum,
        "latency_gate_enforced": latency_enforced,
        "latency_passed": latency_passed,
        "passed": quality,
    }


def validate_offline(
    config: Mapping[str, Any], counter: TokenCounter, check_price_age: bool = False
) -> dict[str, Any]:
    validate_config(config)
    if check_price_age:
        validate_price_snapshot(config)
    suite = base.load_json(base.CASES_PATH)
    suite_validation = base.validate_case_suite(suite)
    token_rows: list[dict[str, Any]] = []
    for case in suite["cases"]:
        payload = base.build_case_payloads(case)["C"]
        reason = base.preflight_reason(payload)
        if case["should_call_model"]:
            if reason is not None:
                raise OpenAIBenchmarkError(f"callable_preflight_blocked:{case['case_id']}")
            body = build_request(payload, config)
            tokens = estimate_request_tokens(body, counter, config)
            token_rows.append({"case_id": case["case_id"], "tokens": tokens})
        elif reason != case["expected_failure_reason"]:
            raise OpenAIBenchmarkError(f"preflight_reason_drift:{case['case_id']}")
    maximum_cost = _maximum_call_cost(config) * config["maximum_live_calls"]
    if maximum_cost > config["budget_usd"]:
        raise OpenAIBenchmarkError("planned_budget_exceeded")
    return {
        "offline_validation": "passed",
        "synthetic_only": True,
        "config": validate_config(config),
        "suite": suite_validation,
        "prompt_sha256": sha256_file(PROMPT_PATH),
        "config_sha256": sha256_file(CONFIG_PATH),
        "callable_input_tokens": token_rows,
        "maximum_estimated_input_tokens": max(row["tokens"] for row in token_rows),
        "target_input_tokens": config["target_input_tokens"],
        "maximum_input_tokens": config["maximum_input_tokens"],
        "maximum_planned_cost_usd": maximum_cost,
        "maximum_live_calls": config["maximum_live_calls"],
    }


def run_evaluation(
    client: ResponsesClient,
    counter: TokenCounter,
    config: Mapping[str, Any],
    budget_usd: float,
    attempt: str,
) -> dict[str, Any]:
    offline = validate_offline(config, counter, check_price_age=True)
    if budget_usd <= 0 or budget_usd > config["budget_usd"]:
        raise OpenAIBenchmarkError("budget_must_be_between_zero_and_five_usd")
    if _maximum_call_cost(config) * config["maximum_live_calls"] > budget_usd:
        raise OpenAIBenchmarkError("planned_budget_exceeded")
    suite = base.load_json(base.CASES_PATH)
    cases = {case["case_id"]: case for case in suite["cases"]}
    rows = _preflight_rows(suite)
    tracker = BudgetTracker(budget_usd)
    completed_repeats: dict[str, int] = defaultdict(int)

    smoke_callable = [
        case_id
        for case_id in suite["smoke"]["case_ids"]
        if cases[case_id]["should_call_model"]
    ]
    for case_id in smoke_callable:
        case = cases[case_id]
        payload = base.build_case_payloads(case)["C"]
        repeated_payload, probe = payload_for_repeat(case, payload, 0)
        rows.append(
            call_case(client, counter, tracker, config, case, repeated_payload, 0, probe)
        )
        completed_repeats[case_id] = 1
    smoke_passed = all(
        row.get("passed") is True
        for row in rows
        if row.get("case_id") in smoke_callable and row.get("model_called")
    ) and tracker.calls == 4

    if smoke_passed:
        for case in suite["cases"]:
            if not case["should_call_model"]:
                continue
            payload = base.build_case_payloads(case)["C"]
            start = completed_repeats[case["case_id"]]
            for repeat_index in range(start, config["callable_case_repeats"]):
                repeated_payload, probe = payload_for_repeat(case, payload, repeat_index)
                rows.append(
                    call_case(
                        client,
                        counter,
                        tracker,
                        config,
                        case,
                        repeated_payload,
                        repeat_index,
                        probe,
                    )
                )

    full_run = smoke_passed and tracker.calls == config["maximum_live_calls"]
    gate = evaluate_gate(rows, config, full_run)
    if gate["passed"]:
        production_status = "benchmark_passed_pending_owner_reviews"
    else:
        production_status = "benchmark_failed"
    return {
        "run_version": "openai-luna-max-run-v1",
        "synthetic_only": True,
        "model_id": config["model_id"],
        "reasoning": dict(config["reasoning"]),
        "input_variant": "C",
        "attempt": attempt,
        "prompt_sha256": sha256_file(PROMPT_PATH),
        "config_sha256": sha256_file(CONFIG_PATH),
        "maximum_estimated_input_tokens": offline["maximum_estimated_input_tokens"],
        "price_snapshot": dict(config["price_snapshot"]),
        "budget_usd": budget_usd,
        "spent_usd_conservative": tracker.spent_usd,
        "live_call_count": tracker.calls,
        "smoke_passed": smoke_passed,
        "gate": gate,
        "production_status": production_status,
        "production_approved": False,
        "results": rows,
    }


def _diagnostic_config(config: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(config)
    value["maximum_output_tokens"] = None
    value["model_max_output_tokens"] = 128_000
    value["maximum_output_text_tokens"] = None
    return value


def _validate_diagnostic_limits(
    config: Mapping[str, Any], budget_usd: float, timeout_seconds: float | None
) -> None:
    if timeout_seconds is not None and (timeout_seconds <= 10 or timeout_seconds > 120):
        raise OpenAIBenchmarkError("diagnostic_timeout_must_be_between_10_and_120_seconds")
    if budget_usd <= 0 or budget_usd > config["budget_usd"]:
        raise OpenAIBenchmarkError("budget_must_be_between_zero_and_five_usd")


def run_diagnostic_smoke(
    client: ResponsesClient,
    counter: TokenCounter,
    config: Mapping[str, Any],
    budget_usd: float,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    """Run only the four callable smoke cases with a diagnostic timeout.

    This lane intentionally does not change the production latency gate or the
    fixed baseline configuration. It answers a narrower question: does the
    provider return a valid, grounded recommendation when the client is willing
    to wait longer than the production SLO?
    """
    _validate_diagnostic_limits(config, budget_usd, timeout_seconds)
    offline = validate_offline(config, counter, check_price_age=True)
    diagnostic_config = _diagnostic_config(config)
    smoke_worst_cost = _maximum_call_cost(diagnostic_config) * 4
    if smoke_worst_cost > budget_usd:
        raise OpenAIBenchmarkError("planned_budget_exceeded")

    suite = base.load_json(base.CASES_PATH)
    cases = {case["case_id"]: case for case in suite["cases"]}
    rows = _preflight_rows(suite)
    tracker = BudgetTracker(budget_usd)
    smoke_callable = [
        case_id
        for case_id in suite["smoke"]["case_ids"]
        if cases[case_id]["should_call_model"]
    ]
    for case_id in smoke_callable:
        case = cases[case_id]
        payload = base.build_case_payloads(case)["C"]
        repeated_payload, probe = payload_for_repeat(case, payload, 0)
        rows.append(
            call_case(
                client,
                counter,
                tracker,
                diagnostic_config,
                case,
                repeated_payload,
                0,
                probe,
            )
        )

    callable_rows = [row for row in rows if row.get("model_called")]
    smoke_passed = (
        len(callable_rows) == 4
        and tracker.calls == 4
        and all(row.get("passed") is True for row in callable_rows)
    )
    latencies = [float(row["latency_ms"]) for row in callable_rows if "latency_ms" in row]
    return {
        "run_version": "openai-luna-max-diagnostic-smoke-v1",
        "synthetic_only": True,
        "diagnostic_only": True,
        "model_id": config["model_id"],
        "reasoning": dict(config["reasoning"]),
        "input_variant": "C",
        "timeout_seconds": timeout_seconds,
        "production_timeout_seconds": config["timeout_seconds"],
        "diagnostic_output_text_token_limit": None,
        "diagnostic_request_max_output_tokens": None,
        "diagnostic_budget_output_token_ceiling": diagnostic_config["model_max_output_tokens"],
        "production_output_text_token_limit": config["maximum_output_text_tokens"],
        "diagnostic_output_text_byte_limit": config["maximum_output_text_bytes"],
        "prompt_sha256": sha256_file(PROMPT_PATH),
        "config_sha256": sha256_file(CONFIG_PATH),
        "maximum_estimated_input_tokens": offline["maximum_estimated_input_tokens"],
        "price_snapshot": dict(config["price_snapshot"]),
        "budget_usd": budget_usd,
        "spent_usd_conservative": tracker.spent_usd,
        "live_call_count": tracker.calls,
        "smoke_passed": smoke_passed,
        "gate": {
            "quality_passed": smoke_passed,
            "no_call_gate_3_of_3": len(rows) == 3 + len(callable_rows)
            and all(row.get("model_called") is False for row in rows[:3]),
            "live_call_count": tracker.calls,
            "p95_latency_ms": _percentile95(latencies),
            "maximum_latency_ms": max(latencies) if latencies else None,
            "production_latency_gate_evaluated": False,
            "passed": smoke_passed,
        },
        "production_status": (
            "diagnostic_smoke_quality_passed_pending_full_benchmark"
            if smoke_passed
            else "diagnostic_smoke_failed"
        ),
        "production_approved": False,
        "results": rows,
    }


def run_diagnostic_full(
    client: ResponsesClient,
    counter: TokenCounter,
    config: Mapping[str, Any],
    budget_usd: float,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    """Run all nine callable cases three times without application token caps."""
    _validate_diagnostic_limits(config, budget_usd, timeout_seconds)
    offline = validate_offline(config, counter, check_price_age=True)
    diagnostic_config = _diagnostic_config(config)
    maximum_planned_cost = (
        _maximum_call_cost(diagnostic_config) * config["maximum_live_calls"]
    )
    if maximum_planned_cost > budget_usd:
        raise OpenAIBenchmarkError("planned_budget_exceeded")

    suite = base.load_json(base.CASES_PATH)
    cases = {case["case_id"]: case for case in suite["cases"]}
    rows = _preflight_rows(suite)
    tracker = BudgetTracker(budget_usd)
    completed_repeats: dict[str, int] = defaultdict(int)
    smoke_callable = [
        case_id
        for case_id in suite["smoke"]["case_ids"]
        if cases[case_id]["should_call_model"]
    ]
    for case_id in smoke_callable:
        case = cases[case_id]
        payload = base.build_case_payloads(case)["C"]
        repeated_payload, probe = payload_for_repeat(case, payload, 0)
        rows.append(
            call_case(
                client,
                counter,
                tracker,
                diagnostic_config,
                case,
                repeated_payload,
                0,
                probe,
            )
        )
        completed_repeats[case_id] = 1

    smoke_passed = all(
        row.get("passed") is True
        for row in rows
        if row.get("case_id") in smoke_callable and row.get("model_called")
    ) and tracker.calls == 4
    if smoke_passed:
        for case in suite["cases"]:
            if not case["should_call_model"]:
                continue
            payload = base.build_case_payloads(case)["C"]
            start = completed_repeats[case["case_id"]]
            for repeat_index in range(start, config["callable_case_repeats"]):
                repeated_payload, probe = payload_for_repeat(case, payload, repeat_index)
                rows.append(
                    call_case(
                        client,
                        counter,
                        tracker,
                        diagnostic_config,
                        case,
                        repeated_payload,
                        repeat_index,
                        probe,
                    )
                )

    full_run = smoke_passed and tracker.calls == config["maximum_live_calls"]
    evaluated = evaluate_gate(rows, config, full_run)
    quality_passed = evaluated["quality_passed"]
    diagnostic_gate = {
        "quality_passed": quality_passed,
        "replay_stability_3_of_3": evaluated["replay_stability_3_of_3"],
        "exact_replay_stability": evaluated["exact_replay_stability"],
        "no_call_gate_3_of_3": evaluated["no_call_gate_3_of_3"],
        "live_call_count": evaluated["live_call_count"],
        "p95_latency_ms": evaluated["p95_latency_ms"],
        "maximum_latency_ms": evaluated["maximum_latency_ms"],
        "production_latency_passed": evaluated["latency_passed"],
        "production_gate_passed": evaluated["passed"],
        "diagnostic_passed": quality_passed,
    }
    return {
        "run_version": "openai-luna-max-diagnostic-full-v1",
        "synthetic_only": True,
        "diagnostic_only": True,
        "model_id": config["model_id"],
        "reasoning": dict(config["reasoning"]),
        "input_variant": "C",
        "timeout_seconds": timeout_seconds,
        "production_timeout_seconds": config["timeout_seconds"],
        "diagnostic_output_text_token_limit": None,
        "diagnostic_request_max_output_tokens": None,
        "diagnostic_budget_output_token_ceiling": diagnostic_config[
            "model_max_output_tokens"
        ],
        "production_output_text_token_limit": config["maximum_output_text_tokens"],
        "diagnostic_output_text_byte_limit": config["maximum_output_text_bytes"],
        "prompt_sha256": sha256_file(PROMPT_PATH),
        "config_sha256": sha256_file(CONFIG_PATH),
        "maximum_estimated_input_tokens": offline["maximum_estimated_input_tokens"],
        "price_snapshot": dict(config["price_snapshot"]),
        "budget_usd": budget_usd,
        "maximum_planned_cost_usd": maximum_planned_cost,
        "spent_usd_conservative": tracker.spent_usd,
        "live_call_count": tracker.calls,
        "smoke_passed": smoke_passed,
        "gate": diagnostic_gate,
        "production_status": (
            "diagnostic_full_quality_passed_pending_adr_and_integration"
            if quality_passed
            else "diagnostic_full_failed"
        ),
        "production_approved": False,
        "results": rows,
    }


def _artifact_output_path(value: str) -> Path:
    path = Path(value).resolve()
    root = ARTIFACT_ROOT.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OpenAIBenchmarkError("output_must_be_under_artifact_root") from exc
    if path.suffix.lower() != ".json":
        raise OpenAIBenchmarkError("output_must_be_json")
    return path


def validate_optimized_attempt(
    baseline: Mapping[str, Any], config: Mapping[str, Any], counter: TokenCounter
) -> None:
    if config.get("latency_gate") == {"enforced": False, "record_only": True}:
        raise OpenAIBenchmarkError("optimized_attempt_disabled_latency_not_a_gate")
    if baseline.get("model_id") != config["model_id"] or baseline.get("reasoning") != config["reasoning"]:
        raise OpenAIBenchmarkError("optimized_attempt_configuration_mismatch")
    gate = baseline.get("gate") or {}
    if gate.get("quality_passed") is not True or gate.get("latency_passed") is not False:
        raise OpenAIBenchmarkError("optimized_attempt_requires_latency_only_baseline_failure")
    if baseline.get("production_status") != "quality_passed_latency_failed_retry_once":
        raise OpenAIBenchmarkError("optimized_attempt_not_authorized")
    current = validate_offline(config, counter, check_price_age=True)
    prompt_changed = baseline.get("prompt_sha256") != current["prompt_sha256"]
    input_reduced = (
        isinstance(baseline.get("maximum_estimated_input_tokens"), int)
        and current["maximum_estimated_input_tokens"]
        < baseline["maximum_estimated_input_tokens"]
    )
    if not prompt_changed and not input_reduced:
        raise OpenAIBenchmarkError("optimized_attempt_requires_smaller_prompt_or_input")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate synthetic inputs without an API call")
    run = subparsers.add_parser("run", help="run the gated synthetic live benchmark")
    run.add_argument("--live", action="store_true")
    run.add_argument("--synthetic-only", action="store_true")
    run.add_argument("--budget-usd", type=float, required=True)
    run.add_argument("--attempt", choices=("baseline", "optimized"), default="baseline")
    run.add_argument("--baseline")
    run.add_argument("--output", required=True)
    diagnostic = subparsers.add_parser(
        "diagnostic-smoke",
        help="run four callable smoke cases with a longer diagnostic timeout",
    )
    diagnostic.add_argument("--live", action="store_true")
    diagnostic.add_argument("--synthetic-only", action="store_true")
    diagnostic.add_argument("--budget-usd", type=float, required=True)
    diagnostic_timeout = diagnostic.add_mutually_exclusive_group()
    diagnostic_timeout.add_argument("--timeout-seconds", type=float, default=30.0)
    diagnostic_timeout.add_argument("--no-timeout", action="store_true")
    diagnostic.add_argument("--output", required=True)
    diagnostic_full = subparsers.add_parser(
        "diagnostic-full",
        help="run all 27 callable evaluations without application token caps",
    )
    diagnostic_full.add_argument("--live", action="store_true")
    diagnostic_full.add_argument("--synthetic-only", action="store_true")
    diagnostic_full.add_argument("--budget-usd", type=float, required=True)
    diagnostic_full_timeout = diagnostic_full.add_mutually_exclusive_group()
    diagnostic_full_timeout.add_argument("--timeout-seconds", type=float, default=90.0)
    diagnostic_full_timeout.add_argument("--no-timeout", action="store_true")
    diagnostic_full.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config()
        counter = TiktokenCounter(config["api"]["tokenizer_encoding"])
        if args.command == "validate":
            result = validate_offline(config, counter)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not args.live or not args.synthetic_only:
            raise OpenAIBenchmarkError("live_and_synthetic_only_flags_are_required")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key.strip():
            raise OpenAIBenchmarkError("missing_openai_api_key")
        output = _artifact_output_path(args.output)
        if args.command in {"diagnostic-smoke", "diagnostic-full"}:
            timeout_seconds = None if args.no_timeout else args.timeout_seconds
            runtime_config = dict(config)
            runtime_config["timeout_seconds"] = timeout_seconds
            client = OpenAIResponsesHTTPClient(api_key, runtime_config)
            if args.command == "diagnostic-smoke":
                result = run_diagnostic_smoke(
                    client,
                    counter,
                    config,
                    args.budget_usd,
                    timeout_seconds,
                )
                succeeded = result["smoke_passed"]
            else:
                result = run_diagnostic_full(
                    client,
                    counter,
                    config,
                    args.budget_usd,
                    timeout_seconds,
                )
                succeeded = result["gate"]["diagnostic_passed"]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(
                json.dumps(
                    {
                        "production_status": result["production_status"],
                        "smoke_passed": result["smoke_passed"],
                        "diagnostic_passed": succeeded,
                        "live_call_count": result["live_call_count"],
                        "spent_usd_conservative": result["spent_usd_conservative"],
                        "output": str(output),
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if succeeded else 2
        if args.attempt == "optimized":
            if not args.baseline:
                raise OpenAIBenchmarkError("optimized_attempt_requires_baseline")
            baseline_path = _artifact_output_path(args.baseline)
            if baseline_path == output or not baseline_path.is_file():
                raise OpenAIBenchmarkError("optimized_attempt_baseline_invalid")
            baseline = load_json(baseline_path)
            if not isinstance(baseline, dict):
                raise OpenAIBenchmarkError("optimized_attempt_baseline_invalid")
            validate_optimized_attempt(baseline, config, counter)
        elif args.baseline:
            raise OpenAIBenchmarkError("baseline_argument_only_for_optimized_attempt")
        client = OpenAIResponsesHTTPClient(api_key, config)
        result = run_evaluation(client, counter, config, args.budget_usd, args.attempt)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "production_status": result["production_status"],
                    "live_call_count": result["live_call_count"],
                    "spent_usd_conservative": result["spent_usd_conservative"],
                    "output": str(output),
                },
                ensure_ascii=False,
            )
        )
        return 0 if result["gate"]["passed"] else 2
    except (OpenAIBenchmarkError, base.BenchmarkError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())

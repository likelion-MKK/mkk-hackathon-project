#!/usr/bin/env python3
"""Build and validate central-recommender A/B/C payloads without model calls."""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
PROFILE_PATH = ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
EVIDENCE_PATH = CONTRACTS / "examples" / "recommendation-evidence-v2.valid.json"
FRAME_PATH = CONTRACTS / "examples" / "frame-observation-v2.valid.json"
DECISION_PATH = CONTRACTS / "examples" / "recommendation-decision-v2.valid.json"
REGISTRY_PATH = Path(__file__).with_name("model-candidates.v2.json")
BENCHMARK_PATH = Path(__file__).with_name("results") / "model-benchmark-status.v2.json"
CASES_PATH = Path(__file__).with_name("cases") / "central-recommender-cases.v1.json"
PROMPT_VERSION = "central-recommender-ko-v2"

PSYCHOLOGICAL_ASSERTION_PATTERN = re.compile(
    r"성격|심리|감정\s*(?:이다|입니다|유형)|구매\s*의도|내향|외향|우울|불안|"
    r"personality|psycholog|diagnos|emotion\s*(?:is|type)",
    re.IGNORECASE,
)

EXPECTED_PRODUCT_IDS = (
    "mcm-toni-medium-disco-visetos",
    "mcm-diamant-3d-small-calfskin",
    "mcm-milla-small-grained-leather",
    "mcm-ella-small-disco-visetos",
    "mcm-aren-nova-small-monogram-econyl",
    "mcm-ottomar-nova-55cm-monogram-econyl",
    "mcm-aren-nova-medium-backpack-econyl",
    "mcm-aren-triangle-mini-visetos",
    "mcm-pina-small-tambourine-visetos",
    "mcm-tracy-large-hobo-visetos",
)

EXPECTED_MODEL_CANDIDATES = {
    "qwen35-9b-colab-ref": (
        "Qwen/Qwen3.5-9B",
        "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
        "colab-gpu",
    ),
    "mistral-small-31-24b-colab-ref": (
        "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
        "68faf511d618ef198fef186659617cfd2eb8e33a",
        "colab-gpu",
    ),
    "hyperclovax-seed-05b-q4km": (
        "naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B",
        "4d88cd03638f3d0d88fd341be8ef625b60630fb8",
        "colab-gpu",
    ),
    "qwen3-06b-q8": (
        "Qwen/Qwen3-0.6B-GGUF",
        "23749fefcc72300e3a2ad315e1317431b06b590a",
        "colab-gpu",
    ),
    "qwen3-17b-q8": (
        "Qwen/Qwen3-1.7B-GGUF",
        "90862c4b9d2787eaed51d12237eafdfe7c5f6077",
        "colab-gpu",
    ),
    "kanana-15-21b-q4km": (
        "kakaocorp/kanana-1.5-2.1b-instruct-2505",
        "7df4bc35ccd610e451809d7106e1c3cf82bfd44c",
        "colab-gpu",
    ),
    "phi4-mini-onnx-cpu-int4": (
        "microsoft/Phi-4-mini-instruct-onnx",
        "fc04c8f93df696602fd9f300a30d1bf2e3081347",
        "colab-gpu",
    ),
}

FORBIDDEN_KEYS = {
    "base64",
    "blob",
    "faceembedding",
    "framebytes",
    "framedata",
    "framepayload",
    "imagebytes",
    "imagedata",
    "imagepayload",
    "landmark",
    "landmarks",
    "originalpath",
    "rawframe",
    "rawimage",
    "sourcepath",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def schema_registry() -> tuple[dict[str, Mapping[str, Any]], Registry]:
    schemas: dict[str, Mapping[str, Any]] = {}
    registry: Registry = Registry()
    for path in sorted(CONTRACTS.rglob("*.schema.json")):
        body = load_json(path)
        Draft202012Validator.check_schema(body)
        schemas[path.name] = body
        resource = Resource.from_contents(body, default_specification=DRAFT202012)
        registry = registry.with_resource(path.resolve().as_uri(), resource)
        if isinstance(body.get("$id"), str):
            registry = registry.with_resource(body["$id"], resource)
    return schemas, registry


def validate(instance: Any, schema_name: str, schemas: Mapping[str, Any], registry: Registry) -> None:
    schema = schemas[schema_name]
    errors = sorted(
        Draft202012Validator(schema, registry=registry).iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors
        )
        raise ValueError(f"{schema_name} validation failed: {rendered}")


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _forbidden_model_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return (
        normalized in FORBIDDEN_KEYS
        or "embedding" in normalized
        or "landmark" in normalized
        or normalized.endswith("originalpath")
        or normalized.endswith("sourcepath")
    )


def privacy_violations(value: Any, path: tuple[Any, ...] = ()) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if _forbidden_model_key(str(key)):
                yield f"/{'/'.join(map(str, child_path))}: forbidden key {key}"
            if isinstance(child, str) and child.lower().startswith("data:image/"):
                yield f"/{'/'.join(map(str, child_path))}: data URI forbidden"
            yield from privacy_violations(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from privacy_violations(child, (*path, index))


def string_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for child in value.values():
            yield from string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from string_values(child)
    elif isinstance(value, str):
        yield value


def psychological_assertion_count(value: Any) -> int:
    return sum(bool(PSYCHOLOGICAL_ASSERTION_PATTERN.search(text)) for text in string_values(value))


def model_product_view(product: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude display assets/source metadata the model does not need."""

    return {
        "product_id": product["product_id"],
        "display_name": product["display_name"],
        "controlled_tags": product["controlled_tags"],
        "recommendation_summary": product["recommendation_summary"],
        "style": product["style"],
    }


def build_evidence_variants() -> dict[str, dict[str, Any]]:
    base_evidence = load_json(EVIDENCE_PATH)
    frame = load_json(FRAME_PATH)
    variants: dict[str, dict[str, Any]] = {}
    for variant in ("A", "B", "C"):
        evidence = copy.deepcopy(base_evidence)
        evidence["input_variant"] = variant
        evidence["evidence_windows"] = None if variant == "B" else copy.deepcopy(
            base_evidence["evidence_windows"]
        )
        evidence["timeline"] = [copy.deepcopy(frame)] if variant in {"A", "B"} else None
        variants[variant] = evidence
    return variants


def model_evidence_view(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize evidence blocks in the exact A/B/C prompt order.

    The strict internal RecommendationEvidenceV2 keeps explicit null fields. The
    model view omits absent blocks so B is literally timeline then summary, and
    C does not accidentally receive a null timeline field.
    """

    view = {
        "schema_version": evidence["schema_version"],
        "decision_request_id": evidence["decision_request_id"],
        "input_variant": evidence["input_variant"],
        "session_id": evidence["session_id"],
        "video_id": evidence["video_id"],
        "manifest_version": evidence["manifest_version"],
        "catalog_version": evidence["catalog_version"],
        "feature_version": evidence["feature_version"],
        "signal_versions": evidence["signal_versions"],
        "data_quality": evidence["data_quality"],
    }
    variant = evidence["input_variant"]
    if variant == "A":
        view["summary"] = evidence["summary"]
        view["evidence_windows"] = evidence["evidence_windows"]
        view["timeline"] = evidence["timeline"]
    elif variant == "B":
        view["timeline"] = evidence["timeline"]
        view["summary"] = evidence["summary"]
    else:
        view["summary"] = evidence["summary"]
        view["evidence_windows"] = evidence["evidence_windows"]
    return view


def build_payloads() -> dict[str, dict[str, Any]]:
    profile = load_json(PROFILE_PATH)
    evidence_variants = build_evidence_variants()
    payloads: dict[str, dict[str, Any]] = {}
    for variant, evidence in evidence_variants.items():
        payloads[variant] = {
            "schema_version": "2.0",
            "decision_request_id": evidence["decision_request_id"],
            "session_id": evidence["session_id"],
            "video_id": evidence["video_id"],
            "prompt_version": PROMPT_VERSION,
            "evidence_version": evidence["feature_version"],
            "evidence": model_evidence_view(evidence),
            "products": [model_product_view(product) for product in profile["products"]],
        }
    return payloads


def assert_catalog(profile: Mapping[str, Any]) -> set[str]:
    products = profile["products"]
    product_ids = tuple(product["product_id"] for product in products)
    if len(products) != 10 or len(set(product_ids)) != 10:
        raise ValueError("v2 catalog must contain exactly 10 unique product_id values")
    if product_ids != EXPECTED_PRODUCT_IDS:
        raise ValueError("v2 catalog product IDs or ordering differ from the reviewed seed")
    for product in products:
        if product["approved_asset"] is not False:
            raise ValueError(f"pending product unexpectedly approved: {product['product_id']}")
        for field in ("official_product_url", "image_asset_path", "qr_asset_path"):
            if product[field] is not None or not product[f"{field}_reason"]:
                raise ValueError(f"pending product {field} must remain null+reason")
    return set(product_ids)


def assert_decision_grounding(
    decision: Mapping[str, Any], evidence: Mapping[str, Any], profile: Mapping[str, Any]
) -> None:
    catalog = {product["product_id"]: product for product in profile["products"]}
    selected = decision.get("selected_product_id")
    if decision.get("status") != "completed":
        return
    if decision["version"]["input_variant"] != evidence["input_variant"]:
        raise ValueError("decision input_variant differs from its evidence payload")
    if selected not in catalog:
        raise ValueError("completed decision selected a product outside the provided catalog")
    variant = evidence["input_variant"]
    windows = {window["window_id"]: window for window in evidence.get("evidence_windows") or []}
    frames = {frame["frame_id"]: frame for frame in evidence.get("timeline") or []}
    for item in decision["evidence"]:
        if item["product_id"] != selected:
            raise ValueError("decision evidence product differs from selected_product_id")
        for reference in item["evidence_refs"]:
            if variant == "B":
                if reference["kind"] != "frame":
                    raise ValueError("variant B evidence_ref must use kind=frame")
                frame = frames.get(reference["ref_id"])
                attention = frame.get("attention") if isinstance(frame, dict) else None
                candidate_ids = {
                    candidate["product_id"]
                    for candidate in attention.get("candidates", [])
                } if isinstance(attention, dict) else set()
                if selected not in candidate_ids:
                    raise ValueError("frame evidence_ref is absent or has no selected-product candidate")
            else:
                if reference["kind"] != "window":
                    raise ValueError("variant A/C evidence_ref must use kind=window")
                window = windows.get(reference["ref_id"])
                if window is None or window["product_id"] != selected:
                    raise ValueError("window evidence_ref is absent or belongs to another product")
    if not set(decision["style"]["matched_tags"]) <= set(catalog[selected]["controlled_tags"]):
        raise ValueError("decision style contains a tag outside the selected product profile")


def run_static_validation() -> dict[str, Any]:
    schemas, registry = schema_registry()
    profile = load_json(PROFILE_PATH)
    validate(profile, "product-recommendation-profile-v2.schema.json", schemas, registry)
    catalog_ids = assert_catalog(profile)

    payloads = build_payloads()
    evidence_variants = build_evidence_variants()
    for variant, payload in payloads.items():
        validate(
            evidence_variants[variant],
            "recommendation-evidence-v2.schema.json",
            schemas,
            registry,
        )
        violations = list(privacy_violations(payload))
        if violations:
            raise ValueError(f"variant {variant} violated privacy gate: {violations}")
        evidence_keys = list(payload["evidence"])
        block_keys = [
            key for key in evidence_keys if key in {"summary", "evidence_windows", "timeline"}
        ]
        expected_order = {
            "A": ["summary", "evidence_windows", "timeline"],
            "B": ["timeline", "summary"],
            "C": ["summary", "evidence_windows"],
        }[variant]
        if block_keys != expected_order:
            raise ValueError(f"variant {variant} serialization order differs: {block_keys}")

    missing_aggregate = copy.deepcopy(evidence_variants["C"])
    gaze_summary = missing_aggregate["summary"][0]["gaze"]
    gaze_summary.update(
        {
            "return_candidate_count": None,
            "return_candidate_reason": "no_comparable_interval",
            "movement_distance_norm": None,
            "mean_speed_norm_per_s": None,
            "movement_reason": "no_comparable_interval",
        }
    )
    expression_summary = missing_aggregate["summary"][0]["expression"]
    expression_summary.update(
        {
            "action_changes": None,
            "action_change_rates_per_s": None,
            "change_reason": "no_comparable_signals",
        }
    )
    validate(
        missing_aggregate,
        "recommendation-evidence-v2.schema.json",
        schemas,
        registry,
    )

    measured_zero = copy.deepcopy(evidence_variants["C"])
    measured_zero_gaze = measured_zero["summary"][0]["gaze"]
    measured_zero_gaze.update(
        {
            "return_candidate_count": 0,
            "return_candidate_reason": None,
            "movement_distance_norm": 0.0,
            "mean_speed_norm_per_s": 0.0,
            "movement_reason": None,
        }
    )
    validate(measured_zero, "recommendation-evidence-v2.schema.json", schemas, registry)

    decision = load_json(DECISION_PATH)
    validate(decision, "recommendation-decision-v2.schema.json", schemas, registry)
    assert_decision_grounding(decision, evidence_variants["C"], profile)
    if decision["selected_product_id"] not in catalog_ids:
        raise ValueError("decision fixture selected an unknown product")
    for variant in ("A", "B"):
        variant_decision = copy.deepcopy(decision)
        variant_decision["version"]["input_variant"] = variant
        reference = (
            {"kind": "frame", "ref_id": "frame-v2-00421"}
            if variant == "B"
            else {"kind": "window", "ref_id": "evidence-window-001"}
        )
        for item in variant_decision["evidence"]:
            item["evidence_refs"] = [reference]
        validate(
            variant_decision,
            "recommendation-decision-v2.schema.json",
            schemas,
            registry,
        )
        assert_decision_grounding(variant_decision, evidence_variants[variant], profile)

    candidate_registry = load_json(REGISTRY_PATH)
    benchmark = load_json(BENCHMARK_PATH)
    if candidate_registry["selection_status"] != "benchmark_gated_not_selected":
        raise ValueError("model registry must not claim selection before benchmark")
    candidates = {
        candidate["candidate_id"]: candidate for candidate in candidate_registry["candidates"]
    }
    if set(candidates) != set(EXPECTED_MODEL_CANDIDATES):
        raise ValueError("model candidate registry differs from the reviewed seven-model set")
    for candidate_id, (model_id, revision, execution_lane) in EXPECTED_MODEL_CANDIDATES.items():
        candidate = candidates[candidate_id]
        if (
            candidate.get("model_id") != model_id
            or candidate.get("revision") != revision
            or candidate.get("execution_lane") != execution_lane
        ):
            raise ValueError(f"model identity drifted for {candidate_id}")
        if not re.fullmatch(r"[0-9a-f]{40}", candidate["revision"]):
            raise ValueError(f"model revision is not an immutable SHA for {candidate_id}")
        license_info = candidate.get("license")
        if not isinstance(license_info, dict) or not all(
            license_info.get(field) for field in ("code", "weights", "url", "approval_status")
        ):
            raise ValueError(f"license provenance missing for {candidate_id}")
        artifact = candidate.get("artifact")
        prepared_manifests = {
            "qwen3-06b-q8": "64217f47ee2f7d5d2d619ddcbeebd7142b9b2a6d85857551a54abf99b4bd148d",
            "qwen3-17b-q8": "ddc070e86f5732cfb3e729329b289c8cc7799939898f55644c3b5472642bab93",
        }
        if not isinstance(artifact, dict):
            raise ValueError(f"artifact provenance missing for {candidate_id}")
        if candidate_id in prepared_manifests:
            if (
                artifact.get("manifest_sha256") != prepared_manifests[candidate_id]
                or artifact.get("checksum_status") != "verified"
                or any(file_info.get("sha256") is None for file_info in artifact.get("files", []))
            ):
                raise ValueError(f"prepared model {candidate_id} checksum manifest drifted")
        elif (
            artifact.get("manifest_sha256") is not None
            or artifact.get("checksum_status") != "not_collected_model_not_downloaded"
            or any(file_info.get("sha256") is not None for file_info in artifact.get("files", []))
        ):
            raise ValueError(f"un-downloaded model {candidate_id} must not claim local checksums")
        runtime = candidate.get("runtime")
        if (
            not isinstance(runtime, dict)
            or not re.fullmatch(r"[0-9a-f]{40}", str(runtime.get("commit", "")))
            or not runtime.get("version")
        ):
            raise ValueError(f"runtime provenance missing for {candidate_id}")

    suite = load_json(CASES_PATH)
    cases = suite.get("cases")
    categories = Counter(case.get("category") for case in cases or [])
    callable_count = sum(case.get("should_call_model") is True for case in cases or [])
    auxiliary_count = sum(
        isinstance(case.get("psychology_auxiliary_signal"), dict)
        for case in cases or []
        if case.get("should_call_model") is True
    )
    smoke = suite.get("smoke")
    case_by_id = {
        case.get("case_id"): case
        for case in cases or []
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    }
    smoke_case_ids = smoke.get("case_ids") if isinstance(smoke, dict) else None
    smoke_callable_count = sum(
        case_by_id[case_id].get("should_call_model") is True
        for case_id in smoke_case_ids or []
        if case_id in case_by_id
    )
    if (
        suite.get("synthetic_only") is not True
        or len(cases or []) != 12
        or categories != Counter({"normal": 6, "preflight_block": 3, "red_team": 3})
        or suite.get("variants") != ["A", "B", "C"]
        or suite.get("repeats_per_callable_case_variant") != 5
        or callable_count * 3 * 5 != 135
        or not isinstance(smoke, dict)
        or smoke.get("variants") != ["C"]
        or smoke.get("repeats") != 1
        or smoke.get("cold_start_count") != 1
        or not isinstance(smoke_case_ids, list)
        or len(smoke_case_ids) != 5
        or len(set(smoke_case_ids)) != 5
        or any(case_id not in case_by_id for case_id in smoke_case_ids)
        or smoke_callable_count != 4
        or auxiliary_count != callable_count
    ):
        raise ValueError("synthetic benchmark suite or 135-call plan drifted")
    if (
        benchmark.get("status") != "not_run"
        or benchmark.get("reason") != "benchmark_preparation_only"
        or benchmark.get("synthetic_only") is not True
        or benchmark.get("weight_download_performed") is not True
        or benchmark.get("downloaded_candidate_ids") != ["qwen3-06b-q8", "qwen3-17b-q8"]
        or benchmark.get("checksum_verified_candidate_ids")
        != ["qwen3-06b-q8", "qwen3-17b-q8"]
        or benchmark.get("weight_sha256")
        != {
            "qwen3-06b-q8": "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
            "qwen3-17b-q8": "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a",
        }
        or benchmark.get("manifest_sha256")
        != {
            "qwen3-06b-q8": "64217f47ee2f7d5d2d619ddcbeebd7142b9b2a6d85857551a54abf99b4bd148d",
            "qwen3-17b-q8": "ddc070e86f5732cfb3e729329b289c8cc7799939898f55644c3b5472642bab93",
        }
        or benchmark.get("runtime_source_checkout_prepared") is not True
        or benchmark.get("runtime_source_commit")
        != "e9fa0781f1c25fc4fe8c86be1edc6970661ad6f0"
        or benchmark.get("runtime_binary_available") is not False
        or benchmark.get("conversion_performed") is not False
        or benchmark.get("conversion_performed") is not False
        or benchmark.get("external_provider_used") is not False
        or benchmark.get("selected_model") is not None
    ):
        raise ValueError("benchmark status must remain explicit and unselected")

    return {
        "contract_validation": "passed",
        "catalog_unique_ids": len(catalog_ids),
        "payload_variants": list(payloads),
        "variant_shapes": {
            "A": "summary+evidence_windows+timeline",
            "B": "timeline+summary",
            "C": "summary+evidence_windows",
        },
        "missing_vs_measured_zero": "passed",
        "benchmark_status": benchmark["status"],
        "benchmark_reason": benchmark["reason"],
        "selected_model": benchmark["selected_model"],
        "model_candidate_count": len(candidates),
        "synthetic_case_count": len(cases),
        "planned_correctness_calls_per_candidate": 135,
        "psychology_auxiliary_case_count": auxiliary_count,
        "smoke_case_count": len(smoke_case_ids),
        "smoke_callable_case_count": smoke_callable_count,
    }


def _parse_decision(result: Mapping[str, Any]) -> tuple[Any | None, bool, str | None]:
    raw = result.get("raw_response")
    if isinstance(raw, str):
        try:
            return json.loads(raw), True, None
        except json.JSONDecodeError as exc:
            return None, False, f"invalid JSON: {exc.msg}"
    if "decision" in result:
        return result["decision"], isinstance(result["decision"], dict), None
    return None, False, "missing raw_response or decision"


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return ordered[index]


def evaluate_response_file(path: Path) -> dict[str, Any]:
    """Score future repeated self-hosted DecisionV2 results without calling a model."""

    static = run_static_validation()
    body = load_json(path)
    if body.get("status") == "not_run":
        return {**static, "response_evaluation": "not_run", "reason": body.get("reason")}

    schemas, registry = schema_registry()
    profile = load_json(PROFILE_PATH)
    catalog_ids = {product["product_id"] for product in profile["products"]}
    payloads = build_payloads()
    evidence_variants = build_evidence_variants()
    input_bytes = {
        variant: len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        for variant, payload in payloads.items()
    }
    results = body.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("response file must contain a non-empty results array")

    evaluated: list[dict[str, Any]] = []
    stability_groups: dict[tuple[str, str], list[tuple[Any, Any]]] = defaultdict(list)
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise ValueError(f"results/{index} must be an object")
        variant = result.get("variant")
        if variant not in payloads:
            raise ValueError("response result variant must be A, B or C")
        case_id = result.get("case_id", "default-case")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id must be a non-empty string")

        decision, raw_json_valid, parse_error = _parse_decision(result)
        schema_valid = False
        schema_error: str | None = None
        if raw_json_valid:
            try:
                validate(decision, "recommendation-decision-v2.schema.json", schemas, registry)
                schema_valid = True
            except (TypeError, ValueError) as exc:
                schema_error = str(exc)

        catalog_ok = False
        version_ok = False
        grounding_ok = False
        expected_ok: bool | None = None
        assertion_count = psychological_assertion_count(decision)
        if schema_valid and isinstance(decision, dict):
            selected = decision.get("selected_product_id")
            catalog_ok = selected in catalog_ids if decision.get("status") == "completed" else selected is None
            version_ok = (
                decision["version"]["catalog_version"] == profile["catalog_version"]
                and decision["version"]["input_variant"] == variant
            )
            try:
                assert_decision_grounding(decision, evidence_variants[variant], profile)
                grounding_ok = True
            except (KeyError, TypeError, ValueError):
                grounding_ok = False
            expected_status = result.get("expected_status")
            expected_product_id = result.get("expected_product_id")
            if expected_status is not None or "expected_product_id" in result:
                expected_ok = decision.get("status") == expected_status
                if expected_product_id is not None:
                    expected_ok = expected_ok and selected == expected_product_id
            stability_groups[(variant, case_id)].append(
                (decision.get("status"), decision.get("selected_product_id"))
            )

        latency = result.get("latency_ms")
        latency_ms = float(latency) if isinstance(latency, (int, float)) and latency >= 0 else None
        evaluated.append(
            {
                "case_id": case_id,
                "variant": variant,
                "repeat_index": result.get("repeat_index"),
                "raw_json_valid": raw_json_valid,
                "schema_valid": schema_valid,
                "catalog_id_compliant": catalog_ok,
                "evidence_grounded": grounding_ok,
                "version_compliant": version_ok,
                "expected_result_match": expected_ok,
                "psychological_assertion_count": assertion_count,
                "latency_ms": latency_ms,
                "input_bytes": input_bytes[variant],
                "error": parse_error or schema_error,
            }
        )

    summaries: dict[str, dict[str, Any]] = {}
    for variant in ("A", "B", "C"):
        rows = [row for row in evaluated if row["variant"] == variant]
        if not rows:
            continue
        count = len(rows)
        latencies = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
        expectations = [row["expected_result_match"] for row in rows if row["expected_result_match"] is not None]
        group_stabilities: list[float] = []
        minimum_repeats: int | None = None
        for (group_variant, _), outputs in stability_groups.items():
            if group_variant != variant:
                continue
            minimum_repeats = len(outputs) if minimum_repeats is None else min(minimum_repeats, len(outputs))
            group_stabilities.append(Counter(outputs).most_common(1)[0][1] / len(outputs))
        summary = {
            "result_count": count,
            "raw_json_compliance_rate": sum(row["raw_json_valid"] for row in rows) / count,
            "schema_compliance_rate": sum(row["schema_valid"] for row in rows) / count,
            "catalog_id_compliance_rate": sum(row["catalog_id_compliant"] for row in rows) / count,
            "evidence_grounding_rate": sum(row["evidence_grounded"] for row in rows) / count,
            "version_compliance_rate": sum(row["version_compliant"] for row in rows) / count,
            "expected_result_accuracy": (sum(expectations) / len(expectations)) if expectations else None,
            "repeat_stability_rate": min(group_stabilities) if group_stabilities else None,
            "minimum_repeats_per_case": minimum_repeats,
            "psychological_assertion_count": sum(row["psychological_assertion_count"] for row in rows),
            "latency_ms": {
                "mean": mean(latencies) if latencies else None,
                "p95": _p95(latencies),
                "max": max(latencies) if latencies else None,
            },
            "input_bytes": input_bytes[variant],
        }
        summary["safe_gate_passed"] = all(
            (
                summary["raw_json_compliance_rate"] == 1,
                summary["schema_compliance_rate"] == 1,
                summary["catalog_id_compliance_rate"] == 1,
                summary["evidence_grounding_rate"] == 1,
                summary["version_compliance_rate"] == 1,
                summary["psychological_assertion_count"] == 0,
                summary["expected_result_accuracy"] == 1,
                summary["repeat_stability_rate"] == 1,
                (summary["minimum_repeats_per_case"] or 0) >= 2,
                len(latencies) == count,
            )
        )
        summaries[variant] = summary

    eligible = [variant for variant, summary in summaries.items() if summary["safe_gate_passed"]]
    recommendation: str | None = None
    if eligible:
        best_accuracy = max(summaries[variant]["expected_result_accuracy"] for variant in eligible)
        tied = [
            variant
            for variant in eligible
            if summaries[variant]["expected_result_accuracy"] == best_accuracy
        ]
        smallest = min(summaries[variant]["input_bytes"] for variant in tied)
        smallest_variants = [
            variant for variant in tied if summaries[variant]["input_bytes"] == smallest
        ]
        recommendation = "C" if "C" in smallest_variants else sorted(smallest_variants)[0]

    return {
        **static,
        "response_evaluation": "completed",
        "results": evaluated,
        "variant_summary": summaries,
        "recommended_variant": recommendation,
        "tie_break_rule": "safe gates, then expected accuracy, then smallest input bytes; prefer C on an exact tie",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="validate fixtures and A/B/C payloads")
    parser.add_argument("--emit-variant", choices=("A", "B", "C"), help="print one model payload")
    parser.add_argument("--responses", type=Path, help="evaluate future self-hosted DecisionV2 results")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.emit_variant:
        run_static_validation()
        print(json.dumps(build_payloads()[args.emit_variant], ensure_ascii=False, indent=2))
        return 0
    result = evaluate_response_file(args.responses) if args.responses else run_static_validation()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

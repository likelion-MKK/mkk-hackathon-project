"""Run one live, synthetic-only Luna recommendation canary.

The command intentionally has no retry loop and never prints model prose, the
request payload, the raw provider response, or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Sequence

from apps.api.app.v2_central import (
    APPROVED_PROMPT_VERSION,
    CentralModelError,
    OpenAILunaCentralClient,
    configured_central_client,
    validate_central_output,
)
from apps.api.app.v2_models import (
    CentralRecommendationRequestV2,
    ProductRecommendationProfileV2,
    RecommendationEvidenceV2,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = REPO_ROOT / "contracts" / "examples" / "recommendation-evidence-v2.valid.json"
CATALOG_PATH = REPO_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
EXPECTED_PRODUCT_ID = "mcm-toni-medium-disco-visetos"
EXPECTED_CATALOG_SIZE = 10
SAFE_PROVIDER_DIAGNOSTIC_PATTERN = re.compile(r"^provider_http_[1-5][0-9]{2}$")
SAFE_PROVIDER_ERROR_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
SAFE_PROVIDER_ERROR_PARAM_PATTERN = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,200}$")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_canary_request() -> CentralRecommendationRequestV2:
    """Build the canonical synthetic variant-C request from repository fixtures."""

    evidence = RecommendationEvidenceV2.model_validate(_read_json(EVIDENCE_PATH))
    catalog = ProductRecommendationProfileV2.model_validate(_read_json(CATALOG_PATH))

    if len(catalog.products) != EXPECTED_CATALOG_SIZE:
        raise ValueError("canary catalog must contain exactly 10 products")
    if catalog.catalog_version != evidence.catalog_version:
        raise ValueError("canary evidence and catalog versions do not match")
    if EXPECTED_PRODUCT_ID not in {product.product_id for product in catalog.products}:
        raise ValueError("expected canary product is missing from catalog")

    return CentralRecommendationRequestV2(
        decision_request_id=evidence.decision_request_id,
        session_id=evidence.session_id,
        video_id=evidence.video_id,
        prompt_version=APPROVED_PROMPT_VERSION,
        evidence_version=evidence.feature_version,
        evidence=evidence,
        products=catalog.products,
    )


async def _call_once(
    client: OpenAILunaCentralClient,
    request: CentralRecommendationRequestV2,
):
    raw_output = await client.recommend_async(request)
    return validate_central_output(raw_output, request=request)


def _emit(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--max-calls", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.live or not args.synthetic_only or args.max_calls != 1:
        _emit(
            {
                "status": "blocked",
                "reason_code": "explicit_live_synthetic_single_call_required",
                "live_call_count": 0,
            }
        )
        return 2

    live_call_count = 0
    try:
        request = build_canary_request()
        client = configured_central_client()
        if not isinstance(client, OpenAILunaCentralClient):
            raise ValueError("Luna provider is not configured")

        live_call_count = 1
        decision = asyncio.run(_call_once(client, request))
        if decision.product_id != EXPECTED_PRODUCT_ID:
            raise CentralModelError(
                "invalid_model_output",
                "The canary selected an unexpected product.",
            )

        _emit(
            {
                "status": "passed",
                "selected_product_id": decision.product_id,
                "model_id": client.model_id,
                "validation_code": "strict_passed",
                "live_call_count": live_call_count,
            }
        )
        return 0
    except CentralModelError as exc:
        result = {
            "status": "failed",
            "reason_code": exc.reason_code,
            "live_call_count": live_call_count,
        }
        diagnostic_code = exc.provider_diagnostic_code
        if diagnostic_code == "provider_transport_error" or (
            isinstance(diagnostic_code, str)
            and SAFE_PROVIDER_DIAGNOSTIC_PATTERN.fullmatch(diagnostic_code)
        ):
            result["provider_diagnostic_code"] = diagnostic_code
        if isinstance(exc.provider_error_type, str) and SAFE_PROVIDER_ERROR_TOKEN_PATTERN.fullmatch(
            exc.provider_error_type
        ):
            result["provider_error_type"] = exc.provider_error_type
        if isinstance(exc.provider_error_code, str) and SAFE_PROVIDER_ERROR_TOKEN_PATTERN.fullmatch(
            exc.provider_error_code
        ):
            result["provider_error_code"] = exc.provider_error_code
        if isinstance(exc.provider_error_param, str) and SAFE_PROVIDER_ERROR_PARAM_PATTERN.fullmatch(
            exc.provider_error_param
        ):
            result["provider_error_param"] = exc.provider_error_param
        _emit(result)
        return 1
    except Exception:
        _emit(
            {
                "status": "failed",
                "reason_code": "canary_preflight_failed" if live_call_count == 0 else "canary_execution_failed",
                "live_call_count": live_call_count,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

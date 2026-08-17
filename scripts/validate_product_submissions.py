#!/usr/bin/env python3
"""Validate detailed product research submissions before catalog import."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONTROLLED_TAGS = {
    "backpack",
    "bold",
    "boston",
    "classic",
    "compact",
    "crossbody",
    "daily",
    "evening",
    "hobo",
    "leather",
    "lightweight",
    "minimal",
    "modern",
    "monogram",
    "neutral",
    "recycled_material",
    "shoulder",
    "shopper",
    "soft",
    "spacious",
    "sporty",
    "structured",
    "tambourine",
    "top_handle",
    "tote",
    "travel",
    "triangle",
    "weekender",
    "work",
}
SILHOUETTES = {"boxy", "cylindrical", "rounded", "slouchy", "trapezoid", "triangular"}
VISUAL_TONES = {"bold", "casual", "classic", "minimal", "refined", "sporty"}
USE_CASES = {"daily", "evening", "travel", "weekend", "work"}
REVIEW_STATUSES = {"draft", "reviewed", "approved"}
FORBIDDEN_KEYS = {
    "base64",
    "blob",
    "embedding",
    "embeddings",
    "frame",
    "frames",
    "imagebytes",
    "rawframe",
    "rawimage",
    "sourcepath",
    "token",
}
PLACEHOLDER_MARKERS = {
    "replace-with",
    "official-product-url",
    "official-image-url",
    "yyyy-mm-dd",
    "todo",
    "tbd",
}


class SubmissionError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=root / "data" / "products" / "submissions",
    )
    parser.add_argument(
        "--canonical",
        type=Path,
        default=root / "data" / "products" / "mcm-demo-recommendation-profile-v2.json",
    )
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SubmissionError(message)


def require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{path} must be an object")
    return value


def require_string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        fail(f"{path} must be a non-empty string")
    return value


def require_list(value: Any, path: str, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        fail(f"{path} must be a non-empty array")
    return value


def require_date(value: Any, path: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    text = require_string(value, path)
    if not DATE_PATTERN.fullmatch(text):
        fail(f"{path} must use YYYY-MM-DD")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise SubmissionError(f"{path} is not a real calendar date") from exc


def require_url(value: Any, path: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    text = require_string(value, path)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        fail(f"{path} must be an HTTP(S) URL")


def check_no_forbidden_keys(value: Any, path: str = "submission") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in FORBIDDEN_KEYS:
                fail(f"{path}.{key} is not allowed in a research submission")
            check_no_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_no_forbidden_keys(child, f"{path}[{index}]")


def check_no_placeholders(value: Any, path: str = "submission") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            check_no_placeholders(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_no_placeholders(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            fail(f"{path} still contains a template placeholder")


def validate_submission(payload: Any, *, expected_id: str, canonical_ids: set[str]) -> None:
    root = require_mapping(payload, expected_id)
    required = {
        "submission_version",
        "product_id",
        "research",
        "recommendation_profile",
        "sources",
        "asset_review",
        "review",
    }
    if set(root) != required:
        fail(f"{expected_id}: top-level fields must be exactly {sorted(required)}")
    if root["submission_version"] != "1.0":
        fail(f"{expected_id}: unsupported submission_version")
    product_id = require_string(root["product_id"], f"{expected_id}.product_id")
    if product_id != expected_id:
        fail(f"{expected_id}: filename and product_id must match")
    if product_id not in canonical_ids:
        fail(f"{expected_id}: product_id is outside the canonical 10-product catalog")

    research = require_mapping(root["research"], f"{expected_id}.research")
    required_research = {
        "brand",
        "display_name",
        "category",
        "collection_or_line",
        "official_product_url",
        "official_listing_url",
        "color",
        "material",
        "dimensions_mm",
        "weight_g",
        "carrying_methods",
        "closure",
        "capacity_and_pockets",
        "visual_features",
        "recommended_use_cases",
        "care_notes",
        "availability",
    }
    if set(research) != required_research:
        fail(f"{expected_id}.research fields are incomplete")
    if research["brand"] != "MCM" or research["category"] != "bag":
        fail(f"{expected_id}: research must describe an MCM bag")
    require_string(research["display_name"], f"{expected_id}.research.display_name")
    require_url(research["official_product_url"], f"{expected_id}.research.official_product_url")
    require_url(research["official_listing_url"], f"{expected_id}.research.official_listing_url")

    for field in ("color", "material"):
        value = require_mapping(research[field], f"{expected_id}.research.{field}")
        if set(value) != {"official_name", "normalized_family", "not_verified_reason"}:
            fail(f"{expected_id}.research.{field} fields are incomplete")
        if value["official_name"] is None and not str(value["not_verified_reason"]).strip():
            fail(f"{expected_id}.research.{field} needs a verification reason")

    dimensions = require_mapping(research["dimensions_mm"], f"{expected_id}.research.dimensions_mm")
    if set(dimensions) != {"width", "height", "depth", "not_verified_reason"}:
        fail(f"{expected_id}.research.dimensions_mm fields are incomplete")
    if any(dimensions[key] is None for key in ("width", "height", "depth")) and not str(
        dimensions["not_verified_reason"]
    ).strip():
        fail(f"{expected_id}.research.dimensions_mm needs a verification reason")

    weight = require_mapping(research["weight_g"], f"{expected_id}.research.weight_g")
    if set(weight) != {"value", "not_verified_reason"}:
        fail(f"{expected_id}.research.weight_g fields are incomplete")
    if weight["value"] is None and not str(weight["not_verified_reason"]).strip():
        fail(f"{expected_id}.research.weight_g needs a verification reason")

    for field in ("carrying_methods", "capacity_and_pockets", "visual_features", "recommended_use_cases"):
        require_list(research[field], f"{expected_id}.research.{field}")
    availability = require_mapping(research["availability"], f"{expected_id}.research.availability")
    if set(availability) != {"status", "checked_at", "not_verified_reason"}:
        fail(f"{expected_id}.research.availability fields are incomplete")
    require_date(availability["checked_at"], f"{expected_id}.research.availability.checked_at", nullable=True)

    profile = require_mapping(root["recommendation_profile"], f"{expected_id}.recommendation_profile")
    if set(profile) != {"controlled_tags", "recommendation_summary", "style"}:
        fail(f"{expected_id}.recommendation_profile fields are incomplete")
    tags = require_list(profile["controlled_tags"], f"{expected_id}.recommendation_profile.controlled_tags")
    if not 3 <= len(tags) <= 12 or len(tags) != len(set(tags)) or not set(tags) <= CONTROLLED_TAGS:
        fail(f"{expected_id}: controlled_tags are invalid or outside the allowlist")
    summary = require_string(profile["recommendation_summary"], f"{expected_id}.recommendation_summary")
    if not 20 <= len(summary) <= 500:
        fail(f"{expected_id}.recommendation_summary must contain 20..500 characters")
    style = require_mapping(profile["style"], f"{expected_id}.recommendation_profile.style")
    if set(style) != {"silhouette", "visual_tone", "use_cases"}:
        fail(f"{expected_id}.style fields are incomplete")
    if style["silhouette"] not in SILHOUETTES or style["visual_tone"] not in VISUAL_TONES:
        fail(f"{expected_id}: style value is outside the allowlist")
    use_cases = require_list(style["use_cases"], f"{expected_id}.style.use_cases")
    if not set(use_cases) <= USE_CASES or len(use_cases) != len(set(use_cases)):
        fail(f"{expected_id}: style.use_cases are invalid")

    sources = require_list(root["sources"], f"{expected_id}.sources")
    if not any(isinstance(source, dict) and source.get("kind") == "official_product_page" for source in sources):
        fail(f"{expected_id}: at least one official_product_page source is required")
    for index, source_value in enumerate(sources):
        source = require_mapping(source_value, f"{expected_id}.sources[{index}]")
        if set(source) != {"source_id", "kind", "url", "accessed_on", "supports"}:
            fail(f"{expected_id}.sources[{index}] fields are incomplete")
        require_string(source["source_id"], f"{expected_id}.sources[{index}].source_id")
        require_string(source["kind"], f"{expected_id}.sources[{index}].kind")
        require_url(source["url"], f"{expected_id}.sources[{index}].url")
        require_date(source["accessed_on"], f"{expected_id}.sources[{index}].accessed_on")
        require_list(source["supports"], f"{expected_id}.sources[{index}].supports")

    asset_review = require_mapping(root["asset_review"], f"{expected_id}.asset_review")
    if set(asset_review) != {"image_source_url", "usage_approval_reference", "approved_asset", "note"}:
        fail(f"{expected_id}.asset_review fields are incomplete")
    if asset_review["image_source_url"] is not None:
        require_url(asset_review["image_source_url"], f"{expected_id}.asset_review.image_source_url")
    if not isinstance(asset_review["approved_asset"], bool):
        fail(f"{expected_id}.asset_review.approved_asset must be boolean")
    if asset_review["approved_asset"] and not str(asset_review["usage_approval_reference"]).strip():
        fail(f"{expected_id}: approved assets need a usage_approval_reference")

    review = require_mapping(root["review"], f"{expected_id}.review")
    if set(review) != {"researcher", "checked_at", "reviewer", "review_status"}:
        fail(f"{expected_id}.review fields are incomplete")
    require_string(review["researcher"], f"{expected_id}.review.researcher")
    require_date(review["checked_at"], f"{expected_id}.review.checked_at")
    if review["review_status"] not in REVIEW_STATUSES:
        fail(f"{expected_id}.review.review_status is invalid")


def main() -> int:
    args = parse_args()
    directory = args.directory.resolve()
    canonical_path = args.canonical.resolve()
    try:
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        canonical_products = canonical["products"]
        canonical_ids = {item["product_id"] for item in canonical_products}
        if len(canonical_ids) != 10 or len(canonical_products) != 10:
            fail("canonical catalog must contain exactly 10 unique products")
        files = sorted(path for path in directory.glob("*.json") if path.name != "template.json")
        if not files:
            if args.allow_empty:
                print("[OK] no product submissions yet (--allow-empty)")
                return 0
            fail("no product submission files found")
        if not args.allow_partial and len(files) != 10:
            fail(f"expected exactly 10 product submissions, found {len(files)}")
        seen: set[str] = set()
        for path in files:
            product_id = path.stem
            if product_id in seen:
                fail(f"duplicate product submission: {product_id}")
            seen.add(product_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            check_no_forbidden_keys(payload)
            check_no_placeholders(payload)
            validate_submission(
                payload,
                expected_id=product_id,
                canonical_ids=canonical_ids,
            )
        if not args.allow_partial and seen != canonical_ids:
            missing = sorted(canonical_ids - seen)
            extra = sorted(seen - canonical_ids)
            fail(f"submission IDs do not match canonical catalog; missing={missing}, extra={extra}")
        print(f"[OK] validated {len(files)} product submission(s)")
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, SubmissionError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

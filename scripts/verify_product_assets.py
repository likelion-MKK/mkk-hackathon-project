#!/usr/bin/env python3
"""Verify the reviewed product catalog and its exact local image asset set."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


CATALOG_VERSION = "mcm-us-pdp-verified-v3-2026-08-18"
EXPECTED_ASSET_KIND = "image"
EXPECTED_PRODUCT_COUNT = 10
PRODUCT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ProductAssetVerificationError(ValueError):
    """Raised when catalog metadata and local product assets are inconsistent."""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProductAssetVerificationError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise ProductAssetVerificationError(f"expected a JSON object: {path}")
    return value


def _catalog_products(root: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    catalog_path = root / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
    catalog = _read_json_object(catalog_path)
    catalog_version = catalog.get("catalog_version")
    products = catalog.get("products")
    if catalog_version != CATALOG_VERSION or not isinstance(products, list):
        raise ProductAssetVerificationError("invalid canonical product catalog envelope")
    if len(products) != EXPECTED_PRODUCT_COUNT or any(
        not isinstance(product, dict) for product in products
    ):
        raise ProductAssetVerificationError(
            f"canonical catalog must contain exactly {EXPECTED_PRODUCT_COUNT} product objects"
        )

    products_by_id: dict[str, dict[str, Any]] = {}
    for product in products:
        product_id = product.get("product_id")
        if not isinstance(product_id, str) or product_id in products_by_id:
            raise ProductAssetVerificationError("canonical catalog product IDs must be unique strings")
        products_by_id[product_id] = product
    return catalog_version, products_by_id


def verify_product_assets(root: Path, media_root: Path | None = None) -> int:
    """Verify catalog/manifest equivalence and every physical product image."""

    resolved_root = root.resolve()
    resolved_media_root = (media_root or resolved_root / "apps" / "kiosk" / "public").resolve()
    catalog_version, products_by_id = _catalog_products(resolved_root)

    metadata_path = (
        resolved_root / "data" / "products" / "mcm-recommendation-catalog-assets-v2.json"
    )
    metadata = _read_json_object(metadata_path)
    assets = metadata.get("assets")
    if (
        metadata.get("schema_version") != "2.0"
        or metadata.get("catalog_version") != catalog_version
        or not isinstance(assets, list)
        or len(assets) != EXPECTED_PRODUCT_COUNT
        or any(not isinstance(asset, dict) for asset in assets)
    ):
        raise ProductAssetVerificationError("invalid product asset metadata envelope")

    assets_by_id: dict[str, dict[str, Any]] = {}
    for asset in assets:
        product_id = asset.get("product_id")
        if not isinstance(product_id, str) or product_id in assets_by_id:
            raise ProductAssetVerificationError("product asset IDs must be unique strings")
        assets_by_id[product_id] = asset
    if set(assets_by_id) != set(products_by_id):
        raise ProductAssetVerificationError(
            "product asset IDs must exactly match the canonical catalog IDs"
        )

    products_directory = resolved_media_root / "media" / "products"
    if products_directory.is_symlink() or not products_directory.is_dir():
        raise ProductAssetVerificationError(
            f"product media directory must be a real directory: {products_directory}"
        )
    resolved_products_directory = products_directory.resolve()
    try:
        resolved_products_directory.relative_to(resolved_media_root)
    except ValueError as error:
        raise ProductAssetVerificationError(
            f"product media directory escapes media root: {products_directory}"
        ) from error

    expected_filenames: set[str] = set()
    for product_id, asset in assets_by_id.items():
        product = products_by_id[product_id]
        relative_path = asset.get("relative_path")
        source_url = asset.get("source_url")
        expected_hash = asset.get("sha256")
        expected_relative_path = f"media/products/{product_id}.jpeg"
        expected_logical_path = f"assets/products/{product_id}.jpeg"
        if (
            asset.get("asset_kind") != EXPECTED_ASSET_KIND
            or relative_path != expected_relative_path
            or not isinstance(expected_hash, str)
            or SHA256_PATTERN.fullmatch(expected_hash) is None
            or not isinstance(source_url, str)
            or not isinstance(asset.get("approval_note"), str)
            or not asset["approval_note"].strip()
        ):
            raise ProductAssetVerificationError(f"invalid asset metadata for {product_id!r}")

        unresolved_path = resolved_media_root / Path(relative_path)
        resolved_path = unresolved_path.resolve()
        try:
            resolved_path.relative_to(resolved_products_directory)
        except ValueError as error:
            raise ProductAssetVerificationError(
                f"product image path escapes product media directory: {relative_path}"
            ) from error

        if PRODUCT_ID_PATTERN.fullmatch(product_id) is None:
            raise ProductAssetVerificationError(f"invalid product ID for local asset: {product_id!r}")
        if (
            product.get("source_status") != "team_approved_catalog_record"
            or product.get("approved_asset") is not True
            or product.get("image_asset_path") != expected_logical_path
            or product.get("image_asset_path_reason") is not None
            or product.get("official_product_url") != source_url
        ):
            raise ProductAssetVerificationError(
                f"catalog image asset does not match product record for {product_id!r}"
            )
        if unresolved_path.is_symlink() or not resolved_path.is_file():
            raise ProductAssetVerificationError(f"missing product image: {unresolved_path}")

        actual_hash = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ProductAssetVerificationError(
                f"sha256 mismatch for {product_id}: {actual_hash}"
            )
        expected_filenames.add(f"{product_id}.jpeg")

    actual_entries = {entry.name for entry in products_directory.iterdir()}
    if actual_entries != expected_filenames:
        missing = sorted(expected_filenames - actual_entries)
        unexpected = sorted(actual_entries - expected_filenames)
        raise ProductAssetVerificationError(
            f"product media directory must contain the exact approved set; "
            f"missing={missing}, unexpected={unexpected}"
        )

    return len(assets_by_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    parser.add_argument(
        "--media-root",
        type=Path,
        default=None,
        help="physical media root; defaults to apps/kiosk/public",
    )
    args = parser.parse_args()
    try:
        verified_count = verify_product_assets(args.root, args.media_root)
    except ProductAssetVerificationError as error:
        raise SystemExit(str(error)) from error

    media_root = (args.media_root or args.root / "apps" / "kiosk" / "public").resolve()
    print(f"[OK] verified {verified_count} exact product image assets under {media_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

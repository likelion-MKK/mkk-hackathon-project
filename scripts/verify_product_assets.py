#!/usr/bin/env python3
"""Verify the reviewed product catalog and its exact local image and QR assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


CATALOG_VERSION = "mcm-us-pdp-verified-v3-2026-08-18"
EXPECTED_ASSET_KINDS = ("image", "qr")
EXPECTED_PRODUCT_COUNT = 10
EXPECTED_ASSET_COUNT = EXPECTED_PRODUCT_COUNT * len(EXPECTED_ASSET_KINDS)
PRODUCT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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
        if PRODUCT_ID_PATTERN.fullmatch(product_id) is None:
            raise ProductAssetVerificationError(f"invalid product ID for local asset: {product_id!r}")
        products_by_id[product_id] = product
    return catalog_version, products_by_id


def _real_media_directory(media_root: Path, directory_name: str) -> Path:
    directory = media_root / "media" / directory_name
    if directory.is_symlink() or not directory.is_dir():
        raise ProductAssetVerificationError(
            f"{directory_name} media directory must be a real directory: {directory}"
        )
    resolved_directory = directory.resolve()
    try:
        resolved_directory.relative_to(media_root)
    except ValueError as error:
        raise ProductAssetVerificationError(
            f"{directory_name} media directory escapes media root: {directory}"
        ) from error
    return resolved_directory


def _asset_spec(asset_kind: str, product_id: str) -> tuple[str, str, str, str]:
    if asset_kind == "image":
        return (
            "products",
            f"{product_id}.jpeg",
            f"media/products/{product_id}.jpeg",
            f"assets/products/{product_id}.jpeg",
        )
    if asset_kind == "qr":
        return (
            "qr",
            f"{product_id}/official-product.png",
            f"media/qr/{product_id}/official-product.png",
            f"assets/qr/{product_id}/official-product.png",
        )
    raise ProductAssetVerificationError(f"unsupported product asset kind: {asset_kind!r}")


def verify_product_assets(root: Path, media_root: Path | None = None) -> int:
    """Verify catalog/manifest equivalence and every physical image and QR asset."""

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
        or len(assets) != EXPECTED_ASSET_COUNT
        or any(not isinstance(asset, dict) for asset in assets)
    ):
        raise ProductAssetVerificationError("invalid product asset metadata envelope")

    assets_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for asset in assets:
        asset_kind = asset.get("asset_kind")
        product_id = asset.get("product_id")
        if not isinstance(asset_kind, str) or not isinstance(product_id, str):
            raise ProductAssetVerificationError("product asset kind and ID must be strings")
        key = (asset_kind, product_id)
        if key in assets_by_key:
            raise ProductAssetVerificationError("product asset kind and ID pairs must be unique")
        assets_by_key[key] = asset

    expected_keys = {
        (asset_kind, product_id)
        for asset_kind in EXPECTED_ASSET_KINDS
        for product_id in products_by_id
    }
    if set(assets_by_key) != expected_keys:
        raise ProductAssetVerificationError(
            "image and QR asset IDs must exactly match the canonical catalog IDs"
        )

    resolved_directories = {
        directory_name: _real_media_directory(resolved_media_root, directory_name)
        for directory_name in ("products", "qr")
    }
    expected_entries: dict[str, set[str]] = {"products": set(), "qr": set()}

    for (asset_kind, product_id), asset in assets_by_key.items():
        product = products_by_id[product_id]
        directory_name, filename, expected_relative_path, expected_logical_path = _asset_spec(
            asset_kind, product_id
        )
        relative_path = asset.get("relative_path")
        source_url = asset.get("source_url")
        expected_hash = asset.get("sha256")
        if (
            relative_path != expected_relative_path
            or not isinstance(expected_hash, str)
            or SHA256_PATTERN.fullmatch(expected_hash) is None
            or not isinstance(source_url, str)
            or not isinstance(asset.get("approval_note"), str)
            or not asset["approval_note"].strip()
        ):
            raise ProductAssetVerificationError(
                f"invalid {asset_kind} asset metadata for {product_id!r}"
            )

        unresolved_path = resolved_media_root / Path(relative_path)
        resolved_path = unresolved_path.resolve()
        try:
            resolved_path.relative_to(resolved_directories[directory_name])
        except ValueError as error:
            raise ProductAssetVerificationError(
                f"product {asset_kind} path escapes {directory_name} media directory: {relative_path}"
            ) from error

        catalog_path_field = f"{asset_kind}_asset_path"
        catalog_reason_field = f"{asset_kind}_asset_path_reason"
        if (
            product.get("source_status") != "team_approved_catalog_record"
            or product.get("approved_asset") is not True
            or product.get(catalog_path_field) != expected_logical_path
            or product.get(catalog_reason_field) is not None
            or product.get("official_product_url") != source_url
        ):
            raise ProductAssetVerificationError(
                f"catalog {asset_kind} asset does not match product record for {product_id!r}"
            )
        if (
            unresolved_path.is_symlink()
            or (asset_kind == "qr" and unresolved_path.parent.is_symlink())
            or not resolved_path.is_file()
        ):
            raise ProductAssetVerificationError(
                f"missing product {asset_kind} asset: {unresolved_path}"
            )

        file_bytes = resolved_path.read_bytes()
        if asset_kind == "qr" and not file_bytes.startswith(PNG_SIGNATURE):
            raise ProductAssetVerificationError(f"QR asset is not a PNG file: {relative_path}")
        actual_hash = hashlib.sha256(file_bytes).hexdigest()
        if actual_hash != expected_hash:
            raise ProductAssetVerificationError(
                f"sha256 mismatch for {asset_kind} {product_id}: {actual_hash}"
            )
        expected_entries[directory_name].add(filename)
        if asset_kind == "qr":
            expected_entries[directory_name].add(product_id)

    for directory_name, entries in expected_entries.items():
        directory = resolved_directories[directory_name]
        actual_entries = {
            entry.relative_to(directory).as_posix() for entry in directory.rglob("*")
        }
        if actual_entries != entries:
            missing = sorted(entries - actual_entries)
            unexpected = sorted(actual_entries - entries)
            raise ProductAssetVerificationError(
                f"{directory_name} media directory must contain the exact approved set; "
                f"missing={missing}, unexpected={unexpected}"
            )

    return len(assets_by_key)


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
    print(
        f"[OK] verified {verified_count} exact product image/QR assets "
        f"for {EXPECTED_PRODUCT_COUNT} products under {media_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

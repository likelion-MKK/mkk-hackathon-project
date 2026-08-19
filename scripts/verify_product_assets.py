#!/usr/bin/env python3
"""Verify staged product image paths and SHA-256 metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_ASSET_KIND = "image"


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
    root = args.root.resolve()
    metadata_path = root / "data" / "products" / "mcm-recommendation-catalog-assets-v2.json"
    media_root = (args.media_root or root / "apps" / "kiosk" / "public").resolve()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assets = metadata.get("assets")
    if metadata.get("catalog_version") != "mcm-us-pdp-verified-v3-2026-08-18" or not isinstance(assets, list):
        raise SystemExit("invalid product asset metadata envelope")
    if len(assets) != 10 or len({asset.get("product_id") for asset in assets}) != 10:
        raise SystemExit("product asset metadata must contain exactly 10 unique products")

    for asset in assets:
        product_id = asset.get("product_id")
        relative_path = asset.get("relative_path")
        expected_hash = asset.get("sha256")
        if (
            asset.get("asset_kind") != EXPECTED_ASSET_KIND
            or not isinstance(product_id, str)
            or relative_path != f"media/products/{product_id}.jpeg"
            or not isinstance(expected_hash, str)
        ):
            raise SystemExit(f"invalid asset metadata for {product_id!r}")
        path = media_root / Path(relative_path)
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"missing product image: {path}")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise SystemExit(f"sha256 mismatch for {product_id}: {actual_hash}")

    print(f"[OK] verified {len(assets)} product image assets under {media_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

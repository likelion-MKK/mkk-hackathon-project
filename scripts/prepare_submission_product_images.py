#!/usr/bin/env python3
"""Build a new ten-product submission catalog from user-supplied images."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps


SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
CATALOG_VERSION = "mcm-submission-assets-v1-2026-08-19"


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--source-catalog",
        type=Path,
        default=root / "data/products/mcm-demo-recommendation-profile-v2.json",
    )
    parser.add_argument(
        "--source-matching-catalog",
        type=Path,
        default=root / "data/products/mcm-recommendation-matching-profiles-v1.json",
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        default=root / "apps/kiosk/public/assets/products",
    )
    parser.add_argument(
        "--catalog-output",
        type=Path,
        default=root / "data/products/mcm-submission-recommendation-profile-v2.json",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=root / "data/products/mcm-submission-assets-v1.json",
    )
    parser.add_argument(
        "--matching-catalog-output",
        type=Path,
        default=root / "data/products/mcm-submission-matching-profiles-v1.json",
    )
    parser.add_argument("--catalog-version", default=CATALOG_VERSION)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_exact_image(input_dir: Path, product_id: str) -> Path:
    matches = [
        path
        for path in input_dir.iterdir()
        if path.is_file()
        and path.stem == product_id
        and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    if len(matches) != 1:
        raise ValueError(f"{product_id}: expected exactly one supported image, found {len(matches)}")
    return matches[0]


def _convert_without_metadata(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        clean = Image.new(image.mode, image.size)
        clean.paste(image)
        clean.save(destination, "WEBP", quality=90, method=6, exif=b"", icc_profile=None)


def main() -> int:
    args = parse_args()
    source = json.loads(args.source_catalog.read_text(encoding="utf-8"))
    source_matching = json.loads(
        args.source_matching_catalog.read_text(encoding="utf-8")
    )
    products = source.get("products")
    if not isinstance(products, list) or len(products) != 10:
        raise ValueError("source catalog must contain exactly ten products")
    product_ids = [item.get("product_id") for item in products if isinstance(item, dict)]
    if len(product_ids) != 10 or len(set(product_ids)) != 10:
        raise ValueError("source catalog product IDs must be ten unique strings")
    matching_products = source_matching.get("products")
    matching_ids = {
        item.get("product_id")
        for item in matching_products or []
        if isinstance(item, dict)
    }
    if len(matching_products or []) != 10 or matching_ids != set(product_ids):
        raise ValueError("matching catalog must contain the same ten product IDs")
    if not args.input_dir.is_dir():
        raise ValueError("input directory does not exist")

    output_products: list[dict[str, object]] = []
    assets: list[dict[str, object]] = []
    for item in products:
        product = dict(item)
        product_id = str(product["product_id"])
        source_image = _find_exact_image(args.input_dir, product_id)
        relative_path = f"assets/products/{product_id}/{product_id}.webp"
        destination = args.asset_root / product_id / f"{product_id}.webp"
        _convert_without_metadata(source_image, destination)
        digest = _sha256(destination)
        product.update(
            {
                "approved_asset": True,
                "source_status": "team_approved_catalog_record",
                "image_asset_path": relative_path,
                "image_asset_path_reason": None,
                "source_note": (
                    str(product["source_note"])
                    + " 제출자가 제공한 상품 이미지를 WebP로 정규화하고 EXIF를 제거해 제출 자산으로 승인했습니다."
                ),
            }
        )
        output_products.append(product)
        assets.append(
            {
                "product_id": product_id,
                "asset_kind": "image",
                "relative_path": relative_path,
                "source_url": None,
                "sha256": digest,
                "approval_note": "user_supplied_submission_image_webp_exif_removed",
            }
        )

    catalog = {
        "schema_version": source.get("schema_version", "2.0"),
        "catalog_version": args.catalog_version,
        "products": output_products,
    }
    metadata = {
        "schema_version": "1.0",
        "catalog_version": args.catalog_version,
        "assets": assets,
    }
    matching_catalog = dict(source_matching)
    matching_catalog["catalog_version"] = args.catalog_version
    args.catalog_output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
    args.matching_catalog_output.parent.mkdir(parents=True, exist_ok=True)
    args.catalog_output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.metadata_output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.matching_catalog_output.write_text(
        json.dumps(matching_catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "submission_assets_prepared "
        f"catalog_version={args.catalog_version} product_count=10 exif_removed=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

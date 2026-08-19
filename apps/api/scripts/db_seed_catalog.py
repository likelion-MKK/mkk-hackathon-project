#!/usr/bin/env python3
"""Validate or insert the canonical ten-product catalog without overwrites."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

from apps.api.app.v2_postgres import (
    load_canonical_catalog,
    require_direct_database_url,
    seed_catalog,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--assets", type=Path)
    return parser.parse_args()


def load_assets(path: Path, *, catalog_version: str, product_ids: set[str]) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("catalog_version") != catalog_version:
        raise ValueError("asset metadata catalog_version does not match catalog")
    assets = payload.get("assets")
    if not isinstance(assets, list) or len(assets) != 10:
        raise ValueError("asset metadata must contain exactly ten image assets")
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("asset metadata entries must be objects")
        product_id = asset.get("product_id")
        relative_path = asset.get("relative_path")
        digest = asset.get("sha256")
        if (
            product_id not in product_ids
            or product_id in seen
            or asset.get("asset_kind") != "image"
            or not isinstance(relative_path, str)
            or not relative_path.startswith(f"assets/products/{product_id}/")
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(asset.get("approval_note"), str)
            or not asset["approval_note"]
        ):
            raise ValueError("asset metadata entry is invalid")
        seen.add(str(product_id))
    if seen != product_ids:
        raise ValueError("asset metadata product IDs do not match catalog")
    return assets


def seed_assets(connection: object, *, catalog_version: str, assets: list[dict[str, object]]) -> None:
    insert_sql = """
        INSERT INTO recommendation_catalog_asset_v2 (
            catalog_version, product_id, asset_kind, relative_path,
            source_url, sha256, approval_note
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (catalog_version, product_id, asset_kind) DO NOTHING
    """
    rows = [
        (
            catalog_version,
            asset["product_id"],
            asset["asset_kind"],
            asset["relative_path"],
            asset.get("source_url"),
            asset["sha256"],
            asset["approval_note"],
        )
        for asset in assets
    ]
    with connection.cursor() as cursor:
        cursor.executemany(insert_sql, rows)
        cursor.execute(
            """
            SELECT product_id, asset_kind, relative_path, source_url, sha256, approval_note
            FROM recommendation_catalog_asset_v2
            WHERE catalog_version = %s
            ORDER BY product_id, asset_kind
            """,
            (catalog_version,),
        )
        actual = [tuple(row) for row in cursor.fetchall()]
    expected = sorted(
        [tuple(row[1:]) for row in rows],
        key=lambda row: (str(row[0]), str(row[1])),
    )
    if actual != expected:
        raise ValueError("existing asset metadata differs; refusing to overwrite")


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[3]
    catalog_path = args.catalog or (
        root / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
    )
    catalog = load_canonical_catalog(
        catalog_path
    )
    assets = (
        load_assets(
            args.assets,
            catalog_version=catalog.catalog_version,
            product_ids={item.product_id for item in catalog.products},
        )
        if args.assets is not None
        else []
    )
    if args.dry_run:
        print(
            "catalog_seed_dry_run_ok "
            f"catalog_version={catalog.catalog_version} product_count={len(catalog.products)} "
            f"asset_count={len(assets)} overwrite_existing=false "
            "direct_connection_required=true"
        )
        return 0

    database_url = require_direct_database_url(
        os.getenv("MIGRATION_DATABASE_URL", "")
    )
    import psycopg

    with psycopg.connect(database_url) as connection:
        seed_catalog(connection, catalog)
        if assets:
            seed_assets(connection, catalog_version=catalog.catalog_version, assets=assets)
    print(
        "catalog_seed_verified "
        f"catalog_version={catalog.catalog_version} product_count={len(catalog.products)} "
        f"asset_count={len(assets)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

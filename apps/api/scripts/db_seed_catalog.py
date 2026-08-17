#!/usr/bin/env python3
"""Validate or insert the canonical ten-product catalog without overwrites."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[3]
    catalog = load_canonical_catalog(
        root / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
    )
    if args.dry_run:
        print(
            "catalog_seed_dry_run_ok "
            f"catalog_version={catalog.catalog_version} product_count={len(catalog.products)} "
            "overwrite_existing=false direct_connection_required=true"
        )
        return 0

    database_url = require_direct_database_url(
        os.getenv("MIGRATION_DATABASE_URL", "")
    )
    import psycopg

    with psycopg.connect(database_url) as connection:
        seed_catalog(connection, catalog)
    print(
        "catalog_seed_verified "
        f"catalog_version={catalog.catalog_version} product_count={len(catalog.products)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

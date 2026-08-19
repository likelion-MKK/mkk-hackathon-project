#!/usr/bin/env python3
"""Validate or apply ordered PostgreSQL migrations using the direct URL."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from apps.api.app.v2_postgres import REQUIRED_MIGRATION_ID, require_direct_database_url


ALLOWED_TABLES = {
    "mcm_schema_migration",
    "recommendation_catalog_asset_v2",
    "recommendation_catalog_v2",
    "recommendation_job_v2",
}


def _migration_files() -> list[Path]:
    migration_directory = Path(__file__).resolve().parents[1] / "migrations"
    files = sorted(migration_directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not files or files[-1].stem != REQUIRED_MIGRATION_ID:
        raise RuntimeError("ordered migration set is incomplete")
    return files


def validate_migrations(files: list[Path]) -> None:
    numbers = [int(path.name[:4]) for path in files]
    if numbers != list(range(1, len(files) + 1)):
        raise RuntimeError("migration numbers must be contiguous and ordered")
    for path in files:
        sql = path.read_text(encoding="utf-8")
        if not sql.strip():
            raise RuntimeError(f"empty migration: {path.name}")
        created_tables = {
            match.lower()
            for match in re.findall(
                r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z0-9_]+)",
                sql,
                flags=re.IGNORECASE,
            )
        }
        unexpected = created_tables - ALLOWED_TABLES
        if unexpected:
            raise RuntimeError(f"migration creates an unapproved table: {path.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = _migration_files()
    validate_migrations(files)
    if args.dry_run:
        print(
            "migration_dry_run_ok "
            f"count={len(files)} latest={files[-1].stem} direct_connection_required=true"
        )
        return 0

    database_url = require_direct_database_url(
        os.getenv("MIGRATION_DATABASE_URL", "")
    )
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for path in files:
                sql = path.read_text(encoding="utf-8")
                has_transaction = re.search(
                    r"^\s*BEGIN\s*;", sql, flags=re.IGNORECASE | re.MULTILINE
                ) is not None
                if has_transaction:
                    cursor.execute(sql)
                else:
                    cursor.execute("BEGIN")
                    try:
                        cursor.execute(sql)
                    except Exception:
                        cursor.execute("ROLLBACK")
                        raise
                    cursor.execute("COMMIT")
                print(f"migration_applied id={path.stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

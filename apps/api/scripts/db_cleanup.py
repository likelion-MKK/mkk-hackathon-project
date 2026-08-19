#!/usr/bin/env python3
"""Preview or execute bounded orphan and terminal job cleanup."""

from __future__ import annotations

import argparse
import os

from apps.api.app.v2_postgres import psycopg_persistence


def _positive_seconds(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    orphan_seconds = _positive_seconds("V2_ORPHAN_JOB_SECONDS", 1_800.0)
    retention_seconds = _positive_seconds("V2_JOB_RETENTION_SECONDS", 86_400.0)
    if args.dry_run:
        print(
            "cleanup_dry_run_ok table=recommendation_job_v2 "
            "orphan_statuses=pending,running "
            "retention_statuses=completed,failed,cancelled,insufficient_data "
            f"orphan_seconds={orphan_seconds:g} retention_seconds={retention_seconds:g}"
        )
        return 0

    database_url = os.getenv("DATABASE_URL", "")
    persistence = psycopg_persistence(database_url)
    orphan_count = persistence.cleanup_orphan_jobs(orphan_seconds)
    retention_count = persistence.cleanup_retention(retention_seconds)
    print(
        "cleanup_completed table=recommendation_job_v2 "
        f"orphan_failed={orphan_count} retention_deleted={retention_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

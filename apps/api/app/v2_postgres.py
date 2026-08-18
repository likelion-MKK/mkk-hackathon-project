"""Supabase PostgreSQL catalog readiness and minimal v2 job persistence.

Runtime connections use ``DATABASE_URL``. Migration, seed and backup tooling
uses ``MIGRATION_DATABASE_URL`` separately. This module never accepts a frame
timeline, gaze coordinate, token, request body, or raw model response.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, Sequence
from urllib.parse import urlsplit

from apps.api.app.v2_models import (
    ProductRecommendationProfileV2,
    RecommendationAcceptedV2,
    RecommendationDecisionV2,
    RecommendationVersionV2,
)


REQUIRED_MIGRATION_ID = "0004_supabase_backend_rls"
TERMINAL_JOB_STATUSES = (
    "completed",
    "failed",
    "cancelled",
    "insufficient_data",
)
ReadinessReasonCode = Literal[
    "database_not_configured",
    "db_unavailable",
    "migration_version_mismatch",
    "catalog_count_mismatch",
    "catalog_revision_mismatch",
    "catalog_product_mismatch",
    "catalog_content_mismatch",
    "job_intake_unavailable",
]
JobFailureReasonCode = Literal[
    "service_restart",
    "orphan_cleanup",
    "cancelled",
    "job_start_failed",
    "model_unavailable",
    "invalid_model_output",
    "catalog_mismatch",
    "insufficient_valid_signal",
    "no_eligible_product",
]


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    ready: bool
    reason: ReadinessReasonCode | None = None

    def __post_init__(self) -> None:
        if self.ready == (self.reason is not None):
            raise ValueError("ready state must have no reason and not-ready state needs one")


class CatalogReadinessError(RuntimeError):
    def __init__(self, reason: ReadinessReasonCode) -> None:
        super().__init__(reason)
        self.reason = reason


class CursorLike(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Any: ...

    def executemany(self, query: str, params_seq: list[tuple[object, ...]]) -> Any: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def __enter__(self) -> "CursorLike": ...

    def __exit__(self, *args: object) -> None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...

    def __enter__(self) -> "ConnectionLike": ...

    def __exit__(self, *args: object) -> None: ...


ConnectionFactory = Callable[[], ConnectionLike]


INSERT_CATALOG_SQL = """
INSERT INTO recommendation_catalog_v2 (
    catalog_version, product_id, display_name, category, controlled_tags,
    recommendation_summary, style, approved_asset, source_status,
    official_product_url, official_product_url_reason, official_listing_url,
    image_asset_path, image_asset_path_reason, qr_asset_path,
    qr_asset_path_reason, source_note
) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (catalog_version, product_id) DO NOTHING
"""


def load_canonical_catalog(path: Path) -> ProductRecommendationProfileV2:
    catalog = ProductRecommendationProfileV2.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
    ids = [product.product_id for product in catalog.products]
    if len(ids) != 10 or len(set(ids)) != 10:
        raise ValueError("canonical v2 catalog must contain exactly 10 unique product IDs")
    return catalog


def _catalog_insert_rows(
    catalog: ProductRecommendationProfileV2,
) -> list[tuple[object, ...]]:
    return [
        (
            catalog.catalog_version,
            product.product_id,
            product.display_name,
            product.category,
            list(product.controlled_tags),
            product.recommendation_summary,
            product.style.model_dump_json(),
            product.approved_asset,
            product.source_status,
            product.official_product_url,
            product.official_product_url_reason,
            product.official_listing_url,
            product.image_asset_path,
            product.image_asset_path_reason,
            product.qr_asset_path,
            product.qr_asset_path_reason,
            product.source_note,
        )
        for product in catalog.products
    ]


def _normalise_json(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


def catalog_readiness_rows(
    catalog: ProductRecommendationProfileV2,
) -> list[tuple[object, ...]]:
    """Return the canonical shape selected by the database readiness query."""

    return [
        (
            product.product_id,
            product.display_name,
            product.category,
            list(product.controlled_tags),
            product.recommendation_summary,
            product.style.model_dump(mode="json"),
            product.approved_asset,
            product.source_status,
            product.official_product_url,
            product.official_product_url_reason,
            product.official_listing_url,
            product.image_asset_path,
            product.image_asset_path_reason,
            product.qr_asset_path,
            product.qr_asset_path_reason,
            product.source_note,
        )
        for product in catalog.products
    ]


def validate_catalog_rows(
    rows: Sequence[tuple[object, ...]],
    catalog: ProductRecommendationProfileV2,
) -> None:
    """Compare database rows with the reviewed canonical revision exactly."""

    if len(rows) != 10:
        raise CatalogReadinessError("catalog_count_mismatch")
    expected = {
        product.product_id: (
            product.display_name,
            product.category,
            tuple(product.controlled_tags),
            product.recommendation_summary,
            product.style.model_dump(mode="json"),
            product.approved_asset,
            product.source_status,
            product.official_product_url,
            product.official_product_url_reason,
            product.official_listing_url,
            product.image_asset_path,
            product.image_asset_path_reason,
            product.qr_asset_path,
            product.qr_asset_path_reason,
            product.source_note,
        )
        for product in catalog.products
    }
    actual_ids = {str(row[0]) for row in rows if row}
    if actual_ids != set(expected):
        raise CatalogReadinessError("catalog_product_mismatch")
    for row in rows:
        if len(row) != 16:
            raise CatalogReadinessError("catalog_content_mismatch")
        product_id = str(row[0])
        actual = (
            row[1],
            row[2],
            tuple(row[3]) if isinstance(row[3], (list, tuple)) else row[3],
            row[4],
            _normalise_json(row[5]),
            row[6],
            row[7],
            row[8],
            row[9],
            row[10],
            row[11],
            row[12],
            row[13],
            row[14],
            row[15],
        )
        if actual != expected[product_id]:
            raise CatalogReadinessError("catalog_content_mismatch")


def _validate_required_migration(cursor: CursorLike) -> None:
    cursor.execute("SELECT to_regclass('public.mcm_schema_migration')")
    relation = cursor.fetchone()
    if relation is None or relation[0] is None:
        raise CatalogReadinessError("migration_version_mismatch")
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM mcm_schema_migration WHERE migration_id = %s)",
        (REQUIRED_MIGRATION_ID,),
    )
    applied = cursor.fetchone()
    if applied is None or applied[0] is not True:
        raise CatalogReadinessError("migration_version_mismatch")


def _load_and_validate_catalog(
    cursor: CursorLike,
    catalog: ProductRecommendationProfileV2,
) -> None:
    cursor.execute(
        "SELECT DISTINCT catalog_version FROM recommendation_catalog_v2 ORDER BY catalog_version"
    )
    versions = {str(row[0]) for row in cursor.fetchall() if row}
    if catalog.catalog_version not in versions:
        raise CatalogReadinessError("catalog_revision_mismatch")
    cursor.execute(
        """
        SELECT product_id, display_name, category, controlled_tags,
               recommendation_summary, style, approved_asset, source_status,
               official_product_url, official_product_url_reason,
               official_listing_url, image_asset_path, image_asset_path_reason,
               qr_asset_path, qr_asset_path_reason, source_note
        FROM recommendation_catalog_v2
        WHERE catalog_version = %s
        ORDER BY product_id
        """,
        (catalog.catalog_version,),
    )
    validate_catalog_rows(cursor.fetchall(), catalog)


def seed_catalog(connection: ConnectionLike, catalog: ProductRecommendationProfileV2) -> None:
    """Insert missing canonical rows without overwriting any reviewed record."""

    with connection.cursor() as cursor:
        cursor.executemany(INSERT_CATALOG_SQL, _catalog_insert_rows(catalog))
        _load_and_validate_catalog(cursor, catalog)


def require_direct_database_url(database_url: str) -> str:
    """Reject a Supabase pooler URL for migration/backup/restore tooling."""

    value = database_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("MIGRATION_DATABASE_URL must be a PostgreSQL connection string")
    hostname = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "MIGRATION_DATABASE_URL must use the Supabase direct connection"
        ) from exc
    if (
        re.fullmatch(r"db\.[a-z0-9-]+\.supabase\.co", hostname) is None
        or port not in {None, 5432}
    ):
        raise ValueError("MIGRATION_DATABASE_URL must use the Supabase direct connection")
    return value


def require_runtime_database_url(database_url: str) -> str:
    """Validate the runtime URL without ever returning it in an error."""

    value = database_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
    hostname = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "DATABASE_URL must use the Supabase IPv4 session pooler"
        ) from exc
    if not hostname.endswith(".pooler.supabase.com") or port not in {None, 5432}:
        raise ValueError("DATABASE_URL must use the Supabase IPv4 session pooler")
    return value


class PostgresDecisionPersistence:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        central_provider: str | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._central_provider = central_provider or os.getenv(
            "CENTRAL_AI_PROVIDER", "openai_luna"
        ).strip() or "openai_luna"
        self._startup_cleanup_complete = False

    def check_readiness(
        self,
        catalog: ProductRecommendationProfileV2,
        *,
        require_job_intake: bool = True,
    ) -> DatabaseReadiness:
        try:
            with self._connection_factory() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                connected = cursor.fetchone()
                if connected is None or connected[0] != 1:
                    return DatabaseReadiness(False, "db_unavailable")
                _validate_required_migration(cursor)
                _load_and_validate_catalog(cursor, catalog)
        except CatalogReadinessError as exc:
            return DatabaseReadiness(False, exc.reason)
        except Exception:
            return DatabaseReadiness(False, "db_unavailable")
        if require_job_intake and not self._startup_cleanup_complete:
            return DatabaseReadiness(False, "job_intake_unavailable")
        return DatabaseReadiness(True)

    def initialize_runtime(
        self, catalog: ProductRecommendationProfileV2
    ) -> DatabaseReadiness:
        # Restart cleanup depends only on a reachable, migrated job table. It
        # must still close in-flight rows when the catalog itself is not ready.
        try:
            with self._connection_factory() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                connected = cursor.fetchone()
                if connected is None or connected[0] != 1:
                    self._startup_cleanup_complete = False
                    return DatabaseReadiness(False, "db_unavailable")
                _validate_required_migration(cursor)
        except CatalogReadinessError as exc:
            self._startup_cleanup_complete = False
            return DatabaseReadiness(False, exc.reason)
        except Exception:
            self._startup_cleanup_complete = False
            return DatabaseReadiness(False, "db_unavailable")
        try:
            self.mark_inflight_jobs_failed_on_startup()
        except Exception:
            self._startup_cleanup_complete = False
            return DatabaseReadiness(False, "db_unavailable")
        self._startup_cleanup_complete = True
        return self.check_readiness(catalog)

    def mark_inflight_jobs_failed_on_startup(self) -> int:
        """Fail pending/running jobs; transient evidence is never restored."""

        query = """
        WITH changed AS (
            UPDATE recommendation_job_v2
            SET status = 'failed', selected_product_id = NULL,
                reason_code = 'model_unavailable', reason_explanation = NULL,
                reason_codes = '{}', evidence = '[]'::jsonb, style = NULL,
                exploration_tendency_code = NULL, data_quality = NULL,
                failure_reason_code = 'service_restart', completed_at = now(),
                updated_at = now(), lock_version = lock_version + 1
            WHERE status IN ('pending', 'running')
            RETURNING 1
        )
        SELECT count(*) FROM changed
        """
        return self._execute_count(query)

    def save_pending(
        self,
        session_id: str,
        accepted: RecommendationAcceptedV2,
        version: RecommendationVersionV2,
    ) -> bool:
        query = """
        INSERT INTO recommendation_job_v2 (
            decision_request_id, recommendation_id, session_id, status,
            input_variant, catalog_version, model_id, model_revision,
            prompt_version, feature_version, deployment_mode, central_provider,
            reason_codes, evidence, created_at, updated_at
        ) VALUES (
            %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s,
            '{}', '[]'::jsonb, now(), now()
        )
        ON CONFLICT DO NOTHING
        RETURNING decision_request_id, recommendation_id, session_id
        """
        params = (
            accepted.decision_request_id,
            accepted.recommendation_id,
            session_id,
            version.input_variant,
            version.catalog_version,
            version.model_id,
            version.model_revision,
            version.prompt_version,
            version.feature_version,
            version.deployment_mode,
            self._central_provider,
        )
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    SELECT decision_request_id, recommendation_id, session_id
                    FROM recommendation_job_v2
                    WHERE recommendation_id = %s
                    """,
                    (accepted.recommendation_id,),
                )
                row = cursor.fetchone()
        return row == (
            accepted.decision_request_id,
            accepted.recommendation_id,
            session_id,
        )

    def claim_job(self, decision_request_id: str) -> bool:
        query = """
        UPDATE recommendation_job_v2
        SET status = 'running', claimed_at = now(), updated_at = now(),
            lock_version = lock_version + 1
        WHERE decision_request_id = %s AND status = 'pending'
        RETURNING decision_request_id
        """
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(query, (decision_request_id,))
            return cursor.fetchone() == (decision_request_id,)

    def save_decision(self, session_id: str, decision: RecommendationDecisionV2) -> bool:
        failure_reason: str | None = (
            None if decision.status == "completed" else decision.reason.code
        )
        query = """
        WITH inserted AS (
            INSERT INTO recommendation_job_v2 (
                decision_request_id, recommendation_id, session_id, status,
                input_variant, selected_product_id, reason_code,
                reason_explanation, reason_codes, evidence, style,
                exploration_tendency_code, data_quality, catalog_version,
                model_id, model_revision, prompt_version, feature_version,
                deployment_mode, central_provider, failure_reason_code,
                created_at, updated_at, completed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, NULL, %s, '[]'::jsonb,
                NULL, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s,
                now(), now(), now()
            )
            ON CONFLICT DO NOTHING
            RETURNING 1
        ), changed AS (
            UPDATE recommendation_job_v2
            SET status = %s, selected_product_id = %s, reason_code = %s,
                reason_explanation = NULL, reason_codes = %s,
                evidence = '[]'::jsonb, style = NULL,
                exploration_tendency_code = %s, data_quality = NULL,
                failure_reason_code = %s, completed_at = now(),
                updated_at = now(), lock_version = lock_version + 1
            WHERE decision_request_id = %s AND session_id = %s
              AND status IN ('pending', 'running')
            RETURNING 1
        )
        SELECT (SELECT count(*) FROM inserted) + (SELECT count(*) FROM changed)
        """
        params = (
            decision.decision_request_id,
            decision.recommendation_id,
            session_id,
            decision.status,
            decision.version.input_variant,
            decision.selected_product_id,
            decision.reason.code,
            list(decision.reason_codes),
            decision.exploration_tendency_code,
            decision.version.catalog_version,
            decision.version.model_id,
            decision.version.model_revision,
            decision.version.prompt_version,
            decision.version.feature_version,
            decision.version.deployment_mode,
            self._central_provider,
            failure_reason,
            decision.status,
            decision.selected_product_id,
            decision.reason.code,
            list(decision.reason_codes),
            decision.exploration_tendency_code,
            failure_reason,
            decision.decision_request_id,
            session_id,
        )
        return self._execute_count(query, params) == 1

    def mark_cancelled(self, decision_request_id: str) -> bool:
        query = """
        UPDATE recommendation_job_v2
        SET status = 'cancelled', selected_product_id = NULL,
            reason_code = NULL, reason_explanation = NULL, reason_codes = '{}',
            evidence = '[]'::jsonb, style = NULL,
            exploration_tendency_code = NULL, data_quality = NULL,
            failure_reason_code = 'cancelled', completed_at = now(),
            updated_at = now(), lock_version = lock_version + 1
        WHERE decision_request_id = %s AND status IN ('pending', 'running')
        RETURNING decision_request_id
        """
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(query, (decision_request_id,))
            return cursor.fetchone() == (decision_request_id,)

    def fail_job(
        self,
        decision_request_id: str,
        reason: JobFailureReasonCode,
    ) -> bool:
        if reason not in {"orphan_cleanup", "job_start_failed"}:
            raise ValueError("fail_job only accepts runtime cleanup reason codes")
        query = """
        UPDATE recommendation_job_v2
        SET status = 'failed', selected_product_id = NULL,
            reason_code = 'model_unavailable', reason_explanation = NULL,
            reason_codes = '{}', evidence = '[]'::jsonb, style = NULL,
            exploration_tendency_code = NULL, data_quality = NULL,
            failure_reason_code = %s, completed_at = now(),
            updated_at = now(), lock_version = lock_version + 1
        WHERE decision_request_id = %s AND status IN ('pending', 'running')
        RETURNING decision_request_id
        """
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(query, (reason, decision_request_id))
            return cursor.fetchone() == (decision_request_id,)

    def cleanup_orphan_jobs(self, orphan_seconds: float) -> int:
        if orphan_seconds <= 0:
            raise ValueError("orphan_seconds must be positive")
        query = """
        WITH changed AS (
            UPDATE recommendation_job_v2
            SET status = 'failed', selected_product_id = NULL,
                reason_code = 'model_unavailable', reason_explanation = NULL,
                reason_codes = '{}', evidence = '[]'::jsonb, style = NULL,
                exploration_tendency_code = NULL, data_quality = NULL,
                failure_reason_code = 'orphan_cleanup', completed_at = now(),
                updated_at = now(), lock_version = lock_version + 1
            WHERE status IN ('pending', 'running')
              AND updated_at < now() - (%s * interval '1 second')
            RETURNING 1
        )
        SELECT count(*) FROM changed
        """
        return self._execute_count(query, (orphan_seconds,))

    def cleanup_retention(self, retention_seconds: float) -> int:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be positive")
        query = """
        WITH deleted AS (
            DELETE FROM recommendation_job_v2
            WHERE status IN ('completed', 'failed', 'cancelled', 'insufficient_data')
              AND updated_at < now() - (%s * interval '1 second')
            RETURNING 1
        )
        SELECT count(*) FROM deleted
        """
        return self._execute_count(query, (retention_seconds,))

    def _execute_count(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> int:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
        if row is None or not isinstance(row[0], int):
            raise RuntimeError("database operation did not return a count")
        return row[0]


def psycopg_persistence(database_url: str) -> PostgresDecisionPersistence:
    """Create the runtime pooler adapter lazily without logging its secret URL."""

    safe_url = require_runtime_database_url(database_url)
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - deployment misconfiguration
        raise RuntimeError("PostgreSQL runtime dependency is unavailable") from exc
    try:
        connect_timeout = max(1, int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5")))
    except ValueError as exc:
        raise ValueError("DB_CONNECT_TIMEOUT_SECONDS must be an integer") from exc

    def connect() -> ConnectionLike:
        return psycopg.connect(safe_url, connect_timeout=connect_timeout)

    return PostgresDecisionPersistence(connect)

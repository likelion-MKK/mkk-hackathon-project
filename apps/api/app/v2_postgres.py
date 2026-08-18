"""PostgreSQL catalog seed and durable v2 job/decision metadata adapter.

The adapter never receives or stores the transient FrameObservationV2 timeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from apps.api.app.v2_models import (
    ProductRecommendationProfileV2,
    RecommendationAcceptedV2,
    RecommendationDecisionV2,
    RecommendationVersionV2,
)


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


UPSERT_CATALOG_SQL = """
INSERT INTO recommendation_catalog_v2 (
    catalog_version, product_id, display_name, category, controlled_tags,
    recommendation_summary, style, approved_asset, source_status,
    official_product_url, official_product_url_reason, official_listing_url,
    image_asset_path, image_asset_path_reason, qr_asset_path,
    qr_asset_path_reason, source_note
) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (catalog_version, product_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    category = EXCLUDED.category,
    controlled_tags = EXCLUDED.controlled_tags,
    recommendation_summary = EXCLUDED.recommendation_summary,
    style = EXCLUDED.style,
    approved_asset = EXCLUDED.approved_asset,
    source_status = EXCLUDED.source_status,
    official_product_url = EXCLUDED.official_product_url,
    official_product_url_reason = EXCLUDED.official_product_url_reason,
    official_listing_url = EXCLUDED.official_listing_url,
    image_asset_path = EXCLUDED.image_asset_path,
    image_asset_path_reason = EXCLUDED.image_asset_path_reason,
    qr_asset_path = EXCLUDED.qr_asset_path,
    qr_asset_path_reason = EXCLUDED.qr_asset_path_reason,
    source_note = EXCLUDED.source_note,
    updated_at = now()
"""


def load_canonical_catalog(path: Path) -> ProductRecommendationProfileV2:
    catalog = ProductRecommendationProfileV2.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
    ids = [product.product_id for product in catalog.products]
    if len(ids) != 10 or len(set(ids)) != 10:
        raise ValueError("canonical v2 catalog must contain exactly 10 unique product IDs")
    return catalog


def seed_catalog(connection: ConnectionLike, catalog: ProductRecommendationProfileV2) -> None:
    """Idempotently upsert the exact reviewed catalog version."""

    rows = [
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
    with connection.cursor() as cursor:
        cursor.executemany(UPSERT_CATALOG_SQL, rows)
        cursor.execute(
            "SELECT count(*) FROM recommendation_catalog_v2 WHERE catalog_version = %s",
            (catalog.catalog_version,),
        )
        count_row = cursor.fetchone()
        if count_row is None or count_row[0] != 10:
            raise RuntimeError("PostgreSQL v2 catalog readiness gate requires exactly 10 rows")


class PostgresDecisionPersistence:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def seed_and_load(self, catalog_path: Path) -> ProductRecommendationProfileV2:
        catalog = load_canonical_catalog(catalog_path)
        with self._connection_factory() as connection:
            seed_catalog(connection, catalog)
        return catalog

    def save_pending(
        self,
        session_id: str,
        accepted: RecommendationAcceptedV2,
        input_variant: Literal["A", "B", "C"],
        version: RecommendationVersionV2,
    ) -> None:
        query = """
        INSERT INTO recommendation_job_v2 (
            decision_request_id, recommendation_id, session_id, status, input_variant,
            catalog_version, model_id, model_revision, prompt_version, feature_version,
            deployment_mode
        ) VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (decision_request_id) DO NOTHING
        """
        params = (
            accepted.decision_request_id,
            accepted.recommendation_id,
            session_id,
            input_variant,
            version.catalog_version,
            version.model_id,
            version.model_revision,
            version.prompt_version,
            version.feature_version,
            version.deployment_mode,
        )
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)

    def save_decision(self, session_id: str, decision: RecommendationDecisionV2) -> None:
        query = """
        INSERT INTO recommendation_job_v2 (
            decision_request_id, recommendation_id, session_id, status, input_variant,
            selected_product_id, reason_code, reason_explanation, reason_codes,
            evidence, style, exploration_tendency_code, data_quality,
            catalog_version, model_id, model_revision, prompt_version,
            feature_version, deployment_mode, completed_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s,
            %s::jsonb, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (decision_request_id) DO UPDATE SET
            status = EXCLUDED.status,
            input_variant = EXCLUDED.input_variant,
            selected_product_id = EXCLUDED.selected_product_id,
            reason_code = EXCLUDED.reason_code,
            reason_explanation = EXCLUDED.reason_explanation,
            reason_codes = EXCLUDED.reason_codes,
            evidence = EXCLUDED.evidence,
            style = EXCLUDED.style,
            exploration_tendency_code = EXCLUDED.exploration_tendency_code,
            data_quality = EXCLUDED.data_quality,
            completed_at = EXCLUDED.completed_at
        """
        params = (
            decision.decision_request_id,
            decision.recommendation_id,
            session_id,
            decision.status,
            decision.version.input_variant,
            decision.selected_product_id,
            decision.reason.code,
            decision.reason.explanation,
            list(decision.reason_codes),
            json.dumps([item.model_dump(mode="json") for item in decision.evidence]),
            None if decision.style is None else decision.style.model_dump_json(),
            decision.exploration_tendency_code,
            decision.data_quality.model_dump_json(),
            decision.version.catalog_version,
            decision.version.model_id,
            decision.version.model_revision,
            decision.version.prompt_version,
            decision.version.feature_version,
            decision.version.deployment_mode,
        )
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)


def psycopg_persistence(database_url: str) -> PostgresDecisionPersistence:
    """Create the production adapter lazily so tests need no live PostgreSQL."""

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - deployment misconfiguration
        raise RuntimeError("DATABASE_URL requires the psycopg package") from exc

    def connect() -> ConnectionLike:
        return psycopg.connect(database_url)

    return PostgresDecisionPersistence(connect)

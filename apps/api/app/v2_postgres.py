"""PostgreSQL catalog seed and durable v2 job/decision metadata adapter.

The adapter never receives or stores the transient FrameObservationV2 timeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class CatalogAssetRecord:
    asset_kind: Literal["image", "qr", "video"]
    product_id: str
    relative_path: str
    source_url: str | None
    sha256: str | None
    approval_note: str


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

UPSERT_ASSET_SQL = """
INSERT INTO recommendation_catalog_asset_v2 (
    catalog_version, product_id, asset_kind, relative_path, source_url,
    sha256, approval_note
) VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (catalog_version, product_id, asset_kind) DO UPDATE SET
    relative_path = EXCLUDED.relative_path,
    source_url = EXCLUDED.source_url,
    sha256 = EXCLUDED.sha256,
    approval_note = EXCLUDED.approval_note,
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


def load_catalog_assets(
    path: Path, catalog: ProductRecommendationProfileV2
) -> list[CatalogAssetRecord]:
    body = json.loads(path.read_text(encoding="utf-8"))
    if (
        body.get("schema_version") != "2.0"
        or body.get("catalog_version") != catalog.catalog_version
    ):
        raise ValueError("product asset metadata does not match the canonical catalog")
    raw_assets = body.get("assets")
    if not isinstance(raw_assets, list) or len(raw_assets) != 10:
        raise ValueError("product asset metadata must contain exactly 10 records")

    products_by_id = {product.product_id: product for product in catalog.products}
    records: list[CatalogAssetRecord] = []
    for raw in raw_assets:
        if not isinstance(raw, dict):
            raise ValueError("product asset metadata records must be objects")
        asset_kind = raw.get("asset_kind")
        product_id = raw.get("product_id")
        relative_path = raw.get("relative_path")
        source_url = raw.get("source_url")
        sha256_value = raw.get("sha256")
        approval_note = raw.get("approval_note")
        if (
            asset_kind != "image"
            or not isinstance(product_id, str)
            or product_id not in products_by_id
            or relative_path != f"media/products/{product_id}.jpeg"
            or not isinstance(source_url, str)
            or not isinstance(sha256_value, str)
            or len(sha256_value) != 64
            or sha256_value != sha256_value.lower()
            or any(character not in "0123456789abcdef" for character in sha256_value)
            or not isinstance(approval_note, str)
            or not approval_note.strip()
        ):
            raise ValueError(f"invalid product asset metadata for {product_id!r}")

        product = products_by_id[product_id]
        if (
            not product.approved_asset
            or product.source_status != "team_approved_catalog_record"
            or product.image_asset_path != f"assets/products/{product_id}.jpeg"
            or product.image_asset_path_reason is not None
            or product.official_product_url != source_url
        ):
            raise ValueError(
                f"catalog image asset does not match product record for {product_id!r}"
            )
        records.append(
            CatalogAssetRecord(
                asset_kind="image",
                product_id=product_id,
                relative_path=relative_path,
                source_url=source_url,
                sha256=sha256_value,
                approval_note=approval_note,
            )
        )

    if {record.product_id for record in records} != set(products_by_id):
        raise ValueError("product asset metadata product IDs must match the canonical catalog")
    return records


def seed_catalog(
    connection: ConnectionLike,
    catalog: ProductRecommendationProfileV2,
    assets: list[CatalogAssetRecord] | None = None,
) -> None:
    """Idempotently upsert the reviewed catalog and optional asset metadata."""

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
        if assets is not None:
            asset_rows = [
                (
                    catalog.catalog_version,
                    asset.product_id,
                    asset.asset_kind,
                    asset.relative_path,
                    asset.source_url,
                    asset.sha256,
                    asset.approval_note,
                )
                for asset in assets
            ]
            cursor.executemany(UPSERT_ASSET_SQL, asset_rows)
        cursor.execute(
            "SELECT count(*) FROM recommendation_catalog_v2 WHERE catalog_version = %s",
            (catalog.catalog_version,),
        )
        count_row = cursor.fetchone()
        if count_row is None or count_row[0] != 10:
            raise RuntimeError("PostgreSQL v2 catalog readiness gate requires exactly 10 rows")

        if assets is not None:
            cursor.execute(
                """
                SELECT count(*), count(DISTINCT product_id)
                FROM recommendation_catalog_asset_v2
                WHERE catalog_version = %s AND asset_kind = 'image'
                """,
                (catalog.catalog_version,),
            )
            asset_count_row = cursor.fetchone()
            if asset_count_row is None or asset_count_row != (10, 10):
                raise RuntimeError(
                    "PostgreSQL v2 asset readiness gate requires exactly 10 image rows "
                    "for 10 distinct products"
                )


class PostgresDecisionPersistence:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def seed_and_load(self, catalog_path: Path) -> ProductRecommendationProfileV2:
        catalog = load_canonical_catalog(catalog_path)
        asset_path = catalog_path.with_name("mcm-recommendation-catalog-assets-v2.json")
        assets = load_catalog_assets(asset_path, catalog)
        with self._connection_factory() as connection:
            seed_catalog(connection, catalog, assets)
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

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.api.app.v2_postgres import (
    UPSERT_ASSET_SQL,
    UPSERT_CATALOG_SQL,
    load_canonical_catalog,
    load_catalog_assets,
    seed_catalog,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = (
    REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
)
ASSET_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "products"
    / "mcm-recommendation-catalog-assets-v2.json"
)


def test_catalog_asset_metadata_matches_all_ten_reviewed_products() -> None:
    catalog = load_canonical_catalog(CATALOG_PATH)
    assets = load_catalog_assets(ASSET_PATH, catalog)

    assert len(assets) == 10
    assert {asset.product_id for asset in assets} == {
        product.product_id for product in catalog.products
    }
    assert all(asset.asset_kind == "image" for asset in assets)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda body: body.update(catalog_version="wrong-version"), "does not match"),
        (
            lambda body: body["assets"].__setitem__(1, body["assets"][0].copy()),
            "product IDs must match",
        ),
        (
            lambda body: body["assets"][0].update(relative_path="media/products/wrong.jpeg"),
            "invalid product asset metadata",
        ),
        (
            lambda body: body["assets"][0].update(sha256="not-a-sha256"),
            "invalid product asset metadata",
        ),
    ],
)
def test_catalog_asset_loader_rejects_mismatch(
    tmp_path: Path, mutation: object, message: str
) -> None:
    body = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    assert callable(mutation)
    mutation(body)
    path = tmp_path / "assets.json"
    path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_catalog_assets(path, load_canonical_catalog(CATALOG_PATH))


class FakeCursor:
    def __init__(self, readiness_rows: list[tuple[object, ...]]) -> None:
        self.readiness_rows = readiness_rows
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def executemany(self, query: str, rows: list[tuple[object, ...]]) -> None:
        self.executemany_calls.append((query, rows))

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        self.execute_calls.append((query, params))

    def fetchone(self) -> tuple[object, ...] | None:
        return self.readiness_rows.pop(0) if self.readiness_rows else None


class FakeConnection:
    def __init__(self, readiness_rows: list[tuple[object, ...]]) -> None:
        self.fake_cursor = FakeCursor(readiness_rows)

    def cursor(self) -> FakeCursor:
        return self.fake_cursor


def test_seed_catalog_upserts_ten_catalog_and_ten_image_asset_rows() -> None:
    catalog = load_canonical_catalog(CATALOG_PATH)
    assets = load_catalog_assets(ASSET_PATH, catalog)
    connection = FakeConnection([(10,), (10, 10)])

    seed_catalog(connection, catalog, assets)

    assert connection.fake_cursor.executemany_calls[0] == (UPSERT_CATALOG_SQL, connection.fake_cursor.executemany_calls[0][1])
    assert len(connection.fake_cursor.executemany_calls[0][1]) == 10
    assert connection.fake_cursor.executemany_calls[1] == (UPSERT_ASSET_SQL, connection.fake_cursor.executemany_calls[1][1])
    assert len(connection.fake_cursor.executemany_calls[1][1]) == 10
    assert "count(DISTINCT product_id)" in connection.fake_cursor.execute_calls[1][0]


@pytest.mark.parametrize("readiness", [(9, 9), (10, 9), (11, 10)])
def test_seed_catalog_rejects_inexact_image_asset_readiness(
    readiness: tuple[int, int]
) -> None:
    catalog = load_canonical_catalog(CATALOG_PATH)
    assets = load_catalog_assets(ASSET_PATH, catalog)

    with pytest.raises(RuntimeError, match="exactly 10 image rows"):
        seed_catalog(FakeConnection([(10,), readiness]), catalog, assets)


def test_all_ten_product_routes_return_reviewed_image_metadata() -> None:
    catalog = load_canonical_catalog(CATALOG_PATH)
    app = create_app(MemoryStore(REPOSITORY_ROOT))

    with TestClient(app) as client:
        for product in catalog.products:
            response = client.get(f"/api/v2/products/{product.product_id}")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["source_status"] == "team_approved_catalog_record"
            assert body["approved_asset"] is True
            assert body["image_asset_path"] == (
                f"assets/products/{product.product_id}.jpeg"
            )
            assert body["official_product_url"] == product.official_product_url


def test_asset_migration_stores_metadata_without_binary_columns() -> None:
    migration = (
        REPOSITORY_ROOT
        / "apps"
        / "api"
        / "migrations"
        / "0002_catalog_assets_v2.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table if not exists recommendation_catalog_asset_v2" in migration
    assert "foreign key (catalog_version, product_id)" in migration
    assert "sha256 char(64)" in migration
    assert "bytea" not in migration
    assert "blob" not in migration

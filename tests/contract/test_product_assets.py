from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.verify_product_assets import (  # noqa: E402
    ProductAssetVerificationError,
    verify_product_assets,
)


class ProductAssetVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

        products_data = self.root / "data" / "products"
        products_data.mkdir(parents=True)
        for filename in (
            "mcm-demo-recommendation-profile-v2.json",
            "mcm-recommendation-catalog-assets-v2.json",
        ):
            shutil.copy2(REPOSITORY_ROOT / "data" / "products" / filename, products_data)

        shutil.copytree(
            REPOSITORY_ROOT / "apps" / "kiosk" / "public" / "media" / "products",
            self.root / "apps" / "kiosk" / "public" / "media" / "products",
        )

    def _read_json(self, relative_path: str) -> dict[str, object]:
        return json.loads((self.root / relative_path).read_text(encoding="utf-8"))

    def _write_json(self, relative_path: str, value: dict[str, object]) -> None:
        (self.root / relative_path).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_repository_fixture_contains_exact_approved_assets(self) -> None:
        self.assertEqual(verify_product_assets(self.root), 10)

    def test_rejects_unexpected_product_media_file(self) -> None:
        unexpected = (
            self.root
            / "apps"
            / "kiosk"
            / "public"
            / "media"
            / "products"
            / "unreviewed.jpeg"
        )
        unexpected.write_bytes(b"not reviewed")

        with self.assertRaisesRegex(ProductAssetVerificationError, "unexpected=.*unreviewed"):
            verify_product_assets(self.root)

    def test_rejects_missing_product_media_file(self) -> None:
        manifest = self._read_json(
            "data/products/mcm-recommendation-catalog-assets-v2.json"
        )
        assets = manifest["assets"]
        self.assertIsInstance(assets, list)
        missing_path = (
            self.root
            / "apps"
            / "kiosk"
            / "public"
            / assets[0]["relative_path"]
        )
        missing_path.unlink()

        with self.assertRaisesRegex(ProductAssetVerificationError, "missing product image"):
            verify_product_assets(self.root)

    def test_rejects_manifest_ids_outside_canonical_catalog(self) -> None:
        manifest_path = "data/products/mcm-recommendation-catalog-assets-v2.json"
        manifest = self._read_json(manifest_path)
        assets = manifest["assets"]
        self.assertIsInstance(assets, list)
        assets[0]["product_id"] = "mcm-unreviewed-product"
        assets[0]["relative_path"] = "media/products/mcm-unreviewed-product.jpeg"
        self._write_json(manifest_path, manifest)

        with self.assertRaisesRegex(ProductAssetVerificationError, "exactly match"):
            verify_product_assets(self.root)

    def test_rejects_path_escape_even_when_catalog_and_manifest_agree(self) -> None:
        catalog_path = "data/products/mcm-demo-recommendation-profile-v2.json"
        manifest_path = "data/products/mcm-recommendation-catalog-assets-v2.json"
        catalog = self._read_json(catalog_path)
        manifest = self._read_json(manifest_path)
        products = catalog["products"]
        assets = manifest["assets"]
        self.assertIsInstance(products, list)
        self.assertIsInstance(assets, list)

        malicious_id = "../../outside"
        products[0]["product_id"] = malicious_id
        products[0]["image_asset_path"] = f"assets/products/{malicious_id}.jpeg"
        assets[0]["product_id"] = malicious_id
        assets[0]["relative_path"] = f"media/products/{malicious_id}.jpeg"
        self._write_json(catalog_path, catalog)
        self._write_json(manifest_path, manifest)

        with self.assertRaisesRegex(ProductAssetVerificationError, "escapes"):
            verify_product_assets(self.root)

    @unittest.skipIf(os.name == "nt", "symlink creation requires elevated Windows privileges")
    def test_rejects_product_image_symlink(self) -> None:
        manifest = self._read_json(
            "data/products/mcm-recommendation-catalog-assets-v2.json"
        )
        assets = manifest["assets"]
        self.assertIsInstance(assets, list)
        products_root = self.root / "apps" / "kiosk" / "public"
        symlink_path = products_root / assets[0]["relative_path"]
        target_path = products_root / assets[1]["relative_path"]
        symlink_path.unlink()
        symlink_path.symlink_to(target_path.name)

        with self.assertRaisesRegex(ProductAssetVerificationError, "missing product image"):
            verify_product_assets(self.root)

    @unittest.skipIf(os.name == "nt", "symlink creation requires elevated Windows privileges")
    def test_rejects_product_media_directory_symlink(self) -> None:
        products_directory = (
            self.root / "apps" / "kiosk" / "public" / "media" / "products"
        )
        real_directory = products_directory.with_name("products-real")
        products_directory.rename(real_directory)
        products_directory.symlink_to(real_directory, target_is_directory=True)

        with self.assertRaisesRegex(ProductAssetVerificationError, "real directory"):
            verify_product_assets(self.root)

    def test_rejects_sha256_mismatch(self) -> None:
        manifest_path = "data/products/mcm-recommendation-catalog-assets-v2.json"
        manifest = self._read_json(manifest_path)
        assets = manifest["assets"]
        self.assertIsInstance(assets, list)
        assets[0]["sha256"] = "0" * 64
        self._write_json(manifest_path, manifest)

        with self.assertRaisesRegex(ProductAssetVerificationError, "sha256 mismatch"):
            verify_product_assets(self.root)


if __name__ == "__main__":
    unittest.main()

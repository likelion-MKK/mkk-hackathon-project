from __future__ import annotations

import hashlib
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

        for directory_name in ("products", "qr"):
            shutil.copytree(
                REPOSITORY_ROOT
                / "apps"
                / "kiosk"
                / "public"
                / "media"
                / directory_name,
                self.root
                / "apps"
                / "kiosk"
                / "public"
                / "media"
                / directory_name,
            )

    def _read_json(self, relative_path: str) -> dict[str, object]:
        return json.loads((self.root / relative_path).read_text(encoding="utf-8"))

    def _write_json(self, relative_path: str, value: dict[str, object]) -> None:
        (self.root / relative_path).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _asset(self, asset_kind: str) -> dict[str, object]:
        manifest = self._read_json(
            "data/products/mcm-recommendation-catalog-assets-v2.json"
        )
        assets = manifest["assets"]
        self.assertIsInstance(assets, list)
        return next(asset for asset in assets if asset["asset_kind"] == asset_kind)

    def test_repository_fixture_contains_exact_approved_assets(self) -> None:
        self.assertEqual(verify_product_assets(self.root), 20)

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

    def test_rejects_unexpected_qr_media_file(self) -> None:
        unexpected = (
            self.root
            / "apps"
            / "kiosk"
            / "public"
            / "media"
            / "qr"
            / "unreviewed.png"
        )
        unexpected.write_bytes(b"not reviewed")

        with self.assertRaisesRegex(ProductAssetVerificationError, "unexpected=.*unreviewed"):
            verify_product_assets(self.root)

    def test_rejects_missing_product_media_file(self) -> None:
        image_asset = self._asset("image")
        missing_path = (
            self.root
            / "apps"
            / "kiosk"
            / "public"
            / str(image_asset["relative_path"])
        )
        missing_path.unlink()

        with self.assertRaisesRegex(ProductAssetVerificationError, "missing product image asset"):
            verify_product_assets(self.root)

    def test_rejects_missing_qr_media_file(self) -> None:
        qr_asset = self._asset("qr")
        missing_path = (
            self.root
            / "apps"
            / "kiosk"
            / "public"
            / str(qr_asset["relative_path"])
        )
        missing_path.unlink()

        with self.assertRaisesRegex(ProductAssetVerificationError, "missing product qr asset"):
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
        original_id = products[0]["product_id"]
        products[0]["product_id"] = malicious_id
        products[0]["image_asset_path"] = f"assets/products/{malicious_id}.jpeg"
        products[0]["qr_asset_path"] = f"assets/qr/{malicious_id}.png"
        for asset in assets:
            if asset["product_id"] == original_id:
                asset["product_id"] = malicious_id
                suffix = "jpeg" if asset["asset_kind"] == "image" else "png"
                directory = "products" if asset["asset_kind"] == "image" else "qr"
                asset["relative_path"] = f"media/{directory}/{malicious_id}.{suffix}"
        self._write_json(catalog_path, catalog)
        self._write_json(manifest_path, manifest)

        with self.assertRaisesRegex(ProductAssetVerificationError, "invalid product ID"):
            verify_product_assets(self.root)

    def test_rejects_catalog_qr_path_mismatch(self) -> None:
        catalog_path = "data/products/mcm-demo-recommendation-profile-v2.json"
        catalog = self._read_json(catalog_path)
        products = catalog["products"]
        self.assertIsInstance(products, list)
        products[0]["qr_asset_path"] = "assets/qr/wrong-product.png"
        self._write_json(catalog_path, catalog)

        with self.assertRaisesRegex(ProductAssetVerificationError, "catalog qr asset"):
            verify_product_assets(self.root)

    def test_rejects_qr_source_url_mismatch(self) -> None:
        manifest_path = "data/products/mcm-recommendation-catalog-assets-v2.json"
        manifest = self._read_json(manifest_path)
        assets = manifest["assets"]
        self.assertIsInstance(assets, list)
        next(asset for asset in assets if asset["asset_kind"] == "qr")["source_url"] = (
            "https://example.invalid/not-approved"
        )
        self._write_json(manifest_path, manifest)

        with self.assertRaisesRegex(ProductAssetVerificationError, "catalog qr asset"):
            verify_product_assets(self.root)

    def test_rejects_non_png_qr_asset(self) -> None:
        qr_asset = self._asset("qr")
        qr_path = (
            self.root
            / "apps"
            / "kiosk"
            / "public"
            / str(qr_asset["relative_path"])
        )
        qr_path.write_bytes(b"not a png")
        manifest_path = "data/products/mcm-recommendation-catalog-assets-v2.json"
        manifest = self._read_json(manifest_path)
        assets = manifest["assets"]
        self.assertIsInstance(assets, list)
        next(
            asset
            for asset in assets
            if asset["asset_kind"] == "qr"
            and asset["product_id"] == qr_asset["product_id"]
        )["sha256"] = hashlib.sha256(qr_path.read_bytes()).hexdigest()
        self._write_json(manifest_path, manifest)

        with self.assertRaisesRegex(ProductAssetVerificationError, "not a PNG"):
            verify_product_assets(self.root)

    @unittest.skipIf(os.name == "nt", "symlink creation requires elevated Windows privileges")
    def test_rejects_product_image_symlink(self) -> None:
        manifest = self._read_json(
            "data/products/mcm-recommendation-catalog-assets-v2.json"
        )
        image_assets = [
            asset for asset in manifest["assets"] if asset["asset_kind"] == "image"
        ]
        products_root = self.root / "apps" / "kiosk" / "public"
        symlink_path = products_root / image_assets[0]["relative_path"]
        target_path = products_root / image_assets[1]["relative_path"]
        symlink_path.unlink()
        symlink_path.symlink_to(target_path.name)

        with self.assertRaisesRegex(ProductAssetVerificationError, "missing product image asset"):
            verify_product_assets(self.root)

    @unittest.skipIf(os.name == "nt", "symlink creation requires elevated Windows privileges")
    def test_rejects_qr_media_directory_symlink(self) -> None:
        qr_directory = self.root / "apps" / "kiosk" / "public" / "media" / "qr"
        real_directory = qr_directory.with_name("qr-real")
        qr_directory.rename(real_directory)
        qr_directory.symlink_to(real_directory, target_is_directory=True)

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

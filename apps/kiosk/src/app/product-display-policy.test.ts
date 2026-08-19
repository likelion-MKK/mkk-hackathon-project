import assert from "node:assert/strict";
import test from "node:test";
import type { ProductRecommendationItemV2 } from "./kiosk-types.ts";
import { resolveProductDisplayPolicy } from "./product-display-policy.ts";

const pendingProduct: ProductRecommendationItemV2 = {
  product_id: "mcm-toni-medium-disco-visetos",
  display_name: "Verified listing name only",
  category: "bag",
  controlled_tags: ["monogram", "shopper"],
  recommendation_summary: "Controlled catalog summary",
  style: { silhouette: "trapezoid", visual_tone: "bold", use_cases: ["daily"] },
  approved_asset: false,
  source_status: "official_listing_name_verified_assets_pending",
  official_product_url: null,
  official_product_url_reason: "individual_product_url_unverified",
  official_listing_url: "https://example.invalid/listing",
  image_asset_path: null,
  image_asset_path_reason: "asset_license_review_pending",
  qr_asset_path: null,
  qr_asset_path_reason: "official_product_url_unverified",
  source_note: "pending",
};

test("pending central catalog data never falls back to an image, listing URL, QR, or Manager request", () => {
  assert.deepEqual(resolveProductDisplayPolicy(pendingProduct), {
    isCentralProduct: true,
    catalogApproved: false,
    showProductDetails: false,
    imageUrl: null,
    officialProductUrl: null,
    qrUrl: null,
    canRequestManager: false,
    unavailableMessage: "상품 정보 준비 중",
  });
});

test("reviewed product shows only approved local assets and an approved official URL", () => {
  const product: ProductRecommendationItemV2 = {
    ...pendingProduct,
    source_status: "team_approved_catalog_record",
    approved_asset: true,
    official_product_url: "https://official.example/product",
    official_product_url_reason: null,
    image_asset_path: "assets/products/mcm-toni-medium-disco-visetos.jpeg",
    image_asset_path_reason: null,
    qr_asset_path: "assets/qr/mcm-toni-medium-disco-visetos.png",
    qr_asset_path_reason: null,
  };

  assert.deepEqual(resolveProductDisplayPolicy(product), {
    isCentralProduct: true,
    catalogApproved: true,
    showProductDetails: true,
    imageUrl: "/media/products/mcm-toni-medium-disco-visetos.jpeg",
    officialProductUrl: "https://official.example/product",
    qrUrl: "/media/qr/mcm-toni-medium-disco-visetos.png",
    canRequestManager: true,
    unavailableMessage: null,
  });
});

test("approved product does not accept a non-local asset path", () => {
  const product: ProductRecommendationItemV2 = {
    ...pendingProduct,
    source_status: "team_approved_catalog_record",
    approved_asset: true,
    official_product_url: "https://official.example/product",
    official_product_url_reason: null,
    image_asset_path: "https://unreviewed.example/image.jpg",
    image_asset_path_reason: null,
    qr_asset_path: "../not-allowed.png",
    qr_asset_path_reason: null,
  };
  const policy = resolveProductDisplayPolicy(product);
  assert.equal(policy.imageUrl, null);
  assert.equal(policy.qrUrl, null);
  assert.equal(policy.canRequestManager, true);
});

test("team-approved metadata remains closed until its asset is approved", () => {
  const product: ProductRecommendationItemV2 = {
    ...pendingProduct,
    source_status: "team_approved_catalog_record",
    official_product_url: "https://official.example/product",
    official_product_url_reason: null,
  };

  assert.deepEqual(resolveProductDisplayPolicy(product), {
    isCentralProduct: true,
    catalogApproved: false,
    showProductDetails: false,
    imageUrl: null,
    officialProductUrl: null,
    qrUrl: null,
    canRequestManager: false,
    unavailableMessage: "상품 정보 준비 중",
  });
});

test("an approved image and official URL do not require a QR asset", () => {
  const product: ProductRecommendationItemV2 = {
    ...pendingProduct,
    source_status: "team_approved_catalog_record",
    approved_asset: true,
    official_product_url: "https://official.example/product",
    official_product_url_reason: null,
    image_asset_path: "assets/products/mcm-toni-medium-disco-visetos.jpeg",
    image_asset_path_reason: null,
    qr_asset_path: null,
    qr_asset_path_reason: "qr_asset_generation_pending",
  };
  const policy = resolveProductDisplayPolicy(product);

  assert.equal(policy.imageUrl, "/media/products/mcm-toni-medium-disco-visetos.jpeg");
  assert.equal(policy.officialProductUrl, "https://official.example/product");
  assert.equal(policy.qrUrl, null);
  assert.equal(policy.canRequestManager, true);
  assert.equal(policy.unavailableMessage, null);
});

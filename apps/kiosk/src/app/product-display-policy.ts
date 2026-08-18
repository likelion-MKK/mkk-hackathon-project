import type { Product, ProductRecommendationItemV2 } from "./kiosk-types.ts";

export type ProductDisplayPolicy = Readonly<{
  isCentralProduct: boolean;
  catalogApproved: boolean;
  showProductDetails: boolean;
  imageUrl: string | null;
  officialProductUrl: string | null;
  qrUrl: string | null;
  canRequestManager: boolean;
  unavailableMessage: string | null;
}>;

function isCentralProduct(
  product: Product | ProductRecommendationItemV2,
): product is ProductRecommendationItemV2 {
  return "controlled_tags" in product;
}

function localAssetUrl(path: string | null): string | null {
  if (
    !path ||
    path.startsWith("/") ||
    path.includes("..") ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/.test(path)
  ) {
    return null;
  }
  return `/${path}`;
}

/**
 * Keep asset and Manager UI fail-closed until the reviewed catalog record is
 * explicitly promoted. A pending listing name is not enough to display an
 * arbitrary image, QR code, listing link, or staff request.
 */
export function resolveProductDisplayPolicy(
  product: Product | ProductRecommendationItemV2,
): ProductDisplayPolicy {
  if (!isCentralProduct(product)) {
    return {
      isCentralProduct: false,
      catalogApproved: true,
      showProductDetails: true,
      imageUrl: product.image_url,
      officialProductUrl: product.product_url,
      qrUrl: product.qr_asset_path,
      canRequestManager: true,
      unavailableMessage: null,
    };
  }

  const catalogApproved = product.source_status === "team_approved_catalog_record";
  if (!catalogApproved) {
    return {
      isCentralProduct: true,
      catalogApproved: false,
      showProductDetails: false,
      imageUrl: null,
      officialProductUrl: null,
      qrUrl: null,
      canRequestManager: false,
      unavailableMessage: "상품 정보 준비 중",
    };
  }

  const imageUrl = product.approved_asset ? localAssetUrl(product.image_asset_path) : null;
  const officialProductUrl = product.official_product_url;
  const qrUrl = product.approved_asset && officialProductUrl
    ? localAssetUrl(product.qr_asset_path)
    : null;
  return {
    isCentralProduct: true,
    catalogApproved: true,
    showProductDetails: true,
    imageUrl,
    officialProductUrl,
    qrUrl,
    canRequestManager: officialProductUrl !== null,
    unavailableMessage:
      imageUrl && qrUrl
        ? null
        : "검수된 상품 이미지·공식 URL·QR 정보를 준비하고 있습니다.",
  };
}

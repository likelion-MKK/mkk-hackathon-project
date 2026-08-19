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

function localAssetUrl(
  path: string | null,
  logicalPrefix: "assets/products" | "assets/qr",
  publicPrefix: "media/products" | "media/qr",
  expectedFilename?: string,
): string | null {
  if (
    !path ||
    path.startsWith("/") ||
    path.includes("..") ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/.test(path) ||
    !path.startsWith(`${logicalPrefix}/`)
  ) {
    return null;
  }
  if (expectedFilename && path !== `${logicalPrefix}/${expectedFilename}`) {
    return null;
  }
  return `/${publicPrefix}/${path.slice(logicalPrefix.length + 1)}`;
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

  const catalogApproved =
    product.source_status === "team_approved_catalog_record" && product.approved_asset;
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

  const imageUrl = localAssetUrl(
    product.image_asset_path,
    "assets/products",
    "media/products",
    `${product.product_id}.jpeg`,
  );
  if (imageUrl === null) {
    return {
      isCentralProduct: true,
      catalogApproved: true,
      showProductDetails: false,
      imageUrl: null,
      officialProductUrl: null,
      qrUrl: null,
      canRequestManager: false,
      unavailableMessage: "검수된 상품 이미지를 준비하고 있습니다.",
    };
  }

  const officialProductUrl = product.official_product_url;
  const qrUrl = officialProductUrl
    ? localAssetUrl(
        product.qr_asset_path,
        "assets/qr",
        "media/qr",
        `${product.product_id}/official-product.png`,
      )
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
      officialProductUrl === null ? "공식 상품 URL을 준비하고 있습니다." : null,
  };
}

export function isProductDisplayReady(
  policy: ProductDisplayPolicy,
  imageLoaded: boolean,
): boolean {
  return policy.showProductDetails && policy.imageUrl !== null && imageLoaded;
}

import type { ManagerProductRequestV2 } from "./kiosk-types.ts";

const CONTRACT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
const CONTRACT_ID_MAX_LENGTH = 128;

export function buildManagerProductRequestV2(
  sessionId: string,
  recommendationId: string,
  selectedProductId: string,
): ManagerProductRequestV2 {
  const requestId = `manager-request-${sessionId}-${recommendationId}`;
  if (
    requestId.length > CONTRACT_ID_MAX_LENGTH ||
    !CONTRACT_ID_PATTERN.test(requestId)
  ) {
    throw new Error("The stable manager request ID does not satisfy the v2 contract.");
  }

  return {
    schema_version: "2.0",
    request_id: requestId,
    recommendation_id: recommendationId,
    selected_product_id: selectedProductId,
    intent: "view_recommended_product",
  };
}

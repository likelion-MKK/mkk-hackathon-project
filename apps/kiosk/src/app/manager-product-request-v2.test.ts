import assert from "node:assert/strict";
import test from "node:test";
import { buildManagerProductRequestV2 } from "./manager-product-request-v2.ts";

test("같은 추천의 매니저 요청은 재시도해도 동일한 멱등 ID를 사용한다", () => {
  const first = buildManagerProductRequestV2(
    "session-v2-001",
    "recommendation-v2-001",
    "mcm-pina-vanity-case-studded-calfskin",
  );
  const retry = buildManagerProductRequestV2(
    "session-v2-001",
    "recommendation-v2-001",
    "mcm-pina-vanity-case-studded-calfskin",
  );

  assert.deepEqual(retry, first);
  assert.deepEqual(first, {
    schema_version: "2.0",
    request_id: "manager-request-session-v2-001-recommendation-v2-001",
    recommendation_id: "recommendation-v2-001",
    selected_product_id: "mcm-pina-vanity-case-studded-calfskin",
    intent: "view_recommended_product",
  });
});

test("계약 최대 길이를 넘는 매니저 요청 ID는 보내지 않는다", () => {
  assert.throws(
    () =>
      buildManagerProductRequestV2(
        `session-${"a".repeat(80)}`,
        `recommendation-${"b".repeat(80)}`,
        "mcm-pina-vanity-case-studded-calfskin",
      ),
    /does not satisfy/,
  );
});

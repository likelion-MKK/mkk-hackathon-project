import assert from "node:assert/strict";
import test from "node:test";

import { ManagerApiClient, requestedProductId, type ManagerEvent } from "./api.ts";

function eventWithPayload(payload: ManagerEvent["payload"]): ManagerEvent {
  return {
    schema_version: "2.0",
    event_id: "manager-event-001",
    sequence: 1,
    session_id: "session-001",
    kiosk_id: "kiosk-001",
    event_type: "customer_product_request",
    emitted_at: "2026-08-16T00:00:00Z",
    payload,
  };
}

test("v2 selected product is the manager card source", () => {
  const event = eventWithPayload({
    intent: "view_recommended_product",
    recommendation_id: "recommendation-v2-001",
    selected_product_id: "mcm-toni-medium-disco-visetos",
  });

  assert.equal(requestedProductId(event), "mcm-toni-medium-disco-visetos");
});

test("manager client polls only the v2 event and product endpoints", async () => {
  const originalFetch = globalThis.fetch;
  const requestedUrls: string[] = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    requestedUrls.push(url);
    return new Response(url.includes("/manager/events") ? "[]" : "{}", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const client = new ManagerApiClient("http://localhost:8000/");
    await client.listEvents(4);
    await client.getProduct("mcm-toni-medium-disco-visetos");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requestedUrls, [
    "http://localhost:8000/api/v2/manager/events?after_sequence=4",
    "http://localhost:8000/api/v2/products/mcm-toni-medium-disco-visetos",
  ]);
});

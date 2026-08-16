import assert from "node:assert/strict";
import test from "node:test";
import { ApiRequestError, HttpApiClient } from "./HttpApiClient.ts";

test("HTTP API client uses the configured backend and JSON contracts", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(
      JSON.stringify({
        session_id: "session-0001",
        display_code: "MKK-0001",
        status: "collecting",
        created_at: "2026-08-16T00:00:00Z",
      }),
      { status: 201, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  try {
    const client = new HttpApiClient("http://localhost:8000/");
    const result = await client.createSession({
      kiosk_id: "kiosk-001",
      lookbook_id: "mcm-lookbook-example-v1",
      consent_version: "consent-v1",
    });
    assert.equal(result.session_id, "session-0001");
    assert.equal(calls[0]?.url, "http://localhost:8000/api/v1/sessions");
    assert.equal(calls[0]?.init?.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("HTTP API client preserves structured API failures", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ code: "session_not_found", message: "missing" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;

  try {
    const client = new HttpApiClient("");
    await assert.rejects(
      () => client.getSessionRecommendation("session-missing"),
      (error: unknown) =>
        error instanceof ApiRequestError &&
        error.status === 404 &&
        error.code === "session_not_found",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("HTTP API client uses v2 observation, completion, polling, and cleanup routes", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const originalFetch = globalThis.fetch;
  const responses = [
    new Response(JSON.stringify({ batch_id: "batch-v2-001", status: "accepted" }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    }),
    new Response(
      JSON.stringify({
        recommendation_id: "recommendation-v2-001",
        decision_request_id: "decision-v2-001",
        status: "pending",
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    ),
    new Response(
      JSON.stringify({
        recommendation_id: "recommendation-v2-001",
        decision_request_id: "decision-v2-001",
        status: "pending",
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    ),
    new Response(
      JSON.stringify({
        product_id: "mcm-diamant-3d-small-calfskin",
        display_name: "Small Diamant 3D Shoulder Bag in Calfskin",
        category: "bag",
        controlled_tags: ["compact", "leather", "structured"],
        recommendation_summary: "팀 검수 요약",
        style: {
          silhouette: "boxy",
          visual_tone: "refined",
          use_cases: ["evening"],
        },
        approved_asset: false,
        source_status: "official_listing_name_verified_assets_pending",
        official_product_url: null,
        official_product_url_reason: "individual_product_url_unverified",
        official_listing_url: "https://us.mcmworldwide.com/en_US/women/bags/all-bags",
        image_asset_path: null,
        image_asset_path_reason: "asset_license_review_pending",
        qr_asset_path: null,
        qr_asset_path_reason: "official_product_url_unverified",
        source_note: "공식 listing에서 이름만 확인",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
    new Response(JSON.stringify({ request_id: "manager-request-v2-001", status: "accepted" }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    }),
    new Response(null, { status: 204 }),
  ];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const response = responses.shift();
    if (!response) throw new Error("unexpected request");
    return response;
  }) as typeof fetch;

  try {
    const client = new HttpApiClient("http://localhost:8000");
    await client.appendObservationBatch("session-v2-001", {
      schema_version: "2.0",
      batch_id: "batch-v2-001",
      batch_sequence: 0,
      session_id: "session-v2-001",
      video_id: "video-v2-001",
      observations: [
        {
          schema_version: "2.0",
          frame_id: "frame-v2-001",
          sequence: 0,
          captured_at_mono_ms: 250,
          session_offset_ms: 0,
          video_time_ms: 250,
          playback_epoch: 0,
          gaze: null,
          gaze_reason: "not_observed",
          attention: null,
          attention_reason: "source_gaze_unavailable",
          expression: null,
          expression_reason: "not_observed",
          derived: null,
          derived_reason: "no_valid_signal",
        },
      ],
    });
    await client.completeCentralRecommendation("session-v2-001");
    await client.getCentralRecommendation("session-v2-001");
    await client.getCentralProduct("mcm-diamant-3d-small-calfskin");
    await client.requestCentralManagerProduct("session-v2-001", {
      schema_version: "2.0",
      request_id: "manager-request-v2-001",
      recommendation_id: "recommendation-v2-001",
      selected_product_id: "mcm-diamant-3d-small-calfskin",
      intent: "view_recommended_product",
    });
    await client.discardSession("session-v2-001");

    assert.deepEqual(
      calls.map(({ url }) => url),
      [
        "http://localhost:8000/api/v2/sessions/session-v2-001/observations",
        "http://localhost:8000/api/v2/sessions/session-v2-001/complete",
        "http://localhost:8000/api/v2/sessions/session-v2-001/recommendation",
        "http://localhost:8000/api/v2/products/mcm-diamant-3d-small-calfskin",
        "http://localhost:8000/api/v2/sessions/session-v2-001/manager-product-requests",
        "http://localhost:8000/api/v2/sessions/session-v2-001",
      ],
    );
    assert.deepEqual(
      calls.map(({ init }) => init?.method ?? "GET"),
      ["POST", "POST", "GET", "GET", "POST", "DELETE"],
    );
    assert.deepEqual(JSON.parse(String(calls[4]?.init?.body)), {
      schema_version: "2.0",
      request_id: "manager-request-v2-001",
      recommendation_id: "recommendation-v2-001",
      selected_product_id: "mcm-diamant-3d-small-calfskin",
      intent: "view_recommended_product",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

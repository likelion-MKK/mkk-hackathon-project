import assert from "node:assert/strict";
import test from "node:test";
import {
  runSessionStartWithTimeout,
  SessionStartTimeoutError,
} from "../../app/consent-flow.ts";
import type { ProductCategory, ReactionBatch } from "../../app/kiosk-types.ts";
import {
  MOCK_LOOKBOOK_ID_BY_CATEGORY,
  MockApiClient,
} from "./MockApiClient.ts";

const categoryCases: Array<{
  category: ProductCategory;
  productIds: [string, string];
}> = [
  { category: "가방", productIds: ["BAG001", "BAG002"] },
  { category: "의류", productIds: ["RTW001", "RTW002"] },
  { category: "액세서리", productIds: ["ACC001", "ACC002"] },
  { category: "전체 컬렉션", productIds: ["BAG001", "RTW001"] },
];

test("mock API가 세션 생성부터 Top 2 추천까지 계약 형식으로 응답한다", async () => {
  const client = new MockApiClient();
  const lookbookId = MOCK_LOOKBOOK_ID_BY_CATEGORY.가방;
  const session = await client.createSession({
    kiosk_id: "kiosk-d1",
    lookbook_id: lookbookId,
    consent_version: "consent-v1",
  });

  assert.equal(session.status, "collecting");
  assert.match(session.session_id, /^session-d1-mock-/);

  const pending = await client.getSessionRecommendation(session.session_id);
  assert.equal(pending.status, "pending");
  assert.deepEqual(pending.items, []);

  const accepted = await client.completeSessionAnalysis(session.session_id);
  assert.deepEqual(accepted, {
    session_id: session.session_id,
    status: "pending",
  });

  const completed = await client.getSessionRecommendation(session.session_id);
  assert.equal(completed.status, "completed");
  assert.deepEqual(completed.items, [
    { rank: 1, product_id: "BAG001" },
    { rank: 2, product_id: "BAG002" },
  ]);
});

test("카테고리별 manifest와 Top 2 추천 결과를 제공한다", async () => {
  const client = new MockApiClient();

  for (const { category, productIds } of categoryCases) {
    const lookbookId = MOCK_LOOKBOOK_ID_BY_CATEGORY[category];
    const session = await client.createSession({
      kiosk_id: "kiosk-d1",
      lookbook_id: lookbookId,
      consent_version: "consent-v1",
    });
    const manifest = await client.getLookbookManifest(lookbookId);

    assert.equal(manifest.video_id, lookbookId);
    assert.deepEqual(
      manifest.exposures.map((exposure) => exposure.product_id),
      productIds,
    );

    await client.completeSessionAnalysis(session.session_id);
    const recommendation = await client.getSessionRecommendation(session.session_id);

    assert.equal(recommendation.video_id, lookbookId);
    assert.deepEqual(recommendation.items, [
      { rank: 1, product_id: productIds[0] },
      { rank: 2, product_id: productIds[1] },
    ]);

    for (const productId of productIds) {
      const product = await client.getProduct(productId);
      assert.equal(product.product_id, productId);
    }
  }
});

test("mock API가 선택한 manifest와 reaction batch 중복 상태를 제공한다", async () => {
  const client = new MockApiClient();
  const lookbookId = MOCK_LOOKBOOK_ID_BY_CATEGORY.가방;
  const session = await client.createSession({
    kiosk_id: "kiosk-d1",
    lookbook_id: lookbookId,
    consent_version: "consent-v1",
  });
  const manifest = await client.getLookbookManifest(lookbookId);

  assert.equal(manifest.coordinate_space, "video_normalized");
  assert.deepEqual(
    manifest.exposures.map((exposure) => exposure.product_id),
    ["BAG001", "BAG002"],
  );

  const batch: ReactionBatch = {
    schema_version: "1.0",
    batch_id: "batch-d1-0001",
    batch_sequence: 0,
    session_id: session.session_id,
    video_id: lookbookId,
    events: [
      {
        schema_version: "1.0",
        session_id: session.session_id,
        event_id: "expression-d1-0001",
        sequence: 1,
        frame_id: "frame-d1-0001",
        captured_at_mono_ms: 100,
        video_id: lookbookId,
        video_time_ms: 100,
        playback_epoch: 0,
        producer_id: "mock-vision-client-face",
        model_revision: "d1-mock-v1",
        taxonomy_version: "d1-mock-taxonomy-v1",
        face_detected: true,
        face_count: 1,
        scores: { unknown: 0.58 },
        quality: 0.79,
        valid: true,
        confidence: 0.82,
        reason: null,
      },
    ],
  };

  assert.equal((await client.appendReactionBatch(session.session_id, batch)).status, "accepted");
  assert.equal((await client.appendReactionBatch(session.session_id, batch)).status, "duplicate");

  await client.completeSessionAnalysis(session.session_id);
  await assert.rejects(
    client.appendReactionBatch(session.session_id, batch),
    /Completed mock sessions cannot accept reaction batches/,
  );
});

test("mock API가 알 수 없는 세션을 정상 응답으로 꾸미지 않는다", async () => {
  const client = new MockApiClient();

  await assert.rejects(
    client.getSessionRecommendation("missing-session"),
    /Unknown mock session/,
  );
});

test("mock API가 알 수 없는 lookbook으로 세션을 만들지 않는다", async () => {
  const client = new MockApiClient();

  await assert.rejects(
    client.createSession({
      kiosk_id: "kiosk-d1",
      lookbook_id: "missing-lookbook",
      consent_version: "consent-v1",
    }),
    /Unknown mock lookbook/,
  );
  await assert.rejects(client.getLookbookManifest("missing-lookbook"), /Unknown mock lookbook/);
});

test("mock API의 세션 시작 지연값을 안전하게 검증한다", () => {
  assert.throws(
    () => new MockApiClient({ sessionStartDelayMs: -1 }),
    /non-negative finite number/,
  );
});

test("화면 세션이 끝나면 Mock 추천 상태와 익명 세션 metadata를 폐기한다", async () => {
  const client = new MockApiClient();
  const session = await client.createSession({
    kiosk_id: "kiosk-d2-retention",
    lookbook_id: MOCK_LOOKBOOK_ID_BY_CATEGORY.가방,
    consent_version: "consent-v2",
  });

  client.discardSession(session.session_id);

  await assert.rejects(
    client.getSessionRecommendation(session.session_id),
    /Unknown mock session/,
  );
});

test("timeout된 Mock 세션은 늦게 생성되지 않고 재시도가 첫 세션을 만든다", async () => {
  const client = new MockApiClient({ sessionStartDelayMs: 25 });
  const request = {
    kiosk_id: "kiosk-d2-timeout",
    lookbook_id: MOCK_LOOKBOOK_ID_BY_CATEGORY.가방,
    consent_version: "consent-v1",
  };

  await assert.rejects(
    runSessionStartWithTimeout(
      (signal) => client.createSession(request, { signal }),
      { timeoutMs: 5 },
    ),
    SessionStartTimeoutError,
  );
  await new Promise((resolve) => globalThis.setTimeout(resolve, 30));

  const retrySession = await client.createSession(request);
  assert.equal(retrySession.session_id, "session-d1-mock-001");
});

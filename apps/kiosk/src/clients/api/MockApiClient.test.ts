import assert from "node:assert/strict";
import test from "node:test";
import type { ReactionBatch } from "../../app/kiosk-types.ts";
import { MOCK_LOOKBOOK_ID, MockApiClient } from "./MockApiClient.ts";

test("mock API가 세션 생성부터 Top 2 추천까지 계약 형식으로 응답한다", async () => {
  const client = new MockApiClient();
  const session = await client.createSession({
    kiosk_id: "kiosk-d1",
    lookbook_id: MOCK_LOOKBOOK_ID,
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
    { rank: 1, product_id: "P001" },
    { rank: 2, product_id: "P002" },
  ]);
});

test("mock API가 공통 manifest와 reaction batch 중복 상태를 제공한다", async () => {
  const client = new MockApiClient();
  const session = await client.createSession({
    kiosk_id: "kiosk-d1",
    lookbook_id: MOCK_LOOKBOOK_ID,
    consent_version: "consent-v1",
  });
  const manifest = await client.getLookbookManifest(MOCK_LOOKBOOK_ID);

  assert.equal(manifest.coordinate_space, "video_normalized");
  assert.deepEqual(
    manifest.exposures.map((exposure) => exposure.product_id),
    ["P001", "P002"],
  );

  const batch: ReactionBatch = {
    schema_version: "1.0",
    batch_id: "batch-d1-0001",
    batch_sequence: 0,
    session_id: session.session_id,
    video_id: MOCK_LOOKBOOK_ID,
    events: [
      {
        schema_version: "1.0",
        session_id: session.session_id,
        event_id: "expression-d1-0001",
        sequence: 1,
        frame_id: "frame-d1-0001",
        captured_at_mono_ms: 100,
        video_id: MOCK_LOOKBOOK_ID,
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
});

test("mock API가 알 수 없는 세션을 정상 응답으로 꾸미지 않는다", async () => {
  const client = new MockApiClient();

  await assert.rejects(
    client.getSessionRecommendation("missing-session"),
    /Unknown mock session/,
  );
});

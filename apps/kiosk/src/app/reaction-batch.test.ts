import assert from "node:assert/strict";
import test from "node:test";
import type {
  ExpressionSample,
  GazeSample,
  LookbookManifest,
  ProductAttentionEvent,
} from "./kiosk-types.ts";
import {
  buildD1ReactionBatch,
  createProductAttentionEvent,
} from "./reaction-batch.ts";

const manifest: LookbookManifest = {
  schema_version: "1.0",
  video_id: "mcm-lookbook-example-v1",
  manifest_version: "example-1.0",
  coordinate_space: "video_normalized",
  exposures: [
    {
      exposure_id: "scene-01-product-01",
      product_id: "P001",
      start_ms: 0,
      end_ms: 10_000,
      priority: 0,
      shape: {
        type: "polygon",
        points: [
          [0.08, 0.18],
          [0.46, 0.18],
          [0.46, 0.88],
          [0.08, 0.88],
        ],
      },
    },
    {
      exposure_id: "overlapping-product",
      product_id: "P003",
      start_ms: 0,
      end_ms: 10_000,
      priority: 1,
      shape: {
        type: "polygon",
        points: [
          [0.2, 0.3],
          [0.4, 0.3],
          [0.4, 0.6],
          [0.2, 0.6],
        ],
      },
    },
    {
      exposure_id: "expired-product",
      product_id: "P004",
      start_ms: 0,
      end_ms: 100,
      priority: 0,
      shape: {
        type: "polygon",
        points: [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 1],
        ],
      },
    },
  ],
};

const validGazeSample: GazeSample = {
  schema_version: "1.0",
  session_id: "session-example-001",
  event_id: "gaze-example-0001",
  sequence: 1,
  frame_id: "frame-00421",
  captured_at_mono_ms: 143_220.4,
  video_id: manifest.video_id,
  video_time_ms: 4_200,
  playback_epoch: 0,
  producer_id: "mock-vision-client-eye",
  model_revision: "d1-mock-v1",
  calibration_id: "calibration-example-001",
  screen_x_norm: 0.3,
  screen_y_norm: 0.46,
  valid: true,
  confidence: 0.88,
  reason: null,
};

const expressionSample: ExpressionSample = {
  schema_version: "1.0",
  session_id: "session-example-001",
  event_id: "expression-example-0001",
  sequence: 2,
  frame_id: "frame-00421",
  captured_at_mono_ms: 143_220.4,
  video_id: manifest.video_id,
  video_time_ms: 4_200,
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
};

test("시선과 표정 신호를 함께 ReactionBatch에 담는다", () => {
  const batch = buildD1ReactionBatch({
    batchId: "batch-session-example-001-0001",
    batchSequence: 0,
    sessionId: "session-example-001",
    manifest,
    gazeSample: validGazeSample,
    expressionSample,
  });

  assert.ok(batch);
  assert.equal(batch.events.length, 2);
  assert.equal(batch.events[0]?.event_id, expressionSample.event_id);

  const attentionEvent = batch.events[1] as ProductAttentionEvent;
  assert.equal(attentionEvent.source_gaze_event_id, validGazeSample.event_id);
  assert.equal(attentionEvent.sequence, 3);
  assert.equal(attentionEvent.video_x_norm, 0.3);
  assert.equal(attentionEvent.video_y_norm, 0.46);
  assert.deepEqual(
    attentionEvent.candidates.map((candidate) => candidate.product_id),
    ["P001", "P003"],
  );
});

test("AOI의 시간 구간 밖 상품은 관심 후보에서 제외한다", () => {
  const event = createProductAttentionEvent(validGazeSample, manifest, 3, {
    valid: true,
    outside_video: false,
    video_x_norm: 0.3,
    video_y_norm: 0.46,
  });

  assert.equal(event.valid, true);
  assert.equal(event.candidates.some((candidate) => candidate.product_id === "P004"), false);
});

test("무효 시선을 좌표나 상품 후보로 대체하지 않는다", () => {
  const invalidGazeSample: GazeSample = {
    schema_version: "1.0",
    session_id: "session-example-001",
    event_id: "gaze-example-invalid-0001",
    sequence: 3,
    frame_id: "frame-00422",
    captured_at_mono_ms: 143_320.4,
    video_id: manifest.video_id,
    video_time_ms: 4_300,
    playback_epoch: 0,
    producer_id: "mock-vision-client-eye",
    model_revision: "d1-mock-v1",
    calibration_id: "calibration-example-001",
    valid: false,
    confidence: 0,
    reason: "face_not_detected",
  };

  const batch = buildD1ReactionBatch({
    batchId: "batch-session-example-001-0002",
    batchSequence: 1,
    sessionId: "session-example-001",
    manifest,
    gazeSample: invalidGazeSample,
    expressionSample: null,
  });

  assert.ok(batch);
  const event = batch.events[0] as ProductAttentionEvent;
  assert.equal(event.valid, false);
  assert.equal(event.reason, "face_not_detected");
  assert.deepEqual(event.candidates, []);
  assert.equal("video_x_norm" in event, false);
  assert.equal("video_y_norm" in event, false);
});

test("영상 밖의 유효한 시선은 측정 실패와 구분한다", () => {
  const event = createProductAttentionEvent(validGazeSample, manifest, 3, {
    valid: true,
    outside_video: true,
  });

  assert.equal(event.valid, true);
  assert.equal(event.outside_video, true);
  assert.equal(event.reason, null);
  assert.deepEqual(event.candidates, []);
  assert.equal("video_x_norm" in event, false);
  assert.equal("video_y_norm" in event, false);
});

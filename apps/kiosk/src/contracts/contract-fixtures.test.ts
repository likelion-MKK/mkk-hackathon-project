import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type {
  ExpressionSample,
  GazeSample,
  LookbookManifest,
  ProductAttentionEvent,
  ReactionBatch,
  RecommendationResult,
} from "../app/kiosk-types.ts";

type JsonRecord = Record<string, unknown>;

function loadFixture(name: string): unknown {
  const fixtureUrl = new URL(`../../../../contracts/examples/${name}`, import.meta.url);
  return JSON.parse(readFileSync(fixtureUrl, "utf8")) as unknown;
}

function record(value: unknown, label: string): JsonRecord {
  assert.equal(typeof value, "object", `${label} must be an object`);
  assert.notEqual(value, null, `${label} must not be null`);
  assert.equal(Array.isArray(value), false, `${label} must not be an array`);
  return value as JsonRecord;
}

function nonEmptyString(value: unknown, label: string): string {
  assert.equal(typeof value, "string", `${label} must be a string`);
  assert.ok((value as string).length > 0, `${label} must not be empty`);
  return value as string;
}

function nonNegativeNumber(value: unknown, label: string): number {
  assert.equal(typeof value, "number", `${label} must be a number`);
  assert.ok(Number.isFinite(value), `${label} must be finite`);
  assert.ok((value as number) >= 0, `${label} must be non-negative`);
  return value as number;
}

function nonNegativeInteger(value: unknown, label: string): number {
  const numberValue = nonNegativeNumber(value, label);
  assert.ok(Number.isInteger(numberValue), `${label} must be an integer`);
  return numberValue;
}

function normalized(value: unknown, label: string): number {
  const numberValue = nonNegativeNumber(value, label);
  assert.ok(numberValue <= 1, `${label} must be at most 1`);
  return numberValue;
}

function observationBase(value: JsonRecord): void {
  assert.equal(value.schema_version, "1.0");
  nonEmptyString(value.session_id, "session_id");
  nonEmptyString(value.event_id, "event_id");
  nonNegativeInteger(value.sequence, "sequence");
  nonEmptyString(value.frame_id, "frame_id");
  nonNegativeNumber(value.captured_at_mono_ms, "captured_at_mono_ms");
  nonEmptyString(value.video_id, "video_id");
  nonNegativeInteger(value.video_time_ms, "video_time_ms");
  nonNegativeInteger(value.playback_epoch, "playback_epoch");
  nonEmptyString(value.producer_id, "producer_id");
  nonEmptyString(value.model_revision, "model_revision");
  normalized(value.confidence, "confidence");
}

function gazeSample(value: unknown): GazeSample {
  const sample = record(value, "GazeSample");
  observationBase(sample);
  nonEmptyString(sample.calibration_id, "calibration_id");
  assert.equal(typeof sample.valid, "boolean");

  if (sample.valid) {
    normalized(sample.screen_x_norm, "screen_x_norm");
    normalized(sample.screen_y_norm, "screen_y_norm");
    assert.equal(sample.reason, null);
  } else {
    assert.equal("screen_x_norm" in sample, false);
    assert.equal("screen_y_norm" in sample, false);
    nonEmptyString(sample.reason, "reason");
  }

  return sample as GazeSample;
}

function expressionSample(value: unknown): ExpressionSample {
  const sample = record(value, "ExpressionSample");
  observationBase(sample);
  nonEmptyString(sample.taxonomy_version, "taxonomy_version");
  assert.equal(typeof sample.face_detected, "boolean");
  nonNegativeInteger(sample.face_count, "face_count");
  const scores = record(sample.scores, "scores");
  normalized(sample.quality, "quality");
  assert.equal(typeof sample.valid, "boolean");

  if (sample.valid) {
    assert.equal(sample.face_detected, true);
    assert.equal(sample.face_count, 1);
    assert.ok(Object.keys(scores).length > 0);
    Object.values(scores).forEach((score) => normalized(score, "score"));
    assert.equal(sample.reason, null);
  } else {
    assert.deepEqual(scores, {});
    nonEmptyString(sample.reason, "reason");
  }

  return sample as ExpressionSample;
}

function productAttentionEvent(value: unknown): ProductAttentionEvent {
  const event = record(value, "ProductAttentionEvent");
  observationBase(event);
  nonEmptyString(event.manifest_version, "manifest_version");
  nonEmptyString(event.source_gaze_event_id, "source_gaze_event_id");
  assert.equal(typeof event.outside_video, "boolean");
  assert.equal(typeof event.valid, "boolean");
  assert.ok(Array.isArray(event.candidates));

  if (event.valid && !event.outside_video) {
    normalized(event.video_x_norm, "video_x_norm");
    normalized(event.video_y_norm, "video_y_norm");
    assert.equal(event.reason, null);
  } else {
    assert.equal("video_x_norm" in event, false);
    assert.equal("video_y_norm" in event, false);
    assert.deepEqual(event.candidates, []);
    if (!event.valid) nonEmptyString(event.reason, "reason");
  }

  return event as ProductAttentionEvent;
}

function lookbookManifest(value: unknown): LookbookManifest {
  const manifest = record(value, "LookbookManifest");
  assert.equal(manifest.schema_version, "1.0");
  nonEmptyString(manifest.video_id, "video_id");
  nonEmptyString(manifest.manifest_version, "manifest_version");
  assert.equal(manifest.coordinate_space, "video_normalized");
  const exposures = manifest.exposures;
  assert.ok(Array.isArray(exposures));

  for (const rawExposure of exposures) {
    const exposure = record(rawExposure, "exposure");
    nonEmptyString(exposure.exposure_id, "exposure_id");
    nonEmptyString(exposure.product_id, "product_id");
    nonNegativeInteger(exposure.start_ms, "start_ms");
    nonNegativeInteger(exposure.end_ms, "end_ms");
    const shape = record(exposure.shape, "shape");
    assert.equal(shape.type, "polygon");
    const points = shape.points;
    assert.ok(Array.isArray(points));
    assert.ok(points.length >= 3);
    for (const point of points) {
      assert.ok(Array.isArray(point));
      assert.equal(point.length, 2);
      normalized(point[0], "point x");
      normalized(point[1], "point y");
    }
  }

  return manifest as LookbookManifest;
}

function recommendationResult(value: unknown): RecommendationResult {
  const result = record(value, "RecommendationResult");
  assert.equal(result.schema_version, "1.0");
  nonEmptyString(result.recommendation_id, "recommendation_id");
  nonEmptyString(result.session_id, "session_id");
  nonEmptyString(result.video_id, "video_id");
  nonEmptyString(result.manifest_version, "manifest_version");
  nonEmptyString(result.algorithm_version, "algorithm_version");
  assert.ok(result.engine_mode === "mock" || result.engine_mode === "research_version");
  const items = result.items;
  assert.ok(Array.isArray(items));

  if (result.status === "completed") {
    assert.equal(items.length, 2);
    assert.equal(result.reason, null);
  } else {
    assert.equal(items.length, 0);
  }

  return result as RecommendationResult;
}

function reactionBatch(value: unknown): ReactionBatch {
  const batch = record(value, "ReactionBatch");
  assert.equal(batch.schema_version, "1.0");
  nonEmptyString(batch.batch_id, "batch_id");
  nonNegativeInteger(batch.batch_sequence, "batch_sequence");
  nonEmptyString(batch.session_id, "session_id");
  nonEmptyString(batch.video_id, "video_id");
  const events = batch.events;
  assert.ok(Array.isArray(events));
  assert.ok(events.length > 0);

  for (const event of events) {
    const eventRecord = record(event, "reaction event");
    if ("taxonomy_version" in eventRecord) {
      expressionSample(eventRecord);
    } else {
      productAttentionEvent(eventRecord);
    }
  }

  return batch as ReactionBatch;
}

test("FE가 공통 D1 fixture를 Contract v1 타입으로 소비한다", () => {
  const gaze = gazeSample(loadFixture("gaze-sample.valid.json"));
  const expression = expressionSample(loadFixture("expression-sample.valid.json"));
  const manifest = lookbookManifest(loadFixture("lookbook-manifest.valid.json"));
  const batch = reactionBatch(loadFixture("reaction-batch.valid.json"));
  const recommendation = recommendationResult(
    loadFixture("recommendation-result.valid.json"),
  );

  assert.equal(gaze.session_id, expression.session_id);
  assert.equal(batch.session_id, gaze.session_id);
  assert.equal(manifest.video_id, gaze.video_id);
  assert.equal(recommendation.video_id, manifest.video_id);
});

test("FE가 무효 계약 fixture를 거부한다", () => {
  assert.throws(() => gazeSample(loadFixture("invalid/gaze-sample.invalid.json")));
});

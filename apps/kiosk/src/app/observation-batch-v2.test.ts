import assert from "node:assert/strict";
import test from "node:test";
import type {
  ExpressionSample,
  GazeSample,
  LookbookManifest,
} from "./kiosk-types.ts";
import {
  buildObservationBatchesV2,
  resolveObservationAttentionAuthority,
} from "./observation-batch-v2.ts";
import { calculateContainedVideoLayout } from "./video-context.ts";

const manifest: LookbookManifest = {
  schema_version: "1.0",
  video_id: "video-v2-demo",
  manifest_version: "manifest-v2-demo",
  coordinate_space: "video_normalized",
  exposures: [
    {
      exposure_id: "exposure-a",
      product_id: "MCM-DEMO-BAG-001",
      product_part: "body",
      start_ms: 0,
      end_ms: 10_000,
      priority: 0,
      shape: {
        type: "polygon",
        points: [
          [0, 0],
          [0.5, 0],
          [0.5, 1],
          [0, 1],
        ],
      },
    },
  ],
};

const fullFrameVideoLayout = calculateContainedVideoLayout({
  viewport_width_px: 1_000,
  viewport_height_px: 1_000,
  source_width_px: 1_000,
  source_height_px: 1_000,
  element_rect: { x_px: 0, y_px: 0, width_px: 1_000, height_px: 1_000 },
});

function gaze(
  frame: number,
  overrides: Partial<Extract<GazeSample, { valid: true }>> = {},
): Extract<GazeSample, { valid: true }> {
  return {
    schema_version: "1.0",
    session_id: "session-v2-001",
    event_id: `gaze-${frame}`,
    sequence: frame,
    frame_id: `frame-${frame}`,
    captured_at_mono_ms: frame * 250,
    video_id: manifest.video_id,
    video_time_ms: frame * 250,
    playback_epoch: 0,
    producer_id: "eye-producer",
    model_revision: "eye-revision",
    confidence: 0.9,
    calibration_id: "calibration-001",
    valid: true,
    screen_x_norm: 0.25,
    screen_y_norm: 0.5,
    reason: null,
    ...overrides,
  };
}

function expression(
  frame: number,
  overrides: Partial<Extract<ExpressionSample, { valid: true }>> = {},
): Extract<ExpressionSample, { valid: true }> {
  return {
    schema_version: "1.0",
    session_id: "session-v2-001",
    event_id: `expression-${frame}`,
    sequence: frame,
    frame_id: `frame-${frame}`,
    captured_at_mono_ms: frame * 250,
    video_id: manifest.video_id,
    video_time_ms: frame * 250,
    playback_epoch: 0,
    producer_id: "face-producer",
    model_revision: "face-revision",
    confidence: 0.8,
    taxonomy_version: "observable-actions-v1",
    quality: 0.75,
    face_detected: true,
    face_count: 1,
    scores: { brow_inner_up: 0.6 },
    valid: true,
    reason: null,
    ...overrides,
  };
}

function invalidGaze(frame: number): GazeSample {
  const sample = gaze(frame);
  return {
    schema_version: sample.schema_version,
    session_id: sample.session_id,
    event_id: sample.event_id,
    sequence: sample.sequence,
    frame_id: sample.frame_id,
    captured_at_mono_ms: sample.captured_at_mono_ms,
    video_id: sample.video_id,
    video_time_ms: sample.video_time_ms,
    playback_epoch: sample.playback_epoch,
    producer_id: sample.producer_id,
    model_revision: sample.model_revision,
    calibration_id: sample.calibration_id,
    confidence: 0,
    valid: false,
    reason: "gaze_unavailable",
  };
}

function invalidExpression(frame: number): ExpressionSample {
  const sample = expression(frame);
  return {
    schema_version: sample.schema_version,
    session_id: sample.session_id,
    event_id: sample.event_id,
    sequence: sample.sequence,
    frame_id: sample.frame_id,
    captured_at_mono_ms: sample.captured_at_mono_ms,
    video_id: sample.video_id,
    video_time_ms: sample.video_time_ms,
    playback_epoch: sample.playback_epoch,
    producer_id: sample.producer_id,
    model_revision: sample.model_revision,
    taxonomy_version: sample.taxonomy_version,
    confidence: 0,
    quality: 0,
    face_detected: false,
    face_count: 0,
    scores: {},
    valid: false,
    reason: "face_not_detected",
  };
}

function build(
  gazeSamples: readonly GazeSample[],
  expressionSamples: readonly ExpressionSample[],
  lookbookManifest = manifest,
  videoLayoutsByFrameId = new Map(
    gazeSamples
      .filter((sample) => sample.valid)
      .map((sample) => [sample.frame_id, fullFrameVideoLayout] as const),
  ),
  attentionAuthority: "backend_source_aoi" | "kiosk_manifest" = "backend_source_aoi",
) {
  return buildObservationBatchesV2({
    batchId: "observation-batch-001",
    batchSequence: 0,
    sessionId: "session-v2-001",
    manifest: lookbookManifest,
    attentionAuthority,
    gazeSamples,
    expressionSamples,
    videoLayoutsByFrameId,
  });
}

test("승인된 source manifest pair만 Backend AOI authority를 사용한다", () => {
  assert.equal(
    resolveObservationAttentionAuthority({
      video_id: "lookbook-demo-v1",
      manifest_version: "lookbook-demo-v1-grid-details-v2-2026-08-18",
    }),
    "backend_source_aoi",
  );
  assert.equal(
    resolveObservationAttentionAuthority({
      video_id: "mcm-central-ai-replay-v2",
      manifest_version: "mcm-central-ai-replay-v2-2026-08-18",
    }),
    "kiosk_manifest",
  );
  assert.equal(
    resolveObservationAttentionAuthority({
      video_id: "lookbook-demo-v1",
      manifest_version: "unapproved-revision",
    }),
    "kiosk_manifest",
  );
});

test("동일 frame_id의 시선과 표정을 하나의 v2 observation으로 결합한다", () => {
  const batches = build([gaze(1)], [expression(1)]);
  assert.equal(batches.length, 1);
  assert.equal(batches[0].schema_version, "2.0");
  assert.equal(batches[0].observations.length, 1);

  const observation = batches[0].observations[0];
  assert.equal(observation.frame_id, "frame-1");
  assert.equal(observation.gaze?.producer_id, "eye-producer");
  assert.equal(observation.expression?.producer_id, "face-producer");
  assert.equal(observation.attention?.producer_id, "kiosk-aoi-mapper-v1");
  assert.equal(observation.attention?.model_revision, "aoi-mapper-v2");
  assert.deepEqual(observation.attention?.candidates, []);
  assert.equal(observation.attention?.video_x_norm, 0.25);
  assert.equal(observation.attention?.video_y_norm, 0.5);
  assert.equal(observation.gaze_reason, null);
  assert.equal(observation.expression_reason, null);
  assert.equal(observation.derived_reason, null);
});

test("legacy manifest는 기존 Kiosk candidate mapping을 유지한다", () => {
  const legacyManifest: LookbookManifest = {
    ...manifest,
    exposures: [
      {
        exposure_id: "legacy-exposure-handle",
        product_id: "MCM-DEMO-BAG-001",
        start_ms: 0,
        end_ms: 10_000,
        priority: 0,
        shape: manifest.exposures[0].shape,
      },
    ],
  };
  const attention = build(
    [gaze(1)],
    [],
    legacyManifest,
    new Map([["frame-1", fullFrameVideoLayout]]),
    "kiosk_manifest",
  )[0].observations[0].attention;

  assert.equal(attention?.candidates.length, 1);
  assert.equal(attention?.candidates[0].exposure_id, "legacy-exposure-handle");
  assert.equal(attention?.candidates[0].product_id, "MCM-DEMO-BAG-001");
  assert.equal(attention?.video_x_norm, 0.25);
  assert.equal(attention?.video_y_norm, 0.5);
});

test("유효한 real v2 gaze frame의 layout이 없으면 fail closed한다", () => {
  assert.throws(
    () => build([gaze(1)], [], manifest, new Map()),
    /Missing video layout for valid gaze frame_id "frame-1"/,
  );
});

test("real v2에서 캡처 layout으로 viewport 좌표를 매핑하고 letterbox를 제외한다", () => {
  const letterboxedLayout = calculateContainedVideoLayout({
    viewport_width_px: 1_000,
    viewport_height_px: 1_000,
    source_width_px: 1_920,
    source_height_px: 1_080,
    element_rect: { x_px: 0, y_px: 0, width_px: 1_000, height_px: 1_000 },
  });
  const insideSample = gaze(1);
  const letterboxSample = gaze(2, { screen_y_norm: 0.05 });
  const observations = build(
    [insideSample, letterboxSample],
    [],
    manifest,
    new Map([
      [insideSample.frame_id, letterboxedLayout],
      [letterboxSample.frame_id, letterboxedLayout],
    ]),
  )[0].observations;

  assert.equal(observations[0].attention?.outside_video, false);
  assert.equal(observations[0].attention?.video_x_norm, 0.25);
  assert.equal(observations[0].attention?.video_y_norm, 0.5);
  assert.equal(observations[1].attention?.outside_video, true);
  assert.deepEqual(observations[1].attention?.candidates, []);
});

test("frame_id가 다른 모든 시선·표정 샘플을 보존하고 누락을 null+reason으로 표현한다", () => {
  const observations = build([gaze(1), gaze(3)], [expression(2)])[0].observations;
  assert.deepEqual(
    observations.map((item) => item.frame_id),
    ["frame-1", "frame-2", "frame-3"],
  );
  assert.equal(observations[0].expression, null);
  assert.equal(observations[0].expression_reason, "not_observed");
  assert.equal(observations[1].gaze, null);
  assert.equal(observations[1].gaze_reason, "not_observed");
  assert.equal(observations[1].attention, null);
  assert.equal(observations[1].attention_reason, "source_gaze_unavailable");
  assert.deepEqual(
    observations.map((item) => item.sequence),
    [1, 2, 3],
  );
});

test("frame drop의 source sequence gap을 재번호화하지 않고 보존한다", () => {
  const observations = build([gaze(1), gaze(4)], [expression(1), expression(4)])[0]
    .observations;
  assert.deepEqual(
    observations.map((item) => item.sequence),
    [1, 4],
  );
});

test("return 후보는 Backend source AOI 판정 전까지 미결 상태로 보존한다", () => {
  const observations = build(
    [
      gaze(1),
      gaze(2, { screen_x_norm: 0.75 }),
      gaze(3, { screen_x_norm: 0.25 }),
    ],
    [expression(1), expression(2), expression(3)],
  )[0].observations;

  assert.equal(observations[0].derived?.gaze?.movement, null);
  assert.equal(
    observations[0].derived?.gaze?.movement_reason,
    "no_previous_observation",
  );
  assert.deepEqual(observations[1].attention?.candidates, []);
  assert.equal(observations[2].derived?.gaze?.return_candidate, null);
  assert.equal(
    observations[2].derived?.gaze?.return_candidate_reason,
    "backend_aoi_mapping_required",
  );
  assert.ok((observations[2].derived?.gaze?.movement?.distance_norm ?? 0) > 0);
});

test("표정 결측과 playback epoch 변경 뒤 계산값을 0으로 위장하지 않고 reset한다", () => {
  const observations = build(
    [gaze(1), gaze(2), gaze(3, { playback_epoch: 1 })],
    [
      expression(1),
      expression(3, {
        playback_epoch: 1,
        scores: { brow_inner_up: 0.9 },
      }),
    ],
  )[0].observations;

  assert.equal(observations[1].expression, null);
  assert.equal(observations[2].derived?.expression?.score_changes, null);
  assert.equal(observations[2].derived?.expression?.change_reason, "continuity_reset");
  assert.equal(observations[2].derived?.gaze?.movement, null);
  assert.equal(observations[2].derived?.gaze?.movement_reason, "continuity_reset");
});

test("연속된 두 frame부터 이동·변화·지속 값을 계산한다", () => {
  const observations = build(
    [gaze(1), gaze(2, { screen_x_norm: 0.35 })],
    [expression(1), expression(2, { scores: { brow_inner_up: 0.8 } })],
  )[0].observations;

  assert.equal(observations[0].derived?.gaze?.movement, null);
  assert.ok((observations[1].derived?.gaze?.movement?.distance_norm ?? 0) > 0);
  assert.equal(observations[1].derived?.gaze?.continuous_observation_ms, 250);
  assert.ok(
    (observations[1].derived?.expression?.score_changes?.brow_inner_up ?? 0) > 0,
  );
  assert.equal(
    observations[1].derived?.expression?.sustained_actions[0]?.duration_ms,
    250,
  );
});

test("out-of-order capture는 continuity를 reset하고 session offset은 감소시키지 않는다", () => {
  const observations = build(
    [
      gaze(1, { captured_at_mono_ms: 500 }),
      gaze(2, { captured_at_mono_ms: 250 }),
    ],
    [
      expression(1, { captured_at_mono_ms: 500 }),
      expression(2, { captured_at_mono_ms: 250 }),
    ],
  )[0].observations;

  assert.deepEqual(
    observations.map((item) => item.session_offset_ms),
    [0, 0],
  );
  assert.deepEqual(
    observations.map((item) => item.sequence),
    [1, 2],
  );
  assert.equal(observations[1].derived?.gaze?.movement, null);
  assert.equal(observations[1].derived?.gaze?.movement_reason, "continuity_reset");
  assert.equal(observations[1].derived?.expression?.score_changes, null);
  assert.equal(observations[1].derived?.expression?.change_reason, "continuity_reset");
});

test("표정 taxonomy에서 사라진 label을 0으로 대체하지 않는다", () => {
  const observations = build(
    [gaze(1), gaze(2)],
    [
      expression(1, { scores: { brow_inner_up: 0.6, jaw_open: 0.4 } }),
      expression(2, { scores: { brow_inner_up: 0.7 } }),
    ],
  )[0].observations;

  assert.deepEqual(
    Object.keys(observations[1].derived?.expression?.score_changes ?? {}),
    ["brow_inner_up"],
  );
  assert.equal(
    Object.hasOwn(observations[1].derived?.expression?.score_changes ?? {}, "jaw_open"),
    false,
  );
});

test("invalid gaze와 no-face를 좌표나 중립 score로 바꾸지 않는다", () => {
  const observation = build([invalidGaze(1)], [invalidExpression(1)])[0]
    .observations[0];
  assert.equal(observation.gaze, null);
  assert.equal(observation.gaze_reason, "gaze_unavailable");
  assert.equal(observation.attention, null);
  assert.equal(observation.attention_reason, "source_gaze_unavailable");
  assert.equal(observation.expression, null);
  assert.equal(observation.expression_reason, "face_not_detected");
  assert.equal(observation.derived?.gaze, null);
  assert.equal(observation.derived?.expression, null);
});

test("1초를 넘는 frame gap은 movement와 expression change 연속성을 reset한다", () => {
  const observations = build(
    [gaze(1), gaze(2, { captured_at_mono_ms: 1_501 })],
    [expression(1), expression(2, { captured_at_mono_ms: 1_501 })],
  )[0].observations;
  assert.equal(observations[1].derived?.gaze?.movement, null);
  assert.equal(observations[1].derived?.gaze?.movement_reason, "continuity_reset");
  assert.equal(observations[1].derived?.expression?.score_changes, null);
  assert.equal(observations[1].derived?.expression?.change_reason, "continuity_reset");
});

test("v2 batch 상한을 넘는 모든 frame을 순서대로 분할 보존한다", () => {
  const gazeSamples = Array.from({ length: 257 }, (_, index) => gaze(index + 1));
  const batches = build(gazeSamples, []);
  assert.deepEqual(
    batches.map((item) => item.observations.length),
    [256, 1],
  );
  assert.equal(batches[1].batch_sequence, 1);
  assert.equal(batches[1].observations[0].sequence, 257);
});

test("겹치는 local AOI도 Kiosk가 candidate로 임의 귀속하지 않는다", () => {
  const overlappingManifest: LookbookManifest = {
    ...manifest,
    exposures: [
      ...manifest.exposures,
      {
        ...manifest.exposures[0],
        exposure_id: "exposure-b",
        product_id: "MCM-DEMO-BAG-002",
      },
    ],
  };
  const observation = build([gaze(1)], [expression(1)], overlappingManifest)[0]
    .observations[0];
  assert.deepEqual(observation.attention?.candidates, []);
  assert.equal(observation.derived?.gaze?.return_candidate, null);
  assert.equal(
    observation.derived?.gaze?.return_candidate_reason,
    "backend_aoi_mapping_required",
  );
});

test("한 frame에 서로 다른 동일 modality 샘플이 오면 조용히 버리지 않는다", () => {
  assert.throws(
    () =>
      build(
        [
          gaze(1),
          gaze(1, { event_id: "gaze-conflict", screen_x_norm: 0.4 }),
        ],
        [],
      ),
    /cannot be represented without loss/,
  );
});

test("같은 frame의 modality sequence 불일치나 서로 다른 frame의 중복 sequence를 거부한다", () => {
  assert.throws(
    () => build([gaze(1)], [expression(1, { sequence: 2 })]),
    /same frame_id must preserve one frame sequence/,
  );
  assert.throws(
    () => build([gaze(1), gaze(2, { sequence: 1 })], []),
    /Different frames cannot share one source sequence/,
  );
});

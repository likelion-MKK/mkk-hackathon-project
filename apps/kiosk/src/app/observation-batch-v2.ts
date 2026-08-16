import type {
  ExpressionDerivedV2,
  ExpressionSample,
  FrameObservationV2,
  GazeDerivedV2,
  GazeSample,
  LookbookManifest,
  ObservationBatchV2,
  ProductAttentionEvent,
} from "./kiosk-types.ts";
import {
  createProductAttentionEvent,
  mapD1MockGazeToVideoPoint,
  mapGazeToVideoPoint,
} from "./reaction-batch.ts";
import type { VideoLayout } from "./video-context.ts";

const MAX_OBSERVATIONS_PER_BATCH = 256;
const CONTINUITY_GAP_MS = 1_000;
const SUSTAINED_ACTION_THRESHOLD = 0.5;

type BuildObservationBatchesV2Options = {
  batchId: string;
  batchSequence: number;
  sessionId: string;
  manifest: LookbookManifest;
  gazeSamples: readonly GazeSample[];
  expressionSamples: readonly ExpressionSample[];
  videoLayoutsByFrameId?: ReadonlyMap<string, VideoLayout>;
};

type FusedFrame = {
  key: string;
  frame_id: string;
  captured_at_mono_ms: number;
  video_time_ms: number;
  playback_epoch: number;
  source_sequence: number;
  gaze?: GazeSample;
  expression?: ExpressionSample;
};

type GazeContinuity = {
  sample: Extract<GazeSample, { valid: true }>;
  run_started_at_mono_ms: number;
  last_unambiguous_product_id: string | null;
  seen_product_ids: Set<string>;
};

type ExpressionContinuity = {
  sample: Extract<ExpressionSample, { valid: true }>;
  sustained_started_at_mono_ms: Map<string, number>;
};

function requireMatchingContext(
  sample: GazeSample | ExpressionSample,
  options: BuildObservationBatchesV2Options,
): void {
  if (sample.session_id !== options.sessionId) {
    throw new Error("Observation sample must match the batch session_id.");
  }
  if (sample.video_id !== options.manifest.video_id) {
    throw new Error("Observation sample must match the manifest video_id.");
  }
}

function requireSameFrameContext(frame: FusedFrame, sample: GazeSample | ExpressionSample): void {
  if (
    frame.captured_at_mono_ms !== sample.captured_at_mono_ms ||
    frame.video_time_ms !== sample.video_time_ms ||
    frame.playback_epoch !== sample.playback_epoch
  ) {
    throw new Error("Signals with the same frame_id must preserve one capture context.");
  }
}

function addSampleToFrames(
  frames: Map<string, FusedFrame>,
  sample: GazeSample | ExpressionSample,
  modality: "gaze" | "expression",
  options: BuildObservationBatchesV2Options,
): void {
  requireMatchingContext(sample, options);
  const key = `${sample.playback_epoch}:${sample.frame_id}`;
  let frame = frames.get(key);
  if (!frame) {
    frame = {
      key,
      frame_id: sample.frame_id,
      captured_at_mono_ms: sample.captured_at_mono_ms,
      video_time_ms: sample.video_time_ms,
      playback_epoch: sample.playback_epoch,
      source_sequence: sample.sequence,
    };
    frames.set(key, frame);
  } else {
    requireSameFrameContext(frame, sample);
    if (frame.source_sequence !== sample.sequence) {
      throw new Error("Signals with the same frame_id must preserve one frame sequence.");
    }
  }

  if (modality === "gaze") {
    const gazeSample = sample as GazeSample;
    if (frame.gaze) {
      if (
        frame.gaze.event_id !== gazeSample.event_id ||
        JSON.stringify(frame.gaze) !== JSON.stringify(gazeSample)
      ) {
        throw new Error("Multiple gaze samples for one frame cannot be represented without loss.");
      }
      return;
    }
    frame.gaze = gazeSample;
    return;
  }

  const expressionSample = sample as ExpressionSample;
  if (frame.expression) {
    if (
      frame.expression.event_id !== expressionSample.event_id ||
      JSON.stringify(frame.expression) !== JSON.stringify(expressionSample)
    ) {
      throw new Error("Multiple expression samples for one frame cannot be represented without loss.");
    }
    return;
  }
  frame.expression = expressionSample;
}

function fuseByFrameId(options: BuildObservationBatchesV2Options): FusedFrame[] {
  const frames = new Map<string, FusedFrame>();
  for (const sample of options.gazeSamples) {
    addSampleToFrames(frames, sample, "gaze", options);
  }
  for (const sample of options.expressionSamples) {
    addSampleToFrames(frames, sample, "expression", options);
  }

  const fusedFrames = [...frames.values()].sort(
    (left, right) =>
      left.source_sequence - right.source_sequence ||
      left.captured_at_mono_ms - right.captured_at_mono_ms ||
      left.key.localeCompare(right.key),
  );
  const sequenceOwners = new Map<number, string>();
  for (const frame of fusedFrames) {
    const owner = sequenceOwners.get(frame.source_sequence);
    if (owner && owner !== frame.key) {
      throw new Error("Different frames cannot share one source sequence.");
    }
    sequenceOwners.set(frame.source_sequence, frame.key);
  }
  return fusedFrames;
}

function mapAttention(
  sample: GazeSample,
  manifest: LookbookManifest,
  videoLayoutsByFrameId: ReadonlyMap<string, VideoLayout> | undefined,
): ProductAttentionEvent {
  const layout = videoLayoutsByFrameId?.get(sample.frame_id);
  const videoPoint = layout
    ? mapGazeToVideoPoint(sample, layout)
    : mapD1MockGazeToVideoPoint(sample);
  return createProductAttentionEvent(sample, manifest, sample.sequence, videoPoint);
}

function isContinuityReset(
  previous: GazeSample | ExpressionSample,
  frame: FusedFrame,
): boolean {
  const elapsedMs = frame.captured_at_mono_ms - previous.captured_at_mono_ms;
  return (
    frame.playback_epoch !== previous.playback_epoch ||
    elapsedMs <= 0 ||
    elapsedMs > CONTINUITY_GAP_MS ||
    frame.video_time_ms < previous.video_time_ms
  );
}

function unambiguousProductId(attention: ProductAttentionEvent | null): string | null {
  if (!attention?.valid || attention.outside_video || attention.candidates.length !== 1) {
    return null;
  }
  return attention.candidates[0].product_id;
}

function buildGazeDerived(
  sample: Extract<GazeSample, { valid: true }>,
  frame: FusedFrame,
  attention: ProductAttentionEvent,
  previous: GazeContinuity | null,
  forcedReset: boolean,
): { value: GazeDerivedV2; next: GazeContinuity } {
  const reset = forcedReset || !previous || isContinuityReset(previous.sample, frame);
  const resetReason = forcedReset || previous ? "continuity_reset" : "no_previous_observation";
  const elapsedMs = reset ? 0 : frame.captured_at_mono_ms - previous.sample.captured_at_mono_ms;
  const movementDistance = reset
    ? 0
    : Math.hypot(
        sample.screen_x_norm - previous.sample.screen_x_norm,
        sample.screen_y_norm - previous.sample.screen_y_norm,
      );
  const currentProductId = unambiguousProductId(attention);
  const seenProductIds = reset ? new Set<string>() : new Set(previous.seen_product_ids);
  const lastProductId = reset ? null : previous.last_unambiguous_product_id;
  const returnCandidate =
    currentProductId !== null &&
    lastProductId !== currentProductId &&
    seenProductIds.has(currentProductId);

  if (currentProductId) seenProductIds.add(currentProductId);
  const productIsAmbiguous =
    attention.valid && !attention.outside_video && attention.candidates.length > 1;

  return {
    value: {
      movement: reset
        ? null
        : {
            distance_norm: movementDistance,
            speed_norm_per_s: movementDistance / (elapsedMs / 1_000),
          },
      movement_reason: reset ? resetReason : null,
      continuous_observation_ms: reset
        ? 0
        : frame.captured_at_mono_ms - previous.run_started_at_mono_ms,
      return_candidate: reset || productIsAmbiguous ? null : returnCandidate,
      return_candidate_reason: reset
        ? resetReason
        : productIsAmbiguous
          ? "ambiguous_product"
          : null,
    },
    next: {
      sample,
      run_started_at_mono_ms: reset
        ? frame.captured_at_mono_ms
        : previous.run_started_at_mono_ms,
      last_unambiguous_product_id: currentProductId,
      seen_product_ids: seenProductIds,
    },
  };
}

function buildExpressionDerived(
  sample: Extract<ExpressionSample, { valid: true }>,
  frame: FusedFrame,
  previous: ExpressionContinuity | null,
  forcedReset: boolean,
): { value: ExpressionDerivedV2; next: ExpressionContinuity } {
  const reset = forcedReset || !previous || isContinuityReset(previous.sample, frame);
  const resetReason = forcedReset || previous ? "continuity_reset" : "no_previous_observation";
  const elapsedMs = reset ? 0 : frame.captured_at_mono_ms - previous.sample.captured_at_mono_ms;
  const previousScores = reset ? sample.scores : previous.sample.scores;
  const labels = Object.keys(sample.scores).filter((label) => label in previousScores);
  const scoreChanges: Record<string, number> = {};
  const scoreChangeRates: Record<string, number> = {};

  for (const label of labels) {
    const change = sample.scores[label] - previousScores[label];
    scoreChanges[label] = change;
    scoreChangeRates[label] = elapsedMs > 0 ? change / (elapsedMs / 1_000) : 0;
  }

  const sustainedStartedAt = reset
    ? new Map<string, number>()
    : new Map(previous.sustained_started_at_mono_ms);
  for (const [label, score] of Object.entries(sample.scores)) {
    if (score >= SUSTAINED_ACTION_THRESHOLD && !sustainedStartedAt.has(label)) {
      sustainedStartedAt.set(label, frame.captured_at_mono_ms);
    }
    if (score < SUSTAINED_ACTION_THRESHOLD) sustainedStartedAt.delete(label);
  }
  for (const label of [...sustainedStartedAt.keys()]) {
    if (!(label in sample.scores)) sustainedStartedAt.delete(label);
  }

  const hasSharedLabels = labels.length > 0;
  const ratesAreInContractRange = Object.values(scoreChangeRates).every(
    (rate) => Math.abs(rate) <= 1_000,
  );
  const changesAreCalculable = !reset && hasSharedLabels && ratesAreInContractRange;
  return {
    value: {
      score_changes: changesAreCalculable ? scoreChanges : null,
      score_change_rates_per_s: changesAreCalculable ? scoreChangeRates : null,
      change_reason: reset
        ? resetReason
        : !hasSharedLabels
          ? "no_shared_taxonomy_signal"
          : ratesAreInContractRange
            ? null
            : "rate_out_of_range",
      sustained_actions: reset
        ? []
        : [...sustainedStartedAt.entries()]
            .sort(([left], [right]) => left.localeCompare(right))
            .map(([signal, startedAt]) => ({
              signal,
              duration_ms: frame.captured_at_mono_ms - startedAt,
            })),
    },
    next: {
      sample,
      sustained_started_at_mono_ms: sustainedStartedAt,
    },
  };
}

function buildObservations(options: BuildObservationBatchesV2Options): FrameObservationV2[] {
  const frames = fuseByFrameId(options);
  let gazeContinuity: GazeContinuity | null = null;
  let expressionContinuity: ExpressionContinuity | null = null;
  let gazeWasReset = false;
  let expressionWasReset = false;
  const firstCapturedAt = frames[0]?.captured_at_mono_ms ?? 0;
  let lastSessionOffsetMs = 0;

  return frames.map((frame) => {
    const gazeSample = frame.gaze;
    const expressionSample = frame.expression;
    const validGaze = gazeSample?.valid ? gazeSample : null;
    const validExpression = expressionSample?.valid ? expressionSample : null;
    const attentionEvent = validGaze
      ? mapAttention(validGaze, options.manifest, options.videoLayoutsByFrameId)
      : null;

    let gazeDerived: GazeDerivedV2 | null = null;
    if (validGaze && attentionEvent?.valid) {
      const result = buildGazeDerived(
        validGaze,
        frame,
        attentionEvent,
        gazeContinuity,
        gazeWasReset,
      );
      gazeDerived = result.value;
      gazeContinuity = result.next;
      gazeWasReset = false;
    } else {
      gazeContinuity = null;
      gazeWasReset = true;
    }

    let expressionDerived: ExpressionDerivedV2 | null = null;
    if (validExpression) {
      const result = buildExpressionDerived(
        validExpression,
        frame,
        expressionContinuity,
        expressionWasReset,
      );
      expressionDerived = result.value;
      expressionContinuity = result.next;
      expressionWasReset = false;
    } else {
      expressionContinuity = null;
      expressionWasReset = true;
    }

    const capturedOffset = Math.max(0, frame.captured_at_mono_ms - firstCapturedAt);
    lastSessionOffsetMs = Math.max(lastSessionOffsetMs, capturedOffset);

    return {
      schema_version: "2.0",
      frame_id: frame.frame_id,
      sequence: frame.source_sequence,
      captured_at_mono_ms: frame.captured_at_mono_ms,
      session_offset_ms: lastSessionOffsetMs,
      video_time_ms: frame.video_time_ms,
      playback_epoch: frame.playback_epoch,
      gaze: validGaze
        ? {
            screen_x_norm: validGaze.screen_x_norm,
            screen_y_norm: validGaze.screen_y_norm,
            confidence: validGaze.confidence,
            producer_id: validGaze.producer_id,
            model_revision: validGaze.model_revision,
            calibration_id: validGaze.calibration_id,
          }
        : null,
      gaze_reason: validGaze ? null : (gazeSample?.reason ?? "not_observed"),
      attention:
        attentionEvent?.valid
          ? {
              outside_video: attentionEvent.outside_video,
              ...(attentionEvent.outside_video
                ? {}
                : {
                    video_x_norm: attentionEvent.video_x_norm,
                    video_y_norm: attentionEvent.video_y_norm,
                  }),
              confidence: attentionEvent.confidence,
              producer_id: attentionEvent.producer_id,
              model_revision: attentionEvent.model_revision,
              manifest_version: attentionEvent.manifest_version,
              candidates: attentionEvent.candidates,
            }
          : null,
      attention_reason: attentionEvent?.valid
        ? null
        : validGaze
          ? (attentionEvent?.reason ?? "aoi_mapping_failed")
          : "source_gaze_unavailable",
      expression: validExpression
        ? {
            scores: validExpression.scores,
            quality: validExpression.quality,
            confidence: validExpression.confidence,
            producer_id: validExpression.producer_id,
            model_revision: validExpression.model_revision,
            taxonomy_version: validExpression.taxonomy_version,
          }
        : null,
      expression_reason: validExpression
        ? null
        : (expressionSample?.reason ?? "not_observed"),
      derived: {
        gaze: gazeDerived,
        gaze_reason: gazeDerived ? null : "source_gaze_unavailable",
        expression: expressionDerived,
        expression_reason: expressionDerived ? null : "source_expression_unavailable",
      },
      derived_reason: null,
    };
  });
}

export function buildObservationBatchesV2(
  options: BuildObservationBatchesV2Options,
): ObservationBatchV2[] {
  const observations = buildObservations(options);
  const batches: ObservationBatchV2[] = [];

  for (let offset = 0; offset < observations.length; offset += MAX_OBSERVATIONS_PER_BATCH) {
    const chunk = observations.slice(offset, offset + MAX_OBSERVATIONS_PER_BATCH);
    if (chunk.length === 0) continue;
    const chunkIndex = batches.length;
    batches.push({
      schema_version: "2.0",
      batch_id:
        chunkIndex === 0 ? options.batchId : `${options.batchId}-${chunkIndex + 1}`,
      batch_sequence: options.batchSequence + chunkIndex,
      session_id: options.sessionId,
      video_id: options.manifest.video_id,
      observations: [chunk[0], ...chunk.slice(1)],
    });
  }

  return batches;
}

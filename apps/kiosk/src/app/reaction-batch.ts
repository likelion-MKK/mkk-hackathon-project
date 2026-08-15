import type {
  ExpressionSample,
  GazeSample,
  LookbookManifest,
  ProductAttentionEvent,
  ReactionBatch,
} from "./kiosk-types.ts";
import type { VideoLayout } from "./video-context.ts";

export type VideoPointMapping =
  | {
      valid: false;
      outside_video: boolean;
      reason: string;
    }
  | {
      valid: true;
      outside_video: true;
    }
  | {
      valid: true;
      outside_video: false;
      video_x_norm: number;
      video_y_norm: number;
    };

type BuildD1ReactionBatchOptions = {
  batchId: string;
  batchSequence: number;
  sessionId: string;
  manifest: LookbookManifest;
  gazeSample?: GazeSample | null;
  gazeSamples?: readonly GazeSample[];
  expressionSample: ExpressionSample | null;
  videoLayout?: VideoLayout;
  videoLayoutsByFrameId?: ReadonlyMap<string, VideoLayout>;
};

const AOI_PRODUCER_ID = "kiosk-aoi-mapper-v1";
const AOI_MAPPER_REVISION = "aoi-mapper-v1";
const MAX_ATTENTION_CANDIDATES = 32;
const MAX_EVENTS_PER_BATCH = 256;
const POINT_EPSILON = 1e-9;

function pointIsOnSegment(
  pointX: number,
  pointY: number,
  startX: number,
  startY: number,
  endX: number,
  endY: number,
): boolean {
  const crossProduct =
    (pointY - startY) * (endX - startX) -
    (pointX - startX) * (endY - startY);

  if (Math.abs(crossProduct) > POINT_EPSILON) return false;

  return (
    pointX >= Math.min(startX, endX) - POINT_EPSILON &&
    pointX <= Math.max(startX, endX) + POINT_EPSILON &&
    pointY >= Math.min(startY, endY) - POINT_EPSILON &&
    pointY <= Math.max(startY, endY) + POINT_EPSILON
  );
}

function pointIsInsidePolygon(
  pointX: number,
  pointY: number,
  polygon: [number, number][],
): boolean {
  let inside = false;

  for (let current = 0, previous = polygon.length - 1; current < polygon.length; previous = current++) {
    const [currentX, currentY] = polygon[current];
    const [previousX, previousY] = polygon[previous];

    if (
      pointIsOnSegment(
        pointX,
        pointY,
        previousX,
        previousY,
        currentX,
        currentY,
      )
    ) {
      return true;
    }

    const crossesHorizontalRay =
      currentY > pointY !== previousY > pointY &&
      pointX <
        ((previousX - currentX) * (pointY - currentY)) /
          (previousY - currentY) +
          currentX;

    if (crossesHorizontalRay) inside = !inside;
  }

  return inside;
}

function requireNormalizedCoordinate(value: number, fieldName: string): void {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new RangeError(`${fieldName} must be a finite number between 0 and 1.`);
  }
}

export function mapD1MockGazeToVideoPoint(gazeSample: GazeSample): VideoPointMapping {
  if (!gazeSample.valid) {
    return {
      valid: false,
      outside_video: false,
      reason: gazeSample.reason,
    };
  }

  // D1의 임시 룩북은 별도의 video layout이 없으므로 두 정규화 좌표계를 같게 둔다.
  // 실제 영상 연결 시에는 캡처 시점의 layout으로 screen 좌표를 video 좌표로 변환해야 한다.
  return {
    valid: true,
    outside_video: false,
    video_x_norm: gazeSample.screen_x_norm,
    video_y_norm: gazeSample.screen_y_norm,
  };
}

function pointIsInsideRect(
  pointX: number,
  pointY: number,
  rect: VideoLayout["content_rect"],
): boolean {
  return (
    pointX >= rect.x_px - POINT_EPSILON &&
    pointX <= rect.x_px + rect.width_px + POINT_EPSILON &&
    pointY >= rect.y_px - POINT_EPSILON &&
    pointY <= rect.y_px + rect.height_px + POINT_EPSILON
  );
}

/**
 * Convert viewport-normalized gaze to video-content-normalized gaze.
 *
 * The layout is captured with the same frame as the gaze sample. A point in
 * letterbox padding is valid gaze data but is not a product observation.
 */
export function mapGazeToVideoPoint(
  gazeSample: GazeSample,
  layout: VideoLayout,
): VideoPointMapping {
  if (!gazeSample.valid) {
    return {
      valid: false,
      outside_video: false,
      reason: gazeSample.reason,
    };
  }

  requireNormalizedCoordinate(gazeSample.screen_x_norm, "screen_x_norm");
  requireNormalizedCoordinate(gazeSample.screen_y_norm, "screen_y_norm");

  const screenX = gazeSample.screen_x_norm * layout.viewport_width_px;
  const screenY = gazeSample.screen_y_norm * layout.viewport_height_px;
  const contentRect = layout.content_rect;

  if (!pointIsInsideRect(screenX, screenY, contentRect)) {
    return {
      valid: true,
      outside_video: true,
    };
  }

  const videoX = (screenX - contentRect.x_px) / contentRect.width_px;
  const videoY = (screenY - contentRect.y_px) / contentRect.height_px;

  if (
    videoX < -POINT_EPSILON ||
    videoX > 1 + POINT_EPSILON ||
    videoY < -POINT_EPSILON ||
    videoY > 1 + POINT_EPSILON
  ) {
    return {
      valid: true,
      outside_video: true,
    };
  }

  return {
    valid: true,
    outside_video: false,
    video_x_norm: Math.min(1, Math.max(0, videoX)),
    video_y_norm: Math.min(1, Math.max(0, videoY)),
  };
}

export function createProductAttentionEvent(
  gazeSample: GazeSample,
  manifest: LookbookManifest,
  sequence: number,
  videoPoint: VideoPointMapping,
): ProductAttentionEvent {
  if (gazeSample.video_id !== manifest.video_id) {
    throw new Error("Gaze sample and lookbook manifest must use the same video_id.");
  }

  const base = {
    schema_version: gazeSample.schema_version,
    session_id: gazeSample.session_id,
    event_id: `attention-${String(sequence).padStart(4, "0")}`,
    sequence,
    frame_id: gazeSample.frame_id,
    captured_at_mono_ms: gazeSample.captured_at_mono_ms,
    video_id: gazeSample.video_id,
    video_time_ms: gazeSample.video_time_ms,
    playback_epoch: gazeSample.playback_epoch,
    producer_id: AOI_PRODUCER_ID,
    model_revision: AOI_MAPPER_REVISION,
    manifest_version: manifest.manifest_version,
    source_gaze_event_id: gazeSample.event_id,
    confidence: gazeSample.confidence,
  };

  if (!videoPoint.valid) {
    return {
      ...base,
      outside_video: videoPoint.outside_video,
      candidates: [],
      valid: false,
      reason: videoPoint.reason,
    };
  }

  if (videoPoint.outside_video) {
    return {
      ...base,
      outside_video: true,
      candidates: [],
      valid: true,
      reason: null,
    };
  }

  requireNormalizedCoordinate(videoPoint.video_x_norm, "video_x_norm");
  requireNormalizedCoordinate(videoPoint.video_y_norm, "video_y_norm");

  const candidates = manifest.exposures
    .filter(
      (exposure) =>
        exposure.start_ms <= gazeSample.video_time_ms &&
        gazeSample.video_time_ms < exposure.end_ms &&
        pointIsInsidePolygon(
          videoPoint.video_x_norm,
          videoPoint.video_y_norm,
          exposure.shape.points,
        ),
    )
    .map(({ exposure_id, product_id, priority }) => ({
      exposure_id,
      product_id,
      priority,
    }));

  if (candidates.length > MAX_ATTENTION_CANDIDATES) {
    throw new Error("ProductAttentionEvent cannot contain more than 32 candidates.");
  }

  return {
    ...base,
    outside_video: false,
    video_x_norm: videoPoint.video_x_norm,
    video_y_norm: videoPoint.video_y_norm,
    candidates,
    valid: true,
    reason: null,
  };
}

function resolveGazeSamples({
  gazeSample,
  gazeSamples,
}: Pick<BuildD1ReactionBatchOptions, "gazeSample" | "gazeSamples">): readonly GazeSample[] {
  if (gazeSamples) {
    if (gazeSample) {
      throw new Error("Provide gazeSample or gazeSamples, not both.");
    }
    return gazeSamples;
  }

  return gazeSample ? [gazeSample] : [];
}

function mapSampleToVideoPoint(
  gazeSample: GazeSample,
  options: Pick<BuildD1ReactionBatchOptions, "videoLayout" | "videoLayoutsByFrameId">,
): VideoPointMapping {
  const layout = options.videoLayoutsByFrameId?.get(gazeSample.frame_id) ?? options.videoLayout;
  return layout ? mapGazeToVideoPoint(gazeSample, layout) : mapD1MockGazeToVideoPoint(gazeSample);
}

function buildReactionEvents(options: BuildD1ReactionBatchOptions): Array<
  ExpressionSample | ProductAttentionEvent
> {
  const { manifest, expressionSample } = options;
  const samples = resolveGazeSamples(options);
  const events: Array<ExpressionSample | ProductAttentionEvent> = [];

  if (expressionSample) {
    events.push(expressionSample);
  }

  const firstAttentionSequence = Math.max(
    expressionSample?.sequence ?? -1,
    ...samples.map((sample) => sample.sequence),
  ) + 1;

  samples.forEach((sample, index) => {
    events.push(
      createProductAttentionEvent(
        sample,
        manifest,
        firstAttentionSequence + index,
        mapSampleToVideoPoint(sample, options),
      ),
    );
  });

  for (const event of events) {
    if (event.session_id !== options.sessionId || event.video_id !== manifest.video_id) {
      throw new Error("Reaction event must match the batch session_id and video_id.");
    }
  }

  return events;
}

export function buildD1ReactionBatches(options: BuildD1ReactionBatchOptions): ReactionBatch[] {
  const events = buildReactionEvents(options);
  if (events.length === 0) return [];

  const batches: ReactionBatch[] = [];
  for (let offset = 0; offset < events.length; offset += MAX_EVENTS_PER_BATCH) {
    const chunk = events.slice(offset, offset + MAX_EVENTS_PER_BATCH);
    const chunkIndex = batches.length;
    const batchId =
      chunkIndex === 0 ? options.batchId : `${options.batchId}-${chunkIndex + 1}`;

    batches.push({
      schema_version: "1.0",
      batch_id: batchId,
      batch_sequence: options.batchSequence + chunkIndex,
      session_id: options.sessionId,
      video_id: options.manifest.video_id,
      events: [chunk[0], ...chunk.slice(1)],
    });
  }

  return batches;
}

export function buildD1ReactionBatch({
  batchId,
  batchSequence,
  sessionId,
  manifest,
  gazeSample,
  gazeSamples,
  expressionSample,
  videoLayout,
  videoLayoutsByFrameId,
}: BuildD1ReactionBatchOptions): ReactionBatch | null {
  const batches = buildD1ReactionBatches({
    batchId,
    batchSequence,
    sessionId,
    manifest,
    gazeSample,
    gazeSamples,
    expressionSample,
    videoLayout,
    videoLayoutsByFrameId,
  });

  if (batches.length > 1) {
    throw new RangeError(
      "More than 256 reaction events require buildD1ReactionBatches to preserve all samples.",
    );
  }

  return batches[0] ?? null;
}

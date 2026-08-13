import type {
  ExpressionSample,
  GazeSample,
  LookbookManifest,
  ProductAttentionEvent,
  ReactionBatch,
} from "./kiosk-types.ts";

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
  gazeSample: GazeSample | null;
  expressionSample: ExpressionSample | null;
};

const AOI_PRODUCER_ID = "kiosk-aoi-mapper-v1";
const AOI_MAPPER_REVISION = "d1-mock-aoi-v1";
const MAX_ATTENTION_CANDIDATES = 32;
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

export function buildD1ReactionBatch({
  batchId,
  batchSequence,
  sessionId,
  manifest,
  gazeSample,
  expressionSample,
}: BuildD1ReactionBatchOptions): ReactionBatch | null {
  const events: Array<ExpressionSample | ProductAttentionEvent> = [];

  if (expressionSample) {
    events.push(expressionSample);
  }

  if (gazeSample) {
    const nextSequence =
      Math.max(gazeSample.sequence, expressionSample?.sequence ?? -1) + 1;
    events.push(
      createProductAttentionEvent(
        gazeSample,
        manifest,
        nextSequence,
        mapD1MockGazeToVideoPoint(gazeSample),
      ),
    );
  }

  if (events.length === 0) return null;

  for (const event of events) {
    if (event.session_id !== sessionId || event.video_id !== manifest.video_id) {
      throw new Error("Reaction event must match the batch session_id and video_id.");
    }
  }

  const [firstEvent, ...remainingEvents] = events;

  return {
    schema_version: "1.0",
    batch_id: batchId,
    batch_sequence: batchSequence,
    session_id: sessionId,
    video_id: manifest.video_id,
    events: [firstEvent, ...remainingEvents],
  };
}

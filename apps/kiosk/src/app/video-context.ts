export type PixelRect = Readonly<{
  x_px: number;
  y_px: number;
  width_px: number;
  height_px: number;
}>;

export type VideoLayout = Readonly<{
  viewport_width_px: number;
  viewport_height_px: number;
  source_width_px: number;
  source_height_px: number;
  object_fit: "contain";
  element_rect: PixelRect;
  content_rect: PixelRect;
}>;

export type FrameContext = Readonly<{
  session_id: string;
  sequence: number;
  frame_id: string;
  captured_at_mono_ms: number;
  video_id: string;
  video_time_ms: number;
  playback_epoch: number;
  layout: VideoLayout;
}>;

export type VideoLayoutInput = {
  viewport_width_px: number;
  viewport_height_px: number;
  source_width_px: number;
  source_height_px: number;
  element_rect: PixelRect;
};

export type FrameContextInput = {
  session_id: string;
  sequence: number;
  frame_id: string;
  captured_at_mono_ms: number;
  video_id: string;
  video_time_seconds: number;
  playback_epoch: number;
  layout: VideoLayout;
};

/**
 * Allocates frame sequences for one Vision Stream session.
 * Calibration and lookbook captures must share the same instance because the
 * gateway validates sequence ordering across the whole session.
 */
export class SessionFrameSequence {
  private nextValue = 0;

  next(): number {
    const value = this.nextValue;
    this.nextValue += 1;
    return value;
  }

  reset(): void {
    this.nextValue = 0;
  }
}

function requirePositiveFinite(value: number, name: string): void {
  if (!Number.isFinite(value) || value <= 0) {
    throw new RangeError(`${name} must be a positive finite number.`);
  }
}

function requireNonNegativeFinite(value: number, name: string): void {
  if (!Number.isFinite(value) || value < 0) {
    throw new RangeError(`${name} must be a non-negative finite number.`);
  }
}

function requireFinite(value: number, name: string): void {
  if (!Number.isFinite(value)) {
    throw new RangeError(`${name} must be a finite number.`);
  }
}

function requireNonNegativeInteger(value: number, name: string): void {
  if (!Number.isInteger(value) || value < 0) {
    throw new RangeError(`${name} must be a non-negative integer.`);
  }
}

/** Advance before seek, replay, or source replacement captures any new frame. */
export function advancePlaybackEpoch(playbackEpoch: number): number {
  requireNonNegativeInteger(playbackEpoch, "playbackEpoch");
  return playbackEpoch + 1;
}

function requireIdentifier(value: string, name: string): void {
  if (value.trim().length === 0) {
    throw new TypeError(`${name} must not be empty.`);
  }
}

function cloneRect(rect: PixelRect): PixelRect {
  return { ...rect };
}

function normalizePixel(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

export function calculateContainedVideoLayout({
  viewport_width_px,
  viewport_height_px,
  source_width_px,
  source_height_px,
  element_rect,
}: VideoLayoutInput): VideoLayout {
  requirePositiveFinite(viewport_width_px, "viewport_width_px");
  requirePositiveFinite(viewport_height_px, "viewport_height_px");
  requirePositiveFinite(source_width_px, "source_width_px");
  requirePositiveFinite(source_height_px, "source_height_px");
  requirePositiveFinite(element_rect.width_px, "element_rect.width_px");
  requirePositiveFinite(element_rect.height_px, "element_rect.height_px");
  requireFinite(element_rect.x_px, "element_rect.x_px");
  requireFinite(element_rect.y_px, "element_rect.y_px");

  const scale = Math.min(
    element_rect.width_px / source_width_px,
    element_rect.height_px / source_height_px,
  );
  const contentWidth = source_width_px * scale;
  const contentHeight = source_height_px * scale;

  return {
    viewport_width_px,
    viewport_height_px,
    source_width_px,
    source_height_px,
    object_fit: "contain",
    element_rect: cloneRect(element_rect),
    content_rect: {
      x_px: normalizePixel(element_rect.x_px + (element_rect.width_px - contentWidth) / 2),
      y_px: normalizePixel(element_rect.y_px + (element_rect.height_px - contentHeight) / 2),
      width_px: normalizePixel(contentWidth),
      height_px: normalizePixel(contentHeight),
    },
  };
}

export function createFrameContext({
  session_id,
  sequence,
  frame_id,
  captured_at_mono_ms,
  video_id,
  video_time_seconds,
  playback_epoch,
  layout,
}: FrameContextInput): FrameContext {
  requireIdentifier(session_id, "session_id");
  requireIdentifier(frame_id, "frame_id");
  requireIdentifier(video_id, "video_id");
  requireNonNegativeInteger(sequence, "sequence");
  requireNonNegativeFinite(captured_at_mono_ms, "captured_at_mono_ms");
  requireNonNegativeFinite(video_time_seconds, "video_time_seconds");
  requireNonNegativeInteger(playback_epoch, "playback_epoch");

  return {
    session_id,
    sequence,
    frame_id,
    captured_at_mono_ms,
    video_id,
    video_time_ms: Math.floor(video_time_seconds * 1_000),
    playback_epoch,
    layout: {
      ...layout,
      element_rect: cloneRect(layout.element_rect),
      content_rect: cloneRect(layout.content_rect),
    },
  };
}

import type { FrameContext } from "../../app/video-context.ts";
import type { VisionClient } from "./VisionClient.ts";

export type VisionFrameEncoding = "image/jpeg" | "image/webp";

export type EphemeralVideoFrame = {
  readonly width: number;
  readonly height: number;
  /** The in-memory image source is never serialized or retained after close(). */
  readonly source?: CanvasImageSource;
  close(): void;
};

export type VisionDropReason =
  | "in_flight"
  | "duplicate_frame"
  | "out_of_order"
  | "stale_epoch"
  | "fps_limited"
  | "frame_too_large"
  | "decode_timeout"
  | "inference_timeout"
  | "server_overloaded"
  | "session_closing";

export type FrameDeliveryResult = {
  frame_id: string;
  status: "accepted" | "dropped";
  reason: null | VisionDropReason;
};

export type FrameDeliveryOptions = {
  signal?: AbortSignal;
};

export type VisionStreamToken = {
  protocol_version: "1.0";
  session_id: string;
  video_id: string;
  stream_token: string;
  expires_at: string;
  websocket_path: "/vision/v1/stream";
};

export type VisionStreamTokenProvider = (
  context: { session_id: string; video_id: string },
  options?: FrameDeliveryOptions,
) => Promise<VisionStreamToken>;

export type VisionFrameEncoder = (
  frame: EphemeralVideoFrame,
  encoding: VisionFrameEncoding,
  options?: FrameDeliveryOptions,
) => Promise<Uint8Array>;

export interface RemoteVisionClient extends VisionClient {
  sendFrame(
    frame: EphemeralVideoFrame,
    context: FrameContext,
    options?: FrameDeliveryOptions,
  ): Promise<FrameDeliveryResult>;
}

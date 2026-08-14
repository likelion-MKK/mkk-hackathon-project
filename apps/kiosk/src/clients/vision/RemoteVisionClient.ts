import type { FrameContext } from "../../app/video-context.ts";
import type { VisionClient } from "./VisionClient.ts";

export type EphemeralVideoFrame = {
  readonly width: number;
  readonly height: number;
  close(): void;
};

export type FrameDeliveryResult = {
  frame_id: string;
  status: "accepted" | "dropped";
  reason: null | "in_flight";
};

export interface RemoteVisionClient extends VisionClient {
  sendFrame(
    frame: EphemeralVideoFrame,
    context: FrameContext,
  ): Promise<FrameDeliveryResult>;
}

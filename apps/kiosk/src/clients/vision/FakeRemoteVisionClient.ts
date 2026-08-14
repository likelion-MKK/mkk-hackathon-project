import type {
  CalibrationPattern,
  CalibrationResult,
  VisionHealth,
  VisionSessionContext,
} from "../../app/kiosk-types.ts";
import type { FrameContext } from "../../app/video-context.ts";
import { MockVisionClient, type MockVisionScenario } from "./MockVisionClient.ts";
import type {
  ExpressionSampleListener,
  GazeSampleListener,
  Unsubscribe,
  VisionOperationOptions,
} from "./VisionClient.ts";
import type {
  FrameDeliveryOptions,
  EphemeralVideoFrame,
  FrameDeliveryResult,
  RemoteVisionClient,
} from "./RemoteVisionClient.ts";

export class FakeRemoteVisionClient implements RemoteVisionClient {
  private readonly mockVisionClient: MockVisionClient;
  private sessionContext: VisionSessionContext | null = null;
  private frameInFlight = false;

  constructor(scenario: MockVisionScenario = "valid") {
    this.mockVisionClient = new MockVisionClient(scenario);
  }

  async startSession(
    context: VisionSessionContext,
    options: VisionOperationOptions = {},
  ): Promise<void> {
    await this.mockVisionClient.startSession(context, options);
    this.sessionContext = { ...context };
    this.frameInFlight = false;
  }

  startCalibration(pattern: CalibrationPattern): Promise<CalibrationResult> {
    return this.mockVisionClient.startCalibration(pattern);
  }

  startInference(): Promise<void> {
    return this.mockVisionClient.startInference();
  }

  onGazeSample(listener: GazeSampleListener): Unsubscribe {
    return this.mockVisionClient.onGazeSample(listener);
  }

  onExpressionSample(listener: ExpressionSampleListener): Unsubscribe {
    return this.mockVisionClient.onExpressionSample(listener);
  }

  async sendFrame(
    frame: EphemeralVideoFrame,
    context: FrameContext,
    { signal }: FrameDeliveryOptions = {},
  ): Promise<FrameDeliveryResult> {
    signal?.throwIfAborted();

    const sessionContext = this.sessionContext;
    if (!sessionContext) throw new Error("Fake remote Vision session has not started.");
    if (
      context.session_id !== sessionContext.session_id ||
      context.video_id !== sessionContext.video_id
    ) {
      throw new Error("FrameContext does not match the active Vision session.");
    }
    if (frame.width <= 0 || frame.height <= 0) {
      throw new Error("Ephemeral frame dimensions must be positive.");
    }
    if (this.frameInFlight) {
      return {
        frame_id: context.frame_id,
        status: "dropped",
        reason: "in_flight",
      };
    }

    this.frameInFlight = true;
    try {
      await Promise.resolve();
      signal?.throwIfAborted();
      return {
        frame_id: context.frame_id,
        status: "accepted",
        reason: null,
      };
    } finally {
      this.frameInFlight = false;
    }
  }

  async stopSession(): Promise<void> {
    this.sessionContext = null;
    this.frameInFlight = false;
    await this.mockVisionClient.stopSession();
  }

  health(): Promise<VisionHealth> {
    return this.mockVisionClient.health();
  }
}

import type {
  CalibrationPattern,
  CalibrationResult,
  ExpressionSample,
  GazeSample,
  VisionHealth,
  VisionSessionContext,
} from "../../app/kiosk-types.ts";
import type {
  ExpressionSampleListener,
  GazeSampleListener,
  Unsubscribe,
  VisionClient,
  VisionOperationOptions,
} from "./VisionClient.ts";

export type MockVisionScenario = "valid" | "no-face";

export class MockVisionClient implements VisionClient {
  private readonly gazeListeners = new Set<GazeSampleListener>();
  private readonly expressionListeners = new Set<ExpressionSampleListener>();
  private readonly scenario: MockVisionScenario;
  private context: VisionSessionContext | null = null;
  private calibrationId: string | null = null;
  private sequence = 0;

  constructor(scenario: MockVisionScenario = "valid") {
    this.scenario = scenario;
  }

  async startSession(
    context: VisionSessionContext,
    { signal }: VisionOperationOptions = {},
  ): Promise<void> {
    signal?.throwIfAborted();
    this.context = { ...context };
    this.calibrationId = null;
    this.sequence = 0;
  }

  async startCalibration(pattern: CalibrationPattern): Promise<CalibrationResult> {
    this.requireSession();

    if (pattern.points.length === 0) {
      return {
        calibration_id: `calibration-${pattern.pattern_id}`,
        valid: false,
        reason: "empty_pattern",
      };
    }

    this.calibrationId = `calibration-${pattern.pattern_id}`;

    return {
      calibration_id: this.calibrationId,
      valid: true,
      reason: null,
    };
  }

  async startInference(): Promise<void> {
    const context = this.requireSession();

    if (!this.calibrationId) {
      throw new Error("Mock vision calibration must finish before inference starts.");
    }

    this.sequence += 1;
    const gazeSample = this.createGazeSample(context, this.sequence);
    this.gazeListeners.forEach((listener) => listener(gazeSample));

    this.sequence += 1;
    const expressionSample = this.createExpressionSample(context, this.sequence);
    this.expressionListeners.forEach((listener) => listener(expressionSample));
  }

  onGazeSample(listener: GazeSampleListener): Unsubscribe {
    this.gazeListeners.add(listener);
    return () => this.gazeListeners.delete(listener);
  }

  onExpressionSample(listener: ExpressionSampleListener): Unsubscribe {
    this.expressionListeners.add(listener);
    return () => this.expressionListeners.delete(listener);
  }

  async stopSession(): Promise<void> {
    this.context = null;
    this.calibrationId = null;
    this.sequence = 0;
  }

  async health(): Promise<VisionHealth> {
    return {
      status: "ok",
      runtime: "mock",
      session_active: this.context !== null,
    };
  }

  private requireSession(): VisionSessionContext {
    if (!this.context) {
      throw new Error("Mock vision session has not started.");
    }

    return this.context;
  }

  private createGazeSample(
    context: VisionSessionContext,
    sequence: number,
  ): GazeSample {
    const base = {
      schema_version: "1.0" as const,
      session_id: context.session_id,
      event_id: `gaze-mock-${String(sequence).padStart(4, "0")}`,
      sequence,
      frame_id: `frame-${String(sequence).padStart(5, "0")}`,
      captured_at_mono_ms: sequence * 100,
      video_id: context.video_id,
      video_time_ms: sequence * 100,
      playback_epoch: 0,
      producer_id: "mock-vision-client-eye",
      model_revision: "d1-mock-v1",
      calibration_id: this.calibrationId ?? "calibration-missing",
    };

    if (this.scenario === "no-face") {
      return {
        ...base,
        valid: false,
        confidence: 0,
        reason: "face_not_detected",
      };
    }

    return {
      ...base,
      screen_x_norm: 0.3,
      screen_y_norm: 0.46,
      valid: true,
      confidence: 0.88,
      reason: null,
    };
  }

  private createExpressionSample(
    context: VisionSessionContext,
    sequence: number,
  ): ExpressionSample {
    const base = {
      schema_version: "1.0" as const,
      session_id: context.session_id,
      event_id: `expression-mock-${String(sequence).padStart(4, "0")}`,
      sequence,
      frame_id: `frame-${String(sequence - 1).padStart(5, "0")}`,
      captured_at_mono_ms: (sequence - 1) * 100,
      video_id: context.video_id,
      video_time_ms: (sequence - 1) * 100,
      playback_epoch: 0,
      producer_id: "mock-vision-client-face",
      model_revision: "d1-mock-v1",
      taxonomy_version: "d1-mock-taxonomy-v1",
    };

    if (this.scenario === "no-face") {
      return {
        ...base,
        face_detected: false,
        face_count: 0,
        scores: {},
        quality: 0,
        valid: false,
        confidence: 0,
        reason: "face_not_detected",
      };
    }

    return {
      ...base,
      face_detected: true,
      face_count: 1,
      scores: { unknown: 0.58 },
      quality: 0.79,
      valid: true,
      confidence: 0.82,
      reason: null,
    };
  }
}

import type { CalibrationProgress } from "../../app/calibration-session.ts";
import type {
  CalibrationPattern,
  CalibrationResult,
  ExpressionSample,
  GazeSample,
  VisionHealth,
  VisionSessionContext,
} from "../../app/kiosk-types.ts";

export type Unsubscribe = () => void;
export type GazeSampleListener = (sample: GazeSample) => void;
export type ExpressionSampleListener = (sample: ExpressionSample) => void;
export type VisionOperationOptions = {
  signal?: AbortSignal;
};

export interface VisionClient {
  startSession(
    context: VisionSessionContext,
    options?: VisionOperationOptions,
  ): Promise<void>;
  startCalibration(pattern: CalibrationPattern): Promise<CalibrationResult>;
  startInference(): Promise<void>;
  onCalibrationProgress?(listener: (progress: CalibrationProgress) => void): Unsubscribe;
  onGazeSample(listener: GazeSampleListener): Unsubscribe;
  onExpressionSample(listener: ExpressionSampleListener): Unsubscribe;
  stopSession(): Promise<void>;
  health(): Promise<VisionHealth>;
}

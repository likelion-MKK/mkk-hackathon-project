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

export interface VisionClient {
  startSession(context: VisionSessionContext): Promise<void>;
  startCalibration(pattern: CalibrationPattern): Promise<CalibrationResult>;
  startInference(): Promise<void>;
  onGazeSample(listener: GazeSampleListener): Unsubscribe;
  onExpressionSample(listener: ExpressionSampleListener): Unsubscribe;
  stopSession(): Promise<void>;
  health(): Promise<VisionHealth>;
}

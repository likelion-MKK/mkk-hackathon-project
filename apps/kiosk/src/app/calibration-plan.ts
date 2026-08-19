import type { CalibrationPattern, NormalizedPoint } from "./kiosk-types.ts";

const point = (x: number, y: number): NormalizedPoint => [x, y];

// Keep this 5x5 serpentine grid and its dwell times aligned with the original
// EyeTrax Dense5 calibration in services/eye.
const DENSE_GRID_AXIS = [0.1, 0.3, 0.5, 0.7, 0.9] as const;
export const FULLSCREEN_TRAINING_POINTS: readonly NormalizedPoint[] = DENSE_GRID_AXIS.flatMap(
  (y, row) =>
    (row % 2 === 0 ? DENSE_GRID_AXIS : [...DENSE_GRID_AXIS].reverse()).map((x) => point(x, y)),
);

export const FULLSCREEN_VALIDATION_POINTS: readonly NormalizedPoint[] = [
  point(0.2, 0.3),
  point(0.38, 0.3),
  point(0.2, 0.7),
  point(0.42, 0.7),
  point(0.8, 0.3),
  point(0.62, 0.3),
  point(0.8, 0.7),
  point(0.58, 0.7),
];

export const CALIBRATION_PATTERN: CalibrationPattern = {
  pattern_id: "dense5-validation-v1",
  points: [...FULLSCREEN_TRAINING_POINTS, ...FULLSCREEN_VALIDATION_POINTS],
};

export const CALIBRATION_CAPTURE_INTERVAL_MS = 50;
export const CALIBRATION_TARGET_TRANSITION_MS = 240;
export const CALIBRATION_TRAINING_DWELL_MS = 2_000;
export const CALIBRATION_VALIDATION_DWELL_MS = 1_750;
export const CALIBRATION_MAX_ATTEMPTS = 1;
export const CALIBRATION_ATTEMPT_DURATION_MS =
  FULLSCREEN_TRAINING_POINTS.length * CALIBRATION_TRAINING_DWELL_MS +
  FULLSCREEN_VALIDATION_POINTS.length * CALIBRATION_VALIDATION_DWELL_MS;
export const CALIBRATION_WORST_CASE_DURATION_MS =
  CALIBRATION_MAX_ATTEMPTS * CALIBRATION_ATTEMPT_DURATION_MS;

export function calibrationDwellMs(targetIndex: number): number {
  if (!Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex >= CALIBRATION_PATTERN.points.length) {
    throw new RangeError("Calibration target index is out of range.");
  }
  return targetIndex < FULLSCREEN_TRAINING_POINTS.length
    ? CALIBRATION_TRAINING_DWELL_MS
    : CALIBRATION_VALIDATION_DWELL_MS;
}

const CALIBRATION_FAILURE_COPY: Readonly<Record<string, string>> = {
  no_face: "얼굴을 인식하지 못했습니다. 얼굴을 화면 중앙에 두고 다시 시도해주세요.",
  quality_gate_failed: "시선 품질을 확인하지 못했습니다. 점을 천천히 따라가며 다시 시도해주세요.",
  calibration_timed_out: "보정 시간이 끝났습니다. 다시 시도해주세요.",
  calibration_cancelled: "보정이 취소되었습니다. 다시 시도해주세요.",
  eye_not_connected: "로컬 Eye worker 연결을 확인한 뒤 다시 시도해주세요.",
  calibration_error: "로컬 Eye worker 처리 중 오류가 발생했습니다. 다시 시도해주세요.",
};

export function calibrationFailureMessage(reason: unknown): string {
  if (typeof reason === "string" && Object.hasOwn(CALIBRATION_FAILURE_COPY, reason)) {
    return CALIBRATION_FAILURE_COPY[reason] ?? "로컬 시선 보정을 완료하지 못했습니다.";
  }
  return "로컬 시선 보정을 완료하지 못했습니다.";
}

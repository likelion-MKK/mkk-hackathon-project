import type { CalibrationPattern, NormalizedPoint } from "./kiosk-types.ts";

const point = (x: number, y: number): NormalizedPoint => [x, y];

// Training coordinates must match the named worker profile. Validation is worker-owned.
// Legacy dwell constants below are retained only for baseline timing comparisons.
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
  pattern_id: "adaptive-dense5-v2",
  points: [...FULLSCREEN_TRAINING_POINTS],
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
  if (!Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex >= FULLSCREEN_TRAINING_POINTS.length + FULLSCREEN_VALIDATION_POINTS.length) {
    throw new RangeError("Calibration target index is out of range.");
  }
  return targetIndex < FULLSCREEN_TRAINING_POINTS.length
    ? CALIBRATION_TRAINING_DWELL_MS
    : CALIBRATION_VALIDATION_DWELL_MS;
}

export function resolveCalibrationPattern(profile = "adaptive-dense5-v2"): CalibrationPattern {
  if (profile === "adaptive-dense5-v2" || profile === "fixed-dense5-v2") {
    return { pattern_id: profile, points: [...FULLSCREEN_TRAINING_POINTS] };
  }
  if (profile === "adaptive-sparse16-v2") {
    const axis = [0.1, 0.366667, 0.633333, 0.9];
    return { pattern_id: profile, points: axis.flatMap((y, row) =>
      (row % 2 === 0 ? axis : [...axis].reverse()).map((x) => point(x, y))) };
  }
  throw new Error("Unsupported VITE_CALIBRATION_PROFILE.");
}

const CALIBRATION_FAILURE_COPY: Readonly<Record<string, string>> = {
  face_position_not_ready: "얼굴 위치를 맞추지 못했습니다. 조명과 카메라 위치를 확인한 뒤 다시 시작해주세요.",
  face_position_unavailable: "얼굴 위치 확인을 시작하지 못했습니다. 로컬 Eye worker를 다시 실행해주세요.",
  unstable_head: "편안하게 고개를 고정하고 다시 시작해주세요.",
  insufficient_calibration_samples: "시선을 충분히 모으지 못했습니다. 조명과 눈 위치를 확인해주세요.",
  viewport_changed: "화면 크기가 바뀌었습니다. 같은 화면 크기로 다시 시작해주세요.",
  no_face: "얼굴을 인식하지 못했습니다. 얼굴을 화면 중앙에 두고 다시 시도해주세요.",
  validation_samples_insufficient: "확인에 필요한 표본이 충분히 도착하지 않았습니다. 카메라 연결과 얼굴 인식 상태를 확인해주세요.",
  validation_signal_insufficient: "시선 검출이 충분히 이어지지 않았습니다. 조명과 카메라 위치를 조정해 양쪽 눈이 잘 보이게 해주세요.",
  validation_accuracy_failed: "시선 위치의 오차가 기준보다 컸습니다. 카메라를 화면 정면에 맞추고 편안한 자세에서 다시 보정해주세요.",
  validation_signal_and_accuracy_failed: "시선 검출의 연속성과 위치 오차가 모두 기준에 미치지 못했습니다. 조명과 카메라 위치를 조정한 뒤 다시 보정해주세요.",
  quality_gate_failed: "현재 환경에서 시선 품질을 확인하지 못했습니다. 조명과 카메라 위치를 확인해주세요.",
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

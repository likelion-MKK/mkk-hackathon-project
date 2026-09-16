import assert from "node:assert/strict";
import test from "node:test";

import {
  CALIBRATION_ATTEMPT_DURATION_MS,
  CALIBRATION_PATTERN,
  CALIBRATION_TARGET_TRANSITION_MS,
  CALIBRATION_WORST_CASE_DURATION_MS,
  FULLSCREEN_TRAINING_POINTS,
  FULLSCREEN_VALIDATION_POINTS,
  calibrationFailureMessage,
  calibrationDwellMs,
  resolveCalibrationPattern,
} from "./calibration-plan.ts";

test("face positioning progress cannot expose raw geometry or claim stability with a failed check", async () => {
  const { parseCalibrationProgress, calibrationHint } = await import("./calibration-session.ts");
  const progress = {
    calibration_id: "cal-position", profile_id: "adaptive-dense5-v2", phase: "positioning",
    target_id: "target-1", target: [.5, .5], accepted_samples: 9, required_samples: 15,
    completed_targets: 0, total_targets: 34, hint: "position_ready",
    positioning: { face_detected: true, eyes_visible: true, centered: true, distance_ok: true, facing_forward: true, stable_ms: 600 },
  };
  assert.equal(parseCalibrationProgress(progress).positioning?.stable_ms, 600);
  assert.match(calibrationHint(parseCalibrationProgress(progress)), /준비/);
  for (const change of [
    { phase: "training" }, { positioning: null },
    { positioning: { ...progress.positioning, stable_ms: 1001 } },
    { positioning: { ...progress.positioning, eyes_visible: false } },
    { positioning: { ...progress.positioning, landmarks: [] } },
  ]) assert.throws(() => parseCalibrationProgress({ ...progress, ...change }));
});

test("submission Dense5 calibration covers the viewport in one attempt", () => {
  assert.deepEqual(FULLSCREEN_TRAINING_POINTS[0], [0.1, 0.1]);
  assert.deepEqual(FULLSCREEN_TRAINING_POINTS[5], [0.9, 0.3]);
  assert.deepEqual(FULLSCREEN_TRAINING_POINTS[24], [0.9, 0.9]);
  assert.equal(CALIBRATION_PATTERN.pattern_id, "adaptive-dense5-v2");
  assert.equal(
    CALIBRATION_PATTERN.points.length,
    FULLSCREEN_TRAINING_POINTS.length,
  );
  assert.equal(FULLSCREEN_TRAINING_POINTS.length, 25);
  assert.equal(FULLSCREEN_VALIDATION_POINTS.length, 8);
  assert.equal(CALIBRATION_ATTEMPT_DURATION_MS, 64_000);
  assert.equal(CALIBRATION_WORST_CASE_DURATION_MS, 64_000);
  assert.ok(CALIBRATION_TARGET_TRANSITION_MS < calibrationDwellMs(0));
  assert.equal(calibrationDwellMs(FULLSCREEN_TRAINING_POINTS.length), 1_750);
});

test("calibration failures expose only an allowlisted local reason", () => {
  assert.match(calibrationFailureMessage("no_face"), /얼굴/);
  assert.match(calibrationFailureMessage("eye_not_connected"), /Eye worker/);
  assert.equal(
    calibrationFailureMessage("connection string must never be shown"),
    "로컬 시선 보정을 완료하지 못했습니다.",
  );
});

test("calibration distinguishes missing signal from spatial error without blaming target following", () => {
  assert.match(calibrationFailureMessage("validation_samples_insufficient"), /표본/);
  assert.match(calibrationFailureMessage("validation_signal_insufficient"), /검출/);
  assert.doesNotMatch(calibrationFailureMessage("validation_signal_insufficient"), /오차|따라/);
  assert.match(calibrationFailureMessage("validation_accuracy_failed"), /오차/);
  assert.match(calibrationFailureMessage("validation_signal_and_accuracy_failed"), /연속성.*오차/);
  assert.doesNotMatch(calibrationFailureMessage("quality_gate_failed"), /천천히 따라/);
});


test("sparse and fixed profiles cover the screen without training on validation points", () => {
  for (const [id, count] of [["adaptive-sparse16-v2", 16], ["fixed-dense5-v2", 25]] as const) {
    const pattern = resolveCalibrationPattern(id);
    assert.equal(pattern.points.length, count);
    assert.deepEqual(pattern.points[0], [0.1, 0.1]);
    assert.ok(pattern.points.some(([x, y]) => x === 0.9 && y === 0.9));
    assert.ok(pattern.points.every((p) => !FULLSCREEN_VALIDATION_POINTS.some((v) => String(v) === String(p))));
  }
  assert.throws(() => resolveCalibrationPattern("unknown"));
});


import { parseCalibrationProgress, calibrationHint } from "./calibration-session.ts";

test("a quality failure remains a failure and requires a fresh calibration", () => {
  for (const reason of ["validation_accuracy_failed", "validation_signal_insufficient", "validation_samples_insufficient",
    "no_face", "face_position_not_ready", "insufficient_calibration_samples", "calibration_timed_out", "eye_not_connected"]) {
    assert.match(calibrationFailureMessage(reason), /./);
  }
});
const progress = { calibration_id: "cal-1", profile_id: "adaptive-dense5-v2", phase: "training",
  target_id: "target-2", target: [0.1, 0.1], accepted_samples: 10, required_samples: 15,
  completed_targets: 1, total_targets: 34, hint: "more_samples" };

test("progress accepts only bounded fields and meaningful sample counts", () => {
  assert.deepEqual(parseCalibrationProgress(progress), progress);
  for (const change of [ { accepted_samples: 16 }, { required_samples: 0 }, { target: [NaN, 0.1] },
    { completed_targets: 35 }, { profile_id: "arbitrary" }, { target_id: "" }, { raw_image: "private" } ]) {
    assert.throws(() => parseCalibrationProgress({ ...progress, ...change }));
  }
  assert.match(calibrationHint(parseCalibrationProgress({ ...progress, hint: "no_face" })), /얼굴/);
  assert.match(calibrationHint(parseCalibrationProgress({ ...progress, hint: "blink" })), /깜빡/);
  const extended = parseCalibrationProgress({ ...progress, phase: "validation", required_samples: 30, accepted_samples: 20 });
  assert.equal(extended.required_samples, 30);
  assert.match(calibrationHint(extended), /조금 더.*같은 점/);
});

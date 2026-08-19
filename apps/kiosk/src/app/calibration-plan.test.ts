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
} from "./calibration-plan.ts";

test("submission Dense5 calibration covers the viewport in one attempt", () => {
  assert.deepEqual(FULLSCREEN_TRAINING_POINTS[0], [0.1, 0.1]);
  assert.deepEqual(FULLSCREEN_TRAINING_POINTS[5], [0.9, 0.3]);
  assert.deepEqual(FULLSCREEN_TRAINING_POINTS[24], [0.9, 0.9]);
  assert.equal(CALIBRATION_PATTERN.pattern_id, "dense5-validation-v1");
  assert.equal(
    CALIBRATION_PATTERN.points.length,
    FULLSCREEN_TRAINING_POINTS.length + FULLSCREEN_VALIDATION_POINTS.length,
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

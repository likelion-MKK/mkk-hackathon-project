import assert from "node:assert/strict";
import test from "node:test";
import type { ExpressionSample, GazeSample } from "../../app/kiosk-types.ts";
import { MockVisionClient } from "./MockVisionClient.ts";

const calibrationPattern = {
  pattern_id: "five-point-v1",
  points: [
    [0.5, 0.5],
    [0.1, 0.1],
    [0.9, 0.1],
    [0.1, 0.9],
    [0.9, 0.9],
  ] as [number, number][],
};

test("mock Vision이 보정 후 계약 형식의 시선·표정 신호를 전달한다", async () => {
  const client = new MockVisionClient();
  const gazeSamples: GazeSample[] = [];
  const expressionSamples: ExpressionSample[] = [];
  const removeGazeListener = client.onGazeSample((sample) => gazeSamples.push(sample));
  const removeExpressionListener = client.onExpressionSample((sample) =>
    expressionSamples.push(sample),
  );

  await client.startSession({
    session_id: "session-example-001",
    video_id: "mcm-lookbook-example-v1",
  });
  const calibration = await client.startCalibration(calibrationPattern);
  await client.startInference();

  assert.equal(calibration.valid, true);
  assert.equal(gazeSamples.length, 1);
  assert.equal(gazeSamples[0]?.valid, true);
  assert.equal(expressionSamples.length, 1);
  assert.equal(expressionSamples[0]?.valid, true);
  assert.deepEqual(await client.health(), {
    status: "ok",
    runtime: "mock",
    session_active: true,
  });

  removeGazeListener();
  removeExpressionListener();
  await client.startInference();
  assert.equal(gazeSamples.length, 1);
  assert.equal(expressionSamples.length, 1);

  await client.stopSession();
  assert.equal((await client.health()).session_active, false);
});

test("무효 신호를 좌표 0 또는 중립 표정으로 바꾸지 않는다", async () => {
  const client = new MockVisionClient("no-face");
  let gazeSample: GazeSample | undefined;
  let expressionSample: ExpressionSample | undefined;

  client.onGazeSample((sample) => {
    gazeSample = sample;
  });
  client.onExpressionSample((sample) => {
    expressionSample = sample;
  });

  await client.startSession({
    session_id: "session-example-001",
    video_id: "mcm-lookbook-example-v1",
  });
  await client.startCalibration(calibrationPattern);
  await client.startInference();

  assert.equal(gazeSample?.valid, false);
  assert.equal(gazeSample?.reason, "face_not_detected");
  assert.equal("screen_x_norm" in (gazeSample ?? {}), false);
  assert.equal("screen_y_norm" in (gazeSample ?? {}), false);
  assert.equal(expressionSample?.valid, false);
  assert.equal(expressionSample?.reason, "face_not_detected");
  assert.deepEqual(expressionSample?.scores, {});
});

test("세션이나 보정 없이 추론을 시작하지 못한다", async () => {
  const client = new MockVisionClient();

  await assert.rejects(client.startInference(), /session has not started/);
  await client.startSession({
    session_id: "session-example-001",
    video_id: "mcm-lookbook-example-v1",
  });
  await assert.rejects(client.startInference(), /calibration must finish/);
});

test("취소된 시작 요청은 Mock Vision 세션을 열지 않는다", async () => {
  const client = new MockVisionClient();
  const controller = new AbortController();
  controller.abort(new Error("session_start_cancelled"));

  await assert.rejects(
    client.startSession(
      {
        session_id: "session-cancelled-001",
        video_id: "mcm-lookbook-example-v1",
      },
      { signal: controller.signal },
    ),
    /session_start_cancelled/,
  );
  assert.equal((await client.health()).session_active, false);
});

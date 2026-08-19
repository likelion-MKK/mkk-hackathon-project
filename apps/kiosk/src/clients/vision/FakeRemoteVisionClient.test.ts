import assert from "node:assert/strict";
import test from "node:test";
import type { ExpressionSample, GazeSample } from "../../app/kiosk-types.ts";
import type { FrameContext } from "../../app/video-context.ts";
import { FakeRemoteVisionClient } from "./FakeRemoteVisionClient.ts";

const context: FrameContext = {
  session_id: "session-d03-001",
  sequence: 1,
  frame_id: "frame-00000001",
  captured_at_mono_ms: 1_234.5,
  video_id: "mcm-lookbook-bags-v1",
  video_time_ms: 4_200,
  playback_epoch: 0,
  layout: {
    viewport_width_px: 1_920,
    viewport_height_px: 1_080,
    source_width_px: 1_920,
    source_height_px: 1_080,
    object_fit: "contain",
    element_rect: { x_px: 0, y_px: 0, width_px: 1_920, height_px: 1_080 },
    content_rect: { x_px: 0, y_px: 0, width_px: 1_920, height_px: 1_080 },
  },
};

const calibrationPattern = {
  pattern_id: "five-point-v1",
  points: [[0.5, 0.5]] as [number, number][],
};

test("FakeRemoteVisionClient가 frame을 보관하지 않고 context 경계를 확인한다", async () => {
  const client = new FakeRemoteVisionClient();
  let closeCount = 0;
  const frame = {
    width: 1_280,
    height: 720,
    close: () => {
      closeCount += 1;
    },
  };

  await client.startSession({
    session_id: context.session_id,
    video_id: context.video_id,
  });
  const result = await client.sendFrame(frame, context);

  assert.deepEqual(result, {
    frame_id: context.frame_id,
    status: "accepted",
    reason: null,
  });
  assert.equal(closeCount, 0);
});

test("활성 session과 다른 FrameContext는 전송하지 않는다", async () => {
  const client = new FakeRemoteVisionClient();
  const frame = { width: 640, height: 360, close: () => undefined };

  await assert.rejects(client.sendFrame(frame, context), /session has not started/);
  await client.startSession({
    session_id: context.session_id,
    video_id: context.video_id,
  });
  await assert.rejects(
    client.sendFrame(frame, { ...context, session_id: "session-other" }),
    /does not match/,
  );
});

test("frame 전달 중 취소되면 accepted로 완료하지 않는다", async () => {
  const client = new FakeRemoteVisionClient();
  const frame = { width: 640, height: 360, close: () => undefined };
  const abortController = new AbortController();

  await client.startSession({
    session_id: context.session_id,
    video_id: context.video_id,
  });
  const delivery = client.sendFrame(frame, context, {
    signal: abortController.signal,
  });
  abortController.abort();

  await assert.rejects(delivery, (error: unknown) => {
    return error instanceof DOMException && error.name === "AbortError";
  });
  assert.equal((await client.sendFrame(frame, context)).status, "accepted");
});

test("captured frame context is preserved in emitted gaze and expression samples", async () => {
  const client = new FakeRemoteVisionClient();
  const gazeSamples: GazeSample[] = [];
  const expressionSamples: ExpressionSample[] = [];
  const capturedContext: FrameContext = {
    ...context,
    sequence: 0,
    frame_id: "frame-00000000",
    captured_at_mono_ms: 5_678.9,
    video_time_ms: 8_400,
  };
  const frame = { width: 640, height: 360, close: () => undefined };

  client.onGazeSample((sample) => gazeSamples.push(sample));
  client.onExpressionSample((sample) => expressionSamples.push(sample));
  await client.startSession({
    session_id: capturedContext.session_id,
    video_id: capturedContext.video_id,
  });
  await client.startCalibration(calibrationPattern);
  await client.startInference();

  assert.equal(gazeSamples.length, 0);
  assert.equal(expressionSamples.length, 0);
  await client.sendFrame(frame, capturedContext);

  assert.equal(gazeSamples.length, 1);
  assert.equal(gazeSamples[0]?.frame_id, capturedContext.frame_id);
  assert.equal(gazeSamples[0]?.captured_at_mono_ms, capturedContext.captured_at_mono_ms);
  assert.equal(gazeSamples[0]?.video_time_ms, capturedContext.video_time_ms);
  assert.equal(expressionSamples.length, 1);
  assert.equal(expressionSamples[0]?.frame_id, capturedContext.frame_id);
});

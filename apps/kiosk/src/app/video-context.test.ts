import assert from "node:assert/strict";
import test from "node:test";
import {
  calculateContainedVideoLayout,
  createFrameContext,
} from "./video-context.ts";

test("16:9 영상을 정사각형 element 안에 contain으로 배치한다", () => {
  const layout = calculateContainedVideoLayout({
    viewport_width_px: 1_200,
    viewport_height_px: 900,
    source_width_px: 1_920,
    source_height_px: 1_080,
    element_rect: {
      x_px: 100,
      y_px: 50,
      width_px: 1_000,
      height_px: 800,
    },
  });

  assert.deepEqual(layout.element_rect, {
    x_px: 100,
    y_px: 50,
    width_px: 1_000,
    height_px: 800,
  });
  assert.deepEqual(layout.content_rect, {
    x_px: 100,
    y_px: 168.75,
    width_px: 1_000,
    height_px: 562.5,
  });
  assert.equal(layout.object_fit, "contain");
});

test("세로 영상의 좌우 letterbox를 실제 content 영역에서 제외한다", () => {
  const layout = calculateContainedVideoLayout({
    viewport_width_px: 1_200,
    viewport_height_px: 600,
    source_width_px: 1_080,
    source_height_px: 1_920,
    element_rect: {
      x_px: 100,
      y_px: 50,
      width_px: 1_000,
      height_px: 500,
    },
  });

  assert.deepEqual(layout.content_rect, {
    x_px: 459.375,
    y_px: 50,
    width_px: 281.25,
    height_px: 500,
  });
});

test("FrameContext는 캡처 순간의 영상 시각과 layout을 복사해 고정한다", () => {
  const layout = calculateContainedVideoLayout({
    viewport_width_px: 1_920,
    viewport_height_px: 1_080,
    source_width_px: 1_920,
    source_height_px: 1_080,
    element_rect: {
      x_px: 0,
      y_px: 0,
      width_px: 1_920,
      height_px: 1_080,
    },
  });
  const context = createFrameContext({
    session_id: "session-d03-preview",
    sequence: 7,
    frame_id: "frame-00007",
    captured_at_mono_ms: 12_345.67,
    video_id: "mcm-lookbook-example-v1",
    video_time_seconds: 4.2009,
    playback_epoch: 1,
    layout,
  });

  assert.equal(context.video_time_ms, 4_200);
  assert.equal(context.playback_epoch, 1);
  assert.notEqual(context.layout, layout);
  assert.notEqual(context.layout.content_rect, layout.content_rect);
  assert.deepEqual(context.layout, layout);
});

test("layout과 FrameContext의 잘못된 시간·크기를 거부한다", () => {
  assert.throws(
    () =>
      calculateContainedVideoLayout({
        viewport_width_px: 1_920,
        viewport_height_px: 1_080,
        source_width_px: 0,
        source_height_px: 1_080,
        element_rect: { x_px: 0, y_px: 0, width_px: 1_920, height_px: 1_080 },
      }),
    RangeError,
  );

  const layout = calculateContainedVideoLayout({
    viewport_width_px: 1_920,
    viewport_height_px: 1_080,
    source_width_px: 1_920,
    source_height_px: 1_080,
    element_rect: { x_px: 0, y_px: 0, width_px: 1_920, height_px: 1_080 },
  });

  assert.throws(
    () =>
      createFrameContext({
        session_id: "session-d03-preview",
        sequence: 0,
        frame_id: "frame-00000",
        captured_at_mono_ms: 10,
        video_id: "mcm-lookbook-example-v1",
        video_time_seconds: -0.1,
        playback_epoch: 0,
        layout,
      }),
    RangeError,
  );
});

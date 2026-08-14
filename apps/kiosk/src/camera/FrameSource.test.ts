import assert from "node:assert/strict";
import test from "node:test";
import {
  CameraAccessError,
  CAMERA_VIDEO_CONSTRAINTS,
  FrameSource,
} from "./FrameSource.ts";
import type { FrameContext } from "../app/video-context.ts";

function createContext(): FrameContext {
  return {
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
}

function createCameraFixture() {
  let stopCount = 0;
  let pauseCount = 0;
  let loadCount = 0;
  const track = {
    stop: () => {
      stopCount += 1;
    },
  } as unknown as MediaStreamTrack;
  const stream = {
    getTracks: () => [track],
    getVideoTracks: () => [track],
  } as unknown as MediaStream;
  const video = {
    readyState: 2,
    videoWidth: 1_280,
    videoHeight: 720,
    muted: false,
    playsInline: false,
    srcObject: null,
    play: async () => undefined,
    pause: () => {
      pauseCount += 1;
    },
    load: () => {
      loadCount += 1;
    },
    removeAttribute: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  } as unknown as HTMLVideoElement;

  return {
    stream,
    video,
    get stopCount() {
      return stopCount;
    },
    get pauseCount() {
      return pauseCount;
    },
    get loadCount() {
      return loadCount;
    },
  };
}

test("동시에 열어도 카메라 stream은 한 번만 요청한다", async () => {
  const fixture = createCameraFixture();
  let requestCount = 0;
  let requestedConstraints: MediaStreamConstraints | undefined;
  const source = new FrameSource({
    mediaDevices: {
      getUserMedia: async (constraints) => {
        requestCount += 1;
        requestedConstraints = constraints;
        return fixture.stream;
      },
    },
    createVideoElement: () => fixture.video,
  });

  await Promise.all([source.open(), source.open()]);

  assert.equal(requestCount, 1);
  assert.deepEqual(requestedConstraints, {
    audio: false,
    video: CAMERA_VIDEO_CONSTRAINTS,
  });
  assert.equal(source.isOpen(), true);
  assert.equal(fixture.video.muted, true);
  assert.equal(fixture.video.playsInline, true);
});

test("FrameSource가 frame과 FrameContext를 전달한 뒤 원본 frame을 해제한다", async () => {
  const fixture = createCameraFixture();
  let closeCount = 0;
  const frame = {
    width: 1_280,
    height: 720,
    close: () => {
      closeCount += 1;
    },
  };
  const source = new FrameSource({
    mediaDevices: { getUserMedia: async () => fixture.stream },
    createVideoElement: () => fixture.video,
    createFrame: async () => frame,
  });
  const context = createContext();
  let receivedContext: FrameContext | undefined;

  await source.open();
  const outcome = await source.capture(context, async (_frame, received) => {
    receivedContext = received;
  });

  assert.equal(outcome, "delivered");
  assert.equal(receivedContext, context);
  assert.equal(closeCount, 1);
});

test("이전 frame 처리 중에는 새 frame을 쌓지 않고 drop한다", async () => {
  const fixture = createCameraFixture();
  let finishConsumer: (() => void) | undefined;
  let markConsumerStarted: (() => void) | undefined;
  const consumerStarted = new Promise<void>((resolve) => {
    markConsumerStarted = resolve;
  });
  const consumerFinished = new Promise<void>((resolve) => {
    finishConsumer = resolve;
  });
  const source = new FrameSource({
    mediaDevices: { getUserMedia: async () => fixture.stream },
    createVideoElement: () => fixture.video,
    createFrame: async () => ({ width: 640, height: 360, close: () => undefined }),
  });

  await source.open();
  const firstCapture = source.capture(createContext(), async () => {
    markConsumerStarted?.();
    await consumerFinished;
  });
  await consumerStarted;
  const secondOutcome = await source.capture(createContext(), async () => undefined);
  finishConsumer?.();

  assert.equal(secondOutcome, "dropped");
  assert.equal(await firstCapture, "delivered");
});

test("화면을 나가면 모든 camera track과 video 참조를 해제한다", async () => {
  const fixture = createCameraFixture();
  const source = new FrameSource({
    mediaDevices: { getUserMedia: async () => fixture.stream },
    createVideoElement: () => fixture.video,
  });

  await source.open();
  source.stop();

  assert.equal(source.isOpen(), false);
  assert.equal(fixture.stopCount, 1);
  assert.equal(fixture.pauseCount, 1);
  assert.equal(fixture.loadCount, 1);
  assert.equal(fixture.video.srcObject, null);
  await assert.rejects(
    source.capture(createContext(), async () => undefined),
    (error: unknown) =>
      error instanceof CameraAccessError && error.code === "camera_not_ready",
  );
});

test("권한 대기 중 취소되면 늦게 열린 stream도 즉시 닫는다", async () => {
  const fixture = createCameraFixture();
  let resolveStream: ((stream: MediaStream) => void) | undefined;
  const pendingStream = new Promise<MediaStream>((resolve) => {
    resolveStream = resolve;
  });
  const source = new FrameSource({
    mediaDevices: { getUserMedia: async () => pendingStream },
    createVideoElement: () => fixture.video,
  });

  const opening = source.open();
  source.stop();
  resolveStream?.(fixture.stream);

  await assert.rejects(
    opening,
    (error: unknown) => error instanceof CameraAccessError && error.code === "cancelled",
  );
  assert.equal(fixture.stopCount, 1);
  assert.equal(source.isOpen(), false);
});

test("브라우저 카메라 거부를 명시적인 permission_denied로 구분한다", async () => {
  const deniedError = Object.assign(new Error("denied"), { name: "NotAllowedError" });
  const source = new FrameSource({
    mediaDevices: {
      getUserMedia: async () => {
        throw deniedError;
      },
    },
  });

  await assert.rejects(
    source.open(),
    (error: unknown) =>
      error instanceof CameraAccessError && error.code === "permission_denied",
  );
});

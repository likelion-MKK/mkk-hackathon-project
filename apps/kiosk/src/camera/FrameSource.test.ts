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

function createWaitingVideo(onPlay: () => void): HTMLVideoElement {
  return {
    readyState: 0,
    videoWidth: 0,
    videoHeight: 0,
    muted: false,
    playsInline: false,
    srcObject: null,
    play: async () => {
      onPlay();
    },
    pause: () => undefined,
    load: () => undefined,
    removeAttribute: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  } as unknown as HTMLVideoElement;
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

test("캡처 직전에 만든 context는 inference가 지연돼도 최초 video_time_ms를 유지한다", async () => {
  const fixture = createCameraFixture();
  let videoTimeMs = 4_200;
  let factoryCallCount = 0;
  let markConsumerStarted: (() => void) | undefined;
  let finishConsumer: (() => void) | undefined;
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
  let receivedContext: FrameContext | undefined;

  await source.open();
  const capture = source.capture(
    () => {
      factoryCallCount += 1;
      return { ...createContext(), video_time_ms: videoTimeMs };
    },
    async (_frame, context) => {
      receivedContext = context;
      markConsumerStarted?.();
      await consumerFinished;
    },
  );
  await consumerStarted;

  videoTimeMs = 9_000;
  finishConsumer?.();

  assert.equal(await capture, "delivered");
  assert.equal(factoryCallCount, 1);
  assert.equal(receivedContext?.video_time_ms, 4_200);
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
  let droppedContextFactoryCalls = 0;
  const secondOutcome = await source.capture(
    () => {
      droppedContextFactoryCalls += 1;
      return createContext();
    },
    async () => undefined,
  );
  finishConsumer?.();

  assert.equal(secondOutcome, "dropped");
  assert.equal(droppedContextFactoryCalls, 0);
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

test("카메라 초기화 중 stop하면 pending stream을 즉시 해제한다", async () => {
  const fixture = createCameraFixture();
  let markVideoPlayStarted: (() => void) | undefined;
  const videoPlayStarted = new Promise<void>((resolve) => {
    markVideoPlayStarted = resolve;
  });
  const source = new FrameSource({
    mediaDevices: { getUserMedia: async () => fixture.stream },
    createVideoElement: () =>
      createWaitingVideo(() => {
        markVideoPlayStarted?.();
      }),
    readyTimeoutMs: 1_000,
  });

  const opening = source.open();
  const openingRejected = assert.rejects(
    opening,
    (error: unknown) =>
      error instanceof CameraAccessError && error.code === "cancelled",
  );
  await videoPlayStarted;

  source.stop();

  assert.equal(fixture.stopCount, 1);
  assert.equal(source.isOpen(), false);
  await openingRejected;
  assert.equal(fixture.stopCount, 1);
});

test("취소된 open과 분리해 재시도는 새 camera 요청을 시작한다", async () => {
  const firstFixture = createCameraFixture();
  const retryFixture = createCameraFixture();
  let requestCount = 0;
  let videoCount = 0;
  let markFirstVideoPlayStarted: (() => void) | undefined;
  const firstVideoPlayStarted = new Promise<void>((resolve) => {
    markFirstVideoPlayStarted = resolve;
  });
  const source = new FrameSource({
    mediaDevices: {
      getUserMedia: async () => {
        requestCount += 1;
        return requestCount === 1 ? firstFixture.stream : retryFixture.stream;
      },
    },
    createVideoElement: () => {
      videoCount += 1;
      return videoCount === 1
        ? createWaitingVideo(() => {
            markFirstVideoPlayStarted?.();
          })
        : retryFixture.video;
    },
    readyTimeoutMs: 1_000,
  });

  const firstOpening = source.open();
  const firstOpeningRejected = assert.rejects(
    firstOpening,
    (error: unknown) =>
      error instanceof CameraAccessError && error.code === "cancelled",
  );
  await firstVideoPlayStarted;

  source.stop();
  await source.open();

  assert.equal(requestCount, 2);
  assert.equal(firstFixture.stopCount, 1);
  assert.equal(source.isOpen(), true);
  await firstOpeningRejected;
  assert.equal(firstFixture.stopCount, 1);

  source.stop();
  assert.equal(retryFixture.stopCount, 1);
});

test("consumer 처리 중 stop하면 취소 신호를 보내고 delivered 완료를 막는다", async () => {
  const fixture = createCameraFixture();
  let closeCount = 0;
  let observedSignal: AbortSignal | undefined;
  let markConsumerStarted: (() => void) | undefined;
  let finishConsumer: (() => void) | undefined;
  const consumerStarted = new Promise<void>((resolve) => {
    markConsumerStarted = resolve;
  });
  const consumerFinished = new Promise<void>((resolve) => {
    finishConsumer = resolve;
  });
  const source = new FrameSource({
    mediaDevices: { getUserMedia: async () => fixture.stream },
    createVideoElement: () => fixture.video,
    createFrame: async () => ({
      width: 640,
      height: 360,
      close: () => {
        closeCount += 1;
      },
    }),
  });

  await source.open();
  const capture = source.capture(createContext(), async (_frame, _context, signal) => {
    observedSignal = signal;
    markConsumerStarted?.();
    await consumerFinished;
  });
  const captureRejected = assert.rejects(
    capture,
    (error: unknown) =>
      error instanceof CameraAccessError && error.code === "cancelled",
  );
  await consumerStarted;

  source.stop();

  assert.equal(observedSignal?.aborted, true);
  assert.equal(closeCount, 1);
  finishConsumer?.();
  await captureRejected;
  assert.equal(closeCount, 1);
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

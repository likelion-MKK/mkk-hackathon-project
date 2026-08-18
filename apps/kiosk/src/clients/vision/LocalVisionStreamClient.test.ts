import assert from "node:assert/strict";
import test from "node:test";
import type { FrameContext } from "../../app/video-context.ts";
import {
  LocalVisionStreamClient,
} from "./LocalVisionStreamClient.ts";
import type { EphemeralVideoFrame, VisionStreamToken } from "./RemoteVisionClient.ts";

const context: FrameContext = {
  session_id: "session-live-001",
  sequence: 4,
  frame_id: "frame-00000004",
  captured_at_mono_ms: 1_234.5,
  video_id: "mcm-lookbook-live-v1",
  video_time_ms: 1_000,
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

const token: VisionStreamToken = {
  protocol_version: "1.0",
  session_id: context.session_id,
  video_id: context.video_id,
  stream_token: "t".repeat(32),
  expires_at: "2099-01-01T00:00:00Z",
  websocket_path: "/vision/v1/stream",
};

function createFrame(): EphemeralVideoFrame {
  return { width: 640, height: 480, close: () => undefined };
}

function expressionSample(): Record<string, unknown> {
  return {
    schema_version: "1.0",
    session_id: context.session_id,
    event_id: "expression-face-0004",
    sequence: context.sequence,
    frame_id: context.frame_id,
    captured_at_mono_ms: context.captured_at_mono_ms,
    video_id: context.video_id,
    video_time_ms: context.video_time_ms,
    playback_epoch: context.playback_epoch,
    producer_id: "mediapipe-face-landmarker",
    model_revision: "mediapipe-face-landmarker-v1",
    taxonomy_version: "blendshape-v1",
    face_detected: true,
    face_count: 1,
    scores: { smile: 0.7 },
    quality: 0.9,
    valid: true,
    confidence: 0.9,
    reason: null,
  };
}

type SocketEvent = { data?: unknown; code?: number; reason?: string };

class FakeSocket {
  readonly sent: Array<string | ArrayBuffer | Uint8Array> = [];
  readonly url: string;
  deferFrameResult = false;
  readyState = 0;
  binaryType = "";
  private readonly listeners = new Map<string, Set<(event: SocketEvent) => void>>();
  private pendingFrameResult: string | null = null;
  private pendingStopResponse: string | null = null;

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, listener: (event: SocketEvent) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: (event: SocketEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  send(data: string | ArrayBuffer | Uint8Array): void {
    this.sent.push(data);
    if (typeof data === "string") {
      const message = JSON.parse(data) as Record<string, unknown>;
      if (message.type === "hello") {
        this.emit("message", {
          data: JSON.stringify({
            type: "ready",
            protocol_version: "1.0",
            session_id: context.session_id,
            video_id: context.video_id,
            selected_frame_encoding: "image/jpeg",
            limits: {
              in_flight_limit: 1,
              max_frame_bytes: 524_288,
              max_fps: 4,
              decode_timeout_ms: 250,
              inference_timeout_ms: 500,
            },
          }),
        });
        return;
      }
      const action = message.action;
      const requestId = message.request_id;
      const valid = action !== "start_calibration" || false;
      const response: Record<string, unknown> = {
        type: "control_result",
        protocol_version: "1.0",
        request_id: requestId,
        action,
        valid,
        reason: valid ? null : "eye_not_connected",
      };
      if (action === "start_calibration") response.calibration_id = "calibration-unavailable-test";
      if (action === "stop_session" && this.deferFrameResult) {
        this.pendingStopResponse = JSON.stringify(response);
        return;
      }
      this.emit("message", { data: JSON.stringify(response) });
      if (action === "stop_session") queueMicrotask(() => this.close(1000, "normal"));
      return;
    }

    const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    const headerLength = new DataView(bytes.buffer, bytes.byteOffset).getUint32(4, false);
    const header = JSON.parse(
      new TextDecoder().decode(bytes.slice(8, 8 + headerLength)),
    ) as Record<string, unknown>;
    const frameContext = header;
    const result = JSON.stringify({
      type: "result",
      protocol_version: "1.0",
      session_id: frameContext.session_id,
      video_id: frameContext.video_id,
      frame_id: frameContext.frame_id,
      sequence: frameContext.sequence,
      captured_at_mono_ms: frameContext.captured_at_mono_ms,
      video_time_ms: frameContext.video_time_ms,
      playback_epoch: frameContext.playback_epoch,
      gaze_sample: null,
      gaze_reason: "eye_not_connected",
      expression_sample: expressionSample(),
      expression_reason: null,
    });
    if (this.deferFrameResult) {
      this.pendingFrameResult = result;
    } else {
      this.emit("message", { data: result });
    }
  }

  releaseDeferredFrame(): void {
    const frameResult = this.pendingFrameResult;
    this.pendingFrameResult = null;
    if (frameResult !== null) this.emit("message", { data: frameResult });

    const stopResponse = this.pendingStopResponse;
    this.pendingStopResponse = null;
    if (stopResponse !== null) {
      this.emit("message", { data: stopResponse });
      queueMicrotask(() => this.close(1000, "normal"));
    }
  }

  close(code = 1000, reason = "normal"): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.emit("close", { code, reason });
  }

  open(): void {
    this.readyState = 1;
    this.emit("open", {});
  }

  private emit(type: string, event: SocketEvent): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function createClient(
  socketRef: { current: FakeSocket | null },
  frameEncoder: (frame: EphemeralVideoFrame) => Promise<Uint8Array> = async () =>
    new Uint8Array([0xff, 0xd8, 0xff, 0xd9]),
): LocalVisionStreamClient {
  return new LocalVisionStreamClient({
    tokenProvider: async () => token,
    websocketUrl: "ws://127.0.0.1:8765/vision/v1/stream",
    frameEncoder: async (frame) => frameEncoder(frame),
    createWebSocket: (url) => {
      const socket = new FakeSocket(url);
      socketRef.current = socket;
      queueMicrotask(() => socket.open());
      return socket;
    },
  });
}

test("localhost Vision Stream이 handshake·control·binary frame을 처리하고 ExpressionSample을 전달한다", async () => {
  const socketRef = { current: null as FakeSocket | null };
  const client = createClient(socketRef);
  let receivedExpression: Record<string, unknown> | null = null;
  client.onExpressionSample((sample) => {
    receivedExpression = sample as unknown as Record<string, unknown>;
  });

  await client.startSession({ session_id: context.session_id, video_id: context.video_id });
  const health = await client.health();
  assert.deepEqual(health, {
    status: "ok",
    runtime: "mediapipe_gateway",
    session_active: true,
  });

  const calibration = await client.startCalibration({
    pattern_id: "five-point-v1",
    points: [[0.5, 0.5]],
  });
  assert.deepEqual(calibration, {
    calibration_id: "calibration-unavailable-test",
    valid: false,
    reason: "eye_not_connected",
  });
  await client.startInference();

  const result = await client.sendFrame(createFrame(), context);
  assert.deepEqual(result, {
    frame_id: context.frame_id,
    status: "accepted",
    reason: null,
  });
  assert.equal(
    (receivedExpression as Record<string, unknown> | null)?.frame_id,
    context.frame_id,
  );
  const sent = socketRef.current?.sent ?? [];
  const binary = sent.find((item) => typeof item !== "string") as Uint8Array | undefined;
  assert.ok(binary);
  assert.deepEqual(Array.from(binary.slice(0, 4)), [0x4d, 0x43, 0x4d, 0x31]);
  const headerLength = new DataView(binary.buffer, binary.byteOffset).getUint32(4, false);
  const header = JSON.parse(
    new TextDecoder().decode(binary.slice(8, 8 + headerLength)),
  ) as Record<string, unknown>;
  assert.deepEqual(header.camera_frame, {
    encoding: "image/jpeg",
    width_px: 640,
    height_px: 480,
    byte_length: 4,
  });
  assert.deepEqual(Array.from(binary.slice(8 + headerLength)), [0xff, 0xd8, 0xff, 0xd9]);

  await client.stopSession();
});

test("새 frame은 이전 binary 결과가 끝날 때까지 in_flight으로 drop된다", async () => {
  let releaseEncoding: (() => void) | undefined;
  const encodingReady = new Promise<void>((resolve) => {
    releaseEncoding = resolve;
  });
  const socketRef = { current: null as FakeSocket | null };
  const client = createClient(socketRef, async () => {
    await encodingReady;
    return new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
  });
  await client.startSession({ session_id: context.session_id, video_id: context.video_id });
  await client.startInference();

  const first = client.sendFrame(createFrame(), context);
  const second = await client.sendFrame(createFrame(), {
    ...context,
    frame_id: "frame-00000005",
    sequence: 5,
  });
  assert.deepEqual(second, {
    frame_id: "frame-00000005",
    status: "dropped",
    reason: "in_flight",
  });
  releaseEncoding?.();
  assert.equal((await first).status, "accepted");
  await client.stopSession();
});

test("전송된 frame의 호출 abort 뒤 늦은 result를 소비하고 stopSession을 정상 종료한다", async () => {
  const socketRef = { current: null as FakeSocket | null };
  const client = createClient(socketRef);
  let expressionCount = 0;
  client.onExpressionSample(() => {
    expressionCount += 1;
  });

  await client.startSession({ session_id: context.session_id, video_id: context.video_id });
  await client.startInference();
  const socket = socketRef.current;
  assert.ok(socket);
  socket.deferFrameResult = true;

  const abortController = new AbortController();
  const delivery = client.sendFrame(createFrame(), context, {
    signal: abortController.signal,
  });
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
  assert.ok(socket.sent.some((data) => typeof data !== "string"));

  abortController.abort();
  await assert.rejects(delivery, /Vision Stream frame delivery was cancelled/);

  const stopping = client.stopSession();
  socket.releaseDeferredFrame();
  await stopping;

  assert.equal(expressionCount, 0);
  assert.deepEqual(await client.health(), {
    status: "degraded",
    runtime: "mediapipe_gateway",
    session_active: false,
  });
});

test("Demo 3-C: Gateway 연결 중단은 in-flight frame을 accepted로 바꾸지 않는다", async () => {
  const socketRef = { current: null as FakeSocket | null };
  const client = createClient(socketRef);

  await client.startSession({ session_id: context.session_id, video_id: context.video_id });
  await client.startInference();
  const socket = socketRef.current;
  assert.ok(socket);
  socket.deferFrameResult = true;

  const delivery = client.sendFrame(createFrame(), context);
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
  socket.close(1011, "gateway_unavailable");

  await assert.rejects(delivery, /gateway_unavailable/);
  assert.deepEqual(await client.health(), {
    status: "degraded",
    runtime: "mediapipe_gateway",
    session_active: false,
  });
});

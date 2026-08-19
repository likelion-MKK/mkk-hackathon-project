import type {
  CalibrationPattern,
  CalibrationResult,
  ExpressionSample,
  GazeSample,
  GazeUnavailableSample,
  VisionHealth,
  VisionSessionContext,
} from "../../app/kiosk-types.ts";
import type { FrameContext } from "../../app/video-context.ts";
import type {
  ExpressionSampleListener,
  GazeSampleListener,
  Unsubscribe,
  VisionOperationOptions,
} from "./VisionClient.ts";
import type {
  FrameDeliveryOptions,
  FrameDeliveryResult,
  EphemeralVideoFrame,
  RemoteVisionClient,
  VisionDropReason,
  VisionFrameEncoder,
  VisionFrameEncoding,
  VisionStreamToken,
  VisionStreamTokenProvider,
} from "./RemoteVisionClient.ts";

const PROTOCOL_VERSION = "1.0" as const;
const MAX_METADATA_BYTES = 65_535;
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const DROP_REASONS = new Set<VisionDropReason>([
  "in_flight",
  "duplicate_frame",
  "out_of_order",
  "stale_epoch",
  "fps_limited",
  "frame_too_large",
  "decode_timeout",
  "inference_timeout",
  "server_overloaded",
  "session_closing",
]);
const CONTROL_ACTIONS = new Set<CalibrationAction>([
  "start_calibration",
  "start_inference",
  "stop_inference",
  "stop_session",
]);

type SocketEvent = {
  data?: unknown;
  code?: number;
  reason?: string;
};

type SocketListener = (event: SocketEvent) => void;
type GazeUnavailableListener = (sample: GazeUnavailableSample) => void;

type VisionSocket = {
  readonly readyState: number;
  binaryType: string;
  addEventListener(type: "open" | "message" | "error" | "close", listener: SocketListener): void;
  removeEventListener(type: "open" | "message" | "error" | "close", listener: SocketListener): void;
  send(data: string | ArrayBuffer | Uint8Array): void;
  close(code?: number, reason?: string): void;
};

type Deferred<T> = {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
  settled: boolean;
};

type ReadyMessage = {
  type: "ready";
  protocol_version: "1.0";
  session_id: string;
  video_id: string;
  selected_frame_encoding: VisionFrameEncoding;
  limits: {
    in_flight_limit: 1;
    max_frame_bytes: number;
    max_fps: number;
    decode_timeout_ms: number;
    inference_timeout_ms: number;
  };
};

type ControlResultMessage = {
  type: "control_result";
  protocol_version: "1.0";
  request_id: string;
  action: CalibrationAction;
  valid: boolean;
  reason: string | null;
  calibration_id?: string;
};

type CalibrationAction =
  | "start_calibration"
  | "start_inference"
  | "stop_inference"
  | "stop_session";

type PendingFrame = {
  context: FrameContext;
  deferred: Deferred<FrameDeliveryResult>;
  sent: boolean;
  callerAborted: boolean;
};

type LocalVisionStreamClientOptions = {
  tokenProvider: VisionStreamTokenProvider;
  websocketUrl?: string;
  frameEncoder: VisionFrameEncoder;
  createWebSocket?: (url: string) => VisionSocket;
  offeredFrameEncodings?: readonly VisionFrameEncoding[];
};

type FetchTokenProviderOptions = {
  endpoint: string;
  mode?: "backend" | "local";
  fetchImpl?: typeof fetch;
};

function createDeferred<T>(): Deferred<T> {
  let resolvePromise: (value: T) => void = () => undefined;
  let rejectPromise: (error: unknown) => void = () => undefined;
  const deferred: Deferred<T> = {
    promise: new Promise<T>((resolve, reject) => {
      resolvePromise = resolve;
      rejectPromise = reject;
    }),
    resolve: (value) => {
      if (deferred.settled) return;
      deferred.settled = true;
      resolvePromise(value);
    },
    reject: (error) => {
      if (deferred.settled) return;
      deferred.settled = true;
      rejectPromise(error);
    },
    settled: false,
  };
  return deferred;
}

function awaitWithAbort<T>(
  promise: Promise<T>,
  signal: AbortSignal | undefined,
  message: string,
): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(new Error(message));

  return new Promise<T>((resolve, reject) => {
    const abort = () => {
      cleanup();
      reject(new Error(message));
    };
    const cleanup = () => signal.removeEventListener("abort", abort);
    signal.addEventListener("abort", abort, { once: true });
    promise.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error: unknown) => {
        cleanup();
        reject(error);
      },
    );
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, message: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(message);
  return value;
}

function requireString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${name} is invalid.`);
  }
  return value;
}

function requireIdentifier(value: unknown, name: string): string {
  if (typeof value !== "string" || ID_PATTERN.test(value) === false) {
    throw new Error(`${name} is invalid.`);
  }
  return value;
}

function requireBoolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${name} is invalid.`);
  return value;
}

function requireNumber(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Error(`${name} is invalid.`);
  }
  return value;
}

function requireInteger(value: unknown, name: string): number {
  const number = requireNumber(value, name);
  if (!Number.isInteger(number)) throw new Error(`${name} is invalid.`);
  return number;
}

function requireNullableReason(value: unknown, name: string): string | null {
  if (value === null) return null;
  return requireString(value, name);
}

function sameFrameContext(value: Record<string, unknown>, context: FrameContext): boolean {
  return (
    value.session_id === context.session_id &&
    value.video_id === context.video_id &&
    value.frame_id === context.frame_id &&
    value.sequence === context.sequence &&
    value.captured_at_mono_ms === context.captured_at_mono_ms &&
    value.video_time_ms === context.video_time_ms &&
    value.playback_epoch === context.playback_epoch
  );
}

function validateToken(
  value: unknown,
  context: VisionSessionContext,
): VisionStreamToken {
  const token = requireRecord(value, "Vision Stream token response is invalid.");
  if (token.protocol_version !== PROTOCOL_VERSION) {
    throw new Error("Vision Stream token protocol version is unsupported.");
  }
  if (token.session_id !== context.session_id || token.video_id !== context.video_id) {
    throw new Error("Vision Stream token is bound to a different session.");
  }
  const streamToken = requireString(token.stream_token, "stream_token");
  if (streamToken.length < 32 || streamToken.length > 2_048) {
    throw new Error("stream_token is invalid.");
  }
  if (token.websocket_path !== "/vision/v1/stream") {
    throw new Error("Vision Stream websocket path is unsupported.");
  }
  requireString(token.expires_at, "expires_at");
  return token as unknown as VisionStreamToken;
}

function validateFrameReference(
  message: Record<string, unknown>,
  context: FrameContext,
): void {
  for (const [name, value] of [
    ["session_id", message.session_id],
    ["video_id", message.video_id],
    ["frame_id", message.frame_id],
  ] as const) {
    requireIdentifier(value, name);
  }
  requireInteger(message.sequence, "sequence");
  requireNumber(message.captured_at_mono_ms, "captured_at_mono_ms");
  requireInteger(message.video_time_ms, "video_time_ms");
  requireInteger(message.playback_epoch, "playback_epoch");
  if (!sameFrameContext(message, context)) {
    throw new Error("Vision Stream result context does not match the pending frame.");
  }
}

function encodeBinaryFrame(
  metadata: Record<string, unknown>,
  imageBytes: Uint8Array,
): Uint8Array {
  const header = new TextEncoder().encode(JSON.stringify(metadata));
  if (header.byteLength > MAX_METADATA_BYTES) {
    throw new Error("Vision Stream frame metadata is too large.");
  }
  const message = new Uint8Array(8 + header.byteLength + imageBytes.byteLength);
  message.set([0x4d, 0x43, 0x4d, 0x31], 0);
  new DataView(message.buffer).setUint32(4, header.byteLength, false);
  message.set(header, 8);
  message.set(imageBytes, 8 + header.byteLength);
  return message;
}

function defaultWebSocketFactory(url: string): VisionSocket {
  return new WebSocket(url) as unknown as VisionSocket;
}

function defaultWebsocketUrl(path: string): string {
  const location = globalThis.location;
  if (!location) throw new Error("Vision Stream websocket URL is not configured.");
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}${path}`;
}

function controlActionForPattern(pattern: CalibrationPattern): Record<string, unknown> {
  return {
    pattern_id: pattern.pattern_id,
    points: pattern.points,
  };
}

function toError(value: unknown, fallback: string): Error {
  return value instanceof Error ? value : new Error(fallback);
}

export function createFetchVisionStreamTokenProvider({
  endpoint,
  mode = "backend",
  fetchImpl = fetch,
}: FetchTokenProviderOptions): VisionStreamTokenProvider {
  if (!endpoint.trim()) throw new Error("Vision Stream token endpoint is required.");

  return async (context, { signal } = {}) => {
    const url = endpoint.replace("{session_id}", encodeURIComponent(context.session_id));
    const headers = new Headers({ Accept: "application/json" });
    const init: RequestInit = { method: "POST", headers, signal };
    if (mode === "local") {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(context);
    }
    const response = await fetchImpl(url, init);
    if (!response.ok) throw new Error(`Vision Stream token request failed (${response.status}).`);
    return validateToken(await response.json(), context);
  };
}

export class LocalVisionStreamClient implements RemoteVisionClient {
  private readonly tokenProvider: VisionStreamTokenProvider;
  private readonly websocketUrl: string | undefined;
  private readonly frameEncoder: VisionFrameEncoder;
  private readonly createWebSocket: (url: string) => VisionSocket;
  private readonly offeredFrameEncodings: readonly VisionFrameEncoding[];
  private readonly gazeListeners = new Set<GazeSampleListener>();
  private readonly gazeUnavailableListeners = new Set<GazeUnavailableListener>();
  private readonly expressionListeners = new Set<ExpressionSampleListener>();
  private readonly controlWaiters = new Map<string, Deferred<ControlResultMessage>>();
  private sessionContext: VisionSessionContext | null = null;
  private socket: VisionSocket | null = null;
  private socketHandlers: {
    open: SocketListener;
    message: SocketListener;
    error: SocketListener;
    close: SocketListener;
  } | null = null;
  private socketOpenWaiter: Deferred<void> | null = null;
  private readyWaiter: Deferred<ReadyMessage> | null = null;
  private ready: ReadyMessage | null = null;
  private pendingFrame: PendingFrame | null = null;
  private frameCaptureActive = false;
  private requestSequence = 0;
  private terminalError: Error | null = null;

  constructor({
    tokenProvider,
    websocketUrl,
    frameEncoder,
    createWebSocket = defaultWebSocketFactory,
    offeredFrameEncodings = ["image/jpeg", "image/webp"],
  }: LocalVisionStreamClientOptions) {
    if (offeredFrameEncodings.length === 0) {
      throw new Error("At least one Vision Stream frame encoding must be offered.");
    }
    this.tokenProvider = tokenProvider;
    this.websocketUrl = websocketUrl;
    this.frameEncoder = frameEncoder;
    this.createWebSocket = createWebSocket;
    this.offeredFrameEncodings = [...offeredFrameEncodings];
  }

  async startSession(
    context: VisionSessionContext,
    { signal }: VisionOperationOptions = {},
  ): Promise<void> {
    signal?.throwIfAborted();
    if (this.sessionContext || this.socket) {
      throw new Error("Vision Stream session is already active.");
    }

    const token = await this.tokenProvider(context, { signal });
    signal?.throwIfAborted();
    const validatedToken = validateToken(token, context);
    const websocketUrl = this.websocketUrl ?? defaultWebsocketUrl(validatedToken.websocket_path);
    const socket = this.createWebSocket(websocketUrl);
    socket.binaryType = "arraybuffer";
    this.sessionContext = { ...context };
    this.socket = socket;
    this.terminalError = null;
    this.attachSocket(socket);

    try {
      const openWaiter = createDeferred<void>();
      this.socketOpenWaiter = openWaiter;
      await awaitWithAbort(openWaiter.promise, signal, "Vision Stream connection was cancelled.");
      this.socketOpenWaiter = null;

      const readyWaiter = createDeferred<ReadyMessage>();
      this.readyWaiter = readyWaiter;
      socket.send(
        JSON.stringify({
          type: "hello",
          protocol_version: PROTOCOL_VERSION,
          session_id: context.session_id,
          video_id: context.video_id,
          stream_token: validatedToken.stream_token,
          offered_frame_encodings: this.offeredFrameEncodings,
        }),
      );
      this.ready = await awaitWithAbort(
        readyWaiter.promise,
        signal,
        "Vision Stream handshake was cancelled.",
      );
      this.readyWaiter = null;
    } catch (error: unknown) {
      this.closeSocket(1000, "normal");
      throw toError(error, "Vision Stream session could not start.");
    }
  }

  async startCalibration(pattern: CalibrationPattern): Promise<CalibrationResult> {
    // The Gateway keeps this control request pending until EyeTrax finishes.
    // Frames must be allowed through while that request is in flight.
    this.frameCaptureActive = true;
    let result: ControlResultMessage;
    try {
      result = await this.sendControl(
        "start_calibration",
        controlActionForPattern(pattern),
      );
    } catch (error) {
      this.frameCaptureActive = false;
      throw error;
    }
    if (!result.valid) this.frameCaptureActive = false;
    if (result.calibration_id === undefined) {
      this.frameCaptureActive = false;
      throw new Error("Vision Stream calibration response has no calibration_id.");
    }
    return {
      calibration_id: requireIdentifier(result.calibration_id, "calibration_id"),
      valid: result.valid,
      reason: result.reason,
    };
  }

  async startInference(): Promise<void> {
    const result = await this.sendControl("start_inference");
    if (!result.valid) throw new Error(result.reason ?? "Vision inference could not start.");
    this.frameCaptureActive = true;
  }

  onGazeSample(listener: GazeSampleListener): Unsubscribe {
    this.gazeListeners.add(listener);
    return () => this.gazeListeners.delete(listener);
  }

  onGazeUnavailable(listener: GazeUnavailableListener): Unsubscribe {
    this.gazeUnavailableListeners.add(listener);
    return () => this.gazeUnavailableListeners.delete(listener);
  }

  onExpressionSample(listener: ExpressionSampleListener): Unsubscribe {
    this.expressionListeners.add(listener);
    return () => this.expressionListeners.delete(listener);
  }

  async sendFrame(
    frame: EphemeralVideoFrame,
    context: FrameContext,
    { signal }: FrameDeliveryOptions = {},
  ): Promise<FrameDeliveryResult> {
    signal?.throwIfAborted();
    const sessionContext = this.requireSession();
    const ready = this.requireReady();
    if (!this.frameCaptureActive) throw new Error("Vision frame capture has not started.");
    if (
      context.session_id !== sessionContext.session_id ||
      context.video_id !== sessionContext.video_id
    ) {
      throw new Error("FrameContext does not match the active Vision session.");
    }
    if (frame.width <= 0 || frame.height <= 0) {
      throw new Error("Ephemeral frame dimensions must be positive.");
    }
    if (this.pendingFrame) {
      return { frame_id: context.frame_id, status: "dropped", reason: "in_flight" };
    }

    const pendingFrame: PendingFrame = {
      context,
      deferred: createDeferred<FrameDeliveryResult>(),
      sent: false,
      callerAborted: false,
    };
    this.pendingFrame = pendingFrame;
    try {
      const imageBytes = await this.frameEncoder(
        frame,
        ready.selected_frame_encoding,
        { signal },
      );
      signal?.throwIfAborted();
      if (imageBytes.byteLength > ready.limits.max_frame_bytes) {
        pendingFrame.deferred.resolve({
          frame_id: context.frame_id,
          status: "dropped",
          reason: "frame_too_large",
        });
      } else {
        const message = encodeBinaryFrame(
          {
            type: "frame",
            protocol_version: PROTOCOL_VERSION,
            session_id: context.session_id,
            video_id: context.video_id,
            frame_id: context.frame_id,
            sequence: context.sequence,
            captured_at_mono_ms: context.captured_at_mono_ms,
            video_time_ms: context.video_time_ms,
            playback_epoch: context.playback_epoch,
            layout: context.layout,
            camera_frame: {
              encoding: ready.selected_frame_encoding,
              width_px: frame.width,
              height_px: frame.height,
              byte_length: imageBytes.byteLength,
            },
          },
          imageBytes,
        );
        this.requireOpenSocket().send(message);
        pendingFrame.sent = true;
      }
      return await awaitWithAbort(
        pendingFrame.deferred.promise,
        signal,
        "Vision Stream frame delivery was cancelled.",
      );
    } catch (error: unknown) {
      if (signal?.aborted && pendingFrame.sent && !pendingFrame.deferred.settled) {
        // The caller has stopped waiting, but the gateway still owns the
        // in-flight frame until it returns a terminal result or drop.
        // Keep the pending frame so that a late response is consumed safely.
        pendingFrame.callerAborted = true;
      } else if (!pendingFrame.deferred.settled) {
        pendingFrame.deferred.reject(error);
      }
      throw toError(error, "Vision Stream frame delivery failed.");
    } finally {
      if (this.pendingFrame === pendingFrame && pendingFrame.deferred.settled) {
        this.pendingFrame = null;
      }
    }
  }

  async stopSession(): Promise<void> {
    if (!this.socket) {
      this.clearSessionState();
      return;
    }

    let failure: Error | null = null;
    if (this.socket.readyState === 1) {
      try {
        const result = await this.sendControl("stop_session");
        if (!result.valid) failure = new Error(result.reason ?? "Vision session close failed.");
      } catch (error: unknown) {
        failure = toError(error, "Vision session close failed.");
      }
    }
    this.closeSocket(1000, "normal");
    if (failure) throw failure;
  }

  async health(): Promise<VisionHealth> {
    return {
      status: this.socket?.readyState === 1 && this.ready ? "ok" : "degraded",
      runtime: "mediapipe_gateway",
      session_active: this.sessionContext !== null,
    };
  }

  private attachSocket(socket: VisionSocket): void {
    const handlers = {
      open: () => this.socketOpenWaiter?.resolve(undefined),
      message: (event: SocketEvent) => this.handleMessage(event.data),
      error: () => this.failTransport(new Error("Vision Stream websocket failed.")),
      close: (event: SocketEvent) => {
        const reason = typeof event.reason === "string" && event.reason
          ? event.reason
          : "Vision Stream websocket closed.";
        this.failTransport(new Error(reason));
      },
    } satisfies {
      open: SocketListener;
      message: SocketListener;
      error: SocketListener;
      close: SocketListener;
    };
    this.socketHandlers = handlers;
    socket.addEventListener("open", handlers.open);
    socket.addEventListener("message", handlers.message);
    socket.addEventListener("error", handlers.error);
    socket.addEventListener("close", handlers.close);
  }

  private detachSocket(): void {
    const socket = this.socket;
    const handlers = this.socketHandlers;
    if (!socket || !handlers) return;
    socket.removeEventListener("open", handlers.open);
    socket.removeEventListener("message", handlers.message);
    socket.removeEventListener("error", handlers.error);
    socket.removeEventListener("close", handlers.close);
    this.socketHandlers = null;
  }

  private closeSocket(code: number, reason: string): void {
    const socket = this.socket;
    this.detachSocket();
    this.socket = null;
    this.rejectWaiters(new Error("Vision Stream session closed."));
    this.clearSessionState();
    if (socket && (socket.readyState === 0 || socket.readyState === 1)) {
      try {
        socket.close(code, reason);
      } catch {
        // The browser may already have completed the close handshake.
      }
    }
  }

  private clearSessionState(): void {
    this.sessionContext = null;
    this.ready = null;
    this.frameCaptureActive = false;
    this.pendingFrame = null;
    this.socketOpenWaiter = null;
    this.readyWaiter = null;
    this.terminalError = null;
  }

  private failTransport(error: Error): void {
    this.terminalError = error;
    this.rejectWaiters(error);
    const socket = this.socket;
    this.detachSocket();
    this.socket = null;
    this.clearSessionState();
    if (socket && (socket.readyState === 0 || socket.readyState === 1)) {
      try {
        socket.close(1000, "normal");
      } catch {
        // The transport is already terminal; no retry or fallback sample is safe.
      }
    }
  }

  private rejectWaiters(error: Error): void {
    this.socketOpenWaiter?.reject(error);
    this.readyWaiter?.reject(error);
    this.socketOpenWaiter = null;
    this.readyWaiter = null;
    for (const waiter of this.controlWaiters.values()) waiter.reject(error);
    this.controlWaiters.clear();
    const pendingFrame = this.pendingFrame;
    this.pendingFrame = null;
    pendingFrame?.deferred.reject(error);
  }

  private handleMessage(data: unknown): void {
    let message: Record<string, unknown>;
    try {
      if (typeof data !== "string") throw new Error("Vision Stream message must be JSON text.");
      message = requireRecord(JSON.parse(data), "Vision Stream message must be an object.");
      this.handleJsonMessage(message);
    } catch (error: unknown) {
      this.failTransport(toError(error, "Vision Stream message is invalid."));
    }
  }

  private handleJsonMessage(message: Record<string, unknown>): void {
    if (message.protocol_version !== PROTOCOL_VERSION) {
      throw new Error("Vision Stream message protocol version is unsupported.");
    }
    switch (message.type) {
      case "ready":
        this.handleReady(message);
        return;
      case "control_result":
        this.handleControlResult(message);
        return;
      case "result":
        this.handleResult(message);
        return;
      case "drop":
        this.handleDrop(message);
        return;
      case "error":
        this.handleErrorMessage(message);
        return;
      case "close":
        this.failTransport(new Error(`Vision Stream closed: ${String(message.reason)}`));
        return;
      default:
        throw new Error("Vision Stream message type is unsupported.");
    }
  }

  private handleReady(message: Record<string, unknown>): void {
    if (!this.readyWaiter || !this.sessionContext) throw new Error("Unexpected Vision Stream ready message.");
    const sessionId = requireIdentifier(message.session_id, "session_id");
    const videoId = requireIdentifier(message.video_id, "video_id");
    if (sessionId !== this.sessionContext.session_id || videoId !== this.sessionContext.video_id) {
      throw new Error("Vision Stream ready context does not match the session.");
    }
    const selected = requireString(message.selected_frame_encoding, "selected_frame_encoding");
    if (selected !== "image/jpeg" && selected !== "image/webp") {
      throw new Error("Vision Stream selected encoding is unsupported.");
    }
    const limits = requireRecord(message.limits, "Vision Stream ready limits are invalid.");
    if (limits.in_flight_limit !== 1) throw new Error("Vision Stream in-flight limit must be one.");
    const ready: ReadyMessage = {
      type: "ready",
      protocol_version: PROTOCOL_VERSION,
      session_id: sessionId,
      video_id: videoId,
      selected_frame_encoding: selected,
      limits: {
        in_flight_limit: 1,
        max_frame_bytes: requireInteger(limits.max_frame_bytes, "max_frame_bytes"),
        max_fps: requireNumber(limits.max_fps, "max_fps"),
        decode_timeout_ms: requireInteger(limits.decode_timeout_ms, "decode_timeout_ms"),
        inference_timeout_ms: requireInteger(limits.inference_timeout_ms, "inference_timeout_ms"),
      },
    };
    this.readyWaiter.resolve(ready);
  }

  private handleControlResult(message: Record<string, unknown>): void {
    const requestId = requireIdentifier(message.request_id, "request_id");
    const waiter = this.controlWaiters.get(requestId);
    if (!waiter) throw new Error("Vision Stream control response is unexpected.");
    this.controlWaiters.delete(requestId);
    const actionValue = requireString(message.action, "action");
    if (!CONTROL_ACTIONS.has(actionValue as CalibrationAction)) {
      throw new Error("Vision Stream control action is invalid.");
    }
    const action = actionValue as CalibrationAction;
    const valid = requireBoolean(message.valid, "valid");
    const reason = requireNullableReason(message.reason, "reason");
    if (valid && reason !== null) throw new Error("Valid control result must have no reason.");
    if (!valid && reason === null) throw new Error("Invalid control result must have a reason.");
    const result: ControlResultMessage = {
      type: "control_result",
      protocol_version: PROTOCOL_VERSION,
      request_id: requestId,
      action,
      valid,
      reason,
    };
    if (message.calibration_id !== undefined) {
      result.calibration_id = requireIdentifier(message.calibration_id, "calibration_id");
    }
    waiter.resolve(result);
  }

  private handleResult(message: Record<string, unknown>): void {
    const pending = this.pendingFrame;
    if (!pending) throw new Error("Vision Stream result has no pending frame.");
    validateFrameReference(message, pending.context);
    const expression = message.expression_sample;
    if (expression !== null) {
      const sample = requireRecord(expression, "ExpressionSample is invalid.");
      validateFrameReference(sample, pending.context);
      if (!pending.callerAborted) {
        this.notifyExpression(sample as unknown as ExpressionSample);
      }
    } else if (typeof message.expression_reason !== "string") {
      throw new Error("ExpressionSample absence reason is invalid.");
    }
    const gaze = message.gaze_sample;
    if (gaze !== null) {
      const sample = requireRecord(gaze, "GazeSample is invalid.");
      validateFrameReference(sample, pending.context);
      if (!pending.callerAborted) {
        this.notifyGaze(sample as unknown as GazeSample);
      }
    } else {
      const reason = requireString(message.gaze_reason, "GazeSample absence reason is invalid.");
      if (!/^[a-z][a-z0-9_]{0,63}$/.test(reason)) {
        throw new Error("GazeSample absence reason is invalid.");
      }
      if (!pending.callerAborted) {
        this.notifyGazeUnavailable({
          session_id: pending.context.session_id,
          sequence: pending.context.sequence,
          frame_id: pending.context.frame_id,
          captured_at_mono_ms: pending.context.captured_at_mono_ms,
          video_id: pending.context.video_id,
          video_time_ms: pending.context.video_time_ms,
          playback_epoch: pending.context.playback_epoch,
          reason,
        });
      }
    }
    pending.deferred.resolve({
      frame_id: pending.context.frame_id,
      status: "accepted",
      reason: null,
    });
    this.pendingFrame = null;
  }

  private handleDrop(message: Record<string, unknown>): void {
    const pending = this.pendingFrame;
    if (!pending) throw new Error("Vision Stream drop has no pending frame.");
    validateFrameReference(message, pending.context);
    const reason = requireString(message.reason, "drop.reason");
    if (!DROP_REASONS.has(reason as VisionDropReason)) throw new Error("drop.reason is invalid.");
    requireBoolean(message.retryable, "drop.retryable");
    pending.deferred.resolve({
      frame_id: pending.context.frame_id,
      status: "dropped",
      reason: reason as VisionDropReason,
    });
    this.pendingFrame = null;
  }

  private handleErrorMessage(message: Record<string, unknown>): void {
    const error = new Error(`Vision Stream error: ${String(message.code)}`);
    const frame = message.frame;
    if (isRecord(frame) && this.pendingFrame && sameFrameContext(frame, this.pendingFrame.context)) {
      this.pendingFrame.deferred.reject(error);
      this.pendingFrame = null;
      return;
    }
    this.failTransport(error);
  }

  private notifyGaze(sample: GazeSample): void {
    for (const listener of this.gazeListeners) {
      try {
        listener(sample);
      } catch {
        // A UI listener must not break the transport receive loop.
      }
    }
  }

  private notifyGazeUnavailable(sample: GazeUnavailableSample): void {
    for (const listener of this.gazeUnavailableListeners) {
      try {
        listener(sample);
      } catch {
        // A UI listener must not break the transport receive loop.
      }
    }
  }

  private notifyExpression(sample: ExpressionSample): void {
    for (const listener of this.expressionListeners) {
      try {
        listener(sample);
      } catch {
        // A UI listener must not break the transport receive loop.
      }
    }
  }

  private requireSession(): VisionSessionContext {
    if (!this.sessionContext) throw new Error("Vision Stream session has not started.");
    return this.sessionContext;
  }

  private requireReady(): ReadyMessage {
    if (!this.ready) {
      if (this.terminalError) throw this.terminalError;
      throw new Error("Vision Stream handshake has not completed.");
    }
    return this.ready;
  }

  private requireOpenSocket(): VisionSocket {
    if (!this.socket || this.socket.readyState !== 1) {
      throw this.terminalError ?? new Error("Vision Stream websocket is not open.");
    }
    return this.socket;
  }

  private async sendControl(
    action: CalibrationAction,
    payload?: Record<string, unknown>,
  ): Promise<ControlResultMessage> {
    const socket = this.requireOpenSocket();
    this.requireReady();
    const requestId = `control-${++this.requestSequence}`;
    const waiter = createDeferred<ControlResultMessage>();
    this.controlWaiters.set(requestId, waiter);
    try {
      const message: Record<string, unknown> = {
        type: "control",
        protocol_version: PROTOCOL_VERSION,
        request_id: requestId,
        action,
      };
      if (payload) message.payload = payload;
      socket.send(JSON.stringify(message));
      return await waiter.promise;
    } catch (error: unknown) {
      this.controlWaiters.delete(requestId);
      throw toError(error, "Vision Stream control request failed.");
    }
  }
}

export type { LocalVisionStreamClientOptions, FetchTokenProviderOptions };

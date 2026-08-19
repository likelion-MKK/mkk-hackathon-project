import type { FrameContext } from "../app/video-context.ts";
import type { EphemeralVideoFrame } from "../clients/vision/RemoteVisionClient.ts";

export const CAMERA_VIDEO_CONSTRAINTS: MediaTrackConstraints = {
  width: { ideal: 1_280 },
  height: { ideal: 720 },
  frameRate: { ideal: 30, max: 30 },
  facingMode: "user",
};

export type CameraAccessErrorCode =
  | "permission_denied"
  | "camera_unavailable"
  | "camera_not_ready"
  | "capture_failed"
  | "unsupported"
  | "cancelled";

export class CameraAccessError extends Error {
  readonly code: CameraAccessErrorCode;

  constructor(code: CameraAccessErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "CameraAccessError";
    this.code = code;
  }
}

export type FrameCaptureOutcome = "delivered" | "dropped";
export type FrameContextFactory = () => FrameContext;
export type FrameConsumer = (
  frame: EphemeralVideoFrame,
  context: FrameContext,
  signal: AbortSignal,
) => Promise<void>;

type OpenOperation = {
  generation: number;
  controller: AbortController;
  stream: MediaStream | null;
  video: HTMLVideoElement | null;
};

type OpenTask = {
  operation: OpenOperation;
  promise: Promise<void>;
};

type CaptureOperation = {
  generation: number;
  controller: AbortController;
  stream: MediaStream;
  video: HTMLVideoElement;
  frame: EphemeralVideoFrame | null;
};

type FrameSourceDependencies = {
  mediaDevices?: Pick<MediaDevices, "getUserMedia"> | null;
  createVideoElement?: () => HTMLVideoElement;
  createFrame?: (video: HTMLVideoElement) => Promise<EphemeralVideoFrame>;
  readyTimeoutMs?: number;
};

function stopStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

function releaseVideo(video: HTMLVideoElement): void {
  video.pause();
  video.srcObject = null;
  video.removeAttribute("src");
  video.load();
}

function createCancelledError(message: string): CameraAccessError {
  return new CameraAccessError("cancelled", message);
}

function releaseOpenResources(operation: OpenOperation): void {
  const video = operation.video;
  const stream = operation.stream;
  operation.video = null;
  operation.stream = null;

  if (video) releaseVideo(video);
  if (stream) stopStream(stream);
}

function releaseCaptureFrame(operation: CaptureOperation): void {
  const frame = operation.frame;
  operation.frame = null;
  frame?.close();
}

function classifyCameraError(error: unknown): CameraAccessError {
  if (error instanceof CameraAccessError) return error;

  const errorName =
    typeof error === "object" && error !== null && "name" in error
      ? String(error.name)
      : "";

  if (errorName === "NotAllowedError" || errorName === "SecurityError") {
    return new CameraAccessError(
      "permission_denied",
      "Camera permission was denied.",
      { cause: error },
    );
  }

  if (
    errorName === "NotFoundError" ||
    errorName === "NotReadableError" ||
    errorName === "OverconstrainedError"
  ) {
    return new CameraAccessError(
      "camera_unavailable",
      "A usable camera is not available.",
      { cause: error },
    );
  }

  return new CameraAccessError("camera_unavailable", "Camera startup failed.", {
    cause: error,
  });
}

function waitForAbortablePromise<T>(
  promise: Promise<T>,
  signal: AbortSignal,
  message: string,
): Promise<T> {
  if (signal.aborted) return Promise.reject(createCancelledError(message));

  return new Promise<T>((resolve, reject) => {
    const handleAbort = () => {
      cleanup();
      reject(createCancelledError(message));
    };
    const cleanup = () => signal.removeEventListener("abort", handleAbort);

    signal.addEventListener("abort", handleAbort, { once: true });
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

function waitForVideoData(
  video: HTMLVideoElement,
  timeoutMs: number,
  signal: AbortSignal,
): Promise<void> {
  if (video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) {
    return Promise.resolve();
  }

  if (signal.aborted) {
    return Promise.reject(createCancelledError("Camera startup was cancelled."));
  }

  return new Promise<void>((resolve, reject) => {
    const timeoutId = globalThis.setTimeout(() => {
      cleanup();
      reject(
        new CameraAccessError(
          "camera_not_ready",
          "Camera stream did not become ready in time.",
        ),
      );
    }, timeoutMs);

    const handleReady = () => {
      if (video.videoWidth <= 0 || video.videoHeight <= 0) return;
      cleanup();
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new CameraAccessError("camera_not_ready", "Camera video failed to load."));
    };
    const handleAbort = () => {
      cleanup();
      reject(createCancelledError("Camera startup was cancelled."));
    };
    const cleanup = () => {
      globalThis.clearTimeout(timeoutId);
      video.removeEventListener("loadeddata", handleReady);
      video.removeEventListener("canplay", handleReady);
      video.removeEventListener("error", handleError);
      signal.removeEventListener("abort", handleAbort);
    };

    video.addEventListener("loadeddata", handleReady);
    video.addEventListener("canplay", handleReady);
    video.addEventListener("error", handleError);
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

export class FrameSource {
  private readonly mediaDevices: Pick<MediaDevices, "getUserMedia"> | null;
  private readonly createVideoElement: () => HTMLVideoElement;
  private readonly createFrame: (video: HTMLVideoElement) => Promise<EphemeralVideoFrame>;
  private readonly readyTimeoutMs: number;
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private openTask: OpenTask | null = null;
  private lifecycleGeneration = 0;
  private captureOperation: CaptureOperation | null = null;

  constructor({
    mediaDevices = globalThis.navigator?.mediaDevices ?? null,
    createVideoElement = () => document.createElement("video"),
    createFrame = async (video) => {
      const bitmap = await createImageBitmap(video);
      return {
        width: bitmap.width,
        height: bitmap.height,
        source: bitmap,
        close: () => bitmap.close(),
      };
    },
    readyTimeoutMs = 5_000,
  }: FrameSourceDependencies = {}) {
    this.mediaDevices = mediaDevices;
    this.createVideoElement = createVideoElement;
    this.createFrame = createFrame;
    this.readyTimeoutMs = readyTimeoutMs;
  }

  isOpen(): boolean {
    return this.stream !== null && this.video !== null;
  }

  async open(): Promise<void> {
    if (this.isOpen()) return;
    if (this.openTask && !this.openTask.operation.controller.signal.aborted) {
      return this.openTask.promise;
    }
    if (!this.mediaDevices) {
      throw new CameraAccessError(
        "unsupported",
        "Camera access is unavailable in this browser context.",
      );
    }

    const operation: OpenOperation = {
      generation: this.lifecycleGeneration,
      controller: new AbortController(),
      stream: null,
      video: null,
    };
    const pendingOpen = this.openCamera(operation);
    const task = { operation, promise: pendingOpen };
    this.openTask = task;

    try {
      await pendingOpen;
      this.assertOpenActive(operation);
    } finally {
      if (this.openTask === task) this.openTask = null;
    }
  }

  stop(): void {
    this.lifecycleGeneration += 1;

    const openTask = this.openTask;
    this.openTask = null;
    if (openTask) {
      openTask.operation.controller.abort();
      releaseOpenResources(openTask.operation);
    }

    const captureOperation = this.captureOperation;
    this.captureOperation = null;
    if (captureOperation) {
      captureOperation.controller.abort();
      releaseCaptureFrame(captureOperation);
    }

    const video = this.video;
    const stream = this.stream;
    this.video = null;
    this.stream = null;

    if (video) releaseVideo(video);
    if (stream) stopStream(stream);
  }

  async capture(
    contextOrFactory: FrameContext | FrameContextFactory,
    consume: FrameConsumer,
  ): Promise<FrameCaptureOutcome> {
    if (this.captureOperation) return "dropped";

    const video = this.video;
    const stream = this.stream;
    const generation = this.lifecycleGeneration;
    if (!video || !stream || video.readyState < 2) {
      throw new CameraAccessError("camera_not_ready", "Camera is not ready to capture.");
    }

    const operation: CaptureOperation = {
      generation,
      controller: new AbortController(),
      stream,
      video,
      frame: null,
    };
    this.captureOperation = operation;

    try {
      // Snapshot lookbook time/layout immediately before initiating camera-frame
      // capture. The same immutable object follows this frame through inference;
      // response-time video.currentTime is never read again.
      const context =
        typeof contextOrFactory === "function" ? contextOrFactory() : contextOrFactory;
      operation.frame = await this.createFrame(video);
      this.assertCaptureActive(operation);

      await consume(operation.frame, context, operation.controller.signal);
      this.assertCaptureActive(operation);
      return "delivered";
    } catch (error: unknown) {
      if (
        operation.controller.signal.aborted ||
        operation.generation !== this.lifecycleGeneration ||
        this.captureOperation !== operation
      ) {
        throw createCancelledError("Camera capture was cancelled.");
      }
      if (error instanceof CameraAccessError) throw error;
      throw new CameraAccessError("capture_failed", "Camera frame capture failed.", {
        cause: error,
      });
    } finally {
      releaseCaptureFrame(operation);
      if (this.captureOperation === operation) this.captureOperation = null;
    }
  }

  private async openCamera(operation: OpenOperation): Promise<void> {
    try {
      const stream = await this.mediaDevices!.getUserMedia({
        audio: false,
        video: CAMERA_VIDEO_CONSTRAINTS,
      });
      operation.stream = stream;

      this.assertOpenActive(operation);
      if (stream.getVideoTracks().length === 0) {
        throw new CameraAccessError(
          "camera_unavailable",
          "Camera stream does not contain a video track.",
        );
      }

      const video = this.createVideoElement();
      operation.video = video;
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      await waitForAbortablePromise(
        video.play(),
        operation.controller.signal,
        "Camera startup was cancelled.",
      );
      await waitForVideoData(video, this.readyTimeoutMs, operation.controller.signal);

      this.assertOpenActive(operation);

      operation.stream = null;
      operation.video = null;
      this.stream = stream;
      this.video = video;
    } catch (error: unknown) {
      const wasCancelled =
        operation.controller.signal.aborted ||
        operation.generation !== this.lifecycleGeneration;
      releaseOpenResources(operation);
      if (wasCancelled) throw createCancelledError("Camera startup was cancelled.");
      throw classifyCameraError(error);
    }
  }

  private assertOpenActive(operation: OpenOperation): void {
    if (
      operation.controller.signal.aborted ||
      operation.generation !== this.lifecycleGeneration
    ) {
      throw createCancelledError("Camera startup was cancelled.");
    }
  }

  private assertCaptureActive(operation: CaptureOperation): void {
    if (
      operation.controller.signal.aborted ||
      operation.generation !== this.lifecycleGeneration ||
      this.captureOperation !== operation ||
      this.stream !== operation.stream ||
      this.video !== operation.video
    ) {
      throw createCancelledError("Camera capture was cancelled.");
    }
  }
}

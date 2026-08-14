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
export type FrameConsumer = (
  frame: EphemeralVideoFrame,
  context: FrameContext,
) => Promise<void>;

type FrameSourceDependencies = {
  mediaDevices?: Pick<MediaDevices, "getUserMedia"> | null;
  createVideoElement?: () => HTMLVideoElement;
  createFrame?: (video: HTMLVideoElement) => Promise<EphemeralVideoFrame>;
  readyTimeoutMs?: number;
};

function stopStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
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

function waitForVideoData(video: HTMLVideoElement, timeoutMs: number): Promise<void> {
  if (video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) {
    return Promise.resolve();
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
    const cleanup = () => {
      globalThis.clearTimeout(timeoutId);
      video.removeEventListener("loadeddata", handleReady);
      video.removeEventListener("canplay", handleReady);
      video.removeEventListener("error", handleError);
    };

    video.addEventListener("loadeddata", handleReady);
    video.addEventListener("canplay", handleReady);
    video.addEventListener("error", handleError);
  });
}

export class FrameSource {
  private readonly mediaDevices: Pick<MediaDevices, "getUserMedia"> | null;
  private readonly createVideoElement: () => HTMLVideoElement;
  private readonly createFrame: (video: HTMLVideoElement) => Promise<EphemeralVideoFrame>;
  private readonly readyTimeoutMs: number;
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private openPromise: Promise<void> | null = null;
  private lifecycleGeneration = 0;
  private captureInFlight = false;

  constructor({
    mediaDevices = globalThis.navigator?.mediaDevices ?? null,
    createVideoElement = () => document.createElement("video"),
    createFrame = (video) => createImageBitmap(video),
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
    if (this.openPromise) return this.openPromise;
    if (!this.mediaDevices) {
      throw new CameraAccessError(
        "unsupported",
        "Camera access is unavailable in this browser context.",
      );
    }

    const generation = this.lifecycleGeneration;
    const pendingOpen = this.openCamera(generation);
    this.openPromise = pendingOpen;

    try {
      await pendingOpen;
    } finally {
      if (this.openPromise === pendingOpen) this.openPromise = null;
    }
  }

  stop(): void {
    this.lifecycleGeneration += 1;
    this.captureInFlight = false;

    const video = this.video;
    const stream = this.stream;
    this.video = null;
    this.stream = null;

    if (video) {
      video.pause();
      video.srcObject = null;
      video.removeAttribute("src");
      video.load();
    }
    if (stream) stopStream(stream);
  }

  async capture(
    context: FrameContext,
    consume: FrameConsumer,
  ): Promise<FrameCaptureOutcome> {
    if (this.captureInFlight) return "dropped";

    const video = this.video;
    const generation = this.lifecycleGeneration;
    if (!video || !this.stream || video.readyState < 2) {
      throw new CameraAccessError("camera_not_ready", "Camera is not ready to capture.");
    }

    this.captureInFlight = true;
    let frame: EphemeralVideoFrame | null = null;

    try {
      frame = await this.createFrame(video);
      if (generation !== this.lifecycleGeneration) {
        throw new CameraAccessError("cancelled", "Camera capture was cancelled.");
      }

      await consume(frame, context);
      return "delivered";
    } catch (error: unknown) {
      if (error instanceof CameraAccessError) throw error;
      throw new CameraAccessError("capture_failed", "Camera frame capture failed.", {
        cause: error,
      });
    } finally {
      frame?.close();
      if (generation === this.lifecycleGeneration) this.captureInFlight = false;
    }
  }

  private async openCamera(generation: number): Promise<void> {
    let stream: MediaStream | null = null;
    let video: HTMLVideoElement | null = null;

    try {
      stream = await this.mediaDevices!.getUserMedia({
        audio: false,
        video: CAMERA_VIDEO_CONSTRAINTS,
      });

      if (generation !== this.lifecycleGeneration) {
        throw new CameraAccessError("cancelled", "Camera startup was cancelled.");
      }
      if (stream.getVideoTracks().length === 0) {
        throw new CameraAccessError(
          "camera_unavailable",
          "Camera stream does not contain a video track.",
        );
      }

      video = this.createVideoElement();
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      await video.play();
      await waitForVideoData(video, this.readyTimeoutMs);

      if (generation !== this.lifecycleGeneration) {
        throw new CameraAccessError("cancelled", "Camera startup was cancelled.");
      }

      this.stream = stream;
      this.video = video;
    } catch (error: unknown) {
      if (video) {
        video.pause();
        video.srcObject = null;
      }
      if (stream) stopStream(stream);
      throw classifyCameraError(error);
    }
  }
}

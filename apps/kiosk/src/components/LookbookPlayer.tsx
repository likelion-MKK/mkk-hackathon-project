import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  createProductAttentionEvent,
  mapGazeToVideoPoint,
} from "../app/reaction-batch.ts";
import type { GazeSample, LookbookManifest } from "../app/kiosk-types.ts";
import {
  calculateContainedVideoLayout,
  createFrameContext,
  type FrameContext,
  type PixelRect,
} from "../app/video-context.ts";

type MediaState = "missing" | "loading" | "ready" | "error";
export type CameraDisplayState =
  | "idle"
  | "requesting"
  | "ready"
  | "denied"
  | "error";

export const ANALYSIS_SAMPLE_INTERVAL_MS = 250;

type LookbookPlayerProps = {
  cameraState: CameraDisplayState;
  categoryLabel: string;
  chrome: ReactNode;
  debugEnabled: boolean;
  debugGazeLayout: FrameContext["layout"] | null;
  debugGazeSample: GazeSample | null;
  manifest: LookbookManifest;
  posterUrl: string;
  sessionId: string;
  videoId: string;
  videoUrl: string;
  onCameraRetry: () => Promise<void>;
  onComplete: () => Promise<void>;
  onFrameCapture: (context: FrameContext) => Promise<void>;
  onHome: () => void;
  onPlaybackUnavailable: () => void;
};

function formatMediaTime(timeMs: number): string {
  const safeTimeMs = Number.isFinite(timeMs) ? Math.max(0, timeMs) : 0;
  const totalSeconds = Math.floor(safeTimeMs / 1_000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function toPixelRect(rect: DOMRect): PixelRect {
  return {
    x_px: rect.left,
    y_px: rect.top,
    width_px: rect.width,
    height_px: rect.height,
  };
}

function toPolygonClipPath(points: [number, number][]): string {
  return `polygon(${points.map(([x, y]) => `${x * 100}% ${y * 100}%`).join(", ")})`;
}

function getPolygonCenter(points: [number, number][]): [number, number] {
  const total = points.reduce(
    ([xTotal, yTotal], [x, y]) => [xTotal + x, yTotal + y],
    [0, 0],
  );

  return [total[0] / points.length, total[1] / points.length];
}

export function LookbookPlayer({
  cameraState,
  categoryLabel,
  chrome,
  debugEnabled,
  debugGazeLayout,
  debugGazeSample,
  manifest,
  posterUrl,
  sessionId,
  videoId,
  videoUrl,
  onCameraRetry,
  onComplete,
  onFrameCapture,
  onHome,
  onPlaybackUnavailable,
}: LookbookPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLElement>(null);
  const playbackEpochRef = useRef(0);
  const frameSequenceRef = useRef(0);
  const didCompleteRef = useRef(false);
  const [mediaState, setMediaState] = useState<MediaState>(
    videoUrl ? "loading" : "missing",
  );
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const [durationMs, setDurationMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackEpoch, setPlaybackEpoch] = useState(0);
  const [contextPreview, setContextPreview] = useState<FrameContext | null>(null);
  const [stageRect, setStageRect] = useState<PixelRect | null>(null);

  const incrementPlaybackEpoch = () => {
    playbackEpochRef.current += 1;
    setPlaybackEpoch(playbackEpochRef.current);
  };

  const readFrameContext = useCallback((sequence: number, frameId: string) => {
    const video = videoRef.current;

    if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) return null;

    const layout = calculateContainedVideoLayout({
      viewport_width_px: document.documentElement.clientWidth,
      viewport_height_px: document.documentElement.clientHeight,
      source_width_px: video.videoWidth,
      source_height_px: video.videoHeight,
      element_rect: toPixelRect(video.getBoundingClientRect()),
    });
    return createFrameContext({
      session_id: sessionId,
      sequence,
      frame_id: frameId,
      captured_at_mono_ms: performance.now(),
      video_id: videoId,
      video_time_seconds: video.currentTime,
      playback_epoch: playbackEpochRef.current,
      layout,
    });
  }, [sessionId, videoId]);

  const updateContextPreview = useCallback(() => {
    const context = readFrameContext(0, "frame-context-preview");
    if (!context) return;

    setCurrentTimeMs(context.video_time_ms);
    setContextPreview(context);
  }, [readFrameContext]);

  const updateStageRect = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return;

    setStageRect(toPixelRect(stage.getBoundingClientRect()));
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const resizeObserver = new ResizeObserver(updateContextPreview);
    resizeObserver.observe(video);
    window.addEventListener("resize", updateContextPreview);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", updateContextPreview);
    };
  }, [updateContextPreview]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;

    const resizeObserver = new ResizeObserver(updateStageRect);
    resizeObserver.observe(stage);
    updateStageRect();
    window.addEventListener("resize", updateStageRect);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", updateStageRect);
    };
  }, [updateStageRect]);

  useEffect(() => {
    if (videoUrl) return;
    onPlaybackUnavailable();
  }, [onPlaybackUnavailable, videoUrl]);

  useEffect(() => {
    if (cameraState === "ready") return;
    videoRef.current?.pause();
  }, [cameraState]);

  useEffect(() => {
    if (mediaState !== "ready" || cameraState !== "ready" || !isPlaying) return;

    let isActive = true;
    const captureCurrentFrame = () => {
      if (!isActive) return;

      const sequence = frameSequenceRef.current;
      const context = readFrameContext(
        sequence,
        `frame-${String(sequence).padStart(8, "0")}`,
      );
      if (!context) return;

      frameSequenceRef.current += 1;
      void onFrameCapture(context).catch(() => undefined);
    };

    captureCurrentFrame();
    const captureTimer = window.setInterval(
      captureCurrentFrame,
      ANALYSIS_SAMPLE_INTERVAL_MS,
    );

    return () => {
      isActive = false;
      window.clearInterval(captureTimer);
    };
  }, [cameraState, isPlaying, mediaState, onFrameCapture, readFrameContext]);

  const handleLoadedMetadata = () => {
    const video = videoRef.current;
    if (!video) return;

    setDurationMs(Number.isFinite(video.duration) ? Math.floor(video.duration * 1_000) : 0);
    setMediaState("ready");
    updateContextPreview();
  };

  const handleSeek = (nextTimeMs: number) => {
    const video = videoRef.current;
    if (!video || durationMs <= 0) return;

    incrementPlaybackEpoch();
    video.currentTime = Math.min(Math.max(nextTimeMs, 0), durationMs) / 1_000;
    setCurrentTimeMs(nextTimeMs);
  };

  const togglePlayback = async () => {
    const video = videoRef.current;
    if (!video || mediaState !== "ready" || cameraState !== "ready") return;

    if (!video.paused) {
      video.pause();
      return;
    }

    if (video.ended) {
      incrementPlaybackEpoch();
      video.currentTime = 0;
    }

    try {
      await video.play();
    } catch {
      setMediaState("error");
      setIsPlaying(false);
      onPlaybackUnavailable();
    }
  };

  const handleMediaError = () => {
    videoRef.current?.pause();
    setMediaState("error");
    setIsPlaying(false);
    onPlaybackUnavailable();
  };

  const handleEnded = () => {
    setIsPlaying(false);
    updateContextPreview();

    if (didCompleteRef.current) return;
    didCompleteRef.current = true;
    void onComplete();
  };

  const contentRect = contextPreview?.layout.content_rect;
  const activeExposures = useMemo(
    () =>
      manifest.exposures.filter(
        (exposure) =>
          exposure.start_ms <= currentTimeMs && currentTimeMs < exposure.end_ms,
      ),
    [currentTimeMs, manifest.exposures],
  );
  const debugVideoPoint = useMemo(
    () =>
      debugGazeSample && debugGazeLayout
        ? mapGazeToVideoPoint(debugGazeSample, debugGazeLayout)
        : null,
    [debugGazeLayout, debugGazeSample],
  );
  const debugAttention = useMemo(() => {
    if (!debugGazeSample || !debugVideoPoint) return null;

    try {
      return createProductAttentionEvent(
        debugGazeSample,
        manifest,
        debugGazeSample.sequence,
        debugVideoPoint,
      );
    } catch {
      return null;
    }
  }, [debugGazeSample, debugVideoPoint, manifest]);
  const contentStyle =
    contentRect && stageRect
      ? ({
          left: contentRect.x_px - stageRect.x_px,
          top: contentRect.y_px - stageRect.y_px,
          width: contentRect.width_px,
          height: contentRect.height_px,
        } satisfies CSSProperties)
      : null;
  const debugStatus = !debugGazeSample
    ? "WAITING FOR GAZE"
    : !debugGazeSample.valid
      ? `INVALID / ${debugGazeSample.reason}`
      : !debugVideoPoint
        ? "WAITING FOR CAPTURE LAYOUT"
        : debugVideoPoint.outside_video
          ? "OUTSIDE VIDEO"
          : debugAttention && debugAttention.candidates.length > 0
            ? `AOI HIT / ${debugAttention.candidates.map((candidate) => candidate.product_id).join(", ")}`
            : "VALID / NO AOI HIT";
  const mediaMessage =
    mediaState === "missing"
      ? "룩북 영상 파일을 연결해주세요."
      : mediaState === "error"
        ? "룩북 영상을 불러오지 못했습니다."
        : mediaState === "loading"
          ? "룩북 영상을 준비하고 있습니다."
          : null;

  return (
    <main className="store-screen lookbook-screen screen-enter" aria-labelledby="lookbook-title">
      {chrome}

      <section className="lookbook-stage" ref={stageRef}>
        <video
          className="lookbook-video"
          ref={videoRef}
          src={videoUrl || undefined}
          poster={posterUrl}
          preload="metadata"
          playsInline
          onLoadedMetadata={handleLoadedMetadata}
          onTimeUpdate={updateContextPreview}
          onSeeked={updateContextPreview}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={handleEnded}
          onError={handleMediaError}
        />

        <div className="lookbook-stage__shade" aria-hidden="true" />

        {debugEnabled && (
          <>
            {contentStyle && (
              <div className="lookbook-debug-canvas" style={contentStyle} aria-hidden="true">
                {activeExposures.map((exposure) => {
                  const [centerX, centerY] = getPolygonCenter(exposure.shape.points);

                  return (
                    <div className="lookbook-aoi-region" key={exposure.exposure_id}>
                      <span
                        className="lookbook-aoi-region__fill"
                        style={{ clipPath: toPolygonClipPath(exposure.shape.points) }}
                      />
                      <span
                        className="lookbook-aoi-region__label"
                        style={{ left: `${centerX * 100}%`, top: `${centerY * 100}%` }}
                      >
                        {exposure.product_id}
                      </span>
                    </div>
                  );
                })}

                {debugVideoPoint?.valid && !debugVideoPoint.outside_video && (
                  <span
                    className="lookbook-gaze-point"
                    style={{
                      left: `${debugVideoPoint.video_x_norm * 100}%`,
                      top: `${debugVideoPoint.video_y_norm * 100}%`,
                    }}
                  />
                )}
              </div>
            )}

            <aside className="lookbook-debug-panel" aria-label="AOI debug overlay" role="status">
              <div className="lookbook-debug-panel__topline">
                <span>AOI MAP</span>
                <span>DEV ONLY</span>
              </div>
              <strong>{debugStatus}</strong>
              <dl>
                <div>
                  <dt>TIME</dt>
                  <dd>{Math.round(currentTimeMs)} MS</dd>
                </div>
                <div>
                  <dt>GAZE</dt>
                  <dd>
                    {debugVideoPoint?.valid && !debugVideoPoint.outside_video
                      ? `${debugVideoPoint.video_x_norm.toFixed(2)}, ${debugVideoPoint.video_y_norm.toFixed(2)}`
                      : "NO VIDEO POINT"}
                  </dd>
                </div>
                <div>
                  <dt>EXPOSURES</dt>
                  <dd>{activeExposures.length} ACTIVE</dd>
                </div>
              </dl>
            </aside>
          </>
        )}

        <div className="lookbook-stage__heading">
          <p className="section-label">AI LOOKBOOK · {categoryLabel}</p>
          <h1 id="lookbook-title">당신의 시선이 머무는 순간</h1>
          <span>{videoId}</span>
        </div>

        <span className={`lookbook-camera-status is-${cameraState}`} role="status">
          {cameraState === "ready"
            ? "CAMERA ACTIVE · IN-PROCESS REPLAY"
            : cameraState === "requesting"
              ? "CAMERA CONNECTING"
              : "CAMERA OFF"}
        </span>

        {(mediaMessage || cameraState !== "ready") && (
          <div className="lookbook-media-message" role="status">
            <strong>
              {mediaMessage ??
                (cameraState === "requesting"
                  ? "카메라 연결을 확인하고 있습니다."
                  : cameraState === "denied"
                    ? "카메라 권한이 필요합니다."
                    : "카메라를 시작하지 못했습니다.")}
            </strong>
            <span>
              {mediaMessage
                ? "개발 환경의 VITE_LOOKBOOK_VIDEO_URL을 확인해주세요."
                : "승인 전 local/in-process 분석 경계에서만 frame을 일시 처리합니다."}
            </span>
            {!mediaMessage &&
              cameraState !== "requesting" &&
              cameraState !== "ready" && (
                <button
                  className="lookbook-camera-retry"
                  type="button"
                  onClick={() => void onCameraRetry()}
                >
                  카메라 다시 연결
                </button>
              )}
          </div>
        )}

        <div className="lookbook-controls">
          <button
            className="lookbook-play-button"
            type="button"
            onClick={() => void togglePlayback()}
            disabled={mediaState !== "ready" || cameraState !== "ready"}
            aria-label={isPlaying ? "룩북 일시정지" : "룩북 재생"}
          >
            <span aria-hidden="true">{isPlaying ? "Ⅱ" : "▶"}</span>
            {isPlaying ? "일시정지" : "재생"}
          </button>

          <div className="lookbook-timeline">
            <div className="lookbook-timeline__meta">
              <span>
                {formatMediaTime(currentTimeMs)} / {formatMediaTime(durationMs)}
              </span>
              <span>
                FRAME CONTEXT · {currentTimeMs}MS · EPOCH {playbackEpoch}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max={Math.max(durationMs, 0)}
              step="1"
              value={Math.min(currentTimeMs, durationMs)}
              onChange={(event) => handleSeek(Number(event.currentTarget.value))}
              disabled={mediaState !== "ready" || durationMs <= 0}
              aria-label="룩북 재생 위치"
            />
            <span className="lookbook-layout-status">
              {contentRect
                ? `VIDEO LAYOUT · ${Math.round(contentRect.width_px)} × ${Math.round(contentRect.height_px)} PX`
                : "VIDEO LAYOUT · WAITING"}
            </span>
          </div>

          <button className="lookbook-exit-button" type="button" onClick={onHome}>
            처음으로
          </button>
        </div>
      </section>
    </main>
  );
}

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
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

const D3_FAKE_FRAME_SAMPLE_INTERVAL_MS = 250;

type LookbookPlayerProps = {
  cameraState: CameraDisplayState;
  categoryLabel: string;
  chrome: ReactNode;
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

export function LookbookPlayer({
  cameraState,
  categoryLabel,
  chrome,
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
      D3_FAKE_FRAME_SAMPLE_INTERVAL_MS,
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
  const mediaMessage =
    mediaState === "missing"
      ? "임시 룩북 영상 파일을 연결해주세요."
      : mediaState === "error"
        ? "임시 룩북 영상을 불러오지 못했습니다."
        : mediaState === "loading"
          ? "임시 룩북 영상을 준비하고 있습니다."
          : null;

  return (
    <main className="store-screen lookbook-screen screen-enter" aria-labelledby="lookbook-title">
      {chrome}

      <section className="lookbook-stage">
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

        <div className="lookbook-stage__heading">
          <p className="section-label">AI LOOKBOOK · {categoryLabel}</p>
          <h1 id="lookbook-title">당신의 시선이 머무는 순간</h1>
          <span>{videoId}</span>
        </div>

        <span className={`lookbook-camera-status is-${cameraState}`} role="status">
          {cameraState === "ready"
            ? "CAMERA ACTIVE · LOCAL FAKE"
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
                : "원격 전송 없이 현재 브라우저의 카메라와 fake 경계만 사용합니다."}
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

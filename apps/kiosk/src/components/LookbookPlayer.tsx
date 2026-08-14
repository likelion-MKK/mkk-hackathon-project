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

type LookbookPlayerProps = {
  categoryLabel: string;
  chrome: ReactNode;
  posterUrl: string;
  sessionId: string;
  videoId: string;
  videoUrl: string;
  onComplete: () => Promise<void>;
  onHome: () => void;
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
  categoryLabel,
  chrome,
  posterUrl,
  sessionId,
  videoId,
  videoUrl,
  onComplete,
  onHome,
}: LookbookPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playbackEpochRef = useRef(0);
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

  const updateContextPreview = useCallback(() => {
    const video = videoRef.current;

    if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) return;

    const layout = calculateContainedVideoLayout({
      viewport_width_px: document.documentElement.clientWidth,
      viewport_height_px: document.documentElement.clientHeight,
      source_width_px: video.videoWidth,
      source_height_px: video.videoHeight,
      element_rect: toPixelRect(video.getBoundingClientRect()),
    });
    const context = createFrameContext({
      session_id: sessionId,
      sequence: 0,
      frame_id: "frame-context-preview",
      captured_at_mono_ms: performance.now(),
      video_id: videoId,
      video_time_seconds: video.currentTime,
      playback_epoch: playbackEpochRef.current,
      layout,
    });

    setCurrentTimeMs(context.video_time_ms);
    setContextPreview(context);
  }, [sessionId, videoId]);

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
    if (!video || mediaState !== "ready") return;

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
    }
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
          onError={() => setMediaState("error")}
        />

        <div className="lookbook-stage__shade" aria-hidden="true" />

        <div className="lookbook-stage__heading">
          <p className="section-label">AI LOOKBOOK · {categoryLabel}</p>
          <h1 id="lookbook-title">당신의 시선이 머무는 순간</h1>
          <span>{videoId}</span>
        </div>

        {mediaMessage && (
          <div className="lookbook-media-message" role="status">
            <strong>{mediaMessage}</strong>
            <span>개발 환경의 VITE_LOOKBOOK_VIDEO_URL을 확인해주세요.</span>
          </div>
        )}

        <div className="lookbook-controls">
          <button
            className="lookbook-play-button"
            type="button"
            onClick={() => void togglePlayback()}
            disabled={mediaState !== "ready"}
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

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { calibrationHint, type CalibrationProgress } from "../app/calibration-session.ts";

export function FacePositioningGuide({ stream, progress, fresh }: {
  stream: MediaStream | null;
  progress: CalibrationProgress | null;
  fresh: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [aspect, setAspect] = useState(16 / 9);
  const state = fresh ? progress?.positioning : undefined;
  const aligned = Boolean(state?.face_detected && state.eyes_visible && state.centered && state.distance_ok && state.facing_forward);
  const stable = state?.stable_ms ?? 0;

  useEffect(() => {
    const element = video.current;
    if (!element || !stream) return;
    element.srcObject = stream;
    void element.play().catch(() => { /* Muted autoplay can be resumed by the user's tap. */ });
    return () => { element.pause(); element.srcObject = null; };
  }, [stream]);

  return <section className="face-positioning" aria-labelledby="face-positioning-title">
    <p className="section-label">FIND YOUR POSITION</p>
    <h1 id="face-positioning-title">먼저, 얼굴을 맞춰주세요</h1>
    <p className="face-positioning__description">테두리 가운데에 편하게 앉아주세요.<br />초록색이 된 뒤 잠깐 유지하면 시선 맞추기가 시작돼요.</p>
    <div className={`face-positioning__preview ${aligned ? "is-aligned" : ""}`} style={{ aspectRatio: aspect, "--camera-aspect": aspect } as CSSProperties}>
      <video ref={video} autoPlay muted playsInline aria-label="얼굴 위치 확인용 카메라 미리보기"
        onClick={() => { void video.current?.play().catch(() => undefined); }}
        onLoadedMetadata={() => {
          const v = video.current;
          if (v && v.videoWidth > 0 && v.videoHeight > 0) setAspect(v.videoWidth / v.videoHeight);
        }} />
      {!stream && <span className="face-positioning__placeholder">카메라 미리보기 영역</span>}
      <svg className="face-positioning__outline" viewBox={`0 0 ${1000 * aspect} 1000`} aria-hidden="true">
        <ellipse cx={500 * aspect} cy="500" rx="270" ry="370" />
        <path d={`M ${500 * aspect - 170} 410 H ${500 * aspect + 170}`} />
      </svg>
      <span className="face-positioning__badge">{aligned ? "위치가 좋아요" : "얼굴 위치 맞추기"}</span>
    </div>
    <ul className="face-positioning__checks" aria-label="시작 준비 상태">
      {([
        ["양쪽 눈", state?.eyes_visible],
        ["위치와 거리", state?.centered && state?.distance_ok],
        ["고개 각도", state?.facing_forward],
      ] as const).map(([label, ok]) => <li key={label} className={ok ? "is-ready" : ""}>
        <span aria-hidden="true">{ok ? "✓" : "○"}</span> {label}<span className="sr-only">{ok ? " 확인됨" : " 확인 중"}</span>
      </li>)}
    </ul>
    <p className="face-positioning__hint" role="status">{fresh ? calibrationHint(progress) : "카메라에서 얼굴 위치를 확인하고 있어요"}</p>
    <progress aria-label="안정된 자세 유지" max={1000} value={stable} />
    <p className="face-positioning__timing">{aligned ? "지금 자세로 약 1초만 유지해주세요" : "테두리에 정확히 맞추지 않아도 괜찮아요"}</p>
  </section>;
}

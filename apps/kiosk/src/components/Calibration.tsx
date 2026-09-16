import { useEffect, useRef, useState, type CSSProperties } from "react";
import { CALIBRATION_CAPTURE_INTERVAL_MS, CALIBRATION_TARGET_TRANSITION_MS } from "../app/calibration-plan.ts";
import { calibrationHint, type CalibrationMarker, type CalibrationProgress } from "../app/calibration-session.ts";
import type { VisionClient } from "../clients/vision/VisionClient.ts";
import { FacePositioningGuide } from "./FacePositioningGuide.tsx";

const PHASE_LABELS = {
  positioning: "자세 맞추기", training: "시선 맞추기", validation: "시선 확인",
  repair: "시선 더 확인하기", verification: "마지막 확인", fitting: "시선 맞추는 중",
};

export function Calibration({ onHome, onBegin, onComplete, onFrameCapture, visionClient, cameraStream = null }: {
  onHome: () => void;
  onBegin: () => Promise<unknown>;
  onComplete: () => Promise<void>;
  onFrameCapture: (marker?: CalibrationMarker) => Promise<void>;
  visionClient: VisionClient;
  cameraStream?: MediaStream | null;
}) {
  const [started, setStarted] = useState(false);
  const [progress, setProgress] = useState<CalibrationProgress | null>(null);
  const [sound, setSound] = useState(false);
  const [freshProgress, setFreshProgress] = useState(false);
  const lastProgressAt = useRef(0);
  const marker = useRef<CalibrationMarker | undefined>(undefined);
  const audio = useRef<AudioContext | null>(null);
  const previousCompleted = useRef(0);

  useEffect(() => visionClient.onCalibrationProgress?.((next) => {
    if (next.completed_targets > previousCompleted.current && audio.current?.state === "running") {
      const oscillator = audio.current.createOscillator();
      const gain = audio.current.createGain();
      oscillator.connect(gain); gain.connect(audio.current.destination);
      oscillator.frequency.value = 660;
      gain.gain.setValueAtTime(0.035, audio.current.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audio.current.currentTime + 0.09);
      oscillator.start(); oscillator.stop(audio.current.currentTime + 0.1);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
    }
    previousCompleted.current = next.completed_targets;
    lastProgressAt.current = performance.now();
    setFreshProgress(true);
    // Invalidate synchronously: a capture between notification and React's commit
    // must not label the new position with the previous target.
    if (marker.current?.target_id !== next.target_id || next.phase === "fitting") marker.current = undefined;
    setProgress(next);
  }), [visionClient]);

  const targetId = progress?.target_id;
  const calibrationId = progress?.calibration_id;
  const phase = progress?.phase;
  const x = progress?.target[0] ?? 0.5;
  const y = progress?.target[1] ?? 0.5;
  const positioning = started && (!phase || phase === "positioning");

  useEffect(() => {
    if (!positioning) return;
    const timer = window.setInterval(() => {
      setFreshProgress(performance.now() - lastProgressAt.current <= 600 && !document.hidden);
    }, 200);
    return () => window.clearInterval(timer);
  }, [positioning]);

  useEffect(() => {
    if (!targetId || !calibrationId || phase === "fitting") return;
    let frame = 0;
    // Wait for the position transition and a painted frame. Both this timestamp
    // and captured_at_mono_ms use the browser's performance clock.
    const timer = window.setTimeout(() => {
      frame = window.requestAnimationFrame(() => {
        frame = window.requestAnimationFrame(() => {
          marker.current = { calibration_id: calibrationId, target_id: targetId, presented_at_mono_ms: performance.now() };
        });
      });
    }, CALIBRATION_TARGET_TRANSITION_MS);
    return () => {
      marker.current = undefined;
      window.clearTimeout(timer);
      window.cancelAnimationFrame(frame);
    };
  }, [targetId, calibrationId, phase, x, y]);

  useEffect(() => {
    if (!started) return;
    let active = true;
    const timer = window.setInterval(() => {
      // Unlabelled frames bootstrap worker progress; they are never training data.
      if (!document.hidden) void onFrameCapture(marker.current).catch(() => undefined);
    }, CALIBRATION_CAPTURE_INTERVAL_MS);
    void (async () => {
      try { await onBegin(); } catch { /* Parent presents the same guarded result. */ }
      window.clearInterval(timer);
      if (active) await onComplete();
    })();
    return () => { active = false; marker.current = undefined; window.clearInterval(timer); };
  }, [started, onBegin, onComplete, onFrameCapture]);

  useEffect(() => () => { void audio.current?.close(); audio.current = null; }, []);

  const toggleSound = () => {
    if (sound) { void audio.current?.suspend(); setSound(false); }
    else {
      audio.current ??= new AudioContext();
      void audio.current.resume().then(() => setSound(true)).catch(() => setSound(false));
    }
  };
  const ratio = progress ? progress.accepted_samples / progress.required_samples : 0;
  return (
    <main className="store-screen calibration-screen screen-enter">
      <section className={`calibration-page calibration-page--${started ? "active" : "intro"}`} aria-label="시선 맞춤">
        {!started && <div className="calibration-page__copy">
          <p className="section-label">FOLLOW THE DOT</p>
          <h1>화면의 점을<br />눈으로 따라가세요</h1>
          <p>먼저 카메라 미리보기에서 얼굴 위치를 맞춰요. 준비되면 화면에 나타나는 점의 가운데를 바라봐 주세요.</p>
          <p className="calibration-page__warning">편하게 앉아주세요. 얼굴 위치가 약 1초 동안 안정되면 시선 맞추기가 자동으로 시작돼요.</p>
          <button className="store-button store-button--solid calibration-start-button" type="button" onClick={() => setStarted(true)}>얼굴 맞추기 시작</button>
          <button className="back-link" type="button" onClick={onHome}>처음으로 돌아가기</button>
        </div>}
        <div className="calibration-stage" aria-hidden="true">
          {started && !positioning && phase !== "fitting" && <span className="calibration-target calibration-charm" style={{
            left: `${x * 100}%`, top: `${y * 100}%`,
            transitionDuration: `${CALIBRATION_TARGET_TRANSITION_MS}ms`,
            "--collected": `${ratio * 100}%`,
          } as CSSProperties}>
            <span className="calibration-charm__center" />
            {progress && <span key={progress.completed_targets} className="calibration-charm__arrival" />}
          </span>}
        </div>
        {positioning && <FacePositioningGuide stream={cameraStream} progress={progress} fresh={freshProgress} />}
        <div className="calibration-controls">
          <button type="button" aria-pressed={sound} onClick={toggleSound}>효과음 {sound ? "켜짐" : "꺼짐"}</button>
          {started && <button type="button" onClick={onHome}>그만하기</button>}
        </div>
        {started && !positioning && <footer className="calibration-status">
          <span className="calibration-status__phase">{phase ? PHASE_LABELS[phase] : "연결 준비"}</span>
          <p role="status">{calibrationHint(progress)}</p>
          {progress && <div className="calibration-status__count">
            <progress aria-label="시선 맞춤 진행" max={progress.total_targets} value={progress.completed_targets} />
            <span>{progress.completed_targets} / {progress.total_targets}</span>
          </div>}
        </footer>}
      </section>
    </main>
  );
}

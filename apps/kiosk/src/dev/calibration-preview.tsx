// Isolated Vite development entry. Never imported by the production Kiosk.
import { useCallback, useState } from "react";
import { createRoot } from "react-dom/client";
import { Calibration } from "../components/Calibration.tsx";
import { FakeRemoteVisionClient } from "../clients/vision/FakeRemoteVisionClient.ts";
import type { CalibrationPattern, CalibrationResult } from "../app/kiosk-types.ts";
import type { CalibrationMarker, CalibrationProgress } from "../app/calibration-session.ts";
import "../index.css";
import "../App.css";

class PreviewClient extends FakeRemoteVisionClient {
  listeners = new Set<(p: CalibrationProgress) => void>();
  hint: CalibrationProgress["hint"] = "more_samples";
  repair = false;
  onCalibrationProgress(listener: (p: CalibrationProgress) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  override startCalibration(_pattern: CalibrationPattern): Promise<CalibrationResult> {
    void _pattern;
    const steps: { target: readonly [number, number]; phase: CalibrationProgress["phase"] }[] = [
      { target: [.5, .5], phase: "positioning" }, { target: [.1, .1], phase: "training" },
      { target: [.9, .9], phase: "training" }, { target: [.85, .2], phase: "validation" },
    ];
    if (this.repair) steps.push({ target: [.2, .7], phase: "repair" }, { target: [.55, .6], phase: "verification" });
    return new Promise((resolve) => {
      let index = 0;
      let samples = 0;
      const timer = window.setInterval(() => {
        if (index === steps.length) {
          window.clearInterval(timer);
          resolve({ calibration_id: "preview-calibration", valid: true, reason: null });
          return;
        }
        const step = steps[index]!;
        const positioning = step.phase === "positioning";
        const holding = this.hint === "more_samples";
        const progress: CalibrationProgress = { calibration_id: "preview-calibration", profile_id: "adaptive-dense5-v2",
          phase: step.phase, target_id: `target-${index + 1}`, target: step.target, accepted_samples: samples,
          required_samples: 15, completed_targets: index, total_targets: steps.length, hint: positioning && holding ? "position_ready" : this.hint,
          ...(positioning ? { positioning: {
            face_detected: this.hint !== "no_face", eyes_visible: !["no_face", "blink", "eyes_visible"].includes(this.hint),
            centered: !["no_face", "center_face"].includes(this.hint), distance_ok: !["no_face", "move_closer", "move_back"].includes(this.hint),
            facing_forward: !["no_face", "face_forward", "hold_still"].includes(this.hint), stable_ms: holding ? Math.min(1000, samples * 200) : 0,
          } } : {}), };
        for (const listener of this.listeners) listener(progress);
        if (holding) samples++; else samples = 0;
        if (samples > (positioning ? 5 : 15)) { index++; samples = 0; }
      }, 200);
    });
  }
}
const client = new PreviewClient();
export function Preview() {
  const [done, setDone] = useState(false);
  const [marker, setMarker] = useState("대기");
  const begin = useCallback(() => client.startCalibration({ pattern_id: "adaptive-dense5-v2", points: [] }), []);
  const complete = useCallback(async () => { setDone(true); }, []);
  const capture = useCallback(async (value?: CalibrationMarker) => { setMarker(value?.target_id ?? "이동 중"); }, []);
  const home = useCallback(() => location.reload(), []);
  return <>
    {done ? <main style={{ padding: "25vh 10vw", textAlign: "center" }}><h1>화면 점검 완료</h1><p>실제 카메라 정확도 검사 결과가 아닙니다.</p><button onClick={home}>다시 보기</button></main>
      : <Calibration visionClient={client} onBegin={begin} onComplete={complete} onHome={home} onFrameCapture={capture} />}
    <aside style={{ position: "fixed", top: 46, left: 12, zIndex: 20, fontSize: 11, color: "#514b42", background: "#faf8f2e8", padding: 8 }}>
      <strong>로컬 UI 점검 · 카메라 미사용 · 짧은 모의 경로</strong><br />
      <label>상황 <select aria-label="테스트 상황" onChange={(e) => { client.hint = e.target.value as CalibrationProgress["hint"]; }}>
        <option value="more_samples">정상 수집</option><option value="blink">깜빡임</option><option value="no_face">얼굴 미인식</option><option value="hold_still">고개 움직임</option>
        <option value="center_face">얼굴 중앙 맞추기</option><option value="move_closer">너무 멀리 있음</option><option value="move_back">너무 가까이 있음</option><option value="face_forward">고개 각도 맞추기</option><option value="eyes_visible">양쪽 눈 확인</option>
      </select></label>{" "}
      <label><input type="checkbox" onChange={(e) => { client.repair = e.target.checked; }} />부분 보완 포함 (시작 전 선택)</label><br />
      <output>화면 표시 후 캡처 표식: {marker}</output>
    </aside>
  </>;
}
createRoot(document.getElementById("root")!).render(<Preview />);

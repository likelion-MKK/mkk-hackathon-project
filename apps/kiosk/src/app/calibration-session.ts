export const CALIBRATION_PROFILES = ["adaptive-dense5-v2", "adaptive-sparse16-v2", "fixed-dense5-v2"] as const;
export type CalibrationProfile = typeof CALIBRATION_PROFILES[number];
export type CalibrationMarker = Readonly<{
  calibration_id: string;
  target_id: string;
  presented_at_mono_ms: number;
}>;
export type FacePositioning = Readonly<{
  face_detected: boolean;
  eyes_visible: boolean;
  centered: boolean;
  distance_ok: boolean;
  facing_forward: boolean;
  stable_ms: number;
}>;
export type CalibrationProgress = Readonly<{
  calibration_id: string;
  profile_id: CalibrationProfile;
  phase: "positioning" | "training" | "validation" | "repair" | "verification" | "fitting";
  target_id: string;
  target: readonly [number, number];
  accepted_samples: number;
  required_samples: number;
  completed_targets: number;
  total_targets: number;
  hint: "follow_target" | "hold_still" | "no_face" | "blink" | "more_samples" | "fitting"
    | "center_face" | "move_closer" | "move_back" | "face_forward" | "eyes_visible" | "position_ready";
  positioning?: FacePositioning;
}>;

export function parseCalibrationProgress(value: unknown): CalibrationProgress {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid_calibration_progress");
  const v = value as Record<string, unknown>;
  const fields = ["calibration_id", "profile_id", "phase", "target_id", "target", "accepted_samples", "required_samples", "completed_targets", "total_targets", "hint"];
  const id = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  if (Object.keys(v).some((key) => !fields.includes(key) && key !== "positioning") || fields.some((key) => !(key in v))
      || typeof v.calibration_id !== "string" || !id.test(v.calibration_id)
      || typeof v.target_id !== "string" || !id.test(v.target_id)
      || !CALIBRATION_PROFILES.includes(v.profile_id as CalibrationProfile)
      || !["positioning", "training", "validation", "repair", "verification", "fitting"].includes(String(v.phase))
      || !["follow_target", "hold_still", "no_face", "blink", "more_samples", "fitting", "center_face", "move_closer", "move_back", "face_forward", "eyes_visible", "position_ready"].includes(String(v.hint))
      || !Array.isArray(v.target) || v.target.length !== 2
      || v.target.some((n) => typeof n !== "number" || !Number.isFinite(n) || n < 0 || n > 1)) {
    throw new Error("invalid_calibration_progress");
  }
  for (const key of ["accepted_samples", "required_samples", "completed_targets", "total_targets"]) {
    if (typeof v[key] !== "number" || !Number.isInteger(v[key]) || v[key] < 0 || v[key] > 128) throw new Error("invalid_calibration_progress");
  }
  if (Number(v.required_samples) < 1 || Number(v.accepted_samples) > Number(v.required_samples)
      || Number(v.completed_targets) > Number(v.total_targets)) throw new Error("invalid_calibration_progress");
  if ("positioning" in v) {
    const p = v.positioning as Record<string, unknown> | null;
    const flags = ["face_detected", "eyes_visible", "centered", "distance_ok", "facing_forward"];
    if (v.phase !== "positioning" || !p || typeof p !== "object" || Array.isArray(p)
        || Object.keys(p).length !== 6 || flags.some((key) => typeof p[key] !== "boolean")
        || typeof p.stable_ms !== "number" || !Number.isInteger(p.stable_ms) || p.stable_ms < 0 || p.stable_ms > 1000
        || (p.stable_ms > 0 && flags.some((key) => p[key] !== true))) throw new Error("invalid_calibration_progress");
  }
  return v as unknown as CalibrationProgress;
}

export function calibrationHint(progress: CalibrationProgress | null): string {
  if (!progress) return "시선 연결을 준비하고 있어요";
  if (progress.phase === "positioning") {
    const hints: Partial<Record<CalibrationProgress["hint"], string>> = {
      no_face: "얼굴이 미리보기 안에 보이도록 앉아주세요",
      center_face: "얼굴을 테두리 가운데로 옮겨주세요",
      move_closer: "조금 가까이 와주세요",
      move_back: "조금 뒤로 앉아주세요",
      face_forward: "카메라 쪽으로 얼굴을 편하게 맞춰주세요",
      eyes_visible: "양쪽 눈이 잘 보이도록 해주세요",
      blink: "편하게 깜빡인 뒤 카메라 쪽을 봐주세요",
      hold_still: "좋아요. 지금 자세로 잠깐만 계세요",
      position_ready: "준비됐어요. 곧 시선 맞추기가 시작돼요",
    };
    return hints[progress.hint] ?? "얼굴의 위치와 눈을 확인하고 있어요";
  }
  if (progress.phase === "fitting") return "모은 시선을 맞추고 있어요. 잠시 편하게 계세요";
  if (progress.hint === "no_face") return "얼굴과 눈이 화면 중앙에 보이도록 맞춰주세요";
  if (progress.hint === "hold_still") return "고개는 편하게 멈추고, 점의 가운데를 바라봐 주세요";
  if (progress.hint === "blink") return "눈은 편하게 깜빡여도 괜찮아요. 같은 점을 봐주세요";
  if (progress.phase === "repair") return "이 부분만 조금 더 모으면 돼요";
  if (progress.phase === "validation" || progress.phase === "verification") {
    if (progress.required_samples > 15) return "이 지점의 시선을 조금 더 확인하고 있어요. 같은 점을 바라봐주세요";
    return "시선이 잘 맞는지 확인하고 있어요";
  }
  return "빛나는 점의 가운데를 눈으로 따라가세요";
}

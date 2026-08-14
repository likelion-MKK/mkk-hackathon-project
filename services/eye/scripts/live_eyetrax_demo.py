"""Run one private, full-screen EyeTrax calibration and gaze-overlay demo."""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))

from mcm_eye.adapters.eyetrax import (  # noqa: E402
    DEFAULT_FACE_MODEL_PATH,
    CalibrationCancelled,
    CalibrationCapture,
    CalibrationPhase,
    EyeTraxAdapter,
    EyeTraxConfig,
)
from mcm_eye.contracts import CalibrationRequest  # noqa: E402

WINDOW_NAME = "MCM EyeTrax Gaze Demo"


@dataclass(frozen=True, slots=True)
class DemoFrameContext:
    session_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int = 0


def logical_viewport_size() -> tuple[int, int]:
    if sys.platform == "win32":
        width = int(ctypes.windll.user32.GetSystemMetrics(0))
        height = int(ctypes.windll.user32.GetSystemMetrics(1))
    else:
        from screeninfo import get_monitors

        monitor = get_monitors()[0]
        width, height = int(monitor.width), int(monitor.height)
    if width <= 0 or height <= 0:
        raise RuntimeError("Could not determine a positive logical viewport")
    return width, height


def draw_canvas(
    width: int,
    height: int,
    lines: tuple[str, ...],
    *,
    target: tuple[int, int] | None = None,
    progress: float | None = None,
    wait_ms: int = 1,
) -> int:
    canvas = np.full((height, width, 3), 35, dtype=np.uint8)
    if target is not None:
        cv2.circle(canvas, target, 18, (0, 190, 255), -1)
        cv2.circle(canvas, target, 34, (255, 255, 255), 3)
        if progress is not None:
            cv2.ellipse(
                canvas,
                target,
                (44, 44),
                0,
                -90,
                -90 + int(360 * max(0.0, min(progress, 1.0))),
                (80, 220, 80),
                4,
            )
    for index, line in enumerate(lines):
        scale = 1.1 if index == 0 else 0.8
        size, _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
        x = max(20, (width - size[0]) // 2)
        cv2.putText(
            canvas,
            line,
            (x, 70 + index * 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (235, 235, 235),
            2,
            cv2.LINE_AA,
        )
    cv2.imshow(WINDOW_NAME, canvas)
    key = cv2.waitKey(wait_ms) & 0xFF
    if key == 27:
        raise CalibrationCancelled("Participant cancelled with Escape")
    return key


def draw_camera_ready(
    width: int,
    height: int,
    frame: np.ndarray | None,
) -> int:
    canvas = np.full((height, width, 3), 35, dtype=np.uint8)
    if frame is not None:
        mirrored = cv2.flip(frame, 1)
        frame_height, frame_width = mirrored.shape[:2]
        scale = min(width / frame_width, height / frame_height)
        preview_width = max(1, int(frame_width * scale))
        preview_height = max(1, int(frame_height * scale))
        preview = cv2.resize(mirrored, (preview_width, preview_height))
        left = (width - preview_width) // 2
        top = (height - preview_height) // 2
        canvas[top : top + preview_height, left : left + preview_width] = preview

    overlay_height = 150
    cv2.rectangle(canvas, (0, 0), (width, overlay_height), (20, 20, 20), -1)
    lines = (
        "ALIGN YOUR FACE INSIDE THE OVAL",
        "Keep your head centered. Blink during LOOK AT DOT, not during HOLD.",
        "Press SPACE when ready. Press ESC to cancel. Preview is not saved.",
    )
    for index, line in enumerate(lines):
        scale = 1.0 if index == 0 else 0.68
        size, _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
        cv2.putText(
            canvas,
            line,
            (max(20, (width - size[0]) // 2), 45 + index * 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (235, 235, 235),
            2,
            cv2.LINE_AA,
        )
    cv2.ellipse(
        canvas,
        (width // 2, height // 2 + 35),
        (max(90, int(width * 0.11)), max(150, int(height * 0.28))),
        0,
        0,
        360,
        (80, 220, 80),
        4,
    )
    cv2.imshow(WINDOW_NAME, canvas)
    key = cv2.waitKey(20) & 0xFF
    if key == 27:
        raise CalibrationCancelled("Participant cancelled with Escape")
    return key


def wait_for_space(cap: cv2.VideoCapture, width: int, height: int) -> None:
    while True:
        ok, frame = cap.read()
        key = draw_camera_ready(width, height, frame if ok else None)
        if key == 32:
            return


class OpenCvCalibrationSource:
    def __init__(self, cap: cv2.VideoCapture, width: int, height: int) -> None:
        self._cap = cap
        self._width = width
        self._height = height

    def __call__(self, capture: CalibrationCapture):
        target = (
            int(capture.target_x_norm * self._width),
            int(capture.target_y_norm * self._height),
        )
        phase = "CALIBRATION" if capture.phase is CalibrationPhase.TRAINING else "VALIDATION"
        prefix = (
            f"ATTEMPT {capture.attempt}/2 - {phase} "
            f"{capture.point_index}/{capture.point_count}"
        )

        adaptation_started = time.perf_counter()
        while (elapsed := time.perf_counter() - adaptation_started) < capture.adaptation_seconds:
            self._cap.grab()
            draw_canvas(
                self._width,
                self._height,
                (prefix, "LOOK AT THE DOT"),
                target=target,
                progress=elapsed / capture.adaptation_seconds,
            )

        collection_started = time.perf_counter()
        while (elapsed := time.perf_counter() - collection_started) < capture.collection_seconds:
            ok, frame = self._cap.read()
            draw_canvas(
                self._width,
                self._height,
                (prefix, "HOLD"),
                target=target,
                progress=elapsed / capture.collection_seconds,
            )
            if ok:
                yield frame


def open_camera(args: argparse.Namespace) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened() and backend != cv2.CAP_ANY:
        cap.release()
        cap = cv2.VideoCapture(args.camera, cv2.CAP_ANY)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {args.camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.requested_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.requested_height)
    cap.set(cv2.CAP_PROP_FPS, args.requested_fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_FACE_MODEL_PATH)
    parser.add_argument("--requested-width", type=int, default=1280)
    parser.add_argument("--requested-height", type=int, default=720)
    parser.add_argument("--requested-fps", type=float, default=30.0)
    parser.add_argument("--windowed", action="store_true")
    return parser.parse_args()


def run_demo(args: argparse.Namespace) -> int:
    width, height = logical_viewport_size()
    cap = open_camera(args)
    adapter: EyeTraxAdapter | None = None
    try:
        source = OpenCvCalibrationSource(cap, width, height)
        adapter = EyeTraxAdapter(
            EyeTraxConfig(width, height, args.model_path),
            source,
        )

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        if not args.windowed:
            cv2.setWindowProperty(
                WINDOW_NAME,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN,
            )
        if sys.platform == "win32":
            cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_TOPMOST, 1)

        print(
            "Camera opened: "
            f"requested={args.requested_width}x{args.requested_height}@"
            f"{args.requested_fps:g} "
            f"actual={int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}@"
            f"{cap.get(cv2.CAP_PROP_FPS):g} backend={cap.getBackendName()}"
        )

        adapter.initialize()
        adapter.warmup()
        wait_for_space(cap, width, height)
        result = adapter.calibrate(CalibrationRequest("calibration-eyetrax-live-demo"))
        if not result.valid:
            print(f"Calibration failed: {result.reason}")
            return 2

        print("Calibration passed. Live gaze overlay started; press ESC to finish.")
        started = time.perf_counter()
        sequence = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            sequence += 1
            now_ms = time.perf_counter() * 1000.0
            context = DemoFrameContext(
                session_id="session-eyetrax-live-demo",
                sequence=sequence,
                frame_id=f"frame-{sequence:08d}",
                captured_at_mono_ms=now_ms,
                video_id="mcm-lookbook-demo",
                video_time_ms=int((time.perf_counter() - started) * 1000),
            )
            sample = adapter.infer(frame, context)
            canvas = np.full((height, width, 3), 35, dtype=np.uint8)
            if sample.valid:
                x = int((sample.screen_x_norm or 0.0) * width)
                y = int((sample.screen_y_norm or 0.0) * height)
                cv2.drawMarker(
                    canvas,
                    (x, y),
                    (0, 80, 255),
                    cv2.MARKER_CROSS,
                    48,
                    5,
                    cv2.LINE_AA,
                )
                status = "GAZE VALID"
                color = (80, 220, 80)
            else:
                status = (sample.reason or "GAZE UNAVAILABLE").replace("_", " ").upper()
                color = (80, 80, 255)
            cv2.putText(
                canvas,
                status,
                (40, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                color,
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                canvas,
                "Press ESC to finish. Frames and gaze coordinates are not saved.",
                (40, height - 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (220, 220, 220),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(WINDOW_NAME, canvas)
            if cv2.waitKey(1) & 0xFF == 27:
                break
        return 0
    finally:
        try:
            if adapter is not None:
                adapter.dispose()
        finally:
            try:
                cap.release()
            finally:
                cv2.destroyAllWindows()


def main() -> int:
    try:
        return run_demo(parse_args())
    except CalibrationCancelled:
        print("EyeTrax live demo cancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

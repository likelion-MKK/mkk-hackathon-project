"""Run the real EyeTrax initialize, black-frame warmup and dispose path."""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))

from mcm_eye.adapters.eyetrax import (  # noqa: E402
    DEFAULT_FACE_MODEL_PATH,
    FACE_MODEL_SHA256,
    EyeTraxAdapter,
    EyeTraxConfig,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_FACE_MODEL_PATH)
    parser.add_argument("--viewport-width", type=int, default=1536)
    parser.add_argument("--viewport-height", type=int, default=864)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    def unused_calibration_source(_capture):
        raise RuntimeError("Smoke test must not request calibration frames")

    adapter = EyeTraxAdapter(
        EyeTraxConfig(
            viewport_width_px=args.viewport_width,
            viewport_height_px=args.viewport_height,
            face_model_path=args.model_path,
        ),
        unused_calibration_source,
    )
    try:
        adapter.initialize()
        adapter.warmup()
    finally:
        adapter.dispose()

    print(
        "EyeTrax smoke passed: "
        f"python={platform.python_version()} "
        f"eyetrax={importlib.metadata.version('eyetrax')} "
        f"mediapipe={importlib.metadata.version('mediapipe')} "
        f"model_sha256={FACE_MODEL_SHA256} raw_frame_saved=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

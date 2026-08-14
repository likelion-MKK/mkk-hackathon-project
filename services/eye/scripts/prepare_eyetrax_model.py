"""Prepare or verify the pinned EyeTrax FaceLandmarker model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))

from mcm_eye.adapters.eyetrax import (  # noqa: E402
    DEFAULT_FACE_MODEL_PATH,
    FACE_MODEL_SHA256,
    prepare_face_model,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_FACE_MODEL_PATH)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Verify an existing model without making a network request.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model_path = prepare_face_model(args.model_path, offline=args.offline)
    print(f"FaceLandmarker verified: {model_path} ({FACE_MODEL_SHA256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

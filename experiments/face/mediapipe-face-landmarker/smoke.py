"""Run a local MediaPipe Face Landmarker smoke check with synthetic input."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

import mediapipe as mp
import numpy as np


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
MODEL_PATH = Path(__file__).parent / "models" / "face_landmarker.task"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(*, offline: bool) -> None:
    if MODEL_PATH.is_file():
        return
    if offline:
        raise FileNotFoundError(f"offline model asset is missing: {MODEL_PATH}")
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = MODEL_PATH.with_suffix(".download")
    try:
        urllib.request.urlretrieve(MODEL_URL, temporary_path)
        temporary_path.replace(MODEL_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    ensure_model(offline=args.offline)

    options = mp.tasks.vision.FaceLandmarkerOptions(
        # The C runtime cannot open non-ASCII Windows paths reliably. Passing the
        # same local asset as bytes also proves inference does not need a URL.
        base_options=mp.tasks.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_faces=1,
        output_face_blendshapes=True,
    )
    pixels = np.full((256, 256, 3), 127, dtype=np.uint8)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=pixels)
    with mp.tasks.vision.FaceLandmarker.create_from_options(options) as landmarker:
        result = landmarker.detect(image)

    if result.face_landmarks or result.face_blendshapes:
        raise AssertionError("synthetic no-face input unexpectedly produced a face")

    print(
        json.dumps(
            {
                "candidate": "mediapipe-face-landmarker",
                "offline": args.offline,
                "model_sha256": sha256(MODEL_PATH),
                "input_shape": list(pixels.shape),
                "face_count": len(result.face_landmarks),
                "blendshape_groups": len(result.face_blendshapes),
                "status": "pass",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

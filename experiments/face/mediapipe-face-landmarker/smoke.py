"""Run a local MediaPipe Face Landmarker smoke check with synthetic input."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MODEL_PATH = Path(__file__).parent / "models" / "face_landmarker.task"
EXPECTED_MODEL_SHA256 = (
    "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
)


class ModelChecksumError(ValueError):
    """Raised before model loading when an asset checksum is unexpected."""

    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__(f"model SHA256 mismatch: expected {expected}, got {actual}")
        self.expected = expected
        self.actual = actual


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(path: Path, expected_sha256: str) -> str:
    actual_sha256 = sha256(path)
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise ModelChecksumError(expected=expected_sha256, actual=actual_sha256)
    return actual_sha256


def ensure_model(
    *,
    offline: bool,
    model_path: Path = MODEL_PATH,
    model_url: str = MODEL_URL,
    expected_sha256: str = EXPECTED_MODEL_SHA256,
) -> str:
    if model_path.is_file():
        return verify_model(model_path, expected_sha256)
    if offline:
        raise FileNotFoundError(f"offline model asset is missing: {model_path}")
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = model_path.with_suffix(".download")
    try:
        urllib.request.urlretrieve(model_url, temporary_path)
        actual_sha256 = verify_model(temporary_path, expected_sha256)
        temporary_path.replace(model_path)
        return actual_sha256
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        model_sha256 = ensure_model(offline=args.offline)
    except ModelChecksumError as error:
        print(
            json.dumps(
                {
                    "actual_model_sha256": error.actual,
                    "candidate": "mediapipe-face-landmarker",
                    "expected_model_sha256": error.expected,
                    "offline": args.offline,
                    "reason": "model_checksum_mismatch",
                    "status": "fail",
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None

    import mediapipe as mp
    import numpy as np

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
                "model_sha256": model_sha256,
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

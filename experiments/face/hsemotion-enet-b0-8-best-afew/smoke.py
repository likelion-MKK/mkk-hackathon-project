"""Run HSEmotion enet_b0_8_best_afew on a synthetic face crop."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import pickle
import urllib.request
from pathlib import Path

MODEL_ID = "enet_b0_8_best_afew"
MODEL_REVISION = "520a051c64cd191521e5934655314e769a319684"
MODEL_URL = (
    "https://raw.githubusercontent.com/HSE-asavchenko/face-emotion-recognition/"
    f"{MODEL_REVISION}/models/affectnet_emotions/{MODEL_ID}.pt"
)
MODEL_PATH = Path(__file__).parent / "models" / f"{MODEL_ID}.pt"
EXPECTED_MODEL_SHA256 = (
    "47c1423f3e6f50e3750bf7b0eda7db947c9ce0c2637e1766bf2187eddc652b17"
)
LABELS = (
    "Anger",
    "Contempt",
    "Disgust",
    "Fear",
    "Happiness",
    "Neutral",
    "Sadness",
    "Surprise",
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
                    "candidate": "hsemotion-enet-b0-8-best-afew",
                    "expected_model_sha256": error.expected,
                    "offline": args.offline,
                    "reason": "model_checksum_mismatch",
                    "status": "fail",
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None

    import hsemotion.facial_emotions as facial_emotions
    import numpy as np

    facial_emotions.get_model_path = lambda _: str(MODEL_PATH)
    try:
        recognizer = facial_emotions.HSEmotionRecognizer(
            model_name=MODEL_ID, device="cpu"
        )
    except pickle.UnpicklingError:
        print(
            json.dumps(
                {
                    "candidate": "hsemotion-enet-b0-8-best-afew",
                    "offline": args.offline,
                    "model_sha256": model_sha256,
                    "reason": "unsafe_legacy_pickle_blocked",
                    "status": "fail",
                },
                sort_keys=True,
            )
        )
        raise SystemExit(2) from None
    pixels = np.full((224, 224, 3), 127, dtype=np.uint8)
    label, scores = recognizer.predict_emotions(pixels, logits=False)
    score_array = np.asarray(scores)
    if score_array.shape != (8,):
        raise AssertionError(f"unexpected output shape: {score_array.shape}")
    if not np.isfinite(score_array).all():
        raise AssertionError("output contains a non-finite score")
    if not np.isclose(score_array.sum(), 1.0, atol=1e-4):
        raise AssertionError(f"softmax scores do not sum to one: {score_array.sum()}")

    print(
        json.dumps(
            {
                "candidate": "hsemotion-enet-b0-8-best-afew",
                "offline": args.offline,
                "model_sha256": model_sha256,
                "input_shape": list(pixels.shape),
                "output_shape": list(score_array.shape),
                "labels": list(LABELS),
                "top_label": label,
                "status": "pass",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

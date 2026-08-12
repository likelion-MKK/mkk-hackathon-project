"""Run HSEmotion enet_b0_8_best_afew on a synthetic face crop."""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import urllib.request
from pathlib import Path

import numpy as np


MODEL_ID = "enet_b0_8_best_afew"
MODEL_REVISION = "520a051c64cd191521e5934655314e769a319684"
MODEL_URL = (
    "https://raw.githubusercontent.com/HSE-asavchenko/face-emotion-recognition/"
    f"{MODEL_REVISION}/models/affectnet_emotions/{MODEL_ID}.pt"
)
MODEL_PATH = Path(__file__).parent / "models" / f"{MODEL_ID}.pt"
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

    import hsemotion.facial_emotions as facial_emotions

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
                    "model_sha256": sha256(MODEL_PATH),
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
                "model_sha256": sha256(MODEL_PATH),
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

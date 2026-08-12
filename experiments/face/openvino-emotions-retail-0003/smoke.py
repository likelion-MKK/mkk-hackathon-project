"""Run OpenVINO emotions-recognition-retail-0003 on synthetic input."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

import numpy as np
import openvino as ov


MODEL_ROOT = Path(__file__).parent / "models" / "FP32"
MODEL_NAME = "emotions-recognition-retail-0003"
ASSETS = {
    f"{MODEL_NAME}.xml": {
        "url": (
            "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
            "2023.0/models_bin/1/emotions-recognition-retail-0003/FP32/"
            "emotions-recognition-retail-0003.xml"
        ),
        "sha384": (
            "670369f2550d26d86fe78e87a8d1221b979d3ae595a85d10b264b170858fff51"
            "c3e22103897896ff61c090cd0923a648"
        ),
    },
    f"{MODEL_NAME}.bin": {
        "url": (
            "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
            "2023.0/models_bin/1/emotions-recognition-retail-0003/FP32/"
            "emotions-recognition-retail-0003.bin"
        ),
        "sha384": (
            "b763e002e1084a792e99c755c457a2d64848967cfaa2bb851ef09e3d5d756a335"
            "b77cf08a1b770d60ccfbb87329b3f62"
        ),
    },
}
LABELS = ("neutral", "happy", "sad", "surprise", "anger")


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_models(*, offline: bool) -> dict[str, str]:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    checksums: dict[str, str] = {}
    for name, metadata in ASSETS.items():
        path = MODEL_ROOT / name
        if not path.is_file():
            if offline:
                raise FileNotFoundError(f"offline model asset is missing: {path}")
            temporary_path = path.with_suffix(path.suffix + ".download")
            try:
                urllib.request.urlretrieve(metadata["url"], temporary_path)
                temporary_path.replace(path)
            finally:
                temporary_path.unlink(missing_ok=True)
        actual_sha384 = file_digest(path, "sha384")
        if actual_sha384 != metadata["sha384"]:
            raise ValueError(f"SHA-384 mismatch for {name}")
        checksums[name] = file_digest(path, "sha256")
    return checksums


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    checksums = ensure_models(offline=args.offline)

    core = ov.Core()
    model = core.read_model(MODEL_ROOT / f"{MODEL_NAME}.xml")
    compiled = core.compile_model(model, "CPU")
    pixels = np.zeros((1, 3, 64, 64), dtype=np.float32)
    output = compiled([pixels])[compiled.output(0)]
    if output.shape != (1, 5, 1, 1):
        raise AssertionError(f"unexpected output shape: {output.shape}")
    scores = output.reshape(-1)
    if not np.isfinite(scores).all():
        raise AssertionError("output contains a non-finite score")
    if not np.isclose(scores.sum(), 1.0, atol=1e-4):
        raise AssertionError(f"softmax scores do not sum to one: {scores.sum()}")

    print(
        json.dumps(
            {
                "candidate": "openvino-emotions-retail-0003",
                "offline": args.offline,
                "model_sha256": checksums,
                "input_shape": list(pixels.shape),
                "output_shape": list(output.shape),
                "labels": list(LABELS),
                "status": "pass",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

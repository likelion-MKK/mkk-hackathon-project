"""Start the private Eye worker from the repository root.

The Eye project intentionally is not installed as a package.  This entry point
adds its source directory and the repository root before delegating to the
worker module, so its shared Vision Stream import remains available in local
development exactly as it is in the container image.
"""

from __future__ import annotations

import argparse
import importlib.util
import runpy
import sys
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVICE_ROOT.parents[1]


def configure_import_paths() -> None:
    """Make the local source tree importable without installing it."""

    for path in (SERVICE_ROOT / "src", REPOSITORY_ROOT):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the private MCM Eye worker.")
    parser.add_argument(
        "--check-imports",
        action="store_true",
        help="Verify the local import path without starting the HTTP worker.",
    )
    args = parser.parse_args()
    configure_import_paths()
    if args.check_imports:
        if importlib.util.find_spec("mcm_eye.worker") is None:
            raise RuntimeError("mcm_eye.worker is not importable")
        if importlib.util.find_spec("apps.vision_gateway.vision_stream") is None:
            raise RuntimeError("shared Vision Stream module is not importable")
        print("Eye worker imports are ready.")
        return 0

    runpy.run_module("mcm_eye.worker", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

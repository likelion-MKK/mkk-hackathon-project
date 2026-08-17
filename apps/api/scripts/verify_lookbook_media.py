#!/usr/bin/env python3
"""Verify that the staged canonical MP4 exactly matches reviewed AOI metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from apps.api.app.v2_aoi import load_aoi_metadata, verify_media_file


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media",
        type=Path,
        default=root / "apps" / "kiosk" / "public" / "media" / "mcm-lookbook-v2.mp4",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=(
            root
            / "data"
            / "lookbooks"
            / "mcm-lookbook-v2"
            / "aoi-metadata-v2.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = load_aoi_metadata(args.metadata.resolve())
    verify_media_file(args.media.resolve(), metadata.media_identity)
    identity = metadata.media_identity
    print(
        "lookbook_media_verified "
        f"video_id={metadata.video_id} "
        f"sha256={identity.sha256} "
        f"bytes={identity.byte_length} "
        f"duration_ms={identity.duration_ms} "
        f"resolution={identity.width_px}x{identity.height_px} "
        f"fps={identity.fps:g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run one derived-only low-signal diagnostic without printing model content."""

from __future__ import annotations

import asyncio
import json

from apps.api.app.v2_central import CentralModelError, configured_central_client, validate_central_output
from apps.api.app.v2_models import FrameObservationV2
from apps.api.scripts.luna_canary import build_canary_request


async def main() -> int:
    request = build_canary_request()
    frame = FrameObservationV2.model_validate(
        {
            "schema_version": "2.0",
            "frame_id": "frame-low-signal-diagnostic-0001",
            "sequence": 0,
            "captured_at_mono_ms": 100.0,
            "session_offset_ms": 0.0,
            "video_time_ms": 100,
            "playback_epoch": 0,
            "gaze": None,
            "gaze_reason": "not_observed",
            "attention": None,
            "attention_reason": "source_gaze_unavailable",
            "expression": None,
            "expression_reason": "not_observed",
            "derived": None,
            "derived_reason": "invalid_or_missing_modality",
        }
    )
    evidence = request.evidence.model_copy(
        update={
            "input_variant": "B",
            "evidence_windows": None,
            "timeline": [frame],
            "data_quality": request.evidence.data_quality.model_copy(
                update={
                    "expected_observation_count": 1,
                    "gaze_valid_ratio": 0.0,
                    "expression_valid_ratio": 0.0,
                    "matched_frame_ratio": 0.0,
                    "ambiguous_product_ratio": 0.0,
                }
            ),
        }
    )
    request = request.model_copy(update={"evidence": evidence})
    try:
        raw = await configured_central_client().recommend_async(request)
        validate_central_output(raw, request=request)
    except CentralModelError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason_code": exc.reason_code,
                    "safe_detail": str(exc),
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )
        return 1
    print('{"status":"passed"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

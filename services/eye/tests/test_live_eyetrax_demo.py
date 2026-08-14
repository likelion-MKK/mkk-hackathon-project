from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from mcm_eye.adapters.eyetrax import GazeAbObservation


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_eyetrax_demo.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "mcm_live_eyetrax_demo_test",
    SCRIPT_PATH,
)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
demo = importlib.util.module_from_spec(SCRIPT_SPEC)
sys.modules[SCRIPT_SPEC.name] = demo
SCRIPT_SPEC.loader.exec_module(demo)


class FakeCamera:
    def __init__(self) -> None:
        self.release_calls = 0

    def release(self) -> None:
        self.release_calls += 1


class FakeAdapter:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


def test_window_initialization_failure_releases_camera_and_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = FakeCamera()
    adapters: list[FakeAdapter] = []
    destroy_calls: list[None] = []

    def make_adapter(*args: object, **kwargs: object) -> FakeAdapter:
        adapter = FakeAdapter(*args, **kwargs)
        adapters.append(adapter)
        return adapter

    def fail_window_creation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("window initialization failed")

    monkeypatch.setattr(demo, "logical_viewport_size", lambda: (100, 100))
    monkeypatch.setattr(demo, "open_camera", lambda _args: camera)
    monkeypatch.setattr(demo, "EyeTraxAdapter", make_adapter)
    monkeypatch.setattr(demo.cv2, "namedWindow", fail_window_creation)
    monkeypatch.setattr(
        demo.cv2,
        "destroyAllWindows",
        lambda: destroy_calls.append(None),
    )

    args = argparse.Namespace(
        camera=0,
        model_path=tmp_path / "face_landmarker.task",
        requested_width=1280,
        requested_height=720,
        requested_fps=30.0,
        smoothing="kalman_ema",
        ema_alpha=0.25,
        windowed=False,
    )
    with pytest.raises(RuntimeError, match="window initialization failed"):
        demo.run_demo(args)

    assert len(adapters) == 1
    assert adapters[0].dispose_calls == 1
    assert camera.release_calls == 1
    assert len(destroy_calls) == 1


def test_ab_metrics_use_same_observation_and_never_emit_coordinates() -> None:
    collector = demo.AbMetricsCollector(600, 800)
    for index, offset in enumerate((-0.02, 0.02, -0.01, 0.01)):
        collector.observe(
            GazeAbObservation(
                phase="validation" if index < 2 else "live",
                captured_at_mono_ms=index * 33.0,
                target_x_norm=0.5 if index < 2 else None,
                target_y_norm=0.5 if index < 2 else None,
                raw_valid=True,
                raw_reason=None,
                raw_x_norm=0.5 + offset,
                raw_y_norm=0.5,
                stabilized_valid=True,
                stabilized_reason=None,
                stabilized_x_norm=0.5 + offset / 2.0,
                stabilized_y_norm=0.5,
                raw_aoi_hit=True if index < 2 else None,
                stabilized_aoi_hit=True if index < 2 else None,
                inference_latency_ms=2.0,
                filter_latency_ms=0.2,
            )
        )

    summary = collector.summary("kalman_ema")
    encoded = str(summary)
    assert summary["selected_mode"] == "kalman_ema"
    assert summary["raw-v1"]["aoi_hit_ratio"] == 1.0
    assert summary["gaze-filter-v1"]["aoi_hit_ratio"] == 1.0
    assert summary["frame_coordinates_saved"] is False
    assert "raw_x_norm" not in encoded
    assert "stabilized_x_norm" not in encoded
    assert np.isclose(
        summary["filter_additional_latency_ms"]["p95"],
        0.2,
    )


def test_parse_args_defaults_to_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH)])
    args = demo.parse_args()
    assert args.smoothing == "raw"
    assert args.ema_alpha == 0.25

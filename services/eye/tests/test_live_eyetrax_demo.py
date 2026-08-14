from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


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
        windowed=False,
    )
    with pytest.raises(RuntimeError, match="window initialization failed"):
        demo.run_demo(args)

    assert len(adapters) == 1
    assert adapters[0].dispose_calls == 1
    assert camera.release_calls == 1
    assert len(destroy_calls) == 1

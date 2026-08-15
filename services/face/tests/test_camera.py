from __future__ import annotations

import pytest

from mcm_face.camera import (
    CameraPermissionDenied,
    CameraUnavailable,
    OpenCVCameraSource,
    list_camera_devices,
)


class Capture:
    def __init__(self, opened: bool = True) -> None:
        self.opened = opened
        self.released = False
        self.values = {3: 640.0, 4: 480.0, 5: 30.0}

    def isOpened(self) -> bool:
        return self.opened

    def set(self, key: int, value: float) -> None:
        self.values[key] = value

    def get(self, key: int) -> float:
        return self.values[key]

    def read(self):
        return True, object()

    def release(self) -> None:
        self.released = True


def test_camera_reports_requested_and_actual_video_settings_and_releases() -> None:
    capture = Capture()
    source = OpenCVCameraSource(width=1280, height=720, fps=5, capture_factory=lambda _: capture)
    diagnostics = source.open()
    assert diagnostics.permission == "granted"
    assert (diagnostics.actual_width, diagnostics.actual_height, diagnostics.actual_fps) == (1280, 720, 5)
    source.close()
    assert capture.released is True


def test_camera_permission_denied_is_explicit() -> None:
    def denied(_: int):
        raise PermissionError("secret OS detail")

    with pytest.raises(CameraPermissionDenied, match="permission was denied"):
        OpenCVCameraSource(capture_factory=denied).open()


def test_camera_unavailable_is_explicit_and_capture_is_released() -> None:
    capture = Capture(opened=False)
    with pytest.raises(CameraUnavailable, match="unavailable"):
        OpenCVCameraSource(capture_factory=lambda _: capture).open()
    assert capture.released is True


def test_device_listing_does_not_read_frames_and_releases_every_probe() -> None:
    captures: list[Capture] = []
    def factory(index: int) -> Capture:
        capture = Capture(opened=index == 1)
        capture.read = lambda: pytest.fail("device listing must not read frames")
        captures.append(capture)
        return capture
    assert list_camera_devices(limit=3, capture_factory=factory) == [1]
    assert all(capture.released for capture in captures)

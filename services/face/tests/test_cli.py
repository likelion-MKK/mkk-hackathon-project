from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from mcm_face import cli
from mcm_face.camera import CameraDiagnostics, CameraUnavailable


class PreviewSource:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False
        self.read_count = 0

    def open(self) -> CameraDiagnostics:
        if self.error is not None:
            raise self.error
        return CameraDiagnostics(
            device_index=0,
            permission="granted",
            requested_width=640,
            requested_height=480,
            requested_fps=5.0,
            actual_width=640,
            actual_height=480,
            actual_fps=30.0,
        )

    def read(self) -> object:
        self.read_count += 1
        return object()

    def close(self) -> None:
        self.closed = True


def install_preview_fakes(
    monkeypatch: pytest.MonkeyPatch,
    source: PreviewSource,
) -> SimpleNamespace:
    fake_cv2 = SimpleNamespace(
        displayed=[],
        destroyed=False,
        imshow=lambda title, frame: fake_cv2.displayed.append((title, frame)),
        waitKey=lambda _: ord("q"),
        destroyAllWindows=lambda: setattr(fake_cv2, "destroyed", True),
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setattr(cli, "OpenCVCameraSource", lambda **_: source)
    monkeypatch.setattr(sys, "argv", ["camera-preview"])
    return fake_cv2


def test_camera_preview_is_opt_in_and_releases_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    source = PreviewSource()
    fake_cv2 = install_preview_fakes(monkeypatch, source)

    cli.camera_preview_main()

    assert source.read_count == 1
    assert source.closed is True
    assert len(fake_cv2.displayed) == 1
    assert fake_cv2.destroyed is True


def test_camera_preview_fails_closed_and_releases_unavailable_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = PreviewSource(error=CameraUnavailable("device missing"))
    fake_cv2 = install_preview_fakes(monkeypatch, source)

    with pytest.raises(SystemExit, match="camera_unavailable"):
        cli.camera_preview_main()

    assert source.read_count == 0
    assert source.closed is True
    assert fake_cv2.destroyed is True

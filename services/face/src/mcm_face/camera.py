"""Development-only OpenCV camera source with metadata-only diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


class CameraError(RuntimeError):
    reason = "camera_unavailable"


class CameraPermissionDenied(CameraError):
    reason = "camera_permission_denied"


class CameraUnavailable(CameraError):
    reason = "camera_unavailable"


@dataclass(frozen=True, slots=True)
class CameraDiagnostics:
    device_index: int
    permission: str
    requested_width: int
    requested_height: int
    requested_fps: float
    actual_width: int
    actual_height: int
    actual_fps: float

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


class OpenCVCameraSource:
    """Own one video-only camera; no audio API is imported or requested."""

    def __init__(
        self,
        *,
        device_index: int = 0,
        width: int = 640,
        height: int = 480,
        fps: float = 5.0,
        capture_factory: Callable[[int], Any] | None = None,
    ) -> None:
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self._factory = capture_factory
        self._capture: Any | None = None

    def open(self) -> CameraDiagnostics:
        if self._capture is not None:
            return self.diagnostics()
        try:
            if self._factory is None:
                try:
                    import cv2
                except ImportError as error:
                    raise CameraUnavailable("opencv camera runtime is unavailable") from error
                self._factory = cv2.VideoCapture
                properties = (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT, cv2.CAP_PROP_FPS)
            else:
                properties = (3, 4, 5)
            capture = self._factory(self.device_index)
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                raise CameraUnavailable(f"video device {self.device_index} is unavailable")
            capture.set(properties[0], self.width)
            capture.set(properties[1], self.height)
            capture.set(properties[2], self.fps)
            self._capture = capture
            self._properties = properties
            return self.diagnostics()
        except PermissionError as error:
            raise CameraPermissionDenied("camera permission was denied") from error

    def diagnostics(self) -> CameraDiagnostics:
        if self._capture is None:
            raise CameraUnavailable("camera is not open")
        width_prop, height_prop, fps_prop = self._properties
        return CameraDiagnostics(
            device_index=self.device_index, permission="granted",
            requested_width=self.width, requested_height=self.height, requested_fps=self.fps,
            actual_width=int(self._capture.get(width_prop)), actual_height=int(self._capture.get(height_prop)),
            actual_fps=float(self._capture.get(fps_prop)),
        )

    def read(self) -> Any:
        if self._capture is None:
            raise CameraUnavailable("camera is not open")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraUnavailable("camera did not return a video frame")
        return frame

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()

    def __enter__(self) -> "OpenCVCameraSource":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def list_camera_devices(*, limit: int = 5, capture_factory: Callable[[int], Any] | None = None) -> list[int]:
    """Probe only device availability; never read or persist a frame."""
    devices: list[int] = []
    for index in range(limit):
        source = OpenCVCameraSource(device_index=index, capture_factory=capture_factory)
        try:
            source.open()
            devices.append(index)
        except CameraError:
            pass
        finally:
            source.close()
    return devices

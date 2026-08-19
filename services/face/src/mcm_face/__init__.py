"""Public Face Adapter boundary for the MCM AI Lookbook Kiosk."""

from mcm_face.adapter import FaceAdapter
from mcm_face.adapters.fake import FakeFaceAdapter, FakeFaceScenario
from mcm_face.adapters.replay import (
    ReplayExhaustedError,
    ReplayFaceAdapter,
    ReplayFaceRecord,
)
from mcm_face.adapters.selected import FaceInference, SelectedFaceAdapter
from mcm_face.camera import (
    CameraDiagnostics,
    CameraPermissionDenied,
    CameraUnavailable,
    OpenCVCameraSource,
    list_camera_devices,
)
from mcm_face.models import AdapterMetadata, ExpressionSample, FaceFrameContext
from mcm_face.runtime import FaceRuntimeConfig, create_face_adapter
from mcm_face.worker import FaceWorker, WorkerObservation

__all__ = [
    "AdapterMetadata",
    "ExpressionSample",
    "FaceAdapter",
    "FakeFaceAdapter",
    "FakeFaceScenario",
    "FaceFrameContext",
    "FaceRuntimeConfig",
    "create_face_adapter",
    "FaceInference",
    "FaceWorker",
    "WorkerObservation",
    "SelectedFaceAdapter",
    "CameraDiagnostics",
    "CameraPermissionDenied",
    "CameraUnavailable",
    "OpenCVCameraSource",
    "list_camera_devices",
    "ReplayExhaustedError",
    "ReplayFaceAdapter",
    "ReplayFaceRecord",
]

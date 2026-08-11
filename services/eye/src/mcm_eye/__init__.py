"""Public types and adapters for the Eye service boundary."""

from .adapters import FakeEyeAdapter, FakeScenario
from .contracts import (
    AdapterMetadata,
    AdapterStateError,
    CalibrationRequest,
    CalibrationResult,
    EyeAdapter,
    GazeFrameContext,
    GazeSample,
)

__all__ = [
    "AdapterMetadata",
    "AdapterStateError",
    "CalibrationRequest",
    "CalibrationResult",
    "EyeAdapter",
    "FakeEyeAdapter",
    "FakeScenario",
    "GazeFrameContext",
    "GazeSample",
]

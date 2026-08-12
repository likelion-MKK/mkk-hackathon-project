"""Public types and adapters for the Eye service boundary."""

from .adapters import (
    FakeDeliveryScenario,
    FakeEyeAdapter,
    FakeGazeDelivery,
    FakeScenario,
)
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
    "FakeDeliveryScenario",
    "FakeEyeAdapter",
    "FakeGazeDelivery",
    "FakeScenario",
    "GazeFrameContext",
    "GazeSample",
]

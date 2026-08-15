"""D7-only in-process Vision Gateway harness.

This package is not the production Vision Stream v1 or a WSS implementation.
"""

from apps.vision_gateway.gateway import (
    D7GazeSample,
    DerivedObservation,
    FrameEnvelope,
    GatewayStateError,
    InProcessVisionGateway,
    ObservationJoiner,
    ReplayEyePort,
    SyntheticFrame,
    VisionHandshake,
)
from apps.vision_gateway.d8_signals import (
    D8_REACTION_TAXONOMY_VERSION,
    D8ReactionSignals,
    derive_d8_reaction_signals,
)
from apps.vision_gateway.runner import D7RunConfig, D7SessionRunner, HttpBackendPort

__all__ = [
    "D7GazeSample",
    "D7RunConfig",
    "D7SessionRunner",
    "D8_REACTION_TAXONOMY_VERSION",
    "D8ReactionSignals",
    "DerivedObservation",
    "FrameEnvelope",
    "GatewayStateError",
    "HttpBackendPort",
    "InProcessVisionGateway",
    "ObservationJoiner",
    "ReplayEyePort",
    "SyntheticFrame",
    "VisionHandshake",
    "derive_d8_reaction_signals",
]

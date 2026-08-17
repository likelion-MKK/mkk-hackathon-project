"""Vision Gateway package with lazy public exports.

The private Python 3.12 Eye worker imports the memory-only framing module but
does not run the Python 3.13 Face worker. Lazy exports keep that process
boundary dependency-free while preserving the package's existing public
imports for the D7/D8 harness.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "D7GazeSample": ("apps.vision_gateway.gateway", "D7GazeSample"),
    "D7RunConfig": ("apps.vision_gateway.runner", "D7RunConfig"),
    "D7SessionRunner": ("apps.vision_gateway.runner", "D7SessionRunner"),
    "D8_REACTION_TAXONOMY_VERSION": ("apps.vision_gateway.d8_signals", "D8_REACTION_TAXONOMY_VERSION"),
    "D8ReactionSignals": ("apps.vision_gateway.d8_signals", "D8ReactionSignals"),
    "DerivedObservation": ("apps.vision_gateway.gateway", "DerivedObservation"),
    "FrameEnvelope": ("apps.vision_gateway.gateway", "FrameEnvelope"),
    "GatewayStateError": ("apps.vision_gateway.gateway", "GatewayStateError"),
    "HttpBackendPort": ("apps.vision_gateway.runner", "HttpBackendPort"),
    "InProcessVisionGateway": ("apps.vision_gateway.gateway", "InProcessVisionGateway"),
    "LocalVisionTokenIssuer": ("apps.vision_gateway.server", "LocalVisionTokenIssuer"),
    "ObservationJoiner": ("apps.vision_gateway.gateway", "ObservationJoiner"),
    "ReplayEyePort": ("apps.vision_gateway.gateway", "ReplayEyePort"),
    "SyntheticFrame": ("apps.vision_gateway.gateway", "SyntheticFrame"),
    "VisionHandshake": ("apps.vision_gateway.gateway", "VisionHandshake"),
    "VisionStreamApp": ("apps.vision_gateway.server", "VisionStreamApp"),
    "derive_d8_reaction_signals": ("apps.vision_gateway.d8_signals", "derive_d8_reaction_signals"),
    "selected_face_worker_factory": ("apps.vision_gateway.server", "selected_face_worker_factory"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module = import_module(target[0])
    value = getattr(module, target[1])
    globals()[name] = value
    return value

"""Non-persistent D8 observable reaction diagnostics.

These values are not emotion labels, recommendation features, or Contract v1
events. They exist only while the development camera smoke session is running.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from apps.vision_gateway.gateway import DerivedObservation


D8_REACTION_TAXONOMY_VERSION = "d8-observable-reaction-signals-v1"


@dataclass(frozen=True, slots=True)
class D8ReactionSignals:
    taxonomy_version: str
    valid: bool
    scores: Mapping[str, float]
    reason: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scores", MappingProxyType(dict(self.scores)))

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "taxonomy_version": self.taxonomy_version,
            "valid": self.valid,
            "scores": dict(self.scores),
            "reason": self.reason,
        }


def derive_d8_reaction_signals(
    observation: DerivedObservation,
    attention: Mapping[str, object],
) -> D8ReactionSignals:
    """Combine valid Face and Eye/AOI measurements without persisting them."""

    face = observation.face
    gaze = observation.gaze
    if not face.valid:
        return _invalid(face.reason or "face_invalid")
    if not gaze.valid:
        return _invalid(gaze.reason or "gaze_invalid")
    candidates = attention.get("candidates")
    if attention.get("valid") is not True or not isinstance(candidates, Sequence):
        return _invalid(str(attention.get("reason") or "attention_invalid"))
    if len(candidates) != 1:
        return _invalid("ambiguous_attention")

    required = (
        "mouth_smile_left",
        "mouth_smile_right",
        "brow_inner_up",
        "brow_outer_up_left",
        "brow_outer_up_right",
        "eye_blink_left",
        "eye_blink_right",
    )
    if any(label not in face.scores for label in required):
        return _invalid("taxonomy_unavailable")

    smile_like = (face.scores["mouth_smile_left"] + face.scores["mouth_smile_right"]) / 2
    brow_raise_like = (
        face.scores["brow_inner_up"]
        + face.scores["brow_outer_up_left"]
        + face.scores["brow_outer_up_right"]
    ) / 3
    eye_blink_like = (face.scores["eye_blink_left"] + face.scores["eye_blink_right"]) / 2
    uncertain = 1.0 - min(face.quality, face.confidence, gaze.confidence)
    return D8ReactionSignals(
        taxonomy_version=D8_REACTION_TAXONOMY_VERSION,
        valid=True,
        scores={
            "smile_like": smile_like,
            "brow_raise_like": brow_raise_like,
            "eye_blink_like": eye_blink_like,
            "attention_like": gaze.confidence,
            "uncertain": max(0.0, min(1.0, uncertain)),
        },
        reason=None,
    )


def _invalid(reason: str) -> D8ReactionSignals:
    return D8ReactionSignals(
        taxonomy_version=D8_REACTION_TAXONOMY_VERSION,
        valid=False,
        scores={},
        reason=reason,
    )

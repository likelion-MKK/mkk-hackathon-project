"""Explicit D6 runtime selection. Fake is the safe default for CI and development."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Literal

from mcm_face.adapter import FaceAdapter
from mcm_face.adapters.fake import FakeFaceAdapter
from mcm_face.adapters.replay import ReplayFaceAdapter
from mcm_face.adapters.selected import SelectedFaceAdapter

FaceMode = Literal["fake", "replay", "selected"]


@dataclass(frozen=True, slots=True)
class FaceRuntimeConfig:
    mode: FaceMode = "fake"
    replay_fixture: Path | None = None
    model_path: Path | None = None

    @classmethod
    def from_env(cls) -> "FaceRuntimeConfig":
        mode = os.getenv("MCM_FACE_MODE", "fake")
        if mode not in ("fake", "replay", "selected"):
            raise ValueError("MCM_FACE_MODE must be fake, replay, or selected")
        replay = os.getenv("MCM_FACE_REPLAY_FIXTURE")
        model = os.getenv("MCM_FACE_MODEL_PATH")
        return cls(
            mode=mode,
            replay_fixture=Path(replay) if replay else None,
            model_path=Path(model) if model else None,
        )


def create_face_adapter(config: FaceRuntimeConfig) -> FaceAdapter[Any]:
    if config.mode == "fake":
        return FakeFaceAdapter()
    if config.mode == "replay":
        if config.replay_fixture is None:
            raise ValueError("replay mode requires MCM_FACE_REPLAY_FIXTURE")
        return ReplayFaceAdapter.from_fixture(config.replay_fixture)
    if config.model_path is None:
        raise ValueError("selected mode requires MCM_FACE_MODEL_PATH")
    return SelectedFaceAdapter(model_path=config.model_path)

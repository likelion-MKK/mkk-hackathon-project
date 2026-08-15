from pathlib import Path

import pytest

from mcm_face import FakeFaceAdapter, ReplayFaceAdapter
from mcm_face.runtime import FaceRuntimeConfig, create_face_adapter


def test_default_mode_stays_fake_when_environment_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCM_FACE_MODE", raising=False)
    monkeypatch.delenv("MCM_FACE_REPLAY_FIXTURE", raising=False)
    monkeypatch.delenv("MCM_FACE_MODEL_PATH", raising=False)
    config = FaceRuntimeConfig.from_env()
    assert config.mode == "fake"
    assert isinstance(create_face_adapter(config), FakeFaceAdapter)


def test_replay_mode_runs_without_camera_or_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Path(__file__).parent / "fixtures" / "expression-replay.d3.json"
    monkeypatch.setenv("MCM_FACE_MODE", "replay")
    monkeypatch.setenv("MCM_FACE_REPLAY_FIXTURE", str(fixture))
    adapter = create_face_adapter(FaceRuntimeConfig.from_env())
    assert isinstance(adapter, ReplayFaceAdapter)


def test_selected_mode_requires_explicit_model_path() -> None:
    with pytest.raises(ValueError, match="requires MCM_FACE_MODEL_PATH"):
        create_face_adapter(FaceRuntimeConfig(mode="selected"))

from __future__ import annotations

import gc
import json
import weakref
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mcm_face import FaceAdapter, FakeFaceAdapter, FakeFaceScenario, FrameContext


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXPRESSION_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "contracts/events/expression-sample.schema.json").read_text(
        encoding="utf-8"
    )
)
VALIDATOR = Draft202012Validator(EXPRESSION_SCHEMA)


def frame_context(*, sequence: int = 1, frame_id: str = "frame-0001") -> FrameContext:
    return FrameContext(
        session_id="session-test-001",
        sequence=sequence,
        frame_id=frame_id,
        captured_at_mono_ms=1234.5,
        video_id="lookbook-test-v1",
        video_time_ms=4200,
        playback_epoch=0,
    )


def initialized_adapter(
    scenario: FakeFaceScenario = FakeFaceScenario.VALID_FACE,
    *,
    seed: int = 7,
) -> FakeFaceAdapter:
    adapter = FakeFaceAdapter(seed=seed, scenario=scenario)
    adapter.initialize()
    adapter.warmup()
    return adapter


@pytest.mark.parametrize("scenario", list(FakeFaceScenario))
def test_every_scenario_matches_expression_sample_v1(
    scenario: FakeFaceScenario,
) -> None:
    payload = initialized_adapter(scenario).infer(object(), frame_context()).to_payload()

    errors = sorted(VALIDATOR.iter_errors(payload), key=lambda error: list(error.path))

    assert errors == []


@pytest.mark.parametrize(
    ("scenario", "face_detected", "face_count", "valid", "reason"),
    [
        (FakeFaceScenario.VALID_FACE, True, 1, True, None),
        (FakeFaceScenario.NO_FACE, False, 0, False, "no_face"),
        (FakeFaceScenario.MULTI_FACE, True, 2, False, "multi_face"),
        (FakeFaceScenario.UNKNOWN_LABEL, True, 1, True, None),
        (FakeFaceScenario.LOW_QUALITY, True, 1, False, "low_quality"),
        (FakeFaceScenario.TIMEOUT, False, 0, False, "timeout"),
    ],
)
def test_scenario_semantics_are_explicit(
    scenario: FakeFaceScenario,
    face_detected: bool,
    face_count: int,
    valid: bool,
    reason: str | None,
) -> None:
    sample = initialized_adapter(scenario).infer(object(), frame_context())

    assert sample.face_detected is face_detected
    assert sample.face_count == face_count
    assert sample.valid is valid
    assert sample.reason == reason
    assert bool(sample.scores) is valid


def test_unknown_label_is_not_guessed() -> None:
    sample = initialized_adapter(FakeFaceScenario.UNKNOWN_LABEL).infer(
        object(), frame_context()
    )

    assert set(sample.scores) == {"unknown"}


def test_same_seed_and_context_are_deterministic() -> None:
    context = frame_context()
    first = initialized_adapter(seed=42).infer(object(), context)
    second = initialized_adapter(seed=42).infer(object(), context)

    assert first == second
    assert first.to_payload() == second.to_payload()


def test_different_contexts_have_unique_event_ids_and_sequences() -> None:
    adapter = initialized_adapter(seed=42)
    first = adapter.infer(object(), frame_context(sequence=1, frame_id="frame-0001"))
    second = adapter.infer(object(), frame_context(sequence=2, frame_id="frame-0002"))

    assert first.event_id != second.event_id
    assert (first.sequence, second.sequence) == (1, 2)


def test_capture_context_is_preserved() -> None:
    context = frame_context(sequence=9, frame_id="frame-0099")
    sample = initialized_adapter().infer(object(), context)

    assert sample.session_id == context.session_id
    assert sample.sequence == context.sequence
    assert sample.frame_id == context.frame_id
    assert sample.captured_at_mono_ms == context.captured_at_mono_ms
    assert sample.video_id == context.video_id
    assert sample.video_time_ms == context.video_time_ms
    assert sample.playback_epoch == context.playback_epoch


def test_adapter_satisfies_public_protocol() -> None:
    assert isinstance(FakeFaceAdapter(), FaceAdapter)


def test_lifecycle_is_safe_and_explicit() -> None:
    adapter = FakeFaceAdapter()

    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.warmup()
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.infer(object(), frame_context())

    adapter.initialize()
    adapter.initialize()
    adapter.warmup()
    adapter.infer(object(), frame_context())

    adapter.dispose()
    adapter.dispose()
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.infer(object(), frame_context())

    adapter.initialize()
    adapter.infer(object(), frame_context())


def test_frame_reference_is_not_retained() -> None:
    class Frame:
        pass

    adapter = initialized_adapter()
    frame = Frame()
    frame_reference = weakref.ref(frame)

    adapter.infer(frame, frame_context())
    del frame
    gc.collect()

    assert frame_reference() is None


def test_invalid_scenario_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        FakeFaceAdapter(scenario="unsupported")

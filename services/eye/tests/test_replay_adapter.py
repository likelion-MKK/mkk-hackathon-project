from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mcm_eye import (
    CalibrationRequest,
    EyeAdapter,
    ReplayExhaustedError,
    ReplayEyeAdapter,
    ReplayGazeRecord,
)


@dataclass(frozen=True, slots=True)
class Context:
    session_id: str = "session-replay-001"
    sequence: int = 1
    frame_id: str = "frame-0001"
    captured_at_mono_ms: float = 1000.0
    video_id: str = "lookbook-replay-v1"
    video_time_ms: int = 1000
    playback_epoch: int = 0


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = Path(__file__).parent / "fixtures/gaze-replay.d3.json"
GAZE_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "contracts/events/gaze-sample.schema.json").read_text(
        encoding="utf-8"
    )
)
VALIDATOR = Draft202012Validator(GAZE_SCHEMA)


def initialized_adapter() -> ReplayEyeAdapter[object]:
    adapter = ReplayEyeAdapter.from_fixture(FIXTURE_PATH)
    adapter.initialize()
    adapter.warmup()
    return adapter


def contexts() -> list[Context]:
    times = (1000, 1100, 2000, 2100, 500, 600)
    epochs = (0, 0, 0, 0, 1, 1)
    return [
        Context(
            sequence=index,
            frame_id=f"frame-{index:04d}",
            captured_at_mono_ms=1000.0 + index * 33.3,
            video_time_ms=video_time,
            playback_epoch=epoch,
        )
        for index, (video_time, epoch) in enumerate(
            zip(times, epochs, strict=True), start=1
        )
    ]


def test_public_replay_adapter_matches_protocol_and_metadata() -> None:
    adapter = ReplayEyeAdapter.from_fixture(FIXTURE_PATH)

    assert isinstance(adapter, EyeAdapter)
    assert adapter.metadata().adapter_id == "replay-eye-adapter"
    assert adapter.metadata().model_id == "replay-gaze-fixture"
    assert adapter.metadata().model_revision == "eye-gaze-replay-d3-v1"
    assert adapter.metadata().calibration_supported is True


def test_replay_outputs_are_contract_valid_and_preserve_context() -> None:
    adapter = initialized_adapter()
    adapter.calibrate(CalibrationRequest("calibration-replay-001"))

    for context in contexts():
        sample = adapter.infer(object(), context)
        errors = sorted(VALIDATOR.iter_errors(sample.to_payload()), key=lambda error: list(error.path))
        assert errors == []
        assert sample.session_id == context.session_id
        assert sample.sequence == context.sequence
        assert sample.frame_id == context.frame_id
        assert sample.captured_at_mono_ms == context.captured_at_mono_ms
        assert sample.video_id == context.video_id
        assert sample.video_time_ms == context.video_time_ms
        assert sample.playback_epoch == context.playback_epoch
        assert sample.calibration_id == "calibration-replay-001"


def test_replay_records_are_consumed_in_order_without_inference() -> None:
    adapter = initialized_adapter()
    samples = [adapter.infer(object(), context) for context in contexts()]

    assert [(sample.screen_x_norm, sample.screen_y_norm) for sample in samples] == [
        (0.2, 0.5),
        (0.22, 0.5),
        (0.8, 0.5),
        (None, None),
        (0.2, 0.5),
        (0.8, 0.5),
    ]
    assert samples[3].valid is False
    assert samples[3].reason == "no_face"


def test_same_context_retry_is_idempotent_and_does_not_consume_next_record() -> None:
    adapter = initialized_adapter()
    context = contexts()[0]

    first = adapter.infer(object(), context)
    retried = adapter.infer(object(), context)
    second = adapter.infer(object(), contexts()[1])

    assert retried is first
    assert retried.to_payload() == first.to_payload()
    assert second.screen_x_norm == 0.22


def test_event_ids_are_deterministic_and_change_with_context() -> None:
    first = initialized_adapter().infer(object(), contexts()[0])
    second = initialized_adapter().infer(object(), contexts()[0])
    changed = initialized_adapter().infer(
        object(), replace(contexts()[0], frame_id="frame-changed")
    )

    assert first.event_id == second.event_id
    assert first.to_payload() == second.to_payload()
    assert first.event_id != changed.event_id


def test_replay_keeps_seek_epoch_and_rejects_new_context_after_exhaustion() -> None:
    adapter = initialized_adapter()
    replayed = [adapter.infer(object(), context) for context in contexts()]

    assert replayed[4].playback_epoch == 1
    assert replayed[4].video_time_ms == 500

    with pytest.raises(ReplayExhaustedError, match="exhausted after 6 records"):
        adapter.infer(object(), replace(contexts()[0], frame_id="frame-unseen"))


def test_replay_does_not_expose_frame_data() -> None:
    frame_marker = "DO-NOT-SERIALIZE-THIS-FRAME"
    sample = initialized_adapter().infer(frame_marker, contexts()[0])
    serialized = json.dumps(sample.to_payload())

    assert frame_marker not in serialized
    assert all(
        forbidden not in serialized.lower()
        for forbidden in ("raw_frame", "image", "base64", "embedding", "file_path")
    )


def test_fixture_record_validation_preserves_invalid_semantics() -> None:
    with pytest.raises(ValueError, match="valid gaze samples require both screen coordinates"):
        ReplayGazeRecord(
            screen_x_norm=None,
            screen_y_norm=None,
            valid=True,
            confidence=0.8,
            reason=None,
        )

    with pytest.raises(ValueError, match="invalid gaze samples cannot contain screen coordinates"):
        ReplayGazeRecord(
            screen_x_norm=0.5,
            screen_y_norm=0.5,
            valid=False,
            confidence=0.0,
            reason="no_face",
        )


@pytest.mark.parametrize("field", ["screen_x_norm", "screen_y_norm", "confidence"])
def test_replay_fixture_rejects_boolean_values_for_json_number_fields(
    tmp_path: Path, field: str
) -> None:
    record: dict[str, object] = {
        "screen_x_norm": 0.2,
        "screen_y_norm": 0.5,
        "valid": True,
        "confidence": 0.8,
        "reason": None,
    }
    record[field] = True
    fixture_path = tmp_path / f"boolean-{field}.json"
    fixture_path.write_text(
        json.dumps({"fixture_revision": "test-v1", "records": [record]}),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=rf"records\[0\] is invalid: {field} must be a JSON number",
    ):
        ReplayEyeAdapter.from_fixture(fixture_path)

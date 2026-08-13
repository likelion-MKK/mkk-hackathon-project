from __future__ import annotations

import gc
import json
import weakref
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mcm_face import (
    FaceAdapter,
    FaceFrameContext,
    ReplayExhaustedError,
    ReplayFaceAdapter,
    ReplayFaceRecord,
)
from mcm_face.adapters import (
    ReplayExhaustedError as AdaptersReplayExhaustedError,
)
from mcm_face.adapters import ReplayFaceAdapter as AdaptersReplayFaceAdapter
from mcm_face.adapters import ReplayFaceRecord as AdaptersReplayFaceRecord


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = Path(__file__).parent / "fixtures/expression-replay.d3.json"
EXPRESSION_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "contracts/events/expression-sample.schema.json").read_text(
        encoding="utf-8"
    )
)
VALIDATOR = Draft202012Validator(EXPRESSION_SCHEMA)
ALLOWED_FIXTURE_FIELDS = {"fixture_revision", "records"}
ALLOWED_RECORD_FIELDS = {
    "face_detected",
    "face_count",
    "scores",
    "quality",
    "valid",
    "confidence",
    "reason",
}


@dataclass(frozen=True, slots=True)
class KioskContext:
    session_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int


def replay_contexts() -> list[KioskContext]:
    video_times = (1000, 2000, 3000, 4000, 500)
    epochs = (0, 0, 0, 0, 1)
    return [
        KioskContext(
            session_id="session-replay-001",
            sequence=index,
            frame_id=f"frame-{index:04d}",
            captured_at_mono_ms=1000.0 + (index * 33.3),
            video_id="lookbook-replay-v1",
            video_time_ms=video_time,
            playback_epoch=epoch,
        )
        for index, (video_time, epoch) in enumerate(
            zip(video_times, epochs, strict=True), start=1
        )
    ]


def initialized_adapter() -> ReplayFaceAdapter[object]:
    adapter = ReplayFaceAdapter.from_fixture(FIXTURE_PATH)
    adapter.initialize()
    adapter.warmup()
    return adapter


def replay_all(adapter: ReplayFaceAdapter[object]) -> list[object]:
    return [adapter.infer(object(), context) for context in replay_contexts()]


def valid_record() -> ReplayFaceRecord:
    return ReplayFaceRecord(
        face_detected=True,
        face_count=1,
        scores={"unknown_fixture_label": 0.62},
        quality=0.81,
        valid=True,
        confidence=0.76,
        reason=None,
    )


def write_fixture(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def fixture_document() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_public_types_are_exported_and_protocol_compatible() -> None:
    adapter = ReplayFaceAdapter.from_fixture(FIXTURE_PATH)

    assert ReplayFaceAdapter is AdaptersReplayFaceAdapter
    assert ReplayFaceRecord is AdaptersReplayFaceRecord
    assert ReplayExhaustedError is AdaptersReplayExhaustedError
    assert isinstance(adapter, FaceAdapter)
    assert isinstance(replay_contexts()[0], FaceFrameContext)


def test_metadata_tracks_fixture_revision_and_labels() -> None:
    metadata = ReplayFaceAdapter.from_fixture(FIXTURE_PATH).metadata()

    assert metadata.adapter_id == "replay-face-adapter"
    assert metadata.model_id == "replay-expression-fixture"
    assert metadata.model_revision == "face-expression-replay-d3-v1"
    assert metadata.taxonomy_version == "replay-face-taxonomy-v1"
    assert metadata.runtime == "python"
    assert metadata.source_labels == ("brow_raise_like", "smile_like")


def test_every_replay_output_matches_expression_sample_v1() -> None:
    for sample in replay_all(initialized_adapter()):
        errors = sorted(
            VALIDATOR.iter_errors(sample.to_payload()), key=lambda error: list(error.path)
        )
        assert errors == []


def test_records_are_consumed_in_fixture_order_without_score_inference() -> None:
    samples = replay_all(initialized_adapter())

    assert [dict(sample.scores) for sample in samples] == [
        {"brow_raise_like": 0.28, "smile_like": 0.72},
        {},
        {},
        {"brow_raise_like": 0.36, "smile_like": 0.64},
        {"brow_raise_like": 0.41, "smile_like": 0.59},
    ]


def test_same_fixture_and_context_sequence_are_deterministic() -> None:
    first = [sample.to_payload() for sample in replay_all(initialized_adapter())]
    second = [sample.to_payload() for sample in replay_all(initialized_adapter())]

    assert first == second


def test_event_ids_are_unique_by_record_and_context() -> None:
    samples = replay_all(initialized_adapter())

    assert len({sample.event_id for sample in samples}) == len(samples)

    changed_context = replace(replay_contexts()[0], frame_id="frame-changed")
    changed_adapter = initialized_adapter()
    changed_sample = changed_adapter.infer(object(), changed_context)
    assert changed_sample.event_id != samples[0].event_id


def test_all_capture_context_fields_are_preserved() -> None:
    contexts = replay_contexts()
    samples = replay_all(initialized_adapter())

    for context, sample in zip(contexts, samples, strict=True):
        assert sample.session_id == context.session_id
        assert sample.sequence == context.sequence
        assert sample.frame_id == context.frame_id
        assert sample.captured_at_mono_ms == context.captured_at_mono_ms
        assert sample.video_id == context.video_id
        assert sample.video_time_ms == context.video_time_ms
        assert sample.playback_epoch == context.playback_epoch


def test_consecutive_no_face_is_invalid_observation_not_neutral() -> None:
    samples = replay_all(initialized_adapter())

    first_no_face, second_no_face = samples[1:3]
    for sample, quality, confidence in (
        (first_no_face, 0.22, 0.18),
        (second_no_face, 0.35, 0.25),
    ):
        assert sample.face_detected is False
        assert sample.face_count == 0
        assert sample.valid is False
        assert dict(sample.scores) == {}
        assert sample.reason == "no_face"
        assert sample.quality == quality
        assert sample.confidence == confidence

    assert dict(samples[0].scores)
    assert dict(samples[3].scores) == {
        "brow_raise_like": 0.36,
        "smile_like": 0.64,
    }
    assert samples[3].valid is True
    assert samples[3].reason is None


def test_playback_epoch_and_video_time_rewind_are_preserved() -> None:
    samples = replay_all(initialized_adapter())

    before_seek, after_seek = samples[3:5]
    assert before_seek.playback_epoch == 0
    assert before_seek.video_time_ms == 4000
    assert after_seek.playback_epoch == 1
    assert after_seek.video_time_ms == 500
    assert after_seek.video_time_ms < before_seek.video_time_ms


def test_exhaustion_does_not_loop_and_is_repeatable() -> None:
    adapter = initialized_adapter()
    replay_all(adapter)

    with pytest.raises(ReplayExhaustedError, match="exhausted after 5 records"):
        adapter.infer(object(), replay_contexts()[0])
    with pytest.raises(ReplayExhaustedError, match="exhausted after 5 records"):
        adapter.infer(object(), replay_contexts()[0])


def test_lifecycle_and_cursor_reset_rules_are_explicit() -> None:
    adapter = ReplayFaceAdapter.from_fixture(FIXTURE_PATH)
    first_context, second_context = replay_contexts()[:2]

    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.warmup()
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.infer(object(), first_context)

    adapter.initialize()
    first = adapter.infer(object(), first_context)
    adapter.initialize()
    second = adapter.infer(object(), second_context)
    assert first.valid is True
    assert second.reason == "no_face"

    adapter.dispose()
    adapter.dispose()
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.warmup()
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.infer(object(), first_context)

    adapter.initialize()
    restarted = adapter.infer(object(), first_context)
    assert restarted == first


def test_repeated_initialize_does_not_reset_exhausted_cursor() -> None:
    adapter = initialized_adapter()
    replay_all(adapter)

    adapter.initialize()
    with pytest.raises(ReplayExhaustedError):
        adapter.infer(object(), replay_contexts()[0])

    adapter.dispose()
    adapter.initialize()
    assert adapter.infer(object(), replay_contexts()[0]).valid is True


def test_context_validation_failure_does_not_consume_record() -> None:
    adapter = initialized_adapter()
    valid_context = replay_contexts()[0]
    invalid_context = replace(valid_context, sequence=-1)

    with pytest.raises(ValueError, match="sequence"):
        adapter.infer(object(), invalid_context)

    sample = adapter.infer(object(), valid_context)
    assert dict(sample.scores) == {"brow_raise_like": 0.28, "smile_like": 0.72}


def test_unknown_fixture_label_is_preserved_without_guessing() -> None:
    adapter = ReplayFaceAdapter[object](
        fixture_revision="custom-replay-v1", records=[valid_record()]
    )
    adapter.initialize()

    sample = adapter.infer(object(), replay_contexts()[0])
    assert dict(sample.scores) == {"unknown_fixture_label": 0.62}


def test_record_scores_are_defensively_copied() -> None:
    scores = {"unknown_fixture_label": 0.62}
    record = ReplayFaceRecord(
        face_detected=True,
        face_count=1,
        scores=scores,
        quality=0.81,
        valid=True,
        confidence=0.76,
        reason=None,
    )
    scores["unknown_fixture_label"] = 0.1

    assert dict(record.scores) == {"unknown_fixture_label": 0.62}
    with pytest.raises(TypeError):
        record.scores["new_label"] = 0.2  # type: ignore[index]


@pytest.mark.parametrize(
    "record",
    [
        ReplayFaceRecord(
            face_detected=False,
            face_count=0,
            scores={},
            quality=0.2,
            valid=False,
            confidence=0.1,
            reason="timeout",
        ),
    ],
)
def test_non_no_face_invalid_reason_remains_distinct(record: ReplayFaceRecord) -> None:
    assert record.reason == "timeout"


@pytest.mark.parametrize(
    "changes",
    [
        {"face_detected": True, "face_count": 1},
        {"scores": {"neutral": 1.0}},
        {"valid": True},
    ],
)
def test_invalid_no_face_combinations_are_rejected(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "face_detected": False,
        "face_count": 0,
        "scores": {},
        "quality": 0.2,
        "valid": False,
        "confidence": 0.1,
        "reason": "no_face",
    }
    values.update(changes)

    with pytest.raises(ValueError):
        ReplayFaceRecord(**values)  # type: ignore[arg-type]


def test_missing_fixture_file_is_rejected_without_model_execution(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not read replay fixture"):
        ReplayFaceAdapter.from_fixture(tmp_path / "missing.json")


@pytest.mark.parametrize("document", [[], "fixture", 7, None])
def test_non_object_fixture_root_is_rejected(tmp_path: Path, document: object) -> None:
    path = write_fixture(tmp_path / "fixture.json", document)

    with pytest.raises(ValueError, match="root must be an object"):
        ReplayFaceAdapter.from_fixture(path)


def test_empty_records_are_rejected(tmp_path: Path) -> None:
    path = write_fixture(
        tmp_path / "fixture.json",
        {"fixture_revision": "empty-v1", "records": []},
    )

    with pytest.raises(ValueError, match="non-empty array"):
        ReplayFaceAdapter.from_fixture(path)


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("root", "session_id"),
        ("record", "frame_id"),
        ("record", "producer_id"),
        ("record", "image_base64"),
    ],
)
def test_context_metadata_and_media_fields_are_rejected(
    tmp_path: Path, location: str, field: str
) -> None:
    document = fixture_document()
    if location == "root":
        document[field] = "forbidden"
    else:
        records = document["records"]
        assert isinstance(records, list)
        records[0][field] = "forbidden"
    path = write_fixture(tmp_path / "fixture.json", document)

    with pytest.raises(ValueError, match="unexpected fields") as error:
        ReplayFaceAdapter.from_fixture(path)
    assert "forbidden" not in str(error.value)


def test_missing_record_field_reports_index_without_record_contents(tmp_path: Path) -> None:
    document = fixture_document()
    records = document["records"]
    assert isinstance(records, list)
    del records[2]["reason"]
    path = write_fixture(tmp_path / "fixture.json", document)

    with pytest.raises(ValueError, match=r"records\[2\] is missing fields: reason"):
        ReplayFaceAdapter.from_fixture(path)


def test_invalid_record_reports_index_without_serializing_record(tmp_path: Path) -> None:
    document = fixture_document()
    records = document["records"]
    assert isinstance(records, list)
    records[1]["confidence"] = 2.0
    records[1]["secret_marker"] = "must-not-appear"
    del records[1]["secret_marker"]
    path = write_fixture(tmp_path / "fixture.json", document)

    with pytest.raises(ValueError, match=r"records\[1\] is invalid") as error:
        ReplayFaceAdapter.from_fixture(path)
    assert "must-not-appear" not in str(error.value)
    assert "confidence must be between" in str(error.value)


def test_fixture_contains_only_derived_observation_fields() -> None:
    document = fixture_document()

    assert set(document) == ALLOWED_FIXTURE_FIELDS
    records = document["records"]
    assert isinstance(records, list)
    assert records
    assert all(set(record) == ALLOWED_RECORD_FIELDS for record in records)

    serialized = FIXTURE_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("session_id", "frame_id", "video_id", "base64", "embedding"):
        assert forbidden not in serialized


def test_frame_reference_is_not_retained_or_exposed_on_success() -> None:
    class Frame:
        def __repr__(self) -> str:
            return "frame-object-secret-must-not-appear"

    adapter = initialized_adapter()
    frame = Frame()
    frame_reference = weakref.ref(frame)

    payload = adapter.infer(frame, replay_contexts()[0]).to_payload()
    del frame
    gc.collect()

    assert frame_reference() is None
    assert "frame-object-secret-must-not-appear" not in repr(payload)


def test_frame_is_not_in_exhaustion_error() -> None:
    class SecretFrame:
        def __repr__(self) -> str:
            return "frame-secret-must-not-appear"

    adapter = initialized_adapter()
    replay_all(adapter)

    with pytest.raises(ReplayExhaustedError) as error:
        adapter.infer(SecretFrame(), replay_contexts()[0])
    assert "frame-secret-must-not-appear" not in str(error.value)

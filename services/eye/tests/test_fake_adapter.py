from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mcm_eye import (
    AdapterStateError,
    CalibrationRequest,
    EyeAdapter,
    FakeEyeAdapter,
    FakeScenario,
)


@dataclass(frozen=True, slots=True)
class Context:
    session_id: str = "session-test-001"
    sequence: int = 4
    frame_id: str = "frame-00421"
    captured_at_mono_ms: float = 143220.4
    video_id: str = "mcm-lookbook-example-v1"
    video_time_ms: int = 4200
    playback_epoch: int = 0


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GAZE_SCHEMA_PATH = REPOSITORY_ROOT / "contracts" / "events" / "gaze-sample.schema.json"
GAZE_SCHEMA = json.loads(GAZE_SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(GAZE_SCHEMA)


def initialized_adapter(
    scenario: FakeScenario = FakeScenario.NORMAL,
    *,
    seed: int = 17,
) -> FakeEyeAdapter[object]:
    adapter = FakeEyeAdapter[object](scenario, seed=seed)
    adapter.initialize()
    return adapter


def assert_contract_valid(payload: dict[str, object]) -> None:
    errors = sorted(VALIDATOR.iter_errors(payload), key=lambda error: list(error.path))
    assert errors == []


def test_fake_adapter_satisfies_protocol_and_metadata() -> None:
    adapter = FakeEyeAdapter[object]()

    assert isinstance(adapter, EyeAdapter)
    assert adapter.metadata().adapter_id == "fake-eye-adapter"
    assert adapter.metadata().model_id == "fake-eye-model"
    assert adapter.metadata().model_revision == "fixture-v1"
    assert adapter.metadata().runtime == "python"
    assert adapter.metadata().calibration_supported is True


def test_lifecycle_is_idempotent_and_requires_initialization() -> None:
    adapter = FakeEyeAdapter[object]()
    context = Context()

    with pytest.raises(AdapterStateError):
        adapter.infer(object(), context)

    adapter.initialize()
    adapter.initialize()
    adapter.warmup()
    adapter.dispose()
    adapter.dispose()

    with pytest.raises(AdapterStateError):
        adapter.infer(object(), context)

    adapter.initialize()
    assert adapter.infer(object(), context).valid is True


def test_calibration_id_is_used_by_following_samples() -> None:
    adapter = initialized_adapter()

    result = adapter.calibrate(CalibrationRequest("calibration-test-001"))
    sample = adapter.infer(object(), Context())

    assert result.valid is True
    assert result.reason is None
    assert sample.calibration_id == "calibration-test-001"


def test_normal_sample_preserves_capture_context_and_contract() -> None:
    context = Context()
    sample = initialized_adapter().infer(object(), context)
    payload = sample.to_payload()

    assert payload["session_id"] == context.session_id
    assert payload["sequence"] == context.sequence
    assert payload["frame_id"] == context.frame_id
    assert payload["captured_at_mono_ms"] == context.captured_at_mono_ms
    assert payload["video_id"] == context.video_id
    assert payload["video_time_ms"] == context.video_time_ms
    assert payload["playback_epoch"] == context.playback_epoch
    assert 0.0 <= payload["screen_x_norm"] <= 1.0
    assert 0.0 <= payload["screen_y_norm"] <= 1.0
    assert payload["confidence"] == 0.9
    assert payload["valid"] is True
    assert payload["reason"] is None
    assert "adapter_id" not in payload
    assert_contract_valid(payload)


def test_same_input_seed_and_scenario_are_fully_deterministic() -> None:
    context = Context()
    first = initialized_adapter(seed=99).infer(object(), context).to_payload()
    second = initialized_adapter(seed=99).infer(object(), context).to_payload()
    different_seed = initialized_adapter(seed=100).infer(object(), context).to_payload()

    assert first == second
    assert first["event_id"] != different_seed["event_id"]
    assert first["screen_x_norm"] != different_seed["screen_x_norm"]


@pytest.mark.parametrize(
    ("scenario", "confidence", "reason"),
    [
        (FakeScenario.NO_FACE, 0.0, "no_face"),
        (FakeScenario.LOW_CONFIDENCE, 0.2, "low_confidence"),
        (FakeScenario.OUTSIDE_VIEWPORT, 0.0, "outside_viewport"),
    ],
)
def test_invalid_scenarios_omit_coordinates(
    scenario: FakeScenario,
    confidence: float,
    reason: str,
) -> None:
    payload = initialized_adapter(scenario).infer(object(), Context()).to_payload()

    assert payload["valid"] is False
    assert payload["confidence"] == confidence
    assert payload["reason"] == reason
    assert "screen_x_norm" not in payload
    assert "screen_y_norm" not in payload
    assert_contract_valid(payload)


def test_delayed_scenario_uses_injected_sleeper_without_real_wait() -> None:
    sleep_calls: list[float] = []
    adapter = FakeEyeAdapter[object](
        FakeScenario.DELAYED,
        seed=17,
        delay_ms=125,
        sleeper=sleep_calls.append,
    )
    adapter.initialize()

    payload = adapter.infer(object(), Context()).to_payload()

    assert sleep_calls == [0.125]
    assert_contract_valid(payload)


def test_out_of_order_scenario_swaps_adjacent_sequences() -> None:
    adapter = initialized_adapter(FakeScenario.OUT_OF_ORDER)

    first = adapter.infer(object(), replace(Context(), sequence=0)).to_payload()
    second = adapter.infer(object(), replace(Context(), sequence=1)).to_payload()

    assert first["sequence"] == 1
    assert second["sequence"] == 0
    assert_contract_valid(first)
    assert_contract_valid(second)


def test_payload_does_not_expose_raw_frame_or_forbidden_fields() -> None:
    frame_marker = "DO-NOT-SERIALIZE-THIS-FRAME"
    payload = initialized_adapter().infer(frame_marker, Context()).to_payload()
    serialized = json.dumps(payload)
    forbidden_terms = ("raw_frame", "image", "base64", "embedding", "file_path")

    assert frame_marker not in serialized
    assert all(term not in {key.lower() for key in payload} for term in forbidden_terms)
    assert_contract_valid(payload)

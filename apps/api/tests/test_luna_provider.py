from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from apps.api.app.v2_central import (
    CentralModelError,
    DeterministicCentralStub,
    OpenAILunaCentralClient,
    validate_central_output,
)
from apps.api.app.v2_models import FrameObservationV2
from apps.api.scripts.luna_canary import (
    EXPECTED_PRODUCT_ID,
    build_canary_request,
    main as canary_main,
)
from apps.api.scripts import luna_canary


MODEL_ID = "gpt-5.6-luna"
API_KEY = "test-api-key-never-log"


def _completed_envelope(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "completed",
        "model": MODEL_ID,
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(output, ensure_ascii=False),
                    }
                ],
            }
        ],
    }


def _schema_keywords(schema: object) -> set[str]:
    keywords: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "properties" and isinstance(child, dict):
                    keywords.add(key)
                    for property_schema in child.values():
                        visit(property_schema)
                else:
                    keywords.add(key)
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return keywords


def _client() -> OpenAILunaCentralClient:
    return OpenAILunaCentralClient(
        endpoint="https://api.openai.com/v1/responses",
        api_key=API_KEY,
        model_id=MODEL_ID,
        reasoning_effort="max",
        reasoning_context="current_turn",
        prompt_version="central-recommender-ko-v6",
    )


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    original_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def async_client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        assert not args
        assert kwargs == {"timeout": None, "follow_redirects": False}
        return original_async_client(
            transport=transport,
            timeout=None,
            follow_redirects=False,
        )

    monkeypatch.setattr(httpx, "AsyncClient", async_client_factory)


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response | Callable[[httpx.Request], httpx.Response],
    request_model: object | None = None,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return response(request) if callable(response) else response

    _install_transport(monkeypatch, handler)
    return asyncio.run(_client().recommend_async(request_model or build_canary_request()))


def test_luna_provider_sends_canonical_variant_c_and_accepts_one_output_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_model = build_canary_request()
    valid_output = DeterministicCentralStub().recommend(request_model)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completed_envelope(valid_output))

    raw_output = _invoke(monkeypatch, handler)
    decision = validate_central_output(raw_output, request=request_model)

    assert decision.product_id == EXPECTED_PRODUCT_ID
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["authorization"] == f"Bearer {API_KEY}"

    body = captured["body"]
    assert body["model"] == MODEL_ID
    assert body["reasoning"] == {"effort": "max", "context": "current_turn"}
    assert body["store"] is False
    assert "tools" not in body
    assert "conversation" not in body
    assert "max_output_tokens" not in body
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert _schema_keywords(body["text"]["format"]["schema"]) <= {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
    }

    assert [item["role"] for item in body["input"]] == ["system", "user"]
    variant_c = json.loads(body["input"][1]["content"])
    assert variant_c["evidence"]["input_variant"] == "C"
    assert len(variant_c["products"]) == 10
    assert "evidence" in variant_c


@pytest.mark.parametrize("status_code", [429, 500])
def test_luna_provider_fails_closed_without_retry_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text="provider-raw-marker")

    with pytest.raises(CentralModelError) as caught:
        _invoke(monkeypatch, handler)

    assert calls == 1
    assert caught.value.reason_code == "model_unavailable"
    assert caught.value.provider_diagnostic_code == f"provider_http_{status_code}"
    assert API_KEY not in str(caught.value)
    assert "provider-raw-marker" not in str(caught.value)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_luna_provider_preserves_only_safe_4xx_status_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    with pytest.raises(CentralModelError) as caught:
        _invoke(
            monkeypatch,
            httpx.Response(status_code, text="provider-sensitive-error-body"),
        )

    assert caught.value.reason_code == "model_unavailable"
    assert caught.value.provider_diagnostic_code == f"provider_http_{status_code}"
    assert "provider-sensitive-error-body" not in str(caught.value)


def test_luna_provider_extracts_only_allowlisted_error_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        400,
        json={
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_json_schema",
                "param": "text.format.schema.properties.evidence",
                "message": f"sensitive provider text {API_KEY}",
            }
        },
    )

    with pytest.raises(CentralModelError) as caught:
        _invoke(monkeypatch, response)

    assert caught.value.provider_error_type == "invalid_request_error"
    assert caught.value.provider_error_code == "invalid_json_schema"
    assert caught.value.provider_error_param == "text.format.schema.properties.evidence"
    assert API_KEY not in str(caught.value)


def test_luna_provider_drops_unsafe_or_oversized_error_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        400,
        json={
            "error": {
                "type": "invalid request with spaces",
                "code": "x" * 121,
                "param": "input;secret=do-not-print",
                "message": "x" * (8 * 1024),
            }
        },
    )

    with pytest.raises(CentralModelError) as caught:
        _invoke(monkeypatch, response)

    assert caught.value.provider_error_type is None
    assert caught.value.provider_error_code is None
    assert caught.value.provider_error_param is None


@pytest.mark.parametrize(
    "envelope",
    [
        {"status": "incomplete", "model": MODEL_ID, "output": []},
        {
            "status": "completed",
            "model": MODEL_ID,
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
        },
        {
            "status": "completed",
            "model": MODEL_ID,
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "{}"},
                        {"type": "output_text", "text": "{}"},
                    ],
                }
            ],
        },
    ],
    ids=["incomplete", "refusal", "multiple-output-text"],
)
def test_luna_provider_rejects_non_completed_or_ambiguous_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    envelope: dict[str, Any],
) -> None:
    with pytest.raises(CentralModelError) as caught:
        _invoke(monkeypatch, httpx.Response(200, json=envelope))

    assert caught.value.reason_code == "invalid_model_output"


def test_luna_provider_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CentralModelError) as caught:
        _invoke(monkeypatch, httpx.Response(200, content=b"not-json"))

    assert caught.value.reason_code == "invalid_model_output"


def test_luna_provider_rejects_invalid_output_text_json(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = {
        "status": "completed",
        "model": MODEL_ID,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "not-json"}],
            }
        ],
    }

    with pytest.raises(CentralModelError) as caught:
        _invoke(monkeypatch, httpx.Response(200, json=envelope))

    assert caught.value.reason_code == "invalid_model_output"


def test_luna_provider_does_not_cap_output_text_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    request_model = build_canary_request()
    valid_output = DeterministicCentralStub().recommend(request_model)
    text = (" " * (16 * 1024 + 1)) + json.dumps(valid_output, ensure_ascii=False)
    envelope = _completed_envelope(valid_output)
    envelope["output"][0]["content"][0]["text"] = text

    raw_output = _invoke(monkeypatch, httpx.Response(200, json=envelope))
    assert validate_central_output(raw_output, request=request_model).product_id == EXPECTED_PRODUCT_ID


def test_luna_provider_does_not_cap_response_envelope_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_model = build_canary_request()
    valid_output = DeterministicCentralStub().recommend(request_model)
    envelope = _completed_envelope(valid_output)
    envelope["unused_provider_metadata"] = "x" * (1024 * 1024 + 1)

    raw_output = _invoke(monkeypatch, httpx.Response(200, json=envelope))
    assert validate_central_output(raw_output, request=request_model).product_id == EXPECTED_PRODUCT_ID


def test_luna_provider_accepts_low_signal_variant_b_with_real_frame_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_model = build_canary_request()
    frame = FrameObservationV2.model_validate(
        {
            "schema_version": "2.0",
            "frame_id": "frame-low-signal-0001",
            "sequence": 0,
            "captured_at_mono_ms": 100.0,
            "session_offset_ms": 100.0,
            "video_time_ms": 100,
            "playback_epoch": 0,
            "gaze": None,
            "gaze_reason": "gaze_unavailable",
            "expression": None,
            "expression_reason": "not_observed",
            "attention": None,
            "attention_reason": "gaze_unavailable",
            "derived": None,
            "derived_reason": "invalid_or_missing_modality",
        }
    )
    evidence = request_model.evidence.model_copy(
        update={
            "input_variant": "B",
            "evidence_windows": None,
            "timeline": [frame],
            "data_quality": request_model.evidence.data_quality.model_copy(
                update={
                    "gaze_valid_ratio": 0.0,
                    "expression_valid_ratio": 0.0,
                    "matched_frame_ratio": 0.0,
                    "ambiguous_product_ratio": 0.0,
                }
            ),
        }
    )
    request_model = request_model.model_copy(update={"evidence": evidence})
    product = request_model.products[0]
    low_signal_output = {
        "product_id": product.product_id,
        "reason": "유효 좌표가 없어 결측 상태와 검수된 상품 태그만 사용했습니다.",
        "reason_codes": ["catalog_tag_alignment"],
        "evidence": [
            {
                "code": "data_quality",
                "product_id": product.product_id,
                "evidence_refs": [{"kind": "frame", "ref_id": frame.frame_id}],
                "statement": "실제 관찰 frame의 gaze_unavailable 상태를 유지했습니다.",
            }
        ],
        "style": {
            "matched_tags": [product.controlled_tags[0]],
            "summary": "검수된 상품 태그 기반 저신호 선택",
        },
        "exploration_tendency_code": "focused_single_product",
    }
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completed_envelope(low_signal_output))

    raw_output = _invoke(monkeypatch, handler, request_model)
    output = validate_central_output(raw_output, request=request_model)
    assert output.product_id == product.product_id
    schema = captured["body"]["text"]["format"]["schema"]
    refs = schema["properties"]["evidence"]["items"]["properties"]["evidence_refs"]
    assert refs["items"]["properties"]["kind"]["enum"] == ["frame"]
    assert refs["items"]["properties"]["ref_id"]["enum"] == [frame.frame_id]


def test_canary_fixture_is_synthetic_variant_c_with_ten_products() -> None:
    request = build_canary_request()

    assert len(request.products) == 10
    assert request.evidence.session_id == request.session_id
    assert request.evidence.catalog_version
    assert EXPECTED_PRODUCT_ID in {product.product_id for product in request.products}


def test_canary_requires_all_three_live_safety_flags(capsys: pytest.CaptureFixture[str]) -> None:
    assert canary_main(["--max-calls", "1"]) == 2
    result = json.loads(capsys.readouterr().out)

    assert result == {
        "status": "blocked",
        "reason_code": "explicit_live_synthetic_single_call_required",
        "live_call_count": 0,
    }


def test_canary_prints_safe_provider_status_without_error_body(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _client()

    async def fail_with_safe_status(_: object, __: object) -> object:
        raise CentralModelError(
            "model_unavailable",
            "sanitized failure",
            provider_diagnostic_code="provider_http_401",
            provider_error_type="invalid_request_error",
            provider_error_code="invalid_json_schema",
            provider_error_param="text.format.schema",
        )

    monkeypatch.setattr(luna_canary, "configured_central_client", lambda: client)
    monkeypatch.setattr(OpenAILunaCentralClient, "recommend_async", fail_with_safe_status)

    assert canary_main(["--live", "--synthetic-only", "--max-calls", "1"]) == 1
    result = json.loads(capsys.readouterr().out)

    assert result == {
        "status": "failed",
        "reason_code": "model_unavailable",
        "live_call_count": 1,
        "provider_diagnostic_code": "provider_http_401",
        "provider_error_type": "invalid_request_error",
        "provider_error_code": "invalid_json_schema",
        "provider_error_param": "text.format.schema",
    }

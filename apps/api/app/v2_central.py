"""Central model ports, Luna provider adapter and strict output gate."""

from __future__ import annotations

import asyncio
import inspect
import json
import hashlib
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError

from apps.api.app.v2_models import (
    CentralRecommendationOutputV2,
    CentralRecommendationRequestV2,
)


MAX_MODEL_RESPONSE_BYTES = 64 * 1024
MAX_PROVIDER_RESPONSE_ENVELOPE_BYTES = 1 * 1024 * 1024
MAX_PROVIDER_OUTPUT_TEXT_BYTES = 16 * 1024
MAX_PROVIDER_ERROR_BODY_BYTES = 8 * 1024
APPROVED_PROMPT_VERSION = "central-recommender-ko-v4"
LUNA_MODEL_ID = "gpt-5.6-luna"
LUNA_REASONING_EFFORT = "max"
LUNA_REASONING_CONTEXT = "current_turn"
LUNA_INPUT_VARIANT = "C"
LUNA_RESPONSES_URL = "https://api.openai.com/v1/responses"
LUNA_PROMPT_SHA256 = "bc1186d1e3f1e908e8a865ae8f89c35f7e6c3172ccd010018101141d5a350149"
LUNA_PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "experiments"
    / "recommendation"
    / "prompts"
    / "central-recommender.ko.v4.txt"
)
_SAFE_PROVIDER_ERROR_TOKEN = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_SAFE_PROVIDER_ERROR_PARAM = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,200}$")
_DIAGNOSIS_TERMS = (
    "성격",
    "심리",
    "감정",
    "우울",
    "불안",
    "충동",
    "내향",
    "외향",
    "구매 의도",
    "personality",
    "psycholog",
    "emotion",
    "depress",
    "anxious",
    "anxiety",
    "introvert",
    "extrovert",
    "purchase intent",
    "행복",
    "슬픔",
    "슬퍼",
    "분노",
    "화가 났",
    "스트레스",
    "호감",
    "좋아한다",
    "좋아하",
    "싫어하",
    "구매할 의향",
    "구매하려",
    "구매하고 싶",
    "살 의향",
    "사고 싶",
    "is happy",
    "feels happy",
    "is sad",
    "feels sad",
    "is angry",
    "feels angry",
    "is stressed",
    "feels stressed",
    "likes this product",
    "wants to buy",
    "will purchase",
)


class CentralModelError(RuntimeError):
    """Sanitized adapter error; it never contains request or response bodies."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        provider_diagnostic_code: str | None = None,
        provider_error_type: str | None = None,
        provider_error_code: str | None = None,
        provider_error_param: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.provider_diagnostic_code = provider_diagnostic_code
        self.provider_error_type = provider_error_type
        self.provider_error_code = provider_error_code
        self.provider_error_param = provider_error_param


def _safe_provider_error_fields(
    body: bytes,
) -> tuple[str | None, str | None, str | None]:
    """Extract allowlisted provider metadata without retaining its message."""

    if len(body) > MAX_PROVIDER_ERROR_BODY_BYTES:
        return None, None, None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, None
    if not isinstance(payload, Mapping) or not isinstance(payload.get("error"), Mapping):
        return None, None, None
    error = payload["error"]

    error_type = error.get("type")
    if not isinstance(error_type, str) or not _SAFE_PROVIDER_ERROR_TOKEN.fullmatch(error_type):
        error_type = None
    error_code = error.get("code")
    if not isinstance(error_code, str) or not _SAFE_PROVIDER_ERROR_TOKEN.fullmatch(error_code):
        error_code = None
    error_param = error.get("param")
    if not isinstance(error_param, str) or not _SAFE_PROVIDER_ERROR_PARAM.fullmatch(error_param):
        error_param = None
    return error_type, error_code, error_param


class CentralRecommendationClient(Protocol):
    model_id: str
    model_revision: str
    prompt_version: str

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        """Return the untrusted JSON-shaped model output."""


class JobHandle(Protocol):
    """Cancellation handle for an in-flight recommendation job."""

    def cancel(self) -> None: ...


class JobDispatcher(Protocol):
    def submit(self, job: Callable[[], object]) -> JobHandle | None: ...

    def close(self) -> None: ...


def is_loopback_development_endpoint(endpoint: str) -> bool:
    parsed = urlsplit(endpoint)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _run_dispatched_job(job: Callable[[], object]) -> None:
    result = job()
    if inspect.isawaitable(result):
        asyncio.run(result)


class ThreadJobDispatcher:
    """Compatibility dispatcher for non-ASGI callers.

    Production FastAPI uses ``AsyncioJobDispatcher`` so an in-flight HTTP
    request can be cancelled. This adapter remains useful for command-line
    smoke tests and older callers.
    """

    def __init__(self, *, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="central-recommendation",
        )

    def submit(self, job: Callable[[], object]) -> JobHandle | None:
        self._executor.submit(_run_dispatched_job, job)
        return None

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class ManualJobDispatcher:
    """Explicit test seam. Production configuration never selects this class."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], None]] = []

    def submit(self, job: Callable[[], object]) -> JobHandle | None:
        self.jobs.append(job)
        return None

    def run_next(self) -> None:
        _run_dispatched_job(self.jobs.pop(0))

    def close(self) -> None:
        self.jobs.clear()


class _AsyncioJobHandle:
    def __init__(self, task: asyncio.Task[object]) -> None:
        self._task = task

    def cancel(self) -> None:
        self._task.cancel()


def _consume_asyncio_task(task: asyncio.Task[object]) -> None:
    try:
        task.exception()
    except (asyncio.CancelledError, BaseException):
        pass


class AsyncioJobDispatcher:
    """Cancellable dispatcher bound to the FastAPI event loop."""

    def __init__(self, *, max_workers: int = 2) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._max_workers = max_workers
        self._tasks: set[asyncio.Task[object]] = set()

    def submit(self, job: Callable[[], object]) -> JobHandle:
        if len(self._tasks) >= self._max_workers:
            raise RuntimeError("central recommendation concurrency limit reached")
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(_consume_asyncio_task)
        return _AsyncioJobHandle(task)

    async def _run(self, job: Callable[[], object]) -> None:
        result = job()
        if inspect.isawaitable(result):
            await result

    def close(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        self._tasks.clear()


@dataclass(frozen=True, slots=True)
class SelfHostedHttpCentralClient:
    endpoint: str
    timeout_seconds: float = 10.0
    bearer_token: str | None = None
    model_id: str = "self-hosted-central-model"
    model_revision: str = "unconfigured-revision"
    prompt_version: str = APPROVED_PROMPT_VERSION

    def __post_init__(self) -> None:
        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("central model endpoint must use HTTP or HTTPS")
        if self.endpoint.startswith("http://") and not is_loopback_development_endpoint(
            self.endpoint
        ):
            raise ValueError("production central model endpoints must use HTTPS")
        if not self.bearer_token and not is_loopback_development_endpoint(self.endpoint):
            raise ValueError("production central model endpoints require service authentication")
        if self.timeout_seconds <= 0:
            raise ValueError("central model timeout must be positive")

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        payload = request.model_dump_json().encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        http_request = Request(self.endpoint, data=payload, headers=headers, method="POST")
        try:
            with urlopen(http_request, timeout=self.timeout_seconds) as response:  # noqa: S310
                body = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
        except (TimeoutError, socket.timeout) as exc:
            raise CentralModelError("model_unavailable", "central model timed out") from exc
        except HTTPError as exc:
            raise CentralModelError(
                "model_unavailable", f"central model returned HTTP {exc.code}"
            ) from exc
        except URLError as exc:
            raise CentralModelError("model_unavailable", "central model is unavailable") from exc
        if len(body) > MAX_MODEL_RESPONSE_BYTES:
            raise CentralModelError("invalid_model_output", "central model response is too large")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CentralModelError("invalid_model_output", "central model returned invalid JSON") from exc


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _openai_output_schema(request: CentralRecommendationRequestV2) -> dict[str, object]:
    """Build a strict schema narrowed to this exact ten-product request."""

    products = list(request.products)
    windows = list(request.evidence.evidence_windows or [])
    if len(products) != 10 or len({item.product_id for item in products}) != 10:
        raise CentralModelError("catalog_mismatch", "central model catalog must contain exactly ten products")
    if request.evidence.input_variant != LUNA_INPUT_VARIANT or not windows:
        raise CentralModelError("invalid_model_output", "Luna production input must be canonical variant C")
    product_ids = [item.product_id for item in products]
    tags = sorted({tag for product in products for tag in product.controlled_tags})
    window_ids = [window.window_id for window in windows]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "product_id", "reason", "reason_codes", "evidence", "style",
            "exploration_tendency_code",
        ],
        "properties": {
            "product_id": {"type": "string", "enum": product_ids},
            "reason": {"type": "string"},
            "reason_codes": {
                "type": "array",
                "items": {"type": "string", "enum": [
                    "observed_attention_lead", "return_candidate_support",
                    "movement_pattern_support", "observable_action_support",
                    "catalog_tag_alignment", "sufficient_data_quality",
                ]},
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["code", "product_id", "evidence_refs", "statement"],
                    "properties": {
                        "code": {"type": "string", "enum": [
                            "observed_attention", "return_candidate", "gaze_movement",
                            "face_action_change", "product_tag_match", "data_quality",
                        ]},
                        "product_id": {"type": "string", "enum": product_ids},
                        "evidence_refs": {
                            "type": "array",
                            "items": {
                                "type": "object", "additionalProperties": False,
                                "required": ["kind", "ref_id"],
                                "properties": {
                                    "kind": {"type": "string", "enum": ["window"]},
                                    "ref_id": {"type": "string", "enum": window_ids},
                                },
                            },
                        },
                        "statement": {"type": "string"},
                    },
                },
            },
            "style": {
                "type": "object", "additionalProperties": False,
                "required": ["matched_tags", "summary"],
                "properties": {
                    "matched_tags": {
                        "type": "array",
                        "items": {"type": "string", "enum": tags},
                    },
                    "summary": {"type": "string"},
                },
            },
            "exploration_tendency_code": {"type": "string", "enum": [
                "focused_single_product", "comparative_exploration", "broad_exploration",
            ]},
        },
    }


def _load_luna_prompt() -> str:
    try:
        prompt = LUNA_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise CentralModelError("model_unavailable", "central model prompt is unavailable") from exc
    normalized = prompt.replace("\r\n", "\n").replace("\r", "\n")
    if hashlib.sha256(normalized.encode("utf-8")).hexdigest() != LUNA_PROMPT_SHA256:
        raise CentralModelError("invalid_model_output", "central model prompt revision is not approved")
    return prompt


@dataclass(frozen=True, slots=True)
class OpenAILunaCentralClient:
    """Cancellable OpenAI Responses API adapter for the selected Luna config."""

    api_key: str = field(repr=False)
    model_id: str = LUNA_MODEL_ID
    model_revision: str = LUNA_MODEL_ID
    prompt_version: str = APPROVED_PROMPT_VERSION
    reasoning_effort: str = LUNA_REASONING_EFFORT
    reasoning_context: str = LUNA_REASONING_CONTEXT
    endpoint: str = LUNA_RESPONSES_URL
    response_envelope_bytes: int = MAX_PROVIDER_RESPONSE_ENVELOPE_BYTES
    output_text_bytes: int = MAX_PROVIDER_OUTPUT_TEXT_BYTES

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OPENAI_API_KEY is required for the Luna provider")
        if self.endpoint != LUNA_RESPONSES_URL:
            raise ValueError("Luna provider endpoint is fixed to the Responses API")
        if self.model_id != LUNA_MODEL_ID:
            raise ValueError(f"CENTRAL_AI_MODEL_ID must be {LUNA_MODEL_ID}")
        if self.model_revision != LUNA_MODEL_ID:
            raise ValueError(f"CENTRAL_AI_MODEL_REVISION must be {LUNA_MODEL_ID}")
        if self.reasoning_effort != LUNA_REASONING_EFFORT:
            raise ValueError("CENTRAL_AI_REASONING_EFFORT must be max")
        if self.reasoning_context != LUNA_REASONING_CONTEXT:
            raise ValueError("CENTRAL_AI_REASONING_CONTEXT must be current_turn")
        if self.prompt_version != APPROVED_PROMPT_VERSION:
            raise ValueError(f"CENTRAL_AI_PROMPT_VERSION must match approved {APPROVED_PROMPT_VERSION}")
        if self.response_envelope_bytes <= 0 or self.output_text_bytes <= 0:
            raise ValueError("provider response limits must be positive")

    async def recommend_async(self, request: CentralRecommendationRequestV2) -> object:
        if request.evidence.input_variant != LUNA_INPUT_VARIANT or request.evidence.timeline is not None:
            raise CentralModelError("invalid_model_output", "Luna provider accepts only canonical variant C")
        payload = request.model_dump(mode="json", exclude_none=True)
        body = {
            "model": self.model_id,
            "input": [
                {"role": "system", "content": _load_luna_prompt()},
                {"role": "user", "content": _canonical_json(payload)},
            ],
            "reasoning": {
                "effort": self.reasoning_effort,
                "context": self.reasoning_context,
            },
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "mcm_central_recommendation_v1",
                    "strict": True,
                    "schema": _openai_output_schema(request),
                }
            },
        }
        try:
            import httpx

            async with httpx.AsyncClient(timeout=None, follow_redirects=False) as client:
                async with client.stream(
                    "POST",
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    content=_canonical_json(body).encode("utf-8"),
                ) as response:
                    if response.status_code != 200:
                        error_chunks: list[bytes] = []
                        error_total = 0
                        async for chunk in response.aiter_bytes():
                            error_total += len(chunk)
                            if error_total > MAX_PROVIDER_ERROR_BODY_BYTES:
                                error_chunks.clear()
                                break
                            error_chunks.append(chunk)
                        provider_error_type, provider_error_code, provider_error_param = (
                            _safe_provider_error_fields(b"".join(error_chunks))
                            if error_chunks
                            else (None, None, None)
                        )
                        provider_diagnostic_code = f"provider_http_{response.status_code}"
                        if response.status_code == 429 or response.status_code >= 500:
                            raise CentralModelError(
                                "model_unavailable",
                                "central model provider is unavailable",
                                provider_diagnostic_code=provider_diagnostic_code,
                                provider_error_type=provider_error_type,
                                provider_error_code=provider_error_code,
                                provider_error_param=provider_error_param,
                            )
                        raise CentralModelError(
                            "model_unavailable",
                            "central model provider rejected the request",
                            provider_diagnostic_code=provider_diagnostic_code,
                            provider_error_type=provider_error_type,
                            provider_error_code=provider_error_code,
                            provider_error_param=provider_error_param,
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.response_envelope_bytes:
                            raise CentralModelError("invalid_model_output", "central model response is too large")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
        except CentralModelError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never expose provider details or request/response bodies.
            raise CentralModelError(
                "model_unavailable",
                "central model provider is unavailable",
                provider_diagnostic_code="provider_transport_error",
            ) from exc

        try:
            response_body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CentralModelError("invalid_model_output", "central model returned invalid JSON") from exc
        if not isinstance(response_body, Mapping):
            raise CentralModelError("invalid_model_output", "central model response envelope is invalid")
        if response_body.get("status") == "incomplete":
            raise CentralModelError("invalid_model_output", "central model returned an incomplete response")
        if response_body.get("status") != "completed":
            raise CentralModelError("invalid_model_output", "central model response was not completed")
        response_model = response_body.get("model")
        if not isinstance(response_model, str) or not (
            response_model == self.model_id or response_model.startswith(self.model_id + "-")
        ):
            raise CentralModelError("invalid_model_output", "central model response model is unexpected")
        texts: list[str] = []
        output = response_body.get("output")
        if not isinstance(output, list):
            raise CentralModelError("invalid_model_output", "central model output is missing")
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, Mapping):
                    continue
                if block.get("type") == "refusal":
                    raise CentralModelError("invalid_model_output", "central model refused the request")
                if block.get("type") == "output_text" and isinstance(block.get("text"), str):
                    texts.append(block["text"])
        if len(texts) != 1:
            raise CentralModelError("invalid_model_output", "central model output_text count is invalid")
        text = texts[0]
        if len(text.encode("utf-8")) > self.output_text_bytes:
            raise CentralModelError("invalid_model_output", "central model output text is too large")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CentralModelError("invalid_model_output", "central model output text is not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise CentralModelError("invalid_model_output", "central model output text is not an object")
        return value

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        """Synchronous compatibility shim; ASGI production uses recommend_async."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.recommend_async(request))
        raise CentralModelError("model_unavailable", "Luna provider requires cancellable async execution")


@dataclass(frozen=True, slots=True)
class UnavailableCentralClient:
    """Safe default: absence of a real endpoint is a failure, never mock success."""

    model_id: str = "unconfigured-central-model"
    model_revision: str = "unconfigured-revision"
    prompt_version: str = APPROVED_PROMPT_VERSION

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        del request
        raise CentralModelError("model_unavailable", "central model endpoint is not configured")


class DeterministicCentralStub:
    """Deterministic test double that cannot be enabled through environment config."""

    model_id = "deterministic-test-stub"
    model_revision = "test-only-v1"
    prompt_version = "test-only-prompt-v1"

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        signals = [
            item
            for item in request.evidence.summary
            if item.gaze is not None and item.gaze.valid_observation_count > 0
        ]
        if not signals:
            raise CentralModelError("invalid_model_output", "test input has no eligible product")
        signal = sorted(
            signals,
            key=lambda item: (
                -(item.gaze.valid_observation_count if item.gaze is not None else 0),
                -(item.gaze.observed_attention_ms if item.gaze is not None else 0),
                -((item.gaze.return_candidate_count or 0) if item.gaze is not None else 0),
                item.product_id,
            ),
        )[0]
        profile = next(product for product in request.products if product.product_id == signal.product_id)
        tag = profile.controlled_tags[0] if profile.controlled_tags else "observed"
        if request.evidence.input_variant == "B":
            frames = [
                frame
                for frame in (request.evidence.timeline or [])
                if frame.attention is not None
                and len(frame.attention.candidates) == 1
                and frame.attention.candidates[0].product_id == signal.product_id
            ]
            if not frames:
                raise CentralModelError("invalid_model_output", "test input has no grounded frame")
            evidence_ref = {"kind": "frame", "ref_id": frames[0].frame_id}
        else:
            windows = [
                window
                for window in (request.evidence.evidence_windows or [])
                if window.product_id == signal.product_id
            ]
            if not windows:
                raise CentralModelError("invalid_model_output", "test input has no evidence window")
            evidence_ref = {"kind": "window", "ref_id": windows[0].window_id}
        eligible_count = len(signals)
        return {
            "product_id": signal.product_id,
            "reason": "관찰된 시선 반응과 상품 정보를 함께 고려한 추천입니다.",
            "reason_codes": ["observed_attention_lead", "catalog_tag_alignment"],
            "evidence": [
                {
                    "code": "observed_attention",
                    "product_id": signal.product_id,
                    "evidence_refs": [evidence_ref],
                    "statement": "이 상품 영역에서 유효한 시선 반응이 관찰되었습니다.",
                }
            ],
            "style": {
                "matched_tags": [tag],
                "summary": "관찰된 반응과 연결되는 상품 특성입니다.",
            },
            "exploration_tendency_code": (
                "focused_single_product"
                if eligible_count == 1
                else "comparative_exploration"
                if eligible_count <= 3
                else "broad_exploration"
            ),
        }


def configured_central_client() -> CentralRecommendationClient:
    provider = os.getenv("CENTRAL_AI_PROVIDER", "").strip().lower()
    if provider in {"openai_luna", "luna"}:
        model_id = os.getenv("CENTRAL_AI_MODEL_ID", LUNA_MODEL_ID).strip()
        prompt_version = os.getenv("CENTRAL_AI_PROMPT_VERSION", APPROVED_PROMPT_VERSION).strip()
        input_variant = os.getenv("CENTRAL_AI_INPUT_VARIANT", LUNA_INPUT_VARIANT).strip().upper()
        if input_variant != LUNA_INPUT_VARIANT:
            raise ValueError("CENTRAL_AI_INPUT_VARIANT must be C for the Luna provider")
        model_revision = os.getenv("CENTRAL_AI_MODEL_REVISION", model_id).strip() or model_id
        if model_revision != LUNA_MODEL_ID:
            raise ValueError(f"CENTRAL_AI_MODEL_REVISION must be {LUNA_MODEL_ID}")
        return OpenAILunaCentralClient(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model_id=model_id,
            model_revision=model_revision,
            prompt_version=prompt_version,
            reasoning_effort=os.getenv("CENTRAL_AI_REASONING_EFFORT", LUNA_REASONING_EFFORT).strip(),
            reasoning_context=os.getenv("CENTRAL_AI_REASONING_CONTEXT", LUNA_REASONING_CONTEXT).strip(),
        )
    if provider and provider not in {"self_hosted", "unavailable"}:
        raise ValueError("CENTRAL_AI_PROVIDER must be openai_luna, self_hosted or unavailable")
    endpoint = os.getenv("CENTRAL_AI_ENDPOINT", "").strip()
    if not endpoint:
        return UnavailableCentralClient()
    required = {
        name: os.getenv(name, "").strip()
        for name in (
            "CENTRAL_AI_MODEL_ID",
            "CENTRAL_AI_MODEL_REVISION",
            "CENTRAL_AI_PROMPT_VERSION",
        )
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(
            "CENTRAL_AI_ENDPOINT requires explicit " + ", ".join(sorted(missing))
        )
    if required["CENTRAL_AI_PROMPT_VERSION"] != APPROVED_PROMPT_VERSION:
        raise ValueError(
            f"CENTRAL_AI_PROMPT_VERSION must match approved {APPROVED_PROMPT_VERSION}"
        )
    timeout_raw = os.getenv("CENTRAL_AI_TIMEOUT_SECONDS", "10").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("CENTRAL_AI_TIMEOUT_SECONDS must be numeric") from exc
    return SelfHostedHttpCentralClient(
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        bearer_token=os.getenv("CENTRAL_AI_BEARER_TOKEN") or None,
        model_id=required["CENTRAL_AI_MODEL_ID"],
        model_revision=required["CENTRAL_AI_MODEL_REVISION"],
        prompt_version=required["CENTRAL_AI_PROMPT_VERSION"],
    )


def validate_central_output(
    raw_output: object,
    *,
    request: CentralRecommendationRequestV2,
) -> CentralRecommendationOutputV2:
    if not isinstance(raw_output, Mapping):
        raise CentralModelError("invalid_model_output", "central model output must be a JSON object")
    try:
        output = CentralRecommendationOutputV2.model_validate(raw_output)
    except ValidationError as exc:
        raise CentralModelError("invalid_model_output", "central model output violated its schema") from exc

    profiles = {profile.product_id: profile for profile in request.products}
    profile = profiles.get(output.product_id)
    if profile is None:
        raise CentralModelError("catalog_mismatch", "central model selected an unknown product")
    eligible_product_ids = {
        item.product_id
        for item in request.evidence.summary
        if item.gaze is not None and item.gaze.valid_observation_count > 0
    }
    if output.product_id not in eligible_product_ids:
        raise CentralModelError(
            "invalid_model_output", "central model selected a product without observation evidence"
        )

    combined_text = " ".join(
        [output.reason, output.style.summary]
        + [item.statement for item in output.evidence]
    ).casefold()
    if any(term.casefold() in combined_text for term in _DIAGNOSIS_TERMS):
        raise CentralModelError(
            "invalid_model_output", "central model output contained a psychological diagnosis"
        )

    allowed_tags = set(profile.controlled_tags)
    if not output.style.matched_tags or not set(output.style.matched_tags) <= allowed_tags:
        raise CentralModelError("invalid_model_output", "central model returned uncontrolled tags")
    for item in output.evidence:
        if item.product_id is not None and item.product_id != output.product_id:
            raise CentralModelError(
                "invalid_model_output", "central model evidence referenced another product"
            )
    windows = {
        window.window_id: window for window in (request.evidence.evidence_windows or [])
    }
    frames = {frame.frame_id: frame for frame in (request.evidence.timeline or [])}
    code_to_window_code = {
        "observed_attention": "observed_attention",
        "return_candidate": "return_candidate",
        "gaze_movement": "gaze_movement",
        "face_action_change": "face_action_change",
    }
    for item in output.evidence:
        for ref in item.evidence_refs:
            if request.evidence.input_variant == "B":
                if ref.kind != "frame":
                    raise CentralModelError(
                        "invalid_model_output", "variant B requires frame evidence references"
                    )
                frame = frames.get(ref.ref_id)
                if (
                    frame is None
                    or frame.attention is None
                    or len(frame.attention.candidates) != 1
                    or frame.attention.candidates[0].product_id != output.product_id
                ):
                    raise CentralModelError(
                        "invalid_model_output", "central model referenced an ungrounded frame"
                    )
                if item.code == "return_candidate" and (
                    frame.derived is None
                    or frame.derived.gaze is None
                    or frame.derived.gaze.return_candidate is not True
                ):
                    raise CentralModelError(
                        "invalid_model_output", "frame did not contain return-candidate evidence"
                    )
                if item.code == "gaze_movement" and (
                    frame.derived is None
                    or frame.derived.gaze is None
                    or frame.derived.gaze.movement is None
                ):
                    raise CentralModelError(
                        "invalid_model_output", "frame did not contain gaze-movement evidence"
                    )
                if item.code == "face_action_change" and (
                    frame.derived is None
                    or frame.derived.expression is None
                    or frame.derived.expression.score_changes is None
                ):
                    raise CentralModelError(
                        "invalid_model_output", "frame did not contain face-action evidence"
                    )
            else:
                if ref.kind != "window":
                    raise CentralModelError(
                        "invalid_model_output", "variants A and C require window evidence references"
                    )
                window = windows.get(ref.ref_id)
                if window is None or window.product_id != output.product_id:
                    raise CentralModelError(
                        "invalid_model_output", "central model referenced an unknown evidence window"
                    )
                required_code = code_to_window_code.get(item.code)
                if required_code is not None and required_code not in window.evidence_codes:
                    raise CentralModelError(
                        "invalid_model_output", "central model evidence code was not present in its window"
                    )
    return output

"""Central model port, self-hosted HTTP adapter and strict output gate."""

from __future__ import annotations

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
APPROVED_PROMPT_VERSION = "central-recommender-ko-v1"
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

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class CentralRecommendationClient(Protocol):
    model_id: str
    model_revision: str
    prompt_version: str

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        """Return the untrusted JSON-shaped model output."""


class JobDispatcher(Protocol):
    def submit(self, job: Callable[[], None]) -> None: ...

    def close(self) -> None: ...


def is_loopback_development_endpoint(endpoint: str) -> bool:
    parsed = urlsplit(endpoint)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


class ThreadJobDispatcher:
    def __init__(self, *, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="central-recommendation",
        )

    def submit(self, job: Callable[[], None]) -> None:
        self._executor.submit(job)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class ManualJobDispatcher:
    """Explicit test seam. Production configuration never selects this class."""

    def __init__(self) -> None:
        self.jobs: list[Callable[[], None]] = []

    def submit(self, job: Callable[[], None]) -> None:
        self.jobs.append(job)

    def run_next(self) -> None:
        self.jobs.pop(0)()

    def close(self) -> None:
        self.jobs.clear()


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

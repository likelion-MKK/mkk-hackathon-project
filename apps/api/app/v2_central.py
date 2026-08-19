"""Central model port, self-hosted HTTP adapter and strict output gate."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import ssl
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event, RLock
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError

from apps.api.app.aoi_metadata import (
    ProductMatchingItemV1,
    SourceVisualEvidenceV1,
    product_feature_match_score,
)
from apps.api.app.v2_models import (
    CentralRecommendationOutputV2,
    CentralRecommendationRequestV2,
)


MAX_MODEL_RESPONSE_BYTES = 64 * 1024
APPROVED_PROMPT_VERSION = "central-recommender-ko-v2"
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

    def recommend_cancellable(
        self,
        request: CentralRecommendationRequestV2,
        cancel_event: Event,
    ) -> object:
        """Return output or stop promptly when cancel_event is set."""


class JobDispatcher(Protocol):
    def submit(self, job: Callable[[], None]) -> None: ...

    def close(self) -> None: ...


def is_loopback_development_endpoint(endpoint: str) -> bool:
    parsed = urlsplit(endpoint)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


class ThreadJobDispatcher:
    def __init__(
        self,
        *,
        max_workers: int = 2,
        shutdown_timeout_seconds: float = 15.0,
    ) -> None:
        if shutdown_timeout_seconds <= 0:
            raise ValueError("dispatcher shutdown timeout must be positive")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="central-recommendation",
        )
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._lock = RLock()
        self._futures: set[Future[None]] = set()
        self._closed = False

    def _discard_future(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def submit(self, job: Callable[[], None]) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("central recommendation dispatcher is closed")
            future = self._executor.submit(job)
            self._futures.add(future)
            future.add_done_callback(self._discard_future)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = tuple(self._futures)
            self._executor.shutdown(wait=False, cancel_futures=True)
        if futures:
            wait(futures, timeout=self._shutdown_timeout_seconds)


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

    def recommend_cancellable(
        self,
        request: CentralRecommendationRequestV2,
        cancel_event: Event,
    ) -> object:
        """Call the self-hosted endpoint with cancellable asyncio socket I/O."""

        if cancel_event.is_set():
            raise CentralModelError("model_unavailable", "central model request was cancelled")

        parsed = urlsplit(self.endpoint)
        host = parsed.hostname
        if host is None:
            raise CentralModelError("model_unavailable", "central model endpoint is unavailable")
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        if "\r" in target or "\n" in target:
            raise CentralModelError("model_unavailable", "central model endpoint is unavailable")

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host_header = f"[{host}]" if ":" in host else host
        if port != (443 if parsed.scheme == "https" else 80):
            host_header = f"{host_header}:{port}"
        payload = request.model_dump_json().encode("utf-8")
        headers = [
            f"Host: {host_header}",
            "Content-Type: application/json",
            "Accept: application/json",
            "Connection: close",
            f"Content-Length: {len(payload)}",
        ]
        if self.bearer_token:
            if "\r" in self.bearer_token or "\n" in self.bearer_token:
                raise CentralModelError(
                    "model_unavailable", "central model authentication is invalid"
                )
            headers.append(f"Authorization: Bearer {self.bearer_token}")
        request_head = (
            f"POST {target} HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n"
        ).encode("ascii")

        async def read_response(reader: asyncio.StreamReader) -> bytes:
            status_line = await reader.readline()
            if len(status_line) > 8_192 or not status_line.startswith(b"HTTP/"):
                raise CentralModelError(
                    "invalid_model_output", "central model returned an invalid HTTP response"
                )
            try:
                status = int(status_line.split(None, 2)[1])
            except (IndexError, ValueError) as exc:
                raise CentralModelError(
                    "invalid_model_output", "central model returned an invalid HTTP status"
                ) from exc

            response_headers: dict[bytes, bytes] = {}
            header_bytes = len(status_line)
            while True:
                line = await reader.readline()
                header_bytes += len(line)
                if header_bytes > 64 * 1024:
                    raise CentralModelError(
                        "invalid_model_output", "central model response headers are too large"
                    )
                if line in {b"\r\n", b"\n"}:
                    break
                if not line or b":" not in line:
                    raise CentralModelError(
                        "invalid_model_output", "central model returned invalid HTTP headers"
                    )
                name, value = line.split(b":", 1)
                response_headers[name.strip().lower()] = value.strip().lower()

            if not 200 <= status < 300:
                raise CentralModelError(
                    "model_unavailable", f"central model returned HTTP {status}"
                )

            body = bytearray()
            if b"chunked" in response_headers.get(b"transfer-encoding", b""):
                while True:
                    size_line = await reader.readline()
                    try:
                        chunk_size = int(size_line.split(b";", 1)[0].strip(), 16)
                    except ValueError as exc:
                        raise CentralModelError(
                            "invalid_model_output", "central model returned invalid chunked data"
                        ) from exc
                    if chunk_size == 0:
                        while await reader.readline() not in {b"\r\n", b"\n", b""}:
                            pass
                        break
                    if len(body) + chunk_size > MAX_MODEL_RESPONSE_BYTES:
                        raise CentralModelError(
                            "invalid_model_output", "central model response is too large"
                        )
                    body.extend(await reader.readexactly(chunk_size))
                    if await reader.readexactly(2) != b"\r\n":
                        raise CentralModelError(
                            "invalid_model_output", "central model returned invalid chunked data"
                        )
            elif b"content-length" in response_headers:
                try:
                    content_length = int(response_headers[b"content-length"])
                except ValueError as exc:
                    raise CentralModelError(
                        "invalid_model_output", "central model returned invalid content length"
                    ) from exc
                if content_length < 0 or content_length > MAX_MODEL_RESPONSE_BYTES:
                    raise CentralModelError(
                        "invalid_model_output", "central model response is too large"
                    )
                body.extend(await reader.readexactly(content_length))
            else:
                while len(body) <= MAX_MODEL_RESPONSE_BYTES:
                    chunk = await reader.read(
                        min(8_192, MAX_MODEL_RESPONSE_BYTES + 1 - len(body))
                    )
                    if not chunk:
                        break
                    body.extend(chunk)
                if len(body) > MAX_MODEL_RESPONSE_BYTES:
                    raise CentralModelError(
                        "invalid_model_output", "central model response is too large"
                    )
            return bytes(body)

        async def perform_request() -> bytes:
            ssl_context = ssl.create_default_context() if parsed.scheme == "https" else None
            reader: asyncio.StreamReader
            writer: asyncio.StreamWriter
            reader, writer = await asyncio.open_connection(
                host,
                port,
                ssl=ssl_context,
                server_hostname=host if ssl_context is not None else None,
            )
            try:
                writer.write(request_head)
                writer.write(payload)
                await writer.drain()
                return await read_response(reader)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError, ssl.SSLError):
                    pass

        async def wait_for_cancel() -> None:
            while not cancel_event.is_set():
                await asyncio.sleep(0.02)

        async def perform_or_cancel() -> bytes:
            request_task = asyncio.create_task(perform_request())
            cancel_task = asyncio.create_task(wait_for_cancel())
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    done, _ = await asyncio.wait(
                        {request_task, cancel_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancel_task in done or cancel_event.is_set():
                        request_task.cancel()
                        await asyncio.gather(request_task, return_exceptions=True)
                        raise CentralModelError(
                            "model_unavailable", "central model request was cancelled"
                        )
                    cancel_task.cancel()
                    await asyncio.gather(cancel_task, return_exceptions=True)
                    return await request_task
            finally:
                for task in (request_task, cancel_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(request_task, cancel_task, return_exceptions=True)

        try:
            body = asyncio.run(perform_or_cancel())
        except CentralModelError:
            raise
        except TimeoutError as exc:
            message = (
                "central model request was cancelled"
                if cancel_event.is_set()
                else "central model timed out"
            )
            raise CentralModelError("model_unavailable", message) from exc
        except (OSError, asyncio.IncompleteReadError, ssl.SSLError) as exc:
            message = (
                "central model request was cancelled"
                if cancel_event.is_set()
                else "central model is unavailable"
            )
            raise CentralModelError("model_unavailable", message) from exc
        finally:
            del payload

        if cancel_event.is_set():
            raise CentralModelError("model_unavailable", "central model request was cancelled")
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

    def recommend_cancellable(
        self,
        request: CentralRecommendationRequestV2,
        cancel_event: Event,
    ) -> object:
        del cancel_event
        return self.recommend(request)


class DeterministicCentralStub:
    """Deterministic test double that cannot be enabled through environment config."""

    model_id = "deterministic-test-stub"
    model_revision = "test-only-v1"
    prompt_version = "test-only-prompt-v1"

    def recommend(self, request: CentralRecommendationRequestV2) -> object:
        if request.source_visual_evidence is not None:
            try:
                source_evidence = SourceVisualEvidenceV1.model_validate(
                    request.source_visual_evidence
                )
                matching_products = [
                    ProductMatchingItemV1.model_validate(item)
                    for item in (request.matching_products or [])
                ]
            except ValidationError as exc:
                raise CentralModelError(
                    "invalid_model_output", "test source input violated its schema"
                ) from exc
            ranked = sorted(
                (
                    (*product_feature_match_score(product, source_evidence), product)
                    for product in matching_products
                ),
                key=lambda item: (-item[0], item[2].product_id),
            )
            if not ranked or ranked[0][0] <= 0:
                raise CentralModelError(
                    "invalid_model_output", "test source input has no matching catalog product"
                )
            _, matched_values, matching_product = ranked[0]
            profile = next(
                product
                for product in request.products
                if product.product_id == matching_product.product_id
            )
            matched_tags = [
                tag for tag in profile.controlled_tags if tag in set(matched_values)
            ]
            if not matched_tags:
                matched_tags = [
                    tag
                    for tag in profile.controlled_tags
                    if tag in matching_product.controlled_tags
                ][:1]
            if not matched_tags:
                raise CentralModelError(
                    "invalid_model_output", "matching product has no grounded catalog tag"
                )
            frame_id = sorted(source_evidence.grounded_frame_ids)[0]
            source_count = len(source_evidence.source_aois)
            return {
                "product_id": profile.product_id,
                "reason": "승인된 source AOI에서 관찰된 시선 특징과 상품 정보를 함께 고려한 추천입니다.",
                "reason_codes": ["observed_attention_lead", "catalog_tag_alignment"],
                "evidence": [
                    {
                        "code": "product_tag_match",
                        "product_id": profile.product_id,
                        "evidence_refs": [{"kind": "frame", "ref_id": frame_id}],
                        "statement": "관찰된 source AOI의 시각 특징과 검수된 상품 태그가 일치했습니다.",
                    }
                ],
                "style": {
                    "matched_tags": matched_tags,
                    "summary": "세션에서 관찰된 시각 특징과 연결되는 검수된 상품 특성입니다.",
                },
                "exploration_tendency_code": (
                    "focused_single_product"
                    if source_count == 1
                    else "comparative_exploration"
                    if source_count <= 3
                    else "broad_exploration"
                ),
            }

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

    def recommend_cancellable(
        self,
        request: CentralRecommendationRequestV2,
        cancel_event: Event,
    ) -> object:
        if cancel_event.is_set():
            raise CentralModelError("model_unavailable", "central model request was cancelled")
        return self.recommend(request)


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
    source_evidence: SourceVisualEvidenceV1 | None = None
    if request.source_visual_evidence is not None:
        try:
            source_evidence = SourceVisualEvidenceV1.model_validate(
                request.source_visual_evidence
            )
            matching_products = [
                ProductMatchingItemV1.model_validate(item)
                for item in (request.matching_products or [])
            ]
        except ValidationError as exc:
            raise CentralModelError(
                "invalid_model_output", "source matching input violated its schema"
            ) from exc
        if {item.product_id for item in matching_products} != set(profiles):
            raise CentralModelError(
                "catalog_mismatch", "matching profiles differ from the canonical catalog"
            )
        matching_by_id = {item.product_id: item for item in matching_products}
        selected_matching_product = matching_by_id.get(output.product_id)
        if selected_matching_product is None:
            raise CentralModelError(
                "catalog_mismatch", "selected product has no matching profile"
            )
        selected_score, matched_values = product_feature_match_score(
            selected_matching_product,
            source_evidence,
        )
        if selected_score <= 0 or not matched_values:
            raise CentralModelError(
                "invalid_model_output",
                "central model selected a product without grounded feature overlap",
            )
    else:
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
            if source_evidence is not None:
                if ref.kind != "frame" or ref.ref_id not in source_evidence.grounded_frame_ids:
                    raise CentralModelError(
                        "invalid_model_output",
                        "central model referenced an ungrounded source AOI frame",
                    )
                continue
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

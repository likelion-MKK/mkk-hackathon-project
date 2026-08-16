"""Transient observation buffer and atomic central-recommendation state machine."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from threading import RLock
from time import monotonic
from typing import Callable, Literal, Protocol
from uuid import uuid4

from apps.api.app.schemas import ManagerProductRequestAccepted
from apps.api.app.store import DomainError, MemoryStore
from apps.api.app.v2_central import (
    CentralModelError,
    CentralRecommendationClient,
    JobDispatcher,
    validate_central_output,
)
from apps.api.app.v2_evidence import FEATURE_VERSION, EvidenceSummary, summarize_observations
from apps.api.app.v2_models import (
    CentralRecommendationRequestV2,
    DecisionReasonV2,
    FrameObservationV2,
    ManagerEventPayloadV2,
    ManagerEventV2,
    ManagerProductRequestV2,
    ObservationBatchAcceptedV2,
    ObservationBatchV2,
    ProductRecommendationItemV2,
    ProductRecommendationProfileV2,
    RecommendationAcceptedV2,
    RecommendationDataQualityV2,
    RecommendationDecisionV2,
    RecommendationVersionV2,
)


MAX_BUFFERED_OBSERVATIONS = 512


@dataclass(frozen=True, slots=True)
class SessionRecommendationContext:
    session_id: str
    video_id: str
    manifest_version: str
    catalog_version: str
    products: tuple[ProductRecommendationItemV2, ...]
    exposure_product_pairs: frozenset[tuple[str, str]]
    already_completed_v1: bool


class RecommendationRepository(Protocol):
    """DB/provider seam used by v2 without requiring the future catalog migration."""

    def get_context(self, session_id: str) -> SessionRecommendationContext: ...

    def get_product(self, product_id: str) -> ProductRecommendationItemV2: ...

    def request_manager_product(
        self,
        session_id: str,
        request: ManagerProductRequestV2,
        decision: RecommendationDecisionV2,
    ) -> ManagerProductRequestAccepted: ...

    def list_manager_events(self, after_sequence: int | None = None) -> list[ManagerEventV2]: ...

    def save_pending(
        self,
        session_id: str,
        accepted: RecommendationAcceptedV2,
        evidence: object,
        version: RecommendationVersionV2,
    ) -> None: ...

    def save_decision(self, session_id: str, decision: RecommendationDecisionV2) -> None: ...


class DecisionPersistence(Protocol):
    def save_pending(
        self,
        session_id: str,
        accepted: RecommendationAcceptedV2,
        evidence: object,
        version: RecommendationVersionV2,
    ) -> None: ...

    def save_decision(self, session_id: str, decision: RecommendationDecisionV2) -> None: ...


class MemoryStoreRecommendationRepository:
    """v1 session adapter plus strict canonical 10-product v2 catalog loader."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        catalog: ProductRecommendationProfileV2 | None = None,
        persistence: DecisionPersistence | None = None,
    ) -> None:
        self._store = store
        self._persistence = persistence
        self._manager_lock = RLock()
        self._manager_events_v2: list[ManagerEventV2] = []
        self._manager_requests_v2: dict[str, tuple[str, str, str]] = {}
        self._manager_sequence_v2 = 0
        if catalog is None:
            path = (
                store.repository_root
                / "data"
                / "products"
                / "mcm-demo-recommendation-profile-v2.json"
            )
            try:
                catalog = ProductRecommendationProfileV2.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError("canonical v2 10-product catalog is not ready") from exc
        self._catalog = catalog
        ids = [product.product_id for product in self._catalog.products]
        if len(ids) != 10 or len(ids) != len(set(ids)):
            raise RuntimeError("canonical v2 catalog must contain exactly 10 unique products")
        self._products = {product.product_id: product for product in self._catalog.products}

    def get_context(self, session_id: str) -> SessionRecommendationContext:
        with self._store._lock:
            session = self._store._require_session(session_id)
            manifest = self._store._require_lookbook(session.lookbook_id)
            return SessionRecommendationContext(
                session_id=session.session_id,
                video_id=manifest.video_id,
                manifest_version=manifest.manifest_version,
                catalog_version=self._catalog.catalog_version,
                products=tuple(self._catalog.products),
                exposure_product_pairs=frozenset(
                    (exposure.exposure_id, exposure.product_id)
                    for exposure in manifest.exposures
                ),
                already_completed_v1=session.completed,
            )

    def get_product(self, product_id: str) -> ProductRecommendationItemV2:
        product = self._products.get(product_id)
        if product is None:
            raise DomainError(404, "product_not_found", f"v2 product '{product_id}' was not found")
        return product

    def request_manager_product(
        self,
        session_id: str,
        request: ManagerProductRequestV2,
        decision: RecommendationDecisionV2,
    ) -> ManagerProductRequestAccepted:
        with self._store._lock, self._manager_lock:
            session = self._store._require_session(session_id)
            request_key = (
                session_id,
                request.recommendation_id,
                request.selected_product_id,
            )
            existing = self._manager_requests_v2.get(request.request_id)
            if existing is not None:
                if existing != request_key:
                    raise DomainError(409, "request_id_conflict", "request_id was already used")
                return ManagerProductRequestAccepted(request_id=request.request_id, status="duplicate")
            if request.recommendation_id != decision.recommendation_id:
                raise DomainError(400, "recommendation_mismatch", "recommendation_id does not match")
            if request.selected_product_id != decision.selected_product_id:
                raise DomainError(400, "product_mismatch", "selected_product_id does not match")
            self._manager_events_v2.append(
                ManagerEventV2(
                    schema_version="2.0",
                    event_id=request.request_id,
                    sequence=self._manager_sequence_v2,
                    session_id=session_id,
                    kiosk_id=session.kiosk_id,
                    event_type="customer_product_request",
                    emitted_at=datetime.now(timezone.utc),
                    payload=ManagerEventPayloadV2(
                        recommendation_id=decision.recommendation_id,
                        selected_product_id=request.selected_product_id,
                        intent="view_recommended_product",
                    ),
                )
            )
            self._manager_sequence_v2 += 1
            self._manager_requests_v2[request.request_id] = request_key
            return ManagerProductRequestAccepted(request_id=request.request_id, status="accepted")

    def list_manager_events(self, after_sequence: int | None = None) -> list[ManagerEventV2]:
        with self._manager_lock:
            return [
                event
                for event in self._manager_events_v2
                if after_sequence is None or event.sequence > after_sequence
            ]

    def save_pending(
        self,
        session_id: str,
        accepted: RecommendationAcceptedV2,
        evidence: object,
        version: RecommendationVersionV2,
    ) -> None:
        if self._persistence is not None:
            self._persistence.save_pending(session_id, accepted, evidence, version)

    def save_decision(self, session_id: str, decision: RecommendationDecisionV2) -> None:
        if self._persistence is not None:
            self._persistence.save_decision(session_id, decision)


def configured_recommendation_repository(store: MemoryStore) -> MemoryStoreRecommendationRepository:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return MemoryStoreRecommendationRepository(store)
    from apps.api.app.v2_postgres import psycopg_persistence

    persistence = psycopg_persistence(database_url)
    catalog_path = (
        store.repository_root
        / "data"
        / "products"
        / "mcm-demo-recommendation-profile-v2.json"
    )
    try:
        catalog = persistence.seed_and_load(catalog_path)
    except Exception as exc:
        raise RuntimeError("PostgreSQL v2 catalog readiness check failed") from exc
    return MemoryStoreRecommendationRepository(
        store,
        catalog=catalog,
        persistence=persistence,
    )


@dataclass(slots=True)
class V2SessionState:
    observations: dict[tuple[int, str], FrameObservationV2] = field(default_factory=dict)
    sequence_index: dict[int, tuple[int, str]] = field(default_factory=dict)
    batch_fingerprints: dict[str, str] = field(default_factory=dict)
    batch_sequence_index: dict[int, str] = field(default_factory=dict)
    status: Literal["collecting", "pending", "terminal"] = "collecting"
    accepted: RecommendationAcceptedV2 | None = None
    decision: RecommendationDecisionV2 | None = None
    active_job_id: str | None = None
    expires_at: float = 0.0

    def clear_transient(self) -> None:
        self.observations.clear()
        self.sequence_index.clear()
        self.batch_fingerprints.clear()
        self.batch_sequence_index.clear()


@dataclass(frozen=True, slots=True)
class CompletionJob:
    session_id: str
    job_id: str
    accepted: RecommendationAcceptedV2
    request: CentralRecommendationRequestV2
    summary: EvidenceSummary
    version: RecommendationVersionV2


def _merge_observation(
    current: FrameObservationV2,
    incoming: FrameObservationV2,
) -> tuple[FrameObservationV2, bool]:
    context_fields = (
        "frame_id",
        "sequence",
        "captured_at_mono_ms",
        "session_offset_ms",
        "video_time_ms",
        "playback_epoch",
    )
    if any(getattr(current, field_name) != getattr(incoming, field_name) for field_name in context_fields):
        raise DomainError(
            400,
            "frame_context_conflict",
            "the same frame_id and playback_epoch carried conflicting frame context",
        )

    updates: dict[str, object] = {}
    changed = False
    for value_name, reason_name in (
        ("gaze", "gaze_reason"),
        ("expression", "expression_reason"),
        ("attention", "attention_reason"),
        ("derived", "derived_reason"),
    ):
        old_value = getattr(current, value_name)
        new_value = getattr(incoming, value_name)
        old_reason = getattr(current, reason_name)
        new_reason = getattr(incoming, reason_name)
        if old_value is not None and new_value is not None and old_value != new_value:
            raise DomainError(
                400,
                "frame_modality_conflict",
                f"frame {value_name} was submitted with conflicting values",
            )
        if old_value is None and new_value is not None:
            updates[value_name] = new_value
            updates[reason_name] = None
            changed = True
        elif old_value is None and new_value is None and old_reason != new_reason:
            raise DomainError(
                400,
                "frame_modality_conflict",
                f"frame {value_name} was submitted with conflicting missing reasons",
            )
    if not changed:
        return current, False
    return current.model_copy(update=updates), True


class V2RecommendationStore:
    """Lock-protected state; model calls are deliberately executed elsewhere."""

    def __init__(
        self,
        repository: RecommendationRepository,
        *,
        clock: Callable[[], float] = monotonic,
        collecting_ttl_seconds: float = 300.0,
        pending_ttl_seconds: float = 60.0,
        decision_ttl_seconds: float = 900.0,
        input_variant: Literal["A", "B", "C"] = "C",
    ) -> None:
        if min(collecting_ttl_seconds, pending_ttl_seconds, decision_ttl_seconds) <= 0:
            raise ValueError("v2 TTL values must be positive")
        if input_variant not in {"A", "B", "C"}:
            raise ValueError("v2 input_variant must be A, B or C")
        self._repository = repository
        self._clock = clock
        self._collecting_ttl = collecting_ttl_seconds
        self._pending_ttl = pending_ttl_seconds
        self._decision_ttl = decision_ttl_seconds
        self._input_variant = input_variant
        self._lock = RLock()
        self._states: dict[str, V2SessionState] = {}

    def cleanup_expired(self) -> int:
        now = self._clock()
        with self._lock:
            expired = [
                session_id
                for session_id, state in self._states.items()
                if state.expires_at <= now
            ]
            for session_id in expired:
                state = self._states.pop(session_id)
                state.clear_transient()
                state.active_job_id = None
            return len(expired)

    def append_batch(
        self, session_id: str, batch: ObservationBatchV2
    ) -> ObservationBatchAcceptedV2:
        context = self._repository.get_context(session_id)
        if batch.session_id != session_id:
            raise DomainError(400, "session_mismatch", "batch session_id does not match the URL")
        if batch.video_id != context.video_id:
            raise DomainError(400, "video_mismatch", "batch video_id does not match the session manifest")
        if context.already_completed_v1:
            raise DomainError(409, "session_completed", "completed sessions cannot accept observations")

        catalog_ids = {product.product_id for product in context.products}
        for observation in batch.observations:
            attention = observation.attention
            if attention is not None:
                if attention.manifest_version != context.manifest_version:
                    raise DomainError(
                        400,
                        "manifest_mismatch",
                        "attention manifest_version does not match the session manifest",
                    )
                if any(candidate.product_id not in catalog_ids for candidate in attention.candidates):
                    raise DomainError(
                        400,
                        "catalog_mismatch",
                        "attention referenced a product outside the session catalog",
                    )
                if any(
                    (candidate.exposure_id, candidate.product_id)
                    not in context.exposure_product_pairs
                    for candidate in attention.candidates
                ):
                    raise DomainError(
                        400,
                        "manifest_mismatch",
                        "attention candidate does not match a manifest exposure",
                    )

        fingerprint = sha256(batch.model_dump_json().encode("utf-8")).hexdigest()
        self.cleanup_expired()
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                state = V2SessionState(expires_at=self._clock() + self._collecting_ttl)
                self._states[session_id] = state
            if state.status != "collecting":
                raise DomainError(409, "session_completed", "session is no longer collecting")
            old_fingerprint = state.batch_fingerprints.get(batch.batch_id)
            if old_fingerprint is not None:
                if old_fingerprint != fingerprint:
                    raise DomainError(
                        409,
                        "batch_id_conflict",
                        "batch_id was already used for different observations",
                    )
                return ObservationBatchAcceptedV2(batch_id=batch.batch_id, status="duplicate")
            old_batch_id = state.batch_sequence_index.get(batch.batch_sequence)
            if old_batch_id is not None and old_batch_id != batch.batch_id:
                raise DomainError(
                    400,
                    "batch_sequence_conflict",
                    "batch_sequence values must be unique within a session",
                )

            changed = False
            prospective_observations = dict(state.observations)
            prospective_sequence_index = dict(state.sequence_index)
            for observation in batch.observations:
                key = (observation.playback_epoch, observation.frame_id)
                sequence_key = prospective_sequence_index.get(observation.sequence)
                if sequence_key is not None and sequence_key != key:
                    raise DomainError(
                        400,
                        "observation_sequence_conflict",
                        "observation sequence values must be unique within a session",
                    )
                current = prospective_observations.get(key)
                if current is None:
                    if len(prospective_observations) >= MAX_BUFFERED_OBSERVATIONS:
                        raise DomainError(
                            413,
                            "observation_buffer_full",
                            "session observation buffer reached its bounded limit",
                        )
                    prospective_observations[key] = observation.model_copy(deep=True)
                    prospective_sequence_index[observation.sequence] = key
                    changed = True
                else:
                    merged, did_change = _merge_observation(current, observation)
                    prospective_observations[key] = merged
                    changed = changed or did_change

            semantic_order = sorted(
                prospective_observations.values(),
                key=lambda item: (
                    item.playback_epoch,
                    item.captured_at_mono_ms,
                    item.sequence,
                    item.frame_id,
                ),
            )
            offsets = [item.session_offset_ms for item in semantic_order]
            if any(current < previous for previous, current in zip(offsets, offsets[1:])):
                raise DomainError(
                    400,
                    "session_offset_conflict",
                    "session_offset_ms must be nondecreasing in analysis order",
                )

            state.observations = prospective_observations
            state.sequence_index = prospective_sequence_index
            state.batch_fingerprints[batch.batch_id] = fingerprint
            state.batch_sequence_index[batch.batch_sequence] = batch.batch_id
            state.expires_at = self._clock() + self._collecting_ttl
            return ObservationBatchAcceptedV2(
                batch_id=batch.batch_id,
                status="accepted" if changed else "duplicate",
            )

    def begin_completion(
        self,
        session_id: str,
        client: CentralRecommendationClient,
    ) -> tuple[RecommendationAcceptedV2, CompletionJob | None]:
        context = self._repository.get_context(session_id)
        self.cleanup_expired()
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                state = V2SessionState(expires_at=self._clock() + self._collecting_ttl)
                self._states[session_id] = state
            if state.status != "collecting":
                if state.accepted is None:
                    raise DomainError(500, "recommendation_missing", "v2 job metadata is missing")
                return state.accepted, None
            if context.already_completed_v1:
                raise DomainError(409, "session_completed", "session has already been completed")

            snapshot = tuple(item.model_copy(deep=True) for item in state.observations.values())
            recommendation_id = f"recommendation-v2-{session_id}-001"
            decision_request_id = f"decision-{uuid4().hex}"
            accepted = RecommendationAcceptedV2(
                recommendation_id=recommendation_id,
                decision_request_id=decision_request_id,
                status="pending",
            )
            version = RecommendationVersionV2(
                model_id=client.model_id,
                model_revision=client.model_revision,
                prompt_version=client.prompt_version,
                feature_version=FEATURE_VERSION,
                catalog_version=context.catalog_version,
                input_variant=self._input_variant,
                deployment_mode="self_hosted",
            )
            state.status = "pending"
            state.accepted = accepted
            state.clear_transient()
            state.expires_at = self._clock() + self._pending_ttl

            if not snapshot:
                quality = RecommendationDataQualityV2(
                    expected_observation_count=0,
                    gaze_valid_ratio=0.0,
                    expression_valid_ratio=0.0,
                    matched_frame_ratio=0.0,
                    ambiguous_product_ratio=0.0,
                )
                state.decision = RecommendationDecisionV2(
                    recommendation_id=recommendation_id,
                    decision_request_id=decision_request_id,
                    status="insufficient_data",
                    selected_product_id=None,
                    reason=DecisionReasonV2(
                        code="insufficient_valid_signal",
                        explanation="추천에 필요한 유효한 관찰 신호가 없습니다.",
                    ),
                    reason_codes=[],
                    evidence=[],
                    style=None,
                    exploration_tendency_code=None,
                    data_quality=quality,
                    version=version,
                )
                state.status = "terminal"
                state.expires_at = self._clock() + self._decision_ttl
                return accepted, None

            summary = summarize_observations(
                snapshot,
                decision_request_id=decision_request_id,
                session_id=session_id,
                video_id=context.video_id,
                manifest_version=context.manifest_version,
                catalog_version=context.catalog_version,
                product_ids=[product.product_id for product in context.products],
                input_variant=self._input_variant,
            )
            if (
                summary.data_quality.gaze_valid_ratio == 0
                or summary.data_quality.expression_valid_ratio == 0
                or not summary.eligible_product_ids
            ):
                code = (
                    "insufficient_valid_signal"
                    if summary.data_quality.gaze_valid_ratio == 0
                    or summary.data_quality.expression_valid_ratio == 0
                    else "no_eligible_product"
                )
                explanation = (
                    "추천에 필요한 유효한 시선·표정 신호가 충분하지 않습니다."
                    if code == "insufficient_valid_signal"
                    else "하나의 상품에 안전하게 연결할 수 있는 관찰 근거가 없습니다."
                )
                state.decision = RecommendationDecisionV2(
                    recommendation_id=recommendation_id,
                    decision_request_id=decision_request_id,
                    status="insufficient_data",
                    selected_product_id=None,
                    reason=DecisionReasonV2(code=code, explanation=explanation),
                    reason_codes=[],
                    evidence=[],
                    style=None,
                    exploration_tendency_code=None,
                    data_quality=summary.data_quality,
                    version=version,
                )
                state.status = "terminal"
                state.expires_at = self._clock() + self._decision_ttl
                return accepted, None

            job_id = uuid4().hex
            state.active_job_id = job_id
            request = CentralRecommendationRequestV2(
                decision_request_id=decision_request_id,
                session_id=session_id,
                video_id=context.video_id,
                prompt_version=client.prompt_version,
                evidence_version=FEATURE_VERSION,
                evidence=summary.evidence,
                products=list(context.products),
            )
            return accepted, CompletionJob(
                session_id=session_id,
                job_id=job_id,
                accepted=accepted,
                request=request,
                summary=summary,
                version=version,
            )

    def run_completion(
        self,
        job: CompletionJob,
        client: CentralRecommendationClient,
    ) -> None:
        """Call the model outside the store lock, then conditionally save once."""

        try:
            raw_output = client.recommend(job.request)
            output = validate_central_output(raw_output, request=job.request)
            decision = RecommendationDecisionV2(
                recommendation_id=job.accepted.recommendation_id,
                decision_request_id=job.accepted.decision_request_id,
                status="completed",
                selected_product_id=output.product_id,
                reason=DecisionReasonV2(
                    code="grounded_product_match", explanation=output.reason
                ),
                reason_codes=output.reason_codes,
                evidence=output.evidence,
                style=output.style,
                exploration_tendency_code=output.exploration_tendency_code,
                data_quality=job.summary.data_quality,
                version=job.version,
            )
        except CentralModelError as exc:
            code = exc.reason_code
            if code not in {"model_unavailable", "invalid_model_output", "catalog_mismatch"}:
                code = "invalid_model_output"
            explanations = {
                "model_unavailable": "추천 모델에 연결할 수 없습니다.",
                "invalid_model_output": "추천 모델 응답을 안전하게 검증할 수 없습니다.",
                "catalog_mismatch": "추천 모델 응답이 현재 상품 카탈로그와 일치하지 않습니다.",
            }
            decision = RecommendationDecisionV2(
                recommendation_id=job.accepted.recommendation_id,
                decision_request_id=job.accepted.decision_request_id,
                status="failed",
                selected_product_id=None,
                reason=DecisionReasonV2(code=code, explanation=explanations[code]),
                reason_codes=[],
                evidence=[],
                style=None,
                exploration_tendency_code=None,
                data_quality=job.summary.data_quality,
                version=job.version,
            )
        except Exception:
            # Keep unexpected client failures sanitized and fail closed.
            decision = RecommendationDecisionV2(
                recommendation_id=job.accepted.recommendation_id,
                decision_request_id=job.accepted.decision_request_id,
                status="failed",
                selected_product_id=None,
                reason=DecisionReasonV2(
                    code="model_unavailable",
                    explanation="추천 모델 실행 중 안전하게 처리할 수 없는 오류가 발생했습니다.",
                ),
                reason_codes=[],
                evidence=[],
                style=None,
                exploration_tendency_code=None,
                data_quality=job.summary.data_quality,
                version=job.version,
            )

        saved = self._commit_terminal(job, decision)
        if saved:
            self._repository.save_decision(job.session_id, decision)

    def _commit_terminal(
        self,
        job: CompletionJob,
        decision: RecommendationDecisionV2,
    ) -> bool:
        """Atomically publish a terminal result only for the still-active job."""

        self.cleanup_expired()
        with self._lock:
            state = self._states.get(job.session_id)
            if (
                state is None
                or state.status != "pending"
                or state.active_job_id != job.job_id
            ):
                return
            state.decision = decision
            state.status = "terminal"
            state.active_job_id = None
            state.clear_transient()
            state.expires_at = self._clock() + self._decision_ttl
            return True

    @staticmethod
    def _job_start_failure(job: CompletionJob) -> RecommendationDecisionV2:
        return RecommendationDecisionV2(
            recommendation_id=job.accepted.recommendation_id,
            decision_request_id=job.accepted.decision_request_id,
            status="failed",
            selected_product_id=None,
            reason=DecisionReasonV2(
                code="model_unavailable",
                explanation="추천 작업을 안전하게 시작할 수 없습니다.",
            ),
            reason_codes=[],
            evidence=[],
            style=None,
            exploration_tendency_code=None,
            data_quality=job.summary.data_quality,
            version=job.version,
        )

    def complete(
        self,
        session_id: str,
        client: CentralRecommendationClient,
        dispatcher: JobDispatcher,
    ) -> RecommendationAcceptedV2:
        accepted, job = self.begin_completion(session_id, client)
        if job is not None:
            try:
                self._repository.save_pending(
                    session_id,
                    accepted,
                    job.summary.evidence,
                    job.version,
                )
                dispatcher.submit(lambda: self.run_completion(job, client))
            except Exception:
                # A durable pending record without a runnable job would poll
                # forever. Fail closed in memory and best-effort persist the
                # sanitized terminal failure; never restore the raw timeline.
                decision = self._job_start_failure(job)
                if self._commit_terminal(job, decision):
                    try:
                        self._repository.save_decision(session_id, decision)
                    except Exception:
                        pass
        else:
            terminal = self.get_recommendation(session_id)
            if isinstance(terminal, RecommendationDecisionV2):
                self._repository.save_decision(session_id, terminal)
        return accepted

    def get_recommendation(
        self, session_id: str
    ) -> RecommendationAcceptedV2 | RecommendationDecisionV2:
        self._repository.get_context(session_id)
        self.cleanup_expired()
        with self._lock:
            state = self._states.get(session_id)
            if state is None or state.accepted is None:
                raise DomainError(404, "recommendation_not_found", "v2 recommendation was not started")
            if state.status == "pending":
                return state.accepted
            if state.decision is None:
                raise DomainError(500, "recommendation_missing", "v2 recommendation state is missing")
            return state.decision

    def get_product(self, product_id: str) -> ProductRecommendationItemV2:
        return self._repository.get_product(product_id)

    def request_manager_product(
        self,
        session_id: str,
        request: ManagerProductRequestV2,
    ) -> ManagerProductRequestAccepted:
        self._repository.get_context(session_id)
        self.cleanup_expired()
        with self._lock:
            state = self._states.get(session_id)
            decision = None if state is None else state.decision
            if decision is None or decision.status != "completed":
                raise DomainError(
                    409,
                    "recommendation_not_ready",
                    "manager requests require a completed v2 recommendation",
                )
        return self._repository.request_manager_product(session_id, request, decision)

    def list_manager_events(self, after_sequence: int | None = None) -> list[ManagerEventV2]:
        return self._repository.list_manager_events(after_sequence)

    def cancel(self, session_id: str) -> None:
        self._repository.get_context(session_id)
        with self._lock:
            state = self._states.pop(session_id, None)
            if state is not None:
                state.clear_transient()
                state.active_job_id = None

    def buffered_observation_count(self, session_id: str) -> int:
        with self._lock:
            state = self._states.get(session_id)
            return 0 if state is None else len(state.observations)

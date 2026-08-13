"""Development persistence boundary for the first API vertical slice.

The store is intentionally in-memory while the session and event contracts are
being wired. Its public methods are the seam for the planned PostgreSQL 17.10
and Alembic implementation; no raw media is accepted or retained here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from apps.api.app.schemas import (
    LookbookManifest,
    Product,
    ProductCatalog,
    ReactionBatch,
    ReactionBatchAccepted,
    ReactionEvent,
    RecommendationAccepted,
    RecommendationResult,
    SessionCreate,
    SessionCreated,
)
from services.recommendation.engine.interface import RecommendationEngine


class DomainError(Exception):
    """An application error that maps to the public Error contract."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class SessionRecord:
    session_id: str
    kiosk_id: str
    lookbook_id: str
    consent_version: str
    created_at: datetime
    display_code: str
    event_ids: set[str] = field(default_factory=set)
    event_sequences: set[int] = field(default_factory=set)
    events: list[ReactionEvent] = field(default_factory=list)
    batch_ids: set[str] = field(default_factory=set)
    recommendation: RecommendationResult | None = None
    completed: bool = False


class MemoryStore:
    """Thread-safe fixture-backed store used by the API scaffold."""

    def __init__(self, repository_root: Path | None = None) -> None:
        self._lock = RLock()
        self.repository_root = repository_root or Path(__file__).resolve().parents[3]
        self.catalog = self._load_catalog()
        self.manifest = self._load_manifest()
        self.products = {product.product_id: product for product in self.catalog.products}
        self.sessions: dict[str, SessionRecord] = {}

    def _load_catalog(self) -> ProductCatalog:
        path = self.repository_root / "data" / "products" / "catalog.example.json"
        return ProductCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_manifest(self) -> LookbookManifest:
        path = self.repository_root / "data" / "lookbooks" / "example" / "manifest.json"
        return LookbookManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _new_recommendation(self, session_id: str) -> RecommendationResult:
        return RecommendationResult(
            schema_version="1.0",
            recommendation_id=f"recommendation-{session_id}-001",
            session_id=session_id,
            video_id=self.manifest.video_id,
            manifest_version=self.manifest.manifest_version,
            algorithm_version="mock-v1",
            engine_mode="mock",
            status="pending",
            items=[],
            reason=None,
        )

    def _require_session(self, session_id: str) -> SessionRecord:
        session = self.sessions.get(session_id)
        if session is None:
            raise DomainError(404, "session_not_found", f"session '{session_id}' was not found")
        return session

    def _require_lookbook(self, lookbook_id: str) -> LookbookManifest:
        supported_ids = {self.manifest.video_id, "example", "mcm-lookbook-example"}
        if lookbook_id not in supported_ids:
            raise DomainError(404, "lookbook_not_found", f"lookbook '{lookbook_id}' was not found")
        return self.manifest

    def create_session(self, request: SessionCreate) -> SessionCreated:
        with self._lock:
            manifest = self._require_lookbook(request.lookbook_id)
            session_number = len(self.sessions) + 1
            session_id = f"session-{session_number:04d}"
            created_at = datetime.now(timezone.utc)
            record = SessionRecord(
                session_id=session_id,
                kiosk_id=request.kiosk_id,
                lookbook_id=request.lookbook_id,
                consent_version=request.consent_version,
                created_at=created_at,
                display_code=f"MKK-{session_number:04d}",
                recommendation=self._new_recommendation(session_id),
            )
            self.sessions[session_id] = record
            if manifest.video_id != self.manifest.video_id:  # defensive invariant
                raise DomainError(500, "manifest_mismatch", "session manifest is inconsistent")
            return SessionCreated(
                session_id=session_id,
                display_code=record.display_code,
                status="collecting",
                created_at=created_at,
            )

    def get_manifest(self, lookbook_id: str) -> LookbookManifest:
        with self._lock:
            return self._require_lookbook(lookbook_id)

    def get_product(self, product_id: str) -> Product:
        with self._lock:
            product = self.products.get(product_id)
            if product is None:
                raise DomainError(404, "product_not_found", f"product '{product_id}' was not found")
            return product

    def append_batch(self, session_id: str, batch: ReactionBatch) -> ReactionBatchAccepted:
        with self._lock:
            session = self._require_session(session_id)
            if batch.session_id != session_id:
                raise DomainError(400, "session_mismatch", "batch session_id does not match the URL")
            if batch.video_id != self.manifest.video_id:
                raise DomainError(400, "video_mismatch", "batch video_id does not match the session manifest")
            if session.completed:
                raise DomainError(409, "session_completed", "completed sessions cannot accept more batches")
            if batch.batch_id in session.batch_ids:
                return ReactionBatchAccepted(batch_id=batch.batch_id, status="duplicate")

            new_events = [event for event in batch.events if event.event_id not in session.event_ids]
            conflicting_sequences = [
                event.sequence
                for event in new_events
                if event.sequence in session.event_sequences
            ]
            if conflicting_sequences:
                raise DomainError(
                    400,
                    "duplicate_event_sequence",
                    "event sequence values must be unique within a session",
                )
            session.batch_ids.add(batch.batch_id)
            for event in new_events:
                session.event_ids.add(event.event_id)
                session.event_sequences.add(event.sequence)
                session.events.append(event)

            if not new_events:
                return ReactionBatchAccepted(batch_id=batch.batch_id, status="duplicate")
            return ReactionBatchAccepted(batch_id=batch.batch_id, status="accepted")

    def complete_session(
        self,
        session_id: str,
        engine: RecommendationEngine,
    ) -> RecommendationAccepted:
        with self._lock:
            session = self._require_session(session_id)
            if session.completed:
                raise DomainError(409, "session_already_completed", "session has already been completed")
            if session.recommendation is None:
                raise DomainError(500, "recommendation_missing", "session recommendation state is missing")

            engine_result = engine.run(
                recommendation_id=session.recommendation.recommendation_id,
                session_id=session.session_id,
                video_id=self.manifest.video_id,
                manifest_version=self.manifest.manifest_version,
                events=[event.model_dump(mode="json") for event in session.events],
                products=[product.model_dump(mode="json") for product in self.products.values()],
            )
            session.recommendation = RecommendationResult.model_validate(engine_result.to_payload())
            session.completed = True
            return RecommendationAccepted(session_id=session_id, status="pending")

    def get_recommendation(self, session_id: str) -> RecommendationResult:
        with self._lock:
            session = self._require_session(session_id)
            if session.recommendation is None:
                raise DomainError(500, "recommendation_missing", "session recommendation state is missing")
            return session.recommendation

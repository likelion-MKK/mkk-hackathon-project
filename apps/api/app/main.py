"""FastAPI entrypoint for the first Contract v1 vertical slice."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Path, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.app.schemas import (
    ErrorResponse,
    Health,
    IDENTIFIER_PATTERN,
    LookbookManifest,
    ManagerEvent,
    ManagerProductRequest,
    ManagerProductRequestAccepted,
    Product,
    ReactionBatch,
    ReactionBatchAccepted,
    RecommendationAccepted,
    RecommendationResult,
    SessionCreate,
    SessionCreated,
)
from apps.api.app.store import DomainError, MemoryStore
from services.recommendation.mock.engine import MockRecommendationEngine


IdentifierPath = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN),
]


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorResponse(code=code, message=message)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def create_app(store: MemoryStore | None = None) -> FastAPI:
    """Create an app with an injectable store for deterministic tests."""

    app = FastAPI(
        title="MCM AI Lookbook Kiosk API",
        version="0.1.0",
        description="Contract-first API scaffold; raw webcam frames are not accepted.",
    )
    app.state.store = store or MemoryStore()
    app.state.recommendation_engine = MockRecommendationEngine()

    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        message = errors[0].get("msg", "request validation failed") if errors else "request validation failed"
        return _error_response("invalid_request", message, status.HTTP_400_BAD_REQUEST)

    @app.post(
        "/api/v1/sessions",
        response_model=SessionCreated,
        status_code=status.HTTP_201_CREATED,
        responses={400: {"model": ErrorResponse}},
    )
    def create_session(request: SessionCreate) -> SessionCreated:
        return app.state.store.create_session(request)

    @app.get(
        "/api/v1/lookbooks/{lookbook_id}/manifest",
        response_model=LookbookManifest,
        responses={404: {"model": ErrorResponse}},
    )
    def get_manifest(lookbook_id: IdentifierPath) -> LookbookManifest:
        return app.state.store.get_manifest(lookbook_id)

    @app.post(
        "/api/v1/sessions/{session_id}/reaction-batches",
        response_model=ReactionBatchAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def append_reaction_batch(session_id: IdentifierPath, batch: ReactionBatch) -> ReactionBatchAccepted:
        return app.state.store.append_batch(session_id, batch)

    @app.post(
        "/api/v1/sessions/{session_id}/complete",
        response_model=RecommendationAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def complete_session(session_id: str) -> RecommendationAccepted:
        return app.state.store.complete_session(session_id, app.state.recommendation_engine)

    @app.get(
        "/api/v1/sessions/{session_id}/recommendations",
        response_model=RecommendationResult,
        responses={404: {"model": ErrorResponse}},
    )
    def get_recommendation(session_id: str) -> RecommendationResult:
        return app.state.store.get_recommendation(session_id)

    @app.post(
        "/api/v1/sessions/{session_id}/manager-product-requests",
        response_model=ManagerProductRequestAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def request_manager_product(
        session_id: IdentifierPath,
        request: ManagerProductRequest,
    ) -> ManagerProductRequestAccepted:
        return app.state.store.request_manager_product(session_id, request)

    @app.get("/api/v1/manager/events", response_model=list[ManagerEvent])
    def list_manager_events(after_sequence: int | None = Query(default=None, ge=0)) -> list[ManagerEvent]:
        return app.state.store.list_manager_events(after_sequence)

    @app.get(
        "/api/v1/products/{product_id}",
        response_model=Product,
        responses={404: {"model": ErrorResponse}},
    )
    def get_product(product_id: IdentifierPath) -> Product:
        return app.state.store.get_product(product_id)

    @app.get("/api/v1/health", response_model=Health)
    def health() -> Health:
        # The memory store is a development adapter. The response shape stays
        # compatible with the future PostgreSQL readiness check.
        return Health(status="ok", database="up")

    return app


app = create_app()

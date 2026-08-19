"""FastAPI entrypoint for the first Contract v1 vertical slice."""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Annotated

from fastapi import FastAPI, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.app.schemas import (
    ConversionOutcome,
    ErrorResponse,
    Health,
    IDENTIFIER_PATTERN,
    Liveness,
    LookbookManifest,
    ManagerEvent,
    ManagerProductRequest,
    ManagerProductRequestAccepted,
    Product,
    ReactionBatch,
    ReactionBatchAccepted,
    RecommendationAccepted,
    RecommendationResult,
    Readiness,
    SessionCreate,
    SessionCreated,
    VisionStreamToken,
)
from apps.common.vision_token import SignedVisionTokenIssuer
from apps.api.app.store import DomainError, MemoryStore
from apps.api.app.v2_central import (
    AsyncioJobDispatcher,
    CentralRecommendationClient,
    JobDispatcher,
    configured_central_client,
    is_loopback_development_endpoint,
)
from apps.api.app.v2_models import (
    ManagerEventV2,
    ManagerProductRequestV2,
    ObservationBatchAcceptedV2,
    ObservationBatchV2,
    ProductRecommendationItemV2,
    RecommendationAcceptedV2,
    RecommendationDecisionV2,
)
from apps.api.app.v2_store import (
    V2RecommendationStore,
    configured_recommendation_repository,
)
from services.recommendation.engine.interface import RecommendationEngine
from services.recommendation.engine.research_gaze import ResearchGazeScoreEngine
from services.recommendation.mock.engine import MockRecommendationEngine


IdentifierPath = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN),
]


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorResponse(code=code, message=message)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _configured_recommendation_engine() -> RecommendationEngine:
    """Select the development or replay-safe recommendation implementation."""

    mode = os.getenv("RECOMMENDATION_ENGINE", "mock").strip().lower()
    if mode == "mock":
        return MockRecommendationEngine()
    if mode == "research_version":
        return ResearchGazeScoreEngine()
    raise ValueError(
        "RECOMMENDATION_ENGINE must be 'mock' or 'research_version'"
    )


def _configured_cors_origins() -> list[str]:
    raw = os.getenv(
        "KIOSK_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174",
    )
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise ValueError("KIOSK_CORS_ORIGINS must list explicit HTTP(S) origins")
    if any(not origin.startswith(("http://", "https://")) for origin in origins):
        raise ValueError("KIOSK_CORS_ORIGINS entries must use HTTP or HTTPS")
    return origins


def _configured_vision_token_issuer() -> SignedVisionTokenIssuer | None:
    secret = os.getenv("VISION_STREAM_TOKEN_SECRET", "").strip()
    if not secret:
        return None
    return SignedVisionTokenIssuer(secret, ttl_seconds=60)


def _positive_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _configured_input_variant() -> str:
    endpoint = os.getenv("CENTRAL_AI_ENDPOINT", "").strip()
    provider = os.getenv("CENTRAL_AI_PROVIDER", "").strip().lower()
    raw_variant = os.getenv("CENTRAL_AI_INPUT_VARIANT")
    if (endpoint or provider == "openai_luna") and (raw_variant is None or not raw_variant.strip()):
        raise ValueError("configured central provider requires explicit CENTRAL_AI_INPUT_VARIANT")
    variant = (raw_variant or "C").strip().upper()
    if variant not in {"A", "B", "C"}:
        raise ValueError("CENTRAL_AI_INPUT_VARIANT must be A, B or C")
    is_loopback = is_loopback_development_endpoint(endpoint)
    if endpoint and not is_loopback and not os.getenv("CENTRAL_AI_BENCHMARK_APPROVAL", "").strip():
        raise ValueError("production input_variant requires CENTRAL_AI_BENCHMARK_APPROVAL")
    return variant


def _configured_insufficient_signal_demo_fallback() -> bool:
    enabled = os.getenv("MCM_LOCAL_DEMO_ALLOW_INSUFFICIENT_SIGNAL", "").strip() == "1"
    if not enabled:
        return False
    provider = os.getenv("CENTRAL_AI_PROVIDER", "").strip().lower()
    demo_mode = os.getenv("MCM_LOCAL_DEMO_MODE", "").strip() == "1"
    if provider != "local_demo_stub" or not demo_mode:
        raise ValueError(
            "MCM_LOCAL_DEMO_ALLOW_INSUFFICIENT_SIGNAL=1 requires "
            "CENTRAL_AI_PROVIDER=local_demo_stub and MCM_LOCAL_DEMO_MODE=1"
        )
    return True


def create_app(
    store: MemoryStore | None = None,
    recommendation_engine: RecommendationEngine | None = None,
    central_client: CentralRecommendationClient | None = None,
    job_dispatcher: JobDispatcher | None = None,
    v2_store: V2RecommendationStore | None = None,
    central_input_variant: str | None = None,
) -> FastAPI:
    """Create an app with injectable storage and recommendation seams for tests."""

    app = FastAPI(
        title="MCM AI Lookbook Kiosk API",
        version="0.1.0",
        description="Contract-first API scaffold; raw webcam frames are not accepted.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_configured_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.state.store = store or MemoryStore()
    app.state.vision_token_issuer = _configured_vision_token_issuer()
    app.state.recommendation_engine = recommendation_engine or _configured_recommendation_engine()
    app.state.central_client = central_client or configured_central_client()
    app.state.job_dispatcher = job_dispatcher or AsyncioJobDispatcher(max_workers=2)
    app.state.v2_store = v2_store or V2RecommendationStore(
        configured_recommendation_repository(app.state.store),
        collecting_ttl_seconds=_positive_env_float("V2_COLLECTING_TTL_SECONDS", 300.0),
        pending_ttl_seconds=_positive_env_float("V2_PENDING_TTL_SECONDS", 1_800.0),
        decision_ttl_seconds=_positive_env_float("V2_DECISION_TTL_SECONDS", 900.0),
        orphan_job_seconds=_positive_env_float("V2_ORPHAN_JOB_SECONDS", 1_800.0),
        job_retention_seconds=_positive_env_float(
            "V2_JOB_RETENTION_SECONDS", 86_400.0
        ),
        input_variant=central_input_variant or _configured_input_variant(),
        allow_insufficient_signal_demo=_configured_insufficient_signal_demo_fallback(),
    )
    app.state.maintenance_task = None

    async def initialize_database_runtime() -> None:
        await asyncio.to_thread(app.state.v2_store.initialize_runtime)
        if not app.state.v2_store.durable_mode:
            return
        interval_seconds = _positive_env_float(
            "V2_MAINTENANCE_INTERVAL_SECONDS", 60.0
        )

        async def maintenance_loop() -> None:
            while True:
                await asyncio.sleep(interval_seconds)
                readiness = await asyncio.to_thread(
                    app.state.v2_store.check_readiness
                )
                if not readiness.ready:
                    readiness = await asyncio.to_thread(
                        app.state.v2_store.initialize_runtime
                    )
                if readiness.ready:
                    await asyncio.to_thread(
                        app.state.v2_store.cleanup_operational
                    )

        app.state.maintenance_task = asyncio.create_task(maintenance_loop())

    async def stop_database_runtime() -> None:
        task = app.state.maintenance_task
        app.state.maintenance_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.router.add_event_handler("startup", initialize_database_runtime)
    app.router.add_event_handler("shutdown", stop_database_runtime)
    app.router.add_event_handler("shutdown", app.state.job_dispatcher.close)

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
        "/api/v1/sessions/{session_id}/vision-stream-token",
        response_model=VisionStreamToken,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def issue_vision_stream_token(session_id: IdentifierPath) -> VisionStreamToken:
        issuer = app.state.vision_token_issuer
        if issuer is None:
            raise DomainError(
                409,
                "vision_token_unavailable",
                "backend Vision Stream tokens are not configured",
            )
        video_id = app.state.store.get_active_session_video_id(session_id)
        return VisionStreamToken.model_validate(issuer.issue(session_id, video_id))

    @app.post(
        "/api/v1/sessions/{session_id}/reaction-batches",
        response_model=ReactionBatchAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
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
        "/api/v1/conversions",
        response_model=ConversionOutcome,
        status_code=status.HTTP_201_CREATED,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def record_conversion(outcome: ConversionOutcome) -> ConversionOutcome:
        return app.state.store.record_conversion(outcome)

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

    @app.get("/healthz", response_model=Liveness)
    def healthz() -> Liveness:
        return Liveness(status="ok")

    @app.get(
        "/readyz",
        response_model=Readiness,
        responses={503: {"model": Readiness}},
    )
    def readyz(response: Response) -> Readiness:
        readiness = app.state.v2_store.check_readiness()
        if not readiness.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return Readiness(status="not_ready", reason=readiness.reason)
        return Readiness(status="ready", reason=None)

    @app.get("/api/v1/health", response_model=Health, deprecated=True)
    def health() -> Health:
        readiness = app.state.v2_store.check_readiness()
        return Health(
            status="ok" if readiness.ready else "degraded",
            database="up" if readiness.ready else "down",
        )

    @app.post(
        "/api/v2/sessions/{session_id}/observations",
        response_model=ObservationBatchAcceptedV2,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
        },
    )
    def append_v2_observations(
        session_id: IdentifierPath,
        batch: ObservationBatchV2,
    ) -> ObservationBatchAcceptedV2:
        return app.state.v2_store.append_batch(session_id, batch)

    @app.post(
        "/api/v2/sessions/{session_id}/complete",
        response_model=RecommendationAcceptedV2,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def complete_v2_session(session_id: IdentifierPath) -> RecommendationAcceptedV2:
        return app.state.v2_store.complete(
            session_id,
            app.state.central_client,
            app.state.job_dispatcher,
        )

    @app.get(
        "/api/v2/sessions/{session_id}/recommendation",
        response_model=RecommendationAcceptedV2 | RecommendationDecisionV2,
        responses={
            202: {"model": RecommendationAcceptedV2},
            404: {"model": ErrorResponse},
        },
    )
    def get_v2_recommendation(
        session_id: IdentifierPath,
        response: Response,
    ) -> RecommendationAcceptedV2 | RecommendationDecisionV2:
        recommendation = app.state.v2_store.get_recommendation(session_id)
        if isinstance(recommendation, RecommendationAcceptedV2):
            response.status_code = status.HTTP_202_ACCEPTED
        return recommendation

    @app.delete(
        "/api/v2/sessions/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses={404: {"model": ErrorResponse}},
    )
    def cancel_v2_session(session_id: IdentifierPath) -> Response:
        app.state.v2_store.cancel(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v2/products/{product_id}",
        response_model=ProductRecommendationItemV2,
        responses={404: {"model": ErrorResponse}},
    )
    def get_v2_product(product_id: IdentifierPath) -> ProductRecommendationItemV2:
        return app.state.v2_store.get_product(product_id)

    @app.get(
        "/api/v2/lookbooks/{lookbook_id}/manifest",
        response_model=LookbookManifest,
        responses={404: {"model": ErrorResponse}},
    )
    def get_v2_manifest(lookbook_id: IdentifierPath) -> LookbookManifest:
        return app.state.store.get_manifest(lookbook_id)

    @app.post(
        "/api/v2/sessions/{session_id}/manager-product-requests",
        response_model=ManagerProductRequestAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def request_v2_manager_product(
        session_id: IdentifierPath,
        request: ManagerProductRequestV2,
    ) -> ManagerProductRequestAccepted:
        return app.state.v2_store.request_manager_product(session_id, request)

    @app.get("/api/v2/manager/events", response_model=list[ManagerEventV2])
    def list_v2_manager_events(
        after_sequence: int | None = Query(default=None, ge=0),
    ) -> list[ManagerEventV2]:
        return app.state.v2_store.list_manager_events(after_sequence)

    return app


app = create_app()

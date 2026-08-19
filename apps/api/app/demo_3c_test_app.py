"""Explicit local-only API factory for the Demo 3-C camera smoke test.

This module is intentionally not selected through ``CENTRAL_AI_PROVIDER`` and
does not expose an ``app`` module variable.  Running it requires uvicorn's
``--factory`` option plus the static-AOI opt-in.  Its only central provider is
the deterministic test double; it cannot call Luna or a self-hosted endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.api.app.v2_central import (
    CentralRecommendationClient,
    DeterministicCentralStub,
    JobDispatcher,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEMO_STATIC_AOI_ENV = "MCM_LOOKBOOK_DEMO_STATIC_AOI"


def _require_local_demo_environment() -> None:
    """Reject configurations that could make this test app use live services."""

    if os.getenv(DEMO_STATIC_AOI_ENV, "").strip() != "1":
        raise RuntimeError(
            "Demo 3-C requires MCM_LOOKBOOK_DEMO_STATIC_AOI=1; "
            "the canonical pending AOI remains the default."
        )
    if os.getenv("DATABASE_URL", "").strip():
        raise RuntimeError("Demo 3-C test app never accepts DATABASE_URL.")
    if os.getenv("CENTRAL_AI_ENDPOINT", "").strip():
        raise RuntimeError("Demo 3-C test app never accepts CENTRAL_AI_ENDPOINT.")

    provider = os.getenv("CENTRAL_AI_PROVIDER", "").strip().lower()
    if provider not in {"", "unavailable"}:
        raise RuntimeError(
            "Demo 3-C uses its injected deterministic stub, not CENTRAL_AI_PROVIDER."
        )


def create_demo_3c_test_app(
    *,
    central_client: CentralRecommendationClient | None = None,
    job_dispatcher: JobDispatcher | None = None,
) -> FastAPI:
    """Build the disposable loopback app used by the manual camera smoke.

    Dependency injection is kept solely for the test suite.  The no-argument
    factory remains the manual-run entry point and always uses the test-only
    deterministic provider.
    """

    _require_local_demo_environment()
    return create_app(
        MemoryStore(REPOSITORY_ROOT),
        central_client=central_client or DeterministicCentralStub(),
        job_dispatcher=job_dispatcher,
        central_input_variant="C",
    )

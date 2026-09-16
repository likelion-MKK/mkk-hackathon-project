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
from apps.api.app.source_aoi import load_product_matching_catalog
from apps.api.app.store import MemoryStore
from apps.api.app.v2_central import (
    CentralRecommendationClient,
    DeterministicCentralStub,
    JobDispatcher,
)
from apps.api.app.v2_postgres import load_canonical_catalog
from apps.api.app.v2_store import MemoryStoreRecommendationRepository, V2RecommendationStore


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
    store = MemoryStore(REPOSITORY_ROOT)
    # Use the already-approved product records for the final screen. The old
    # contract fixture has all assets pending and therefore hides every product.
    repository = MemoryStoreRecommendationRepository(
        store,
        catalog=load_canonical_catalog(
            REPOSITORY_ROOT / "data/products/mcm-submission-recommendation-profile-v4.json"
        ),
        matching_catalog=load_product_matching_catalog(
            REPOSITORY_ROOT,
            REPOSITORY_ROOT / "data/products/mcm-submission-matching-profiles-v4.json",
        ),
        aoi_metadata_paths={
            "mcm-lookbook-v2": REPOSITORY_ROOT
            / "data/lookbooks/mcm-lookbook-v2/aoi-metadata-v2-demo-static-assumptions.json",
        },
        source_aoi_enabled=False,
    )
    return create_app(
        store,
        central_client=central_client or DeterministicCentralStub(),
        job_dispatcher=job_dispatcher,
        central_input_variant="C",
        v2_store=V2RecommendationStore(repository, input_variant="C"),
    )

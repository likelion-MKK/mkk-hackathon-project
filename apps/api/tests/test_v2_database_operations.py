from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.api.app.v2_central import DeterministicCentralStub, ManualJobDispatcher
from apps.api.app.v2_models import (
    RecommendationAcceptedV2,
    RecommendationDecisionV2,
    RecommendationVersionV2,
)
from apps.api.app.v2_postgres import (
    CatalogReadinessError,
    DatabaseReadiness,
    PostgresDecisionPersistence,
    catalog_readiness_rows,
    load_canonical_catalog,
    require_direct_database_url,
    require_runtime_database_url,
    validate_catalog_rows,
)
from apps.api.app.v2_store import (
    MemoryStoreRecommendationRepository,
    V2RecommendationStore,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG = load_canonical_catalog(
    REPOSITORY_ROOT / "data" / "products" / "mcm-demo-recommendation-profile-v2.json"
)


class FakeDatabase:
    def __init__(self) -> None:
        self.connected = True
        self.migration_table = True
        self.migration_applied = True
        self.versions = [CATALOG.catalog_version]
        self.catalog_rows = catalog_readiness_rows(CATALOG)
        self.jobs: dict[str, dict[str, object]] = {}
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def connect(self) -> "FakeConnection":
        if not self.connected:
            raise RuntimeError("driver detail with postgresql://secret-value")
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self.database)


class FakeCursor:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.one: tuple[object, ...] | None = None
        self.many: list[tuple[object, ...]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def executemany(self, query: str, params_seq: list[tuple[object, ...]]) -> None:
        self.database.queries.append((query, tuple(params_seq)))

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        assert query.count("%s") == len(params)
        self.database.queries.append((query, params))
        normalized = " ".join(query.lower().split())
        self.one = None
        self.many = []

        if normalized == "select 1":
            self.one = (1,)
        elif "to_regclass('public.mcm_schema_migration')" in normalized:
            self.one = (
                "mcm_schema_migration" if self.database.migration_table else None,
            )
        elif "select exists" in normalized and "mcm_schema_migration" in normalized:
            self.one = (self.database.migration_applied,)
        elif "select distinct catalog_version" in normalized:
            self.many = [(version,) for version in self.database.versions]
        elif (
            "from recommendation_catalog_v2" in normalized
            and "where catalog_version" in normalized
        ):
            self.many = list(self.database.catalog_rows)
        elif "failure_reason_code = 'service_restart'" in normalized:
            changed = 0
            for job in self.database.jobs.values():
                if job["status"] in {"pending", "running"}:
                    job.update(status="failed", failure_reason_code="service_restart")
                    changed += 1
            self.one = (changed,)
        elif (
            "insert into recommendation_job_v2" in normalized
            and "returning decision_request_id, recommendation_id, session_id" in normalized
        ):
            decision_request_id, recommendation_id, session_id = params[:3]
            existing = next(
                (
                    job
                    for job in self.database.jobs.values()
                    if job["recommendation_id"] == recommendation_id
                ),
                None,
            )
            if existing is None and decision_request_id not in self.database.jobs:
                self.database.jobs[str(decision_request_id)] = {
                    "decision_request_id": decision_request_id,
                    "recommendation_id": recommendation_id,
                    "session_id": session_id,
                    "status": "pending",
                    "age_seconds": 0.0,
                }
                self.one = (decision_request_id, recommendation_id, session_id)
        elif (
            "select decision_request_id, recommendation_id, session_id" in normalized
            and "where recommendation_id" in normalized
        ):
            recommendation_id = params[0]
            existing = next(
                (
                    job
                    for job in self.database.jobs.values()
                    if job["recommendation_id"] == recommendation_id
                ),
                None,
            )
            if existing is not None:
                self.one = (
                    existing["decision_request_id"],
                    existing["recommendation_id"],
                    existing["session_id"],
                )
        elif "set status = 'running'" in normalized:
            decision_request_id = str(params[0])
            job = self.database.jobs.get(decision_request_id)
            if job is not None and job["status"] == "pending":
                job["status"] = "running"
                self.one = (decision_request_id,)
        elif "select (select count(*) from inserted)" in normalized:
            decision_request_id = str(params[0])
            job = self.database.jobs.get(decision_request_id)
            if job is None:
                self.database.jobs[decision_request_id] = {
                    "decision_request_id": params[0],
                    "recommendation_id": params[1],
                    "session_id": params[2],
                    "status": params[3],
                    "age_seconds": 0.0,
                }
                self.one = (1,)
            elif job["status"] in {"pending", "running"}:
                job["status"] = params[3]
                self.one = (1,)
            else:
                self.one = (0,)
        elif "set status = 'cancelled'" in normalized:
            decision_request_id = str(params[0])
            job = self.database.jobs.get(decision_request_id)
            if job is not None and job["status"] in {"pending", "running"}:
                job.update(status="cancelled", failure_reason_code="cancelled")
                self.one = (decision_request_id,)
        elif "failure_reason_code = 'orphan_cleanup'" in normalized:
            threshold = float(params[0])
            changed = 0
            for job in self.database.jobs.values():
                if (
                    job["status"] in {"pending", "running"}
                    and float(job["age_seconds"]) > threshold
                ):
                    job.update(status="failed", failure_reason_code="orphan_cleanup")
                    changed += 1
            self.one = (changed,)
        elif normalized.startswith("with deleted as"):
            threshold = float(params[0])
            terminal = {"completed", "failed", "cancelled", "insufficient_data"}
            deleted = [
                key
                for key, job in self.database.jobs.items()
                if job["status"] in terminal
                and float(job["age_seconds"]) > threshold
            ]
            for key in deleted:
                del self.database.jobs[key]
            self.one = (len(deleted),)
        elif "failure_reason_code = %s" in normalized and "returning decision_request_id" in normalized:
            reason, raw_id = params
            decision_request_id = str(raw_id)
            job = self.database.jobs.get(decision_request_id)
            if job is not None and job["status"] in {"pending", "running"}:
                job.update(status="failed", failure_reason_code=reason)
                self.one = (decision_request_id,)
        else:  # pragma: no cover - catches new SQL that needs explicit test semantics
            raise AssertionError(f"unhandled SQL in fake database: {normalized}")

    def fetchone(self) -> tuple[object, ...] | None:
        return self.one

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.many


def _version() -> RecommendationVersionV2:
    return RecommendationVersionV2(
        model_id="test-model",
        model_revision="test-revision",
        prompt_version="test-prompt",
        feature_version="test-feature",
        catalog_version=CATALOG.catalog_version,
        input_variant="C",
        deployment_mode="self_hosted",
    )


def _accepted() -> RecommendationAcceptedV2:
    return RecommendationAcceptedV2(
        recommendation_id="recommendation-v2-session-db-001",
        decision_request_id="decision-v2-session-db-001",
        status="pending",
    )


def test_database_connection_and_migration_readiness_are_safely_classified() -> None:
    database = FakeDatabase()
    persistence = PostgresDecisionPersistence(database.connect)

    assert persistence.initialize_runtime(CATALOG) == DatabaseReadiness(True)

    database.connected = False
    assert persistence.check_readiness(CATALOG) == DatabaseReadiness(
        False, "db_unavailable"
    )

    database.connected = True
    database.migration_applied = False
    assert persistence.check_readiness(CATALOG) == DatabaseReadiness(
        False, "migration_version_mismatch"
    )


@pytest.mark.parametrize("count", [9, 11])
def test_catalog_count_mismatch_fails_readiness(count: int) -> None:
    database = FakeDatabase()
    database.catalog_rows = catalog_readiness_rows(CATALOG)[:count]
    if count == 11:
        database.catalog_rows.append(tuple(database.catalog_rows[0]))
    readiness = PostgresDecisionPersistence(database.connect).check_readiness(
        CATALOG, require_job_intake=False
    )
    assert readiness == DatabaseReadiness(False, "catalog_count_mismatch")


def test_catalog_revision_unknown_product_and_controlled_tag_mismatch_fail() -> None:
    database = FakeDatabase()
    persistence = PostgresDecisionPersistence(database.connect)

    database.versions = ["old-catalog-revision"]
    assert persistence.check_readiness(
        CATALOG, require_job_intake=False
    ) == DatabaseReadiness(False, "catalog_revision_mismatch")

    database.versions = [CATALOG.catalog_version]
    rows = catalog_readiness_rows(CATALOG)
    rows[0] = ("unknown-product-id", *rows[0][1:])
    database.catalog_rows = rows
    assert persistence.check_readiness(
        CATALOG, require_job_intake=False
    ) == DatabaseReadiness(False, "catalog_product_mismatch")

    rows = catalog_readiness_rows(CATALOG)
    changed = list(rows[0])
    changed[3] = ["unknown_controlled_tag"]
    rows[0] = tuple(changed)
    database.catalog_rows = rows
    assert persistence.check_readiness(
        CATALOG, require_job_intake=False
    ) == DatabaseReadiness(False, "catalog_content_mismatch")


def test_healthz_is_liveness_while_readyz_fails_without_leaking_driver_details() -> None:
    database = FakeDatabase()
    database.connected = False
    persistence = PostgresDecisionPersistence(database.connect)
    memory = MemoryStore(REPOSITORY_ROOT)
    repository = MemoryStoreRecommendationRepository(
        memory,
        catalog=CATALOG,
        persistence=persistence,
        database_required=True,
    )
    app = create_app(
        memory,
        central_client=DeterministicCentralStub(),
        job_dispatcher=ManualJobDispatcher(),
        v2_store=V2RecommendationStore(repository),
    )

    with TestClient(app) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        legacy = client.get("/api/v1/health")
        session = client.post(
            "/api/v1/sessions",
            json={
                "kiosk_id": "kiosk-readiness-test",
                "lookbook_id": "mcm-central-ai-replay-v2",
                "consent_version": "consent-v1",
            },
        ).json()
        blocked = client.post(
            f"/api/v2/sessions/{session['session_id']}/complete"
        )

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "reason": "db_unavailable"}
    assert "secret-value" not in ready.text
    assert legacy.json() == {"status": "degraded", "database": "down"}
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "service_not_ready"


def test_readyz_requires_exact_catalog_and_completed_startup_cleanup() -> None:
    database = FakeDatabase()
    persistence = PostgresDecisionPersistence(database.connect)
    memory = MemoryStore(REPOSITORY_ROOT)
    repository = MemoryStoreRecommendationRepository(
        memory,
        catalog=CATALOG,
        persistence=persistence,
        database_required=True,
    )
    app = create_app(
        memory,
        central_client=DeterministicCentralStub(),
        job_dispatcher=ManualJobDispatcher(),
        v2_store=V2RecommendationStore(repository),
    )
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "reason": None}


def test_pending_insert_is_idempotent_and_job_claim_occurs_once() -> None:
    database = FakeDatabase()
    persistence = PostgresDecisionPersistence(database.connect)
    accepted = _accepted()

    assert persistence.save_pending("session-db", accepted, _version()) is True
    assert persistence.save_pending("session-db", accepted, _version()) is True
    assert len(database.jobs) == 1
    assert persistence.claim_job(accepted.decision_request_id) is True
    assert persistence.claim_job(accepted.decision_request_id) is False


def test_restart_orphan_and_retention_cleanup_are_bounded_and_idempotent() -> None:
    database = FakeDatabase()
    database.jobs = {
        "pending": {
            "decision_request_id": "pending",
            "recommendation_id": "recommendation-pending",
            "session_id": "session-pending",
            "status": "pending",
            "age_seconds": 1_801.0,
        },
        "running": {
            "decision_request_id": "running",
            "recommendation_id": "recommendation-running",
            "session_id": "session-running",
            "status": "running",
            "age_seconds": 1_801.0,
        },
        "completed": {
            "decision_request_id": "completed",
            "recommendation_id": "recommendation-completed",
            "session_id": "session-completed",
            "status": "completed",
            "age_seconds": 86_401.0,
        },
    }
    persistence = PostgresDecisionPersistence(database.connect)

    assert persistence.mark_inflight_jobs_failed_on_startup() == 2
    assert database.jobs["pending"]["failure_reason_code"] == "service_restart"
    assert database.jobs["running"]["failure_reason_code"] == "service_restart"
    assert persistence.mark_inflight_jobs_failed_on_startup() == 0

    database.jobs["orphan"] = {
        "decision_request_id": "orphan",
        "recommendation_id": "recommendation-orphan",
        "session_id": "session-orphan",
        "status": "running",
        "age_seconds": 1_801.0,
    }
    assert persistence.cleanup_orphan_jobs(1_800.0) == 1
    assert database.jobs["orphan"]["failure_reason_code"] == "orphan_cleanup"
    assert persistence.cleanup_orphan_jobs(1_800.0) == 0

    assert persistence.cleanup_retention(86_400.0) == 1
    assert "completed" not in database.jobs
    assert persistence.cleanup_retention(86_400.0) == 0


def test_restart_cleanup_does_not_restore_jobs_when_catalog_is_not_ready() -> None:
    database = FakeDatabase()
    database.catalog_rows = catalog_readiness_rows(CATALOG)[:9]
    database.jobs["pending"] = {
        "decision_request_id": "pending",
        "recommendation_id": "recommendation-pending",
        "session_id": "session-pending",
        "status": "pending",
        "age_seconds": 1.0,
    }
    persistence = PostgresDecisionPersistence(database.connect)

    readiness = persistence.initialize_runtime(CATALOG)

    assert readiness == DatabaseReadiness(False, "catalog_count_mismatch")
    assert database.jobs["pending"]["status"] == "failed"
    assert database.jobs["pending"]["failure_reason_code"] == "service_restart"


def test_minimal_decision_persistence_excludes_raw_or_free_form_payloads() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "contracts"
            / "examples"
            / "recommendation-decision-v2.valid.json"
        ).read_text(encoding="utf-8")
    )
    payload["reason"]["explanation"] = "raw-model-free-form-sentinel"
    payload["evidence"][0]["statement"] = "raw-evidence-sentinel"
    payload["style"]["summary"] = "raw-style-sentinel"
    decision = RecommendationDecisionV2.model_validate(payload)
    database = FakeDatabase()
    persistence = PostgresDecisionPersistence(database.connect)

    assert persistence.save_decision("session-private", decision) is True
    query, params = database.queries[-1]
    assert params[4] == decision.version.input_variant
    assert params[7] == list(decision.reason_codes)
    assert params[8] == decision.exploration_tendency_code
    serialized_params = repr(params)
    for forbidden in (
        "raw-model-free-form-sentinel",
        "raw-evidence-sentinel",
        "raw-style-sentinel",
        "video_x_norm",
        "screen_x_norm",
        "stream_token",
        "raw_frame",
    ):
        assert forbidden not in serialized_params
    assert "evidence = '[]'::jsonb" in query
    assert "reason_explanation = NULL" in query
    assert "data_quality = NULL" in query


def test_database_url_roles_reject_supabase_connection_mixups() -> None:
    runtime = (
        "postgresql://postgres.project:placeholder@"
        "aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
    )
    direct = "postgresql://postgres:placeholder@db.project.supabase.co:5432/postgres"
    assert require_runtime_database_url(runtime) == runtime
    assert require_direct_database_url(direct) == direct
    with pytest.raises(ValueError, match="direct"):
        require_direct_database_url(runtime)
    with pytest.raises(ValueError, match="session pooler"):
        require_runtime_database_url(direct)
    with pytest.raises(ValueError, match="direct connection"):
        require_direct_database_url("postgresql://postgres:placeholder@localhost:5432/postgres")
    with pytest.raises(ValueError, match="session pooler"):
        require_runtime_database_url(
            "postgresql://postgres.project:placeholder@"
            "aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
        )


def test_pending_memory_ttl_cannot_outlive_database_orphan_cleanup() -> None:
    repository = MemoryStoreRecommendationRepository(
        MemoryStore(REPOSITORY_ROOT), catalog=CATALOG
    )
    with pytest.raises(ValueError, match="pending_ttl_seconds"):
        V2RecommendationStore(
            repository,
            pending_ttl_seconds=1_801.0,
            orphan_job_seconds=1_800.0,
        )


def test_browser_sources_do_not_receive_database_credentials_or_supabase_client() -> None:
    browser_files = [
        *(
            REPOSITORY_ROOT / "apps" / "kiosk" / "src"
        ).rglob("*.ts"),
        *(
            REPOSITORY_ROOT / "apps" / "kiosk" / "src"
        ).rglob("*.tsx"),
        *(
            REPOSITORY_ROOT / "apps" / "manager" / "src"
        ).rglob("*.ts"),
        *(
            REPOSITORY_ROOT / "apps" / "manager" / "src"
        ).rglob("*.tsx"),
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in browser_files
    )
    for forbidden in (
        "database_url",
        "migration_database_url",
        "@supabase/supabase-js",
        "pooler.supabase.com",
        "db.project.supabase.co",
    ):
        assert forbidden not in combined


def test_catalog_row_validator_never_repairs_invalid_rows() -> None:
    rows = catalog_readiness_rows(CATALOG)[:9]
    with pytest.raises(CatalogReadinessError) as exc_info:
        validate_catalog_rows(rows, CATALOG)
    assert exc_info.value.reason == "catalog_count_mismatch"
    assert len(rows) == 9

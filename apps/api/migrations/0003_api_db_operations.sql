-- API/DB operations hardening for Supabase PostgreSQL.
-- 0001 and 0002 remain immutable. This migration stores only catalog and
-- minimal job/decision metadata; no frame, coordinate, token, timeline,
-- request body, model payload, or free-form model response is retained.

BEGIN;

CREATE TABLE IF NOT EXISTS mcm_schema_migration (
    migration_id text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO mcm_schema_migration (migration_id)
VALUES
    ('0001_central_recommendation_v2'),
    ('0002_catalog_assets_and_provider'),
    ('0003_api_db_operations')
ON CONFLICT (migration_id) DO NOTHING;

ALTER TABLE recommendation_job_v2
    ADD COLUMN IF NOT EXISTS failure_reason_code text,
    ADD COLUMN IF NOT EXISTS claimed_at timestamptz,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS lock_version bigint NOT NULL DEFAULT 0;

ALTER TABLE recommendation_job_v2
    DROP CONSTRAINT IF EXISTS recommendation_job_v2_status_check;

ALTER TABLE recommendation_job_v2
    ADD CONSTRAINT recommendation_job_v2_status_check CHECK (
        status IN (
            'pending',
            'running',
            'completed',
            'failed',
            'cancelled',
            'insufficient_data'
        )
    );

ALTER TABLE recommendation_job_v2
    DROP CONSTRAINT IF EXISTS recommendation_job_v2_failure_reason_code_check;

ALTER TABLE recommendation_job_v2
    ADD CONSTRAINT recommendation_job_v2_failure_reason_code_check CHECK (
        failure_reason_code IS NULL OR failure_reason_code IN (
            'service_restart',
            'orphan_cleanup',
            'cancelled',
            'job_start_failed',
            'model_unavailable',
            'invalid_model_output',
            'catalog_mismatch',
            'insufficient_valid_signal',
            'no_eligible_product'
        )
    );

-- Any pre-migration in-flight record cannot be resumed because its evidence
-- was intentionally memory-only. Close only those exact rows before adding
-- the active-session uniqueness guard.
UPDATE recommendation_job_v2
SET status = 'failed',
    selected_product_id = NULL,
    reason_code = 'model_unavailable',
    reason_explanation = NULL,
    reason_codes = '{}',
    evidence = '[]'::jsonb,
    style = NULL,
    exploration_tendency_code = NULL,
    data_quality = NULL,
    failure_reason_code = 'service_restart',
    completed_at = now(),
    updated_at = now(),
    lock_version = lock_version + 1
WHERE status IN ('pending', 'running');

-- Remove fields that older application revisions may have persisted. The
-- selected product, controlled codes, versions, provider, status and
-- timestamps remain as the minimal decision audit record.
UPDATE recommendation_job_v2
SET reason_explanation = NULL,
    evidence = '[]'::jsonb,
    style = NULL,
    data_quality = NULL,
    updated_at = now()
WHERE reason_explanation IS NOT NULL
   OR evidence <> '[]'::jsonb
   OR style IS NOT NULL
   OR data_quality IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS recommendation_job_v2_one_active_session_idx
    ON recommendation_job_v2 (session_id)
    WHERE status IN ('pending', 'running');

CREATE INDEX IF NOT EXISTS recommendation_job_v2_cleanup_idx
    ON recommendation_job_v2 (status, updated_at);

COMMIT;

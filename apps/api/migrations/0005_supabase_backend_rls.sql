-- Expose no application tables to the browser-facing anon/authenticated roles.
-- The API uses a direct PostgreSQL connection; service_role is retained for
-- controlled administrative access through Supabase tooling.  Do not FORCE
-- RLS: the database owner must continue to run the API and migrations.

ALTER TABLE recommendation_catalog_v2 ENABLE ROW LEVEL SECURITY;
ALTER TABLE recommendation_job_v2 ENABLE ROW LEVEL SECURITY;
ALTER TABLE recommendation_catalog_asset_v2 ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcm_schema_migration ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS recommendation_catalog_backend_all
    ON recommendation_catalog_v2;
CREATE POLICY recommendation_catalog_backend_all
    ON recommendation_catalog_v2
    FOR ALL
    TO postgres, service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS recommendation_job_backend_all
    ON recommendation_job_v2;
CREATE POLICY recommendation_job_backend_all
    ON recommendation_job_v2
    FOR ALL
    TO postgres, service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS recommendation_catalog_asset_backend_all
    ON recommendation_catalog_asset_v2;
CREATE POLICY recommendation_catalog_asset_backend_all
    ON recommendation_catalog_asset_v2
    FOR ALL
    TO postgres, service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS mcm_schema_migration_backend_all
    ON mcm_schema_migration;
CREATE POLICY mcm_schema_migration_backend_all
    ON mcm_schema_migration
    FOR ALL
    TO postgres, service_role
    USING (true)
    WITH CHECK (true);

INSERT INTO mcm_schema_migration (migration_id)
VALUES ('0005_supabase_backend_rls')
ON CONFLICT (migration_id) DO NOTHING;

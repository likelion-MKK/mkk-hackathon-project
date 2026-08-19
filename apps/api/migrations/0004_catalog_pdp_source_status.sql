-- Allow catalog records whose official PDP identity is verified while assets remain pending.
-- 0001 through 0003 remain immutable. This migration changes only the catalog
-- source-status constraint and stores no customer-derived data.

BEGIN;

INSERT INTO mcm_schema_migration (migration_id)
VALUES ('0004_catalog_pdp_source_status')
ON CONFLICT (migration_id) DO NOTHING;

ALTER TABLE recommendation_catalog_v2
    DROP CONSTRAINT IF EXISTS recommendation_catalog_v2_source_status_check;

ALTER TABLE recommendation_catalog_v2
    ADD CONSTRAINT recommendation_catalog_v2_source_status_check CHECK (
        source_status IN (
            'demo_placeholder',
            'official_listing_name_verified_assets_pending',
            'official_product_page_verified_assets_pending',
            'team_approved_catalog_record'
        )
    );

ALTER TABLE recommendation_catalog_v2
    DROP CONSTRAINT IF EXISTS recommendation_catalog_v2_pdp_pending_check;

ALTER TABLE recommendation_catalog_v2
    ADD CONSTRAINT recommendation_catalog_v2_pdp_pending_check CHECK (
        source_status <> 'official_product_page_verified_assets_pending'
        OR (
            approved_asset = false
            AND official_product_url IS NOT NULL
            AND official_product_url_reason IS NULL
            AND image_asset_path IS NULL
            AND image_asset_path_reason IS NOT NULL
            AND qr_asset_path IS NULL
            AND qr_asset_path_reason IS NOT NULL
        )
    );

COMMIT;

-- Additive production metadata only. 0001 remains immutable.
-- No frame, observation, timeline, image bytes, embedding or request-body data
-- is stored in this table.

ALTER TABLE recommendation_job_v2
    ADD COLUMN IF NOT EXISTS central_provider text NOT NULL DEFAULT 'self_hosted';

CREATE TABLE IF NOT EXISTS recommendation_catalog_asset_v2 (
    catalog_version text NOT NULL,
    product_id text NOT NULL,
    asset_kind text NOT NULL CHECK (asset_kind IN ('image', 'qr', 'video')),
    relative_path text NOT NULL,
    source_url text,
    sha256 char(64),
    approval_note text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog_version, product_id, asset_kind),
    FOREIGN KEY (catalog_version, product_id)
        REFERENCES recommendation_catalog_v2 (catalog_version, product_id),
    CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS recommendation_catalog_asset_v2_product_idx
    ON recommendation_catalog_asset_v2 (product_id, asset_kind);

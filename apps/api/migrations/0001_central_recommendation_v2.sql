-- Central recommendation v2 persistent boundary.
-- Deliberately absent: frame, observation, timeline, image, embedding or request-body tables.

CREATE TABLE IF NOT EXISTS recommendation_catalog_v2 (
    catalog_version text NOT NULL,
    product_id text NOT NULL,
    display_name text NOT NULL,
    category text NOT NULL CHECK (category = 'bag'),
    controlled_tags text[] NOT NULL,
    recommendation_summary text NOT NULL,
    style jsonb NOT NULL,
    approved_asset boolean NOT NULL,
    source_status text NOT NULL CHECK (
        source_status IN (
            'demo_placeholder',
            'official_listing_name_verified_assets_pending',
            'team_approved_catalog_record'
        )
    ),
    official_product_url text,
    official_product_url_reason text,
    official_listing_url text NOT NULL,
    image_asset_path text,
    image_asset_path_reason text,
    qr_asset_path text,
    qr_asset_path_reason text,
    source_note text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog_version, product_id),
    CHECK (cardinality(controlled_tags) BETWEEN 3 AND 12),
    CHECK ((official_product_url IS NULL) <> (official_product_url_reason IS NULL)),
    CHECK ((image_asset_path IS NULL) <> (image_asset_path_reason IS NULL)),
    CHECK ((qr_asset_path IS NULL) <> (qr_asset_path_reason IS NULL))
);

CREATE TABLE IF NOT EXISTS recommendation_job_v2 (
    decision_request_id text PRIMARY KEY,
    recommendation_id text NOT NULL UNIQUE,
    session_id text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('pending', 'completed', 'insufficient_data', 'failed')
    ),
    input_variant text NOT NULL CHECK (input_variant IN ('A', 'B', 'C')),
    selected_product_id text,
    reason_code text,
    reason_explanation text,
    reason_codes text[] NOT NULL DEFAULT '{}',
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    style jsonb,
    exploration_tendency_code text,
    data_quality jsonb,
    catalog_version text NOT NULL,
    model_id text NOT NULL,
    model_revision text NOT NULL,
    prompt_version text NOT NULL,
    feature_version text NOT NULL,
    deployment_mode text NOT NULL CHECK (deployment_mode = 'self_hosted'),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    FOREIGN KEY (catalog_version, selected_product_id)
        REFERENCES recommendation_catalog_v2 (catalog_version, product_id),
    CHECK (
        (status = 'completed' AND selected_product_id IS NOT NULL AND completed_at IS NOT NULL)
        OR
        (status <> 'completed' AND selected_product_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS recommendation_job_v2_session_idx
    ON recommendation_job_v2 (session_id, created_at DESC);

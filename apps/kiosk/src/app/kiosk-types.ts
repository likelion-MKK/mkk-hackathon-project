export type KioskScreen =
  | "screensaver"
  | "menu"
  | "consent"
  | "calibration"
  | "lookbook"
  | "finalizing"
  | "report";

export type ProductCategory = "가방" | "의류" | "액세서리" | "전체 컬렉션";

export type SchemaVersion = "1.0";
export type SchemaVersionV2 = "2.0";

export type SessionCreate = {
  kiosk_id: string;
  lookbook_id: string;
  consent_version: string;
};

export type SessionCreated = {
  session_id: string;
  display_code: string;
  status: "created" | "collecting";
  created_at: string;
};

export type NormalizedPoint = [number, number];

export type ProductPart = "handle" | "body" | "accessory";

export type LookbookExposure = {
  exposure_id: string;
  product_id: string;
  product_part?: ProductPart;
  start_ms: number;
  end_ms: number;
  priority: number;
  shape: {
    type: "polygon";
    points: NormalizedPoint[];
  };
};

export type LookbookManifest = {
  schema_version: SchemaVersion;
  video_id: string;
  manifest_version: string;
  coordinate_space: "video_normalized";
  exposures: LookbookExposure[];
};

type ObservationBase = {
  schema_version: SchemaVersion;
  session_id: string;
  event_id: string;
  sequence: number;
  frame_id: string;
  captured_at_mono_ms: number;
  video_id: string;
  video_time_ms: number;
  playback_epoch: number;
  producer_id: string;
  model_revision: string;
  confidence: number;
};

export type GazeSample = ObservationBase &
  {
    calibration_id: string;
  } & (
    | {
        valid: true;
        screen_x_norm: number;
        screen_y_norm: number;
        reason: null;
      }
    | {
        valid: false;
        screen_x_norm?: never;
        screen_y_norm?: never;
        reason: string;
      }
  );

export type ExpressionSample = ObservationBase &
  {
    taxonomy_version: string;
    quality: number;
  } & (
    | {
        face_detected: true;
        face_count: 1;
        scores: Record<string, number>;
        valid: true;
        reason: null;
      }
    | {
        face_detected: boolean;
        face_count: number;
        scores: Record<string, never>;
        valid: false;
        reason: string;
      }
  );

type ProductCandidate = {
  exposure_id: string;
  product_id: string;
  product_part?: ProductPart;
  priority: number;
};

export type ProductAttentionEvent = ObservationBase &
  {
    manifest_version: string;
    source_gaze_event_id: string;
  } & (
    | {
        outside_video: false;
        video_x_norm: number;
        video_y_norm: number;
        candidates: ProductCandidate[];
        valid: true;
        reason: null;
      }
    | {
        outside_video: true;
        video_x_norm?: never;
        video_y_norm?: never;
        candidates: [];
        valid: true;
        reason: null;
      }
    | {
        outside_video: boolean;
        video_x_norm?: never;
        video_y_norm?: never;
        candidates: [];
        valid: false;
        reason: string;
      }
  );

export type ReactionBatch = {
  schema_version: SchemaVersion;
  batch_id: string;
  batch_sequence: number;
  session_id: string;
  video_id: string;
  events: [
    ExpressionSample | ProductAttentionEvent,
    ...(ExpressionSample | ProductAttentionEvent)[],
  ];
};

export type ReactionBatchAccepted = {
  batch_id: string;
  status: "accepted" | "duplicate";
};

export type AttentionCandidateV2 = {
  exposure_id: string;
  product_id: string;
  product_part?: ProductPart;
  priority: number;
};

export type GazeObservationV2 = {
  screen_x_norm: number;
  screen_y_norm: number;
  confidence: number;
  producer_id: string;
  model_revision: string;
  calibration_id: string;
};

export type AttentionObservationV2 = {
  outside_video: boolean;
  video_x_norm?: number;
  video_y_norm?: number;
  confidence: number;
  producer_id: string;
  model_revision: string;
  manifest_version: string;
  candidates: AttentionCandidateV2[];
};

export type ExpressionObservationV2 = {
  scores: Record<string, number>;
  quality: number;
  confidence: number;
  producer_id: string;
  model_revision: string;
  taxonomy_version: string;
};

export type GazeDerivedV2 = {
  movement: {
    distance_norm: number;
    speed_norm_per_s: number;
  } | null;
  movement_reason: string | null;
  continuous_observation_ms: number;
  return_candidate: boolean | null;
  return_candidate_reason: string | null;
};

export type ExpressionDerivedV2 = {
  score_changes: Record<string, number> | null;
  score_change_rates_per_s: Record<string, number> | null;
  change_reason: string | null;
  sustained_actions: Array<{
    signal: string;
    duration_ms: number;
  }>;
};

export type FrameDerivedV2 = {
  gaze: GazeDerivedV2 | null;
  gaze_reason: string | null;
  expression: ExpressionDerivedV2 | null;
  expression_reason: string | null;
};

export type FrameObservationV2 = {
  schema_version: SchemaVersionV2;
  frame_id: string;
  sequence: number;
  captured_at_mono_ms: number;
  session_offset_ms: number;
  video_time_ms: number;
  playback_epoch: number;
  gaze: GazeObservationV2 | null;
  gaze_reason: string | null;
  attention: AttentionObservationV2 | null;
  attention_reason: string | null;
  expression: ExpressionObservationV2 | null;
  expression_reason: string | null;
  derived: FrameDerivedV2 | null;
  derived_reason: string | null;
};

export type ObservationBatchV2 = {
  schema_version: SchemaVersionV2;
  batch_id: string;
  batch_sequence: number;
  session_id: string;
  video_id: string;
  observations: [FrameObservationV2, ...FrameObservationV2[]];
};

export type ObservationBatchAcceptedV2 = {
  batch_id: string;
  status: "accepted" | "duplicate";
};

export type ManagerProductRequest = {
  request_id: string;
  recommendation_id: string;
};

export type ManagerProductRequestAccepted = {
  request_id: string;
  status: "accepted" | "duplicate";
};

export type ManagerProductRequestV2 = {
  schema_version: SchemaVersionV2;
  request_id: string;
  recommendation_id: string;
  selected_product_id: string;
  intent: "view_recommended_product";
};

export type RecommendationAccepted = {
  session_id: string;
  status: "pending";
};

export type RecommendationAcceptedV2 = {
  recommendation_id: string;
  decision_request_id: string;
  status: "pending";
};

type RecommendationBase = {
  schema_version: SchemaVersion;
  recommendation_id: string;
  session_id: string;
  video_id: string;
  manifest_version: string;
  algorithm_version: string;
  engine_mode: "mock" | "research_version";
};

export type RecommendationResult = RecommendationBase &
  (
    | {
        status: "completed";
        items: [
          { rank: 1; product_id: string },
          { rank: 2; product_id: string },
        ];
        reason: null;
      }
    | {
        status: "pending";
        items: [];
        reason: null;
      }
    | {
        status: "insufficient_data" | "failed";
        items: [];
        reason: string;
      }
  );

export type RecommendationReasonCodeV2 =
  | "grounded_product_match"
  | "insufficient_valid_signal"
  | "no_eligible_product"
  | "model_unavailable"
  | "invalid_model_output"
  | "catalog_mismatch";

export type RecommendationEvidenceCodeV2 =
  | "observed_attention"
  | "return_candidate"
  | "gaze_movement"
  | "face_action_change"
  | "product_tag_match"
  | "data_quality";

export type RecommendationReasonCodeDetailV2 =
  | "observed_attention_lead"
  | "return_candidate_support"
  | "movement_pattern_support"
  | "observable_action_support"
  | "catalog_tag_alignment"
  | "sufficient_data_quality";

export type ExplorationTendencyCodeV2 =
  | "focused_single_product"
  | "comparative_exploration"
  | "broad_exploration";

export type RecommendationDecisionV2 = {
  schema_version: SchemaVersionV2;
  recommendation_id: string;
  decision_request_id: string;
  status: "completed" | "insufficient_data" | "failed";
  selected_product_id: string | null;
  reason: {
    code: RecommendationReasonCodeV2;
    explanation: string;
  };
  reason_codes: RecommendationReasonCodeDetailV2[];
  evidence: Array<{
    code: RecommendationEvidenceCodeV2;
    product_id: string;
    evidence_refs: Array<{
      kind: "window" | "frame";
      ref_id: string;
    }>;
    statement: string;
  }>;
  style: {
    matched_tags: string[];
    summary: string;
  } | null;
  exploration_tendency_code: ExplorationTendencyCodeV2 | null;
  data_quality: {
    expected_observation_count: number;
    gaze_valid_ratio: number;
    expression_valid_ratio: number;
    matched_frame_ratio: number;
    ambiguous_product_ratio: number;
  };
  version: {
    model_id: string;
    model_revision: string;
    prompt_version: string;
    feature_version: string;
    catalog_version: string;
    input_variant: "A" | "B" | "C";
    deployment_mode: "self_hosted";
  };
};

export type Product = {
  product_id: string;
  display_name: string;
  category: string;
  image_url: string;
  product_url: string;
  qr_asset_path: string;
};

export type ProductRecommendationItemV2 = {
  product_id: string;
  display_name: string;
  category: "bag";
  controlled_tags: string[];
  recommendation_summary: string;
  style: {
    silhouette: string;
    visual_tone: string;
    use_cases: string[];
  };
  approved_asset: boolean;
  source_status:
    | "demo_placeholder"
    | "official_listing_name_verified_assets_pending"
    | "team_approved_catalog_record";
  official_product_url: string | null;
  official_product_url_reason: string | null;
  official_listing_url: string;
  image_asset_path: string | null;
  image_asset_path_reason: string | null;
  qr_asset_path: string | null;
  qr_asset_path_reason: string | null;
  source_note: string;
};

export type ApiHealth = {
  status: "ok" | "degraded";
  database: "up" | "down";
};

export type VisionSessionContext = {
  session_id: string;
  video_id: string;
};

export type CalibrationPattern = {
  pattern_id: string;
  points: NormalizedPoint[];
};

export type CalibrationResult = {
  calibration_id: string;
  valid: boolean;
  reason: string | null;
};

export type VisionHealth = {
  status: "ok" | "degraded";
  runtime: "mock" | "mediapipe_gateway";
  session_active: boolean;
};

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

export type LookbookExposure = {
  exposure_id: string;
  product_id: string;
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

export type RecommendationAccepted = {
  session_id: string;
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

export type Product = {
  product_id: string;
  display_name: string;
  category: string;
  image_url: string;
  product_url: string;
  qr_asset_path: string;
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
  runtime: "mock";
  session_active: boolean;
};

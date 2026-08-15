import assert from "node:assert/strict";
import test from "node:test";
import type {
  ProductRecommendationItemV2,
  RecommendationDecisionV2,
} from "./kiosk-types.ts";
import { presentCentralRecommendation } from "./recommendation-presentation.ts";

const product: ProductRecommendationItemV2 = {
  product_id: "mcm-diamant-3d-small-calfskin",
  display_name: "Small Diamant 3D Shoulder Bag in Calfskin",
  category: "bag",
  controlled_tags: ["compact", "leather", "structured"],
  recommendation_summary: "팀 검수 요약",
  style: {
    silhouette: "boxy",
    visual_tone: "refined",
    use_cases: ["evening"],
  },
  approved_asset: false,
  source_status: "official_listing_name_verified_assets_pending",
  official_product_url: null,
  official_product_url_reason: "individual_product_url_unverified",
  official_listing_url: "https://us.mcmworldwide.com/en_US/women/bags/all-bags",
  image_asset_path: null,
  image_asset_path_reason: "asset_license_review_pending",
  qr_asset_path: null,
  qr_asset_path_reason: "official_product_url_unverified",
  source_note: "공식 목록에서 이름만 확인",
};

const decision: RecommendationDecisionV2 = {
  schema_version: "2.0",
  recommendation_id: "recommendation-v2-001",
  decision_request_id: "decision-v2-001",
  status: "completed",
  selected_product_id: product.product_id,
  reason: {
    code: "grounded_product_match",
    explanation: "고객의 감정을 단정하는 자유 문장이 들어와도 UI가 사용하지 않습니다.",
  },
  reason_codes: ["observed_attention_lead", "catalog_tag_alignment"],
  evidence: [
    {
      code: "observed_attention",
      product_id: product.product_id,
      evidence_refs: [{ kind: "window", ref_id: "window-001" }],
      statement: "고객의 성격을 단정하는 자유 문장이 들어와도 UI가 사용하지 않습니다.",
    },
  ],
  style: {
    matched_tags: ["compact", "structured"],
    summary: "AI 자유 생성 요약",
  },
  exploration_tendency_code: "focused_single_product",
  data_quality: {
    expected_observation_count: 240,
    gaze_valid_ratio: 0.8,
    expression_valid_ratio: 0.7,
    matched_frame_ratio: 0.6,
    ambiguous_product_ratio: 0.05,
  },
  version: {
    model_id: "central-model",
    model_revision: "revision",
    prompt_version: "prompt",
    feature_version: "feature",
    catalog_version: "catalog",
    input_variant: "C",
    deployment_mode: "self_hosted",
  },
};

test("고객 문구는 code와 DB controlled tag 템플릿으로만 만든다", () => {
  const presentation = presentCentralRecommendation(decision, product);
  assert.equal(presentation.tendency, "한 상품을 중심으로 살펴본 경향");
  assert.match(presentation.reason, /상대적으로 많은 유효 시선 관찰/);
  assert.match(presentation.reason, /컴팩트, 구조적인 형태/);
  assert.doesNotMatch(presentation.reason, /감정|성격|AI 자유 생성/);
});

test("다른 상품 근거나 통제되지 않은 tag를 표시하지 않는다", () => {
  assert.throws(
    () =>
      presentCentralRecommendation(
        {
          ...decision,
          evidence: [
            {
              ...decision.evidence[0],
              product_id: "mcm-other-product",
            },
          ],
        },
        product,
      ),
    /not grounded/,
  );
  assert.throws(
    () =>
      presentCentralRecommendation(
        {
          ...decision,
          style: { matched_tags: ["uncontrolled"], summary: "ignored" },
        },
        product,
      ),
    /not grounded/,
  );
});

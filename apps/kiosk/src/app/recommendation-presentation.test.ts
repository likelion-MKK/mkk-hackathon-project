import assert from "node:assert/strict";
import test from "node:test";
import type {
  ProductRecommendationItemV2,
  RecommendationDecisionV2,
} from "./kiosk-types.ts";
import { presentCentralRecommendation } from "./recommendation-presentation.ts";

const product: ProductRecommendationItemV2 = {
  product_id: "mcm-pina-vanity-case-studded-calfskin",
  display_name: "Pina Vanity Case in Studded Calfskin",
  category: "bag",
  controlled_tags: ["compact", "evening", "leather", "shoulder", "structured"],
  recommendation_summary:
    "컴팩트한 스터드 장식 가죽 베니티 케이스와 구조적인 숄더 스타일 방향을 비교하기 위한 팀 작성 추천 profile입니다.",
  style: {
    silhouette: "boxy",
    visual_tone: "refined",
    use_cases: ["evening", "weekend"],
  },
  approved_asset: false,
  source_status: "official_product_page_verified_assets_pending",
  official_product_url:
    "https://us.mcmworldwide.com/en_US/bags/shoulder-crossbody-bags/pina-vanity-case-in-studded-calfskin/MWRGATA01BK001.html",
  official_product_url_reason: null,
  official_listing_url: "https://us.mcmworldwide.com/en_US/women/bags/all-bags",
  image_asset_path: null,
  image_asset_path_reason: "asset_license_review_pending",
  qr_asset_path: null,
  qr_asset_path_reason: "qr_asset_generation_pending",
  source_note: "공식 MCM PDP URL과 SKU identity 확인, 자산과 PDP 본문 상세는 미검증",
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
  assert.equal(presentation.tendency, "한 상품에 시선이 오래 머문 흐름");
  assert.match(presentation.reason, /가장 오래 머문 시선/);
  assert.match(presentation.reason, /컴팩트·구조적인 형태/);
  assert.doesNotMatch(presentation.reason, /감정|성격|구매 의도|AI 자유 생성/);
});

test("명시적 로컬 데모 fallback은 시선 기반 추천으로 표시하지 않는다", () => {
  const presentation = presentCentralRecommendation(
    {
      ...decision,
      reason_codes: ["catalog_tag_alignment"],
      data_quality: { ...decision.data_quality, gaze_valid_ratio: 0 },
      version: { ...decision.version, model_id: "deterministic-test-stub" },
    },
    product,
  );
  assert.equal(presentation.mode, "demo_fallback_v2");
  // Without observed gaze the copy may only talk about reviewed catalog style.
  assert.equal(presentation.tendency, "스타일 취향 중심의 선택");
  assert.match(presentation.reason, /컴팩트·구조적인 형태/);
  assert.doesNotMatch(presentation.reason, /시선|응시|바라보|다시 돌아온/);
});

test("Luna 저신호 variant B는 유효 시선 추천으로 표현하지 않는다", () => {
  const presentation = presentCentralRecommendation(
    {
      ...decision,
      reason_codes: ["catalog_tag_alignment"],
      evidence: [
        {
          code: "data_quality",
          product_id: product.product_id,
          evidence_refs: [{ kind: "frame", ref_id: "frame-001" }],
          statement: "유효 시선 좌표가 없어 결측 상태를 유지했습니다.",
        },
      ],
      data_quality: { ...decision.data_quality, gaze_valid_ratio: 0 },
      version: {
        ...decision.version,
        model_id: "gpt-5.6-luna",
        input_variant: "B",
      },
    },
    product,
  );
  assert.equal(presentation.mode, "central_low_signal_v2");
  // Variant B ran without a single valid gaze coordinate, so the customer copy
  // must never imply that a gaze observation happened.
  assert.equal(presentation.tendency, "스타일 취향 중심의 선택");
  assert.match(presentation.reason, /컴팩트·구조적인 형태/);
  assert.doesNotMatch(presentation.reason, /시선|응시|바라보|다시 돌아온/);
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

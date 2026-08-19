import type {
  ExplorationTendencyCodeV2,
  ProductRecommendationItemV2,
  RecommendationDecisionV2,
  RecommendationReasonCodeDetailV2,
  RecommendationResult,
} from "./kiosk-types.ts";

export type RecommendationPresentation = {
  recommendation_id: string;
  product_id: string;
  tendency: string;
  reason: string;
  mode: "central_v2" | "central_low_signal_v2" | "demo_fallback_v2" | "replay_v2" | "mock_v1";
};

const TENDENCY_COPY: Record<ExplorationTendencyCodeV2, string> = {
  focused_single_product: "한 상품을 중심으로 살펴본 경향",
  comparative_exploration: "몇 가지 상품을 비교해 살펴본 경향",
  broad_exploration: "여러 상품을 폭넓게 살펴본 경향",
};

const REACTION_COPY: Record<RecommendationReasonCodeDetailV2, string> = {
  observed_attention_lead: "이 상품 구간에서 상대적으로 많은 유효 시선 관찰",
  return_candidate_support: "다른 구간을 본 뒤 이 상품 구간을 다시 확인한 관찰",
  movement_pattern_support: "이 상품 구간에서 이어진 시선 이동 관찰",
  observable_action_support: "이 상품 구간에서 나타난 얼굴 동작 신호 변화",
  catalog_tag_alignment: "관찰 근거와 상품 특성의 일치",
  sufficient_data_quality: "추천에 사용할 수 있는 관찰 품질",
};

const TAG_COPY: Readonly<Record<string, string>> = {
  backpack: "백팩",
  bold: "대담한 인상",
  boston: "보스턴 실루엣",
  classic: "클래식",
  compact: "컴팩트",
  crossbody: "크로스바디",
  daily: "데일리",
  evening: "이브닝",
  hobo: "호보 실루엣",
  leather: "가죽",
  lightweight: "가벼운 구성",
  minimal: "미니멀",
  modern: "모던",
  monogram: "모노그램",
  neutral: "뉴트럴",
  recycled_material: "재생 소재",
  shoulder: "숄더",
  shopper: "쇼퍼",
  soft: "부드러운 실루엣",
  spacious: "넉넉한 수납",
  sporty: "스포티",
  structured: "구조적인 형태",
  tambourine: "탬버린 실루엣",
  top_handle: "탑 핸들",
  tote: "토트",
  travel: "여행",
  triangle: "트라이앵글 실루엣",
  weekender: "위켄더",
  work: "업무용",
};

function requireCopy<T extends string>(
  mapping: Readonly<Record<T, string>>,
  code: T,
  label: string,
): string {
  const copy = mapping[code];
  if (!copy) throw new Error(`Unsupported ${label}: ${code}`);
  return copy;
}

export function presentCentralRecommendation(
  decision: RecommendationDecisionV2,
  product: ProductRecommendationItemV2,
): RecommendationPresentation {
  if (
    decision.status !== "completed" ||
    !decision.selected_product_id ||
    !decision.style ||
    !decision.exploration_tendency_code
  ) {
    throw new Error("Only a grounded completed v2 decision can be presented.");
  }
  if (decision.selected_product_id !== product.product_id) {
    throw new Error("The selected product does not match the reviewed catalog item.");
  }
  if (
    decision.evidence.length === 0 ||
    decision.evidence.some(
      (item) =>
        item.product_id !== product.product_id || item.evidence_refs.length === 0,
    )
  ) {
    throw new Error("Recommendation evidence is not grounded in the selected product.");
  }

  const matchedTags = decision.style.matched_tags;
  if (
    matchedTags.length === 0 ||
    matchedTags.some((tag) => !product.controlled_tags.includes(tag))
  ) {
    throw new Error("Recommendation tags are not grounded in the reviewed catalog.");
  }
  const tagCopy = matchedTags
    .slice(0, 3)
    .map((tag) => requireCopy(TAG_COPY, tag, "controlled product tag"));
  const reactionCopy = decision.reason_codes
    .filter((code) => code !== "catalog_tag_alignment")
    .slice(0, 2)
    .map((code) => requireCopy(REACTION_COPY, code, "reason code"));
  const isLocalDemoFallback =
    decision.version.model_id === "deterministic-test-stub" &&
    decision.data_quality.gaze_valid_ratio === 0 &&
    decision.reason_codes.length === 1 &&
    decision.reason_codes[0] === "catalog_tag_alignment";
  if (isLocalDemoFallback) {
    return {
      recommendation_id: decision.recommendation_id,
      product_id: product.product_id,
      tendency: "로컬 제출 데모용 기본 카탈로그 추천",
      reason: `유효한 시선 신호가 부족해 관찰 기반 판단 대신 검수된 상품 태그(${tagCopy.join(", ")})의 기본 항목을 표시했습니다.`,
      mode: "demo_fallback_v2",
    };
  }
  const isCentralLowSignal =
    decision.version.input_variant === "B" &&
    decision.data_quality.gaze_valid_ratio === 0 &&
    decision.reason_codes.length === 1 &&
    decision.reason_codes[0] === "catalog_tag_alignment" &&
    decision.evidence.some((item) => item.code === "data_quality");
  if (isCentralLowSignal) {
    return {
      recommendation_id: decision.recommendation_id,
      product_id: product.product_id,
      tendency: "제한된 관찰로 진행한 카탈로그 선택",
      reason: `유효한 시선 좌표는 부족했지만 실제 관찰의 결측 상태와 검수된 상품 태그(${tagCopy.join(", ")})를 Luna에 전달해 선택했습니다.`,
      mode: "central_low_signal_v2",
    };
  }
  if (reactionCopy.length === 0) {
    throw new Error("A completed decision needs an observation reason code.");
  }

  return {
    recommendation_id: decision.recommendation_id,
    product_id: product.product_id,
    tendency: requireCopy(
      TENDENCY_COPY,
      decision.exploration_tendency_code,
      "exploration tendency",
    ),
    reason: `${reactionCopy.join("과 ")}과 검수된 상품 태그(${tagCopy.join(", ")})를 바탕으로 추천했습니다.`,
    mode: "central_v2",
  };
}

export function presentMockRecommendation(
  recommendation: Extract<RecommendationResult, { status: "completed" }>,
): RecommendationPresentation {
  const productId = recommendation.items.find((item) => item.rank === 1)?.product_id;
  if (!productId) throw new Error("Mock fixture has no rank 1 product.");
  return {
    recommendation_id: recommendation.recommendation_id,
    product_id: productId,
    tendency: "개발용 v1 fixture 흐름 확인",
    reason: "이 결과는 production 추천이 아닌 명시적으로 활성화한 Mock fixture입니다.",
    mode: "mock_v1",
  };
}

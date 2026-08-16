import type {
  ApiHealth,
  LookbookManifest,
  ManagerProductRequest,
  ManagerProductRequestAccepted,
  ManagerProductRequestV2,
  ObservationBatchAcceptedV2,
  ObservationBatchV2,
  Product,
  ProductRecommendationItemV2,
  ReactionBatch,
  ReactionBatchAccepted,
  RecommendationAccepted,
  RecommendationAcceptedV2,
  RecommendationDecisionV2,
  RecommendationResult,
  SessionCreate,
  SessionCreated,
} from "../../app/kiosk-types.ts";

export type ApiRequestOptions = {
  signal?: AbortSignal;
};

export interface ApiClient {
  createSession(
    request: SessionCreate,
    options?: ApiRequestOptions,
  ): Promise<SessionCreated>;
  getLookbookManifest(
    lookbookId: string,
    options?: ApiRequestOptions,
  ): Promise<LookbookManifest>;
  appendReactionBatch(
    sessionId: string,
    batch: ReactionBatch,
  ): Promise<ReactionBatchAccepted>;
  completeSessionAnalysis(
    sessionId: string,
    options?: ApiRequestOptions,
  ): Promise<RecommendationAccepted>;
  getSessionRecommendation(
    sessionId: string,
    options?: ApiRequestOptions,
  ): Promise<RecommendationResult>;
  getProduct(productId: string): Promise<Product>;
  requestManagerProduct(
    sessionId: string,
    request: ManagerProductRequest,
  ): Promise<ManagerProductRequestAccepted>;
  health(): Promise<ApiHealth>;
  discardSession(sessionId: string): Promise<void> | void;
}

export interface CentralRecommendationApiClient {
  appendObservationBatch(
    sessionId: string,
    batch: ObservationBatchV2,
    options?: ApiRequestOptions,
  ): Promise<ObservationBatchAcceptedV2>;
  completeCentralRecommendation(
    sessionId: string,
    options?: ApiRequestOptions,
  ): Promise<RecommendationAcceptedV2>;
  getCentralRecommendation(
    sessionId: string,
    options?: ApiRequestOptions,
  ): Promise<RecommendationAcceptedV2 | RecommendationDecisionV2>;
  getCentralProduct(productId: string): Promise<ProductRecommendationItemV2>;
  requestCentralManagerProduct(
    sessionId: string,
    request: ManagerProductRequestV2,
  ): Promise<ManagerProductRequestAccepted>;
}

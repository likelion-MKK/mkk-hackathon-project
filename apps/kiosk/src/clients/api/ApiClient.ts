import type {
  ApiHealth,
  LookbookManifest,
  Product,
  ReactionBatch,
  ReactionBatchAccepted,
  RecommendationAccepted,
  RecommendationResult,
  SessionCreate,
  SessionCreated,
} from "../../app/kiosk-types.ts";

export interface ApiClient {
  createSession(request: SessionCreate): Promise<SessionCreated>;
  getLookbookManifest(lookbookId: string): Promise<LookbookManifest>;
  appendReactionBatch(
    sessionId: string,
    batch: ReactionBatch,
  ): Promise<ReactionBatchAccepted>;
  completeSessionAnalysis(sessionId: string): Promise<RecommendationAccepted>;
  getSessionRecommendation(sessionId: string): Promise<RecommendationResult>;
  getProduct(productId: string): Promise<Product>;
  health(): Promise<ApiHealth>;
}

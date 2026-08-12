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
import type { ApiClient } from "./ApiClient.ts";

const MOCK_LOOKBOOK_ID = "mcm-lookbook-example-v1";

const mockManifest: LookbookManifest = {
  schema_version: "1.0",
  video_id: MOCK_LOOKBOOK_ID,
  manifest_version: "example-1.0",
  coordinate_space: "video_normalized",
  exposures: [
    {
      exposure_id: "scene-01-product-01",
      product_id: "P001",
      start_ms: 0,
      end_ms: 10_000,
      priority: 0,
      shape: {
        type: "polygon",
        points: [
          [0.08, 0.18],
          [0.46, 0.18],
          [0.46, 0.88],
          [0.08, 0.88],
        ],
      },
    },
    {
      exposure_id: "scene-01-product-02",
      product_id: "P002",
      start_ms: 0,
      end_ms: 10_000,
      priority: 0,
      shape: {
        type: "polygon",
        points: [
          [0.54, 0.18],
          [0.92, 0.18],
          [0.92, 0.88],
          [0.54, 0.88],
        ],
      },
    },
  ],
};

const mockProducts: Record<string, Product> = {
  P001: {
    product_id: "P001",
    display_name: "Mock Product 01",
    category: "bags",
    image_url: "/mock/products/P001.jpg",
    product_url: "https://example.com/products/P001",
    qr_asset_path: "/mock/qr/P001.svg",
  },
  P002: {
    product_id: "P002",
    display_name: "Mock Product 02",
    category: "ready-to-wear",
    image_url: "/mock/products/P002.jpg",
    product_url: "https://example.com/products/P002",
    qr_asset_path: "/mock/qr/P002.svg",
  },
};

type MockSession = {
  request: SessionCreate;
  analysisCompleted: boolean;
};

export class MockApiClient implements ApiClient {
  private sessionSequence = 0;
  private readonly sessions = new Map<string, MockSession>();
  private readonly acceptedBatchIds = new Set<string>();

  async createSession(request: SessionCreate): Promise<SessionCreated> {
    this.sessionSequence += 1;
    const suffix = String(this.sessionSequence).padStart(3, "0");
    const sessionId = `session-d1-mock-${suffix}`;

    this.sessions.set(sessionId, {
      request: { ...request },
      analysisCompleted: false,
    });

    return {
      session_id: sessionId,
      display_code: `D1MOCK${suffix}`,
      status: "collecting",
      created_at: "2026-01-01T00:00:00.000Z",
    };
  }

  async getLookbookManifest(lookbookId: string): Promise<LookbookManifest> {
    if (lookbookId !== MOCK_LOOKBOOK_ID) {
      throw new Error(`Unknown mock lookbook: ${lookbookId}`);
    }

    return structuredClone(mockManifest);
  }

  async appendReactionBatch(
    sessionId: string,
    batch: ReactionBatch,
  ): Promise<ReactionBatchAccepted> {
    this.requireSession(sessionId);

    if (batch.session_id !== sessionId) {
      throw new Error("Reaction batch session_id does not match the request path.");
    }

    const duplicate = this.acceptedBatchIds.has(batch.batch_id);
    this.acceptedBatchIds.add(batch.batch_id);

    return {
      batch_id: batch.batch_id,
      status: duplicate ? "duplicate" : "accepted",
    };
  }

  async completeSessionAnalysis(sessionId: string): Promise<RecommendationAccepted> {
    const session = this.requireSession(sessionId);
    session.analysisCompleted = true;

    return {
      session_id: sessionId,
      status: "pending",
    };
  }

  async getSessionRecommendation(sessionId: string): Promise<RecommendationResult> {
    const session = this.requireSession(sessionId);

    if (!session.analysisCompleted) {
      return {
        schema_version: "1.0",
        recommendation_id: `recommendation-${sessionId}`,
        session_id: sessionId,
        video_id: session.request.lookbook_id,
        manifest_version: "example-1.0",
        algorithm_version: "mock-v1",
        engine_mode: "mock",
        status: "pending",
        items: [],
        reason: null,
      };
    }

    return {
      schema_version: "1.0",
      recommendation_id: `recommendation-${sessionId}`,
      session_id: sessionId,
      video_id: session.request.lookbook_id,
      manifest_version: "example-1.0",
      algorithm_version: "mock-v1",
      engine_mode: "mock",
      status: "completed",
      items: [
        { rank: 1, product_id: "P001" },
        { rank: 2, product_id: "P002" },
      ],
      reason: null,
    };
  }

  async getProduct(productId: string): Promise<Product> {
    const product = mockProducts[productId];

    if (!product) {
      throw new Error(`Unknown mock product: ${productId}`);
    }

    return { ...product };
  }

  async health(): Promise<ApiHealth> {
    return {
      status: "ok",
      database: "up",
    };
  }

  private requireSession(sessionId: string): MockSession {
    const session = this.sessions.get(sessionId);

    if (!session) {
      throw new Error(`Unknown mock session: ${sessionId}`);
    }

    return session;
  }
}

export { MOCK_LOOKBOOK_ID };

import type {
  ApiHealth,
  LookbookManifest,
  ManagerProductRequest,
  ManagerProductRequestAccepted,
  Product,
  ProductCategory,
  ReactionBatch,
  ReactionBatchAccepted,
  RecommendationAccepted,
  RecommendationResult,
  SessionCreate,
  SessionCreated,
} from "../../app/kiosk-types.ts";
import type { ApiClient, ApiRequestOptions } from "./ApiClient.ts";

export const MOCK_LOOKBOOK_ID_BY_CATEGORY: Record<ProductCategory, string> = {
  가방: "mcm-lookbook-bags-v1",
  의류: "mcm-lookbook-ready-to-wear-v1",
  액세서리: "mcm-lookbook-accessories-v1",
  "전체 컬렉션": "mcm-lookbook-all-v1",
};

type MockLookbook = {
  manifest: LookbookManifest;
  recommendationProductIds: [string, string];
};

function createMockManifest(
  videoId: string,
  productIds: [string, string],
): LookbookManifest {
  return {
    schema_version: "1.0",
    video_id: videoId,
    manifest_version: "d1-category-mock-1.0",
    coordinate_space: "video_normalized",
    exposures: [
      {
        exposure_id: `${videoId}-product-01`,
        product_id: productIds[0],
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
        exposure_id: `${videoId}-product-02`,
        product_id: productIds[1],
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
}

const mockLookbooks: Record<string, MockLookbook> = {
  [MOCK_LOOKBOOK_ID_BY_CATEGORY.가방]: {
    manifest: createMockManifest(MOCK_LOOKBOOK_ID_BY_CATEGORY.가방, ["BAG001", "BAG002"]),
    recommendationProductIds: ["BAG001", "BAG002"],
  },
  [MOCK_LOOKBOOK_ID_BY_CATEGORY.의류]: {
    manifest: createMockManifest(MOCK_LOOKBOOK_ID_BY_CATEGORY.의류, ["RTW001", "RTW002"]),
    recommendationProductIds: ["RTW001", "RTW002"],
  },
  [MOCK_LOOKBOOK_ID_BY_CATEGORY.액세서리]: {
    manifest: createMockManifest(MOCK_LOOKBOOK_ID_BY_CATEGORY.액세서리, [
      "ACC001",
      "ACC002",
    ]),
    recommendationProductIds: ["ACC001", "ACC002"],
  },
  [MOCK_LOOKBOOK_ID_BY_CATEGORY["전체 컬렉션"]]: {
    manifest: createMockManifest(MOCK_LOOKBOOK_ID_BY_CATEGORY["전체 컬렉션"], [
      "BAG001",
      "RTW001",
    ]),
    recommendationProductIds: ["BAG001", "RTW001"],
  },
};

const mockProducts: Record<string, Product> = {
  BAG001: {
    product_id: "BAG001",
    display_name: "Mock Bag 01",
    category: "bags",
    image_url: "https://example.invalid/assets/BAG001.jpg",
    product_url: "https://example.invalid/products/BAG001",
    qr_asset_path: "assets/qr/BAG001.png",
  },
  BAG002: {
    product_id: "BAG002",
    display_name: "Mock Bag 02",
    category: "bags",
    image_url: "https://example.invalid/assets/BAG002.jpg",
    product_url: "https://example.invalid/products/BAG002",
    qr_asset_path: "assets/qr/BAG002.png",
  },
  RTW001: {
    product_id: "RTW001",
    display_name: "Mock Ready-to-wear 01",
    category: "ready-to-wear",
    image_url: "https://example.invalid/assets/RTW001.jpg",
    product_url: "https://example.invalid/products/RTW001",
    qr_asset_path: "assets/qr/RTW001.png",
  },
  RTW002: {
    product_id: "RTW002",
    display_name: "Mock Ready-to-wear 02",
    category: "ready-to-wear",
    image_url: "https://example.invalid/assets/RTW002.jpg",
    product_url: "https://example.invalid/products/RTW002",
    qr_asset_path: "assets/qr/RTW002.png",
  },
  ACC001: {
    product_id: "ACC001",
    display_name: "Mock Accessory 01",
    category: "accessories",
    image_url: "https://example.invalid/assets/ACC001.jpg",
    product_url: "https://example.invalid/products/ACC001",
    qr_asset_path: "assets/qr/ACC001.png",
  },
  ACC002: {
    product_id: "ACC002",
    display_name: "Mock Accessory 02",
    category: "accessories",
    image_url: "https://example.invalid/assets/ACC002.jpg",
    product_url: "https://example.invalid/products/ACC002",
    qr_asset_path: "assets/qr/ACC002.png",
  },
};

type MockSession = {
  request: SessionCreate;
  analysisCompleted: boolean;
  acceptedBatchIds: Set<string>;
  managerRequestIds: Set<string>;
};

export type MockApiClientOptions = {
  sessionStartDelayMs?: number;
};

function waitForDelay(delayMs: number, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  if (delayMs === 0) return Promise.resolve();

  return new Promise<void>((resolve, reject) => {
    const timeoutId = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", handleAbort);
      resolve();
    }, delayMs);

    const handleAbort = () => {
      globalThis.clearTimeout(timeoutId);
      signal?.removeEventListener("abort", handleAbort);
      reject(signal?.reason ?? new Error("Mock API request was cancelled."));
    };

    signal?.addEventListener("abort", handleAbort, { once: true });
  });
}

export class MockApiClient implements ApiClient {
  private sessionSequence = 0;
  private readonly sessions = new Map<string, MockSession>();
  private readonly sessionStartDelayMs: number;

  constructor({ sessionStartDelayMs = 0 }: MockApiClientOptions = {}) {
    if (!Number.isFinite(sessionStartDelayMs) || sessionStartDelayMs < 0) {
      throw new RangeError("sessionStartDelayMs must be a non-negative finite number.");
    }

    this.sessionStartDelayMs = sessionStartDelayMs;
  }

  async createSession(
    request: SessionCreate,
    { signal }: ApiRequestOptions = {},
  ): Promise<SessionCreated> {
    await waitForDelay(this.sessionStartDelayMs, signal);
    signal?.throwIfAborted();

    this.requireLookbook(request.lookbook_id);
    this.sessionSequence += 1;
    const suffix = String(this.sessionSequence).padStart(3, "0");
    const sessionId = `session-d1-mock-${suffix}`;

    this.sessions.set(sessionId, {
      request: { ...request },
      analysisCompleted: false,
      acceptedBatchIds: new Set<string>(),
      managerRequestIds: new Set<string>(),
    });

    return {
      session_id: sessionId,
      display_code: `D1MOCK${suffix}`,
      status: "collecting",
      created_at: "2026-01-01T00:00:00.000Z",
    };
  }

  async getLookbookManifest(
    lookbookId: string,
    { signal }: ApiRequestOptions = {},
  ): Promise<LookbookManifest> {
    signal?.throwIfAborted();
    return structuredClone(this.requireLookbook(lookbookId).manifest);
  }

  async appendReactionBatch(
    sessionId: string,
    batch: ReactionBatch,
  ): Promise<ReactionBatchAccepted> {
    const session = this.requireSession(sessionId);

    if (batch.session_id !== sessionId) {
      throw new Error("Reaction batch session_id does not match the request path.");
    }

    if (batch.video_id !== session.request.lookbook_id) {
      throw new Error("Reaction batch video_id does not match the session lookbook_id.");
    }

    if (session.analysisCompleted) {
      throw new Error("Completed mock sessions cannot accept reaction batches.");
    }

    // D02의 C 정책: payload는 검증 뒤 보관하지 않고, 수집 중 중복 제거용 ID만 유지한다.
    const duplicate = session.acceptedBatchIds.has(batch.batch_id);
    session.acceptedBatchIds.add(batch.batch_id);

    return {
      batch_id: batch.batch_id,
      status: duplicate ? "duplicate" : "accepted",
    };
  }

  async completeSessionAnalysis(sessionId: string): Promise<RecommendationAccepted> {
    const session = this.requireSession(sessionId);
    session.analysisCompleted = true;
    session.acceptedBatchIds.clear();

    return {
      session_id: sessionId,
      status: "pending",
    };
  }

  async getSessionRecommendation(sessionId: string): Promise<RecommendationResult> {
    const session = this.requireSession(sessionId);
    const lookbook = this.requireLookbook(session.request.lookbook_id);

    if (!session.analysisCompleted) {
      return {
        schema_version: "1.0",
        recommendation_id: `recommendation-${sessionId}`,
        session_id: sessionId,
        video_id: session.request.lookbook_id,
        manifest_version: lookbook.manifest.manifest_version,
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
      manifest_version: lookbook.manifest.manifest_version,
      algorithm_version: "mock-v1",
      engine_mode: "mock",
      status: "completed",
      items: [
        { rank: 1, product_id: lookbook.recommendationProductIds[0] },
        { rank: 2, product_id: lookbook.recommendationProductIds[1] },
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

  discardSession(sessionId: string): void {
    this.sessions.delete(sessionId);
  }

  async requestManagerProduct(
    sessionId: string,
    request: ManagerProductRequest,
  ): Promise<ManagerProductRequestAccepted> {
    const session = this.requireSession(sessionId);
    if (!session.analysisCompleted) {
      throw new Error("Manager requests require a completed recommendation.");
    }
    const duplicate = session.managerRequestIds.has(request.request_id);
    session.managerRequestIds.add(request.request_id);
    return {
      request_id: request.request_id,
      status: duplicate ? "duplicate" : "accepted",
    };
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

  private requireLookbook(lookbookId: string): MockLookbook {
    const lookbook = mockLookbooks[lookbookId];

    if (!lookbook) {
      throw new Error(`Unknown mock lookbook: ${lookbookId}`);
    }

    return lookbook;
  }
}

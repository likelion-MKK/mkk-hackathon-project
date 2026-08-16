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
import type {
  ApiClient,
  ApiRequestOptions,
  CentralRecommendationApiClient,
} from "./ApiClient.ts";

type ErrorPayload = {
  code?: unknown;
  message?: unknown;
};

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(
    message: string,
    status: number,
    code: string | null,
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export class HttpApiClient implements ApiClient, CentralRecommendationApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = normalizeBaseUrl(baseUrl);
  }

  createSession(
    request: SessionCreate,
    { signal }: ApiRequestOptions = {},
  ): Promise<SessionCreated> {
    return this.request<SessionCreated>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify(request),
      signal,
    });
  }

  getLookbookManifest(
    lookbookId: string,
    { signal }: ApiRequestOptions = {},
  ): Promise<LookbookManifest> {
    return this.request<LookbookManifest>(
      `/api/v1/lookbooks/${encodeURIComponent(lookbookId)}/manifest`,
      { signal },
    );
  }

  appendReactionBatch(
    sessionId: string,
    batch: ReactionBatch,
  ): Promise<ReactionBatchAccepted> {
    return this.request<ReactionBatchAccepted>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/reaction-batches`,
      { method: "POST", body: JSON.stringify(batch) },
    );
  }

  appendObservationBatch(
    sessionId: string,
    batch: ObservationBatchV2,
    { signal }: ApiRequestOptions = {},
  ): Promise<ObservationBatchAcceptedV2> {
    return this.request<ObservationBatchAcceptedV2>(
      `/api/v2/sessions/${encodeURIComponent(sessionId)}/observations`,
      { method: "POST", body: JSON.stringify(batch), signal },
    );
  }

  completeSessionAnalysis(
    sessionId: string,
    { signal }: ApiRequestOptions = {},
  ): Promise<RecommendationAccepted> {
    return this.request<RecommendationAccepted>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/complete`,
      { method: "POST", body: "{}", signal },
    );
  }

  completeCentralRecommendation(
    sessionId: string,
    { signal }: ApiRequestOptions = {},
  ): Promise<RecommendationAcceptedV2> {
    return this.request<RecommendationAcceptedV2>(
      `/api/v2/sessions/${encodeURIComponent(sessionId)}/complete`,
      { method: "POST", body: "{}", signal },
    );
  }

  getSessionRecommendation(
    sessionId: string,
    { signal }: ApiRequestOptions = {},
  ): Promise<RecommendationResult> {
    return this.request<RecommendationResult>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/recommendations`,
      { signal },
    );
  }

  getCentralRecommendation(
    sessionId: string,
    { signal }: ApiRequestOptions = {},
  ): Promise<RecommendationAcceptedV2 | RecommendationDecisionV2> {
    return this.request<RecommendationAcceptedV2 | RecommendationDecisionV2>(
      `/api/v2/sessions/${encodeURIComponent(sessionId)}/recommendation`,
      { signal },
    );
  }

  getCentralProduct(productId: string): Promise<ProductRecommendationItemV2> {
    return this.request<ProductRecommendationItemV2>(
      `/api/v2/products/${encodeURIComponent(productId)}`,
    );
  }

  getProduct(productId: string): Promise<Product> {
    return this.request<Product>(`/api/v1/products/${encodeURIComponent(productId)}`);
  }

  requestManagerProduct(
    sessionId: string,
    request: ManagerProductRequest,
  ): Promise<ManagerProductRequestAccepted> {
    return this.request<ManagerProductRequestAccepted>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/manager-product-requests`,
      { method: "POST", body: JSON.stringify(request) },
    );
  }

  requestCentralManagerProduct(
    sessionId: string,
    request: ManagerProductRequestV2,
  ): Promise<ManagerProductRequestAccepted> {
    return this.request<ManagerProductRequestAccepted>(
      `/api/v2/sessions/${encodeURIComponent(sessionId)}/manager-product-requests`,
      { method: "POST", body: JSON.stringify(request) },
    );
  }

  health(): Promise<ApiHealth> {
    return this.request<ApiHealth>("/api/v1/health");
  }

  async discardSession(sessionId: string): Promise<void> {
    await this.request<unknown>(
      `/api/v2/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
      true,
    );
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    allowMissing = false,
  ): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body !== undefined) headers.set("Content-Type", "application/json");

    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    if (allowMissing && response.status === 404) return undefined as T;

    if (!response.ok) {
      let payload: ErrorPayload = {};
      try {
        payload = (await response.json()) as ErrorPayload;
      } catch {
        // Preserve the HTTP status when an upstream proxy returns non-JSON.
      }
      const message =
        typeof payload.message === "string"
          ? payload.message
          : `API request failed with status ${response.status}.`;
      const code = typeof payload.code === "string" ? payload.code : null;
      throw new ApiRequestError(message, response.status, code);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
}

export type ManagerEvent = {
  schema_version: "2.0";
  event_id: string;
  sequence: number;
  session_id: string;
  kiosk_id: string;
  event_type: "customer_product_request";
  emitted_at: string;
  payload: {
    intent: "view_recommended_product";
    recommendation_id: string;
    selected_product_id: string;
  };
};

export type Product = {
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
  source_status: string;
  official_product_url: string | null;
  official_product_url_reason: string | null;
  official_listing_url: string;
  image_asset_path: string | null;
  image_asset_path_reason: string | null;
  qr_asset_path: string | null;
  qr_asset_path_reason: string | null;
  source_note: string;
};

export type ManagerEventView = {
  event: ManagerEvent;
  product: Product | null;
};

const normalizeBaseUrl = (value: string): string => value.replace(/\/+$/, "");

export class ManagerApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = normalizeBaseUrl(baseUrl);
  }

  async listEvents(afterSequence: number | null, signal?: AbortSignal): Promise<ManagerEvent[]> {
    const query = afterSequence === null ? "" : `?after_sequence=${afterSequence}`;
    return this.request<ManagerEvent[]>(`/api/v2/manager/events${query}`, signal);
  }

  async getProduct(productId: string, signal?: AbortSignal): Promise<Product> {
    return this.request<Product>(`/api/v2/products/${encodeURIComponent(productId)}`, signal);
  }

  private async request<T>(path: string, signal?: AbortSignal): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: { Accept: "application/json" },
      signal,
    });

    if (!response.ok) {
      let message = `API 요청이 실패했습니다. (${response.status})`;
      try {
        const body = (await response.json()) as { message?: unknown };
        if (typeof body.message === "string") message = body.message;
      } catch {
        // The status code is sufficient when the response is not JSON.
      }
      throw new Error(message);
    }

    return (await response.json()) as T;
  }
}

export function requestedProductId(event: ManagerEvent): string | null {
  return event.payload.selected_product_id || null;
}

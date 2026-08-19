import { useEffect, useMemo, useRef, useState } from "react";
import {
  ManagerApiClient,
  requestedProductId,
  type ManagerEventView,
} from "./api";

const POLL_INTERVAL_MS = 1_500;
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(date);
}

function App() {
  const client = useMemo(() => new ManagerApiClient(apiBaseUrl), []);
  const [requests, setRequests] = useState<ManagerEventView[]>([]);
  const [status, setStatus] = useState<"connecting" | "ready" | "error">("connecting");
  const cursorRef = useRef<number | null>(null);
  const seenEventIds = useRef(new Set<string>());

  useEffect(() => {
    let active = true;
    let timerId: number | undefined;
    let controller: AbortController | null = null;

    const poll = async () => {
      controller?.abort();
      controller = new AbortController();

      try {
        const events = await client.listEvents(cursorRef.current, controller.signal);
        if (!active) return;

        const unseen = events.filter((event) => !seenEventIds.current.has(event.event_id));
        unseen.forEach((event) => seenEventIds.current.add(event.event_id));
        if (events.length > 0) {
          cursorRef.current = Math.max(
            cursorRef.current ?? -1,
            ...events.map((event) => event.sequence),
          );
        }

        const views = await Promise.all(
          unseen.map(async (event): Promise<ManagerEventView> => {
            const productId = requestedProductId(event);
            if (!productId) return { event, product: null };
            try {
              return {
                event,
                product: await client.getProduct(productId, controller?.signal),
              };
            } catch {
              return { event, product: null };
            }
          }),
        );
        if (!active) return;
        if (views.length > 0) setRequests((current) => [...views, ...current]);
        setStatus("ready");
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setStatus("error");
      } finally {
        if (active) timerId = window.setTimeout(poll, POLL_INTERVAL_MS);
      }
    };

    void poll();
    return () => {
      active = false;
      if (timerId !== undefined) window.clearTimeout(timerId);
      controller?.abort();
    };
  }, [client]);

  return (
    <main className="manager-shell">
      <header className="manager-header">
        <div>
          <p className="eyebrow">MCM AI LOOKBOOK</p>
          <h1>Product Requests</h1>
        </div>
        <p className={`connection connection--${status}`} role="status">
          {status === "ready" && "REST POLLING · CONNECTED"}
          {status === "connecting" && "CONNECTING"}
          {status === "error" && "RECONNECTING"}
        </p>
      </header>

      <section className="request-list" aria-live="polite">
        {requests.length === 0 ? (
          <div className="empty-state">
            <span>NO REQUESTS</span>
            <h2>고객의 제품 확인 요청을 기다리고 있습니다.</h2>
            <p>S04에서 고객이 직접 요청한 경우에만 이 화면에 표시됩니다.</p>
          </div>
        ) : (
          requests.map(({ event, product }) => {
            const productId = requestedProductId(event);
            return (
              <article className="request-card" key={event.event_id}>
                <div className="request-card__meta">
                  <span>{event.kiosk_id}</span>
                  <time dateTime={event.emitted_at}>{formatTime(event.emitted_at)}</time>
                </div>
                <p className="request-card__label">CUSTOMER REQUEST</p>
                <h2>{product?.display_name ?? productId ?? "상품 정보 확인 필요"}</h2>
                <p>고객이 추천 상품을 직접 보고 싶다고 요청했습니다.</p>
                <dl>
                  <div>
                    <dt>SESSION</dt>
                    <dd>{event.session_id}</dd>
                  </div>
                  <div>
                    <dt>PRODUCT</dt>
                    <dd>{productId ?? "UNKNOWN"}</dd>
                  </div>
                </dl>
              </article>
            );
          })
        )}
      </section>
    </main>
  );
}

export default App;

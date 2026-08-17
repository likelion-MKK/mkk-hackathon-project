export type PollableRecommendation = {
  status: "pending" | "completed" | "insufficient_data" | "failed";
  reason: string | { code?: string; explanation: string } | null;
};

export class RecommendationPollingError extends Error {
  readonly code: "timeout" | "insufficient_data" | "failed";

  constructor(
    code: "timeout" | "insufficient_data" | "failed",
    message: string,
  ) {
    super(message);
    this.name = "RecommendationPollingError";
    this.code = code;
  }
}

type PollRecommendationOptions<T extends PollableRecommendation> = {
  load: (signal: AbortSignal) => Promise<T>;
  signal?: AbortSignal;
  /** Optional compatibility guard. Production leaves this unset and waits for a terminal state. */
  timeoutMs?: number;
  intervalMs?: number;
};

function delay(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const handleResolve = () => {
      signal.removeEventListener("abort", handleAbort);
      resolve();
    };
    const timerId = globalThis.setTimeout(handleResolve, ms);
    const handleAbort = () => {
      globalThis.clearTimeout(timerId);
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    };
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

function reasonExplanation(
  reason: PollableRecommendation["reason"],
  fallback: string,
): string {
  if (typeof reason === "string") return reason;
  if (!reason?.code) return fallback;
  return (
    {
      insufficient_valid_signal:
        "추천에 사용할 수 있는 유효 관찰 신호가 충분하지 않습니다.",
      no_eligible_product: "관찰 근거와 연결할 수 있는 검수 상품이 없습니다.",
      model_unavailable: "중앙 추천 모델에 연결하지 못했습니다.",
      invalid_model_output: "중앙 추천 결과가 안전성 검증을 통과하지 못했습니다.",
      catalog_mismatch: "추천 결과와 검수 상품 목록이 일치하지 않습니다.",
    }[reason.code] ?? fallback
  );
}

export async function pollRecommendation<T extends PollableRecommendation>({
  load,
  signal,
  timeoutMs,
  intervalMs = 400,
}: PollRecommendationOptions<T>): Promise<T> {
  const timeoutController = new AbortController();
  const timeoutId = timeoutMs === undefined
    ? undefined
    : globalThis.setTimeout(
        () => timeoutController.abort(new RecommendationPollingError("timeout", "추천 처리 시간이 초과되었습니다.")),
        timeoutMs,
      );
  const forwardAbort = () => timeoutController.abort(signal?.reason);
  signal?.addEventListener("abort", forwardAbort, { once: true });

  try {
    while (true) {
      timeoutController.signal.throwIfAborted();
      const result = await load(timeoutController.signal);
      if (result.status === "completed") return result;
      if (result.status === "insufficient_data") {
        throw new RecommendationPollingError(
          "insufficient_data",
          reasonExplanation(
            result.reason,
            "추천에 사용할 수 있는 관찰 신호가 충분하지 않습니다.",
          ),
        );
      }
      if (result.status === "failed") {
        throw new RecommendationPollingError(
          "failed",
          reasonExplanation(result.reason, "중앙 추천 AI가 결과를 만들지 못했습니다."),
        );
      }
      await delay(intervalMs, timeoutController.signal);
    }
  } finally {
    if (timeoutId !== undefined) globalThis.clearTimeout(timeoutId);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

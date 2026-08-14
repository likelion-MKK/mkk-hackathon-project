export const CONSENT_VERSION = "consent-v1";
export const CONSENT_IDLE_TIMEOUT_MS = 30_000;
export const SESSION_START_TIMEOUT_MS = 5_000;

export class SessionStartTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`Mock session start exceeded ${timeoutMs}ms.`);
    this.name = "SessionStartTimeoutError";
  }
}

export type SessionStartTimeoutOptions = {
  timeoutMs?: number;
  signal?: AbortSignal;
};

export function getConsentSecondsRemaining(
  deadlineMs: number,
  nowMs: number,
): number {
  return Math.max(0, Math.ceil((deadlineMs - nowMs) / 1_000));
}

export function runSessionStartWithTimeout<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  {
    timeoutMs = SESSION_START_TIMEOUT_MS,
    signal: externalSignal,
  }: SessionStartTimeoutOptions = {},
): Promise<T> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new RangeError("timeoutMs must be a positive finite number.");
  }

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const operationController = new AbortController();

    if (externalSignal?.aborted) {
      const reason = externalSignal.reason ?? new Error("Session start was cancelled.");
      operationController.abort(reason);
      reject(reason);
      return;
    }

    const cleanup = () => {
      globalThis.clearTimeout(timeoutId);
      externalSignal?.removeEventListener("abort", handleExternalAbort);
    };

    const rejectOnce = (error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    const handleExternalAbort = () => {
      const reason = externalSignal?.reason ?? new Error("Session start was cancelled.");
      operationController.abort(reason);
      rejectOnce(reason);
    };

    const timeoutId = globalThis.setTimeout(() => {
      const timeoutError = new SessionStartTimeoutError(timeoutMs);
      operationController.abort(timeoutError);
      rejectOnce(timeoutError);
    }, timeoutMs);
    externalSignal?.addEventListener("abort", handleExternalAbort, { once: true });

    Promise.resolve()
      .then(() => operation(operationController.signal))
      .then(
        (value) => {
          if (settled) return;
          settled = true;
          cleanup();
          resolve(value);
        },
        (error: unknown) => {
          if (!operationController.signal.aborted) {
            operationController.abort(error);
          }
          rejectOnce(error);
        },
      );
  });
}

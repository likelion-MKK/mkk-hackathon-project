export const CONSENT_VERSION = "consent-v1";
export const CONSENT_IDLE_TIMEOUT_MS = 30_000;
export const SESSION_START_TIMEOUT_MS = 5_000;

export class SessionStartTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`Mock session start exceeded ${timeoutMs}ms.`);
    this.name = "SessionStartTimeoutError";
  }
}

export function getConsentSecondsRemaining(
  deadlineMs: number,
  nowMs: number,
): number {
  return Math.max(0, Math.ceil((deadlineMs - nowMs) / 1_000));
}

export function runSessionStartWithTimeout<T>(
  operation: () => Promise<T>,
  timeoutMs = SESSION_START_TIMEOUT_MS,
): Promise<T> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new RangeError("timeoutMs must be a positive finite number.");
  }

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const timeoutId = globalThis.setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new SessionStartTimeoutError(timeoutMs));
    }, timeoutMs);

    Promise.resolve()
      .then(operation)
      .then(
        (value) => {
          if (settled) return;
          settled = true;
          globalThis.clearTimeout(timeoutId);
          resolve(value);
        },
        (error: unknown) => {
          if (settled) return;
          settled = true;
          globalThis.clearTimeout(timeoutId);
          reject(error);
        },
      );
  });
}

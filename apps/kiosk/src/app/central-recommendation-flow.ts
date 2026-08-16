import type { ObservationBatchV2 } from "./kiosk-types.ts";
import type { CentralRecommendationApiClient } from "../clients/api/ApiClient.ts";

type CentralSubmissionClient = Pick<
  CentralRecommendationApiClient,
  "appendObservationBatch" | "completeCentralRecommendation"
> & {
  discardSession(sessionId: string): Promise<void> | void;
};

export async function discardCentralSessionBestEffort(
  client: Pick<CentralSubmissionClient, "discardSession">,
  sessionId: string,
): Promise<void> {
  try {
    await client.discardSession(sessionId);
  } catch {
    // The Backend TTL remains the last-resort cleanup if the DELETE cannot arrive.
  }
}

export async function submitCentralRecommendation(
  client: CentralSubmissionClient,
  sessionId: string,
  batches: readonly ObservationBatchV2[],
  signal: AbortSignal,
): Promise<void> {
  try {
    for (const batch of batches) {
      signal.throwIfAborted();
      await client.appendObservationBatch(sessionId, batch, { signal });
    }
    signal.throwIfAborted();
    await client.completeCentralRecommendation(sessionId, { signal });
  } catch (error: unknown) {
    await discardCentralSessionBestEffort(client, sessionId);
    throw error;
  }
}

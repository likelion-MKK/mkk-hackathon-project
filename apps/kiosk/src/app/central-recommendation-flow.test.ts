import assert from "node:assert/strict";
import test from "node:test";
import type { ObservationBatchV2 } from "./kiosk-types.ts";
import { submitCentralRecommendation } from "./central-recommendation-flow.ts";

const batch: ObservationBatchV2 = {
  schema_version: "2.0",
  batch_id: "batch-v2-001",
  batch_sequence: 0,
  session_id: "session-v2-001",
  video_id: "video-v2-001",
  observations: [
    {
      schema_version: "2.0",
      frame_id: "frame-v2-001",
      sequence: 0,
      captured_at_mono_ms: 100,
      session_offset_ms: 0,
      video_time_ms: 100,
      playback_epoch: 0,
      gaze: null,
      gaze_reason: "not_observed",
      attention: null,
      attention_reason: "source_gaze_unavailable",
      expression: null,
      expression_reason: "not_observed",
      derived: null,
      derived_reason: "no_valid_signal",
    },
  ],
};

test("v2 append 실패 시 transient session DELETE를 best-effort로 호출한다", async () => {
  const calls: string[] = [];
  const client = {
    appendObservationBatch: async () => {
      calls.push("append");
      throw new Error("append failed");
    },
    completeCentralRecommendation: async () => {
      calls.push("complete");
      return {
        recommendation_id: "recommendation-v2-001",
        decision_request_id: "decision-v2-001",
        status: "pending" as const,
      };
    },
    discardSession: async () => {
      calls.push("delete");
    },
  };

  await assert.rejects(
    () =>
      submitCentralRecommendation(
        client,
        "session-v2-001",
        [batch],
        new AbortController().signal,
      ),
    /append failed/,
  );
  assert.deepEqual(calls, ["append", "delete"]);
});

test("취소된 전송은 observation을 보내지 않고 session DELETE를 호출한다", async () => {
  const calls: string[] = [];
  const controller = new AbortController();
  controller.abort();
  const client = {
    appendObservationBatch: async () => {
      calls.push("append");
      return { batch_id: batch.batch_id, status: "accepted" as const };
    },
    completeCentralRecommendation: async () => {
      calls.push("complete");
      return {
        recommendation_id: "recommendation-v2-001",
        decision_request_id: "decision-v2-001",
        status: "pending" as const,
      };
    },
    discardSession: async () => {
      calls.push("delete");
    },
  };

  await assert.rejects(() =>
    submitCentralRecommendation(client, "session-v2-001", [batch], controller.signal),
  );
  assert.deepEqual(calls, ["delete"]);
});

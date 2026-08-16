import assert from "node:assert/strict";
import test from "node:test";
import {
  pollRecommendation,
  RecommendationPollingError,
  type PollableRecommendation,
} from "./recommendation-polling.ts";

test("pending recommendation을 completed까지 polling한다", async () => {
  const states: PollableRecommendation[] = [
    { status: "pending", reason: null },
    { status: "completed", reason: null },
  ];
  const result = await pollRecommendation({
    load: async () => states.shift() ?? { status: "failed", reason: "unexpected" },
    timeoutMs: 100,
    intervalMs: 0,
  });
  assert.equal(result.status, "completed");
});

test("근거 부족을 성공 결과로 대체하지 않는다", async () => {
  await assert.rejects(
    () =>
      pollRecommendation({
        load: async () => ({ status: "insufficient_data", reason: "no_valid_gaze" }),
        timeoutMs: 100,
        intervalMs: 0,
      }),
    (error: unknown) =>
      error instanceof RecommendationPollingError &&
      error.code === "insufficient_data" &&
      error.message === "no_valid_gaze",
  );
});

test("v2 오류는 자유 explanation 대신 reason code allowlist 문구를 사용한다", async () => {
  await assert.rejects(
    () =>
      pollRecommendation({
        load: async () => ({
          status: "failed",
          reason: {
            code: "invalid_model_output",
            explanation: "감정과 성격을 단정하는 자유 문장은 표시하면 안 됩니다.",
          },
        }),
        timeoutMs: 100,
        intervalMs: 0,
      }),
    (error: unknown) =>
      error instanceof RecommendationPollingError &&
      error.code === "failed" &&
      error.message === "중앙 추천 결과가 안전성 검증을 통과하지 못했습니다.",
  );
});

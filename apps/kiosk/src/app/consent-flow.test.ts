import assert from "node:assert/strict";
import test from "node:test";
import {
  getConsentSecondsRemaining,
  runSessionStartWithTimeout,
  SessionStartTimeoutError,
} from "./consent-flow.ts";

test("동의 화면의 남은 시간을 초 단위로 계산한다", () => {
  assert.equal(getConsentSecondsRemaining(30_000, 0), 30);
  assert.equal(getConsentSecondsRemaining(30_000, 29_001), 1);
  assert.equal(getConsentSecondsRemaining(30_000, 30_000), 0);
  assert.equal(getConsentSecondsRemaining(30_000, 31_000), 0);
});

test("Mock 세션이 제한 시간 안에 시작되면 결과를 반환한다", async () => {
  const result = await runSessionStartWithTimeout(async () => "session-ready", 50);

  assert.equal(result, "session-ready");
});

test("Mock 세션 시작이 오래 걸리면 timeout으로 구분한다", async () => {
  await assert.rejects(
    runSessionStartWithTimeout(() => new Promise<never>(() => undefined), 5),
    SessionStartTimeoutError,
  );
});

test("Mock API 자체 오류를 timeout으로 바꾸지 않는다", async () => {
  await assert.rejects(
    runSessionStartWithTimeout(async () => {
      throw new Error("mock_api_unavailable");
    }, 50),
    /mock_api_unavailable/,
  );
});

import assert from "node:assert/strict";
import test from "node:test";
import { AsyncFlowController } from "./async-flow-controller.ts";

function createDeferred(): {
  promise: Promise<void>;
  resolve: () => void;
} {
  let resolvePromise: (() => void) | undefined;
  const promise = new Promise<void>((resolve) => {
    resolvePromise = resolve;
  });

  return {
    promise,
    resolve: () => resolvePromise?.(),
  };
}

test("RESTART가 이전 flow 세대를 즉시 무효화한다", () => {
  const controller = new AsyncFlowController();
  const previousGeneration = controller.captureGeneration();

  const currentGeneration = controller.invalidateCurrentFlow();

  assert.equal(controller.isCurrent(previousGeneration), false);
  assert.equal(controller.isCurrent(currentGeneration), true);
});

test("Vision 작업을 이전 시작, 종료, 새 시작 순서로 직렬화한다", async () => {
  const controller = new AsyncFlowController();
  const firstOperationGate = createDeferred();
  const executionOrder: string[] = [];

  const previousStart = controller.runSerialized(async () => {
    executionOrder.push("previous-start:begin");
    await firstOperationGate.promise;
    executionOrder.push("previous-start:end");
  });
  const restartStop = controller.runSerialized(async () => {
    executionOrder.push("restart-stop");
  });
  const nextStart = controller.runSerialized(async () => {
    executionOrder.push("next-start");
  });

  await Promise.resolve();
  assert.deepEqual(executionOrder, ["previous-start:begin"]);

  firstOperationGate.resolve();
  await Promise.all([previousStart, restartStop, nextStart]);

  assert.deepEqual(executionOrder, [
    "previous-start:begin",
    "previous-start:end",
    "restart-stop",
    "next-start",
  ]);
});

test("앞 작업이 실패해도 종료 작업을 이어서 실행한다", async () => {
  const controller = new AsyncFlowController();
  const executionOrder: string[] = [];

  const failedStart = controller.runSerialized(async () => {
    executionOrder.push("failed-start");
    throw new Error("start_failed");
  });
  const cleanup = controller.runSerialized(async () => {
    executionOrder.push("cleanup");
  });

  await assert.rejects(failedStart, /start_failed/);
  await cleanup;

  assert.deepEqual(executionOrder, ["failed-start", "cleanup"]);
});

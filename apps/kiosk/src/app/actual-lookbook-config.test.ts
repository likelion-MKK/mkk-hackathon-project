import assert from "node:assert/strict";
import test from "node:test";
import {
  ACTUAL_LOOKBOOK_ID,
  ACTUAL_LOOKBOOK_VIDEO_URL,
  resolveActualLookbookConfig,
} from "./actual-lookbook-config.ts";

test("local actual-camera Kiosk defaults only to the pinned demo media", () => {
  assert.deepEqual(resolveActualLookbookConfig(undefined, undefined), {
    lookbookId: ACTUAL_LOOKBOOK_ID,
    videoUrl: ACTUAL_LOOKBOOK_VIDEO_URL,
  });
  assert.deepEqual(
    resolveActualLookbookConfig(ACTUAL_LOOKBOOK_ID, ACTUAL_LOOKBOOK_VIDEO_URL),
    { lookbookId: ACTUAL_LOOKBOOK_ID, videoUrl: ACTUAL_LOOKBOOK_VIDEO_URL },
  );
});

test("local actual-camera Kiosk refuses a synthetic ID or arbitrary media URL", () => {
  assert.throws(
    () => resolveActualLookbookConfig("mcm-central-ai-replay-v2", ACTUAL_LOOKBOOK_VIDEO_URL),
    /requires lookbook-demo-v1/,
  );
  assert.throws(
    () => resolveActualLookbookConfig(ACTUAL_LOOKBOOK_ID, "/media/other.mp4"),
    /requires \/lookbook-demo-v1.mp4/,
  );
});

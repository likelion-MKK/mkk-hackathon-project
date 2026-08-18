import assert from "node:assert/strict";
import test from "node:test";
import {
  ACTUAL_LOOKBOOK_ID,
  ACTUAL_LOOKBOOK_VIDEO_URL,
  resolveActualLookbookConfig,
} from "./actual-lookbook-config.ts";

test("real Kiosk defaults only to the reviewed actual lookbook media", () => {
  assert.deepEqual(resolveActualLookbookConfig(undefined, undefined), {
    lookbookId: ACTUAL_LOOKBOOK_ID,
    videoUrl: ACTUAL_LOOKBOOK_VIDEO_URL,
  });
  assert.deepEqual(
    resolveActualLookbookConfig(ACTUAL_LOOKBOOK_ID, ACTUAL_LOOKBOOK_VIDEO_URL),
    { lookbookId: ACTUAL_LOOKBOOK_ID, videoUrl: ACTUAL_LOOKBOOK_VIDEO_URL },
  );
});

test("real Kiosk refuses a synthetic video ID or an arbitrary media URL", () => {
  assert.throws(
    () => resolveActualLookbookConfig("mcm-central-ai-replay-v2", ACTUAL_LOOKBOOK_VIDEO_URL),
    /requires mcm-lookbook-v2/,
  );
  assert.throws(
    () => resolveActualLookbookConfig(ACTUAL_LOOKBOOK_ID, "/media/other.mp4"),
    /requires \/media\/mcm-lookbook-v2.mp4/,
  );
});

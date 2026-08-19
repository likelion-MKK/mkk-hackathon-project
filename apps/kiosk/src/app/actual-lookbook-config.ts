export const ACTUAL_LOOKBOOK_ID = "lookbook-demo-v1";
export const ACTUAL_LOOKBOOK_VIDEO_URL = "/lookbook-demo-v1.mp4";

export type ActualLookbookConfig = Readonly<{
  lookbookId: typeof ACTUAL_LOOKBOOK_ID;
  videoUrl: typeof ACTUAL_LOOKBOOK_VIDEO_URL;
}>;

function clean(value: string | undefined): string {
  return value?.trim() ?? "";
}

/**
 * Local actual-camera sessions are deliberately pinned to the current demo
 * media and its unapproved demo-assumption AOI manifest. They must never fall
 * back to a synthetic replay or an arbitrary local file.
 */
export function resolveActualLookbookConfig(
  lookbookIdValue: string | undefined,
  videoUrlValue: string | undefined,
): ActualLookbookConfig {
  const lookbookId = clean(lookbookIdValue) || ACTUAL_LOOKBOOK_ID;
  const videoUrl = clean(videoUrlValue) || ACTUAL_LOOKBOOK_VIDEO_URL;
  if (lookbookId !== ACTUAL_LOOKBOOK_ID) {
    throw new Error(`Real Kiosk requires ${ACTUAL_LOOKBOOK_ID}.`);
  }
  if (videoUrl !== ACTUAL_LOOKBOOK_VIDEO_URL) {
    throw new Error(`Real Kiosk requires ${ACTUAL_LOOKBOOK_VIDEO_URL}.`);
  }
  return { lookbookId: ACTUAL_LOOKBOOK_ID, videoUrl: ACTUAL_LOOKBOOK_VIDEO_URL };
}

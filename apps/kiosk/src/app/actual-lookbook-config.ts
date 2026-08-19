export const ACTUAL_LOOKBOOK_ID = "mcm-lookbook-v2";
export const ACTUAL_LOOKBOOK_VIDEO_URL = "/media/mcm-lookbook-v2.mp4";

export type ActualLookbookConfig = Readonly<{
  lookbookId: typeof ACTUAL_LOOKBOOK_ID;
  videoUrl: typeof ACTUAL_LOOKBOOK_VIDEO_URL;
}>;

function clean(value: string | undefined): string {
  return value?.trim() ?? "";
}

/**
 * Real Kiosk sessions must not quietly fall back to the old synthetic replay
 * or an unreviewed local video. The mock-only path is selected elsewhere.
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

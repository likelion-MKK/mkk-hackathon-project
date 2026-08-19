import type { KioskScreen } from "./kiosk-types.ts";

export const INITIAL_KIOSK_SCREEN: KioskScreen = "screensaver";

export const KIOSK_SCREENS: readonly KioskScreen[] = [
  "screensaver",
  "menu",
  "consent",
  "calibration",
  "lookbook",
  "finalizing",
  "report",
];

export type KioskEvent =
  | "START"
  | "SELECT_CATEGORY"
  | "AGREE"
  | "CALIBRATION_SUCCESS"
  | "LOOKBOOK_FINISHED"
  | "RECOMMENDATION_READY"
  | "BACK"
  | "CANCEL"
  | "RESTART";

const transitions: Record<
  KioskScreen,
  Partial<Record<KioskEvent, KioskScreen>>
> = {
  screensaver: {
    START: "menu",
    RESTART: "screensaver",
  },
  menu: {
    SELECT_CATEGORY: "consent",
    CANCEL: "screensaver",
    RESTART: "screensaver",
  },
  consent: {
    AGREE: "calibration",
    BACK: "menu",
    CANCEL: "screensaver",
    RESTART: "screensaver",
  },
  calibration: {
    CALIBRATION_SUCCESS: "lookbook",
    CANCEL: "screensaver",
    RESTART: "screensaver",
  },
  lookbook: {
    LOOKBOOK_FINISHED: "finalizing",
    CANCEL: "screensaver",
    RESTART: "screensaver",
  },
  finalizing: {
    RECOMMENDATION_READY: "report",
    CANCEL: "screensaver",
    RESTART: "screensaver",
  },
  report: {
    RESTART: "screensaver",
  },
};

export class InvalidKioskTransitionError extends Error {
  constructor(screen: KioskScreen, event: KioskEvent) {
    super(`Kiosk state '${screen}' cannot handle event '${event}'.`);
    this.name = "InvalidKioskTransitionError";
  }
}

export function transitionKioskScreen(
  screen: KioskScreen,
  event: KioskEvent,
): KioskScreen {
  const nextScreen = transitions[screen][event];

  if (!nextScreen) {
    throw new InvalidKioskTransitionError(screen, event);
  }

  return nextScreen;
}

import assert from "node:assert/strict";
import test from "node:test";
import {
  INITIAL_KIOSK_SCREEN,
  InvalidKioskTransitionError,
  KIOSK_SCREENS,
  transitionKioskScreen,
  type KioskEvent,
} from "./kiosk-machine.ts";

test("S01에서 S04까지 정해진 순서로 전환한다", () => {
  const events: KioskEvent[] = [
    "START",
    "SELECT_CATEGORY",
    "AGREE",
    "CALIBRATION_SUCCESS",
    "LOOKBOOK_FINISHED",
    "RECOMMENDATION_READY",
  ];

  const finalScreen = events.reduce(transitionKioskScreen, INITIAL_KIOSK_SCREEN);

  assert.equal(finalScreen, "report");
});

test("모든 화면에서 RESTART로 초기 화면에 돌아간다", () => {
  for (const screen of KIOSK_SCREENS) {
    assert.equal(transitionKioskScreen(screen, "RESTART"), "screensaver");
  }
});

test("동의 화면의 BACK은 카테고리 화면으로 돌아간다", () => {
  assert.equal(transitionKioskScreen("consent", "BACK"), "menu");
});

test("허용하지 않은 상태 전환을 차단한다", () => {
  assert.throws(
    () => transitionKioskScreen("screensaver", "AGREE"),
    InvalidKioskTransitionError,
  );
});

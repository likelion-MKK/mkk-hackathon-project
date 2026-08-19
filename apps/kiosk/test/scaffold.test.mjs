import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("kiosk entry document identifies the MCM lookbook app", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");

  assert.match(html, /MCM AI Lookbook/);
  assert.match(html, /id="root"/);
});

test("consent copy states the MVP session-only derived data policy", async () => {
  const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");

  assert.match(appSource, /개별 파생 신호는 저장하지 않습니다/);
  assert.match(appSource, /추천\s*생성\s*후 폐기합니다/);
  assert.match(appSource, /표정 분석은\s*사용하지 않습니다/);
  assert.match(appSource, /null과 not_observed 사유를 보존합니다/);
  assert.doesNotMatch(appSource, /세부 보유 기간은 운영 정책/);
});

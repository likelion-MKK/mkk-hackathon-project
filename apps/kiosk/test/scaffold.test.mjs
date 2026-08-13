import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("kiosk entry document identifies the MCM lookbook app", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");

  assert.match(html, /MCM AI Lookbook/);
  assert.match(html, /id="root"/);
});

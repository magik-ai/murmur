/* The page must not rebuild itself under the reader. Without this, a click lands on a node the
   tick has already replaced, a half typed message disappears, an open drawer shuts and the
   scroll position jumps. The tick is three seconds, so this check waits out two of them and
   asks whether anything the reader was holding on to survived. */

import { loadPlaywright } from "./test_playwright.mjs";

const URL = process.env.DASH_URL || "http://127.0.0.1:7903";
const TWO_TICKS = 7000;

const results = [];
const check = (name, passed, detail) => {
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
};

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
// A short window on purpose: the list has to be taller than the screen for a scroll
// position to exist at all, and a check that cannot move cannot prove it stayed.
const page = await (await browser.newContext({ viewport: { width: 1100, height: 520 } })).newPage();

await page.goto(`${URL}/#/board`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1600);

/* Mark the first card, so a rebuild can be seen even when the new node looks identical. */
await page.evaluate(() => {
  document.querySelector(".agent-card").dataset.probe = "held";
});
await page.click(".agent-card");
// The Board scrolls as a page, and the drawer scrolls inside itself. Both positions are what
// this check is about, so the list has to be long enough to have one.
await page.waitForTimeout(1200);

const opened = await page.evaluate(() => !document.getElementById("drawer").hidden);
check("a card opens the drawer", opened);

await page.fill("#laneMessage", "half a sentence the reader has not finished");
const scrolled = await page.evaluate(() => {
  document.getElementById("drawerBody").scrollTop = 120;
  window.scrollTo(0, 80);
  return { page: Math.round(window.scrollY), drawer: document.getElementById("drawerBody").scrollTop };
});
check("the fixture is tall enough to have a scroll position", scrolled.page > 0 && scrolled.drawer > 0,
  JSON.stringify(scrolled));
await page.waitForTimeout(TWO_TICKS);

const after = await page.evaluate(() => ({
  drawerOpen: !document.getElementById("drawer").hidden,
  typed: document.getElementById("laneMessage").value,
  drawerScroll: document.getElementById("drawerBody").scrollTop,
  pageScroll: Math.round(window.scrollY),
  probe: document.querySelector(".agent-card").dataset.probe,
  focused: document.activeElement && document.activeElement.id,
}));

check("the drawer is still open two ticks later", after.drawerOpen);
check("the half written message survived", after.typed === "half a sentence the reader has not finished", after.typed);
check("the drawer kept its scroll position", after.drawerScroll === scrolled.drawer, String(after.drawerScroll));
check("the page kept its scroll position", after.pageScroll === scrolled.page, String(after.pageScroll));
check("the card was updated, not replaced", after.probe === "held", String(after.probe));

/* Closing puts the reader back on the list, and nothing stays behind on the screen. */
await page.click("#drawerClose");
await page.waitForTimeout(1200);
const closed = await page.evaluate(() => ({
  hidden: document.getElementById("drawer").hidden,
  scrimHidden: document.getElementById("drawerScrim").hidden,
  cards: document.querySelectorAll(".agent-card").length,
}));
check("closing the drawer hides it and its cover", closed.hidden && closed.scrimHidden);
check("the list is still there afterwards", closed.cards > 0, `${closed.cards} cards`);

await browser.close();
const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

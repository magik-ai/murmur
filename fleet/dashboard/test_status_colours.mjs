/* The five status colours, measured in both themes, on the Machine tab of a stub farm that
   carries every one of them: a running service, a login waiting for a person, an expired
   login, a logged in account and a login nobody can read. A colour that reads strongly in one
   theme and washes out in the other is the defect this check exists to catch. */

import { loadPlaywright } from "./test_playwright.mjs";

const URL = process.env.DASH_URL || "http://127.0.0.1:7903";
const WANTED = { run: "blue", wait: "amber", fail: "red", done: "green", pause: "grey" };

const results = [];
const check = (name, passed, detail) => {
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
};

/* Classify a colour the way an eye does, not by its exact value: the point is that failed is
   red in both themes, not that it is one particular red. A browser hands back whichever form
   the stylesheet used, so both the wide gamut form and the plain one are read here. */
const hue = (value) => {
  const text = String(value);
  const parts = text.match(/[\d.]+/g);
  if (!parts) return "none";
  if (text.startsWith("oklch")) {
    const [, chroma, angle] = parts.map(Number);
    if (chroma < 0.05) return "grey";
    if (angle < 40 || angle >= 340) return "red";
    if (angle < 110) return "amber";
    if (angle < 200) return "green";
    if (angle < 300) return "blue";
    return `other(${angle})`;
  }
  const [red, green, blue] = parts.map(Number);
  if (Math.abs(red - green) < 18 && Math.abs(green - blue) < 18) return "grey";
  if (green > red + 25 && green > blue + 15) return "green";
  if (red > green + 40 && green > blue + 15) return "amber";
  if (red > green + 50) return "red";
  if (blue > red + 30) return "blue";
  return `other(${red},${green},${blue})`;
};

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();

for (const scheme of ["light", "dark"]) {
  const page = await (await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: scheme,
  })).newPage();
  await page.goto(`${URL}/#/machine`, { waitUntil: "domcontentloaded" });
  /* The tab draws each section as its answer comes in, so a fixed wait measures whichever
     sections happen to be in. Wait until every meaning is on the page, up to ten seconds; a
     meaning still missing then is reported below. */
  await page.waitForFunction((names) => names.every((name) => document.querySelector(`#view .pill.${name}`)),
    Object.keys(WANTED), { timeout: 10000 }).catch(() => {});

  const measured = await page.evaluate(() => {
    const out = {};
    for (const pill of document.querySelectorAll("#view .pill")) {
      const meaning = ["run", "wait", "fail", "done", "pause"]
        .find((name) => pill.classList.contains(name));
      if (!meaning || out[meaning]) continue;
      out[meaning] = {
        dot: getComputedStyle(pill.querySelector(".dot")).backgroundColor,
        text: getComputedStyle(pill).color,
      };
    }
    return out;
  });

  for (const [meaning, want] of Object.entries(WANTED)) {
    const found = measured[meaning];
    const seen = found ? hue(found.dot) : null;
    check(`${scheme}: ${meaning} reads ${want}`, seen === want,
      found ? `dot=${found.dot} -> ${seen}` : "no pill with this meaning on the Machine tab");
  }
  await page.close();
}

await browser.close();
const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

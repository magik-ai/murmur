/* The five status colours, measured in both themes, against a queue that carries every
   verdict. The live queue rarely holds an ejected or a cancelled record, and "I could not find
   one to look at" is not evidence that it renders correctly. A colour that reads strongly in
   one theme and washes out in the other is the defect this check exists to catch. */

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
  await page.goto(`${URL}/#/queue`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1600);

  /* The queue is one table with three bands, so every verdict is on the screen already: there
     is nothing to expand before the colours can be read. What this check still wants from the
     page is that all three bands are there, and that the recent one is not hiding the rows the
     colours live in. */
  const bands = await page.evaluate(() => [...document.querySelectorAll(".q-band")]
    .map((node) => node.innerText.replace(/\s+/g, " ").trim()));
  if (scheme === "light") {
    check("the queue names its three bands", bands.length === 3, bands.join(" | "));
    check("the recent band counts what finished", /Recent \(\d+\)/.test(bands[2] || ""), bands[2]);
  }

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
    /* The row's coloured edge is drawn by queue.css, which index.html links next to app.css.
       A page served without it still has to read correctly, so the edge is measured when it is
       there and the dot speaks for the row when it is not. */
    for (const row of document.querySelectorAll(".q-row")) {
      const meaning = ["run", "wait", "fail", "done", "pause"]
        .find((name) => row.classList.contains(name));
      const cell = row.querySelector("td");
      const shadow = cell ? getComputedStyle(cell).boxShadow : "none";
      if (meaning && out[meaning] && shadow && shadow !== "none") out[meaning].edge = shadow;
    }
    return out;
  });

  for (const [meaning, want] of Object.entries(WANTED)) {
    const found = measured[meaning];
    const seen = found ? [hue(found.dot), hue(found.edge || found.dot)] : null;
    check(`${scheme}: ${meaning} reads ${want}`,
      Boolean(found) && seen.every((value) => value === want),
      found ? `dot=${found.dot} edge=${found.edge} -> ${seen}` : "no record in this state");
  }
  await page.close();
}

await browser.close();
const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

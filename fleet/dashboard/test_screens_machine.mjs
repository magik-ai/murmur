/* Machine, in every state the stub can produce, at a desktop width and a phone width, and
   with the add-account step panel open. The check is narrow on purpose: nothing may throw, the
   page may never scroll sideways, and every screen must draw something. The pictures are the
   point, so a person can look at a tab they have never seen and say what it is for. They are
   written outside the repository and never committed.

   The view is opened through the stub's harness page, a small shell around the same modules
   index.html puts it in, so each picture is of the view and nothing else. */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./test_playwright.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR || path.join(os.tmpdir(), "murmur-dash-shots");
const PORT = Number(process.env.PORT || 7977);
const BASE = `http://127.0.0.1:${PORT}`;
const STATES = ["ready", "empty", "error", "loading", "quiet"];
const SIZES = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

const results = [];
function check(name, passed, detail) {
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

/* A port that is already taken is the one way these checks can go green against a page nobody
   here wrote: another worktree's stub answers, and every reading is about its tree. So the port
   is claimed before anything starts, and the harness this stub serves is proved to be there. */
async function answers(path) {
  try {
    return (await fetch(`${BASE}${path}`)).ok;
  } catch (error) {
    return false;
  }
}

if (await answers("/api/config")) {
  console.log(`FAIL  something already listens on ${PORT}. Set PORT to a free one.`);
  process.exit(1);
}

const stub = spawn("python3", [path.join(HERE, "test_stub_server.py"), String(PORT)], {
  env: { ...process.env, STUB_LOADING_DELAY: "20", STUB_JOB_SECONDS: "2", STUB_ADD_LOGIN_SECONDS: "600" },
  stdio: "ignore",
});
process.on("exit", () => stub.kill());
let up = false;
for (let attempt = 0; attempt < 60 && !up; attempt += 1) {
  up = await answers("/harness");
  if (!up) await new Promise((resolve) => setTimeout(resolve, 200));
}
if (!up) {
  console.log("FAIL  the stub server next to this file never came up");
  process.exit(1);
}
fs.mkdirSync(OUT, { recursive: true });

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();

/* What each state is supposed to say, beyond drawing without throwing. These are the lines a
   person would otherwise have to find in the pictures by hand. */
async function measured(page, state, screen, size) {
  const body = await page.evaluate(() => document.getElementById("view").innerText);
  const powerTitle = await page.evaluate(() => {
    const head = [...document.querySelectorAll("#view .section-head h2")].find((node) => node.textContent === "Power");
    return head ? head.title : "";
  });
  if (screen === "machine" && state === "ready") {
    const out = [
      ["carries its five sections",
        ["Power", "Services", "Accounts", "Models", "Projects"]
          .every((word) => body.includes(word)), body.slice(0, 120)],
      ["draws no Settings section, which only repeated where files live",
        !body.includes("written where they live"), "the settings live in their files"],
      ["draws no Health section on a farm that has not asked for one",
        !body.includes("What this farm needs"), "Health is off unless FLEET_DASH_HEALTH=on"],
      ["says the dashboard keeps running through a power action, on the Power heading",
        /keeps running through all of these/.test(powerTitle), powerTitle],
    ];
    return out;
  }
  if (screen === "machine" && state === "empty") {
    return [["says what is missing rather than showing empty tables",
      /No accounts registered/.test(body) && /Import your first repository/.test(body)
      && /No providers connected/.test(body), body.slice(0, 200)]];
  }
  if (screen === "machine" && state === "error") {
    return [
      ["switches every write control off and says why", /read/i.test(body), body.slice(0, 160)],
      ["says why services cannot be read, with the command that fixes it",
        /no user service manager/.test(body) && /enable-linger/.test(body), body.slice(0, 200)],
    ];
  }
  if (state === "loading") {
    const skeletons = await page.evaluate(() => document.querySelectorAll("#view .skeleton").length);
    return [["shows placeholders, not an error", skeletons > 0, `${skeletons} placeholders`]];
  }
  return [];
}

/* The screen that is not a plain tab: the add-account step panel. The Models section's screens
   are test_screens_models.mjs. */
async function openExtra(page, screen, size, state) {
  if (screen === "machine-add") {
    /* A read-only page switches this button off on purpose, and a page still loading has not
       drawn it yet. Both are screens worth a picture, they are simply not this one. */
    const found = await page.evaluate(() => {
      const button = document.querySelector("[data-add-account]");
      return Boolean(button) && !button.disabled;
    });
    if (!found) return false;
    await page.click("[data-add-account]");
    await page.waitForTimeout(400);
    // One name per screen: the stub remembers the ones already added, and an account that is
    // already logged in is not the panel this picture is of.
    await page.fill("#drawer input[aria-label='Account name']", `farm-${state}-${size.width}`);
    await page.click("[data-add-start]");
    await page.waitForTimeout(1200);
    const step = await page.evaluate(() => {
      const node = document.querySelector(".m-steps");
      return node ? node.innerText : "";
    });
    check(`machine add-account ${size.width} shows the command and the waiting state`,
      /ssh -t farm/.test(step) && /Waiting for the first login/.test(step), step.slice(0, 120));
    return true;
  }
  return true;
}

const SCREENS = ["machine", "machine-add"];

for (const state of STATES) {
  for (const size of SIZES) {
    const context = await browser.newContext({
      viewport: size,
      colorScheme: state === "ready" ? "light" : "dark",
    });
    const page = await context.newPage();
    const problems = [];
    page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      problems.push(message.text());
    });
    for (const screen of SCREENS) {
      await page.goto(`${BASE}/harness?state=${state}#/machine`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(state === "loading" ? 900 : 1500);
      if (screen.includes("-")) {
        const done = await openExtra(page, screen, size, state);
        if (!done && state === "ready") check(`${state} ${screen} ${size.width} could be opened`, false);
      }
      const wide = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        view: window.innerWidth,
      }));
      check(`${state} ${screen} ${size.width} does not scroll sideways`,
        wide.scroll <= wide.view + 1, `${wide.scroll} wide in ${wide.view}`);
      const empty = await page.evaluate(() => document.getElementById("view").childElementCount === 0);
      check(`${state} ${screen} ${size.width} drew something`, !empty);
      if (!screen.includes("-")) {
        for (const [name, passed, detail] of await measured(page, state, screen, size)) {
          check(`${state} ${screen} ${size.width} ${name}`, passed, detail);
        }
      }
      await page.screenshot({ path: path.join(OUT, `${state}-${screen}-${size.width}.png`),
        fullPage: size.width === 1440 && state === "ready" });
    }
    check(`${state} ${size.width} logged no error`, problems.length === 0, problems.slice(0, 3).join(" | "));
    await context.close();
  }
}

await browser.close();
stub.kill();

const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
console.log(`Pictures: ${OUT}`);
if (failed.length) process.exit(1);

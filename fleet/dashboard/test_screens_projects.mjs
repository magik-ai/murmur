/* The Projects section in pictures: the GitHub strip in each of its states, the table, the
   Connect and Switch dialogs, and each step of the Import dialog, at a desktop width and a
   phone width. The checks are narrow on purpose: nothing may throw, the page may never scroll
   sideways, and every screen must draw what it is for. The pictures are the point, so a person
   can look at a state they have never seen. They are written outside the repository and never
   committed (SHOT_DIR, by default a folder under the system's temporary directory). */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./test_playwright.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR || path.join(os.tmpdir(), "murmur-projects-shots");
const PORT = Number(process.env.PORT || 7983);
const BASE = `http://127.0.0.1:${PORT}`;
const SIZES = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

const results = [];
function check(name, passed, detail) {
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

async function answers(route) {
  try {
    return (await fetch(`${BASE}${route}`)).ok;
  } catch (error) {
    return false;
  }
}

if (await answers("/api/config")) {
  console.log(`FAIL  something already listens on ${PORT}. Set PORT to a free one.`);
  process.exit(1);
}

/* The stub runs in a home of its own, so no change to it can ever read or write the farm. */
const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), "murmur-projects-stub-"));
for (const name of ["home", "state", "config"]) fs.mkdirSync(path.join(SCRATCH, name));
const stub = spawn("python3", [path.join(HERE, "test_stub_server.py"), String(PORT)], {
  env: {
    ...process.env, STUB_LOADING_DELAY: "20", STUB_JOB_SECONDS: "600",
    HOME: path.join(SCRATCH, "home"),
    FLEET_STATE: path.join(SCRATCH, "state"),
    FLEET_CONFIG: path.join(SCRATCH, "config"),
  },
  stdio: "ignore",
});
process.on("exit", () => {
  stub.kill();
  fs.rmSync(SCRATCH, { recursive: true, force: true });
});
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

{
  const env = await (await fetch(`${BASE}/stub/github/env`)).json();
  const inside = (value) => typeof value === "string" && value.startsWith(SCRATCH + path.sep);
  check("the stub runs with a temporary HOME, FLEET_STATE and FLEET_CONFIG",
    inside(env.home) && inside(env.fleet_state) && inside(env.fleet_config), JSON.stringify(env));
}

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const shots = [];

/* The strip, one picture per state, each with the words it has to say. */
const STRIPS = [
  ["ready", "connected", /Signed in as @octo-farm/],
  ["ready", "missing_scope", /Agents cannot change CI workflow files/],
  ["ready", "no_git", /Git on this farm does not use this login/],
  ["ready", "two", /Two identities/],
  ["ready", "not_connected", /GitHub is not connected on this farm/],
  ["ready", "no_gh", /gh, is not installed/],
  ["ready", "no_answer", /did not answer/],
  ["ready", "fine", /scopes cannot be read/],
  ["ready", "office_denied", /cannot write to the head office/],
  ["ready", "office_name", /is not written as owner\/name/],
  ["ready", "unread", /What the agents may do is not known yet/],
  ["quiet", "connected", /Last read at/],
  ["empty", "connected", /Import your first repository/],
  ["empty", "not_connected", /Connect GitHub first/],
  ["error", "connected", /did not answer/],
  ["loading", "connected", null],
];

async function open(context, state, gh) {
  const page = await context.newPage();
  const thrown = [];
  page.on("pageerror", (error) => thrown.push(error.message));
  await page.goto(`${BASE}/harness?state=${state}&gh=${gh}${state === "quiet" ? "&long=1" : ""}#/machine`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(state === "loading" ? 900 : 1500);
  return { page, thrown };
}

async function sideways(page) {
  return page.evaluate(() => {
    const body = document.getElementById("drawerBody");
    return Math.max(document.documentElement.scrollWidth - window.innerWidth,
      body && !document.getElementById("drawer").hidden ? body.scrollWidth - body.clientWidth : 0);
  });
}

async function section(page) {
  return page.evaluateHandle(() => [...document.querySelectorAll("#view section")]
    .find((node) => node.querySelector("h2") && node.querySelector("h2").textContent === "Projects"));
}

async function shoot(page, name, target) {
  const file = path.join(OUT, `${name}.png`);
  if (target) {
    await target.scrollIntoViewIfNeeded();
    await target.screenshot({ path: file });
  } else {
    await page.screenshot({ path: file });
  }
  shots.push(file);
}

for (const size of SIZES) {
  const context = await browser.newContext({ viewport: size });
  for (const [state, gh, words] of STRIPS) {
    const { page, thrown } = await open(context, state, gh);
    const label = `${state} ${gh} ${size.width}`;
    const host = await section(page);
    const text = await host.evaluate((node) => (node ? node.innerText : ""));
    check(`strip ${label}: drew the section`, text.includes("Projects"), "");
    if (words) check(`strip ${label}: says it in words`, words.test(text), text.slice(0, 160));
    check(`strip ${label}: does not scroll sideways`, (await sideways(page)) <= 1, "");
    check(`strip ${label}: nothing threw`, thrown.length === 0, thrown[0]);
    await shoot(page, `strip-${state}-${gh}-${size.width}`, host.asElement());
    await page.close();
  }

  /* The dialogs, each step in turn. */
  {
    const { page, thrown } = await open(context, "ready", "not_connected");
    await page.click("[data-github-connect]");
    await page.waitForTimeout(300);
    check(`connect ${size.width}: opens with the warning first`,
      /^Every agent on this farm will act as this account\./.test(await page.evaluate(() => document.getElementById("drawerBody").innerText)), "");
    check(`connect ${size.width}: does not scroll sideways`, (await sideways(page)) <= 1, "");
    await shoot(page, `dialog-connect-${size.width}`);
    check(`connect ${size.width}: nothing threw`, thrown.length === 0, thrown[0]);
    await page.close();
  }
  {
    const { page, thrown } = await open(context, "ready", "connected");
    await page.click("[data-github-switch]");
    await page.waitForTimeout(300);
    check(`switch ${size.width}: does not scroll sideways`, (await sideways(page)) <= 1, "");
    await shoot(page, `dialog-switch-${size.width}`);
    check(`switch ${size.width}: nothing threw`, thrown.length === 0, thrown[0]);
    await page.close();
  }
  {
    const { page, thrown } = await open(context, "ready", "missing_scope");
    await page.click("[data-import-open]");
    await page.waitForSelector("[data-repo]");
    await page.selectOption("[data-owner]", "your-org");
    await page.waitForTimeout(500);
    check(`import choose ${size.width}: draws the list`, (await page.$$("[data-repo]")).length >= 8, "");
    check(`import choose ${size.width}: does not scroll sideways`, (await sideways(page)) <= 1, "");
    await shoot(page, `dialog-import-1-choose-${size.width}`);
    await page.fill("[data-paste]", "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8");
    await page.click("[data-paste-use]");
    await page.waitForTimeout(300);
    await page.evaluate(() => document.querySelector("[data-paste-error]").scrollIntoView());
    await shoot(page, `dialog-import-1-token-refused-${size.width}`);
    /* Each width imports its own repository: the first import registers it for the second. */
    await page.click(`[data-import-repo='your-org/${size.width > 640 ? "billing" : "analytics"}']`);
    await page.waitForSelector("[data-import-step='2']");
    await page.waitForTimeout(500);
    check(`import configure ${size.width}: does not scroll sideways`, (await sideways(page)) <= 1, "");
    await shoot(page, `dialog-import-2-configure-${size.width}`);
    await page.click("[data-port-change]");
    await page.selectOption("[data-branch]", "__typed");
    await page.waitForTimeout(200);
    await shoot(page, `dialog-import-2-configure-changed-${size.width}`);
    await page.fill("[data-branch-typed]", "release/2026");
    await page.click("[data-import-check]");
    await page.waitForSelector("[data-check]");
    await page.waitForTimeout(200);
    check(`import check ${size.width}: draws the checklist`, (await page.$$("[data-check]")).length === 6, "");
    check(`import check ${size.width}: does not scroll sideways`, (await sideways(page)) <= 1, "");
    await shoot(page, `dialog-import-3-check-${size.width}`);
    await page.click("[data-import-start]");
    await page.waitForSelector("[data-import-step='4']");
    await page.waitForTimeout(400);
    check(`import running ${size.width}: does not scroll sideways`, (await sideways(page)) <= 1, "");
    await shoot(page, `dialog-import-4-running-${size.width}`);
    check(`import ${size.width}: nothing threw`, thrown.length === 0, thrown[0]);
    await page.close();
  }
  {
    const { page, thrown } = await open(context, "ready", "connected");
    await page.click("[data-remove-project='sandbox']");
    await page.waitForTimeout(300);
    const host = await section(page);
    await shoot(page, `table-remove-confirm-${size.width}`, host.asElement());
    check(`remove ${size.width}: nothing threw`, thrown.length === 0, thrown[0]);
    await page.close();
  }
  await context.close();
}

await browser.close();
stub.kill();

const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
console.log(`Pictures (${shots.length}): ${OUT}`);
if (failed.length) process.exit(1);

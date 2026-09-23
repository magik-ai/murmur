/* The Models section in pictures: the providers table in every state the stub can produce, a
   provider's sidebar before and after "Request available models", a request that failed, the
   cost question, and the add-a-provider dialog, at a desktop width and a phone width. The check
   is narrow on purpose: nothing may throw, the page may never scroll sideways, and every screen
   must draw what it is a picture of. The pictures are written outside the repository and never
   committed.

   Nothing here reaches a provider: the stub answers every route, and the two model routes are
   answered by stub_models.py from lists written in it. */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./test_playwright.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR || path.join(os.tmpdir(), "murmur-dash-shots");
const PORT = Number(process.env.PORT || 7981);
const BASE = `http://127.0.0.1:${PORT}`;
const STATES = ["ready", "empty", "error", "loading"];
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

const stub = spawn("python3", [path.join(HERE, "test_stub_server.py"), String(PORT)], {
  env: { ...process.env, STUB_LOADING_DELAY: "20", STUB_JOB_SECONDS: "2" },
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

/* The catalog as a server of design section 6 answers it, built from the stub's own rows. Kimi
   takes a model here, so its sidebar reaches the request that fails. */
const STUB_ROWS = await (await fetch(`${BASE}/api/engines`)).json();
const CONTRACT = {
  claude: { models_on: ["opus", "sonnet"], default_model: "opus" },
  codex: { models_on: ["gpt-6-sol"], default_model: "gpt-6-sol" },
  qwen: { models_on: [], default_model: "" },
  kimi: { models_on: [], default_model: "", run: "{bin} -m {variant} -p {task}" },
  local: { models_on: [], default_model: "" },
};
const ENGINES = JSON.stringify(STUB_ROWS.map((row) => ({ ...row, ...(CONTRACT[row.id] || {}) })));

async function shoot(page, name, size, fullPage = false) {
  await page.screenshot({ path: path.join(OUT, `models-${name}-${size.width}.png`), fullPage });
}

async function wide(page, label) {
  const seen = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    view: window.innerWidth,
    drawer: (() => {
      const body = document.getElementById("drawerBody");
      return body && !document.getElementById("drawer").hidden ? body.scrollWidth - body.clientWidth : 0;
    })(),
  }));
  check(`${label} does not scroll sideways`, seen.scroll <= seen.view + 1 && seen.drawer <= 1,
    JSON.stringify(seen));
}

async function openPage(size, state, overrides = {}) {
  const context = await browser.newContext({
    viewport: size,
    colorScheme: state === "ready" ? "light" : "dark",
  });
  const page = await context.newPage();
  const problems = [];
  page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  for (const [route, body] of Object.entries(overrides)) {
    await page.route((url) => url.pathname === route,
      (handler) => handler.fulfill({ status: 200, contentType: "application/json", body }));
  }
  await page.goto(`${BASE}/harness?state=${state}#/machine`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(state === "loading" ? 900 : 1500);
  return { context, page, problems };
}

/* The section scrolled to, so its picture is the picture of it and not a strip at the bottom of
   a full page shot. The header is fixed over the top, so it is left a little room. */
async function toSection(page) {
  return page.evaluate(() => {
    const models = [...document.querySelectorAll("#view .section")]
      .find((item) => /^Models/.test(item.innerText));
    if (!models) return false;
    models.scrollIntoView({ block: "start" });
    window.scrollBy(0, -90);
    return true;
  });
}

/* ------------------------------------------------------ the table, in every state */

for (const state of STATES) {
  for (const size of SIZES) {
    const label = `${state} table ${size.width}`;
    const { context, page, problems } = await openPage(size, state,
      state === "ready" ? { "/api/engines": ENGINES } : {});
    const found = await toSection(page);
    check(`${label} draws the Models section`, found);
    await page.waitForTimeout(300);
    await wide(page, label);
    const body = await page.evaluate(() => {
      const node = [...document.querySelectorAll("#view .section")].find((item) => /^Models/.test(item.innerText));
      return node ? node.innerText : "";
    });
    if (state === "ready") {
      const seen = await page.evaluate(() => ({
        columns: [...document.querySelectorAll("#view .mo-providers thead th")]
          .filter((cell) => getComputedStyle(cell).display !== "none").map((cell) => cell.textContent),
        pills: [...document.querySelectorAll("#view .mo-providers tbody tr")]
          .map((row) => row.querySelector("td:nth-child(3) .pill-text").textContent),
        switches: [...document.querySelectorAll("#view .mo-providers [data-model-switch]")]
          .filter((node) => node.offsetParent).map((node) => node.textContent),
        counts: [...document.querySelectorAll("#view [data-model-count]")].map((node) => node.textContent),
      }));
      const columns = size.width > 640
        ? "Provider|Access|Status|Models|Last test|Actions" : "Provider|Status|Models";
      check(`${label} draws the providers table with its columns`,
        seen.columns.join("|") === columns, seen.columns.join("|"));
      check(`${label} shows the server's five status words, on drawn as Connected`,
        ["Connected", "Failing", "Off", "Needs a key", "Not installed"]
          .every((word) => seen.pills.includes(word)), seen.pills.join(", "));
      check(`${label} counts the models that are on`,
        seen.counts.includes("2 on") && seen.counts.includes("1 on"), seen.counts.join(", "));
      if (size.width > 640) {
        check(`${label} labels every switch with the press it makes`,
          seen.switches.length > 0 && seen.switches.every((word) => /^Switch (on|off)$/.test(word)),
          seen.switches.join(", "));
      }
    }
    if (state === "empty") {
      check(`${label} says no provider is connected and offers to add one`,
        /No providers connected/.test(body) && /Add a provider/.test(body), body.slice(0, 200));
    }
    if (state === "loading") {
      const skeletons = await page.evaluate(() => document.querySelectorAll("#view .skeleton").length);
      check(`${label} shows placeholders, not an error`, skeletons > 0, `${skeletons} placeholders`);
    }
    await shoot(page, `table-${state}`, size);
    check(`${label} logged no error`, problems.length === 0, problems.slice(0, 3).join(" | "));
    await context.close();
  }
}

/* ------------------------------------------------------------- the sidebar */

for (const size of SIZES) {
  const { context, page, problems } = await openPage(size, "ready", { "/api/engines": ENGINES });
  const label = (name) => `sidebar ${name} ${size.width}`;

  await page.click("[data-model-open='claude']");
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    const block = document.querySelector("#drawer .mo-list-block");
    if (block) block.scrollIntoView({ block: "start" });
  });
  const before = await page.evaluate(() => ({
    rows: [...document.querySelectorAll("#drawer [data-list-row]")].map((row) => row.getAttribute("data-list-row")),
    pill: (document.querySelector("#drawer [data-list-row='opus'] .pill-text") || {}).textContent || "",
  }));
  check(`${label("before a request")} lists the models that are on, the default marked`,
    before.rows.join(",") === "opus,sonnet" && before.pill === "Default", JSON.stringify(before));
  await wide(page, label("before a request"));
  await shoot(page, "sidebar-before", size);

  await page.click("[data-model-request='claude']");
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const block = document.querySelector("#drawer .mo-list-block");
    if (block) block.scrollIntoView({ block: "start" });
  });
  const after = await page.evaluate(() => ({
    rows: document.querySelectorAll("#drawer [data-list-row]").length,
    sources: [...document.querySelectorAll("#drawer .mo-tag .pill-text")].map((node) => node.textContent),
  }));
  check(`${label("after a request")} merges the offered models into the one list`,
    after.rows === 6 && after.sources.includes("From the docs") && after.sources.includes("On"),
    JSON.stringify(after));
  await wide(page, label("after a request"));
  await shoot(page, "sidebar-after", size);

  await page.click("[data-model-tick='fable']");
  await page.click("[data-model-tick='haiku']");
  await page.click("[data-model-save='claude']");
  await page.waitForTimeout(400);
  await page.evaluate(() => {
    const node = document.querySelector("#drawer [data-cost-question]");
    if (node) node.scrollIntoView({ block: "center" });
  });
  const question = await page.evaluate(() => {
    const node = document.querySelector("#drawer [data-cost-question]");
    return node ? node.innerText : "";
  });
  check(`${label("cost question")} asks before a noted model is switched on`,
    /can cost money/.test(question) && /Yes, switch it on/.test(question), question.slice(0, 200));
  await wide(page, label("cost question"));
  await shoot(page, "sidebar-cost", size);

  await page.click("#drawerClose");
  await page.waitForTimeout(300);
  await page.click("[data-model-open='kimi']");
  await page.waitForTimeout(500);
  await page.click("[data-model-request='kimi']");
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const block = document.querySelector("#drawer .mo-list-block");
    if (block) block.scrollIntoView({ block: "start" });
  });
  const failed = await page.evaluate(() => {
    const node = document.querySelector("#drawer [data-model-failed]");
    return { said: node ? node.textContent : "", rows: document.querySelectorAll("#drawer [data-list-row]").length };
  });
  check(`${label("failed request")} says why and shows the docs list`,
    /the file is missing/.test(failed.said) && failed.rows === 1, JSON.stringify(failed));
  await wide(page, label("failed request"));
  await shoot(page, "sidebar-failed", size);

  await page.click("#drawerClose");
  await page.waitForTimeout(300);
  await page.click("[data-model-open='qwen']");
  await page.waitForTimeout(500);
  const cannot = await page.evaluate(() => Boolean(document.querySelector("#drawer [data-model-cannot]")));
  check(`${label("no model list")} says the provider runs its own model`, cannot);
  await wide(page, label("no model list"));
  await shoot(page, "sidebar-cannot", size);

  check(`sidebar ${size.width} logged no error`, problems.length === 0, problems.slice(0, 3).join(" | "));
  await context.close();
}

/* ------------------------------------------------------- adding a provider */

for (const size of SIZES) {
  const { context, page, problems } = await openPage(size, "ready");
  await page.click("[data-add-model]");
  await page.waitForTimeout(500);
  /* A preset already in this farm's catalog cannot be picked, so the picture is taken on one
     that can: a service with a key, which draws all four steps. */
  const pickable = await page.evaluate(() => {
    const node = [...document.querySelectorAll("#drawer [data-preset]")].find((item) => !item.disabled);
    return node ? node.getAttribute("data-preset") : "";
  });
  check(`add a provider ${size.width} offers a service to pick`, Boolean(pickable), pickable);
  if (pickable) {
    await page.click(`#drawer [data-preset='${pickable}']`);
    await page.waitForTimeout(400);
    const steps = await page.evaluate(() => {
      const host = document.getElementById("drawerBody");
      return {
        count: host.querySelectorAll(".m-step-no").length,
        text: host.innerText,
        title: document.getElementById("drawerTitle").textContent,
      };
    });
    check(`add a provider ${size.width} draws four numbered steps under its new name`,
      steps.count === 4 && steps.title === "Add a provider", `${steps.count} steps, ${steps.title}`);
    check(`add a provider ${size.width} never asks for a key on the page`,
      !/paste (the |your )?key (here|below|in this)/i.test(steps.text), steps.text.slice(0, 160));
  }
  await wide(page, `add a provider ${size.width}`);
  await shoot(page, "add-provider", size);
  check(`add a provider ${size.width} logged no error`, problems.length === 0, problems.slice(0, 3).join(" | "));
  await context.close();
}

await browser.close();
stub.kill();

const failedChecks = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failedChecks.length}/${results.length} passed`);
console.log(`Pictures: ${OUT}`);
if (failedChecks.length) process.exit(1);

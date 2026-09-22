/* Queue and Machine, in every state the stub can produce, at a desktop width and a phone
   width, with the detail panel open and the add-account step panel open. The check is narrow
   on purpose: nothing may throw, the page may never scroll sideways, and every screen must
   draw something. The pictures are the point, so a person can look at a tab they have never
   seen and say what it is for. They are written outside the repository and never committed.

   The views are opened through the stub's harness page: the lane that owns index.html and
   app.js registers them in the real shell, and this check does not wait for it to land. */

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

/* The failed requests a state is meant to produce. The browser logs one console line for each;
   that line is the fixture working, not the page breaking. */
const EXPECTED_REQUEST_FAILURES = { error: ["/api/ci"] };

const results = [];
function check(name, passed, detail) {
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

/* Classify a colour the way an eye does, not by its exact value: the point is that a failed
   run reads red in both themes, not that it is one particular red. */
function hue(value) {
  const text = String(value);
  const parts = text.match(/[\d.]+/g);
  if (!parts) return "none";
  if (text.includes("oklch")) {
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
  if (screen === "queue" && state === "ready") {
    const counted = await page.evaluate(() => ({
      rows: document.querySelectorAll(".q-row").length,
      bands: [...document.querySelectorAll(".q-band")].map((node) => node.innerText.trim()),
    }));
    return [
      ["shows every run as a row", counted.rows >= 40, `${counted.rows} rows`],
      ["names its three bands with their counts",
        counted.bands.length === 3 && /Running \(1\)/.test(counted.bands[0])
        && /Recent \(40\)/.test(counted.bands[2]), counted.bands.join(" | ")],
    ];
  }
  if (screen === "queue" && state === "quiet") {
    return [
      ["says a quiet queue is quiet and still counts what finished",
        /Nothing is being verified right now/.test(body) && /Recent \(40\)/.test(body),
        body.slice(0, 160)],
    ];
  }
  if (screen === "queue" && state === "empty") {
    return [["says the queue has never run and how to fill it",
      /never run/.test(body) && /fleet ci enqueue/.test(body), body.slice(0, 160)]];
  }
  if (screen === "queue" && state === "error") {
    return [
      ["says the queue could not be read instead of drawing an empty table",
        /reported a problem|could not be read|did not answer/i.test(body), body.slice(0, 160)],
      ["passes on the service manager's own sentence about the runner",
        /no user service manager/.test(body), body.slice(0, 250)],
    ];
  }
  if (screen === "machine" && state === "ready") {
    const models = await page.evaluate(() => ({
      columns: [...document.querySelectorAll("#view .m-models thead th")]
        .map((node) => node.textContent),
      pills: [...document.querySelectorAll("#view .m-models tbody tr")]
        .map((row) => row.querySelector("td:nth-child(4) .pill-text").textContent),
      switches: [...document.querySelectorAll("#view [data-model-switch]")]
        .map((node) => node.textContent),
    }));
    /* Below 640px the same table is a card list, so a phone shows the state, the access and the
       actions instead of a clipped Model column with the rest behind a sideways drag. */
    const phone = size.width > 640 ? null : await page.evaluate(() => {
      const table = document.querySelector("#view .m-models");
      const wrap = table.closest(".tablewrap");
      const row = table.querySelector("tbody tr");
      return {
        head: getComputedStyle(table.querySelector("thead")).display,
        row: getComputedStyle(row).display,
        drag: wrap.scrollWidth - wrap.clientWidth,
        labels: [...row.querySelectorAll("td[data-col]")]
          .map((cell) => cell.getAttribute("data-col")).join(","),
      };
    });
    const out = [
      ["carries all seven sections",
        ["Power", "Services", "Accounts", "Models", "Projects", "Health", "Settings"]
          .every((word) => body.includes(word)), body.slice(0, 120)],
      ["says the dashboard keeps running through a power action",
        /keeps running through all of these/.test(body), body.slice(0, 160)],
      ["draws the models table with its six columns",
        models.columns.join("|") === "Model|Runs as|Access|Status|Last test|Actions",
        models.columns.join("|")],
      ["shows every model status as its own pill",
        ["On", "Failing", "Off", "Needs a key", "Not installed"]
          .every((word) => models.pills.includes(word)), models.pills.join(", ")],
      ["labels every switch with the press it makes, not the state",
        models.switches.length > 0
        && models.switches.every((word) => /^Switch (on|off)$/.test(word)),
        models.switches.join(", ")],
    ];
    if (phone) {
      out.push(["draws the models table as one card per model",
        phone.head === "none" && phone.row === "grid" && phone.drag <= 1
        && /Status/.test(phone.labels) && /Actions/.test(phone.labels),
        JSON.stringify(phone)]);
    }
    return out;
  }
  if (screen === "machine" && state === "empty") {
    return [["says what is missing rather than showing empty tables",
      /No accounts registered/.test(body) && /No projects yet/.test(body)
      && /No models registered/.test(body), body.slice(0, 200)]];
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

/* Going to the same address with the same hash does not reload the page, so a drawer opened by
   the screen before is still there and takes every click meant for the page under it. */
async function closeAnyDrawer(page) {
  const shut = await page.evaluate(() => {
    const host = document.getElementById("drawer");
    const close = document.getElementById("drawerClose");
    if (!host || host.hidden || !close) return false;
    close.click();
    return true;
  });
  if (shut) await page.waitForTimeout(400);
}

/* The four screens that are not a plain tab: the run detail, the add-account step panel, the
   models table on its own, and the add-model dialog with every step drawn. */
async function openExtra(page, screen, size, state) {
  if (screen === "queue-detail") {
    const target = await page.evaluate(() => {
      const row = document.querySelector(".q-row");
      return row ? row.dataset.run : "";
    });
    // Nothing to open in a queue that is empty, failing or still loading: that is its own screen.
    if (!target) return false;
    await page.click(`[data-run='${target}']`);
    await page.waitForTimeout(1200);
    const seen = await page.evaluate(() => {
      const panel = document.querySelector(".q-detail");
      if (!panel) return null;
      const box = panel.getBoundingClientRect();
      return { width: Math.round(box.width), view: window.innerWidth, fixed: getComputedStyle(panel).position };
    });
    if (seen && size.width <= 1000) {
      check(`queue detail ${size.width} becomes a full width sheet`,
        seen.fixed === "fixed" && seen.width >= seen.view - 1, JSON.stringify(seen));
    } else if (seen) {
      check(`queue detail ${size.width} sits beside the table`,
        seen.fixed !== "fixed" && seen.width < seen.view, JSON.stringify(seen));
    }
    return true;
  }
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
  if (screen === "machine-models") {
    await closeAnyDrawer(page);
    /* The table on its own, scrolled to, so the picture of it is the picture of it and not a
       strip at the bottom of a full page shot. An empty or failing farm still has the section;
       a loading one has a card of placeholders. */
    const found = await page.evaluate(() => {
      const sections = [...document.querySelectorAll("#view .section")];
      const models = sections.find((item) => /^Models/.test(item.innerText));
      if (!models) return false;
      models.scrollIntoView({ block: "start" });
      // The header is fixed over the top of the page, so a section put flush against the top
      // loses its own title behind it.
      window.scrollBy(0, -90);
      return true;
    });
    if (!found) return false;
    await page.waitForTimeout(300);
    return true;
  }
  if (screen === "machine-model-add") {
    await closeAnyDrawer(page);
    const open = await page.evaluate(() => {
      const button = document.querySelector("[data-add-model]");
      return Boolean(button) && !button.disabled;
    });
    if (!open) return false;
    await page.click("[data-add-model]");
    await page.waitForTimeout(500);
    /* A preset that is already in this farm's catalog cannot be picked, so the picture is
       taken on one that can: a service with a key, which draws all four steps. */
    const pickable = await page.evaluate(() => {
      const node = [...document.querySelectorAll("#drawer [data-preset]")].find((item) => !item.disabled);
      return node ? node.getAttribute("data-preset") : "";
    });
    if (!pickable) return false;
    await page.click(`#drawer [data-preset='${pickable}']`);
    await page.waitForTimeout(400);
    const steps = await page.evaluate(() => {
      const host = document.getElementById("drawerBody");
      return { count: host.querySelectorAll(".m-step-no").length, text: host.innerText };
    });
    check(`machine add-model ${size.width} draws four numbered steps`,
      steps.count === 4, `${steps.count} steps`);
    check(`machine add-model ${size.width} never asks for a key on the page`,
      !/paste (the |your )?key (here|below|in this)/i.test(steps.text), steps.text.slice(0, 160));
    return true;
  }
  return true;
}

const SCREENS = ["queue", "machine", "queue-detail", "machine-add", "machine-models",
  "machine-model-add"];

for (const state of STATES) {
  for (const size of SIZES) {
    const context = await browser.newContext({
      viewport: size,
      colorScheme: state === "ready" ? "light" : "dark",
    });
    const page = await context.newPage();
    const problems = [];
    const allowed = EXPECTED_REQUEST_FAILURES[state] || [];
    page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const said = message.text();
      if (said.includes("Failed to load resource")
        && allowed.some((route) => message.location().url.includes(route))) return;
      problems.push(said);
    });
    for (const screen of SCREENS) {
      const view = screen.startsWith("queue") ? "queue" : "machine";
      await page.goto(`${BASE}/harness?state=${state}#/${view}`, { waitUntil: "domcontentloaded" });
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

/* The five meanings, measured on the row edge in both themes. The pill colours come from
   app.css and are measured by the verdict check; the row edge is this stylesheet's own. */
for (const scheme of ["light", "dark"]) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: scheme });
  const page = await context.newPage();
  await page.goto(`${BASE}/harness?state=ready#/queue`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  const edges = await page.evaluate(() => {
    const out = {};
    for (const row of document.querySelectorAll(".q-row")) {
      const meaning = ["run", "wait", "fail", "done", "pause"].find((name) => row.classList.contains(name));
      if (!meaning || out[meaning]) continue;
      out[meaning] = getComputedStyle(row.querySelector("td")).boxShadow;
    }
    return out;
  });
  for (const [meaning, want] of Object.entries({ run: "blue", wait: "amber", fail: "red", done: "green", pause: "grey" })) {
    check(`${scheme}: a ${meaning} run has a ${want} edge`, edges[meaning] && hue(edges[meaning]) === want,
      `${edges[meaning]} reads ${hue(edges[meaning] || "")}`);
  }
  await context.close();
}

await browser.close();
stub.kill();

const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
console.log(`Pictures: ${OUT}`);
if (failed.length) process.exit(1);

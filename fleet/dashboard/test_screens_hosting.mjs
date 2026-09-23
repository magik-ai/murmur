/* The Hosting section and its two dialogs, in every state the stub can produce and at both
   widths, step by step. The check is narrow on purpose: nothing may throw, the page may never
   scroll sideways, every screen must draw something, and every row of both tables must be one
   line high. The pictures are the point, so a person can look at a section they have never seen
   and say what it costs them. They are written outside the repository and never committed.

   The section is opened through the stub's harness page, which is the same shell around the
   same modules that index.html puts them in. */

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
const STATES = ["ready", "empty", "error", "loading", "quiet"];
const SIZES = [{ width: 1440, height: 1000 }, { width: 390, height: 844 }];

/* The failed requests a state is meant to produce. The browser logs one console line for each;
   that line is the fixture working, not the page breaking. */
const EXPECTED_REQUEST_FAILURES = { error: ["/api/ci"] };

const KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKqkqLp0m1n2o3p4q5r6s7t8u9v0w1x2y3z4a5b6c7d8 you@laptop";

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
  env: { ...process.env, STUB_LOADING_DELAY: "20", STUB_JOB_SECONDS: "2",
    STUB_MACHINE_SECONDS: "600" },
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

/** Put the Hosting section under the header, so its picture is of it and not of the page. */
async function scrollToSection(page) {
  const found = await page.evaluate(() => {
    const section = [...document.querySelectorAll("#view .section")]
      .find((node) => node.innerText.startsWith("Hosting"));
    if (!section) return false;
    section.scrollIntoView({ block: "start" });
    // The header sits over the top of the page, so a section flush against it loses its title.
    window.scrollBy(0, -90);
    return true;
  });
  await page.waitForTimeout(300);
  return found;
}

/** Scroll the drawer to a numbered step, so the picture is of that step. */
async function scrollToStep(page, number) {
  await page.evaluate((wanted) => {
    const head = [...document.querySelectorAll("#drawer .m-step-no")]
      .find((node) => node.textContent === String(wanted));
    if (head) head.scrollIntoView({ block: "start" });
  }, number);
  await page.waitForTimeout(250);
}

/* What each screen has to say, beyond drawing without throwing. These are the lines a person
   would otherwise have to find in the pictures by hand. */
async function measured(page, screen, state) {
  const text = await page.evaluate(() => {
    const section = [...document.querySelectorAll("#view .section")]
      .find((node) => node.innerText.startsWith("Hosting"));
    return section ? section.innerText : "";
  });
  if (screen !== "hosting") return [];
  if (state === "ready" || state === "quiet") {
    return [
      ["says what this list costs a month", /You pay \$\d+ a month for \d+ machines/.test(text),
        text.slice(0, 120)],
      ["draws this farm first and both tables after it",
        /This farm/.test(text) && /Size and price/.test(text) && /Secrets/.test(text),
        text.slice(0, 200)],
      ["says the gap the Accounts windows have",
        /Usage by cloud agents is not in the Accounts windows yet/.test(text), text.slice(-160)],
    ];
  }
  if (state === "empty") {
    return [["says a fresh farm has only itself, and what fills the table",
      /No machine but this one/.test(text) && /fleet machines list/.test(text),
      text.slice(0, 200)]];
  }
  if (state === "error") {
    return [["says the machines could not be read, rather than drawing an empty table",
      /did not answer|reported a problem|could not be read/i.test(text), text.slice(0, 200)]];
  }
  if (state === "loading") {
    const skeletons = await page.evaluate(() => {
      const section = [...document.querySelectorAll("#view .section")]
        .find((node) => node.innerText.startsWith("Hosting"));
      return section ? section.querySelectorAll(".skeleton").length : 0;
    });
    return [["shows placeholders, not an error", skeletons > 0, `${skeletons} placeholders`]];
  }
  return [];
}

/* Every screen worth a picture: the section itself, then each dialog as a person walks it. */
async function openScreen(page, screen) {
  if (screen === "hosting") {
    await closeAnyDrawer(page);
    return scrollToSection(page);
  }
  if (screen.startsWith("add-machine")) {
    await closeAnyDrawer(page);
    const open = await page.evaluate(() => {
      const button = document.querySelector("[data-add-machine]");
      return Boolean(button) && !button.disabled;
    });
    if (!open) return false;
    await page.click("[data-add-machine]");
    await page.waitForTimeout(500);
    if (screen === "add-machine-1") return true;
    const pickable = await page.evaluate((wanted) => {
      const node = document.querySelector(`#drawer [data-machine-provider='${wanted}']`);
      return Boolean(node) && !node.disabled;
    }, screen === "add-machine-own" ? "ssh" : "do-droplet");
    if (!pickable) return false;
    await page.click(`#drawer [data-machine-provider='${screen === "add-machine-own" ? "ssh" : "do-droplet"}']`);
    await page.waitForTimeout(400);
    if (screen === "add-machine-own") {
      await page.fill("#drawer [data-machine-name]", "loft");
      await page.fill("#drawer [data-target]", "dev@192.168.1.55");
      await scrollToStep(page, 2);
      return true;
    }
    if (screen === "add-machine-2") {
      await scrollToStep(page, 2);
      return true;
    }
    await page.fill("#drawer [data-machine-name]", "lagos");
    await page.fill("#drawer [data-ssh-public]", KEY);
    if (screen === "add-machine-3") {
      await scrollToStep(page, 3);
      return true;
    }
    await page.click("[data-machine-plan]");
    await page.waitForTimeout(900);
    if (screen === "add-machine-4") {
      await scrollToStep(page, 4);
      const shown = await page.evaluate(() =>
        Boolean(document.querySelector("[data-machine-cloudinit]")));
      check(`add-machine review shows the cloud-init file`, shown, "");
      return true;
    }
    await page.click("[data-machine-create-open]");
    await page.waitForTimeout(400);
    await scrollToStep(page, 5);
    const said = await page.evaluate(() =>
      (document.querySelector("#drawer .m-confirm") || {}).innerText || "");
    check("add-machine confirm repeats the price and the bill",
      /\$48 a month/.test(said) && /billed until you destroy it/.test(said), said.slice(0, 160));
    return true;
  }
  if (screen.startsWith("runner")) {
    await closeAnyDrawer(page);
    const open = await page.evaluate(() => {
      const button = document.querySelector("[data-connect-runner]");
      return Boolean(button) && !button.disabled;
    });
    if (!open) return false;
    await page.click("[data-connect-runner]");
    await page.waitForTimeout(500);
    if (screen === "runner-1") return true;
    const pickable = await page.evaluate(() => {
      const node = document.querySelector("#drawer [data-runner-provider='railway']");
      return Boolean(node) && !node.disabled;
    });
    if (!pickable) return false;
    await page.click("#drawer [data-runner-provider='railway']");
    await page.waitForTimeout(400);
    const step = { "runner-2": 2, "runner-3": 3, "runner-4": 4, "runner-5": 5, "runner-6": 6 }[screen];
    if (step) await scrollToStep(page, step);
    if (screen === "runner-4") {
      const commands = await page.evaluate(() => [...document.querySelectorAll(
        "#drawer [data-runner-secret]")].map((node) => node.textContent).join(" | "));
      check("the runner dialog hands over one secret command per name",
        /fleet hosts secret railway CLAUDE_CODE_OAUTH_TOKEN/.test(commands)
        && /fleet hosts secret railway GITHUB_TOKEN/.test(commands), commands.slice(0, 200));
    }
    return true;
  }
  return true;
}

const SCREENS = ["hosting", "add-machine-1", "add-machine-2", "add-machine-3", "add-machine-4",
  "add-machine-5", "add-machine-own", "runner-1", "runner-2", "runner-3", "runner-4",
  "runner-5", "runner-6"];

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
      await page.goto(`${BASE}/harness?state=${state}#/machine`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(state === "loading" ? 900 : 1500);
      const done = await openScreen(page, screen);
      /* A read-only farm switches the two buttons off on purpose, and a farm still loading has
         not drawn them yet. Both are screens worth a picture; they are simply not this one. */
      if (!done && (state === "ready" || state === "quiet")) {
        check(`${state} ${screen} ${size.width} could be opened`, false);
      }
      const wide = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        view: window.innerWidth,
      }));
      check(`${state} ${screen} ${size.width} does not scroll sideways`,
        wide.scroll <= wide.view + 1, `${wide.scroll} wide in ${wide.view}`);
      const empty = await page.evaluate(() =>
        document.getElementById("view").childElementCount === 0);
      check(`${state} ${screen} ${size.width} drew something`, !empty);
      if (screen === "hosting") {
        for (const [name, passed, detail] of await measured(page, screen, state)) {
          check(`${state} hosting ${size.width} ${name}`, passed, detail);
        }
        /* The owner's rule, measured in the same pass that photographs it. */
        const heights = await page.evaluate(() => {
          const out = {};
          for (const table of document.querySelectorAll("#view .h-machines, #view .h-runners")) {
            out[table.className] = [...table.querySelectorAll("tbody tr")]
              .map((row) => Math.round(row.getBoundingClientRect().height));
          }
          return out;
        });
        for (const [name, rows] of Object.entries(heights)) {
          if (rows.length < 2) continue;
          check(`${state} ${name} ${size.width} has rows of one line each`,
            Math.max(...rows) - Math.min(...rows) <= 2, rows.join(", "));
        }
      }
      await page.screenshot({
        path: path.join(OUT, `hosting-${state}-${screen}-${size.width}.png`),
        fullPage: size.width === 1440 && state === "ready" && screen === "hosting",
      });
    }
    check(`${state} ${size.width} logged no error`, problems.length === 0,
      problems.slice(0, 3).join(" | "));
    await context.close();
  }
}

await browser.close();
stub.kill();

const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
console.log(`Pictures: ${OUT}`);
if (failed.length) process.exit(1);

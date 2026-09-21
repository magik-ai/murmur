/* Every tab, in every state, at a desktop width and a phone width. The check is narrow on
   purpose: nothing may throw, and the page may never scroll sideways. The pictures are the
   point, so a person can look at a tab they have never seen and say what it is for.
   The pictures are written outside the repository and are never committed. */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { loadPlaywright } from "./test_playwright.mjs";

const OUT = process.env.SHOT_DIR || path.join(os.tmpdir(), "murmur-dash-shots");
const PORT = Number(process.env.PORT || 7921);
const STATES = ["ready", "empty", "error", "loading", "quiet"];
const TABS = ["overview", "agents", "mail", "queue", "projects", "accounts", "system"];
const SIZES = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

/* A failed request the state is meant to produce. The browser logs one console line for it;
   that line is the fixture working, not the page breaking. */
const EXPECTED_REQUEST_FAILURES = { error: ["/api/ci"] };

/* What the live farm showed and no fixture used to: names too long for a card, twenty filters,
   a queue with nothing running, and an office holding one name twice. The pictures are taken
   either way; these are the three things a person would otherwise have to spot in them. */
async function measured(page, state, tab, size) {
  if (state !== "quiet") return [];
  if (tab === "overview") {
    const seen = await page.evaluate(() => {
      const card = (word) => [...document.querySelectorAll(".card")].find((node) => node.innerText.startsWith(word));
      const agents = card("Agents");
      const queue = card("Queue");
      return {
        agentSkeletons: agents ? agents.querySelectorAll(".skeleton").length : -1,
        agentText: agents ? agents.innerText.replace(/\s+/g, " ") : "",
        queueText: queue ? queue.innerText.replace(/\s+/g, " ") : "",
        queueSkeletons: queue ? queue.querySelectorAll(".skeleton").length : -1,
      };
    });
    return [
      ["shows the counts with no placeholder left above them",
        seen.agentSkeletons === 0 && /Running \d/.test(seen.agentText), JSON.stringify(seen)],
      ["says a quiet queue is quiet and counts what finished",
        seen.queueSkeletons === 0 && /Nothing is being verified right now/.test(seen.queueText)
          && /\d finished runs?/.test(seen.queueText), seen.queueText],
    ];
  }
  if (tab === "agents") {
    const seen = await page.evaluate(() => {
      const cut = (node) => node.scrollWidth > node.clientWidth + 1;
      const cards = [...document.querySelectorAll(".agent-card")];
      const heights = [...new Set([...document.querySelectorAll(".chip")].map((node) => Math.round(node.getBoundingClientRect().height)))];
      return {
        cards: cards.length,
        squeezed: cards.filter((card) => cut(card.querySelector(".pill-text"))).map((card) => card.querySelector(".pill-text").textContent),
        longNames: cards.filter((card) => cut(card.querySelector(".name"))).length,
        heights,
      };
    });
    return [
      ["never squeezes a status word", seen.cards > 0 && seen.squeezed.length === 0, seen.squeezed.join(", ")],
      ["cuts the long lane names instead", seen.longNames > 0, `${seen.longNames} cut`],
      ["keeps every filter chip one height", seen.heights.length === 1 && seen.heights[0] === 32,
        seen.heights.join(", ")],
    ];
  }
  if (tab === "mail") {
    const names = await page.evaluate(() => [...document.querySelectorAll(".boxlist li span:first-child")].map((node) => node.textContent));
    return [
      ["lists one mailbox per name", names.length === new Set(names).size, names.join(", ")],
      ["pins the box everybody reads to the top", names[0] === "all", names.join(", ")],
    ];
  }
  return [];
}

function startStub() {
  const child = spawn("python3", [new URL("./test_stub_server.py", import.meta.url).pathname, String(PORT)], {
    env: { ...process.env, STUB_LOADING_DELAY: "20" },
    stdio: "ignore",
  });
  return child;
}

async function waitForStub() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/api/config`);
      if (response.ok) return;
    } catch (error) { /* not up yet */ }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("the stub server never came up");
}

const results = [];
function check(name, passed, detail) {
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

const stub = startStub();
process.on("exit", () => stub.kill());
await waitForStub();
fs.mkdirSync(OUT, { recursive: true });

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();

for (const state of STATES) {
  for (const size of SIZES) {
    const context = await browser.newContext({ viewport: size, colorScheme: state === "ready" ? "light" : "dark" });
    const page = await context.newPage();
    const problems = [];
    const allowed = EXPECTED_REQUEST_FAILURES[state] || [];
    page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      if (text.includes("Failed to load resource") && allowed.some((route) => message.location().url.includes(route))) return;
      problems.push(text);
    });
    await page.goto(`http://127.0.0.1:${PORT}/?state=${state}#/overview`, { waitUntil: "domcontentloaded" });
    for (const tab of [...TABS, "agents-drawer", "agents-palette"]) {
      await page.evaluate((next) => {
        location.hash = next === "agents-drawer" || next === "agents-palette" ? "#/agents" : `#/${next}`;
      }, tab);
      await page.waitForTimeout(state === "loading" ? 600 : 900);
      // The drawer and the palette sit above the page, so the page's own clipping does not
      // reach them. They are measured here for the same reason every tab is.
      if (tab === "agents-drawer") {
        const slug = await page.evaluate(() => {
          const card = document.querySelector("[data-agent-card]");
          return card ? card.dataset.agentCard : "";
        });
        if (slug) {
          await page.evaluate((name) => {
            location.hash = `#/agents?agent=${encodeURIComponent(name)}`;
          }, slug);
        }
        await page.waitForTimeout(900);
      }
      if (tab === "agents-palette") {
        await page.keyboard.press("Meta+k");
        await page.waitForTimeout(500);
      }
      const wide = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        view: window.innerWidth,
      }));
      check(`${state} ${tab} ${size.width} does not scroll sideways`,
        wide.scroll <= wide.view + 1, `${wide.scroll} wide in ${wide.view}`);
      const empty = await page.evaluate(() => document.getElementById("view").childElementCount === 0);
      check(`${state} ${tab} ${size.width} drew something`, !empty);
      for (const [name, passed, detail] of await measured(page, state, tab, size)) {
        check(`${state} ${tab} ${size.width} ${name}`, passed, detail);
      }
      await page.screenshot({ path: path.join(OUT, `${state}-${tab}-${size.width}.png`) });
      if (tab === "agents-palette") await page.keyboard.press("Escape");
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

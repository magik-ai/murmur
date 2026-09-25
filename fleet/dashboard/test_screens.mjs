/* Every tab, in every state, at a desktop width and a phone width. The check is narrow on
   purpose: nothing may throw, the page may never scroll sideways, and the Board and the Mail tab
   must say the things measured below. The pictures are the point, so a person can look at a tab
   they have never seen and say what it is for.
   The pictures are written outside the repository and are never committed. */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { loadPlaywright } from "./test_playwright.mjs";

const OUT = process.env.SHOT_DIR || path.join(os.tmpdir(), "murmur-dash-shots");
const PORT = Number(process.env.PORT || 7921);
const STATES = ["ready", "empty", "error", "loading", "quiet"];
const TABS = ["board", "mail", "machine"];
const SIZES = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

/* The page asks Google Fonts for its three families. A machine that cannot reach them (offline,
   or behind a proxy the browser does not trust) draws the page in its fallback fonts, which is
   not a broken page, so a font that did not load is not counted as an error. */
const FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

/* What a busy farm shows and a plain fixture does not: names too long for a card and an office
   holding one name twice. The pictures are taken either way; these are the things a person
   would otherwise have to spot in them. */
async function measured(page, state, tab, size) {
  if (tab === "board" && state === "ready") {
    const seen = await page.evaluate(() => {
      const canvas = document.querySelector(".board-canvas");
      const agents = document.querySelector(".agents-pane");
      const tiles = [...document.querySelectorAll(".machine-strip .tile")];
      const heights = tiles.map((tile) => Math.round(tile.getBoundingClientRect().height));
      const accounts = [...document.querySelectorAll("[data-account]")];
      const tops = accounts.map((node) => Math.round(node.getBoundingClientRect().top));
      return {
        strip: tiles.length,
        accounts: accounts.length,
        oneHeight: heights.length > 0 && Math.max(...heights) - Math.min(...heights) <= 1,
        oneRow: tops.length > 0 && Math.max(...tops) - Math.min(...tops) <= 1,
        agentsFull: Boolean(canvas && agents) && agents.getBoundingClientRect().width >= canvas.getBoundingClientRect().width - 2,
        controls: ["agentSpawner", "agentStatus", "agentSearch"].filter((id) => document.getElementById(id)).length,
        power: document.querySelectorAll("#powerPick option").length,
        sweep: (document.getElementById("sweepNote") || {}).textContent || "",
      };
    });
    return [
      // Five tiles: capacity and the sweep are header lines, not tiles.
      ["puts the machine on one strip", seen.strip === 5, JSON.stringify(seen)],
      ["says when the sweep runs in the header", /^Sweep /.test(seen.sweep), seen.sweep],
      ["puts every subscription on the strip under it", seen.accounts >= 2, String(seen.accounts)],
      ["draws every machine tile at one height", seen.oneHeight, JSON.stringify(seen)],
      ["draws every subscription in one row", size.width === 390 ? true : seen.oneRow, JSON.stringify(seen)],
      ["gives the agents the full width", seen.agentsFull, JSON.stringify(seen)],
      ["gives the agents two selects and a search", seen.controls === 3, String(seen.controls)],
      ["keeps the power setting in the header", seen.power === 5, String(seen.power)],
    ];
  }
  if (tab === "board" && state === "empty") {
    const body = await page.evaluate(() => document.getElementById("view").innerText.replace(/\s+/g, " "));
    return [
      ["a farm with no agent is a page about starting one",
        /No agent has ever run here/.test(body) && /fleet spawn/.test(body), body.slice(0, 120)],
    ];
  }
  if (tab === "board" && state === "error") {
    const seen = await page.evaluate(() => ({
      checklist: Boolean([...document.querySelectorAll(".card")].find((node) => /^Finish setting up/.test(node.innerText))),
      note: document.getElementById("view").innerText.includes("This page was opened without the dashboard token."),
      power: document.getElementById("powerPick").disabled,
    }));
    return [
      ["a farm that is not finished says what is missing, first", seen.checklist, JSON.stringify(seen)],
      ["a page with no token says so and switches its controls off",
        seen.note && seen.power, JSON.stringify(seen)],
    ];
  }
  if (tab === "board" && state === "quiet") {
    const seen = await page.evaluate(() => {
      const cut = (node) => node.scrollWidth > node.clientWidth + 1;
      const cards = [...document.querySelectorAll(".agent-card")];
      return {
        cards: cards.length,
        squeezed: cards.filter((card) => cut(card.querySelector(".pill-text"))).map((card) => card.querySelector(".pill-text").textContent),
        longNames: cards.filter((card) => cut(card.querySelector(".name"))).length,
      };
    });
    return [
      ["never squeezes a status word", seen.cards > 0 && seen.squeezed.length === 0, seen.squeezed.join(", ")],
      ["cuts the long lane names instead", seen.longNames > 0, `${seen.longNames} cut`],
    ];
  }
  if (tab === "mail" && (state === "ready" || state === "quiet")) {
    const seen = await page.evaluate(() => ({
      names: [...document.querySelectorAll(".conversations li")].map((node) => node.dataset.conversation),
      first: document.querySelector(".conversations li .name")
        ? document.querySelector(".conversations li .name").textContent : "",
      pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 1,
      composer: Boolean(document.querySelector(".composer-label")),
      words: document.getElementById("view").innerText,
    }));
    const jargon = ["mailbox", "feed", "issue", "thread id"]
      .filter((word) => new RegExp(`\\b${word}\\b`, "i").test(seen.words));
    return [
      ["lists one conversation per name",
        size.width === 390 || seen.names.length === new Set(seen.names).size, seen.names.join(", ")],
      ["pins the conversation everybody reads to the top",
        size.width === 390 || (seen.names[0] === "all" && seen.first === "Everyone"), seen.names.join(", ")],
      ["never scrolls the page under the panes", !seen.pageScrolls, String(seen.pageScrolls)],
      ["keeps the composer on the screen", seen.composer, String(seen.composer)],
      ["says none of the jargon words", jargon.length === 0, jargon.join(", ")],
    ];
  }
  if (tab === "mail" && state === "error") {
    const body = await page.evaluate(() => document.getElementById("view").innerText.replace(/\s+/g, " "));
    return [
      ["a farm with no office says so in one sentence, with the command",
        /No head office is configured/.test(body) && /hq init/.test(body), body.slice(0, 140)],
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
    page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      if (text.includes("Failed to load resource") && FONT_HOSTS.some((host) => message.location().url.includes(host))) return;
      problems.push(text);
    });
    await page.goto(`http://127.0.0.1:${PORT}/?state=${state}#/board`, { waitUntil: "domcontentloaded" });
    for (const tab of [...TABS, "board-drawer", "board-palette"]) {
      await page.evaluate((next) => {
        location.hash = next === "board-drawer" || next === "board-palette" ? "#/board" : `#/${next}`;
      }, tab);
      await page.waitForTimeout(state === "loading" ? 600 : 900);
      // The drawer and the palette sit above the page, so the page's own clipping does not
      // reach them. They are measured here for the same reason every tab is.
      if (tab === "board-drawer") {
        const slug = await page.evaluate(() => {
          const card = document.querySelector("[data-agent-card]");
          return card ? card.dataset.agentCard : "";
        });
        if (slug) {
          await page.evaluate((name) => {
            location.hash = `#/board?agent=${encodeURIComponent(name)}`;
          }, slug);
        }
        await page.waitForTimeout(900);
      }
      if (tab === "board-palette") {
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
      if (tab === "board-palette") await page.keyboard.press("Escape");
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

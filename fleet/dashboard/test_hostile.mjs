/* What the page does when a route lies to it. Every case here overrides one route with a shape
   the server should never send, and asks two questions: did anything throw, and did the reader
   get told. A dashboard that draws half a screen and keeps saying "Live" is worse than one that
   says it cannot read the answer. The keyboard, the header, the read-only page and the
   addresses the old tabs answered on live here too, because they are the same kind of
   question: can a person still use this. */

import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./test_playwright.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 7971);
const BASE = `http://127.0.0.1:${PORT}`;
const ONLY = process.env.ONLY || "";

const results = [];
function check(name, passed, detail) {
  if (ONLY && !name.includes(ONLY)) return;
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

const stub = spawn("python3", [path.join(HERE, "test_stub_server.py"), String(PORT)], { stdio: "ignore" });
process.on("exit", () => stub.kill());
for (let attempt = 0; attempt < 60; attempt += 1) {
  try {
    if ((await fetch(`${BASE}/api/config`)).ok) break;
  } catch (error) { /* not up yet */ }
  await new Promise((resolve) => setTimeout(resolve, 200));
}

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();

/** A page with no write token, which is a legitimate way to run this dashboard. */
const READ_ONLY = JSON.stringify({
  writable: false,
  reason: "This page was opened without the dashboard token.",
  token_required: true,
  loopback: false,
});

/** One page, with the routes named in `overrides` answered by this test instead of the stub. */
async function open({ hash = "#/board", size = { width: 1440, height: 900 }, overrides = {}, seed = null }) {
  const context = await browser.newContext({ viewport: size });
  const page = await context.newPage();
  const thrown = [];
  const asked = [];
  page.on("pageerror", (error) => thrown.push(error.message));
  page.on("request", (request) => asked.push(request.url()));
  for (const [route, body] of Object.entries(overrides)) {
    await page.route((url) => url.pathname === route, (handler) => {
      if (typeof body === "function") return body(handler);
      return handler.fulfill({ status: 200, contentType: "application/json", body });
    });
  }
  if (seed) {
    await page.addInitScript((entries) => {
      for (const [key, value] of Object.entries(entries)) localStorage.setItem(key, value);
    }, seed);
  }
  await page.goto(`${BASE}/${hash}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1800);
  return { page, context, thrown, asked };
}

const text = (page) => page.evaluate(() => document.getElementById("view").innerText);

/* ------------------------------------------- a body that is not the shape it claims to be */

for (const [route, hash, name] of [
  ["/api/ci", "#/queue", "queue"],
  ["/api/metrics", "#/board", "the machine strip"],
  ["/api/accounts", "#/board", "the accounts strip"],
  ["/api/fleet", "#/board", "the agents pane"],
]) {
  const { page, context, thrown } = await open({
    hash,
    overrides: { [route]: (handler) => handler.fulfill({ status: 200, contentType: "application/json", body: "<html>a proxy said hello</html>" }) },
  });
  const body = await text(page);
  const label = await page.evaluate(() => document.getElementById("freshness").textContent);
  check(`${name}: an answer that is not JSON is an error, not data`, thrown.length === 0, thrown[0]);
  check(`${name}: the reader is told the answer could not be read`, /could not be read|not JSON|did not answer|reported a problem/i.test(body), body.slice(0, 60));
  check(`${name}: the header stops claiming the page is live`, /Stale/.test(label), label);
  await context.close();
}

{
  const { page, context, thrown } = await open({
    hash: "#/board",
    overrides: { "/api/fleet": JSON.stringify({ unavailable: "The farm state directory is not readable.", fix: "fleet doctor" }) },
  });
  const body = await text(page);
  check("a route that answers \"unavailable\" does not break the tab", thrown.length === 0, thrown[0]);
  check("the sentence and its command are shown", body.includes("not readable") && body.includes("fleet doctor"), body.slice(0, 80));
  await context.close();
}

{
  const { page, context, thrown } = await open({
    hash: "#/board",
    overrides: { "/api/projects": JSON.stringify({ rows: [] }), "/api/fleet": "null" },
  });
  check("a list route that answers an object breaks nothing", thrown.length === 0, thrown[0]);
  const chrome = await page.evaluate(() => document.getElementById("projectFilter").options.length);
  check("the chrome keeps repainting after a misshapen list", chrome >= 1, String(chrome));
  await context.close();
}

/* ------------------------------------------------------ data that wants to be a stylesheet */

{
  const beacon = "https://evil.example.invalid/beacon.png";
  const { page, context, thrown, asked } = await open({
    hash: "#/board",
    overrides: {
      "/api/identities": JSON.stringify({
        winston: { icon: "E", color: `red;background-image:url('${beacon}');position:fixed;inset:0;z-index:99999` },
      }),
    },
  });
  check("a colour from the registry breaks nothing", thrown.length === 0, thrown[0]);
  check("no third party is fetched because of a registry colour", !asked.some((url) => url.includes("evil.example.invalid")));
  const styled = await page.evaluate(() => [...document.querySelectorAll("#view .glyph")]
    .filter((node) => node.getAttribute("style")).length);
  check("no server value reaches a style attribute", styled === 0, `${styled} glyphs carry one`);
  await context.close();
}

{
  const { page, context } = await open({
    hash: "#/board",
    overrides: {
      "/api/identities": JSON.stringify({ winston: { icon: "X".repeat(400), color: "#5b8def" } }),
    },
  });
  const wide = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, view: window.innerWidth }));
  check("a very long glyph does not widen the page", wide.scroll <= wide.view + 1, JSON.stringify(wide));
  await context.close();
}

/* ------------------------------------------------------------------ a link that is not one */

{
  const { page, context } = await open({
    hash: "#/board?agent=demo-web-91bd",
    overrides: {
      "/api/agent": JSON.stringify({
        slug: "demo-web-91bd", project: "demo", lane: "web", status: "pr_open",
        started_at: Math.floor(Date.now() / 1000) - 600,
        pr_url: "javascript:window.__pwn=1;void 0",
      }),
    },
  });
  const hrefs = await page.evaluate(() => [...document.querySelectorAll("#drawerBody a")].map((node) => node.getAttribute("href")));
  const shown = await page.evaluate(() => document.getElementById("drawerBody").innerText);
  check("a link that is not http is never rendered as a link", !hrefs.some((href) => /^javascript:/i.test(href)), JSON.stringify(hrefs));
  check("the address is still shown as text", shown.includes("javascript:window.__pwn"), shown.slice(0, 60));
  await context.close();
}

/* ------------------------------------------- the addresses the old seven tabs answered on */

for (const [from, wanted, name] of [
  ["#/overview", "#/board", "overview"],
  ["#/system", "#/machine", "system"],
  ["#/projects", "#/machine?section=projects", "projects"],
  ["#/accounts", "#/machine?section=accounts", "accounts"],
  ["#/agents?agent=demo-api-3f2a", "#/board?agent=demo-api-3f2a", "an agent bookmark"],
]) {
  const { page, context, thrown } = await open({ hash: from });
  const where = await page.evaluate(() => location.hash);
  const drew = await page.evaluate(() => document.getElementById("view").childElementCount > 0);
  check(`${name}: the old address lands on its new home`, where === wanted, `${where} wanted ${wanted}`);
  check(`${name}: and the page it lands on drew something`, drew && thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/agents?agent=demo-api-3f2a" });
  const open2 = await page.evaluate(() => ({
    drawer: !document.getElementById("drawer").hidden,
    title: document.getElementById("drawerTitle").textContent,
  }));
  check("a bookmarked lane still opens its drawer after the redirect",
    open2.drawer && open2.title === "demo-api-3f2a", JSON.stringify(open2));
  await context.close();
}

/* -------------------------------------------------------- the four states, everywhere */

{
  const { page, context } = await open({
    hash: "#/board",
    overrides: { "/api/fleet": (handler) => new Promise(() => { /* never answers */ }) },
  });
  const pane = await page.evaluate(() => {
    const found = document.querySelector(".agents-pane");
    return found ? { text: found.innerText, skeletons: found.querySelectorAll(".skeleton").length } : null;
  });
  check("the agents pane shows a skeleton, not an empty list", pane && pane.skeletons > 0, JSON.stringify(pane));
  await context.close();
}

/* A panel that is drawn before its answer arrives has TWO shapes under one key: a grey
   placeholder and the value that replaces it. The live farm showed both at once. */

{
  const late = JSON.stringify([
    { slug: "a", project: "demo", lane: "web", status: "running", started_at: 1, updated_at: 1 },
    { slug: "b", project: "demo", lane: "api", status: "failed", started_at: 1, updated_at: 1 },
  ]);
  const { page, context } = await open({
    hash: "#/board",
    overrides: {
      "/api/fleet": (handler) => setTimeout(() => handler.fulfill({
        status: 200, contentType: "application/json", body: late,
      }), 1000),
    },
  });
  const pane = await page.evaluate(() => {
    const found = document.querySelector(".agents-pane");
    return found ? {
      skeletons: found.querySelectorAll(".skeleton").length,
      cards: found.querySelectorAll("[data-agent-card]").length,
    } : null;
  });
  check("the skeleton is replaced by the cards, not left above them",
    pane && pane.skeletons === 0 && pane.cards === 2, JSON.stringify(pane));
  await context.close();
}

/* The queue lives on its own tab (owner ruling 2026-09-22). The Board is the two strips and the
   agents at full width, every machine tile one height with its note on the bottom edge, and
   every subscription in one row. */

{
  const { page, context, thrown, asked } = await open({ hash: "#/board" });
  await page.waitForTimeout(800);
  const seen = await page.evaluate(() => {
    const tiles = [...document.querySelectorAll(".machine-strip .tile")];
    const heights = tiles.map((tile) => Math.round(tile.getBoundingClientRect().height));
    const notes = tiles.map((tile) => tile.querySelector(".note"));
    const bottomsMatch = tiles.every((tile, index) => notes[index]
      && Math.abs(tile.getBoundingClientRect().bottom - notes[index].getBoundingClientRect().bottom) < 16);
    const accounts = [...document.querySelectorAll("[data-account]")];
    const tops = accounts.map((node) => Math.round(node.getBoundingClientRect().top));
    const canvas = document.querySelector(".board-canvas");
    const agents = document.querySelector(".agents-pane");
    return {
      queue: Boolean(document.querySelector(".queue-pane, .splitter")),
      tiles: tiles.length,
      oneHeight: Math.max(...heights) - Math.min(...heights) <= 1,
      notesAtBottom: bottomsMatch,
      accounts: accounts.length,
      oneRow: Math.max(...tops) - Math.min(...tops) <= 1,
      full: agents.getBoundingClientRect().width >= canvas.getBoundingClientRect().width - 2,
    };
  });
  check("nothing of the queue is on the Board", !seen.queue, JSON.stringify(seen));
  check("the Board never asks for the queue", !asked.some((url) => url.includes("/api/ci")), asked.join(" "));
  check("every machine tile is one height with its note on the bottom edge",
    seen.tiles >= 5 && seen.oneHeight && seen.notesAtBottom, JSON.stringify(seen));
  check("every subscription sits in one row", seen.accounts >= 4 && seen.oneRow, JSON.stringify(seen));
  check("the agents take the full width", seen.full, JSON.stringify(seen));
  check("the Board threw nothing", thrown.length === 0, thrown.join(" | "));
  await context.close();
}

/* ------------------------------------------ a farm that has not been finished, or started */

{
  const { page, context, thrown } = await open({
    hash: "#/board",
    overrides: {
      "/api/health": JSON.stringify({
        at: new Date().toISOString(), stale_since: null, error: null, pending: null,
        checks: [
          { id: "gh", label: "gh", state: "missing", detail: "gh is not installed.", fix: "sudo apt install gh" },
          { id: "tmux", label: "tmux", state: "ok", detail: "version 3.4", fix: "" },
        ],
      }),
    },
  });
  const seen = await page.evaluate(() => {
    const found = [...document.querySelectorAll(".card")].find((node) => /^Finish setting up/.test(node.innerText));
    return found ? { text: found.innerText.replace(/\s+/g, " "), buttons: found.querySelectorAll("button").length } : null;
  });
  check("a missing prerequisite puts the checklist on top of the board",
    seen && /sudo apt install gh/.test(seen.text), seen ? seen.text.slice(0, 120) : "no checklist");
  check("and the checklist cannot be dismissed without fixing it", seen && seen.buttons === 0, JSON.stringify(seen));
  check("the checklist breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open({
    hash: "#/board",
    overrides: { "/api/fleet": JSON.stringify([]) },
  });
  const body = await text(page);
  check("a farm that has never run a lane is told how to run one",
    /No agent has ever run here/.test(body) && /fleet spawn --project demo/.test(body), body.replace(/\s+/g, " ").slice(0, 200));
  check("and the strips are not drawn over an empty farm", !/Memory free/.test(body), body.slice(0, 80));
  await context.close();
}

/* -------------------------------------------------------- a name nobody thought to bound */

{
  const long = "lane-".concat("x".repeat(660));
  const { page, context, thrown } = await open({
    hash: `#/board?agent=${long}`,
    size: { width: 390, height: 844 },
    overrides: {
      "/api/fleet": JSON.stringify([{ slug: long, project: long, lane: "web", status: "running", started_at: 1 }]),
      "/api/agent": JSON.stringify({ slug: long, project: long, lane: "web", status: "running", started_at: 1, branch: long }),
    },
  });
  const wide = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, view: window.innerWidth }));
  check("an open drawer never widens the page", wide.scroll <= wide.view + 1, JSON.stringify(wide));
  check("a very long name breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown } = await open({
    hash: "#/board",
    overrides: { "/api/fleet": JSON.stringify([{ slug: null, project: "demo", status: "running", started_at: 1 }]) },
  });
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(300);
  await page.keyboard.type("boa");
  await page.waitForTimeout(400);
  const options = await page.evaluate(() => document.getElementById("paletteList").children.length);
  check("a nameless lane does not kill the jump palette", thrown.length === 0, thrown[0]);
  check("the palette still filters", options > 0, String(options));
  await context.close();
}

/* --------------------------------------------------------------------------- the keyboard */

{
  const { page, context } = await open({ hash: "#/board" });
  const reached = await page.evaluate(async () => {
    const card = document.querySelector("[data-agent-card]");
    if (!card) return { found: false };
    card.focus();
    return { found: true, focused: document.activeElement === card };
  });
  check("an agent card can take focus", reached.found && reached.focused, JSON.stringify(reached));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(900);
  const drawer = await page.evaluate(() => {
    const node = document.getElementById("drawer");
    return {
      open: !node.hidden,
      role: node.getAttribute("role"),
      modal: node.getAttribute("aria-modal"),
      focusInside: node.contains(document.activeElement),
    };
  });
  check("Enter on a card opens the drawer", drawer.open);
  check("the drawer is a dialog", drawer.role === "dialog" && drawer.modal === "true", JSON.stringify(drawer));
  check("focus moves into the drawer", drawer.focusInside, JSON.stringify(drawer));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(600);
  const back = await page.evaluate(() => ({
    closed: document.getElementById("drawer").hidden,
    focused: document.activeElement && document.activeElement.dataset && document.activeElement.dataset.agentCard,
  }));
  check("Escape closes the drawer and hands focus back to the card", back.closed && Boolean(back.focused), JSON.stringify(back));

  await page.evaluate(() => {
    const table = [...document.querySelectorAll(".segmented button")].find((node) => node.textContent === "Table");
    if (table) table.click();
  });
  await page.waitForTimeout(500);
  const rows = await page.evaluate(() => ({
    header: Boolean(document.querySelector("thead th button")),
    row: document.querySelector("tbody tr") && document.querySelector("tbody tr").getAttribute("tabindex"),
  }));
  check("a sortable column is a button", rows.header, JSON.stringify(rows));
  check("a table row can take focus", rows.row === "0", JSON.stringify(rows));
  /* The table says what each lane runs on: the vendor's mark and the model with its effort
     (owner, 2026-09-24). */
  const models = await page.evaluate(() => {
    const heads = [...document.querySelectorAll("thead th")].map((node) => node.textContent.trim());
    const at = heads.indexOf("Model");
    return {
      at,
      cells: at < 0 ? [] : [...document.querySelectorAll("tbody tr")].map((row) => {
        const cell = row.children[at];
        const mark = cell.querySelector("svg.engine-mark");
        return `${mark ? mark.getAttribute("aria-label") : "-"}:${cell.innerText.trim()}`;
      }),
    };
  });
  check("the agents table has a Model column", models.at > 0, JSON.stringify(models));
  check("and a Claude lane shows Claude's mark with its model and effort",
    models.cells.includes("Claude:opus high"), JSON.stringify(models.cells));
  check("and a Codex lane with no model recorded shows OpenAI's mark and says default",
    models.cells.includes("Codex (OpenAI):default xhigh"), JSON.stringify(models.cells));
  await context.close();
}

/* The agents table keeps to the window at laptop widths with its Model column in, and a cell
   its fixed columns cut keeps its words on a title. */
for (const width of [700, 1024, 1280, 1440]) {
  const { page, context } = await open({ hash: "#/board", size: { width, height: 900 } });
  await page.evaluate(() => {
    const table = [...document.querySelectorAll(".segmented button")].find((node) => node.textContent === "Table");
    if (table) table.click();
  });
  await page.waitForSelector("table.agents-table tbody tr", { timeout: 10000 }).catch(() => null);
  const fit = await page.evaluate(() => {
    const wrap = document.querySelector("table.agents-table") && document.querySelector("table.agents-table").closest(".tablewrap");
    const untitled = [];
    for (const cell of document.querySelectorAll("table.agents-table :is(td, th)")) {
      const cut = [cell, ...cell.querySelectorAll("*")].some((node) => node.scrollWidth > node.clientWidth + 1);
      const words = cell.innerText.replace(/\s+/g, " ").trim().toLowerCase();
      const title = (cell.title || "").toLowerCase();
      if (cut && !(title && words.split(" ").every((word) => title.includes(word.replace(/\u2026$/, ""))))) untitled.push(words.slice(0, 40));
    }
    return { rows: document.querySelectorAll("table.agents-table tbody tr").length,
      over: wrap ? wrap.scrollWidth - wrap.clientWidth : -1, untitled };
  });
  check(`the agents table does not scroll sideways at ${width}`, fit.rows > 0 && fit.over <= 1, JSON.stringify(fit));
  check(`and every cut cell in it carries its words on a title at ${width}`, fit.untitled.length === 0, JSON.stringify(fit.untitled));
  await context.close();
}

/* A card carries its engine as the vendor's mark at the right of its foot, and no longer as
   a word in the line under its name. */
{
  const { page, context } = await open({ hash: "#/board" });
  const marks = await page.evaluate(() => [...document.querySelectorAll("[data-agent-card]")].map((card) => {
    const mark = card.querySelector(".foot svg.engine-mark");
    return {
      slug: card.dataset.agentCard,
      mark: mark ? mark.getAttribute("aria-label") : "",
      right: mark ? Math.round(card.getBoundingClientRect().right - mark.getBoundingClientRect().right) : -1,
      word: card.querySelector(".sub .tag") ? card.querySelector(".sub .tag").textContent : "",
    };
  }));
  const claude = marks.find((row) => row.slug === "demo-api-3f2a") || {};
  check("a Claude card carries Claude's mark in its foot", claude.mark === "Claude", JSON.stringify(claude));
  check("and the mark sits at the right edge, not after the words",
    claude.right >= 0 && claude.right <= 24, JSON.stringify(claude));
  check("and the engine is no longer a word under the name", claude.word === "", JSON.stringify(claude));
  await context.close();
}

/* The Board's subscription cards carry their engine as the vendor's mark in the top right
   corner, not as a word next to the name. */
{
  const { page, context } = await open({ hash: "#/board" });
  await page.waitForSelector("[data-account]", { timeout: 10000 }).catch(() => null);
  const chips = await page.evaluate(() => [...document.querySelectorAll("[data-account]")].map((chip) => {
    const mark = chip.querySelector(".label svg.engine-mark");
    const box = chip.getBoundingClientRect();
    return {
      name: chip.dataset.account,
      mark: mark ? mark.getAttribute("aria-label") : "",
      right: mark ? Math.round(box.right - mark.getBoundingClientRect().right) : -1,
      top: mark ? Math.round(mark.getBoundingClientRect().top - box.top) : -1,
      word: chip.querySelector(".label .tag") ? chip.querySelector(".label .tag").textContent : "",
    };
  }));
  const one = chips.find((chip) => chip.name === "farm-one") || {};
  const two = chips.find((chip) => chip.name === "farm-two") || {};
  check("a Claude subscription card carries Claude's mark", one.mark === "Claude", JSON.stringify(one));
  check("a Codex subscription card carries OpenAI's mark", two.mark === "Codex (OpenAI)", JSON.stringify(two));
  check("and the mark sits in the top right corner", one.right >= 0 && one.right <= 24 && one.top >= 0 && one.top <= 28,
    JSON.stringify(one));
  check("and the engine is no longer a word beside the name", one.word === "" && two.word === "", JSON.stringify(chips));
  await context.close();
}

/* The Accounts table: each subscription carries its engine as a mark at the right of its name. */
{
  const { page, context } = await open({ hash: "#/machine" });
  await page.waitForSelector("table.m-accounts tbody tr", { timeout: 10000 }).catch(() => null);
  const accounts = await page.evaluate(() => ({
    heads: [...document.querySelectorAll("table.m-accounts thead th")].map((node) => node.textContent.trim()),
    marks: [...document.querySelectorAll("table.m-accounts tbody tr")].map((row) => {
      const mark = row.querySelector("td:first-child svg.engine-mark");
      return mark ? mark.getAttribute("aria-label") : "";
    }),
  }));
  check("the Accounts table has no Engine column of words",
    accounts.heads.length > 0 && !accounts.heads.includes("Engine"), JSON.stringify(accounts.heads));
  check("and each account shows its engine's mark", accounts.marks.includes("Claude")
    && accounts.marks.includes("Codex (OpenAI)"), JSON.stringify(accounts.marks));
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/mail" });
  const listed = await page.evaluate(() => ({
    listbox: document.querySelector(".conversations") && document.querySelector(".conversations").getAttribute("role"),
    option: document.querySelector(".conversations li") && document.querySelector(".conversations li").getAttribute("tabindex"),
  }));
  check("the conversation list is a listbox", listed.listbox === "listbox", JSON.stringify(listed));
  check("a conversation can take focus", listed.option === "0", JSON.stringify(listed));
  await context.close();
}


{
  const { page, context } = await open({ hash: "#/board" });
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(400);
  const before = await page.evaluate(() => {
    const input = document.getElementById("paletteInput");
    return {
      role: input.getAttribute("role"),
      controls: input.getAttribute("aria-controls"),
      active: input.getAttribute("aria-activedescendant"),
      focused: document.activeElement === input,
    };
  });
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(250);
  const after = await page.evaluate(() => document.getElementById("paletteInput").getAttribute("aria-activedescendant"));
  check("the palette input is a combobox", before.role === "combobox" && before.controls === "paletteList", JSON.stringify(before));
  check("the palette says which option is highlighted", Boolean(before.active) && after !== before.active, `${before.active} -> ${after}`);
  await context.close();
}

/* The search field is the only field in its box: it takes the whole width, and its focus is a
   line along its own bottom edge rather than an outline the box's corners cut in half (owner,
   2026-09-23: the field stopped at 200px and its focus ring was clipped on two sides). */
{
  const { page, context } = await open({ hash: "#/board" });
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(400);
  await page.keyboard.type("demo");
  const field = await page.evaluate(() => {
    const input = document.getElementById("paletteInput");
    const box = input.closest(".palette-box");
    const style = getComputedStyle(input);
    return {
      input: Math.round(input.getBoundingClientRect().width),
      box: Math.round(box.clientWidth),
      focused: document.activeElement === input,
      outline: style.outlineStyle,
      edge: style.borderBottomColor,
      // The accent as the browser computes a colour, so a token written in hex and an edge
      // reported in rgb() compare as the same colour.
      accent: (() => {
        const probe = document.createElement("span");
        probe.style.color = "var(--accent)";
        document.body.appendChild(probe);
        const value = getComputedStyle(probe).color;
        probe.remove();
        return value;
      })(),
    };
  });
  check("the search field takes the whole width of its box", Math.abs(field.input - field.box) <= 2, JSON.stringify(field));
  check("the search field shows focus without an outline its box would cut",
    field.focused && field.outline === "none" && field.edge === field.accent, JSON.stringify(field));
  await context.close();
}

/* A tab left open across a deploy says so and offers a reload, instead of quietly running the
   old code against the new data (owner, 2026-09-23). */
{
  let build = "1000";
  const { page, context } = await open({
    hash: "#/board",
    overrides: {
      "/api/version": (handler) => handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ v: build }) }),
    },
  });
  await page.waitForTimeout(1200);
  const before = await page.evaluate(() => Boolean(document.querySelector(".update-strip")));
  build = "2000";
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await page.waitForTimeout(1200);
  const after = await page.evaluate(() => {
    const strip = document.querySelector(".update-strip");
    return strip ? { text: strip.textContent, button: Boolean(strip.querySelector("button")) } : null;
  });
  check("a tab on the build it was loaded from shows no update note", before === false, String(before));
  check("a tab left open across a deploy says so and offers a reload",
    Boolean(after && after.button && /updated/.test(after.text)), JSON.stringify(after));
  await context.close();
}

/* The note arrives on its own, up to thirty seconds after a deploy, so it lands on whoever is
   typing: a half-written message and its cursor must survive it. */
{
  let build = "1000";
  const { page, context } = await open({
    hash: "#/mail",
    overrides: {
      "/api/version": (handler) => handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ v: build }) }),
    },
  });
  await page.waitForTimeout(1200);
  await page.click("#mailText");
  await page.keyboard.type("half a message");
  build = "2000";
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await page.waitForTimeout(1200);
  const kept = await page.evaluate(() => ({
    note: Boolean(document.querySelector(".update-strip")),
    value: document.getElementById("mailText") && document.getElementById("mailText").value,
    focused: document.activeElement && document.activeElement.id,
  }));
  check("a half-typed message and its cursor survive the update note",
    kept.note && kept.value === "half a message" && kept.focused === "mailText", JSON.stringify(kept));
  await context.close();
}

/* ------------------------------------------------------------------- the reader's own eyes */

{
  const { page, context } = await open({ hash: "#/board", size: { width: 390, height: 844 } });
  const header = await page.evaluate(() => {
    const bar = document.getElementById("topbar");
    const right = document.querySelector(".top-controls");
    return {
      bar: bar.scrollWidth <= bar.clientWidth + 1,
      right: right.scrollWidth <= right.clientWidth + 1,
      wide: right.scrollWidth,
      room: right.clientWidth,
    };
  });
  check("the header fits on a phone", header.bar && header.right, JSON.stringify(header));
  const fullWidth = await page.evaluate(() => {
    const agents = document.querySelector(".agents-pane").getBoundingClientRect();
    const canvas = document.querySelector(".board-canvas").getBoundingClientRect();
    return agents.width >= canvas.width - 2;
  });
  check("the agents take the full width on a phone", fullWidth);
  const clipped = await page.evaluate(() => {
    const bad = [];
    for (const pill of document.querySelectorAll(".agent-card .pill")) {
      const card = pill.closest(".agent-card").getBoundingClientRect();
      const box = pill.getBoundingClientRect();
      if (box.right > card.right + 1 || pill.querySelector(".pill-text").scrollWidth > pill.querySelector(".pill-text").clientWidth + 1) {
        bad.push(pill.textContent.trim());
      }
    }
    return bad;
  });
  check("a status pill is never clipped on a card", clipped.length === 0, clipped.join(" | "));
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/board" });
  const words = await page.evaluate(() => [...document.querySelectorAll(".agent-card .pill-text")].map((node) => node.textContent));
  check("there are five status words and no sixth", !words.includes("Unreadable"), words.join(" | "));
  const detail = await text(page);
  check("an unreadable record says so as a detail", /record unreadable/i.test(detail));
  const emoji = await page.evaluate(() => {
    // Every mark on the page comes from the server's registry. The page itself draws none.
    const marks = [...document.querySelectorAll("#view .glyph")].map((node) => node.textContent);
    const rest = document.getElementById("view").innerText;
    for (const mark of marks) if (mark) { /* a registry glyph is data, not page copy */ }
    return [...rest].filter((sign) => sign.codePointAt(0) > 0x2100 && !marks.some((mark) => mark.includes(sign))).join("");
  });
  check("the page's own copy carries no emoji markers", emoji === "", emoji);
  await context.close();
}

/* One word, one meaning, on one screen. A farm with no room for another agent has a header
   pill that says "No room" and a power setting a few inches away whose top setting is called
   "Full". The Capacity tile is gone (owner audit 2026-09-23: the header already says it), so
   nothing on the Board may be a second capacity reading that could disagree with the pill. */
{
  const { page, context } = await open({
    hash: "#/board",
    overrides: {
      "/api/metrics": JSON.stringify({
        ts: Date.now() / 1000, agents: 6, can_spawn: false, level: "block",
        reasons: ["free memory is under the floor"],
        block_reasons: ["free memory is under the floor"], warnings: [],
        load: { load1: 12.8, load5: 11.2, load15: 9.7, cores: 14 },
        mem: { ram_total_gb: 64, ram_avail_gb: 1.2, ram_used_gb: 62.8, swap_total_gb: 8, swap_used_gb: 6.4, swap_churn_kbps: 900 },
        disk: { path: "/", total_gb: 1000, used_gb: 980, free_gb: 20 },
        cpu_temp_c: 71, cpu_temp_source: "package sensor", sensors_unavailable: false,
      }),
    },
  });
  const said = await page.evaluate(() => {
    const found = [...document.querySelectorAll(".tile")]
      .find((node) => node.querySelector(".label").textContent.startsWith("Capacity"));
    return {
      tile: found ? found.querySelector(".value").textContent : "",
      pill: document.querySelector("#capacity .pill-text").textContent,
      power: document.getElementById("powerPick").textContent.replace(/\s+/g, " "),
    };
  });
  check("the header pill says No room on a farm with no room", said.pill === "No room", said.pill);
  check("the Board draws no second capacity reading", said.tile === "", said.tile);
  check("Full on this screen means only the power setting", said.power.includes("Full"), said.power);
  await context.close();
}

/* A graphics card that answers 0 degrees has given no temperature (a resting card can), and
   the tile says there is no reading instead of drawing a freezing card (owner, 2026-09-24). */
{
  const { page, context } = await open({
    hash: "#/board",
    overrides: {
      "/api/metrics": JSON.stringify({
        ts: Date.now() / 1000, agents: 1, can_spawn: true, level: "ok", reasons: [],
        block_reasons: [], warnings: [],
        load: { load1: 1.2, load5: 1.1, load15: 1.0, cores: 12 },
        mem: { ram_total_gb: 17.6, ram_avail_gb: 11.6, ram_used_gb: 6, swap_total_gb: 4, swap_used_gb: 0, swap_churn_kbps: 0 },
        disk: { path: "/", total_gb: 1000, used_gb: 700, free_gb: 300 },
        gpu: { name: "generic card", temp_c: 0, util_pct: 0, mem_used_mb: 2000, mem_total_mb: 16000 },
        cpu_temp_c: null, cpu_temp_source: null, sensors_unavailable: true,
      }),
    },
  });
  const gpu = await page.evaluate(() => {
    const found = [...document.querySelectorAll(".tile")]
      .find((node) => node.querySelector(".label").textContent.startsWith("Graphics card"));
    return found ? found.querySelector(".value").textContent : "";
  });
  check("a graphics card that answers 0 degrees reads No reading, not 0 C", gpu === "No reading", gpu);
  await context.close();
}

/* ------------------------------------------------- what the two selects and the search do */

{
  const { page, context } = await open({ hash: "#/board" });
  const started = await page.evaluate(() => [...document.querySelectorAll("#agentSpawner option")].map((node) => node.textContent));
  const states = await page.evaluate(() => [...document.querySelectorAll("#agentStatus option")].map((node) => node.textContent));
  check("the started-by select counts the lanes behind every name",
    started[0] === "Anyone (6)" && started.some((row) => /^winston \(\d\)$/.test(row)), started.join(" | "));
  check("the status select offers the five meanings and counts them",
    states.length === 6 && states[0] === "Any (6)" && states.some((row) => /^Running \(\d\)$/.test(row)),
    states.join(" | "));
  await page.fill("#agentSearch", "checkout");
  await page.waitForTimeout(500);
  const found = await page.evaluate(() => [...document.querySelectorAll("[data-agent-card]")].map((node) => node.dataset.agentCard));
  check("the search finds a lane by its name", found.length === 1 && found[0].includes("checkout"), found.join(", "));
  await page.fill("#agentSearch", "412");
  await page.waitForTimeout(500);
  const byNumber = await page.evaluate(() => [...document.querySelectorAll("[data-agent-card]")].map((node) => node.dataset.agentCard));
  check("and by the number of the change it has open", byNumber.length === 1 && byNumber[0] === "demo-web-91bd", byNumber.join(", "));
  await page.fill("#agentSearch", "nothing-like-this");
  await page.waitForTimeout(500);
  const none = await page.evaluate(() => document.querySelector(".agents-pane").innerText);
  check("a search that finds nothing says how to get back", /No agent matches this filter/.test(none), none.slice(0, 80));
  await context.close();
}

/* The way a reader uses these two selects twice: pick a name, then go back to everyone. The
   first option of each is the one that clears it, and picking it must never leave the pane
   empty with the advice "clear the two selects" under it. */
{
  const { page, context, thrown } = await open({ hash: "#/board" });
  const countLine = () => page.evaluate(() => document.querySelector(".count-line").textContent);
  const cards = () => page.evaluate(() => document.querySelectorAll("[data-agent-card]").length);
  const values = await page.evaluate(() => [...document.querySelectorAll("#agentSpawner option")]
    .map((node) => node.getAttribute("value")));
  check("every option carries its own value and not its label",
    values[0] === "" && values.slice(1).every((value) => value && !value.includes("(")),
    values.map((value) => JSON.stringify(value)).join(" | "));

  await page.selectOption("#agentSpawner", { index: 1 });
  await page.waitForTimeout(400);
  const narrowed = await countLine();
  check("picking a name in Started by narrows the pane", /^[1-5] of 6$/.test(narrowed), narrowed);
  await page.selectOption("#agentSpawner", { index: 0 });
  await page.waitForTimeout(400);
  const back = await countLine();
  check("picking Anyone again shows every lane", back === "6 of 6" && (await cards()) === 6,
    `${back}, ${await cards()} cards`);

  await page.selectOption("#agentStatus", { index: 1 });
  await page.waitForTimeout(400);
  await page.selectOption("#agentStatus", { index: 0 });
  await page.waitForTimeout(400);
  const cleared = await countLine();
  check("picking Any status again shows every lane", cleared === "6 of 6" && (await cards()) === 6,
    `${cleared}, ${await cards()} cards`);
  check("clearing a filter throws nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------- stopping a lane, and retiring it */

{
  const writes = [];
  const { page, context, thrown } = await open({
    hash: "#/board?agent=demo-api-3f2a",
    overrides: {
      "/api/agent": JSON.stringify({
        slug: "demo-api-3f2a", project: "demo", lane: "api", status: "running",
        started_at: Math.floor(Date.now() / 1000) - 600, restart: "until-pr",
      }),
      "/api/agents/kill": (handler) => {
        writes.push(JSON.parse(handler.request().postData() || "{}"));
        return handler.fulfill({
          status: 200, contentType: "application/json",
          body: JSON.stringify({ ok: true, slug: "demo-api-3f2a", restart: "until-pr", detail: "demo-api-3f2a was asked to stop." }),
        });
      },
    },
  });
  const offered = await page.evaluate(() => [...document.querySelectorAll("[data-lane-end]")].map((node) => node.textContent));
  check("a lane with a restart policy is offered both endings",
    offered.join(" | ") === "Stop this pass | Retire this lane", offered.join(" | "));
  await page.click('[data-lane-end="stop"]');
  await page.waitForTimeout(400);
  const said = await page.evaluate(() => document.querySelector(".confirm").innerText.replace(/\s+/g, " "));
  check("the confirm says what the runner will do next",
    /under a new name/.test(said) && /until-pr/.test(said), said.slice(0, 160));
  await page.click('[data-confirm-yes="stop"]');
  await page.waitForTimeout(900);
  const toast = await page.evaluate(() => document.getElementById("toasts").innerText.replace(/\s+/g, " "));
  check("stopping posts the slug and whether it is a retirement",
    writes.length === 1 && writes[0].slug === "demo-api-3f2a" && writes[0].retire === false, JSON.stringify(writes));
  check("and the reader is told what happened", /was asked to stop/.test(toast), toast);
  check("ending a lane breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const writes = [];
  const { page, context } = await open({
    hash: "#/board?agent=demo-api-3f2a",
    overrides: {
      "/api/agent": JSON.stringify({
        slug: "demo-api-3f2a", project: "demo", lane: "api", status: "running",
        started_at: Math.floor(Date.now() / 1000) - 600, restart: "until-merged",
      }),
      "/api/agents/kill": (handler) => {
        writes.push(JSON.parse(handler.request().postData() || "{}"));
        return handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, restart: null }) });
      },
    },
  });
  await page.click('[data-lane-end="retire"]');
  await page.waitForTimeout(400);
  const said = await page.evaluate(() => document.querySelector(".confirm").innerText.replace(/\s+/g, " "));
  check("retiring says the runner will not start it again", /will not\s+start it again/.test(said), said.slice(0, 160));
  await page.click('[data-confirm-yes="retire"]');
  await page.waitForTimeout(900);
  check("retiring posts the retirement", writes.length === 1 && writes[0].retire === true, JSON.stringify(writes));
  await context.close();
}

{
  const { page, context } = await open({
    hash: "#/board?agent=demo-api-3f2a",
    overrides: {
      "/api/agent": JSON.stringify({
        slug: "demo-api-3f2a", project: "demo", lane: "api", status: "running",
        started_at: Math.floor(Date.now() / 1000) - 600,
      }),
    },
  });
  const offered = await page.evaluate(() => [...document.querySelectorAll("[data-lane-end]")].map((node) => node.textContent));
  check("a lane with no restart policy has one ending, not two",
    offered.join(" | ") === "Stop this lane", offered.join(" | "));
  await context.close();
}

{
  const said = "that lane is not running any more";
  const { page, context } = await open({
    hash: "#/board?agent=demo-api-3f2a",
    overrides: {
      "/api/agents/kill": (handler) => handler.fulfill({
        status: 409, contentType: "application/json", body: JSON.stringify({ error: said }),
      }),
    },
  });
  await page.click('[data-lane-end="stop"]');
  await page.waitForTimeout(300);
  await page.click('[data-confirm-yes="stop"]');
  await page.waitForTimeout(900);
  const toast = await page.evaluate(() => document.getElementById("toasts").innerText);
  check("a refused stop shows the reason the server gave", toast.includes(said), toast);
  await context.close();
}

/* ---------------------------------------------------------------- the read-only page */

{
  const { page, context, thrown } = await open({
    hash: "#/board?agent=demo-api-3f2a",
    overrides: { "/api/access": READ_ONLY },
  });
  const off = await page.evaluate(() => {
    const controls = [...document.querySelectorAll("#powerPick, [data-lane-end], #drawerBody .composer button, #drawerBody .composer textarea")];
    return {
      count: controls.length,
      allOff: controls.every((node) => node.disabled),
      said: document.body.innerText.includes("This page was opened without the dashboard token."),
      marked: document.body.classList.contains("readonly"),
    };
  });
  // The header's power setting is one select since 2026-09-24 (it was five buttons): the power
  // select, the lane's endings and the composer's button and field.
  check("a page with no token has every write control on the board switched off",
    off.count >= 4 && off.allOff, JSON.stringify(off));
  check("and it says why, in the server's own words", off.said && off.marked, JSON.stringify(off));
  check("a read-only board breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open({
    hash: "#/mail",
    overrides: { "/api/access": READ_ONLY },
  });
  const off = await page.evaluate(() => {
    const controls = [...document.querySelectorAll(".composer button, .composer textarea")];
    return {
      count: controls.length,
      allOff: controls.every((node) => node.disabled),
      said: document.getElementById("view").innerText.includes("This page was opened without the dashboard token."),
    };
  });
  check("a page with no token cannot send a message either",
    off.count >= 2 && off.allOff && off.said, JSON.stringify(off));
  await context.close();
}

/* ------------------------------------------------------------- the power setting */

{
  const writes = [];
  const { page, context, thrown } = await open({
    hash: "#/board",
    overrides: {
      "/api/mode": (handler) => {
        const request = handler.request();
        if (request.method() !== "POST") return handler.continue();
        writes.push(JSON.parse(request.postData() || "{}"));
        return handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
      },
    },
  });
  const options = await page.evaluate(() => [...document.querySelectorAll("#powerPick option")].map((node) => node.value));
  check("the header offers the four settings and Automatic",
    options.join(" | ") === "full | soft | balanced | hard | auto", options.join(" | "));
  await page.selectOption("#powerPick", "balanced");
  await page.waitForTimeout(900);
  check("choosing one posts it", writes.some((row) => row.mode === "balanced"), JSON.stringify(writes));
  check("the power setting breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The power setting is a select at every width (owner audit 2026-09-24): at 1024 it has to be
   on screen, post what it says, and carry the write mark. */
{
  const writes = [];
  const { page, context, thrown } = await open({
    hash: "#/board",
    size: { width: 1024, height: 800 },
    overrides: {
      "/api/mode": (handler) => {
        const request = handler.request();
        if (request.method() !== "POST") return handler.continue();
        writes.push(JSON.parse(request.postData() || "{}"));
        return handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
      },
    },
  });
  const seen = await page.evaluate(() => {
    const pick = document.getElementById("powerPick");
    return {
      pick: Boolean(pick) && getComputedStyle(pick.closest("label")).display !== "none",
      right: pick ? Math.round(pick.getBoundingClientRect().right) : 0,
      options: pick ? [...pick.options].map((node) => node.value).join(",") : "",
      marked: Boolean(pick && pick.closest("[data-write]")),
    };
  });
  check("at 1024 the header shows the power select, on the screen",
    seen.pick && seen.right > 0 && seen.right <= 1024, JSON.stringify(seen));
  check("the select offers the same five settings", seen.options === "full,soft,balanced,hard,auto", seen.options);
  check("the select is marked as a write", seen.marked, JSON.stringify(seen));
  await page.selectOption("#powerPick", "balanced");
  await page.waitForTimeout(900);
  check("choosing one posts it", writes.some((row) => row.mode === "balanced"), JSON.stringify(writes));
  check("the power select breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The header says whether the farm works, in three words (owner, 2026-09-24): on, paused or off,
   and room is only mentioned when there is none. */
{
  const services = (state) => JSON.stringify({ at: new Date().toISOString(), stale_since: null, error: null,
    services: [{ id: "agent_runner", label: "Agent runner", state, since: Date.now() / 1000 - 600, actions: ["start", "stop", "restart"] }] });
  const read = async (overrides) => {
    const { page, context } = await open({ hash: "#/board", overrides });
    const seen = await page.evaluate(() => ({
      farm: document.querySelector("#farmState .pill-text").textContent,
      why: document.getElementById("farmState").title,
      room: document.getElementById("capacity").hidden,
    }));
    await context.close();
    return seen;
  };
  const on = await read({ "/api/services": services("active") });
  check("a working farm reads Farm on, and says nothing about room", on.farm === "Farm on" && on.room, JSON.stringify(on));
  const off = await read({ "/api/services": services("inactive") });
  check("a stopped agent runner reads Farm off, and says what to do", off.farm === "Farm off" && /Start it/.test(off.why), JSON.stringify(off));
  const empty = await read({ "/api/services": JSON.stringify({ at: new Date().toISOString(), stale_since: null, error: null, services: [] }) });
  check("a farm that lists no agent runner is not called on", empty.farm !== "Farm on", JSON.stringify(empty));
  const failed = await read({ "/api/services": (handler) => handler.fulfill({ status: 500, contentType: "application/json", body: '{"error":"no user service manager"}' }) });
  check("a farm whose services cannot be read is not called on", failed.farm !== "Farm on", JSON.stringify(failed));
  const noMode = await read({ "/api/services": services("active"),
    "/api/mode": (handler) => handler.fulfill({ status: 500, contentType: "application/json", body: '{"error":"no power profile"}' }) });
  check("an active runner with an unreadable power setting is not called on", noMode.farm !== "Farm on" && /may be Paused/.test(noMode.why), JSON.stringify(noMode));
  /* A runner that answered active once and then stopped answering: the cache keeps the old
     data, and an old active is not Farm on. */
  {
    let calls = 0;
    const { page, context } = await open({ hash: "#/board", overrides: {
      "/api/services": (handler) => (calls++ === 0
        ? handler.fulfill({ status: 200, contentType: "application/json", body: services("active") })
        : handler.fulfill({ status: 500, contentType: "application/json", body: '{"error":"gone"}' })),
    } });
    await page.waitForTimeout(8000);
    const later = await page.evaluate(() => document.querySelector("#farmState .pill-text").textContent);
    check("a services answer that goes stale after an active one is not Farm on", later !== "Farm on" && calls > 1, `${later} after ${calls} reads`);
    await context.close();
  }
  const paused = await read({ "/api/services": services("active"),
    "/api/mode": JSON.stringify({ setting: "hard", effective: "hard", slice: true }) });
  check("power on Paused reads Farm paused", paused.farm === "Farm paused", JSON.stringify(paused));
}

/* A project name may be forty characters. At 1024 the header still fits: the project filter is
   what gives way, never Search or the theme. */
{
  const { page, context } = await open({ hash: "#/board", size: { width: 1024, height: 800 } });
  const seen = await page.evaluate(() => {
    const name = "p".repeat(40);
    document.getElementById("projectFilter").add(new Option(name, name));
    const theme = document.getElementById("themeSwitch").getBoundingClientRect();
    return { page: document.documentElement.scrollWidth, width: window.innerWidth, theme: Math.round(theme.right) };
  });
  check("a forty-character project leaves the 1024 header on the screen",
    seen.page <= seen.width && seen.theme <= seen.width, JSON.stringify(seen));
  await context.close();
}

/* The actions that moved into the section headings are write controls wherever they sit. */
{
  const { page, context } = await open({ hash: "#/machine", size: { width: 1024, height: 900 } });
  await page.waitForTimeout(1500);
  const marks = await page.evaluate(() => ["[data-accounts-refresh]", "[data-add-account]", "[data-add-model]",
    "[data-add-machine]", "[data-connect-runner]"].map((selector) => {
    const node = document.querySelector(selector);
    return [selector, node ? Boolean(node.closest("[data-write]")) : null];
  }));
  check("every heading action on the Machine tab is marked as a write",
    marks.every(([, marked]) => marked === true), JSON.stringify(marks));
  await context.close();
}

/* A failed sweep says so in words in the header: colour alone is not a warning. */
{
  const { page, context } = await open({
    hash: "#/board",
    overrides: {
      "/api/sweep": JSON.stringify({ enabled: true, result: "failed", secs_left: 90 }),
    },
  });
  const said = await page.evaluate(() => {
    const node = document.getElementById("sweepNote");
    return { text: node.textContent, title: node.title };
  });
  check("a failed sweep reads Sweep failed in the header", said.text === "Sweep failed", JSON.stringify(said));
  check("and its title says when the next one runs", /next one runs in 2m/.test(said.title), said.title);
  await context.close();
}

/* The office's own list: it has to draw, and pressing the button has to cost one read. The
   pane used to ask for the conversation and the list in turn, each dropping the other from the
   tick, which is six grey bars forever and two hundred reads of the office a second. */
{
  const { page, context, thrown, asked } = await open({ hash: "#/mail?to=winston" });
  const before = asked.length;
  await page.click("[data-timeline]");
  await page.waitForTimeout(2500);
  const rows = await page.evaluate(() => document.querySelectorAll(".feed .item").length);
  const since = asked.slice(before);
  const feed = since.filter((url) => url.includes("/api/mail/feed")).length;
  const thread = since.filter((url) => url.includes("/api/mail/thread")).length;
  check("everything the office did draws its rows", rows > 0, `${rows} rows`);
  check("pressing it reads the office once and never loops",
    feed === 1 && thread === 0, `${feed} reads of the list, ${thread} of the conversation`);
  check("the office's list throws nothing", thrown.length === 0, thrown[0]);
  const skeletons = await page.evaluate(() => document.querySelectorAll(".thread .skeleton").length);
  check("and it is not still loading", skeletons === 0, `${skeletons} grey bars`);
  await context.close();
}

/* ------------------------------------------------------- how much the mail asks for */

{
  const seen = {};
  for (let index = 0; index < 20; index += 1) seen[`name${index}`] = new Date(Date.now() - 86400000).toISOString();
  const boxes = Object.keys(seen).map((name, index) => ({
    name, number: index, updated_at: Date.now() / 1000, count_24h: 3, last_at: Date.now() / 1000,
  }));
  const { page, context, asked } = await open({
    hash: "#/mail",
    seed: { "murmur.mail.seen": JSON.stringify(seen) },
    overrides: {
      "/api/mail/boxes": JSON.stringify({ at: Date.now() / 1000, stale_since: null, error: null, boxes }),
    },
  });
  await page.waitForTimeout(2500);
  const threads = asked.filter((url) => url.includes("/api/mail/thread"));
  const distinct = new Set(threads.map((url) => new URL(url).searchParams.get("box")));
  check("mail reads one conversation, the one on screen", distinct.size <= 1, `${distinct.size} names, ${threads.length} requests`);
  await context.close();
}

/* ------------------------------------------------------- a list nobody meant to be this long */

{
  const many = Array.from({ length: 400 }, (unused, index) => ({
    slug: `lane-${index}`, project: "demo", lane: "web", status: "running",
    started_at: Math.floor(Date.now() / 1000) - index,
  }));
  const { page, context } = await open({
    hash: "#/board",
    overrides: { "/api/fleet": JSON.stringify(many) },
  });
  const first = await page.evaluate(() => document.querySelectorAll("[data-agent-card]").length);
  check("a very long list is drawn a screenful at a time", first > 0 && first < 400, String(first));
  const button = await page.evaluate(() => {
    const node = [...document.querySelectorAll("button")].find((candidate) => /Show the other/.test(candidate.textContent));
    if (node) node.click();
    return Boolean(node);
  });
  await page.waitForTimeout(900);
  const all = await page.evaluate(() => document.querySelectorAll("[data-agent-card]").length);
  check("the reader can ask for the rest", button && all === 400, `${all} after asking`);
  await context.close();
}

/* ------------------------------------------------------------ a lane that dropped work */

{
  const { page, context } = await open({ hash: "#/board" });
  const chip = await page.evaluate(() => {
    const card = document.querySelector('[data-agent-card="storefront-checkout-77c1"]');
    const tag = card && card.querySelector("[data-scope-dropped]");
    return tag ? tag.textContent : "";
  });
  check("a lane that dropped part of its scope says so on its card",
    chip === "scope dropped: 1842, 1843", chip);
  await page.click('[data-agent-card="storefront-checkout-77c1"]');
  await page.waitForTimeout(1200);
  const drawer = await page.evaluate(() => {
    const keys = [...document.querySelectorAll("#drawerBody dt")];
    const key = keys.find((node) => node.textContent === "Scope dropped");
    return key ? key.nextElementSibling.textContent : "";
  });
  check("and the drawer says which parts", drawer === "1842, 1843", drawer);
  await context.close();
}

/* ------------------------------------------------------- the palette, from every tab */

for (const [hash, name] of [["#/mail", "mail"], ["#/queue", "queue"], ["#/machine", "machine"]]) {
  const { page, context, thrown } = await open({ hash });
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(400);
  await page.fill("#paletteInput", "demo-api");
  await page.waitForTimeout(900);
  const rows = await page.evaluate(() => [...document.querySelectorAll("#paletteList li")].map((node) => node.textContent));
  check(`${name}: the palette offers a lane from a tab that never read the lanes`,
    rows.some((row) => row.includes("demo-api-3f2a")), rows.join(" | "));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(700);
  const where = await page.evaluate(() => location.hash);
  check(`${name}: Enter lands on the lane that was typed`,
    where.includes("board") && where.includes("agent=demo-api-3f2a"), where);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(400);
  await page.fill("#paletteInput", "rubicon");
  await page.waitForTimeout(900);
  const names = await page.evaluate(() => [...document.querySelectorAll("#paletteList li")].map((node) => node.textContent));
  check(`${name}: the palette offers a conversation too`, names.some((row) => row.includes("Conversation")), names.join(" | "));
  check(`${name}: opening the palette breaks nothing`, thrown.length === 0, thrown[0]);
  await context.close();
}

/* ----------------------------------------------------- a subscription with no numbers */

{
  const { page, context, thrown } = await open({
    hash: "#/board",
    overrides: {
      "/api/accounts": JSON.stringify({
        at: Date.now() / 1000,
        accounts: [
          { name: "farm-one", label: "farm one", engine: "claude", read_at: null,
            session: null, weekly: null, scoped: [],
            stale_error: "This account has no login on the farm yet." },
          { name: "farm-two", label: "farm two", engine: "claude", read_at: Date.now() / 1000 - 900,
            session: 100, weekly: 71, scoped: [], limit_reached: true },
          { name: "farm-three", label: "farm three", email: "farm.three@example.com", engine: "claude",
            read_at: Date.now() / 1000 - 60, session: 2, weekly: 88,
            scoped: [{ label: "Fable", percent: 100, active: true, resets: "2026-09-26T14:00:00Z" }] },
        ],
        errors: {},
      }),
    },
  });
  const body = await text(page);
  const red = await page.evaluate(() => {
    const card = document.querySelector('[data-account="farm-two"]');
    return card ? { out: card.classList.contains("out"), text: card.innerText.replace(/\s+/g, " ") } : null;
  });
  check("a subscription with no numbers says so in words",
    /No numbers yet/.test(body), body.replace(/\s+/g, " ").slice(0, 160));
  check("a subscription with nothing left is red and says so",
    red && red.out && /Out of room/.test(red.text), JSON.stringify(red));
  const fable = await page.evaluate(() => {
    const card = document.querySelector('[data-account="farm-three"]');
    return card ? { out: card.classList.contains("out"), text: card.innerText.replace(/\s+/g, " "),
      bars: card.querySelectorAll(".limit").length, title: card.getAttribute("title") || "" } : null;
  });
  check("an account with only Fable spent is not out of room, and says what is spent",
    fable && !fable.out && /Fable used up/.test(fable.text) && !/Out of room/.test(fable.text),
    JSON.stringify(fable));
  check("the card shows every window, the Fable one included",
    fable && fable.bars === 3 && /Fable/.test(fable.text), JSON.stringify(fable));
  check("the card says whose login it is",
    fable && /farm\.three@example\.com/.test(fable.title), JSON.stringify(fable));
  check("no card prints an exception or a path",
    !/Error:|Errno|\/private\/|\/home\//.test(body), body.slice(0, 200));
  check("a subscription card with nothing to report breaks nothing", thrown.length === 0, thrown[0]);
  await page.click('[data-account="farm-two"]');
  await page.waitForTimeout(600);
  const where = await page.evaluate(() => location.hash);
  check("and pressing it opens the machine tab at the accounts section",
    where.includes("machine") && where.includes("section=accounts"), where);
  await context.close();
}

/* ------------------------------------------------- what the server said about a refusal */

{
  const said = "that lane is not running any more";
  const { page, context } = await open({
    hash: "#/board?agent=demo-api-3f2a",
    overrides: {
      "/api/agent/msg": (handler) => handler.fulfill({
        status: 400, contentType: "application/json", body: JSON.stringify({ error: said }),
      }),
    },
  });
  await page.fill("#laneMessage", "look at the orders screen");
  await page.evaluate(() => [...document.querySelectorAll("#drawerBody button")].find((node) => node.textContent === "Send").click());
  await page.waitForTimeout(1000);
  const toast = await page.evaluate(() => [...document.querySelectorAll(".toast")].map((node) => node.textContent).join(" | "));
  check("a refused message to a lane shows the reason the server gave", toast.includes(said), toast);
  await context.close();
}

/* ------------------------------------------------------------------- the mail, in use */

{
  const sent = [];
  const { page, context, thrown } = await open({
    hash: "#/mail",
    overrides: {
      "/api/mail/send": (handler) => {
        sent.push(JSON.parse(handler.request().postData() || "{}"));
        return handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, to: "all", from: "dashboard" }) });
      },
    },
  });
  const label = await page.evaluate(() => document.querySelector(".composer-label").textContent);
  check("the composer says who the message goes to", label === "Message to Everyone", label);
  const under = await page.evaluate(() => document.querySelector(".composer .readonly-note").textContent);
  check("and that it is not sent as the reader", under === "Sent as dashboard, not as you", under);
  await page.fill("#mailText", "the search lane is done");
  await page.click("#mailSend");
  await page.waitForTimeout(1200);
  const echo = await page.evaluate(() => {
    const row = document.querySelector("[data-echo]");
    return row ? { state: row.dataset.echo, text: row.innerText.replace(/\s+/g, " ") } : null;
  });
  check("a sent message appears at once and says where it is",
    echo && echo.state === "sent" && /sent, it will show here at the next refresh/.test(echo.text),
    JSON.stringify(echo));
  check("and it went to the conversation on screen", sent.length === 1 && sent[0].to === "all", JSON.stringify(sent));
  check("sending breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open({
    hash: "#/mail",
    overrides: {
      "/api/mail/send": (handler) => handler.fulfill({
        status: 503, contentType: "application/json", body: JSON.stringify({ error: "the office is still being read" }),
      }),
    },
  });
  await page.fill("#mailText", "a sentence the reader does not want to type twice");
  await page.click("#mailSend");
  await page.waitForTimeout(1200);
  const after = await page.evaluate(() => ({
    kept: document.getElementById("mailText").value,
    toast: document.getElementById("toasts").innerText,
    echoes: document.querySelectorAll("[data-echo]").length,
  }));
  check("a message the office refused is left in the box for another try",
    after.kept === "a sentence the reader does not want to type twice" && after.echoes === 0, JSON.stringify(after));
  check("and the refusal is said in the server's words", /still being read/.test(after.toast), after.toast);
  await context.close();
}

/* The panes are fixed and the page under them does not move, however long the conversation. */

{
  const now = Date.now() / 1000;
  const many = Array.from({ length: 120 }, (unused, index) => ({
    sender: index % 2 ? "winston" : "rubicon",
    at: `${index}m ago`, created_at: now - index * 60,
    text: `line ${index}: something that was said about the orders screen and the checkout lane`,
  })).reverse();
  const { page, context } = await open({
    hash: "#/mail",
    overrides: {
      "/api/mail/thread": JSON.stringify({
        at: new Date().toISOString(), stale_since: null, error: null, pending: null,
        box: "all", window_hours: 72, messages: many,
      }),
    },
  });
  const seen = await page.evaluate(() => ({
    pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 1,
    threadScrolls: (() => {
      const pane = document.querySelector(".thread-pane .pane-scroll");
      return pane.scrollHeight > pane.clientHeight + 1;
    })(),
    composerInView: (() => {
      const box = document.querySelector(".composer").getBoundingClientRect();
      return box.bottom <= window.innerHeight + 1;
    })(),
    days: document.querySelectorAll(".thread .day").length,
  }));
  check("a long conversation scrolls inside its own pane, not the page",
    !seen.pageScrolls && seen.threadScrolls, JSON.stringify(seen));
  const bottom = await page.evaluate(() => {
    const pane = document.querySelector(".thread-pane .pane-scroll");
    return { left: pane.scrollHeight - pane.scrollTop - pane.clientHeight, height: pane.scrollHeight };
  });
  check("and it opens at the newest message, not the oldest", bottom.left < 48, JSON.stringify(bottom));
  check("the composer stays on the screen under it", seen.composerInView, JSON.stringify(seen));
  check("the messages are separated by day", seen.days > 0, String(seen.days));
  await context.close();
}

/* Twenty five code names is what a real office holds, and two of the records carry one name. */

{
  const now = Date.now() / 1000;
  const names = ["all", "winston", "winston", ...Array.from({ length: 22 }, (_unused, index) => `agent-${index}`)];
  const boxes = names.map((name, index) => ({
    name, number: 100 - index, updated_at: now - index * 600,
    count_24h: 1, last_at: now - index * 600,
  }));
  const { page, context, thrown } = await open({
    hash: "#/mail",
    overrides: { "/api/mail/boxes": JSON.stringify({ at: new Date().toISOString(), stale_since: null, error: null, pending: null, boxes }) },
  });
  const read = () => page.evaluate(() => ({
    names: [...document.querySelectorAll(".conversations li")].map((node) => node.dataset.conversation),
    first: document.querySelector(".conversations li .name").textContent,
    button: document.querySelector(".pane-more button") ? document.querySelector(".pane-more button").textContent : "",
  }));
  const first = await read();
  check("one name is one conversation however many records carry it",
    first.names.filter((name) => name === "winston").length === 1, first.names.join(", "));
  check("a long office list stops at twelve and offers the rest",
    first.names.length === 12 && first.button === "Show all 24", `${first.names.length} rows, button ${first.button}`);
  check("the conversation everybody reads is first and is called Everyone",
    first.names[0] === "all" && first.first === "Everyone", `${first.names[0]} / ${first.first}`);
  await page.click(".pane-more button");
  await page.waitForTimeout(400);
  const all = await read();
  check("asking for the rest shows them", all.names.length === 24 && all.button === "Show fewer",
    `${all.names.length} rows, button ${all.button}`);
  check("a long office list threw nothing", thrown.length === 0, thrown.join(" | "));
  await context.close();
}

/* The people pane and the conversation list give way on a small screen, per amendment 17. */

{
  const { page, context } = await open({ hash: "#/mail", size: { width: 1000, height: 800 } });
  const narrow = await page.evaluate(() => ({
    people: getComputedStyle(document.querySelector(".people-pane")).display,
    count: document.querySelector(".people-count") ? document.querySelector(".people-count").textContent : "",
    countShown: document.querySelector(".people-count") && getComputedStyle(document.querySelector(".people-count")).display !== "none",
  }));
  check("under 1100 px the people pane is a count in the thread header",
    narrow.people === "none" && narrow.countShown && /^Agents \(\d\)$/.test(narrow.count), JSON.stringify(narrow));
  await page.click(".people-count");
  await page.waitForTimeout(400);
  const opened = await page.evaluate(() => getComputedStyle(document.querySelector(".people-pane")).display);
  check("and pressing the count shows the people", opened !== "none", opened);
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/mail", size: { width: 700, height: 800 } });
  const phone = await page.evaluate(() => ({
    list: getComputedStyle(document.querySelector(".conversations-pane")).display,
    pick: getComputedStyle(document.querySelector(".convo-select")).display,
    options: document.querySelectorAll(".convo-select option").length,
    pageScrolls: document.documentElement.scrollHeight > window.innerHeight + 1,
  }));
  check("under 800 px the conversations become a select above the thread",
    phone.list === "none" && phone.pick !== "none" && phone.options > 0, JSON.stringify(phone));
  check("and the page still does not scroll", !phone.pageScrolls, JSON.stringify(phone));
  await context.close();
}

/* ------------------------------------------------------------------ the freshness label */

{
  const { page, context } = await open({
    hash: "#/board",
    overrides: { "/api/fleet": (handler) => handler.fulfill({ status: 500, contentType: "application/json", body: '{"error":"the state directory is gone"}' }) },
  });
  const label = await page.evaluate(() => document.getElementById("freshness").textContent);
  check("one dead route is enough to stop saying live", /Stale/.test(label), label);
  await context.close();
}

{
  const since = new Date(Date.now() - 300000).toISOString().replace(/\.\d+Z$/, "Z");
  const { page, context } = await open({
    hash: "#/mail",
    overrides: {
      "/api/mail/boxes": JSON.stringify({
        at: since, stale_since: since, error: "gh could not reach github.com", pending: null,
        boxes: [{ name: "all", number: 1, updated_at: Date.now() / 1000 - 600, count_24h: 9, last_at: Date.now() / 1000 - 600 }],
      }),
    },
  });
  const seen = await page.evaluate(() => ({
    label: document.getElementById("freshness").textContent,
    why: document.getElementById("freshness").title,
    stale: document.getElementById("freshness").classList.contains("stale"),
    rows: document.querySelectorAll(".conversations li").length,
  }));
  check("a kept answer from the office stops the header saying live", /^Stale since /.test(seen.label), seen.label);
  check("the header says on hover which route is old and why",
    seen.why.includes("/api/mail/boxes") && seen.why.includes("github.com"), seen.why);
  // Nothing here failed: the request worked, the answer itself said it was a kept copy.
  check("the header is marked old even though every request worked",
    seen.stale && seen.rows > 0, JSON.stringify(seen));
  await context.close();
}

{
  const { page, context } = await open({
    hash: "#/mail",
    overrides: {
      "/api/mail/who": JSON.stringify({
        at: new Date().toISOString(), stale_since: new Date(Date.now() - 360000).toISOString(),
        error: null, pending: null,
        sessions: [{ name: "winston", state: "live", age_hours: 0.2, since: null, task: "the orders screen" }],
      }),
    },
  });
  const said = await page.evaluate(() => document.querySelector(".people-pane").innerText.replace(/\s+/g, " "));
  check("an old reading of the office says so in the reader's words",
    /The office last answered \d/.test(said), said.slice(0, 120));
  // Nothing in the Agents pane is a message, so the sentence over it says what it is about.
  check("and the sentence over a list of agents is about agents",
    /agents it knew about then/.test(said) && !/message/i.test(said), said.slice(0, 160));
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/board" });
  const label = await page.evaluate(() => {
    const node = document.getElementById("freshness");
    return { text: node.textContent, title: node.title, hidden: node.hidden };
  });
  check("nothing old and nothing failing says nothing, with the time on its title",
    label.text === "" && label.hidden && /as of /.test(label.title), JSON.stringify(label));
  await context.close();
}

await browser.close();
stub.kill();
const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

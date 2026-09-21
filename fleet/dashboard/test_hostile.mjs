/* What the page does when a route lies to it. Every case here overrides one route with a shape
   the server should never send, and asks two questions: did anything throw, and did the reader
   get told. A dashboard that draws half a screen and keeps saying "Live" is worse than one that
   says it cannot read the answer. The keyboard and the header cases live here too, because they
   are the same kind of question: can a person still use the page. */

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

/** One page, with the routes named in `overrides` answered by this test instead of the stub. */
async function open({ hash = "#/overview", size = { width: 1440, height: 900 }, overrides = {}, seed = null }) {
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
  ["/api/metrics", "#/system", "system"],
  ["/api/accounts", "#/accounts", "accounts"],
  ["/api/fleet", "#/agents", "agents"],
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

for (const [route, hash, name] of [
  ["/api/fleet", "#/agents", "agents"],
  ["/api/fleet", "#/overview", "overview"],
  ["/api/projects", "#/projects", "projects"],
]) {
  const { page, context, thrown } = await open({
    hash,
    overrides: { [route]: JSON.stringify({ unavailable: "The farm state directory is not readable.", fix: "fleet doctor" }) },
  });
  const body = await text(page);
  check(`${name}: a route that answers "unavailable" does not break the tab`, thrown.length === 0, thrown[0]);
  check(`${name}: the sentence and its command are shown`, body.includes("not readable") && body.includes("fleet doctor"), body.slice(0, 80));
  await context.close();
}

{
  const { page, context, thrown } = await open({
    hash: "#/projects",
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
    hash: "#/agents",
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
    hash: "#/agents",
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
    hash: "#/agents?agent=demo-web-91bd",
    overrides: {
      "/api/agent": JSON.stringify({
        slug: "demo-web-91bd", project: "demo", lane: "web", status: "pr_open",
        started_at: Math.floor(Date.now() / 1000) - 600,
        pr_url: "javascript:window.__pwn=1;void 0",
      }),
    },
  });
  const hrefs = await page.evaluate(() => [...document.querySelectorAll("#drawerBody a")].map((node) => node.getAttribute("href")));
  check("a link that is not http is never rendered as a link", !hrefs.some((href) => /^javascript:/i.test(href)), JSON.stringify(hrefs));
  const shown = await page.evaluate(() => document.getElementById("drawerBody").innerText);
  check("the address is still shown as text", shown.includes("javascript:window.__pwn"), shown.slice(0, 60));
  await context.close();
}

/* -------------------------------------------------------------- the four states, everywhere */

{
  const { page, context } = await open({
    hash: "#/overview",
    overrides: { "/api/fleet": (handler) => new Promise(() => { /* never answers */ }) },
  });
  const card = await page.evaluate(() => {
    const heads = [...document.querySelectorAll(".card")];
    const agents = heads.find((node) => /^Agents/.test(node.innerText));
    return agents ? { text: agents.innerText, skeletons: agents.querySelectorAll(".skeleton").length } : null;
  });
  check("the agents card shows a skeleton, not four zeros", card && card.skeletons > 0, JSON.stringify(card));
  await context.close();
}

/* -------------------------------------------------------- a name nobody thought to bound */

{
  const long = "lane-".concat("x".repeat(660));
  const { page, context, thrown } = await open({
    hash: `#/agents?agent=${long}`,
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
    hash: "#/agents",
    overrides: { "/api/fleet": JSON.stringify([{ slug: null, project: "demo", status: "running", started_at: 1 }]) },
  });
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(300);
  await page.keyboard.type("age");
  await page.waitForTimeout(400);
  const options = await page.evaluate(() => document.getElementById("paletteList").children.length);
  check("a nameless lane does not kill the jump palette", thrown.length === 0, thrown[0]);
  check("the palette still filters", options > 0, String(options));
  await context.close();
}

/* --------------------------------------------------------------------------- the keyboard */

{
  const { page, context } = await open({ hash: "#/agents" });
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

  const sortable = await page.evaluate(() => {
    const table = [...document.querySelectorAll(".segmented button")].find((node) => node.textContent === "Table");
    if (table) table.click();
    return true;
  });
  await page.waitForTimeout(500);
  const rows = await page.evaluate(() => ({
    header: Boolean(document.querySelector("thead th button")),
    row: document.querySelector("tbody tr") && document.querySelector("tbody tr").getAttribute("tabindex"),
  }));
  check("a sortable column is a button", rows.header, JSON.stringify(rows));
  check("a table row can take focus", rows.row === "0", JSON.stringify(rows));
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/mail" });
  const boxes = await page.evaluate(() => ({
    listbox: document.querySelector(".boxlist") && document.querySelector(".boxlist").getAttribute("role"),
    option: document.querySelector(".boxlist li") && document.querySelector(".boxlist li").getAttribute("tabindex"),
  }));
  check("the mailbox list is a listbox", boxes.listbox === "listbox", JSON.stringify(boxes));
  check("a mailbox can take focus", boxes.option === "0", JSON.stringify(boxes));
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/agents" });
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(400);
  const before = await page.evaluate(() => {
    const input = document.getElementById("paletteInput");
    return {
      role: input.getAttribute("role"),
      controls: input.getAttribute("aria-controls"),
      label: input.getAttribute("aria-label"),
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

/* ------------------------------------------------------------------- the reader's own eyes */

{
  const { page, context } = await open({ hash: "#/agents", size: { width: 390, height: 844 } });
  const header = await page.evaluate(() => {
    const bar = document.getElementById("topbar");
    const right = document.querySelector(".top-right");
    return {
      bar: bar.scrollWidth <= bar.clientWidth + 1,
      right: right.scrollWidth <= right.clientWidth + 1,
      wide: right.scrollWidth,
      room: right.clientWidth,
    };
  });
  check("the header fits on a phone", header.bar && header.right, JSON.stringify(header));
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
  const { page, context } = await open({ hash: "#/agents" });
  const words = await page.evaluate(() => [...document.querySelectorAll(".agent-card .pill-text")].map((node) => node.textContent));
  check("there are five status words and no sixth", !words.includes("Unreadable"), words.join(" | "));
  const detail = await page.evaluate(() => document.getElementById("view").innerText);
  check("an unreadable record says so as a detail", /record unreadable/i.test(detail));
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/overview" });
  const said = await page.evaluate(() => {
    const cards = [...document.querySelectorAll(".card")];
    const mail = cards.find((node) => /^Last said/.test(node.innerText));
    return mail ? mail.innerText : "";
  });
  check("the last said list shows messages, not housekeeping", said.length > 0 && !said.includes("snapshot was refreshed"), said.slice(0, 120));
  await context.close();
}

/* -------------------------------------------------------------------- how much it asks for */

{
  const seen = {};
  for (let index = 0; index < 20; index += 1) seen[`box${index}`] = new Date(Date.now() - 86400000).toISOString();
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
  check("mail reads one thread, the one on screen", distinct.size <= 1, `${distinct.size} boxes, ${threads.length} requests`);
  await context.close();
}

/* ------------------------------------------------------- a list nobody meant to be this long */

{
  const many = Array.from({ length: 400 }, (unused, index) => ({
    slug: `lane-${index}`, project: "demo", lane: "web", status: "running",
    started_at: Math.floor(Date.now() / 1000) - index,
  }));
  const { page, context } = await open({
    hash: "#/agents",
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

/* ------------------------------------------------------------------ the freshness label */

{
  const { page, context } = await open({
    hash: "#/agents",
    overrides: { "/api/fleet": (handler) => handler.fulfill({ status: 500, contentType: "application/json", body: '{"error":"the state directory is gone"}' }) },
  });
  const label = await page.evaluate(() => document.getElementById("freshness").textContent);
  check("one dead route is enough to stop saying live", /Stale/.test(label), label);
  await context.close();
}

await browser.close();
stub.kill();
const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

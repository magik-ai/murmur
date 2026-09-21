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

/* A panel that is drawn before its answer arrives has TWO shapes under one key: a grey
   placeholder and the value that replaces it. The live farm showed both at once, four grey
   rows sitting above the four numbers they were standing in for. */

{
  const late = JSON.stringify([
    { slug: "a", project: "demo", lane: "web", status: "running", started_at: 1, updated_at: 1 },
    { slug: "b", project: "demo", lane: "api", status: "failed", started_at: 1, updated_at: 1 },
  ]);
  const { page, context } = await open({
    hash: "#/overview",
    overrides: {
      "/api/fleet": (handler) => setTimeout(() => handler.fulfill({
        status: 200, contentType: "application/json", body: late,
      }), 1000),
    },
  });
  const card = await page.evaluate(() => {
    const agents = [...document.querySelectorAll(".card")].find((node) => /^Agents/.test(node.innerText));
    return agents ? { text: agents.innerText, skeletons: agents.querySelectorAll(".skeleton").length } : null;
  });
  check("the skeleton is replaced by the numbers, not left above them",
    card && card.skeletons === 0 && /Running\n1/.test(card.text), JSON.stringify(card));
  await context.close();
}

/* A queue with nothing running and nothing waiting is a state, not a gap. It used to be the
   one shape that left the overview card on its placeholder with nothing to read. */

{
  const finished = [0, 1, 2].map((index) => ({
    id: `ci-${index}`, project: "demo", pr: 400 + index, branch: `demo/change-${index}`,
    state: "passed", started: 1, ended: 2, tiers: [],
  }));
  const { page, context, thrown } = await open({
    hash: "#/overview",
    overrides: {
      "/api/ci": JSON.stringify({ updated: 1, daemon_alive: true, running: [], queued: [], recent: finished }),
    },
  });
  const card = await page.evaluate(() => {
    const queue = [...document.querySelectorAll(".card")].find((node) => /^Queue/.test(node.innerText));
    return queue ? { text: queue.innerText, skeletons: queue.querySelectorAll(".skeleton").length,
      open: Boolean(queue.querySelector('a[href="#/queue"]')) } : null;
  });
  check("an empty queue says so, counts what finished, and keeps its way in",
    card && card.skeletons === 0 && card.open
      && /Nothing is being verified right now/.test(card.text)
      && /3 finished runs/.test(card.text), JSON.stringify(card));
  check("an empty queue threw nothing", thrown.length === 0, thrown.join(" | "));
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

/* ------------------------------------------------------------ a lane that dropped work */

{
  const { page, context } = await open({ hash: "#/agents" });
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

for (const [hash, name] of [["#/system", "system"], ["#/projects", "projects"], ["#/accounts", "accounts"]]) {
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
  check(`${name}: Enter lands on the lane that was typed`, where.includes("agent=demo-api-3f2a"), where);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+k");
  await page.waitForTimeout(400);
  await page.fill("#paletteInput", "rubicon");
  await page.waitForTimeout(900);
  const boxes = await page.evaluate(() => [...document.querySelectorAll("#paletteList li")].map((node) => node.textContent));
  check(`${name}: the palette offers a mailbox too`, boxes.some((row) => row.includes("Mailbox")), boxes.join(" | "));
  check(`${name}: opening the palette breaks nothing`, thrown.length === 0, thrown[0]);
  await context.close();
}

/* ----------------------------------------------------- a subscription with no numbers */

{
  const { page, context, thrown } = await open({
    hash: "#/accounts",
    overrides: {
      "/api/accounts": JSON.stringify({
        at: Date.now() / 1000,
        accounts: [
          { name: "farm-one", label: "farm one", engine: "claude", read_at: null,
            session: null, weekly: null, scoped: [],
            stale_error: "This account has no login on the farm yet. Log in once: ssh -t farm claude" },
          { name: "farm-two", label: "farm two", engine: "claude", read_at: Date.now() / 1000 - 900,
            session: 42, weekly: 71, scoped: [],
            stale_error: "The vendor did not answer the last time the farm asked." },
          { name: "codex", label: "codex", engine: "codex", read_at: null,
            session: 30, weekly: null, scoped: [],
            stale_error: "The login on this account has expired. Log in again." },
        ],
        errors: {},
      }),
    },
  });
  const body = await text(page);
  check("a card with no numbers says so in words", /No numbers yet\. This account has no login on the farm yet\./.test(body), body.slice(0, 200));
  check("a kept reading says when it was last true",
    /These numbers are as of 15m ago and have not refreshed\. The vendor did not answer/.test(body));
  check("a card with no time never writes one",
    /These numbers have not refreshed\. The login on this account has expired\./.test(body));
  check("no card ever says \"from not known\"", !/from not known/.test(body));
  check("no card prints an exception or a path",
    !/Error:|Errno|\/private\/|\/home\//.test(body), body.slice(0, 200));
  check("a card with nothing to report breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

/* --------------------------------------------------------------- switching an engine */

{
  const writes = [];
  const { page, context, thrown } = await open({
    hash: "#/accounts",
    overrides: {
      "/api/models": (handler) => {
        const request = handler.request();
        if (request.method() !== "POST") return handler.continue();
        writes.push(JSON.parse(request.postData() || "{}"));
        return handler.fulfill({
          status: 200, contentType: "application/json",
          body: JSON.stringify({ model: { id: "codex" }, error: null }),
        });
      },
    },
  });
  const controls = await page.evaluate(() => ({
    switches: document.querySelectorAll("[data-engine-switch]").length,
    tests: document.querySelectorAll("[data-engine-test]").length,
    word: (document.querySelector('[data-engine-switch="codex"]') || {}).textContent || "",
  }));
  check("every engine card carries a switch and a test",
    controls.switches === 3 && controls.tests === 3, JSON.stringify(controls));
  check("the switch says what pressing it does", controls.word === "Switch off", controls.word);
  await page.click('[data-engine-switch="codex"]');
  await page.waitForTimeout(1000);
  check("switching an engine off posts the action the server understands",
    writes.some((row) => row.action === "disable" && row.id === "codex"), JSON.stringify(writes));
  await page.click('[data-engine-test="codex"]');
  await page.waitForTimeout(1000);
  check("the test button asks the server to try that engine",
    writes.some((row) => row.action === "test" && row.id === "codex"), JSON.stringify(writes));
  check("the engine controls break nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open({
    hash: "#/accounts",
    overrides: {
      "/api/access": JSON.stringify({ writable: false, reason: "This page was opened without the dashboard token.", token_required: true, loopback: false }),
    },
  });
  const off = await page.evaluate(() => [...document.querySelectorAll("[data-engine-switch], [data-engine-test]")]
    .every((node) => node.disabled));
  check("a reader who cannot write cannot switch an engine", off);
  await context.close();
}

/* ------------------------------------------------------- what the server said about a refusal */

{
  const said = "a repository is owner/name";
  const { page, context, thrown } = await open({
    hash: "#/projects",
    overrides: {
      "/api/projects": (handler) => (handler.request().method() === "POST"
        ? handler.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: said }) })
        : handler.continue()),
    },
  });
  await page.fill("#projectName", "broken");
  await page.fill("#projectRepo", "not a repository");
  await page.evaluate(() => [...document.querySelectorAll("button")].find((node) => node.textContent === "Add").click());
  await page.waitForTimeout(1200);
  const shown = await page.evaluate(() => [...document.querySelectorAll(".readonly-note")].map((node) => node.textContent).join(" | "));
  check("a refused project shows the reason the server gave", shown.includes(said), shown);
  check("a refused project breaks nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const said = "that lane is not running any more";
  const { page, context } = await open({
    hash: "#/agents?agent=demo-api-3f2a",
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

/* Twenty five code names is what a real office holds, and two of the issues carry one name.
   The list has to be one row per name, newest first, and short enough to read. */

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
    names: [...document.querySelectorAll(".boxlist li span:first-child")].map((node) => node.textContent),
    button: document.querySelector(".boxlist-more button") ? document.querySelector(".boxlist-more button").textContent : "",
  }));
  const first = await read();
  check("one name is one mailbox however many issues carry it",
    first.names.filter((name) => name === "winston").length === 1, first.names.join(", "));
  check("a long office list stops at twelve and offers the rest",
    first.names.length === 12 && first.button === "Show all 24", `${first.names.length} rows, button ${first.button}`);
  check("the box everybody reads is first", first.names[0] === "all", first.names.slice(0, 3).join(", "));
  await page.click(".boxlist-more button");
  await page.waitForTimeout(400);
  const all = await read();
  check("asking for the rest shows them", all.names.length === 24 && all.button === "Show fewer",
    `${all.names.length} rows, button ${all.button}`);
  check("a long office list threw nothing", thrown.length === 0, thrown.join(" | "));
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
    boxes: document.querySelectorAll(".boxlist li").length,
  }));
  check("a kept answer from the office stops the header saying live", /^Stale since /.test(seen.label), seen.label);
  check("the header says on hover which route is old and why",
    seen.why.includes("/api/mail/boxes") && seen.why.includes("github.com"), seen.why);
  // Nothing here failed: the request worked, the answer itself said it was a kept copy.
  check("the header is marked old even though every request worked",
    seen.stale && seen.boxes > 0, JSON.stringify(seen));
  await context.close();
}

{
  const { page, context } = await open({ hash: "#/agents" });
  const label = await page.evaluate(() => document.getElementById("freshness").textContent);
  check("nothing old and nothing failing still reads live", /^Live, as of /.test(label), label);
  await context.close();
}

await browser.close();
stub.kill();
const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

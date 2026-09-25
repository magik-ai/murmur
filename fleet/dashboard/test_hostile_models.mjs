/* What the Models section does when a route lies to it, when the page may not write, and when a
   request fails halfway: the providers table, a provider's sidebar with its one list of models,
   and the add-a-provider dialog. Every case asks the same two questions: did anything throw,
   and was the reader told.

   Nothing here reaches a provider or the live farm. The stub next to this file answers every
   route, stub_models.py answers the two model routes from lists written in it, and the routes a
   case needs to hold, fail or lie are answered by the case itself.

   The view is opened through the stub's harness page, the same shell around the same modules
   that index.html puts it in. */

import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./test_playwright.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 7979);
const BASE = `http://127.0.0.1:${PORT}`;
const ONLY = process.env.ONLY || "";

const results = [];
function check(name, passed, detail) {
  if (ONLY && !name.includes(ONLY)) return;
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
}

/* A port that is already taken is the one way these checks can go green against a page nobody
   here wrote: another worktree's stub answers, and every reading is about its tree. */
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
  env: { ...process.env, STUB_JOB_SECONDS: "2", STUB_ADD_LOGIN_SECONDS: "2" },
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

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** One harness page, with the routes named in `overrides` answered by this test. */
async function open({ view = "machine", state = "ready", size = { width: 1440, height: 1000 },
  overrides = {} } = {}) {
  const context = await browser.newContext({ viewport: size });
  const page = await context.newPage();
  const thrown = [];
  const posted = [];
  const sent = [];
  const pulled = [];
  page.on("pageerror", (error) => thrown.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "POST") {
      posted.push(request.url());
      sent.push({ url: request.url(), body: request.postData() || "" });
      return;
    }
    if (request.method() === "GET") pulled.push(request.url());
  });
  for (const [route, body] of Object.entries(overrides)) {
    await page.route((url) => url.pathname === route, (handler) => {
      if (typeof body === "function") return body(handler);
      return handler.fulfill({ status: 200, contentType: "application/json", body });
    });
  }
  await page.goto(`${BASE}/harness?state=${state}#/${view}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1600);
  return { page, context, thrown, posted, sent, pulled };
}

const text = (page) => page.evaluate(() => document.getElementById("view").innerText);

const READ_ONLY = JSON.stringify({
  writable: false,
  reason: "This page was opened without the dashboard token, so it can only read.",
  token_required: true,
  loopback: true,
});

/* The bodies one route was sent, parsed. */
function bodies(sent, route) {
  return sent.filter((row) => new URL(row.url).pathname === route)
    .map((row) => JSON.parse(row.body || "{}"));
}

/* Two bodies are the same when they carry the same fields with the same values. */
function same(one, two) {
  const sorted = (value) => JSON.stringify(value, Object.keys(value || {}).sort());
  return sorted(one) === sorted(two);
}

/* The catalog as a server of section 6 answers it: every row carries `models_on` and
   `default_model`. Built from the stub's own rows, read before any case writes to them, so the
   two model routes and this answer agree about which provider is which. demo-strict's run line
   takes a model here, so its sidebar reaches the request that fails; demo-plain's does not, so
   its sidebar draws the sentence of a provider that cannot take one. Both are rows of the
   stub's fictional contributed presets: murmur ships no such engine. */
const STUB_ROWS = await (await fetch(`${BASE}/api/engines`)).json();
const CONTRACT = {
  claude: { models_on: ["opus", "sonnet"], default_model: "opus" },
  codex: { models_on: ["gpt-6-sol"], default_model: "gpt-6-sol" },
  "demo-plain": { models_on: [], default_model: "" },
  "demo-strict": { models_on: [], default_model: "", run: "{bin} -m {variant} -p {task}" },
  local: { models_on: [], default_model: "" },
};
function engines(changes = {}) {
  return JSON.stringify(STUB_ROWS.map((row) => ({
    ...row, ...(CONTRACT[row.id] || {}), ...(changes[row.id] || {}),
  })));
}

/* A select the stub would answer, recorded by the page's own request log and answered here,
   so a case can send as many as it likes without rewriting the stub's catalog. */
const SELECT_OK = (handler) => handler.fulfill({
  status: 200, contentType: "application/json", body: JSON.stringify({ model: { id: "claude" } }),
});

/* A select the server refuses the way section 4 says, for a model with a cost note that
   confirm_cost does not name: 400 with the note and the model, so the page can ask. */
const SELECT_COST = (handler) => {
  const body = JSON.parse(handler.request().postData() || "{}");
  const noted = (body.on || []).find((id) => /\[1m\]$|fable/.test(id) && !(body.confirm_cost || []).includes(id));
  if (!noted) return SELECT_OK(handler);
  return handler.fulfill({
    status: 400, contentType: "application/json",
    body: JSON.stringify({ error: "Needs usage credits on Pro.", cost_note: "Needs usage credits on Pro.", model: noted }),
  });
};

/* A request held open, then passed on to the stub: the time a button has to stay off. */
function held(ms) {
  return async (handler) => {
    await sleep(ms);
    return handler.continue();
  };
}

async function openSidebar(page, id) {
  await page.click(`[data-model-open='${id}']`);
  await page.waitForTimeout(400);
}

async function listSeen(page) {
  return page.evaluate(() => {
    const out = {};
    for (const row of document.querySelectorAll("#drawer [data-list-row]")) {
      const tick = row.querySelector("[data-model-tick]");
      out[row.getAttribute("data-list-row")] = {
        ticked: tick.checked,
        locked: tick.disabled,
        tag: (row.querySelector(".mo-tag .pill-text") || {}).textContent || "",
        note: (row.querySelector(".mo-note") || {}).textContent || "",
        noteTitle: (row.querySelector(".mo-note") || { getAttribute: () => "" }).getAttribute("title") || "",
        cost: Boolean(row.querySelector("[data-model-cost]")),
      };
    }
    const save = document.querySelector("#drawer [data-model-save]");
    return {
      rows: out,
      order: Object.keys(out),
      save: save ? save.textContent : "",
      saveOff: save ? save.disabled : null,
    };
  });
}

/* Every row of a table one line: all rows as tall as one line, and no cell that wraps or holds
   more than it shows without an ellipsis to say so. */
async function oneLine(page, selector) {
  return page.evaluate((wanted) => {
    const table = document.querySelector(wanted);
    if (!table) return { found: false };
    const rows = [...table.querySelectorAll("tbody tr")];
    const heights = rows.map((row) => Math.round(row.getBoundingClientRect().height));
    const wrapped = [];
    for (const cell of table.querySelectorAll("tbody td")) {
      const style = getComputedStyle(cell);
      if (style.display === "none") continue;
      if (style.whiteSpace !== "nowrap") wrapped.push(`${cell.className}: ${style.whiteSpace}`);
      const cut = cell.scrollWidth > cell.clientWidth + 1;
      if (cut && style.textOverflow !== "ellipsis" && !cell.querySelector(".pill, button")) {
        wrapped.push(`${cell.className}: cut with no ellipsis`);
      }
      if (cut && !cell.getAttribute("title") && !cell.querySelector("[title]:not([title=''])")) {
        wrapped.push(`${cell.className}: cut with no title`);
      }
    }
    return {
      found: true,
      count: rows.length,
      tallest: Math.max(0, ...heights),
      shortest: Math.min(...heights),
      wrapped,
    };
  }, selector);
}

/* ------------------------------------------------------------ the providers table */

{
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: {
      "/api/accounts/login-state": JSON.stringify([{ name: "farm-one" }]),
      "/api/engines": JSON.stringify({ models: [] }),
    },
  });
  const body = await text(page);
  check("machine: a login state that is not an envelope leaves the table standing",
    thrown.length === 0, thrown[0]);
  check("machine: an account with no login reading says so", /not read yet/.test(body), body.slice(0, 200));
  check("machine: a models answer that is not a list is an empty providers table",
    /No providers connected/.test(body), body.slice(0, 200));
  check("machine: and the empty table still offers the button that fills it",
    /Add a provider/.test(body), body.slice(0, 200));
  await context.close();
}

/* The models table draws ONE pill per row and exactly the actions that pill allows. Five rows,
   one per status, because each carries a different set: only On and Off can be switched, only
   an installed and keyed model can be tested, and only a model this operator added can be
   removed. A page that assumed every catalog row was installed offered to switch on a command
   that is not there, and told the reader it was "on the path". */
{
  const { page, context, posted } = await open({ view: "machine" });
  const seen = await page.evaluate(() => {
    const out = {};
    for (const row of document.querySelectorAll("#view .mo-providers tbody tr")) {
      const name = row.querySelector("[data-model-open]");
      const id = name ? name.getAttribute("data-model-open") : "?";
      out[id] = {
        pills: [...row.querySelectorAll(".pill-text")].map((node) => node.textContent),
        status: row.querySelector("td:nth-child(3) .pill-text").textContent,
        meaning: row.querySelector("td:nth-child(3) .pill").className.replace("pill ", ""),
        switch: Boolean(row.querySelector("[data-model-switch]")),
        switchLabel: row.querySelector("[data-model-switch]")
          ? row.querySelector("[data-model-switch]").textContent : "",
        test: Boolean(row.querySelector("[data-model-test]")),
        remove: Boolean(row.querySelector("[data-model-remove]")),
        text: row.innerText,
        // one line per row: the key command and a failure's reason ride on titles, not on
        // second lines, so they are read from where they live
        hint: row.querySelector("[data-model-auth-hint]")
          ? row.querySelector("[data-model-auth-hint]").getAttribute("title") : "",
        why: row.querySelector("td:nth-child(3) .pill").getAttribute("title") || "",
        runs: name ? name.getAttribute("title") : "",
        paid: row.querySelector("td:nth-child(2)").getAttribute("title") || "",
        lines: Math.round(row.getBoundingClientRect().height),
      };
    }
    return out;
  });
  const want = {
    claude: { status: "Connected", meaning: "done", switch: true, test: true, remove: false },
    codex: { status: "Failing", meaning: "fail", switch: true, test: true, remove: false },
    "demo-plain": { status: "Off", meaning: "pause", switch: true, test: true, remove: true },
    "demo-strict": { status: "Needs a key", meaning: "wait", switch: false, test: true, remove: true },
    local: { status: "Not installed", meaning: "pause", switch: false, test: false, remove: false },
    // murmur no longer ships its engine; the farm added it, so it is still offered Remove
    grok: { status: "Off", meaning: "pause", switch: true, test: true, remove: true },
  };
  // One per status plus the row murmur no longer ships, because this runs before the add-dialog
  // checks at the end of this file write anything into the stub's catalog. A new block that
  // registers a model belongs after this one.
  check("machine: the models table has one row per status, and the row not in the catalog",
    Object.keys(seen).length === 6, Object.keys(seen).join(", "));
  for (const [id, wanted] of Object.entries(want)) {
    const row = seen[id] || {};
    check(`machine: ${id} is drawn as ${wanted.status}`,
      row.status === wanted.status && row.meaning === wanted.meaning,
      JSON.stringify(row).slice(0, 160));
    check(`machine: ${id} offers exactly the actions its status allows`,
      row.switch === wanted.switch && row.test === wanted.test && row.remove === wanted.remove,
      JSON.stringify(row).slice(0, 160));
  }
  check("machine: a model with no key offers the command that gives it one, and Test",
    /fleet models auth demo-strict/.test(seen["demo-strict"].hint) && seen["demo-strict"].test === true,
    `${seen["demo-strict"].hint} | ${seen["demo-strict"].text.slice(0, 120)}`);
  check("machine: a model that is failing every call can still be switched off",
    seen.codex.switch === true && seen.codex.switchLabel === "Switch off",
    JSON.stringify(seen.codex).slice(0, 160));
  check("machine: the switch says what pressing it does, never the state the row is in",
    seen.claude.switchLabel === "Switch off" && seen["demo-plain"].switchLabel === "Switch on",
    `claude: ${seen.claude.switchLabel}, demo-plain: ${seen["demo-plain"].switchLabel}`);
  check("machine: a model with one status wears one pill in that column",
    (seen.claude.pills || []).filter((word) => word === "Connected").length === 1,
    (seen.claude.pills || []).join(", "));
  check("machine: a failing model carries its reason on the pill, and the row stays one line",
    /the last health call timed out/.test(seen.codex.why) && !/timed out/.test(seen.codex.text),
    `${seen.codex.why} | ${seen.codex.text.slice(0, 120)}`);
  {
    // The one-line table rule: a one-line table has one-line cells. Every row is the same height as
    // the first, whatever its cells hold, or a cell has wrapped.
    const heights = Object.values(seen).map((row) => row.lines);
    check("machine: every models row is one line high, none taller than its neighbours",
      heights.length > 1 && Math.max(...heights) - Math.min(...heights) <= 2, heights.join(", "));
  }
  check("machine: a model that is not installed says so, with what to run on its pill",
    /Not installed/.test(seen.local.text) && /example.invalid/.test(seen.local.why)
    && !/on the path/.test(seen.local.text), `${seen.local.why} | ${seen.local.text.slice(0, 200)}`);
  check("machine: and says it once, in the status column and nowhere else",
    (seen.local.pills || []).length === 1 && seen.local.status === "Not installed",
    (seen.local.pills || []).join(", "));
  check("machine: an installed provider says the command it runs, in the name's tooltip",
    /\/usr\/bin\/codex/.test(seen.codex.runs) && /codex exec/.test(seen.codex.runs), seen.codex.runs);
  check("machine: every row says how it is paid for, in a word, with the sentence in its title",
    /Subscription/.test(seen.claude.text) && /Your Claude subscription/.test(seen.claude.paid)
    && /API key, paid per token on your key/.test(seen["demo-plain"].text)
    && /Local/.test(seen.local.text) && /Runs on this machine/.test(seen.local.paid),
    `${seen["demo-plain"].text.slice(0, 160)} | ${seen.local.paid}`);
  check("machine: no role or quality note is in the table",
    !/the workhorse/.test(await text(page)), "");
  check("machine: nothing was switched by drawing the models table",
    !posted.some((url) => url.endsWith("/api/models")), posted.join(" "));
  await context.close();
}

/* A row murmur no longer ships. murmur ships Claude Code and Codex, and a farm that added an
   engine before its preset was removed still lists it in its models.toml. The server reads the
   row as it always did and sends in_catalog false with one sentence on how to take it out; the
   table says so with a pill beside the name, on the same one line, and the sidebar opens with
   the sentence. Nothing removes it for the person. */
{
  const note = (STUB_ROWS.find((row) => row && row.id === "grok") || {}).catalog_note || "";
  const { page, context, thrown } = await open({ view: "machine" });
  const seen = await page.evaluate(() => {
    const rows = [...document.querySelectorAll("#view .mo-providers tbody tr")];
    const heights = rows.map((row) => Math.round(row.getBoundingClientRect().height));
    const orphans = [...document.querySelectorAll("#view .mo-providers [data-model-orphan]")];
    const mark = document.querySelector("#view .mo-providers [data-model-orphan='grok']");
    const row = mark ? mark.closest("tr") : null;
    const name = row ? row.querySelector("[data-model-open='grok']") : null;
    const cell = row ? row.querySelector("td:first-child") : null;
    const pill = mark ? mark.querySelector(".pill") : null;
    const top = (node) => Math.round(node.getBoundingClientRect().top);
    const bottom = (node) => Math.round(node.getBoundingClientRect().bottom);
    return {
      ids: orphans.map((node) => node.getAttribute("data-model-orphan")),
      word: pill ? pill.querySelector(".pill-text").textContent : "",
      title: pill ? pill.getAttribute("title") : "",
      inProvider: Boolean(cell && mark && cell.contains(mark)),
      // one line: the pill sits within the name's own line, and the row is no taller than the rest
      sameLine: Boolean(name && pill) && Math.abs((top(pill) + bottom(pill)) - (top(name) + bottom(name))) <= 4
        && pill.getBoundingClientRect().height <= name.getBoundingClientRect().height + 4,
      rowHeight: row ? Math.round(row.getBoundingClientRect().height) : 0,
      heights,
      wrap: cell ? getComputedStyle(cell.querySelector(".mo-provider-cell") || cell).whiteSpace : "",
      status: row ? row.querySelector("td:nth-child(3) .pill-text").textContent : "",
      width: window.innerWidth,
    };
  });
  check("machine: a row murmur no longer ships wears Not in the catalog, and only that row does",
    seen.ids.join(",") === "grok" && seen.word === "Not in the catalog" && seen.inProvider,
    JSON.stringify(seen).slice(0, 300));
  check("machine: the pill's title is the server's own sentence on how to take it out",
    note.length > 0 && seen.title === note && /press Remove/.test(seen.title),
    `${seen.title} | ${note}`);
  check("machine: at 1440 the pill sits beside the name on the one line, the row as tall as the rest",
    seen.width === 1440 && seen.sameLine && seen.wrap === "nowrap"
    && seen.heights.every((height) => Math.abs(height - seen.rowHeight) <= 2),
    JSON.stringify(seen).slice(0, 300));
  check("machine: and the row keeps its own status word beside it",
    seen.status === "Off", seen.status);
  await page.click("[data-model-open='grok']");
  await page.waitForTimeout(500);
  const drawer = await page.evaluate(() => {
    const body = document.getElementById("drawerBody");
    const node = body.querySelector("p.readonly-note[data-model-orphan-note]");
    if (!node) return { said: "", first: false };
    // first: before the status line and before anything else the sidebar draws
    const status = body.querySelector("[data-model-status-words]");
    const before = [...body.querySelectorAll("*")].filter((other) => other !== node
      && !other.contains(node) && !node.contains(other) && other.textContent.trim()
      && node.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_PRECEDING);
    return {
      said: node ? node.textContent : "",
      first: Boolean(node && status) && before.length === 0
        && Boolean(node.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING),
    };
  });
  check("machine: the orphan's sidebar starts with the same sentence",
    drawer.said === note && drawer.first, JSON.stringify(drawer).slice(0, 300));
  await page.click("#drawerClose");
  await page.waitForTimeout(300);
  await page.click("[data-model-open='claude']");
  await page.waitForTimeout(500);
  const shipped = await page.evaluate(() => Boolean(document.querySelector("#drawerBody [data-model-orphan-note]")));
  check("machine: a row in the catalog carries no such note", shipped === false, String(shipped));
  check("machine: nothing threw around a row not in the catalog", thrown.length === 0, thrown[0]);
  await context.close();

  /* A phone's provider column is narrower than the pill alone. The name must stay on screen and
     tappable, and the pill must stay inside its own cell. */
  const phone = await open({ view: "machine", size: { width: 390, height: 844 } });
  const small = await phone.page.evaluate(() => {
    const name = document.querySelector("#view [data-model-open='grok']");
    const mark = document.querySelector("#view [data-model-orphan='grok']");
    if (!name || !mark) return { found: false };
    const cell = name.closest("td").getBoundingClientRect();
    const box = name.getBoundingClientRect();
    const pill = mark.getBoundingClientRect();
    const row = name.closest("tr").getBoundingClientRect();
    const other = document.querySelector("#view [data-model-open='claude']").closest("tr").getBoundingClientRect();
    return {
      found: true,
      name: Math.round(box.width),
      pillRight: Math.round(pill.right),
      cellRight: Math.round(cell.right),
      row: Math.round(row.height),
      other: Math.round(other.height),
    };
  });
  check("machine: on a phone the orphan's name stays on screen, its pill inside its cell, one line",
    small.found && small.name >= 40 && small.pillRight <= small.cellRight
    && Math.abs(small.row - small.other) <= 2, JSON.stringify(small));
  await phone.page.click("[data-model-open='grok']");
  await phone.page.waitForTimeout(500);
  const tapped = await phone.page.evaluate(() => Boolean(document.querySelector("#drawerBody [data-model-orphan-note]")));
  check("machine: and tapping it opens its sidebar with the note", tapped, String(tapped));
  check("machine: nothing threw on the orphan at a phone width", phone.thrown.length === 0, phone.thrown[0]);
  await phone.context.close();
}

/* The same at laptop widths: at 1024 the full pill used to push the name to nothing, so the row
   could not be opened. The pill yields first at every width. */
for (const width of [1024, 1280]) {
  const laptop = await open({ view: "machine", size: { width, height: 900 } });
  const seen = await laptop.page.evaluate(() => {
    const name = document.querySelector("#view [data-model-open='grok']");
    const mark = document.querySelector("#view [data-model-orphan='grok']");
    if (!name || !mark) return { found: false };
    const cell = name.closest("td");
    return { found: true, name: Math.round(name.getBoundingClientRect().width),
      pillRight: Math.round(mark.getBoundingClientRect().right), cellRight: Math.round(cell.getBoundingClientRect().right),
      title: cell.title || "" };
  });
  check(`machine: at ${width} the orphan's name stays clickable and its pill stays in its cell`,
    seen.found && seen.name >= 40 && seen.pillRight <= seen.cellRight && /not in the catalog/.test(seen.title),
    JSON.stringify(seen));
  await laptop.page.click("[data-model-open='grok']", { timeout: 3000 }).catch(() => null);
  await laptop.page.waitForTimeout(500);
  const opened = await laptop.page.evaluate(() => Boolean(document.querySelector("#drawerBody [data-model-orphan-note]")));
  check(`machine: and at ${width} clicking it opens its sidebar with the note`, opened, String(opened));
  await laptop.context.close();
}

/* Status and Actions disagree on a real farm, and that is the server being right: a generic
   model is "off" until a test passes, however it is switched. The pill carries the state, the
   button carries the press, so a row like this says Off and offers Switch off. */
{
  const only = [{
    id: "democli", label: "Demo CLI", engine: "generic", source: "added", status: "off",
    enabled: true, installed: true, path: "/usr/bin/democli", command: "democli",
    access: "An API key, held on the farm.", auth_env: "DEMOCLI_API_KEY",
    run: "{bin} -p {task}", last_test: null, install_hint: "npm install -g @example/democli",
  }];
  const { page, context, thrown, sent } = await open({
    view: "machine",
    overrides: { "/api/engines": JSON.stringify(only) },
  });
  const seen = await page.evaluate(() => ({
    status: document.querySelector("#view .mo-providers td:nth-child(3) .pill-text").textContent,
    label: document.querySelector("[data-model-switch='democli']").textContent,
  }));
  check("machine: a row that is switched on and still off says Off and offers Switch off",
    seen.status === "Off" && seen.label === "Switch off", JSON.stringify(seen));
  await page.click("[data-model-switch='democli']");
  await page.waitForTimeout(800);
  const posted = sent.find((item) => item.url.endsWith("/api/models"));
  const body = JSON.parse((posted || {}).body || "{}");
  check("machine: and pressing it sends the press the button named",
    body.action === "disable" && body.id === "democli", JSON.stringify(body));
  check("machine: nothing threw where the status and the switch disagree",
    thrown.length === 0, thrown[0]);
  await context.close();
}

/* A farm on last release's server, which sends no status word at all. The five are worked out
   from the fields that route has always carried. `keyed` is not one of them: no server has ever
   sent it, so the line that read it decided nothing and named a field a reader would go looking
   for in vain. */
{
  const legacy = [
    { id: "one", label: "Switched on", engine: "generic", installed: true, enabled: true,
      health: "ok", auth_env: "ONE_API_KEY", keyed: false, path: "/usr/bin/one",
      command: "one", access: "An API key." },
    { id: "two", label: "Switched off", engine: "generic", installed: true, enabled: false,
      health: "ok", path: "/usr/bin/two", command: "two", access: "An API key." },
    { id: "three", label: "Failing", engine: "generic", installed: true, enabled: true,
      health: "fail", health_detail: "the provider said no", path: "/usr/bin/three",
      command: "three", access: "An API key." },
    { id: "four", label: "Not here", engine: "generic", installed: false, enabled: true,
      command: "four", access: "An API key.", install_hint: "npm install -g four" },
  ];
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: { "/api/engines": JSON.stringify(legacy) },
  });
  const seen = await page.evaluate(() => {
    const out = {};
    for (const row of document.querySelectorAll("#view .mo-providers tbody tr")) {
      const name = row.querySelector("[data-model-open]");
      const said = row.querySelector("td:nth-child(3) .pill-text");
      out[name.getAttribute("data-model-open")] = said ? said.textContent : "";
    }
    return out;
  });
  check("machine: a farm that sends no status word still draws the five",
    seen.one === "Connected" && seen.two === "Off" && seen.three === "Failing"
    && seen.four === "Not installed", JSON.stringify(seen));
  check("machine: nothing threw on a farm on an older server", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A models answer with a hole in it. A null row, or a row with no id, is a catalog entry the
   farm could not read: reading a field off it used to throw twice and leave the card with no
   table and no Add button, while the rest of the answer was a perfectly good catalog. */
{
  const holed = [
    { id: "claude", label: "Claude Code", engine: "claude", status: "on", enabled: true,
      installed: true, path: "/usr/bin/claude", command: "claude", source: "shipped",
      access: "Your Claude subscription.", last_test: null },
    null,
    { label: "no id at all", engine: "generic", status: "off", installed: true },
  ];
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: { "/api/engines": JSON.stringify(holed) },
  });
  const seen = await page.evaluate(() => ({
    rows: document.querySelectorAll("#view .mo-providers tbody tr").length,
    names: [...document.querySelectorAll("#view [data-model-open]")]
      .map((node) => node.getAttribute("data-model-open")),
    add: Boolean(document.querySelector("[data-add-model]")),
  }));
  check("machine: a row the farm could not read leaves the rest of the catalog standing",
    seen.rows === 1 && seen.names.join(",") === "claude", JSON.stringify(seen));
  check("machine: and the card keeps the button that adds one", seen.add === true,
    JSON.stringify(seen));
  check("machine: nothing threw on a models answer with a hole in it",
    thrown.length === 0, thrown[0]);
  await context.close();
}

/* A phone. The table stays a table, one line per row, and drops the columns its sidebar
   carries (Access, Last test and the buttons), so nothing is behind a sideways drag. */
{
  const { page, context, thrown } = await open({
    view: "machine",
    size: { width: 390, height: 844 },
  });
  const seen = await page.evaluate(() => {
    const table = document.querySelector("#view .mo-providers");
    const wrap = table.closest(".tablewrap");
    const row = table.querySelector("tbody tr");
    const box = row.getBoundingClientRect();
    return {
      head: getComputedStyle(table.querySelector("thead")).display,
      columns: [...table.querySelectorAll("thead th")]
        .filter((cell) => getComputedStyle(cell).display !== "none").map((cell) => cell.textContent),
      drag: wrap.scrollWidth - wrap.clientWidth,
      right: Math.round(box.right),
      view: window.innerWidth,
      status: (row.querySelector("td:nth-child(3) .pill-text") || {}).textContent || "",
    };
  });
  check("machine: on a phone the providers table keeps its head and never drags sideways",
    seen.head !== "none" && seen.drag <= 1 && seen.right <= seen.view,
    JSON.stringify(seen).slice(0, 260));
  check("machine: and shows the provider, its state and its models",
    seen.columns.join("|") === "Provider|Status|Models" && seen.status.length > 0,
    JSON.stringify(seen).slice(0, 260));
  check("machine: nothing threw at a phone width", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The shape of the rows themselves, read off the route rather than off the page: no row carries
   `docs`, because nothing on the server writes one into a catalog, and a row the add route writes
   carries no role, quality or caps note, because model_presets.ENTRY_FIELDS holds none of them.
   A stub that invents any of those lets this page lean on a field the farm will never send. */
{
  const rows = await (await fetch(`${BASE}/api/engines`)).json();
  check("machine: no row of the catalog carries a documentation link",
    rows.every((row) => !(row || {}).docs),
    rows.filter((row) => (row || {}).docs).map((row) => row.id).join(","));
  check("machine: a row's state and its switch are two fields, not one",
    rows.every((row) => typeof row.status === "string" && typeof row.enabled === "boolean"),
    JSON.stringify(rows.map((row) => [row.id, row.status, row.enabled])).slice(0, 240));
  check("machine: and the last test's outcome is a state word, not the prompt it sent",
    rows.every((row) => ["ok", "fail", "unchecked"].includes(row.health)),
    rows.map((row) => `${row.id}:${row.health}`).join(","));
  const written = await (await fetch(`${BASE}/api/models/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preset: "demo-plain", id: "shaped" }),
  })).json();
  const row = written.model || {};
  check("machine: the add route answers the row under model, with the preset's own fields",
    row.id === "shaped" && row.source === "added" && row.preset === "demo-plain"
    && row.auth_env === "DEMO_PLAIN_API_KEY", JSON.stringify(written).slice(0, 240));
  check("machine: and invents no role, quality, caps or docs for it",
    !row.role && !row.quality && !row.caps && !row.docs,
    JSON.stringify(row).slice(0, 300));
  await fetch(`${BASE}/api/models/remove`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: "shaped" }),
  });
}

/* Clicking the name opens the drawer, and that is where the role, the quality note, the terms,
   the run template and the key's variable name live. They left the table on purpose. A row this
   farm added carries what the add route writes: its terms, its variant, the variable its key is
   read from and where it came from. The role, the quality note and the limits are catalog fields
   a person writes, so they are on the shipped rows. */
{
  const { page, context, thrown } = await open({ view: "machine" });
  await page.click("[data-model-open='demo-plain']");
  await page.waitForTimeout(500);
  const drawer = await page.evaluate(() => {
    const host = document.getElementById("drawer");
    return {
      open: host && !host.hidden,
      title: document.getElementById("drawerTitle").textContent,
      text: document.getElementById("drawerBody").innerText,
      run: Boolean(host.querySelector("[data-model-run]")),
      actions: [...host.querySelectorAll("[data-model-switch], [data-model-test], "
        + "[data-model-remove]")].length,
    };
  });
  check("machine: the model name opens a drawer about that model",
    drawer.open && /Demo Plain/.test(drawer.title), JSON.stringify(drawer).slice(0, 160));
  check("machine: the drawer carries what the table dropped",
    /headless mode/.test(drawer.text) && /fleet models auth demo-plain/.test(drawer.text)
    && /DEMO_PLAIN_API_KEY/.test(drawer.text) && /Added on this farm/.test(drawer.text),
    drawer.text.slice(0, 400));
  check("machine: and the run template, with {bin} and {task} explained",
    drawer.run && /\{bin\} is the command/.test(drawer.text), drawer.text.slice(0, 300));
  check("machine: the drawer offers the same actions as the row", drawer.actions === 3,
    String(drawer.actions));
  /* A shipped row's catalog carries the notes a person wrote in models.toml, and those are the
     ones the table dropped: what it is for, how good it is, and what the plan allows. */
  await page.click("#drawerClose");
  await page.waitForTimeout(300);
  await page.click("[data-model-open='claude']");
  await page.waitForTimeout(500);
  const shipped = await page.evaluate(() => document.getElementById("drawerBody").innerText);
  check("machine: a shipped row's drawer carries its role, its quality and its limits",
    /the workhorse/.test(shipped) && /frontier/.test(shipped)
    && /Two windows/.test(shipped), shipped.slice(0, 400));
  check("machine: nothing threw around the model drawer", thrown.length === 0, thrown[0]);
  await context.close();

  /* The Documentation row is drawn when, and only when, a route sends a link for that row. No
     shipped catalog and no added entry carries one today, so this is the case that proves the
     row works when a farm's own models.toml does. */
  const linked = [{
    id: "democli", label: "Demo CLI", engine: "generic", source: "added", status: "off",
    enabled: false, installed: true, path: "/usr/bin/democli", command: "democli",
    access: "An API key, held on the farm.", auth_env: "DEMOCLI_API_KEY",
    run: "{bin} -p {task}", last_test: null, health: "ok",
    docs: "https://example.invalid/docs/democli",
  }];
  const second = await open({
    view: "machine",
    overrides: { "/api/engines": JSON.stringify(linked) },
  });
  await second.page.click("[data-model-open='democli']");
  await second.page.waitForTimeout(500);
  const link = await second.page.evaluate(() => {
    const node = document.querySelector("#drawerBody a[href]");
    return node ? node.getAttribute("href") : "";
  });
  check("machine: a row that carries a documentation link draws it",
    link === "https://example.invalid/docs/democli", link || "no link");
  check("machine: nothing threw on the linked drawer",
    second.thrown.length === 0, second.thrown[0]);
  await second.context.close();
}

/* One press of a model switch is one real request to a provider. The stub is held open here so
   the second press lands while the first is still in flight, which is what a double click is. */
{
  const { page, context, posted, thrown } = await open({
    view: "machine",
    overrides: {
      "/api/models": (handler) => {
        if (handler.request().method() !== "POST") return handler.continue();
        return new Promise((resolve) => setTimeout(resolve, 1500)).then(() => handler.fulfill({
          status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }),
        }));
      },
    },
  });
  await page.click("[data-model-switch='claude']");
  await page.waitForTimeout(200);
  const during = await page.evaluate(() => ({
    disabled: document.querySelector("[data-model-switch='claude']").disabled,
  }));
  await page.click("[data-model-switch='claude']", { force: true });
  await page.waitForTimeout(400);
  const count = posted.filter((url) => url.endsWith("/api/models")).length;
  check("machine: a model switch that is working refuses a second press",
    during.disabled === true, JSON.stringify(during));
  check("machine: so a double click sends one request, not two", count === 1, `${count} sent`);
  check("machine: nothing threw around the model switch", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------ a provider's sidebar, one list of models */

/* The list opens with the models that are on, ticked. The default model wears its pill and
   cannot be unticked: untick it and no bare spawn would have a model. Opening it asks nothing,
   and a sidebar left open asks nothing either: nothing on this list polls. */
{
  const { page, context, thrown, sent } = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": SELECT_OK },
  });
  const cell = await page.evaluate(() => {
    const node = document.querySelector("[data-model-count='claude']");
    return { text: node.textContent, title: node.getAttribute("title") };
  });
  check("models: the Models cell counts the models that are on, with their names in the title",
    cell.text === "2 on" && cell.title === "opus, sonnet", JSON.stringify(cell));
  await openSidebar(page, "claude");
  const seen = await listSeen(page);
  check("models: the sidebar opens with the models that are on, ticked, the default first",
    seen.order.join(",") === "opus,sonnet" && seen.rows.opus.ticked && seen.rows.sonnet.ticked,
    JSON.stringify(seen).slice(0, 300));
  check("models: the default model wears its Default pill, and another on model says On",
    seen.rows.opus.tag === "Default" && seen.rows.sonnet.tag === "On",
    JSON.stringify(seen.rows).slice(0, 300));
  check("models: the default model's tick cannot be pressed",
    seen.rows.opus.locked === true && seen.rows.sonnet.locked === false,
    JSON.stringify(seen.rows).slice(0, 300));
  check("models: and Save is off until something changed", seen.saveOff === true && seen.save === "Save",
    `${seen.save} ${seen.saveOff}`);
  await page.click("[data-model-tick='opus']", { force: true });
  await page.waitForTimeout(300);
  const after = await listSeen(page);
  check("models: pressing the default's tick anyway leaves it on and changes nothing",
    after.rows.opus.ticked === true && after.saveOff === true, JSON.stringify(after.rows.opus));
  await page.waitForTimeout(7000);
  const asked = sent.filter((row) => /\/api\/models\/(discover|select)$/.test(row.url));
  check("models: an open sidebar sends nothing by itself, however long it is open",
    asked.length === 0, asked.map((row) => row.url).join(" "));
  check("models: nothing threw on the sidebar", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Request available models merges what the provider offers into the same list. The request is
   one POST with the provider's id and nothing else, and its button is off while it is out. New
   rows arrive unticked with their source pill; the rows already on stay ticked and say On; a
   noted row carries its note in the row. */
{
  const { page, context, thrown, sent } = await open({
    overrides: { "/api/engines": engines(), "/api/models/discover": held(1500) },
  });
  await openSidebar(page, "claude");
  await page.click("[data-model-request='claude']");
  await page.waitForTimeout(300);
  const during = await page.evaluate(() => {
    const node = document.querySelector("[data-model-request='claude']");
    return { off: node.disabled, said: node.textContent };
  });
  check("models: Request is off while its own request is in flight",
    during.off === true && during.said === "Requesting", JSON.stringify(during));
  await page.click("[data-model-request='claude']", { force: true });
  await page.waitForTimeout(1800);
  const asked = bodies(sent, "/api/models/discover");
  check("models: so a double press sends one request",
    asked.length === 1, `${asked.length} sent`);
  check("models: the request body is the provider's id and nothing else",
    asked.length === 1 && same(asked[0], { id: "claude" }), JSON.stringify(asked));
  const seen = await listSeen(page);
  check("models: the answer merges into the one list, after the models that are on",
    seen.order.join(",") === "opus,sonnet,haiku,fable,claude-opus-5-5,claude-sonnet-4-6[1m]",
    seen.order.join(","));
  check("models: rows already on stay ticked and say On",
    seen.rows.opus.ticked && seen.rows.opus.tag === "Default"
    && seen.rows.sonnet.ticked && seen.rows.sonnet.tag === "On", JSON.stringify(seen.rows).slice(0, 200));
  check("models: new rows arrive unticked with their source pill",
    ["haiku", "fable", "claude-opus-5-5"].every((id) => seen.rows[id].ticked === false
      && seen.rows[id].tag === "From the docs"), JSON.stringify(seen.rows).slice(0, 400));
  check("models: a row with a cost note carries it in the row, whole in its title",
    /usage credits/.test(seen.rows.fable.noteTitle) && seen.rows.fable.note === seen.rows.fable.noteTitle
    && seen.rows.fable.cost === true, JSON.stringify(seen.rows.fable));
  check("models: the cost note is decided for the full id too, not by a lookup of the alias",
    /usage credits on every plan/.test(seen.rows["claude-sonnet-4-6[1m]"].note)
    && seen.rows["claude-sonnet-4-6[1m]"].cost === true, JSON.stringify(seen.rows["claude-sonnet-4-6[1m]"]));
  const button = await page.evaluate(() => document.querySelector("[data-model-request='claude']").disabled);
  check("models: and Request is live again once the answer is in", button === false, String(button));
  check("models: nothing threw around a request", thrown.length === 0, thrown[0]);
  await context.close();
}

/* An account's list says so: Codex asks the account, and its rows say From your account. */
{
  const { page, context, thrown } = await open({ overrides: { "/api/engines": engines() } });
  await openSidebar(page, "codex");
  await page.click("[data-model-request='codex']");
  await page.waitForTimeout(900);
  const seen = await listSeen(page);
  check("models: a list read from the account says From your account",
    seen.rows["gpt-6-astra"] && seen.rows["gpt-6-astra"].tag === "From your account"
    && seen.rows["gpt-6-sol"].tag === "Default", JSON.stringify(seen.rows).slice(0, 300));
  check("models: nothing threw on an account list", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Ticking and saving. Two new models read "Add 2 models" and send exactly those two on; an
   untick turns the button into Save and sends the untick as off. The save's own button is off
   while it is out, so a double press sends one. */
{
  const { page, context, thrown, sent } = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": SELECT_OK },
  });
  await openSidebar(page, "claude");
  await page.click("[data-model-request='claude']");
  await page.waitForTimeout(900);
  await page.click("[data-model-tick='haiku']");
  await page.click("[data-model-tick='claude-opus-5-5']");
  await page.waitForTimeout(200);
  const two = await listSeen(page);
  check("models: two new ticks read Add 2 models, and the button is live",
    two.save === "Add 2 models" && two.saveOff === false, `${two.save} ${two.saveOff}`);
  await page.click("[data-model-tick='sonnet']");
  await page.waitForTimeout(200);
  const withOff = await listSeen(page);
  check("models: a change that includes a removal reads Save",
    withOff.save === "Save" && withOff.saveOff === false && withOff.rows.sonnet.ticked === false,
    `${withOff.save} ${withOff.saveOff}`);
  await page.click("[data-model-tick='sonnet']");
  await page.waitForTimeout(200);
  check("models: and ticking it back reads Add 2 models again",
    (await listSeen(page)).save === "Add 2 models", "");
  await page.click("[data-model-save='claude']");
  await page.waitForTimeout(800);
  const saved = bodies(sent, "/api/models/select");
  check("models: Add sends the two ticked ids on, nothing off, and no cost confirm",
    saved.length === 1 && same(saved[0],
      { id: "claude", on: ["haiku", "claude-opus-5-5"], off: [], confirm_cost: [] }),
    JSON.stringify(saved));
  check("models: and no request sent a prompt, a test or a key",
    sent.every((row) => !/\/api\/models$/.test(row.url) && !/"(prompt|key|token)"/.test(row.body)),
    sent.map((row) => row.url).join(" "));
  await context.close();

  const second = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": SELECT_OK },
  });
  await openSidebar(second.page, "claude");
  await second.page.click("[data-model-tick='sonnet']");
  await second.page.waitForTimeout(200);
  await second.page.click("[data-model-save='claude']");
  await second.page.waitForTimeout(800);
  const off = bodies(second.sent, "/api/models/select");
  check("models: an untick alone reads Save and sends the id off",
    off.length === 1 && same(off[0], { id: "claude", on: [], off: ["sonnet"], confirm_cost: [] }),
    JSON.stringify(off));
  check("models: nothing threw around a save", thrown.length === 0 && second.thrown.length === 0,
    thrown[0] || second.thrown[0]);
  await second.context.close();

  const third = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": held(1500) },
  });
  await openSidebar(third.page, "codex");
  await third.page.fill("[data-model-name='codex']", "gpt-6-luna");
  await third.page.click("[data-model-name-add='codex']");
  await third.page.click("[data-model-save='codex']");
  await third.page.waitForTimeout(250);
  const during = await third.page.evaluate(() => {
    const node = document.querySelector("[data-model-save='codex']");
    return { off: node.disabled, said: node.textContent };
  });
  await third.page.click("[data-model-save='codex']", { force: true });
  await third.page.waitForTimeout(1800);
  check("models: Save is off while its own request is in flight",
    during.off === true && during.said === "Saving", JSON.stringify(during));
  check("models: so a double press sends one save",
    bodies(third.sent, "/api/models/select").length === 1,
    `${bodies(third.sent, "/api/models/select").length} sent`);
  await third.context.close();
}

/* A model whose use can cost money the plan does not cover asks once more before it is
   switched on, and the save that follows names it in confirm_cost. Declining sends nothing and
   leaves it off. A retirement date is a note too, and asks nothing. */
{
  const { page, context, thrown, sent } = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": SELECT_OK },
  });
  await openSidebar(page, "claude");
  await page.click("[data-model-request='claude']");
  await page.waitForTimeout(900);
  await page.click("[data-model-tick='fable']");
  await page.click("[data-model-save='claude']");
  await page.waitForTimeout(400);
  const asked = await page.evaluate(() => {
    const node = document.querySelector("#drawer [data-cost-question]");
    return node ? node.innerText : "";
  });
  check("models: switching a noted model on asks the second question first",
    /can cost money/.test(asked) && /usage credits/.test(asked), asked.slice(0, 240));
  check("models: and nothing is sent until it is answered",
    bodies(sent, "/api/models/select").length === 0, "");
  await page.click("[data-cost-no]");
  await page.waitForTimeout(300);
  const declined = await listSeen(page);
  check("models: No leaves it off and sends nothing",
    declined.rows.fable.ticked === false && bodies(sent, "/api/models/select").length === 0
    && declined.saveOff === true, JSON.stringify(declined.rows.fable));
  await page.click("[data-model-tick='fable']");
  await page.click("[data-model-tick='haiku']");
  await page.click("[data-model-save='claude']");
  await page.waitForTimeout(300);
  await page.click("[data-cost-yes]");
  await page.waitForTimeout(800);
  const saved = bodies(sent, "/api/models/select");
  check("models: Yes sends the noted model on, and names it in confirm_cost and nothing else",
    saved.length === 1 && same(saved[0],
      { id: "claude", on: ["fable", "haiku"], off: [], confirm_cost: ["fable"] }),
    JSON.stringify(saved));
  await context.close();

  const second = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": SELECT_OK },
  });
  await openSidebar(second.page, "codex");
  await second.page.click("[data-model-request='codex']");
  await second.page.waitForTimeout(900);
  const retiring = await listSeen(second.page);
  await second.page.click("[data-model-tick='gpt-5.5']");
  await second.page.click("[data-model-save='codex']");
  await second.page.waitForTimeout(800);
  const plain = bodies(second.sent, "/api/models/select");
  check("models: a retirement date is shown as a note in its row",
    /Retires on 2026-10-14/.test(retiring.rows["gpt-5.5"].note), JSON.stringify(retiring.rows["gpt-5.5"]));
  check("models: and asks nothing: the save goes at once, with no cost confirm",
    plain.length === 1 && same(plain[0], { id: "codex", on: ["gpt-5.5"], off: [], confirm_cost: [] }),
    JSON.stringify(plain));
  check("models: nothing threw around the cost question",
    thrown.length === 0 && second.thrown.length === 0, thrown[0] || second.thrown[0]);
  await second.context.close();

  /* A description is shown and asks nothing, whatever its words: the Codex docs' pick for a
     plan, and a description that talks about cost, both go at once. Only cost_note asks, even
     when its own words name a retirement. */
  const third = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": SELECT_OK },
  });
  await openSidebar(third.page, "codex");
  await third.page.click("[data-model-request='codex']");
  await third.page.waitForTimeout(900);
  const described = await listSeen(third.page);
  await third.page.click("[data-model-tick='gpt-6-astra']");
  await third.page.click("[data-model-save='codex']");
  await third.page.waitForTimeout(800);
  const quiet = await third.page.evaluate(() => Boolean(document.querySelector("#drawer [data-cost-question]")));
  const going = bodies(third.sent, "/api/models/select");
  check("models: a description is shown in its row, and is not a cost note",
    /billed to the plan/.test(described.rows["gpt-6-astra"].note) && described.rows["gpt-6-astra"].cost === false,
    JSON.stringify(described.rows["gpt-6-astra"]));
  check("models: a description asks nothing, even one that talks about cost",
    !quiet && going.length === 1
    && same(going[0], { id: "codex", on: ["gpt-6-astra"], off: [], confirm_cost: [] }), JSON.stringify(going));
  await third.context.close();

  const fourth = await open({
    overrides: {
      "/api/engines": engines(),
      "/api/models/select": SELECT_OK,
      "/api/models/discover": JSON.stringify({
        source: "docs", error: null,
        models: [{ id: "gpt-6-nova", label: "GPT-6 Nova", description: "", cost_note: "Retires on 2026-12-01, and bills credits until then.", on: false }],
      }),
    },
  });
  await openSidebar(fourth.page, "codex");
  await fourth.page.click("[data-model-request='codex']");
  await fourth.page.waitForTimeout(700);
  await fourth.page.click("[data-model-tick='gpt-6-nova']");
  await fourth.page.click("[data-model-save='codex']");
  await fourth.page.waitForTimeout(400);
  const noted = await fourth.page.evaluate(() => (document.querySelector("#drawer [data-cost-question]") || {}).innerText || "");
  check("models: a cost note asks, whatever its words, and nothing is sent first",
    /bills credits/.test(noted) && bodies(fourth.sent, "/api/models/select").length === 0, noted.slice(0, 200));
  check("models: nothing threw around descriptions and cost notes",
    third.thrown.length === 0 && fourth.thrown.length === 0, third.thrown[0] || fourth.thrown[0]);
  await fourth.context.close();
}

/* A request that fails says why in the server's own fixed sentence, shown as sent, and shows the
   docs list instead. A key-shaped string is never drawn, even if a server were to pass it on. */
{
  const { page, context, thrown } = await open({ overrides: { "/api/engines": engines() } });
  await openSidebar(page, "demo-strict");
  await page.click("[data-model-request='demo-strict']");
  await page.waitForTimeout(900);
  const said = await page.evaluate(() => {
    const node = document.querySelector("#drawer [data-model-failed]");
    return node ? node.textContent : "";
  });
  const seen = await listSeen(page);
  check("models: a failed request says why, in the fixed sentence",
    said === "The request failed: the file is missing. The list below is the docs list.", said);
  check("models: and shows the docs list instead",
    seen.rows["demo-strict/coder"] && seen.rows["demo-strict/coder"].tag === "From the docs",
    JSON.stringify(seen.rows));
  await context.close();

  const leaked = "Traceback: api_key=sk-ant-api03-0123456789abcdefghij in /home/farm/.demo-strict/config.toml";
  const second = await open({
    overrides: {
      "/api/engines": engines(),
      "/api/models/discover": JSON.stringify({ source: "docs", error: leaked, models: [] }),
    },
  });
  await openSidebar(second.page, "demo-strict");
  await second.page.click("[data-model-request='demo-strict']");
  await second.page.waitForTimeout(700);
  const drawn = await second.page.evaluate(() => document.getElementById("drawerBody").innerText);
  check("models: an error that carries a key-shaped string is never drawn",
    !/Traceback|sk-ant|config\.toml/.test(drawn)
    && /The request failed, and its reason is not shown here\./.test(drawn), drawn.slice(-300));
  await second.context.close();

  /* Each of the server's seven failure sentences (lib/model_discovery.py FAILURES) is drawn as
     sent; the eighth, a row with no list at all, is not a failure and says so in its own words. */
  const NO_LIST = "this provider has no list to offer here; add a model by its name";
  const SENTENCES = [
    "the CLI is not installed", "it did not answer in 15 seconds", "its output could not be read",
    "the file is missing", "the CLI exited with an error", "nothing answered on its port",
    "it listed no models",
  ];
  let next = 0;
  const each = await open({
    overrides: {
      "/api/engines": engines(),
      "/api/models/discover": (handler) => handler.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ source: "docs", error: next < SENTENCES.length ? SENTENCES[next] : NO_LIST, models: [] }),
      }),
    },
  });
  await openSidebar(each.page, "demo-strict");
  for (const sentence of SENTENCES) {
    await each.page.click("[data-model-request='demo-strict']");
    await each.page.waitForTimeout(500);
    const shown = await each.page.evaluate(() => (document.querySelector("#drawer [data-model-failed]") || {}).textContent || "");
    check(`models: the server's sentence "${sentence}" is shown as sent`,
      shown === `The request failed: ${sentence}. The list below is the docs list.`, shown);
    next += 1;
  }
  await each.page.click("[data-model-request='demo-strict']");
  await each.page.waitForTimeout(500);
  const none = await each.page.evaluate(() => (document.querySelector("#drawer [data-model-failed]") || {}).textContent || "");
  check("models: a provider with no list says so, and does not call it a failed request",
    none === "This provider has no list to offer here. Add a model by its name below.", none);
  check("models: nothing threw across the eight sentences", each.thrown.length === 0, each.thrown[0]);
  await each.context.close();

  const third = await open({
    overrides: {
      "/api/engines": engines(),
      "/api/models/discover": (handler) => handler.fulfill({
        status: 409, contentType: "application/json",
        body: JSON.stringify({ error: "a request for demo-strict is already running" }),
      }),
    },
  });
  await openSidebar(third.page, "demo-strict");
  await third.page.click("[data-model-request='demo-strict']");
  await third.page.waitForTimeout(700);
  const refused = await third.page.evaluate(() => {
    const node = document.querySelector("#drawer [data-model-failed]");
    return { said: node ? node.textContent : "", button: document.querySelector("[data-model-request='demo-strict']").disabled };
  });
  check("models: a request the server refuses says the server's sentence, and can be tried again",
    refused.said === "a request for demo-strict is already running" && refused.button === false,
    JSON.stringify(refused));
  check("models: nothing threw on a failed request",
    thrown.length === 0 && second.thrown.length === 0 && third.thrown.length === 0,
    thrown[0] || second.thrown[0] || third.thrown[0]);
  await third.context.close();
}

/* Add by name takes a model the list does not show, under the one model rule. A leading "-"
   could become an option on the command line, and a key pasted into the field must never leave
   the page: both are refused here, before any request. A typed name has no cost note on the
   page, so the server's refusal is what asks the question. */
{
  const { page, context, thrown, sent } = await open({
    overrides: { "/api/engines": engines(), "/api/models/select": SELECT_COST },
  });
  await openSidebar(page, "claude");
  const before = sent.length;
  const refusal = async (typed) => {
    await page.fill("[data-model-name='claude']", typed);
    await page.click("[data-model-name-add='claude']");
    await page.waitForTimeout(200);
    return page.evaluate(() => {
      const node = document.querySelector("#drawer [data-model-name-error]");
      return node ? node.textContent : "";
    });
  };
  const dash = await refusal("-rf");
  check("models: a name with a leading - is refused on the page, with the rule",
    /starts with a letter or a digit/.test(dash), dash);
  const keyed = await refusal("sk-ant-api03-AbCdEf0123456789xyz");
  check("models: a token-looking string is refused as a key, not a model name",
    /looks like a key/.test(keyed), keyed);
  const long = await refusal("a".repeat(8) + "B1c2D3e4F5g6H7i8J9k0L1m2N3o4P5q6");
  check("models: and so is a long unbroken run of letters and digits",
    /looks like a key/.test(long), long);
  const spaced = await refusal("opus 5");
  check("models: a name with a space breaks the rule",
    /starts with a letter or a digit/.test(spaced), spaced);
  const typed = await listSeen(page);
  check("models: and none of them reached the list or the network",
    typed.order.join(",") === "opus,sonnet" && sent.length === before,
    `${typed.order.join(",")} ${sent.slice(before).map((row) => row.url).join(" ")}`);
  await page.fill("[data-model-name='claude']", "claude-opus-4-6[1m]");
  await page.click("[data-model-name-add='claude']");
  await page.waitForTimeout(200);
  const added = await listSeen(page);
  const field = await page.evaluate(() => document.querySelector("[data-model-name='claude']").value);
  check("models: a good name joins the list ticked, marked Added by name, and the field empties",
    added.rows["claude-opus-4-6[1m]"] && added.rows["claude-opus-4-6[1m]"].ticked
    && added.rows["claude-opus-4-6[1m]"].tag === "Added by name" && field === ""
    && added.save === "Add 1 model", `${JSON.stringify(added.rows["claude-opus-4-6[1m]"])} ${added.save} [${field}]`);
  await page.fill("[data-model-name='claude']", "sonnet");
  await page.click("[data-model-name-add='claude']");
  await page.waitForTimeout(200);
  const again = await page.evaluate(() => document.querySelector("#drawer [data-model-name-error]").textContent);
  check("models: a name already on says so", /already on/.test(again), again);
  await page.click("[data-model-save='claude']");
  await page.waitForTimeout(800);
  const first = bodies(sent, "/api/models/select");
  const question = await page.evaluate(() => {
    const node = document.querySelector("#drawer [data-cost-question]");
    return {
      said: node ? node.innerText : "",
      error: (document.querySelector("#drawer [data-model-save-error]") || {}).textContent || "",
      note: (document.querySelector("#drawer [data-model-cost='claude-opus-4-6[1m]']") || {}).textContent || "",
    };
  });
  check("models: a typed name is sent like any tick, with nothing confirmed it was not asked",
    first.length === 1 && same(first[0], { id: "claude", on: ["claude-opus-4-6[1m]"], off: [], confirm_cost: [] }),
    JSON.stringify(first));
  check("models: the server's cost refusal of a typed name asks the cost question, with its note",
    /can cost money/.test(question.said) && /usage credits on Pro/.test(question.said)
    && question.error === "" && /usage credits on Pro/.test(question.note), JSON.stringify(question));
  await page.click("[data-cost-yes]");
  await page.waitForTimeout(800);
  const saved = bodies(sent, "/api/models/select");
  const left = await page.evaluate(() => ({
    question: Boolean(document.querySelector("#drawer [data-cost-question]")),
    error: Boolean(document.querySelector("#drawer [data-model-save-error]")),
  }));
  check("models: and Yes sends it again, named in confirm_cost, and the save goes through",
    saved.length === 2 && same(saved[1],
      { id: "claude", on: ["claude-opus-4-6[1m]"], off: [], confirm_cost: ["claude-opus-4-6[1m]"] })
    && !left.question && !left.error, `${JSON.stringify(saved)} ${JSON.stringify(left)}`);
  check("models: nothing threw around Add by name", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A provider whose command cannot take a model shows one sentence instead of the list. */
{
  const { page, context, thrown } = await open({ overrides: { "/api/engines": engines() } });
  const cell = await page.evaluate(() => document.querySelector("[data-model-count='demo-plain']").getAttribute("title"));
  await openSidebar(page, "demo-plain");
  const seen = await page.evaluate(() => ({
    said: (document.querySelector("#drawer [data-model-cannot]") || {}).textContent || "",
    list: Boolean(document.querySelector("#drawer .mo-list")),
    request: Boolean(document.querySelector("#drawer [data-model-request]")),
    name: Boolean(document.querySelector("#drawer [data-model-name]")),
  }));
  check("models: a provider that cannot take a model says so in one sentence, and nothing else",
    seen.said === "This provider runs the model its own settings choose; change it there."
    && !seen.list && !seen.request && !seen.name, JSON.stringify(seen));
  check("models: and its Models cell carries the same sentence", /its own settings choose/.test(cell), cell);
  check("models: nothing threw on a provider with no model list", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A server that sends no `models_on` yet: the catalog's old string is read the same way, and the
   row's variant stands in for the default model. */
{
  const { page, context, thrown } = await open();
  const cell = await page.evaluate(() => document.querySelector("[data-model-count='claude']").textContent);
  await openSidebar(page, "claude");
  const seen = await listSeen(page);
  check("models: an older server's model string still counts and lists the models that are on",
    cell === "3 on" && seen.order.join(",") === "opus,sonnet,haiku" && seen.rows.opus.tag === "Default",
    `${cell} ${seen.order.join(",")}`);
  check("models: nothing threw on an older server's row", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The page may not write: every control of the sidebar is off, with the reason on each. */
{
  const { page, context, thrown } = await open({
    overrides: { "/api/engines": engines(), "/api/access": READ_ONLY },
  });
  await openSidebar(page, "claude");
  const seen = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll("#drawer [data-model-request], #drawer [data-model-tick], "
      + "#drawer [data-model-name], #drawer [data-model-name-add], #drawer [data-model-save]")];
    return {
      total: nodes.length,
      live: nodes.filter((node) => !node.disabled).map((node) => node.outerHTML.slice(0, 80)),
      reasons: nodes.filter((node) => /only read/.test(node.title || "")).length,
      locked: nodes.filter((node) => node.matches("[data-model-tick='opus']")).length,
    };
  });
  check("models: a read-only page switches every sidebar control off",
    seen.total >= 6 && seen.live.length === 0, JSON.stringify(seen).slice(0, 300));
  check("models: and says why on each, the default's own reason aside",
    seen.reasons === seen.total - seen.locked, JSON.stringify(seen).slice(0, 300));
  check("models: nothing threw on a read-only sidebar", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The one-line table rule, at a desktop and at a phone: every row of the providers table and of
   the sidebar list is one line, and nothing scrolls sideways at 390. */
for (const size of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  const long = {
    claude: {
      label: "Claude Code with a provider name far longer than any column could ever hold",
      models_on: ["opus", "sonnet", "claude-opus-5-5", "claude-sonnet-4-6[1m]"],
    },
  };
  const { page, context, thrown } = await open({
    size,
    overrides: {
      "/api/engines": engines(long),
      "/api/models/discover": JSON.stringify({
        source: "account", error: null,
        models: [
          { id: "a-model-id-that-is-far-too-long-for-its-column-and-then-some-more", label: "A label that is also much too long to fit in one line of this list", description: "A note that runs on well past the edge of the sidebar, so the row would wrap if it could", on: false },
          { id: "fable", label: "Fable 5.1", description: "", cost_note: "Some plans bill Fable to usage credits, and a headless run bills without asking.", on: false },
        ],
      }),
    },
  });
  const table = await oneLine(page, "#view .mo-providers");
  check(`models ${size.width}: every providers row is one line`,
    table.found && table.count >= 5 && table.tallest - table.shortest <= 2 && table.tallest <= 44
    && table.wrapped.length === 0, JSON.stringify(table).slice(0, 300));
  const wide = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth - window.innerWidth,
    wrap: (() => {
      const node = document.querySelector("#view .mo-providers").closest(".tablewrap");
      return node.scrollWidth - node.clientWidth;
    })(),
  }));
  check(`models ${size.width}: the providers table never scrolls sideways`,
    wide.page <= 1 && wide.wrap <= 1, JSON.stringify(wide));
  await openSidebar(page, "claude");
  await page.click("[data-model-request='claude']");
  await page.waitForTimeout(700);
  const sidebar = await oneLine(page, "#drawer .mo-list");
  check(`models ${size.width}: every sidebar list row is one line`,
    sidebar.found && sidebar.count >= 6 && sidebar.tallest - sidebar.shortest <= 2 && sidebar.tallest <= 44
    && sidebar.wrapped.length === 0, JSON.stringify(sidebar).slice(0, 300));
  const drawer = await page.evaluate(() => {
    const body = document.getElementById("drawerBody");
    const wrap = body.querySelector(".mo-listwrap");
    return {
      body: body.scrollWidth - body.clientWidth,
      wrap: wrap.scrollWidth - wrap.clientWidth,
      page: document.documentElement.scrollWidth - window.innerWidth,
    };
  });
  check(`models ${size.width}: the sidebar never scrolls sideways`,
    drawer.body <= 1 && drawer.wrap <= 1 && drawer.page <= 1, JSON.stringify(drawer));
  check(`models ${size.width}: nothing threw on long values`, thrown.length === 0, thrown[0]);
  await context.close();
}

/* The whole road against the stub's own routes, nothing held or answered here: a save writes
   the stub's catalog, the table reads it back, and the route refuses the two things the page
   refuses to send. */
{
  const { page, context, thrown } = await open();
  await openSidebar(page, "codex");
  await page.fill("[data-model-name='codex']", "gpt-6-astra");
  await page.click("[data-model-name-add='codex']");
  await page.click("[data-model-save='codex']");
  await page.waitForTimeout(1500);
  const cell = await page.evaluate(() => document.querySelector("[data-model-count='codex']").textContent);
  const rows = await (await fetch(`${BASE}/api/engines`)).json();
  const codex = rows.find((row) => row.id === "codex") || {};
  check("models: a save through the stub writes models_on, and the table reads it back",
    // gpt-6-luna is there too: the held save above was passed on to this same stub.
    JSON.stringify(codex.models_on) === JSON.stringify(["gpt-5-codex", "gpt-6-luna", "gpt-6-astra"])
    && cell === "3 on",
    `${JSON.stringify(codex.models_on)} ${cell}`);
  const post = async (body) => {
    const answer = await fetch(`${BASE}/api/models/select`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const payload = (await answer.json()) || {};
    return { status: answer.status, said: payload.error || "", note: payload.cost_note || "", model: payload.model || "" };
  };
  const noted = await post({ id: "claude", on: ["fable"], off: [], confirm_cost: [] });
  check("models: the route refuses a noted model that confirm_cost does not name, with the note",
    noted.status === 400 && /usage credits/.test(noted.said), JSON.stringify(noted));
  check("models: and names the note and the model, so the page can ask and send again",
    /usage credits/.test(noted.note) && noted.model === "fable", JSON.stringify(noted));
  const full = await post({ id: "claude", on: ["claude-fable-5-1"], off: [], confirm_cost: [] });
  check("models: and a full id its rule covers, not only the alias",
    full.status === 400 && /usage credits/.test(full.said), JSON.stringify(full));
  const deflt = await post({ id: "claude", on: [], off: ["opus"], confirm_cost: [] });
  check("models: and the default model in off",
    deflt.status === 400 && /default model/.test(deflt.said), JSON.stringify(deflt));
  check("models: nothing threw on the stub's own road", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------ adding a provider */

/* Step one is the choice of service. A preset already in this farm's catalog is shown and not
   choosable: adding the same service twice writes a second entry the farm then has to tell
   apart. */
{
  const { page, context, thrown, sent } = await open({ view: "machine" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  const presets = await page.evaluate(() => {
    const host = document.getElementById("drawer");
    const nodes = [...host.querySelectorAll("[data-preset]")];
    return {
      count: nodes.length,
      radios: nodes.every((node) => node.getAttribute("role") === "radio"),
      off: nodes.filter((node) => node.disabled).map((node) => node.getAttribute("data-preset")),
      alreadySaid: nodes.filter((node) => /already added/.test(node.innerText))
        .map((node) => node.getAttribute("data-preset")),
      terms: nodes.filter((node) => /safe headless|check the terms|not permitted/.test(node.innerText)).length,
      risky: nodes.filter((node) => /check the terms/.test(node.innerText))
        .map((node) => node.getAttribute("data-preset")),
      text: host.innerText,
    };
  });
  const served = (await (await fetch(`${BASE}/api/models/presets`)).json()).length;
  check("machine: the dialog draws a card per service", presets.count === served
    && served >= 6 && presets.radios, `${served} served ${JSON.stringify(presets).slice(0, 200)}`);
  check("machine: a service already in the catalog is said to be, and cannot be picked",
    presets.off.includes("claude") && presets.alreadySaid.includes("claude"),
    `off: ${presets.off.join(", ")} said: ${presets.alreadySaid.join(", ")}`);
  check("machine: every choosable service says whether it is safe to run headless",
    presets.terms + presets.off.length >= presets.count, JSON.stringify(presets).slice(0, 200));
  check("machine: and a service whose terms forbid a farm says so",
    presets.risky.length > 0 || presets.off.includes("demo-strict"), presets.risky.join(", "));
  check("machine: every card says how that service is paid for",
    /An API key, billed per token/.test(presets.text)
    && /Runs on this machine/.test(presets.text), presets.text.slice(0, 200));

  /* A service behind a key: the command that takes it is named, and the page says out loud
     that the key does not pass through it. */
  await page.click("#drawer [data-preset='democli']");
  await page.waitForTimeout(400);
  const key = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    return {
      text: host.innerText,
      command: host.querySelector("[data-model-auth]") ? host.querySelector("[data-model-auth]").textContent : "",
      variant: host.querySelector("[data-model-variant]") ? host.querySelector("[data-model-variant]").value : "",
      name: host.querySelector("[data-model-id]") ? host.querySelector("[data-model-id]").value : "",
      fields: host.querySelectorAll("input, select").length,
    };
  });
  check("machine: a key service names the command that takes the key",
    key.command === "fleet models auth democli", key.command);
  check("machine: and says a key never goes through this page",
    /A key never goes through this page/.test(key.text)
    && /Paste the key when it asks/.test(key.text), key.text.slice(0, 400));
  check("machine: the name is filled in from the preset and the variant is offered",
    key.name === "democli" && key.variant === "demo-large", JSON.stringify(key).slice(0, 160));
  check("machine: and the dialog asks for no key of its own",
    !/password/.test(key.text) && key.fields <= 2, JSON.stringify(key).slice(0, 160));

  /* A local service: two commands, nothing paid, no key at all. */
  await page.click("#drawer [data-preset='demo-local']");
  await page.waitForTimeout(400);
  const local = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    return {
      install: host.querySelector("[data-model-install]") ? host.querySelector("[data-model-install]").textContent : "",
      pull: host.querySelector("[data-model-pull]") ? host.querySelector("[data-model-pull]").textContent : "",
      auth: Boolean(host.querySelector("[data-model-auth]")),
      text: host.innerText,
    };
  });
  check("machine: a local service shows the install and the pull, and asks for no key",
    /install.sh/.test(local.install) && local.pull === "demolocal pull demo-7b"
    && local.auth === false, JSON.stringify(local).slice(0, 200));
  check("machine: and says nothing is paid for it",
    /Nothing is paid/.test(local.text), local.text.slice(0, 200));

  /* Registering sends the preset, the name and the variant, and nothing else. */
  await page.click("#drawer [data-preset='democli']");
  await page.waitForTimeout(300);
  await page.click("[data-model-register]");
  await page.waitForTimeout(1200);
  const add = sent.filter((row) => row.url.endsWith("/api/models/add"));
  const body = add.length ? JSON.parse(add[0].body || "{}") : {};
  check("machine: Register posts the preset, the name and the variant", add.length === 1
    && body.preset === "democli" && body.id === "democli" && body.variant === "demo-large",
    JSON.stringify(body));
  check("machine: and the body carries no key, by any name",
    !Object.keys(body).some((field) => /key|secret|token/i.test(field))
    && !/sk-|AIza/.test(add[0] ? add[0].body : ""), JSON.stringify(body));
  check("machine: no request this page ever sends carries a key",
    sent.every((row) => !/"key"\s*:/.test(row.body || "")),
    sent.map((row) => row.url).join(" "));
  const done = await page.evaluate(() => document.getElementById("drawerBody").innerText);
  check("machine: the dialog then shows what the farm says about the new row",
    /in the catalog/.test(done) && /Needs a key/.test(done), done.slice(0, 300));
  /* The last step of a key service is not a dead end: the one command that finishes the job is
     on it, in words, and Test is live so the person can prove the key landed without leaving. */
  const last = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    const command = host.querySelector("[data-model-auth]");
    const test = host.querySelector("[data-model-test]");
    return {
      command: command ? command.textContent : "",
      said: host.innerText,
      test: Boolean(test) && !test.disabled,
    };
  });
  check("machine: a model that needs a key is told the command, in a terminal, then Test",
    last.command === "fleet models auth democli" && /then press Test/.test(last.said),
    JSON.stringify(last).slice(0, 240));
  check("machine: and Test can be pressed on that step", last.test === true,
    JSON.stringify(last).slice(0, 160));
  check("machine: and offers the door", /Done/.test(done), done.slice(0, 300));
  check("machine: nothing threw anywhere in the add dialog", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The presets are a static list one dialog reads. Left in the page's watch list they were
   asked for again on every tick for as long as Machine was open, which is a request every three
   seconds for a list that cannot change. */
{
  const { page, context, thrown, pulled } = await open({ view: "machine" });
  const asked = () => pulled.filter((url) => url.includes("/api/models/presets")).length;
  await page.click("[data-add-model]");
  await page.waitForTimeout(1400);
  const opened = asked();
  await page.click("#drawerClose");
  await page.waitForTimeout(800);
  const atClose = asked();
  await page.waitForTimeout(8000);
  check("machine: the presets are read when the dialog opens", opened >= 1, String(opened));
  check("machine: and are not asked for again once it is shut", asked() === atClose,
    `${atClose} by the time it shut, ${asked()} eight seconds later`);
  check("machine: nothing threw around the closed dialog", thrown.length === 0, thrown[0]);
  await context.close();
}

/* murmur ships two engines and a farm usually has both, so step one of the dialog can be a row
   of cards none of which can be picked. It then says why, and where another engine comes from;
   while any card can be picked it says nothing of the kind. */
{
  const every = (await (await fetch(`${BASE}/api/models/presets`)).json())
    .map((row) => ({ ...row, added: true }));
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: { "/api/models/presets": JSON.stringify(every) },
  });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  const seen = await page.evaluate(() => {
    const node = document.querySelector("#drawer [data-model-all-added]");
    const cards = [...document.querySelectorAll("#drawer [data-preset]")];
    return {
      said: node ? node.textContent : "",
      cards: cards.length,
      off: cards.filter((card) => card.disabled).length,
    };
  });
  check("machine: when every preset is already added, step one says so",
    /Every engine murmur ships is already in this farm's catalog/.test(seen.said)
    && /fleet\/lib\/model_presets\.py/.test(seen.said) && /CONTRIBUTING\.md/.test(seen.said)
    && seen.cards === every.length && seen.off === seen.cards, JSON.stringify(seen));
  check("machine: nothing threw on a dialog with nothing to pick", thrown.length === 0, thrown[0]);
  await context.close();

  for (const state of ["ready", "empty"]) {
    const other = await open({ view: "machine", state });
    await other.page.click("[data-add-model]");
    await other.page.waitForTimeout(700);
    const quiet = await other.page.evaluate(() => ({
      note: Boolean(document.querySelector("#drawer [data-model-all-added]")),
      pickable: [...document.querySelectorAll("#drawer [data-preset]")].filter((card) => !card.disabled).length,
    }));
    check(`machine: while a preset can still be picked (${state}), there is no such note`,
      quiet.note === false && quiet.pickable > 0, JSON.stringify(quiet));
    check(`machine: nothing threw on the ${state} dialog`, other.thrown.length === 0, other.thrown[0]);
    await other.context.close();
  }
}

/* A local runner's pull command is the preset's own (pull_hint), not one this page builds. A
   line it built, "{bin} pull {variant}", would be right for one runner by luck and wrong for the
   next local runner a contributor adds. */
{
  const own = [{
    id: "lmstudio", label: "LM Studio", color: "#8b949e", kind: "local", tos_kind: "safe",
    engine: "generic", bin: "lms", install_hint: "brew install lmstudio",
    pull_hint: "lms get <variant> --yes", auth_env: "", run: "{bin} run {variant} {task}",
    health: "What is 17 plus 25? Reply with the number only.", tos: "runs on this machine, so there are no service terms",
    access: "Runs on this machine. Nothing is paid.", variants: ["llama3.1", "qwen2.5-coder"],
    docs: "https://example.invalid/docs/lmstudio", added: false,
  }];
  const { page, context, thrown } = await open({
    view: "machine",
    state: "empty",
    overrides: { "/api/models/presets": JSON.stringify(own) },
  });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='lmstudio']");
  await page.waitForTimeout(400);
  const seen = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    const node = host.querySelector("[data-model-pull]");
    return { pull: node ? node.textContent : "", install: host.querySelector("[data-model-install]").textContent };
  });
  check("machine: the pull command is the preset's own, with the chosen model in it",
    seen.pull === "lms get llama3.1 --yes", JSON.stringify(seen));
  check("machine: and the install command is the preset's own too",
    seen.install === "brew install lmstudio", JSON.stringify(seen));
  check("machine: nothing threw on a local preset", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The terms pill is the server's own classification of its terms sentence, in one word. The
   page used to read the sentence itself and call anything it did not recognise "safe headless",
   which put a green pill on a command whose terms nobody here has read. The three cards are the
   stub's fictional contributed presets, one per word. */
{
  // An empty catalog, so every card draws its terms pill rather than "already added".
  const { page, context, thrown } = await open({ view: "machine", state: "empty" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  const said = await page.evaluate(() => {
    const out = {};
    for (const node of document.querySelectorAll("#drawer [data-preset]")) {
      const badge = node.querySelector(".pill-text");
      out[node.getAttribute("data-preset")] = badge ? badge.textContent : "";
    }
    return out;
  });
  check("machine: a service the server calls safe wears the safe pill",
    said.democli === "safe headless" && said["demo-local"] === "safe headless", JSON.stringify(said));
  check("machine: a service whose terms refuse a farm says so, and is not called safe",
    said["demo-strict"] === "not permitted", JSON.stringify(said));
  check("machine: and a service nobody has read the terms of says check the terms",
    said["demo-plain"] === "check the terms", JSON.stringify(said));
  await context.close();

  /* A farm on a server that sends the sentence and no classification. The words of the
     sentence decide, and a sentence that is neither is a thing to read, not to trust. */
  const own = [
    { id: "one", label: "Refuses it", kind: "key", engine: "generic", bin: "one",
      install_hint: "", pull_hint: "", auth_env: "ONE_API_KEY", run: "{bin} -p {task}",
      health: "What is 17 plus 25? Reply with the number only.", tos: "its terms forbid non-interactive use",
      access: "An API key.", variants: [], docs: "", added: false },
    { id: "two", label: "Documents it", kind: "key", engine: "generic", bin: "two",
      install_hint: "", pull_hint: "", auth_env: "TWO_API_KEY", run: "{bin} -p {task}",
      health: "What is 17 plus 25? Reply with the number only.", tos: "a documented non-interactive mode",
      access: "An API key.", variants: [], docs: "", added: false },
    { id: "three", label: "Says nothing", kind: "key", engine: "generic", bin: "three",
      install_hint: "", pull_hint: "", auth_env: "THREE_API_KEY", run: "{bin} -p {task}",
      health: "What is 17 plus 25? Reply with the number only.", tos: "", access: "An API key.", variants: [],
      docs: "", added: false },
  ];
  const second = await open({
    view: "machine",
    state: "empty",
    overrides: { "/api/models/presets": JSON.stringify(own) },
  });
  await second.page.click("[data-add-model]");
  await second.page.waitForTimeout(700);
  const older = await second.page.evaluate(() => {
    const out = {};
    for (const node of document.querySelectorAll("#drawer [data-preset]")) {
      const badge = node.querySelector(".pill-text");
      out[node.getAttribute("data-preset")] = badge ? badge.textContent : "";
    }
    return out;
  });
  check("machine: a server that sends no classification is read from its own sentence",
    older.one === "not permitted" && older.two === "safe headless"
    && older.three === "check the terms", JSON.stringify(older));
  check("machine: nothing threw on the terms pills",
    thrown.length === 0 && second.thrown.length === 0, thrown[0] || second.thrown[0]);
  await second.context.close();
}

/* A key engine is authenticated under the name it is given, so step 3 has no command to show
   while the name is empty. Falling back to the preset's id printed a runnable-looking command
   for a model that would not exist under that name. */
{
  const { page, context, thrown } = await open({ view: "machine", state: "empty" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='democli']");
  await page.waitForTimeout(400);
  await page.fill("#drawer [data-model-id]", "");
  // Typing repaints nothing by itself; the page's own tick does.
  await page.waitForTimeout(3500);
  const bare = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    return {
      command: host.querySelector("[data-model-auth]") ? host.querySelector("[data-model-auth]").textContent : "",
      said: host.innerText,
    };
  });
  check("machine: a key service with its name cleared shows no auth command",
    bare.command === "" && /Name it, and it appears here/.test(bare.said),
    JSON.stringify(bare).slice(0, 240));
  check("machine: and never prints one built from the preset's id",
    !/fleet models auth democli/.test(bare.said), bare.said.slice(0, 300));
  await page.fill("#drawer [data-model-id]", "mine");
  await page.waitForTimeout(3500);
  const named = await page.evaluate(() => {
    const node = document.querySelector("#drawerBody [data-model-auth]");
    return node ? node.textContent : "";
  });
  check("machine: and shows it under that name once it is typed",
    named === "fleet models auth mine", named || "no command");
  check("machine: nothing threw on a renamed key service", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The name rule the dialog teaches is the farm's own. The page used to accept a capital, a
   dot and forty characters, and every one of those is refused by lib/models.py, which writes
   the name as a table in this farm's catalog. */
{
  // An empty catalog, because every preset is choosable there and the cases above have already
  // written democli into this stub's catalog.
  const { page, context, thrown, sent } = await open({ view: "machine", state: "empty" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='democli']");
  await page.waitForTimeout(300);
  await page.fill("#drawer [data-model-id]", "Democli");
  await page.click("[data-model-register]");
  await page.waitForTimeout(600);
  const said = await page.evaluate(() => {
    const node = document.querySelector("#drawerBody .m-bad");
    return node ? node.innerText : "";
  });
  check("machine: a name the farm would refuse is refused here, in the farm's own rule",
    /lower case letters/.test(said) && /2 to 31 characters/.test(said), said.slice(0, 200));
  check("machine: and nothing was written to the catalog",
    !sent.some((row) => row.url.endsWith("/api/models/add")),
    sent.map((row) => row.url).join(" "));
  /* And the rule behind the page is the same rule, so a page that drifts is caught by the
     route rather than by a farm nobody is watching. */
  const refused = [];
  for (const name of ["Democli", "my.model", "a", "g".repeat(32)]) {
    const answer = await fetch(`${BASE}/api/models/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset: "democli", id: name }),
    });
    refused.push({ name, status: answer.status, said: (await answer.json()).error || "" });
  }
  check("machine: the route behind the page keeps the same rule",
    refused.every((row) => row.status === 400 && /lower case letters/.test(row.said)),
    JSON.stringify(refused).slice(0, 300));
  check("machine: nothing threw on a refused name", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The add route answers {"model": row}, and that row is what the last step draws until the
   table catches up. Reading it off the top level of the answer left the step saying "this farm
   has not listed it back yet" on every real farm whose refresh lagged by a tick. */
{
  const seed = {
    id: "seeded", label: "A seeded model", engine: "generic", source: "added",
    status: "needs_key", enabled: false, installed: true, path: "/usr/bin/seeded",
    command: "seeded", access: "An API key, held on the farm.", auth_env: "SEEDED_API_KEY",
    run: "{bin} -p {task}", last_test: null, install_hint: "", health: "unchecked",
  };
  // An empty farm, so /api/engines never lists the new row and the seed is the only source.
  const { page, context, thrown } = await open({
    view: "machine",
    state: "empty",
    overrides: {
      "/api/models/add": (handler) => handler.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ model: seed }),
      }),
    },
  });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='democli']");
  await page.waitForTimeout(300);
  await page.fill("#drawer [data-model-id]", "seeded");
  await page.click("[data-model-register]");
  await page.waitForTimeout(1300);
  const said = await page.evaluate(() => document.getElementById("drawerBody").innerText);
  check("machine: the row the add route answered is the row the last step draws",
    /A seeded model is in the catalog/.test(said) && /Needs a key/.test(said)
    && !/has not listed it back yet/.test(said), said.slice(0, 300));
  check("machine: nothing threw on the answer the server actually sends",
    thrown.length === 0, thrown[0]);
  await context.close();
}

/* The route refuses a credential by the NAME of the field, whatever its spelling, and a
   credential written into a command line. This page sends neither, and the check is here so that
   a page which started to would fail against this stub before it reached a farm: the stub used
   to refuse the exact spelling "key" alone, which is weaker than the server it stands in for. */
{
  const post = async (body) => {
    const answer = await fetch(`${BASE}/api/models/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { status: answer.status, said: ((await answer.json()) || {}).error || "" };
  };
  const fields = ["key", "api_key", "apikey", "apiKey", "API_KEY", "x-api-key", "secret",
    "credential", "token", "password"];
  const answers = [];
  for (const field of fields) {
    answers.push({
      field,
      ...await post({ preset: "democli", id: "keyed", [field]: "sk-abcdefgh12345678" }),
    });
  }
  check("machine: a credential in the body is refused by any name it goes by",
    answers.every((row) => row.status === 400
      && /A key never goes through this page/.test(row.said)),
    JSON.stringify(answers.filter((row) => row.status !== 400)).slice(0, 300));
  check("machine: and the refusal names the command that does take one",
    answers.every((row) => /fleet models auth keyed/.test(row.said)),
    answers[0].said);
  const written = await post({ preset: "democli", id: "pasted", bin: "mine",
    run: "{bin} --api-key sk-abcdefgh12345678 -p {task}" });
  check("machine: a key written into the command line is refused as well",
    written.status === 400 && /take it out of the command line/.test(written.said),
    JSON.stringify(written));
  const kept = await (await fetch(`${BASE}/api/engines`)).json();
  check("machine: and none of those refusals wrote a row",
    kept.every((row) => row && row.id !== "keyed" && row.id !== "pasted"),
    kept.map((row) => (row || {}).id).join(","));
}

/* The last step of a model that can be run: Test and Switch on, both there, and the row asked
   for again on its own clock while the test is in flight. The page's tick is three seconds and
   only repaints, so a test that answers in four would otherwise sit on screen as "asking". */
{
  const { page, context, thrown, pulled } = await open({
    view: "machine",
    overrides: {
      "/api/models": (handler) => {
        if (handler.request().method() !== "POST") return handler.continue();
        return new Promise((resolve) => setTimeout(resolve, 6000)).then(() => handler.fulfill({
          status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }),
        }));
      },
    },
  });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='demo-local']");
  await page.waitForTimeout(300);
  await page.click("[data-model-register]");
  await page.waitForTimeout(1200);
  const offered = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    return {
      test: Boolean(host.querySelector("[data-model-test]")),
      swtch: Boolean(host.querySelector("[data-model-switch]")),
      done: Boolean(host.querySelector("[data-model-done]")),
      text: host.innerText,
    };
  });
  check("machine: a model that can be run is offered Test and a switch at once",
    offered.test && offered.swtch && offered.done, JSON.stringify(offered).slice(0, 200));
  const before = pulled.filter((url) => url.includes("/api/engines")).length;
  // The new row is in the table as well as in the dialog, and the table is behind the drawer.
  await page.click("#drawer [data-model-test]");
  await page.waitForTimeout(700);
  const during = await page.evaluate(() => document.getElementById("drawerBody").innerText);
  check("machine: and says out loud that it is waiting for the provider",
    /Asking the provider to answer/.test(during), during.slice(0, 300));
  await page.waitForTimeout(5600);
  const polls = pulled.filter((url) => url.includes("/api/engines")).length - before;
  // Six seconds of a held test. The page's own three second tick can ask twice in that window
  // and no more, so a third ask can only have come from the dialog's own two second clock.
  check("machine: the row is asked for again every two seconds while the test runs",
    polls >= 3, `${polls} asks in six seconds`);
  check("machine: nothing threw around the test in the dialog", thrown.length === 0, thrown[0]);
  await context.close();
  // Taken out again, so the remove case below can add the same local preset through the dialog.
  await fetch(`${BASE}/api/models/remove`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: "demo-local" }),
  });
}

/* Remove says what it deletes before it deletes it, and a model that shipped with the farm is
   never offered it at all. */
{
  const { page, context, thrown, posted } = await open({ view: "machine" });
  await page.click("[data-model-remove='demo-plain']");
  await page.waitForTimeout(500);
  const asked = await page.evaluate(() => document.querySelector("#view .m-confirm").innerText);
  check("machine: Remove asks first, naming the entry and the key it deletes",
    /Remove Demo Plain\?/.test(asked) && /deleted from this farm's catalog/.test(asked)
    && /key stored/.test(asked), asked.slice(0, 300));
  check("machine: and the key by the name of the variable that holds it",
    /DEMO_PLAIN_API_KEY/.test(asked), asked.slice(0, 300));
  await page.click("#view .m-confirm .ghost-button");
  await page.waitForTimeout(400);
  check("machine: keeping it sends nothing",
    !posted.some((url) => url.endsWith("/api/models/remove")), posted.join(" "));

  /* And the whole way through on a model this run added, so the table is read back afterwards
     rather than trusted. */
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='demo-local']");
  await page.waitForTimeout(300);
  await page.click("[data-model-register]");
  await page.waitForTimeout(1200);
  await page.click("[data-model-done]");
  await page.waitForTimeout(1200);
  const added = await page.evaluate(() => Boolean(document.querySelector("[data-model-remove='demo-local']")));
  check("machine: a model this operator added can be removed", added, "no Remove on the new row");
  await page.click("[data-model-remove='demo-local']");
  await page.waitForTimeout(400);
  await page.click("[data-confirm='remove-model:demo-local']");
  await page.waitForTimeout(1400);
  const after = await page.evaluate(() => ({
    row: Boolean(document.querySelector("[data-model-open='demo-local']")),
    shipped: Boolean(document.querySelector("[data-model-remove='claude']")),
  }));
  check("machine: the post goes, and the table is read back without that row",
    posted.some((url) => url.endsWith("/api/models/remove")) && after.row === false,
    JSON.stringify(after));
  check("machine: a model that shipped with the farm is never offered Remove",
    after.shipped === false, JSON.stringify(after));
  check("machine: nothing threw around remove", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Any row this farm added can be removed, including one it added before this run. The stub knew
   only the rows added in the same process, so the fixture rows carrying source "added" wore a
   Remove button that answered "there is no model with that name" the first time it was pressed. */
{
  const { page, context, thrown, posted } = await open({ view: "machine" });
  await page.click("[data-model-remove='demo-strict']");
  await page.waitForTimeout(500);
  await page.click("[data-confirm='remove-model:demo-strict']");
  await page.waitForTimeout(1500);
  const seen = await page.evaluate(() => {
    const models = [...document.querySelectorAll("#view .section")]
      .find((item) => item.innerText.startsWith("Models"));
    return {
      row: Boolean(document.querySelector("[data-model-open='demo-strict']")),
      said: models ? models.innerText : "",
    };
  });
  check("machine: a row this farm added is removed, whenever it was added",
    seen.row === false && posted.some((url) => url.endsWith("/api/models/remove")),
    JSON.stringify(seen).slice(0, 240));
  check("machine: and the card says nothing went wrong",
    !/could not be removed/.test(seen.said) && !/no such model/.test(seen.said),
    seen.said.slice(0, 240));
  /* And a row that came with the farm is refused by the route, in the server's own words, which
     is why the page never offers Remove on one. */
  const answer = await fetch(`${BASE}/api/models/remove`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: "claude" }),
  });
  const said = ((await answer.json()) || {}).error || "";
  check("machine: a row that came with fleet is refused, with what to do instead",
    answer.status === 400 && /came with fleet/.test(said), `${answer.status} ${said}`);
  check("machine: nothing threw around removing a fixture row", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A removal the farm refuses is answered under the models card, and nowhere else. The two
   footers used to read one field, so a model that would not go printed its sentence under
   Accounts as well, about accounts that had nothing to do with it. */
{
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: {
      "/api/models/remove": (handler) => handler.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ error: "demo-plain is held open by a lane that is still running" }),
      }),
    },
  });
  await page.click("[data-model-remove='demo-plain']");
  await page.waitForTimeout(500);
  await page.click("[data-confirm='remove-model:demo-plain']");
  await page.waitForTimeout(1000);
  const said = await page.evaluate(() => {
    const sections = [...document.querySelectorAll("#view .section")];
    const words = (head) => {
      const node = sections.find((item) => item.innerText.startsWith(head));
      return node ? node.innerText : "";
    };
    return { models: words("Models"), accounts: words("Accounts") };
  });
  check("machine: a refused model removal is answered under the models card",
    /still running/.test(said.models), said.models.slice(0, 240));
  check("machine: and never under the accounts card",
    said.accounts.length > 0 && !/still running/.test(said.accounts),
    said.accounts.slice(0, 240));
  check("machine: nothing threw on a refused removal", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The default model is on whether or not it was saved: the sidebar ticks and locks it and a lane
   spawned without a model runs it, so the table counts it too (the end-to-end run saw "None on"). */
{
  const { page, context, thrown } = await open({
    overrides: { "/api/engines": engines({ codex: { models_on: [], default_model: "gpt-6-sol" } }) },
  });
  const cell = await page.evaluate(() => {
    const node = document.querySelector("[data-model-count='codex']");
    return node ? { text: node.textContent, title: node.getAttribute("title") } : null;
  });
  check("models: the default model counts as on in the table",
    Boolean(cell) && cell.text === "1 on" && cell.title === "gpt-6-sol", JSON.stringify(cell));
  check("models: nothing threw counting the default", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Codex signs in through a page on port 1455 of the farm, so its sidebar gives the command that
   forwards the port, the one the Accounts row gives, not Claude's /login steps. */
{
  const { page, context, thrown } = await open({
    overrides: { "/api/engines": engines({ codex: { status: "failing", health: "fail" } }) },
  });
  await openSidebar(page, "codex");
  const seen = await page.evaluate(() => {
    const host = document.getElementById("drawerBody") || document;
    const node = host.querySelector("[data-model-login]");
    return { login: node ? node.textContent : "", text: host.innerText || "" };
  });
  check("models: the Codex sidebar gives the codex login with the forwarded port",
    seen.login === "ssh -L 1455:localhost:1455 -t farm codex login" && !/type \/login/.test(seen.text),
    JSON.stringify(seen).slice(0, 240));
  check("models: nothing threw in the Codex sidebar", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A subscription is logged in, not keyed, so its third step is a login command and the steps
   that go with it. Every preset is choosable on a farm with an empty catalog, which is the one
   place this branch can be reached. */
{
  const { page, context, thrown } = await open({ view: "machine", state: "empty" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='claude']");
  await page.waitForTimeout(400);
  const seen = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    return {
      login: host.querySelector("[data-model-login]") ? host.querySelector("[data-model-login]").textContent : "",
      auth: Boolean(host.querySelector("[data-model-auth]")),
      steps: host.querySelectorAll("ol li").length,
      text: host.innerText,
    };
  });
  check("machine: an empty catalog offers every service, including the shipped ones",
    /Claude Code/.test(seen.text), seen.text.slice(0, 160));
  check("machine: a subscription shows the login command and its steps",
    seen.login === "ssh -t farm claude" && seen.steps >= 4 && seen.auth === false,
    JSON.stringify(seen).slice(0, 200));
  check("machine: and says the login happens in a terminal, not here",
    /not on this page/.test(seen.text) && /\/login/.test(seen.text), seen.text.slice(0, 300));
  check("machine: nothing threw on a farm with no models", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Codex in the same dialog: its third step is the codex login with the forwarded port, not
   Claude's /login steps (the end-to-end run's defect 6, on its second screen). */
{
  const { page, context, thrown } = await open({ view: "machine", state: "empty" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='codex']");
  await page.waitForTimeout(400);
  const seen = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    const node = host.querySelector("[data-model-login]");
    return { login: node ? node.textContent : "", text: host.innerText };
  });
  check("machine: adding Codex gives the codex login with the forwarded port",
    seen.login === "ssh -L 1455:localhost:1455 -t farm codex login" && !/type \/login/.test(seen.text),
    JSON.stringify(seen).slice(0, 220));
  check("machine: nothing threw adding Codex", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A page with no write token draws the models section in full and switches every control in it
   off, drawer included, with the server's own sentence. A read-only dashboard is legitimate and
   must not look broken. */
{
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: { "/api/access": READ_ONLY },
  });
  const table = await page.evaluate(() => {
    const controls = [...document.querySelectorAll("#view [data-model-switch], "
      + "#view [data-model-test], #view [data-model-remove], #view [data-add-model]")];
    return {
      total: controls.length,
      live: controls.filter((node) => !node.disabled).length,
      reasons: controls.filter((node) => /only read/.test(node.title || "")).length,
      rows: document.querySelectorAll("#view .mo-providers tbody tr").length,
      names: [...document.querySelectorAll("#view [data-model-open]")].filter((node) => !node.disabled).length,
    };
  });
  check("machine: a read-only page still draws every model row", table.rows >= 5,
    JSON.stringify(table));
  check("machine: and switches every model control off, with the reason on each",
    table.total > 0 && table.live === 0 && table.reasons === table.total, JSON.stringify(table));
  check("machine: reading a model is still allowed", table.names === table.rows,
    JSON.stringify(table));
  await page.click("[data-model-open='demo-plain']");
  await page.waitForTimeout(500);
  const drawer = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll("#drawer [data-model-switch], "
      + "#drawer [data-model-test], #drawer [data-model-remove]")];
    return {
      total: nodes.length,
      live: nodes.filter((node) => !node.disabled).length,
      text: document.getElementById("drawerBody").innerText,
    };
  });
  check("machine: the drawer's copies of the actions are off too",
    drawer.total === 3 && drawer.live === 0, JSON.stringify(drawer).slice(0, 160));
  check("machine: and the reason is written out where the actions are",
    /opened without the dashboard token/.test(drawer.text), drawer.text.slice(-200));
  check("machine: nothing threw on the read-only models section", thrown.length === 0, thrown[0]);
  await context.close();
}

await browser.close();
stub.kill();

const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

/* The Projects section when the page may not write, when a person pastes the wrong thing, and
   when a table cell holds more than fits (design record github-projects.md, sections 3 to 5).
   Every POST body is asserted exactly, from what the stub recorded, and the GitHub snapshot is
   proved to be read every three seconds only while the Connect dialog is open.

   The view is opened through the stub's harness page, the same shell around the same modules
   that index.html puts it in. Nothing here reaches GitHub: the stub answers every route. */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./test_playwright.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 7981);
const BASE = `http://127.0.0.1:${PORT}`;
const ONLY = process.env.ONLY || "";

const results = [];
function check(name, passed, detail) {
  if (ONLY && !name.includes(ONLY)) return;
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
    ...process.env, STUB_JOB_SECONDS: "2", STUB_GH_FLIP_SECONDS: "5",
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

{
  const env = await (await fetch(`${BASE}/stub/github/env`)).json();
  const inside = (value) => typeof value === "string" && value.startsWith(SCRATCH + path.sep);
  check("the stub runs with a temporary HOME, FLEET_STATE and FLEET_CONFIG",
    inside(env.home) && inside(env.fleet_state) && inside(env.fleet_config), JSON.stringify(env));
}

/* Every rule in projects.css starts from a p- class, so no sibling lane's class can collide. */
{
  const css = fs.readFileSync(path.join(HERE, "static", "projects.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const loose = [];
  for (const [, selectors] of css.matchAll(/([^{}]+)\{/g)) {
    if (selectors.trim().startsWith("@")) continue;
    for (const selector of selectors.split(",")) {
      const first = selector.trim().split(/\s+|>|\+|~/)[0];
      const classes = [...first.matchAll(/\.([\w-]+)/g)].map((found) => found[1]);
      if (!classes.some((name) => name.startsWith("p-"))) loose.push(selector.trim());
    }
  }
  check("css: every rule in projects.css starts from a p- class", loose.length === 0, loose.join(" | "));
}

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();

const READ_ONLY_REASON = "This page was opened without the dashboard token, so it can only read.";
const READ_ONLY = JSON.stringify({
  writable: false, reason: READ_ONLY_REASON, token_required: true, loopback: true,
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function sent() {
  return (await (await fetch(`${BASE}/stub/github/sent`)).json()).sent;
}

/** The bodies recorded since `from`, as [path, body] pairs. */
async function sentSince(from) {
  return (await sent()).slice(from).map((row) => [row.path, row.body]);
}

async function open({ state = "ready", gh = "", long = false, size = { width: 1440, height: 1000 }, overrides = {}, clock = false } = {}) {
  const context = await browser.newContext({ viewport: size });
  const page = await context.newPage();
  /* A simulated clock, for waits that run for minutes on the page and must not in the test. */
  if (clock) await page.clock.install();
  const thrown = [];
  const requests = [];
  page.on("pageerror", (error) => thrown.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    requests.push({ method: request.method(), path: url.pathname, at: Date.now(), body: request.postData() || "" });
  });
  for (const [route, body] of Object.entries(overrides)) {
    await page.route((url) => url.pathname === route, (handler) => {
      if (typeof body === "function") return body(handler);
      return handler.fulfill({ status: 200, contentType: "application/json", body });
    });
  }
  const query = `state=${state}${gh ? `&gh=${gh}` : ""}${long ? "&long=1" : ""}`;
  await page.goto(`${BASE}/harness?${query}#/machine`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#view [data-login-state], #view section[data-x]", { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(700);
  return { page, context, thrown, requests };
}

const sectionText = (page) => page.evaluate(() => {
  const section = [...document.querySelectorAll("#view section")]
    .find((node) => node.querySelector("h2") && node.querySelector("h2").textContent === "Projects");
  return section ? section.innerText : "";
});
const drawerText = (page) => page.evaluate(() => document.getElementById("drawerBody").innerText);

async function openImport(page) {
  await page.click("[data-import-open]");
  await page.waitForSelector("[data-repo]", { timeout: 5000 });
}

/* ------------------------------------------------------------------ Re-check */

/* Re-check keeps the strip drawn while the farm checks, and shows the new answer within
   seconds of the check ending. The end-to-end run saw the answer a minute late; the first fix
   blanked the strip into a loading skeleton for the whole check. */
{
  let phase = "before";
  let reads = 0;
  const { page, context, thrown } = await open({ gh: "no_git", overrides: {
    "/api/github": async (handler) => {
      if (handler.request().method() !== "GET") return handler.continue();
      const response = await handler.fetch();
      const json = await response.json();
      if (phase === "checking") {
        reads += 1;
        json.checking = reads < 3;
        if (reads >= 3) json.git_uses_login = true;
      }
      return handler.fulfill({ response, json });
    },
  } });
  const before = await sectionText(page);
  phase = "checking";
  const started = Date.now();
  await page.click("#view [data-github-check]");
  await page.waitForTimeout(1300);
  const during = await page.evaluate(() => Boolean(document.querySelector("#view [data-login-state]"))
    && Boolean(document.querySelector("#view [data-github-check]")));
  let gone = false;
  for (let i = 0; i < 24 && !gone; i += 1) {
    gone = !/Git on this farm does not use this login/.test(await sectionText(page));
    if (!gone) await page.waitForTimeout(500);
  }
  const took = Date.now() - started;
  check("recheck: the farm's old answer was drawn before the press",
    /Git on this farm does not use this login/.test(before), before.slice(0, 200));
  check("recheck: the strip stays drawn while the check runs, never a skeleton", during, String(during));
  check("recheck: the new answer shows within seconds of the check ending", gone && took < 9000, `${took} ms, ${reads} reads`);
  check("recheck: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A 409 means a pass is already running (almost always the five-minute one): the page waits
   for that pass's answer the same way, instead of reading once and leaving the answer to the next
   minute's read. The farm now sets "checking" for every pass, so the page sees it on a 409 too. */
{
  let phase = "before";
  let reads = 0;
  const { page, context, thrown } = await open({ gh: "no_git", overrides: {
    "/api/github/check": (handler) => handler.fulfill({ status: 409, contentType: "application/json",
      body: JSON.stringify({ error: "The GitHub connection is being checked right now; the answer arrives in a few seconds.", retry_after: 5 }) }),
    "/api/github": async (handler) => {
      if (handler.request().method() !== "GET") return handler.continue();
      const response = await handler.fetch();
      const json = await response.json();
      if (phase === "checking") {
        reads += 1;
        json.checking = reads < 3;
        if (reads >= 3) json.git_uses_login = true;
      }
      return handler.fulfill({ response, json });
    },
  } });
  phase = "checking";
  const started = Date.now();
  await page.click("#view [data-github-check]");
  let gone = false;
  for (let i = 0; i < 24 && !gone; i += 1) {
    await page.waitForTimeout(500);
    gone = !/Git on this farm does not use this login/.test(await sectionText(page));
  }
  const took = Date.now() - started;
  check("recheck 409: the answer of the pass already running shows within seconds", gone && took < 9000,
    `${took} ms, ${reads} reads`);
  check("recheck 409: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A pass can outlast 25 seconds (several GitHub calls of up to 20 seconds each), so the page
   must keep reading while "checking" is set instead of giving up after a count of reads and
   leaving the old answer until the next minute's read. */
{
  let phase = "before";
  let reads = 0;
  let pressedAt = 0;
  const { page, context, thrown } = await open({ gh: "no_git", overrides: {
    "/api/github/check": (handler) => {
      pressedAt = Date.now();
      return handler.fulfill({ status: 409, contentType: "application/json",
        body: JSON.stringify({ error: "The GitHub connection is being checked right now.", retry_after: 5 }) });
    },
    "/api/github": async (handler) => {
      if (handler.request().method() !== "GET") return handler.continue();
      const response = await handler.fetch();
      const json = await response.json();
      if (phase === "checking") {
        reads += 1;
        json.checking = Date.now() - pressedAt < 27000;
        if (!json.checking) json.git_uses_login = true;
      }
      return handler.fulfill({ response, json });
    },
  } });
  phase = "checking";
  await page.click("#view [data-github-check]");
  let gone = false;
  let took = 0;
  for (let i = 0; i < 80 && !gone; i += 1) {
    await page.waitForTimeout(500);
    gone = !/Git on this farm does not use this login/.test(await sectionText(page));
    took = Date.now() - pressedAt;
  }
  check("recheck long pass: the answer shows within seconds of a 27 second pass ending",
    gone && took > 27000 && took < 33000, `${took} ms, ${reads} reads`);
  check("recheck long pass: later reads slow down, not one a second for the whole pass",
    reads > 10 && reads < 22, `${reads} reads`);
  check("recheck long pass: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A pass may outlast any fixed wait (twenty missing-repository lookups of up to 20 seconds each),
   so the page reads for as long as the farm says "checking", then stops. The clock is simulated:
   a pass of 400 seconds runs in a few seconds, past the five minute cap the page once had. */
{
  const GET = "/api/github";
  let phase = "before";
  let checking = true;
  let simulated = 0;
  const reads = [];
  const { page, context, thrown } = await open({ gh: "no_git", clock: true, overrides: {
    "/api/github/check": (handler) => handler.fulfill({ status: 409, contentType: "application/json",
      body: JSON.stringify({ error: "The GitHub connection is being checked right now.", retry_after: 5 }) }),
    [GET]: async (handler) => {
      if (handler.request().method() !== "GET") return handler.continue();
      const response = await handler.fetch();
      const json = await response.json();
      if (phase === "checking") {
        reads.push(simulated);
        json.checking = checking;
        if (!checking) json.git_uses_login = true;
      }
      return handler.fulfill({ response, json });
    },
  } });
  /* One simulated second at a time, with a real pause so each read can land before the next. */
  const advance = async (ms) => {
    for (let done = 0; done < ms; done += 1000) {
      await page.clock.runFor(1000);
      simulated += 1000;
      await sleep(40);
    }
  };
  const stillOld = async () => /Git on this farm does not use this login/.test(await sectionText(page));
  phase = "checking";
  await page.click("#view [data-github-check]");
  await sleep(200);
  await advance(400000);
  const late = reads.filter((at) => at > 305000).length;
  check("recheck past five minutes: the page still reads while the farm says checking",
    late >= 10, `${late} reads between 305 and 400 simulated seconds, ${reads.length} in all`);
  check("recheck past five minutes: the old answer stays while the pass runs", await stillOld());
  checking = false;
  const flipped = simulated;
  let gone = false;
  while (!gone && simulated - flipped < 8000) {
    await advance(1000);
    gone = !(await stillOld());
  }
  check("recheck past five minutes: the answer shows within seconds of a 400 second pass ending",
    gone, `${simulated - flipped} simulated ms after the pass ended`);
  const settled = reads.length;
  await advance(30000);
  check("recheck past five minutes: the reads stop once a read says checking is false",
    reads.length === settled, `${reads.length - settled} reads in the next 30 simulated seconds`);
  check("recheck past five minutes: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The reads serve the strip on the Machine tab only: a reader who leaves it stops them, even
   while the farm still says "checking". */
{
  let simulated = 0;
  const reads = [];
  const { page, context, thrown } = await open({ gh: "no_git", clock: true, overrides: {
    "/api/github/check": (handler) => handler.fulfill({ status: 409, contentType: "application/json",
      body: JSON.stringify({ error: "The GitHub connection is being checked right now.", retry_after: 5 }) }),
    "/api/github": async (handler) => {
      if (handler.request().method() !== "GET") return handler.continue();
      const response = await handler.fetch();
      const json = await response.json();
      reads.push(simulated);
      json.checking = true;
      return handler.fulfill({ response, json });
    },
  } });
  const advance = async (ms) => {
    for (let done = 0; done < ms; done += 1000) {
      await page.clock.runFor(1000);
      simulated += 1000;
      await sleep(40);
    }
  };
  await page.click("#view [data-github-check]");
  await sleep(200);
  await advance(20000);
  const before = reads.length;
  await page.evaluate(() => { location.hash = "#/elsewhere"; });
  await sleep(200);
  const left = simulated;
  await advance(120000);
  const after = reads.filter((at) => at > left + 1000).length;
  check("recheck leave: the page read while the reader stayed on the Machine tab", before >= 5, `${before} reads`);
  check("recheck leave: no read of the GitHub snapshot after the reader left the Machine tab",
    after === 0, `${after} reads in 120 simulated seconds after leaving`);
  check("recheck leave: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A read already in flight when the farm answers the press was taken before it: its "checking"
   is clear and its answer is the old one. The page must not take it as the end of the check. */
{
  let phase = "before";
  let reads = 0;
  const { page, context, thrown } = await open({ gh: "no_git", overrides: {
    "/api/github/check": (handler) => handler.fulfill({ status: 202, contentType: "application/json",
      body: JSON.stringify({ ok: true, checking: true, retry_after: 60 }) }),
    "/api/github": async (handler) => {
      if (handler.request().method() !== "GET") return handler.continue();
      const response = await handler.fetch();
      const json = await response.json();
      if (phase === "slow") {
        /* The read from before the press: held until well after the press, then the old answer. */
        phase = "checking";
        await sleep(1800);
        return handler.fulfill({ response, json });
      }
      if (phase === "checking") {
        reads += 1;
        json.checking = reads < 2;
        if (reads >= 2) json.git_uses_login = true;
      }
      return handler.fulfill({ response, json });
    },
  } });
  phase = "slow";
  await page.evaluate(() => import("/static/core/api.js").then((api) => { api.refresh("/api/github"); }));
  await page.waitForTimeout(100);
  const started = Date.now();
  await page.click("#view [data-github-check]");
  let gone = false;
  for (let i = 0; i < 24 && !gone; i += 1) {
    await page.waitForTimeout(500);
    gone = !/Git on this farm does not use this login/.test(await sectionText(page));
  }
  const took = Date.now() - started;
  check("recheck in flight: a read from before the press does not end the wait", gone && took < 9000,
    `${took} ms, ${reads} reads after the press`);
  check("recheck in flight: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------ a page that may not write, and one that may */

{
  const { page, context, thrown } = await open({ overrides: { "/api/access": READ_ONLY } });
  const seen = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll("#view [data-github-check], #view [data-import-open], #view [data-remove-project]")];
    return {
      total: nodes.length,
      live: nodes.filter((node) => !node.disabled).map((node) => node.outerHTML.slice(0, 80)),
      titles: [...new Set(nodes.map((node) => node.title))],
    };
  });
  check("read-only: the strip, the head and the table have write controls to switch off",
    seen.total >= 5, `${seen.total} found`);
  check("read-only: every one of them is off", seen.live.length === 0, seen.live.join(" | "));
  check("read-only: each says why in the sentence from /api/access",
    seen.titles.length === 1 && seen.titles[0] === READ_ONLY_REASON, JSON.stringify(seen.titles));
  const body = await sectionText(page);
  check("read-only: the section says it under the table", body.includes(READ_ONLY_REASON), body.slice(-200));
  await page.click("[data-import-open]", { force: true });
  await page.waitForTimeout(400);
  check("read-only: a forced press opens no Import dialog",
    await page.evaluate(() => document.getElementById("drawer").hidden), "");
  check("read-only: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown } = await open();
  const seen = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll("#view [data-github-check], #view [data-import-open], #view [data-remove-project]")];
    return { total: nodes.length, off: nodes.filter((node) => node.disabled).map((node) => node.outerHTML.slice(0, 80)) };
  });
  check("writable: every write control is on", seen.total >= 5 && seen.off.length === 0,
    `${seen.total} found, off: ${seen.off.join(" | ")}`);
  const connect = await page.$$("#view [data-github-connect]");
  check("writable: a connected farm offers no Connect button", connect.length === 0, `${connect.length}`);
  check("writable: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ---------------------------------------------------------- the strip in words */

const STRIP = [
  ["connected", /Signed in as @octo-farm\. Agents can copy, push and change CI files/, /can write to the head office your-org\/agent-hq/],
  ["missing_scope", /Agents cannot change CI workflow files/, /Signed in as @octo-farm\. Agents can copy and push in every/],
  ["missing_repo", /Signed in as @octo-farm\. Agents cannot copy or push private repositories\.\s/, /the login lacks the repo scope/],
  ["no_scopes", /Signed in as @octo-farm\. Agents cannot copy or push private repositories\. Agents cannot change CI workflow files\.\s/,
    /the login lacks the workflow scope/],
  ["no_git", /Git on this farm does not use this login/, /Signed in/],
  ["two", /Two identities: GH_TOKEN is set in \/home\/farm\/\.config\/fleet\/env/, /Remove line 3 \(GH_TOKEN=\.\.\.\) from \/home\/farm\/\.config\/fleet\/env\./],
  ["two_flag", /Signed in as @octo-farm/, null],
  ["not_connected", /GitHub is not connected on this farm/, /Connect GitHub/],
  ["no_gh", /gh, is not installed on this farm/, null],
  ["no_answer", /did not answer, so whether GitHub is connected cannot be told/, null],
  ["fine", /scopes cannot be read for this kind of token; the access check still applies/, /Signed in/],
  ["office_denied", /cannot write to the head office your-org\/agent-hq: this account can only read/, /Signed in/],
  ["unread", /Signed in as @octo-farm\. What the agents may do is not known yet/,
    /Whether this login can write to the head office your-org\/agent-hq is not known yet/],
  ["office_name", /The head office "agent-hq" is not written as owner\/name/, /Set it as owner\/name/],
];

for (const [gh, first, second] of STRIP) {
  const { page, context, thrown } = await open({ gh });
  const body = await sectionText(page);
  check(`strip ${gh}: says it in words`, first.test(body) && (!second || second.test(body)), body.slice(0, 400).replace(/\s+/g, " "));
  if (gh === "two_flag") {
    check("strip two_flag: a two_identities that is not {file, line, variable} draws nothing",
      !/Two identities/.test(body) && !(await page.$("[data-strip='two']")), body.slice(0, 200));
  }
  if (gh === "unread") {
    check("strip unread: never prints a null login, never promises a right, never calls the office refused",
      !/@null|@undefined/.test(body) && !/Agents can copy/.test(body) && !/cannot write to the head office/.test(body)
      && !/this kind of token/.test(body),
      body.slice(0, 300));
    /* The strip says Connected, so no role cell may say GitHub is not connected. */
    const tips = await page.evaluate(() => [...document.querySelectorAll("#view [data-col='Your access']")]
      .map((node) => node.title));
    check("strip unread: every role cell says the account has not been read yet, never not connected",
      tips.length > 0 && tips.every((tip) => /has not been read yet/.test(tip) && !/not connected/.test(tip)),
      JSON.stringify(tips));
  }
  if (gh === "office_name") {
    check("strip office_name: a head office not written as owner/name is never drawn as a wait",
      !/is not known yet/.test(body) && !(await page.$("[data-strip='office'].pause")), body.slice(0, 400));
  }
  if (gh === "missing_repo" || gh === "no_scopes") {
    check(`strip ${gh}: the headline never claims the agents can copy and push`,
      !/Agents can copy/.test(body), body.slice(0, 200));
  }
  if (gh === "no_gh" || gh === "no_answer") {
    check(`strip ${gh}: is never drawn as not connected`, !/not connected/i.test(body)
      && !(await page.$("#view [data-github-connect]")), body.slice(0, 200));
  }
  check(`strip ${gh}: nothing threw`, thrown.length === 0, thrown[0]);
  if (gh === "connected") {
    const tip = await page.evaluate(() => document.querySelector("[data-strip='state'] .pill").title);
    check("strip connected: the tooltip carries the scopes", tip === "Scopes: gist, read:org, repo, workflow", tip);
    const switchLink = await page.$("[data-github-switch]");
    check("strip connected: Switch account is offered instead of Connect", Boolean(switchLink), "");
  }
  if (gh === "missing_scope") {
    const copy = await page.evaluate(() => document.querySelector("[data-copy-refresh-scopes]").title);
    check("strip missing_scope: Copy carries the refresh command",
      copy === "ssh -t farm gh auth refresh -h github.com -s workflow", copy);
  }
  if (gh === "no_git") {
    const copy = await page.evaluate(() => document.querySelector("[data-copy-setup-git]").title);
    check("strip no_git: Copy carries gh auth setup-git", copy === "ssh -t farm gh auth setup-git", copy);
  }
  if (gh === "not_connected") {
    check("strip not_connected: Import says to connect first", await page.evaluate(() => {
      const node = document.querySelector("[data-import-open]");
      return node.disabled && node.title === "Connect GitHub first.";
    }), "");
  }
  await context.close();
}

/* No access: the row, its tooltip with the two ways out, and the strip's count. */
{
  const { page, context } = await open();
  const row = await page.evaluate(() => {
    const cell = document.querySelector("[data-project='sandbox'] [data-access]");
    return { text: cell.innerText.trim(), title: cell.title };
  });
  check("table: a registered repository out of reach reads No access",
    row.text === "No access", row.text);
  check("table: its tooltip names both ways out",
    /Grant it access on GitHub/.test(row.title) && /Remove the project/.test(row.title), row.title);
  const body = await sectionText(page);
  check("strip: counts the No access rows", /1 project is out of this account's reach/.test(body), "");
  const cells = await page.evaluate(() => {
    const tr = document.querySelector("[data-project='demo']");
    return { project: tr.cells[0].title, repo: tr.cells[1].innerText.replace(/\s+/g, " ").trim() };
  });
  check("table: the Project tooltip carries the ports", /Ports: web 5200, api 8100, e2e 9100/.test(cells.project), cells.project);
  check("table: the Repository cell holds the visibility tag", /your-org\/demo private/.test(cells.repo), cells.repo);
  await context.close();
}

/* ------------------------------------------------------------- the empty states */

{
  const { page, context, thrown } = await open({ state: "empty", gh: "not_connected" });
  const body = await sectionText(page);
  check("empty, not connected: says Connect GitHub first", /Connect GitHub first/.test(body), body.slice(0, 200));
  const buttons = await page.$$("#view [data-empty='connect'] [data-github-connect]");
  check("empty, not connected: with the Connect button", buttons.length === 1, `${buttons.length}`);
  check("empty, not connected: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown } = await open({ state: "empty" });
  const body = await sectionText(page);
  check("empty, connected: says Import your first repository", /Import your first repository/.test(body), body.slice(0, 200));
  const live = await page.evaluate(() => {
    const node = document.querySelector("#view [data-empty='import'] [data-import-open]");
    return node ? !node.disabled : null;
  });
  check("empty, connected: with an Import button that works", live === true, String(live));
  check("empty, connected: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown } = await open({ state: "loading" });
  const skeletons = await page.evaluate(() => document.querySelectorAll("#view [data-write] .skeleton").length);
  check("loading: the strip and the table are skeletons", skeletons >= 2, `${skeletons}`);
  check("loading: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------ one line per row, and no sideways drag */

for (const state of ["ready", "quiet"]) {
  for (const size of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    const { page, context } = await open({ state, size, long: state === "quiet" });
    const seen = await page.evaluate(() => {
      const table = document.querySelector("#view .p-table");
      const rows = [...table.querySelectorAll("tbody tr")];
      const tall = rows.map((row) => Math.round(row.getBoundingClientRect().height));
      const wrapped = [];
      for (const cell of table.querySelectorAll("tbody td")) {
        if (getComputedStyle(cell).display === "none") continue;
        const style = getComputedStyle(cell);
        if (style.whiteSpace !== "nowrap") wrapped.push(`${cell.cellIndex}: white-space ${style.whiteSpace}`);
        for (const child of cell.querySelectorAll("*")) {
          const box = child.getBoundingClientRect();
          if (box.height > 34) wrapped.push(`${cell.cellIndex}: ${child.className} ${Math.round(box.height)}px`);
        }
        if (cell.scrollWidth > cell.clientWidth + 1 && !cell.title) wrapped.push(`${cell.cellIndex}: cut with no title`);
      }
      const wrap = document.querySelector("#view .p-tablewrap");
      return {
        tall,
        wrapped,
        page: document.documentElement.scrollWidth - window.innerWidth,
        table: wrap.scrollWidth - wrap.clientWidth,
      };
    });
    const label = `${state} at ${size.width}`;
    const pills = await page.evaluate(() => [...document.querySelectorAll("#view .p-table tbody tr")].map((tr) => {
      const pill = tr.querySelector(".p-visibility .tag");
      if (!pill) return "none";
      const box = pill.getBoundingClientRect();
      return getComputedStyle(pill.closest(".p-visibility")).display !== "none" && box.width > 20 ? "shown" : "hidden";
    }));
    check(`table ${label}: every row keeps its Private or Public pill`,
      pills.length > 0 && pills.every((seen) => seen === "shown"), pills.join(", "));
    check(`table ${label}: every row is one line`, seen.tall.every((px) => px <= 40) && !seen.wrapped.length,
      `${seen.tall.join(", ")} ${seen.wrapped.slice(0, 3).join(" | ")}`);
    check(`table ${label}: nothing scrolls sideways`, seen.page <= 0 && seen.table <= 1,
      `page ${seen.page}, table ${seen.table}`);
    if (state === "quiet") {
      const long = await page.evaluate(() => {
        const tr = document.querySelector("[data-project^='checkout-retry']");
        return { name: tr.cells[0].title, repo: tr.cells[1].title };
      });
      check(`table ${label}: a long name is cut and its title carries it whole`,
        long.name.startsWith("checkout-retry-a-declined-card-once-then-explain")
        && long.repo === "your-org/checkout-retry-a-declined-card-once-then-explain-it-plainly-to-the-customer",
        JSON.stringify(long));
    }
    await context.close();
  }
}

/* ---------------------------------------------- the import flow, body by exact body */

{
  const { page, context, thrown } = await open();
  const from = (await sent()).length;
  await openImport(page);
  const first = await sentSince(from);
  check("import: opening lists the signed-in account's repositories",
    JSON.stringify(first) === JSON.stringify([["/api/github/repos", { owner: "octo-farm", q: "" }]]), JSON.stringify(first));
  const owners = await page.evaluate(() => [...document.querySelectorAll("[data-owner] option")].map((node) => node.value));
  check("import: the owner select is you first, then each organization",
    JSON.stringify(owners) === JSON.stringify(["octo-farm", "your-org", "labs-collective"]), owners.join(", "));
  await page.selectOption("[data-owner]", "your-org");
  await page.waitForTimeout(400);
  const mark = (await sent()).length;
  await page.type("[data-repo-search]", "bil", { delay: 60 });
  await page.waitForTimeout(150);
  const early = await sentSince(mark);
  await page.waitForTimeout(600);
  const typed = await sentSince(mark);
  check("import: the search waits for the typing to stop", early.length === 0, JSON.stringify(early));
  check("import: then asks once, with what was typed",
    JSON.stringify(typed) === JSON.stringify([["/api/github/repos", { owner: "your-org", q: "bil" }]]), JSON.stringify(typed));
  await page.fill("[data-repo-search]", "");
  await page.waitForTimeout(700);
  const rows = await page.evaluate(() => {
    const list = document.querySelector(".p-repos");
    const heights = [...list.querySelectorAll("[data-repo]")].map((node) => Math.round(node.getBoundingClientRect().height));
    return {
      count: heights.length,
      heights,
      visible: Math.round(list.clientHeight / 40),
      scrolls: list.scrollHeight > list.clientHeight,
      handbook: (() => {
        const button = document.querySelector("[data-import-repo='your-org/handbook']");
        return { disabled: button.disabled, text: button.innerText };
      })(),
      demo: document.querySelector("[data-import-repo='your-org/demo']").innerText,
      design: document.querySelector("[data-import-repo='your-org/design-system']").innerText,
      order: [...list.querySelectorAll("[data-repo]")].slice(0, 3).map((node) => node.dataset.repo),
    };
  });
  check("import: at most eight rows show and the list scrolls inside the dialog",
    rows.count > 8 && rows.visible <= 8 && rows.scrolls, JSON.stringify({ count: rows.count, visible: rows.visible }));
  check("import: every repository row is one line", rows.heights.every((px) => px <= 41), rows.heights.join(", "));
  check("import: the rows come newest push first",
    JSON.stringify(rows.order) === JSON.stringify(["your-org/demo", "your-org/storefront", "your-org/billing"]), rows.order.join(", "));
  check("import: a read-only repository cannot be imported, and the button says why",
    rows.handbook.disabled && rows.handbook.text === "Read only: agents need write", JSON.stringify(rows.handbook));
  check("import: triage counts as read", rows.design === "Read only: agents need write", rows.design);
  check("import: a registered repository says so", rows.demo === "Already a project", rows.demo);

  const before = (await sent()).length;
  await page.click("[data-import-repo='your-org/billing']");
  await page.waitForSelector("[data-import-step='2']");
  await page.waitForTimeout(500);
  const config = await page.evaluate(() => ({
    name: document.querySelector("[data-project-name]").value,
    copied: document.querySelector("[data-copied-to]").innerText,
    branches: [...document.querySelectorAll("[data-branch] option")].map((node) => node.innerText),
    ports: document.querySelector(".p-ports").innerText,
  }));
  check("import: the name is the repository's", config.name === "billing", config.name);
  check("import: and says where the copy goes", config.copied === "Copied to ~/work/billing on this farm", config.copied);
  /* The hint follows the typing at once, not at the next repaint a few seconds later. */
  await page.fill("[data-project-name]", "billing-app");
  const hintNow = await page.evaluate(() => document.querySelector("[data-copied-to]").innerText);
  check("import: the folder hint follows the typing at once", hintNow === "Copied to ~/work/billing-app on this farm", hintNow);
  await page.fill("[data-project-name]", "billing");
  check("import: the branch is the default, then the protected ones, then a typed name",
    JSON.stringify(config.branches) === JSON.stringify(["trunk (default)", "release/2026 (protected)", "Type another name"]),
    config.branches.join(" | "));
  check("import: the ports are a sentence with Change", /^Ports 5230 to 5329, the next free block\.\s*Change$/.test(config.ports), config.ports);
  await page.selectOption("[data-branch]", "release/2026");
  await page.click("[data-import-check]");
  await page.waitForSelector("[data-check]");
  const checks = await page.evaluate(() => ({
    ids: [...document.querySelectorAll("[data-check]")].map((node) => `${node.dataset.check}:${node.dataset.checkState}`),
    live: !document.querySelector("[data-import-start]").disabled,
  }));
  check("import: the checklist is drawn, one pill and one sentence a line",
    checks.ids.length === 6 && checks.ids.every((id) => id.endsWith(":ok")), checks.ids.join(", "));
  check("import: Import is enabled when nothing fails", checks.live, "");
  await page.click("[data-import-start]");
  await page.waitForSelector("[data-import-step='4']");
  const running = await drawerText(page);
  check("import: the dialog shows the copy running", /Importing/.test(running) && /Running/.test(running), running.slice(0, 160));
  let closed = false;
  for (let attempt = 0; attempt < 20 && !closed; attempt += 1) {
    await page.waitForTimeout(500);
    closed = await page.evaluate(() => document.getElementById("drawer").hidden);
  }
  check("import: the dialog closes to the table when the job ends", closed, "");
  const flow = await sentSince(before);
  check("import: the exact bodies, in order", JSON.stringify(flow) === JSON.stringify([
    ["/api/github/branches", { repo: "your-org/billing" }],
    ["/api/github/access", { repo: "your-org/billing", branch: "release/2026", name: "billing" }],
    ["/api/projects", { name: "billing", repo: "your-org/billing", branch: "release/2026" }],
  ]), JSON.stringify(flow));
  let row = "";
  for (let attempt = 0; attempt < 10 && !row; attempt += 1) {
    row = await page.evaluate(() => {
      const found = document.querySelector("[data-project='billing']");
      return found ? found.innerText.replace(/\s+/g, " ") : "";
    });
    if (!row) await page.waitForTimeout(500);
  }
  check("import: the new row is in the table, on its chosen branch", /release\/2026/.test(row), row);
  check("import: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A check that fails keeps Import off; a port typed after Change is sent as port_base. */
{
  const { page, context, thrown } = await open();
  await openImport(page);
  await page.selectOption("[data-owner]", "your-org");
  await page.waitForTimeout(400);
  await page.click("[data-import-repo='your-org/mobile-app']");
  await page.waitForSelector("[data-import-step='2']");
  await page.waitForTimeout(400);
  await page.selectOption("[data-branch]", "__typed");
  await page.fill("[data-branch-typed]", "no-such-branch");
  await page.click("[data-port-change]");
  await page.fill("[data-port]", "5700");
  const before = (await sent()).length;
  await page.click("[data-import-check]");
  await page.waitForSelector("[data-check]");
  const seen = await page.evaluate(() => ({
    fail: [...document.querySelectorAll("[data-check-state='fail']")].map((node) => node.dataset.check),
    live: !document.querySelector("[data-import-start]").disabled,
  }));
  check("check: a missing branch fails", JSON.stringify(seen.fail) === JSON.stringify(["branch"]), seen.fail.join(", "));
  check("check: and Import stays off while anything fails", seen.live === false, "");
  const bodies = await sentSince(before);
  check("check: the typed branch is what is checked", JSON.stringify(bodies) === JSON.stringify([
    ["/api/github/access", { repo: "your-org/mobile-app", branch: "no-such-branch", name: "mobile-app" }],
  ]), JSON.stringify(bodies));
  await page.click("[data-import-configure]");
  await page.fill("[data-branch-typed]", "release/2026");
  await page.click("[data-import-check]");
  await page.waitForSelector("[data-check]");
  await page.waitForTimeout(200);
  const mark = (await sent()).length;
  await page.click("[data-import-start]");
  await page.waitForTimeout(600);
  const posted = await sentSince(mark);
  check("check: a port block typed after Change is sent as port_base", JSON.stringify(posted) === JSON.stringify([
    ["/api/projects", { name: "mobile-app", repo: "your-org/mobile-app", branch: "release/2026", port_base: 5700 }],
  ]), JSON.stringify(posted));
  check("check: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A name that breaks the registry's rule, or one already taken, is refused before a check. */
{
  const { page, context } = await open();
  await openImport(page);
  await page.selectOption("[data-owner]", "labs-collective");
  await page.waitForTimeout(400);
  await page.click("[data-import-repo^='labs-collective/an-exceptionally-long']");
  await page.waitForSelector("[data-import-step='2']");
  const name = await page.evaluate(() => document.querySelector("[data-project-name]").value);
  check("configure: a long repository name is cut to 40 for the project name",
    name === "an-exceptionally-long-repository-name-th" && name.length === 40, name);
  await page.fill("[data-project-name]", "demo");
  const before = (await sent()).length;
  await page.click("[data-import-check]");
  await page.waitForTimeout(300);
  const said = await page.evaluate(() => document.querySelector("[data-config-error]")?.innerText || "");
  check("configure: a name already taken is refused in a sentence", /A project called demo already exists/.test(said), said);
  await page.fill("[data-project-name]", "-bad name");
  await page.click("[data-import-check]");
  await page.waitForTimeout(300);
  const bad = await page.evaluate(() => document.querySelector("[data-config-error]")?.innerText || "");
  check("configure: a name outside the registry's rule is refused", /letters, digits, dot, dash or underscore/.test(bad), bad);
  check("configure: and neither was sent to be checked", (await sent()).length === before, "");
  await context.close();
}

/* ------------------------------------------------------------------- the paste field */

{
  const { page, context, thrown, requests } = await open();
  await openImport(page);
  await page.waitForTimeout(300);
  for (const token of ["ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
    "0123456789abcdef0123456789abcdef01234567"]) {
    const before = requests.length;
    const recorded = (await sent()).length;
    await page.fill("[data-paste]", token);
    await page.click("[data-paste-use]");
    await page.waitForTimeout(500);
    const seen = await page.evaluate(() => ({
      error: document.querySelector("[data-paste-error]")?.innerText || "",
      value: document.querySelector("[data-paste]").value,
    }));
    const leaked = requests.slice(before).filter((request) => request.method !== "GET" || request.path.startsWith("/api/github"));
    check(`paste: a token-looking string is refused in the page (${token.slice(0, 10)})`,
      /looks like a GitHub token/.test(seen.error) && seen.value === "", JSON.stringify(seen));
    check(`paste: and no request carried it (${token.slice(0, 10)})`,
      leaked.length === 0 && (await sent()).length === recorded
      && !requests.some((request) => request.body.includes(token) || request.path.includes(token)),
      JSON.stringify(leaked));
  }
  const handbook = (await sent()).length;
  await page.fill("[data-paste]", "your-org/handbook");
  await page.click("[data-paste-use]");
  await page.waitForTimeout(400);
  const refused = await page.evaluate(() => document.querySelector("[data-paste-error]")?.innerText || "");
  const looked = await sentSince(handbook);
  check("paste: a read-only repository cannot be imported by address either",
    /Read only: agents need write/.test(refused) && JSON.stringify(looked) === JSON.stringify([
      ["/api/github/repos", { owner: "your-org", q: "handbook" }],
    ]), `${refused} ${JSON.stringify(looked)}`);
  await page.fill("[data-paste]", "https://gitlab.com/your-org/elsewhere");
  await page.click("[data-paste-use]");
  await page.waitForTimeout(300);
  const host = await page.evaluate(() => document.querySelector("[data-paste-error]")?.innerText || "");
  check("paste: an address on another host is refused", /An address is owner\/repo/.test(host), host);
  check("paste: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A token typed anywhere else on the page is refused the same way: in the project name, in a
   typed branch and in the search box. A classic token passes the registry's name rule, so
   without the screen it would reach an argv, a job record and a folder. */
const CLASSIC = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8";
for (const field of ["name", "branch"]) {
  const { page, context, thrown, requests } = await open();
  await openImport(page);
  await page.click("[data-import-repo='octo-farm/notes']");
  await page.waitForSelector("[data-import-step='2']");
  await page.waitForTimeout(400);
  if (field === "name") {
    await page.fill("[data-project-name]", CLASSIC);
  } else {
    await page.selectOption("[data-branch]", "__typed");
    await page.fill("[data-branch-typed]", CLASSIC);
  }
  await page.waitForTimeout(3500);
  const copied = await page.evaluate(() => document.querySelector("[data-copied-to]").innerText);
  if (field === "name") {
    check("token in the name: the Copied to line never echoes it", !copied.includes("ghp_"), copied);
  }
  const before = requests.length;
  const recorded = (await sent()).length;
  await page.click("[data-import-check]");
  await page.waitForTimeout(500);
  const seen = await page.evaluate((mark) => ({
    error: document.querySelector("[data-config-error]")?.innerText || "",
    value: document.querySelector(mark)?.value ?? "",
    page: document.body.innerText,
  }), field === "name" ? "[data-project-name]" : "[data-branch-typed]");
  check(`token in the ${field}: refused in the page, and the field is wiped`,
    /looks like a GitHub token/.test(seen.error) && seen.value === "" && !seen.page.includes(CLASSIC), JSON.stringify(seen.error));
  check(`token in the ${field}: and no request carried it`,
    (await sent()).length === recorded
    && !requests.slice(before).some((request) => request.method === "POST")
    && !requests.some((request) => request.body.includes(CLASSIC) || request.path.includes(CLASSIC)), "");
  check(`token in the ${field}: nothing threw`, thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown, requests } = await open();
  await openImport(page);
  await page.waitForTimeout(300);
  const before = requests.length;
  const recorded = (await sent()).length;
  await page.fill("[data-repo-search]", CLASSIC);
  await page.waitForTimeout(900);
  const seen = await page.evaluate(() => ({
    error: document.querySelector("[data-search-error]")?.innerText || "",
    value: document.querySelector("[data-repo-search]").value,
    page: document.body.innerText,
  }));
  check("token in the search: refused in the page, and the box is wiped",
    /looks like a GitHub token/.test(seen.error) && seen.value === "" && !seen.page.includes(CLASSIC), JSON.stringify(seen.error));
  check("token in the search: and no request carried it",
    (await sent()).length === recorded
    && !requests.slice(before).some((request) => request.method === "POST")
    && !requests.some((request) => request.body.includes(CLASSIC) || request.path.includes(CLASSIC)), "");
  check("token in the search: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

for (const [typed, full] of [
  ["outside-org/tool", "outside-org/tool"],
  ["https://github.com/outside-org/tool.git/", "outside-org/tool"],
  ["git@github.com:outside-org/tool.git", "outside-org/tool"],
]) {
  const { page, context } = await open();
  await openImport(page);
  const before = (await sent()).length;
  await page.fill("[data-paste]", typed);
  await page.press("[data-paste]", "Enter");
  await page.waitForSelector("[data-import-step='2']", { timeout: 4000 }).catch(() => {});
  await page.waitForTimeout(300);
  const bodies = await sentSince(before);
  check(`paste: ${typed} is looked up in the list, then read as ${full}`, JSON.stringify(bodies) === JSON.stringify([
    ["/api/github/repos", { owner: "outside-org", q: "tool" }],
    ["/api/github/branches", { repo: full }],
  ]), JSON.stringify(bodies));
  await context.close();
}

/* ------------------------------------------------ nothing asks GitHub twice for one answer */

{
  const { page, context, thrown } = await open();
  await openImport(page);
  await page.selectOption("[data-owner]", "your-org");
  await page.waitForTimeout(400);
  await page.click("[data-import-repo='your-org/support-bot']");
  await page.waitForSelector("[data-import-step='2']");
  await page.waitForTimeout(500);
  const before = (await sent()).length;
  await page.click("[data-import-back]");
  await page.waitForSelector("[data-import-repo='your-org/support-bot']");
  await page.click("[data-import-repo='your-org/support-bot']");
  await page.waitForSelector("[data-import-step='2']");
  await page.waitForTimeout(500);
  const again = await sentSince(before);
  const branches = await page.evaluate(() => [...document.querySelectorAll("[data-branch] option")].map((node) => node.innerText));
  check("budget: Choose another, then the same repository, reads its branches from memory",
    again.length === 0 && branches[0] === "main (default)", `${JSON.stringify(again)} ${branches.join(" | ")}`);
  await page.click("[data-import-check]");
  await page.waitForSelector("[data-check]");
  await page.waitForTimeout(300);
  const mark = (await sent()).length;
  const button = await page.evaluate(() => {
    const node = document.querySelector("[data-import-recheck]");
    return { disabled: node.disabled, text: node.innerText };
  });
  await page.click("[data-import-recheck]", { force: true });
  await page.waitForTimeout(500);
  check("budget: Check again rests right after an answer, and says for how long",
    button.disabled && /^Check again \(in /.test(button.text), JSON.stringify(button));
  check("budget: and a forced press asks GitHub nothing", (await sentSince(mark)).length === 0,
    JSON.stringify(await sentSince(mark)));
  check("budget: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------ an import that ends after the dialog was closed */

/* The clone is a job, and a person may close the dialog while it runs. The section keeps
   following it: a failure says why in the table card, and the job stops being read. */
{
  const LATE = "job-late-failure";
  const REASON = "git clone could not read your-org/infra: permission denied";
  let asked = 0;
  const { page, context, thrown, requests } = await open({
    overrides: {
      "/api/projects": (handler) => (handler.request().method() === "POST"
        ? handler.fulfill({ status: 202, contentType: "application/json",
          body: JSON.stringify({ job: { id: LATE, state: "running" } }) })
        : handler.continue()),
      [`/api/jobs/${LATE}`]: (handler) => {
        asked += 1;
        const failed = asked > 2;
        return handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
          id: LATE, action: "add_project", state: failed ? "failed" : "running",
          detail: "copying your-org/infra", error: failed ? REASON : "",
        }) });
      },
    },
  });
  await openImport(page);
  await page.selectOption("[data-owner]", "your-org");
  await page.waitForTimeout(400);
  await page.click("[data-import-repo='your-org/infra']");
  await page.waitForSelector("[data-import-step='2']");
  await page.waitForTimeout(400);
  await page.click("[data-import-check]");
  await page.waitForSelector("[data-check]");
  await page.waitForTimeout(200);
  await page.click("[data-import-start]");
  await page.waitForSelector("[data-import-step='4']");
  await page.click("[data-import-close]");
  let said = "";
  for (let attempt = 0; attempt < 24 && !said; attempt += 1) {
    await page.waitForTimeout(500);
    said = await page.evaluate(() => document.querySelector("#view [data-import-failed]")?.innerText || "");
  }
  check("late failure: after Close, the table card says the import failed and why",
    said.includes(REASON) && said.includes("infra"), said);
  const reads = () => requests.filter((request) => request.path === `/api/jobs/${LATE}`).length;
  const settled = reads();
  await page.waitForTimeout(6500);
  check("late failure: and the ended job is no longer read", reads() === settled, `${reads() - settled} more`);
  await page.click("[data-import-dismiss]");
  await page.waitForTimeout(300);
  check("late failure: Dismiss takes the sentence away",
    !(await page.$("#view [data-import-failed]")), "");
  check("late failure: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The same, when the copy succeeds: the row lands and the job is dropped. */
{
  const { page, context, thrown, requests } = await open();
  await openImport(page);
  await page.selectOption("[data-owner]", "your-org");
  await page.waitForTimeout(400);
  await page.click("[data-import-repo='your-org/analytics']");
  await page.waitForSelector("[data-import-step='2']");
  await page.waitForTimeout(400);
  await page.click("[data-import-check]");
  await page.waitForSelector("[data-check]");
  await page.waitForTimeout(200);
  await page.click("[data-import-start]");
  await page.waitForSelector("[data-import-step='4']");
  const job = await page.evaluate(() => document.querySelector("[data-import-job]").dataset.importJob);
  await page.click("[data-import-close]");
  await page.waitForTimeout(4500);
  const row = await page.$("#view [data-project='analytics']");
  const reads = () => requests.filter((request) => request.path === `/api/jobs/${job}`).length;
  const settled = reads();
  await page.waitForTimeout(6500);
  check("late success: after Close, the row lands", Boolean(row), job);
  check("late success: and the finished job is no longer read", settled > 0 && reads() === settled,
    `${settled} reads, then ${reads() - settled} more`);
  check("late success: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

/* --------------------------------------------- buttons are off while their request runs */

{
  const { page, context } = await open({
    overrides: {
      "/api/github/branches": (handler) => sleep(1500).then(() => handler.continue()),
      "/api/projects": (handler) => (handler.request().method() === "POST"
        ? sleep(1500).then(() => handler.continue()) : handler.continue()),
    },
  });
  await openImport(page);
  await page.selectOption("[data-owner]", "your-org");
  await page.waitForTimeout(400);
  await page.click("[data-import-repo='your-org/infra']");
  await page.waitForTimeout(300);
  const during = await page.evaluate(() => document.querySelector("[data-import-check]").disabled);
  check("in flight: Check is off while the branches are read", during === true, String(during));
  await page.waitForTimeout(1600);
  await page.click("[data-import-check]");
  await page.waitForSelector("[data-check]");
  await page.waitForTimeout(200);
  const before = (await sent()).length;
  await page.click("[data-import-start]");
  await page.waitForTimeout(300);
  const importing = await page.evaluate(() => {
    const node = document.querySelector("[data-import-start]");
    return node ? { disabled: node.disabled, text: node.innerText } : null;
  });
  check("in flight: Import is off while its request runs",
    importing && importing.disabled && importing.text === "Starting the import", JSON.stringify(importing));
  await page.click("[data-import-start]", { force: true }).catch(() => {});
  await page.waitForTimeout(1800);
  const posts = (await sentSince(before)).filter(([route]) => route === "/api/projects");
  check("in flight: a second press starts no second import", posts.length === 1, `${posts.length}`);
  await context.close();
}

/* ------------------------------- the Connect dialog reads GET /api/github, and only then */

{
  const { page, context, thrown, requests } = await open({ gh: "not_connected" });
  await page.waitForTimeout(3500);
  const gets = () => requests.filter((request) => request.method === "GET" && request.path === "/api/github");
  const checks = () => requests.filter((request) => request.method === "POST" && request.path === "/api/github/check");
  const idle = gets().length;
  await page.waitForTimeout(6500);
  check("polling: with no dialog open GET /api/github is not on the three second tick",
    gets().length === idle, `${gets().length - idle} in 6.5 s`);
  await page.click("[data-github-connect]");
  const lead = await page.evaluate(() => document.getElementById("drawerBody").querySelector(".p-lead, p")?.innerText || "");
  check("connect: the dialog says first that every agent will act as this account",
    lead === "Every agent on this farm will act as this account.", lead);
  const text = await drawerText(page);
  check("connect: it gives the login command with -s workflow",
    text.includes("ssh -t farm gh auth login -h github.com -p https --web -s workflow")
    && /Answer Yes when it asks to authenticate Git/.test(text)
    && text.includes("ssh -t farm gh auth setup-git"), text.slice(0, 300));
  const opened = gets().length;
  const checksOpen = checks().length;
  await page.waitForTimeout(10000);
  const polled = gets().length - opened;
  check("polling: while the dialog is open GET /api/github is read about every 3 seconds",
    polled >= 3 && polled <= 5, `${polled} in 10 s`);
  check("polling: and POST /api/github/check is never sent on a timer",
    checks().length === 0 && checksOpen === 0, `${checks().length}`);
  await page.click("#drawerClose");
  await page.waitForTimeout(300);
  const closedAt = gets().length;
  await page.waitForTimeout(10500);
  check("polling: after the dialog closes GET /api/github stops (10.5 s, room for three polls)",
    gets().length === closedAt, `${gets().length - closedAt} after close`);
  check("polling: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown } = await open({ gh: "flip" });
  await page.click("[data-github-connect]");
  let flipped = "";
  for (let attempt = 0; attempt < 16 && !flipped; attempt += 1) {
    await page.waitForTimeout(700);
    const text = await drawerText(page);
    if (/Signed in as @octo-farm/.test(text)) flipped = text;
  }
  check("connect: the dialog notices the login by itself", Boolean(flipped), flipped.slice(0, 120));
  const done = await page.evaluate(() => document.querySelector("[data-connect-done]")?.innerText);
  check("connect: and offers Done", done === "Done", String(done));
  check("connect: nothing threw", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open();
  await page.click("[data-github-switch]");
  const text = await drawerText(page);
  check("switch: the dialog explains first that every agent and the head office change account",
    text.startsWith("Every agent on this farm and the head office will act as the new account."), text.slice(0, 120));
  check("switch: then shows gh auth switch", text.includes("ssh -t farm gh auth switch"), "");
  await context.close();
}

/* ---------------------------------------------------------------------- re-check */

{
  const { page, context, requests } = await open();
  await page.click("[data-github-check]");
  /* The button says "Asking GitHub" until the farm's check has answered (the page reads until
     "checking" clears), then rests for the cooldown. */
  await page.waitForTimeout(2000);
  const posts = requests.filter((request) => request.method === "POST" && request.path === "/api/github/check");
  const after = await page.evaluate(() => {
    const node = document.querySelector("[data-github-check]");
    return { disabled: node.disabled, text: node.innerText };
  });
  check("re-check: one press is one POST /api/github/check with an empty body",
    posts.length === 1 && posts[0].body === "{}", JSON.stringify(posts.map((post) => post.body)));
  check("re-check: the button rests for the cooldown", after.disabled && /Re-check \(in /.test(after.text), JSON.stringify(after));
  await context.close();
}

/* ------------------------------------------------------------------------- remove */

{
  const { page, context, requests } = await open();
  await page.click("[data-remove-project='sandbox']");
  await page.waitForTimeout(300);
  const confirm = await page.evaluate(() => document.querySelector("[data-remove-confirm='sandbox']").innerText);
  check("remove: the confirmation names the row's own folder, and says it and the GitHub repository both stay",
    /The folder \/home\/farm\/work\/sandbox on this farm stays, and the repository your-org\/sandbox on GitHub stays\./.test(confirm),
    confirm.slice(0, 240));
  await page.click("[data-confirm='remove-project:sandbox']");
  await page.waitForTimeout(700);
  const posts = requests.filter((request) => request.method === "POST" && request.path === "/api/projects/remove");
  check("remove: the body is the project's name and nothing else",
    posts.length === 1 && posts[0].body === JSON.stringify({ name: "sandbox" }), JSON.stringify(posts.map((post) => post.body)));
  await context.close();
}

/* ------------------------------------------------------------ the phone, sideways */

{
  const { page, context } = await open({ size: { width: 390, height: 844 } });
  await openImport(page);
  await page.selectOption("[data-owner]", "labs-collective");
  await page.waitForTimeout(500);
  const seen = await page.evaluate(() => {
    const body = document.getElementById("drawerBody");
    const list = document.querySelector(".p-repos");
    return {
      page: document.documentElement.scrollWidth - window.innerWidth,
      drawer: body.scrollWidth - body.clientWidth,
      list: list.scrollWidth - list.clientWidth,
      heights: [...list.querySelectorAll("[data-repo]")].map((node) => Math.round(node.getBoundingClientRect().height)),
    };
  });
  check("phone: the Import dialog does not scroll sideways", seen.page <= 0 && seen.drawer <= 1 && seen.list <= 1,
    JSON.stringify(seen));
  check("phone: its rows stay one line", seen.heights.every((px) => px <= 41), seen.heights.join(", "));
  await context.close();
}

await browser.close();
const failed = results.filter((row) => !row.passed);
console.log(`\n${results.length - failed.length} of ${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

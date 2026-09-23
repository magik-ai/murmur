/* What Queue and Machine do when a route lies to them, when the page may not write, and when
   an action fails halfway. Every case asks the same two questions: did anything throw, and was
   the reader told. A control room that draws half a screen and keeps its buttons bright is
   worse than one that says plainly it cannot do the thing.

   The two views are opened through the stub's harness page, which is the same shell around the
   same modules that index.html puts them in: the lane that owns index.html registers them
   there, and this check does not wait for it to land. */

import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPlaywright } from "./test_playwright.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 7975);
const BASE = `http://127.0.0.1:${PORT}`;
const ONLY = process.env.ONLY || "";

const results = [];
function check(name, passed, detail) {
  if (ONLY && !name.includes(ONLY)) return;
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
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

/** One harness page, with the routes named in `overrides` answered by this test. */
async function open({ view = "queue", state = "ready", size = { width: 1440, height: 1000 },
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

const WRITE_CONTROLS = "[data-enqueue], [data-runner], [data-cancel], [data-power], [data-mode],"
  + " [data-service], [data-accounts-refresh], [data-add-account], [data-remove-account],"
  + " [data-model-switch], [data-model-test], [data-model-remove], [data-add-model],"
  + " [data-add-project], [data-remove-project]";

const READ_ONLY = JSON.stringify({
  writable: false,
  reason: "This page was opened without the dashboard token, so it can only read.",
  token_required: true,
  loopback: true,
});

/* ------------------------------------------- every table on the tab is one line per row */

{
  const { page, context } = await open({ view: "machine" });
  await page.waitForTimeout(600);
  const tables = await page.evaluate(() => {
    const out = {};
    for (const table of document.querySelectorAll("#view .tablewrap table")) {
      const section = table.closest("section");
      const name = section && section.querySelector("h2") ? section.querySelector("h2").textContent.trim() : "?";
      const rows = [...table.querySelectorAll("tbody tr")].map((row) => Math.round(row.getBoundingClientRect().height));
      if (rows.length > 1) out[name] = rows;
    }
    return out;
  });
  for (const [name, heights] of Object.entries(tables)) {
    check(`machine: every row of the ${name} table is the same height`,
      Math.max(...heights) - Math.min(...heights) <= 2, heights.join(", "));
  }
  check("machine: the tab has tables to hold to that rule", Object.keys(tables).length >= 3,
    Object.keys(tables).join(", "));
  const cut = await page.evaluate(() => [...document.querySelectorAll(".m-limits")]
    .map((node) => node.scrollWidth - node.clientWidth));
  check("machine: no subscription window is cut off at 1440", cut.every((px) => px <= 1), cut.join(", "));
  await context.close();
}

/* ------------------------------------------------- a page that may not write */

for (const view of ["queue", "machine"]) {
  const { page, context, thrown } = await open({ view, overrides: { "/api/access": READ_ONLY } });
  const seen = await page.evaluate((selector) => {
    const nodes = [...document.querySelectorAll(`#view ${selector.split(", ").join(", #view ")}`)];
    return {
      total: nodes.length,
      live: nodes.filter((node) => !node.disabled).map((node) => node.outerHTML.slice(0, 80)),
    };
  }, WRITE_CONTROLS);
  const body = await text(page);
  check(`${view}: nothing threw when the page may not write`, thrown.length === 0, thrown[0]);
  check(`${view}: it has write controls to switch off`, seen.total > 0, `${seen.total} found`);
  check(`${view}: every write control is switched off`, seen.live.length === 0, seen.live.join(" | "));
  check(`${view}: the reader is told why in the server's own words`,
    body.includes("opened without the dashboard token"), body.slice(0, 120));
  await context.close();
}

/* Marking a card as a write marks everything in it. The queue's controls card holds two
   filters and a help button, which only narrow what is already on screen, so the mark belongs
   on the half that really writes: switching off a reader's only way back to the whole table is
   not what "this page may not write" means. */
{
  const { page, context } = await open({ view: "queue", overrides: { "/api/access": READ_ONLY } });
  const seen = await page.evaluate(() => {
    const inWrite = (selector) => {
      const node = document.querySelector(`#view ${selector}`);
      return node ? Boolean(node.closest("[data-write]")) : null;
    };
    const live = (selector) => {
      const node = document.querySelector(`#view ${selector}`);
      return node ? !node.disabled : null;
    };
    return {
      state: inWrite("select[aria-label='Filter by state']"),
      project: inWrite("select[aria-label='Filter by project']"),
      help: inWrite(".q-help"),
      verify: inWrite("[data-enqueue]"),
      runner: inWrite(".q-runner"),
      stateLive: live("select[aria-label='Filter by state']"),
      helpLive: live(".q-help"),
    };
  });
  check("queue: the two filters and the help button are not marked as writes",
    seen.state === false && seen.project === false && seen.help === false, JSON.stringify(seen));
  check("queue: the controls that do write still are",
    seen.verify === true && seen.runner === true, JSON.stringify(seen));
  check("queue: and a read-only page can still narrow the table",
    seen.stateLive === true && seen.helpLive === true, JSON.stringify(seen));
  await context.close();
}

/* ----------------------------------------------- a route that is not the shape it claims */

{
  const { page, context, thrown } = await open({
    view: "queue",
    overrides: {
      "/api/ci": (handler) => handler.fulfill({
        status: 200, contentType: "application/json", body: "<html>a proxy said hello</html>",
      }),
    },
  });
  const body = await text(page);
  check("queue: an answer that is not JSON is an error, not data", thrown.length === 0, thrown[0]);
  check("queue: the reader is told the answer could not be read",
    /could not be read|reported a problem|did not answer/i.test(body), body.slice(0, 80));
  await context.close();
}

{
  const { page, context, thrown } = await open({
    view: "queue",
    overrides: {
      "/api/ci": JSON.stringify({ running: "nope", queued: null, recent: { one: 1 } }),
    },
  });
  const body = await text(page);
  check("queue: lists that are not lists leave the tab standing", thrown.length === 0, thrown[0]);
  check("queue: it says the queue has never run", /never run/i.test(body), body.slice(0, 80));
  await context.close();
}

{
  const { page, context, thrown } = await open({
    view: "queue",
    overrides: { "/api/services": JSON.stringify({ at: "now", services: "not a list" }) },
  });
  const body = await text(page);
  check("queue: a services answer without services does not break the runner control",
    thrown.length === 0, thrown[0]);
  check("queue: it says the runner cannot be switched from here",
    /cannot be switched from here/.test(body), body.slice(0, 120));
  await context.close();
}

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
  check("machine: a models answer that is not a list is an empty models table",
    /No models registered/.test(body), body.slice(0, 200));
  check("machine: and the empty table still offers the button that fills it",
    /Add a model/.test(body), body.slice(0, 200));
  await context.close();
}

{
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: { "/api/services": (handler) => handler.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "the service manager is not answering" }) }) },
  });
  const body = await text(page);
  check("machine: a services route that fails is an error card, not an empty table",
    thrown.length === 0, thrown[0]);
  check("machine: the service manager's refusal is shown",
    /not answering/.test(body), body.slice(0, 200));
  await context.close();
}

/* ------------------------------------------------------------ a job that fails */

{
  const { page, context, thrown, posted } = await open({ view: "queue" });
  await page.selectOption("#view select[aria-label='Project']", "demo");
  await page.fill("#view input[aria-label^='Number']", "999");
  await page.click("[data-enqueue]");
  await page.waitForTimeout(1200);
  const during = await page.evaluate(() => ({
    disabled: document.querySelector("[data-enqueue]").disabled,
    label: document.querySelector("[data-enqueue]").textContent,
  }));
  check("queue: the verify button waits while its job runs", during.disabled && /Verifying/.test(during.label),
    JSON.stringify(during));
  await page.waitForTimeout(4000);
  const body = await text(page);
  const after = await page.evaluate(() => document.querySelector("[data-enqueue]").disabled);
  check("queue: a job that fails is sent to the reader in words",
    /refused this request|its log says why/.test(body), body.slice(0, 200));
  check("queue: the button comes back after a failed job", after === false);
  check("queue: it asked the enqueue route", posted.some((url) => url.endsWith("/api/ci/enqueue")));
  check("queue: nothing threw while a job failed", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown } = await open({
    view: "queue",
    overrides: {
      "/api/ci/enqueue": JSON.stringify({ ok: true, job: "job-missing" }),
    },
  });
  await page.selectOption("#view select[aria-label='Project']", "demo");
  await page.fill("#view input[aria-label^='Number']", "412");
  await page.click("[data-enqueue]");
  await page.waitForTimeout(2000);
  const body = await text(page);
  check("queue: a job id the server does not know does not hang the button",
    thrown.length === 0, thrown[0]);
  check("queue: the reader is told the job could not be read",
    /no job with that id|reported a problem|could not be read/i.test(body), body.slice(0, 200));
  await context.close();
}

{
  const { page, context, posted } = await open({ view: "queue" });
  await page.fill("#view input[aria-label^='Number']", "412");
  await page.waitForTimeout(400);
  const off = await page.evaluate(() => document.querySelector("[data-enqueue]").disabled);
  await page.click("[data-enqueue]", { force: true });
  await page.waitForTimeout(800);
  const body = await text(page);
  check("queue: verifying without a project cannot be pressed", off === true, String(off));
  check("queue: verifying without a project is refused with what to do",
    /Pick a project/.test(body), body.slice(0, 200));
  check("queue: and nothing was sent to the runner",
    !posted.some((url) => url.endsWith("/api/ci/enqueue")), posted.join(" "));
  await context.close();
}

/* Picking a project and then picking the placeholder again is the shape that posted
   {"project":"Pick a project"} to the runner, with no refusal shown anywhere. */
{
  const { page, context, posted } = await open({ view: "queue" });
  const bodies = [];
  page.on("request", (request) => {
    if (request.method() === "POST") bodies.push(request.postData() || "");
  });
  await page.selectOption("#view select[aria-label='Project']", "demo");
  await page.fill("#view input[aria-label^='Number']", "412");
  await page.waitForTimeout(400);
  const armed = await page.evaluate(() => document.querySelector("[data-enqueue]").disabled);
  await page.selectOption("#view select[aria-label='Project']", { label: "Pick a project" });
  await page.waitForTimeout(400);
  const off = await page.evaluate(() => document.querySelector("[data-enqueue]").disabled);
  await page.click("[data-enqueue]", { force: true });
  await page.waitForTimeout(900);
  check("queue: Verify is live only while a project and a number are both there",
    armed === false && off === true, JSON.stringify({ armed, off }));
  check("queue: the placeholder is never posted as a project",
    !posted.some((url) => url.endsWith("/api/ci/enqueue"))
    && !bodies.some((sent) => sent.includes("Pick a project")), bodies.join(" ").slice(0, 200));
  await context.close();
}

{
  const { page, context } = await open({ view: "queue" });
  await page.selectOption("#view select[aria-label='Filter by state']", "failed");
  await page.selectOption("#view select[aria-label='Filter by project']", "demo");
  // Two ticks: a select whose options the tick rebuilds must still show what it is filtering by.
  await page.waitForTimeout(7000);
  const seen = await page.evaluate(() => {
    const pick = (label) => {
      const node = document.querySelector(`#view select[aria-label='${label}']`);
      return { value: node.value, shown: node.options[node.selectedIndex].textContent };
    };
    return {
      state: pick("Filter by state"),
      project: pick("Filter by project"),
      rows: [...document.querySelectorAll(".q-row")].length,
      states: [...new Set([...document.querySelectorAll(".q-row .pill-text")].map((n) => n.textContent))],
    };
  });
  check("queue: a filter still says what it is filtering by after a tick",
    seen.state.value === "failed" && /Failed/.test(seen.state.shown)
    && seen.project.value === "demo" && /demo/.test(seen.project.shown), JSON.stringify(seen));
  check("queue: and the table shows only those runs",
    seen.rows > 0 && seen.states.length === 1 && seen.states[0] === "Failed", JSON.stringify(seen));
  await context.close();
}

/* A filter that cannot be undone is worse than no filter: the tab is its table, and the only
   way back from "Any state" filtering for the words "Any state" is a reload. */
{
  const { page, context, thrown } = await open({ view: "queue" });
  const count = () => page.evaluate(() => document.querySelectorAll(".q-row").length);
  const all = await count();
  await page.selectOption("#view select[aria-label='Filter by state']", "failed");
  await page.waitForTimeout(500);
  const narrowed = await count();
  await page.selectOption("#view select[aria-label='Filter by state']", { label: "Any state" });
  await page.waitForTimeout(500);
  const back = await count();
  check("queue: Any state gives every run back", all > 0 && narrowed > 0 && narrowed < all
    && back === all, JSON.stringify({ all, narrowed, back }));
  await page.selectOption("#view select[aria-label='Filter by project']", "demo");
  await page.waitForTimeout(500);
  const oneProject = await count();
  await page.selectOption("#view select[aria-label='Filter by project']", { label: "Every project" });
  await page.waitForTimeout(500);
  const bothProjects = await count();
  check("queue: Every project gives every run back", oneProject > 0 && oneProject < all
    && bothProjects === all, JSON.stringify({ all, oneProject, bothProjects }));
  const body = await text(page);
  check("queue: and a cleared filter leaves nothing filtered out",
    !/finished runs are filtered out/.test(body), body.slice(0, 200));
  check("queue: nothing threw while the filters were cleared", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The header filter narrows the whole page. A state select that goes on counting the project
   the reader has already filtered away offers "Passed (17)" over a table of 21 rows. */
{
  const { page, context, thrown } = await open({ view: "queue" });
  const all = await page.evaluate(() => document.querySelectorAll(".q-row").length);
  await page.selectOption("#projectFilter", "demo");
  await page.waitForTimeout(800);
  const seen = await page.evaluate(() => {
    const options = [...document.querySelectorAll("#view select[aria-label='Filter by state'] option")]
      .slice(1).map((node) => node.textContent);
    const shown = {};
    for (const node of document.querySelectorAll(".q-row .pill-text")) {
      shown[node.textContent] = (shown[node.textContent] || 0) + 1;
    }
    return { options, shown, rows: document.querySelectorAll(".q-row").length };
  });
  const wrong = seen.options.filter((label) => {
    const parts = label.match(/^(.*) \((\d+)\)$/);
    return !parts || Number(parts[2]) !== (seen.shown[parts[1]] || 0);
  });
  check("queue: the header filter narrows the table", seen.rows > 0 && seen.rows < all,
    `${seen.rows} of ${all}`);
  check("queue: and the state counts are of the runs it allows", wrong.length === 0,
    JSON.stringify({ wrong, options: seen.options, shown: seen.shown }));
  check("queue: nothing threw under the header filter", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------ cancel and runner */

/* The runner row is looked up by the name the server gives it. A name this page invented
   instead found nothing, and the tab told a farm with four services that it reports none. */
{
  const { page, context } = await open({ view: "queue" });
  const seen = await page.evaluate(() => ({
    button: Boolean(document.querySelector("[data-runner]")),
    text: document.querySelector(".q-runner") ? document.querySelector(".q-runner").innerText : "",
  }));
  check("queue: the runner is found under the name the server gives it",
    seen.button && /Runner/.test(seen.text) && !/cannot be switched from here/.test(seen.text),
    JSON.stringify(seen));
  await context.close();
}

{
  const { page, context, posted } = await open({ view: "queue" });
  await page.click("[data-cancel]");
  await page.waitForTimeout(900);
  check("queue: cancel asks the cancel route", posted.some((url) => url.endsWith("/api/ci/cancel")));
  await page.click("[data-runner]");
  await page.waitForTimeout(900);
  check("queue: the runner control asks the services route",
    posted.some((url) => url.endsWith("/api/services")));
  await context.close();
}

{
  const { page, context } = await open({
    view: "queue",
    overrides: {
      "/api/ci": (handler) => handler.fetch().then(async (answer) => {
        const payload = await answer.json();
        payload.daemon_alive = false;
        return handler.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
      }),
    },
  });
  const body = await text(page);
  check("queue: a stopped runner is named by the command that starts it",
    body.includes("fleet ci daemon start") && !body.includes("fleet daemon start"),
    body.slice(0, 200));
  await context.close();
}

/* A run ages out of `recent` while its panel is open. The panel has to go, and so has the
   column it sat in, or the table is squeezed beside 420 px of page with no Close button in it. */
{
  let dropped = "";
  const { page, context, thrown } = await open({
    view: "queue",
    overrides: {
      "/api/ci": (handler) => handler.fetch().then(async (answer) => {
        const payload = await answer.json();
        for (const band of ["running", "queued", "recent"]) {
          if (dropped) payload[band] = (payload[band] || []).filter((row) => row.id !== dropped);
        }
        return handler.fulfill({
          status: 200, contentType: "application/json", body: JSON.stringify(payload),
        });
      }),
    },
  });
  const measure = () => page.evaluate(() => {
    const shell = document.querySelector(".q-shell");
    const table = document.querySelector(".q-table");
    return {
      panel: Boolean(document.querySelector(".q-detail")),
      open: Boolean(shell && shell.classList.contains("open")),
      table: table ? Math.round(table.getBoundingClientRect().width) : 0,
      shell: shell ? Math.round(shell.getBoundingClientRect().width) : 0,
    };
  });
  await page.click("[data-run='ci-2001-0000']");
  await page.waitForTimeout(900);
  const opened = await measure();
  dropped = "ci-2001-0000";
  await page.waitForTimeout(4500);
  const after = await measure();
  check("queue: a run that leaves the queue takes its panel with it",
    opened.panel && opened.open && !after.panel && !after.open,
    JSON.stringify({ opened, after }));
  check("queue: and the table is given the whole width back",
    after.table >= after.shell - 2 && after.table > opened.table, JSON.stringify(after));
  check("queue: nothing threw when the open run left the queue", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------ the stage log */

{
  const { page, context } = await open({ view: "queue" });
  await page.click("[data-run='ci-2001-0000']");
  await page.waitForTimeout(900);
  await page.click("#view .q-tab:nth-child(2)");
  await page.waitForTimeout(1200);
  const seen = await page.evaluate(() => {
    const log = document.getElementById("queueLog");
    return {
      bottom: log ? log.scrollHeight - log.scrollTop - log.clientHeight : -1,
      text: document.querySelector(".q-detail").innerText,
    };
  });
  check("queue: a cut log names the command that shows all of it",
    seen.text.includes("fleet ci log ci-2001-0000") && seen.text.includes("256 KB"),
    seen.text.slice(0, 200));
  check("queue: the log opens at its end", seen.bottom >= 0 && seen.bottom < 40, String(seen.bottom));
  check("queue: the failed tests of that run are listed by name",
    /orders.spec.ts/.test(seen.text), seen.text.slice(0, 200));
  await page.fill("#view .q-findbox", "step 3999");
  await page.waitForTimeout(700);
  const found = await page.evaluate(() => ({
    marks: document.querySelectorAll("#queueLog mark").length,
    label: document.querySelector(".q-find").innerText,
  }));
  check("queue: a find marks what it found and counts it",
    found.marks > 0 && /of \d+/.test(found.label), JSON.stringify(found));
  await context.close();
}

{
  const { page, context } = await open({ view: "queue" });
  await page.click("[data-run='ci-2007-0000']");
  await page.waitForTimeout(900);
  const seen = await page.evaluate(() => document.querySelector(".q-detail").innerText);
  check("queue: two verdicts that disagree are explained in one sentence",
    /This farm says failed and the hosted run says passed/.test(seen)
    && /hosted answer is the one that counts/.test(seen), seen.slice(0, 250));
  await context.close();
}

/* On a phone the detail panel is the whole viewport. Every other cover on this dashboard
   closes on Escape, and one that does not is a cover a reader can feel stuck in. */
{
  const { page, context, thrown } = await open({
    view: "queue", size: { width: 390, height: 844 },
  });
  await page.click("[data-run='ci-2001-0000']");
  await page.waitForTimeout(900);
  const sheet = await page.evaluate(() => {
    const node = document.querySelector(".q-detail");
    return node ? getComputedStyle(node).position : "";
  });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);
  const gone = await page.evaluate(() => !document.querySelector(".q-detail"));
  check("queue: the small screen sheet closes on Escape", sheet === "fixed" && gone,
    JSON.stringify({ sheet, gone }));
  check("queue: and the table is there to read again",
    (await page.evaluate(() => document.querySelectorAll(".q-row").length)) > 0);
  check("queue: nothing threw on Escape", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------ the drain preview */

{
  const { page, context, thrown, posted } = await open({ view: "machine" });
  await page.click("[data-power='drain']");
  await page.waitForTimeout(900);
  const confirm = await page.evaluate(() => document.querySelector(".m-confirm").innerText);
  check("machine: the drain confirm names the lanes it will stop",
    /demo-api-3f2a/.test(confirm), confirm.slice(0, 200));
  check("machine: the drain confirm says what is lost",
    /loses its verdict/.test(confirm) && /restart policy/.test(confirm), confirm.slice(0, 300));
  check("machine: the drain confirm says the agent runner stops",
    /stops the agent runner/.test(confirm), confirm.slice(0, 300));
  check("machine: the drain confirm says this page keeps running",
    /page keeps running/.test(confirm), confirm.slice(0, 300));
  await page.click("[data-confirm='drain']");
  await page.waitForTimeout(800);
  const during = await page.evaluate(() => ({
    disabled: document.querySelector("[data-power='drain']").disabled,
    label: document.querySelector("[data-power='drain']").textContent,
    body: document.getElementById("view").innerText,
  }));
  check("machine: a drain in flight refuses a second press",
    during.disabled && /running/.test(during.label), JSON.stringify(during).slice(0, 200));
  check("machine: the running job is named on the page", /Job job-/.test(during.body),
    during.body.slice(0, 200));
  check("machine: drain asks the power route", posted.some((url) => url.endsWith("/api/power")));
  await page.waitForTimeout(3000);
  const after = await page.evaluate(() => document.querySelector("[data-power='drain']").disabled);
  check("machine: the drain button comes back when its job ends", after === false);
  check("machine: nothing threw around the drain", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open({ view: "machine" });
  await page.click("[data-power='throttle']");
  await page.waitForTimeout(900);
  const throttle = await page.evaluate(() => document.querySelector(".m-confirm").innerText);
  check("machine: the throttle confirm names the caps and the database it releases",
    /40% of the CPU/.test(throttle) && /5.6 of 14 cores/.test(throttle)
    && /releases the verification database/.test(throttle), throttle.slice(0, 400));
  check("machine: the throttle confirm carries no number the server did not send",
    !/none of/.test(throttle), throttle.slice(0, 400));
  check("machine: the throttle confirm passes on the server's warnings",
    /Nothing is lost, and nothing is stopped/.test(throttle), throttle.slice(0, 400));
  await page.click("[data-power='resume']");
  await page.waitForTimeout(900);
  const resume = await page.evaluate(() => document.querySelector(".m-confirm").innerText);
  check("machine: the resume confirm says what it will respawn and that it spends subscription",
    /respawn every until-pr and until-merged lane/.test(resume) && /spending subscription/.test(resume),
    resume.slice(0, 300));
  await context.close();
}

/* The preview route walks the lanes on a real farm. A confirm nobody is looking at must stop
   asking for it, or the page keeps that walk going every three seconds for the life of the
   tab. */
{
  const { page, context, thrown } = await open({ view: "machine" });
  const asked = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/power/preview")) asked.push(request.url());
  });
  await page.click("[data-power='drain']");
  await page.waitForTimeout(1500);
  const whileOpen = asked.length;
  await page.click(".m-confirm .ghost-button");
  await page.waitForTimeout(600);
  const atClose = asked.length;
  await page.waitForTimeout(7000);
  check("machine: a confirm that was closed stops asking for its preview",
    whileOpen > 0 && asked.length === atClose,
    JSON.stringify({ whileOpen, atClose, later: asked.length }));
  check("machine: nothing threw when the confirm was closed", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context, thrown } = await open({
    view: "machine",
    overrides: { "/api/power/preview": JSON.stringify({}) },
  });
  await page.click("[data-power='drain']");
  await page.waitForTimeout(900);
  const confirm = await page.evaluate(() => document.querySelector(".m-confirm").innerText);
  check("machine: a preview with no lanes still says what drain does",
    /No lane is running/.test(confirm), confirm.slice(0, 200));
  check("machine: an empty preview throws nothing", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Three columns of the services table are three keys of the server's answer. The page once
   read changed_at, note and command, none of which is sent, so every row said "not known",
   every description was blank and the row that cannot be switched from here said "no command". */
{
  const { page, context } = await open({ view: "machine" });
  const seen = await page.evaluate(() => {
    const rows = [...document.querySelectorAll("#view table tr")];
    const pick = (word) => {
      const found = rows.find((node) => node.innerText.startsWith(word));
      return found ? [...found.querySelectorAll("td")].map((cell) => cell.innerText) : [];
    };
    return { runner: pick("agent runner"), dashboard: pick("This dashboard") };
  });
  check("machine: a service says when it last changed",
    seen.runner.length > 2 && /ago/.test(seen.runner[2]) && !/not known/.test(seen.runner[2]),
    JSON.stringify(seen.runner));
  check("machine: a service says what it does",
    /respawns a lane/.test(seen.runner[3] || ""), JSON.stringify(seen.runner));
  check("machine: the row that cannot be worked here hands over the command that works it",
    /fleet dashboard restart/.test((seen.dashboard[4] || "")), JSON.stringify(seen.dashboard));
  await context.close();
}

/* The queue runner is started by `fleet ci daemon start`. `fleet daemon start` is the agent
   runner, a different service on a different unit, and a fix column that hands a reader the
   wrong one of the two sends them to stop the farm's other half. */
{
  const { page, context } = await open({ view: "machine", state: "error" });
  const row = await page.evaluate(() => {
    const found = [...document.querySelectorAll("#view table tr")]
      .find((node) => /queue runner/.test(node.innerText));
    return found ? found.innerText : "";
  });
  check("machine: the queue runner is fixed by the command that starts the queue runner",
    /fleet ci daemon start/.test(row), row.slice(0, 160));
  await context.close();
}

/* ------------------------------------------------ projects, engines and accounts */

/* The Login column is two words from this page and one sentence from the server. The words
   are keyed by the server's own state names, and the sentence is the only part that says what
   to do about an account that is not in, so it is drawn in the row and not hidden in a hover. */
{
  const { page, context } = await open({ view: "machine" });
  const seen = await page.evaluate(() => {
    const rows = [...document.querySelectorAll("#view table tr")];
    const pick = (word) => {
      const found = rows.find((node) => node.innerText.startsWith(word));
      return found ? found.innerText : "";
    };
    return {
      waiting: pick("farm three"),
      unknown: pick("farm unread"),
      body: document.getElementById("view").innerText,
    };
  });
  check("machine: an account that has never been logged in is told so in full",
    /Waiting for the first login/.test(seen.waiting), seen.waiting.slice(0, 200));
  check("machine: a login this farm cannot read is not drawn as one never set up",
    /Cannot tell/.test(seen.unknown) && !/Waiting for the first login/.test(seen.unknown),
    seen.unknown.slice(0, 200));
  check("machine: the sentence that says what to do is in the row",
    /Log in once: ssh -t farm claude/.test(seen.waiting)
    && /could not read this account/.test(seen.unknown), seen.waiting.slice(0, 260));
  check("machine: every account's sentence is on the page",
    ["Lanes can be spawned", "has expired", "Log in once", "asked the farm to slow down",
      "could not read this account"].every((line) => seen.body.includes(line)),
    seen.body.slice(0, 400));
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
    for (const row of document.querySelectorAll("#view .m-models tbody tr")) {
      const name = row.querySelector("[data-model-open]");
      const id = name ? name.getAttribute("data-model-open") : "?";
      out[id] = {
        pills: [...row.querySelectorAll(".pill-text")].map((node) => node.textContent),
        status: row.querySelector("td:nth-child(4) .pill-text").textContent,
        meaning: row.querySelector("td:nth-child(4) .pill").className.replace("pill ", ""),
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
        why: row.querySelector("td:nth-child(4) .pill").getAttribute("title") || "",
        lines: Math.round(row.getBoundingClientRect().height),
      };
    }
    return out;
  });
  const want = {
    claude: { status: "On", meaning: "done", switch: true, test: true, remove: false },
    codex: { status: "Failing", meaning: "fail", switch: true, test: true, remove: false },
    qwen: { status: "Off", meaning: "pause", switch: true, test: true, remove: true },
    kimi: { status: "Needs a key", meaning: "wait", switch: false, test: true, remove: true },
    local: { status: "Not installed", meaning: "pause", switch: false, test: false, remove: false },
  };
  // Five, because this runs before the add-dialog checks at the end of this file write anything
  // into the stub's catalog. A new block that registers a model belongs after this one.
  check("machine: the models table has one row per status", Object.keys(seen).length === 5,
    Object.keys(seen).join(", "));
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
    /fleet models auth kimi/.test(seen.kimi.hint) && seen.kimi.test === true,
    `${seen.kimi.hint} | ${seen.kimi.text.slice(0, 120)}`);
  check("machine: a model that is failing every call can still be switched off",
    seen.codex.switch === true && seen.codex.switchLabel === "Switch off",
    JSON.stringify(seen.codex).slice(0, 160));
  check("machine: the switch says what pressing it does, never the state the row is in",
    seen.claude.switchLabel === "Switch off" && seen.qwen.switchLabel === "Switch on",
    `claude: ${seen.claude.switchLabel}, qwen: ${seen.qwen.switchLabel}`);
  check("machine: a model with one status wears one pill in that column",
    (seen.claude.pills || []).filter((word) => word === "On").length === 1,
    (seen.claude.pills || []).join(", "));
  check("machine: a failing model carries its reason on the pill, and the row stays one line",
    /the last health call timed out/.test(seen.codex.why) && !/timed out/.test(seen.codex.text),
    `${seen.codex.why} | ${seen.codex.text.slice(0, 120)}`);
  {
    // The owner's rule: a one-line table has one-line cells. Every row is the same height as
    // the first, whatever its cells hold, or a cell has wrapped.
    const heights = Object.values(seen).map((row) => row.lines);
    check("machine: every models row is one line high, none taller than its neighbours",
      heights.length > 1 && Math.max(...heights) - Math.min(...heights) <= 2, heights.join(", "));
  }
  check("machine: a model that is not installed says so, with what to run",
    /Not installed/.test(seen.local.text) && /example.invalid/.test(seen.local.text)
    && !/on the path/.test(seen.local.text), seen.local.text.slice(0, 200));
  check("machine: and says it once, in the status column and nowhere else",
    (seen.local.pills || []).length === 1 && seen.local.status === "Not installed",
    (seen.local.pills || []).join(", "));
  check("machine: an installed model says where it is",
    /\/usr\/bin\/codex/.test(seen.codex.text), seen.codex.text.slice(0, 120));
  check("machine: every row says how it is paid for",
    /Your Claude subscription/.test(seen.claude.text)
    && /An API key/.test(seen.qwen.text)
    && /Runs on this machine/.test(seen.local.text), seen.qwen.text.slice(0, 160));
  check("machine: no role or quality note is in the table",
    !/the workhorse/.test(await text(page)), "");
  check("machine: nothing was switched by drawing the models table",
    !posted.some((url) => url.endsWith("/api/models")), posted.join(" "));
  await context.close();
}

/* Status and Actions disagree on a real farm, and that is the server being right: a generic
   model is "off" until a test passes, however it is switched. The pill carries the state, the
   button carries the press, so a row like this says Off and offers Switch off. */
{
  const only = [{
    id: "gemini", label: "Gemini CLI", engine: "generic", source: "added", status: "off",
    enabled: true, installed: true, path: "/usr/bin/gemini", command: "gemini",
    access: "An API key, held on the farm.", auth_env: "GEMINI_API_KEY",
    run: "{bin} -p {task}", last_test: null, install_hint: "npm install -g @google/gemini-cli",
  }];
  const { page, context, thrown, sent } = await open({
    view: "machine",
    overrides: { "/api/engines": JSON.stringify(only) },
  });
  const seen = await page.evaluate(() => ({
    status: document.querySelector("#view .m-models td:nth-child(4) .pill-text").textContent,
    label: document.querySelector("[data-model-switch='gemini']").textContent,
  }));
  check("machine: a row that is switched on and still off says Off and offers Switch off",
    seen.status === "Off" && seen.label === "Switch off", JSON.stringify(seen));
  await page.click("[data-model-switch='gemini']");
  await page.waitForTimeout(800);
  const posted = sent.find((item) => item.url.endsWith("/api/models"));
  const body = JSON.parse((posted || {}).body || "{}");
  check("machine: and pressing it sends the press the button named",
    body.action === "disable" && body.id === "gemini", JSON.stringify(body));
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
    for (const row of document.querySelectorAll("#view .m-models tbody tr")) {
      const name = row.querySelector("[data-model-open]");
      const said = row.querySelector("td:nth-child(4) .pill-text");
      out[name.getAttribute("data-model-open")] = said ? said.textContent : "";
    }
    return out;
  });
  check("machine: a farm that sends no status word still draws the five",
    seen.one === "On" && seen.two === "Off" && seen.three === "Failing"
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
    rows: document.querySelectorAll("#view .m-models tbody tr").length,
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

/* A phone. The six column table with its floors was 857px wide inside a 354px frame, so the
   two columns this section is about, Status and Actions, were off the edge behind a sideways
   drag nothing announced. Under 640px it is a card list instead. */
{
  const { page, context, thrown } = await open({
    view: "machine",
    size: { width: 390, height: 844 },
  });
  const seen = await page.evaluate(() => {
    const table = document.querySelector("#view .m-models");
    const wrap = table.closest(".tablewrap");
    const row = table.querySelector("tbody tr");
    const box = row.getBoundingClientRect();
    return {
      head: getComputedStyle(table.querySelector("thead")).display,
      rows: getComputedStyle(row).display,
      drag: wrap.scrollWidth - wrap.clientWidth,
      labels: [...row.querySelectorAll("td")]
        .map((cell) => cell.getAttribute("data-col") || "").filter(Boolean),
      right: Math.round(box.right),
      view: window.innerWidth,
      status: (row.querySelector("td:nth-child(4) .pill-text") || {}).textContent || "",
      actions: Boolean(row.querySelector("[data-model-switch], [data-model-test]")),
    };
  });
  check("machine: on a phone the models table is a card per model, not a sideways table",
    seen.head === "none" && seen.rows === "grid" && seen.drag <= 1,
    JSON.stringify(seen).slice(0, 260));
  check("machine: and a card carries the name, the state, the access and the actions on screen",
    seen.labels.includes("Status") && seen.labels.includes("Access")
    && seen.labels.includes("Actions") && seen.status.length > 0 && seen.actions
    && seen.right <= seen.view, JSON.stringify(seen).slice(0, 260));
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
    body: JSON.stringify({ preset: "opencode", id: "shaped" }),
  })).json();
  const row = written.model || {};
  check("machine: the add route answers the row under model, with the preset's own fields",
    row.id === "shaped" && row.source === "added" && row.preset === "opencode"
    && row.auth_env === "OPENCODE_API_KEY", JSON.stringify(written).slice(0, 240));
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
  await page.click("[data-model-open='qwen']");
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
    drawer.open && /Qwen Code/.test(drawer.title), JSON.stringify(drawer).slice(0, 160));
  check("machine: the drawer carries what the table dropped",
    /headless mode/.test(drawer.text) && /qwen3-coder-plus/.test(drawer.text)
    && /QWEN_CODE_API_KEY/.test(drawer.text) && /Added on this farm/.test(drawer.text),
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
    id: "qwen", label: "Qwen Code", engine: "generic", source: "added", status: "off",
    enabled: false, installed: true, path: "/usr/bin/qwen", command: "qwen",
    access: "An API key, held on the farm.", auth_env: "QWEN_CODE_API_KEY",
    run: "{bin} -p {task}", last_test: null, health: "ok",
    docs: "https://example.invalid/docs/qwen-code",
  }];
  const second = await open({
    view: "machine",
    overrides: { "/api/engines": JSON.stringify(linked) },
  });
  await second.page.click("[data-model-open='qwen']");
  await second.page.waitForTimeout(500);
  const link = await second.page.evaluate(() => {
    const node = document.querySelector("#drawerBody a[href]");
    return node ? node.getAttribute("href") : "";
  });
  check("machine: a row that carries a documentation link draws it",
    link === "https://example.invalid/docs/qwen-code", link || "no link");
  check("machine: nothing threw on the linked drawer",
    second.thrown.length === 0, second.thrown[0]);
  await second.context.close();
}

/* The token can go while a confirm is open: the page is read from a second tab, or the token
   is rotated. Every write control obeys that answer, and a confirm's own button is a write
   control like any other. */
{
  let writable = true;
  const { page, context, thrown, posted } = await open({
    view: "machine",
    overrides: {
      "/api/access": (handler) => handler.fulfill({
        status: 200,
        contentType: "application/json",
        body: writable
          ? JSON.stringify({ writable: true, reason: "", token_required: true, loopback: true })
          : READ_ONLY,
      }),
    },
  });
  await page.click("[data-remove-account='farm-one']");
  await page.waitForTimeout(500);
  const live = await page.evaluate(() =>
    document.querySelector("[data-confirm='remove-account:farm-one']").disabled);
  writable = false;
  await page.evaluate(() => import("/static/core/api.js").then((api) => api.refresh("/api/access")));
  await page.waitForTimeout(3600);
  const account = await page.evaluate(() => {
    const node = document.querySelector("[data-confirm='remove-account:farm-one']");
    return { there: Boolean(node), disabled: node ? node.disabled : null };
  });
  await page.click("[data-confirm='remove-account:farm-one']", { force: true });
  await page.waitForTimeout(500);
  check("machine: a remove confirm is live while the page may write", live === false, String(live));
  check("machine: and switched off the moment it may not",
    account.there && account.disabled === true, JSON.stringify(account));
  check("machine: so a forced press removes nothing",
    !posted.some((url) => url.endsWith("/api/accounts/remove")), posted.join(" "));
  check("machine: nothing threw when the token went", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The same for the project remove confirm, the other write control that carried no guard. */
{
  let writable = true;
  const { page, context, posted } = await open({
    view: "machine",
    overrides: {
      "/api/access": (handler) => handler.fulfill({
        status: 200,
        contentType: "application/json",
        body: writable
          ? JSON.stringify({ writable: true, reason: "", token_required: true, loopback: true })
          : READ_ONLY,
      }),
    },
  });
  await page.click("[data-remove-project='sandbox']");
  await page.waitForTimeout(500);
  writable = false;
  await page.evaluate(() => import("/static/core/api.js").then((api) => api.refresh("/api/access")));
  await page.waitForTimeout(3600);
  const project = await page.evaluate(() => {
    const node = document.querySelector("[data-confirm='remove-project:sandbox']");
    return { there: Boolean(node), disabled: node ? node.disabled : null };
  });
  await page.click("[data-confirm='remove-project:sandbox']", { force: true });
  await page.waitForTimeout(500);
  check("machine: the project remove confirm is switched off with the token",
    project.there && project.disabled === true, JSON.stringify(project));
  check("machine: so a forced press removes no project",
    !posted.some((url) => url.endsWith("/api/projects/remove")), posted.join(" "));
  await context.close();
}

/* The message after a removal names the block that is now free. It read the answer under a
   key nothing sends, so it only ever said "the ports it held". */
{
  const { page, context, thrown } = await open({ view: "machine" });
  await page.click("[data-remove-project='sandbox']");
  await page.waitForTimeout(500);
  await page.click("[data-confirm='remove-project:sandbox']");
  await page.waitForTimeout(900);
  const said = await page.evaluate(() => {
    const node = document.querySelector(".toast, [class*='toast']");
    return node ? node.innerText : document.body.innerText;
  });
  check("machine: the removal message names the block that is now free",
    /5220 to 5319/.test(said) && !/Ports it held/.test(said), said.slice(0, 200));
  check("machine: nothing threw around the removal", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Registering clones a repository, which takes minutes. The button that started it has to
   hold, or a second press starts a second clone and only the server is there to refuse it. */
{
  const { page, context, thrown } = await open({ view: "machine" });
  const posts = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/projects")) posts.push(1);
  });
  await page.fill("#view input[aria-label='Project name']", "held");
  await page.fill("#view input[aria-label='Repository']", "your-org/held");
  await page.click("[data-add-project]");
  await page.waitForTimeout(900);
  const during = await page.evaluate(() => ({
    disabled: document.querySelector("[data-add-project]").disabled,
    label: document.querySelector("[data-add-project]").textContent,
    body: document.getElementById("view").innerText,
  }));
  check("machine: the Add button holds while the registration runs",
    during.disabled === true && /Adding/.test(during.label),
    JSON.stringify({ disabled: during.disabled, label: during.label }));
  check("machine: and the running job is named next to it",
    /Job job-\d+ is running/.test(during.body), during.body.slice(0, 200));
  await page.click("[data-add-project]", { force: true });
  await page.waitForTimeout(400);
  check("machine: so a second press starts no second clone", posts.length === 1,
    `${posts.length} sent`);
  let back = true;
  for (let attempt = 0; attempt < 15; attempt += 1) {
    await page.waitForTimeout(600);
    back = await page.evaluate(() => document.querySelector("[data-add-project]").disabled);
    if (back === false) break;
  }
  check("machine: the Add button comes back when the job ends", back === false, String(back));
  // The row lands with the table's next refresh, a beat after the button returns.
  let rowSeen = false;
  for (let attempt = 0; attempt < 10 && !rowSeen; attempt += 1) {
    rowSeen = /your-org\/held/.test(await text(page));
    if (!rowSeen) await page.waitForTimeout(500);
  }
  check("machine: and the row appeared on its own", rowSeen, "");
  check("machine: nothing threw while the registration ran", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The port block a new project gets is the farm's to hand out. The page used to work one out
   of every port in the table, api and end-to-end bases included, put it in the field, and send
   it, so the farm's own answer was never used. */
{
  const { page, context, thrown } = await open({ view: "machine" });
  const bodies = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/projects")) {
      bodies.push(request.postData() || "");
    }
  });
  const free = await page.evaluate(async () => {
    const answer = await (await fetch("/api/projects/next-port")).json();
    return String(answer.next_port_base);
  });
  const shown = await page.evaluate(() =>
    document.querySelector("#view input[aria-label='Port base']").placeholder);
  check("machine: the port field suggests the block the farm says is free",
    shown === free, `${shown} shown, ${free} free`);
  await page.fill("#view input[aria-label='Project name']", "fresh");
  await page.fill("#view input[aria-label='Repository']", "your-org/fresh");
  await page.click("[data-add-project]");
  await page.waitForTimeout(900);
  check("machine: an empty port field sends no block, so the farm picks one",
    bodies.length === 1 && !bodies[0].includes("port_base"), bodies.join(" "));
  /* The table is re-read on its own rhythm, so the row is waited for rather than timed. */
  let row = "no row for fresh";
  for (let attempt = 0; attempt < 24 && !row.includes("your-org/fresh"); attempt += 1) {
    await page.waitForTimeout(1000);
    row = await page.evaluate(() => {
      const found = [...document.querySelectorAll("#view table tr")]
        .find((node) => node.innerText.includes("your-org/fresh"));
      return found ? found.innerText : "no row for fresh";
    });
  }
  check("machine: and the row lands on the farm's own block",
    row.includes(`web ${free}`), row.slice(0, 200));
  check("machine: nothing threw around the port suggestion", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A port block is the one field of this form that is a number, and a field that reads "not a
   port" used to be posted as port_base null for the registry to make sense of. */
{
  const { page, context, posted, thrown } = await open({ view: "machine" });
  await page.fill("#view input[aria-label='Project name']", "junk");
  await page.fill("#view input[aria-label='Repository']", "your-org/junk");
  await page.fill("#view input[aria-label='Port base']", "not a port");
  await page.click("[data-add-project]");
  await page.waitForTimeout(700);
  const body = await text(page);
  check("machine: a port block that is not a number is refused in a sentence",
    /A port block is a whole number/.test(body), body.slice(0, 200));
  check("machine: and nothing was sent to the registry",
    !posted.some((url) => url.endsWith("/api/projects")), posted.join(" "));
  check("machine: nothing threw over the port field", thrown.length === 0, thrown[0]);
  await context.close();
}

{
  const { page, context } = await open({ view: "machine" });
  await page.click("[data-remove-project='demo']");
  await page.waitForTimeout(600);
  const confirm = await page.evaluate(() => document.querySelector(".m-confirm").innerText);
  const offered = await page.evaluate(() => document.querySelectorAll("[data-confirm^='remove-project']").length);
  check("machine: removing a project with open lanes is refused with the count",
    /3 open lanes/.test(confirm), confirm.slice(0, 200));
  check("machine: and no button is offered to do it anyway", offered === 0, String(offered));
  await page.click("[data-remove-project='sandbox']");
  await page.waitForTimeout(600);
  const free = await page.evaluate(() => document.querySelector(".m-confirm").innerText);
  check("machine: an idle project names the port block that becomes free",
    /5220/.test(free) && /registry only|registry/.test(free), free.slice(0, 250));
  await context.close();
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



{
  const { page, context, thrown } = await open({ view: "machine" });
  await page.click("[data-accounts-refresh]");
  await page.waitForTimeout(900);
  const quiet = await page.evaluate(() => ({
    disabled: document.querySelector("[data-accounts-refresh]").disabled,
    label: document.querySelector("[data-accounts-refresh]").textContent,
  }));
  check("machine: refresh goes quiet for a minute after a press",
    quiet.disabled && /in \d/.test(quiet.label), JSON.stringify(quiet));
  await page.click("[data-add-account]");
  await page.waitForTimeout(400);
  await page.fill("#drawer input[aria-label='Account name']", "farm-five");
  await page.click("[data-add-start]");
  await page.waitForTimeout(1000);
  const step = await page.evaluate(() => document.querySelector(".m-steps").innerText);
  check("machine: the add flow shows the exact command to run",
    /ssh -t farm/.test(step) && /farm-five/.test(step), step.slice(0, 200));
  check("machine: and says it is waiting for the first login",
    /Waiting for the first login/.test(step), step.slice(0, 200));
  await page.waitForTimeout(4000);
  const flipped = await page.evaluate(() => document.querySelector(".m-steps").innerText);
  check("machine: the step panel turns itself into logged in",
    /Logged in/.test(flipped), flipped.slice(0, 200));
  const dialog = await page.evaluate(() => {
    const host = document.getElementById("drawer");
    const title = document.getElementById("drawerTitle");
    return {
      open: host && !host.hidden,
      role: host && host.getAttribute("role"),
      title: title && title.textContent,
      inDrawer: Boolean(host && host.querySelector(".m-steps")),
      copy: Boolean(host && host.querySelector("[data-add-copy]")),
      command: Boolean(host && host.querySelector("[data-add-command]")),
      steps: host ? host.querySelectorAll(".m-steps li").length : 0,
    };
  });
  check("machine: adding an account is a dialog with the command, a copy button and the steps",
    dialog.open && dialog.role === "dialog" && dialog.inDrawer && dialog.copy && dialog.command && dialog.steps >= 3,
    JSON.stringify(dialog));
  // The harness wires the drawer's Close button and scrim; the Escape key is the real shell's
  // and is covered by the sibling suite against index.html.
  await page.click("#drawerClose");
  await page.waitForTimeout(300);
  const closed = await page.evaluate(() => document.getElementById("drawer").hidden);
  check("machine: Close shuts the add dialog", closed);
  await page.click("[data-add-account]");
  await page.waitForTimeout(400);
  const choices = await page.evaluate(() => {
    const host = document.getElementById("drawer");
    const nodes = [...host.querySelectorAll("[data-engine-choice]")];
    return {
      count: nodes.length,
      radios: nodes.every((node) => node.getAttribute("role") === "radio"),
      offOnes: nodes.filter((node) => node.disabled).map((node) => node.getAttribute("data-engine-choice")),
      chosen: nodes.filter((node) => node.getAttribute("aria-checked") === "true").length,
    };
  });
  // Which engines are offered, and that an uninstalled one cannot be picked, is the subject of
  // its own case below: this one is about the dialog drawing them as one radio group.
  check("machine: the dialog offers the engines as choices, with one of them chosen",
    choices.count >= 2 && choices.radios && choices.chosen === 1,
    JSON.stringify(choices));
  await page.click("#drawerClose");
  check("machine: nothing threw around the add flow", thrown.length === 0, thrown[0]);
  await context.close();
}

/* An account is a subscription, so the dialog that adds one offers the two engines that have
   a subscription and not the whole model catalog. Offering a generic CLI here asked a person
   to log in to a thing that is paid for by the token and has no login at all. */
{
  const { page, context, thrown } = await open({ view: "machine" });
  await page.click("[data-add-account]");
  await page.waitForTimeout(700);
  const offered = await page.evaluate(() => [
    ...document.querySelectorAll("#drawer [data-engine-choice]"),
  ].map((node) => node.getAttribute("data-engine-choice")));
  check("machine: adding an account offers the subscription engines and no model",
    offered.join(",") === "claude,codex", offered.join(",") || "none");
  check("machine: nothing threw on the engine choices", thrown.length === 0, thrown[0]);
  await context.close();

  /* A subscription engine this farm cannot run is still offered, and still cannot be picked:
     the reader has to see why no Codex account can be added here. */
  const half = [
    { id: "claude", label: "Claude Code", engine: "claude", status: "on", enabled: true,
      installed: true, path: "/usr/bin/claude", command: "claude", source: "shipped",
      access: "Your Claude subscription.", last_test: null },
    { id: "codex", label: "Codex", engine: "codex", status: "not_installed", enabled: false,
      installed: false, path: "", command: "codex", source: "shipped",
      access: "Your ChatGPT subscription.", last_test: null,
      install_hint: "npm install -g @openai/codex" },
    { id: "qwen", label: "Qwen Code", engine: "generic", status: "off", enabled: false,
      installed: true, path: "/usr/bin/qwen", command: "qwen", source: "added",
      access: "An API key, held on the farm.", last_test: null },
  ];
  const second = await open({
    view: "machine",
    overrides: { "/api/engines": JSON.stringify(half) },
  });
  await second.page.click("[data-add-account]");
  await second.page.waitForTimeout(700);
  const seen = await second.page.evaluate(() => [
    ...document.querySelectorAll("#drawer [data-engine-choice]"),
  ].map((node) => `${node.getAttribute("data-engine-choice")}:${node.disabled ? "off" : "on"}`));
  check("machine: an engine this farm cannot run is offered and cannot be picked",
    seen.join(",") === "claude:on,codex:off", seen.join(",") || "none");
  check("machine: nothing threw on a farm missing an engine",
    second.thrown.length === 0, second.thrown[0]);
  await second.context.close();
}

/* ------------------------------------------------------ adding a model */

/* Step one is the choice of service. A preset already in this farm's catalog is shown and not
   choosable: adding the same service twice writes a second entry the farm then has to tell
   apart, and the owner's complaint was that nothing on this screen was clear. */
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
  check("machine: the dialog draws a card per service", presets.count >= 8 && presets.radios,
    JSON.stringify(presets).slice(0, 200));
  check("machine: a service already in the catalog is said to be, and cannot be picked",
    presets.off.includes("claude") && presets.alreadySaid.includes("claude"),
    `off: ${presets.off.join(", ")} said: ${presets.alreadySaid.join(", ")}`);
  check("machine: every choosable service says whether it is safe to run headless",
    presets.terms + presets.off.length >= presets.count, JSON.stringify(presets).slice(0, 200));
  check("machine: and a service whose terms forbid a farm says so",
    presets.risky.length > 0 || presets.off.includes("kimi"), presets.risky.join(", "));
  check("machine: every card says how that service is paid for",
    /An API key, billed per token/.test(presets.text)
    && /Runs on this machine/.test(presets.text), presets.text.slice(0, 200));

  /* A service behind a key: the command that takes it is named, and the page says out loud
     that the key does not pass through it. */
  await page.click("#drawer [data-preset='gemini']");
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
    key.command === "fleet models auth gemini", key.command);
  check("machine: and says a key never goes through this page",
    /A key never goes through this page/.test(key.text)
    && /Paste the key when it asks/.test(key.text), key.text.slice(0, 400));
  check("machine: the name is filled in from the preset and the variant is offered",
    key.name === "gemini" && key.variant === "gemini-2.5-pro", JSON.stringify(key).slice(0, 160));
  check("machine: and the dialog asks for no key of its own",
    !/password/.test(key.text) && key.fields <= 2, JSON.stringify(key).slice(0, 160));

  /* A local service: two commands, nothing paid, no key at all. */
  await page.click("#drawer [data-preset='ollama']");
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
    /install.sh/.test(local.install) && local.pull === "ollama pull qwen2.5-coder:14b"
    && local.auth === false, JSON.stringify(local).slice(0, 200));
  check("machine: and says nothing is paid for it",
    /Nothing is paid/.test(local.text), local.text.slice(0, 200));

  /* Registering sends the preset, the name and the variant, and nothing else. */
  await page.click("#drawer [data-preset='gemini']");
  await page.waitForTimeout(300);
  await page.click("[data-model-register]");
  await page.waitForTimeout(1200);
  const add = sent.filter((row) => row.url.endsWith("/api/models/add"));
  const body = add.length ? JSON.parse(add[0].body || "{}") : {};
  check("machine: Register posts the preset, the name and the variant", add.length === 1
    && body.preset === "gemini" && body.id === "gemini" && body.variant === "gemini-2.5-pro",
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
    last.command === "fleet models auth gemini" && /then press Test/.test(last.said),
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

/* A local runner's pull command is the preset's own (pull_hint), not one this page builds. The
   line it built, "{bin} pull {variant}", is Ollama's by luck and is wrong for the next local
   runner a farm adds. */
{
  const own = [{
    id: "lmstudio", label: "LM Studio", color: "#8b949e", kind: "local", tos_kind: "safe",
    engine: "generic", bin: "lms", install_hint: "brew install lmstudio",
    pull_hint: "lms get <variant> --yes", auth_env: "", run: "{bin} run {variant} {task}",
    health: "Reply with exactly: OK", tos: "runs on this machine, so there are no service terms",
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
   which put a green pill on Custom command, whose terms nobody here has read. */
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
    said.gemini === "safe headless" && said.ollama === "safe headless", JSON.stringify(said));
  check("machine: a service whose terms refuse a farm says so, and is not called safe",
    said.kimi === "not permitted", JSON.stringify(said));
  check("machine: and a command nobody has read the terms of says check the terms",
    said.custom === "check the terms", JSON.stringify(said));
  await context.close();

  /* A farm on a server that sends the sentence and no classification. The words of the
     sentence decide, and a sentence that is neither is a thing to read, not to trust. */
  const own = [
    { id: "one", label: "Refuses it", kind: "key", engine: "generic", bin: "one",
      install_hint: "", pull_hint: "", auth_env: "ONE_API_KEY", run: "{bin} -p {task}",
      health: "Reply with exactly: OK", tos: "its terms forbid non-interactive use",
      access: "An API key.", variants: [], docs: "", added: false },
    { id: "two", label: "Documents it", kind: "key", engine: "generic", bin: "two",
      install_hint: "", pull_hint: "", auth_env: "TWO_API_KEY", run: "{bin} -p {task}",
      health: "Reply with exactly: OK", tos: "a documented non-interactive mode",
      access: "An API key.", variants: [], docs: "", added: false },
    { id: "three", label: "Says nothing", kind: "key", engine: "generic", bin: "three",
      install_hint: "", pull_hint: "", auth_env: "THREE_API_KEY", run: "{bin} -p {task}",
      health: "Reply with exactly: OK", tos: "", access: "An API key.", variants: [],
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

/* A command of your own is authenticated under the name you give it, so step 3 has no command
   to show until there is a name. It used to fall back to the preset's id and print "fleet models
   auth custom", which is a runnable-looking command that does nothing. */
{
  const { page, context, thrown } = await open({ view: "machine", state: "empty" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='custom']");
  await page.waitForTimeout(400);
  const bare = await page.evaluate(() => {
    const host = document.getElementById("drawerBody");
    return {
      command: host.querySelector("[data-model-auth]") ? host.querySelector("[data-model-auth]").textContent : "",
      said: host.innerText,
    };
  });
  check("machine: a command of your own shows no auth command before it has a name",
    bare.command === "" && /Name it, and it appears here/.test(bare.said),
    JSON.stringify(bare).slice(0, 240));
  check("machine: and never prints fleet models auth custom",
    !/fleet models auth custom/.test(bare.said), bare.said.slice(0, 300));
  await page.fill("#drawer [data-model-id]", "mine");
  await page.waitForTimeout(500);
  const named = await page.evaluate(() => {
    const node = document.querySelector("#drawerBody [data-model-auth]");
    return node ? node.textContent : "";
  });
  check("machine: and shows it under that name once it is typed",
    named === "fleet models auth mine", named || "no command");
  check("machine: nothing threw on a command of your own", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The name rule the dialog teaches is the farm's own. The page used to accept a capital, a
   dot and forty characters, and every one of those is refused by lib/models.py, which writes
   the name as a table in this farm's catalog. */
{
  // An empty catalog, because every preset is choosable there and the cases above have already
  // written gemini into this stub's catalog.
  const { page, context, thrown, sent } = await open({ view: "machine", state: "empty" });
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='gemini']");
  await page.waitForTimeout(300);
  await page.fill("#drawer [data-model-id]", "Gemini");
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
  for (const name of ["Gemini", "my.model", "a", "g".repeat(32)]) {
    const answer = await fetch(`${BASE}/api/models/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset: "gemini", id: name }),
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
  await page.click("#drawer [data-preset='gemini']");
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
      ...await post({ preset: "gemini", id: "keyed", [field]: "sk-abcdefgh12345678" }),
    });
  }
  check("machine: a credential in the body is refused by any name it goes by",
    answers.every((row) => row.status === 400
      && /A key never goes through this page/.test(row.said)),
    JSON.stringify(answers.filter((row) => row.status !== 400)).slice(0, 300));
  check("machine: and the refusal names the command that does take one",
    answers.every((row) => /fleet models auth keyed/.test(row.said)),
    answers[0].said);
  const written = await post({ preset: "custom", id: "pasted", bin: "mine",
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
  await page.click("#drawer [data-preset='ollama']");
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
}

/* Remove says what it deletes before it deletes it, and a model that shipped with the farm is
   never offered it at all. */
{
  const { page, context, thrown, posted } = await open({ view: "machine" });
  await page.click("[data-model-remove='qwen']");
  await page.waitForTimeout(500);
  const asked = await page.evaluate(() => document.querySelector("#view .m-confirm").innerText);
  check("machine: Remove asks first, naming the entry and the key it deletes",
    /Remove Qwen Code\?/.test(asked) && /deleted from this farm's catalog/.test(asked)
    && /key stored/.test(asked), asked.slice(0, 300));
  check("machine: and the key by the name of the variable that holds it",
    /QWEN_CODE_API_KEY/.test(asked), asked.slice(0, 300));
  await page.click("#view .m-confirm .ghost-button");
  await page.waitForTimeout(400);
  check("machine: keeping it sends nothing",
    !posted.some((url) => url.endsWith("/api/models/remove")), posted.join(" "));

  /* And the whole way through on a model this run added, so the table is read back afterwards
     rather than trusted. */
  await page.click("[data-add-model]");
  await page.waitForTimeout(700);
  await page.click("#drawer [data-preset='aider']");
  await page.waitForTimeout(300);
  await page.click("[data-model-register]");
  await page.waitForTimeout(1200);
  await page.click("[data-model-done]");
  await page.waitForTimeout(1200);
  const added = await page.evaluate(() => Boolean(document.querySelector("[data-model-remove='aider']")));
  check("machine: a model this operator added can be removed", added, "no Remove on the new row");
  await page.click("[data-model-remove='aider']");
  await page.waitForTimeout(400);
  await page.click("[data-confirm='remove-model:aider']");
  await page.waitForTimeout(1400);
  const after = await page.evaluate(() => ({
    row: Boolean(document.querySelector("[data-model-open='aider']")),
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
   only the rows added in the same process, so the two fixture rows carrying source "added" wore a
   Remove button that answered "there is no model with that name" the first time it was pressed. */
{
  const { page, context, thrown, posted } = await open({ view: "machine" });
  await page.click("[data-model-remove='kimi']");
  await page.waitForTimeout(500);
  await page.click("[data-confirm='remove-model:kimi']");
  await page.waitForTimeout(1500);
  const seen = await page.evaluate(() => {
    const models = [...document.querySelectorAll("#view .section")]
      .find((item) => item.innerText.startsWith("Models"));
    return {
      row: Boolean(document.querySelector("[data-model-open='kimi']")),
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
        body: JSON.stringify({ error: "qwen is held open by a lane that is still running" }),
      }),
    },
  });
  await page.click("[data-model-remove='qwen']");
  await page.waitForTimeout(500);
  await page.click("[data-confirm='remove-model:qwen']");
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

/* Two commands of your own are two rows, each under the name its operator gave it. The server
   takes a row's label from the preset, and for Custom command that is the name of the card, so
   two of them drew as two rows both called "Custom command". */
{
  const { page, context, thrown } = await open({ view: "machine" });
  for (const [name, command] of [["mine-one", "one-cli"], ["mine-two", "two-cli"]]) {
    await page.click("[data-add-model]");
    await page.waitForTimeout(700);
    await page.click("#drawer [data-preset='custom']");
    await page.waitForTimeout(300);
    await page.fill("#drawer [data-model-id]", name);
    await page.fill("#drawer [data-model-bin]", command);
    await page.fill("#drawer [data-model-run-template]", "{bin} -p {task}");
    await page.click("[data-model-register]");
    await page.waitForTimeout(1300);
    await page.click("[data-model-done]");
    await page.waitForTimeout(1000);
  }
  const named = await page.evaluate(() => [
    ...document.querySelectorAll("#view .m-models tbody tr"),
  ].map((row) => row.querySelector("td:first-child").innerText.replace(/\n/g, " ")));
  check("machine: two commands of your own are two rows under the names they were given",
    named.some((line) => /mine-one/.test(line)) && named.some((line) => /mine-two/.test(line)),
    named.join(" | "));
  check("machine: and neither of them is called Custom command",
    named.every((line) => !/Custom command/.test(line)), named.join(" | "));
  check("machine: nothing threw around a command of your own",
    thrown.length === 0, thrown[0]);
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
      rows: document.querySelectorAll("#view .m-models tbody tr").length,
      names: [...document.querySelectorAll("#view [data-model-open]")].filter((node) => !node.disabled).length,
    };
  });
  check("machine: a read-only page still draws every model row", table.rows >= 5,
    JSON.stringify(table));
  check("machine: and switches every model control off, with the reason on each",
    table.total > 0 && table.live === 0 && table.reasons === table.total, JSON.stringify(table));
  check("machine: reading a model is still allowed", table.names === table.rows,
    JSON.stringify(table));
  await page.click("[data-model-open='qwen']");
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

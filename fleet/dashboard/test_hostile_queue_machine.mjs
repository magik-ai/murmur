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
  await page.selectOption("#view select[aria-label='Filter by state']", { label: "Any" });
  await page.waitForTimeout(500);
  const back = await count();
  check("queue: Any state gives every run back", all > 0 && narrowed > 0 && narrowed < all
    && back === all, JSON.stringify({ all, narrowed, back }));
  await page.selectOption("#view select[aria-label='Filter by project']", "demo");
  await page.waitForTimeout(500);
  const oneProject = await count();
  await page.selectOption("#view select[aria-label='Filter by project']", { label: "All" });
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
  /* The prerequisites table lives in the Health section, which a farm draws only when it sets
     FLEET_DASH_HEALTH=on; this page is that farm. */
  const healthOn = async (route) => {
    const answer = await route.fetch();
    const config = await answer.json();
    config.features = { ...(config.features || {}), health_panel: true };
    return route.fulfill({ response: answer, json: config });
  };
  const { page, context } = await open({ view: "machine", state: "error",
    overrides: { "/api/config": healthOn } });
  const row = await page.evaluate(() => {
    const found = [...document.querySelectorAll("#view table tr")]
      .find((node) => /queue runner/.test(node.innerText));
    return found ? found.innerText : "";
  });
  check("machine: the queue runner is fixed by the command that starts the queue runner",
    /fleet ci daemon start/.test(row), row.slice(0, 160));
  await context.close();
}

/* A farm that has not asked for the Health section draws none, even with prerequisites
   missing. (The tab's count is checked in test_ui.mjs: this harness draws no tab badges.) */
{
  const { page, context } = await open({ view: "machine", state: "error" });
  const body = await text(page);
  check("machine: with Health off, the page draws no Health section",
    !/What this farm needs/.test(body), body.slice(0, 120));
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
      loggedTitle: (document.querySelector("#view .m-login[title*='Lanes can be spawned']") || {}).title || "",
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
  check("machine: every account that needs something done says it in the row",
    ["has expired", "Log in once", "asked the farm to slow down",
      "could not read this account"].every((line) => seen.body.includes(line)),
    seen.body.slice(0, 400));
  check("machine: a login that is in keeps its sentence in the cell's title, not in the row",
    /Lanes can be spawned/.test(seen.loggedTitle) && !seen.body.includes("Lanes can be spawned"),
    seen.loggedTitle);
  await context.close();
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

/* Importing a project, its job, its port block and its checks moved with the Projects section
   to views/projects.js, and are checked in test_hostile_projects.mjs. */

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

await browser.close();
stub.kill();

const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

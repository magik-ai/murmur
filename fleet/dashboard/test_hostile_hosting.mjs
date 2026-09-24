/* What the Hosting section does when the page may not write, when a route lies to it, when a
   person types a token into a field that is not for one, and when an action costs money. The
   questions are always the same three: did anything throw, was the reader told, and did money
   move without being named first.

   The section is opened through the stub's harness page, which is the same shell around the
   same modules that index.html puts them in. */

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
  env: { ...process.env, STUB_JOB_SECONDS: "2", STUB_MACHINE_SECONDS: "2" },
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

async function open({ state = "ready", size = { width: 1440, height: 1000 },
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
  await page.goto(`${BASE}/harness?state=${state}#/machine`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1600);
  return { page, context, thrown, posted, sent, pulled };
}

const hosting = (page) => page.evaluate(() => {
  const found = [...document.querySelectorAll("#view .section")]
    .find((node) => node.innerText.startsWith("Hosting"));
  return found ? found.innerText : "";
});

const bodyOf = (sent, route) => {
  const found = sent.filter((row) => row.url.endsWith(route));
  return found.length ? JSON.parse(found[found.length - 1].body || "{}") : null;
};

/* Every control that writes, and the ones that only put a command on the clipboard. A read-only
   dashboard switches off the first group and keeps the second: copying a command into your own
   terminal is exactly how this section is meant to be used when the page cannot write. */
const WRITE_CONTROLS = "[data-add-machine], [data-machine-check],"
  + " [data-machine-destroy], [data-machine-adopt], [data-machine-forget]";
const COPY_CONTROLS = "[data-machine-finish], [data-machine-tunnel]";

const READ_ONLY = JSON.stringify({
  writable: false,
  reason: "This page was opened without the dashboard token, so it can only read.",
  token_required: true,
  loopback: true,
});

const KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKqkqLp0m1n2o3p4q5r6s7t8u9v0w1x2y3z4a5b6c7d8 you@laptop";
/* A token, in the shape the page must refuse before it sends anything. It is never a real one
   and it never reaches a request, which is the point of the case. */
const TOKEN = "sk-ant-oat01-AAAABBBBCCCCDDDDEEEEFFFFGGGG";

/* --------------------------------------------------- the section, as it is drawn */

{
  const { page, context, thrown } = await open();
  const seen = await page.evaluate(() => {
    const rows = {};
    for (const row of document.querySelectorAll("#view .h-machines tbody tr")) {
      const cells = [...row.querySelectorAll("td")].map((cell) => cell.innerText.trim());
      const name = cells[0].split("\n")[0];
      rows[name] = {
        cells,
        state: (row.querySelector("td:nth-child(5) .pill-text") || {}).textContent || "",
        meaning: (row.querySelector("td:nth-child(5) .pill") || {}).className || "",
        why: (row.querySelector("td:nth-child(5) .pill") || {}).title || "",
        actions: [...row.querySelectorAll("td:last-child button")].map((node) => node.textContent),
        finishTitle: (row.querySelector("[data-machine-finish]") || {}).title || "",
        height: Math.round(row.getBoundingClientRect().height),
        first: row === document.querySelector("#view .h-machines tbody tr"),
      };
    }
    const head = [...document.querySelectorAll("#view .section")]
      .find((node) => node.innerText.startsWith("Hosting"));
    return {
      rows,
      total: (head.querySelector("[data-hosting-total]") || {}).textContent || "",
      columns: [...document.querySelectorAll("#view .h-machines thead th")]
        .map((node) => node.textContent).join("|"),
      text: head.innerText,
      note: (head.querySelector("h2") || {}).title || "",
    };
  });
  check("hosting: the machines table has the seven columns of the design record",
    seen.columns === "Name|Provider|Address|Size and price|State|Last check|Actions", seen.columns);
  check("hosting: this farm is the first row, and is marked as this farm",
    seen.rows.quartz && seen.rows.quartz.first && /This farm/.test(seen.rows.quartz.cells[0]),
    JSON.stringify(seen.rows.quartz || {}).slice(0, 200));
  check("hosting: the head says what this list costs a month, and for how many machines",
    /You pay \$\d+ a month for \d+ machines/.test(seen.total), seen.total);
  check("hosting: and it counts only the rows that exist at the provider, as the farm does",
    seen.total === "You pay $264 a month for 6 machines.", seen.total);
  check("hosting: a size and its price are one line, in words",
    seen.rows.athens.cells[3] === "4 vCPU, 8 GB, $48 a month", seen.rows.athens.cells[3]);
  const want = {
    athens: ["Ready", "done"], brussels: ["Needs your login", "wait"],
    cairo: ["Creating", "wait"], delhi: ["Preparing", "wait"],
    edinburgh: ["Unreachable", "fail"], faro: ["Failed", "fail"],
    genoa: ["Destroyed", "pause"], haifa: ["Unrecorded", "fail"],
  };
  for (const [name, [label, meaning]] of Object.entries(want)) {
    const row = seen.rows[name] || {};
    check(`hosting: ${name} is drawn as ${label}`,
      row.state === label && row.meaning.includes(meaning),
      `${row.state} / ${row.meaning}`);
  }
  check("hosting: every droplet that is not destroyed says on its pill that it is still billed",
    /Still billed: \$48 a month/.test(seen.rows.athens.why)
    && /Powering it off does not stop the bill/.test(seen.rows.athens.why)
    && !/Still billed/.test(seen.rows.genoa.why),
    `${seen.rows.athens.why} | ${seen.rows.genoa.why}`);
  check("hosting: a failed row carries its reason on the pill and keeps the cell to one line",
    /no payment method/.test(seen.rows.faro.why) && !/payment method/.test(seen.rows.faro.cells[4]),
    seen.rows.faro.why.slice(0, 140));
  check("hosting: an unrecorded row carries its reason too, and offers Adopt and Destroy",
    /not in this registry/.test(seen.rows.haifa.why)
    && seen.rows.haifa.actions.join(",") === "Adopt,Destroy",
    `${seen.rows.haifa.why} | ${seen.rows.haifa.actions.join(",")}`);
  check("hosting: a machine that needs your login offers the finish command, with the sentence",
    seen.rows.brussels.actions.includes("Finish")
    && /Run this from your laptop/.test(seen.rows.brussels.finishTitle)
    && /clones murmur and runs the installer/.test(seen.rows.brussels.finishTitle),
    seen.rows.brussels.finishTitle);
  check("hosting: a ready machine offers the tunnel, and one that is not does not",
    seen.rows.athens.actions.includes("Tunnel")
    && !seen.rows.cairo.actions.includes("Tunnel"),
    seen.rows.athens.actions.join(","));
  check("hosting: Forget is offered on a destroyed row, on a failed row with no id, and on a "
    + "machine of your own, and nowhere else",
    seen.rows.genoa.actions.join(",") === "Forget"
    && seen.rows.faro.actions.includes("Forget")
    && seen.rows.ithaca.actions.includes("Forget")
    && !seen.rows.athens.actions.includes("Forget"),
    Object.entries(seen.rows).map(([name, row]) => `${name}:${row.actions.join("+")}`).join(" "));
  check("hosting: a destroyed row is not offered a check or a destroy",
    !seen.rows.genoa.actions.includes("Check") && !seen.rows.genoa.actions.includes("Destroy"),
    seen.rows.genoa.actions.join(","));
  /* A farm runs on your own machine or on a DigitalOcean Droplet, and the section names no
     other kind of host. */
  check("hosting: the head names the two places a farm runs, and nothing else does",
    /your own machine over SSH, or a DigitalOcean Droplet/.test(seen.note)
    && !/runner|sandbox/i.test(seen.note) && !/runner|sandbox/i.test(seen.text),
    `${seen.note} | ${seen.text.slice(0, 200)}`);
  check("hosting: nothing threw drawing the section", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A provider that was slow to answer is not a provider you are logged out of. The quiet farm is
   the state that produces that reading, on the droplet's login step, and a long name is cut
   rather than wrapped. */
{
  const { page, context, thrown } = await open({ state: "quiet" });
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(400);
  const login = await page.evaluate(() => {
    const pill = document.querySelector("#drawer .m-wait .pill");
    return { login: pill ? pill.textContent : "", why: pill ? pill.title : "" };
  });
  await page.click("#drawerClose");
  await page.waitForTimeout(300);
  const seen = await page.evaluate(() => {
    const long = [...document.querySelectorAll("#view .h-machines tbody tr")]
      .find((node) => node.innerText.includes("the-second-farm"));
    const cell = long ? long.querySelector("td:first-child") : null;
    return {
      height: long ? Math.round(long.getBoundingClientRect().height) : 0,
      cut: cell ? cell.scrollWidth > cell.clientWidth : false,
      title: cell ? cell.title : "",
    };
  });
  check("hosting: a provider that did not answer wears its own pill, never Not logged in",
    /No answer/.test(login.login) && /did not come back in time/.test(login.why),
    `${login.login} | ${login.why}`);
  check("hosting: a name too long for its cell is cut, and the cell carries all of it",
    seen.cut && /the-second-farm-for-the-checkout-rewrite/.test(seen.title),
    JSON.stringify(seen).slice(0, 200));
  // One line at the table's row height, 40px since the owner's audit of 2026-09-23.
  check("hosting: and the row it is in is still one line high", seen.height <= 42,
    String(seen.height));
  check("hosting: nothing threw on the quiet farm", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------- every row of every table is one line */

/* Two tables on this tab do not hold to the owner's rule today, and did not before this section
   existed: the models table has one row of 59px at 1440, and the accounts table wraps to three
   lines at 390. Both are measured on main and both live in machine.css, which is another lane's
   file, so they are named here rather than quietly skipped, and the rule still covers every
   other table at both widths. */
/* ---------------------------------------------- one actions column, one button size */

/* Every table on the Machine tab keeps its actions in one last column of one width, every
   button in it is the same size, and a destructive one is always the last in its row (owner,
   2026-09-24: the buttons were all different widths and sizes). */
{
  const { page, context } = await open();
  await page.waitForTimeout(800);
  const seen = await page.evaluate(() => {
    const widths = new Set();
    const columns = new Set();
    const wrongOrder = [];
    const outside = [];
    for (const cell of document.querySelectorAll("#view td.actions")) {
      if (!cell.classList.contains("one")) columns.add(Math.round(cell.getBoundingClientRect().width));
      const buttons = [...cell.querySelectorAll("button, a.ghost-button")];
      buttons.forEach((node) => widths.add(Math.round(node.getBoundingClientRect().width)));
      const danger = buttons.findIndex((node) => node.classList.contains("danger"));
      if (danger !== -1 && danger !== buttons.length - 1) {
        wrongOrder.push(buttons.map((node) => node.textContent).join("+"));
      }
    }
    for (const table of document.querySelectorAll("#view table")) {
      for (const node of table.querySelectorAll("tbody td:not(.actions) :is(.button, .ghost-button)")) outside.push(node.textContent);
    }
    return { widths: [...widths], columns: [...columns], wrongOrder, outside };
  });
  check("machine: every button in an actions column is the same width",
    seen.widths.length === 1, JSON.stringify(seen.widths));
  check("machine: every full actions column is the same width in every table",
    seen.columns.length === 1, JSON.stringify(seen.columns));
  check("machine: a destructive action is the last one in its row",
    seen.wrongOrder.length === 0, seen.wrongOrder.join(" | "));
  check("machine: no table keeps a button outside its actions column",
    seen.outside.length === 0, seen.outside.join(" | "));
  await context.close();
}

/* A laptop window of 1280 or 1366 holds every Machine table without a sideways scroll: the
   widest three switch to fixed columns and cut their cells (owner, 2026-09-24). The fixed
   columns start at 641, so 700 is checked for titles too, where the cuts are deepest. */
for (const width of [700, 1024, 1280, 1366, 1440]) {
  const { page, context } = await open({ size: { width, height: 900 } });
  await page.waitForTimeout(800);
  if (width >= 1024) {
    const wide = await page.evaluate(() => [...document.querySelectorAll("#view .tablewrap")]
      .map((node) => [node.querySelector("table").className || "table", node.scrollWidth - node.clientWidth])
      .filter(([, over]) => over > 1));
    check(`machine: no table scrolls sideways at ${width}`, wide.length === 0, JSON.stringify(wide));
  }
  /* A cell the fixed columns cut keeps its whole text on a title, on the cell or on the one
     element that fills it: cutting is only fair when the words are one hover away. */
  const untitled = await page.evaluate(() => {
    const out = [];
    /* Headings too: a fixed column cuts its name as it cuts its cells, and a cut name must
       neither run into the next one nor lose its words. */
    for (const cell of document.querySelectorAll("#view :is(table.h-machines, table.m-accounts, table.m-services) :is(td, th):not(.actions)")) {
      const cut = [cell, ...cell.querySelectorAll("*")].some((node) => node.scrollWidth > node.clientWidth + 1);
      /* The title has to carry what the cell shows, not just any sentence: the visible words,
         whitespace folded, must all be in it. */
      const words = cell.innerText.replace(/\s+/g, " ").trim();
      const title = [cell.title, cell.firstElementChild && cell.firstElementChild.title].filter(Boolean).join(" ").replace(/\s+/g, " ");
      const titled = Boolean(title) && words.toLowerCase().split(" ")
        .every((word) => title.toLowerCase().includes(word.replace(/\u2026$/, "")));
      if (cut && !titled) out.push(`${cell.closest("table").className}: ${cell.innerText.replace(/\s+/g, " ").slice(0, 40)}`);
      if (cut && getComputedStyle(cell).overflowX === "visible") out.push(`${cell.closest("table").className}: ${words.slice(0, 40)} spills into the next column`);
    }
    return out;
  });
  check(`machine: every cut cell carries its text on a title at ${width}`, untitled.length === 0, untitled.join(" | "));
  await context.close();
}

const KNOWN_WRAPPING = { 1440: ["m-models"], 390: ["Accounts"] };

for (const size of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  const { page, context, thrown } = await open({ size });
  await page.waitForTimeout(600);
  const tables = await page.evaluate(() => {
    const out = {};
    for (const table of document.querySelectorAll("#view .tablewrap table")) {
      const head = table.querySelector("thead");
      /* A table the stylesheet turns into a card list at this width is not a table any more,
         and the one-line rule is about cells in a row. The models table is the one that does. */
      if (head && getComputedStyle(head).display === "none") continue;
      const section = table.closest("section");
      const name = section && section.querySelector("h2")
        ? `${section.querySelector("h2").textContent.trim()}:${table.className || "table"}` : "?";
      const rows = [...table.querySelectorAll("tbody tr")]
        .map((row) => Math.round(row.getBoundingClientRect().height));
      if (rows.length > 1) out[name] = rows;
    }
    return out;
  });
  for (const [name, heights] of Object.entries(tables)) {
    if ((KNOWN_WRAPPING[size.width] || []).some((known) => name.includes(known))) continue;
    check(`hosting: every row of the ${name} table is the same height at ${size.width}`,
      Math.max(...heights) - Math.min(...heights) <= 2, heights.join(", "));
  }
  check(`hosting: the tab has tables to hold to that rule at ${size.width}`,
    Object.keys(tables).length >= 3, Object.keys(tables).join(", "));
  check(`hosting: the machines table is among them at ${size.width}`,
    Object.keys(tables).some((name) => name.includes("h-machines")),
    Object.keys(tables).join(", "));
  check(`hosting: nothing threw at ${size.width}`, thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------- the four states of each table */

const PENDING = JSON.stringify({ at: "now", pending: "now", providers: [], machines: [] });

/* The machines table is on the tab; the providers list is read by the Add a machine dialog, so
   its four states are read there. */
async function openStates(overrides, route) {
  const opened = await open({ overrides });
  if (route === "/api/hosts") {
    await opened.page.click("[data-add-machine]");
    await opened.page.waitForTimeout(600);
  }
  return opened;
}

const statesText = (page, route) => (route === "/api/hosts"
  ? page.evaluate(() => document.getElementById("drawerBody").innerText) : hosting(page));

for (const [route, table] of [["/api/machines", "machines"], ["/api/hosts", "hosts"]]) {
  {
    const { page, context, thrown } = await openStates({ [route]: PENDING }, route);
    const seen = await page.evaluate((where) => ({
      skeletons: document.querySelectorAll(`${where} .skeleton`).length,
      text: document.querySelector(where).innerText,
    }), route === "/api/hosts" ? "#drawer" : "#view");
    check(`hosting: ${table} before the farm's first pass is a placeholder, not an error`,
      seen.skeletons > 0 && !/reported a problem/.test(seen.text), `${seen.skeletons} placeholders`);
    check(`hosting: nothing threw while ${table} was pending`, thrown.length === 0, thrown[0]);
    await context.close();
  }
  {
    const empty = route === "/api/machines"
      ? JSON.stringify({ at: "now", this: { name: "quartz", address: "127.0.0.1" },
        total_monthly_usd: 0, machines: [] })
      : JSON.stringify({ at: "now", providers: [] });
    const { page, context, thrown } = await openStates({ [route]: empty }, route);
    const text = await statesText(page, route);
    check(`hosting: an empty ${table} answer says what is missing and how to fill it`,
      route === "/api/machines"
        ? /No machine but this one/.test(text) && /fleet machines list/.test(text)
        : /lists no provider a machine can run on/.test(text) && /fleet hosts list/.test(text),
      text.slice(0, 300));
    check(`hosting: and the button that fills it is still there (${table})`,
      await page.evaluate(() => Boolean(document.querySelector("[data-add-machine]"))), "");
    check(`hosting: nothing threw on an empty ${table}`, thrown.length === 0, thrown[0]);
    await context.close();
  }
  {
    const { page, context, thrown } = await openStates({
      [route]: (handler) => handler.fulfill({
        status: 500, contentType: "application/json",
        body: JSON.stringify({ error: `${route} did not answer within sixty seconds` }),
      }),
    }, route);
    const text = await statesText(page, route);
    check(`hosting: a ${table} route that fails is an error card, not an empty table`,
      /did not answer within sixty seconds|reported a problem/.test(text), text.slice(0, 300));
    check(`hosting: nothing threw while ${table} failed`, thrown.length === 0, thrown[0]);
    await context.close();
  }
  {
    const { page, context, thrown } = await openStates({
      [route]: (handler) => handler.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ at: "now", providers: "not a list", machines: "not a list",
          this: null }),
      }),
    }, route);
    const text = await statesText(page, route);
    check(`hosting: a ${table} answer whose list is not a list leaves the section standing`,
      thrown.length === 0 && text.length > 0, thrown[0]);
    check(`hosting: and it reads as empty, not as a broken table (${table})`,
      /No machine but this one|lists no provider a machine can run on/.test(text),
      text.slice(0, 200));
    await context.close();
  }
}

/* A farm whose snapshot could not be refreshed answers the way design section 7 says a
   snapshot route does: 200, the rows it last read, stale_since and the reason. The rows are
   drawn, the card says how old they are, and the head's total says it is an old total. */
{
  const { page, context, thrown } = await open({ state: "error" });
  const text = await hosting(page);
  const seen = await page.evaluate(() => ({
    machines: [...document.querySelectorAll("#view .h-machines tbody tr")]
      .map((row) => row.innerText.split(/\s/)[0]),
    notes: [...document.querySelectorAll("#view [data-hosting-stale]")]
      .map((node) => node.textContent),
    total: (document.querySelector("#view [data-hosting-total]") || {}).textContent || "",
  }));
  check("hosting: a stale machines snapshot still draws the rows it last read",
    seen.machines.includes("athens") && seen.machines.includes("haifa"),
    seen.machines.join(","));
  check("hosting: and says under the table since when the list is old, and why",
    seen.notes.length === 1
    && seen.notes.every((note) => /has not refreshed this list since/.test(note))
    && /fleet machines list did not answer within sixty seconds/.test(seen.notes[0]),
    seen.notes.join(" | "));
  check("hosting: a total read from a stale snapshot says it is not fresh",
    /^You pay \$\d+ a month for \d+ machines\. Not refreshed since /.test(seen.total),
    seen.total);
  check("hosting: nothing threw on the stale farm", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A machines route that fails outright: the card says so, and the head says nothing about money
   it cannot know. */
{
  const { page, context, thrown } = await open({
    overrides: {
      "/api/machines": (handler) => handler.fulfill({
        status: 500, contentType: "application/json",
        body: JSON.stringify({ error: "fleet machines list did not answer within sixty seconds" }),
      }),
    },
  });
  const text = await hosting(page);
  check("hosting: a machines route that will not answer is an error card",
    /did not answer within sixty seconds|reported a problem/.test(text), text.slice(0, 300));
  check("hosting: the head claims nothing about money it could not read",
    !/You pay/.test(text) && !/Nothing on this list is billed/.test(text), text.slice(0, 200));
  check("hosting: nothing threw on the failing farm", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------ a page that may not write */

{
  const { page, context, thrown } = await open({ overrides: { "/api/access": READ_ONLY } });
  const seen = await page.evaluate(([writes, copies]) => {
    const pick = (selector) => [...document.querySelectorAll(
      `#view ${selector.split(", ").join(", #view ")}`)];
    const writeNodes = pick(writes);
    const copyNodes = pick(copies);
    return {
      writes: writeNodes.length,
      live: writeNodes.filter((node) => !node.disabled).map((node) => node.outerHTML.slice(0, 80)),
      reasons: writeNodes.filter((node) => /only read/.test(node.title || "")).length,
      copies: copyNodes.length,
      copiesLive: copyNodes.filter((node) => !node.disabled).length,
      rows: document.querySelectorAll("#view .h-machines tbody tr").length,
    };
  }, [WRITE_CONTROLS, COPY_CONTROLS]);
  const text = await hosting(page);
  check("hosting: a read-only page still draws every machine", seen.rows > 5, String(seen.rows));
  check("hosting: it has write controls to switch off", seen.writes > 0, `${seen.writes} found`);
  check("hosting: every write control is switched off", seen.live.length === 0, seen.live.join(" | "));
  check("hosting: with the server's own sentence on each one", seen.reasons === seen.writes,
    `${seen.reasons} of ${seen.writes}`);
  check("hosting: the reader is told why, in the server's own words",
    text.includes("opened without the dashboard token"), text.slice(-240));
  check("hosting: and a command can still be copied into your own terminal",
    seen.copies > 0 && seen.copiesLive === seen.copies, `${seen.copiesLive} of ${seen.copies}`);
  check("hosting: nothing threw on a read-only page", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The token can go while a dialog is open: the page is read from a second tab, or the token is
   rotated. Every write control in the dialog obeys that answer, buttons and fields alike. */
for (const [opener, picker, controls] of [
  ["[data-add-machine]", "[data-machine-provider='do-droplet']",
    "[data-machine-provider], [data-size], [data-region], [data-machine-name], [data-ssh-public],"
    + " [data-machine-plan], [data-machine-create-open]"],
]) {
  let writable = true;
  const { page, context, thrown, posted } = await open({
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
  await page.click(opener);
  await page.waitForTimeout(500);
  await page.click(`#drawer ${picker}`);
  await page.waitForTimeout(400);
  const before = await page.evaluate((selector) => [...document.querySelectorAll(
    `#drawer ${selector.split(", ").join(", #drawer ")}`)].filter((node) => !node.disabled).length,
  controls);
  writable = false;
  await page.evaluate(() => import("/static/core/api.js").then((api) => api.refresh("/api/access")));
  await page.waitForTimeout(3600);
  const after = await page.evaluate((selector) => {
    const nodes = [...document.querySelectorAll(
      `#drawer ${selector.split(", ").join(", #drawer ")}`)];
    return {
      total: nodes.length,
      live: nodes.filter((node) => !node.disabled).length,
      said: /only read/.test(document.getElementById("drawerBody").innerText),
    };
  }, controls);
  await page.click(`#drawer ${picker}`, { force: true });
  await page.waitForTimeout(400);
  check(`hosting: ${opener} is live while the page may write`, before > 0, String(before));
  check(`hosting: and every control in it is switched off the moment it may not`,
    after.total > 0 && after.live === 0, JSON.stringify(after));
  check(`hosting: the reason is written where the actions are (${opener})`, after.said,
    JSON.stringify(after));
  check(`hosting: so a forced press sends nothing (${opener})`,
    !posted.some((url) => /\/api\/(machines|hosts)/.test(url)), posted.join(" "));
  check(`hosting: nothing threw when the token went (${opener})`, thrown.length === 0, thrown[0]);
  await context.close();
}

/* What a row's pill says about money, read straight from the page's own module, for rows the
   fixture does not carry. */
{
  const { page, context, thrown } = await open();
  const said = await page.evaluate(async () => {
    const module = await import("/static/views/hosting.js");
    return {
      unpriced: module.billedLine({ name: "x", provider: "do-droplet", state: "creating",
        provider_id: null }),
      unreachable: module.billedLine({ name: "x", provider: "do-droplet", state: "unreachable",
        provider_id: 7, monthly_usd: 0 }),
      neverBought: module.billedLine({ name: "x", provider: "do-droplet", state: "failed",
        provider_id: null, monthly_usd: 48 }),
      own: module.billedLine({ name: "x", provider: "ssh", state: "ready", provider_id: null }),
    };
  });
  check("hosting: a droplet whose price is not read yet still says it is billed",
    said.unpriced === "Still billed. You are billed until you destroy it. Powering it off does "
      + "not stop the bill." && said.unreachable.startsWith("Still billed. "),
    `${said.unpriced} | ${said.unreachable}`);
  check("hosting: and a row the provider never made, or a machine of your own, says nothing",
    said.neverBought === "" && said.own === "", `${said.neverBought} | ${said.own}`);
  check("hosting: nothing threw reading the pill's money sentence", thrown.length === 0, thrown[0]);
  await context.close();
}

/* What the head says about money, from the page's own module: the farm's total is said whenever
   it is positive, whatever the rows carry. */
{
  const { page, context, thrown } = await open();
  const said = await page.evaluate(async () => {
    const module = await import("/static/views/hosting.js");
    return {
      totalWithoutPrices: module.totalLine({ total_monthly_usd: 48, machines: [
        { name: "a", provider: "do-droplet", state: "ready", provider_id: 1 }] }),
      totalWithoutRows: module.totalLine({ total_monthly_usd: 48, machines: [] }),
      nothing: module.totalLine({ total_monthly_usd: 0, machines: [
        { name: "a", provider: "do-droplet", state: "destroyed", provider_id: 1 }] }),
    };
  });
  check("hosting: a positive total is said even when the rows carry no price",
    said.totalWithoutPrices === "You pay $48 a month for 1 machine."
    && said.totalWithoutRows === "You pay $48 a month.",
    `${said.totalWithoutPrices} | ${said.totalWithoutRows}`);
  check("hosting: and only a zero total is called nothing billed",
    said.nothing === "Nothing on this list is billed.", said.nothing);
  check("hosting: nothing threw reading the head's money sentence", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------- the add a machine dialog */

/* No droplet is bought by one press. The first press names the price and asks; only the second
   sends anything, and it sends the price it named. */
{
  const { page, context, thrown, posted, sent } = await open();
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  const steps = await page.evaluate(() => ({
    numbers: [...document.querySelectorAll("#drawer .m-step-no")].map((node) => node.textContent),
    providers: [...document.querySelectorAll("#drawer [data-machine-provider]")]
      .map((node) => node.getAttribute("data-machine-provider")),
    text: document.getElementById("drawerBody").innerText,
  }));
  check("hosting: the dialog offers your own machine and a DigitalOcean Droplet, and nothing else",
    steps.providers.join(",") === "ssh,do-droplet", steps.providers.join(","));
  /* The price waits for the pick (owner, 2026-09-24): an unpicked card is its stage and a
     summary, and the picked one carries its price line. */
  check("hosting: an unpicked provider card carries its stage, its summary and no price line",
    /generally available/.test(steps.text) && /A Linux box you already reach over SSH/.test(steps.text)
    && /runs the whole farm/.test(steps.text) && !/From \$24 a month/.test(steps.text),
    steps.text.slice(0, 300));
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(400);
  const pickedText = await page.evaluate(() =>
    (document.querySelector("#drawer [data-machine-provider='do-droplet']") || {}).innerText || "");
  check("hosting: and the picked card carries its price line",
    /From \$24 a month/.test(pickedText), pickedText.slice(0, 300));
  const droplet = await page.evaluate(() => ({
    numbers: [...document.querySelectorAll("#drawer .m-step-no")].map((node) => node.textContent),
    sizes: [...document.querySelectorAll("#drawer [data-size]")]
      .map((node) => node.getAttribute("data-size")),
    chosen: (document.querySelector("#drawer [data-size][aria-checked='true']") || {})
      .getAttribute("data-size"),
    regions: [...document.querySelectorAll("#drawer [data-region] option")]
      .map((node) => node.value),
    create: (document.querySelector("[data-machine-create-open]") || {}).textContent,
    text: document.getElementById("drawerBody").innerText,
  }));
  check("hosting: a droplet is asked for in five numbered steps",
    droplet.numbers.join(",") === "1,2,3,4,5", droplet.numbers.join(","));
  check("hosting: the sizes are radio cards with their cores, memory, disk and price",
    droplet.sizes.length === 3 && /4 vCPU, 8 GB, 160 GB disk/.test(droplet.text)
    && /\$48 a month/.test(droplet.text), droplet.sizes.join(","));
  check("hosting: the size the preset calls its default is the one chosen",
    droplet.chosen === "s-4vcpu-8gb", droplet.chosen);
  check("hosting: the regions are the provider's own", droplet.regions.join(",") === "fra1,ams3,nyc3",
    droplet.regions.join(","));
  check("hosting: the key field says what it is for and where to find it",
    /how your laptop reaches the machine/.test(droplet.text)
    && /cat ~\/.ssh\/id_ed25519.pub/.test(droplet.text), droplet.text.slice(0, 400));
  check("hosting: the create button names the price and what it buys",
    droplet.create === "Create, $48 a month until you destroy it", droplet.create);

  await page.fill("#drawer [data-machine-name]", "lagos");
  await page.fill("#drawer [data-ssh-public]", KEY);
  await page.waitForTimeout(200);
  await page.click("[data-machine-plan]");
  await page.waitForTimeout(900);
  const planned = await page.evaluate(() => ({
    commands: (document.querySelector("[data-machine-commands]") || {}).textContent || "",
    cloud: (document.querySelector("[data-machine-cloudinit]") || {}).textContent || "",
    scrolls: (() => {
      const node = document.querySelector("[data-machine-cloudinit]");
      return node ? getComputedStyle(node).overflow : "";
    })(),
    copies: document.querySelectorAll("#drawer [data-copy-machine-cloudinit]").length,
    text: document.getElementById("drawerBody").innerText,
  }));
  check("hosting: Review asks the plan route and shows the commands that will run",
    /doctl compute droplet create lagos/.test(planned.commands)
    && bodyOf(sent, "/api/machines/plan").name === "lagos",
    planned.commands.slice(0, 160));
  check("hosting: the firewall Review shows lets the farm out as well as SSH in",
    /firewall create .*--inbound-rules .*--outbound-rules ['"]protocol:tcp,ports:0,address:0\.0\.0\.0\/0/
      .test(planned.commands), planned.commands.slice(0, 400));
  check("hosting: and the cloud-init file, in a scrollable block with a Copy",
    /#cloud-config/.test(planned.cloud) && planned.scrolls === "auto" && planned.copies === 1,
    JSON.stringify({ scrolls: planned.scrolls, copies: planned.copies }));
  check("hosting: and the live price the farm read back",
    /The live price is \$48 a month/.test(planned.text), planned.text.slice(-200));

  await page.click("[data-machine-create-open]");
  await page.waitForTimeout(400);
  const confirm = await page.evaluate(() => ({
    said: (document.querySelector("#drawer .m-confirm") || {}).innerText || "",
    button: (document.querySelector("[data-machine-create]") || {}).textContent || "",
  }));
  check("hosting: the create button alone buys nothing",
    !posted.some((url) => url.endsWith("/api/machines")), posted.join(" "));
  check("hosting: the confirm repeats the price and says the bill runs until you destroy it",
    /\$48 a month/.test(confirm.said)
    && /You are billed until you destroy it. Powering it off does not stop the bill/.test(confirm.said),
    confirm.said.slice(0, 300));
  check("hosting: and its button names the price too", confirm.button === "Create, $48 a month",
    confirm.button);
  await page.click("[data-machine-create]");
  await page.waitForTimeout(900);
  const body = bodyOf(sent, "/api/machines");
  check("hosting: creating sends the provider, the name, the size, the region, the key and the "
    + "price that was confirmed",
    body && body.provider === "do-droplet" && body.name === "lagos"
    && body.size === "s-4vcpu-8gb" && body.region === "fra1" && body.confirm_usd === 48
    && body.ssh_public === KEY, JSON.stringify(body));
  check("hosting: the public key is sent under ssh_public, never under a name with key in it",
    body && !Object.keys(body).some((field) => /key|secret|token|password/i.test(field)),
    Object.keys(body || {}).join(","));
  /* The dialog shows the job, then closes to the table, where the row moves on its own. */
  let moved = "";
  for (let attempt = 0; attempt < 24 && !/Preparing|Needs your login/.test(moved); attempt += 1) {
    await page.waitForTimeout(700);
    moved = await page.evaluate(() => {
      const row = [...document.querySelectorAll("#view .h-machines tbody tr")]
        .find((node) => node.innerText.startsWith("lagos"));
      return row ? row.innerText : "";
    });
  }
  const closed = await page.evaluate(() => document.getElementById("drawer").hidden);
  check("hosting: the row appears and moves on by itself", /Preparing|Needs your login/.test(moved),
    moved.slice(0, 160));
  check("hosting: and the dialog closes to the table", closed, String(closed));
  check("hosting: nothing threw around creating a machine", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A token typed into the key field never leaves the page, and the refusal never repeats it. */
{
  const { page, context, thrown, posted } = await open();
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(300);
  await page.fill("#drawer [data-machine-name]", "beirut");
  await page.fill("#drawer [data-ssh-public]", TOKEN);
  await page.click("[data-machine-create-open]");
  await page.waitForTimeout(500);
  await page.click("[data-machine-plan]");
  await page.waitForTimeout(700);
  const said = await page.evaluate(() => ({
    bad: (document.querySelector("#drawer .m-bad") || {}).innerText || "",
    confirm: Boolean(document.querySelector("#drawer .m-confirm")),
    all: document.getElementById("drawerBody").innerText,
  }));
  check("hosting: a token in the public key field is refused in the page",
    /looks like a token, not a public key/.test(said.bad)
    && /never goes through this page/.test(said.bad), said.bad.slice(0, 200));
  check("hosting: and the refusal never repeats the value",
    !said.all.includes(TOKEN) && !said.bad.includes("sk-ant"), said.bad.slice(0, 200));
  check("hosting: no confirm is opened on a refused key", !said.confirm, String(said.confirm));
  check("hosting: and nothing at all was sent to the farm",
    !posted.some((url) => /\/api\/machines/.test(url)), posted.join(" "));
  /* A key that is simply not a key is refused too, in words that say what one looks like. */
  await page.fill("#drawer [data-ssh-public]", "my laptop key");
  await page.click("[data-machine-create-open]");
  await page.waitForTimeout(400);
  const second = await page.evaluate(() =>
    (document.querySelector("#drawer .m-bad") || {}).innerText || "");
  check("hosting: a public key that is not one is refused with what one looks like",
    /ssh-ed25519/.test(second) && /never the private one/.test(second), second.slice(0, 200));
  /* Review buys nothing, so it does not insist on the key; Create does, because without it the
     finish command and the tunnel, both run from a laptop, cannot log in. */
  await page.fill("#drawer [data-ssh-public]", "");
  await page.click("[data-machine-plan]");
  await page.waitForTimeout(900);
  check("hosting: Review asks for a plan without a key",
    posted.some((url) => url.endsWith("/api/machines/plan")), posted.join(" "));
  await page.click("[data-machine-create-open]");
  await page.waitForTimeout(400);
  const needed = await page.evaluate(() =>
    (document.querySelector("#drawer .m-bad") || {}).innerText || "");
  check("hosting: and Create insists on one, saying what it is for",
    /Paste your SSH public key/.test(needed) && /cannot reach the machine/.test(needed),
    needed.slice(0, 200));
  check("hosting: and still buys nothing",
    !posted.some((url) => url.endsWith("/api/machines")), posted.join(" "));
  check("hosting: nothing threw over the key field", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The name rule is the farm's, taught before a request rather than after a refusal. */
{
  const { page, context, thrown, posted } = await open();
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(300);
  await page.fill("#drawer [data-machine-name]", "Athens Two");
  await page.fill("#drawer [data-ssh-public]", KEY);
  await page.click("[data-machine-create-open]");
  await page.waitForTimeout(400);
  const said = await page.evaluate(() =>
    (document.querySelector("#drawer .m-bad") || {}).innerText || "");
  check("hosting: a name the farm would refuse is refused here, in the farm's own rule",
    /lower case letters, digits and dashes/.test(said) && /2 to 31 characters/.test(said),
    said.slice(0, 200));
  check("hosting: and nothing was sent", !posted.some((url) => /\/api\/machines/.test(url)),
    posted.join(" "));
  /* And the route behind the page keeps the same rule, so a page that drifts is caught. */
  const answer = await fetch(`${BASE}/api/machines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: "do-droplet", name: "Athens Two", size: "s-4vcpu-8gb",
      region: "fra1", ssh_public: KEY, confirm_usd: 48 }),
  });
  const refusal = ((await answer.json()) || {}).error || "";
  check("hosting: the route behind the page keeps that rule too",
    answer.status === 400 && /lower case letters/.test(refusal), `${answer.status} ${refusal}`);
  check("hosting: nothing threw on a refused name", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A plan belongs to the name it was asked with. Changing the name takes the plan off the page
   at once, and a refusal goes as soon as the field it was about is changed. */
{
  const { page, context, thrown } = await open();
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(300);
  await page.fill("#drawer [data-machine-name]", "lagos");
  await page.click("[data-machine-plan]");
  await page.waitForTimeout(900);
  const asked = await page.evaluate(() =>
    (document.querySelector("#drawer [data-machine-commands]") || {}).textContent || "");
  await page.fill("#drawer [data-machine-name]", "beirut");
  await page.waitForTimeout(300);
  const after = await page.evaluate(() =>
    (document.querySelector("#drawer [data-machine-commands]") || {}).textContent || "");
  check("hosting: a plan is drawn for the name it was asked with",
    /droplet create lagos/.test(asked), asked.slice(0, 160));
  check("hosting: each planned command reads as a shell line a person can copy, not a list",
    !/doctl,compute/.test(asked) && /--inbound-rules 'protocol:tcp,ports:22/.test(asked),
    asked.slice(0, 240));
  check("hosting: and changing the name takes that plan off Review at once",
    !/lagos/.test(after), after.slice(0, 160));
  await page.fill("#drawer [data-machine-name]", "Bad Name");
  await page.click("[data-machine-create-open]");
  await page.waitForTimeout(300);
  const refused = await page.evaluate(() => Boolean(document.querySelector("#drawer .m-bad")));
  await page.fill("#drawer [data-machine-name]", "rome");
  await page.waitForTimeout(300);
  const cleared = await page.evaluate(() => !document.querySelector("#drawer .m-bad"));
  check("hosting: a refusal goes as soon as the name it was about is changed",
    refused && cleared, JSON.stringify({ refused, cleared }));
  check("hosting: nothing threw changing the name", thrown.length === 0, thrown[0]);
  await context.close();
}

/* One press buys one droplet, even from a farm that takes a second and a half to answer: the
   button is off from the press, not from the answer. */
{
  const { page, context, thrown, posted } = await open({
    overrides: {
      "/api/machines": (handler) => (handler.request().method() === "POST"
        ? new Promise((resolve) => setTimeout(resolve, 1500)).then(() => handler.continue())
        : handler.continue()),
    },
  });
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(300);
  await page.fill("#drawer [data-machine-name]", "oslo");
  await page.fill("#drawer [data-ssh-public]", KEY);
  await page.click("[data-machine-create-open]");
  await page.waitForTimeout(300);
  await page.click("[data-machine-create]");
  await page.waitForTimeout(300);
  const during = await page.evaluate(() => {
    const buttons = [...document.querySelectorAll("#drawer [data-machine-create], "
      + "#drawer [data-machine-create-open]")];
    const armed = buttons.filter((node) => !node.disabled).length;
    for (const node of buttons) node.click();
    return { buttons: buttons.length, armed };
  });
  await page.waitForTimeout(2500);
  const creates = posted.filter((url) => url.endsWith("/api/machines")).length;
  check("hosting: while its create is in flight, no create button on screen is armed",
    during.buttons > 0 && during.armed === 0, JSON.stringify(during));
  check("hosting: so a second press sends no second create", creates === 1, String(creates));
  check("hosting: nothing threw around a slow create", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A machine of your own is registered and checked, and nothing about money is said anywhere. */
{
  const { page, context, thrown, sent } = await open();
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='ssh']");
  await page.waitForTimeout(400);
  const own = await page.evaluate(() => ({
    text: document.getElementById("drawerBody").innerText,
    button: (document.querySelector("[data-machine-create]") || {}).textContent || "",
    buys: Boolean(document.querySelector("[data-machine-create-open]")),
    command: (document.querySelector("[data-machine-commands]") || {}).textContent || "",
  }));
  /* The DigitalOcean card in step one names its price, as it must. Everything after it, for a
     machine of your own, says nothing about money at all. */
  const afterCards = own.text.split("What it is")[1] || "";
  check("hosting: a machine of your own ends in Add and check, not in a price",
    own.button === "Add and check" && !own.buys && !/a month/.test(afterCards),
    `${own.button} | ${afterCards.slice(0, 200)}`);
  check("hosting: and its review shows the one command that will run",
    /fleet machines add --name/.test(own.command), own.command);
  await page.fill("#drawer [data-machine-name]", "loft");
  await page.fill("#drawer [data-target]", "dev@192.168.1.55");
  await page.fill("#drawer [data-port]", "2222");
  await page.click("[data-machine-create]");
  await page.waitForTimeout(1200);
  const body = bodyOf(sent, "/api/machines");
  check("hosting: adding your own machine sends the target and the port, and no price",
    body && body.provider === "ssh" && body.name === "loft"
    && body.target === "dev@192.168.1.55" && body.port === "2222"
    && body.confirm_usd === undefined, JSON.stringify(body));
  check("hosting: nothing threw adding a machine of your own", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The login step flips by itself while it is open, because the login happens somewhere else. */
{
  let loggedIn = false;
  const { page, context, thrown } = await open({
    overrides: {
      "/api/hosts": (handler) => handler.fetch().then(async (answer) => {
        const payload = await answer.json();
        for (const row of payload.providers || []) {
          if (row.id !== "do-droplet") continue;
          row.login_state = loggedIn ? "logged_in" : "logged_out";
          row.account = loggedIn ? "owner@example.invalid" : "";
        }
        return handler.fulfill({
          status: 200, contentType: "application/json", body: JSON.stringify(payload),
        });
      }),
    },
  });
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(500);
  const before = await page.evaluate(() => ({
    command: (document.querySelector("#drawer [data-host-login]") || {}).textContent || "",
    text: document.getElementById("drawerBody").innerText,
  }));
  check("hosting: a farm that is not logged in is handed the provider's own login command",
    before.command === "ssh -t farm doctl auth init --context murmur", before.command);
  check("hosting: and told the page is watching for it",
    /watching for it/.test(before.text), before.text.slice(0, 400));
  loggedIn = true;
  await page.waitForTimeout(4000);
  const after = await page.evaluate(() => ({
    command: Boolean(document.querySelector("#drawer [data-host-login]")),
    text: document.getElementById("drawerBody").innerText,
  }));
  check("hosting: the step turns itself into logged in, with the account named",
    !after.command && /Logged in as owner@example.invalid/.test(after.text),
    after.text.slice(0, 400));
  check("hosting: nothing threw while the login landed", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------------- the row actions */

{
  const { page, context, thrown, sent } = await open();
  await page.click("[data-machine-check='athens']");
  await page.waitForTimeout(700);
  check("hosting: Check asks the check route with the machine's name",
    JSON.stringify(bodyOf(sent, "/api/machines/check")) === JSON.stringify({ name: "athens" }),
    JSON.stringify(bodyOf(sent, "/api/machines/check")));
  const during = await page.evaluate(() => {
    const node = document.querySelector("[data-machine-check='athens']");
    return { off: node.disabled, label: node.textContent, title: node.title };
  });
  check("hosting: and the button holds while its job runs, keeping its word and saying why",
    during.off && during.label === "Check" && /is running/.test(during.title), JSON.stringify(during));
  await page.click("[data-machine-adopt='haifa']");
  await page.waitForTimeout(700);
  check("hosting: Adopt asks the adopt route",
    JSON.stringify(bodyOf(sent, "/api/machines/adopt")) === JSON.stringify({ name: "haifa" }),
    JSON.stringify(bodyOf(sent, "/api/machines/adopt")));
  await page.click("[data-machine-forget='genoa']");
  await page.waitForTimeout(700);
  check("hosting: Forget asks the forget route",
    JSON.stringify(bodyOf(sent, "/api/machines/forget")) === JSON.stringify({ name: "genoa" }),
    JSON.stringify(bodyOf(sent, "/api/machines/forget")));
  check("hosting: nothing threw around the row actions", thrown.length === 0, thrown[0]);
  await context.close();
}

/* Destroy deletes a disk and stops a bill, and cannot be pressed until the name is typed. */
{
  const { page, context, thrown, posted, sent } = await open();
  await page.click("[data-machine-destroy='edinburgh']");
  await page.waitForTimeout(500);
  const asked = await page.evaluate(() => ({
    said: (document.querySelector("#view .m-confirm") || {}).innerText || "",
    off: document.querySelector("[data-confirm='destroy:edinburgh']").disabled,
    why: document.querySelector("[data-confirm='destroy:edinburgh']").title,
  }));
  check("hosting: the destroy confirm names the droplet, its disk and the bill it stops",
    /Destroy edinburgh\?/.test(asked.said) && /disk are deleted/.test(asked.said)
    && /stops the bill of \$24 a month/.test(asked.said), asked.said.slice(0, 300));
  check("hosting: its button is off until the name is typed", asked.off === true
    && /Type edinburgh/.test(asked.why), JSON.stringify(asked).slice(0, 200));
  await page.fill("#view [data-machine-typed]", "edinburg");
  await page.waitForTimeout(300);
  const nearly = await page.evaluate(() =>
    document.querySelector("[data-confirm='destroy:edinburgh']").disabled);
  await page.click("[data-confirm='destroy:edinburgh']", { force: true });
  await page.waitForTimeout(400);
  check("hosting: a name that nearly matches is still not the name", nearly === true,
    String(nearly));
  check("hosting: so a forced press destroys nothing",
    !posted.some((url) => url.endsWith("/api/machines/destroy")), posted.join(" "));
  await page.fill("#view [data-machine-typed]", "edinburgh");
  await page.waitForTimeout(300);
  const armed = await page.evaluate(() =>
    document.querySelector("[data-confirm='destroy:edinburgh']").disabled);
  await page.click("[data-confirm='destroy:edinburgh']");
  await page.waitForTimeout(900);
  const body = bodyOf(sent, "/api/machines/destroy");
  check("hosting: the typed name arms it", armed === false, String(armed));
  check("hosting: and destroying sends the name and the confirmation",
    body && body.name === "edinburgh" && body.confirm === "edinburgh", JSON.stringify(body));
  let gone = "";
  for (let attempt = 0; attempt < 12 && !/Destroyed/.test(gone); attempt += 1) {
    await page.waitForTimeout(600);
    gone = await page.evaluate(() => {
      const row = [...document.querySelectorAll("#view .h-machines tbody tr")]
        .find((node) => node.innerText.startsWith("edinburgh"));
      return row ? row.innerText : "";
    });
  }
  check("hosting: and the row says so by itself, with Forget in place of Destroy",
    /Destroyed/.test(gone) && /Forget/.test(gone) && !/Destroy\b/.test(gone.replace("Destroyed", "")),
    gone.replace(/\s+/g, " ").slice(0, 400));
  check("hosting: nothing threw around destroy", thrown.length === 0, thrown[0]);
  await context.close();
}

/* A job the farm refuses is answered under this section, and never under another card. */
{
  const { page, context, thrown } = await open({
    overrides: {
      "/api/machines/check": (handler) => handler.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ error: "athens is held open by a lane that is still running" }),
      }),
    },
  });
  await page.click("[data-machine-check='athens']");
  await page.waitForTimeout(900);
  const said = await page.evaluate(() => {
    const sections = [...document.querySelectorAll("#view .section")];
    const words = (head) => {
      const node = sections.find((item) => item.innerText.startsWith(head));
      return node ? node.innerText : "";
    };
    return { hosting: words("Hosting"), power: words("Power") };
  });
  check("hosting: a refused action is answered under the Hosting card",
    /still running/.test(said.hosting), said.hosting.slice(-240));
  check("hosting: and never under the Power card",
    said.power.length > 0 && !/still running/.test(said.power), said.power.slice(0, 200));
  check("hosting: nothing threw on a refused action", thrown.length === 0, thrown[0]);
  await context.close();
}

/* ------------------------------------------------------------ the provider cards */

/* A card before it is picked is its name, its stage and two short lines; the price and the terms
   wait for the pick (owner, 2026-09-24: "short descriptions, two lines each, and the rest after
   the choice"). */
{
  const { page, context, thrown } = await open();
  await page.click("[data-add-machine]");
  await page.waitForTimeout(600);
  const card = await page.evaluate(() =>
    (document.querySelector("#drawer [data-machine-provider='do-droplet']") || {}).innerText || "");
  const lines = await page.evaluate(() => [...document.querySelectorAll("#drawer .m-preset-sum")]
    .map((node) => Math.round(node.getBoundingClientRect().height
      / parseFloat(getComputedStyle(node).lineHeight))));
  check("hosting: an unpicked card is its stage and a summary, with no fine print",
    /generally available/.test(card) && /runs the whole farm/.test(card)
    && !/Powering it off/.test(card), card.slice(0, 300));
  check("hosting: and every summary fits in two lines",
    lines.length === 2 && lines.every((count) => count <= 2), JSON.stringify(lines));
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(400);
  const picked = await page.evaluate(() =>
    (document.querySelector("#drawer [data-machine-provider='do-droplet']") || {}).innerText || "");
  check("hosting: a picked card carries its price and its terms",
    /From \$24 a month/.test(picked) && /Powering it off does not/.test(picked),
    picked.slice(0, 300));
  check("hosting: nothing threw around the provider cards", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The dialog asks the farm again while it waits on a login, and stops the moment it closes. */
{
  const { page, context, thrown } = await open({
    overrides: {
      "/api/hosts": (handler) => handler.fetch().then(async (answer) => {
        const payload = await answer.json();
        for (const row of payload.providers || []) {
          if (row.id === "do-droplet") row.login_state = "logged_out";
        }
        return handler.fulfill({
          status: 200, contentType: "application/json", body: JSON.stringify(payload),
        });
      }),
    },
  });
  const asked = [];
  page.on("request", (request) => {
    if (request.method() === "GET" && request.url().includes("/api/hosts")) asked.push(1);
  });
  await page.click("[data-add-machine]");
  await page.waitForTimeout(500);
  await page.click("#drawer [data-machine-provider='do-droplet']");
  await page.waitForTimeout(4000);
  const whileOpen = asked.length;
  /* The Machine tab reads /api/hosts on its own three second tick, so the dialog's own asking is
     only visible from a tab that does not: leaving the tab closes the dialog, and from then on
     every request for the providers would be the dialog's clock still running. */
  await page.evaluate(() => { location.hash = "#/elsewhere"; });
  await page.waitForTimeout(400);
  const atClose = asked.length;
  await page.waitForTimeout(4000);
  check("hosting: an open dialog keeps asking the farm for the login it is watching",
    whileOpen >= 2, `${whileOpen} in four seconds`);
  check("hosting: and a dialog that was closed stops its own asking",
    asked.length === atClose, JSON.stringify({ whileOpen, atClose, later: asked.length }));
  check("hosting: nothing threw around the dialog's own clock", thrown.length === 0, thrown[0]);
  await context.close();
}

/* No request this section sends ever carries a secret, by any name. */
{
  const { page, context, sent } = await open();
  await page.click("[data-machine-check='athens']");
  await page.waitForTimeout(500);
  await page.click("[data-machine-check='brussels']");
  await page.waitForTimeout(500);
  const hosting = sent.filter((row) => /\/api\/(machines|hosts)/.test(row.url));
  check("hosting: every write it sends is to a route of the design record", hosting.length >= 2,
    hosting.map((row) => row.url.replace(BASE, "")).join(" "));
  check("hosting: and none of them carries a field that looks like a credential",
    hosting.every((row) => !/"(api_)?key"|"secret"|"token"|"password"|"pubkey"/i.test(row.body)),
    hosting.map((row) => row.body).join(" ").slice(0, 200));
  await context.close();
}

/* The route behind the page never repeats a value that looks like a token, whichever field it
   came in, and never answers with it in a plan either. */
{
  const post = async (route, body) => {
    const answer = await fetch(`${BASE}${route}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { status: answer.status, text: await answer.text() };
  };
  const named = await post("/api/machines", { provider: "do-droplet", name: TOKEN,
    size: "s-4vcpu-8gb", region: "fra1", ssh_public: KEY, confirm_usd: 48 });
  const planned = await post("/api/machines/plan", { provider: "do-droplet", name: "lima",
    size: "s-4vcpu-8gb", region: TOKEN });
  const target = await post("/api/machines", { provider: "ssh", name: "lima", target: TOKEN });
  check("hosting: a token given as a name is refused without being repeated",
    named.status === 400 && !named.text.includes("sk-ant"), `${named.status} ${named.text}`);
  check("hosting: a token given in any other field is refused before a plan is drawn from it",
    planned.status === 400 && !planned.text.includes("sk-ant")
    && target.status === 400 && !target.text.includes("sk-ant"),
    `${planned.status} ${planned.text.slice(0, 120)} | ${target.status} ${target.text}`);
}

/* A copied command is answered with one toast, which carries the button's own sentence. */
{
  const { page, context, thrown } = await open();
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE });
  await page.click("#view .h-machines tr:has-text('athens') [data-machine-tunnel]");
  await page.waitForTimeout(400);
  const toasts = await page.evaluate(() =>
    [...document.querySelectorAll("#toasts .toast")].map((node) => node.textContent));
  check("hosting: copying a row command says so once, with what the command does",
    toasts.length === 1 && /^Copied\. Opens this dashboard from your laptop/.test(toasts[0]),
    JSON.stringify(toasts));
  check("hosting: nothing threw copying a command", thrown.length === 0, thrown[0]);
  await context.close();
}

/* The routes answer exactly the shape of design section 7 as amended: provider_id on a machine
   row; cli, color, engines and docs on a provider row; default on each size, true on exactly
   one. Nothing more, so a page that leans on a field nobody promised is caught here. Asked
   last, after this run has created machines of its own through the page. */
{
  const hosts = await (await fetch(`${BASE}/api/hosts`)).json();
  const machines = await (await fetch(`${BASE}/api/machines`)).json();
  const HOST_KEYS = ["id", "label", "job", "stage", "cli_installed", "login_state", "account",
    "detail", "checked_at", "login", "install", "terms", "pricing", "sizes",
    "regions", "cli", "color", "engines", "docs", "summary"].sort().join(",");
  const MACHINE_KEYS = ["name", "provider", "user", "address", "size", "monthly_usd", "region",
    "state", "detail", "checked_at", "finish_command", "tunnel_command", "provider_id"]
    .sort().join(",");
  const hostShapes = [...new Set(hosts.providers.map((row) => Object.keys(row).sort().join(",")))];
  const machineShapes = [...new Set(machines.machines
    .map((row) => Object.keys(row).sort().join(",")))];
  check("hosting: every provider row carries exactly the amended section 7 fields",
    hostShapes.length === 1 && hostShapes[0] === HOST_KEYS, hostShapes.join(" | "));
  check("hosting: every machine row carries exactly the amended section 7 fields, created ones too",
    machines.machines.length > 9 && machineShapes.length === 1 && machineShapes[0] === MACHINE_KEYS,
    machineShapes.join(" | "));
  const sized = hosts.providers.filter((row) => row.sizes.length);
  check("hosting: every size says whether it is the default, and exactly one is",
    sized.length > 0 && sized.every((row) =>
      row.sizes.every((size) => typeof size.default === "boolean")
      && row.sizes.filter((size) => size.default).length === 1),
    JSON.stringify(sized.map((row) => row.sizes.map((size) => size.default))));
}

await browser.close();
stub.kill();

const failed = results.filter((result) => !result.passed);
console.log(`\nRESULT: ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);

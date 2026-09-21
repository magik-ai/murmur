/* The front end's contract, checked without a browser: the shape of the page, the shape of
   every module, and the shape of every route the page reads. It starts the stub itself, so a
   green reading here is a reading against the same fixtures the browser check uses. */

import assert from "node:assert/strict";
import fs from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { tokens, parseColour, contrast } from "./test_palette.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 7951);
const BASE = `http://127.0.0.1:${PORT}`;

const EM_DASH = String.fromCharCode(8212);
const read = (relative) => fs.readFileSync(path.join(HERE, relative), "utf8");

let passed = 0;
function ok(name, body) {
  body();
  passed += 1;
  console.log(`PASS  ${name}`);
}
async function okAsync(name, body) {
  await body();
  passed += 1;
  console.log(`PASS  ${name}`);
}

/* ------------------------------------------------------------- the page */

const html = read("index.html");

ok("the page is a shell, not an application", () => {
  assert.ok(html.split("\n").length < 100, "index.html must stay under a hundred lines");
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1, "only the pre-paint theme script may be inline");
  assert.ok(scripts[0][1].includes("data-theme"), "the inline script sets the theme before paint");
  assert.ok(scripts[0][1].split("\n").length < 12, "the inline script stays a handful of lines");
  assert.match(html, /<script type="module" src="\/static\/app\.js">/);
  assert.match(html, /<link rel="stylesheet" href="\/static\/app\.css">/);
});

ok("the page carries the chrome the views expect", () => {
  for (const id of ["sidebar", "navlinks", "topbar", "productTitle", "viewTitle", "capacity",
    "projectFilter", "freshness", "themeSwitch", "paletteOpen", "palette", "paletteInput",
    "paletteList", "view", "drawer", "drawerTitle", "drawerBody", "drawerScrim", "toasts",
    "favicon", "sidebarTitle"]) {
    assert.ok(html.includes(`id="${id}"`), `index.html is missing #${id}`);
  }
  const shell = read("static/app.js");
  for (const choice of ["system", "light", "dark"]) {
    assert.ok(new RegExp(`\\["${choice}"`).test(shell), `the theme control cannot reach ${choice}`);
  }
  assert.ok(html.includes("murmur"), "the fallback product name is murmur");
});

/* ------------------------------------------------------------- the files */

const REQUIRED_FILES = [
  "static/app.css", "static/app.js",
  "static/core/api.js", "static/core/ui.js", "static/core/fmt.js", "static/core/identity.js",
  "static/views/overview.js", "static/views/agents.js", "static/views/mail.js",
  "static/views/queue.js", "static/views/projects.js", "static/views/accounts.js",
  "static/views/system.js",
];

ok("every file the design record names exists", () => {
  for (const relative of REQUIRED_FILES) {
    assert.ok(fs.existsSync(path.join(HERE, relative)), `missing ${relative}`);
  }
});

ok("nothing outside the api module talks to the network", () => {
  for (const relative of REQUIRED_FILES) {
    if (relative.endsWith("core/api.js") || relative.endsWith(".css")) continue;
    const source = read(relative);
    for (const forbidden of ["fetch(", "new WebSocket", "new EventSource", "XMLHttpRequest"]) {
      assert.ok(!source.includes(forbidden), `${relative} performs its own ${forbidden}`);
    }
  }
});

ok("no file carries an em dash", () => {
  for (const relative of ["index.html", "test_stub_server.py", "test_screens.mjs", ...REQUIRED_FILES]) {
    assert.ok(!read(relative).includes(EM_DASH), `${relative} contains an em dash`);
  }
});

/* -------------------------------------------------------------- the css */

const css = read("static/app.css");

ok("the theme is defined three times and nowhere else", () => {
  assert.match(css, /^:root \{/m, "the light palette sits on :root");
  assert.match(css, /@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{/);
  assert.match(css, /^:root\[data-theme="dark"\] \{/m);
  assert.match(css, /@supports \(color: oklch\(/, "wide gamut refines the sRGB fallback");
  assert.match(css, /body \{[\s\S]*background: var\(--bg\)/, "body paints its own background");
});

ok("every colour in the stylesheet is a token", () => {
  const stray = [];
  css.split("\n").forEach((line, index) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("--") || trimmed.startsWith("@supports") || trimmed.startsWith("/*")) return;
    if (/#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(|hsla?\(/.test(trimmed)) stray.push(`${index + 1}: ${trimmed}`);
  });
  assert.deepEqual(stray, [], `a colour literal escaped the token blocks:\n${stray.join("\n")}`);
});

ok("the measurements the record fixes are tokens", () => {
  assert.match(css, /--control: 32px/);
  assert.match(css, /--radius: 8px/);
  assert.match(css, /--head: 40px/);
  assert.match(css, /ui-monospace/);
  assert.match(css, /font-variant-numeric: tabular-nums/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\[hidden\] \{ display: none !important; \}/);
});

ok("every colour a reader has to read passes AA in both themes", () => {
  // Nothing here is large text: the smallest of it is eleven pixels, so 4.5 is the bar.
  const TEXT = ["text", "text-dim", "text-faint", "accent",
    "tone-run", "tone-wait", "tone-fail", "tone-done", "tone-pause"];
  const BEHIND = ["surface", "surface-2", "bg"];
  const thin = [];
  for (const gamut of ["srgb", "oklch"]) {
    for (const theme of ["light", "dark"]) {
      const palette = tokens(theme, gamut);
      for (const front of TEXT) {
        for (const behind of BEHIND) {
          const one = parseColour(palette[front]);
          const other = parseColour(palette[behind]);
          assert.ok(one && other, `${gamut} ${theme}: --${front} or --${behind} is missing`);
          const ratio = contrast(one, other);
          if (ratio < 4.5) thin.push(`${gamut} ${theme} --${front} on --${behind}: ${ratio.toFixed(2)}`);
        }
      }
    }
  }
  assert.deepEqual(thin, [], `text that cannot be read:\n${thin.join("\n")}`);
});

ok("the sidebar really collapses at the two widths the record names", () => {
  const narrow = css.match(/@media \(max-width: 900px\) \{([\s\S]*?)\n\}/);
  const phone = css.match(/@media \(max-width: 600px\) \{([\s\S]*?)\n\}/);
  assert.ok(narrow, "there is no rule for the icons-only width");
  assert.ok(phone, "there is no rule for the phone width");
  assert.match(narrow[1], /--sidebar: \d+px/, "the sidebar does not narrow");
  assert.match(narrow[1], /\.navlink span\.label[\s\S]*display: none/, "the labels do not go away");
  assert.match(narrow[1], /\.navlink \{[^}]*min-width: (\d\d)px/, "a link becomes smaller than a fingertip");
  const tap = Number(narrow[1].match(/\.navlink \{[^}]*min-width: (\d+)px/)[1]);
  assert.ok(tap >= 24, `a navigation target is ${tap}px wide`);
  assert.match(phone[1], /grid-template-areas: "top" "side" "view"/, "the sidebar does not move to the top");
});

ok("every movement respects a reader who asked for less of it", () => {
  const durations = [...css.matchAll(/transition:[^;]*?(\d+)(ms|s)\b/g)].map((found) => found[0]);
  assert.deepEqual(durations, [],
    `a transition names its own duration instead of the token:\n${durations.join("\n")}`);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*:root \{ --motion: 1ms; \}/);
});

/* ---------------------------------------------------------- the modules */

const fmt = await import("./static/core/fmt.js");
const ui = await import("./static/core/ui.js");
const identity = await import("./static/core/identity.js");
const api = await import("./static/core/api.js");

ok("times and sizes read the way a person says them", () => {
  const now = 1_000_000;
  assert.equal(fmt.ago(now - 10, now), "just now");
  assert.equal(fmt.ago(now - 600, now), "10m ago");
  assert.equal(fmt.ago(null), "not known");
  assert.equal(fmt.duration(3700), "1h 1m");
  assert.equal(fmt.duration(90061), "1d 1h");
  assert.equal(fmt.until(now + 300, now), "in 5m");
  assert.equal(fmt.bytes(1536), "1.5 KB");
  assert.equal(fmt.num(1234567), "1,234,567");
  assert.equal(fmt.money(1.5), "$1.50");
  assert.equal(fmt.percent(71), "71%");
  assert.equal(fmt.num(null), "none");
  assert.equal(fmt.shorten("one two three four", 9), "one two…");
});

ok("status has five meanings and only five", () => {
  assert.deepEqual(Object.keys(ui.MEANINGS), ["run", "wait", "fail", "done", "pause"]);
  const raw = ["running", "starting", "pr_open", "done_no_pr", "done", "ended", "failed",
    "killed", "gave_up", "state_unreadable", "paused", "held", "", null, "something new"];
  for (const status of raw) {
    assert.ok(ui.MEANINGS[ui.agentMeaning(status)], `${status} lands outside the five meanings`);
  }
  assert.equal(ui.agentMeaning("running"), "run");
  assert.equal(ui.agentMeaning("pr_open"), "wait");
  assert.equal(ui.agentMeaning("state_unreadable"), "fail");
  assert.equal(ui.agentMeaning("done"), "done");
  assert.equal(ui.agentMeaning("held"), "pause");
  for (const state of ["passed", "failed", "queued", "running", "conflict", "blocked", "anything"]) {
    assert.ok(ui.MEANINGS[ui.queueMeaning(state)], `${state} lands outside the five meanings`);
  }
});

ok("only a real web address is rendered as a link", () => {
  for (const good of ["https://example.invalid/demo/pull/1", "http://127.0.0.1:8080/x?y=1"]) {
    assert.equal(typeof ui.safeHref(good), "string", good);
  }
  for (const bad of ["javascript:window.__pwn=1", "JavaScript:alert(1)", "data:text/html,<b>x",
    "vbscript:x", "//example.invalid/x", "/api/fleet", "", null, undefined, 12, "ftp://host/x"]) {
    assert.equal(ui.safeHref(bad), null, `${bad} must not become a link`);
  }
});

/** Every word a tree would put on the screen, so a check can read what a reader would read. */
function words(node) {
  if (node == null || node === false) return "";
  if (Array.isArray(node)) return node.map(words).join(" ");
  if (typeof node !== "object") return String(node);
  if (node.text != null) return node.text;
  return (node.children || []).map(words).join(" ");
}

/** The tags a tree uses, so a check can tell a command apart from a sentence about one. */
function tags(node, found = []) {
  if (node == null || typeof node !== "object") return found;
  if (Array.isArray(node)) {
    for (const child of node) tags(child, found);
    return found;
  }
  if (node.tag) found.push(`${node.tag}.${node.props.class || ""}`);
  for (const child of node.children || []) tags(child, found);
  return found;
}

ok("an empty panel and an error panel both print the command they name", () => {
  const empty = ui.emptyState({
    title: "No projects yet",
    body: "A project tells the farm which repository a lane may work in.",
    command: "fleet add-project --name <name> --repo <owner>/<repo>",
  });
  assert.equal(empty.tag, "div");
  assert.equal(empty.props.class, "state-note");
  assert.match(words(empty), /No projects yet/);
  assert.match(words(empty), /fleet add-project --name <name> --repo <owner>\/<repo>/);
  assert.ok(tags(empty).includes("code.cmd"), "the command is not written as a command");

  const error = ui.errorState({
    title: "gh is not installed",
    body: "Checks on a change cannot be read without it.",
    command: "sudo apt install gh",
  });
  assert.equal(error.props.class, "state-note error");
  assert.match(words(error), /sudo apt install gh/);
  assert.ok(tags(error).includes("code.cmd"));

  // A panel with nothing to suggest must not invent a command line for the reader to copy.
  const quiet = ui.emptyState({ title: "Nothing here", body: "", command: "" });
  assert.ok(!tags(quiet).includes("code.cmd"), "an empty command still drew a command line");
});

ok("the four states are decided in one place, and each of them draws something", () => {
  const waiting = { path: "/api/x", everLoaded: false, error: null, data: null };
  const failed = { path: "/api/x", everLoaded: false, error: { title: "gh could not answer", body: "one line", command: "sudo apt install gh" } };
  const missing = { path: "/api/x", everLoaded: true, data: { unavailable: "No head office is configured.", fix: "hq init" } };
  const waking = { path: "/api/x", everLoaded: true, data: { pending: "2026-09-21T00:00:00Z", boxes: [] } };
  const empty = { path: "/api/x", everLoaded: true, data: [] };
  const ready = { path: "/api/x", everLoaded: true, data: ["one"] };
  const options = {
    isEmpty: (data) => !api.list(data).length,
    empty: () => ui.emptyState({ title: "Nothing yet", body: "", command: "fleet status" }),
    ready: (data) => ui.h("p", null, `${data.length} of them`),
  };
  assert.ok(tags(ui.panel(waiting, options)).some((tag) => tag.startsWith("div.skeleton")),
    "a panel that has never had an answer must shimmer");
  assert.match(words(ui.panel(failed, options)), /sudo apt install gh/);
  assert.match(words(ui.panel(missing, options)), /No head office is configured\./);
  assert.ok(tags(ui.panel(waking, options)).some((tag) => tag.startsWith("div.skeleton")),
    "a snapshot that has not been taken yet must shimmer, not show an error");
  assert.match(words(ui.panel(empty, options)), /Nothing yet/);
  assert.match(words(ui.panel(ready, options)), /1 of them/);
});

ok("a mark is a glyph and one of the page's own twelve colours", () => {
  identity.setRegistry({
    winston: { icon: "W", color: "#5b8def" },
    evil: { icon: "E".repeat(400), color: "red;background-image:url('https://evil.example.invalid/x.png')" },
  });
  assert.equal(identity.mark("winston").registered, true);
  const unknown = identity.mark("newcomer");
  assert.equal(unknown.registered, false);
  assert.equal(unknown.glyph, "N");
  assert.equal(identity.mark("").glyph, String.fromCharCode(183));
  for (const name of ["winston", "evil", "newcomer", "", null]) {
    const found = identity.mark(name);
    assert.equal("color" in found, false, "a mark must not carry a colour value at all");
    assert.ok(Number.isInteger(found.tone) && found.tone >= 0 && found.tone < identity.TONES,
      `${name} has tone ${found.tone}`);
    assert.ok([...found.glyph].length <= 2, `${name} has a glyph of ${[...found.glyph].length} characters`);
  }
  assert.equal(identity.mark("evil").glyph, "EE");
  assert.equal(identity.tone("abc"), identity.tone("abc"));
});

ok("layout lives in the stylesheet and no route writes a style attribute", () => {
  for (const relative of REQUIRED_FILES.filter((name) => name.endsWith(".js"))) {
    const source = read(relative);
    const styles = [...source.matchAll(/style:\s*([^,)}]+)/g)].map((found) => found[1].trim());
    for (const value of styles) {
      assert.match(value, /^widthStyle\(/,
        `${relative} writes a style attribute instead of using a class: ${value}`);
    }
  }
});

ok("an answer that is not an object is a failure, not data", () => {
  for (const payload of [null, undefined, "a proxy said hello", 42, true]) {
    assert.throws(() => api.shaped(payload, "/api/ci"), api.ApiError,
      `${JSON.stringify(payload)} must not reach a view as data`);
  }
  for (const payload of [{}, [], { unavailable: "no office", fix: "hq init" }]) {
    assert.equal(api.shaped(payload, "/api/ci"), payload);
  }
  const shaped = api.normaliseError(new api.ApiError(200, { error: api.UNREADABLE }, "/api/ci"), "/api/ci");
  assert.match(shaped.title, /could not be read/);
  assert.ok(shaped.command.length > 0);
  assert.deepEqual(api.list(["one"]), ["one"]);
  for (const notAList of [null, undefined, {}, "x", 3]) assert.deepEqual(api.list(notAList), []);
});

ok("a failure is turned into a sentence and a command, never a trace", () => {
  const offline = api.normaliseError(new TypeError("fetch failed"), "/api/fleet");
  assert.match(offline.title, /did not answer/);
  assert.ok(offline.command);
  const missing = api.normaliseError(new api.ApiError(404, null, "/api/projects"), "/api/projects");
  assert.match(missing.body, /\/api\/projects/);
  const refused = api.normaliseError(new api.ApiError(403, { error: "no token" }, "/api/projects"));
  assert.match(refused.title, /cannot read/);
  const tool = api.normaliseError(new api.ApiError(500, { error: "gh is not installed" }, "/api/ci"));
  assert.equal(tool.command, "sudo apt install gh");
  for (const shaped of [offline, missing, refused, tool]) {
    assert.ok(!/ at |Error:|\.js:\d/.test(shaped.body), "an error body must not carry a stack trace");
  }
});

ok("an answer that says it is old is counted as old, even though it arrived", () => {
  const fresh = api.resource("/api/health");
  fresh.data = { at: "2026-09-21T19:00:00Z", stale_since: null, error: null, checks: [] };
  const old = api.resource("/api/mail/boxes");
  old.data = { at: "2026-09-21T18:00:00Z", stale_since: "2026-09-21T18:00:00Z",
    error: "gh could not reach github.com", boxes: [] };
  const found = api.staleSnapshots(["/api/health", "/api/mail/boxes", "/api/never-asked-for"]);
  assert.deepEqual(found.map((row) => row.path), ["/api/mail/boxes"]);
  assert.equal(found[0].reason, "gh could not reach github.com");
  assert.deepEqual(api.staleSnapshots(["/api/health"]), []);
  // A route that answers a list has no envelope to be old, and must not throw here.
  const listed = api.resource("/api/fleet");
  listed.data = [{ slug: "one" }];
  assert.deepEqual(api.staleSnapshots(["/api/fleet"]), []);
  api.forget("/api/health");
  api.forget("/api/mail/boxes");
  api.forget("/api/fleet");
  assert.ok(read("static/app.js").includes("staleSnapshots"),
    "the header does not look at whether a snapshot on screen is old");
});

ok("a refusal carries the server's own sentence to whoever has to act on it", () => {
  const refused = new api.ApiError(400, { error: "a repository is owner/name" }, "/api/projects");
  assert.equal(api.serverReason(refused), "a repository is owner/name");
  assert.equal(refused.reason, "a repository is owner/name");
  // Nothing to say is said as nothing, so the caller falls back to its own wording.
  assert.equal(api.serverReason(new api.ApiError(500, null, "/api/projects")), "");
  assert.equal(api.serverReason(new api.ApiError(500, { detail: "x" }, "/api/projects")), "");
  assert.equal(api.serverReason(new TypeError("fetch failed")), "");
  assert.equal(api.serverReason(null), "");
  for (const relative of ["static/views/projects.js", "static/views/agents.js", "static/views/mail.js"]) {
    assert.ok(read(relative).includes("serverReason"),
      `${relative} throws the server's reason away and writes its own sentence instead`);
  }
});

const VIEWS = await Promise.all(
  ["overview", "agents", "mail", "queue", "projects", "accounts", "system"]
    .map((name) => import(`./static/views/${name}.js`).then((module) => module.default)),
);

ok("every view declares the same contract", () => {
  const ids = VIEWS.map((view) => view.id);
  assert.deepEqual(ids, ["overview", "agents", "mail", "queue", "projects", "accounts", "system"]);
  for (const view of VIEWS) {
    assert.equal(typeof view.title, "string");
    assert.ok(view.title.length > 0);
    assert.equal(typeof view.render, "function");
    const needs = typeof view.needs === "function" ? view.needs({}) : view.needs;
    assert.ok(Array.isArray(needs), `${view.id} must declare what it reads`);
    for (const route of needs) assert.match(route, /^\/api\//, `${view.id} reads ${route}`);
  }
});

await okAsync("a card with no numbers says so in words, and never prints a time it does not have", async () => {
  const { troubleNote } = await import("./static/views/accounts.js");
  const said = "This account has no login on the farm yet. Log in once: ssh -t farm claude";
  const sentence = (node) => words(node);

  // No numbers and no time: the card must not turn a missing time into "from not known".
  const fresh = sentence(troubleNote({ name: "farm-one", read_at: null, stale_error: said }));
  assert.equal(fresh, `No numbers yet. ${said}`);
  assert.ok(!/not known/.test(fresh), fresh);

  // Numbers that have stopped refreshing, with a time behind them.
  const kept = sentence(troubleNote({
    name: "farm-two", session: 42, read_at: (Date.now() / 1000) - 900,
    stale_error: "The vendor did not answer the last time the farm asked.",
  }));
  assert.match(kept, /^These numbers are as of 15m ago and have not refreshed\./);
  assert.match(kept, /The vendor did not answer/);

  // Numbers with no time at all: no "as of" is written.
  const timeless = sentence(troubleNote({
    name: "farm-three", weekly: 71, read_at: null,
    stale_error: "The login on this account has expired. Log in again.",
  }));
  assert.equal(timeless, "These numbers have not refreshed. The login on this account has expired. Log in again.");
  assert.ok(!/as of/.test(timeless), timeless);

  // Nothing wrong: no sentence at all.
  assert.equal(troubleNote({ name: "farm-four", session: 42, read_at: 1 }), null);
  assert.equal(troubleNote({ name: "farm-five", stale_error: "   " }), null);
});

await okAsync("a lane that put part of its work down says so", async () => {
  const { droppedScope } = await import("./static/views/agents.js");
  assert.equal(droppedScope({ scope: { delivered: [1841], dropped: [1842, 1843] } }),
    "scope dropped: 1842, 1843");
  for (const quiet of [{}, { scope: {} }, { scope: { dropped: [] } }, { scope: { dropped: "some" } }, null]) {
    assert.equal(droppedScope(quiet), "", JSON.stringify(quiet));
  }
});

await okAsync("a check keeps the name the farm gave it, whatever that name is", async () => {
  const { checkEntries } = await import("./static/views/agents.js");
  assert.deepEqual(checkEntries([
    { name: "unit tests", state: "pass" },
    { name: "typecheck", state: "pass" },
    { name: "container image", state: "pending" },
  ]), [["unit tests", "pass"], ["typecheck", "pass"], ["container image", "pending"]]);
  // A record written before the server answered a list still draws.
  assert.deepEqual(checkEntries({ "unit tests": "pass", "container image": "pend" }),
    [["unit tests", "pass"], ["container image", "pend"]]);
  // A word this page has no colour for is drawn as unknown, not as a class of its own.
  assert.deepEqual(checkEntries([{ name: "odd", state: "something else" }]), [["odd", "unknown"]]);
  for (const nothing of [null, undefined, [], {}, "checks", 7]) {
    assert.deepEqual(checkEntries(nothing), [], `${JSON.stringify(nothing)} is not a check list`);
  }
});

ok("the status vocabulary is written down once", () => {
  const shell = read("static/app.js");
  assert.match(shell, /agentMeaning/, "the shell reads the one table in core/ui.js");
  assert.ok(!/pr_open:\s*"wait"/.test(shell) && !/done_no_pr:/.test(shell),
    "the shell must not carry a second copy of the status table");
  for (const relative of REQUIRED_FILES.filter((name) => name.endsWith(".js") && !name.endsWith("core/ui.js"))) {
    assert.ok(!/state_unreadable:\s*"/.test(read(relative)), `${relative} maps a status of its own`);
  }
});

ok("the page and the shell agree on the seven entries, exactly", () => {
  const registry = read("static/app.js");
  const icons = registry.match(/const ICONS = \{([\s\S]*?)\n\};/);
  assert.ok(icons, "the shell has no icon table");
  const named = [...icons[1].matchAll(/^\s{2}([a-z]+):/gm)].map((found) => found[1]);
  assert.deepEqual(named, VIEWS.map((view) => view.id),
    "the icons and the views are not the same seven, in the same order");
  for (const icon of icons[1].match(/'[^']*'/g) || []) {
    assert.match(icon, /^'<(path|circle)/, "an icon is not drawn by this page");
  }
});

/* ---------------------------------------------------------- the routes */

const stub = spawn("python3", [path.join(HERE, "test_stub_server.py"), String(PORT)], { stdio: "ignore" });
process.on("exit", () => stub.kill());

async function waitForStub() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      if ((await fetch(`${BASE}/api/config`)).ok) return;
    } catch (error) { /* not up yet */ }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("the stub server never came up");
}
await waitForStub();

const get = async (route, state = "ready") => {
  const joiner = route.includes("?") ? "&" : "?";
  const response = await fetch(`${BASE}${route}${joiner}state=${state}`);
  return { status: response.status, body: await response.json(), response };
};

await okAsync("the page and its files are served", async () => {
  const page = await fetch(`${BASE}/`);
  assert.equal(page.status, 200);
  assert.match(page.headers.get("content-type"), /text\/html/);
  const script = await fetch(`${BASE}/static/app.js`);
  assert.equal(script.status, 200);
  assert.match(script.headers.get("content-type"), /javascript/);
  const style = await fetch(`${BASE}/static/app.css`);
  assert.match(style.headers.get("content-type"), /text\/css/);
  assert.equal((await fetch(`${BASE}/static/../test_ui.mjs`)).status, 404);
});

await okAsync("the settings the page needs before it can draw", async () => {
  const { body } = await get("/api/config");
  assert.equal(typeof body.title, "string");
  assert.equal(typeof body.version, "string");
  for (const flag of ["hq", "slice", "gpu", "cpu_temp", "ci_daemon", "forge"]) {
    assert.equal(typeof body.features[flag], "boolean", `features.${flag} must be a boolean`);
  }
  assert.ok("pending" in body, "/api/config does not say whether its first pass has run");
  const waking = (await get("/api/config", "loading")).body;
  assert.ok(waking.pending, "a config read before the first pass says so");
  assert.equal(waking.features.slice, false, "a control with no reading behind it stays off");
  assert.equal(waking.features.ci_daemon, false);
});

await okAsync("a snapshot that has never been taken says so instead of answering empty", async () => {
  for (const route of ["/api/health", "/api/mail/boxes", "/api/mail/feed?hours=24", "/api/mail/who"]) {
    const { status, body } = await get(route, "loading");
    assert.equal(status, 200, `${route} must not fail while it is waking up`);
    assert.ok(body.pending, `${route} does not say its first pass is still to come`);
  }
});

await okAsync("the prerequisites come back in the order the record fixes", async () => {
  const { body } = await get("/api/health");
  for (const field of ["at", "stale_since", "error", "pending"]) {
    assert.ok(field in body, `/api/health does not say its ${field}`);
  }
  assert.match(body.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/, "a snapshot time is ISO in UTC");
  assert.deepEqual(body.checks.map((check) => check.id), [
    "gh", "tmux", "systemd_user", "linger", "hq", "claude", "codex",
    "gpu_sensor", "cpu_temp_sensor", "ci_daemon", "sweep_timer", "office",
  ]);
  for (const check of body.checks) {
    assert.ok(["ok", "missing", "error", "off"].includes(check.state), `${check.id} has state ${check.state}`);
    assert.equal(typeof check.label, "string");
    assert.equal(typeof check.detail, "string");
    assert.equal(typeof check.fix, "string");
    if (check.state === "ok") assert.equal(check.fix, "", `${check.id} is ok and needs no fix`);
  }
  const broken = (await get("/api/health", "error")).body.checks;
  for (const check of broken.filter((row) => row.state === "missing" || row.state === "error")) {
    assert.ok(check.fix.length > 0, `${check.id} is not ok and must name the command that fixes it`);
  }
});

await okAsync("a project row says where it is and what it is doing", async () => {
  const { body } = await get("/api/projects");
  assert.ok(Array.isArray(body));
  for (const row of body) {
    for (const field of ["name", "repo", "path", "base_branch", "ports", "lanes_open", "last_activity"]) {
      assert.ok(field in row, `a project row has no ${field}`);
    }
    for (const port of ["web", "api", "e2e"]) assert.equal(typeof row.ports[port], "number");
  }
  assert.deepEqual((await get("/api/projects", "empty")).body, []);
});

await okAsync("a lane's log says whether there is a file at all", async () => {
  const { body } = await get("/api/agent/log?slug=demo-api-3f2a&tail=25");
  assert.equal(body.slug, "demo-api-3f2a");
  assert.ok(Array.isArray(body.lines));
  assert.equal(body.lines.length, 25);
  assert.equal(typeof body.truncated, "boolean");
  assert.equal(typeof body.missing, "boolean");
  assert.ok("file" in body);
  const none = (await get("/api/agent/log?slug=demo-api-3f2a", "empty")).body;
  assert.equal(none.missing, true);
  assert.equal(typeof none.message, "string");
});

const ENVELOPES = [
  ["/api/mail/boxes", "boxes", ["name", "number", "updated_at", "count_24h", "last_at"]],
  ["/api/mail/thread?box=all", "messages", ["sender", "at", "text", "created_at"]],
  ["/api/mail/feed?hours=24", "events", ["at", "at_label", "kind", "text"]],
  ["/api/mail/who", "sessions", ["name", "state", "age_hours", "since", "task"]],
];

await okAsync("every mail route answers the same envelope", async () => {
  for (const [route, key, fields] of ENVELOPES) {
    const { body } = await get(route);
    for (const field of ["at", "stale_since", "error", "pending"]) {
      assert.ok(field in body, `${route} does not say its ${field}`);
    }
    assert.match(body.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/, `${route} does not date itself in ISO`);
    for (const field of ["stale_since", "pending"]) {
      if (body[field] != null) assert.match(body[field], /^\d{4}-\d{2}-\d{2}T/, `${route}.${field} is not ISO`);
    }
    assert.ok(Array.isArray(body[key]), `${route} does not carry ${key}`);
    for (const row of body[key]) {
      for (const field of fields) assert.ok(field in row, `a row of ${key} has no ${field}`);
    }
    const drained = (await get(route, "empty")).body;
    assert.deepEqual(drained[key], [], `${route} does not empty out`);
  }
  const thread = (await get("/api/mail/thread?box=all")).body;
  assert.equal(thread.box, "all");
  assert.equal(typeof thread.window_hours, "number");
  assert.equal(typeof (await get("/api/mail/feed?hours=24")).body.hours, "number");
  for (const session of (await get("/api/mail/who")).body.sessions) {
    assert.ok(["live", "stale"].includes(session.state));
  }
});

await okAsync("a thread request that cannot be served is refused, not guessed at", async () => {
  assert.equal((await get("/api/mail/thread?box=")).status, 400, "an empty mailbox name is refused");
  assert.equal((await get("/api/mail/thread?box=all&since=yesterday")).status, 400, "a time the server cannot read is refused");
  const send = await fetch(`${BASE}/api/mail/send?state=empty`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to: "all", text: "hello" }),
  });
  assert.equal(send.status, 503, "sending before the office has been read is refused");
  assert.equal(typeof (await send.json()).error, "string");
});

await okAsync("an unknown mailbox is answered, not swallowed", async () => {
  const { status, body } = await get("/api/mail/thread?box=nobody");
  assert.equal(status, 404);
  assert.equal(typeof body.error, "string");
  assert.ok(Array.isArray(body.boxes), "a wrong box is answered with the boxes that do exist");
});

await okAsync("a farm with no office says so in one sentence", async () => {
  for (const [route] of ENVELOPES) {
    const { status, body } = await get(route, "error");
    assert.equal(status, 200, `${route} must not turn a missing office into a failure`);
    assert.equal(typeof body.unavailable, "string");
    assert.ok(body.fix.length > 0, `${route} must name the command that fixes it`);
  }
});

await okAsync("the two write routes say what they did", async () => {
  const send = async (route, payload) => {
    const response = await fetch(`${BASE}${route}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return { status: response.status, body: await response.json() };
  };
  const message = await send("/api/agent/msg", { slug: "demo-api-3f2a", text: "look at the orders screen" });
  assert.equal(message.status, 200);
  assert.equal(message.body.ok, true);
  assert.equal(message.body.slug, "demo-api-3f2a");
  assert.equal(typeof message.body.detail, "string");
  assert.equal((await send("/api/agent/msg", { slug: "" })).status, 400);

  const mail = await send("/api/mail/send", { to: "all", text: "the search lane is done" });
  assert.equal(mail.body.ok, true);
  assert.equal(mail.body.to, "all");
  assert.equal(typeof mail.body.from, "string");
  assert.equal((await send("/api/mail/send", { to: "all", text: "" })).status, 400);

  const project = await send("/api/projects", { name: "newone", repo: "your-org/newone", port_base: 5300 });
  assert.equal(project.body.name, "newone");
  assert.equal(typeof project.body.ports.web, "number");
  assert.equal(typeof (await send("/api/projects", { name: "" })).body.error, "string");
});

await okAsync("the state flag flips the whole dataset", async () => {
  assert.equal((await get("/api/fleet", "ready")).body.length > 0, true);
  assert.deepEqual((await get("/api/fleet", "empty")).body, []);
  assert.equal((await get("/api/accounts", "empty")).body.accounts.length, 0);
  assert.deepEqual((await get("/api/models", "empty")).body, []);
  assert.equal((await get("/api/ci", "empty")).body.recent.length, 0);
  assert.equal((await get("/api/ci", "error")).status, 500);
  assert.equal((await get("/api/config", "error")).body.features.gpu, false);
  assert.equal((await get("/api/access", "error")).body.writable, false);
  assert.equal((await get("/api/metrics", "error")).body.gpu, null);
});

await okAsync("a limit window is labelled by its own name", async () => {
  const { body } = await get("/api/accounts");
  const windows = [];
  for (const account of body.accounts) {
    if (account.session != null) windows.push("session");
    if (account.weekly != null) windows.push("weekly");
    for (const scoped of account.scoped || []) windows.push(scoped.label);
  }
  assert.ok(windows.includes("long context"), "a scoped window keeps its own label");
  const source = read("static/views/accounts.js");
  assert.ok(!/fable/i.test(source), "no window may be singled out by name in the page");
  assert.ok(!/<svg|base64/i.test(source), "an engine mark comes from the server, not from a logo in the page");
});

stub.kill();
console.log(`\nRESULT: ${passed} checks passed`);

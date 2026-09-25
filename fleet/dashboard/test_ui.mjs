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
  // The Machine tab's own stylesheet is linked from the page, next to app.css.
  assert.match(html, /<link rel="stylesheet" href="\/static\/machine\.css">/);
});

/* The tab shows the murmur mark, the same file the landing uses, in both themes: a status
   square in the tab reads as a broken icon, and every murmur page should look like one product. */
ok("the favicon is the murmur mark, drawn from the mark's own paths", () => {
  assert.match(html, /<link rel="icon" id="favicon" href="\/static\/favicon\.svg" type="image\/svg\+xml">/);
  const icon = read("static/favicon.svg");
  const paths = (text) => [...text.matchAll(/ d="([^"]+)"/g)].map((found) => found[1]).join("|");
  assert.equal(paths(icon), paths(read("static/mark.svg")), "the favicon is not the mark");
  assert.match(icon, /prefers-color-scheme:\s*dark/, "the favicon has no dark variant");
  assert.ok(!read("static/app.js").includes("getElementById(\"favicon\")"),
    "something still repaints the favicon");
});

ok("the page carries the chrome the views expect", () => {
  for (const id of ["sidebar", "navlinks", "topbar", "productTitle", "viewTitle", "capacity", "farmState",
    "projectFilter", "freshness", "themeSwitch", "paletteOpen", "palette", "paletteInput",
    "paletteList", "view", "drawer", "drawerTitle", "drawerBody", "drawerScrim", "toasts",
    "favicon", "sidebarTitle", "powerField", "powerPick"]) {
    assert.ok(html.includes(`id="${id}"`), `index.html is missing #${id}`);
  }
  const shell = read("static/app.js");
  for (const choice of ["system", "light", "dark"]) {
    assert.ok(new RegExp(`\\["${choice}"`).test(shell), `the theme control cannot reach ${choice}`);
  }
  assert.ok(html.includes("murmur"), "the fallback product name is murmur");
  // A view's own clock (the Re-check reads) stops when the reader leaves its tab, so the
  // context tells a view which tab is on screen.
  assert.match(shell, /get view\(\) \{\s*return state\.view;/, "the context names the tab on screen");
});

/* ------------------------------------------------------------- the files */

const REQUIRED_FILES = [
  "static/app.css", "static/app.js",
  "static/core/api.js", "static/core/ui.js", "static/core/fmt.js", "static/core/identity.js",
  "static/views/board.js", "static/views/agents.js", "static/views/mail.js",
];

/* The machine tab is loaded after the page, from a file of its own. It is checked like every
   other view when that file is here. */
const MACHINE = "static/views/machine.js";

/* The Machine tab's count points at its Health section, so it is drawn only when that section
   is: the badge must bail out on the same feature the render checks. Read from the source,
   because the browser harness draws no tab badges. */
ok("machine: the tab count and the Health section hang on the same feature", () => {
  const source = read(MACHINE);
  const badge = source.slice(source.indexOf("  badge(context) {"), source.indexOf("  render(context) {"));
  assert.match(badge, /if \(!context\.features\.health_panel\) return "";/);
  assert.match(source, /context\.features\.health_panel \? healthSection\(context\) : null/);
});
const hasMachine = fs.existsSync(path.join(HERE, MACHINE));

ok("every file the design record names exists, and the three it removes are gone", () => {
  for (const relative of REQUIRED_FILES) {
    assert.ok(fs.existsSync(path.join(HERE, relative)), `missing ${relative}`);
  }
  /* static/views/projects.js came back as the Machine tab's Projects section (design record
     github-projects.md, section 7), not as a tab of its own. */
  for (const gone of ["static/views/overview.js",
    "static/views/accounts.js", "static/views/system.js"]) {
    assert.ok(!fs.existsSync(path.join(HERE, gone)), `${gone} is still here`);
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

ok("the fixed measurements are tokens", () => {
  // One height for every control on a screen, the Almanac's button.
  assert.match(css, /--control: 34px/);
  assert.match(css, /--control-sm: 28px/);
  // The Starling Almanac design system: cards and dialogs on the 12px step, controls on 7px.
  assert.match(css, /--radius: 12px/);
  assert.match(css, /--radius-sm: 7px/);
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
  // accent-soft is the ground of a selected row, tab, card and conversation, all of them
  // carrying small state words.
  const BEHIND = ["surface", "surface-2", "bg", "accent-soft"];
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
      assert.match(value, /^(widthStyle)\(/,
        `${relative} writes a style attribute instead of using a class: ${value}`);
    }
  }
});

ok("an answer that is not an object is a failure, not data", () => {
  for (const payload of [null, undefined, "a proxy said hello", 42, true]) {
    assert.throws(() => api.shaped(payload, "/api/fleet"), api.ApiError,
      `${JSON.stringify(payload)} must not reach a view as data`);
  }
  for (const payload of [{}, [], { unavailable: "no office", fix: "hq init" }]) {
    assert.equal(api.shaped(payload, "/api/fleet"), payload);
  }
  const shaped = api.normaliseError(new api.ApiError(200, { error: api.UNREADABLE }, "/api/fleet"), "/api/fleet");
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
  const tool = api.normaliseError(new api.ApiError(500, { error: "gh is not installed" }, "/api/fleet"));
  assert.equal(tool.command, "install gh 2.40 or newer: https://github.com/cli/cli#installation");
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
  for (const relative of ["static/views/agents.js", "static/views/mail.js"]) {
    assert.ok(read(relative).includes("serverReason"),
      `${relative} throws the server's reason away and writes its own sentence instead`);
  }
});

const TABS = ["board", "mail", ...(hasMachine ? ["machine"] : [])];
const VIEWS = await Promise.all(
  TABS.map((name) => import(`./static/views/${name}.js`).then((module) => module.default)),
);

ok("every view declares the same contract", () => {
  const ids = VIEWS.map((view) => view.id);
  assert.deepEqual(ids, TABS);
  for (const view of VIEWS) {
    assert.equal(typeof view.title, "string");
    assert.ok(view.title.length > 0);
    assert.equal(typeof view.render, "function");
    const needs = typeof view.needs === "function" ? view.needs({}) : view.needs;
    assert.ok(Array.isArray(needs), `${view.id} must declare what it reads`);
    for (const route of needs) assert.match(route, /^\/api\//, `${view.id} reads ${route}`);
  }
});

ok("the browser check runs every hostile and screenshot pass, by glob", () => {
  const runner = read("test_browser.sh");
  assert.match(runner, /test_hostile\*\.mjs/, "a lane's own hostile pass would never run");
  assert.match(runner, /test_screens\*\.mjs/, "a lane's own screenshot pass would never run");
  assert.match(runner, /PORT=\$own_port/, "two lanes' checks would collide on one socket");
  /* Every port in here is asked of the kernel. A number written in the file is a number the
     other lane's run on this machine takes at the same second. */
  assert.match(runner, /own_port=\$\(free_port\)/, "the per-check port is not a free one");
  assert.match(runner, /PORT=\$\{PORT:-\$\(free_port\)\}/, "the shared stub's port is not a free one");
  assert.ok(!/(?:^|[\s{(])(?:PORT|own_port)=\$?\{?[A-Za-z_]*:?-?\d/m.test(runner),
    "a port number is written into the file, so the other lane's run takes the same socket");
});

ok("the four old addresses still land on the thing they named", () => {
  const shell = read("static/app.js");
  const table = shell.match(/const REDIRECTS = \{([\s\S]*?)\n\};/);
  assert.ok(table, "the shell has no redirect table, so yesterday's bookmark is a blank page");
  for (const [from, to] of [["overview", "board"], ["agents", "board"],
    ["projects", "machine"], ["accounts", "machine"], ["system", "machine"]]) {
    assert.match(table[1], new RegExp(`${from}: \\["${to}"`), `#/${from} does not land on ${to}`);
  }
  assert.match(table[1], /projects: \["machine", "projects"\]/, "the projects section is not named");
  assert.match(table[1], /accounts: \["machine", "accounts"\]/, "the accounts section is not named");
  // The address bar is rewritten, so the reader can bookmark where they actually are.
  assert.match(shell, /history\.replaceState/);
});

ok("the header carries the power setting as a control, not as a word", () => {
  const shell = read("static/app.js");
  assert.match(shell, /POWER_MODES/, "the header does not read the one table of settings");
  assert.match(shell, /apiPost\("\/api\/mode"/, "the header control does not post the setting");
  // The control is a select written in the page itself, so its write mark is there too.
  assert.match(read("index.html"), /<select id="powerPick" data-write/, "the header control is not marked as a write");
  const ui = read("static/core/ui.js");
  for (const word of ["Full", "Shared", "Background", "Paused", "Automatic"]) {
    assert.ok(ui.includes(`"${word}"`), `the power setting cannot reach ${word}`);
  }
  assert.ok(shell.includes('api.access.writable'), "the header control ignores a read-only page");
});

ok("the Board is its four parts: checklist, machine strip, accounts strip, agents", () => {
  const board = read("static/views/board.js");
  assert.match(board, /setupChecklist/, "no setup checklist");
  assert.match(board, /machineStrip/, "no machine strip");
  assert.match(board, /accountsStrip/, "no accounts strip");
  assert.match(board, /agentsPane/, "the agents pane is not on the Board");
  // The checklist has no dismiss: the only way to put it away is to fix what it names, so
  // the thing it draws carries no control at all.
  const checklist = board.slice(board.indexOf("function setupChecklist"));
  assert.ok(!checklist.slice(0, checklist.indexOf("\n}\n")).includes('h("button"'),
    "the setup checklist can be dismissed without fixing anything");
  const css = read("static/app.css");
  assert.match(css, /\.tile \{[^}]*grid-template-rows: auto auto 1fr/, "tiles are not three fixed rows");
  assert.match(css, /\.tile \.note \{[^}]*align-self: end/, "the tile note is not pinned to the bottom");
  assert.match(css, /\.grid\.accounts-row \{[^}]*\/ 6\)/, "the accounts do not share one row");
});

ok("the agents pane has two selects and a search, and no chips", () => {
  const source = read("static/views/agents.js");
  assert.match(source, /id: "agentSpawner"/);
  assert.match(source, /id: "agentStatus"/);
  assert.match(source, /id: "agentSearch"/);
  assert.ok(!/class: "chip"/.test(source), "the chips are still here");
  assert.match(source, /Started by/);
  assert.match(source, /Lane, branch or change number/);
});

/* The rule that decides which lanes stay on screen, read on its own. The pane used to be
   filtered by whatever string the select handed it, so the option labelled "Anyone (6)"
   filtered by the words "Anyone (6)" and left the reader with an empty pane and the advice to
   clear a filter they had just cleared. */
await okAsync("the first option of a filter select clears the filter, it does not empty the pane", async () => {
  const { filterAgents } = await import("./static/views/agents.js");
  const rows = [
    { slug: "one", spawned_by: "winston", status: "running", project: "murmur", lane: "board" },
    { slug: "two", spawned_by: "winston", status: "pr_open", project: "murmur", lane: "mail" },
    { slug: "three", spawned_by: "rubicon", status: "failed", project: "other", lane: "search" },
  ];
  assert.equal(filterAgents(rows, {}).length, 3, "a pane with no filter hides a lane");
  assert.equal(filterAgents(rows, { spawner: "" }).length, 3, "Anyone is not a name to filter by");
  assert.equal(filterAgents(rows, { status: "" }).length, 3, "Any status is not a status to filter by");
  assert.equal(filterAgents(rows, { spawner: "winston" }).length, 2);
  assert.equal(filterAgents(rows, { status: "run" }).length, 1);
  assert.equal(filterAgents(rows, { project: "murmur" }).length, 2);
  assert.equal(filterAgents(rows, { search: "SEARCH" }).length, 1, "the search is not case sensitive");
  // A status the five meanings do not have is not a filter: it came from somewhere it should
  // not have, and the honest answer is every lane, not none.
  assert.equal(filterAgents(rows, { status: "Any status (3)" }).length, 3,
    "a status outside the vocabulary empties the pane");
  assert.equal(filterAgents(rows, { search: "  " }).length, 3, "a search of blanks is no search");
  assert.equal(filterAgents(null, {}).length, 0, "a route that answered no list must not throw");
  const source = read("static/views/agents.js");
  assert.match(source, /selectedIndex === 0/, "the select that clears is read by label, not by position");
  assert.match(read("static/core/ui.js"), /localName === "option"/,
    "an option's value is written as a property, so it reports its own label as its value");
});

ok("stopping a lane and retiring it are asked about before they happen", () => {
  const source = read("static/views/agents.js");
  assert.match(source, /apiPost\("\/api\/agents\/kill", \{ slug, retire: choice\.retire \}\)/,
    "the drawer does not post the route the server lane serves");
  assert.match(source, /Stop this pass/, "a lane with a restart policy has no pass to stop");
  assert.match(source, /Retire this lane/);
  assert.match(source, /Stop this lane/, "a lane with no policy is offered the wrong two words");
  assert.match(source, /under a new name/, "the confirm does not say the runner will start it again");
  assert.match(source, /data-confirm-yes/, "there is no confirm step at all");
});

ok("every word the Mail tab promises is on the page, and no jargon with it", () => {
  const source = read("static/views/mail.js");
  for (const label of ["Conversations", "Everyone", "every agent on this farm",
    "Unread since you last looked", "Show all ", "Agents", "Here now",
    "Not heard from lately (", "Last seen ", "Message to ", "Sent as ", ", not as you",
    "Everything the office did", "The office last answered "]) {
    assert.ok(source.includes(label), `the mail page never says "${label}"`);
  }
  /* The jargon words, looked for in the sentences this page writes itself.
     A route it reads is not a sentence, and a class name is not either. */
  const said = [...source.matchAll(/"([^"\\]{8,})"|`([^`\\]{8,})`/g)]
    .map((found) => found[1] || found[2])
    .filter((text) => text.includes(" ") && !text.startsWith("/api/"));
  const jargon = [];
  for (const text of said) {
    for (const word of ["mailbox", "mailboxes", "feed", "hq", "issue", "thread id"]) {
      if (new RegExp(`\\b${word}\\b`, "i").test(text)) jargon.push(`${word}: ${text}`);
    }
  }
  assert.deepEqual(jargon, [], `the mail page speaks in jargon:\n${jargon.join("\n")}`);
});

ok("the mail page holds itself to the window and sends before the office answers", () => {
  const source = read("static/views/mail.js");
  assert.match(source, /fixed: true/, "the mail page still scrolls as one document");
  assert.match(source, /state: "sending"/, "a sent message does not appear at once");
  assert.match(source, /sent, it will show here at the next refresh/);
  const css = read("static/app.css");
  assert.match(css, /body\.fixed-page #view \{[^}]*overflow: hidden/, "the page under the panes can scroll");
  assert.match(css, /\.mail-pane \.pane-scroll \{[^}]*overflow-y: auto/, "a pane has no scroll of its own");
  assert.match(css, /@media \(max-width: 1100px\) \{[\s\S]*?\.people-count, \.people-close \{ display: inline-flex/,
    "the people pane does not become a count under 1100 px");
  assert.match(css, /@media \(max-width: 800px\) \{[\s\S]*?\.convo-select \{ display: flex/,
    "the conversations do not become a select under 800 px");
});

ok("every write control on these pages is marked and switched off without a token", () => {
  for (const relative of ["static/views/agents.js", "static/views/mail.js", "static/app.js"]) {
    const source = read(relative);
    // The header's one write control is written in index.html, so app.js is checked there.
    const marked = relative === "static/app.js" ? read("index.html") : source;
    assert.ok(marked.includes("data-write"), `${relative} has a write control nobody marked`);
    assert.ok(/access\.reason|api\.access\.reason/.test(source),
      `${relative} switches a control off without saying why`);
  }
  // A read-only dashboard is legitimate and must not look broken: one line on every tab says
  // so in the server's own words, instead of leaving the reader to find a dead button.
  assert.match(read("static/app.js"), /function readOnlyNote/);
  assert.match(read("static/app.css"), /\.readonly-strip/);
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
  /* The shell used the table only for the status favicon, which is gone; what stays true is
     that it never carries a copy of it. */
  assert.ok(!/pr_open:\s*"wait"/.test(shell) && !/done_no_pr:/.test(shell),
    "the shell must not carry a second copy of the status table");
  for (const relative of REQUIRED_FILES.filter((name) => name.endsWith(".js") && !name.endsWith("core/ui.js"))) {
    assert.ok(!/state_unreadable:\s*"/.test(read(relative)), `${relative} maps a status of its own`);
  }
});

ok("the page and the shell agree on the three entries, exactly", () => {
  const registry = read("static/app.js");
  const icons = registry.match(/const ICONS = \{([\s\S]*?)\n\};/);
  assert.ok(icons, "the shell has no icon table");
  const named = [...icons[1].matchAll(/^\s{2}([a-z]+):/gm)].map((found) => found[1]);
  assert.deepEqual(named, ["board", "mail", "machine"],
    "the icons and the tabs are not the same three, in the same order");
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
  for (const flag of ["hq", "slice", "gpu", "cpu_temp", "forge"]) {
    assert.equal(typeof body.features[flag], "boolean", `features.${flag} must be a boolean`);
  }
  assert.ok("pending" in body, "/api/config does not say whether its first pass has run");
  const waking = (await get("/api/config", "loading")).body;
  assert.ok(waking.pending, "a config read before the first pass says so");
  assert.equal(waking.features.slice, false, "a control with no reading behind it stays off");
});

await okAsync("a snapshot that has never been taken says so instead of answering empty", async () => {
  for (const route of ["/api/health", "/api/mail/boxes", "/api/mail/feed?hours=24", "/api/mail/who"]) {
    const { status, body } = await get(route, "loading");
    assert.equal(status, 200, `${route} must not fail while it is waking up`);
    assert.ok(body.pending, `${route} does not say its first pass is still to come`);
  }
});

await okAsync("the prerequisites come back in the order a person would fix them", async () => {
  const { body } = await get("/api/health");
  for (const field of ["at", "stale_since", "error", "pending"]) {
    assert.ok(field in body, `/api/health does not say its ${field}`);
  }
  assert.match(body.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/, "a snapshot time is ISO in UTC");
  assert.deepEqual(body.checks.map((check) => check.id), [
    "gh", "tmux", "systemd_user", "linger", "hq", "claude", "codex",
    "gpu_sensor", "cpu_temp_sensor", "sweep_timer", "office",
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

await okAsync("the farm says which port block is free, so the page never guesses", async () => {
  const { body } = await get("/api/projects/next-port");
  assert.equal(typeof body.next_port_base, "number");
  assert.equal(typeof body.sentence, "string");
  const highest = Math.max(...(await get("/api/projects")).body.map((row) => row.ports.web));
  assert.ok(body.next_port_base > highest, "the next block is above every dev server base");
  const shared = (await get("/api/projects")).body.map((row) => row.ports.api);
  assert.ok(body.next_port_base < Math.min(...shared),
    "the shared api base is not a project's own and must not raise the suggestion");
});

await okAsync("an engine row says whether this machine can run it", async () => {
  const { body } = await get("/api/engines");
  assert.ok(Array.isArray(body));
  for (const row of body) {
    for (const field of ["id", "label", "installed", "path", "install_hint", "enabled"]) {
      assert.ok(field in row, `an engine row has no ${field}`);
    }
    assert.equal(typeof row.installed, "boolean");
    assert.equal(typeof row.enabled, "boolean");
    assert.ok("last_test" in row, `${row.id} does not say when it was last tested`);
    if (!row.installed) {
      assert.equal(row.path, "", `${row.id} is not installed and can have no path`);
      assert.ok(row.install_hint.length > 0, `${row.id} must say what to run to install it`);
    }
  }
  assert.ok(body.some((row) => row.installed === false), "one engine is not on this machine");
  assert.deepEqual((await get("/api/engines", "empty")).body, []);
});

await okAsync("a service row carries when it changed, what it does and what fixes it", async () => {
  const { body } = await get("/api/services");
  for (const row of body.services) {
    for (const field of ["id", "label", "state", "since", "what", "verb", "fix", "actions"]) {
      assert.ok(field in row, `the ${row.id} service row has no ${field}`);
    }
  }
  const ids = body.services.map((row) => row.id);
  assert.ok(ids.includes("agent_runner"),
    "the agent runner keeps the server's own id, which the header looks it up by");
});

await okAsync("a login row carries the sentence that says what to do about it", async () => {
  const { body } = await get("/api/accounts/login-state");
  const states = new Set(body.accounts.map((row) => row.state));
  for (const row of body.accounts) {
    assert.ok(["logged_in", "waiting_for_login", "expired", "rate_limited", "unknown"]
      .includes(row.state), `${row.name} is in the state ${row.state}`);
    assert.ok(row.sentence.length > 0, `${row.name} carries no sentence`);
  }
  assert.ok(states.has("waiting_for_login"), "one account has never been logged in");
  assert.ok(states.has("unknown"), "one login cannot be read at all");
});

await okAsync("removing a project answers with the block it frees", async () => {
  const answer = await fetch(`${BASE}/api/projects/remove`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: "sandbox" }),
  });
  const body = await answer.json();
  assert.equal(answer.status, 200);
  assert.equal(typeof body.freed, "string");
  assert.ok(body.freed.length > 0, "the answer names the block that is now free");
  assert.ok(body.sentence.includes(body.freed), "and says it in a sentence");
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
  // Registering clones the repository, so the answer is a job, not the row.
  assert.equal(project.status, 202);
  assert.equal(project.body.job.action, "add_project");
  assert.ok(project.body.job.id);
  const job = await get(`/api/jobs/${project.body.job.id}`);
  assert.equal(job.body.action, "add_project");
  assert.equal(typeof (await send("/api/projects", { name: "" })).body.error, "string");
});

await okAsync("the state flag flips the whole dataset", async () => {
  assert.equal((await get("/api/fleet", "ready")).body.length > 0, true);
  assert.deepEqual((await get("/api/fleet", "empty")).body, []);
  assert.equal((await get("/api/accounts", "empty")).body.accounts.length, 0);
  assert.deepEqual((await get("/api/models", "empty")).body, []);
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
  const source = read("static/views/board.js");
  assert.ok(!/fable/i.test(source), "no window may be singled out by name in the page");
  assert.ok(!/<svg|base64/i.test(source), "a mark comes from the server, not from a logo in the page");
  assert.match(source, /fmt\.room\(account\)/, "the Board asks the shared rule whether an account has room");
  assert.match(read("static/core/fmt.js"), /Out of room/, "a subscription with nothing left does not say so");
});

await okAsync("the quiet farm carries what a busy farm shows and no other state does", async () => {
  const lanes = (await get("/api/fleet", "quiet")).body;
  assert.ok(lanes.some((row) => String(row.slug).length > 48), "a lane name wider than a card");
  const names = (await get("/api/mail/boxes", "quiet")).body.boxes.map((row) => row.name);
  assert.ok(names.length > new Set(names).size, "an office holding one name twice");
});

stub.kill();
console.log(`\nRESULT: ${passed} checks passed`);

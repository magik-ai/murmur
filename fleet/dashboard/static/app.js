/* The page: a hash router, a three second tick, the view registry, and the chrome around
   them (theme, project filter, freshness, capacity, the power setting, the jump palette,
   the favicon). Four tabs, and the addresses the old seven used still work. */

import * as api from "./core/api.js";
import * as identity from "./core/identity.js";
import * as fmt from "./core/fmt.js";
import {
  render, paintDrawer, closeDrawer, openDrawerKey, trapFocus, agentMeaning, h,
  emptyState, toast, POWER_MODES, powerLabel,
} from "./core/ui.js";
import board from "./views/board.js";
import mail from "./views/mail.js";
import queue from "./views/queue.js";

/* The machine tab is written in its own lane, in its own file. Until that file is on the
   farm the tab is here and says so, rather than taking the whole page down with a failed
   import: a missing module in a static import list is a blank screen, not a missing tab. */
const machineSoon = {
  id: "machine",
  title: "Machine",
  needs: [],
  render: () => emptyState({
    title: "The machine controls are coming from the machine lane",
    body: "Power, services, accounts, models and projects live here. "
      + "Until that file is installed, use the command line for them.",
    command: "fleet status",
  }),
};

let VIEWS = [board, mail, queue, machineSoon];
const BY_ID = new Map(VIEWS.map((view) => [view.id, view]));
/* Asked for on every tab: the page cannot draw its chrome without them, and the jump
   palette can only offer a conversation it has heard of. */
const ALWAYS = ["/api/config", "/api/access", "/api/identities", "/api/health",
  "/api/metrics", "/api/mode", "/api/mail/boxes", "/api/version", "/api/sweep"];
const TICK = 3000;

/* An address the old seven tabs answered on, and where that reader is taken now. A bookmark
   from yesterday must land on the thing it named, not on a blank page. */
const REDIRECTS = {
  overview: ["board", null],
  agents: ["board", null],
  projects: ["machine", "projects"],
  accounts: ["machine", "accounts"],
  system: ["machine", null],
};

const ICONS = {
  board: '<path d="M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z" fill="currentColor"/>',
  mail: '<path d="M3 5h18v14H3zM3 6l9 7 9-7" fill="none" stroke="currentColor" stroke-width="2"/>',
  queue: '<path d="M4 6h16M4 12h16M4 18h10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  machine: '<path d="M6 6h12v12H6z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" stroke="currentColor" stroke-width="2"/>',
};

/* The three theme settings, in the order the one control walks through them, each with the
   picture it shows: a half filled circle for following the system, a sun, and a moon. */
const THEMES = [
  ["system", "system", '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 4a8 8 0 010 16z" fill="currentColor"/>'],
  ["light", "light", '<circle cx="12" cy="12" r="4.5" fill="currentColor"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'],
  ["dark", "dark", '<path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z" fill="currentColor"/>'],
];

const state = {
  view: "board",
  params: new URLSearchParams(),
  project: "",
  extra: new Set(),
  powerBusy: "",
};

/* ---------------------------------------------------------- the context */

const context = {
  get config() {
    return api.resource("/api/config").data || { title: "murmur", features: {} };
  },
  get features() {
    return (context.config && context.config.features) || {};
  },
  get access() {
    return api.access;
  },
  get project() {
    return state.project;
  },
  get params() {
    return state.params;
  },
  /* The tab on screen, so work a view started on its own clock can stop once the reader leaves. */
  get view() {
    return state.view;
  },
  res: (path) => api.resource(path),
  watch(path) {
    if (!state.extra.has(path)) {
      state.extra.add(path);
      api.pull([path]).then((done) => {
        if (done.length) paint();
      });
    }
    return api.resource(path);
  },
  drop(path) {
    state.extra.delete(path);
    api.forget(path);
  },
  go,
  paint,
  identity,
  async refresh(path) {
    await api.refresh(path);
    paint();
  },
};

/* ---------------------------------------------------------- the router */

function parseHash() {
  const raw = (location.hash || "#/board").replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const id = path.split("/")[0] || "board";
  const params = new URLSearchParams(query);
  const moved = REDIRECTS[id];
  if (moved) {
    const [view, section] = moved;
    if (section) params.set("section", section);
    return { view, params, moved: true };
  }
  return { view: BY_ID.has(id) ? id : "board", params, moved: false };
}

export function go(view, params) {
  const query = params ? new URLSearchParams(params).toString() : "";
  location.hash = `#/${view}${query ? `?${query}` : ""}`;
}

function onRoute() {
  const next = parseHash();
  if (next.moved) {
    // The address bar is rewritten in place, so a bookmark saved from here is the new one and
    // the back button does not walk the reader through a redirect they never asked for.
    const query = next.params.toString();
    history.replaceState(null, "", `${location.pathname}${location.search}#/${next.view}${query ? `?${query}` : ""}`);
  }
  if (next.view !== state.view) {
    state.extra.clear();
    closeDrawer();
    window.scrollTo(0, 0);
  }
  state.view = next.view;
  state.params = next.params;
  paintChrome();
  paint();
  tick(true);
}

function currentView() {
  return BY_ID.get(state.view) || VIEWS[0];
}

function currentPaths() {
  const view = currentView();
  const needs = typeof view.needs === "function" ? view.needs(context) : view.needs || [];
  return [...ALWAYS, ...needs, ...state.extra];
}

/* ------------------------------------------------------------ the tick */

let timer = null;

async function tick(force = false) {
  if (document.hidden && !force) return;
  await api.pull(currentPaths(), force);
  const config = api.resource("/api/config").data;
  if (config && config.title) {
    document.getElementById("productTitle").textContent = config.title;
    document.getElementById("sidebarTitle").textContent = config.title;
    document.title = config.title;
  }
  const accessData = api.resource("/api/access").data;
  if (accessData) {
    api.access.writable = accessData.writable !== false;
    api.access.reason = accessData.reason || "";
    api.access.loopback = accessData.loopback !== false;
    api.access.checked = true;
    document.body.classList.toggle("readonly", !api.access.writable);
  }
  const ids = api.resource("/api/identities").data;
  if (ids) identity.setRegistry(ids);
  paintChrome();
  paint();
}

export function paint() {
  const view = currentView();
  document.getElementById("viewTitle").textContent = view.title;
  // One tab holds itself to the window and scrolls inside its own panes. The page may not
  // scroll under it, or the fixed panes slide away from their header.
  document.body.classList.toggle("fixed-page", Boolean(view.fixed));
  /* The tab's own content is keyed, so a note that appears above it (an update, read-only) never
     moves it to a new position and rebuilds it: a rebuilt Mail tab lost a half-typed message. */
  const body = [].concat(view.render(context));
  body.forEach((node, index) => {
    if (node && node.props && node.props.key == null) node.props.key = `view-${view.id}-${index}`;
  });
  render(document.getElementById("view"), [newBuildNote(), readOnlyNote(), ...body]);
  paintDrawer();
}

/* The build this tab was loaded from. A tab left open across a deploy keeps running the old code
   against the new data, which looks exactly like a fix that never shipped (owner, 2026-09-23: the
   Board "lost" its Fable limits in a tab opened before the deploy that added them). */
let loadedBuild = "";

function newBuildNote() {
  const version = api.resource("/api/version").data;
  const current = version && version.v ? String(version.v) : "";
  if (!loadedBuild) {
    loadedBuild = current;
    return null;
  }
  if (!current || current === loadedBuild) return null;
  return h("div", { class: "banner warn update-strip", key: "update", role: "status" },
    h("span", null, "This dashboard was updated after this tab was opened. Reload it to see the new version."),
    h("button", { type: "button", class: "button small primary", onclick: () => location.reload() }, "Reload"));
}

/* A dashboard with no write token is a legitimate way to run this, and it must not look
   broken: every control that writes is drawn switched off, and this one line, on every tab,
   says why in the server's own words rather than leaving the reader to guess. */
function readOnlyNote() {
  if (api.access.writable) return null;
  return h("p", { class: "banner readonly-strip", key: "readonly" },
    api.access.reason || "This dashboard is read-only, so nothing on it can be changed from here.");
}

/* ----------------------------------------------------------- the chrome */

function paintChrome() {
  paintNav();
  paintFreshness();
  paintSweep();
  paintCapacity();
  paintPower();
  paintProjects();
  paintFavicon();
  const version = api.resource("/api/version").data;
  const label = document.getElementById("versionLabel");
  if (label && version) label.textContent = `build ${version.v}`;
}

function paintNav() {
  const host = document.getElementById("navlinks");
  render(host, VIEWS.map((view) => h("a", {
    key: view.id,
    class: "navlink",
    href: `#/${view.id}`,
    "aria-current": view.id === state.view ? "page" : null,
  },
    { tag: "svg", props: { viewBox: "0 0 24 24", "aria-hidden": "true", __svg: ICONS[view.id] }, children: [] },
    h("span", { class: "label" }, view.title),
    badgeFor(view))));
}

function badgeFor(view) {
  if (typeof view.badge !== "function") return null;
  const value = view.badge(context);
  return value ? h("span", { class: "count" }, String(value)) : null;
}

/* A moment, however the answer wrote it: seconds since the epoch, or a stamp in ISO. */
function clockTime(value) {
  const when = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(when.getTime()) ? String(value) : when.toLocaleTimeString("en-US");
}

/* Live means two things at once: this page's own requests are working AND nothing on screen is
   a kept copy of an older reading. Saying Live over a panel that says the office last answered
   a minute ago is the header contradicting the page under it. */
function paintFreshness() {
  const node = document.getElementById("freshness");
  if (!node) return;
  const paths = currentPaths();
  const at = api.oldestAt(paths);
  const failing = api.anyFailing(paths);
  const stale = api.staleSnapshots(paths);
  if (failing) {
    node.textContent = `Stale since ${at == null ? "not yet" : clockTime(at)}`;
    node.title = "A request from this page is failing, so what you see is the last answer.";
  } else if (stale.length) {
    const oldest = stale.reduce((one, other) => (new Date(other.since) < new Date(one.since) ? other : one));
    node.textContent = `Stale since ${clockTime(oldest.since)}`;
    node.title = stale
      .map((row) => `${row.path}: last good answer at ${clockTime(row.since)}${row.reason ? `, ${row.reason}` : ""}`)
      .join("\n");
  } else {
    /* Fresh is the normal case and says nothing: the header only speaks when something on the
       page is an old answer. */
    node.textContent = "";
    node.title = `Every panel on this screen is showing a fresh answer, as of ${at == null ? "not yet" : clockTime(at)}.`;
  }
  node.classList.toggle("stale", failing || stale.length > 0);
  node.hidden = !(failing || stale.length > 0);
}

/* The sweep's countdown is one short line in the header, where the owner's first dashboard
   kept it: it looks after the whole machine, so it belongs on every tab, not on a Board tile. */
function paintSweep() {
  const node = document.getElementById("sweepNote");
  if (!node) return;
  const data = api.resource("/api/sweep").data;
  node.hidden = !data;
  if (!data) return;
  const failed = Boolean(data.enabled && data.result && data.result !== "success");
  node.classList.toggle("bad", failed);
  if (!data.enabled) {
    node.textContent = "Sweep off";
    node.title = "Dead worktrees are never cleared away on their own here.";
  } else {
    // Whole minutes: a header line that ticks every few seconds is movement nobody asked for.
    const next = data.secs_left == null ? "scheduled"
      : `in ${fmt.duration(Math.max(60, Math.round(data.secs_left / 60) * 60))}`;
    /* A failed sweep says so in words: colour alone is not a warning anybody can read. */
    node.textContent = failed ? "Sweep failed" : `Sweep ${next}`;
    node.title = failed
      ? `The last sweep ended with: ${data.result}. The next one runs ${next}.`
      : "The sweep clears dead worktrees and finished cards on a timer.";
  }
}

function paintCapacity() {
  const node = document.getElementById("capacity");
  if (!node) return;
  const metrics = api.resource("/api/metrics").data;
  if (!metrics) {
    node.className = "pill pause";
    node.querySelector(".pill-text").textContent = "capacity";
    node.title = "The machine has not answered yet.";
    return;
  }
  const blocks = metrics.block_reasons || [];
  const warnings = metrics.warnings || [];
  /* "No room", not "Full": the power setting next to this pill has a setting called Full,
     and two Fulls in one header that mean opposite things is a header nobody can read. */
  const word = metrics.can_spawn === false ? "No room" : warnings.length ? "Tight" : "Ready";
  const meaning = metrics.can_spawn === false ? "fail" : warnings.length ? "wait" : "done";
  node.className = `pill ${meaning}`;
  node.querySelector(".pill-text").textContent = word;
  node.title = [...blocks, ...warnings].join("\n") || "There is room for another agent.";
}

/* The power setting is a control, not a word: the reader changes it from the header of every
   tab. It is only drawn on a machine that has a slice to cap with, because a switch that
   cannot do anything is worse than no switch. */
function paintPower() {
  const field = document.getElementById("powerField");
  const pick = document.getElementById("powerPick");
  if (!field || !pick) return;
  const mode = api.resource("/api/mode").data;
  field.hidden = !context.features.slice || !mode;
  if (!field.hidden) paintPowerPick(pick, mode);
}

/* The five settings are a select, the same field as the project filter beside it: five
   buttons on a sunk track were the widest and the odd one out in the header (owner audit,
   2026-09-24), and on a phone they did not fit at all. */
function paintPowerPick(pick, mode) {
  const allowed = api.access.writable;
  pick.disabled = !allowed || Boolean(state.powerBusy);
  pick.title = allowed
    ? (mode.setting === "auto" ? `Automatic, the agents are on ${powerLabel(mode.effective)} now.`
      : `The agents are on ${powerLabel(mode.setting)}.`)
    : api.access.reason || "This dashboard is read-only.";
  render(pick, POWER_MODES.map(([id, label]) => h("option", {
    key: id, value: id, selected: mode.setting === id,
  }, mode.setting === "auto" && id === "auto" ? `Automatic (${powerLabel(mode.effective)})` : label)));
  pick.value = mode.setting;
  if (!pick.__wired) {
    pick.__wired = true;
    pick.addEventListener("change", () => {
      const found = POWER_MODES.find((row) => row[0] === pick.value);
      if (found) setPower(found[0], found[1]);
    });
  }
}

async function setPower(id, label) {
  state.powerBusy = id;
  paintPower();
  try {
    await api.apiPost("/api/mode", { mode: id });
    toast(`The agents are on ${label}.`);
  } catch (error) {
    toast(api.serverReason(error) || "The power setting was not changed.", "bad");
  } finally {
    state.powerBusy = "";
    await api.refresh("/api/mode");
    paintChrome();
    paint();
  }
}

function paintProjects() {
  const select = document.getElementById("projectFilter");
  if (!select) return;
  const listed = api.list(api.resource("/api/projects").data).map((row) => row.name).filter(Boolean);
  const seen = api.list(api.resource("/api/fleet").data).map((row) => row.project).filter(Boolean);
  const options = ["", ...new Set([...listed, ...seen])].sort();
  if (select.__options !== options.join("|")) {
    select.__options = options.join("|");
    select.textContent = "";
    for (const value of options) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value || "All";
      select.append(option);
    }
  }
  if (select.value !== state.project) select.value = state.project;
}

/* The favicon mirrors the worst thing on the page, so a background tab still says it. */
function paintFavicon() {
  const worst = worstMeaning();
  const link = document.getElementById("favicon");
  if (!link || link.__meaning === worst) return;
  link.__meaning = worst;
  const colour = getComputedStyle(document.documentElement)
    .getPropertyValue(`--tone-${worst}`).trim() || "#888888";
  const markup = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">' +
    `<rect width="32" height="32" rx="8" fill="${colour}"/></svg>`;
  link.href = `data:image/svg+xml,${encodeURIComponent(markup)}`;
}

function worstMeaning() {
  const agentRows = api.list(api.resource("/api/fleet").data);
  const health = api.list((api.resource("/api/health").data || {}).checks);
  const queueRows = api.resource("/api/ci").data || {};
  const meanings = new Set();
  for (const row of agentRows) meanings.add(agentMeaning(row.status));
  for (const check of health) {
    if (check.state === "error") meanings.add("fail");
    if (check.state === "missing") meanings.add("wait");
  }
  for (const row of api.list(queueRows.recent)) {
    if (row.state === "failed" || row.state === "conflict") meanings.add("fail");
  }
  if (meanings.has("fail")) return "fail";
  if (meanings.has("wait")) return "wait";
  if (meanings.has("run")) return "run";
  if (meanings.has("done")) return "done";
  return "pause";
}

/* ------------------------------------------------------------ the theme */

function applyTheme(choice) {
  if (choice === "light" || choice === "dark") {
    document.documentElement.setAttribute("data-theme", choice);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  try {
    localStorage.setItem("murmur.theme", choice);
  } catch (error) { /* storage off: the choice lasts for this page only */ }
  const button = document.getElementById("themeSwitch");
  const found = THEMES.find((row) => row[0] === choice) || THEMES[0];
  if (button) {
    button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${found[2]}</svg>`;
    button.setAttribute("aria-label", `Theme: ${found[1]}. Change it.`);
    button.dataset.theme = found[0];
  }
  const link = document.getElementById("favicon");
  if (link) link.__meaning = null;
  paintFavicon();
}

function storedTheme() {
  try {
    return localStorage.getItem("murmur.theme") || "system";
  } catch (error) {
    return "system";
  }
}

/* --------------------------------------------------------- the palette */

/* What the palette needs to be able to offer everything, whichever tab is open. Half the tabs
   never read the lanes or the conversations, and the palette used to offer only what the open
   tab had already asked for: from the Machine tab, typing a lane name found nothing at all.
   These go through the same cache as every other read, so opening the palette on the Board
   costs nothing and opening it on Machine costs one pass. */
const PALETTE_PATHS = ["/api/fleet", "/api/projects", "/api/mail/boxes"];

/* Everything a reader might want to jump to. A row with no name is not offered: it cannot be
   typed for, and a nameless entry used to stop the list dead on the first keystroke. */
function paletteItems() {
  const items = VIEWS.map((view) => ({ label: view.title, where: "Tab", go: () => go(view.id) }));
  for (const row of api.list(api.resource("/api/fleet").data)) {
    items.push({
      label: row.slug,
      where: `Agent, ${row.project || "no project"}`,
      go: () => go("board", { agent: row.slug }),
    });
  }
  for (const row of api.list(api.resource("/api/projects").data)) {
    items.push({
      label: row.name,
      where: "Project",
      go: () => go("machine", { section: "projects", project: row.name }),
    });
  }
  const boxes = api.resource("/api/mail/boxes").data;
  // One name is one conversation, however many the office holds under it.
  const offered = new Set();
  for (const box of api.list(boxes && boxes.boxes)) {
    if (offered.has(box.name)) continue;
    offered.add(box.name);
    items.push({
      label: box.name === "all" ? "Everyone" : box.name,
      where: "Conversation",
      go: () => go("mail", { to: box.name }),
    });
  }
  return items.filter((item) => typeof item.label === "string" && item.label.trim() !== "");
}

let paletteIndex = 0;

function paintPalette() {
  const input = document.getElementById("paletteInput");
  const list = document.getElementById("paletteList");
  const needle = input.value.trim().toLowerCase();
  const matches = paletteItems()
    .filter((item) => !needle || item.label.toLowerCase().includes(needle))
    .slice(0, 40);
  paletteIndex = Math.min(paletteIndex, Math.max(0, matches.length - 1));
  list.__matches = matches;
  const input2 = input;
  input2.setAttribute("aria-activedescendant", matches.length ? `palette-option-${paletteIndex}` : "");
  render(list, matches.map((item, index) => h("li", {
    key: `${item.where}:${item.label}`,
    id: `palette-option-${index}`,
    role: "option",
    "aria-selected": String(index === paletteIndex),
    onclick: () => {
      item.go();
      togglePalette(false);
    },
  }, h("span", null, item.label), h("span", { class: "where" }, item.where))));
}

function togglePalette(open) {
  const host = document.getElementById("palette");
  host.hidden = !open;
  if (open) {
    paletteIndex = 0;
    const input = document.getElementById("paletteInput");
    input.value = "";
    paintPalette();
    input.focus();
    // Read what this tab never asked for, then draw the list again with it in.
    api.pull(PALETTE_PATHS).then((done) => {
      if (done.length && !document.getElementById("palette").hidden) paintPalette();
    });
  }
}

/* ------------------------------------------------------------- wiring */

function wire() {
  window.addEventListener("hashchange", onRoute);
  document.getElementById("projectFilter").addEventListener("change", (event) => {
    state.project = event.target.value;
    try {
      localStorage.setItem("murmur.project", state.project);
    } catch (error) { /* the filter simply does not survive a reload */ }
    paint();
  });
  document.getElementById("themeSwitch").addEventListener("click", () => {
    const at = THEMES.findIndex((row) => row[0] === storedTheme());
    applyTheme(THEMES[(at + 1) % THEMES.length][0]);
  });
  document.getElementById("drawerClose").addEventListener("click", () => {
    closeDrawer();
    paint();
  });
  document.getElementById("drawerScrim").addEventListener("click", () => {
    closeDrawer();
    paint();
  });
  document.getElementById("paletteOpen").addEventListener("click", () => togglePalette(true));
  document.getElementById("palette").addEventListener("click", (event) => {
    if (event.target.id === "palette") togglePalette(false);
  });
  document.getElementById("paletteInput").addEventListener("input", () => {
    paletteIndex = 0;
    paintPalette();
  });
  document.addEventListener("keydown", (event) => {
    const palette = document.getElementById("palette");
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      togglePalette(palette.hidden);
      return;
    }
    if (palette.hidden) {
      if (event.key === "Escape" && openDrawerKey()) {
        closeDrawer();
        paint();
        return;
      }
      if (openDrawerKey()) trapFocus(document.getElementById("drawer"), event);
      return;
    }
    trapFocus(document.getElementById("palette"), event);
    const matches = document.getElementById("paletteList").__matches || [];
    if (event.key === "Escape") togglePalette(false);
    if (event.key === "ArrowDown") {
      paletteIndex = Math.min(paletteIndex + 1, matches.length - 1);
      paintPalette();
      event.preventDefault();
    }
    if (event.key === "ArrowUp") {
      paletteIndex = Math.max(paletteIndex - 1, 0);
      paintPalette();
      event.preventDefault();
    }
    if (event.key === "Enter" && matches[paletteIndex]) {
      matches[paletteIndex].go();
      togglePalette(false);
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tick(true);
  });
}

/* The machine tab, once its lane has installed its file. A tab that is not there yet is a
   tab that says so; it is never a reason for the other three not to draw. */
async function adoptMachine() {
  try {
    const module = await import("./views/machine.js");
    const view = module && module.default;
    if (!view || view.id !== "machine" || typeof view.render !== "function") return;
    VIEWS = VIEWS.map((entry) => (entry.id === "machine" ? view : entry));
    BY_ID.set("machine", view);
    paintChrome();
    paint();
  } catch (error) { /* the placeholder above stays, and the other tabs are untouched */ }
}

function boot() {
  applyTheme(storedTheme());
  try {
    state.project = localStorage.getItem("murmur.project") || "";
  } catch (error) { /* no stored filter, show every project */ }
  wire();
  api.pull(["/api/version"]);
  onRoute();
  timer = setInterval(tick, TICK);
  adoptMachine();
}

boot();
export { context, VIEWS, timer };

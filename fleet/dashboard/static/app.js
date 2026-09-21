/* The page: a hash router, a three second tick, the view registry, and the chrome around
   them (theme, project filter, freshness, capacity, the jump palette, the favicon). */

import * as api from "./core/api.js";
import * as identity from "./core/identity.js";
import { render, paintDrawer, closeDrawer, openDrawerKey, trapFocus, agentMeaning, h } from "./core/ui.js";
import overview from "./views/overview.js";
import agents from "./views/agents.js";
import mail from "./views/mail.js";
import queue from "./views/queue.js";
import projects from "./views/projects.js";
import accounts from "./views/accounts.js";
import system from "./views/system.js";

const VIEWS = [overview, agents, mail, queue, projects, accounts, system];
const BY_ID = new Map(VIEWS.map((view) => [view.id, view]));
/* Asked for on every tab: the page cannot draw its chrome without them, and the jump
   palette can only offer a mailbox it has heard of. */
const ALWAYS = ["/api/config", "/api/access", "/api/identities", "/api/health",
  "/api/metrics", "/api/mail/boxes"];
const TICK = 3000;

const ICONS = {
  overview: '<path d="M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z" fill="currentColor"/>',
  agents: '<path d="M12 12a4 4 0 100-8 4 4 0 000 8zm-8 9a8 8 0 0116 0z" fill="currentColor"/>',
  mail: '<path d="M3 5h18v14H3zM3 6l9 7 9-7" fill="none" stroke="currentColor" stroke-width="2"/>',
  queue: '<path d="M4 6h16M4 12h16M4 18h10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  projects: '<path d="M3 7h6l2 2h10v10H3z" fill="none" stroke="currentColor" stroke-width="2"/>',
  accounts: '<path d="M3 6h18v12H3zM3 10h18" fill="none" stroke="currentColor" stroke-width="2"/>',
  system: '<path d="M6 6h12v12H6z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" stroke="currentColor" stroke-width="2"/>',
};

/* The three theme settings, in the order the one control walks through them, each with the
   picture it shows: a half filled circle for following the system, a sun, and a moon. */
const THEMES = [
  ["system", "system", '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 4a8 8 0 010 16z" fill="currentColor"/>'],
  ["light", "light", '<circle cx="12" cy="12" r="4.5" fill="currentColor"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'],
  ["dark", "dark", '<path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z" fill="currentColor"/>'],
];

const state = {
  view: "overview",
  params: new URLSearchParams(),
  project: "",
  extra: new Set(),
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
  const raw = (location.hash || "#/overview").replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const id = path.split("/")[0] || "overview";
  return { view: BY_ID.has(id) ? id : "overview", params: new URLSearchParams(query) };
}

export function go(view, params) {
  const query = params ? new URLSearchParams(params).toString() : "";
  location.hash = `#/${view}${query ? `?${query}` : ""}`;
}

function onRoute() {
  const next = parseHash();
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
  render(document.getElementById("view"), view.render(context));
  paintDrawer();
}

/* ----------------------------------------------------------- the chrome */

function paintChrome() {
  paintNav();
  paintFreshness();
  paintCapacity();
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
    node.textContent = `Live, as of ${at == null ? "not yet" : clockTime(at)}`;
    node.title = "Every panel on this screen is showing a fresh answer.";
  }
  node.classList.toggle("stale", failing || stale.length > 0);
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
  const word = metrics.can_spawn === false ? "Full" : warnings.length ? "Tight" : "Ready";
  const meaning = metrics.can_spawn === false ? "fail" : warnings.length ? "wait" : "done";
  node.className = `pill ${meaning}`;
  node.querySelector(".pill-text").textContent = word;
  node.title = [...blocks, ...warnings].join("\n") || "There is room for another agent.";
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
      option.textContent = value || "All projects";
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
   never read the lanes or the mailboxes, and the palette used to offer only what the open tab
   had already asked for: from System, typing a lane name found nothing at all. These go
   through the same cache as every other read, so opening the palette on the agents tab costs
   nothing and opening it on System costs one pass. */
const PALETTE_PATHS = ["/api/fleet", "/api/projects", "/api/mail/boxes"];

/* Everything a reader might want to jump to. A row with no name is not offered: it cannot be
   typed for, and a nameless entry used to stop the list dead on the first keystroke. */
function paletteItems() {
  const items = VIEWS.map((view) => ({ label: view.title, where: "Tab", go: () => go(view.id) }));
  for (const row of api.list(api.resource("/api/fleet").data)) {
    items.push({
      label: row.slug,
      where: `Agent, ${row.project || "no project"}`,
      go: () => go("agents", { agent: row.slug }),
    });
  }
  for (const row of api.list(api.resource("/api/projects").data)) {
    items.push({ label: row.name, where: "Project", go: () => go("projects", { project: row.name }) });
  }
  const boxes = api.resource("/api/mail/boxes").data;
  for (const box of api.list(boxes && boxes.boxes)) {
    items.push({ label: box.name, where: "Mailbox", go: () => go("mail", { box: box.name }) });
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

function boot() {
  applyTheme(storedTheme());
  try {
    state.project = localStorage.getItem("murmur.project") || "";
  } catch (error) { /* no stored filter, show every project */ }
  wire();
  api.pull(["/api/version"]);
  onRoute();
  timer = setInterval(tick, TICK);
}

boot();
export { context, VIEWS, timer };

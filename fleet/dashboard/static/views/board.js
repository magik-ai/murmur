/* The Board: the one screen an operator keeps open all day. It answers three questions
   without a terminal, in this order: is anything unfinished about the setup, is the machine
   and the subscription healthy, and who is working on what.
   Nothing else belongs here, and nothing here is a summary of a summary. */

import {
  h, card, panel, pill, emptyState, skeletonStack, widthStyle, agentMeaning, engineMark,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { list } from "../core/api.js";
import { agentsPane, spawnCommand } from "./agents.js";


const local = {};


/* ------------------------------------------------- finishing the setup */

function checks(health) {
  return list(health && health.checks);
}

function unfinished(health) {
  return checks(health).filter((check) => check.state === "missing" || check.state === "error");
}

/* The checklist has no dismiss button on purpose: the only way to put it away is to fix what
   it names. A farm with a missing prerequisite is a farm that will surprise its owner later. */
function setupChecklist(health) {
  const open = unfinished(health);
  return card({ class: "card-pad", key: "setup" },
    h("div", { class: "section-head" },
      h("h2", null, "Finish setting up"),
      h("div", { class: "spacer" }),
      h("span", { class: "muted" }, `${open.length} of ${checks(health).length} still open`)),
    h("ul", { class: "checklist" }, open.map((check) => h("li", { key: check.id },
      h("span", { class: `mark-state ${check.state}` }),
      h("div", null,
        h("div", { class: "title" }, check.label),
        check.detail ? h("div", { class: "detail" }, check.detail) : null,
        check.fix ? h("code", { class: "cmd" }, check.fix) : null)))));
}

/* A farm that has never run a lane gets the whole page as a checklist, because there is
   nothing else true to put on it. The spawn command carries a real project name. */
function emptyFarm(context) {
  const health = context.res("/api/health").data;
  const projects = list(context.res("/api/projects").data);
  const commands = [
    projects.length ? null : "fleet add-project --name <project> --repo <owner>/<repo>",
    spawnCommand(context),
    "fleet status",
  ].filter(Boolean);
  return [
    checks(health).length && unfinished(health).length ? setupChecklist(health) : null,
    card({ class: "card-pad", key: "first" },
      h("h2", null, "No agent has ever run here"),
      h("p", { class: "muted" },
        "An agent is one lane of work on one branch. These commands produce the first one, "
        + "and it appears on this page as soon as it starts."),
      h("div", { class: "stack" },
        commands.map((command, index) => h("code", { class: "cmd", key: `cmd${index}` }, command)))),
  ];
}

/* ------------------------------------------------------ the machine strip */

/* A tile says three things: what it measures, the number, and one line about the number. The
   pill is for the tiles whose state is not readable from the number itself: a sensor that is
   silent reads the same as a sensor at zero unless the tile says which it is. */
function tile(label, value, note, state, key) {
  /* Every tile has the same three rows in the same places: label at the top, value under it,
     note pinned to the bottom. A long note is cut with an ellipsis and carried in full in its
     title, so a long path or a long sensor name never makes one tile taller than its row. */
  /* The state pill sits in the note row, never beside the label: beside it, a pill squeezed
     "Temperature" into "Temper..." on the reference farm. */
  return card({ class: "card-pad tile", key: key || label },
    h("div", { class: "label" }, h("span", { class: "label-text" }, label)),
    h("div", { class: "value", "data-flash": "", title: value }, value),
    h("div", { class: "muted note", title: note || "" },
      state ? pill(state[0], state[1], note || "") : null,
      h("span", { class: "note-text" }, note || "\u00a0")));
}

/* "of 512 GB" when the total is known, else the last part of the path the reading is for. */
function diskNote(path, total) {
  if (Number.isFinite(total)) return `of ${fmt.gigabytes(total)}`;
  const parts = String(path || "").split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
}

function gpuTile(context, metrics) {
  if (!context.features.gpu) {
    return tile("Graphics card", "Not configured",
      "Power mode has no signal from it and stays on full.", null);
  }
  if (!metrics.gpu) {
    return tile("Graphics card", "No answer",
      "The sensor is configured but returned nothing on the last read.", null);
  }
  /* A card that reports 0 degrees has not reported a temperature (a card resting in a power
     saving state can answer 0), and a room is never at freezing: say there is no reading. */
  const temp = Number(metrics.gpu.temp_c);
  return tile("Graphics card", temp > 0 ? `${fmt.decimal(temp, 0)} C` : "No reading",
    `${fmt.percent(metrics.gpu.util_pct)} busy, ${metrics.gpu.name || "unnamed card"}`, null);
}

function heatTile(context, metrics) {
  if (!context.features.cpu_temp) {
    return tile("Temperature", "Not configured",
      "No temperature sensor is enabled here.", null);
  }
  if (metrics.cpu_temp_c == null) {
    return tile("Temperature", "No answer",
      metrics.sensors_unavailable ? "The sensor package is not installed." : "The sensor returned nothing.",
      null);
  }
  return tile("Temperature", `${fmt.decimal(metrics.cpu_temp_c, 0)} C`,
    metrics.cpu_temp_source || "", null);
}

/* Capacity and the sweep are not tiles any more: both are one short line in the header, which
   is on every tab (owner audit 2026-09-23), and a tile here only said the same thing again. */

function machineStrip(context) {
  const resource = context.res("/api/metrics");
  return h("section", { class: "strip machine-strip", key: "machine" },
    panel(resource, {
      loading: () => h("div", { class: "grid tiles strip-tiles" },
        [0, 1, 2, 3].map((index) => card({ class: "card-pad", key: `sk${index}` }, skeletonStack(2)))),
      ready: (metrics) => h("div", { class: "grid tiles strip-tiles" },
        tile("Load", fmt.decimal((metrics.load || {}).load1, 2), `${fmt.num((metrics.load || {}).cores)} cores`),
        tile("Memory free", fmt.gigabytes((metrics.mem || {}).ram_avail_gb),
          `of ${fmt.gigabytes((metrics.mem || {}).ram_total_gb)}`),
        tile("Disk free", fmt.gigabytes((metrics.disk || {}).free_gb),
          diskNote((metrics.disk || {}).path, (metrics.disk || {}).total_gb)),
        gpuTile(context, metrics),
        heatTile(context, metrics)),
    }));
}

/* ----------------------------------------------------- the accounts strip */

/** Every window the server returns, in its order, labelled by its own name. */
function windows(account) {
  const out = [];
  if (account.session != null || account.session_resets) {
    out.push({ name: "session", percent: account.session, resets: account.session_resets });
  }
  if (account.weekly != null || account.weekly_resets) {
    out.push({ name: "weekly", percent: account.weekly, resets: account.weekly_resets });
  }
  for (const scoped of list(account.scoped)) {
    out.push({ name: scoped.label, percent: scoped.percent, resets: scoped.resets });
  }
  return out;
}

function severity(percent) {
  if (percent == null) return "";
  if (percent >= 95) return "bad";
  if (percent >= 70) return "warn";
  return "";
}

/* Every window the account has, the model-scoped ones included: the card used to cut at two
   and hide the one window that was actually spent. */
function accountCard(account, context) {
  const rows = windows(account);
  const state = fmt.room(account);
  const soonest = windows(account)
    .map((row) => row.resets)
    .filter((value) => value != null)
    .sort((one, other) => one - other)[0];
  return h("button", {
    key: account.name,
    type: "button",
    class: `card card-pad account-chip${state && state.meaning === "fail" ? " out" : ""}`,
    "data-account": account.name,
    title: `${account.email || account.label || account.name}, folder ${account.name}. `
      + "Open this subscription on the Machine tab",
    onclick: () => context.go("machine", { section: "accounts", account: account.name }),
  },
    /* The engine rides in the top right corner as its vendor's mark, where the first farm page
       drew it (owner, 2026-09-24); an engine without a mark stays a word. */
    h("div", { class: "label" },
      h("b", null, account.label || account.name),
      h("div", { class: "spacer" }),
      state ? pill(state.meaning, state.word, "") : null,
      engineMark(account.engine) || (account.engine ? h("span", { class: "tag" }, account.engine) : null)),
    rows.length
      ? h("div", { class: "limits" }, rows.map((row) => h("div", { class: "limit", key: row.name },
        h("span", { class: "lname", title: row.name }, row.name),
        h("span", { class: `bar ${severity(row.percent) === "bad" ? "fail" : severity(row.percent) === "warn" ? "wait" : ""}`.trim() },
          h("i", { style: widthStyle(row.percent) })),
        h("span", { class: `lpct ${severity(row.percent)}`.trim(), "data-flash": "" },
          fmt.percent(row.percent)))))
      : h("p", { class: "muted" }, "No numbers yet"),
    h("div", { class: "foot" },
      soonest ? h("span", null, `resets ${fmt.until(soonest)}`) : null,
      account.stale_error ? h("span", null, "not refreshing") : null));
}

function accountsStrip(context) {
  const resource = context.res("/api/accounts");
  return h("section", { class: "strip", key: "accounts" },
    panel(resource, {
      loading: () => h("div", { class: "grid accounts-row" },
        [0, 1].map((index) => card({ class: "card-pad", key: `ska${index}` }, skeletonStack(2)))),
      isEmpty: (data) => !list(data.accounts).length,
      empty: () => emptyState({
        title: "No subscription is registered",
        body: "An account is the subscription an agent spends while it works.",
        command: "fleet accounts add <name>",
      }),
      ready: (data) => h("div", { class: "grid accounts-row" },
        list(data.accounts).map((account) => accountCard(account, context))),
    }));
}

/* ---------------------------------------------------------- the canvas */

/* The Board is the agents, at full width, under the two strips. */
function canvas(context) {
  return h("div", { class: "board-canvas", key: "canvas" }, agentsPane(context));
}

/* ---------------------------------------------------------------- view */

export default {
  id: "board",
  title: "Board",
  needs: ["/api/fleet", "/api/projects", "/api/metrics", "/api/accounts"],
  badge(context) {
    const rows = list(context.res("/api/fleet").data);
    return rows.filter((row) => agentMeaning(row.status) === "run").length || "";
  },
  render(context) {
    const fleet = context.res("/api/fleet");
    const health = context.res("/api/health").data;
    // An empty farm and a farm that will not answer look the same in a length, and they are
    // not the same thing: only a real empty list means nobody has ever run a lane here.
    if (fleet.everLoaded && Array.isArray(fleet.data) && fleet.data.length === 0) {
      return emptyFarm(context);
    }
    return [
      unfinished(health).length ? setupChecklist(health) : null,
      machineStrip(context),
      accountsStrip(context),
      canvas(context),
    ];
  },
};

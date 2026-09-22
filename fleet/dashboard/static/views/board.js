/* The Board: the one screen an operator keeps open all day. It answers three questions
   without a terminal, in this order: is anything unfinished about the setup, is the machine
   and the subscription healthy, and who is working on what while what is being verified.
   Nothing else belongs here, and nothing here is a summary of a summary. */

import {
  h, card, panel, pill, emptyState, skeletonStack, widthStyle, splitStyle, splitPercent,
  SPLIT_MIN, SPLIT_MAX, agentMeaning, queueMeaning, powerLabel,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { list } from "../core/api.js";
import { agentsPane, spawnCommand } from "./agents.js";

const SPLIT_KEY = "murmur.board.split";
const SPLIT_STEP = 2;

const local = { split: readSplit(), dragging: false };

function readSplit() {
  try {
    return splitPercent(localStorage.getItem(SPLIT_KEY));
  } catch (error) {
    return splitPercent(null);
  }
}

function writeSplit(value) {
  local.split = splitPercent(value);
  try {
    localStorage.setItem(SPLIT_KEY, String(local.split));
  } catch (error) { /* the pane widths simply start again next time */ }
}

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
  return card({ class: "card-pad tile", key: key || label },
    h("div", { class: "label" }, label, state ? pill(state[0], state[1], note || "") : null),
    h("div", { class: "value", "data-flash": "" }, value),
    note ? h("div", { class: "muted" }, note) : null);
}

function gpuTile(context, metrics) {
  if (!context.features.gpu) {
    return tile("Graphics card", "Not configured",
      "Power mode has no signal from it and stays on full.", ["pause", "off"]);
  }
  if (!metrics.gpu) {
    return tile("Graphics card", "No answer",
      "The sensor is configured but returned nothing on the last read.", ["fail", "no answer"]);
  }
  return tile("Graphics card", `${fmt.decimal(metrics.gpu.temp_c, 0)} C`,
    `${fmt.percent(metrics.gpu.util_pct)} busy, ${metrics.gpu.name || "unnamed card"}`, null);
}

function heatTile(context, metrics) {
  if (!context.features.cpu_temp) {
    return tile("Temperature", "Not configured",
      "No temperature sensor is enabled here.", ["pause", "off"]);
  }
  if (metrics.cpu_temp_c == null) {
    return tile("Temperature", "No answer",
      metrics.sensors_unavailable ? "The sensor package is not installed." : "The sensor returned nothing.",
      ["fail", "no answer"]);
  }
  return tile("Temperature", `${fmt.decimal(metrics.cpu_temp_c, 0)} C`,
    metrics.cpu_temp_source || "", null);
}

function capacityTile(context, metrics) {
  const blocked = metrics.can_spawn === false;
  const warnings = list(metrics.warnings);
  const note = blocked
    ? list(metrics.block_reasons).join(", ") || "no room for another agent"
    : warnings.join(", ") || "there is room for another agent";
  const mode = context.res("/api/mode").data;
  /* The header pill's word, for the header pill's reason: the power setting a few inches away
     has a setting called Full which means the opposite of this, so this tile never says it. */
  return tile("Capacity",
    blocked ? "No room" : warnings.length ? "Tight" : "Ready",
    mode ? `${note}, power on ${powerLabel(mode.setting === "auto" ? mode.effective : mode.setting)}` : note,
    blocked ? ["fail", "no room"] : warnings.length ? ["wait", "tight"] : null);
}

/* The sweep countdown lives here, next to the machine it looks after, and not in the header
   where it was one more thing to read before the reader got to the agents. */
function sweepTile(context) {
  const resource = context.res("/api/sweep");
  const data = resource.data;
  if (!data) return tile("Sweep", "not known", "waiting for the machine", null, "sweep");
  if (!data.enabled) {
    return tile("Sweep", "Off", "Dead worktrees are never cleared away on their own here.",
      ["pause", "off"], "sweep");
  }
  const failed = Boolean(data.result && data.result !== "success");
  return tile("Sweep",
    data.secs_left == null ? "Scheduled" : `in ${fmt.duration(data.secs_left)}`,
    failed ? `last run: ${data.result}` : "clears dead worktrees",
    failed ? ["fail", "last run failed"] : null, "sweep");
}

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
        tile("Disk free", fmt.gigabytes((metrics.disk || {}).free_gb), (metrics.disk || {}).path || ""),
        gpuTile(context, metrics),
        heatTile(context, metrics),
        capacityTile(context, metrics),
        sweepTile(context)),
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

function outOfRoom(account) {
  if (account.limit_reached) return true;
  return windows(account).some((row) => row.percent != null && row.percent >= 100);
}

function accountCard(account, context) {
  const rows = windows(account).slice(0, 2);
  const soonest = windows(account)
    .map((row) => row.resets)
    .filter((value) => value != null)
    .sort((one, other) => one - other)[0];
  return h("button", {
    key: account.name,
    type: "button",
    class: `card card-pad account-chip${outOfRoom(account) ? " out" : ""}`,
    "data-account": account.name,
    title: "Open this subscription on the Machine tab",
    onclick: () => context.go("machine", { section: "accounts", account: account.name }),
  },
    h("div", { class: "label" },
      h("b", null, account.label || account.name),
      account.engine ? h("span", { class: "tag" }, account.engine) : null,
      h("div", { class: "spacer" }),
      outOfRoom(account) ? pill("fail", "Out of room", "") : null),
    rows.length
      ? h("div", { class: "limits" }, rows.map((row) => h("div", { class: "limit", key: row.name },
        h("span", { class: "lname" }, row.name),
        h("span", { class: `bar ${severity(row.percent) === "bad" ? "fail" : severity(row.percent) === "warn" ? "wait" : ""}`.trim() },
          h("i", { style: widthStyle(row.percent) })),
        h("span", { class: `lpct ${severity(row.percent)}`.trim(), "data-flash": "" },
          fmt.percent(row.percent)))))
      : h("p", { class: "muted" }, "No window has reported a number yet."),
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

/* ------------------------------------------------------------ the queue */

function queueRow(row) {
  const meaning = queueMeaning(row.state);
  const started = row.started || row.enqueued;
  const stages = list(row.tiers);
  return h("div", { class: `queue-row ${meaning}`, key: row.id || `${row.project}-${row.pr}` },
    h("div", { class: "row" },
      h("b", null, `${row.project || "change"}${row.pr ? ` #${row.pr}` : ""}`),
      h("div", { class: "spacer" }),
      pill(meaning, fmt.titleCase(row.state || ""), row.reason || "")),
    h("div", { class: "muted" }, fmt.tail(row.branch || row.repo || "", 42)),
    h("div", { class: "foot" },
      row.position != null ? h("span", null, `position ${row.position}`) : null,
      started ? h("span", { "data-flash": "" }, `started ${fmt.ago(started)}`) : null,
      stages.length ? h("span", null, `${stages.filter((stage) => stage.state === "passed").length} of ${stages.length} stages done`) : null));
}

function queuePane(context) {
  const resource = context.res("/api/ci");
  const project = context.project;
  const pick = (rows) => list(rows).filter((row) => !project || row.project === project);
  return h("section", { class: "pane queue-pane", key: "queue" },
    h("div", { class: "pane-head" },
      h("h2", null, "Being verified"),
      h("div", { class: "spacer" }),
      h("a", { href: "#/queue" }, "Open the queue")),
    h("div", { class: "pane-body" }, panel(resource, {
      loading: () => skeletonStack(3),
      isEmpty: (data) => !pick(data.running).length && !pick(data.queued).length,
      empty: (data) => [
        h("p", { class: "muted", key: "quiet" }, "Nothing is being verified right now."),
        recentLine(pick(data && data.recent).length),
      ],
      ready: (data) => [
        h("div", { class: "queue-rows", key: "rows" },
          pick(data.running).map(queueRow),
          pick(data.queued).map(queueRow)),
        recentLine(pick(data.recent).length),
      ],
    })));
}

function recentLine(count) {
  return h("p", { class: "muted pane-foot", key: "recent" },
    count
      ? h("a", { href: "#/queue" }, `${count} recent ${count === 1 ? "run" : "runs"}`)
      : "No run has finished here yet.");
}

/* ---------------------------------------------------------- the canvas */

function drag(event, context) {
  const canvas = event.currentTarget.parentNode;
  if (!canvas || event.button > 0) return;
  event.preventDefault();
  local.dragging = true;
  const move = (moved) => {
    const box = canvas.getBoundingClientRect();
    if (!box.width) return;
    const wanted = splitPercent(((moved.clientX - box.left) / box.width) * 100);
    local.split = wanted;
    // The drag writes to the node it is dragging, not through a repaint: a repaint per pointer
    // move would rebuild sixty cards a second and the splitter would stutter under the hand.
    canvas.style.setProperty("--split", `${wanted}%`);
  };
  const stop = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    local.dragging = false;
    writeSplit(local.split);
    context.paint();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
}

function nudge(event, context) {
  const step = { ArrowLeft: -SPLIT_STEP, ArrowRight: SPLIT_STEP, Home: -100, End: 100 }[event.key];
  if (step == null) return;
  event.preventDefault();
  writeSplit(local.split + step);
  context.paint();
}

function canvas(context) {
  return h("div", { class: "board-canvas", key: "canvas", style: splitStyle(local.split) },
    agentsPane(context),
    h("div", {
      class: "splitter",
      role: "separator",
      tabindex: "0",
      "aria-orientation": "vertical",
      "aria-label": "How much of the width the agents take",
      "aria-valuenow": String(local.split),
      "aria-valuemin": String(SPLIT_MIN),
      "aria-valuemax": String(SPLIT_MAX),
      onpointerdown: (event) => drag(event, context),
      onkeydown: (event) => nudge(event, context),
    }),
    queuePane(context));
}

/* ---------------------------------------------------------------- view */

export default {
  id: "board",
  title: "Board",
  needs: ["/api/fleet", "/api/projects", "/api/metrics", "/api/accounts", "/api/ci", "/api/sweep"],
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

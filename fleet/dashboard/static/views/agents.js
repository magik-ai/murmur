/* The agents pane of the Board: who is running, on what, and how far. A card grid for
   looking, a table for counting, and a drawer for one lane. The drawer is a drawer and not a
   modal on purpose: the list stays on screen, so the reader never loses the place they came
   from. This file is a pane, not a tab: the Board draws it next to the queue. */

import {
  h, card, panel, pill, emptyState, skeletonStack, agentMeaning, MEANINGS,
  openDrawer, closeDrawer, openDrawerKey, toast, safeHref, activate,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason } from "../core/api.js";
import { mark } from "../core/identity.js";

/* How many lanes are drawn before the reader is asked whether they want the rest. Five hundred
   cards take three seconds to lay out and are then laid out again on every tick. */
const FIRST_SCREENFUL = 60;

const local = {
  mode: readMode(),
  showAll: false,
  spawner: "",
  status: "",
  search: "",
  sortKey: "started_at",
  sortDir: -1,
  confirm: "",
  busy: false,
};

function readMode() {
  try {
    return localStorage.getItem("murmur.agents.mode") === "table" ? "table" : "cards";
  } catch (error) {
    return "cards";
  }
}

function setMode(mode) {
  local.mode = mode;
  try {
    localStorage.setItem("murmur.agents.mode", mode);
  } catch (error) { /* the choice lasts for this page only */ }
}

/** The number in a change's address, so "412" finds the lane whose change is #412. */
function changeNumber(row) {
  if (row.pr != null && row.pr !== "") return String(row.pr);
  const found = String(row.pr_url || "").match(/(\d+)(?:\/?$)/);
  return found ? found[1] : "";
}

/* What the search box looks at: the lane, the branch and the number of the change. Nothing
   else, because a search that also reads the brief finds every lane on the farm at once. */
function matches(row, needle) {
  if (!needle) return true;
  const hay = [row.slug, row.lane, row.branch, changeNumber(row)]
    .filter(Boolean).join(" ").toLowerCase();
  return hay.includes(needle);
}

/* Which lanes a filter leaves on screen. Pure, and the only place the rule lives, so the
   rule can be read and checked without a browser.

   A status outside the five meanings is not a filter, it is a value that arrived from
   somewhere it should not have, and the answer to that is to show every lane rather than an
   empty pane telling the reader to clear a filter they already cleared. */
export function filterAgents(rows, filter = {}) {
  const needle = String(filter.search || "").trim().toLowerCase();
  const spawner = filter.spawner || "";
  const status = filter.status && MEANINGS[filter.status] ? filter.status : "";
  return list(rows).filter((row) => {
    if (filter.project && row.project !== filter.project) return false;
    if (spawner && (row.spawned_by || "") !== spawner) return false;
    if (status && agentMeaning(row.status) !== status) return false;
    return matches(row, needle);
  });
}

function visible(rows, context) {
  return filterAgents(rows, {
    project: context.project,
    spawner: local.spawner,
    status: local.status,
    search: local.search,
  });
}

/* What a select means when the reader picks something in it. The first option of each of
   these two is the one that clears it, so it is read by position: a label can change, and a
   reader who picks "Anyone" is asking for every lane, never for none. */
function chosen(select) {
  return select.selectedIndex === 0 ? "" : select.value;
}

function glyph(name) {
  const identity = mark(name);
  return h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph);
}

/* ------------------------------------------------------------- filters */

/** Who started a lane and what state it is in, each with how many lanes are behind it. */
function counts(rows, context) {
  const spawners = new Map();
  const statuses = new Map();
  for (const row of rows) {
    if (context.project && row.project !== context.project) continue;
    const by = row.spawned_by || "";
    if (by) spawners.set(by, (spawners.get(by) || 0) + 1);
    const meaning = agentMeaning(row.status);
    statuses.set(meaning, (statuses.get(meaning) || 0) + 1);
  }
  return { spawners, statuses };
}

/* Two selects and a search box, which is what the owner asked for in place of a row of
   twenty chips: a farm with twenty code names cannot be filtered by pressing one of twenty. */
function controls(rows, context, shown) {
  const { spawners, statuses } = counts(rows, context);
  const started = [["", `Anyone (${rows.length})`],
    ...[...spawners.entries()].sort().map(([name, count]) => [name, `${name} (${count})`])];
  const states = [["", `Any status (${rows.length})`],
    ...Object.keys(MEANINGS).map((meaning) => [meaning,
      `${MEANINGS[meaning].label} (${statuses.get(meaning) || 0})`])];
  return h("div", { class: "pane-controls", key: "controls" },
    labelled("Started by", h("select", {
      id: "agentSpawner",
      onchange: (event) => {
        local.spawner = chosen(event.target);
        context.paint();
      },
    }, started.map(([value, label]) => h("option", {
      key: value || "any", value, selected: value === local.spawner,
    }, label)))),
    labelled("Status", h("select", {
      id: "agentStatus",
      onchange: (event) => {
        local.status = chosen(event.target);
        context.paint();
      },
    }, states.map(([value, label]) => h("option", {
      key: value || "any", value, selected: value === local.status,
    }, label)))),
    h("input", {
      id: "agentSearch",
      type: "search",
      class: "search",
      value: local.search,
      placeholder: "Lane, branch or change number",
      "aria-label": "Search the lanes by lane, branch or change number",
      oninput: (event) => {
        local.search = event.target.value;
        local.showAll = false;
        context.paint();
      },
    }),
    h("span", { class: "muted count-line" }, `${shown.length} of ${rows.length}`),
    h("div", { class: "spacer" }),
    h("div", { class: "segmented" },
      h("button", {
        type: "button",
        "aria-pressed": String(local.mode === "cards"),
        onclick: () => {
          setMode("cards");
          context.paint();
        },
      }, "Cards"),
      h("button", {
        type: "button",
        "aria-pressed": String(local.mode === "table"),
        onclick: () => {
          setMode("table");
          context.paint();
        },
      }, "Table")));
}

function labelled(text, control) {
  return h("label", { class: "field-label", key: text }, h("span", null, text), control);
}

/* --------------------------------------------------------------- cards */

function agentCard(row, context) {
  const meaning = agentMeaning(row.status);
  // A real button, so the browser gives it focus, Enter and Space without being asked.
  return h("button", {
    key: row.slug,
    type: "button",
    class: "card agent-card",
    "data-agent-card": row.slug || "",
    onclick: () => context.go("board", { agent: row.slug }),
  },
    h("div", { class: "head" },
      glyph(row.spawned_by || row.slug),
      h("div", { class: "name" }, row.slug),
      h("div", { class: "spacer" }),
      pill(meaning, statusWord(row), row.status || "")),
    statusDetail(row) ? h("span", { class: "tag" }, statusDetail(row)) : null,
    droppedScope(row) ? h("span", { class: "tag", "data-scope-dropped": "" }, droppedScope(row)) : null,
    h("div", { class: "sub" },
      [row.project, row.lane, row.engine].filter(Boolean).join(" · ") || "no project"),
    row.task ? h("div", { class: "task" }, fmt.shorten(row.task, 150)) : null,
    row.ci ? checkRow(row.ci) : null,
    h("div", { class: "foot" },
      h("span", { "data-flash": "" }, fmt.ago(row.updated_at || row.started_at)),
      row.cost_usd != null ? h("span", { class: "num" }, fmt.money(row.cost_usd)) : null,
      row.tokens_out != null ? h("span", { class: "num" }, `${fmt.num(row.tokens_out)} out`) : null,
      row.pr_url ? h("span", null, "has a change open") : null));
}

function statusWord(row) {
  return MEANINGS[agentMeaning(row.status)].label;
}

/* What a lane was asked for and did not deliver. A lane that drops part of its scope records
   what it dropped, and that used to be written nowhere on the page: the card said the lane was
   running and nothing said part of the work had been put down. */
export function droppedScope(row) {
  const dropped = (row && row.scope && row.scope.dropped) || [];
  if (!Array.isArray(dropped) || !dropped.length) return "";
  return `scope dropped: ${dropped.map((item) => String(item)).join(", ")}`;
}

/* Why a lane is in the state it is in, when the state alone does not say it. A record the
   server could not read is a failure like any other; what makes it different is the reason,
   and a reason is not a sixth status. */
function statusDetail(row) {
  if (row.status === "state_unreadable") return "record unreadable";
  if (row.outcome === "unmet") return "the contract was not met";
  return "";
}

/* The five words a check can be in. Anything else a record happens to carry is drawn as
   unknown rather than turned into a class name of its own. */
const CHECK_STATES = ["pass", "fail", "pending", "pend", "skipped", "unknown"];

/** The checks on a change, in the order the server gave them, under their own names.

    The server answers a list of {name, state}. A lane record written before that change holds
    the older object of name to state, and is still read here, so an old record still draws. */
export function checkEntries(checks) {
  const rows = Array.isArray(checks)
    ? checks.filter((row) => row && typeof row === "object").map((row) => [row.name, row.state])
    : Object.entries(checks && typeof checks === "object" ? checks : {});
  return rows
    .filter(([name]) => typeof name === "string" && name.trim() !== "")
    .map(([name, state]) => [name, CHECK_STATES.includes(state) ? state : "unknown"]);
}

/** The names come from the check rollup, so a farm with other jobs reads correctly here. */
function checkRow(checks) {
  const entries = checkEntries(checks);
  if (!entries.length) return null;
  const shown = entries.slice(0, 4);
  const rest = entries.slice(4);
  return h("div", { class: "checks", title: rest.map(([name, state]) => `${name}: ${state}`).join("\n") },
    shown.map(([name, state]) => h("span", { class: `check ${state}`, key: name },
      h("span", { class: "dot" }), name)),
    rest.length ? h("span", { class: "check" }, `+${rest.length} more`) : null);
}

/* --------------------------------------------------------------- table */

const COLUMNS = [
  { key: "slug", label: "Lane" },
  { key: "project", label: "Project" },
  { key: "status", label: "Status" },
  { key: "spawned_by", label: "Started by" },
  { key: "started_at", label: "Started", num: true },
  { key: "cost_usd", label: "Cost", num: true },
  { key: "tokens_out", label: "Tokens out", num: true },
];

function table(rows, context) {
  const sorted = [...rows].sort((left, right) => {
    const a = left[local.sortKey];
    const b = right[local.sortKey];
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    return (a > b ? 1 : a < b ? -1 : 0) * local.sortDir;
  });
  return h("div", { class: "tablewrap" },
    h("table", null,
      h("thead", null, h("tr", null, COLUMNS.map((column) => h("th", {
        key: column.key,
        class: column.num ? "num" : null,
        "aria-sort": local.sortKey === column.key ? (local.sortDir === 1 ? "ascending" : "descending") : "none",
      }, h("button", {
        type: "button",
        class: "sortby",
        onclick: () => {
          if (local.sortKey === column.key) local.sortDir *= -1;
          else {
            local.sortKey = column.key;
            local.sortDir = 1;
          }
          context.paint();
        },
      }, column.label))))),
      h("tbody", null, sorted.map((row) => h("tr", {
        key: row.slug,
        class: "clickable",
        tabindex: "0",
        role: "button",
        "data-agent-row": row.slug || "",
        onclick: () => context.go("board", { agent: row.slug }),
        onkeydown: activate(() => context.go("board", { agent: row.slug })),
      },
        h("td", null, row.slug),
        h("td", null, row.project || "none"),
        h("td", null, pill(agentMeaning(row.status), statusWord(row), statusDetail(row) || row.status || "")),
        h("td", null, row.spawned_by || "none"),
        h("td", { class: "num" }, fmt.ago(row.started_at)),
        h("td", { class: "num" }, fmt.money(row.cost_usd)),
        h("td", { class: "num" }, fmt.num(row.tokens_out)))))));
}

/* -------------------------------------------------------------- drawer */

/* Stopping a lane and retiring it are two different things, and which of them is on offer is
   the lane's own business: a lane with a restart policy is started again by the runner under
   a new name, so stopping it is stopping this pass. A lane with no policy has one ending. */
function endings(row) {
  const policy = String((row && row.restart) || "").trim();
  if (policy && policy !== "none") {
    return [
      {
        id: "stop",
        label: "Stop this pass",
        retire: false,
        says: `This ends the pass that is running now. The runner will start this lane again `
          + `under a new name, because its restart policy is ${policy}.`,
      },
      {
        id: "retire",
        label: "Retire this lane",
        retire: true,
        says: "This ends the lane and takes its restart policy away, so the runner will not "
          + "start it again. Its worktree and its branch are left where they are.",
      },
    ];
  }
  return [
    {
      id: "stop",
      label: "Stop this lane",
      retire: false,
      says: "This ends the lane. It has no restart policy, so nothing will start it again. "
        + "Its worktree and its branch are left where they are.",
    },
  ];
}

async function endLane(slug, choice, context) {
  local.busy = true;
  context.paint();
  try {
    const answer = await apiPost("/api/agents/kill", { slug, retire: choice.retire });
    const again = answer && answer.restart ? `The runner will start it again: ${answer.restart}.` : "";
    toast([(answer && answer.detail) || `${slug} was asked to stop.`, again].filter(Boolean).join(" "));
    local.confirm = "";
    await context.refresh("/api/fleet");
    await context.refresh(`/api/agent?slug=${encodeURIComponent(slug)}`);
  } catch (error) {
    toast(serverReason(error) || `${slug} was not stopped.`, "bad");
  } finally {
    local.busy = false;
    context.paint();
  }
}

function endControls(slug, row, context) {
  const allowed = access.writable;
  const choices = endings(row);
  const asked = choices.find((choice) => choice.id === local.confirm);
  return h("div", { class: "lane-actions", key: "actions", "data-write": "" },
    h("div", { class: "section-head" }, h("h3", null, "Ending this lane")),
    asked
      ? h("div", { class: "confirm", role: "group", "aria-label": `${asked.label}?` },
        h("p", null, `${asked.label}? ${asked.says}`),
        h("div", { class: "row" },
          h("button", {
            class: "button primary",
            "data-confirm-yes": asked.id,
            disabled: allowed && !local.busy ? null : true,
            onclick: () => endLane(slug, asked, context),
          }, local.busy ? "Working" : `Yes, ${asked.label.toLowerCase()}`),
          h("button", {
            class: "ghost-button",
            disabled: local.busy ? true : null,
            onclick: () => {
              local.confirm = "";
              context.paint();
            },
          }, "Cancel")))
      : h("div", { class: "row" },
        choices.map((choice) => h("button", {
          key: choice.id,
          class: choice.id === "retire" ? "ghost-button" : "button",
          "data-lane-end": choice.id,
          disabled: allowed ? null : true,
          title: allowed ? choice.says : access.reason || "This dashboard is read-only.",
          onclick: () => {
            local.confirm = choice.id;
            context.paint();
          },
        }, choice.label))),
    allowed ? null : h("p", { class: "readonly-note" },
      access.reason || "This dashboard is read-only."));
}

function detailBody(slug, context) {
  const detail = context.watch(`/api/agent?slug=${encodeURIComponent(slug)}`);
  const logs = context.watch(`/api/agent/log?slug=${encodeURIComponent(slug)}&tail=200`);
  return panel(detail, {
    loading: () => skeletonStack(5),
    ready: (row) => {
      if (row.error) {
        return emptyState({
          title: "That lane is not on this farm",
          body: `Nothing is recorded under ${slug}. It may have been swept.`,
          command: "fleet status",
        });
      }
      return [
        h("div", { class: "kv", key: "facts" },
          fact("Status", [statusWord(row), statusDetail(row)].filter(Boolean).join(", ")),
          fact("Project", row.project || "none"),
          fact("Lane", row.lane || "none"),
          fact("Engine", [row.engine, row.model, row.effort].filter(Boolean).join(" / ") || "none"),
          fact("Started by", row.spawned_by || "none"),
          fact("Started", fmt.ago(row.started_at)),
          fact("Cost", fmt.money(row.cost_usd)),
          fact("Tokens", `${fmt.num(row.tokens_in)} in, ${fmt.num(row.tokens_out)} out`),
          row.restart ? fact("Restart policy", String(row.restart)) : null,
          droppedScope(row) ? fact("Scope dropped",
            (row.scope.dropped || []).map((item) => String(item)).join(", ")) : null,
          row.branch ? fact("Branch", row.branch) : null,
          row.worktree ? fact("Worktree", row.worktree) : null),
        row.pr_url ? h("div", { key: "pr" },
          h("div", { class: "section-head" }, h("h3", null, "Change and checks")),
          h("p", { class: "mono" }, safeHref(row.pr_url)
            ? h("a", { href: safeHref(row.pr_url), target: "_blank", rel: "noreferrer noopener" }, row.pr_url)
            : row.pr_url),
          checkRow(row.ci) || h("p", { class: "muted" }, "No check has reported yet.")) : null,
        row.task ? block("Brief", row.task) : null,
        row.result_text ? block("Result", row.result_text) : null,
        h("div", { key: "log" },
          h("div", { class: "section-head" },
            h("h3", null, "Log, last 200 lines"),
            h("div", { class: "spacer" }),
            h("button", {
              class: "ghost-button small",
              onclick: () => context.refresh(`/api/agent/log?slug=${encodeURIComponent(slug)}&tail=200`),
            }, "Refresh")),
          panel(logs, {
            loading: () => skeletonStack(4),
            isEmpty: (data) => !((data.lines || []).length),
            empty: (() => emptyState({
              title: logs.data && logs.data.missing
                ? "This lane has no log file"
                : "This lane has written no log yet",
              body: (logs.data && logs.data.message)
                || "A lane writes its log as it works. Nothing here means it has not started talking.",
              command: `fleet tail ${slug}`,
            })),
            ready: (data) => h("pre", { class: "log" },
              (data.truncated ? "... earlier lines not shown ...\n" : "") + data.lines.join("\n")),
          })),
        composer(slug, context),
        endControls(slug, row, context),
      ];
    },
  });
}

function fact(label, value) {
  return [h("dt", { key: `k${label}` }, label), h("dd", { key: `v${label}`, "data-flash": "" }, String(value))];
}

function block(title, body) {
  return h("div", { key: title },
    h("div", { class: "section-head" }, h("h3", null, title)),
    h("pre", { class: "log" }, body));
}

function composer(slug, context) {
  const allowed = access.writable;
  return h("div", { class: "composer", key: "composer", "data-write": "" },
    h("div", { class: "section-head" }, h("h3", null, "Message this lane")),
    h("textarea", {
      id: "laneMessage",
      placeholder: allowed ? "What should this lane do next" : "",
      disabled: allowed ? null : true,
    }),
    h("div", { class: "row" },
      h("button", {
        class: "button primary",
        disabled: allowed ? null : true,
        onclick: async () => {
          const field = document.getElementById("laneMessage");
          const text = (field.value || "").trim();
          if (!text) return;
          try {
            const answer = await apiPost("/api/agent/msg", { slug, text });
            field.value = "";
            toast(answer && answer.detail ? answer.detail : `Sent to ${slug}.`);
          } catch (error) {
            toast(serverReason(error) || "The message was not delivered.", "bad");
          }
        },
      }, "Send"),
      allowed ? null : h("span", { class: "readonly-note" }, access.reason || "This dashboard is read-only.")));
}

/** The drawer follows the address: one lane in the query, one lane open. */
export function syncAgentDrawer(context, rows) {
  const wanted = context.params.get("agent") || "";
  const current = openDrawerKey();
  if (wanted && current !== wanted) {
    const row = rows.find((candidate) => candidate.slug === wanted);
    local.confirm = "";
    openDrawer({
      key: wanted,
      title: wanted,
      sub: row ? [row.project, row.lane].filter(Boolean).join(" · ") : "",
      body: () => detailBody(wanted, context),
      onClose: () => {
        local.confirm = "";
        context.drop(`/api/agent?slug=${encodeURIComponent(wanted)}`);
        context.drop(`/api/agent/log?slug=${encodeURIComponent(wanted)}&tail=200`);
        context.go("board");
      },
    });
  }
  if (!wanted && current) closeDrawer();
}

/* ----------------------------------------------------------- the pane */

/** The lanes, as the left half of the Board. The Board asks for /api/fleet on its behalf. */
export function agentsPane(context) {
  const resource = context.res("/api/fleet");
  const rows = list(resource.data);
  if (context.params.get("status") && !local.status) local.status = context.params.get("status");
  syncAgentDrawer(context, rows);
  const shown = visible(rows, context);
  return h("section", { class: "pane agents-pane", key: "agents" },
    h("div", { class: "pane-head" },
      h("h2", null, "Agents"),
      h("div", { class: "spacer" })),
    controls(rows, context, shown),
    h("div", { class: "pane-body" }, panel(resource, {
      loading: () => h("div", { class: "grid cards" },
        [0, 1, 2].map((index) => card({ class: "card-pad", key: `sk${index}` }, skeletonStack(3)))),
      isEmpty: () => shown.length === 0,
      empty: () => emptyState({
        title: rows.length ? "No agent matches this filter" : "No agents yet",
        body: rows.length
          ? "Clear the two selects and the search box above to see every lane this farm knows about."
          : "An agent is one lane of work on one branch. Start the first one with the command below.",
        command: rows.length ? "" : spawnCommand(context),
      }),
      ready: () => {
        const drawn = local.showAll ? shown : shown.slice(0, FIRST_SCREENFUL);
        const rest = shown.length - drawn.length;
        return [
          local.mode === "table"
            ? table(drawn, context)
            : h("div", { class: "grid cards", key: "cards" }, drawn.map((row) => agentCard(row, context))),
          rest > 0 ? h("div", { class: "section-head", key: "more" },
            h("button", {
              class: "ghost-button",
              onclick: () => {
                local.showAll = true;
                context.paint();
              },
            }, `Show the other ${rest}`)) : null,
        ];
      },
    })));
}

/** The command that produces the first agent, with a real project name in it. */
export function spawnCommand(context) {
  const projects = list(context.res("/api/projects").data);
  const name = projects.length ? projects[0].name : "<project>";
  return `fleet spawn --project ${name} --lane first --task "the first thing you want done"`;
}

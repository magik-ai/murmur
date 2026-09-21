/* Agents: who is running, on what, and how far. A card grid for looking, a table for
   counting, and a drawer for one lane. The drawer is a drawer and not a modal on purpose:
   the list stays on screen, so the reader never loses the place they came from. */

import {
  h, card, panel, pill, emptyState, skeletonStack, agentMeaning, MEANINGS,
  openDrawer, closeDrawer, openDrawerKey, toast, safeHref, activate,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list } from "../core/api.js";
import { mark } from "../core/identity.js";

/* How many lanes are drawn before the reader is asked whether they want the rest. Five hundred
   cards take three seconds to lay out and are then laid out again on every tick. */
const FIRST_SCREENFUL = 60;

const local = {
  mode: readMode(),
  showAll: false,
  spawner: "",
  status: "",
  sortKey: "started_at",
  sortDir: -1,
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

function visible(rows, context) {
  return rows.filter((row) => {
    if (context.project && row.project !== context.project) return false;
    if (local.spawner && (row.spawned_by || "") !== local.spawner) return false;
    if (local.status && agentMeaning(row.status) !== local.status) return false;
    return true;
  });
}

function glyph(name) {
  const identity = mark(name);
  return h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph);
}

/* ------------------------------------------------------------- filters */

function chips(rows, context) {
  const spawners = new Map();
  const statuses = new Map();
  for (const row of rows) {
    if (context.project && row.project !== context.project) continue;
    const by = row.spawned_by || "";
    if (by) spawners.set(by, (spawners.get(by) || 0) + 1);
    const meaning = agentMeaning(row.status);
    statuses.set(meaning, (statuses.get(meaning) || 0) + 1);
  }
  return h("div", { class: "chips" },
    chip("All", !local.status && !local.spawner, () => {
      local.status = "";
      local.spawner = "";
      context.paint();
    }, rows.length),
    [...statuses.entries()].sort().map(([meaning, count]) => chip(
      MEANINGS[meaning].label,
      local.status === meaning,
      () => {
        local.status = local.status === meaning ? "" : meaning;
        context.paint();
      },
      count,
      `status:${meaning}`)),
    [...spawners.entries()].sort().map(([name, count]) => chip(
      `by ${name}`,
      local.spawner === name,
      () => {
        local.spawner = local.spawner === name ? "" : name;
        context.paint();
      },
      count,
      `by:${name}`)));
}

function chip(label, pressed, onclick, count, key) {
  return h("button", { class: "chip", key: key || label, "aria-pressed": String(Boolean(pressed)), onclick },
    h("span", null, label),
    count == null ? null : h("span", { class: "count" }, String(count)));
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
    onclick: () => context.go("agents", { agent: row.slug }),
  },
    h("div", { class: "head" },
      glyph(row.spawned_by || row.slug),
      h("div", { class: "name" }, row.slug),
      h("div", { class: "spacer" }),
      pill(meaning, statusWord(row), row.status || "")),
    statusDetail(row) ? h("span", { class: "tag" }, statusDetail(row)) : null,
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

/* Why a lane is in the state it is in, when the state alone does not say it. A record the
   server could not read is a failure like any other; what makes it different is the reason,
   and a reason is not a sixth status. */
function statusDetail(row) {
  if (row.status === "state_unreadable") return "record unreadable";
  if (row.outcome === "unmet") return "the contract was not met";
  return "";
}

/** The names come from the check rollup, so a farm with other jobs reads correctly here. */
function checkRow(checks) {
  const entries = Object.entries(checks || {});
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
        onclick: () => context.go("agents", { agent: row.slug }),
        onkeydown: activate(() => context.go("agents", { agent: row.slug })),
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
            toast("The message was not delivered.", "bad");
          }
        },
      }, "Send"),
      allowed ? null : h("span", { class: "readonly-note" }, access.reason || "This dashboard is read-only.")));
}

function syncDrawer(context, rows) {
  const wanted = context.params.get("agent") || "";
  const current = openDrawerKey();
  if (wanted && current !== wanted) {
    const row = rows.find((candidate) => candidate.slug === wanted);
    openDrawer({
      key: wanted,
      title: wanted,
      sub: row ? [row.project, row.lane].filter(Boolean).join(" · ") : "",
      body: () => detailBody(wanted, context),
      onClose: () => {
        context.drop(`/api/agent?slug=${encodeURIComponent(wanted)}`);
        context.drop(`/api/agent/log?slug=${encodeURIComponent(wanted)}&tail=200`);
        context.go("agents");
      },
    });
  }
  if (!wanted && current) closeDrawer();
}

/* ---------------------------------------------------------------- view */

export default {
  id: "agents",
  title: "Agents",
  needs: ["/api/fleet", "/api/projects"],
  badge(context) {
    const rows = list(context.res("/api/fleet").data);
    const running = rows.filter((row) => agentMeaning(row.status) === "run").length;
    return running || "";
  },
  render(context) {
    const resource = context.res("/api/fleet");
    const rows = list(resource.data);
    if (context.params.get("status") && !local.status) local.status = context.params.get("status");
    syncDrawer(context, rows);
    const shown = visible(rows, context);
    return [
      h("div", { class: "section-head", key: "controls" },
        chips(rows, context),
        h("div", { class: "spacer" }),
        h("div", { class: "segmented" },
          h("button", {
            "aria-pressed": String(local.mode === "cards"),
            onclick: () => {
              setMode("cards");
              context.paint();
            },
          }, "Cards"),
          h("button", {
            "aria-pressed": String(local.mode === "table"),
            onclick: () => {
              setMode("table");
              context.paint();
            },
          }, "Table"))),
      panel(resource, {
        loading: () => h("div", { class: "grid cards" },
          [0, 1, 2].map((index) => card({ class: "card-pad", key: `sk${index}` }, skeletonStack(3)))),
        isEmpty: () => shown.length === 0,
        empty: () => emptyState({
          title: rows.length ? "No agent matches this filter" : "No agents yet",
          body: rows.length
            ? "Clear the filters above to see every lane this farm knows about."
            : "An agent is one lane of work on one branch. Start the first one with the command below.",
          command: rows.length ? "" : `fleet spawn --project ${firstProject(context)} --lane first --task "the first thing you want done"`,
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
      }),
    ];
  },
};

function firstProject(context) {
  const projects = list(context.res("/api/projects").data);
  return projects.length ? projects[0].name : "<project>";
}

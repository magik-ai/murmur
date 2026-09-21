/* Queue: what is being verified before it merges. The words come from the data, not from one
   farm's vocabulary: a stage is whatever the runner called it, and a change is a change unless
   the server says which forge it lives on. */

import {
  h, card, panel, pill, emptyState, skeletonStack, queueMeaning,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { list } from "../core/api.js";

const local = { recentOpen: false, openStage: "", noteDismissed: readDismissed() };

function readDismissed() {
  try {
    return localStorage.getItem("murmur.queue.note") === "dismissed";
  } catch (error) {
    return false;
  }
}

function dismissNote(context) {
  local.noteDismissed = true;
  try {
    localStorage.setItem("murmur.queue.note", "dismissed");
  } catch (error) { /* the note comes back next time, which is harmless */ }
  context.paint();
}

function changeWord(context) {
  return context.features.forge ? "pull request" : "change";
}

function stageName(stage) {
  return stage.name || "stage";
}

function logPath(id, tier) {
  return `/api/ci/log?id=${encodeURIComponent(id)}&tier=${encodeURIComponent(tier)}`;
}

function stageStrip(record, context) {
  const stages = list(record.tiers);
  if (!stages.length) return null;
  return h("div", { class: "stages" }, stages.map((stage) => {
    const meaning = queueMeaning(stage.state);
    const key = `${record.id}:${stageName(stage)}`;
    return h("button", {
      key,
      class: `stage ${meaning}`,
      title: [stage.state, stage.detail, stage.started && stage.ended ? fmt.duration(stage.ended - stage.started) : ""]
        .filter(Boolean).join(" · "),
      onclick: () => {
        local.openStage = local.openStage === key ? "" : key;
        context.paint();
      },
    }, `${stageName(stage)} ${stage.state || ""}`.trim());
  }));
}

function stageLog(record, context) {
  if (!local.openStage.startsWith(`${record.id}:`)) return null;
  const tier = local.openStage.slice(record.id.length + 1);
  const resource = context.watch(logPath(record.id, tier));
  return h("div", { key: "log" }, panel(resource, {
    loading: () => skeletonStack(3),
    isEmpty: (data) => !(data && data.content),
    empty: () => emptyState({
      title: `${tier} wrote no log`,
      body: "The stage produced no output the server could find.",
      command: "fleet ci log " + record.id,
    }),
    ready: (data) => h("pre", { class: "log" }, data.content),
  }));
}

function record(context, row, kind) {
  const meaning = queueMeaning(row.state);
  const started = row.started || row.enqueued;
  return card({ key: row.id || `${kind}:${row.pr}`, class: `ci-card ${meaning}` },
    h("div", { class: "row" },
      h("b", null, `${row.project || "change"} ${row.pr ? `#${row.pr}` : ""}`.trim()),
      h("div", { class: "spacer" }),
      pill(meaning, fmt.titleCase(row.state || kind), row.reason || "")),
    h("div", { class: "muted" },
      [row.repo, row.branch].filter(Boolean).join(" · ") || `one ${changeWord(context)}`),
    h("div", { class: "foot" },
      kind === "queued" && row.position != null ? `position ${row.position}` : null,
      started ? h("span", { "data-flash": "" }, `${kind === "recent" ? "finished" : "started"} ${fmt.ago(row.ended || started)}`) : null,
      row.ended && started ? h("span", null, `took ${fmt.duration(row.ended - started)}`) : null),
    row.reason ? h("div", { class: "muted" }, row.reason) : null,
    list(row.uncovered).length
      ? h("div", { class: "tag" }, `${row.uncovered.length} not covered here: ${row.uncovered.join(", ")}`)
      : null,
    stageStrip(row, context),
    stageLog(row, context));
}

function group(context, title, rows, kind, collapsible) {
  const body = rows.length
    ? h("div", { class: "grid cards" }, rows.map((row) => record(context, row, kind)))
    : h("p", { class: "muted" }, kind === "running"
      ? "Nothing is being verified right now."
      : kind === "queued"
        ? "Nothing is waiting for a runner."
        : "No verdict has been recorded yet.");
  if (!collapsible) {
    return h("section", { class: "section", key: title },
      h("div", { class: "section-head" }, h("h2", null, `${title} (${rows.length})`)),
      body);
  }
  return h("section", { class: "section", key: title },
    h("div", { class: "section-head" },
      h("h2", null, `${title} (${rows.length})`),
      h("div", { class: "spacer" }),
      h("button", {
        class: "ghost-button small",
        "aria-expanded": String(local.recentOpen),
        onclick: () => {
          local.recentOpen = !local.recentOpen;
          context.paint();
        },
      }, local.recentOpen ? "Hide" : "Show")),
    local.recentOpen ? body : null);
}

export default {
  id: "queue",
  title: "Queue",
  needs: ["/api/ci"],
  badge(context) {
    const data = context.res("/api/ci").data || {};
    return list(data.running).length || "";
  },
  render(context) {
    const resource = context.res("/api/ci");
    const project = context.project;
    const pick = (rows) => list(rows).filter((row) => !project || row.project === project);
    return [
      local.noteDismissed ? null : h("div", { class: "banner", key: "note" },
        h("span", null,
          "This queue verifies a change on top of the current main branch, on this machine. " +
          "A hosted run can still disagree, and when it does the hosted answer is the one that counts."),
        h("div", { class: "spacer" }),
        h("button", { class: "ghost-button small", onclick: () => dismissNote(context) }, "Got it")),
      panel(resource, {
        loading: () => h("div", { class: "grid cards" },
          [0, 1].map((index) => card({ class: "card-pad", key: `sk${index}` }, skeletonStack(3)))),
        isEmpty: (data) => !list(data.running).length && !list(data.queued).length && !list(data.recent).length,
        empty: () => emptyState({
          title: "This queue has never run",
          body: `Send a ${changeWord(context)} to it and its stages will appear here as they run.`,
          command: "fleet ci enqueue --project <project> --pr <number>",
        }),
        ready: (data) => [
          data.daemon_alive === false
            ? h("div", { class: "banner bad", key: "daemon" },
              h("span", null, "The queue runner is not running, so nothing will be verified until it is started."),
              h("div", { class: "spacer" }),
              h("code", { class: "cmd" }, "fleet daemon start"))
            : null,
          h("div", { class: "queue-lists", key: "lists" },
            group(context, "Running", pick(data.running), "running", false),
            group(context, "Waiting", pick(data.queued), "queued", false),
            group(context, "Recent", pick(data.recent), "recent", true)),
        ],
      }),
    ];
  },
};

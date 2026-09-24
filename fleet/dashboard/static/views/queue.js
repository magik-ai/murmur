/* Queue: what is being verified before it merges. One row per run, three bands (running,
   waiting, recent), and a detail panel that answers the only question a person opens this tab
   with: where did this run fail. The words come from the data, not from one farm's vocabulary:
   a stage is whatever the runner called it, and a change is a change unless the server says
   which forge it lives on. */

import {
  h, card, panel, pill, emptyState, skeletonStack, queueMeaning, toast, activate,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason } from "../core/api.js";

/* The value of a placeholder option, and never the empty string. applyProp in core/ui.js writes
   `value` only when it differs from what the element already reads, and a fresh <option> reads
   "" before its text child is rendered: an empty value is therefore never written and the
   option falls back to its own text, so "Any state" would filter for runs in the state "Any
   state" and empty the table. A star is written, and it is neither a state a runner reports nor
   a name a project can have. */
const NO_CHOICE = "*";

/* Everything the reader is holding on to between two ticks. It lives here and not in the
   address bar because a detail panel, a find box and a scroll position are a reading position,
   not a place: a link to "the queue with stage three of run 41 open" helps nobody. */
const local = {
  openId: "",
  openStage: "",
  wrap: true,
  find: "",
  findAt: 0,
  findJump: false,
  logToBottom: false,
  sort: "started",
  descending: true,
  stateFilter: NO_CHOICE,
  projectFilter: NO_CHOICE,
  enqueueProject: NO_CHOICE,
  enqueuePr: "",
  job: "",
  jobLabel: "",
  jobError: "",
  cancelling: "",
  uncoveredOpen: false,
  helpOpen: false,
};

const LOG_ELEMENT = "queueLog";
const FIND_LIMIT = 400;
/* The server's own identifier for the verification runner, as `/api/services` spells it.
   A name this page invented instead found no row, and the tab then drew the sentence meant
   for a server that reports no services at all, on a farm reporting four. */
const RUNNER = "ci_runner";

const EXPLANATION =
  "This queue verifies a change on top of the current main branch, on this machine. " +
  "A hosted run can still disagree, and when it does the hosted answer is the one that counts.";

/* ---------------------------------------------------------------- small readings */

/** What a select is actually filtering by: its placeholder is a choice not yet made. */
function chosen(value) {
  return value && value !== NO_CHOICE ? value : "";
}

/** The number typed into the Verify box, or 0 when it is not a positive whole number. */
function prNumber(value) {
  const number = Number(String(value ?? "").trim());
  return Number.isInteger(number) && number > 0 ? number : 0;
}

function changeWord(context) {
  return context.features.forge ? "pull request" : "change";
}

function stageName(stage) {
  return stage.name || "stage";
}

function logPath(id, stage) {
  return `/api/ci/log?id=${encodeURIComponent(id)}&tier=${encodeURIComponent(stage)}`;
}

function allRows(data) {
  return [
    ...list(data.running).map((row) => ({ ...row, band: "running" })),
    ...list(data.queued).map((row) => ({ ...row, band: "queued" })),
    ...list(data.recent).map((row) => ({ ...row, band: "recent" })),
  ];
}

function rowKey(row) {
  return row.id || `${row.band}:${row.project}:${row.pr}`;
}

function startedAt(row) {
  return row.started || row.enqueued || 0;
}

function tookSeconds(row) {
  const started = startedAt(row);
  if (!started) return null;
  const ended = row.ended || (row.band === "running" ? Date.now() / 1000 : null);
  return ended ? ended - started : null;
}

/** The one sentence a reader needs when the two verdicts disagree, and nothing when they do not. */
export function verdictNote(row) {
  const farm = row.farm_verdict;
  const hosted = row.hosted_verdict;
  if (!farm || !hosted || farm === hosted) return "";
  return `This farm says ${farm} and the hosted run says ${hosted}. `
    + "The hosted answer is the one that counts.";
}

/** Which runs a reader has asked to see: the two selects on this tab and the header's filter. */
export function visible(rows, { state = "", project = "" } = {}) {
  return rows.filter((row) => (!state || row.state === state)
    && (!project || row.project === project));
}

export function sortRows(rows, by, descending) {
  const value = (row) => {
    if (by === "pr") return Number(row.pr) || 0;
    if (by === "branch") return String(row.branch || "");
    if (by === "state") return String(row.state || "");
    if (by === "took") return tookSeconds(row) || 0;
    return startedAt(row);
  };
  const sorted = [...rows].sort((one, other) => {
    const left = value(one);
    const right = value(other);
    if (left === right) return String(rowKey(one)).localeCompare(String(rowKey(other)));
    return left > right ? 1 : -1;
  });
  return descending ? sorted.reverse() : sorted;
}

/* ------------------------------------------------------------------- the table */

function stageStrip(row, context) {
  const stages = list(row.tiers);
  if (!stages.length) return h("span", { class: "muted" }, "no stages yet");
  /* The stage's name is an aria-label and a tooltip, never a hidden span inside the button:
     a span positioned off screen inside a table that scrolls sideways escapes the table's
     clipping and drags the whole page wider than the phone it is being read on. */
  return h("span", { class: "q-stages" }, stages.map((stage) => h("button", {
    key: stageName(stage),
    class: `q-stage ${queueMeaning(stage.state)}`,
    "aria-label": `${stageName(stage)}, ${stage.state || "not started"}`,
    title: [stageName(stage), stage.state, stage.detail].filter(Boolean).join(", "),
    onclick: (event) => {
      event.stopPropagation();
      openRun(context, row, stageName(stage));
    },
  })));
}

function openRun(context, row, stage) {
  local.openId = row.id;
  local.openStage = stage || stageName(list(row.tiers)[0] || {});
  local.find = "";
  local.findAt = 0;
  local.uncoveredOpen = false;
  local.logToBottom = true;
  context.paint();
}

function sortHead(label, by, context, extra) {
  const sorted = local.sort === by ? (local.descending ? " desc" : " asc") : "";
  return h("th", { key: by, class: extra || null }, h("button", {
    class: `sortby${sorted}`,
    "aria-label": `Sort by ${label}`,
    onclick: () => {
      if (local.sort === by) local.descending = !local.descending;
      else {
        local.sort = by;
        local.descending = by !== "branch" && by !== "state";
      }
      context.paint();
    },
  }, label));
}

function bandLine(band, count, data) {
  const words = {
    running: count ? "" : "Nothing is being verified right now.",
    queued: count ? "" : "Nothing is waiting for a runner.",
    recent: count ? "" : "No verdict has been recorded yet.",
  };
  const title = { running: "Running", queued: "Waiting", recent: "Recent" }[band];
  return h("tr", { key: `band:${band}`, class: "q-band" },
    h("td", { colspan: "8" },
      h("b", null, `${title} (${count})`),
      words[band] ? h("span", { class: "muted" }, ` ${words[band]}`) : null,
      band === "recent" && !count && list(data.recent).length
        ? h("span", { class: "muted" }, ` ${list(data.recent).length} finished runs are filtered out.`)
        : null));
}

function runRow(context, row) {
  const meaning = queueMeaning(row.state);
  const took = tookSeconds(row);
  const open = local.openId === row.id;
  return h("tr", {
    key: rowKey(row),
    class: `q-row ${meaning}${open ? " open" : ""}`,
    tabindex: "0",
    role: "button",
    "aria-expanded": String(open),
    "data-run": row.id || "",
    onclick: () => openRun(context, row, ""),
    onkeydown: activate(() => openRun(context, row, "")),
  },
    h("td", { class: "num" }, row.pr ? `#${row.pr}` : "none"),
    h("td", null, h("span", { class: "q-branch" }, row.branch || row.project || "unnamed")),
    h("td", null, pill(meaning, fmt.titleCase(row.state || row.band), row.reason || "")),
    h("td", null, stageStrip(row, context)),
    h("td", { class: "num" }, startedAt(row) ? fmt.ago(startedAt(row)) : "not started"),
    h("td", { class: "num" }, took == null ? ""
      : row.band === "running" ? `${fmt.duration(took)} so far` : fmt.duration(took)),
    h("td", null, verdictCell(row)),
    h("td", { class: "actions one" }, cancelButton(context, row)));
}

function verdictCell(row) {
  const farm = row.farm_verdict;
  const hosted = row.hosted_verdict;
  if (!farm && !hosted) return h("span", { class: "muted" }, "none yet");
  if (verdictNote(row)) {
    return h("span", { class: "q-divergent", title: verdictNote(row) },
      `farm ${farm}, hosted ${hosted}`);
  }
  return h("span", null, String(farm || hosted));
}

function table(context, data, rows) {
  const bands = [["running", "running"], ["queued", "queued"], ["recent", "recent"]];
  return h("div", { class: "tablewrap q-table", key: "table" },
    h("table", null,
      h("thead", null, h("tr", null,
        sortHead(changeWord(context) === "pull request" ? "PR" : "Change", "pr", context, "num"),
        sortHead("Branch", "branch", context),
        sortHead("State", "state", context),
        h("th", { key: "stages" }, "Stages"),
        sortHead("Started", "started", context, "num"),
        sortHead("Took", "took", context, "num"),
        h("th", { key: "verdict" }, "Verdict"),
        h("th", { key: "cancel", class: "actions one" }, ""))),
      h("tbody", null, bands.flatMap(([band]) => {
        const mine = sortRows(rows.filter((row) => row.band === band), local.sort, local.descending);
        return [bandLine(band, mine.length, data), ...mine.map((row) => runRow(context, row))];
      }))));
}

/* ------------------------------------------------------------- the detail panel */

function facts(row) {
  const took = tookSeconds(row);
  return h("dl", { class: "kv", key: "facts" },
    h("dt", null, "State"), h("dd", null, fmt.titleCase(row.state || "")),
    h("dt", null, "Project"), h("dd", null, row.project || "none"),
    h("dt", null, "Branch"), h("dd", { class: "mono" }, row.branch || "none"),
    h("dt", null, "Onto"), h("dd", { class: "mono" }, row.base_branch || "main"),
    h("dt", null, "Started"), h("dd", null, startedAt(row) ? fmt.ago(startedAt(row)) : "not started"),
    h("dt", null, "Took"), h("dd", null, took == null ? "not started"
      : row.band === "running" ? `${fmt.duration(took)} so far, still running` : fmt.duration(took)),
    row.position != null ? h("dt", null, "Position") : null,
    row.position != null ? h("dd", null, String(row.position)) : null,
    row.reason ? h("dt", null, "Why") : null,
    row.reason ? h("dd", { class: "wrap" }, row.reason) : null);
}

function stageTabs(context, row) {
  const stages = list(row.tiers);
  if (!stages.length) return null;
  return h("div", { class: "q-tabs", role: "tablist", key: "tabs" }, stages.map((stage) => {
    const name = stageName(stage);
    const selected = local.openStage === name;
    return h("button", {
      key: name,
      class: `q-tab ${queueMeaning(stage.state)}${selected ? " on" : ""}`,
      role: "tab",
      "aria-selected": String(selected),
      onclick: () => {
        local.openStage = name;
        local.find = "";
        local.findAt = 0;
        local.logToBottom = true;
        context.paint();
      },
    }, name, h("span", { class: "q-tab-state" }, stage.state || ""));
  }));
}

/* The log, cut into text and matches so a find can highlight without the page ever being
   handed a string to interpret. A very long log with a very common needle would otherwise
   build tens of thousands of nodes, so the highlighting stops at the first four hundred. */
export function splitMatches(content, needle, limit = FIND_LIMIT) {
  const text = String(content || "");
  const wanted = String(needle || "");
  if (wanted.length < 2) return { parts: [{ text }], total: 0 };
  const parts = [];
  const lower = text.toLowerCase();
  const target = wanted.toLowerCase();
  let at = 0;
  let total = 0;
  for (;;) {
    const found = lower.indexOf(target, at);
    if (found < 0) break;
    total += 1;
    if (total > limit) break;
    if (found > at) parts.push({ text: text.slice(at, found) });
    parts.push({ text: text.slice(found, found + wanted.length), hit: total - 1 });
    at = found + wanted.length;
  }
  if (at < text.length) parts.push({ text: text.slice(at) });
  return { parts, total };
}

function afterPaint(work) {
  setTimeout(work, 0);
}

function logBody(data) {
  const { parts, total } = splitMatches(data.content, local.find);
  const hits = Math.min(total, FIND_LIMIT);
  if (local.findAt >= hits) local.findAt = 0;
  if (local.logToBottom) {
    local.logToBottom = false;
    afterPaint(() => {
      const node = document.getElementById(LOG_ELEMENT);
      if (node) node.scrollTop = node.scrollHeight;
    });
  }
  if (local.findJump) {
    local.findJump = false;
    afterPaint(() => {
      const node = document.querySelector(`#${LOG_ELEMENT} [data-hit="${local.findAt}"]`);
      if (node) node.scrollIntoView({ block: "center" });
    });
  }
  return h("pre", {
    id: LOG_ELEMENT,
    key: "log",
    class: `log q-log${local.wrap ? "" : " nowrap"}`,
    tabindex: "0",
  }, parts.map((part, index) => (part.hit == null
    ? h("span", { key: `t${index}` }, part.text)
    : h("mark", {
      key: `h${index}`,
      "data-hit": String(part.hit),
      class: part.hit === local.findAt ? "on" : null,
    }, part.text))));
}

function findBox(context, data) {
  const { total } = splitMatches(data.content, local.find);
  const hits = Math.min(total, FIND_LIMIT);
  const step = (delta) => {
    if (!hits) return;
    local.findAt = (local.findAt + delta + hits) % hits;
    local.findJump = true;
    context.paint();
  };
  return h("div", { class: "row q-find", key: "find" },
    h("input", {
      type: "search",
      class: "q-findbox",
      "aria-label": "Find in this log",
      placeholder: "Find in this log",
      value: local.find,
      oninput: (event) => {
        local.find = event.target.value;
        local.findAt = 0;
        local.findJump = local.find.length > 1;
        context.paint();
      },
    }),
    h("span", { class: "muted" }, !local.find ? "" : local.find.length < 2
      ? "two letters or more"
      : `${hits ? local.findAt + 1 : 0} of ${total}${total > FIND_LIMIT ? ", first 400 marked" : ""}`),
    h("button", { class: "ghost-button small", disabled: hits ? null : true, onclick: () => step(-1) }, "Previous"),
    h("button", { class: "ghost-button small", disabled: hits ? null : true, onclick: () => step(1) }, "Next"),
    h("button", {
      class: "ghost-button small",
      "aria-pressed": String(local.wrap),
      onclick: () => {
        local.wrap = !local.wrap;
        context.paint();
      },
    }, local.wrap ? "Soft wrap on" : "Soft wrap off"),
    h("button", {
      class: "ghost-button small",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(String(data.content || ""));
          toast("The log is on the clipboard.");
        } catch (error) {
          toast("This browser did not allow the page to write to the clipboard.", "bad");
        }
      },
    }, "Copy"));
}

function stageLog(context, row) {
  if (!local.openStage) return null;
  const resource = context.watch(logPath(row.id, local.openStage));
  return h("div", { class: "q-logwrap", key: `log:${row.id}:${local.openStage}` }, panel(resource, {
    loading: () => skeletonStack(4),
    isEmpty: (data) => !(data && data.content),
    empty: (data) => emptyState({
      title: `${local.openStage} wrote no log`,
      body: (data && data.message) || "The stage produced no output the server could find.",
      command: `fleet ci log ${row.id}`,
    }),
    ready: (data) => [
      findBox(context, data),
      logBody(data),
      data.truncated
        ? h("p", { class: "muted", key: "cut" },
          `Showing the last 256 KB of this stage, the whole log is fleet ci log ${row.id}`)
        : null,
    ],
  }));
}

function failedTests(row) {
  const rows = list(row.failed_tests);
  if (!rows.length) return null;
  return h("div", { class: "q-failed", key: "failed" },
    h("h3", null, `Failed tests (${rows.length})`),
    h("ul", null, rows.map((test, index) => h("li", { key: `${test.tier}:${test.test}:${index}` },
      h("span", { class: "mono" }, test.test || "unnamed test"),
      test.tier ? h("span", { class: "muted" }, ` in ${test.tier}`) : null))));
}

function uncovered(context, row) {
  const gates = list(row.uncovered);
  if (!gates.length) return null;
  return h("div", { class: "q-uncovered", key: "uncovered" },
    h("button", {
      class: "ghost-button small",
      "aria-expanded": String(local.uncoveredOpen),
      onclick: () => {
        local.uncoveredOpen = !local.uncoveredOpen;
        context.paint();
      },
    }, `${gates.length} checks are not covered here`),
    local.uncoveredOpen
      ? h("ul", null, gates.map((gate, index) => h("li", { key: `${gate}:${index}` }, String(gate))))
      : null);
}

async function cancelRun(context, row) {
  local.cancelling = row.id;
  context.paint();
  try {
    await apiPost("/api/ci/cancel", { id: row.id });
    toast(`Cancelling ${row.project || "this run"}.`);
  } catch (error) {
    toast(serverReason(error) || "This run was not cancelled.", "bad");
  } finally {
    local.cancelling = "";
    await context.refresh("/api/ci");
  }
}

function cancelButton(context, row) {
  if (row.band !== "running" && row.band !== "queued") return null;
  const allowed = access.writable && local.cancelling !== row.id;
  return h("button", {
    class: "button small",
    "data-cancel": row.id,
    disabled: allowed ? null : true,
    title: access.writable ? "" : access.reason || "This dashboard is read-only.",
    onclick: (event) => {
      event.stopPropagation();
      cancelRun(context, row);
    },
  }, local.cancelling === row.id ? "Cancelling" : "Cancel");
}

/* Closing a run lets go of the log it was watching as well, or the page goes on asking for a
   stage nobody is reading for the life of the tab. */
function closeDetail(context) {
  if (local.openId && local.openStage) context.drop(logPath(local.openId, local.openStage));
  local.openId = "";
  local.openStage = "";
}

/* Under 1000 px the panel is the whole viewport, and openDrawer in core/ui.js closes on
   Escape. A cover that only closes by its own button teaches a second habit for the same
   shape, so the sheet closes on Escape too. The key is listened for here and once: this view
   owns no line of app.js. */
const SHEET_WIDTH = "(max-width: 1000px)";
let escapeListening = false;

function listenForEscape(context) {
  if (escapeListening) return;
  escapeListening = true;
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !local.openId) return;
    if (!window.matchMedia(SHEET_WIDTH).matches) return;
    closeDetail(context);
    context.paint();
  });
}

function detail(context, rows) {
  const row = rows.find((item) => item.id === local.openId);
  /* A run ages out of the queue while it is open, and the panel goes with it. The reading
     position goes too: a shell still holding a column for a run nobody can close any more is
     420 px of dead page with the table squeezed beside it. */
  if (!row) {
    if (local.openId) closeDetail(context);
    return null;
  }
  return h("aside", { class: "q-detail", key: "detail", "aria-label": "One run" },
    h("div", { class: "q-detail-head" },
      h("div", null,
        h("h2", null, `${row.project || "change"} ${row.pr ? `#${row.pr}` : ""}`.trim()),
        h("p", { class: "muted mono" }, row.id || "")),
      h("div", { class: "spacer" }),
      cancelButton(context, row),
      h("button", {
        class: "ghost-button",
        "data-close-detail": "",
        onclick: () => {
          closeDetail(context);
          context.paint();
        },
      }, "Close")),
    h("div", { class: "q-detail-body" },
      facts(row),
      verdictNote(row) ? h("p", { class: "q-note", key: "verdicts" }, verdictNote(row)) : null,
      failedTests(row),
      uncovered(context, row),
      stageTabs(context, row),
      stageLog(context, row)));
}

/* ------------------------------------------------------------- the controls bar */

function readOnlyLine() {
  return access.writable ? null : h("p", { class: "readonly-note", key: "ro" },
    access.reason || "This dashboard is read-only.");
}

function jobLine(context) {
  if (!local.job) return null;
  const path = `/api/jobs/${encodeURIComponent(local.job)}`;
  const resource = context.watch(path);
  const job = resource.data;
  /* A job the server cannot tell us about is not a job that is still running: leaving the
     control disabled on a resource that will never answer is how a button dies for good. */
  if (resource.error && !job) {
    const said = resource.error;
    afterPaint(() => {
      if (!local.job) return;
      local.job = "";
      local.jobError = `The job could not be read. ${said.title}.`;
      context.drop(path);
    });
    return h("span", { class: "q-bad", key: "job" }, `The job could not be read. ${said.title}.`);
  }
  if (!job || !job.state) return h("span", { class: "muted", key: "job" }, "Asking the runner");
  if (job.state === "running") {
    return h("span", { class: "muted", key: "job" },
      `Job ${job.id} is running: ${job.detail || local.jobLabel}`);
  }
  const failed = job.state === "failed";
  afterPaint(() => {
    if (local.job !== job.id) return;
    local.job = "";
    local.jobError = failed ? (job.error || "The runner refused this request.") : "";
    if (!failed) toast(`${local.jobLabel || "The job"} is done.`);
    context.drop(`/api/jobs/${encodeURIComponent(job.id)}`);
    context.refresh("/api/ci");
  });
  return h("span", { class: failed ? "q-bad" : "muted", key: "job" },
    failed ? job.error || "The runner refused this request." : "Done");
}

async function enqueue(context) {
  /* The project is the one that was picked, never the first in the list: verifying the wrong
     repository because a select was left alone is not a mistake a page should make for you. */
  const project = chosen(local.enqueueProject);
  const number = prNumber(local.enqueuePr);
  if (!project || !number) {
    local.jobError = `Pick a project and the number of a ${changeWord(context)}, for example 412.`;
    context.paint();
    return;
  }
  local.jobError = "";
  local.jobLabel = `${project} #${number}`;
  context.paint();
  try {
    const answer = await apiPost("/api/ci/enqueue", { project, pr: number });
    const job = answer && answer.job;
    local.job = job && typeof job === "object" ? job.id : String(job || "");
    if (!local.job) {
      local.jobError = "";
      toast(`${project} #${number} is in the queue.`);
      await context.refresh("/api/ci");
    }
  } catch (error) {
    local.jobError = serverReason(error) || "The runner did not take this change.";
  } finally {
    context.paint();
  }
}

function verifyControl(context) {
  const projects = list(context.res("/api/projects").data);
  const busy = Boolean(local.job);
  const usable = access.writable && !busy;
  /* The button is dark until both halves of the request are on the page. A Verify that can be
     pressed with nothing picked is how the placeholder was once posted as a project name. */
  const ready = usable && Boolean(chosen(local.enqueueProject)) && prNumber(local.enqueuePr) > 0;
  const missing = usable && !ready
    ? `Pick a project and the number of a ${changeWord(context)}, for example 412.`
    : "";
  return h("div", { class: "row q-verify", key: "verify" },
    h("label", { class: "field" },
      h("span", { class: "sr-only" }, "Project"),
      h("select", {
        "aria-label": "Project",
        disabled: usable ? null : true,
        value: local.enqueueProject,
        onchange: (event) => {
          local.enqueueProject = event.target.value;
          context.paint();
        },
      }, [h("option", {
        key: "none", value: NO_CHOICE, selected: local.enqueueProject === NO_CHOICE,
      }, "Pick a project"),
        ...projects.map((row) => h("option", {
          key: row.name, value: row.name, selected: local.enqueueProject === row.name,
        }, row.name))])),
    h("input", {
      type: "text",
      inputmode: "numeric",
      class: "q-pr",
      "aria-label": `Number of the ${changeWord(context)}`,
      placeholder: `${changeWord(context) === "pull request" ? "PR" : "Change"} number`,
      disabled: usable ? null : true,
      value: local.enqueuePr,
      oninput: (event) => {
        const was = prNumber(local.enqueuePr) > 0;
        local.enqueuePr = event.target.value;
        // Only when the button's answer changes: a repaint on every keystroke buys nothing.
        if (was !== (prNumber(local.enqueuePr) > 0)) context.paint();
      },
    }),
    h("button", {
      class: "button primary",
      "data-enqueue": "",
      disabled: ready ? null : true,
      title: access.writable ? missing : access.reason || "This dashboard is read-only.",
      onclick: () => enqueue(context),
    }, busy ? "Verifying" : "Verify"),
    jobLine(context),
    local.jobError ? h("span", { class: "q-bad", key: "jobError" }, local.jobError) : null);
}

async function runnerAction(context, action) {
  try {
    await apiPost("/api/services", { service: RUNNER, action });
    toast(action === "stop" ? "The verification runner is stopping." : "The verification runner is starting.");
  } catch (error) {
    toast(serverReason(error) || "The verification runner did not answer.", "bad");
  } finally {
    await context.refresh("/api/services");
  }
}

function runnerControl(context) {
  const resource = context.res("/api/services");
  const rows = list((resource.data || {}).services);
  const runner = rows.find((row) => row.id === RUNNER);
  if (!resource.everLoaded && !resource.error) {
    return h("span", { class: "q-runner", key: "runner" }, h("span", { class: "skeleton line-40" }));
  }
  const said = (resource.data || {}).unavailable;
  if (said) {
    /* The server knows why it cannot answer and has a command for it. Its sentence beats
       anything this page could guess about a machine it is only reading. */
    return h("span", { class: "muted q-runner", key: "runner", title: (resource.data || {}).fix || "" }, said);
  }
  if (!runner) {
    return h("span", { class: "muted q-runner", key: "runner" },
      "This server does not report its services, so the runner cannot be switched from here.");
  }
  const on = runner.state === "active";
  const meaning = on ? "run" : runner.state === "failed" ? "fail" : "pause";
  return h("span", { class: "row q-runner", key: "runner" },
    pill(meaning, on ? "Runner on" : `Runner ${runner.state || "off"}`, runner.detail || ""),
    h("button", {
      class: "button",
      "data-runner": on ? "stop" : "start",
      disabled: access.writable ? null : true,
      title: access.writable ? "" : access.reason || "This dashboard is read-only.",
      onclick: () => runnerAction(context, on ? "stop" : "start"),
    }, on ? "Stop" : "Start"));
}

/* Each option says whether it is the chosen one. A select whose options are rebuilt by the
   tick keeps no memory of its value: the page would go on filtering by nothing while the
   control said "Running", which is worse than either.

   The states are counted over `allowed`, the runs the chosen project leaves on the page, and
   not over every run the server sent: a state select offering "Passed (17)" beside a table of
   21 rows is counting a project the reader has already filtered away. The projects are counted
   over every run, because picking one here is what changes that filter. */
function filters(context, rows, allowed) {
  const states = [...new Set(allowed.map((row) => row.state).filter(Boolean))].sort();
  const projects = [...new Set(rows.map((row) => row.project).filter(Boolean))].sort();
  return h("div", { class: "row q-filters", key: "filters" },
    h("label", { class: "field-label" },
      h("span", null, "State"),
      h("select", {
        "aria-label": "Filter by state",
        value: local.stateFilter,
        onchange: (event) => {
          local.stateFilter = event.target.value;
          context.paint();
        },
      }, [h("option", { key: "all", value: NO_CHOICE, selected: local.stateFilter === NO_CHOICE }, "Any"),
        ...states.map((state) => h("option", {
          key: state, value: state, selected: local.stateFilter === state,
        }, `${fmt.titleCase(state)} (${allowed.filter((row) => row.state === state).length})`))])),
    h("label", { class: "field-label" },
      h("span", null, "Project"),
      h("select", {
        "aria-label": "Filter by project",
        value: local.projectFilter,
        onchange: (event) => {
          local.projectFilter = event.target.value;
          context.paint();
        },
      }, [h("option", {
          key: "all", value: NO_CHOICE, selected: local.projectFilter === NO_CHOICE,
        }, "All"),
        ...projects.map((name) => h("option", {
          key: name, value: name, selected: local.projectFilter === name,
        }, `${name} (${rows.filter((row) => row.project === name).length})`))])),
    h("button", {
      class: "icon-button q-help",
      "aria-expanded": String(local.helpOpen),
      "aria-label": "What this queue is",
      title: EXPLANATION,
      onclick: () => {
        local.helpOpen = !local.helpOpen;
        context.paint();
      },
    }, "?"),
    local.helpOpen
      ? h("span", { class: "q-tip", role: "note", key: "tip" }, EXPLANATION)
      : null);
}

/* One row, the same row the Board's filters sit in: the filters on the left, what writes on
   the right. The mark sits on the half that writes, not on the row. Two filters and a help
   button only narrow what is already on screen, and a page that switched off everything in a
   row marked as a write would take a reader's only way back to the whole table. */
function controls(context, rows, allowed) {
  return h("div", { class: "pane-controls q-controls", key: "controls" },
    filters(context, rows, allowed),
    h("div", { class: "q-controls-right", "data-write": "" },
      verifyControl(context), runnerControl(context)),
    readOnlyLine());
}

/* --------------------------------------------------------------------- the view */

export default {
  id: "queue",
  title: "Queue",
  needs: ["/api/ci", "/api/services", "/api/projects"],
  badge(context) {
    const data = context.res("/api/ci").data || {};
    return list(data.running).length || "";
  },
  render(context) {
    listenForEscape(context);
    const resource = context.res("/api/ci");
    const data = resource.data || {};
    const rows = allRows(data);
    const project = chosen(local.projectFilter) || context.project;
    const allowed = visible(rows, { project });
    const shown = visible(allowed, { state: chosen(local.stateFilter) });
    return [
      controls(context, rows, allowed),
      panel(resource, {
        loading: () => h("div", { class: "tablewrap", key: "sk" },
          h("div", { class: "card-pad" }, skeletonStack(6))),
        isEmpty: (payload) => !allRows(payload).length,
        empty: () => emptyState({
          title: "This queue has never run",
          body: `Send a ${changeWord(context)} to it and its stages will appear here as they run. `
            + "No run has been recorded yet.",
          command: "fleet ci enqueue --project <project> --pr <number>",
        }),
        ready: (payload) => {
          /* The second column is there because the panel is, never because a run id is still
             remembered: the two parted company the moment that run left the queue. */
          const open = detail(context, rows);
          return [
            payload.daemon_alive === false
              ? h("div", { class: "banner bad", key: "daemon" },
                h("span", null, "The verification runner is not running, so nothing will be "
                  + "verified until it is started."),
                h("div", { class: "spacer" }),
                h("code", { class: "cmd" }, "fleet ci daemon start"))
              : null,
            h("div", { class: `q-shell${open ? " open" : ""}`, key: "shell" },
              h("div", { class: "q-main" }, table(context, payload, shown)),
              open),
          ];
        },
      }),
    ];
  },
};

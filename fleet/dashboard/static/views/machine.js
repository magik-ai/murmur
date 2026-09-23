/* Machine: the control room. Everything about this farm as a machine lives here, in the order
   a person needs it: power first, then the services that do the work, then the accounts and
   models they spend, then the projects they work in, then whether anything is missing, then
   the settings and where each one is written. Every action says what it will do before it does
   it, and the dashboard says plainly that it keeps running through all of them. */

import {
  h, card, panel, pill, emptyState, skeletonStack, toast, widthStyle, openDrawer, closeDrawer,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason } from "../core/api.js";
import { projectsSection, githubNeeds } from "./projects.js";
/* The Models section is a file of its own; it shares the helpers exported below. The two
   files import each other, which ES modules allow because neither calls the other while it is
   being evaluated. */
import { modelsSection } from "./models.js";
/* Hosting is a section of this tab and a file of its own: it shares the helpers below and
   nothing else. The two files import each other, which ES modules allow because neither calls
   the other while it is being evaluated. */
import { hostingSection } from "./hosting.js";

/* The four power settings, in plain words, with what each does to the machine's share. */
const POWER = [
  ["full", "Full", "Every core is available to the agents."],
  ["soft", "Shared", "The agents give way to whatever else you are doing."],
  ["balanced", "Background", "The agents keep a small share and stay out of the way."],
  ["hard", "Paused", "No new agent starts, and the running ones are held back hard."],
  ["auto", "Automatic", "The farm picks one of the four from how busy the machine is."],
];

const HEALTH_WORD = { ok: "ok", missing: "missing", error: "error", off: "off" };
const HEALTH_MEANING = { ok: "done", missing: "wait", error: "fail", off: "pause" };
const SENSOR_WORD = { done: "reporting", fail: "no answer", wait: "needs you", pause: "off" };

/* The login states the account reader can report, in the page's own words. The sentence under
   each one is the server's; these are only the two words in the pill. */
const LOGIN = {
  logged_in: ["done", "Logged in"],
  waiting_for_login: ["wait", "Waiting for the first login"],
  expired: ["fail", "Token expired"],
  rate_limited: ["wait", "Rate limited"],
  unknown: ["pause", "Cannot tell"],
};

const REFRESH_QUIET_MS = 60000;

const local = {
  confirm: "",
  jobs: {},
  jobError: "",
  busy: "",
  addOpen: false,
  addBusy: false,
  addPolledAt: 0,
  addName: "",
  addEngine: "claude",
  addStep: null,
  addError: "",
  refreshedAt: 0,
  /* The accounts card's footer sentence. The models card keeps its own in views/models.js: one
     failed model removal used to print itself under both cards, because they read one field. */
  sectionError: "",
};

function afterPaint(work) {
  setTimeout(work, 0);
}

export function readOnlyLine(key) {
  return access.writable ? null : h("p", { class: "readonly-note", key: key || "ro" },
    access.reason || "This dashboard is read-only.");
}

export function blocked() {
  return access.writable ? "" : access.reason || "This dashboard is read-only.";
}

function labelFor(id) {
  const found = POWER.find((row) => row[0] === id);
  return found ? found[1] : id || "unknown";
}

export function sectionHead(title, note, ...extra) {
  return h("div", { class: "section-head" },
    h("h2", null, title),
    note ? h("span", { class: "muted" }, note) : null,
    extra.length ? h("div", { class: "spacer" }) : null,
    ...extra);
}

/* ------------------------------------------------------------------ long jobs */

/* An action that can take more than half a minute answers with a job, and the control that
   started it stays disabled until that job ends. A second press while it runs is refused here
   as well as by the server, so a person never fires two drains by double clicking. */
function jobFor(context, action) {
  const id = local.jobs[action];
  if (!id) return null;
  const resource = context.watch(`/api/jobs/${encodeURIComponent(id)}`);
  const job = resource.data;
  if (!job || !job.state) return { state: "running", detail: "asking the farm", id };
  if (job.state === "running") return job;
  afterPaint(() => {
    if (local.jobs[action] !== id) return;
    delete local.jobs[action];
    local.jobError = job.state === "failed"
      ? `${action}: ${job.error || "the farm refused this action"}` : "";
    if (job.state !== "failed") toast(`${fmt.titleCase(action)} is done.`);
    context.drop(`/api/jobs/${encodeURIComponent(id)}`);
    context.refresh("/api/mode");
    context.refresh("/api/services");
    if (action === "add_project") context.refresh("/api/projects");
  });
  return job;
}

async function startJob(context, action, body, path) {
  if (local.jobs[action]) {
    toast(`${fmt.titleCase(action)} is already running.`, "bad");
    return;
  }
  local.jobError = "";
  try {
    const answer = await apiPost(path, body);
    const job = answer && answer.job;
    const id = job && typeof job === "object" ? job.id : job;
    if (id) local.jobs[action] = String(id);
    else toast(`${fmt.titleCase(action)} is done.`);
  } catch (error) {
    local.jobError = serverReason(error) || `${action} was refused.`;
  } finally {
    setConfirm(context, "");
  }
}

/* --------------------------------------------------------------------- power */

function powerModes(context, mode) {
  return h("div", { class: "grid tiles", key: "modes" }, POWER.map(([id, label, line]) => h("button", {
    key: id,
    class: "m-choice",
    "data-mode": id,
    "aria-pressed": String(mode.setting === id),
    disabled: access.writable ? null : true,
    title: blocked(),
    onclick: async () => {
      try {
        await apiPost("/api/mode", { mode: id });
        toast(`Power is now ${label}.`);
      } catch (error) {
        toast(serverReason(error) || "The power setting was not changed.", "bad");
      } finally {
        context.refresh("/api/mode");
      }
    },
  }, h("b", null, label), h("div", { class: "muted" }, line))));
}

const POWER_CONFIRMS = ["throttle", "drain", "resume"];

function previewPath(action) {
  return `/api/power/preview?action=${action}`;
}

/* Every confirm on this page is opened and closed through here, because a confirm that is
   closed has to stop asking. The preview route walks the lanes on a real farm, and a drain
   confirm a person waved away went on asking it for the life of the tab. */
function setConfirm(context, next) {
  if (local.confirm !== next && POWER_CONFIRMS.includes(local.confirm)) {
    context.drop(previewPath(local.confirm));
  }
  local.confirm = next;
  context.paint();
}

/* What each action is about to do, said in full before it is done. The facts come from the
   preview route; the sentences are the page's, because they are what a person is agreeing to. */
function confirmBody(context, action) {
  const resource = context.watch(previewPath(action));
  return panel(resource, {
    loading: () => skeletonStack(2),
    ready: (data) => {
      const lanes = list(data.lanes);
      if (action === "throttle") {
        /* The numbers are the farm's, read from its own power profile, and the server has
           already written them into one sentence. The page drew a sentence of its own out of
           a `caps` object nothing sends, so every number in it read "none". */
        return [
          h("p", { key: "one" }, data.sentence
            || "This caps the processor and the memory of every agent already running, and "
            + "stops any new agent from being spawned."),
          ...list(data.warnings).map((line, index) => h("p", {
            class: "muted", key: `warn:${index}`,
          }, line)),
        ];
      }
      if (action === "drain") {
        return [
          h("p", { key: "one" }, lanes.length
            ? `These ${lanes.length} lanes are salvaged and then stopped:`
            : "No lane is running, so nothing is salvaged or stopped."),
          lanes.length ? h("ul", { class: "m-lanes", key: "lanes" }, lanes.map((lane) => h("li", {
            key: lane.slug,
          }, h("span", { class: "mono" }, lane.slug),
            h("span", { class: "muted" }, lane.restart ? ` restarts as ${lane.restart}` : " has no restart policy")))) : null,
          h("p", { key: "two" },
            "It stops the agent runner and the verification database. A run in flight loses its "
            + "verdict. A lane with no restart policy loses whatever salvage could not push."),
          h("p", { key: "three" }, "This page keeps running."),
        ];
      }
      return [
        h("p", { key: "one" },
          "The agent runner starts again and will respawn every until-pr and until-merged lane, "
          + "spending subscription."),
        lanes.length
          ? h("ul", { class: "m-lanes", key: "lanes" }, lanes.map((lane) => h("li", { key: lane.slug },
            h("span", { class: "mono" }, lane.slug), h("span", { class: "muted" }, ` ${lane.restart}`))))
          : h("p", { class: "muted", key: "none" }, "No lane carries a restart policy right now."),
        h("p", { key: "three" }, "This page keeps running."),
      ];
    },
  });
}

function powerActions(context) {
  const actions = [
    ["throttle", "Throttle the farm and stop new agents"],
    ["drain", "Drain"],
    ["resume", "Resume"],
  ];
  return h("div", { class: "m-actions", key: "actions" },
    h("div", { class: "row" }, actions.map(([action, label]) => {
      const job = jobFor(context, action);
      const running = Boolean(job && job.state === "running");
      return h("button", {
        key: action,
        class: "button",
        "data-power": action,
        disabled: access.writable && !running ? null : true,
        title: blocked(),
        onclick: () => setConfirm(context, local.confirm === action ? "" : action),
      }, running ? `${label}, running` : label);
    })),
    actions.map(([action, label]) => {
      const job = jobFor(context, action);
      if (!job || job.state !== "running") return null;
      return h("p", { class: "muted", key: `job:${action}` },
        `Job ${job.id} is running: ${job.detail || label}.`);
    }),
    local.jobError ? h("p", { class: "m-bad", key: "jobError" }, local.jobError) : null,
    local.confirm && ["throttle", "drain", "resume"].includes(local.confirm)
      ? h("div", { class: "m-confirm", key: "confirm" },
        h("h3", null, actions.find((row) => row[0] === local.confirm)[1]),
        confirmBody(context, local.confirm),
        h("div", { class: "row" },
          h("button", {
            class: "button primary",
            "data-confirm": local.confirm,
            disabled: access.writable ? null : true,
            onclick: () => startJob(context, local.confirm, { action: local.confirm }, "/api/power"),
          }, "Yes, do it"),
          h("button", {
            class: "ghost-button",
            onclick: () => setConfirm(context, ""),
          }, "Keep things as they are")))
      : null);
}

function powerSection(context) {
  const resource = context.res("/api/mode");
  return h("section", { class: "section", key: "power" },
    sectionHead("Power", "The dashboard keeps running through all of these."),
    card({ class: "card-pad", "data-write": "" }, panel(resource, {
      loading: () => skeletonStack(3),
      ready: (mode) => [
        h("p", { class: "muted", key: "now" },
          `The setting is ${labelFor(mode.setting)}. Right now the agents are on ${labelFor(mode.effective)}.`),
        powerModes(context, mode),
        powerActions(context),
        readOnlyLine("ro-power"),
      ],
    })));
}

/* ------------------------------------------------------------------ services */

async function serviceAction(context, row, action) {
  local.busy = `${row.id}:${action}`;
  context.paint();
  try {
    await apiPost("/api/services", { service: row.id, action });
    toast(`${row.label}: ${action} sent.`);
  } catch (error) {
    toast(serverReason(error) || `${row.label} did not answer.`, "bad");
  } finally {
    local.busy = "";
    await context.refresh("/api/services");
  }
}

function serviceMeaning(state) {
  if (state === "active") return "run";
  if (state === "failed") return "fail";
  return "pause";
}

function servicesSection(context) {
  const resource = context.res("/api/services");
  return h("section", { class: "section", key: "services" },
    sectionHead("Services", "What runs on this machine, and its state as the farm last read it."),
    card({ key: "services", "data-write": "" }, panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(4)),
      isEmpty: (data) => !list(data.services).length,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: "This server does not report its services",
        body: "The page and the server are different versions, so this table has nothing to show.",
        command: "fleet update && fleet dashboard restart",
      })),
      ready: (data) => [
        h("div", { class: "tablewrap", key: "table" }, h("table", null,
          h("thead", null, h("tr", null,
            h("th", null, "Service"),
            h("th", null, "State"),
            h("th", null, "Last change"),
            h("th", null, "What it does"),
            h("th", null, "Controls"))),
          h("tbody", null, list(data.services).map((row) => h("tr", { key: row.id },
            h("td", null, row.label || row.id),
            h("td", null, pill(serviceMeaning(row.state), fmt.titleCase(row.state || "unknown"), row.detail || "")),
            h("td", { class: "num" }, row.since ? fmt.ago(row.since) : "not known"),
            h("td", { title: row.what || "" }, row.what || ""),
            h("td", null, list(row.actions).length
              ? h("div", { class: "row" }, list(row.actions).map((action) => h("button", {
                key: action,
                class: "ghost-button small",
                "data-service": `${row.id}:${action}`,
                disabled: access.writable && local.busy !== `${row.id}:${action}` ? null : true,
                title: blocked(),
                onclick: () => serviceAction(context, row, action),
              }, fmt.titleCase(action))))
              /* The row that cannot be worked from here still hands over the command that
                 works it from a terminal: the server writes that out as `fix`, and names the
                 command family as `verb` when there is nothing to fix. */
              : h("code", { class: "cmd" }, row.fix || row.verb || "no command"))))))),
        readOnlyLine("ro-services"),
      ],
    })));
}

/* ------------------------------------------------------------------ accounts */

/** Every window the server sent, in its order, labelled by its own name. */
export function windows(account) {
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

function windowBars(account) {
  const rows = windows(account);
  if (!rows.length) return h("span", { class: "muted" }, "no numbers yet");
  const summary = rows.map((row) => `${row.name} ${fmt.percent(row.percent)}`).join(", ");
  return h("div", { class: "m-limits", title: summary }, rows.map((row) => h("div", { class: "m-limit", key: row.name },
    h("span", { class: "m-lname" }, row.name),
    h("span", {
      class: `bar ${row.percent >= 95 ? "fail" : row.percent >= 70 ? "wait" : ""}`.trim(),
    }, h("i", { style: widthStyle(row.percent) })),
    h("span", { class: "num" }, fmt.percent(row.percent)))));
}

/* Two words and then the whole sentence. The sentence is the server's, it is the only part
   that says what to do about a login that is not in, and a tooltip is not somewhere a person
   finds it: it goes in the row. */
function loginCell(states, name) {
  const found = states.find((row) => row.name === name);
  if (!found) return h("span", { class: "muted" }, "not read yet");
  const [meaning, word] = LOGIN[found.state] || ["pause", fmt.titleCase(found.state || "unknown")];
  const sentence = found.sentence || "";
  return h("div", { class: "m-login", title: sentence },
    pill(meaning, word, sentence),
    sentence ? h("span", { class: "muted cell-text" }, sentence) : null);
}

async function refreshAccounts(context) {
  local.refreshedAt = Date.now();
  context.paint();
  try {
    await apiPost("/api/accounts/refresh", {});
    toast("The accounts were read again.");
  } catch (error) {
    toast(serverReason(error) || "The accounts were not read again.", "bad");
  } finally {
    await context.refresh("/api/accounts");
    await context.refresh("/api/accounts/login-state");
  }
}

function refreshButton(context) {
  const left = REFRESH_QUIET_MS - (Date.now() - local.refreshedAt);
  const quiet = left > 0;
  return h("button", {
    class: "ghost-button small",
    "data-accounts-refresh": "",
    disabled: access.writable && !quiet ? null : true,
    title: quiet ? "Asking the vendor again this soon changes nothing." : blocked(),
    onclick: () => refreshAccounts(context),
  }, quiet ? `Refresh now (in ${fmt.duration(left / 1000)})` : "Refresh now");
}

async function removeAccount(context, name) {
  try {
    const answer = await apiPost("/api/accounts/remove", { name });
    toast(`${name} was moved to ${(answer && answer.backup) || "the backup folder"}.`);
    setConfirm(context, "");
  } catch (error) {
    local.sectionError = serverReason(error) || `${name} was not removed.`;
  } finally {
    await context.refresh("/api/accounts");
    await context.refresh("/api/accounts/login-state");
  }
}

function removeAccountConfirm(context, name) {
  return h("div", { class: "m-confirm", key: "removeAccount" },
    h("h3", null, `Remove ${name}`),
    h("p", null, "The account folder is moved to the backup folder under "),
    h("code", { class: "cmd" }, `~/.fleet/dead-account-backups/${name}.wiped`),
    h("p", null, "Nothing is deleted, and the farm stops spending this subscription."),
    h("div", { class: "row" },
      h("button", {
        class: "button primary",
        "data-confirm": `remove-account:${name}`,
        disabled: access.writable ? null : true,
        title: blocked(),
        onclick: () => removeAccount(context, name),
      }, "Yes, remove it"),
      h("button", {
        class: "ghost-button",
        onclick: () => setConfirm(context, ""),
      }, "Keep it")));
}

/* -------------------------------------------------------- adding an account */

/* Adding an account is a dialog, not a form squeezed under the table (owner review 2026-09-22).
   Three screens in the drawer: pick the engine and name it, run one command and follow the
   steps, wait for the login, which the dialog notices by itself. */
const ADD_KEY = "add-account";

const ENGINE_NOTES = {
  claude: "One subscription, its own login on the farm. Lanes are spread across the Claude accounts you register here.",
  codex: "One shared login for the whole farm. This re-logs it in; it does not add a second account.",
};

function engineNote(model) {
  return ENGINE_NOTES[model.id] || model.role || "A subscription the agents can spend.";
}

function openAddDialog(context) {
  local.addStep = null;
  local.addError = "";
  local.addBusy = false;
  local.addOpen = true;
  const engines = list(context.res("/api/engines").data);
  if (!engines.some((model) => model.id === local.addEngine)) {
    local.addEngine = (engines.find((model) => model.installed !== false) || engines[0] || {}).id || "claude";
  }
  openDrawer({
    key: ADD_KEY,
    title: "Add an account",
    sub: "A subscription the agents spend while they work.",
    body: () => addDialogBody(context),
    onClose: () => {
      local.addOpen = false;
      local.addStep = null;
      local.addName = "";
      local.addError = "";
      context.refresh("/api/accounts");
      context.refresh("/api/accounts/login-state");
    },
  });
}

async function startAdd(context) {
  const name = local.addName.trim();
  if (local.addEngine !== "codex" && !name) {
    local.addError = "Give the account a name, for example farm-three.";
    context.paint();
    return;
  }
  if (local.addEngine !== "codex" && !/^[A-Za-z0-9._-]{1,40}$/.test(name)) {
    local.addError = "A name is letters, digits, dots, dashes or underscores, up to forty of them.";
    context.paint();
    return;
  }
  local.addError = "";
  local.addBusy = true;
  context.paint();
  try {
    local.addStep = await apiPost("/api/accounts/add", { name, engine: local.addEngine });
    local.addPolledAt = 0;
  } catch (error) {
    local.addError = serverReason(error) || "The farm did not answer with a command to run.";
  } finally {
    local.addBusy = false;
    context.paint();
  }
}

export async function copyCommand(command) {
  try {
    await navigator.clipboard.writeText(String(command || ""));
    toast("Copied. Paste it in a terminal on your own machine.");
  } catch (error) {
    toast("Select the command and copy it by hand: the browser refused the clipboard.", "bad");
  }
}

/* An account is a subscription logged in on this farm, so this dialog offers the two engines
   that have one. Every other row in the catalog is a model a person adds in the Models
   section, and listing those here invited a "subscription" for a CLI paid by the token. */
const ACCOUNT_ENGINES = ["claude", "codex"];

function engineChoices(context) {
  const engines = list(context.res("/api/engines").data)
    .filter((model) => model && ACCOUNT_ENGINES.includes(String(model.engine || model.id)));
  if (!engines.length) {
    return h("p", { class: "muted", key: "no-engines" },
      "The farm has not listed an engine an account can be added for.");
  }
  return h("div", { class: "m-engines", role: "radiogroup", "aria-label": "Engine", key: "engines" },
    engines.map((model) => {
      const off = model.installed === false;
      const chosen = local.addEngine === model.id;
      return h("button", {
        key: model.id,
        type: "button",
        class: "choice m-engine" + (chosen ? " chosen" : ""),
        role: "radio",
        "aria-checked": String(chosen),
        "data-engine-choice": model.id,
        disabled: off || !access.writable ? true : null,
        title: off ? `${model.label || model.id} is not installed on this farm.` : "",
        onclick: () => {
          local.addEngine = model.id;
          local.addError = "";
          context.paint();
        },
      },
        h("div", { class: "m-engine-head" },
          h("b", null, model.label || model.id),
          off ? pill("pause", "not installed", "") : null),
        h("div", { class: "muted" }, engineNote(model)));
    }));
}

/* Screen one: which engine, and what to call it. */
function addForm(context) {
  const codex = local.addEngine === "codex";
  return [
    h("div", { class: "m-dialog-step", key: "s1" },
      h("div", { class: "m-step-no" }, "1"),
      h("div", null,
        h("h3", null, "Which engine"),
        h("p", { class: "muted" }, "Pick the subscription this account spends."))),
    engineChoices(context),
    h("div", { class: "m-dialog-step", key: "s2" },
      h("div", { class: "m-step-no" }, "2"),
      h("div", null,
        h("h3", null, codex ? "Name" : "Name it"),
        h("p", { class: "muted" }, codex
          ? "Codex is one shared login, so it has one name: codex."
          : "Short and yours, for example farm-three. It becomes the account's folder on the farm."))),
    codex
      ? h("code", { class: "cmd", key: "fixed-name" }, "codex")
      : h("input", {
        key: "name",
        type: "text",
        class: "m-name",
        "aria-label": "Account name",
        placeholder: "farm-three",
        autocomplete: "off",
        spellcheck: "false",
        value: local.addName,
        disabled: access.writable ? null : true,
        oninput: (event) => {
          local.addName = event.target.value;
          local.addError = "";
        },
        onkeydown: (event) => {
          if (event.key === "Enter") startAdd(context);
        },
      }),
    local.addError ? h("p", { class: "m-bad", key: "err", role: "alert" }, local.addError) : null,
    h("div", { class: "row m-dialog-actions", key: "actions" },
      h("button", {
        class: "button primary",
        "data-add-start": "",
        disabled: access.writable && !local.addBusy ? null : true,
        title: blocked(),
        onclick: () => startAdd(context),
      }, local.addBusy ? "Asking the farm" : "Get the command"),
      h("button", { class: "ghost-button", onclick: () => closeDrawer() }, "Cancel")),
  ];
}

/* Screens two and three: the command with its steps, then the login the dialog waits for. */
function addSteps(context) {
  const step = local.addStep;
  // Watched, not merely read: the drawer is repainted by the tick, and only a watched route is
  // pulled by it, so the login state keeps arriving while the dialog waits for it.
  const states = list((context.watch("/api/accounts/login-state").data || {}).accounts);
  const found = states.find((row) => row.name === step.name);
  const waiting = !found || found.state !== "logged_in";
  // While the dialog waits it asks on its own rhythm, every two seconds, whatever the page's
  // tick is doing: the flip to "logged in" is the one thing the reader is watching for.
  if (waiting && Date.now() - (local.addPolledAt || 0) > 2000) {
    local.addPolledAt = Date.now();
    context.refresh("/api/accounts/login-state");
  }
  return h("div", { class: "m-steps", key: "steps" },
    h("div", { class: "m-dialog-step" },
      h("div", { class: "m-step-no" }, "3"),
      h("div", null,
        h("h3", null, `Log ${step.name} in`),
        h("p", { class: "muted" }, "In a terminal on your own machine, not on this page, run:"))),
    h("div", { class: "m-cmd-row" },
      h("code", { class: "cmd", "data-add-command": "" }, step.command || ""),
      h("button", {
        class: "button small",
        "data-add-copy": "",
        onclick: () => copyCommand(step.command),
      }, "Copy")),
    h("ol", null, list(step.steps).map((line, index) => h("li", { key: index }, line))),
    h("div", { class: "m-dialog-step" },
      h("div", { class: "m-step-no" }, "4"),
      h("div", null,
        h("h3", null, waiting ? "Waiting for the login" : "Logged in"),
        h("div", { class: "row m-wait" },
          pill(waiting ? "wait" : "done",
            waiting ? "Waiting for the first login" : "Logged in",
            (found && found.sentence) || ""),
          h("span", { class: "muted" }, waiting
            ? "This page notices the login by itself; nothing to press here."
            : "The account is ready to be spent.")))),
    h("div", { class: "row m-dialog-actions" },
      h("button", {
        class: waiting ? "ghost-button" : "button primary",
        "data-add-done": "",
        onclick: () => closeDrawer(),
      }, waiting ? "Close, I will finish later" : "Done")));
}

function addDialogBody(context) {
  return local.addStep ? [addSteps(context)] : addForm(context);
}

/* The button under the table; the dialog is the drawer. */
function addAccount(context) {
  return h("button", {
    class: "button small",
    "data-add-account": "",
    disabled: access.writable ? null : true,
    title: blocked(),
    onclick: () => openAddDialog(context),
  }, "Add an account");
}

function accountsSection(context) {
  const resource = context.res("/api/accounts");
  const states = list((context.res("/api/accounts/login-state").data || {}).accounts);
  return h("section", { class: "section", key: "accounts" },
    sectionHead("Accounts", "The subscriptions the agents spend.", refreshButton(context)),
    card({ key: "accounts", "data-write": "" }, panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(4)),
      isEmpty: (data) => !list(data.accounts).length,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: "No accounts registered",
        body: "An account is the subscription an agent spends while it works.",
        command: "fleet accounts add <name>",
      })),
      ready: (data) => [
        h("div", { class: "tablewrap", key: "table" }, h("table", null,
          h("thead", null, h("tr", null,
            h("th", null, "Account"),
            h("th", null, "Engine"),
            h("th", null, "Login"),
            h("th", null, "Windows"),
            h("th", null, "Last read"),
            h("th", null, ""))),
          h("tbody", null, list(data.accounts).map((account) => h("tr", { key: account.name },
            h("td", { title: `${account.email || account.label || account.name}, folder ${account.name}` },
              h("span", { class: "m-account" }, account.label || account.name,
                fmt.room(account) ? pill(fmt.room(account).meaning, fmt.room(account).word, "") : null)),
            h("td", null, account.engine || "unknown"),
            h("td", null, loginCell(states, account.name)),
            h("td", { class: "m-windows" }, windowBars(account)),
            h("td", { class: "num" }, account.read_at ? fmt.ago(account.read_at) : "never"),
            h("td", null, h("button", {
              class: "ghost-button small",
              "data-remove-account": account.name,
              disabled: access.writable ? null : true,
              title: blocked(),
              onclick: () => setConfirm(context, `remove-account:${account.name}`),
            }, "Remove"))))))),
        h("div", { class: "card-pad", key: "add" },
          local.confirm.startsWith("remove-account:")
            ? removeAccountConfirm(context, local.confirm.slice("remove-account:".length))
            : addAccount(context),
          local.sectionError ? h("p", { class: "m-bad" }, local.sectionError) : null,
          readOnlyLine("ro-accounts")),
      ],
    })));
}

/* -------------------------------------------------------------------- models */

/* The Models section is views/models.js. What stays here are the dialog pieces it shares with
   the accounts dialog and the hosting section, exported. */
export function detailRow(label, value) {
  if (!value) return null;
  return [
    h("dt", { key: `dt:${label}` }, label),
    h("dd", { key: `dd:${label}` }, value),
  ];
}

export function stepHead(number, title, note) {
  return h("div", { class: "m-dialog-step", key: `head${number}` },
    h("div", { class: "m-step-no" }, String(number)),
    h("div", null,
      h("h3", null, title),
      note ? h("p", { class: "muted" }, note) : null));
}

export function commandRow(command, mark, key) {
  return h("div", { class: "m-cmd-row", key: key || `cmd:${mark}` },
    h("code", { class: "cmd", [`data-${mark}`]: "" }, command),
    h("button", {
      class: "button small",
      onclick: () => copyCommand(command),
    }, "Copy"));
}

/* The farm's own ssh name, from the server; "farm" only on a server too old to send one. */
export function farmAlias(context) {
  const config = context.res("/api/config").data || {};
  return String(config.farm_alias || "").trim() || "farm";
}

function tile(label, value, note, meaning) {
  return card({ class: "card-pad tile", key: label },
    h("div", { class: "label" }, label, meaning ? pill(meaning, SENSOR_WORD[meaning] || meaning, note || "") : null),
    h("div", { class: "value", "data-flash": "" }, value),
    note ? h("div", { class: "muted" }, note) : null);
}

function sensorTiles(context, metrics) {
  const features = context.features;
  const out = [];
  if (!features.gpu) {
    out.push(tile("Graphics card", "Not configured",
      "Power mode has no signal from it and stays on full. Set FLEET_NVIDIA_SMI to switch it on.", "pause"));
  } else if (!metrics.gpu) {
    out.push(tile("Graphics card", "No answer",
      "The sensor is configured but returned nothing on the last read.", "fail"));
  } else {
    out.push(tile("Graphics card", `${fmt.decimal(metrics.gpu.temp_c, 0)} C`,
      `${fmt.percent(metrics.gpu.util_pct)} busy, ${metrics.gpu.name || "unnamed card"}`, "done"));
  }
  if (!features.cpu_temp) {
    out.push(tile("Processor temperature", "Not configured",
      "No temperature sensor is enabled on this machine.", "pause"));
  } else if (metrics.cpu_temp_c == null) {
    out.push(tile("Processor temperature", "No answer",
      metrics.sensors_unavailable ? "The sensor package is not installed." : "The sensor returned nothing.", "fail"));
  } else {
    out.push(tile("Processor temperature", `${fmt.decimal(metrics.cpu_temp_c, 0)} C`,
      metrics.cpu_temp_source || "", "done"));
  }
  const load = metrics.load || {};
  const memory = metrics.mem || {};
  const disk = metrics.disk || {};
  out.push(tile("Load", fmt.decimal(load.load1, 2), `${fmt.num(load.cores)} cores`));
  out.push(tile("Memory free", fmt.gigabytes(memory.ram_avail_gb), `of ${fmt.gigabytes(memory.ram_total_gb)}`));
  out.push(tile("Disk free", fmt.gigabytes(disk.free_gb), disk.path || ""));
  return h("div", { class: "grid tiles", key: "sensors" }, out);
}

function healthSection(context) {
  const checks = context.res("/api/health");
  const metrics = context.res("/api/metrics");
  return h("section", { class: "section", key: "health" },
    sectionHead("Health", "What this farm needs, and whether the machine is answering."),
    panel(metrics, {
      loading: () => h("div", { class: "grid tiles" },
        [0, 1, 2].map((index) => card({ class: "card-pad", key: `sk${index}` }, skeletonStack(2)))),
      ready: (data) => sensorTiles(context, data),
    }),
    h("div", { class: "gap-sm", key: "gap" }),
    card({ key: "checks" }, panel(checks, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(5)),
      isEmpty: (data) => !list(data.checks).length,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: "The server does not report its prerequisites",
        body: "The page and the server are different versions, so this table has nothing to show.",
        command: "fleet update && fleet dashboard restart",
      })),
      ready: (data) => h("div", { class: "tablewrap" }, h("table", null,
        h("thead", null, h("tr", null,
          h("th", null, "Tool"),
          h("th", null, "State"),
          h("th", null, "What it means"),
          h("th", null, "Fix"))),
        h("tbody", null, list(data.checks).map((check) => h("tr", { key: check.id },
          h("td", null, check.label || check.id),
          h("td", null, pill(HEALTH_MEANING[check.state] || "pause", HEALTH_WORD[check.state] || check.state, "")),
          h("td", { title: check.detail || "" }, check.detail || ""),
          h("td", { class: "mono" }, check.fix || "none needed")))))),
    })));
}

/* --------------------------------------------------------------------- the view */

export default {
  id: "machine",
  title: "Machine",
  /* "/api/github" is on the tick only while it is worth reading: see githubNeeds. */
  needs: (context) => [
    "/api/mode", "/api/services", "/api/accounts", "/api/accounts/login-state",
    "/api/engines", "/api/projects", "/api/projects/next-port", "/api/health", "/api/metrics",
    "/api/hosts", "/api/machines",
    ...githubNeeds(context),
  ],
  badge(context) {
    /* The count points at the Health section, so it is drawn only when that section is. */
    if (!context.features.health_panel) return "";
    const checks = list((context.res("/api/health").data || {}).checks);
    return checks.filter((check) => check.state === "missing" || check.state === "error").length || "";
  },
  render(context) {
    return [
      powerSection(context),
      servicesSection(context),
      hostingSection(context),
      accountsSection(context),
      modelsSection(context),
      projectsSection(context),
      /* Off unless the farm sets FLEET_DASH_HEALTH=on: its tiles read hardware sensors most
         machines do not have. */
      context.features.health_panel ? healthSection(context) : null,
    ];
  },
};

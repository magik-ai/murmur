/* Machine: the control room. Everything about this farm as a machine lives here, in the order
   a person needs it: power first, then the services that do the work, then the accounts and
   models they spend, then the projects they work in, then whether anything is missing, then
   the settings and where each one is written. Every action says what it will do before it does
   it, and the dashboard says plainly that it keeps running through all of them. */

import {
  h, card, panel, pill, emptyState, skeletonStack, toast, widthStyle, safeHref,
  openDrawer, closeDrawer, openDrawerKey,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason } from "../core/api.js";

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
  projectName: "",
  projectRepo: "",
  projectPort: "",
  projectError: "",
  /* The accounts card's footer sentence and the models card's, kept apart: one failed model
     removal used to print itself under both cards, because the two footers read one field. */
  sectionError: "",
  modelError: "",
  modelPreset: "",
  modelId: "",
  modelVariant: "",
  modelBin: "",
  modelRun: "",
  modelEnv: "",
  addModelError: "",
  modelBusy: false,
  modelAdded: "",
  modelRowSeed: null,
  modelTesting: false,
  modelPoll: 0,
};

function afterPaint(work) {
  setTimeout(work, 0);
}

function readOnlyLine(key) {
  return access.writable ? null : h("p", { class: "readonly-note", key: key || "ro" },
    access.reason || "This dashboard is read-only.");
}

function blocked() {
  return access.writable ? "" : access.reason || "This dashboard is read-only.";
}

function labelFor(id) {
  const found = POWER.find((row) => row[0] === id);
  return found ? found[1] : id || "unknown";
}

function sectionHead(title, note, ...extra) {
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

async function copyCommand(command) {
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
            h("td", null, account.label || account.name),
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

/* Models, not engines (owner review, 2026-09-22 evening). A row is a model the agents can be
   spawned with, and the table answers the five questions a person actually has: what it is,
   what it runs, how it is paid for, whether it works, and when that was last proved. The role
   and the quality notes left the table for the row's own drawer: a table carrying a paragraph
   per row is a wall, and that is how the owner read it. */

/* The five words a status can be, and the meaning each is drawn in. One pill per row, never
   two: a row that carried both "installed" and "enabled" made a reader work out the state the
   page already knew. */
const STATUS = {
  on: ["done", "On"],
  off: ["pause", "Off"],
  needs_key: ["wait", "Needs a key"],
  not_installed: ["pause", "Not installed"],
  failing: ["fail", "Failing"],
};

/* A farm on last release's server sends no status at all, and any route can answer a word this
   page has never heard. Both land on the same five, worked out from the fields the route has
   carried from the beginning: whether the command is here, how the last test went, and whether
   the row is switched on. Whether a key is held is not among them, because no server has ever
   said: on this farm that answer arrives as the status word `needs_key`. */
function statusOf(model) {
  const said = String((model || {}).status || "");
  if (STATUS[said]) return said;
  if (!model || model.installed === false) return "not_installed";
  if (model.health === "fail") return "failing";
  return model.enabled ? "on" : "off";
}

/* How the model is paid for, in the catalog's own sentence. A catalog that does not say falls
   back to the key it reads, and then to what its terms say, because "unknown" on the one
   column about money is the answer a person least wants. */
function accessOf(model) {
  const said = String((model || {}).access || "").trim();
  if (said) return said;
  const env = String((model || {}).auth_env || "").trim();
  if (env) return `An API key, read from ${env}.`;
  const terms = String((model || {}).tos || "").trim();
  return terms || "The catalog does not say how this one is paid for.";
}

/* The terms of a service, as one of three words. The classification is the server's, sent as
   `tos_kind`: safe, check or blocked. A page that read the sentence itself and called anything
   it did not recognise "safe headless" put that green pill on Custom command, whose own terms
   sentence says nobody here has read the terms for you. */
const TOS_PILL = {
  safe: ["done", "safe headless"],
  check: ["wait", "check the terms"],
  blocked: ["fail", "not permitted"],
};

/* A farm on a server that sends the sentence and no word. The sentence's own words are read,
   and anything that is neither plainly permitted nor plainly refused is "check the terms":
   unknown terms are a thing to read, never a thing to trust. */
const TOS_BLOCKED = /\b(forbid|forbids|forbidden|blocked|not permitted|interactive use only)\b/i;
const TOS_LOOK = /\b(high|risk|risks|suspension|check|unknown|could not be confirmed|nobody here has read)\b/i;
const TOS_SAFE = /\b(documented|first-party|open source|no service terms|on this machine|own hardware)\b/i;

function tosKind(row) {
  const said = String((row || {}).tos_kind || "").toLowerCase().trim();
  if (TOS_PILL[said]) return said;
  const terms = String((row || {}).tos || "");
  if (TOS_BLOCKED.test(terms)) return "blocked";
  if (TOS_LOOK.test(terms)) return "check";
  return TOS_SAFE.test(terms) ? "safe" : "check";
}

function tosPill(row) {
  const [meaning, word] = TOS_PILL[tosKind(row)];
  return pill(meaning, word, String((row || {}).tos || ""));
}

/* The one colour on this page that is not a theme token: the provider's own, from the catalog.
   A value from a route reaching a style attribute is an injection surface, so only a plain hex
   colour is let through and anything else falls back to a token. */
function dotStyle(colour) {
  const written = String(colour || "").trim();
  return /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(written)
    ? `background:${written}`
    : "background:var(--text-dim)";
}

/* A model that is failing every call is exactly the one an operator wants to stop, so the
   switch is offered there too. The two statuses left without one are the two where there is
   nothing to switch on: no command on this machine, and no key to run it with. */
function canSwitch(status) {
  return status === "on" || status === "off" || status === "failing";
}

/* Test runs the model for real, so it is offered wherever there is a command to run. A row
   with no key yet is exactly the row a person tests next: they run `fleet models auth` in a
   terminal and come back, and this page cannot see the key land. */
function canTest(status) {
  return status !== "not_installed";
}

function isAdded(model) {
  return String((model || {}).source || "shipped") === "added";
}

/* The rows of a models answer this page can draw. A null in the list is a row the farm could
   not read, and one field read off it emptied the whole card: no table, no Add button, nothing
   but a heading. The rest of the answer is still a catalog worth drawing. */
function modelRows(data) {
  return list(data).filter((row) => row && row.id);
}

function modelById(context, id) {
  return modelRows(context.res("/api/engines").data).find((row) => row.id === id) || null;
}

async function modelAction(context, model, action) {
  local.busy = `${model.id}:${action}`;
  if (action === "test") local.modelTesting = true;
  context.paint();
  try {
    const answer = await apiPost("/api/models", { action, id: model.id });
    if (answer && answer.error) toast(answer.error, "bad");
    else if (action === "test") toast(`${model.label || model.id} was asked to answer.`);
    else toast(`${model.label || model.id} is ${action === "enable" ? "on" : "off"}.`);
  } catch (error) {
    toast(serverReason(error) || `${model.label || model.id} did not answer.`, "bad");
  } finally {
    local.busy = "";
    local.modelTesting = false;
    stopPolling();
    await context.refresh("/api/engines");
  }
}

async function removeModel(context, id) {
  local.modelError = "";
  try {
    await apiPost("/api/models/remove", { id });
    toast(`${id} is gone from this farm's catalog.`);
  } catch (error) {
    local.modelError = serverReason(error) || `${id} could not be removed.`;
  } finally {
    setConfirm(context, "");
    await context.refresh("/api/engines");
    /* Dropped rather than refreshed: the presets are only read while the dialog is open, and
       the next open reads them again, with this row's service choosable once more. */
    context.drop("/api/models/presets");
  }
}

/* The same three actions wherever the model is drawn: in its row, in its drawer, and in the
   last step of the add dialog. Written once, so the three can never drift apart and offer a
   switch in one place and not in another. */
function modelActions(context, model, where) {
  const status = statusOf(model);
  const out = [];
  if (canSwitch(status)) {
    const next = model.enabled ? "disable" : "enable";
    out.push(h("button", {
      key: `${where}:switch`,
      class: "button small",
      "data-model-switch": model.id,
      "aria-pressed": String(Boolean(model.enabled)),
      /* The press this button is about to send, not one of the two: a model that is on sends
         "disable", and guarding against "enable" left the switch live while it worked, so a
         double click sent two real requests. */
      disabled: access.writable && local.busy !== `${model.id}:${next}` ? null : true,
      title: blocked() || `Press to switch ${model.label || model.id} `
        + `${model.enabled ? "off" : "on"}. It sends one real request.`,
      onclick: () => modelAction(context, model, next),
    /* The word on a button is the press it makes, never the state the row is already in: a
       button reading "On" beside a pill reading "Off" is two words for one thing, and the
       server calls a model off until a test passes, so the two really do disagree. */
    }, model.enabled ? "Switch off" : "Switch on"));
  }
  if (canTest(status)) {
    out.push(h("button", {
      key: `${where}:test`,
      class: "ghost-button small",
      "data-model-test": model.id,
      disabled: access.writable && local.busy !== `${model.id}:test` ? null : true,
      title: blocked() || "One real request to the provider.",
      onclick: () => modelAction(context, model, "test"),
    }, local.busy === `${model.id}:test` ? "Testing" : "Test"));
  }
  if (isAdded(model)) {
    out.push(h("button", {
      key: `${where}:remove`,
      class: "ghost-button small",
      "data-model-remove": model.id,
      disabled: access.writable ? null : true,
      title: blocked(),
      onclick: () => setConfirm(context, `remove-model:${model.id}`),
    }, "Remove"));
  }
  if (status === "needs_key") {
    /* The one command that fixes this row, written where the row is. A cell that offered
       Remove and nothing else sent a person back to the dialog to find the command it had
       shown them one step earlier. */
    const command = `fleet models auth ${model.id}`;
    out.push(h("button", {
      key: `${where}:auth`,
      class: "ghost-button small",
      "data-model-auth-hint": model.id,
      title: `Copy the command that stores the key: ${command}`,
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(command);
          toast(`Copied: ${command}. Run it in a terminal, then press Test.`);
        } catch (error) {
          toast(`Run in a terminal: ${command}`, "bad");
        }
      },
    }, "Key command"));
  }
  if (!out.length) {
    out.push(h("span", { key: `${where}:none`, class: "muted" }, "Install it first"));
  }
  return out;
}

function removeModelConfirm(context, id) {
  const model = modelById(context, id) || { id };
  const env = String(model.auth_env || "").trim();
  return h("div", { class: "m-confirm", key: `rm:${id}` },
    h("h3", null, `Remove ${model.label || id}?`),
    h("p", null, `The entry for ${id} is deleted from this farm's catalog, and the key stored `
      /* The variable by name: "the key stored for it" is not something a person can check, and
         this is the sentence they read before deleting a credential. */
      + (env ? `for it with fleet models auth (the one read as ${env}) is deleted with it. ` : "for it with fleet models auth is deleted with it. ")
      + "No agent can be spawned with it again until it is added back."),
    h("p", { class: "muted" }, "Nothing else on the farm is touched, and no lane that already "
      + "ran on it is changed."),
    h("div", { class: "row" },
      h("button", {
        class: "button primary",
        "data-confirm": `remove-model:${id}`,
        disabled: access.writable ? null : true,
        title: blocked(),
        onclick: () => removeModel(context, id),
      }, "Yes, remove it"),
      h("button", {
        class: "ghost-button",
        onclick: () => setConfirm(context, ""),
      }, "Keep it")));
}

/* What the model runs, as the reader would type it. A model that is not on this machine says
   so and shows the one line that installs it: a page that assumed every catalog row was
   installed offered to switch on a command that is not there. */
function runsAs(model) {
  if (model.installed === false) {
    /* One row, one state, said once: "Not installed" is the Status pill's word. This cell
       carries the one thing the pill cannot, the command that puts it on this farm. */
    const hint = model.install_hint || `install ${model.command || model.id}`;
    return h("code", { class: "cmd", key: "hint", title: `Not on this farm's PATH. Install it with: ${hint}` }, hint);
  }
  return h("span", { class: "mono" }, model.path || model.command || "on the path");
}

function modelRow(context, model) {
  const status = statusOf(model);
  const [meaning, label] = STATUS[status];
  const detail = String(model.health_detail || "");
  return h("tr", { key: model.id },
    h("td", null, h("button", {
      class: "m-model-name",
      "data-model-open": model.id,
      title: "Open what this model is for, and its terms.",
      onclick: () => openModelDrawer(context, model.id),
    },
    h("span", { class: "m-dot", style: dotStyle(model.color), "aria-hidden": "true" }),
    h("span", { class: "m-model-words" },
      h("b", null, model.label || model.id),
      h("span", { class: "muted mono m-id" }, model.id)))),
    /* Every cell but the name carries the name of its column. On a phone the table is a card
       list, the header row is gone, and this attribute is what each line is called there. */
    h("td", { class: "m-runs", "data-col": "Runs as" }, runsAs(model)),
    h("td", { "data-col": "Access", title: accessOf(model) }, accessOf(model)),
    /* One line, one word: a failing model's reason is the pill's title and the drawer's
       first row, not a second line that made this row taller than its neighbours. */
    h("td", { "data-col": "Status" }, pill(meaning, label, detail)),
    h("td", { class: "num", "data-col": "Last test" },
      model.last_test ? fmt.ago(model.last_test) : "never"),
    h("td", { "data-col": "Actions" },
      h("div", { class: "row m-row-actions" }, modelActions(context, model, "row"))));
}

/* ------------------------------------------------------- one model, in full */

function detailRow(label, value) {
  if (!value) return null;
  return [
    h("dt", { key: `dt:${label}` }, label),
    h("dd", { key: `dd:${label}` }, value),
  ];
}

function modelDrawerBody(context, id) {
  const model = modelById(context, id);
  if (!model) {
    return h("p", { class: "muted" },
      `${id} is no longer in this farm's catalog.`);
  }
  const link = safeHref(model.docs);
  const status = statusOf(model);
  const [meaning, label] = STATUS[status];
  return [
    h("div", { class: "row m-wait", key: "status" },
      pill(meaning, label, model.health_detail || ""),
      h("span", { class: "muted" }, accessOf(model))),
    h("dl", { class: "kv m-detail-list", key: "facts" },
      detailRow("What it is for", model.role),
      detailRow("Quality", model.quality),
      detailRow("Limits", model.caps || model.limits),
      detailRow("Terms", model.tos),
      detailRow("Variant", model.variant),
      detailRow("Reads its key from", model.auth_env
        ? h("span", { class: "mono" }, model.auth_env)
        : "Nothing. It runs on a subscription already logged in on this farm."),
      detailRow("Where it came from", isAdded(model)
        ? "Added on this farm, so it can be removed."
        : "Shipped with the farm, so it can only be switched off."),
      detailRow("Documentation", link
        ? h("a", { href: link, target: "_blank", rel: "noreferrer noopener" }, link)
        : null)),
    model.run
      ? h("div", { key: "run" },
        h("p", { class: "muted" }, "The line a lane runs. {bin} is the command, {task} is the brief:"),
        h("code", { class: "cmd", "data-model-run": "" }, model.run))
      : null,
    h("div", { class: "row m-dialog-actions", key: "actions" },
      modelActions(context, model, "drawer")),
    readOnlyLine("ro-model-drawer"),
  ];
}

function openModelDrawer(context, id) {
  const model = modelById(context, id) || { id };
  openDrawer({
    key: `model:${id}`,
    title: model.label || id,
    sub: `${id}: what it is for, what it costs, and how it runs.`,
    body: () => modelDrawerBody(context, id),
  });
}

/* ---------------------------------------------------------- adding a model */

/* Adding a model is the accounts dialog's pattern, step for step: numbered steps down the
   drawer, one thing to do in each, and the commands that touch a credential kept where they
   belong, in a terminal. Nothing here ever asks for a key. */
const ADD_MODEL_KEY = "add-model";

const KIND_WORD = {
  subscription: "A subscription you already pay for.",
  key: "An API key you hold.",
  local: "Weights on this machine.",
};

function presetById(context, id) {
  return list(context.res("/api/models/presets").data).find((row) => row && row.id === id) || null;
}

function choosePreset(context, preset) {
  local.modelPreset = preset.id;
  local.modelId = preset.id === "custom" ? "" : preset.id;
  local.modelVariant = list(preset.variants)[0] || "";
  local.modelBin = preset.bin || "";
  local.modelRun = preset.run || "";
  local.modelEnv = preset.auth_env || "";
  local.addModelError = "";
  context.paint();
}

function stepHead(number, title, note) {
  return h("div", { class: "m-dialog-step", key: `head${number}` },
    h("div", { class: "m-step-no" }, String(number)),
    h("div", null,
      h("h3", null, title),
      note ? h("p", { class: "muted" }, note) : null));
}

function commandRow(command, mark, key) {
  return h("div", { class: "m-cmd-row", key: key || `cmd:${mark}` },
    h("code", { class: "cmd", [`data-${mark}`]: "" }, command),
    h("button", {
      class: "button small",
      onclick: () => copyCommand(command),
    }, "Copy"));
}

function presetCards(context, presets) {
  return h("div", { class: "m-presets", role: "radiogroup", "aria-label": "Service", key: "presets" },
    presets.map((preset) => {
      const chosen = local.modelPreset === preset.id;
      const added = Boolean(preset.added);
      return h("button", {
        key: preset.id,
        type: "button",
        class: "choice m-preset" + (chosen ? " chosen" : ""),
        role: "radio",
        "aria-checked": String(chosen),
        "data-preset": preset.id,
        disabled: added || !access.writable ? true : null,
        title: added
          ? `${preset.label || preset.id} is already in this farm's catalog.`
          : blocked(),
        onclick: () => choosePreset(context, preset),
      },
      h("div", { class: "m-preset-head" },
        h("span", { class: "m-dot", style: dotStyle(preset.color), "aria-hidden": "true" }),
        h("b", null, preset.label || preset.id),
        added ? pill("pause", "already added", "") : tosPill(preset)),
      h("div", { class: "muted" }, accessOf(preset)),
      h("div", { class: "muted" }, KIND_WORD[preset.kind] || ""));
    }));
}

/* Step two: the name it goes into the catalog under, the variant when the service sells more
   than one, and, for a command of your own, the three things only you can know. */
function nameStep(context, preset) {
  const custom = preset.id === "custom";
  const variants = list(preset.variants);
  return [
    stepHead(2, "Name it", custom
      ? "A short id for the catalog, plus the command and the line that runs it."
      : "A short id for the catalog. The preset's own name is filled in; change it if you run two."),
    h("label", { class: "m-field", key: "name" },
      h("span", { class: "m-label" }, "Name"),
      h("input", {
        type: "text",
        class: "m-name",
        "aria-label": "Model name",
        "data-model-id": "",
        placeholder: custom ? "my-model" : preset.id,
        autocomplete: "off",
        spellcheck: "false",
        value: local.modelId,
        disabled: access.writable ? null : true,
        oninput: (event) => {
          local.modelId = event.target.value;
          local.addModelError = "";
        },
      })),
    variants.length
      ? h("label", { class: "m-field", key: "variant" },
        h("span", { class: "m-label" }, "Which model"),
        h("select", {
          class: "m-name",
          "aria-label": "Model variant",
          "data-model-variant": "",
          value: local.modelVariant,
          disabled: access.writable ? null : true,
          onchange: (event) => {
            local.modelVariant = event.target.value;
            context.paint();
          },
        }, variants.map((name) => h("option", {
          key: name, value: name, selected: local.modelVariant === name,
        }, name))))
      : null,
    custom
      ? [
        h("p", { class: "muted", key: "tpl" },
          "In the line below, {bin} is the command above and {task} is the brief the lane is "
          + "given. The farm writes both in before it runs anything."),
        h("label", { class: "m-field", key: "bin" },
          h("span", { class: "m-label" }, "Command"),
          h("input", {
            type: "text",
            class: "m-name",
            "aria-label": "Command",
            "data-model-bin": "",
            placeholder: "my-cli",
            autocomplete: "off",
            spellcheck: "false",
            value: local.modelBin,
            disabled: access.writable ? null : true,
            oninput: (event) => {
              local.modelBin = event.target.value;
              local.addModelError = "";
            },
          })),
        h("label", { class: "m-field", key: "run" },
          h("span", { class: "m-label" }, "How to run it"),
          h("input", {
            type: "text",
            class: "m-name",
            "aria-label": "Run template",
            "data-model-run-template": "",
            placeholder: "{bin} -p {task}",
            autocomplete: "off",
            spellcheck: "false",
            value: local.modelRun,
            disabled: access.writable ? null : true,
            oninput: (event) => {
              local.modelRun = event.target.value;
              local.addModelError = "";
            },
          })),
        h("label", { class: "m-field", key: "env" },
          h("span", { class: "m-label" }, "Key is read from"),
          h("input", {
            type: "text",
            class: "m-name",
            "aria-label": "Key environment variable",
            "data-model-env": "",
            placeholder: "MY_MODEL_API_KEY",
            autocomplete: "off",
            spellcheck: "false",
            value: local.modelEnv,
            disabled: access.writable ? null : true,
            oninput: (event) => {
              local.modelEnv = event.target.value;
              local.addModelError = "";
            },
          })),
      ]
      : null,
  ];
}

/* Step three: how this one gets its credential. Three services, three different answers, and
   in none of them does a key pass through this page. */
/* The farm's own ssh name, from the server; "farm" only on a server too old to send one. */
function farmAlias(context) {
  const config = context.res("/api/config").data || {};
  return String(config.farm_alias || "").trim() || "farm";
}

function accessStep(context, preset) {
  const name = (local.modelId || preset.id || "the model").trim();
  const binary = local.modelBin || preset.bin || name;
  if (preset.kind === "subscription") {
    return [
      stepHead(3, "Log it in", "A subscription is logged in once, in a terminal on your own "
        + "machine, not on this page. Run:"),
      commandRow(`ssh -t ${farmAlias(context)} ${binary}`, "model-login"),
      h("ol", { key: "steps" },
        h("li", { key: "1" }, "Run the command from wherever you reach this farm"),
        h("li", { key: "2" }, "In the window it opens, type /login"),
        h("li", { key: "3" }, "Choose the account that holds the subscription"),
        h("li", { key: "4" }, "Type /exit, then come back here")),
    ];
  }
  if (preset.kind === "local") {
    /* The pull command is the preset's own, with the model chosen in step 2 written into it.
       A line this page built itself ("{bin} pull {variant}") matched Ollama by luck and would
       be wrong for the next local runner a farm adds. */
    const wanted = local.modelVariant || name;
    const hint = String(preset.pull_hint || "").trim();
    const pull = hint
      ? hint.replace(/<variant>|\{variant\}/g, wanted)
      : `${binary} pull ${wanted}`;
    return [
      stepHead(3, "Install it and pull the weights", "Nothing is paid and nothing leaves this "
        + "machine. Two commands, in a terminal on the farm:"),
      commandRow(preset.install_hint || `install ${binary}`, "model-install"),
      commandRow(pull, "model-pull"),
      h("p", { class: "muted", key: "note" },
        "The pull is the slow one. It can be running while you finish here."),
    ];
  }
  /* The command is the model's own name, so there is no command to show until the name is
     typed. Falling back to the preset's id printed "fleet models auth custom", a command that
     looks runnable and is not. */
  const named = local.modelId.trim();
  return [
    stepHead(3, "Give it a key", named
      ? "The farm asks for the key on the command line and holds it itself. Run:"
      : "The command carries the name you give it in step 2. Name it, and it appears here."),
    named ? commandRow(`fleet models auth ${named}`, "model-auth") : null,
    named ? h("p", { key: "paste" }, "Paste the key when it asks.") : null,
    h("p", { class: "m-keyline", key: "never" }, "A key never goes through this page."),
  ];
}

/* The farm's own rule for a model id, which is the only rule that decides: lib/models.py
   writes the name as a TOML table. A page that taught a looser one let "Gemini", "my.model"
   and a thirty-five character name through to a refusal nobody could have predicted. */
const MODEL_ID_RE = /^[a-z][a-z0-9_-]{1,30}$/;
const MODEL_ID_RULE = "A model id is lower case letters, digits, - and _, starting with a "
  + "letter, 2 to 31 characters.";

function validateModel(preset) {
  const name = local.modelId.trim();
  if (!name) return "Give the model a name, for example gemini.";
  if (!MODEL_ID_RE.test(name)) return `${MODEL_ID_RULE} ${name} is not one.`;
  if (preset.id === "custom" && !local.modelBin.trim()) {
    return "A command of your own needs the command to run, for example my-cli.";
  }
  if (preset.id === "custom" && !local.modelRun.trim()) {
    return "A command of your own needs the line that runs it, with {bin} and {task} in it.";
  }
  return "";
}

async function registerModel(context, preset) {
  const problem = validateModel(preset);
  if (problem) {
    local.addModelError = problem;
    context.paint();
    return;
  }
  local.addModelError = "";
  local.modelBusy = true;
  context.paint();
  /* The body carries the name of the variable a key is read from, never a key. The server
     refuses a body that carries one, and this page must never be the reason it has to. */
  const body = { preset: preset.id, id: local.modelId.trim() };
  if (local.modelVariant) body.variant = local.modelVariant;
  if (preset.id === "custom") {
    body.bin = local.modelBin.trim();
    body.run = local.modelRun.trim();
    if (local.modelEnv.trim()) body.auth_env = local.modelEnv.trim();
  }
  try {
    const answer = await apiPost("/api/models/add", body);
    /* The server answers {"model": row}. Reading the row off the envelope's top level left the
       seed null on a real farm, so the last step fell back to "this farm has not listed it back
       yet" for as long as the table's own refresh lagged. A bare row is still read, for a farm
       on an older build. */
    const row = (answer && answer.model) || answer;
    local.modelRowSeed = row && row.id ? row : null;
    local.modelAdded = (row && row.id) || body.id;
    await context.refresh("/api/engines");
    context.refresh("/api/models/presets");
    /* Section 11, step 4: the dialog runs the test itself once the row exists, so the reader
       sees an answer without pressing anything. A row that cannot be tested yet (no binary, no
       key) is left at its status word, which says what to do next. */
    const fresh = modelById(context, local.modelAdded) || row;
    const status = fresh && fresh.id ? statusOf(fresh) : "";
    if (status && status !== "not_installed" && status !== "needs_key") {
      pollWhileTesting(context);
      await modelAction(context, fresh, "test");
    }
  } catch (error) {
    local.addModelError = serverReason(error) || "The farm did not write this model to its catalog.";
  } finally {
    local.modelBusy = false;
    context.paint();
  }
}

/* A test is one real request to a provider and can take a while. The page's own tick is three
   seconds and only repaints; this asks for the row again every two, on its own clock, because
   the flip from "asking" to an answer is the single thing the reader is waiting for. */
function pollWhileTesting(context) {
  if (local.modelPoll) return;
  local.modelPoll = setInterval(() => {
    if (!local.modelTesting) {
      clearInterval(local.modelPoll);
      local.modelPoll = 0;
      return;
    }
    context.refresh("/api/engines");
  }, 2000);
}

function stopPolling() {
  if (!local.modelPoll) return;
  clearInterval(local.modelPoll);
  local.modelPoll = 0;
}

/* The last step, after the catalog was written: what the farm now says about this row, the
   two things worth doing to it at once, and the door. */
function registeredStep(context) {
  const model = modelById(context, local.modelAdded) || local.modelRowSeed;
  if (!model) {
    return h("p", { class: "muted", key: "gone" },
      `${local.modelAdded} was registered, and this farm has not listed it back yet.`);
  }
  if (local.modelTesting) pollWhileTesting(context);
  const status = statusOf(model);
  const [meaning, label] = STATUS[status];
  /* A key service ends the dialog with one thing left to do, and it happens in a terminal.
     Saying "come back later" there left the person on the step that mattered with no command
     on it and no way to finish. */
  const keyed = status === "needs_key";
  return h("div", { class: "m-steps", key: "done" },
    stepHead(4, `${model.label || model.id} is in the catalog`,
      keyed
        ? "It is written to this farm's model list. It has no key yet: run "
          + `fleet models auth ${model.id} in a terminal, then press Test.`
        : "It is written to this farm's model list. Test it, switch it on, or come back later."),
    keyed ? commandRow(`fleet models auth ${model.id}`, "model-auth", "auth") : null,
    h("div", { class: "row m-wait", key: "state" },
      pill(meaning, label, model.health_detail || ""),
      h("span", { class: "muted" }, local.modelTesting
        ? "Asking the provider to answer. This page is watching for the result."
        : accessOf(model))),
    h("div", { class: "row m-dialog-actions", key: "acts" },
      modelActions(context, model, "added"),
      h("button", {
        class: "button primary",
        "data-model-done": "",
        onclick: () => closeDrawer(),
      }, "Done")),
    readOnlyLine("ro-model-added"));
}

function addModelSteps(context, presets) {
  const preset = presetById(context, local.modelPreset);
  return h("div", { class: "m-steps", key: "steps" },
    stepHead(1, "Pick a service", "What the agents would be spawned with. A service already in "
      + "this farm's catalog cannot be added twice."),
    presetCards(context, presets),
    preset ? nameStep(context, preset) : null,
    preset ? accessStep(context, preset) : null,
    preset ? stepHead(4, "Register it", "This writes the entry to this farm's model catalog. "
      + "Nothing is spawned and nothing is spent.") : null,
    local.addModelError
      ? h("p", { class: "m-bad", key: "err", role: "alert" }, local.addModelError) : null,
    h("div", { class: "row m-dialog-actions", key: "actions" },
      h("button", {
        class: "button primary",
        "data-model-register": "",
        disabled: access.writable && preset && !local.modelBusy ? null : true,
        title: blocked() || (preset ? "" : "Pick a service first."),
        onclick: () => registerModel(context, preset),
      }, local.modelBusy ? "Writing the catalog" : "Register"),
      h("button", { class: "ghost-button", onclick: () => closeDrawer() }, "Cancel")),
    readOnlyLine("ro-model-add"));
}

function addModelBody(context) {
  const resource = context.watch("/api/models/presets");
  if (local.modelAdded) return registeredStep(context);
  return panel(resource, {
    loading: () => skeletonStack(4),
    isEmpty: (data) => !list(data).length,
    empty: () => emptyState({
      title: "This farm offers no services to add",
      body: "A preset is a service the server knows how to write into the catalog.",
      command: "fleet models",
    }),
    ready: (data) => addModelSteps(context, list(data)),
  });
}

function openAddModel(context) {
  local.modelPreset = "";
  local.modelId = "";
  local.modelVariant = "";
  local.modelBin = "";
  local.modelRun = "";
  local.modelEnv = "";
  local.addModelError = "";
  local.modelBusy = false;
  local.modelAdded = "";
  local.modelRowSeed = null;
  local.modelTesting = false;
  openDrawer({
    key: ADD_MODEL_KEY,
    title: "Add a model",
    sub: "A model the agents can be spawned with.",
    body: () => addModelBody(context),
    onClose: () => {
      local.modelAdded = "";
      local.modelRowSeed = null;
      local.addModelError = "";
      local.modelTesting = false;
      stopPolling();
      context.refresh("/api/engines");
      /* The presets are a static list read by this dialog alone, so the page stops asking for
         them when the dialog shuts. Left in the watch list they were re-fetched on every tick
         for as long as Machine was open. */
      context.drop("/api/models/presets");
    },
  });
}

function modelsSection(context) {
  const resource = context.res("/api/engines");
  const removing = local.confirm.startsWith("remove-model:");
  /* The same footer under a full table and under an empty one. A farm with nothing registered
     is exactly the farm that needs the Add button, and hiding it there left a new operator
     with a sentence and no way to act on it. */
  const footer = () => h("div", { class: "card-pad", key: "add" },
    removing
      ? removeModelConfirm(context, local.confirm.slice("remove-model:".length))
      : h("button", {
        class: "button small",
        "data-add-model": "",
        disabled: access.writable ? null : true,
        title: blocked(),
        onclick: () => openAddModel(context),
      }, "Add a model"),
    h("p", { class: "muted", key: "note" },
      "A provider key is given on the command line, never in a web form: "
      + "fleet models auth <id>."),
    local.modelError ? h("p", { class: "m-bad", key: "err" }, local.modelError) : null,
    readOnlyLine("ro-models"));
  return h("section", { class: "section", key: "models" },
    sectionHead("Models", "What the agents can be spawned with."),
    card({ key: "models", "data-write": "" }, panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(3)),
      isEmpty: (data) => !modelRows(data).length,
      empty: () => [
        h("div", { class: "card-pad", key: "none" }, emptyState({
          title: "No models registered",
          body: "A model is the command an agent runs. Add one to spawn with it.",
          command: "fleet models",
        })),
        footer(),
      ],
      ready: (data) => [
        h("div", { class: "tablewrap", key: "table" }, h("table", { class: "m-models" },
          h("thead", null, h("tr", null,
            h("th", null, "Model"),
            h("th", null, "Runs as"),
            h("th", null, "Access"),
            h("th", null, "Status"),
            h("th", null, "Last test"),
            h("th", null, "Actions"))),
          h("tbody", null, modelRows(data).map((model) => modelRow(context, model))))),
        footer(),
      ],
    })));
}

/* ------------------------------------------------------------------ projects */

function ports(row) {
  const block = (row && row.ports) || {};
  const parts = [["web", block.web], ["api", block.api], ["e2e", block.e2e]]
    .filter(([, value]) => value != null)
    .map(([name, value]) => `${name} ${value}`);
  return parts.length ? parts.join(", ") : "none";
}

async function addProject(context, suggestion) {
  const name = local.projectName.trim();
  const repo = local.projectRepo.trim();
  const typed = String(local.projectPort || "").trim();
  const base = Number(typed);
  if (!name || !repo) {
    local.projectError = "A project needs a name and a repository, for example demo and your-org/demo.";
    context.paint();
    return;
  }
  /* The port block is checked here as the name and the repository are: a field that reads
     "not a port" was posted as port_base null, and the registry was asked to make sense of it. */
  if (typed && (!Number.isInteger(base) || base <= 0)) {
    local.projectError = `A port block is a whole number, for example ${suggestion || 5200}. `
      + "Leave the field empty to take the farm's own next free block.";
    context.paint();
    return;
  }
  local.projectError = "";
  /* An empty field sends no port block at all, so the farm hands out the next free one itself.
     The page used to put its own arithmetic in the field instead, and that number was worked
     out of every port in the table, the api and end-to-end bases included. */
  const wanted = typed ? { name, repo, port_base: base } : { name, repo };
  /* Registering clones the repository, so the server answers with a job (amendment 7). The
     form clears once the job is accepted and the table refreshes when the job ends; a second
     press while it runs is refused, here and by the server. */
  const before = local.jobError;
  await startJob(context, "add_project", wanted, "/api/projects");
  if (local.jobs.add_project) {
    local.projectName = "";
    local.projectRepo = "";
    local.projectPort = "";
    toast(`${name} is being registered; the row appears when the clone finishes.`);
  } else if (local.jobError && local.jobError !== before) {
    local.projectError = local.jobError.replace(/^add_project: /, "");
    local.jobError = before;
  }
  context.paint();
}

async function removeProject(context, name) {
  try {
    const answer = await apiPost("/api/projects/remove", { name });
    /* The block the server says is free, under the name the server sends it in. Reading a key
       nothing sends left the message saying only "the ports it held". */
    toast(`${name} is out of the registry. Ports ${(answer && answer.freed) || "it held"} are free.`);
    setConfirm(context, "");
    local.projectError = "";
  } catch (error) {
    local.projectError = serverReason(error) || `${name} was not removed.`;
  } finally {
    await context.refresh("/api/projects");
    context.paint();
  }
}

function removeProjectConfirm(context, rows, name) {
  const row = rows.find((item) => item.name === name) || {};
  const open = Number(row.lanes_open) || 0;
  return h("div", { class: "m-confirm", key: "removeProject" },
    h("h3", null, `Remove ${name}`),
    open
      ? h("p", null, `${name} has ${open} open ${open === 1 ? "lane" : "lanes"}. `
        + "The farm refuses to remove a project while a lane is open in it. Stop them first.")
      : [h("p", { key: "one" },
        `This edits the registry only. The worktrees on disk are left exactly where they are.`),
        h("p", { key: "two" }, `The port block ${ports(row)} becomes free for the next project.`)],
    h("div", { class: "row" },
      open ? null : h("button", {
        class: "button primary",
        "data-confirm": `remove-project:${name}`,
        disabled: access.writable ? null : true,
        title: blocked(),
        onclick: () => removeProject(context, name),
      }, "Yes, remove it"),
      h("button", {
        class: "ghost-button",
        onclick: () => setConfirm(context, ""),
      }, open ? "Close" : "Keep it")));
}

function projectsSection(context) {
  const resource = context.res("/api/projects");
  const rows = list(resource.data);
  /* The suggestion is the farm's, read from its own registry, never this page's arithmetic. */
  const port = context.res("/api/projects/next-port").data || {};
  const suggestion = port.next_port_base;
  /* Registering clones a repository, so it runs as a job, and the control that started it
     stays off until that job ends. Read here rather than inside the panel, so the job is
     watched on every paint and not only while the table is drawn. */
  const job = jobFor(context, "add_project");
  const adding = Boolean(job && job.state === "running");
  return h("section", { class: "section", key: "projects" },
    sectionHead("Projects", "The repositories a lane may be opened in."),
    card({ key: "projects", "data-write": "" }, panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(3)),
      isEmpty: (data) => !list(data).length,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: "No projects yet",
        body: "A project tells the farm which repository a lane may work in.",
        command: "fleet add-project --name <name> --repo <owner>/<repo>",
      })),
      ready: (data) => [
        h("div", { class: "tablewrap", key: "table" }, h("table", null,
          h("thead", null, h("tr", null,
            h("th", null, "Project"),
            h("th", null, "Repository"),
            h("th", null, "Base branch"),
            h("th", null, "Ports"),
            h("th", { class: "num" }, "Lanes open"),
            h("th", null, ""))),
          h("tbody", null, list(data).map((row) => h("tr", { key: row.name },
            h("td", null, row.name),
            h("td", null, row.repo || "none"),
            h("td", null, row.base_branch || "none"),
            h("td", { class: "mono" }, ports(row)),
            h("td", { class: "num" }, fmt.num(row.lanes_open, "0")),
            h("td", null, h("button", {
              class: "ghost-button small",
              "data-remove-project": row.name,
              disabled: access.writable ? null : true,
              title: blocked(),
              onclick: () => setConfirm(context, `remove-project:${row.name}`),
            }, "Remove"))))))),
        h("div", { class: "card-pad", key: "add" },
          local.confirm.startsWith("remove-project:")
            ? removeProjectConfirm(context, rows, local.confirm.slice("remove-project:".length))
            : h("div", { class: "m-form" },
              h("div", { class: "row" },
                h("input", {
                  type: "text",
                  "aria-label": "Project name",
                  placeholder: "name",
                  disabled: access.writable ? null : true,
                  value: local.projectName,
                  oninput: (event) => {
                    local.projectName = event.target.value;
                  },
                }),
                h("input", {
                  type: "text",
                  "aria-label": "Repository",
                  placeholder: "owner/repo",
                  disabled: access.writable ? null : true,
                  value: local.projectRepo,
                  oninput: (event) => {
                    local.projectRepo = event.target.value;
                  },
                }),
                h("input", {
                  type: "text",
                  class: "m-port",
                  "aria-label": "Port base",
                  placeholder: suggestion ? String(suggestion) : "port block",
                  disabled: access.writable ? null : true,
                  value: local.projectPort,
                  oninput: (event) => {
                    local.projectPort = event.target.value;
                  },
                }),
                h("button", {
                  class: "button primary",
                  "data-add-project": "",
                  disabled: access.writable && !adding ? null : true,
                  title: blocked(),
                  onclick: () => addProject(context, suggestion),
                }, adding ? "Adding" : "Add")),
              adding ? h("p", { class: "muted", key: "job" },
                `Job ${job.id} is running: ${job.detail || "registering the project"}.`) : null,
              h("p", { class: "muted" }, port.sentence
                || "Leave the port field empty and the farm gives this project its next free "
                + "block.")),
          local.projectError ? h("p", { class: "m-bad" }, local.projectError) : null,
          readOnlyLine("ro-projects")),
      ],
    })));
}

/* -------------------------------------------------------------------- health */

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

/* ------------------------------------------------------------------ settings */

function settingRow(label, value, file) {
  return [
    h("dt", { key: `dt:${label}` }, label),
    h("dd", { key: `dd:${label}` },
      h("div", null, value),
      file ? h("div", { class: "muted mono" }, file) : null),
  ];
}

function settingsSection(context) {
  const config = context.config || {};
  const settings = config.settings || {};
  const sweep = context.watch("/api/sweep").data || {};
  const token = settings.token || {};
  const known = (name, fallback) => (settings[name] && settings[name].value) || fallback;
  const file = (name) => (settings[name] && settings[name].file) || "not reported by this server";
  return h("section", { class: "section", key: "settings" },
    sectionHead("Settings", "Read here, written where they live. This page never writes them."),
    card({ class: "card-pad", key: "settings" },
      h("dl", { class: "kv m-settings" },
        settingRow("Product name", known("product_name", config.title || "murmur"), file("product_name")),
        settingRow("Mail identity", known("mail_identity", config.hq_agent || "dashboard"), file("mail_identity")),
        settingRow("Bind", known("bind", access.loopback ? "127.0.0.1" : "not reported"), file("bind")),
        settingRow("Port", known("port", "not reported"), file("port")),
        settingRow("Write token", token.present === false
          ? "Absent, so this page can only read."
          : token.present === true ? "Present. Its value is never shown here."
            : access.writable ? "This page holds one." : "This page holds none.",
        token.file || "~/.fleet/dash-token"),
        settingRow("Sweep", known("sweep_interval", sweep.enabled === false
          ? "Off on this machine" : "On"), file("sweep_interval")),
        settingRow("Respawn limits", known("respawn_limits", "not reported"), file("respawn_limits"))),
      h("p", { class: "muted", key: "tokencmd" }, "To mint a token and pick it up:"),
      h("code", { class: "cmd", key: "cmd1" }, "fleet dashboard token"),
      h("code", { class: "cmd", key: "cmd2" }, "fleet dashboard restart")));
}

/* --------------------------------------------------------------------- the view */

export default {
  id: "machine",
  title: "Machine",
  needs: [
    "/api/mode", "/api/services", "/api/accounts", "/api/accounts/login-state",
    "/api/engines", "/api/projects", "/api/projects/next-port", "/api/health", "/api/metrics",
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
      accountsSection(context),
      modelsSection(context),
      projectsSection(context),
      /* Off unless the farm sets FLEET_DASH_HEALTH=on: its tiles read hardware sensors most
         machines do not have. */
      context.features.health_panel ? healthSection(context) : null,
      settingsSection(context),
    ];
  },
};

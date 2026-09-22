/* Machine: the control room. Everything about this farm as a machine lives here, in the order
   a person needs it: power first, then the services that do the work, then the accounts and
   engines they spend, then the projects they work in, then whether anything is missing, then
   the settings and where each one is written. Every action says what it will do before it does
   it, and the dashboard says plainly that it keeps running through all of them. */

import {
  h, card, panel, pill, emptyState, skeletonStack, toast, widthStyle,
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
  addName: "",
  addEngine: "claude",
  addStep: null,
  addError: "",
  refreshedAt: 0,
  projectName: "",
  projectRepo: "",
  projectPort: "",
  projectError: "",
  sectionError: "",
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
            h("td", { class: "wrap" }, row.what || ""),
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
  return h("div", { class: "m-limits" }, rows.map((row) => h("div", { class: "m-limit", key: row.name },
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
  return h("div", { class: "m-login" },
    pill(meaning, word, sentence),
    sentence ? h("span", { class: "muted" }, sentence) : null);
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

async function startAdd(context) {
  const name = local.addName.trim();
  if (local.addEngine !== "codex" && !name) {
    local.addError = "An account needs a name, for example farm-three.";
    context.paint();
    return;
  }
  local.addError = "";
  try {
    local.addStep = await apiPost("/api/accounts/add", { name, engine: local.addEngine });
  } catch (error) {
    local.addError = serverReason(error) || "The farm did not answer with a command to run.";
  } finally {
    context.paint();
  }
}

/* The step panel: the exact command, the steps in order, and a state that flips to "logged in"
   by itself when the credentials file appears. Nobody has to press anything to find out. */
function addSteps(context) {
  const step = local.addStep;
  const states = list((context.res("/api/accounts/login-state").data || {}).accounts);
  const found = states.find((row) => row.name === step.name);
  const waiting = !found || found.state !== "logged_in";
  return h("div", { class: "m-steps", key: "steps" },
    h("h3", null, `Add ${step.name}`),
    h("p", null, "Run this where you reach the farm from:"),
    h("code", { class: "cmd" }, step.command || ""),
    h("ol", null, list(step.steps).map((line, index) => h("li", { key: index }, line))),
    h("div", { class: "row" },
      pill(waiting ? "wait" : "done",
        waiting ? "Waiting for the first login" : "Logged in",
        (found && found.sentence) || ""),
      h("span", { class: "muted" }, waiting
        ? "This turns itself into logged in as soon as the credentials file appears."
        : "The account is ready to be spent."),
      h("div", { class: "spacer" }),
      h("button", {
        class: "button",
        "data-add-done": "",
        onclick: () => {
          local.addStep = null;
          local.addOpen = false;
          local.addName = "";
          context.refresh("/api/accounts");
        },
      }, "Done")));
}

function addAccount(context) {
  if (local.addStep) return addSteps(context);
  if (!local.addOpen) {
    return h("button", {
      class: "button small",
      "data-add-account": "",
      disabled: access.writable ? null : true,
      title: blocked(),
      onclick: () => {
        local.addOpen = true;
        context.paint();
      },
    }, "Add an account");
  }
  return h("div", { class: "m-form", key: "addform" },
    h("div", { class: "row" },
      h("input", {
        type: "text",
        "aria-label": "Account name",
        placeholder: "name",
        value: local.addName,
        disabled: access.writable ? null : true,
        oninput: (event) => {
          local.addName = event.target.value;
        },
      }),
      h("label", { class: "field" },
        h("span", { class: "sr-only" }, "Engine"),
        h("select", {
          "aria-label": "Engine",
          value: local.addEngine,
          disabled: access.writable ? null : true,
          onchange: (event) => {
            local.addEngine = event.target.value;
            context.paint();
          },
        }, list(context.res("/api/engines").data).map((model) => h("option", {
          key: model.id, value: model.id, selected: local.addEngine === model.id,
        }, model.label || model.id)))),
      h("button", {
        class: "button primary",
        "data-add-start": "",
        disabled: access.writable ? null : true,
        onclick: () => startAdd(context),
      }, "Next"),
      h("button", {
        class: "ghost-button",
        onclick: () => {
          local.addOpen = false;
          local.addError = "";
          context.paint();
        },
      }, "Cancel")),
    local.addError ? h("p", { class: "m-bad" }, local.addError) : null);
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
            h("td", { class: "wrap" }, loginCell(states, account.name)),
            h("td", { class: "wrap" }, windowBars(account)),
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

/* ------------------------------------------------------------------- engines */

async function engineAction(context, model, action) {
  local.busy = `${model.id}:${action}`;
  context.paint();
  try {
    const answer = await apiPost("/api/models", { action, id: model.id });
    if (answer && answer.error) toast(answer.error, "bad");
    else toast(action === "test" ? `${model.label || model.id} was asked to answer.`
      : `${model.label || model.id} is ${action === "enable" ? "on" : "off"}.`);
  } catch (error) {
    toast(serverReason(error) || `${model.label || model.id} did not answer.`, "bad");
  } finally {
    local.busy = "";
    await context.refresh("/api/engines");
  }
}

function engineRow(context, model) {
  /* Installed is a fact the server reads off this machine. Assuming it when nothing says so
     put an On and Off switch on an engine whose command is not there, and the row told the
     reader that a command that does not exist is "on the path". */
  const installed = Boolean(model.installed);
  const health = model.health === "ok" ? "done" : model.health === "fail" ? "fail" : "pause";
  const healthWord = model.health === "ok" ? "Answered"
    : model.health === "fail" ? "Did not answer" : "Not tested";
  return h("tr", { key: model.id },
    h("td", null, model.label || model.id),
    h("td", { class: "wrap" }, installed
      ? h("span", { class: "mono" }, model.path || "on the path")
      : [h("span", { class: "muted", key: "no" }, "Not installed. "),
        h("code", { class: "cmd", key: "hint" }, model.install_hint || `install ${model.id}`)]),
    h("td", null, installed
      ? h("button", {
        class: "button small",
        "data-engine-switch": model.id,
        "aria-pressed": String(Boolean(model.enabled)),
        /* The press this button is about to send, not one of the two: an engine that is on
           sends "disable", and guarding against "enable" left the switch live while it worked,
           so a double click sent two real requests. */
        disabled: access.writable
          && local.busy !== `${model.id}:${model.enabled ? "disable" : "enable"}` ? null : true,
        title: blocked() || `Press to switch ${model.label || model.id} `
          + `${model.enabled ? "off" : "on"}. It sends one real request.`,
        onclick: () => engineAction(context, model, model.enabled ? "disable" : "enable"),
      }, model.enabled ? "On" : "Off")
      : h("span", { class: "muted" }, "no switch until it is installed")),
    h("td", { class: "wrap" },
      pill(health, healthWord, model.health_detail || ""),
      model.last_test ? h("span", { class: "muted" }, ` ${fmt.ago(model.last_test)}`) : null),
    h("td", null, installed
      ? h("button", {
        class: "ghost-button small",
        "data-engine-test": model.id,
        disabled: access.writable && local.busy !== `${model.id}:test` ? null : true,
        title: blocked(),
        onclick: () => engineAction(context, model, "test"),
      }, "Test")
      : null));
}

function enginesSection(context) {
  const resource = context.res("/api/engines");
  return h("section", { class: "section", key: "engines" },
    sectionHead("Engines", "Enable and Test each send one real request to the provider."),
    card({ key: "engines", "data-write": "" }, panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(3)),
      isEmpty: (data) => !list(data).length,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: "No engines registered",
        body: "An engine is the command an agent runs. Register one to spawn with it.",
        command: "fleet models",
      })),
      ready: (data) => [
        h("div", { class: "tablewrap", key: "table" }, h("table", null,
          h("thead", null, h("tr", null,
            h("th", null, "Engine"),
            h("th", null, "Installed"),
            h("th", null, "Enabled"),
            h("th", null, "Last test"),
            h("th", null, ""))),
          h("tbody", null, list(data).map((model) => engineRow(context, model))))),
        h("div", { class: "card-pad", key: "note" },
          h("p", { class: "muted" },
            "A provider key is given on the command line, never in a web form: fleet models auth <id>."),
          readOnlyLine("ro-engines")),
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
          h("td", { class: "wrap" }, check.detail || ""),
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
    const checks = list((context.res("/api/health").data || {}).checks);
    return checks.filter((check) => check.state === "missing" || check.state === "error").length || "";
  },
  render(context) {
    return [
      powerSection(context),
      servicesSection(context),
      accountsSection(context),
      enginesSection(context),
      projectsSection(context),
      healthSection(context),
      settingsSection(context),
    ];
  },
};

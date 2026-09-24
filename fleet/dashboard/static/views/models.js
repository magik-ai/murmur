/* Models: the providers the agents are spawned with, and the models switched on in each.

   Two levels (design record models-providers.md, section 2). A provider is an agent CLI and the
   way it is paid for, and it is one row of the table: connected once, tested, switched on or off.
   A model is one of the models that provider offers, and the provider's sidebar holds one list of
   them: the ones switched on, ticked, and whatever "Request available models" brings in beside
   them. Nothing here sends a prompt: a request reads a list, and a save writes the catalog. */

import {
  h, card, panel, pill, emptyState, skeletonStack, toast, safeHref, openDrawer, closeDrawer,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason } from "../core/api.js";
import { sectionHead, stepHead, commandRow, detailRow, farmAlias } from "./machine.js";

const local = {
  confirm: "",
  busy: "",
  modelError: "",
  modelPreset: "",
  modelId: "",
  modelVariant: "",
  addModelError: "",
  modelBusy: false,
  modelAdded: "",
  modelRowSeed: null,
  modelTesting: false,
  modelPoll: 0,
  /* One sidebar list per provider, by id: what a request brought back, what the person has
     ticked and unticked since, and the two requests that can be in flight. */
  lists: {},
};

function readOnlyLine(key) {
  return access.writable ? null : h("p", { class: "readonly-note", key: key || "ro" },
    access.reason || "This dashboard is read-only.");
}

function blocked() {
  return access.writable ? "" : access.reason || "This dashboard is read-only.";
}

/* The one confirm this section opens, removing a provider. It is this file's own: the power
   confirms in machine.js walk the lanes through a preview route, and closing one of those is
   that file's business. */
function setConfirm(context, next) {
  local.confirm = next;
  context.paint();
}

/* ----------------------------------------------------------------- providers */

/* The server's five status words, and the meaning and the word each is drawn in. One pill per
   row, never two: a row that carried both "installed" and "enabled" made a reader work out the
   state the page already knew. What the server calls on is drawn as Connected. */
const STATUS = {
  on: ["done", "Connected"],
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
   it did not recognise "safe headless" put that green pill on a command whose own terms
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
      class: "ghost-button small danger",
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
    }, "Key"));
  }
  if (!out.length) {
    out.push(h("span", { key: `${where}:none`, class: "muted" }, "Install it first"));
  }
  /* One order in every row: the switch, the key, the test, and a removal last, so a column of
     equal buttons reads the same way down the table. */
  const RANK = { switch: 0, auth: 1, test: 2, none: 3, remove: 9 };
  const rank = (node) => RANK[String((node.props || {}).key || "").split(":").pop()] ?? 5;
  return out.sort((one, other) => rank(one) - rank(other));
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

/* How the provider is paid for, in one or two words for the table's Access column. The catalog's
   own sentence is the cell's title. An API key provider says once, here, that it is paid per
   token on your key, so no model row in its list has to say it again. */
const ACCESS_WORD = {
  subscription: "Subscription",
  key: "API key, paid per token on your key",
  local: "Local",
};

function accessKind(model) {
  const said = String((model || {}).kind || "").trim();
  if (ACCESS_WORD[said]) return said;
  if (String((model || {}).auth_env || "").trim()) return "key";
  return /\b(this machine|local)\b/i.test(String((model || {}).access || "")) ? "local" : "subscription";
}

/* The models switched on, as the server lists them. A farm on last release's server sends the
   catalog's old comma separated string instead, and that is read the same way rather than
   drawn as nothing. */
function modelsOn(model) {
  if (Array.isArray((model || {}).models_on)) {
    return model.models_on.map((id) => String(id || "").trim()).filter(Boolean);
  }
  return String((model || {}).models || "").split(",").map((id) => id.trim()).filter(Boolean);
}

/* The model a lane gets when `fleet spawn` names none. The server says; a server that does not
   is read from the row's variant, the model its command already fills in. */
function defaultModel(model) {
  const said = (model || {}).default_model;
  return String(said != null ? said : (model || {}).variant || "").trim();
}

/* Whether a provider's command can take a model at all (design section 5). Claude and Codex
   take one through their own engine blocks; every other command takes it where its run line
   says {variant}, and a run line without one runs whatever its own settings choose. */
function takesModel(model) {
  const engine = String((model || {}).engine || "");
  if (engine === "claude" || engine === "codex") return true;
  return /\{variant\}/.test(String((model || {}).run || ""));
}

const CANNOT_TAKE = "This provider runs the model its own settings choose; change it there.";

/* "3 on" in the cell and the names in its title. */
function modelCount(model) {
  if (!takesModel(model)) return ["Its own setting", CANNOT_TAKE];
  /* The default model is always on (the sidebar ticks and locks it, and a lane spawned without
     a model runs it), so it is counted here too, first, as the sidebar lists it. */
  const fallback = defaultModel(model);
  const ids = [fallback, ...modelsOn(model).filter((id) => id !== fallback)].filter(Boolean);
  if (!ids.length) return ["None on", "No model is switched on. Open the provider to choose some."];
  return [`${ids.length} on`, ids.join(", ")];
}

function statusTitle(model, status) {
  if (status === "not_installed") {
    const hint = model.install_hint || `install ${model.command || model.id}`;
    return `Not on this farm's PATH. Install it with: ${hint}`;
  }
  return String(model.health_detail || "");
}

function commandTitle(model) {
  const command = model.path || model.command || model.id;
  return model.run ? `${model.label || model.id} runs ${command}: ${model.run}` : `${model.label || model.id} runs ${command}`;
}

/* A row this farm's models.toml still lists and murmur no longer ships (its preset was removed
   on 2026-09-24, or it was a command of its own). The server says so, with the one sentence on
   how to take it out; nothing here removes it for the person. */
function notInCatalog(model) {
  return (model || {}).in_catalog === false;
}

function orphanPill(model) {
  return notInCatalog(model)
    ? h("span", { class: "mo-orphan", "data-model-orphan": model.id },
      pill("wait", "Not in the catalog", String(model.catalog_note || "")))
    : null;
}

/* One provider, one line: every cell is cut with an ellipsis and carries its whole text in its
   title (the owner's table law). The long things live in the sidebar the name opens. */
function modelRow(context, model) {
  const status = statusOf(model);
  const [meaning, label] = STATUS[status];
  const [count, names] = modelCount(model);
  const paid = ACCESS_WORD[accessKind(model)];
  return h("tr", { key: model.id },
    h("td", { class: "mo-provider", title: notInCatalog(model)
      ? `${model.label || model.id}: not in the catalog` : (model.label || model.id) },
    h("div", { class: "mo-provider-cell" }, h("button", {
      class: "mo-name",
      "data-model-open": model.id,
      title: commandTitle(model),
      onclick: () => openModelDrawer(context, model.id),
    },
    h("span", { class: "m-dot", style: dotStyle(model.color), "aria-hidden": "true" }),
    h("b", null, model.label || model.id)), orphanPill(model))),
    h("td", { class: "mo-col-access", title: `${paid}. ${accessOf(model)}` }, paid),
    h("td", { class: "mo-col-status", title: [label, statusTitle(model, status)].filter(Boolean).join(": ") },
      pill(meaning, label, statusTitle(model, status))),
    h("td", { class: "mo-col-models", "data-model-count": model.id, title: names }, count),
    h("td", { class: "num mo-col-last" }, model.last_test ? fmt.ago(model.last_test) : "never"),
    h("td", { class: "mo-col-actions actions" },
      h("div", { class: "row mo-row-actions" }, modelActions(context, model, "row"))));
}

/* ------------------------------------------------- one provider, in its sidebar */

/* The status in words, for the sidebar's first line. */
function statusWords(model, status) {
  if (status === "on") return "Connected: lanes can be spawned with it.";
  if (status === "off") return "Off: no lane is spawned with it until it is switched on.";
  if (status === "needs_key") return "It has no key yet, so it cannot answer.";
  if (status === "not_installed") return "Its command is not on this farm.";
  return model.health_detail ? `Failing: ${model.health_detail}` : "Failing: its last test did not answer.";
}

/* The command that logs the provider in or gives it a key, where it is run: a terminal. */
function loginRows(context, model) {
  if (model.installed === false) {
    return [commandRow(model.install_hint || `install ${model.command || model.id}`, "model-install")];
  }
  const kind = accessKind(model);
  if (kind === "key") return [commandRow(`fleet models auth ${model.id}`, "model-auth")];
  if (kind === "local") return [];
  if (model.engine === "codex" || model.id === "codex") {
    /* Codex signs in through a page on port 1455 of the machine it runs on, so the port comes
       back through the ssh session; this is the command the Accounts row gives too. */
    return [
      commandRow(`ssh -L 1455:localhost:1455 -t ${farmAlias(context)} codex login`, "model-login"),
      h("p", { class: "muted", key: "login" },
        "Open the address it prints in your own browser and sign in; the forwarded port carries the answer back to the farm."),
    ];
  }
  return [
    commandRow(`ssh -t ${farmAlias(context)} ${model.command || model.id}`, "model-login"),
    h("p", { class: "muted", key: "login" }, "In the window it opens, type /login, then /exit."),
  ];
}

/* Why a request failed. The server sends one of its own fixed sentences and never text from the
   provider, and the page shows it as sent: a list kept here as well would only fall behind the
   server's. A key-shaped string is still never drawn, whoever sent it. */
function failureSentence(error) {
  const said = String(error || "").trim().replace(/\.$/, "");
  if (!said || TOKEN_LOOK.test(said)) {
    return "The request failed, and its reason is not shown here. The list below is the docs list.";
  }
  return `The request failed: ${said}. The list below is the docs list.`;
}

const SOURCE_WORD = {
  account: "From your account",
  docs: "From the docs",
  name: "Added by name",
};

/* The one model rule (design section 5), mirrored from the server: a letter or a digit first,
   so no model name can ever become an option on the command line. */
const MODEL_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._:/[\]-]{0,79}$/;
const MODEL_NAME_RULE = "A model name starts with a letter or a digit, and holds letters, digits "
  + "and . _ : / [ ] -, up to 80 characters.";
/* The token shapes lib/scrub.py knows, and any long unbroken run of letters and digits. A
   model name is never one, and a key pasted into the wrong field must stop here. */
const TOKEN_LOOK = /(sk-|sk_|gh[pousr]_|github_pat_|dop_v1_|xox[abposr]-|AIza)[A-Za-z0-9_-]{6,}|[A-Za-z0-9]{32,}/;

function listState(id) {
  if (!local.lists[id]) {
    local.lists[id] = {
      asking: false, answer: null, failed: "",
      adds: new Set(), removes: new Set(), named: [], confirmed: new Set(), costNotes: {},
      typed: "", typedRound: 0, nameError: "", saving: false, saveError: "", costAsk: false,
    };
  }
  return local.lists[id];
}

/* Only a cost note asks the second question. The server sets one by rule, for a model that can
   cost money the subscription does not cover (design section 4); a description is text from the
   provider or the docs, whatever its words, and it asks nothing. */
function asksCost(entry) {
  return Boolean(entry && entry.cost_note);
}

/* The one list: the default first, then the other models that are on, then what a request
   brought back, then what was typed by name. */
function listRows(model, state) {
  const found = new Map();
  const answer = state.answer || { source: "docs", models: [] };
  for (const entry of answer.models) found.set(entry.id, entry);
  const on = modelsOn(model);
  const fallback = defaultModel(model);
  const rows = [];
  const seen = new Set();
  const push = (id, extra) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    const entry = found.get(id) || {};
    rows.push({
      id,
      label: entry.label || id,
      description: entry.description || "",
      cost_note: entry.cost_note || state.costNotes[id] || "",
      ...extra,
    });
  };
  if (fallback && takesModel(model)) push(fallback, { on: true, locked: true });
  for (const id of on) push(id, { on: true });
  for (const entry of answer.models) push(entry.id, { on: false, source: answer.source });
  for (const id of state.named) push(id, { on: false, source: "name" });
  return rows.map((row) => ({
    ...row,
    ticked: row.locked || (row.on ? !state.removes.has(row.id) : state.adds.has(row.id)),
  }));
}

function toggle(context, model, row, ticked) {
  const state = listState(model.id);
  if (row.locked) return;
  if (row.on) {
    if (ticked) state.removes.delete(row.id);
    else state.removes.add(row.id);
  } else if (ticked) {
    state.adds.add(row.id);
  } else {
    state.adds.delete(row.id);
    state.confirmed.delete(row.id);
  }
  state.saveError = "";
  state.costAsk = false;
  context.paint();
}

async function requestModels(context, model) {
  const state = listState(model.id);
  if (state.asking) return;
  state.asking = true;
  state.failed = "";
  context.paint();
  try {
    const answer = await apiPost("/api/models/discover", { id: model.id });
    const source = String((answer || {}).source || "") === "account" ? "account" : "docs";
    const models = list((answer || {}).models)
      .filter((entry) => entry && entry.id)
      .map((entry) => ({
        id: String(entry.id),
        label: String(entry.label || entry.id),
        description: String(entry.description || ""),
        cost_note: String(entry.cost_note || ""),
      }));
    state.answer = { source, models };
    /* A provider with nothing to list is not a failed request: it says so in its own words. */
    state.failed = answer && answer.error
      ? (models.length || source !== "docs" || !/^this provider has no list/.test(answer.error)
        ? failureSentence(answer.error)
        : "This provider has no list to offer here. Add a model by its name below.")
      : "";
  } catch (error) {
    state.failed = serverReason(error) || "The farm did not answer the request.";
  } finally {
    state.asking = false;
    context.paint();
  }
}

function addByName(context, model) {
  const state = listState(model.id);
  const typed = state.typed.trim();
  state.nameError = "";
  if (!typed) state.nameError = "Type a model name first, for example claude-opus-5-5.";
  else if (TOKEN_LOOK.test(typed)) {
    state.nameError = "That looks like a key, not a model name. A key never goes through this page.";
  } else if (!MODEL_NAME_RE.test(typed)) state.nameError = `${MODEL_NAME_RULE} ${typed} is not one.`;
  if (state.nameError) {
    context.paint();
    return;
  }
  const row = listRows(model, state).find((item) => item.id === typed);
  if (row && row.on) {
    state.nameError = `${typed} is already on.`;
  } else {
    if (!row) state.named.push(typed);
    state.adds.add(typed);
    state.typed = "";
    /* A new key draws a new, empty field: the one typed in still holds the text. */
    state.typedRound += 1;
    state.saveError = "";
    state.costAsk = false;
  }
  context.paint();
}

async function saveList(context, model, confirmNow) {
  const state = listState(model.id);
  if (state.saving) return;
  const rows = listRows(model, state);
  const on = [...state.adds];
  const off = [...state.removes];
  if (confirmNow) {
    for (const row of rows) if (state.adds.has(row.id) && asksCost(row)) state.confirmed.add(row.id);
  }
  const unasked = rows.filter((row) => state.adds.has(row.id) && asksCost(row) && !state.confirmed.has(row.id));
  if (unasked.length) {
    state.costAsk = true;
    context.paint();
    return;
  }
  state.costAsk = false;
  state.saving = true;
  state.saveError = "";
  context.paint();
  try {
    await apiPost("/api/models/select", {
      id: model.id, on, off, confirm_cost: on.filter((id) => state.confirmed.has(id)),
    });
    state.adds.clear();
    state.removes.clear();
    state.confirmed.clear();
    state.named = [];
    toast(`${model.label || model.id}: the models are saved.`);
  } catch (error) {
    /* A model no request has listed (one typed into Add by name) has no cost note on the page.
       The server knows it by rule, refuses the save with the note, and the page asks now. */
    const said = (error && error.payload) || {};
    const refused = String(said.model || "");
    if (error && error.status === 400 && said.cost_note && state.adds.has(refused) && !state.confirmed.has(refused)) {
      state.costNotes[refused] = String(said.cost_note);
      state.costAsk = true;
    } else {
      state.saveError = serverReason(error) || "The farm did not save the models.";
    }
  } finally {
    state.saving = false;
    await context.refresh("/api/engines");
    context.paint();
  }
}

function declineCost(context, model) {
  const state = listState(model.id);
  for (const row of listRows(model, state)) {
    if (state.adds.has(row.id) && asksCost(row) && !state.confirmed.has(row.id)) state.adds.delete(row.id);
  }
  state.costAsk = false;
  context.paint();
}

function tagFor(row) {
  if (row.locked) return pill("run", "Default", "The model a lane gets when fleet spawn names none. It stays on.");
  if (row.on) return pill("done", "On", "Switched on for this provider.");
  const word = SOURCE_WORD[row.source] || SOURCE_WORD.docs;
  return pill("pause", word, word);
}

function listRow(context, model, row, state) {
  const off = !access.writable || state.saving || row.locked;
  const title = row.locked
    ? `${row.id} is the default model: a lane spawned without --model runs it, so it stays on.`
    : blocked() || (row.ticked ? `Untick to switch ${row.id} off.` : `Tick to switch ${row.id} on.`);
  return h("tr", { key: row.id, "data-list-row": row.id },
    h("td", { class: "mo-tick" }, h("input", {
      type: "checkbox",
      "data-model-tick": row.id,
      "aria-label": `${row.label} on`,
      checked: row.ticked,
      disabled: off ? true : null,
      title,
      onchange: (event) => toggle(context, model, row, event.target.checked),
    })),
    h("td", { class: "mo-label", title: `${row.label} (${row.id})` }, row.label),
    h("td", { class: "mo-id mono", title: row.id }, row.id),
    h("td", { class: "mo-tag" }, tagFor(row)),
    noteCell(row));
}

/* The cost note when there is one, marked as the money fact it is; the description otherwise. */
function noteCell(row) {
  const said = row.cost_note || row.description;
  return h("td", {
    class: row.cost_note ? "mo-note mo-cost-note" : "mo-note",
    title: said,
    "data-model-note": said ? row.id : null,
    "data-model-cost": row.cost_note ? row.id : null,
  }, said);
}

function costQuestion(context, model, state) {
  const noted = listRows(model, state)
    .filter((row) => state.adds.has(row.id) && asksCost(row) && !state.confirmed.has(row.id));
  return h("div", { class: "m-confirm mo-cost", key: "cost", role: "alert", "data-cost-question": "" },
    h("h3", null, noted.length === 1
      ? `${noted[0].label} can cost money your plan does not cover`
      : "These models can cost money your plan does not cover"),
    h("ul", null, noted.map((row) => h("li", { key: row.id }, h("b", null, row.id), `: ${row.cost_note}`))),
    h("p", { class: "muted" }, "A lane spawned with it spends that money without asking. Switch it on anyway?"),
    h("div", { class: "row" },
      h("button", {
        class: "button primary",
        "data-cost-yes": "",
        disabled: access.writable && !state.saving ? null : true,
        title: blocked(),
        onclick: () => saveList(context, model, true),
      }, noted.length === 1 ? "Yes, switch it on" : "Yes, switch them on"),
      h("button", {
        class: "ghost-button",
        "data-cost-no": "",
        onclick: () => declineCost(context, model),
      }, "No, leave it off")));
}

function saveLabel(state) {
  if (state.removes.size || !state.adds.size) return "Save";
  return `Add ${state.adds.size} model${state.adds.size === 1 ? "" : "s"}`;
}

function modelList(context, model) {
  if (!takesModel(model)) {
    return h("div", { class: "mo-list-block", key: "models" },
      h("h3", null, "Models"),
      h("p", { class: "muted", "data-model-cannot": "" }, CANNOT_TAKE));
  }
  const state = listState(model.id);
  const rows = listRows(model, state);
  const changed = state.adds.size + state.removes.size > 0;
  return h("div", { class: "mo-list-block", key: "models" },
    h("div", { class: "row mo-list-head" },
      h("h3", null, "Models"),
      h("div", { class: "spacer" }),
      h("button", {
        class: "button small",
        "data-model-request": model.id,
        disabled: access.writable && !state.asking ? null : true,
        title: blocked() || "Reads the list this provider offers. No prompt is sent and nothing is spent.",
        onclick: () => requestModels(context, model),
      }, state.asking ? "Requesting" : "Request available models")),
    state.failed ? h("p", { class: "m-bad", role: "status", "data-model-failed": "" }, state.failed) : null,
    rows.length
      ? h("div", { class: "tablewrap mo-listwrap" }, h("table", { class: "mo-list" },
        h("thead", null, h("tr", null,
          h("th", { class: "mo-tick" }, h("span", { class: "sr-only" }, "On")),
          h("th", { class: "mo-label" }, "Model"),
          h("th", { class: "mo-id" }, "Id"),
          h("th", { class: "mo-tag" }, ""),
          h("th", { class: "mo-note" }, "Note"))),
        h("tbody", null, rows.map((row) => listRow(context, model, row, state)))))
      : h("p", { class: "muted", key: "none" },
        "No model is on. Request the available models, or add one by name."),
    h("div", { class: "mo-byname" },
      h("input", {
        key: `name:${state.typedRound}`,
        type: "text",
        "aria-label": "Add a model by name",
        "data-model-name": model.id,
        placeholder: "Add by name, for example claude-opus-5-5",
        autocomplete: "off",
        spellcheck: "false",
        value: state.typed,
        disabled: access.writable && !state.saving ? null : true,
        title: blocked(),
        oninput: (event) => {
          state.typed = event.target.value;
          state.nameError = "";
        },
        onkeydown: (event) => {
          if (event.key === "Enter") addByName(context, model);
        },
      }),
      h("button", {
        class: "ghost-button small",
        "data-model-name-add": model.id,
        disabled: access.writable && !state.saving ? null : true,
        title: blocked(),
        onclick: () => addByName(context, model),
      }, "Add")),
    state.nameError ? h("p", { class: "m-bad", role: "alert", "data-model-name-error": "" }, state.nameError) : null,
    state.costAsk ? costQuestion(context, model, state) : null,
    state.saveError ? h("p", { class: "m-bad", role: "alert", "data-model-save-error": "" }, state.saveError) : null,
    h("div", { class: "row m-dialog-actions" },
      h("button", {
        class: "button primary",
        "data-model-save": model.id,
        disabled: access.writable && changed && !state.saving && !state.costAsk ? null : true,
        title: blocked() || (changed ? "Writes the list to this farm's catalog. Nothing is run." : "Tick or untick a model first."),
        onclick: () => saveList(context, model, false),
      }, state.saving ? "Saving" : saveLabel(state))));
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
    notInCatalog(model)
      ? h("p", { class: "readonly-note", key: "orphan", "data-model-orphan-note": "" },
        String(model.catalog_note || "Not in murmur's catalog."))
      : null,
    h("div", { class: "row m-wait", key: "status" },
      pill(meaning, label, statusTitle(model, status)),
      h("span", { class: "muted", "data-model-status-words": "" }, statusWords(model, status))),
    h("dl", { class: "kv m-detail-list", key: "facts" },
      detailRow("How it is paid for", accessOf(model)),
      detailRow("Terms", model.tos),
      detailRow("What it is for", model.role),
      detailRow("Quality", model.quality),
      detailRow("Limits", model.caps || model.limits),
      detailRow("Reads its key from", model.auth_env
        ? h("span", { class: "mono" }, model.auth_env) : null),
      detailRow("Where it came from", isAdded(model)
        ? "Added on this farm, so it can be removed."
        : "Shipped with the farm, so it can only be switched off."),
      detailRow("Documentation", link
        ? h("a", { href: link, target: "_blank", rel: "noreferrer noopener" }, link)
        : null)),
    h("div", { class: "m-steps", key: "login" }, loginRows(context, model)),
    model.run
      ? h("div", { key: "run" },
        h("p", { class: "muted" }, "The line a lane runs. {bin} is the command, {variant} the model, {task} the brief:"),
        h("code", { class: "cmd", "data-model-run": "" }, model.run))
      : null,
    h("div", { class: "row m-dialog-actions", key: "actions" },
      modelActions(context, model, "drawer")),
    modelList(context, model),
    readOnlyLine("ro-model-drawer"),
  ];
}

/* Each open starts the list afresh: ticks left from an earlier visit would be a change the
   person no longer remembers making. */
function openModelDrawer(context, id) {
  const model = modelById(context, id) || { id };
  delete local.lists[id];
  openDrawer({
    key: `model:${id}`,
    title: model.label || id,
    sub: "How it is paid for, and the models switched on in it.",
    body: () => modelDrawerBody(context, id),
  });
}

/* ------------------------------------------------------- adding a provider */

/* Adding a model is the accounts dialog's pattern, step for step: numbered steps down the
   drawer, one thing to do in each, and the commands that touch a credential kept where they
   belong, in a terminal. Nothing here ever asks for a key. */
const ADD_MODEL_KEY = "add-model";

function presetById(context, id) {
  return list(context.res("/api/models/presets").data).find((row) => row && row.id === id) || null;
}

function choosePreset(context, preset) {
  local.modelPreset = preset.id;
  local.modelId = preset.id;
  local.modelVariant = list(preset.variants)[0] || "";
  local.addModelError = "";
  context.paint();
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
      /* One line on how it is paid for: a second line naming the kind of payment again ("An API
         key you hold" under "An API key, billed per token") only doubled every card. */
      h("div", { class: "muted" }, accessOf(preset)));
    }));
}

/* Step two: the name it goes into the catalog under, and the variant when the service sells more
   than one. */
function nameStep(context, preset) {
  const variants = list(preset.variants);
  return [
    stepHead(2, "Name it",
      "A short id for the catalog. The preset's own name is filled in; change it if you run two."),
    h("label", { class: "m-field", key: "name" },
      h("span", { class: "m-label" }, "Name"),
      h("input", {
        type: "text",
        class: "m-name",
        "aria-label": "Model name",
        "data-model-id": "",
        placeholder: preset.id,
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
  ];
}

/* Step three: how this one gets its credential. Three services, three different answers, and
   in none of them does a key pass through this page. */
function accessStep(context, preset) {
  const name = (local.modelId || preset.id || "the model").trim();
  const binary = preset.bin || name;
  if (preset.kind === "subscription" && (preset.engine === "codex" || preset.id === "codex")) {
    /* Codex signs in through a page on port 1455 of the farm, so the port comes back through
       the ssh session; the Accounts row and the provider sidebar give the same command. */
    return [
      stepHead(3, "Log it in", "A subscription is logged in once, in a terminal on your own "
        + "machine, not on this page. Run:"),
      commandRow(`ssh -L 1455:localhost:1455 -t ${farmAlias(context)} codex login`, "model-login"),
      h("ol", { key: "steps" },
        h("li", { key: "1" }, "Run the command from wherever you reach this farm"),
        h("li", { key: "2" }, "Open the address it prints in your own browser"),
        h("li", { key: "3" }, "Sign in with the account that holds the subscription"),
        h("li", { key: "4" }, "Come back here when the terminal says you are logged in")),
    ];
  }
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
       A line this page built itself ("{bin} pull {variant}") would be right for one local
       runner by luck and wrong for the next one a contributor adds. */
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
     typed: a command built from anything else looks runnable and is not. */
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
   writes the name as a TOML table. A page that taught a looser one let "Codex", "my.model"
   and a thirty-five character name through to a refusal nobody could have predicted. */
const MODEL_ID_RE = /^[a-z][a-z0-9_-]{1,30}$/;
const MODEL_ID_RULE = "A model id is lower case letters, digits, - and _, starting with a "
  + "letter, 2 to 31 characters.";

function validateModel(preset) {
  const name = local.modelId.trim();
  if (!name) return `Give the model a name, for example ${preset.id}.`;
  if (!MODEL_ID_RE.test(name)) return `${MODEL_ID_RULE} ${name} is not one.`;
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
    /* murmur ships Claude Code and Codex, and a farm usually has both already. Saying so beats
       a row of switched-off cards with nothing to explain them. */
    presets.every((row) => row.added)
      ? h("p", { class: "muted", key: "all-added", "data-model-all-added": "" },
        "Every engine murmur ships is already in this farm's catalog. Another engine is a "
        + "contribution: its preset is one entry in fleet/lib/model_presets.py (CONTRIBUTING.md).")
      : null,
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
  local.addModelError = "";
  local.modelBusy = false;
  local.modelAdded = "";
  local.modelRowSeed = null;
  local.modelTesting = false;
  openDrawer({
    key: ADD_MODEL_KEY,
    title: "Add a provider",
    sub: "A provider the agents can be spawned with.",
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

/* --------------------------------------------------------------- the section */

export function modelsSection(context) {
  const resource = context.res("/api/engines");
  const removing = local.confirm.startsWith("remove-model:");
  /* The Add button is in the heading, where every section keeps its one action, so it is there
     over a full table and over an empty one alike: a farm with nothing registered is exactly the
     farm that needs it. The footer only appears when it has something to say. */
  const footer = () => (removing || local.modelError || !access.writable
    ? h("div", { class: "card-pad", key: "add" },
      removing ? removeModelConfirm(context, local.confirm.slice("remove-model:".length)) : null,
      local.modelError ? h("p", { class: "m-bad", key: "err" }, local.modelError) : null,
      readOnlyLine("ro-models"))
    : null);
  const add = h("button", {
    key: "add-model",
    class: "button",
    "data-add-model": "",
    "data-write": "",
    disabled: access.writable ? null : true,
    title: blocked() || "A provider key is given on the command line, never in a web form: fleet models auth <id>",
    onclick: () => openAddModel(context),
  }, "Add a provider");
  return h("section", { class: "section", key: "models" },
    sectionHead("Models", "The providers agents are spawned with. Open one to choose its models.",
      resource.everLoaded ? add : null),
    card({ key: "models", "data-write": "" }, panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(3)),
      isEmpty: (data) => !modelRows(data).length,
      empty: () => [
        h("div", { class: "card-pad", key: "none" }, emptyState({
          title: "No providers connected",
          body: "A provider is the command an agent runs and the way it is paid for. Add one to spawn with it.",
          command: "fleet models",
        })),
        footer(),
      ],
      ready: (data) => [
        h("div", { class: "tablewrap", key: "table" }, h("table", { class: "mo-providers" },
          h("thead", null, h("tr", null,
            h("th", { class: "mo-provider" }, "Provider"),
            h("th", { class: "mo-col-access" }, "Access"),
            h("th", { class: "mo-col-status" }, "Status"),
            h("th", { class: "mo-col-models" }, "Models"),
            h("th", { class: "num mo-col-last" }, "Last test"),
            h("th", { class: "mo-col-actions actions" }, "Actions"))),
          h("tbody", null, modelRows(data).map((model) => modelRow(context, model))))),
        footer(),
      ],
    })));
}

/* Hosting: where a farm and its agents run. Two tables, because the providers do not offer the
   same thing. A machine runs a whole farm (systemd, worktrees, this dashboard); a runner runs
   one agent in a cloud sandbox and nothing else. Every price is said in the same words, and
   every state of a droplet except destroyed still costs money, which the page says out loud
   on the pill, on the button that buys it and in the head.

   Nothing here ever asks for a token. A provider login is made by that provider's own CLI, in
   a terminal, and this page only hands over the command and watches the state flip by itself.
   The one credential-looking thing a person may type here is an SSH public key, which is not a
   secret; its field is ssh_public, because the key classifier refuses any field whose name
   carries the word key. A value that looks like a token is refused here, before any request. */

import {
  h, card, panel, pill, emptyState, skeletonStack, toast, openDrawer, closeDrawer,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason } from "../core/api.js";
import { sectionHead, stepHead, commandRow, copyCommand, farmAlias } from "./machine.js";

/* The sentences a person is asked to act on. They are written once, here, because the dialog,
   the row and the confirm all have to say the same thing about the same money. */
const HEAD_LINE = "Where farms and agents run. A machine runs a whole farm; a runner runs one "
  + "agent in a cloud sandbox.";
const FINISH_LINE = "Run this from your laptop. It signs in to GitHub, clones murmur and runs "
  + "the installer.";
const BILL_LINE = "You are billed until you destroy it. Powering it off does not stop the bill.";
const GAP_LINE = "Usage by cloud agents is not in the Accounts windows yet.";
const KEY_LINE = "Your SSH public key: how your laptop reaches the machine. On your laptop: "
  + "cat ~/.ssh/id_ed25519.pub";
const TEST_LINE = "Starts the smallest sandbox for about a minute; costs a few cents.";
const NOT_LIVE = "not run live";
/* DigitalOcean's own documentation does not show that its claude-code adapter takes a
   subscription token, so the card says what that may cost instead of guessing (UNVERIFIED,
   internal/research/report-hosting-cli.md, 2026-09-23). */
const DO_AGENTS_LINE = "It may need DigitalOcean's own inference, billed by DigitalOcean: their "
  + "documentation does not show the claude-code adapter taking a subscription token.";

/* The hint under each secret. The names are the two the runners need and no others. */
const SECRET_HINTS = {
  CLAUDE_CODE_OAUTH_TOKEN: "run claude setup-token on any machine logged in to your Claude "
    + "subscription and paste what it prints",
  GITHUB_TOKEN: "a fine-grained token limited to the project's repository, with contents: read "
    + "only; the farm pushes, the sandbox never can",
};

/* A machine's state, in the five meanings this dashboard has and the words a person reads.
   needs-login is a wait on a person and says which person and what for. */
const MACHINE_STATE = {
  creating: ["wait", "Creating"],
  preparing: ["wait", "Preparing"],
  "needs-login": ["wait", "Needs your login"],
  ready: ["done", "Ready"],
  unreachable: ["fail", "Unreachable"],
  failed: ["fail", "Failed"],
  unrecorded: ["fail", "Unrecorded"],
  destroyed: ["pause", "Destroyed"],
};

/* A provider's login, as the farm last read it. no_answer is its own pill: a provider that was
   slow to answer is not a provider you are logged out of, and drawing it as one sends a person
   to log in again for nothing. */
const LOGIN_STATE = {
  logged_in: ["done", "Logged in"],
  logged_out: ["wait", "Not logged in"],
  not_installed: ["pause", "Not installed"],
  no_answer: ["pause", "No answer"],
};

const LOGIN_TITLE = {
  no_answer: "The check did not come back in time, so this farm cannot say. This is not a "
    + "provider you are logged out of.",
  not_installed: "The provider's own command is not on this farm yet.",
};

const STAGE_WORD = { ga: "generally available", preview: "preview", "early access": "early access" };

/* The farm's own rule for a machine name: it is a table name in machines.toml and a host name
   at the provider, so it is the narrow one of the two. */
const NAME_RE = /^[a-z][a-z0-9-]{1,30}$/;
const NAME_RULE = "A machine name is lower case letters, digits and dashes, starting with a "
  + "letter, 2 to 31 characters.";
const TARGET_RE = /^[A-Za-z0-9._-]+@[A-Za-z0-9.:_-]+$/;
/* One line of a public key, in the three types OpenSSH writes. */
const PUBLIC_KEY_RE = /^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9-]+)\s+[A-Za-z0-9+/=]+(\s+\S.*)?$/;
/* The exact token shapes, never a "long run of characters" rule, which would eat a commit SHA.
   These are the same four scrub.py knows, so the page refuses what the farm would scrub. */
const TOKEN_SHAPES = [
  /sk-ant-[A-Za-z0-9_-]{20,}/,
  /gh[pousr]_[A-Za-z0-9]{36,}/,
  /github_pat_[A-Za-z0-9_]{50,}/,
  /dop_v1_[a-f0-9]{64}/,
];
const TOKEN_REFUSAL = "That looks like a token, not a public key. A token never goes through "
  + "this page: store it with fleet hosts secret, in a terminal.";

const ADD_MACHINE_KEY = "add-machine";
const CONNECT_RUNNER_KEY = "connect-runner";

/* This section's own state, and its own footer sentence. The Machine tab learned once that two
   cards reading one error field print one card's failure under both of them, so a hosting job
   that fails is answered here and nowhere else. */
const local = {
  jobs: {},
  error: "",
  dialogError: "",
  confirm: "",
  typed: "",
  poll: 0,
  provider: "",
  name: "",
  size: "",
  region: "",
  sshPublic: "",
  target: "",
  port: "",
  plan: null,
  planning: false,
  confirming: false,
  sending: false,
  created: "",
  runner: "",
  project: "",
};

function afterPaint(work) {
  setTimeout(work, 0);
}

function blocked() {
  return access.writable ? "" : access.reason || "This dashboard is read-only.";
}

function readOnlyLine(key) {
  return access.writable ? null : h("p", { class: "readonly-note", key: key || "ro" },
    access.reason || "This dashboard is read-only.");
}

/* ------------------------------------------------------------------ the money */

/** Money is said one way on this page, every time: "$48 a month". */
export function monthly(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) return "";
  return `$${Number.isInteger(amount) ? amount : amount.toFixed(2)} a month`;
}

/* A row that may still exist at the provider, and so may still cost money: everything but a
   destroyed droplet, a machine of your own, and a failed row the provider never gave an id to.
   These are exactly the rows Forget is offered on, for the same reason. */
function billable(row) {
  return Boolean(row) && !canForget(row);
}

/** What a row still costs, said on its state pill. A droplet whose price the farm has not read
    yet still costs money, so the pill says so without a number rather than saying nothing. */
export function billedLine(row) {
  if (!billable(row)) return "";
  const price = monthly(row.monthly_usd);
  return price ? `Still billed: ${price}. ${BILL_LINE}` : `Still billed. ${BILL_LINE}`;
}

/** The head's own sentence: what this list costs a month, and how many machines that is. The
    total is the farm's, and it is said whenever it is positive, whatever the rows carry: a
    head that denies a bill because one row came without its price is the expensive mistake. */
export function totalLine(data) {
  const total = Number(data.total_monthly_usd);
  if (!Number.isFinite(total) || total <= 0) return "Nothing on this list is billed.";
  const count = list(data.machines).filter(billable).length;
  if (!count) return `You pay ${monthly(total)}.`;
  return `You pay ${monthly(total)} for ${count} ${count === 1 ? "machine" : "machines"}.`;
}

/* ------------------------------------------------------------------- the data */

function providers(context) {
  return list((context.res("/api/hosts").data || {}).providers).filter(Boolean);
}

function providerById(context, id) {
  return providers(context).find((row) => row && row.id === id) || null;
}

function providerLabel(context, id) {
  const found = providerById(context, id);
  if (found && found.label) return found.label;
  return id ? fmt.titleCase(id) : "not known";
}

function sizeOf(context, providerId, slug) {
  const found = providerById(context, providerId);
  return list(found && found.sizes).find((size) => size && size.slug === slug) || null;
}

/** "4 vCPU, 8 GB, $48 a month", or as much of it as the farm knows. */
function sizeLine(context, row) {
  const size = sizeOf(context, row.provider, row.size);
  const spec = size ? `${fmt.num(size.vcpu, "?")} vCPU, ${fmt.num(size.ram_gb, "?")} GB` : row.size;
  const parts = [spec, monthly(row.monthly_usd)].filter(Boolean);
  return parts.length ? parts.join(", ") : "Not billed here";
}

function regionValue(region) {
  return typeof region === "string" ? region : String((region || {}).slug || "");
}

function regionLabel(region) {
  if (typeof region === "string") return region;
  const row = region || {};
  return String(row.label || row.slug || "");
}

/* ------------------------------------------------------------------ long jobs */

/* Every write here answers with a job, and the control that started it stays off until that
   job ends. This is the Machine tab's pattern with one thing changed: where the failure is
   written. The shared helper puts it under the Power section, which is the wrong card for a
   droplet that would not build. */
function jobFor(context, key, field = "error") {
  const id = local.jobs[key];
  if (!id) return null;
  const path = `/api/jobs/${encodeURIComponent(id)}`;
  const job = context.watch(path).data;
  if (!job || !job.state) return { state: "running", detail: "asking the farm", id };
  if (job.state === "running") return job;
  afterPaint(() => {
    if (local.jobs[key] !== id) return;
    delete local.jobs[key];
    local[field] = job.state === "failed"
      ? `${key}: ${job.error || "the farm refused this action"}` : "";
    if (job.state !== "failed") toast(`${fmt.titleCase(key)} is done.`);
    context.drop(path);
    context.refresh("/api/machines");
    context.refresh("/api/hosts");
  });
  return job;
}

function running(context, key, field) {
  const job = jobFor(context, key, field);
  return job && job.state === "running" ? job : null;
}

async function startJob(context, key, body, path, field = "error") {
  if (local.jobs[key]) {
    toast(`${fmt.titleCase(key)} is already running.`, "bad");
    return;
  }
  local[field] = "";
  try {
    const answer = await apiPost(path, body);
    const job = answer && answer.job;
    const id = job && typeof job === "object" ? job.id : job;
    if (id) local.jobs[key] = String(id);
    else toast(`${fmt.titleCase(key)} is done.`);
  } catch (error) {
    local[field] = serverReason(error) || `${key} was refused.`;
  } finally {
    context.paint();
  }
}

const machineKey = (name) => `the machine ${name}`;
const runnerKey = (id) => `the runner ${id}`;

/* --------------------------------------------------------- refreshing by itself */

/* A login or a stored secret happens in a terminal, not here, so the dialog that told a person
   to go and do it asks the farm again every three seconds and flips its own state when it
   lands. It stops when the dialog closes: nothing on this page polls in the background. */
function startPoll(context) {
  if (local.poll) return;
  local.poll = setInterval(() => context.refresh("/api/hosts"), 3000);
}

function stopPoll() {
  if (!local.poll) return;
  clearInterval(local.poll);
  local.poll = 0;
}

/* ------------------------------------------------------------ the machines table */

function statePill(row) {
  const [meaning, label] = MACHINE_STATE[row.state] || ["pause", fmt.titleCase(row.state || "unknown")];
  const title = [row.detail || "", billedLine(row)].filter(Boolean).join(" ");
  return pill(meaning, label, title);
}

/* A command a person runs somewhere else. The cell is one line, so what the command does is
   carried on the button's title and said again in a toast when it is copied: a sentence that
   only ever appears on hover is a sentence a person on a touch screen never reads. */
function copyButton(command, mark, label, sentence) {
  return h("button", {
    key: mark,
    class: "ghost-button small",
    [`data-${mark}`]: "",
    title: sentence || "",
    onclick: () => copyWithSentence(command, sentence),
  }, label);
}

/* One toast for one press, carrying the button's own sentence. The Machine tab's copy helper
   says its own generic sentence, and calling it and then toasting this one was two messages
   about one copy. */
async function copyWithSentence(command, sentence) {
  if (!sentence) return copyCommand(command);
  try {
    await navigator.clipboard.writeText(String(command || ""));
    toast(`Copied. ${sentence}`);
  } catch (error) {
    toast("Select the command and copy it by hand: the browser refused the clipboard.", "bad");
  }
  return undefined;
}

function actionButton(context, row, action, label, path, body) {
  const key = machineKey(row.name);
  const busy = Boolean(running(context, key));
  return h("button", {
    key: action,
    class: "ghost-button small",
    [`data-machine-${action}`]: row.name,
    disabled: access.writable && !busy ? null : true,
    title: blocked(),
    onclick: () => startJob(context, key, body || { name: row.name }, path),
  }, busy ? `${label}, running` : label);
}

/* Forget drops a row from the registry and buys nothing back, so it is offered only where
   there is nothing left to destroy: a destroyed droplet, a machine of your own, and a failed
   row the provider never gave an id to. A server that does not send provider_id at all leaves
   that last case unknown, and an unknown one is not offered. */
function canForget(row) {
  if (row.state === "destroyed") return true;
  if (row.provider === "ssh") return true;
  return row.state === "failed" && "provider_id" in row && !row.provider_id;
}

function machineActions(context, row) {
  const out = [];
  if (row.state === "needs-login" && row.finish_command) {
    out.push(copyButton(row.finish_command, "machine-finish", "Finish command", FINISH_LINE));
  }
  if (row.state === "ready" && row.tunnel_command) {
    out.push(copyButton(row.tunnel_command, "machine-tunnel", "Tunnel",
      "Opens this dashboard from your laptop while the tunnel runs."));
  }
  if (row.state !== "destroyed" && row.state !== "unrecorded") {
    out.push(actionButton(context, row, "check", "Check", "/api/machines/check"));
  }
  if (row.state === "unrecorded") {
    out.push(actionButton(context, row, "adopt", "Adopt", "/api/machines/adopt"));
  }
  if (row.provider !== "ssh" && row.state !== "destroyed") {
    out.push(h("button", {
      key: "destroy",
      class: "ghost-button small",
      "data-machine-destroy": row.name,
      disabled: access.writable ? null : true,
      title: blocked(),
      onclick: () => setConfirm(context, `destroy:${row.name}`),
    }, "Destroy"));
  }
  if (canForget(row)) {
    out.push(actionButton(context, row, "forget", "Forget", "/api/machines/forget"));
  }
  return h("div", { class: "row h-do" }, out);
}

function setConfirm(context, next) {
  local.confirm = next === local.confirm ? "" : next;
  local.typed = "";
  context.paint();
}

/* Destroying a droplet deletes its disk and cannot be taken back, so the confirm names the
   droplet, says what goes with it, and stays off until the name is typed back. */
function destroyConfirm(context, rows, name) {
  const row = rows.find((item) => item && item.name === name);
  if (!row) return null;
  const price = monthly(row.monthly_usd);
  const matched = local.typed.trim() === name;
  const busy = Boolean(running(context, machineKey(name)));
  return h("div", { class: "m-confirm", key: "destroy" },
    h("h3", null, `Destroy ${name}?`),
    h("p", null, `The droplet and its disk are deleted. Nothing on it is kept, and this is the `
      + `only thing that stops the bill${price ? ` of ${price}` : ""}.`),
    h("label", { class: "m-field" },
      h("span", { class: "m-label" }, `Type ${name} to confirm`),
      h("input", {
        type: "text",
        class: "m-name",
        "aria-label": "Type the machine name to confirm",
        "data-machine-typed": "",
        autocomplete: "off",
        spellcheck: "false",
        value: local.typed,
        disabled: access.writable ? null : true,
        oninput: (event) => {
          local.typed = event.target.value;
          context.paint();
        },
      })),
    h("div", { class: "row" },
      h("button", {
        class: "button primary",
        "data-confirm": `destroy:${name}`,
        disabled: access.writable && matched && !busy ? null : true,
        title: matched ? blocked() : `Type ${name} to switch this on.`,
        onclick: () => {
          startJob(context, machineKey(name), { name, confirm: name }, "/api/machines/destroy");
          setConfirm(context, "");
        },
      }, "Destroy it"),
      h("button", {
        class: "ghost-button",
        onclick: () => setConfirm(context, ""),
      }, "Keep it")));
}

/* This farm is always the first row and is never in the registry: it is the machine you are
   reading this on, and there is nothing here to check, destroy or forget. */
function thisFarmRow(context, here) {
  return h("tr", { key: "this-farm", class: "h-this" },
    h("td", null, h("div", { class: "h-name" },
      h("b", null, here.name || "this farm"),
      h("span", { class: "muted" }, "This farm"))),
    h("td", null, "This machine"),
    h("td", { class: "mono", title: here.address || "" }, here.address || "not known"),
    h("td", null, "Not billed here"),
    h("td", null, pill("done", "Ready", "You are reading this page on it.")),
    h("td", null, "now"),
    h("td", { class: "h-do-cell" }, ""));
}

function machineRow(context, row) {
  return h("tr", { key: row.name },
    h("td", { title: row.name }, row.name),
    h("td", null, providerLabel(context, row.provider)),
    h("td", { class: "mono", title: row.address || "" },
      row.address ? `${row.user ? `${row.user}@` : ""}${row.address}` : "not yet"),
    h("td", { title: sizeLine(context, row) }, sizeLine(context, row)),
    h("td", null, statePill(row)),
    h("td", null, row.checked_at ? fmt.ago(row.checked_at) : "not checked"),
    h("td", { class: "h-do-cell" }, machineActions(context, row)));
}

/* A snapshot the farm could not refresh still answers, with the rows it last read and since
   when they are old. The rows are worth drawing, and the reader is told what they are. */
function staleNote(data, key) {
  if (!data || !data.stale_since) return null;
  return h("p", { class: "readonly-note card-pad", key, "data-hosting-stale": "" },
    `The farm has not refreshed this list since ${fmt.ago(data.stale_since)}`
    + `${data.error ? `: ${data.error}` : ""}. What is drawn is its last reading.`);
}

function machinesCard(context) {
  const resource = context.res("/api/machines");
  return card({ key: "machines", "data-write": "" }, panel(resource, {
    loading: () => h("div", { class: "card-pad" }, skeletonStack(4)),
    isEmpty: (data) => !list(data.machines).length,
    empty: (data) => h("div", { class: "card-pad" }, emptyState({
      title: "No machine but this one",
      body: `This farm (${(data.this || {}).name || "this machine"}) is the only machine `
        + "registered. Add one to run a second farm, on a droplet or on a box you already have.",
      command: "fleet machines list",
    })),
    ready: (data) => [
      staleNote(data, "stale-machines"),
      h("div", { class: "tablewrap", key: "table" }, h("table", { class: "h-machines" },
        h("thead", null, h("tr", null,
          h("th", null, "Name"),
          h("th", null, "Provider"),
          h("th", null, "Address"),
          h("th", null, "Size and price"),
          h("th", null, "State"),
          h("th", null, "Last check"),
          h("th", null, "Actions"))),
        h("tbody", null,
          data.this ? thisFarmRow(context, data.this) : null,
          list(data.machines).filter(Boolean).map((row) => machineRow(context, row))))),
      local.confirm.startsWith("destroy:")
        ? h("div", { class: "card-pad", key: "confirm" },
          destroyConfirm(context, list(data.machines), local.confirm.slice("destroy:".length)))
        : null,
      readOnlyLine("ro-machines"),
    ],
  }),
  /* Outside the panel: a refused action has to be readable whatever state the table is in,
     including the one where the table could not be read at all. */
  local.error ? h("p", { class: "m-bad card-pad", key: "err" }, local.error) : null);
}

/* ------------------------------------------------------------- the runners table */

function stageWord(row) {
  const stage = String((row || {}).stage || "").toLowerCase();
  return STAGE_WORD[stage] || stage;
}

function loginPill(row) {
  const state = String(row.login_state || "");
  const [meaning, label] = LOGIN_STATE[state] || ["pause", "Cannot tell"];
  const title = [LOGIN_TITLE[state] || "", row.account ? `Account: ${row.account}.` : "",
    row.detail || ""].filter(Boolean).join(" ");
  return pill(meaning, label, title);
}

function secretsCell(row) {
  const secrets = list(row.secrets);
  const stored = secrets.filter((item) => item && item.stored);
  /* The label stored with the token, so a person can see which subscription a lane would
     spend. The farm's Accounts windows cannot see a cloud agent's usage at all. */
  const account = (stored.find((item) => item.account) || {}).account || "";
  const title = secrets.length
    ? secrets.map((item) => `${item.name}: ${item.stored ? "stored" : "not stored"}`
      + `${item.account ? ` (${item.account})` : ""}`).join(". ")
    : "This provider needs no secret.";
  return h("div", { class: "h-cell", title },
    h("span", null, `${stored.length} of ${secrets.length}`),
    account ? h("span", { class: "muted cell-text" }, account) : null);
}

function testCell(row) {
  const tested = row.tested;
  if (!tested) {
    return h("div", { class: "h-cell" },
      pill("pause", "Not tested", "No Test has run on this farm, so nothing here has spoken to "
        + "the provider yet."),
      h("span", { class: "muted cell-text" }, NOT_LIVE));
  }
  const ok = Boolean(tested.ok);
  const seconds = Number(tested.seconds);
  const when = tested.at ? fmt.ago(tested.at) : "";
  /* Only a Test that passed clears the words: one that ran and failed has still not shown
     this farm talking to the provider (design section 5). */
  return h("div", { class: "h-cell" },
    pill(ok ? "done" : "fail", ok ? "Passed" : "Failed",
      [tested.detail || "", when ? `Last run ${when}.` : ""].filter(Boolean).join(" ")),
    h("span", { class: "muted cell-text" }, ok
      ? (Number.isFinite(seconds) && seconds > 0 ? fmt.duration(seconds) : when) : NOT_LIVE));
}

function cliCell(context, row) {
  if (row.cli_installed) {
    return h("div", { class: "h-cell" },
      h("span", null, "Installed"),
      h("span", { class: "muted cell-text mono" }, row.cli || ""));
  }
  if (!row.install) return h("span", { class: "muted" }, "Not installed");
  return copyButton(row.install, "host-install", "Copy install command",
    `Run it on this farm: ${row.install}`);
}

function runnerActions(context, row) {
  const key = runnerKey(row.id);
  const busy = Boolean(running(context, key));
  return h("div", { class: "row h-do" },
    h("button", {
      key: "check",
      class: "ghost-button small",
      "data-host-check": row.id,
      disabled: access.writable && !busy ? null : true,
      title: blocked(),
      onclick: () => startJob(context, key, { provider: row.id }, "/api/hosts/check"),
    }, busy ? "Check, running" : "Check"),
    h("button", {
      key: "test",
      class: "ghost-button small",
      "data-host-open-test": row.id,
      disabled: access.writable ? null : true,
      title: blocked() || TEST_LINE,
      onclick: () => openConnectRunner(context, row.id),
    }, "Test"),
    /* The project is the one the header is filtered to, or the one picked in the dialog; with
       neither, the line carries a placeholder rather than a project nobody chose. */
    copyButton(spawnLine(row.id, local.project || context.project), "host-spawn", "Spawn line",
      "The line that spawns a lane in this provider's sandbox."));
}

function runnerRow(context, row) {
  return h("tr", { key: row.id },
    h("td", null, h("div", { class: "h-name" },
      h("b", null, row.label || row.id),
      h("span", { class: "muted" }, stageWord(row)))),
    h("td", { title: row.install || "" }, cliCell(context, row)),
    h("td", null, loginPill(row)),
    h("td", null, secretsCell(row)),
    h("td", null, testCell(row)),
    h("td", { class: "h-do-cell" }, runnerActions(context, row)));
}

function runnersCard(context) {
  const resource = context.res("/api/hosts");
  return card({ key: "runners", "data-write": "" }, panel(resource, {
    loading: () => h("div", { class: "card-pad" }, skeletonStack(3)),
    isEmpty: (data) => !list(data.providers).filter((row) => row && row.job === "runner").length,
    empty: () => h("div", { class: "card-pad" }, emptyState({
      title: "This server lists no runner",
      body: "A runner is a provider that can hold one agent in a cloud sandbox. The page and "
        + "the server are different versions, so this table has nothing to show.",
      command: "fleet update && fleet dashboard restart",
    })),
    ready: (data) => [
      staleNote(data, "stale-runners"),
      h("div", { class: "tablewrap", key: "table" }, h("table", { class: "h-runners" },
        h("thead", null, h("tr", null,
          h("th", null, "Provider"),
          h("th", null, "CLI"),
          h("th", null, "Login"),
          h("th", null, "Secrets"),
          h("th", null, "Test"),
          h("th", null, "Actions"))),
        h("tbody", null, list(data.providers)
          .filter((row) => row && row.job === "runner")
          .map((row) => runnerRow(context, row))))),
      h("p", { class: "muted card-pad", key: "gap" }, GAP_LINE),
      readOnlyLine("ro-runners"),
    ],
  }));
}

/* ------------------------------------------------------- the add a machine dialog */

function machineProviders(context) {
  return providers(context).filter((row) => row.job === "machine");
}

function chosenProvider(context) {
  return providerById(context, local.provider);
}

function chooseProvider(context, row) {
  local.provider = row.id;
  local.plan = null;
  local.confirming = false;
  local.dialogError = "";
  const sizes = list(row.sizes);
  local.size = String(((sizes.find((size) => size && size.default) || sizes[0]) || {}).slug || "");
  local.region = regionValue(list(row.regions)[0]);
  local.port = local.port || "22";
  context.paint();
}

function providerCard(context, row, mark, extra) {
  const machineSide = mark === "machine-provider";
  const chosen = (machineSide ? local.provider : local.runner) === row.id;
  const stage = stageWord(row);
  return h("button", {
    key: row.id,
    type: "button",
    class: `choice m-preset${chosen ? " chosen" : ""}`,
    role: "radio",
    "aria-checked": String(chosen),
    [`data-${mark}`]: row.id,
    disabled: access.writable ? null : true,
    title: blocked(),
    onclick: () => (machineSide ? chooseProvider(context, row) : chooseRunner(context, row)),
  },
  h("div", { class: "m-preset-head" },
    h("b", null, row.label || row.id),
    stage ? h("span", { class: "h-stage" }, stage) : null),
  row.pricing ? h("div", { class: "muted" }, row.pricing) : null,
  row.terms ? h("div", { class: "muted" }, row.terms) : null,
  extra ? h("div", { class: "muted" }, extra) : null);
}

function priceOfSize(context) {
  const preset = chosenProvider(context);
  const size = list(preset && preset.sizes).find((item) => item && item.slug === local.size);
  const planned = local.plan && Number(local.plan.monthly_usd);
  if (Number.isFinite(planned) && planned > 0) return planned;
  return size ? Number(size.monthly_usd) : 0;
}

function sizeCards(context, preset) {
  const sizes = list(preset.sizes);
  if (!sizes.length) return null;
  return h("div", { class: "h-sizes", role: "radiogroup", "aria-label": "Size", key: "sizes" },
    sizes.map((size) => {
      const chosen = local.size === size.slug;
      return h("button", {
        key: size.slug,
        type: "button",
        class: `choice h-size${chosen ? " chosen" : ""}`,
        role: "radio",
        "aria-checked": String(chosen),
        "data-size": size.slug,
        disabled: access.writable ? null : true,
        title: blocked(),
        onclick: () => {
          local.size = size.slug;
          local.plan = null;
          local.confirming = false;
          context.paint();
        },
      },
      h("b", null, size.label || size.slug),
      h("span", { class: "muted" },
        `${fmt.num(size.vcpu, "?")} vCPU, ${fmt.num(size.ram_gb, "?")} GB, `
        + `${fmt.num(size.disk_gb, "?")} GB disk`),
      h("span", { class: "h-price" }, monthly(size.monthly_usd) || "price not known"));
    }));
}

function field(label, props, note) {
  const { "data-field": name, ...rest } = props;
  return h("label", { class: "m-field", key: name || label },
    h("span", { class: "m-label" }, label),
    h("input", { type: "text", class: "m-name", autocomplete: "off", spellcheck: "false",
      disabled: access.writable ? null : true, ...rest }),
    note ? h("span", { class: "muted" }, note) : null);
}

function nameField(context) {
  return field("Name", {
    "aria-label": "Machine name",
    "data-machine-name": "",
    "data-field": "name",
    placeholder: "athens",
    value: local.name,
    oninput: (event) => {
      local.name = event.target.value;
      local.dialogError = "";
      /* The plan on screen is for the name it was asked with. Left drawn, Review would read
         about another machine, on the step that is the last one before money starts. */
      local.plan = null;
      local.confirming = false;
      context.paint();
    },
  }, NAME_RULE);
}

function dropletFields(context, preset) {
  return [
    stepHead(2, "What it is", "The name it goes into the registry under, how big it is, where "
      + "it runs, and the key your laptop reaches it with."),
    nameField(context),
    sizeCards(context, preset),
    h("label", { class: "m-field", key: "region" },
      h("span", { class: "m-label" }, "Region"),
      h("select", {
        class: "m-name",
        "aria-label": "Region",
        "data-region": "",
        value: local.region,
        disabled: access.writable ? null : true,
        onchange: (event) => {
          local.region = event.target.value;
          local.plan = null;
          context.paint();
        },
      }, list(preset.regions).map((region) => h("option", {
        key: regionValue(region),
        value: regionValue(region),
        selected: local.region === regionValue(region),
      }, regionLabel(region))))),
    field("Your SSH public key", {
      "aria-label": "Your SSH public key",
      "data-ssh-public": "",
      "data-field": "ssh-public",
      placeholder: "ssh-ed25519 AAAA... you@laptop",
      value: local.sshPublic,
      oninput: (event) => {
        local.sshPublic = event.target.value;
        local.dialogError = "";
      },
    }, KEY_LINE),
  ];
}

function ownFields(context) {
  return [
    stepHead(2, "What it is", "The name it goes into the registry under, and how this farm "
      + "reaches it over SSH."),
    nameField(context),
    field("user@host", {
      "aria-label": "user at host",
      "data-target": "",
      "data-field": "target",
      placeholder: "farm@192.168.1.40",
      value: local.target,
      oninput: (event) => {
        local.target = event.target.value;
        local.dialogError = "";
      },
    }, "The account this farm logs in as, and the address it logs in to."),
    field("Port", {
      "aria-label": "SSH port",
      "data-port": "",
      "data-field": "port",
      placeholder: "22",
      value: local.port,
      oninput: (event) => {
        local.port = event.target.value;
        local.dialogError = "";
      },
    }, "Leave it at 22 unless this machine listens somewhere else."),
  ];
}

/* Step three, for a droplet: the provider's own login, made in a terminal on the farm. While
   this step is on screen the dialog asks the farm again every three seconds, so the state
   flips by itself when the login lands. */
function loginStep(context, preset) {
  if (preset.id === "ssh") {
    stopPoll();
    return [
      stepHead(3, "Log in", "A machine of your own needs no provider login."),
      h("p", { class: "muted", key: "own" },
        "This farm reaches it with its own key, which the check below installs and uses."),
    ];
  }
  const state = String(preset.login_state || "");
  const done = state === "logged_in";
  if (done) stopPoll(); else startPoll(context);
  const login = preset.login
    ? `ssh -t ${farmAlias(context)} ${preset.login}`
    : `ssh -t ${farmAlias(context)} doctl auth init --context murmur`;
  return [
    stepHead(3, "Log in", done
      ? "This farm is logged in to the provider."
      : "The provider's own command, in a terminal. Nothing is typed into this page."),
    !preset.cli_installed && preset.install
      ? commandRow(preset.install, "host-install-cmd", "install") : null,
    done ? null : commandRow(login, "host-login", "login"),
    h("div", { class: "row m-wait", key: "state" },
      loginPill(preset),
      h("span", { class: "muted" }, done
        ? `Logged in as ${preset.account || "this account"}.`
        : "This page is watching for it and will say so by itself.")),
  ];
}

/* Step four: what will actually run, from the farm, and the file the droplet first boots with.
   It buys nothing; it is the last place to read before money starts. */
/* The farm answers each planned command as its argument list, the way it will run it. A person
   reads and copies a shell line, so the list is joined with spaces and every argument a shell
   would split or expand is single-quoted. A list drawn as it came showed "doctl,compute,...". */
function shellWord(word) {
  const text = String(word);
  return /^[A-Za-z0-9_@%+=:,./-]+$/.test(text) ? text : `'${text.replace(/'/g, "'\\''")}'`;
}

function commandLine(command) {
  return Array.isArray(command) ? command.map(shellWord).join(" ") : String(command);
}

function reviewStep(context, preset) {
  const busy = local.planning;
  if (preset.id === "ssh") {
    /* A machine of your own is registered and checked, so there is no plan to ask the provider
       for and no price to read back. The one command that runs is shown as it is. */
    const port = local.port.trim();
    const command = `fleet machines add --name ${local.name.trim() || "<name>"} `
      + `--target ${local.target.trim() || "<user@host>"}${port && port !== "22" ? ` --port ${port}` : ""}`;
    return [
      stepHead(4, "Review", "The one command this farm will run. Nothing is bought."),
      codeBlock("The command", command, "machine-commands"),
    ];
  }
  return [
    stepHead(4, "Review", "The exact commands this farm will run, and the file the machine "
      + "boots with. Nothing is bought by looking."),
    h("div", { class: "row", key: "ask" },
      h("button", {
        class: "button small",
        "data-machine-plan": "",
        disabled: access.writable && !busy ? null : true,
        title: blocked(),
        onclick: () => askPlan(context, preset),
      }, busy ? "Asking the farm" : local.plan ? "Ask again" : "Show me")),
    local.plan ? codeBlock("The commands", list(local.plan.commands).map(commandLine).join("\n"),
      "machine-commands") : null,
    local.plan && local.plan.cloud_init
      ? codeBlock("The cloud-init file", local.plan.cloud_init, "machine-cloudinit") : null,
    local.plan && monthly(local.plan.monthly_usd)
      ? h("p", { class: "muted", key: "price" },
        `The live price is ${monthly(local.plan.monthly_usd)}`
        + `${local.plan.price_source ? ` (${local.plan.price_source})` : ""}.`)
      : null,
  ];
}

function codeBlock(label, body, mark) {
  return h("div", { class: "h-block", key: mark },
    h("div", { class: "row" },
      h("span", { class: "m-label" }, label),
      h("div", { class: "spacer" }),
      h("button", {
        class: "button small",
        [`data-copy-${mark}`]: "",
        onclick: () => copyCommand(body),
      }, "Copy")),
    h("pre", { class: "h-code", [`data-${mark}`]: "", tabindex: "0" }, body));
}

async function askPlan(context, preset) {
  const problem = validate(context, preset, false);
  if (problem) {
    local.dialogError = problem;
    context.paint();
    return;
  }
  local.dialogError = "";
  local.planning = true;
  context.paint();
  try {
    const body = { provider: preset.id, name: local.name.trim(), size: local.size,
      region: local.region };
    if (local.sshPublic.trim()) body.ssh_public = local.sshPublic.trim();
    local.plan = await apiPost("/api/machines/plan", body);
  } catch (error) {
    local.dialogError = serverReason(error) || "The farm did not answer with a plan.";
  } finally {
    local.planning = false;
    context.paint();
  }
}

/** Everything the page can refuse before a request goes out, said in the farm's own rules. */
function validate(context, preset, full) {
  const name = local.name.trim();
  if (!name) return "Give the machine a name, for example athens.";
  if (!NAME_RE.test(name)) return NAME_RULE;
  if (preset.id === "ssh") {
    const target = local.target.trim();
    if (!target) return "Say which account and address this farm logs in to, as user@host.";
    if (!TARGET_RE.test(target)) return "A target reads user@host, for example farm@192.168.1.40.";
    const port = local.port.trim();
    if (port && !/^\d{1,5}$/.test(port)) return "A port is a whole number.";
    if (port && (Number(port) < 1 || Number(port) > 65535)) return "A port is between 1 and 65535.";
    return "";
  }
  if (!local.size) return "Pick a size.";
  if (!local.region) return "Pick a region.";
  const key = local.sshPublic.trim();
  /* The key is required to buy a machine, because without it the finish command and the tunnel,
     both run from a laptop, cannot log in. Review asks for a plan and buys nothing, so it does
     not insist: what it does insist on, at every step, is that the value is not a secret. */
  if (!key) {
    return full ? "Paste your SSH public key: without it your laptop cannot reach the machine." : "";
  }
  /* The value is never written into this sentence, or into any other. */
  if (TOKEN_SHAPES.some((shape) => shape.test(key))) return TOKEN_REFUSAL;
  if (!PUBLIC_KEY_RE.test(key)) {
    return "That is not one line of a public key. It starts with ssh-ed25519, ssh-rsa or "
      + "ecdsa-sha2, and it is the .pub file, never the private one.";
  }
  if (full && !(priceOfSize(context) > 0)) {
    return "The price of that size is not known, so there is nothing to confirm.";
  }
  return "";
}

function createStep(context, preset) {
  const own = preset.id === "ssh";
  const price = monthly(priceOfSize(context));
  const name = local.name.trim();
  const job = running(context, machineKey(name || "new"), "dialogError");
  const busy = Boolean(job) || local.sending;
  if (own) {
    return [
      stepHead(5, "Add and check", "This registers the machine and checks that this farm can "
        + "reach it. Nothing is bought."),
      h("div", { class: "row m-dialog-actions", key: "acts" },
        h("button", {
          class: "button primary",
          "data-machine-create": "",
          disabled: access.writable && !busy ? null : true,
          title: blocked(),
          onclick: () => createMachine(context, preset),
        }, busy ? "Adding" : "Add and check"),
        h("button", { class: "ghost-button", onclick: () => closeDrawer() }, "Cancel")),
    ];
  }
  return [
    stepHead(5, "Create it", `This buys a droplet. ${BILL_LINE}`),
    local.confirming
      ? h("div", { class: "m-confirm", key: "confirm" },
        h("h3", null, `Create ${name || "this machine"} at ${price || "an unknown price"}?`),
        h("p", null, BILL_LINE),
        h("div", { class: "row" },
          h("button", {
            class: "button primary",
            "data-machine-create": "",
            disabled: access.writable && !busy ? null : true,
            title: blocked(),
            onclick: () => createMachine(context, preset),
          }, busy ? "Creating" : `Create, ${price}`),
          h("button", {
            class: "ghost-button",
            onclick: () => {
              local.confirming = false;
              context.paint();
            },
          }, "Not yet")))
      : h("div", { class: "row m-dialog-actions", key: "acts" },
        h("button", {
          class: "button primary",
          "data-machine-create-open": "",
          disabled: access.writable && !busy ? null : true,
          title: blocked(),
          onclick: () => openCreateConfirm(context, preset),
        }, price ? `Create, ${price} until you destroy it` : "Create"),
        h("button", { class: "ghost-button", onclick: () => closeDrawer() }, "Cancel")),
    job ? h("p", { class: "muted", key: "job" },
      `Job ${job.id} is running: ${job.detail || "asking the provider"}.`) : null,
  ];
}

function openCreateConfirm(context, preset) {
  const problem = validate(context, preset, true);
  if (problem) {
    local.dialogError = problem;
    local.confirming = false;
    context.paint();
    return;
  }
  local.dialogError = "";
  local.confirming = true;
  context.paint();
}

async function createMachine(context, preset) {
  const problem = validate(context, preset, true);
  if (problem) {
    local.dialogError = problem;
    context.paint();
    return;
  }
  if (local.sending) return;
  const name = local.name.trim();
  const body = preset.id === "ssh"
    ? { provider: "ssh", name, target: local.target.trim() }
    : {
      provider: preset.id,
      name,
      size: local.size,
      region: local.region,
      ssh_public: local.sshPublic.trim(),
      confirm_usd: priceOfSize(context),
    };
  /* A string, as every other field in every body is: the server matches it against a pattern
     before any argv is built, and a pattern is matched against text. */
  if (preset.id === "ssh" && local.port.trim()) body.port = String(local.port.trim());
  /* The button goes off before the request leaves, not when the job comes back: a farm that
     takes a second and a half to answer would otherwise leave an armed button on screen for
     all of it, and a second press would ask for a second droplet. */
  local.sending = true;
  local.confirming = false;
  context.paint();
  try {
    await startJob(context, machineKey(name), body, "/api/machines", "dialogError");
  } finally {
    local.sending = false;
    /* startJob has already painted in its own finally, while this flag was still up, so a
       refused create would keep drawing a disabled "Creating" until the next tick. */
    context.paint();
  }
  /* Only now: a dialog that starts waiting before the farm has answered can close itself on
     the paint between the press and the answer, taking the reader off the step they pressed. */
  if (local.jobs[machineKey(name)]) local.created = name;
  else if (!local.dialogError) closeDrawer();
}

function addMachineSteps(context, rows) {
  const preset = chosenProvider(context);
  const name = local.name.trim();
  /* The job is watched from here, so the dialog can close itself when the farm has the row and
     let the table take over: the row moves from creating to preparing on its own. */
  const job = local.created ? running(context, machineKey(local.created), "dialogError") : null;
  if (local.created && !job && !local.dialogError && !local.jobs[machineKey(local.created)]) {
    afterPaint(() => closeDrawer());
  }
  return h("div", { class: "m-steps", key: "steps" },
    stepHead(1, "Where it runs", "A machine runs a whole farm. A runner is a different thing "
      + "and is connected further down the page."),
    h("div", { class: "m-presets", role: "radiogroup", "aria-label": "Provider", key: "cards" },
      rows.map((row) => providerCard(context, row, "machine-provider"))),
    preset ? (preset.id === "ssh" ? ownFields(context) : dropletFields(context, preset)) : null,
    preset ? loginStep(context, preset) : null,
    preset ? reviewStep(context, preset) : null,
    preset ? createStep(context, preset) : null,
    local.dialogError
      ? h("p", { class: "m-bad", key: "err", role: "alert" }, local.dialogError) : null,
    job ? h("p", { class: "muted", key: "wait" },
      `${name || local.created} is being built. This dialog closes when the farm has the row.`)
      : null,
    readOnlyLine("ro-add-machine"));
}

function addMachineBody(context) {
  const resource = context.res("/api/hosts");
  return panel(resource, {
    loading: () => skeletonStack(4),
    isEmpty: () => !machineProviders(context).length,
    empty: () => emptyState({
      title: "This farm lists no provider a machine can run on",
      body: "A provider is a preset the server knows how to build a machine with.",
      command: "fleet hosts list",
    }),
    ready: () => addMachineSteps(context, machineProviders(context)),
  });
}

export function openAddMachine(context) {
  local.provider = "";
  local.name = "";
  local.size = "";
  local.region = "";
  local.sshPublic = "";
  local.target = "";
  local.port = "22";
  local.plan = null;
  local.planning = false;
  local.confirming = false;
  local.created = "";
  local.dialogError = "";
  openDrawer({
    key: ADD_MACHINE_KEY,
    title: "Add a machine",
    sub: "A machine runs a whole farm: worktrees, the queue and a dashboard of its own.",
    body: () => addMachineBody(context),
    onClose: () => {
      stopPoll();
      local.plan = null;
      local.confirming = false;
      local.created = "";
      local.dialogError = "";
      context.refresh("/api/machines");
    },
  });
}

/* ----------------------------------------------------- the connect a runner dialog */

function runnerProviders(context) {
  return providers(context).filter((row) => row.job === "runner");
}

function chooseRunner(context, row) {
  local.runner = row.id;
  local.dialogError = "";
  context.paint();
}

function spawnLine(provider, project) {
  return `fleet spawn --project ${project || "<project>"} --lane <name> --engine claude `
    + `--model sonnet --runner ${provider} --task "..."`;
}

function installStep(context, row) {
  const done = Boolean(row.cli_installed);
  return [
    stepHead(2, "Install the CLI", done
      ? `${row.cli || "The provider's command"} is on this farm.`
      : "The provider's own command, installed on the farm, in a terminal."),
    done ? null : commandRow(row.install || `install ${row.cli || row.id}`, "runner-install", "install"),
    h("div", { class: "row m-wait", key: "state" },
      pill(done ? "done" : "wait", done ? "Installed" : "Not installed", row.detail || ""),
      h("span", { class: "muted" }, done
        ? "Nothing to do here." : "This page is watching for it.")),
  ];
}

function runnerLoginStep(context, row) {
  const done = String(row.login_state || "") === "logged_in";
  return [
    stepHead(3, "Log in", done
      ? "This farm is logged in to the provider."
      : "The login is made by the provider's own command, never through this page."),
    done ? null : commandRow(`ssh -t ${farmAlias(context)} ${row.login || `${row.cli || row.id} login`}`,
      "runner-login", "login"),
    h("div", { class: "row m-wait", key: "state" },
      loginPill(row),
      h("span", { class: "muted" }, done
        ? `Logged in as ${row.account || "this account"}.`
        : "This page is watching for it and will say so by itself.")),
  ];
}

function secretsStep(context, row) {
  const secrets = list(row.secrets);
  return [
    stepHead(4, "Store the secrets", "Each one is typed into your own terminal and read from "
      + "there. The value never passes through this page, and never reaches a command line."),
    secrets.length
      ? secrets.map((secret) => h("div", { class: "h-secret", key: secret.name },
        h("div", { class: "row" },
          h("b", null, secret.name),
          pill(secret.stored ? "done" : "wait", secret.stored ? "Stored" : "Not stored",
            secret.account ? `Stored for ${secret.account}.` : "")),
        h("p", { class: "muted" }, SECRET_HINTS[secret.name] || "a value this runner needs"),
        commandRow(`ssh -t ${farmAlias(context)} fleet hosts secret ${row.id} ${secret.name}`,
          "runner-secret", `secret:${secret.name}`)))
      : h("p", { class: "muted", key: "none" }, "This provider needs no secret."),
  ];
}

function testStep(context, row) {
  const key = runnerKey(row.id);
  const job = running(context, key, "dialogError");
  const projects = list(context.res("/api/projects").data).filter(Boolean);
  const tested = row.tested;
  return [
    stepHead(5, "Test it", "One real sandbox, started and deleted again, so you know this works "
      + "before a lane depends on it."),
    h("label", { class: "m-field", key: "project" },
      h("span", { class: "m-label" }, "Project"),
      h("select", {
        class: "m-name",
        "aria-label": "Project",
        "data-test-project": "",
        value: local.project,
        disabled: access.writable ? null : true,
        onchange: (event) => {
          local.project = event.target.value;
          context.paint();
        },
      /* Every option says whether it is the chosen one, the placeholder included. Leaving that
         off the placeholder left the select showing the last project in the list while its
         value was empty, which is a select that lies about what pressing Test would do. */
      }, [h("option", { key: "none", value: "", selected: !local.project }, "Pick a project"),
        ...projects.map((project) => h("option", {
          key: project.name, value: project.name, selected: local.project === project.name,
        }, project.name))])),
    h("p", { class: "muted", key: "cost" }, TEST_LINE),
    h("div", { class: "row m-dialog-actions", key: "acts" },
      h("button", {
        class: "button primary",
        "data-host-test": row.id,
        disabled: access.writable && local.project && !job ? null : true,
        title: blocked() || (local.project ? "" : "Pick a project first."),
        onclick: () => startJob(context, key,
          { provider: row.id, project: local.project, confirm: true },
          "/api/hosts/test", "dialogError"),
      }, job ? "Testing" : "Test it")),
    job
      ? h("p", { class: "muted", key: "job" },
        `Job ${job.id} is running: ${job.detail || "starting a sandbox"}.`)
      : h("div", { class: "row m-wait", key: "result" }, testCell(row),
        h("span", { class: "muted" }, tested
          ? tested.detail || "" : "Nothing here has spoken to the provider yet.")),
  ];
}

function spawnStep(context, row) {
  return [
    stepHead(6, "Spawn a lane in it", "Spawning stays a command: the page does not spawn."),
    commandRow(spawnLine(row.id, local.project), "runner-spawn", "spawn"),
  ];
}

function connectRunnerSteps(context, rows) {
  const row = providerById(context, local.runner);
  if (row) startPoll(context); else stopPoll();
  return h("div", { class: "m-steps", key: "steps" },
    stepHead(1, "Pick a provider", "A runner holds one agent at a time, in a sandbox. The farm "
      + "keeps the worktree, the claim and the pull request."),
    h("div", { class: "m-presets", role: "radiogroup", "aria-label": "Runner", key: "cards" },
      rows.map((item) => providerCard(context, item, "runner-provider",
        item.id === "do-agents" ? DO_AGENTS_LINE : ""))),
    row ? installStep(context, row) : null,
    row ? runnerLoginStep(context, row) : null,
    row ? secretsStep(context, row) : null,
    row ? testStep(context, row) : null,
    row ? spawnStep(context, row) : null,
    local.dialogError
      ? h("p", { class: "m-bad", key: "err", role: "alert" }, local.dialogError) : null,
    h("div", { class: "row m-dialog-actions", key: "close" },
      h("button", { class: "ghost-button", "data-runner-done": "", onclick: () => closeDrawer() },
        "Done")),
    readOnlyLine("ro-connect-runner"));
}

function connectRunnerBody(context) {
  const resource = context.res("/api/hosts");
  return panel(resource, {
    loading: () => skeletonStack(4),
    isEmpty: () => !runnerProviders(context).length,
    empty: () => emptyState({
      title: "This farm lists no runner",
      body: "A runner is a provider that can hold one agent in a cloud sandbox.",
      command: "fleet hosts list",
    }),
    ready: () => connectRunnerSteps(context, runnerProviders(context)),
  });
}

export function openConnectRunner(context, provider) {
  local.runner = provider || "";
  local.dialogError = "";
  openDrawer({
    key: CONNECT_RUNNER_KEY,
    title: "Connect a runner",
    sub: "A runner holds one agent at a time, in a sandbox in the cloud.",
    body: () => connectRunnerBody(context),
    onClose: () => {
      stopPoll();
      local.dialogError = "";
      context.refresh("/api/hosts");
    },
  });
}

/* ------------------------------------------------------------------- the section */

export function hostingSection(context) {
  /* The total is the farm's own answer, so it is said only when the farm has answered. A head
     that reads "nothing is billed" over a route that could not be read is the one sentence on
     this page that would cost a person money. */
  const machines = context.res("/api/machines").data;
  let total = machines && !machines.pending ? totalLine(machines) : "";
  /* A total read from a snapshot that could not be refreshed is an old total, and says so:
     a bill stated in the present tense from a half hour old reading is not what it looks like. */
  if (total && machines.stale_since) {
    total = `${total} Not refreshed since ${fmt.ago(machines.stale_since)}.`;
  }
  return h("section", { class: "section", key: "hosting" },
    sectionHead("Hosting", HEAD_LINE,
      total ? h("span", { class: "muted", "data-hosting-total": "", key: "total" }, total) : null,
      h("div", { class: "row h-head-do", key: "buttons" },
        h("button", {
          key: "add-machine",
          class: "button small",
          "data-add-machine": "",
          disabled: access.writable ? null : true,
          title: blocked(),
          onclick: () => openAddMachine(context),
        }, "Add a machine"),
        h("button", {
          key: "connect-runner",
          class: "button small",
          "data-connect-runner": "",
          disabled: access.writable ? null : true,
          title: blocked(),
          onclick: () => openConnectRunner(context, ""),
        }, "Connect a runner"))),
    machinesCard(context),
    h("div", { class: "gap-sm", key: "gap" }),
    runnersCard(context));
}

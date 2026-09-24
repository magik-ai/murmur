/* Projects: the repositories a lane may be opened in, and the GitHub login every agent on this
   farm acts as (design record fleet/docs/design/github-projects.md, sections 3 to 5).

   Three pieces, top to bottom: a strip that says in words what the farm's GitHub login lets the
   agents do, the Import dialog that lists what that login can reach and checks it before the
   clone, and the six-column table. The page never sees a token: a login happens in the
   person's own terminal, and a token typed into the paste field is refused before any request.

   The snapshot behind GET /api/github is a local read, but it describes the one account every
   agent spends, so it is asked for only when it is worth asking: once when the tab opens, then
   once a minute, and every three seconds only while the Connect dialog waits for a login.
   POST /api/github/check asks GitHub, so it runs on a press and never on a timer. */

import {
  h, card, panel, pill, emptyState, skeletonStack, toast, safeHref,
  openDrawer, closeDrawer, openDrawerKey,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason, resource } from "../core/api.js";
import {
  sectionHead, stepHead, commandRow, copyCommand, farmAlias, readOnlyLine, blocked,
} from "./machine.js";

const CONNECT_KEY = "github-connect";
const IMPORT_KEY = "github-import";

/* The snapshot is read again this often while nothing is waiting on it. */
const QUIET_READ_MS = 60000;
/* And this often while the Connect dialog waits for a login. */
const CONNECT_POLL_MS = 3000;
/* The server's own cooldown on POST /api/github/check, used until it names one. */
const CHECK_QUIET_MS = 60000;
/* A pass can make twenty or more GitHub calls of up to 20 seconds each, so no wait is long
   enough to cap it: the page reads until "checking" clears or the reader leaves the Machine tab.
   The first reads are quick because most passes answer in seconds; later ones come at a pace
   close to the page's own three second tick, so a long pass adds nothing a person would notice. */
const CHECK_READ_FAST_MS = 1000;
const CHECK_READ_SLOW_MS = 5000;
const CHECK_FAST_READS = 10;
const SEARCH_DEBOUNCE_MS = 300;
/* The access checks cost GitHub calls, so Check again rests this long after an answer. */
const CHECK_AGAIN_REST_MS = 10000;
/* The registry's own rule for a project name (server.py PROJECT_NAME). */
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$/;
const NAME_LIMIT = 40;
const REPO_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/;
const PORT_BLOCK = 100;
const SSO_LINK = "https://github.com/settings/connections/applications/178c6fc778ccc68e1d6a";

/* What a token looks like, so one pasted by mistake never leaves the page: the classic and
   fine-grained personal tokens, the OAuth, user, server and refresh tokens, and a bare forty
   character hex string, which is what an old token is. */
const TOKEN_LOOK = /(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|^[0-9a-f]{40}$)/i;

/* The sentence for a token caught in any field of the page: the paste field, the project name,
   the typed branch and the search. `what` is what the field should have held. */
function tokenRefusal(what) {
  return `That looks like a GitHub token, not ${what}. A token never goes through this page, `
    + "and nothing was sent.";
}

function looksLikeToken(value) {
  return TOKEN_LOOK.test(String(value || "").trim());
}

/* A role on GitHub, in the page's words. The pill is the role, not a guarantee: the first push
   is the final proof, and the check step says so. */
const ROLE = {
  admin: ["done", "Admin", "Admin: agents can push here, and this account can change its settings."],
  maintain: ["done", "Write", "Write (maintain): agents can push branches and open pull requests."],
  write: ["done", "Write", "Write: agents can push branches and open pull requests."],
  triage: ["wait", "Read", "Read (triage): agents can copy it but cannot push."],
  read: ["wait", "Read", "Read: agents can copy it but cannot push."],
  no_access: ["fail", "No access", "This account cannot reach this repository. Grant it access on "
    + "GitHub, or Remove the project."],
};
const PUSHES = ["admin", "maintain", "write"];

/* What a missing scope stops, said as what the agents cannot do. */
const SCOPE_LOSS = {
  repo: "Agents cannot copy or push private repositories",
  workflow: "Agents cannot change CI workflow files",
};

const CHECK_MEANING = { ok: "done", warn: "wait", fail: "fail" };
const CHECK_WORD = { ok: "ok", warn: "warning", fail: "fails" };

const gh = {
  connectOpen: false,
  connectMode: "connect",
  connectFrom: "",
  poll: 0,
  checkBusy: false,
  checkQuietUntil: 0,
  checkError: "",
  confirm: "",
  removeBusy: "",
  removeError: "",
  imp: null,
  /* Every import this page started, followed until its job ends whether or not the dialog is
     still open: {id, name, repo, detail, ended, error}. A failed one stays until dismissed. */
  jobs: [],
};

function freshImport() {
  return {
    step: 1,
    owner: "",
    q: "",
    timer: 0,
    seq: 0,
    repos: null,
    truncated: false,
    reposBusy: false,
    reposError: "",
    qError: "",
    paste: "",
    pasteError: "",
    pasteBusy: false,
    repo: null,
    name: "",
    nameError: "",
    branches: null,
    branchesFor: "",
    branchesBusy: false,
    branchesError: "",
    branch: "",
    typed: false,
    typedBranch: "",
    portOpen: false,
    port: "",
    checks: null,
    checkBusy: false,
    checkError: "",
    checkedAt: 0,
    importBusy: false,
    importError: "",
    jobId: "",
  };
}

/* -------------------------------------------------------------- reading */

function snapshot(context) {
  return context.res("/api/github");
}

/**
 * The routes this section wants on the tick. GET /api/github is always a local read, but it is
 * only worth three seconds of attention while a person waits for a login. The Connect dialog
 * keeps that clock itself (pollWhileOpen), so the tick leaves it alone then, and otherwise reads
 * it once and again once a minute.
 */
export function githubNeeds() {
  if (gh.connectOpen) return [];
  const entry = resource("/api/github");
  if (!entry.everLoaded && !entry.lastTry) return ["/api/github"];
  return Date.now() - entry.lastTry >= QUIET_READ_MS ? ["/api/github"] : [];
}

function commands(data, context) {
  const farm = farmAlias(context);
  const given = (data && data.commands) || {};
  return {
    login: given.login || `ssh -t ${farm} gh auth login -h github.com -p https --web -s workflow`,
    refresh_scopes: given.refresh_scopes || `ssh -t ${farm} gh auth refresh -h github.com -s workflow`,
    setup_git: given.setup_git || `ssh -t ${farm} gh auth setup-git`,
    switch: given.switch || `ssh -t ${farm} gh auth switch`,
  };
}

/* The scopes the login lacks: the server's list, and both required ones when the token carries
   no scope at all. Null scopes (a token kind that hides them) lack nothing that can be told. */
function lacking(data) {
  const missing = list(data.missing_scopes).slice();
  if (Array.isArray(data.scopes) && !data.scopes.length) {
    for (const scope of Object.keys(SCOPE_LOSS)) if (!missing.includes(scope)) missing.push(scope);
  }
  return missing;
}

/* What the agents can do with this login, in one sentence built from every missing scope. */
function headline(missing) {
  if (!missing.length) {
    return "Agents can copy, push and change CI files in every repository this account can reach.";
  }
  if (missing.length === 1 && missing[0] === "workflow") {
    return "Agents can copy and push in every repository this account can reach.";
  }
  const losses = missing.map((scope) => SCOPE_LOSS[scope] || `The ${scope} scope is missing`);
  return `${losses.join(". ")}.`;
}

function connected(data) {
  return Boolean(data && data.login_state === "connected");
}

/* "Signed in as @name", or, when gh reported no name, that a login exists at all. */
function signedIn(data) {
  return data && data.login ? `Signed in as @${data.login}` : "Signed in to GitHub";
}

/* Whether GitHub has answered about the account yet. Until it has, the page says so and promises
   nothing about what the agents may do (a login can land while the account call is refused). */
function accountRead(data) {
  return Boolean(data && data.account_read !== false);
}

function scopeText(data) {
  if (!data) return "";
  if (data.scopes === null || data.scopes === undefined) {
    return "The scopes cannot be read for this kind of token; the access check still applies.";
  }
  const scopes = list(data.scopes);
  return scopes.length ? `Scopes: ${scopes.join(", ")}` : "This token carries no scopes at all.";
}

/* The two-identities finding: null, or {file, line, variable} with the line's number (the
   shape github_access.py settled). Anything else draws nothing. */
function twoIdentities(value) {
  if (!value || typeof value !== "object") return null;
  const file = typeof value.file === "string" ? value.file.trim() : "";
  const variable = typeof value.variable === "string" ? value.variable.trim() : "";
  const line = Number(value.line);
  if (!file || !variable || !Number.isInteger(line) || line < 1) return null;
  return { file, line, variable };
}

/* "pushed 3 days ago": whole words, the largest unit that carries information. */
function pushedAgo(value) {
  const at = fmt.seconds(value);
  if (at == null) return "never pushed";
  const delta = Math.max(0, Date.now() / 1000 - at);
  const units = [[31536000, "year"], [2592000, "month"], [86400, "day"], [3600, "hour"], [60, "minute"]];
  for (const [size, word] of units) {
    const count = Math.floor(delta / size);
    if (count >= 1) return `pushed ${count} ${word}${count === 1 ? "" : "s"} ago`;
  }
  return "pushed just now";
}

function roleFor(permission, data) {
  /* A signed-in farm whose account GitHub has not answered about yet is not "not connected":
     the strip says Connected, so the cell must not contradict it. */
  if (permission == null && connected(data) && !accountRead(data)) {
    return ["pause", "Not known", "This account has not been read yet, so its access to this "
      + "repository is not known yet."];
  }
  if (permission == null) return ["pause", "Not known", "GitHub is not connected on this farm, so "
    + "this account's access cannot be read."];
  return ROLE[permission] || ["pause", fmt.titleCase(permission), `GitHub says: ${permission}.`];
}

function repoHref(row) {
  return safeHref(row.html_url) || (REPO_RE.test(String(row.repo || ""))
    ? `https://github.com/${row.repo}` : null);
}

/* One line in a table cell: cut with an ellipsis, the whole text in the title. */
function line(text, extra = {}) {
  const value = String(text ?? "");
  return h("span", { class: "p-cut", title: extra.title || value, ...extra, key: extra.key }, value);
}

/* -------------------------------------------------------------- re-check */

async function recheck(context) {
  if (gh.checkBusy || Date.now() < gh.checkQuietUntil) return;
  gh.checkBusy = true;
  gh.checkError = "";
  context.paint();
  let running = false;
  let answeredAt = 0;
  try {
    await apiPost("/api/github/check", {});
    answeredAt = Date.now();
    gh.checkQuietUntil = Date.now() + CHECK_QUIET_MS;
    running = true;
    toast("GitHub was asked again.");
  } catch (error) {
    const wait = Number(error && error.payload && error.payload.retry_after);
    if (error && error.status === 429) {
      gh.checkQuietUntil = Date.now() + (Number.isFinite(wait) && wait > 0 ? wait * 1000 : CHECK_QUIET_MS);
    }
    /* A 409 means a check is already running: its answer is worth waiting for too. */
    running = Boolean(error && error.status === 409);
    answeredAt = Date.now();
    if (!running) gh.checkError = serverReason(error) || "GitHub was not asked again.";
  } finally {
    /* The farm answers the press at once and checks in the background, with "checking" set
       until that pass answers. The page waits a moment (a read already in flight may carry the
       answer from before the press), then reads until "checking" clears, so the new answer shows
       in seconds rather than at the next minute's read. The strip stays drawn all along. Only a
       read that started after the farm answered the press counts: one still in flight from
       before carries "checking" clear with the old answer, and would end the wait early. */
    if (running) {
      for (let tries = 0; ; tries += 1) {
        const step = !tries ? 800 : tries < CHECK_FAST_READS ? CHECK_READ_FAST_MS : CHECK_READ_SLOW_MS;
        await new Promise((resolve) => setTimeout(resolve, step));
        if (context.view !== "machine") break;
        await context.refresh("/api/github");
        const entry = context.res("/api/github");
        if (entry.inflight || !(entry.lastTry > answeredAt)) continue;
        if (entry.state === "error" || !entry.data || !entry.data.checking) break;
      }
    } else {
      await context.refresh("/api/github");
    }
    gh.checkBusy = false;
    context.paint();
  }
}

function recheckButton(context) {
  const left = gh.checkQuietUntil - Date.now();
  const quiet = left > 0;
  return h("button", {
    class: "ghost-button small",
    key: "recheck",
    "data-github-check": "",
    disabled: access.writable && !quiet && !gh.checkBusy ? null : true,
    title: blocked() || (quiet ? "Asking GitHub again this soon changes nothing." : ""),
    onclick: () => recheck(context),
  }, gh.checkBusy ? "Asking GitHub" : quiet ? `Re-check (in ${fmt.duration(left / 1000)})` : "Re-check");
}

/* -------------------------------------------------------------- the strip */

function stripLine([meaning, word], words, title, key, ...extra) {
  return h("div", { class: `p-strip-line ${meaning}`, key, "data-strip": key },
    pill(meaning, word, title),
    h("span", { class: "p-strip-words", title: title || words }, words),
    extra.length ? h("span", { class: "p-strip-acts" }, ...extra) : null);
}

function copyButton(command, mark) {
  return h("button", {
    class: "ghost-button small",
    [`data-copy-${mark}`]: "",
    title: command,
    onclick: () => copyCommand(command),
  }, "Copy the command");
}

function connectButton(context, small) {
  return h("button", {
    class: small ? "button small primary" : "button primary",
    key: "connect",
    "data-github-connect": "",
    onclick: () => openConnect(context, "connect"),
  }, "Connect GitHub");
}

function officeLine(data) {
  const office = data.office || {};
  if (!office.repo) {
    return stripLine(["pause", "No office"], "No head office is configured on this farm, so there is no office "
      + "for this login to write to.", office.detail || "", "office");
  }
  if (office.writable) {
    return stripLine(["done", "Head office"], `This login can write to the head office ${office.repo}.`,
      office.detail || "", "office");
  }
  if (!REPO_RE.test(String(office.repo))) {
    /* A misconfiguration never clears by itself, so it is not drawn as a wait. */
    return stripLine(["fail", "Head office"], `The head office "${office.repo}" is not written as owner/name, `
      + "so this login's access to it cannot be checked. Set it as owner/name in hq's config.", office.detail || "",
    "office");
  }
  if (office.writable === null || office.writable === undefined) {
    return stripLine(["pause", "Not checked"], `Whether this login can write to the head office ${office.repo} `
      + "is not known yet.", office.detail || "", "office");
  }
  const why = office.detail ? `: ${office.detail}` : ".";
  return stripLine(["fail", "Head office"], `This login cannot write to the head office ${office.repo}${why}`,
    office.detail || "", "office");
}

function strip(context, data, projects) {
  const cmd = commands(data, context);
  const state = data.login_state;
  const lines = [];
  if (state === "no_gh") {
    lines.push(stripLine(["fail", "No gh"], "GitHub's command line tool, gh, is not installed on this farm, so "
      + "no agent can copy or push a repository.", "Install gh on the farm, then sign in with it.",
    "state", recheckButton(context)));
  } else if (state === "no_answer") {
    lines.push(stripLine(["pause", "No answer"], "This farm's gh did not answer, so whether GitHub is connected "
      + "cannot be told right now.", data.error || "", "state", recheckButton(context)));
  } else if (state === "not_connected") {
    lines.push(stripLine(["fail", "Not connected"], "GitHub is not connected on this farm.",
      "gh reports no account at all.", "state", connectButton(context, true)));
  } else if (state === "connected") {
    const read = accountRead(data);
    const missing = read ? lacking(data) : [];
    const can = read ? headline(missing)
      : "What the agents may do is not known yet: GitHub has not answered about the account.";
    lines.push(stripLine(["done", "Connected"], `${signedIn(data)}. ${can}`,
      read ? scopeText(data) : (data.error || "The account is read again at the next check."), "state",
      recheckButton(context),
      h("button", {
        class: "p-link",
        key: "switch",
        "data-github-switch": "",
        onclick: () => openConnect(context, "switch"),
      }, "Switch account")));
    if (read && (data.scopes === null || data.scopes === undefined)) {
      lines.push(h("p", { class: "muted p-strip-note", key: "scopes" }, scopeText(data)));
    }
    for (const scope of missing) {
      lines.push(stripLine(["wait", "Scope missing"], `${SCOPE_LOSS[scope] || `The ${scope} scope is missing`}: the `
        + `login lacks the ${scope} scope.`, cmd.refresh_scopes, `scope-${scope}`,
      copyButton(cmd.refresh_scopes, "refresh-scopes")));
    }
    if (data.git_uses_login === false) {
      lines.push(stripLine(["wait", "Git"], "Git on this farm does not use this login, so agents cannot "
        + "copy or push with it.", cmd.setup_git, "git", copyButton(cmd.setup_git, "setup-git")));
    }
    lines.push(officeLine(data));
    const noAccess = projects.filter((row) => row.permission === "no_access").length;
    if (noAccess) {
      lines.push(stripLine(["fail", "No access"], `${noAccess} ${noAccess === 1 ? "project is" : "projects are"} `
        + "out of this account's reach: see No access in the table.",
      "Grant this account access on GitHub, or Remove the project.", "no-access"));
    }
  } else {
    lines.push(stripLine(["pause", "Unknown"], "The server reported a GitHub state this page does not know.",
      String(state || ""), "state", recheckButton(context)));
  }
  const two = twoIdentities(data.two_identities);
  if (two) {
    lines.push(stripLine(["wait", "Two identities"], `Two identities: ${two.variable} is set in ${two.file}. The farm's `
      + "systemd units (the daemon, the sweep and the dashboard's own) load that file and the lanes do not, so "
      + `this farm acts as two accounts. Remove line ${two.line} (${two.variable}=...) from ${two.file}.`,
    `${two.file}:${two.line}`, "two"));
  }
  if (data.stale_since) {
    lines.push(h("p", { class: "muted p-strip-note", key: "stale",
      title: data.rate_remaining != null ? `${data.rate_remaining} GitHub calls left this hour` : "" },
    `Last read at ${new Date(data.stale_since).toLocaleTimeString("en-US")}. `
    + (data.error || "GitHub's allowance for this hour is low, so the farm keeps its last answer.")));
  }
  if (gh.checkError) lines.push(h("p", { class: "m-bad", key: "check-error" }, gh.checkError));
  return h("div", { class: "p-strip", key: "strip", "data-login-state": state || "" }, lines);
}

function stripCard(context, projects) {
  return card({ class: "card-pad", key: "github", "data-write": "" }, panel(snapshot(context), {
    loading: () => skeletonStack(2),
    ready: (data) => strip(context, data, projects),
  }));
}

/* --------------------------------------------------- connect and switch */

/* Every three seconds on the dialog's own clock, whatever the tick is doing: the flip to "signed
   in" is the one thing the reader is waiting for. The clock stops when the dialog closes. */
function pollWhileOpen(context) {
  stopPolling();
  gh.poll = setInterval(() => {
    if (!gh.connectOpen) {
      stopPolling();
      return;
    }
    context.refresh("/api/github");
  }, CONNECT_POLL_MS);
}

function stopPolling() {
  if (gh.poll) clearInterval(gh.poll);
  gh.poll = 0;
}

function openConnect(context, mode) {
  gh.connectOpen = true;
  gh.connectMode = mode;
  gh.connectFrom = (snapshot(context).data || {}).login || "";
  openDrawer({
    key: CONNECT_KEY,
    title: mode === "switch" ? "Switch the GitHub account" : "Connect GitHub",
    sub: "The login happens in your terminal, by GitHub's own device flow. This page never sees a token.",
    body: () => connectBody(context),
    onClose: () => {
      gh.connectOpen = false;
      stopPolling();
    },
  });
  pollWhileOpen(context);
  context.paint();
}

function connectBody(context) {
  const data = snapshot(context).data || {};
  const cmd = commands(data, context);
  const switching = gh.connectMode === "switch";
  const done = switching
    ? connected(data) && data.login && data.login !== gh.connectFrom
    : connected(data);
  return h("div", { class: "m-steps", key: "connect" },
    h("p", { class: "p-lead", key: "lead", "data-connect-lead": "" }, switching
      ? "Every agent on this farm and the head office will act as the new account."
      : "Every agent on this farm will act as this account."),
    switching
      ? [
        stepHead(1, "Switch in your terminal", `Signed in now as @${gh.connectFrom || "nobody"}. `
          + "gh switches between the accounts it already knows:"),
        commandRow(cmd.switch, "switch-command", "switch"),
        h("p", { class: "muted", key: "new" }, "An account gh does not know yet is signed in first:"),
        commandRow(cmd.login, "login-command", "login"),
      ]
      : [
        stepHead(1, "Sign in from your terminal", "On your own machine, not on this page, run:"),
        commandRow(cmd.login, "login-command", "login"),
        h("ol", { key: "steps" },
          h("li", { key: "1" }, "GitHub prints a one-time code and an address: open it and enter the code"),
          h("li", { key: "2" }, "Answer Yes when it asks to authenticate Git with your GitHub credentials"),
          h("li", { key: "3" }, "Come back here: this page notices the login by itself")),
        h("p", { class: "muted", key: "scopes" },
          "-s workflow adds to gh's own defaults (repo, read:org, gist). If you answered No to "
          + "the Git question, run this as well:"),
        commandRow(cmd.setup_git, "setup-git-command", "setup"),
      ],
    stepHead(2, done ? signedIn(data) : "Waiting for the login",
      done ? "The agents act as this account from now on." : null),
    h("div", { class: "row m-wait", key: "wait" },
      pill(done ? "done" : "wait", done ? "Connected" : "Waiting",
        accountRead(data) ? scopeText(data) : "The account is not read yet"),
      h("span", { class: "muted" }, done
        ? "Nothing else to do here."
        : "This page reads the farm's answer every three seconds; nothing to press here.")),
    h("div", { class: "row m-dialog-actions", key: "acts" },
      h("button", {
        class: done ? "button primary" : "ghost-button",
        "data-connect-done": "",
        onclick: () => closeDrawer(),
      }, done ? "Done" : "Close, I will finish later")));
}

/* ------------------------------------------------------------- import */

function ownersOf(data) {
  return list(data && data.owners)
    .map((owner) => (typeof owner === "string" ? owner : owner && owner.login))
    .filter(Boolean);
}

function registeredNames(context) {
  return list(context.res("/api/projects").data).map((row) => row.name);
}

function registeredRepos(context) {
  return list(context.res("/api/projects").data).map((row) => String(row.repo || "").toLowerCase());
}

/* Why a repository cannot be imported, or "" when it can. */
function refusal(context, repo) {
  if (repo.registered || registeredRepos(context).includes(String(repo.full_name).toLowerCase())) {
    return "Already a project";
  }
  if (repo.archived) return "Archived";
  if (repo.permission && !PUSHES.includes(repo.permission)) return "Read only: agents need write";
  return "";
}

function openImport(context) {
  const data = snapshot(context).data || {};
  gh.imp = freshImport();
  const owners = ownersOf(data);
  gh.imp.owner = data.login && owners.includes(data.login) ? data.login : owners[0] || data.login || "";
  openDrawer({
    key: IMPORT_KEY,
    title: "Import a repository",
    sub: "From the GitHub account this farm is signed in as.",
    body: () => importBody(context),
    onClose: () => {
      if (gh.imp && gh.imp.timer) clearTimeout(gh.imp.timer);
      gh.imp = null;
    },
  });
  loadRepos(context);
}

async function loadRepos(context) {
  const imp = gh.imp;
  if (!imp) return;
  imp.seq += 1;
  const mine = imp.seq;
  imp.reposBusy = true;
  imp.reposError = "";
  context.paint();
  try {
    const answer = await apiPost("/api/github/repos", { owner: imp.owner, q: imp.q });
    if (gh.imp !== imp || imp.seq !== mine) return;
    imp.repos = list(answer && answer.repos);
    imp.truncated = Boolean(answer && answer.truncated);
  } catch (error) {
    if (gh.imp !== imp || imp.seq !== mine) return;
    imp.reposError = serverReason(error) || "The farm did not answer with a list of repositories.";
  } finally {
    if (gh.imp === imp && imp.seq === mine) imp.reposBusy = false;
    context.paint();
  }
}

/* `field` is the search box itself: the page never rewrites a box that has the focus, so a
   refused token is wiped from it here. */
function searchSoon(context, field) {
  const imp = gh.imp;
  if (imp.timer) clearTimeout(imp.timer);
  imp.timer = 0;
  imp.qError = "";
  if (looksLikeToken(imp.q)) {
    imp.q = "";
    if (field) field.value = "";
    imp.qError = tokenRefusal("a repository name");
    context.paint();
    return;
  }
  imp.timer = setTimeout(() => {
    imp.timer = 0;
    if (gh.imp === imp) loadRepos(context);
  }, SEARCH_DEBOUNCE_MS);
}

/** owner/repo from the three forms a person might paste, or null. */
export function parseAddress(value) {
  let text = String(value || "").trim();
  const ssh = text.match(/^git@github\.com:(.+)$/i);
  if (ssh) text = ssh[1];
  else if (/^https?:\/\//i.test(text)) {
    let parsed;
    try {
      parsed = new URL(text);
    } catch (error) {
      return null;
    }
    if (parsed.hostname.toLowerCase() !== "github.com" || parsed.search || parsed.hash) return null;
    text = parsed.pathname.replace(/^\/+/, "");
  }
  text = text.replace(/\/+$/, "").replace(/\.git$/i, "");
  return REPO_RE.test(text) ? text : null;
}

/* A pasted address is looked up in the snapshot's own list first, so a repository this account
   can only read is refused here with the same words as its row. One the list does not hold goes
   on to the checks, which decide. */
async function usePaste(context) {
  const imp = gh.imp;
  if (imp.pasteBusy) return;
  const typed = imp.paste.trim();
  if (looksLikeToken(typed)) {
    imp.paste = "";
    imp.pasteError = tokenRefusal("an address");
    context.paint();
    return;
  }
  const full = parseAddress(typed);
  if (!full) {
    imp.pasteError = "An address is owner/repo, https://github.com/owner/repo or "
      + "git@github.com:owner/repo.git.";
    context.paint();
    return;
  }
  const [owner, name] = full.split("/");
  imp.pasteBusy = true;
  imp.pasteError = "";
  context.paint();
  let known = null;
  try {
    const answer = await apiPost("/api/github/repos", { owner, q: name });
    known = list(answer && answer.repos)
      .find((repo) => String(repo.full_name).toLowerCase() === full.toLowerCase()) || null;
  } catch (error) {
    known = null;
  } finally {
    imp.pasteBusy = false;
  }
  if (gh.imp !== imp) return;
  const repo = known || { full_name: full, owner, name, pasted: true };
  const why = refusal(context, repo);
  if (why) {
    imp.pasteError = `${full} cannot be imported. ${why}.`;
    context.paint();
    return;
  }
  choose(context, repo);
}

function choose(context, repo) {
  const imp = gh.imp;
  imp.repo = repo;
  imp.name = String(repo.name || String(repo.full_name).split("/")[1] || "").slice(0, NAME_LIMIT);
  imp.nameError = "";
  imp.branch = repo.default_branch || "";
  imp.typed = false;
  imp.typedBranch = "";
  imp.portOpen = false;
  imp.port = "";
  imp.checks = null;
  imp.step = 2;
  /* Choose another, then the same repository again: its branches are already read. */
  if (imp.branches && imp.branchesFor.toLowerCase() === String(repo.full_name).toLowerCase()) {
    if (imp.branches.default_branch) imp.branch = imp.branches.default_branch;
    context.paint();
    return;
  }
  loadBranches(context);
}

async function loadBranches(context) {
  const imp = gh.imp;
  imp.branchesBusy = true;
  imp.branchesError = "";
  imp.branches = null;
  context.paint();
  try {
    const answer = await apiPost("/api/github/branches", { repo: imp.repo.full_name });
    if (gh.imp !== imp) return;
    imp.branches = { default_branch: answer && answer.default_branch, protected: list(answer && answer.protected) };
    imp.branchesFor = String(imp.repo.full_name);
    if (!imp.typed && imp.branches.default_branch) imp.branch = imp.branches.default_branch;
  } catch (error) {
    if (gh.imp !== imp) return;
    imp.branchesError = serverReason(error) || "The branches were not read. Type the base branch by hand.";
  } finally {
    if (gh.imp === imp) imp.branchesBusy = false;
    context.paint();
  }
}

function chosenBranch(imp) {
  return (imp.typed ? imp.typedBranch : imp.branch).trim();
}

function validBranch(name) {
  return Boolean(name) && !name.startsWith("-") && !/[\s~^:?*[\\]|\.\.|@\{|\/\/|\.lock$|\/$|^\//.test(name);
}

function validateConfig(context) {
  const imp = gh.imp;
  const name = imp.name.trim();
  /* A classic token is forty letters, digits and underscores, so it passes the registry's name
     rule and would become an argv, a job record and a folder. Refused first, and wiped. */
  if (looksLikeToken(name)) {
    imp.name = "";
    return tokenRefusal("a project name");
  }
  if (looksLikeToken(imp.typedBranch)) {
    imp.typedBranch = "";
    return tokenRefusal("a branch name");
  }
  if (!NAME_RE.test(name)) {
    return "A project name is letters, digits, dot, dash or underscore, up to 40 characters, "
      + "starting with a letter or a digit.";
  }
  if (registeredNames(context).includes(name)) return `A project called ${name} already exists.`;
  const branch = chosenBranch(imp);
  if (!validBranch(branch)) return "A base branch is a branch name, for example main.";
  if (imp.portOpen && imp.port.trim()) {
    const base = Number(imp.port.trim());
    if (!Number.isInteger(base) || base < 1024 || base > 60000) {
      return "A port block starts at a whole number between 1024 and 60000.";
    }
  }
  return "";
}

async function runChecks(context) {
  const imp = gh.imp;
  const problem = validateConfig(context);
  if (problem) {
    imp.nameError = problem;
    context.paint();
    return;
  }
  imp.nameError = "";
  imp.step = 3;
  imp.checks = null;
  imp.checkBusy = true;
  imp.checkError = "";
  context.paint();
  try {
    const answer = await apiPost("/api/github/access", {
      repo: imp.repo.full_name, branch: chosenBranch(imp), name: imp.name.trim(),
    });
    if (gh.imp !== imp) return;
    imp.checks = list(answer && answer.checks);
    imp.checkedAt = Date.now();
    setTimeout(() => context.paint(), CHECK_AGAIN_REST_MS + 50);
  } catch (error) {
    if (gh.imp !== imp) return;
    imp.checkError = serverReason(error) || "The farm did not run the checks.";
  } finally {
    if (gh.imp === imp) imp.checkBusy = false;
    context.paint();
  }
}

function checkAgainLeft(imp) {
  return imp.checkedAt ? imp.checkedAt + CHECK_AGAIN_REST_MS - Date.now() : 0;
}

function checkAgain(context) {
  if (checkAgainLeft(gh.imp) > 0) return;
  runChecks(context);
}

function importRequest(imp) {
  const body = { name: imp.name.trim(), repo: imp.repo.full_name, branch: chosenBranch(imp) };
  if (imp.portOpen && imp.port.trim()) body.port_base = Number(imp.port.trim());
  return body;
}

async function startImport(context) {
  const imp = gh.imp;
  if (imp.importBusy || imp.jobId) return;
  imp.importBusy = true;
  imp.importError = "";
  context.paint();
  try {
    const answer = await apiPost("/api/projects", importRequest(imp));
    const job = answer && answer.job;
    const id = job && typeof job === "object" ? job.id : job;
    if (gh.imp !== imp) return;
    if (answer && answer.error) {
      imp.importError = answer.error;
    } else {
      imp.step = 4;
      if (id) {
        imp.jobId = String(id);
        gh.jobs.push({ id: imp.jobId, name: imp.name.trim(), repo: imp.repo.full_name, detail: "", ended: false, error: "" });
      } else {
        finishImport(context, imp.name);
      }
    }
  } catch (error) {
    if (gh.imp === imp) imp.importError = serverReason(error) || `${imp.name} was not imported.`;
  } finally {
    imp.importBusy = false;
    context.paint();
  }
}

/* The row is drawn, and the dialog closes when it is still showing this import. */
function finishImport(context, name, closeDialog = true) {
  toast(`${name} is imported.`);
  context.refresh("/api/projects");
  context.refresh("/api/projects/next-port");
  if (closeDialog && gh.imp && openDrawerKey() === IMPORT_KEY) closeDrawer();
  context.paint();
}

function jobPath(id) {
  return `/api/jobs/${encodeURIComponent(id)}`;
}

function forgetJob(context, entry) {
  gh.jobs = gh.jobs.filter((item) => item !== entry);
  context.drop(jobPath(entry.id));
}

/* Read on every paint of the section, so a clone that ends after the dialog closed still lands:
   done drops the job and draws the row, failed keeps its reason in the table card. */
function followJobs(context) {
  for (const entry of gh.jobs) {
    if (entry.ended) continue;
    const job = context.watch(jobPath(entry.id)).data;
    if (!job || !job.state) continue;
    entry.detail = job.detail || entry.detail;
    if (job.state === "failed") {
      entry.ended = true;
      entry.error = job.error || "The farm refused this import; its job log says why.";
      setTimeout(() => {
        context.drop(jobPath(entry.id));
        context.paint();
      }, 0);
    } else if (job.state === "done") {
      entry.ended = true;
      setTimeout(() => {
        const shown = Boolean(gh.imp && gh.imp.jobId === entry.id);
        forgetJob(context, entry);
        finishImport(context, entry.name, shown);
      }, 0);
    }
  }
}

function failedImports(context) {
  const failed = gh.jobs.filter((entry) => entry.error);
  if (!failed.length) return null;
  return h("div", { class: "card-pad p-failed", key: "failed" }, failed.map((entry) => h("p", {
    class: "m-bad row", key: entry.id, role: "alert", "data-import-failed": entry.name,
  },
  h("span", null, `The import of ${entry.repo} as ${entry.name} failed: ${entry.error}`),
  h("button", {
    class: "ghost-button small",
    "data-import-dismiss": entry.name,
    onclick: () => {
      forgetJob(context, entry);
      context.paint();
    },
  }, "Dismiss"))));
}

/* Step one: whose repositories, which one, or an address pasted by hand. */
function chooseStep(context, data) {
  const imp = gh.imp;
  const owners = ownersOf(data);
  const rows = list(imp.repos).slice().sort((a, b) => (fmt.seconds(b.pushed_at) || 0) - (fmt.seconds(a.pushed_at) || 0));
  let listing;
  if (imp.reposError) {
    listing = h("p", { class: "m-bad", key: "err", role: "alert" }, imp.reposError);
  } else if (imp.repos == null) {
    listing = h("div", { class: "p-repos", key: "list" }, skeletonStack(4));
  } else if (!rows.length) {
    listing = h("p", { class: "muted p-none", key: "none", "data-repos-empty": "" }, imp.q
      ? `No repository of ${imp.owner || "this account"} has "${imp.q}" in its name.`
      : `This account reaches no repository of ${imp.owner || "its own"}.`);
  } else {
    listing = h("div", { class: "p-repos", key: "list", role: "list", "aria-busy": imp.reposBusy ? "true" : "false" },
      rows.map((repo) => {
        const why = refusal(context, repo);
        const [meaning, word, tip] = roleFor(repo.permission);
        return h("div", { class: "p-repo", role: "listitem", key: repo.full_name, "data-repo": repo.full_name },
          /* The owner is the select above the list, so a row names the repository alone. */
          h("span", { class: "p-repo-name", title: [repo.full_name, repo.description].filter(Boolean).join("\n") },
            repo.name || repo.full_name),
          /* Private or public is a fact about the repository, not a state, so it is a tag. */
          h("span", { class: "tag" }, repo.private ? "private" : "public"),
          pill(meaning, word, tip),
          h("span", { class: "muted p-pushed", title: repo.pushed_at || "" }, pushedAgo(repo.pushed_at)),
          h("button", {
            class: why ? "ghost-button small p-why" : "button small primary",
            "data-import-repo": repo.full_name,
            disabled: why || !access.writable ? true : null,
            title: why || blocked(),
            onclick: () => choose(context, repo),
          }, why || "Import"));
      }));
  }
  return [
    stepHead(1, "Choose", "Sorted by the last push. Only a repository the agents can push to can be imported."),
    h("div", { class: "row p-filters", key: "filters" },
      h("select", {
        "aria-label": "Owner",
        "data-owner": "",
        value: imp.owner,
        onchange: (event) => {
          imp.owner = event.target.value;
          if (imp.timer) clearTimeout(imp.timer);
          loadRepos(context);
        },
      }, (owners.length ? owners : [imp.owner]).filter(Boolean).map((owner) => h("option", {
        key: owner, value: owner, selected: owner === imp.owner ? true : null,
      }, owner))),
      h("input", {
        type: "search",
        class: "p-search",
        "aria-label": "Search repositories",
        "data-repo-search": "",
        placeholder: "Search by name",
        autocomplete: "off",
        spellcheck: "false",
        value: imp.q,
        oninput: (event) => {
          imp.q = event.target.value;
          searchSoon(context, event.target);
        },
      }),
      imp.reposBusy ? h("span", { class: "muted", key: "busy" }, "Reading") : null),
    imp.qError ? h("p", { class: "m-bad", key: "qerr", role: "alert", "data-search-error": "" }, imp.qError) : null,
    listing,
    imp.truncated ? h("p", { class: "muted", key: "cut" },
      "GitHub listed more than this farm reads. Search by name, or paste the address.") : null,
    h("div", { class: "p-paste", key: "paste" },
      h("label", { class: "m-field" },
        h("span", { class: "m-label" }, "Not in the list? Paste its address"),
        h("div", { class: "row p-paste-row" },
          h("input", {
            type: "text",
            "aria-label": "Repository address",
            "data-paste": "",
            placeholder: "owner/repo, https://github.com/owner/repo or git@github.com:owner/repo.git",
            autocomplete: "off",
            spellcheck: "false",
            value: imp.paste,
            oninput: (event) => {
              imp.paste = event.target.value;
              imp.pasteError = "";
            },
            onkeydown: (event) => {
              if (event.key === "Enter") usePaste(context);
            },
          }),
          h("button", {
            class: "button small",
            "data-paste-use": "",
            disabled: access.writable && imp.paste.trim() && !imp.pasteBusy ? null : true,
            title: blocked() || (imp.paste.trim() ? "" : "Paste an address first."),
            onclick: () => usePaste(context),
          }, imp.pasteBusy ? "Looking it up" : "Use this address"))),
      imp.pasteError ? h("p", { class: "m-bad", key: "perr", role: "alert", "data-paste-error": "" }, imp.pasteError) : null,
      h("p", { class: "muted", key: "sso" },
        "An organization can hide its private repositories until it approves the GitHub CLI app, "
        + "or until you authorize it for single sign-on: ",
        h("a", { href: SSO_LINK, target: "_blank", rel: "noopener noreferrer", "data-sso": "" },
          "review the GitHub CLI app's access"),
        ".")),
    h("div", { class: "row m-dialog-actions", key: "acts" },
      h("button", { class: "ghost-button", onclick: () => closeDrawer() }, "Cancel")),
  ];
}

function portSentence(context, imp) {
  const port = context.res("/api/projects/next-port").data || {};
  const base = port.next_port_base;
  if (imp.portOpen) {
    return h("label", { class: "m-field", key: "port" },
      h("span", { class: "m-label" }, "First port of the block"),
      h("input", {
        type: "text",
        class: "m-port",
        inputmode: "numeric",
        "aria-label": "Port base",
        "data-port": "",
        placeholder: base ? String(base) : "5300",
        value: imp.port,
        oninput: (event) => {
          imp.port = event.target.value;
          imp.checks = null;
        },
      }),
      h("span", { class: "muted" }, "Empty takes the farm's next free block."));
  }
  return h("p", { class: "row p-ports", key: "port" },
    h("span", null, base
      ? `Ports ${base} to ${base + PORT_BLOCK - 1}, the next free block.`
      : port.sentence || "The farm hands this project its next free port block."),
    h("button", {
      class: "p-link",
      "data-port-change": "",
      onclick: () => {
        imp.portOpen = true;
        context.paint();
      },
    }, "Change"));
}

/* Step two: the name, the base branch and the ports, each with a default worth keeping. */
function configureStep(context) {
  const imp = gh.imp;
  const repo = imp.repo;
  const name = (!looksLikeToken(imp.name) && imp.name.trim()) || "<name>";
  const branches = imp.branches || {};
  const def = branches.default_branch || repo.default_branch || "";
  const options = [];
  if (def) options.push([def, `${def} (default)`]);
  for (const branch of list(branches.protected)) {
    if (branch !== def) options.push([branch, `${branch} (protected)`]);
  }
  options.push(["__typed", "Type another name"]);
  const selected = imp.typed || !def ? "__typed" : imp.branch;
  return [
    h("p", { class: "p-chosen", key: "chosen" }, h("b", null, repo.full_name),
      h("button", {
        class: "p-link",
        "data-import-back": "",
        onclick: () => {
          imp.step = 1;
          imp.repo = null;
          context.paint();
        },
      }, "Choose another")),
    stepHead(2, "Configure", "The defaults are what most projects keep."),
    h("label", { class: "m-field", key: "name" },
      h("span", { class: "m-label" }, "Project name"),
      h("input", {
        type: "text",
        class: "m-name",
        "aria-label": "Project name",
        "data-project-name": "",
        maxlength: String(NAME_LIMIT),
        autocomplete: "off",
        spellcheck: "false",
        value: imp.name,
        oninput: (event) => {
          imp.name = event.target.value;
          imp.nameError = "";
          imp.checks = null;
          /* The hint follows the typing without a repaint of the whole dialog under the caret. */
          const hint = event.target.parentNode && event.target.parentNode.querySelector("[data-copied-to]");
          const typed = (!looksLikeToken(imp.name) && imp.name.trim()) || "<name>";
          if (hint) hint.textContent = `Copied to ~/work/${typed} on this farm`;
        },
      }),
      h("span", { class: "muted", "data-copied-to": "" }, `Copied to ~/work/${name} on this farm`)),
    h("label", { class: "m-field", key: "branch" },
      h("span", { class: "m-label" }, "Base branch"),
      h("select", {
        "aria-label": "Base branch",
        "data-branch": "",
        disabled: imp.branchesBusy ? true : null,
        onchange: (event) => {
          if (event.target.value === "__typed") {
            imp.typed = true;
          } else {
            imp.typed = false;
            imp.branch = event.target.value;
          }
          imp.checks = null;
          context.paint();
        },
      }, options.map(([value, label]) => h("option", {
        key: value, value, selected: value === selected ? true : null,
      }, label))),
      imp.branchesBusy ? h("span", { class: "muted", key: "reading" }, "Reading the branches") : null,
      imp.branchesError ? h("span", { class: "m-bad", key: "berr" }, imp.branchesError) : null,
      selected === "__typed" ? h("input", {
        type: "text",
        key: "typed",
        "aria-label": "Branch name",
        "data-branch-typed": "",
        placeholder: "release/2026",
        autocomplete: "off",
        spellcheck: "false",
        value: imp.typedBranch,
        oninput: (event) => {
          imp.typedBranch = event.target.value;
          imp.typed = true;
          imp.checks = null;
        },
      }) : null),
    portSentence(context, imp),
    imp.nameError ? h("p", { class: "m-bad", key: "nerr", role: "alert", "data-config-error": "" }, imp.nameError) : null,
    h("div", { class: "row m-dialog-actions", key: "acts" },
      h("button", {
        class: "button primary",
        "data-import-check": "",
        disabled: access.writable && !imp.checkBusy && !imp.branchesBusy ? null : true,
        title: blocked() || (imp.branchesBusy ? "Reading the branches first." : ""),
        onclick: () => runChecks(context),
      }, imp.checkBusy ? "Checking" : "Check"),
      h("button", { class: "ghost-button", onclick: () => closeDrawer() }, "Cancel")),
  ];
}

/* Step three: the farm checks the things that would make the first lane fail. */
function checkStep(context) {
  const imp = gh.imp;
  const checks = list(imp.checks);
  const failing = checks.filter((check) => check.state === "fail");
  const ready = imp.checks != null && !failing.length && !imp.checkBusy;
  const rest = checkAgainLeft(imp);
  return [
    h("p", { class: "p-chosen", key: "chosen" },
      h("b", null, `${imp.repo.full_name} as ${imp.name.trim()}, from ${chosenBranch(imp)}`),
      h("button", {
        class: "p-link",
        "data-import-configure": "",
        disabled: imp.importBusy ? true : null,
        onclick: () => {
          imp.step = 2;
          imp.checks = null;
          context.paint();
        },
      }, "Change")),
    stepHead(3, "Check", "Your role is what GitHub says; the first push is the final proof."),
    imp.checkBusy ? h("div", { key: "busy" }, skeletonStack(4)) : null,
    imp.checkError ? h("p", { class: "m-bad", key: "cerr", role: "alert" }, imp.checkError) : null,
    checks.length ? h("ul", { class: "p-checks", key: "checks" }, checks.map((check) => h("li", {
      key: check.id, "data-check": check.id, "data-check-state": check.state,
    },
    pill(CHECK_MEANING[check.state] || "pause", CHECK_WORD[check.state] || String(check.state), check.fix || ""),
    h("span", { class: "p-check-words" }, check.sentence || check.id),
    check.fix && check.state !== "ok" ? h("code", { class: "cmd", key: "fix" }, check.fix) : null))) : null,
    imp.checks != null && failing.length ? h("p", { class: "m-bad", key: "stop" },
      `${failing.length === 1 ? "One check fails" : `${failing.length} checks fail`}, so this cannot be imported yet.`) : null,
    imp.importError ? h("p", { class: "m-bad", key: "ierr", role: "alert" }, imp.importError) : null,
    h("div", { class: "row m-dialog-actions", key: "acts" },
      h("button", {
        class: "button primary",
        "data-import-start": "",
        disabled: access.writable && ready && !imp.importBusy ? null : true,
        title: blocked() || (imp.checkBusy ? "The checks are running."
          : failing.length ? "A check fails. Fix it, then check again." : ""),
        onclick: () => startImport(context),
      }, imp.importBusy ? "Starting the import" : "Import"),
      h("button", {
        class: "ghost-button",
        "data-import-recheck": "",
        disabled: access.writable && !imp.checkBusy && !imp.importBusy && rest <= 0 ? null : true,
        title: blocked() || (rest > 0 ? "Asking GitHub again this soon changes nothing." : ""),
        onclick: () => checkAgain(context),
      }, rest > 0 ? `Check again (in ${fmt.duration(rest / 1000)})` : "Check again"),
      h("button", { class: "ghost-button", onclick: () => closeDrawer() }, "Cancel")),
  ];
}

/* Step four: the clone runs as a job; the dialog closes to the table when it ends. */
function importStep(context) {
  const imp = gh.imp;
  /* The job itself is followed by the section (followJobs); the dialog only draws it. */
  const entry = gh.jobs.find((item) => item.id === imp.jobId) || null;
  const state = !entry ? "done" : entry.error ? "failed" : entry.ended ? "done" : "running";
  const failed = state === "failed";
  return [
    stepHead(4, failed ? "The import failed" : "Importing",
      failed ? null : `Copying ${imp.repo.full_name} to ~/work/${imp.name.trim()} on this farm.`),
    h("div", { class: "row m-wait", key: "job", "data-import-job": imp.jobId },
      pill(failed ? "fail" : state === "done" ? "done" : "run",
        failed ? "Failed" : state === "done" ? "Done" : "Running", imp.jobId ? `Job ${imp.jobId}` : ""),
      h("span", { class: "muted" }, failed ? entry.error : (entry && entry.detail) || "Asking the farm")),
    h("div", { class: "row m-dialog-actions", key: "acts" },
      failed ? h("button", {
        class: "ghost-button",
        onclick: () => {
          if (entry) forgetJob(context, entry);
          imp.jobId = "";
          imp.step = 3;
          context.paint();
        },
      }, "Back to the checks") : null,
      h("button", { class: "ghost-button", "data-import-close": "", onclick: () => closeDrawer() },
        failed ? "Close" : "Close, the row appears when the copy ends")),
  ];
}

function importBody(context) {
  const imp = gh.imp;
  if (!imp) return null;
  const data = snapshot(context).data || {};
  let body;
  if (imp.step === 4) body = importStep(context);
  else if (imp.step === 3 && imp.repo) body = checkStep(context);
  else if (imp.step === 2 && imp.repo) body = configureStep(context);
  else body = chooseStep(context, data);
  return h("div", { class: "m-steps p-import", key: `step${imp.step}`, "data-import-step": String(imp.step) },
    body, readOnlyLine("ro-import"));
}

/* Why Import is off, or "" when it is on. */
function importBlocked(data) {
  if (blocked()) return blocked();
  if (connected(data)) return "";
  if (!data || !data.login_state) return "The GitHub connection has not been read yet.";
  if (data.login_state === "no_gh") return "Install gh on this farm and sign in with it first.";
  if (data.login_state === "no_answer") return "gh on this farm did not answer. Re-check first.";
  return "Connect GitHub first.";
}

function importButton(context, data, primary) {
  const why = importBlocked(data);
  return h("button", {
    "data-write": "",
    class: primary ? "button primary" : "button",
    key: "import",
    "data-import-open": "",
    disabled: why ? true : null,
    title: why,
    onclick: () => openImport(context),
  }, "Import a repository");
}

/* -------------------------------------------------------------- the table */

function ports(row) {
  const block = (row && row.ports) || {};
  const parts = [["web", block.web], ["api", block.api], ["e2e", block.e2e]]
    .filter(([, value]) => value != null)
    .map(([name, value]) => `${name} ${value}`);
  return parts.length ? parts.join(", ") : "none";
}

async function removeProject(context, name) {
  if (gh.removeBusy) return;
  gh.removeBusy = name;
  gh.removeError = "";
  context.paint();
  try {
    const answer = await apiPost("/api/projects/remove", { name });
    toast(`${name} is out of the registry. Ports ${(answer && answer.freed) || "it held"} are free.`);
    gh.confirm = "";
  } catch (error) {
    gh.removeError = serverReason(error) || `${name} was not removed.`;
  } finally {
    gh.removeBusy = "";
    await context.refresh("/api/projects");
  }
}

function removeConfirm(context, rows, name) {
  const row = rows.find((item) => item.name === name) || {};
  const open = Number(row.lanes_open) || 0;
  return h("div", { class: "m-confirm", key: "removeProject", "data-remove-confirm": name },
    h("h3", null, `Remove ${name}`),
    open
      ? h("p", null, `${name} has ${open} open ${open === 1 ? "lane" : "lanes"}. `
        + "The farm refuses to remove a project while a lane is open in it. Stop them first.")
      : [
        h("p", { key: "one" }, `This takes ${name} out of this farm's project registry, and nothing else. `
          + `The folder ${row.path || `~/work/${name}`} on this farm stays, and the repository ${row.repo || ""} on `
          + "GitHub stays."),
        h("p", { key: "two" }, `The port block ${ports(row)} becomes free for the next project.`),
      ],
    h("div", { class: "row" },
      open ? null : h("button", {
        class: "button primary",
        "data-confirm": `remove-project:${name}`,
        disabled: access.writable && !gh.removeBusy ? null : true,
        title: blocked(),
        onclick: () => removeProject(context, name),
      }, gh.removeBusy === name ? "Removing" : "Yes, remove it"),
      h("button", {
        class: "ghost-button",
        onclick: () => {
          gh.confirm = "";
          context.paint();
        },
      }, open ? "Close" : "Keep it")));
}

function projectRow(context, row) {
  const [meaning, word, tip] = roleFor(row.permission, snapshot(context).data);
  const href = repoHref(row);
  const title = [`${row.name}`, `Ports: ${ports(row)}`, row.path ? `Folder: ${row.path}` : "",
    `Base branch: ${row.base_branch || "none"}`, `Lanes open: ${fmt.num(row.lanes_open, "0")}`]
    .filter(Boolean).join("\n");
  const visibility = row.visibility
    ? h("span", { class: "p-visibility", key: "vis" },
      h("span", { class: "tag" }, String(row.visibility).toLowerCase())) : null;
  return h("tr", { key: row.name, "data-project": row.name },
    h("td", { title, "data-col": "Project" }, row.name),
    h("td", { class: "p-repo-cell", title: row.repo || "none", "data-col": "Repository" },
      h("span", { class: "p-inline" },
        href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", class: "p-cut" }, row.repo)
          : line(row.repo || "none"),
        visibility)),
    h("td", { title: tip, "data-col": "Your access", "data-access": row.permission || "" },
      pill(meaning, word, tip)),
    h("td", { class: "p-optional", title: row.base_branch || "none" }, row.base_branch || "none"),
    h("td", { class: "num p-optional" }, fmt.num(row.lanes_open, "0")),
    h("td", { class: "p-actions actions", title: href ? `Open ${row.repo} on GitHub, or Remove ${row.name}` : `Remove ${row.name}` },
      h("span", { class: "p-inline" },
        href ? h("a", {
          class: "ghost-button small p-open", href, target: "_blank", rel: "noopener noreferrer",
          "data-open-github": row.name,
          title: `Open ${row.repo} on GitHub`,
        }, "GitHub") : null,
        h("button", {
          class: "ghost-button small danger",
          "data-remove-project": row.name,
          disabled: access.writable ? null : true,
          title: blocked(),
          onclick: () => {
            gh.confirm = row.name;
            gh.removeError = "";
            context.paint();
          },
        }, "Remove"))));
}

function table(context, rows) {
  return [
    h("div", { class: "tablewrap p-tablewrap", key: "table" }, h("table", { class: "p-table" },
      h("colgroup", null,
        h("col", { class: "p-col-project" }), h("col", { class: "p-col-repo" }),
        h("col", { class: "p-col-access" }), h("col", { class: "p-col-branch p-optional" }),
        h("col", { class: "p-col-lanes p-optional" }), h("col", { class: "p-col-actions" })),
      h("thead", null, h("tr", null,
        h("th", null, "Project"),
        h("th", null, "Repository"),
        h("th", null, "Your access"),
        h("th", { class: "p-optional" }, "Base branch"),
        h("th", { class: "num p-optional" }, "Lanes open"),
        h("th", { class: "actions" }, "Actions"))),
      h("tbody", null, rows.map((row) => projectRow(context, row))))),
    gh.confirm ? h("div", { class: "card-pad", key: "confirm" }, removeConfirm(context, rows, gh.confirm)) : null,
    gh.removeError ? h("p", { class: "m-bad card-pad", key: "rerr" }, gh.removeError) : null,
  ];
}

function emptyProjects(context, data) {
  if (data && data.login_state === "not_connected") {
    return h("div", { class: "card-pad p-empty", key: "empty", "data-empty": "connect" },
      emptyState({
        title: "Connect GitHub first",
        body: "A project is a GitHub repository the agents copy and push to, so the farm needs a "
          + "GitHub login before it can list any.",
      }),
      connectButton(context, false));
  }
  return h("div", { class: "card-pad p-empty", key: "empty", "data-empty": "import" },
    emptyState({
      title: "Import your first repository",
      body: "A project tells the farm which repository a lane may work in.",
    }),
    importButton(context, data, true));
}

export function projectsSection(context) {
  const projects = context.res("/api/projects");
  const rows = list(projects.data);
  const data = snapshot(context).data || {};
  if (gh.confirm && !rows.some((row) => row.name === gh.confirm)) gh.confirm = "";
  followJobs(context);
  return h("section", { class: "section", key: "projects" },
    sectionHead("Projects", "The repositories a lane may be opened in.", importButton(context, data, false)),
    stripCard(context, rows),
    h("div", { class: "gap-sm", key: "gap" }),
    card({ key: "projects", "data-write": "" }, failedImports(context), panel(projects, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(3)),
      isEmpty: (value) => !list(value).length,
      empty: () => emptyProjects(context, data),
      ready: (value) => [table(context, list(value)), h("div", { key: "ro" }, readOnlyLine("ro-projects"))],
    })));
}

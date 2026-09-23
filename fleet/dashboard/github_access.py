"""The farm's GitHub connection, as the Projects section reads it.

Design record: fleet/docs/design/github-projects.md, section 6. Every agent on this farm, the head
office and this dashboard act as the one account `gh` is signed in as, and share its GitHub API
allowance. So nothing here asks GitHub on a page read: a background pass keeps a snapshot, runs
every five minutes, stops spending when the allowance runs low, and runs once more when gh's own
`hosts.yml` changes on disk (which costs no call at all). The POST routes are the only other
callers, and each is one person pressing one button.

A GitHub token never passes through here. No code in this file runs `gh auth token`,
`git credential fill` or anything with `--show-token`, each of which prints one. Only parsed
values reach the snapshot: a header can carry an `X-GitHub-SSO` address, so no raw header text is
kept, and every sentence an answer carries is written here, never copied from a tool.
"""
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "lib"))
from scrub import scrub  # noqa: E402

PASS_SECONDS = 300
WATCH_SECONDS = 2.0
CHECK_COOLDOWN = 60
# Under this many calls left in the hour, a pass keeps its last good answer instead of spending.
RATE_FLOOR = 1000
MAX_PAGES = 5
# A registered repository missing from the list costs one call each; a farm with more than this
# many such projects waits for the next pass for the rest.
MAX_MISSING_LOOKUPS = 20
# A definite answer about one (a 200, 403 or 404) is kept this long, unless gh's login file changes
# or a person presses Re-check: a No access project would otherwise cost a call every pass.
KNOWN_SECONDS = 3600
GH_TIMEOUT = 20
GIT_TIMEOUT = 30
REQUIRED_SCOPES = ("repo", "workflow")
LIST_PATH = "user/repos?affiliation=owner,collaborator,organization_member&sort=pushed&per_page=100"
SSO_HELP = "https://github.com/settings/connections/applications/178c6fc778ccc68e1d6a"

# The registry's own patterns (server.py), repeated so this module imports nothing from it.
PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
PROJECT_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
HTTPS_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?/?")
SSH_URL = re.compile(r"(?:ssh://)?git@github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?")
ENV_TOKEN_LINE = re.compile(r"^\s*(?:export\s+)?(GH_TOKEN|GITHUB_TOKEN)\s*=\s*(.*?)\s*$")


# ---------------------------------------------------------------- tools

def _run(args, timeout=GH_TIMEOUT, env=None):
    """(returncode, stdout, stderr). Never raises: a missing tool and a hung one are answers."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env,
                              stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout or "", done.stderr or ""
    except FileNotFoundError:
        return 127, "", ""
    except subprocess.TimeoutExpired:
        return 124, "", ""
    except OSError:
        return 1, "", ""


def _gh_env():
    env = dict(os.environ)
    env.update({"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1",
                "GH_PAGER": "cat"})
    return env


def gh_api(path):
    """One REST call through `gh api -i`. Answers (status, fields, body): status is the HTTP
    status (0 when there was none: 127 no gh, 124 no answer), fields holds ONLY the parsed values
    this module uses, and body is the decoded JSON or None. The raw headers die here."""
    rc, out, err = _run(["gh", "api", "-i", path], env=_gh_env())
    if rc in (124, 127):
        return rc, {}, None
    status, headers, body_text = 0, {}, ""
    head, _, rest = out.replace("\r\n", "\n").partition("\n\n")
    lines = head.split("\n")
    match = re.match(r"HTTP/\S+\s+(\d{3})", lines[0] if lines else "")
    if match:
        status = int(match.group(1))
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if sep:
                headers[name.strip().lower()] = value.strip()
        body_text = rest
    else:
        found = re.search(r"\(HTTP (\d{3})\)", err)
        status = int(found.group(1)) if found else 0
    fields = {"scopes": _parse_scopes(headers),
              "remaining": _parse_int(headers.get("x-ratelimit-remaining")),
              "next_page": _next_page(headers.get("link", ""))}
    try:
        body = json.loads(body_text) if body_text.strip() else None
    except ValueError:
        body = None
    return status, fields, body


def _parse_scopes(headers):
    """The token's scopes: None when the header is absent (a fine-grained or app token), [] when
    it is present and empty (a classic token with no scopes)."""
    if "x-oauth-scopes" not in headers:
        return None
    return sorted({s.strip().lower() for s in headers["x-oauth-scopes"].split(",") if s.strip()})


def _parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _next_page(link):
    """The page number of rel="next", or None. Only the number is kept: the next call is built
    here from the fixed list path, never from text GitHub sent."""
    for part in link.split(","):
        found = re.match(r'\s*<([^>]*)>\s*;\s*rel="next"', part)
        if found:
            page = parse_qs(urlparse(found.group(1)).query).get("page", [""])[0]
            return _parse_int(page)
    return None


def _permission(perms):
    perms = perms if isinstance(perms, dict) else {}
    if perms.get("admin"):
        return "admin"
    if perms.get("maintain") or perms.get("push"):
        return "write"
    if perms.get("triage") or perms.get("pull"):
        return "read"
    return None


def _repo_row(item):
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    return {"full_name": str(item.get("full_name") or ""),
            "owner": str(owner.get("login") or ""),
            "name": str(item.get("name") or ""),
            "private": bool(item.get("private")),
            "archived": bool(item.get("archived")),
            "fork": bool(item.get("fork")),
            "default_branch": str(item.get("default_branch") or ""),
            "permission": _permission(item.get("permissions")),
            "pushed_at": item.get("pushed_at") if isinstance(item.get("pushed_at"), str) else None,
            # Free text an owner wrote: the one field here gh printed verbatim, so it is scrubbed.
            "description": scrub(str(item.get("description") or ""))[:300],
            "html_url": str(item.get("html_url") or "")}


def _api_path(repo, suffix=""):
    owner, name = repo.split("/", 1)
    return f"repos/{quote(owner, safe='')}/{quote(name, safe='')}{suffix}"


# ---------------------------------------------------------------- local facts, no GitHub call

def fleet_config():
    return os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet"))


def hosts_file():
    """gh's own login file, where gh itself looks for it."""
    base = os.environ.get("GH_CONFIG_DIR", "").strip()
    if not base:
        xdg = os.environ.get("XDG_CONFIG_HOME", "").strip() or os.path.expanduser("~/.config")
        base = os.path.join(xdg, "gh")
    return os.path.join(base, "hosts.yml")


def two_identities():
    """Where `GH_TOKEN` or `GITHUB_TOKEN` is set in fleet's env file, or None. The daemon, the
    sweep and the queue runner load that file and the dashboard and the lanes do not, so the
    farm would act as two accounts. The value itself is never read into anything kept."""
    path = os.path.join(fleet_config(), "env")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                found = ENV_TOKEN_LINE.match(line)
                if found and found.group(2).strip("'\""):
                    return {"file": path, "line": number, "variable": found.group(1)}
    except OSError:
        pass
    return None


def git_uses_login():
    """Whether git hands github.com the gh login (`gh auth setup-git` writes this helper)."""
    rc, out, _ = _run(["git", "config", "--global", "--get-urlmatch", "credential.helper",
                       "https://github.com"], timeout=5)
    if rc == 127:
        return None
    return rc == 0 and "auth git-credential" in out


def farm_alias():
    return os.environ.get("FLEET_FARM_ALIAS", "").strip() or socket.gethostname()


def commands():
    farm = farm_alias()
    return {"login": f"ssh -t {farm} gh auth login -h github.com -p https --web -s workflow",
            "refresh_scopes": f"ssh -t {farm} gh auth refresh -h github.com -s workflow",
            "setup_git": f"ssh -t {farm} gh auth setup-git",
            "switch": f"ssh -t {farm} gh auth switch"}


def auth_status():
    """(login_state, login) from `gh auth status --active -h github.com`. Only the active
    account: the plain command asks GitHub about every account gh knows. Its output shows a
    masked token line, so nothing but the login name is taken from it."""
    rc, out, err = _run(["gh", "auth", "status", "--active", "-h", "github.com"],
                        env=_gh_env())
    text = out + "\n" + err
    if rc == 127:
        return "no_gh", None
    if rc == 124:
        return "no_answer", None
    login = re.search(r"Logged in to github\.com (?:account|as) ([A-Za-z0-9-]+)", text)
    if rc == 0:
        return "connected", login.group(1) if login else None
    low = text.lower()
    if "not logged in" in low or ("token" in low and "invalid" in low):
        return "not_connected", None
    return "no_answer", None


# ---------------------------------------------------------------- the snapshot

_lock = threading.Lock()
_pass_lock = threading.Lock()
_hooks = {"office": lambda: "", "registry": lambda: {}}
_last_check = {"at": 0.0}
_running = {"passes": 0}
_watch = {"mtime": None, "next_pass": 0.0}


def _blank():
    return {"at": None, "stale_since": None, "error": None, "pending": True,
            "login_state": None, "login": None, "scopes": None, "git_uses_login": None,
            "two_identities": None, "office": {"repo": None, "writable": None, "detail": ""},
            "rate_remaining": None, "repos": [], "listed": False, "truncated": False,
            "known": {}, "known_at": {}, "account_read": False, "checking": False}


_snapshot = _blank()


def _now():
    return time.time()


def _iso(stamp):
    if stamp is None:
        return None
    return datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def configure(office=None, registry=None):
    """Where the head office and the project registry are read from: the dashboard's own
    functions, handed in so this module imports nothing from the server."""
    if office is not None:
        _hooks["office"] = office
    if registry is not None:
        _hooks["registry"] = registry


def _registered_repos():
    try:
        registry = _hooks["registry"]() or {}
    except Exception:
        return {}
    return {str(t.get("repo") or "").lower(): str(t.get("repo") or "")
            for t in registry.values() if isinstance(t, dict) and t.get("repo")}


def _publish(update, stale_error=None, good=False):
    now = _now()
    with _lock:
        _snapshot.update(update)
        _snapshot["pending"] = False
        if good:
            _snapshot["at"] = now
            _snapshot["stale_since"] = None
            _snapshot["error"] = None
        elif stale_error is not None:
            if _snapshot["stale_since"] is None:
                _snapshot["stale_since"] = now
            _snapshot["error"] = stale_error


def _office(repos, spend_ok, unchecked=None):
    """What the login may do in the head office. `unchecked` is the reason given when it was not
    asked; the default is the saving-calls reason, which is only true when calls are saved."""
    try:
        office = str(_hooks["office"]() or "").strip()
    except Exception:
        office = ""
    if not office:
        return {"repo": None, "writable": None,
                "detail": "No head office is configured on this farm."}
    permission = None
    for row in repos:
        if row["full_name"].lower() == office.lower():
            permission = row["permission"]
            break
    else:
        if not PROJECT_REPO.fullmatch(office):
            return {"repo": office, "writable": None,
                    "detail": "The head office is not written as owner/name."}
        if not spend_ok:
            return {"repo": office, "writable": None,
                    "detail": unchecked or "Not checked: GitHub calls are being saved for the agents."}
        status, _, body = gh_api(_api_path(office))
        if status in (403, 404):
            return {"repo": office, "writable": False,
                    "detail": f"This login cannot see the head office {office}."}
        if status != 200 or not isinstance(body, dict):
            return {"repo": office, "writable": None,
                    "detail": f"GitHub did not answer about the head office {office}."}
        permission = _permission(body.get("permissions"))
    if permission in ("admin", "write"):
        return {"repo": office, "writable": True,
                "detail": f"This login can write to the head office {office}."}
    return {"repo": office, "writable": False,
            "detail": f"This login can only read the head office {office}, so agents cannot "
                      "post mail there."}


def run_pass(fresh=False):
    """One pass: `gh auth status`, `gh api -i user`, then (only with at least RATE_FLOOR calls
    left) the paged repository list, the head office when it is not in the list, and one
    `repos/<r>` for each registered repository the list did not have and has no definite answer
    for from the last KNOWN_SECONDS. `fresh` asks those again whatever their age."""
    # Counted before the lock is taken, so a Re-check refused with 409 because this pass holds it
    # always finds "checking" set, and the page waits for this pass's answer too.
    _busy(1)
    try:
        with _pass_lock:
            _pass(fresh)
    finally:
        _busy(-1)


def _busy(step):
    """Count a pass that runs or waits to run; "checking" is true while any does."""
    with _lock:
        _running["passes"] = max(0, _running["passes"] + step)
        _snapshot["checking"] = _running["passes"] > 0


def _pass(fresh=False):
    identities = two_identities()
    state, login = auth_status()
    base = {"login_state": state, "two_identities": identities}
    if state in ("no_gh", "not_connected"):
        base.update({"login": None, "scopes": None, "git_uses_login": None,
                     "rate_remaining": None, "repos": [], "listed": False, "truncated": False,
                     "known": {}, "known_at": {}, "account_read": False,
                     "office": _office([], False, "Not checked: this farm is not signed in to "
                                                  "GitHub.")})
        _publish(base, good=True)
        return
    if state == "no_answer":
        _publish(base, stale_error="gh did not answer whether this farm is signed in to "
                                   "GitHub; the last answer is kept.")
        return
    status, fields, body = gh_api("user")
    if status != 200 or not isinstance(body, dict):
        with _lock:
            read_before = _snapshot.get("account_read")
        if not read_before:
            # Signed in, but the account itself has not been read yet: carry the login gh
            # reported, and claim nothing about what it may do until GitHub answers.
            base.update({"login": login or None, "scopes": None, "account_read": False,
                         "git_uses_login": git_uses_login(),
                         "office": _office([], False, "Not checked yet: GitHub did not answer "
                                                      "about the account.")})
        _publish(base, stale_error=_call_error("the account", status))
        return
    base.update({"login": str(body.get("login") or login or "") or None,
                 "scopes": fields["scopes"], "rate_remaining": fields["remaining"],
                 "git_uses_login": git_uses_login(), "account_read": True})
    remaining = fields["remaining"]
    if remaining is not None and remaining < RATE_FLOOR:
        _publish(base, stale_error=_saving(remaining))
        return
    repos, truncated, page, error = [], False, 1, None
    while True:
        status, fields, body = gh_api(f"{LIST_PATH}&page={page}")
        if status != 200 or not isinstance(body, list):
            error = _call_error("the repository list", status)
            break
        repos.extend(_repo_row(item) for item in body if isinstance(item, dict))
        remaining = fields["remaining"] if fields["remaining"] is not None else remaining
        base["rate_remaining"] = remaining
        following = fields["next_page"]
        if not following:
            break
        if page >= MAX_PAGES or (remaining is not None and remaining < RATE_FLOOR):
            truncated = True
            break
        page = following if following > page else page + 1
    if error:
        # A listing that failed changes nothing: the last good list stays, marked stale.
        _publish(base, stale_error=error)
        return
    spend_ok = remaining is None or remaining >= RATE_FLOOR
    known, known_at = _missing_registered(repos, spend_ok, fresh)
    base.update({"repos": repos, "listed": True, "truncated": truncated,
                 "office": _office(repos, spend_ok), "known": known, "known_at": known_at})
    if not spend_ok:
        _publish(base, stale_error=_saving(remaining))
        return
    _publish(base, good=True)


def _saving(remaining):
    return (f"GitHub has {remaining} calls left this hour for this account, which every agent "
            "shares, so the last answer is kept until more are free.")


def _call_error(what, status):
    if status == 124:
        return f"GitHub did not answer the call for {what} in time; the last answer is kept."
    if status:
        return f"GitHub answered HTTP {status} to the call for {what}; the last answer is kept."
    return f"gh could not ask GitHub for {what}; the last answer is kept."


def _missing_registered(repos, spend_ok, fresh=False):
    """(known, known_at): repo (lower case) -> {visibility, permission, html_url} for each
    registered repository the list did not have, and when that definite answer was had. No access
    comes only from a definite 404 or 403; anything else keeps what the last pass knew and is
    asked again next pass. A definite answer younger than KNOWN_SECONDS costs no call unless
    `fresh`."""
    with _lock:
        previous = dict(_snapshot["known"])
        previous_at = dict(_snapshot["known_at"])
    now = _now()
    listed = {row["full_name"].lower() for row in repos}
    known, known_at = {}, {}
    lookups = 0
    for key, repo in sorted(_registered_repos().items()):
        if key in listed or not PROJECT_REPO.fullmatch(repo):
            continue
        at = previous_at.get(key)
        young = key in previous and at is not None and now - at < KNOWN_SECONDS
        if (young and not fresh) or not spend_ok or lookups >= MAX_MISSING_LOOKUPS:
            if key in previous:
                known[key] = previous[key]
                if at is not None:
                    known_at[key] = at
            continue
        lookups += 1
        status, _, body = gh_api(_api_path(repo))
        if status in (403, 404):
            known[key] = {"visibility": None, "permission": "no_access",
                          "html_url": f"https://github.com/{repo}"}
            known_at[key] = now
        elif status == 200 and isinstance(body, dict):
            row = _repo_row(body)
            known[key] = {"visibility": "private" if row["private"] else "public",
                          "permission": row["permission"], "html_url": row["html_url"]}
            known_at[key] = now
        elif key in previous:
            known[key] = previous[key]
    return known, known_at


def snapshot():
    with _lock:
        return json.loads(json.dumps(_snapshot))


def github_answer():
    """GET /api/github. Reads the snapshot and runs nothing."""
    snap = snapshot()
    scopes = snap["scopes"]
    missing = [] if scopes is None else [s for s in REQUIRED_SCOPES if s not in scopes]
    if snap["login_state"] != "connected":
        missing = []
    login = snap["login"]
    others = sorted({r["owner"] for r in snap["repos"] if r["owner"]} - {login or ""},
                    key=str.lower)
    owners = ([login] if login else []) + others
    return {"at": _iso(snap["at"]), "stale_since": _iso(snap["stale_since"]),
            "error": snap["error"], "pending": snap["pending"], "checking": bool(snap.get("checking")),
            "login_state": snap["login_state"], "login": login, "scopes": scopes,
            "account_read": bool(snap.get("account_read")),
            "missing_scopes": missing, "git_uses_login": snap["git_uses_login"],
            "two_identities": snap["two_identities"], "office": snap["office"],
            "owners": owners, "rate_remaining": snap["rate_remaining"],
            "commands": commands()}


def decorate_projects(rows):
    """The `/api/projects` rows with `visibility`, `permission` and `html_url`, from the
    snapshot. `permission` is None when this farm is not connected or does not know yet."""
    snap = snapshot()
    connected = snap["login_state"] == "connected"
    listed = {r["full_name"].lower(): r for r in snap["repos"]}
    for row in rows:
        repo = str(row.get("repo") or "")
        key = repo.lower()
        found = listed.get(key)
        if found:
            facts = {"visibility": "private" if found["private"] else "public",
                     "permission": found["permission"], "html_url": found["html_url"]}
        elif key in snap["known"]:
            facts = dict(snap["known"][key])
        else:
            facts = {"visibility": None, "permission": None, "html_url": None}
        if not connected:
            facts["permission"] = None
        if not facts.get("html_url") and PROJECT_REPO.fullmatch(repo):
            facts["html_url"] = f"https://github.com/{repo}"
        row.update(facts)
    return rows


# ---------------------------------------------------------------- the refresher

def watch_tick(now=None):
    """One turn of the refresher: a pass when one is due or when gh's `hosts.yml` changed since
    the last turn (found by its modification time: a local file, no GitHub call). True when a
    pass ran."""
    now = _now() if now is None else now
    try:
        mtime = os.stat(hosts_file()).st_mtime_ns
    except OSError:
        mtime = None
    changed = _watch["mtime"] is not None and mtime != _watch["mtime"][0]
    _watch["mtime"] = (mtime,)
    if not changed and now < _watch["next_pass"]:
        return False
    _watch["next_pass"] = now + PASS_SECONDS
    try:
        run_pass(fresh=changed)
    except Exception:
        pass
    return True


def _refresher(stop):
    while not stop.is_set():
        watch_tick()
        stop.wait(WATCH_SECONDS)


def start(office=None, registry=None):
    """Start the background pass. Called once, next to the dashboard's other refreshers."""
    configure(office, registry)
    stop = threading.Event()
    threading.Thread(target=_refresher, args=(stop,), name="github-refresher",
                     daemon=True).start()
    return stop


def check_request(now=None):
    """(status, payload) for POST /api/github/check: one pass now, in the background. One at a
    time, and 429 with `retry_after` within CHECK_COOLDOWN seconds of the last one."""
    now = _now() if now is None else now
    since = now - _last_check["at"]
    if since < CHECK_COOLDOWN:
        wait = max(1, int(round(CHECK_COOLDOWN - since)))
        return 429, {"error": f"The GitHub connection was checked {int(since)} seconds ago. "
                              "Every agent on this farm shares one GitHub allowance, so it can "
                              f"be checked again in {wait} seconds.", "retry_after": wait}
    # The page reads "checking" until this pass has answered, so a Re-check shows its own answer
    # within seconds instead of at the next minute's read. It is not "pending": that one means no
    # pass has ever answered, and the page draws a loading skeleton for it. Counted before the
    # lock is tried, like run_pass, so a 409 is only ever answered while "checking" is set.
    _busy(1)
    if not _pass_lock.acquire(blocking=False):
        _busy(-1)
        return 409, {"error": "The GitHub connection is being checked right now; the answer "
                              "arrives in a few seconds.", "retry_after": 5}
    _last_check["at"] = now

    def work():
        try:
            _pass(fresh=True)
        except Exception:
            pass
        finally:
            # Released before it is uncounted, so no 409 is answered while "checking" is clear.
            _pass_lock.release()
            _busy(-1)

    thread = threading.Thread(target=work, name="github-check", daemon=True)
    thread.start()
    return 202, {"ok": True, "checking": True, "retry_after": CHECK_COOLDOWN,
                 "detail": "The farm is checking its GitHub connection now.",
                 "_thread": thread}


# ---------------------------------------------------------------- input rules

def reduce_repo(text):
    """`owner/name` from what a person pasted, or None. A URL is reduced only when its host is
    exactly github.com; the result must pass the registry's own pattern."""
    value = str(text or "").strip()
    for pattern in (HTTPS_URL, SSH_URL):
        found = pattern.fullmatch(value)
        if found:
            value = found.group(1)
            break
    else:
        if ":" in value or "@" in value:
            return None
    if value.endswith(".git"):
        value = value[:-4]
    return value if PROJECT_REPO.fullmatch(value) else None


def branch_problem(branch):
    """A sentence when `branch` cannot be a branch name, or "" when git accepts it. A name
    starting with `-` is refused before any command line sees it."""
    branch = str(branch or "")
    if not branch or branch.startswith("-") or len(branch) > 200 or "\n" in branch:
        return "a base branch is a git branch name, and cannot start with '-'"
    rc, _, _ = _run(["git", "check-ref-format", "--branch", branch], timeout=5)
    if rc != 0:
        return "a base branch is a git branch name, and cannot start with '-'"
    return ""


def _repo_from_body(body):
    raw = body.get("repo")
    repo = reduce_repo(raw) if isinstance(raw, str) else None
    if not repo:
        return None, (400, {"error": "a repository is owner/name, https://github.com/owner/name "
                                     "or git@github.com:owner/name.git"})
    return repo, None


# ---------------------------------------------------------------- the POST routes

def repos_request(body):
    """POST /api/github/repos {owner?, q?}: the snapshot's list, filtered in memory. Neither
    value ever reaches a command line."""
    owner = body.get("owner")
    q = body.get("q")
    owner = owner.strip().lower() if isinstance(owner, str) else ""
    q = q.strip().lower() if isinstance(q, str) else ""
    snap = snapshot()
    registered = set(_registered_repos())
    rows = []
    for row in snap["repos"]:
        if owner and row["owner"].lower() != owner:
            continue
        if q and q not in row["name"].lower():
            continue
        item = {key: row[key] for key in ("full_name", "owner", "name", "private", "archived",
                                          "fork", "default_branch", "permission", "pushed_at",
                                          "description")}
        item["registered"] = row["full_name"].lower() in registered
        rows.append(item)
    return 200, {"repos": rows, "truncated": snap["truncated"], "pending": snap["pending"],
                 "at": _iso(snap["at"]), "error": snap["error"], "sso_help": SSO_HELP}


def branches_request(body):
    """POST /api/github/branches {repo}: the default branch and the protected ones."""
    repo, refusal = _repo_from_body(body)
    if refusal:
        return refusal
    status, _, info = gh_api(_api_path(repo))
    if status in (403, 404):
        return 404, {"error": f"This account cannot see {repo} on GitHub."}
    if status != 200 or not isinstance(info, dict):
        return 502, {"error": _call_error(repo, status).split(";")[0] + "."}
    status, _, listed = gh_api(_api_path(repo, "/branches?protected=true&per_page=100"))
    protected = []
    if status == 200 and isinstance(listed, list):
        protected = [str(b.get("name")) for b in listed if isinstance(b, dict) and b.get("name")]
    return 200, {"repo": repo, "default_branch": str(info.get("default_branch") or ""),
                 "protected": protected}


def _check(ident, state, sentence, fix=""):
    return {"id": ident, "state": state, "sentence": sentence, "fix": fix}


def _ls_remote(repo, ref):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    rc, _, _ = _run(["git", "ls-remote", "--exit-code", f"https://github.com/{repo}.git", ref],
                    timeout=GIT_TIMEOUT, env=env)
    return rc


def access_request(body):
    """POST /api/github/access {repo, branch, name}: design section 4 step 3, one check per
    line. Import may go ahead when no line fails."""
    repo, refusal = _repo_from_body(body)
    if refusal:
        return refusal
    name = body.get("name")
    if not isinstance(name, str) or not PROJECT_NAME.fullmatch(name.strip()):
        return 400, {"error": "a project name is letters, digits, dot, dash or underscore, "
                              "up to 40 characters"}
    name = name.strip()
    branch = body.get("branch")
    branch = branch.strip() if isinstance(branch, str) else ""
    if branch:
        problem = branch_problem(branch)
        if problem:
            return 400, {"error": problem}
    snap = snapshot()
    cmds = commands()
    checks = []
    login = snap["login"]
    if snap["login_state"] == "connected":
        checks.append(_check("signed_in", "ok", f"Signed in to GitHub as @{login}."))
    else:
        checks.append(_check("signed_in", "fail", "This farm is not signed in to GitHub.",
                             cmds["login"]))

    status, _, info = gh_api(_api_path(repo))
    info = info if status == 200 and isinstance(info, dict) else None
    if info is None:
        if status in (403, 404):
            sentence = (f"This account cannot see {repo}: grant it access on GitHub, or check "
                        "the name.")
        else:
            sentence = _call_error(repo, status).split(";")[0] + "."
        checks.append(_check("role", "fail", sentence))
    else:
        permission = _permission(info.get("permissions"))
        if permission == "admin":
            checks.append(_check("role", "ok", "Your role is Admin, which allows a push. The "
                                               "first push is the final proof."))
        elif permission == "write":
            checks.append(_check("role", "ok", "Your role is Write, which allows a push. The "
                                               "first push is the final proof."))
        else:
            checks.append(_check("role", "fail", "Read only: agents need write."))

    # `ls-remote` of a private repository needs a login, so reaching one is the proof. A public
    # one answers anybody, so there only gh's credential helper says the first push will work.
    reached = _ls_remote(repo, "HEAD")
    if reached == 124:
        checks.append(_check("git_login", "fail", f"Git on this farm did not answer within "
                                                  f"{GIT_TIMEOUT} seconds, so its login could "
                                                  "not be checked. Check again in a moment."))
    elif reached == 127:
        checks.append(_check("git_login", "fail", "Git is not installed on this farm. Install "
                                                  "git on the farm."))
    elif reached == 128:
        # Only git refusing the repository is a login problem that gh auth setup-git can fix.
        checks.append(_check("git_login", "fail", "Git on this farm cannot read the repository "
                                                  "with your login.", cmds["setup_git"]))
    elif reached != 0:
        checks.append(_check("git_login", "fail", f"Git on this farm could not read {repo} (it "
                                                  f"stopped with code {reached})."))
    elif (info or {}).get("private") or snap["git_uses_login"] is True:
        checks.append(_check("git_login", "ok", "Git on this farm reaches the repository with "
                                                "your login."))
    else:
        checks.append(_check("git_login", "warn", "Git on this farm can read this public "
                                                  "repository but does not hand GitHub your "
                                                  "login, so the first push would fail.",
                             cmds["setup_git"]))

    scopes = snap["scopes"]
    if scopes is None and not snap.get("account_read"):
        # No scopes because GitHub never answered about the account, not because of the token.
        checks.append(_check("workflow_scope", "warn", "The account has not been read yet, so "
                                                       "its scopes are not known; the first push "
                                                       "that changes a CI file is the proof."))
    elif scopes is None:
        checks.append(_check("workflow_scope", "warn", "The scopes cannot be read for this kind "
                                                       "of token; the first push that changes a "
                                                       "CI file is the proof."))
    elif "workflow" in scopes:
        checks.append(_check("workflow_scope", "ok", "Agents can change CI workflow files."))
    else:
        checks.append(_check("workflow_scope", "warn", "Agents cannot change CI workflow files.",
                             cmds["refresh_scopes"]))

    if info is None:
        checks.append(_check("not_archived", "fail", "Not known: GitHub did not describe the "
                                                     "repository."))
    elif info.get("archived"):
        checks.append(_check("not_archived", "fail", "Archived: nothing can be pushed to it."))
    else:
        checks.append(_check("not_archived", "ok", "The repository is not archived."))

    default = str((info or {}).get("default_branch") or "")
    wanted = branch or default
    if not wanted:
        checks.append(_check("base_branch", "fail", "The base branch is not known."))
    elif wanted == default:
        checks.append(_check("base_branch", "ok", f"The base branch {wanted} is the default "
                                                  "branch."))
    else:
        found = _ls_remote(repo, f"refs/heads/{wanted}")
        if found == 0:
            checks.append(_check("base_branch", "ok", f"The base branch {wanted} exists."))
        elif found == 2:
            # git ls-remote --exit-code answers 2 only when it read the repository and found no
            # such ref; anything else means it could not read the repository at all.
            checks.append(_check("base_branch", "fail", f"There is no branch {wanted} in {repo}."))
        elif found == 124:
            checks.append(_check("base_branch", "fail",
                                 f"Git on this farm did not answer within {GIT_TIMEOUT} seconds, "
                                 f"so the branch {wanted} could not be checked. Check again in a "
                                 "moment."))
        elif found == 127:
            checks.append(_check("base_branch", "fail",
                                 f"Git is not installed on this farm, so the branch {wanted} "
                                 "could not be checked. Install git on the farm."))
        elif found == 128:
            # 128 is git refusing the repository, which a login git does not use explains.
            checks.append(_check("base_branch", "fail",
                                 f"Git on this farm could not read {repo}, so the branch {wanted} "
                                 "could not be checked.", cmds["setup_git"]))
        else:
            checks.append(_check("base_branch", "fail",
                                 f"Git on this farm could not read {repo} (it stopped with code "
                                 f"{found}), so the branch {wanted} could not be checked."))

    checks.append(_folder_check(repo, name, login))
    return 200, {"repo": repo, "branch": wanted, "name": name, "checks": checks,
                 "importable": not any(c["state"] == "fail" for c in checks)}


def _folder_check(repo, name, login):
    folder = os.path.join(os.path.expanduser("~"), "work", name)
    shown = f"~/work/{name}"
    if not os.path.lexists(folder):
        return _check("folder", "ok", f"Copied to {shown} on this farm.")
    rc, out, _ = _run(["git", "-C", folder, "remote", "get-url", "origin"], timeout=5)
    origin = out.strip() if rc == 0 else ""
    if not origin:
        return _check("folder", "fail", f"{shown} already exists and is not a copy of {repo}. "
                                        "Choose another project name.")
    found = reduce_repo(origin)
    if not found:
        return _check("folder", "fail", f"{shown} already exists and its origin is not a GitHub "
                                        "repository. Choose another project name.")
    if found.lower() != repo.lower():
        return _check("folder", "fail", f"{shown} already exists and is a copy of {found}. "
                                        "Choose another project name.")
    if not SSH_URL.fullmatch(origin):
        return _check("folder", "ok", f"{shown} already exists and is a copy of {repo}; it is "
                                      "used as it is.")
    rc, out, err = _run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                         "git@github.com"], timeout=GIT_TIMEOUT)
    greeted = re.search(r"Hi ([A-Za-z0-9-]+)!", out + "\n" + err)
    if not greeted:
        return _check("folder", "fail", f"{shown} is a copy of {repo} over SSH, and GitHub does "
                                        "not accept this farm's SSH key.")
    account = greeted.group(1)
    if login and account.lower() != login.lower():
        return _check("folder", "warn", f"{shown} is a copy of {repo} over SSH, where this farm's "
                                        f"key belongs to @{account}, not @{login}.")
    return _check("folder", "ok", f"{shown} is a copy of {repo} over SSH, as @{account}.")


# ---------------------------------------------------------------- the dispatch server.py calls

def get_route(path):
    """(status, payload) for a GET under /api/github."""
    if path.rstrip("/") == "/api/github":
        return 200, github_answer()
    return 404, {"error": "not found"}


def post_route(path, body):
    """(status, payload) for a POST under /api/github. The payload is JSON-ready."""
    path = path.rstrip("/")
    if path == "/api/github/check":
        code, payload = check_request()
        payload.pop("_thread", None)
        return code, payload
    if path == "/api/github/repos":
        return repos_request(body)
    if path == "/api/github/branches":
        return branches_request(body)
    if path == "/api/github/access":
        return access_request(body)
    return 404, {"error": "not found"}

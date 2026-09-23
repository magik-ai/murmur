"""The GitHub routes of design section 6 (fleet/docs/design/github-projects.md), for the stub.

test_stub_server.py serves the dashboard against fixtures and calls `install(globals())` once;
this file then answers GET /api/github, the four POST /api/github/* routes, adds `visibility`,
`permission` and `html_url` to the /api/projects rows, records every body posted to those
routes and to POST /api/projects, and links projects.css into the stub's harness page.

The stub's own five states (ready, empty, error, loading, quiet) pick the dataset. A second
parameter, `gh`, picks one strip state on top of it, read the same way the state is: from the
request's query, from the query of the page that made it, or from STUB_GH:

    connected       signed in with every scope (the default)
    missing_scope   the token lacks workflow
    missing_repo    the token lacks repo
    no_scopes       a classic token that carries no scope at all
    no_git          git on the farm does not use the login
    two             GH_TOKEN set on line 3 of the farm's fleet env file
    two_flag        two_identities as a bare true, a shape the page must ignore
    not_connected   gh reports no account at all
    no_gh           gh is not installed
    no_answer       gh did not answer
    fine            a fine-grained token, whose scopes cannot be read
    office_denied   the login cannot write to the head office
    unread          signed in (gh names the login), but GitHub refused the account call: nothing read
    flip            not connected for STUB_GH_FLIP_SECONDS after the first read, then connected

`long=1` adds a project whose name, repository and branch are all too long for their cells.

GET /stub/github/sent answers every body recorded so far, for a check to assert on exactly.
GET /stub/github/env answers the HOME, FLEET_STATE and FLEET_CONFIG the stub runs with (the
paths, nothing read from them), so a check can prove it never runs against the real farm.
Nothing here reaches GitHub.
"""
import io
import json
import os
import threading
import time
from urllib.parse import parse_qs, urlparse

VARIANTS = ("connected", "missing_scope", "missing_repo", "no_scopes", "no_git", "two", "two_flag",
            "not_connected", "no_gh", "no_answer", "fine", "office_denied", "flip", "unread")
FLIP_SECONDS = float(os.environ.get("STUB_GH_FLIP_SECONDS", "6"))
CHECK_COOLDOWN = 60
ENV_FILE = "/home/farm/.config/fleet/env"

LOGIN = "octo-farm"
OWNERS = [LOGIN, "your-org", "labs-collective"]
NOW = time.time()

SENT = []
LOCK = threading.Lock()
CURRENT = threading.local()
FIRST_READ = {}
LAST_CHECK = {"at": 0.0}


def _iso(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - seconds_ago))


def _repo(owner, name, permission="write", private=True, archived=False, pushed=3600,
          default="main", description=""):
    return {"full_name": f"{owner}/{name}", "owner": owner, "name": name, "private": private,
            "archived": archived, "fork": False, "default_branch": default,
            "permission": permission, "pushed_at": _iso(pushed), "description": description}


REPOS = [
    _repo("your-org", "demo", "admin", pushed=600, description="The demo shop"),
    _repo("your-org", "storefront", "write", private=False, pushed=5400),
    _repo("your-org", "sandbox", "admin", pushed=86000),
    _repo(LOGIN, "notes", "admin", pushed=3 * 86400, description="Personal notes"),
    _repo(LOGIN, "dotfiles", "admin", private=False, pushed=40 * 86400),
    _repo(LOGIN, "old-experiment", "admin", archived=True, pushed=400 * 86400),
    _repo("your-org", "billing", "maintain", pushed=7200, default="trunk"),
    _repo("your-org", "handbook", "read", private=False, pushed=2 * 86400,
          description="Readable, not writable"),
    _repo("your-org", "mobile-app", "write", pushed=9000),
    _repo("your-org", "design-system", "triage", pushed=12 * 86400),
    _repo("your-org", "infra", "admin", pushed=20000),
    _repo("your-org", "analytics", "write", pushed=30000),
    _repo("your-org", "support-bot", "write", pushed=50000),
    _repo("your-org", "search", "write", pushed=70000),
    _repo("labs-collective", "prototype", "write", pushed=5 * 86400),
    _repo("labs-collective", "an-exceptionally-long-repository-name-that-no-cell-can-hold-"
          "whole-on-any-screen", "write", pushed=6 * 86400),
]

PROTECTED = {"your-org/demo": ["main", "release"], "your-org/billing": ["trunk", "release/2026"]}

# What each registered fixture project is to this account.
ACCESS = {
    "your-org/demo": ("private", "admin"),
    "your-org/storefront": ("public", "write"),
    "your-org/sandbox": ("private", "no_access"),
}

LONG_PROJECT = {
    "name": "checkout-retry-a-declined-card-once-then-explain",
    "repo": "your-org/checkout-retry-a-declined-card-once-then-explain-it-plainly-to-the-customer",
    "path": "/home/farm/work/checkout-retry-a-declined-card-once-then-explain",
    "base_branch": "release/2026-09-autumn-checkout-hardening",
    "ports": {"web": 5290, "api": 8100, "e2e": 9100}, "lanes_open": 12, "last_activity": NOW,
}


def _pick(handler, key, allowed, env, default):
    query = parse_qs(urlparse(handler.path).query)
    if query.get(key, [""])[0] in allowed:
        return query[key][0]
    referer = handler.headers.get("Referer") or ""
    from_page = parse_qs(urlparse(referer).query).get(key, [""])[0]
    if from_page in allowed:
        return from_page
    chosen = os.environ.get(env, default)
    return chosen if chosen in allowed else default


def variant_of(handler):
    return _pick(handler, "gh", VARIANTS, "STUB_GH", "connected")


def wants_long(handler):
    """`long=1` on the page adds one project whose every value is too long for its cell. Kept
    out of the stub's own quiet state: the header's project filter lists every project, and a
    name that long is the Queue lane's layout to answer for, not this one's."""
    return _pick(handler, "long", ("1",), "STUB_GH_LONG", "") == "1"


def _record(path, body):
    with LOCK:
        SENT.append({"path": path, "body": body})


def login_state(state, variant):
    if state == "error" or variant == "no_answer":
        return "no_answer"
    if variant == "no_gh":
        return "no_gh"
    if variant == "not_connected":
        return "not_connected"
    if variant == "flip":
        first = FIRST_READ.setdefault("flip", time.time())
        return "not_connected" if time.time() - first < FLIP_SECONDS else "connected"
    return "connected"


def github_payload(state, variant, farm="farm"):
    """GET /api/github, exactly the keys of design section 6."""
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    commands = {
        "login": f"ssh -t {farm} gh auth login -h github.com -p https --web -s workflow",
        "refresh_scopes": f"ssh -t {farm} gh auth refresh -h github.com -s workflow",
        "setup_git": f"ssh -t {farm} gh auth setup-git",
        "switch": f"ssh -t {farm} gh auth switch",
    }
    if state == "loading":
        return {"at": at, "stale_since": None, "error": None, "pending": at,
                "login_state": None, "login": None, "scopes": None, "missing_scopes": [],
                "git_uses_login": None, "two_identities": None,
                "office": {"repo": None, "writable": None, "detail": ""}, "owners": [],
                "rate_remaining": None, "commands": commands}
    current = login_state(state, variant)
    signed = current == "connected"
    scopes = ["gist", "read:org", "repo", "workflow"]
    missing = []
    if variant == "missing_scope":
        scopes = ["gist", "read:org", "repo"]
        missing = ["workflow"]
    if variant == "missing_repo":
        scopes = ["gist", "read:org", "workflow"]
        missing = ["repo"]
    if variant == "no_scopes":
        scopes = []
    if variant == "fine":
        scopes = None
    error = None
    if current == "no_answer":
        error = "gh auth status did not answer within 20 seconds"
    office = {"repo": "your-org/agent-hq", "writable": True,
              "detail": "the last mail was sent 2 minutes ago"}
    if variant == "office_denied":
        office = {"repo": "your-org/agent-hq", "writable": False,
                  "detail": "this account can only read your-org/agent-hq"}
    if variant == "unread":
        scopes = None
        error = "GitHub refused the account call (HTTP 403); the last answer is kept."
        office = {"repo": "your-org/agent-hq", "writable": None,
                  "detail": "Not checked yet: GitHub did not answer about the account."}
    answer = {
        "at": at, "stale_since": None, "error": error, "pending": None,
        "login_state": current, "login": LOGIN if signed else None, "checking": False,
        "account_read": signed and variant != "unread",
        "scopes": scopes if signed else None, "missing_scopes": missing if signed else [],
        "git_uses_login": (variant != "no_git") if signed else None,
        "two_identities": ({"file": ENV_FILE, "line": 3, "variable": "GH_TOKEN"}
                           if variant == "two" else True if variant == "two_flag" else None),
        "office": office if signed else {"repo": "your-org/agent-hq", "writable": False,
                                         "detail": "no GitHub login on this farm"},
        "owners": OWNERS if signed else [],
        "rate_remaining": 4870 if signed else None,
        "commands": commands,
    }
    if state == "quiet":
        answer["stale_since"] = _iso(700)
        answer["rate_remaining"] = 640
        answer["error"] = ("under 1,000 GitHub calls were left this hour, so the farm kept its "
                           "last answer")
    return answer


def project_rows(state, variant, rows):
    """/api/projects rows, with the three fields the snapshot adds."""
    signed = login_state(state, variant) == "connected"
    rows = [dict(row) for row in rows]
    if getattr(CURRENT, "long", False):
        rows.append(dict(LONG_PROJECT))
    for row in rows:
        visibility, permission = ACCESS.get(row.get("repo"), ("private", "admin"))
        row["visibility"] = visibility if signed else None
        row["permission"] = permission if signed else None
        row["html_url"] = f"https://github.com/{row.get('repo')}"
    return rows


def _registered(module):
    return {str(row.get("repo", "")).lower()
            for row in module["PROJECTS"] + module["SENT"]["projects"]}


def repos_answer(module, body):
    owner = str(body.get("owner") or "").lower()
    query = str(body.get("q") or "").lower()
    taken = _registered(module)
    rows = []
    for repo in REPOS:
        if owner and repo["owner"].lower() != owner:
            continue
        if query and query not in repo["name"].lower():
            continue
        rows.append(dict(repo, registered=repo["full_name"].lower() in taken))
    rows.sort(key=lambda repo: repo["pushed_at"], reverse=True)
    return {"repos": rows, "truncated": False}


def _known(full):
    return next((repo for repo in REPOS if repo["full_name"].lower() == str(full).lower()), None)


def branches_answer(body):
    repo = _known(body.get("repo"))
    default = repo["default_branch"] if repo else "main"
    return {"default_branch": default,
            "protected": PROTECTED.get(repo["full_name"] if repo else "", [default])}


def access_answer(variant, body):
    full = str(body.get("repo") or "")
    branch = str(body.get("branch") or "")
    repo = _known(full)
    permission = repo["permission"] if repo else "write"
    default = repo["default_branch"] if repo else "main"
    known = [default] + PROTECTED.get(full, []) + ["release/2026"]
    pushes = permission in ("admin", "maintain", "write")
    checks = [
        {"id": "signed_in", "state": "ok", "sentence": f"Signed in as @{LOGIN}.", "fix": ""},
        {"id": "role", "state": "ok" if pushes else "fail",
         "sentence": (f"Your role is {permission}, which allows a push. The first push is the "
                      "final proof." if pushes else
                      f"Your role is {permission}: agents could copy it but never push."),
         "fix": "" if pushes else "Ask an admin of the repository for write access."},
        {"id": "git_login", "state": "fail" if variant == "no_git" else "ok",
         "sentence": ("git ls-remote could not read this repository with the farm's login."
                      if variant == "no_git" else
                      "git on this farm reads this repository with your login."),
         "fix": "ssh -t farm gh auth setup-git" if variant == "no_git" else ""},
        {"id": "workflow", "state": "warn" if variant == "missing_scope" else "ok",
         "sentence": ("The token cannot change workflow files, so agents cannot edit CI."
                      if variant == "missing_scope" else "The token can change workflow files."),
         "fix": ("ssh -t farm gh auth refresh -h github.com -s workflow"
                 if variant == "missing_scope" else "")},
        {"id": "archived", "state": "fail" if repo and repo["archived"] else "ok",
         "sentence": "The repository is archived." if repo and repo["archived"]
         else "The repository is not archived.", "fix": ""},
        {"id": "branch", "state": "ok" if branch in known else "fail",
         "sentence": (f"The base branch {branch} exists." if branch in known else
                      f"There is no branch called {branch} in {full}."),
         "fix": "" if branch in known else "Pick the default branch, or type one that exists."},
    ]
    return {"checks": checks}


def install(module):
    """Wire the routes into the stub whose globals are `module`. Called once, at import."""
    handler_class = module["Handler"]
    original_payload = module["payload_for"]
    original_get = handler_class.do_GET
    original_post = handler_class.do_POST

    def payload_for(state, path, query):
        code, payload = original_payload(state, path, query)
        if path == "/api/projects" and code == 200 and isinstance(payload, list):
            payload = project_rows(state, getattr(CURRENT, "variant", "connected"), payload)
        return code, payload

    def do_GET(self):
        CURRENT.variant = variant_of(self)
        CURRENT.long = wants_long(self)
        path = urlparse(self.path).path
        if path == "/stub/github/sent":
            with LOCK:
                return self._json(200, {"sent": list(SENT)})
        if path == "/stub/github/env":
            return self._json(200, {key.lower(): os.environ.get(key, "")
                                    for key in ("HOME", "FLEET_STATE", "FLEET_CONFIG")})
        if path == "/api/github":
            return self._json(200, github_payload(self.state(), CURRENT.variant))
        return original_get(self)

    def do_POST(self):
        path = urlparse(self.path).path
        if not (path.startswith("/api/github") or path == "/api/projects"):
            return original_post(self)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._json(400, {"error": "the body is not JSON"})
        _record(path, body)
        state = self.state()
        variant = variant_of(self)
        if path == "/api/projects":
            # The stub's own handler registers the row; the branch the page chose is kept on it.
            self.rfile = io.BytesIO(raw)
            answer = original_post(self)
            branch = str(body.get("branch") or "").strip()
            if branch and module["SENT"]["projects"]:
                module["SENT"]["projects"][-1]["base_branch"] = branch
            return answer
        if path == "/api/github/check":
            left = CHECK_COOLDOWN - (time.time() - LAST_CHECK["at"])
            if left > 0:
                return self._json(429, {"error": "GitHub was asked less than a minute ago.",
                                        "retry_after": int(left) + 1})
            LAST_CHECK["at"] = time.time()
            return self._json(200, {"ok": True, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                    time.gmtime())})
        if state == "error":
            return self._json(503, {"error": "gh on this farm did not answer"})
        if path == "/api/github/repos":
            return self._json(200, repos_answer(module, body))
        if path == "/api/github/branches":
            return self._json(200, branches_answer(body))
        if path == "/api/github/access":
            return self._json(200, access_answer(variant, body))
        return self._json(404, {"error": "not found"})

    module["payload_for"] = payload_for
    handler_class.do_GET = do_GET
    handler_class.do_POST = do_POST
    module["HARNESS"] = module["HARNESS"].replace(
        '<link rel="stylesheet" href="/static/machine.css">',
        '<link rel="stylesheet" href="/static/machine.css">\n'
        '<link rel="stylesheet" href="/static/projects.css">')

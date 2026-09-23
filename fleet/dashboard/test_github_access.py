"""The GitHub connection behind the Projects section (github_access.py).

Nothing here reaches GitHub or the live farm. Each test gets a temporary HOME, FLEET_STATE and
FLEET_CONFIG, and a PATH holding only fakes: a `gh` that answers `auth status`, `api -i user`
with rate and scope headers, the paged list, `repos/<r>` and `repos/<r>/branches?protected=true`,
and that fails the test (a marker file) if anything asks it for `auth token` or `--show-token`; a
`git` for `ls-remote`, `config`, `check-ref-format` and `-C <dir> remote get-url origin`; and an
`ssh` for `-T`. Every fake records its argv, so each test says exactly what ran.
"""
import contextlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import github_access as GA  # noqa: E402

LIST = GA.LIST_PATH
SSO = "X-GitHub-SSO"
SSO_VALUE = "required; url=https://github.com/orgs/acme/sso?authorization_request=SECRETSSO"

FAKE = r'''#!{python}
import json, os, sys
tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as handle:
    handle.write(json.dumps({"argv": [tool] + args,
                             "prompt": os.environ.get("GIT_TERMINAL_PROMPT")}) + "\n")
with open(os.environ["FAKE_SCENARIO"]) as handle:
    sc = json.load(handle)
if tool == "gh":
    if "--show-token" in args or args[:2] == ["auth", "token"] or "credential" in args:
        open(os.environ["FAKE_MARKER"], "w").write(" ".join(args))
        sys.exit(9)
    if args[:2] == ["auth", "status"]:
        answer = sc.get("auth", {"rc": 0, "out": "github.com\n  Logged in to github.com "
                                 "account octo (/x/hosts.yml)\n  - Token: gho_****\n"})
        sys.stderr.write(answer["out"])
        sys.exit(answer["rc"])
    if args[:2] == ["api", "-i"] and len(args) == 3:
        found = sc.get("api", {}).get(args[2])
        if found is None:
            sys.stdout.write("HTTP/2.0 404 Not Found\r\nContent-Type: application/json\r\n\r\n"
                             '{"message": "Not Found"}')
            sys.stderr.write("gh: Not Found (HTTP 404)\n")
            sys.exit(1)
        lines = ["HTTP/2.0 %d X" % found["status"]]
        lines += ["%s: %s" % pair for pair in found.get("headers", {}).items()]
        sys.stdout.write("\r\n".join(lines) + "\r\n\r\n" + json.dumps(found.get("body")))
        sys.exit(0 if found["status"] < 400 else 1)
    sys.exit(2)
if tool == "git":
    if args[:1] == ["config"]:
        helper = sc.get("git_helper")
        if helper:
            print(helper)
        sys.exit(0 if helper else 1)
    if args[:2] == ["check-ref-format", "--branch"]:
        name = args[2]
        bad = ".." in name or " " in name or name.endswith("/") or name.startswith("-")
        if not bad:
            print(name)
        sys.exit(1 if bad else 0)
    if args[:2] == ["ls-remote", "--exit-code"]:
        if any(url in " ".join(args[2:]) for url in sc.get("ls_remote_unreadable", [])):
            sys.exit(128)
        sys.exit(0 if " ".join(args[2:]) in sc.get("ls_remote_ok", []) else 2)
    if args[:1] == ["-C"] and args[2:] == ["remote", "get-url", "origin"]:
        origin = sc.get("origins", {}).get(args[1])
        if origin:
            print(origin)
        sys.exit(0 if origin else 2)
    sys.exit(2)
if tool == "ssh":
    sys.stderr.write(sc.get("ssh", "git@github.com: Permission denied (publickey).") + "\n")
    sys.exit(1)
sys.exit(2)
'''


def api(status, body, remaining=4000, scopes="repo, workflow, read:org", link=None, sso=True):
    headers = {"Content-Type": "application/json", "X-Ratelimit-Remaining": str(remaining)}
    if scopes is not None:
        headers["X-Oauth-Scopes"] = scopes
    if link:
        headers["Link"] = link
    if sso:
        headers[SSO] = SSO_VALUE
    return {"status": status, "headers": headers, "body": body}


def repo(full, permission="push", private=True, archived=False, pushed="2026-09-20T10:00:00Z"):
    owner, name = full.split("/")
    perms = {"admin": permission == "admin", "maintain": False,
             "push": permission in ("admin", "push"), "triage": False, "pull": True}
    return {"full_name": full, "name": name, "owner": {"login": owner}, "private": private,
            "archived": archived, "fork": False, "default_branch": "main", "permissions": perms,
            "pushed_at": pushed, "description": f"about {name}",
            "html_url": f"https://github.com/{full}"}


def page_link(page):
    return (f'<https://api.github.com/user/repos?page={page}>; rel="next", '
            '<https://api.github.com/user/repos?page=9>; rel="last"')


def connected_scenario(**extra):
    scenario = {
        "git_helper": "!/usr/bin/gh auth git-credential",
        "api": {
            "user": api(200, {"login": "octo"}),
            f"{LIST}&page=1": api(200, [repo("octo/one"), repo("acme/office", "push")],
                                  link=page_link(2)),
            f"{LIST}&page=2": api(200, [repo("acme/two", "pull", private=False)],
                                  remaining=3990),
        },
    }
    scenario.update(extra)
    return scenario


class Box:
    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.calls_file = self.root / "calls.jsonl"
        self.scenario_file = self.root / "scenario.json"
        self.marker = self.root / "token-asked"
        self.home = self.root / "home"
        self.config = self.root / "config"
        self.gh_dir = self.root / "gh"

    def scenario(self, value):
        self.scenario_file.write_text(json.dumps(value))

    def calls(self):
        text = self.calls_file.read_text() if self.calls_file.exists() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def argvs(self):
        return [c["argv"] for c in self.calls()]

    def reset_calls(self):
        self.calls_file.write_text("")


@contextlib.contextmanager
def farm(scenario=None, tools=("gh", "git", "ssh")):
    with tempfile.TemporaryDirectory() as root:
        box = Box(root)
        bindir = box.root / "bin"
        for folder in (bindir, box.home, box.config, box.gh_dir, box.root / "state"):
            folder.mkdir()
        for tool in tools:
            path = bindir / tool
            path.write_text(FAKE.replace("{python}", sys.executable))
            path.chmod(0o755)
        box.scenario(scenario if scenario is not None else connected_scenario())
        box.calls_file.write_text("")
        env = {"PATH": str(bindir), "HOME": str(box.home), "FLEET_CONFIG": str(box.config),
               "FLEET_STATE": str(box.root / "state"), "GH_CONFIG_DIR": str(box.gh_dir),
               "FAKE_CALLS": str(box.calls_file), "FAKE_SCENARIO": str(box.scenario_file),
               "FAKE_MARKER": str(box.marker), "FLEET_FARM_ALIAS": "farm"}
        with mock.patch.dict(os.environ, env):
            for name in ("GH_TOKEN", "GITHUB_TOKEN", "XDG_CONFIG_HOME"):
                os.environ.pop(name, None)
            reset_module()
            try:
                yield box
            finally:
                reset_module()


def reset_module():
    with GA._lock:
        GA._snapshot.clear()
        GA._snapshot.update(GA._blank())
    GA._last_check["at"] = 0.0
    GA._watch.update({"mtime": None, "next_pass": 0.0})
    GA._hooks.update({"office": lambda: "", "registry": lambda: {}})


def registry(*pairs):
    return lambda: {name: {"repo": repo_name} for name, repo_name in pairs}


class Base(unittest.TestCase):
    def assertNoTokenAsked(self, box):
        self.assertFalse(box.marker.exists(), "something asked gh to print the token")
        for argv in box.argvs():
            self.assertNotIn("--show-token", argv)
            self.assertNotEqual(argv[:3], ["gh", "auth", "token"])
            self.assertNotIn("fill", argv)

    def assertNoRawHeaders(self, *values):
        text = json.dumps(values)
        for needle in ("SECRETSSO", "sso?", "x-github-sso", "X-GitHub-SSO", "authorization_request",
                       "gho_"):
            self.assertNotIn(needle, text)


class SnapshotPass(Base):
    def test_one_pass_makes_exactly_these_calls(self):
        with farm() as box:
            GA.configure(office=lambda: "acme/office",
                         registry=registry(("one", "octo/one"), ("gone", "acme/gone")))
            GA.run_pass()
            self.assertEqual(box.argvs(), [
                ["gh", "auth", "status", "--active", "-h", "github.com"],
                ["gh", "api", "-i", "user"],
                ["git", "config", "--global", "--get-urlmatch", "credential.helper",
                 "https://github.com"],
                ["gh", "api", "-i", f"{LIST}&page=1"],
                ["gh", "api", "-i", f"{LIST}&page=2"],
                ["gh", "api", "-i", "repos/acme/gone"],
            ])
            answer = GA.github_answer()
            self.assertEqual(answer["login_state"], "connected")
            self.assertEqual(answer["login"], "octo")
            self.assertEqual(answer["scopes"], ["read:org", "repo", "workflow"])
            self.assertEqual(answer["missing_scopes"], [])
            self.assertTrue(answer["git_uses_login"])
            self.assertEqual(answer["owners"], ["octo", "acme"])
            self.assertEqual(answer["rate_remaining"], 3990)
            self.assertEqual(answer["office"]["writable"], True)
            self.assertIsNone(answer["stale_since"])
            self.assertIsNone(answer["error"])
            self.assertFalse(answer["pending"])
            self.assertIsNotNone(answer["at"])
            self.assertIsNone(answer["two_identities"])
            self.assertEqual(answer["commands"]["login"],
                             "ssh -t farm gh auth login -h github.com -p https --web -s workflow")
            rows = GA.decorate_projects([{"name": "one", "repo": "octo/one"},
                                         {"name": "gone", "repo": "acme/gone"},
                                         {"name": "later", "repo": "acme/later"}])
            self.assertEqual([(r["permission"], r["visibility"]) for r in rows],
                             [("write", "private"), ("no_access", None), (None, None)])
            self.assertEqual(rows[0]["html_url"], "https://github.com/octo/one")
            self.assertNoRawHeaders(answer, rows, GA.snapshot(), GA.repos_request({}))
            self.assertNoTokenAsked(box)

    def test_get_and_the_projects_decoration_run_nothing(self):
        with farm() as box:
            GA.run_pass()
            box.reset_calls()
            self.assertEqual(GA.get_route("/api/github")[0], 200)
            GA.decorate_projects([{"repo": "octo/one"}])
            GA.repos_request({"owner": "octo", "q": "o"})
            self.assertEqual(box.argvs(), [])

    def test_the_office_outside_the_list_costs_one_call_and_a_read_role_is_not_writable(self):
        scenario = connected_scenario()
        scenario["api"]["repos/acme/hq"] = api(200, repo("acme/hq", "pull"))
        with farm(scenario) as box:
            GA.configure(office=lambda: "acme/hq")
            GA.run_pass()
            self.assertIn(["gh", "api", "-i", "repos/acme/hq"], box.argvs())
            office = GA.github_answer()["office"]
            self.assertEqual(office["writable"], False)
            self.assertIn("only read", office["detail"])

    def test_a_404_on_the_office_is_a_definite_no(self):
        with farm() as box:
            GA.configure(office=lambda: "acme/secret")
            GA.run_pass()
            self.assertEqual(GA.github_answer()["office"]["writable"], False)
            self.assertNoTokenAsked(box)

    def test_under_the_floor_no_list_call_is_made_and_the_last_answer_is_kept(self):
        with farm() as box:
            GA.configure(registry=registry(("gone", "acme/gone")))
            GA.run_pass()
            before = GA.github_answer()
            scenario = connected_scenario()
            scenario["api"]["user"] = api(200, {"login": "octo"}, remaining=999)
            box.scenario(scenario)
            box.reset_calls()
            GA.run_pass()
            argvs = box.argvs()
            self.assertEqual([a for a in argvs if a[0] == "gh"], [
                ["gh", "auth", "status", "--active", "-h", "github.com"],
                ["gh", "api", "-i", "user"]])
            after = GA.github_answer()
            self.assertIsNotNone(after["stale_since"])
            self.assertIn("999", after["error"])
            self.assertEqual(after["rate_remaining"], 999)
            self.assertEqual(after["owners"], before["owners"])
            self.assertEqual(after["at"], before["at"])
            self.assertEqual(len(GA.repos_request({})[1]["repos"]), 3)
            rows = GA.decorate_projects([{"repo": "acme/gone"}])
            self.assertEqual(rows[0]["permission"], "no_access")

    def test_the_floor_between_pages_cuts_the_list_short(self):
        scenario = connected_scenario()
        scenario["api"][f"{LIST}&page=1"] = api(200, [repo("octo/one")], remaining=1000,
                                                  link=page_link(2))
        scenario["api"][f"{LIST}&page=2"] = api(200, [repo("octo/two")], remaining=999,
                                                  link=page_link(3))
        with farm(scenario) as box:
            GA.run_pass()
            lists = [a for a in box.argvs() if a[-1].startswith("user/repos")]
            self.assertEqual(len(lists), 2)
            self.assertTrue(GA.repos_request({})[1]["truncated"])
            self.assertIsNotNone(GA.github_answer()["stale_since"])

    def test_the_list_stops_at_five_pages(self):
        scenario = connected_scenario()
        for page in range(1, 8):
            scenario["api"][f"{LIST}&page={page}"] = api(200, [repo(f"octo/r{page}")],
                                                         link=page_link(page + 1))
        with farm(scenario) as box:
            GA.run_pass()
            lists = [a for a in box.argvs() if a[-1].startswith("user/repos")]
            self.assertEqual(len(lists), 5)
            answer = GA.repos_request({})[1]
            self.assertTrue(answer["truncated"])
            self.assertEqual(len(answer["repos"]), 5)

    def test_a_failed_list_changes_nothing(self):
        with farm() as box:
            GA.configure(registry=registry(("gone", "acme/gone")))
            GA.run_pass()
            scenario = connected_scenario()
            scenario["api"][f"{LIST}&page=2"] = api(502, {"message": "bad"})
            box.scenario(scenario)
            box.reset_calls()
            GA.run_pass()
            self.assertNotIn(["gh", "api", "-i", "repos/acme/gone"], box.argvs())
            answer = GA.github_answer()
            self.assertIn("HTTP 502", answer["error"])
            self.assertIsNotNone(answer["stale_since"])
            self.assertEqual(len(GA.repos_request({})[1]["repos"]), 3)
            self.assertEqual(GA.decorate_projects([{"repo": "acme/gone"}])[0]["permission"],
                             "no_access")

    def test_a_500_on_a_missing_repository_is_not_no_access(self):
        scenario = connected_scenario()
        scenario["api"]["repos/acme/flaky"] = api(500, {"message": "oops"})
        with farm(scenario):
            GA.configure(registry=registry(("flaky", "acme/flaky")))
            GA.run_pass()
            self.assertIsNone(GA.decorate_projects([{"repo": "acme/flaky"}])[0]["permission"])

    def test_scopes_are_read_whatever_the_case_absent_is_null_empty_is_a_list(self):
        cases = [("REPO, Workflow", ["repo", "workflow"], []),
                 (None, None, []),
                 ("", [], ["repo", "workflow"]),
                 ("repo", ["repo"], ["workflow"])]
        for header, scopes, missing in cases:
            scenario = connected_scenario()
            scenario["api"]["user"] = api(200, {"login": "octo"}, scopes=header)
            with farm(scenario):
                GA.run_pass()
                answer = GA.github_answer()
                self.assertEqual(answer["scopes"], scopes, header)
                self.assertEqual(answer["missing_scopes"], missing, header)
                self.assertNoRawHeaders(answer)

    def test_a_lower_case_header_block_is_read_too(self):
        scenario = connected_scenario()
        scenario["api"]["user"] = {"status": 200, "body": {"login": "octo"},
                                   "headers": {"x-oauth-scopes": "repo",
                                               "x-ratelimit-remaining": "4321"}}
        with farm(scenario):
            GA.run_pass()
            answer = GA.github_answer()
            self.assertEqual(answer["scopes"], ["repo"])
            self.assertEqual(GA.gh_api("user")[1]["remaining"], 4321)

    def test_not_connected_asks_github_nothing_more(self):
        scenario = connected_scenario(auth={"rc": 1, "out": "You are not logged into any "
                                                            "GitHub hosts. To log in, run: gh "
                                                            "auth login\n"})
        with farm(scenario) as box:
            GA.run_pass()
            self.assertEqual(box.argvs(), [["gh", "auth", "status", "--active", "-h",
                                            "github.com"]])
            answer = GA.github_answer()
            self.assertEqual(answer["login_state"], "not_connected")
            self.assertIsNone(answer["login"])
            self.assertEqual(answer["owners"], [])
            self.assertIsNone(GA.decorate_projects([{"repo": "octo/one"}])[0]["permission"])

    def test_no_gh_is_its_own_state(self):
        with farm(tools=("git", "ssh")):
            GA.run_pass()
            self.assertEqual(GA.github_answer()["login_state"], "no_gh")

    def test_no_answer_keeps_the_last_good_answer(self):
        with farm() as box:
            GA.run_pass()
            box.scenario(connected_scenario(auth={"rc": 1, "out": "X Timeout trying to log in "
                                                                  "to github.com account octo\n"}))
            GA.run_pass()
            answer = GA.github_answer()
            self.assertEqual(answer["login_state"], "no_answer")
            self.assertEqual(answer["login"], "octo")
            self.assertEqual(answer["owners"], ["octo", "acme"])
            self.assertIsNotNone(answer["stale_since"])

    def test_two_identities_names_the_file_and_the_line_never_the_value(self):
        with farm() as box:
            (box.config / "env").write_text("# fleet env\nFLEET_X=1\nexport GH_TOKEN="
                                            "ghp_abcdefabcdefabcdefabcdefabcdefabcdef\n")
            GA.run_pass()
            answer = GA.github_answer()
            self.assertEqual(answer["two_identities"],
                             {"file": str(box.config / "env"), "line": 3,
                              "variable": "GH_TOKEN"})
            self.assertNotIn("ghp_", json.dumps(answer))
            (box.config / "env").write_text("GITHUB_TOKEN=\n# GH_TOKEN=x\n")
            GA.run_pass()
            self.assertIsNone(GA.github_answer()["two_identities"])

    def test_the_fake_refuses_to_print_a_token(self):
        # The guard every other test leans on: asking the fake for the token marks the run.
        with farm() as box:
            rc, _, _ = GA._run(["gh", "auth", "token"])
            self.assertEqual(rc, 9)
            self.assertTrue(box.marker.exists())


class Watcher(Base):
    def test_a_changed_hosts_file_triggers_exactly_one_pass(self):
        with farm() as box:
            hosts = box.gh_dir / "hosts.yml"
            hosts.write_text("github.com: {}\n")
            os.utime(hosts, ns=(1_000_000_000, 1_000_000_000))
            self.assertTrue(GA.watch_tick(now=1000.0))            # the first pass is due
            self.assertFalse(GA.watch_tick(now=1001.0))
            box.reset_calls()
            os.utime(hosts, ns=(2_000_000_000, 2_000_000_000))
            self.assertTrue(GA.watch_tick(now=1002.0))
            self.assertFalse(GA.watch_tick(now=1003.0))
            self.assertFalse(GA.watch_tick(now=1004.0))
            status = [a for a in box.argvs() if a[:3] == ["gh", "auth", "status"]]
            self.assertEqual(len(status), 1)

    def test_noticing_costs_no_call(self):
        with farm() as box:
            GA.watch_tick(now=1000.0)
            box.reset_calls()
            for step in range(1, 50):
                GA.watch_tick(now=1000.0 + step)
            self.assertEqual(box.argvs(), [])

    def test_a_login_appearing_is_noticed(self):
        with farm() as box:
            GA.watch_tick(now=1000.0)
            box.reset_calls()
            (box.gh_dir / "hosts.yml").write_text("github.com: {}\n")
            self.assertTrue(GA.watch_tick(now=1001.0))
            self.assertEqual(len([a for a in box.argvs() if a[:2] == ["gh", "auth"]]), 1)

    def test_a_definite_answer_on_a_missing_repository_is_not_asked_again_for_an_hour(self):
        gone = ["gh", "api", "-i", "repos/acme/gone"]
        scenario = connected_scenario()
        scenario["api"]["repos/acme/seen"] = api(200, repo("acme/seen", "pull"))
        with farm(scenario) as box, mock.patch.object(GA, "_now", return_value=1000.0) as clock:
            GA.configure(registry=registry(("gone", "acme/gone"), ("seen", "acme/seen")))
            for step in (0, 300, 600):
                self.assertTrue(GA.watch_tick(now=1000.0 + step))
            self.assertEqual(box.argvs().count(gone), 1)
            self.assertEqual(box.argvs().count(["gh", "api", "-i", "repos/acme/seen"]), 1)
            rows = GA.decorate_projects([{"repo": "acme/gone"}, {"repo": "acme/seen"}])
            self.assertEqual([r["permission"] for r in rows], ["no_access", "read"])
            # older than an hour: asked again
            clock.return_value = 1000.0 + 3600
            box.reset_calls()
            self.assertTrue(GA.watch_tick(now=1000.0 + 3600))
            self.assertEqual(box.argvs().count(gone), 1)
            # gh's login file changed: asked again, whatever the age
            box.reset_calls()
            (box.gh_dir / "hosts.yml").write_text("github.com: {}\n")
            self.assertTrue(GA.watch_tick(now=1000.0 + 3601))
            self.assertEqual(box.argvs().count(gone), 1)
            # a person pressed Re-check: asked again
            box.reset_calls()
            code, payload = GA.check_request(now=1000.0 + 3700)
            self.assertEqual(code, 202)
            payload["_thread"].join(10)
            self.assertEqual(box.argvs().count(gone), 1)
            self.assertEqual(GA.decorate_projects([{"repo": "acme/gone"}])[0]["permission"],
                             "no_access")

    def test_an_answer_that_was_not_definite_is_asked_again_on_the_next_pass(self):
        flaky = ["gh", "api", "-i", "repos/acme/flaky"]
        scenario = connected_scenario()
        scenario["api"]["repos/acme/flaky"] = api(500, {"message": "oops"})
        with farm(scenario) as box, mock.patch.object(GA, "_now", return_value=1000.0):
            GA.configure(registry=registry(("flaky", "acme/flaky")))
            GA.watch_tick(now=1000.0)
            GA.watch_tick(now=1300.0)
            self.assertEqual(box.argvs().count(flaky), 2)

    def test_the_five_minute_pass(self):
        with farm():
            self.assertTrue(GA.watch_tick(now=1000.0))
            self.assertFalse(GA.watch_tick(now=1299.0))
            self.assertTrue(GA.watch_tick(now=1300.0))


class AccountRefused(Base):
    def test_a_login_whose_account_call_is_refused_names_the_login_and_claims_nothing(self):
        # The login lands while GitHub refuses the account call (an hour whose allowance is
        # spent): the page used to say "Signed in as @null" and promise every right.
        scenario = connected_scenario()
        scenario["api"]["user"] = api(403, {"message": "API rate limit exceeded"}, remaining=0)
        with farm(scenario):
            GA.configure(office=lambda: "acme/office")
            GA.run_pass()
            answer = GA.github_answer()
            self.assertEqual(answer["login_state"], "connected")
            self.assertEqual(answer["login"], "octo")
            self.assertFalse(answer["account_read"])
            self.assertIsNone(answer["office"]["writable"])
            self.assertIn("did not answer about the account", answer["office"]["detail"])
            self.assertNotIn("being saved", answer["office"]["detail"])

    def test_an_answered_account_is_read(self):
        with farm():
            GA.run_pass()
            self.assertTrue(GA.github_answer()["account_read"])

    def test_a_farm_that_is_not_signed_in_says_so_about_the_office(self):
        scenario = connected_scenario(auth={"rc": 1, "out": "You are not logged into any GitHub hosts.\n"})
        with farm(scenario):
            GA.configure(office=lambda: "acme/office")
            GA.run_pass()
            office = GA.github_answer()["office"]
            self.assertIsNone(office["writable"])
            self.assertIn("not signed in", office["detail"])


class Check(Base):
    def test_a_check_is_checking_until_its_pass_answers_and_never_pending(self):
        # The page reads "checking" to know when a Re-check has its answer; without it the answer
        # showed at the next minute's read. "pending" must stay false: the page draws a loading
        # skeleton for it. The pass is held on an event so the check is exact.
        import threading
        with farm():
            GA.run_pass()
            self.assertFalse(GA.github_answer()["pending"])
            self.assertFalse(GA.github_answer()["checking"])
            started, go = threading.Event(), threading.Event()

            def held_pass(fresh=False):
                started.set()
                go.wait(5)

            with mock.patch.object(GA, "_pass", side_effect=held_pass):
                code, payload = GA.check_request(now=5000.0)
                try:
                    self.assertEqual(code, 202)
                    self.assertTrue(started.wait(5))
                    self.assertTrue(GA.github_answer()["checking"])
                    self.assertFalse(GA.github_answer()["pending"])
                finally:
                    go.set()
                    payload["_thread"].join(10)
            self.assertFalse(GA.github_answer()["checking"])

    def test_one_at_a_time_and_a_cooldown(self):
        with farm() as box:
            code, payload = GA.check_request(now=1000.0)
            self.assertEqual(code, 202)
            payload["_thread"].join(10)
            self.assertEqual(len([a for a in box.argvs() if a[:2] == ["gh", "auth"]]), 1)
            code, payload = GA.check_request(now=1030.0)
            self.assertEqual(code, 429)
            self.assertEqual(payload["retry_after"], 30)
            GA._pass_lock.acquire()
            try:
                code, payload = GA.check_request(now=1061.0)
                self.assertEqual(code, 409)
            finally:
                GA._pass_lock.release()
            code, payload = GA.check_request(now=1062.0)
            self.assertEqual(code, 202)
            payload["_thread"].join(10)


class Inputs(Base):
    def test_urls_reduce_only_for_github(self):
        good = ["octo/one", "https://github.com/octo/one", "https://github.com/octo/one.git",
                "https://github.com/octo/one/", "git@github.com:octo/one.git",
                "git@github.com:octo/one"]
        for value in good:
            self.assertEqual(GA.reduce_repo(value), "octo/one", value)
        bad = ["https://gitlab.com/octo/one", "http://github.com/octo/one",
               "https://github.com.evil.io/octo/one", "https://evil.io/github.com/octo/one",
               "git@gitlab.com:octo/one.git", "-x/y", "octo/-y", "../..", "octo", "o/r/x",
               "octo/one; rm -rf /", "https://user:pw@github.com/octo/one", ""]
        for value in bad:
            self.assertIsNone(GA.reduce_repo(value), value)

    def test_refusals_run_nothing(self):
        with farm() as box:
            GA.run_pass()
            box.reset_calls()
            refused = [
                ("/api/github/access", {"repo": "https://gitlab.com/o/r", "name": "r"}),
                ("/api/github/access", {"repo": "-o/r", "name": "r"}),
                ("/api/github/access", {"repo": "o/r", "name": "../r"}),
                ("/api/github/access", {"repo": "o/r", "name": "-r"}),
                ("/api/github/access", {"repo": "o/r", "name": "r", "branch": "-evil"}),
                ("/api/github/access", {"repo": ["o/r"], "name": "r"}),
                ("/api/github/branches", {"repo": "o/r --show-token"}),
                ("/api/github/branches", {}),
            ]
            for path, body in refused:
                code, _ = GA.post_route(path, body)
                self.assertEqual(code, 400, (path, body))
            self.assertEqual(box.argvs(), [])
            code, answer = GA.post_route("/api/github/repos",
                                         {"owner": "--show-token", "q": "$(id)"})
            self.assertEqual((code, answer["repos"]), (200, []))
            self.assertEqual(box.argvs(), [])
            self.assertNoTokenAsked(box)

    def test_a_branch_git_refuses_is_refused(self):
        with farm() as box:
            code, answer = GA.post_route("/api/github/access",
                                         {"repo": "octo/one", "name": "one", "branch": "a..b"})
            self.assertEqual(code, 400)
            self.assertEqual(box.argvs(), [["git", "check-ref-format", "--branch", "a..b"]])

    def test_api_paths_are_quoted(self):
        self.assertEqual(GA._api_path("o/r.x"), "repos/o/r.x")
        self.assertEqual(GA._api_path("o/a b"), "repos/o/a%20b")


class Routes(Base):
    def test_repos_filter_in_memory(self):
        with farm():
            GA.configure(registry=registry(("one", "Octo/One")))
            GA.run_pass()
            code, answer = GA.post_route("/api/github/repos", {"owner": "ACME"})
            self.assertEqual(code, 200)
            self.assertEqual([r["full_name"] for r in answer["repos"]],
                             ["acme/office", "acme/two"])
            answer = GA.repos_request({"q": "ON"})[1]
            self.assertEqual([r["full_name"] for r in answer["repos"]], ["octo/one"])
            row = answer["repos"][0]
            self.assertEqual(set(row), {"full_name", "owner", "name", "private", "archived",
                                        "fork", "default_branch", "permission", "pushed_at",
                                        "description", "registered"})
            self.assertTrue(row["registered"])
            self.assertEqual(row["permission"], "write")
            self.assertFalse(answer["truncated"])
            two = GA.repos_request({"q": "two"})[1]["repos"][0]
            self.assertEqual((two["permission"], two["private"], two["registered"]),
                             ("read", False, False))

    def test_branches(self):
        scenario = connected_scenario()
        scenario["api"]["repos/octo/one"] = api(200, dict(repo("octo/one"),
                                                          default_branch="trunk"))
        scenario["api"]["repos/octo/one/branches?protected=true&per_page=100"] = api(
            200, [{"name": "trunk"}, {"name": "release"}])
        with farm(scenario) as box:
            code, answer = GA.post_route("/api/github/branches",
                                         {"repo": "https://github.com/octo/one.git"})
            self.assertEqual(code, 200)
            self.assertEqual((answer["default_branch"], answer["protected"]),
                             ("trunk", ["trunk", "release"]))
            self.assertEqual(box.argvs(), [
                ["gh", "api", "-i", "repos/octo/one"],
                ["gh", "api", "-i", "repos/octo/one/branches?protected=true&per_page=100"]])
            self.assertNoRawHeaders(answer)
            code, answer = GA.post_route("/api/github/branches", {"repo": "octo/nothing"})
            self.assertEqual(code, 404)

    def test_unknown_routes(self):
        self.assertEqual(GA.get_route("/api/github/repos")[0], 404)
        self.assertEqual(GA.post_route("/api/github/nothing", {})[0], 404)


def access_scenario(permission="push", archived=False, ls=("HEAD",), **extra):
    scenario = connected_scenario(**extra)
    scenario["api"]["repos/octo/one"] = api(200, repo("octo/one", permission,
                                                      archived=archived))
    scenario["ls_remote_ok"] = [f"https://github.com/octo/one.git {ref}" for ref in ls]
    return scenario


class Access(Base):
    def run_access(self, box, body=None, before=None):
        GA.run_pass()
        if before:
            before()
        box.reset_calls()
        body = body or {"repo": "octo/one", "name": "one"}
        code, answer = GA.post_route("/api/github/access", body)
        self.assertEqual(code, 200)
        self.assertNoRawHeaders(answer)
        self.assertNoTokenAsked(box)
        return {c["id"]: c for c in answer["checks"]}, answer

    def test_everything_passes(self):
        with farm(access_scenario()) as box:
            checks, answer = self.run_access(box)
            self.assertEqual(list(checks), ["signed_in", "role", "git_login", "workflow_scope",
                                            "not_archived", "base_branch", "folder"])
            self.assertEqual({c["state"] for c in checks.values()}, {"ok"})
            self.assertTrue(answer["importable"])
            self.assertEqual(answer["branch"], "main")
            self.assertIn("final proof", checks["role"]["sentence"])
            self.assertEqual(box.argvs(), [
                ["gh", "api", "-i", "repos/octo/one"],
                ["git", "ls-remote", "--exit-code", "https://github.com/octo/one.git", "HEAD"]])
            ls_call = box.calls()[1]
            self.assertEqual(ls_call["prompt"], "0")

    def test_a_public_repository_reached_without_the_login_is_not_ok(self):
        # `git ls-remote` of a public repository needs no login, so it proves nothing about the
        # first push: without gh's credential helper the line warns and names the fix.
        scenario = access_scenario()
        scenario["git_helper"] = None
        scenario["api"]["repos/octo/one"] = api(200, repo("octo/one", private=False))
        with farm(scenario) as box:
            checks, answer = self.run_access(box)
            self.assertEqual(checks["git_login"]["state"], "warn")
            self.assertEqual(checks["git_login"]["fix"], "ssh -t farm gh auth setup-git")
            self.assertIn("push", checks["git_login"]["sentence"])
            self.assertNotIn("with your login", checks["git_login"]["sentence"])

    def test_a_private_repository_reached_by_git_is_the_proof(self):
        # For a private repository `ls-remote` needs a login, so reaching it is the proof even
        # when the helper is not gh's own.
        scenario = access_scenario()
        scenario["git_helper"] = "store"
        with farm(scenario) as box:
            checks, _ = self.run_access(box)
            self.assertEqual(checks["git_login"]["state"], "ok")

    def test_a_public_repository_with_the_login_is_ok(self):
        scenario = access_scenario()
        scenario["api"]["repos/octo/one"] = api(200, repo("octo/one", private=False))
        with farm(scenario) as box:
            checks, _ = self.run_access(box)
            self.assertEqual(checks["git_login"]["state"], "ok")

    def test_admin_is_ok_too(self):
        with farm(access_scenario("admin")) as box:
            checks, _ = self.run_access(box)
            self.assertIn("Admin", checks["role"]["sentence"])
            self.assertEqual(checks["role"]["state"], "ok")

    def test_the_failing_and_warning_lines(self):
        scenario = access_scenario("pull", archived=True, ls=())
        scenario["api"]["user"] = api(200, {"login": "octo"}, scopes="repo")
        with farm(scenario) as box:
            checks, answer = self.run_access(box)
            self.assertEqual(checks["role"]["state"], "fail")
            self.assertIn("Read only", checks["role"]["sentence"])
            self.assertEqual(checks["git_login"]["state"], "fail")
            self.assertEqual(checks["git_login"]["fix"], "ssh -t farm gh auth setup-git")
            self.assertEqual(checks["workflow_scope"]["state"], "warn")
            self.assertEqual(checks["workflow_scope"]["fix"],
                             "ssh -t farm gh auth refresh -h github.com -s workflow")
            self.assertEqual(checks["not_archived"]["state"], "fail")
            self.assertFalse(answer["importable"])

    def test_scopes_that_cannot_be_read_warn(self):
        scenario = access_scenario()
        scenario["api"]["user"] = api(200, {"login": "octo"}, scopes=None)
        with farm(scenario) as box:
            checks, answer = self.run_access(box)
            self.assertEqual(checks["workflow_scope"]["state"], "warn")
            self.assertIn("cannot be read", checks["workflow_scope"]["sentence"])
            self.assertTrue(answer["importable"])

    def test_not_signed_in_and_not_visible(self):
        scenario = access_scenario(auth={"rc": 1, "out": "You are not logged into any GitHub "
                                                         "hosts.\n"})
        del scenario["api"]["repos/octo/one"]
        with farm(scenario) as box:
            checks, answer = self.run_access(box)
            self.assertEqual(checks["signed_in"]["state"], "fail")
            self.assertIn("gh auth login", checks["signed_in"]["fix"])
            self.assertEqual(checks["role"]["state"], "fail")
            self.assertIn("cannot see", checks["role"]["sentence"])
            self.assertEqual(checks["not_archived"]["state"], "fail")
            self.assertEqual(checks["base_branch"]["state"], "fail")
            self.assertFalse(answer["importable"])

    def test_the_base_branch(self):
        with farm(access_scenario(ls=("HEAD", "refs/heads/dev"))) as box:
            checks, _ = self.run_access(box, {"repo": "octo/one", "name": "one",
                                              "branch": "dev"})
            self.assertEqual(checks["base_branch"]["state"], "ok")
            self.assertIn(["git", "ls-remote", "--exit-code", "https://github.com/octo/one.git",
                           "refs/heads/dev"], box.argvs())
            self.assertIn(["git", "check-ref-format", "--branch", "dev"], box.argvs())
            checks, _ = self.run_access(box, {"repo": "octo/one", "name": "one",
                                              "branch": "gone"})
            self.assertEqual(checks["base_branch"]["state"], "fail")
            self.assertIn("There is no branch gone", checks["base_branch"]["sentence"])

    def test_a_repository_git_cannot_read_is_not_a_missing_branch(self):
        # Git answers 128, not 2, when it could not read the repository at all (a private one
        # before `gh auth setup-git`): the branch may well exist.
        scenario = access_scenario(ls=("HEAD",))
        scenario["ls_remote_unreadable"] = ["octo/one.git"]
        with farm(scenario) as box:
            checks, _ = self.run_access(box, {"repo": "octo/one", "name": "one",
                                              "branch": "release/2026"})
            self.assertEqual(checks["base_branch"]["state"], "fail")
            self.assertNotIn("There is no branch", checks["base_branch"]["sentence"])
            self.assertIn("could not read octo/one", checks["base_branch"]["sentence"])
            self.assertEqual(checks["base_branch"]["fix"], "ssh -t farm gh auth setup-git")

    def folder_case(self, origin, ssh=None):
        extra = {}
        with farm(access_scenario(**extra)) as box:
            folder = box.home / "work" / "one"
            folder.mkdir(parents=True)
            scenario = access_scenario()
            if origin:
                scenario["origins"] = {str(folder): origin}
            if ssh:
                scenario["ssh"] = ssh
            box.scenario(scenario)
            checks, _ = self.run_access(box)
            self.assertIn(["git", "-C", str(folder), "remote", "get-url", "origin"], box.argvs())
            return checks["folder"], box.argvs()

    def test_folder_https_same_repository(self):
        check, argvs = self.folder_case("https://github.com/octo/one.git")
        self.assertEqual(check["state"], "ok")
        self.assertFalse([a for a in argvs if a[0] == "ssh"])

    def test_folder_other_repository(self):
        check, _ = self.folder_case("https://github.com/octo/other.git")
        self.assertEqual(check["state"], "fail")
        self.assertIn("octo/other", check["sentence"])

    def test_folder_origin_not_github_never_echoes_it(self):
        check, _ = self.folder_case("https://x-access-token:ghs_secretsecret@gitlab.com/o/r.git")
        self.assertEqual(check["state"], "fail")
        self.assertNotIn("secret", check["sentence"])

    def test_folder_without_origin(self):
        check, _ = self.folder_case(None)
        self.assertEqual(check["state"], "fail")

    def test_folder_ssh_same_account(self):
        check, argvs = self.folder_case("git@github.com:octo/one.git",
                                        ssh="Hi octo! You've successfully authenticated, but "
                                            "GitHub does not provide shell access.")
        self.assertEqual(check["state"], "ok")
        self.assertIn(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                       "git@github.com"], argvs)

    def test_folder_ssh_other_account(self):
        check, _ = self.folder_case("git@github.com:octo/one.git",
                                    ssh="Hi robot! You've successfully authenticated, but "
                                        "GitHub does not provide shell access.")
        self.assertEqual(check["state"], "warn")
        self.assertIn("@robot", check["sentence"])

    def test_folder_ssh_key_refused(self):
        check, _ = self.folder_case("git@github.com:octo/one.git")
        self.assertEqual(check["state"], "fail")


# ---------------------------------------------------------------- through the dashboard itself

SERVER_PATH = HERE / "server.py"
SPEC = importlib.util.spec_from_file_location("fleet_dashboard_server_github", SERVER_PATH)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


@contextlib.contextmanager
def running_server():
    server = dashboard.Server(("127.0.0.1", 0), dashboard.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def fetch(base, path, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


class ThroughTheServer(Base):
    def test_routes_behind_the_dashboard(self):
        with farm() as box, mock.patch.object(dashboard, "TOKEN", "secret-token"), \
                mock.patch.object(dashboard, "_projects_registry",
                                  lambda: {"one": {"repo": "octo/one"}}), \
                running_server() as base:
            status, answer = fetch(base, "/api/github")
            self.assertEqual(status, 200)
            self.assertTrue(answer["pending"])
            self.assertEqual(box.argvs(), [])
            status, _ = fetch(base, "/api/github/check", "POST", {})
            self.assertEqual(status, 403)
            self.assertEqual(box.argvs(), [])
            status, answer = fetch(base, "/api/github/check", "POST", {}, token="secret-token")
            self.assertEqual(status, 202)
            with GA._pass_lock:
                pass
            status, answer = fetch(base, "/api/github/check", "POST", {}, token="secret-token")
            self.assertEqual(status, 429)
            self.assertGreater(answer["retry_after"], 0)
            status, answer = fetch(base, "/api/github")
            self.assertEqual((status, answer["login"]), (200, "octo"))
            box.reset_calls()
            status, rows = fetch(base, "/api/projects")
            self.assertEqual(status, 200)
            self.assertEqual((rows[0]["permission"], rows[0]["visibility"], rows[0]["html_url"]),
                             ("write", "private", "https://github.com/octo/one"))
            self.assertEqual(box.argvs(), [])
            self.assertNoTokenAsked(box)

    def test_add_project_passes_the_branch_and_refuses_a_bad_one(self):
        started = []

        def fake_start(action, args, timeout, label=None, key=None):
            started.append(list(args))
            return 202, {"job": "x"}

        scenario = connected_scenario(
            ls_remote_ok=["https://github.com/octo/one.git refs/heads/develop"])
        with farm(scenario) as box, mock.patch.object(dashboard, "start_job", fake_start), \
                mock.patch.object(dashboard, "_projects_registry", lambda: {}):
            code, _ = dashboard.add_project({"name": "one", "repo": "octo/one",
                                             "branch": "develop"})
            self.assertEqual(code, 202)
            self.assertEqual(started[-1][-2:], ["--branch", "develop"])
            ls = [a for a in box.argvs() if a[:2] == ["git", "ls-remote"]]
            self.assertEqual(ls, [["git", "ls-remote", "--exit-code",
                                   "https://github.com/octo/one.git", "refs/heads/develop"]])
            # A branch git cannot find is refused before any job starts: every lane of the
            # project would fail on it.
            code, answer = dashboard.add_project({"name": "one", "repo": "octo/one",
                                                  "branch": "no-such"})
            self.assertEqual(code, 400)
            self.assertIn("no-such", answer["error"])
            self.assertEqual(len(started), 1)
            code, _ = dashboard.add_project({"name": "one", "repo": "octo/one",
                                             "branch": "-x"})
            self.assertEqual(code, 400)
            code, _ = dashboard.add_project({"name": "one", "repo": "octo/one"})
            self.assertNotIn("--branch", started[-1])
            self.assertEqual(len(started), 2)
            self.assertNoTokenAsked(box)


class HouseStyle(unittest.TestCase):
    def test_no_em_dash_and_no_token_printing_command(self):
        for path in (HERE / "github_access.py", pathlib.Path(__file__)):
            text = path.read_text()
            self.assertNotIn(chr(0x2014), text, path.name)
        source = (HERE / "github_access.py").read_text()
        code_lines = [line for line in source.splitlines()
                      if not line.strip().startswith("#") and '"' in line]
        joined = "\n".join(code_lines)
        self.assertNotIn('"token"]', joined)
        self.assertNotIn('"--show-token"', joined)
        self.assertNotIn('"fill"', joined)


if __name__ == "__main__":
    unittest.main(verbosity=1)

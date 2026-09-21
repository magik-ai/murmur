import contextlib
import datetime
import http.client
import importlib.util
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from unittest import mock


SERVER_PATH = pathlib.Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("fleet_dashboard_server", SERVER_PATH)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

@contextlib.contextmanager
def running_server():
    """The dashboard on a throwaway port, shut down whatever the test does."""
    server = dashboard.Server(("127.0.0.1", 0), dashboard.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextlib.contextmanager
def fake_tools(scripts, env=None):
    """A PATH holding only the fake executables this test asks for.

    Every fake appends its own command line to $TOOL_CALLS, so a test can assert what ran and,
    just as important, what did not: `hq inbox` consumes the office's mail for every process
    signing as this name, and this dashboard must never call it.

    PATH holds these fakes and nothing else, so a check cannot quietly pass by finding the real
    tool on the machine the test happens to run on. That also means a fake may only use shell
    builtins; a script starting with "#!" is written verbatim instead, for the rest.
    """
    with tempfile.TemporaryDirectory() as home:
        root = pathlib.Path(home)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        calls = root / "calls.txt"
        calls.write_text("")
        for name, script in scripts.items():
            tool = bin_dir / name
            if script.startswith("#!"):
                tool.write_text(script)
            else:
                tool.write_text('#!/bin/sh\nprintf "%s\\n" "${0##*/} $*" >> "$TOOL_CALLS"\n'
                                + script)
            tool.chmod(0o755)
        environment = {"PATH": str(bin_dir), "TOOL_CALLS": str(calls), "HOME": str(root),
                       "XDG_CONFIG_HOME": str(root / "config")}
        environment.update(env or {})
        with mock.patch.dict(os.environ, environment, clear=False):
            yield types.SimpleNamespace(root=root, bin=bin_dir, calls=calls,
                                        config=root / "config")


def write_hq_config(box, repo="acme/office"):
    path = box.config / "hq" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'repo = "{repo}"\n')
    return path


def fetch(base, path, token=None, method="GET", body=None, headers=None):
    """(status, raw bytes, content type). Errors come back as answers, not exceptions: the
    status is what most of these tests are about."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    if token is not None:
        request.add_header("Authorization", "Bearer " + token)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read(), response.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type")


def fetch_json(base, path, **kwargs):
    status, raw, _ = fetch(base, path, **kwargs)
    return status, json.loads(raw or b"{}")


class DashboardServerTest(unittest.TestCase):
    def setUp(self):
        # The farm's real daemon may be active while these isolated fixtures run.
        # Default it to inactive; the dedicated daemon-state test overrides both
        # outcomes explicitly.
        patcher = mock.patch.object(
            dashboard.subprocess,
            "run",
            return_value=mock.Mock(stdout="inactive\n", returncode=3),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ci_queue_is_well_formed_before_the_coordinator_runs(self):
        with tempfile.TemporaryDirectory() as state:
            with mock.patch.object(dashboard, "STATE", state):
                self.assertEqual(
                    dashboard.ci_queue(),
                    {"updated": None, "running": [], "queued": [], "recent": [],
                     "daemon_alive": False},
                )

    def test_ci_queue_uses_the_coordinator_refreshed_view(self):
        stored = {
            "updated": 1784600000,
            "running": [],
            "queued": [],
            "recent": [{"id": "ci-passed", "state": "passed"}],
        }
        refreshed = {
            **stored,
            "updated": 1784600001,
            "recent": [
                {
                    "id": "ci-passed",
                    "state": "passed",
                    "stale": True,
                    "stale_reason": "verified against main@old, now new",
                    "farm_verdict": "passed",
                    "hosted_verdict": "failed",
                    "divergent": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as state:
            ci_dir = pathlib.Path(state, "ci")
            ci_dir.mkdir()
            ci_dir.joinpath("queue.json").write_text(json.dumps(stored))
            with (
                mock.patch.object(dashboard, "STATE", state),
                mock.patch.object(
                    dashboard.CI, "read_state", return_value=refreshed
                ) as read_state,
            ):
                self.assertEqual(dashboard.ci_queue(), {**refreshed, "daemon_alive": False})
        read_state.assert_called_once_with(refresh=True)

    def test_ci_queue_falls_back_to_the_stored_shape_when_refresh_fails(self):
        stored = {
            "updated": 1784600000,
            "running": "invalid",
            "queued": [{"id": "ci-queued", "state": "queued"}],
            "recent": [{"id": "legacy", "state": "passed"}],
        }
        with tempfile.TemporaryDirectory() as state:
            ci_dir = pathlib.Path(state, "ci")
            ci_dir.mkdir()
            ci_dir.joinpath("queue.json").write_text(json.dumps(stored))
            with (
                mock.patch.object(dashboard, "STATE", state),
                mock.patch.object(
                    dashboard.CI,
                    "read_state",
                    side_effect=dashboard.CI.CIError("refresh unavailable"),
                ),
            ):
                self.assertEqual(
                    dashboard.ci_queue(),
                    {
                        "updated": 1784600000,
                        "running": [],
                        "queued": [{"id": "ci-queued", "state": "queued"}],
                        "recent": [{"id": "legacy", "state": "passed"}],
                        "daemon_alive": False,
                    },
                )

    def test_malformed_ci_queue_returns_empty_payload_and_other_routes_stay_live(self):
        empty = {"updated": None, "running": [], "queued": [], "recent": []}
        live_agents = [{"slug": "ui2", "status": "running"}]
        with tempfile.TemporaryDirectory() as state:
            ci_dir = pathlib.Path(state, "ci")
            ci_dir.mkdir()
            ci_dir.joinpath("queue.json").write_text('{"running": [')
            with (
                mock.patch.object(dashboard, "STATE", state),
                mock.patch.object(dashboard, "agents", return_value=live_agents),
                mock.patch.object(dashboard.CI, "read_state") as read_state,
            ):
                server = dashboard.Server(("127.0.0.1", 0), dashboard.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"

                def get(path):
                    with urllib.request.urlopen(base + path) as response:
                        self.assertEqual(response.status, 200)
                        return json.load(response)

                try:
                    self.assertEqual(get("/api/ci"), {**empty, "daemon_alive": False})
                    self.assertEqual(get("/api/fleet"), live_agents)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
        read_state.assert_not_called()

    def test_unreadable_agent_records_stay_visible_and_detail_is_explicit(self):
        with tempfile.TemporaryDirectory() as state:
            state_dir = pathlib.Path(state, "state")
            state_dir.mkdir()
            state_dir.joinpath("good-1.json").write_text(
                json.dumps(
                    {
                        "slug": "good-1",
                        "project": "demo",
                        "lane": "good",
                        "engine": "codex",
                        "status": "running",
                    }
                )
            )
            torn = state_dir / "torn-1.json"
            torn.write_text('{"slug":"torn-1","project":')
            empty = state_dir / "empty-1.json"
            empty.write_text("")

            with mock.patch.object(dashboard, "STATE", state):
                cards = {card["slug"]: card for card in dashboard.agents()}
                self.assertEqual(
                    set(cards),
                    {"good-1", "torn-1", "empty-1"},
                    "an unreadable record must not make its dashboard card disappear",
                )
                for slug, path in (("torn-1", torn), ("empty-1", empty)):
                    self.assertEqual(cards[slug]["status"], "state_unreadable")
                    self.assertEqual(cards[slug]["outcome"], "unknown")
                    self.assertEqual(cards[slug]["state_path"], str(path))

                detail = dashboard.agent_detail("torn-1")
                self.assertEqual(detail["slug"], "torn-1")
                self.assertEqual(detail["status"], "state_unreadable")
                self.assertEqual(detail["outcome"], "unknown")
                self.assertNotIn("error", detail)
                self.assertEqual(
                    dashboard.agent_detail("missing-1"),
                    {"error": "not found"},
                )


    def test_accounts_snapshot_serves_without_blocking_and_keeps_shape(self):
        # The endpoint serves whatever the 10-minute refresher last produced and never touches
        # the network itself - a dashboard that blocks on Anthropic to draw is the same defect
        # the CI pane had. Shape is pinned so the tiles cannot silently lose fields, and the
        # snapshot must be a deep copy: a handler mutating its response must not poison the
        # shared state.
        fixture = {"at": 123.0,
                   "accounts": [{"name": "default", "session": 5, "weekly": 51,
                                 "scoped": [{"label": "Fable", "percent": 96,
                                              "active": True}]}],
                   "errors": {}}
        with mock.patch.object(dashboard, "_accounts_snapshot", fixture):
            snap = dashboard.accounts_snapshot()
            self.assertEqual(snap["at"], 123.0)
            self.assertEqual(snap["accounts"][0]["weekly"], 51)
            self.assertEqual(snap["accounts"][0]["scoped"][0]["label"], "Fable")
            snap["accounts"][0]["weekly"] = 0
            self.assertEqual(fixture["accounts"][0]["weekly"], 51)

    def test_ci_log_tail_is_bounded_and_missing_logs_are_plain(self):
        with tempfile.TemporaryDirectory() as state:
            log_dir = pathlib.Path(state, "ci", "logs", "ci-safe")
            log_dir.mkdir(parents=True)
            log_path = log_dir / "backend.log"
            log_path.write_text("0123456789")
            record = {
                "id": "ci-safe",
                "tiers": [
                    {"name": "backend", "log": str(log_path)},
                    {
                        "name": "frontend",
                        "log": str(log_dir / "frontend.log"),
                    },
                    {"name": "docker", "log": None},
                ],
            }
            queue = {
                "running": [],
                "queued": [],
                "recent": [record],
            }
            with (
                mock.patch.object(dashboard, "STATE", state),
                mock.patch.object(dashboard, "CI_LOG_TAIL_BYTES", 5),
                mock.patch.object(dashboard, "ci_queue", return_value=queue),
            ):
                code, payload = dashboard.ci_log_tail("ci-safe", "backend")
                self.assertEqual(code, 200)
                self.assertEqual(payload["content"], "56789")
                self.assertTrue(payload["truncated"])

                code, payload = dashboard.ci_log_tail("ci-safe", "docker")
                self.assertEqual(code, 200)
                self.assertTrue(payload["missing"])
                self.assertIn("No action log", payload["message"])

                code, payload = dashboard.ci_log_tail(
                    "ci-safe", "frontend"
                )
                self.assertEqual(code, 200)
                self.assertTrue(payload["missing"])
                self.assertIn("not available yet", payload["message"])

    def test_ci_log_tail_refuses_a_record_path_outside_its_run_directory(self):
        with tempfile.TemporaryDirectory() as state:
            log_dir = pathlib.Path(state, "ci", "logs", "ci-safe")
            log_dir.mkdir(parents=True)
            outside = pathlib.Path(state, "outside.log")
            outside.write_text("must not leak")
            escaped = log_dir / "backend.log"
            escaped.symlink_to(outside)
            queue = {
                "running": [],
                "queued": [],
                "recent": [
                    {
                        "id": "ci-safe",
                        "tiers": [
                            {"name": "backend", "log": str(escaped)}
                        ],
                    }
                ],
            }
            with (
                mock.patch.object(dashboard, "STATE", state),
                mock.patch.object(dashboard, "ci_queue", return_value=queue),
            ):
                code, payload = dashboard.ci_log_tail("ci-safe", "backend")
                self.assertEqual(code, 403)
                self.assertIn("outside", payload["error"])

                code, payload = dashboard.ci_log_tail(
                    "ci-safe", "../../outside.log"
                )
                self.assertEqual(code, 404)
                self.assertEqual(payload["error"], "CI stage not found")

    def test_ci_log_mode_and_models_routes_do_not_shadow_each_other(self):
        with tempfile.TemporaryDirectory() as state:
            log_dir = pathlib.Path(state, "ci", "logs", "ci-passed")
            log_dir.mkdir(parents=True)
            log_path = log_dir / "backend.log"
            log_path.write_text("backend action output\n")
            sample = {
                "updated": 1784600000,
                "running": [{"id": "ci-running", "state": "running"}],
                "queued": [{"id": "ci-queued", "state": "queued"}],
                "recent": [
                    {
                        "id": "ci-passed",
                        "state": "passed",
                        "tiers": [
                            {"name": "backend", "log": str(log_path)}
                        ],
                    }
                ],
            }
            ci_dir = pathlib.Path(state, "ci")
            ci_dir.joinpath("queue.json").write_text(json.dumps(sample))
            with (
                mock.patch.object(dashboard, "STATE", state),
                mock.patch.object(dashboard.CI, "read_state", return_value=sample),
                mock.patch.object(dashboard.MODE, "status", return_value={"route": "mode"}),
                mock.patch.object(dashboard.MODELS, "listing", return_value=[{"route": "models"}]),
            ):
                server = dashboard.Server(("127.0.0.1", 0), dashboard.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"

                def get(path):
                    with urllib.request.urlopen(base + path) as response:
                        return json.load(response)

                try:
                    self.assertEqual(get("/api/ci"), {**sample, "daemon_alive": False})
                    self.assertEqual(
                        get("/api/ci/log?id=ci-passed&tier=backend"),
                        {
                            "id": "ci-passed",
                            "tier": "backend",
                            "content": "backend action output\n",
                            "missing": False,
                            "truncated": False,
                        },
                    )
                    self.assertEqual(get("/api/mode"), {"route": "mode"})
                    self.assertEqual(get("/api/models"), [{"route": "models"}])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)


    def test_daemon_alive_tracks_the_unit_and_is_not_a_constant(self):
        """Every assertion above would still pass if daemon_alive were hardcoded False."""
        import subprocess

        real = subprocess.run
        try:
            with tempfile.TemporaryDirectory() as state:
                with mock.patch.object(dashboard, "STATE", state):
                    subprocess.run = lambda *a, **k: type(
                        "R", (), {"stdout": "active\n", "returncode": 0}
                    )()
                    self.assertTrue(dashboard.ci_queue()["daemon_alive"])
                    subprocess.run = lambda *a, **k: type(
                        "R", (), {"stdout": "inactive\n", "returncode": 3}
                    )()
                    self.assertFalse(dashboard.ci_queue()["daemon_alive"])
        finally:
            subprocess.run = real


class AccountTroubleTest(unittest.TestCase):
    """What a subscription card is told when the numbers could not be read.

    The rule: one sentence, for a person, naming what to do. Never an exception class, never a
    path off this machine's disk. A card that says FileNotFoundError and prints a directory
    tells the reader nothing, and it tells anyone the screen is shared with where the farm
    keeps its files.
    """

    def setUp(self):
        patcher = mock.patch.object(dashboard.CA, "FARM_ALIAS", "farm")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_missing_login_says_how_to_log_in(self):
        for raw in ["FileNotFoundError: [Errno 2] No such file or directory: "
                    "'/private/tmp/e2e/home/.claude/.credentials.json'",
                    "never read"]:
            self.assertEqual(
                dashboard.account_trouble(raw),
                "This account has no login on the farm yet. Log in once: ssh -t farm claude",
                raw)

    def test_the_alias_is_the_one_the_operator_reaches_this_farm_by(self):
        with mock.patch.object(dashboard.CA, "FARM_ALIAS", "big-box"):
            self.assertIn("ssh -t big-box claude",
                          dashboard.account_trouble("FileNotFoundError: nope"))

    def test_a_refused_login_says_to_log_in_again(self):
        for raw in ["HTTP 401", "HTTP 403", "token expired", "HTTPError: 401 Unauthorized"]:
            self.assertEqual(dashboard.account_trouble(raw),
                             "The login on this account has expired. Log in again.", raw)

    def test_a_vendor_that_did_not_answer_says_so_plainly(self):
        for raw in ["URLError: <urlopen error [Errno 61] Connection refused>",
                    "TimeoutError", "socket.gaierror: name or service not known", "HTTP 503"]:
            self.assertEqual(dashboard.account_trouble(raw),
                             "The vendor did not answer the last time the farm asked.", raw)

    def test_being_told_to_slow_down_is_not_an_error_to_act_on(self):
        self.assertEqual(dashboard.account_trouble("429 rate-limited, 3m to retry"),
                         "The vendor asked the farm to slow down. "
                         "These numbers refresh by themselves.")

    def test_anything_else_is_still_a_sentence_and_never_a_traceback(self):
        raw = "ValueError: could not parse /home/farm/.claude/usage.json line 3"
        self.assertEqual(dashboard.account_trouble(raw), dashboard.ACCOUNT_TROUBLE_UNKNOWN)
        self.assertEqual(dashboard.account_trouble(""), "")
        self.assertEqual(dashboard.account_trouble(None), "")

    def test_no_reason_on_a_card_carries_a_class_name_or_a_path(self):
        rows = [{"name": "farm-one", "stale_error": "FileNotFoundError: [Errno 2] No such file "
                                                    "or directory: '/private/tmp/e2e/home'"},
                {"name": "codex", "stale_error": "HTTP 403"},
                {"name": "farm-two", "session": 42}]
        rows, errors = dashboard.plain_account_trouble(
            rows, {"farm-one": "FileNotFoundError: [Errno 2] '/private/tmp/e2e/home'"})
        written = " ".join([row.get("stale_error") or "" for row in rows] + list(errors.values()))
        for forbidden in ["Error:", "Errno", "/private/", "/home/", "Traceback"]:
            self.assertNotIn(forbidden, written)
        self.assertIn("ssh -t farm claude", rows[0]["stale_error"])
        self.assertEqual(rows[1]["stale_error"],
                         "The login on this account has expired. Log in again.")
        self.assertNotIn("stale_error", rows[2])
        self.assertIn("ssh -t farm claude", errors["farm-one"])


class MachineReadingTest(unittest.TestCase):
    """The machine readings are Linux only, and the page must survive being run anywhere else."""

    def test_the_metrics_route_answers_on_a_machine_with_no_proc(self):
        with tempfile.TemporaryDirectory() as state:
            with mock.patch.object(dashboard.M, "MEMINFO", os.path.join(state, "nope")), \
                 mock.patch.object(dashboard.M, "LOADAVG", os.path.join(state, "nope")), \
                 mock.patch.object(dashboard.M, "STATE", state), \
                 mock.patch.object(dashboard, "STATE", state):
                with running_server() as base:
                    status, body = fetch_json(base, "/api/metrics")
        self.assertEqual(status, 200)
        self.assertIsNone(body["mem"])
        self.assertIsNone(body["load"])
        self.assertTrue(body["capacity"]["can_spawn"])
        self.assertIn(dashboard.M.NO_MACHINE_READING, body["capacity"]["warnings"])


class ChecksOnAChangeTest(unittest.TestCase):
    """What the page is told about the checks on a lane's change.

    The rule these hold to: a check belongs to the farm that ran it, so it keeps the name that
    farm gave it, and a poll that read nothing never replaces what a lane already recorded.
    """

    ROLLUP = [
        {"name": "unit tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "typecheck", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "container image", "status": "IN_PROGRESS", "conclusion": None},
    ]

    def setUp(self):
        dashboard.CI_CACHE.clear()
        self.addCleanup(dashboard.CI_CACHE.clear)

    def test_every_check_keeps_its_own_name_in_the_order_it_was_reported(self):
        self.assertEqual(
            dashboard._ci_parse(self.ROLLUP),
            [{"name": "unit tests", "state": "pass"},
             {"name": "typecheck", "state": "pass"},
             {"name": "container image", "state": "pending"}],
        )

    def test_a_check_is_one_of_five_states_however_the_forge_words_it(self):
        rollup = [
            {"name": "one", "conclusion": "FAILURE"},
            {"name": "two", "conclusion": "TIMED_OUT"},
            {"name": "three", "conclusion": "SKIPPED"},
            {"name": "four", "conclusion": "NEUTRAL"},
            {"context": "legacy/status", "state": "PENDING"},
            {"context": "legacy/other", "state": "ERROR"},
            {"name": "nothing said"},
            {"name": "   "},
            "not a check at all",
        ]
        self.assertEqual(
            dashboard._ci_parse(rollup),
            [{"name": "one", "state": "fail"},
             {"name": "two", "state": "fail"},
             {"name": "three", "state": "skipped"},
             {"name": "four", "state": "pass"},
             {"name": "legacy/status", "state": "pending"},
             {"name": "legacy/other", "state": "fail"},
             {"name": "nothing said", "state": "unknown"}],
        )
        self.assertEqual(dashboard._ci_parse(None), [])

    def _farm(self, state, record):
        path = pathlib.Path(state, "state")
        path.mkdir(parents=True, exist_ok=True)
        (path / (record["slug"] + ".json")).write_text(json.dumps(record))

    def test_a_poll_that_read_nothing_leaves_the_lane_its_own_checks(self):
        record = {"slug": "demo-web-91bd", "project": "demo", "lane": "web", "engine": "claude",
                  "status": "pr_open", "branch": "demo/web", "pr_url": "https://example.invalid/1",
                  "ci": [{"name": "unit tests", "state": "pass"}]}
        with tempfile.TemporaryDirectory() as state:
            self._farm(state, record)
            with mock.patch.object(dashboard, "STATE", state):
                dashboard.CI_CACHE.clear()
                self.assertEqual(dashboard.agents()[0]["ci"],
                                 [{"name": "unit tests", "state": "pass"}])
                self.assertEqual(dashboard.agent_detail("demo-web-91bd")["ci"],
                                 [{"name": "unit tests", "state": "pass"}])
                dashboard.CI_CACHE["demo/web"] = dashboard._ci_parse(self.ROLLUP)
                self.assertEqual([row["name"] for row in dashboard.agents()[0]["ci"]],
                                 ["unit tests", "typecheck", "container image"])

    def test_a_poll_of_a_farm_whose_jobs_have_other_names_is_not_thrown_away(self):
        record = {"slug": "demo-web-91bd", "project": "demo", "lane": "web", "engine": "claude",
                  "status": "pr_open", "branch": "demo/web", "pr_url": "https://example.invalid/1"}
        answer = types.SimpleNamespace(stdout=json.dumps({"statusCheckRollup": self.ROLLUP}))
        with tempfile.TemporaryDirectory() as state:
            self._farm(state, record)
            registry = pathlib.Path(state, "projects.toml")
            registry.write_text(f'[demo]\npath = "{state}"\n')
            with mock.patch.object(dashboard, "STATE", state), \
                 mock.patch.object(dashboard, "CONFIG", state), \
                 mock.patch.object(dashboard.subprocess, "run", return_value=answer):
                dashboard._ci_refresh()
            self.assertEqual(dashboard.CI_CACHE["demo/web"],
                             [{"name": "unit tests", "state": "pass"},
                              {"name": "typecheck", "state": "pass"},
                              {"name": "container image", "state": "pending"}])

    def test_a_failing_poll_keeps_the_last_reading_rather_than_blanking_it(self):
        record = {"slug": "demo-web-91bd", "project": "demo", "lane": "web", "engine": "claude",
                  "status": "pr_open", "branch": "demo/web", "pr_url": "https://example.invalid/1"}
        known = [{"name": "unit tests", "state": "pass"}]
        with tempfile.TemporaryDirectory() as state:
            self._farm(state, record)
            pathlib.Path(state, "projects.toml").write_text(f'[demo]\npath = "{state}"\n')
            with mock.patch.object(dashboard, "STATE", state), \
                 mock.patch.object(dashboard, "CONFIG", state):
                dashboard.CI_CACHE["demo/web"] = list(known)
                with mock.patch.object(dashboard.subprocess, "run",
                                       side_effect=OSError("gh is gone")):
                    dashboard._ci_refresh()
                self.assertEqual(dashboard.CI_CACHE["demo/web"], known)
                empty = types.SimpleNamespace(stdout=json.dumps({"statusCheckRollup": []}))
                with mock.patch.object(dashboard.subprocess, "run", return_value=empty):
                    dashboard._ci_refresh()
                self.assertEqual(dashboard.CI_CACHE["demo/web"], known)


class DashboardStaticTest(unittest.TestCase):
    """The front end is a directory of files, so the name comes from the request. These are the
    checks that stop that from becoming "read any file on the machine"."""

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.static = pathlib.Path(self.root.name, "static")
        self.static.mkdir()
        patcher = mock.patch.object(dashboard, "STATIC", str(self.static))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_front_end_file_type_is_served_as_itself(self):
        # A stylesheet or a module served as text/plain is ignored by the browser with no error
        # anywhere, so the type is the property under test, not just the bytes.
        wanted = {
            "app.js": "text/javascript; charset=utf-8",
            "core/api.js": "text/javascript; charset=utf-8",
            "app.css": "text/css; charset=utf-8",
            "mark.svg": "image/svg+xml",
            "shot.png": "image/png",
            "text.woff2": "font/woff2",
        }
        for name in wanted:
            path = self.static / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"body-of-" + name.encode())
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            for name, ctype in wanted.items():
                status, raw, served = fetch(base, "/static/" + name)
                self.assertEqual(status, 200, name)
                self.assertEqual(raw, b"body-of-" + name.encode(), name)
                self.assertEqual(served, ctype, name)
            self.assertEqual(fetch(base, "/static/missing.js")[0], 404)
            self.assertEqual(fetch(base, "/static/")[0], 404)

    def test_the_static_directory_cannot_be_escaped(self):
        secret = pathlib.Path(self.root.name, "secret.txt")
        secret.write_text("must not leak")
        escape = self.static / "escape.css"
        escape.symlink_to(secret)
        self.assertEqual(dashboard.static_file("../secret.txt")[0], 403)
        self.assertEqual(dashboard.static_file("a/../../secret.txt")[0], 403)
        self.assertEqual(dashboard.static_file("/etc/hostname")[0], 404)
        # A symlink inside the directory is the same escape with none of the punctuation.
        code, body, _ = dashboard.static_file("escape.css")
        self.assertEqual(code, 403)
        self.assertNotIn(b"must not leak", body)
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            # percent-encoded, because a client normalises a literal ".." away before it is sent
            status, raw, _ = fetch(base, "/static/%2e%2e/secret.txt")
            self.assertEqual(status, 403)
            self.assertNotIn(b"must not leak", raw)
            self.assertEqual(fetch(base, "/static/escape.css")[0], 403)

    def test_front_end_files_are_open_like_the_shell_even_on_a_wide_bind(self):
        # The token arrives in the URL of the page these files build. Gating them would mean the
        # page could never be opened at all.
        (self.static / "app.js").write_text("export const hello = 1;\n")
        with mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            self.assertEqual(fetch(base, "/static/app.js")[0], 200)
            self.assertEqual(fetch(base, "/api/identities")[0], 403)


class DashboardConfigTest(unittest.TestCase):
    """What the page reads before it draws anything: its name, and which optional parts of a
    farm this one actually has."""

    def setUp(self):
        blank = {"at": None, "tried": False, "stale_since": None, "error": None,
                 "units": {}, "version": None}
        for target, value in ((dashboard._version_cache, {"value": "abc1234"}),
                              (dashboard._config_snapshot, blank)):
            patcher = mock.patch.dict(target, value, clear=target is not dashboard._version_cache)
            patcher.start()
            self.addCleanup(patcher.stop)

    def refreshed(self):
        dashboard.config_refresh()
        return dashboard.config_payload()

    def test_a_read_before_the_first_pass_costs_nothing_and_says_so(self):
        # The route is open, so anyone who can reach the port could otherwise spend two process
        # spawns per request, with no token and nothing to rate limit them.
        systemctl = 'case "$*" in *LoadState*) echo loaded;; esac\n'
        with fake_tools({"gh": "exit 0\n", "systemctl": systemctl}) as box:
            payload = dashboard.config_payload()
            self.assertTrue(payload["pending"])
            self.assertEqual(payload["version"], "unknown")
            # what costs nothing is still answered truthfully
            self.assertEqual(payload["features"]["forge"], "github")
            self.assertFalse(payload["features"]["slice"])
            self.assertEqual(box.calls.read_text(), "")

    def test_reading_the_config_never_spawns_anything_once_the_pass_has_run(self):
        systemctl = 'case "$*" in *LoadState*) echo loaded;; esac\n'
        with fake_tools({"systemctl": systemctl}) as box:
            dashboard.config_refresh()
            box.calls.write_text("")
            for _ in range(5):
                payload = dashboard.config_payload()
                self.assertFalse(payload["pending"])
                self.assertTrue(payload["features"]["slice"])
            self.assertEqual(box.calls.read_text(), "")

    def test_a_bare_machine_reports_every_optional_part_as_absent(self):
        with fake_tools({}), mock.patch.object(dashboard.M, "NVIDIA", None), \
                mock.patch.object(dashboard.M, "LHM_URL", ""):
            payload = self.refreshed()
        self.assertEqual(payload["title"], "murmur")
        self.assertEqual(payload["version"], "abc1234")
        self.assertEqual(payload["hq_agent"], "dashboard")
        self.assertEqual(payload["features"], {"hq": False, "slice": False, "gpu": False,
                                               "cpu_temp": False, "ci_daemon": False,
                                               "forge": "unknown"})

    def test_a_complete_machine_reports_each_part_it_has(self):
        systemctl = 'case "$*" in *LoadState*) echo loaded;; esac\n'
        with fake_tools({"gh": "exit 0\n", "hq": "exit 0\n", "systemctl": systemctl},
                        env={"FLEET_DASH_TITLE": "acme farm",
                             "FLEET_DASH_HQ_AGENT": "console"}) as box:
            write_hq_config(box)
            with mock.patch.object(dashboard.M, "NVIDIA", "/usr/bin/nvidia-smi"), \
                    mock.patch.object(dashboard.M, "LHM_URL", "http://host:8085/data.json"):
                payload = self.refreshed()
        self.assertEqual(payload["title"], "acme farm")
        self.assertEqual(payload["hq_agent"], "console")
        self.assertEqual(payload["features"], {"hq": True, "slice": True, "gpu": True,
                                               "cpu_temp": True, "ci_daemon": True,
                                               "forge": "github"})

    def test_hq_installed_but_never_pointed_at_an_office_is_not_a_feature(self):
        # The binary alone proves nothing: without a repository every mail route has nowhere
        # to read, and a mail tab that draws itself and stays empty is the defect.
        with fake_tools({"hq": "exit 0\n"}) as box:
            self.assertFalse(dashboard.config_payload()["features"]["hq"])
            write_hq_config(box, "acme/office")
            self.assertTrue(dashboard.config_payload()["features"]["hq"])
            self.assertEqual(dashboard.hq_office(), "acme/office")
            with mock.patch.dict(os.environ, {"HQ_REPO": "other/office"}):
                self.assertEqual(dashboard.hq_office(), "other/office")

    def test_the_config_route_is_open_like_the_shell(self):
        with fake_tools({}) as box, mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            dashboard.config_refresh()
            box.calls.write_text("")
            for _ in range(5):
                status, payload = fetch_json(base, "/api/config")
                self.assertEqual(status, 200)
            self.assertEqual(payload["title"], "murmur")
            self.assertIn("forge", payload["features"])
            self.assertEqual(box.calls.read_text(), "")


class DashboardHealthTest(unittest.TestCase):
    """Whether this machine has what a farm needs. Four states, a reason a person can read, and
    a command that fixes it. Never a traceback."""

    def setUp(self):
        blank = {"at": None, "tried": False, "stale_since": None, "error": None, "checks": []}
        patcher = mock.patch.dict(dashboard._health_snapshot, blank, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self):
        dashboard.health_refresh()
        return {row["id"]: row for row in dashboard.health()["checks"]}

    def test_a_read_before_the_first_pass_says_so_and_runs_nothing(self):
        # The page draws every few seconds. A read that runs a tool is a tool run a thousand
        # times an hour, against the API budget every agent on this machine shares.
        with fake_tools({"gh": "exit 0\n", "hq": "exit 0\n", "systemctl": "echo loaded\n",
                         "loginctl": "echo yes\n"}) as box:
            write_hq_config(box)
            answer = dashboard.health()
            self.assertTrue(answer["pending"])
            self.assertEqual(answer["checks"], [])
            self.assertIsNone(answer["at"])
            self.assertEqual(box.calls.read_text(), "")

    def test_reading_health_never_reaches_the_office_however_often_it_is_read(self):
        with fake_tools({"gh": "exit 0\n", "hq": "exit 0\n", "systemctl": "echo loaded\n",
                         "loginctl": "echo yes\n"}) as box:
            write_hq_config(box)
            dashboard.health_refresh()
            box.calls.write_text("")
            for _ in range(5):
                answer = dashboard.health()
                self.assertFalse(answer["pending"])
                self.assertEqual(answer["checks"][0]["id"], "gh")
                self.assertTrue(answer["at"].endswith("Z"))
            self.assertEqual(box.calls.read_text(), "")

    def test_a_bare_machine_names_what_is_missing_and_how_to_get_it(self):
        with fake_tools({}), mock.patch.object(dashboard.M, "NVIDIA", None), \
                mock.patch.object(dashboard.M, "LHM_URL", ""):
            rows = self.rows()
        self.assertEqual(set(rows), {"gh", "tmux", "systemd_user", "linger", "hq", "claude",
                                     "codex", "gpu_sensor", "cpu_temp_sensor", "ci_daemon",
                                     "sweep_timer", "office"})
        for row in rows.values():
            self.assertIn(row["state"], ("ok", "missing", "error", "off"), row)
            self.assertTrue(row["label"], row)
            self.assertNotIn("Traceback", row["detail"])
        self.assertEqual(rows["gh"]["state"], "missing")
        self.assertIn("cli.github.com", rows["gh"]["fix"])
        self.assertEqual(rows["tmux"]["state"], "missing")
        # A machine with no user manager still runs lanes: they live in tmux. Painting that row
        # red said something untrue about what was blocked.
        for name in ("systemd_user", "linger", "ci_daemon"):
            self.assertEqual(rows[name]["state"], "off", name)
            self.assertNotIn("lanes cannot", rows[name]["detail"], name)
        self.assertIn("tmux", rows["systemd_user"]["detail"])
        for word in ("power modes", "CI daemon", "sweep timer"):
            self.assertIn(word, rows["systemd_user"]["detail"], word)
        self.assertEqual(rows["hq"]["state"], "missing")
        # With no engine at all, no lane can run: that is missing, not a choice.
        self.assertEqual(rows["claude"]["state"], "missing")
        self.assertEqual(rows["codex"]["state"], "missing")
        # The two sensors are optional by design, so their absence is a choice, not a fault.
        self.assertEqual(rows["gpu_sensor"]["state"], "off")
        self.assertEqual(rows["cpu_temp_sensor"]["state"], "off")
        self.assertIn("FLEET_NVIDIA_SMI", rows["gpu_sensor"]["fix"])
        self.assertEqual(rows["office"]["state"], "off")

    def test_one_installed_engine_makes_the_other_a_choice_not_a_fault(self):
        with fake_tools({"claude": "exit 0\n"}):
            rows = self.rows()
        self.assertEqual(rows["claude"]["state"], "ok")
        self.assertEqual(rows["codex"]["state"], "off")

    def test_a_healthy_machine_reports_ok_with_what_it_found(self):
        systemctl = '''case "$2" in
  is-system-running) echo running;;
  is-active) echo active;;
  show) case "$*" in *LoadState*) echo loaded;; *UnitFileState*) echo "UnitFileState=enabled";; esac;;
esac
'''
        with fake_tools({"gh": "exit 0\n", "tmux": "exit 0\n", "hq": "exit 0\n",
                         "claude": "exit 0\n", "codex": "exit 0\n",
                         "loginctl": "echo yes\n", "systemctl": systemctl}) as box:
            write_hq_config(box)
            with mock.patch.object(dashboard.M, "NVIDIA", str(box.bin / "gh")), \
                    mock.patch.object(dashboard.M, "LHM_URL", "http://host:8085/data.json"):
                rows = self.rows()
            self.assertNotIn("inbox", box.calls.read_text())
        for name in ("gh", "tmux", "systemd_user", "linger", "hq", "claude", "codex",
                     "gpu_sensor", "cpu_temp_sensor", "ci_daemon", "office"):
            self.assertEqual(rows[name]["state"], "ok", f"{name}: {rows[name]}")
            self.assertEqual(rows[name]["fix"], "", name)
        self.assertIn("acme/office", rows["office"]["detail"])

    def test_an_office_that_does_not_answer_is_an_error_with_what_it_said(self):
        with fake_tools({"gh": 'echo "could not resolve host" >&2\nexit 1\n',
                         "hq": "exit 0\n"}) as box:
            write_hq_config(box)
            rows = self.rows()
        self.assertEqual(rows["office"]["state"], "error")
        self.assertIn("could not resolve host", rows["office"]["detail"])
        self.assertIn("gh auth status", rows["office"]["fix"])

    def test_a_check_that_throws_becomes_one_error_row_not_a_broken_page(self):
        # Eleven working rows must survive the twelfth, and the message a person sees is the
        # exception's text, never a stack trace.
        def boom():
            raise RuntimeError("the sensor exploded")

        table = tuple((identifier, label, boom if identifier == "gh" else check)
                      for identifier, label, check in dashboard.HEALTH_CHECKS)
        with fake_tools({}), mock.patch.object(dashboard, "HEALTH_CHECKS", table):
            rows = self.rows()
        self.assertEqual(rows["gh"]["state"], "error")
        self.assertEqual(rows["gh"]["detail"], "RuntimeError: the sensor exploded")
        self.assertEqual(len(rows), 12)

    def test_a_hung_tool_is_a_failed_check_not_a_hung_page(self):
        hang = f"#!{sys.executable}\nimport time\ntime.sleep(30)\n"
        with fake_tools({"loginctl": hang}), \
                mock.patch.object(dashboard, "TOOL_TIMEOUT", 1):
            started = time.monotonic()
            rows = self.rows()
            self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(rows["linger"]["state"], "error")
        self.assertIn("did not answer", rows["linger"]["detail"])

    def test_the_health_route_is_behind_the_read_gate_and_serves_the_snapshot(self):
        with fake_tools({}) as box, mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            dashboard.health_refresh()
            box.calls.write_text("")
            self.assertEqual(fetch(base, "/api/health")[0], 403)
            status, payload = fetch_json(base, "/api/health", token="s3cret")
            self.assertEqual(status, 200)
            self.assertEqual(payload["checks"][0]["id"], "gh")
            self.assertEqual(box.calls.read_text(), "")

class DashboardProjectsTest(unittest.TestCase):
    """Which repositories this farm serves, plus the two live facts next to each: lanes open
    now, and when the project last did anything."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = pathlib.Path(self.tmp.name, "config")
        self.state = pathlib.Path(self.tmp.name, "state")
        (self.state / "state").mkdir(parents=True)
        self.config.mkdir()
        for target, value in (("CONFIG", str(self.config)), ("STATE", str(self.state))):
            patcher = mock.patch.object(dashboard, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def registry(self, text):
        (self.config / "projects.toml").write_text(text)

    def lane(self, slug, project, status):
        (self.state / "state" / (slug + ".json")).write_text(
            json.dumps({"slug": slug, "project": project, "status": status}))

    def test_no_registry_is_an_empty_list_not_an_error(self):
        self.assertEqual(dashboard.projects(), [])

    def test_a_project_carries_its_ports_branch_and_live_lane_count(self):
        self.registry(
            '[alpha]\n'
            'repo = "acme/alpha"\n'
            'path = "~/work/alpha"\n'
            'branch = "trunk"\n'
            'port_base = 5400\n'
            '\n'
            '[beta]\n'
            'repo = "acme/beta"\n'
            'path = "/srv/beta"\n'
            '\n'
            '[beta.ports]\n'
            'vite_base = 5600\n'
            'api_base = 8600\n'
            'e2e_base = 6600\n')
        self.lane("alpha-1", "alpha", "running")
        self.lane("alpha-2", "alpha", "pr_open")      # waiting on a person is still in flight
        self.lane("alpha-3", "alpha", "failed")       # stopped for good
        self.lane("beta-1", "beta", "done")
        rows = {row["name"]: row for row in dashboard.projects()}
        self.assertEqual(list(rows), ["alpha", "beta"])
        self.assertEqual(rows["alpha"]["repo"], "acme/alpha")
        self.assertEqual(rows["alpha"]["base_branch"], "trunk")
        self.assertEqual(rows["alpha"]["path"], os.path.expanduser("~/work/alpha"))
        self.assertEqual(rows["alpha"]["ports"], {"web": 5400, "api": 8100, "e2e": 6100})
        self.assertEqual(rows["alpha"]["lanes_open"], 2)
        self.assertEqual(rows["beta"]["ports"], {"web": 5600, "api": 8600, "e2e": 6600})
        self.assertEqual(rows["beta"]["base_branch"], "main")
        self.assertEqual(rows["beta"]["lanes_open"], 0)
        newest = int(os.path.getmtime(self.state / "state" / "alpha-3.json"))
        self.assertEqual(rows["alpha"]["last_activity"], newest)
        self.assertIsNotNone(rows["beta"]["last_activity"])

    def test_an_unparseable_registry_does_not_break_the_page(self):
        self.registry("[alpha\nrepo = ")
        self.assertEqual(dashboard.projects(), [])

    def test_adding_a_project_runs_the_cli_and_returns_the_new_row(self):
        registry = self.config / "projects.toml"
        with fake_tools({"fleet": FLEET_FAKE},
                        env={"FLEET_FAKE_REGISTRY": str(registry)}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.add_project({"name": "gamma", "repo": "acme/gamma",
                                                         "port_base": 5800})
            recorded = box.calls.read_text()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["name"], "gamma")
        self.assertEqual(payload["repo"], "acme/gamma")
        self.assertEqual(payload["lanes_open"], 0)
        self.assertIn("add-project --name gamma --repo acme/gamma --port-base 5800", recorded)
        # what fleet's own option loop made of it, not just what was typed at it
        self.assertIn('fleet-parsed add-project {"branch": "main", "name": "gamma", '
                      '"port_base": "5800", "repo": "acme/gamma"}', recorded)

    def test_a_refused_registration_is_a_400_carrying_what_the_cli_said(self):
        with fake_tools({"fleet": FLEET_FAKE},
                        env={"FLEET_FAKE_FAIL": "already registered with different settings"}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.add_project({"name": "gamma", "repo": "acme/gamma"})
        self.assertEqual(status, 400)
        self.assertIn("already registered", payload["error"])

    def test_a_bad_name_or_repository_never_reaches_the_cli(self):
        with fake_tools({"fleet": FLEET_FAKE}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                for body in ({"name": "../etc", "repo": "acme/x"},
                             {"name": "ok", "repo": "not-a-repo"},
                             {"name": "", "repo": "acme/x"},
                             # neither side of a repository may start with a dot or a dash
                             {"name": "ok", "repo": "../.."},
                             {"name": "ok", "repo": "-x/-y"},
                             {"name": "ok", "repo": "acme/../etc"},
                             {"name": "ok", "repo": "acme/x", "port_base": "soon"},
                             # and a port block has to be one a lane can be handed
                             {"name": "ok", "repo": "acme/x", "port_base": -1},
                             {"name": "ok", "repo": "acme/x", "port_base": 80},
                             {"name": "ok", "repo": "acme/x", "port_base": 70000}):
                    status, payload = dashboard.add_project(body)
                    self.assertEqual(status, 400, body)
                    self.assertIn("error", payload)
            self.assertEqual(box.calls.read_text(), "")

    def test_the_routes_sit_on_the_right_side_of_the_read_and_write_gates(self):
        self.registry('[alpha]\nrepo = "acme/alpha"\n')
        with mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard, "add_project") as adder, running_server() as base:
            self.assertEqual(fetch(base, "/api/projects")[0], 403)
            status, payload = fetch_json(base, "/api/projects", token="s3cret")
            self.assertEqual(status, 200)
            self.assertEqual([row["name"] for row in payload], ["alpha"])
            self.assertEqual(fetch(base, "/api/projects", method="POST",
                                   body={"name": "gamma", "repo": "acme/gamma"})[0], 403)
            adder.assert_not_called()
            adder.return_value = (200, {"name": "gamma"})
            status, payload = fetch_json(base, "/api/projects", token="s3cret", method="POST",
                                         body={"name": "gamma", "repo": "acme/gamma"})
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"name": "gamma"})
            adder.assert_called_once_with({"name": "gamma", "repo": "acme/gamma"})

class DashboardAgentLogTest(unittest.TestCase):
    """What one lane has been doing, read from the engine's own stream. The stream is machine
    shaped; the drawer is not."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        (self.state / "logs").mkdir()
        patcher = mock.patch.object(dashboard, "STATE", str(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, *events):
        path = self.state / "logs" / name
        path.write_text("".join(
            (event if isinstance(event, str) else json.dumps(event)) + "\n"
            for event in events))
        return path

    def test_a_claude_stream_is_read_back_as_the_words_a_person_would_have_seen(self):
        self.write(
            "lane-1.jsonl",
            {"type": "system", "subtype": "init", "model": "claude-opus-5"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading the design record"}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
            {"type": "stream_event", "event": {"type": "content_block_delta",
                                               "delta": {"type": "text_delta", "text": "almost done"}}},
            {"type": "rate_limit_event", "used": 10},
            "this line is not JSON at all",
            {"type": "result", "result": "opened pull request #12"})
        status, payload = dashboard.agent_log("lane-1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["slug"], "lane-1")
        self.assertEqual(payload["file"], "lane-1.jsonl")
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["lines"], [
            "session started on claude-opus-5",
            "Reading the design record",
            "tool: Bash",
            "almost done",
            "[rate_limit_event]",
            "this line is not JSON at all",
            "opened pull request #12",
        ])

    def test_a_plain_text_log_is_served_when_there_is_no_stream(self):
        self.write("lane-2.log", "starting", "done")
        payload = dashboard.agent_log("lane-2")[1]
        self.assertEqual(payload["file"], "lane-2.log")
        self.assertEqual(payload["lines"], ["starting", "done"])

    def test_the_tail_defaults_to_two_hundred_and_is_capped_at_two_thousand(self):
        self.write("lane-3.log", *[f"line {n}" for n in range(3000)])
        default = dashboard.agent_log("lane-3")[1]
        self.assertEqual(len(default["lines"]), 200)
        self.assertEqual(default["lines"][-1], "line 2999")
        self.assertTrue(default["truncated"])
        self.assertEqual(len(dashboard.agent_log("lane-3", "5")[1]["lines"]), 5)
        self.assertEqual(len(dashboard.agent_log("lane-3", "99999")[1]["lines"]), 2000)
        self.assertEqual(len(dashboard.agent_log("lane-3", "soon")[1]["lines"]), 200)
        self.assertEqual(len(dashboard.agent_log("lane-3", "0")[1]["lines"]), 1)

    def test_a_lane_with_no_log_says_so_instead_of_failing(self):
        status, payload = dashboard.agent_log("never-ran")
        self.assertEqual(status, 200)
        self.assertTrue(payload["missing"])
        self.assertEqual(payload["lines"], [])
        self.assertIn("no log yet", payload["message"])

    def test_the_log_directory_cannot_be_escaped(self):
        secret = self.state / "secret.jsonl"
        secret.write_text("must not leak\n")
        for slug in ("../secret", "/etc/hostname", "", "a/b", "..", "-dash"):
            status, payload = dashboard.agent_log(slug)
            self.assertEqual(status, 400, slug)
            self.assertIn("error", payload)
        escape = self.state / "logs" / "escape.jsonl"
        escape.symlink_to(secret)
        status, payload = dashboard.agent_log("escape")
        self.assertEqual(status, 403)
        self.assertNotIn("lines", payload)

    def test_the_route_is_behind_the_read_gate_and_does_not_shadow_the_agent_route(self):
        self.write("lane-4.jsonl", {"type": "result", "result": "finished"})
        (self.state / "state").mkdir()
        (self.state / "state" / "lane-4.json").write_text(
            json.dumps({"slug": "lane-4", "project": "alpha", "status": "done"}))
        with mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            self.assertEqual(fetch(base, "/api/agent/log?slug=lane-4")[0], 403)
            status, payload = fetch_json(base, "/api/agent/log?slug=lane-4&tail=1",
                                         token="s3cret")
            self.assertEqual(status, 200)
            self.assertEqual(payload["lines"], ["finished"])
            detail = fetch_json(base, "/api/agent?slug=lane-4", token="s3cret")[1]
            self.assertEqual(detail["status"], "done")

class DashboardAgentMessageTest(unittest.TestCase):
    """Sending one lane a message. It lands in the lane's inbox through the CLI that owns it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        (self.state / "state").mkdir()
        (self.state / "state" / "lane-1.json").write_text(
            json.dumps({"slug": "lane-1", "project": "alpha", "status": "running"}))
        patcher = mock.patch.object(dashboard, "STATE", str(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_message_to_a_live_lane_reaches_the_cli(self):
        with fake_tools({"fleet": FLEET_FAKE}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.agent_msg({"slug": "lane-1",
                                                       "text": "please rebase on main"})
            recorded = box.calls.read_text()
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertIn("fleet msg lane-1 please rebase on main", recorded)

    def test_a_message_beginning_with_a_dash_reaches_the_lane_whole(self):
        # fleet parses with a case loop rather than an option parser, so the text arrives as
        # itself and no separator is sent, which that loop would take as the lane's name.
        with fake_tools({"fleet": FLEET_FAKE}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                for text in ("-h", "--force", "-- careful"):
                    status, payload = dashboard.agent_msg({"slug": "lane-1", "text": text})
                    self.assertEqual(status, 200, payload)
            recorded = box.calls.read_text()
        for text in ("-h", "--force", "-- careful"):
            self.assertIn('fleet-parsed msg ["lane-1", "%s"]' % text, recorded)

    def test_a_name_that_is_not_a_lane_is_refused_before_the_cli_runs(self):
        with fake_tools({"fleet": FLEET_FAKE}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                for body in ({"slug": "ghost", "text": "hello"},
                             {"slug": "../etc/passwd", "text": "hello"},
                             {"slug": "lane-1", "text": "   "},
                             {"slug": "lane-1", "text": "x" * 9000}):
                    status, payload = dashboard.agent_msg(body)
                    self.assertEqual(status, 400, body)
                    self.assertIn("error", payload)
            self.assertEqual(box.calls.read_text(), "")

    def test_a_failing_cli_is_a_400_carrying_what_it_said(self):
        with fake_tools({"fleet": FLEET_FAKE},
                        env={"FLEET_FAKE_FAIL": "usage: fleet msg <slug>"}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.agent_msg({"slug": "lane-1", "text": "hello"})
        self.assertEqual(status, 400)
        self.assertIn("usage", payload["error"])

    def test_the_route_needs_the_write_token(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard, "agent_msg") as sender, running_server() as base:
            self.assertEqual(fetch(base, "/api/agent/msg", method="POST",
                                   body={"slug": "lane-1", "text": "hi"})[0], 403)
            sender.assert_not_called()
            sender.return_value = (200, {"ok": True})
            status, payload = fetch_json(base, "/api/agent/msg", token="s3cret", method="POST",
                                         body={"slug": "lane-1", "text": "hi"})
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"ok": True})
            sender.assert_called_once_with({"slug": "lane-1", "text": "hi"})

GH_FAKE = '''
emit() { while IFS= read -r line || [ -n "$line" ]; do printf "%s\\n" "$line"; done < "$1"; }
if [ -f "$GH_FAIL" ]; then echo "could not resolve host github.com" >&2; exit 1; fi
case "$1" in
  issue) emit "$GH_DIR/boxes.json";;
  api) url="$2"; n=${url#*issues/}; n=${n%%/*}; emit "$GH_DIR/comments-$n.json";;
  *) exit 1;;
esac
'''

# The fakes below are written in python and parse their command line the way the real tools do,
# because the bugs worth catching here live in that parsing. `hq` is argparse with the same
# positionals as hq/src/hq/cli.py, so a text beginning with a dash is eaten as an option exactly
# as the real one eats it. `fleet` mirrors the hand written case loop in fleet/bin/fleet, so a
# separator the real fleet would take as a lane name shows up as one here. Each records the
# command line it received AND what its parser made of it, so a test can assert the difference.

RECORD = '''
import json, os, sys
def record(line):
    with open(os.environ["TOOL_CALLS"], "a") as handle:
        handle.write(line + "\\n")
record(os.path.basename(sys.argv[0]) + " " + " ".join(sys.argv[1:]))
'''

HQ_FAKE = f'''#!{sys.executable}
{RECORD}
import argparse
parser = argparse.ArgumentParser(prog="hq")
sub = parser.add_subparsers(dest="cmd", required=True)
one = sub.add_parser("msg"); one.add_argument("name"); one.add_argument("text")
two = sub.add_parser("feed"); two.add_argument("--hours", type=float, default=24)
sub.add_parser("who")
sub.add_parser("inbox")
args = parser.parse_args()
if args.cmd == "msg":
    record("hq-parsed msg " + json.dumps([args.name, args.text]))
    print("sent to %s (inbox issue #7) as %s" % (args.name, os.environ.get("HQ_AGENT", "?")))
elif args.cmd == "feed":
    record("hq-parsed feed " + json.dumps(args.hours))
    print("21 Sep 09:14  [mail] winston -> all: the queue is open")
    print("21 Sep 09:20  [claim] claim dash/server by dali")
    print("office was busy")
elif args.cmd == "who":
    print("winston            live  updated  0.3h ago  dashboard work")
    print("dali               STALE updated  9.1h ago  ")
elif args.cmd == "inbox":
    sys.exit("hq inbox must never be called by the dashboard: it consumes an agent's mail")
'''

FLEET_FAKE = f'''#!{sys.executable}
{RECORD}
argv = sys.argv[1:]
command, rest = (argv[0] if argv else ""), argv[1:]
failure = os.environ.get("FLEET_FAKE_FAIL", "")
if failure:
    sys.exit(failure)
if command == "msg":
    # fleet/bin/fleet cmd_msg: slug is "${{1:-}}", the message is "$*" after one shift.
    slug = rest[0] if rest else ""
    record("fleet-parsed msg " + json.dumps([slug, " ".join(rest[1:])]))
    print("queued for " + slug)
elif command == "add-project":
    # fleet/bin/fleet cmd_add_project: a case loop over long options, anything else is fatal.
    fields, pending = {{"branch": "main", "port_base": "5200"}}, list(rest)
    while pending:
        head = pending.pop(0)
        if head in ("--name", "--repo", "--path", "--branch", "--port-base") and pending:
            fields[head.lstrip("-").replace("-", "_")] = pending.pop(0)
        else:
            sys.exit("unknown " + head)
    if not fields.get("name") or not fields.get("repo"):
        sys.exit("need --name and --repo owner/name")
    record("fleet-parsed add-project " + json.dumps(fields, sort_keys=True))
    registry = os.environ.get("FLEET_FAKE_REGISTRY", "")
    if registry:
        with open(registry, "a") as handle:
            handle.write('[%s]\\nrepo = "%s"\\npath = "/srv/%s"\\nbranch = "%s"\\n'
                         % (fields["name"], fields["repo"], fields["name"], fields["branch"]))
    print("registered project '%s'" % fields["name"])
else:
    sys.exit("unknown command " + command)
'''


class DashboardMailTest(unittest.TestCase):
    """The head office, read through gh and never through `hq inbox`: a plain inbox read moves a
    cursor shared by every process signing as one name, so a polling page would eat an agent's
    mail."""

    def setUp(self):
        blank = {"at": None, "tried": False, "stale_since": None, "error": None, "boxes": [],
                 "threads": {}, "seen": {}}
        who = {"at": None, "tried": False, "stale_since": None, "error": None, "sessions": []}
        for target, value in ((dashboard._mail_snapshot, blank),
                              (dashboard._who_snapshot, who),
                              (dashboard._feed_snapshots, {}),
                              (dashboard._health_snapshot,
                               {"at": None, "tried": False, "stale_since": None, "error": None,
                                "checks": []})):
            patcher = mock.patch.dict(target, value, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        windows = mock.patch.object(dashboard, "_feed_windows",
                                    [float(dashboard.MAIL_WINDOW_HOURS)])
        windows.start()
        self.addCleanup(windows.stop)
        dashboard._refresh_wake.clear()
        self.addCleanup(dashboard._refresh_wake.clear)

    @contextlib.contextmanager
    def office(self, boxes=None, comments=None, tools=None):
        """A fake office: gh answers from files on disk, hq answers as the real one prints."""
        now = time.time()
        recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
        older = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 40 * 3600))
        default_boxes = [{"number": 7, "title": "inbox: winston", "updatedAt": recent},
                         {"number": 9, "title": "inbox: all", "updatedAt": recent}]
        default_comments = {
            7: [{"created_at": older,
                 "body": "**from dali** (2026-09-19T08:00:00Z):\nthe old one"},
                {"created_at": recent,
                 "body": "**from rubicon** (2026-09-21T08:00:00Z):\nthe trials lane is green"}],
            9: [{"created_at": recent, "body": "a comment with no sender prefix"}],
        }
        scripts = {"gh": GH_FAKE, "hq": HQ_FAKE}
        scripts.update(tools or {})
        with fake_tools(scripts) as box:
            data = box.root / "gh"
            data.mkdir()
            (data / "boxes.json").write_text(json.dumps(
                default_boxes if boxes is None else boxes) + "\n")
            for number, rows in (default_comments if comments is None else comments).items():
                (data / f"comments-{number}.json").write_text(json.dumps(rows) + "\n")
            write_hq_config(box)
            with mock.patch.dict(os.environ, {"GH_DIR": str(data),
                                              "GH_FAIL": str(box.root / "gh-fail")}):
                box.gh = data
                box.fail = box.root / "gh-fail"
                box.recent = recent
                box.older = older
                yield box

    def test_a_pass_over_the_office_builds_boxes_and_threads_without_touching_hq_inbox(self):
        with self.office() as box:
            dashboard.mail_refresh()
            self.assertNotIn("hq inbox", box.calls.read_text())
            payload = dashboard.mail_boxes()
            self.assertIsNone(payload["stale_since"])
            rows = {row["name"]: row for row in payload["boxes"]}
            self.assertEqual(set(rows), {"winston", "all"})
            self.assertEqual(rows["winston"]["number"], 7)
            # two messages in the box, one of them older than the day the count is about
            self.assertEqual(rows["winston"]["count_24h"], 1)
            # one clock: the forge's stamp, never the sender's own line in the body
            self.assertEqual(rows["winston"]["last_at"], box.recent)
            self.assertEqual(rows["all"]["last_at"], box.recent)
            status, thread = dashboard.mail_thread("winston")
            self.assertEqual(status, 200)
            self.assertEqual(thread["messages"][-1], {
                "sender": "rubicon", "at": "2026-09-21T08:00:00Z",
                "text": "the trials lane is green", "created_at": box.recent})
            # a comment nobody wrote through hq still shows, with its author unknown
            self.assertEqual(dashboard.mail_thread("all")[1]["messages"][0]["sender"], "?")

    def test_a_thread_can_be_asked_for_what_is_new_and_an_unknown_box_is_a_404(self):
        with self.office() as box:
            dashboard.mail_refresh()
            status, thread = dashboard.mail_thread("winston", since=box.older)
            self.assertEqual(status, 200)
            self.assertEqual([message["sender"] for message in thread["messages"]], ["rubicon"])
            status, payload = dashboard.mail_thread("nobody")
            self.assertEqual(status, 404)
            self.assertEqual(payload["boxes"], ["all", "winston"])

    def test_an_office_that_has_never_answered_does_not_deny_a_mailbox(self):
        # An outage must not read as "your mailbox does not exist", which is what a 404 says.
        with self.office() as box:
            box.fail.write_text("")
            dashboard._refresh_once()
            status, payload = dashboard.mail_thread("all")
            self.assertEqual(status, 200)
            self.assertEqual(payload["messages"], [])
            self.assertEqual(payload["box"], "all")
            self.assertIn("could not resolve host", payload["error"])
            self.assertNotIn("no mailbox named", json.dumps(payload))
            # and a send is told to come back, rather than creating a ghost mailbox
            status, payload = dashboard.mail_send({"to": "winston", "text": "hello"})
            self.assertEqual(status, 503)
            self.assertIn("not been read yet", payload["error"])
            self.assertNotIn("hq msg", box.calls.read_text())

    def test_once_the_office_has_answered_an_unknown_mailbox_is_still_a_404(self):
        with self.office():
            dashboard._refresh_once()
            status, payload = dashboard.mail_thread("nobody")
            self.assertEqual(status, 404)
            self.assertEqual(payload["boxes"], ["all", "winston"])
            self.assertEqual(dashboard.mail_thread("")[0], 400)

    def test_a_since_that_is_not_a_timestamp_is_refused_rather_than_ignored(self):
        # Compared as strings, "yesterday" quietly returned an empty thread and "2026" returned
        # everything. Both look like an answer and neither is one.
        with self.office():
            dashboard._refresh_once()
            for bad in ("yesterday", "ZZZ", "2026", "last week", "1789995661"):
                status, payload = dashboard.mail_thread("winston", since=bad)
                self.assertEqual(status, 400, bad)
                self.assertIn("ISO 8601", payload["error"])

    def test_since_is_understood_with_a_zone_letter_or_an_offset(self):
        with self.office() as box:
            dashboard._refresh_once()
            whole = dashboard.mail_thread("winston")[1]["messages"]
            self.assertEqual(len(whole), 2)
            cutoff = dashboard.parse_iso(box.older)
            offset_form = cutoff.astimezone(
                datetime.timezone(datetime.timedelta(hours=4))).isoformat()
            for form in (box.older, offset_form, cutoff.strftime("%Y-%m-%dT%H:%M:%S")):
                status, payload = dashboard.mail_thread("winston", since=form)
                self.assertEqual(status, 200, form)
                self.assertEqual([message["sender"] for message in payload["messages"]],
                                 ["rubicon"], form)
            future = dashboard.mail_thread("winston", since="2099-01-01T00:00:00Z")[1]
            self.assertEqual(future["messages"], [])

    def test_a_failed_pass_keeps_the_last_good_answer_and_says_since_when(self):
        with self.office() as box:
            dashboard.mail_refresh()
            good = dashboard.mail_boxes()
            box.fail.write_text("")
            dashboard.mail_refresh()
            stale = dashboard.mail_boxes()
            self.assertEqual([row["name"] for row in stale["boxes"]],
                             [row["name"] for row in good["boxes"]])
            self.assertEqual(stale["stale_since"], good["at"])
            self.assertIn("could not resolve host", stale["error"])

    def test_a_box_nothing_was_written_to_is_not_fetched_again(self):
        # Every agent shares one API budget. Re-reading a mailbox to learn that it has not
        # changed is how a page burns it.
        with self.office() as box:
            dashboard.mail_refresh()
            dashboard.mail_refresh()
            calls = [line for line in box.calls.read_text().splitlines()
                     if line.startswith("gh api")]
            self.assertEqual(len(calls), 2, calls)

    def test_no_mail_read_ever_reaches_the_office_itself(self):
        # The refresher exists so that nothing waits on GitHub to draw, before the first pass
        # as much as after a failed one.
        with self.office() as box:
            for _ in range(3):
                self.assertTrue(dashboard.mail_boxes()["pending"])
            self.assertEqual(box.calls.read_text(), "")
            box.fail.write_text("")
            dashboard._refresh_once()
            box.calls.write_text("")
            for _ in range(3):
                self.assertIsNone(dashboard.mail_boxes()["at"])
            self.assertEqual(box.calls.read_text(), "")

    def test_the_feed_and_the_session_list_are_read_from_the_snapshot_not_run(self):
        # `hq feed` fetches the claims branch and makes several forge calls, so running it to
        # answer a GET would put a disk write and the network on the request path.
        with self.office() as box:
            pending = dashboard.mail_feed("6")
            self.assertTrue(pending["pending"])
            self.assertEqual(pending["events"], [])
            self.assertTrue(dashboard.mail_who()["pending"])
            self.assertEqual(box.calls.read_text(), "")
            self.assertTrue(dashboard._refresh_wake.is_set(),
                            "a window nobody has asked for must wake the refresher")

            dashboard._refresh_once()
            box.calls.write_text("")
            feed = dashboard.mail_feed("6")
            who = dashboard.mail_who()
            self.assertEqual(box.calls.read_text(), "")
            self.assertFalse(feed["pending"])
            self.assertEqual(feed["hours"], 6.0)
            first = feed["events"][0]
            self.assertEqual(first["at_label"], "21 Sep 09:14")
            self.assertEqual(first["kind"], "mail")
            self.assertEqual(first["text"], "winston -> all: the queue is open")
            # a sortable stamp next to hq's label, or the timeline cannot be merged with
            # anything else on the page
            self.assertEqual(dashboard.parse_iso(first["at"]).minute, 14)
            self.assertEqual(feed["events"][1]["kind"], "claim")
            self.assertEqual(feed["events"][2],
                             {"at": None, "at_label": None, "kind": "note",
                              "text": "office was busy"})
            self.assertEqual([session["name"] for session in who["sessions"]],
                             ["winston", "dali"])
            self.assertEqual(who["sessions"][0]["age_hours"], 0.3)
            self.assertEqual(who["sessions"][0]["task"], "dashboard work")
            self.assertEqual(who["sessions"][1]["state"], "stale")

    def test_the_default_window_is_warmed_and_the_tracked_set_stays_bounded(self):
        with self.office():
            dashboard._refresh_once()
            self.assertFalse(dashboard.mail_feed()["pending"])
            for hours in range(1, 20):
                dashboard.mail_feed(str(hours))
            self.assertLessEqual(len(dashboard._feed_windows),
                                 dashboard.FEED_WINDOWS_TRACKED)
            self.assertIn(float(dashboard.MAIL_WINDOW_HOURS), dashboard._feed_windows)

    def test_a_failing_hq_keeps_the_last_feed_and_says_since_when(self):
        with self.office() as box:
            dashboard._refresh_once()
            good = dashboard.mail_feed()
            (box.bin / "hq").write_text("#!/bin/sh\necho 'the office is unreachable' >&2\nexit 1\n")
            dashboard._refresh_once()
            stale = dashboard.mail_feed()
            self.assertEqual(stale["events"], good["events"])
            self.assertEqual(stale["stale_since"], good["at"])
            self.assertIn("unreachable", stale["error"])

    def test_sending_signs_as_the_dashboard_and_only_to_a_real_mailbox(self):
        with self.office() as box:
            with mock.patch.dict(os.environ, {"FLEET_DASH_HQ_AGENT": "console"}):
                dashboard.mail_refresh()
                status, payload = dashboard.mail_send({"to": "winston", "text": "preview is up"})
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["from"], "console")
                self.assertIn("as console", payload["detail"])
                for body in ({"to": "stranger", "text": "hello"},
                             {"to": "winston", "text": " "},
                             {"to": "", "text": "hello"}):
                    self.assertEqual(dashboard.mail_send(body)[0], 400, body)
                # "all" is a mailbox even though nobody is called all
                self.assertEqual(dashboard.mail_send({"to": "all", "text": "hi"})[0], 200)
            calls = box.calls.read_text()
            self.assertIn("hq msg -- winston preview is up", calls)
            self.assertIn('hq-parsed msg ["winston", "preview is up"]', calls)
            self.assertNotIn("stranger", calls)

    def test_a_message_beginning_with_a_dash_is_delivered_not_swallowed_as_an_option(self):
        # hq reads its two positionals with argparse, which takes a leading dash as an option:
        # "-h" printed the subcommand help and exited 0, so this route answered "sent" for a
        # message nobody received.
        with self.office() as box:
            dashboard._refresh_once()
            for text in ("-h", "--force", "-x"):
                status, payload = dashboard.mail_send({"to": "all", "text": text})
                self.assertEqual(status, 200, payload)
                self.assertTrue(payload["ok"])
            recorded = box.calls.read_text()
            for text in ("-h", "--force", "-x"):
                self.assertIn('hq-parsed msg ["all", "%s"]' % text, recorded)
            self.assertNotIn("usage: hq msg", recorded)

    def test_a_farm_with_no_head_office_says_so_once_on_every_mail_route(self):
        with fake_tools({"gh": "exit 0\n"}) as box:          # no hq at all
            answers = {"boxes": dashboard.mail_boxes(),
                       "thread": dashboard.mail_thread("winston")[1],
                       "feed": dashboard.mail_feed(),
                       "who": dashboard.mail_who(),
                       "send": dashboard.mail_send({"to": "all", "text": "hi"})[1]}
            for route, payload in answers.items():
                # exactly one sentence and one command, so the tab can render it as written
                self.assertEqual(sorted(payload), ["fix", "unavailable"], route)
                self.assertIn("No head office is installed", payload["unavailable"], route)
                self.assertIn("hq init", payload["fix"], route)
            self.assertEqual(dashboard.mail_thread("winston")[0], 200)
            self.assertEqual(dashboard.mail_send({"to": "all", "text": "hi"})[0], 200)
            self.assertEqual(box.calls.read_text(), "")
        with fake_tools({"gh": "exit 0\n", "hq": "exit 0\n"}):    # installed, pointed nowhere
            self.assertIn("hq init", dashboard.mail_boxes()["fix"])
        with fake_tools({"hq": "exit 0\n"}) as box:               # office, but no gh to read it
            write_hq_config(box)
            self.assertIn("gh", dashboard.mail_boxes()["unavailable"])

    def test_the_routes_sit_on_the_right_side_of_the_read_and_write_gates(self):
        with self.office(), mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            dashboard._refresh_once()
            for path in ("/api/mail/boxes", "/api/mail/thread?box=winston",
                         "/api/mail/feed?hours=6", "/api/mail/who"):
                self.assertEqual(fetch(base, path)[0], 403, path)
            status, payload = fetch_json(base, "/api/mail/boxes", token="s3cret")
            self.assertEqual(status, 200)
            self.assertEqual(sorted(row["name"] for row in payload["boxes"]), ["all", "winston"])
            self.assertEqual(fetch_json(base, "/api/mail/thread?box=winston",
                                        token="s3cret")[1]["box"], "winston")
            self.assertEqual(fetch_json(base, "/api/mail/who", token="s3cret")[1]["sessions"][0]
                             ["name"], "winston")
            self.assertEqual(fetch(base, "/api/mail/send", method="POST",
                                   body={"to": "all", "text": "hi"})[0], 403)
            status, payload = fetch_json(base, "/api/mail/send", token="s3cret", method="POST",
                                         body={"to": "all", "text": "hi"})
            self.assertEqual(status, 200, payload)
            self.assertTrue(payload["ok"])

class LibraryIsNotOneFarmTest(unittest.TestCase):
    """Nothing in the library may name one machine, one home directory or one palette."""

    @contextlib.contextmanager
    def identity_config(self, policy=None):
        with tempfile.TemporaryDirectory() as config:
            if policy is not None:
                pathlib.Path(config, "policy.toml").write_text(policy)
            with mock.patch.object(dashboard.ID, "CONFIG", config), \
                    mock.patch.object(dashboard.ID, "REG",
                                      str(pathlib.Path(config, "codenames.json"))), \
                    mock.patch.dict(dashboard.ID._marks_cache, {"key": None, "value": None}):
                yield config

    def test_the_marks_are_the_shipped_ones_until_a_policy_says_otherwise(self):
        with self.identity_config():
            glyphs, colours = dashboard.ID.marks()
        self.assertEqual(glyphs, dashboard.ID.DEFAULT_GLYPHS)
        self.assertEqual(colours, dashboard.ID.DEFAULT_COLOURS)

    def test_a_deployment_can_bring_its_own_glyphs_and_colours(self):
        policy = ('[identity]\n'
                  'glyphs  = ["A", "B"]\n'
                  'colours = ["#111111"]\n')
        with self.identity_config(policy):
            self.assertEqual(dashboard.ID.marks(), (["A", "B"], ["#111111"]))
            icon, colour = dashboard.ID.resolve("vivaldi")
            self.assertIn(icon, ("A", "B"))
            self.assertEqual(colour, "#111111")
            # the registry wins from then on, palette or no palette
            self.assertEqual(dashboard.ID.resolve("vivaldi"), (icon, colour))

    def test_the_american_spelling_is_accepted_and_a_broken_policy_is_not_fatal(self):
        with self.identity_config('[identity]\ncolors = ["#222222"]\n'):
            self.assertEqual(dashboard.ID.marks()[1], ["#222222"])
        with self.identity_config("[identity\nglyphs = "):
            self.assertEqual(dashboard.ID.marks()[0], dashboard.ID.DEFAULT_GLYPHS)

    def test_the_model_catalog_finds_its_own_checkout_rather_than_one_persons_home(self):
        # The checkout may be named anything (fleet, fleet-repo, murmur/fleet): what matters is
        # that FLEET_HOME is the directory holding lib/, not a name under somebody's home.
        expected = os.path.realpath(os.path.join(os.path.dirname(dashboard.MODELS.__file__), ".."))
        self.assertEqual(os.path.realpath(dashboard.MODELS.FLEET_HOME), expected)
        self.assertTrue(os.path.isdir(os.path.join(dashboard.MODELS.FLEET_HOME, "config")))
        self.assertNotIn("work/fleet", dashboard.MODELS.EXAMPLE)
        self.assertTrue(os.path.isfile(dashboard.MODELS.EXAMPLE))

    def test_no_shipped_default_or_example_names_one_farm_s_hardware(self):
        room = pathlib.Path(dashboard.FLEET_HOME)
        text = "\n".join((room / "config" / name).read_text()
                         for name in ("policy.example.toml", "models.example.toml"))
        text += (room / "lib" / "metrics.py").read_text()
        for tell in ("5070", "9800X3D", "Ryzen", "08.08", "QUOTA EXHAUSTED"):
            self.assertNotIn(tell, text, tell)

class RefresherTest(unittest.TestCase):
    """One thread fills everything the page reads, and a request that arrives before it has run
    is told so rather than made to wait for a tool."""

    def test_one_pass_fills_the_health_table(self):
        blank = {"at": None, "tried": False, "stale_since": None, "error": None, "checks": []}
        with mock.patch.dict(dashboard._health_snapshot, blank, clear=True), fake_tools({}):
            self.assertTrue(dashboard.health()["pending"])
            dashboard._refresh_once()
            self.assertFalse(dashboard.health()["pending"])
            self.assertEqual(len(dashboard.health()["checks"]), len(dashboard.HEALTH_CHECKS))

    def test_a_part_that_throws_does_not_cost_the_page_the_other_parts(self):
        blank = {"at": None, "tried": False, "stale_since": None, "error": None, "checks": []}
        with mock.patch.dict(dashboard._health_snapshot, blank, clear=True), \
                mock.patch.object(dashboard, "mail_refresh", side_effect=RuntimeError("boom")), \
                fake_tools({}):
            dashboard._refresh_once()
            self.assertFalse(dashboard.health()["pending"])

    def test_the_refresher_wakes_early_when_a_request_asks_for_something_new(self):
        # Without this a window nobody had asked for would take a whole cadence to appear.
        dashboard._refresh_wake.clear()
        passes = []

        def count():
            passes.append(time.monotonic())

        with mock.patch.object(dashboard, "_refresh_once", count):
            thread = threading.Thread(target=dashboard._refresher, args=(30,), daemon=True)
            thread.start()
            for _ in range(200):
                if passes:
                    break
                time.sleep(0.01)
            dashboard._refresh_wake.set()
            for _ in range(200):
                if len(passes) > 1:
                    break
                time.sleep(0.01)
        self.assertGreater(len(passes), 1, "a woken refresher must not wait out its sleep")

class ReadsCostNothingTest(unittest.TestCase):
    """The page redraws every few seconds. Every read this lane added must therefore be pure
    memory and files: one tool call on a read path is a few thousand an hour, against the API
    budget every agent on this machine shares."""

    # The older panes have their own cadence and their own owners, so they are named here rather
    # than silently included: /api/ci, /api/sweep, /api/mode and /api/metrics each ask the
    # machine something on a read, and changing that is not this lane's to do.
    QUIET_ROUTES = ("/", "/index.html", "/static/app.js", "/api/access", "/api/version",
                    "/api/config", "/api/health", "/api/projects", "/api/identities",
                    "/api/fleet", "/api/agent?slug=lane-1", "/api/agent/log?slug=lane-1",
                    "/api/mail/boxes", "/api/mail/thread?box=winston", "/api/mail/feed?hours=24",
                    "/api/mail/who")

    def test_no_read_route_runs_a_tool_touches_the_network_or_writes_to_disk(self):
        mail = DashboardMailTest("test_the_feed_and_the_session_list_are_read_from_the_snapshot_not_run")
        mail.setUp()
        self.addCleanup(mail.doCleanups)
        with mail.office() as box:
            state = box.root / "state"
            (state / "state").mkdir(parents=True)
            (state / "logs").mkdir()
            (state / "state" / "lane-1.json").write_text(
                json.dumps({"slug": "lane-1", "project": "alpha", "status": "running"}))
            (state / "logs" / "lane-1.jsonl").write_text(
                json.dumps({"type": "result", "result": "done"}) + "\n")
            config = box.root / "fleet-config"
            config.mkdir()
            (config / "projects.toml").write_text('[alpha]\nrepo = "acme/alpha"\n')
            static = box.root / "static"
            static.mkdir()
            (static / "app.js").write_text("export const x = 1;\n")
            blank = {"at": None, "tried": False, "stale_since": None, "error": None,
                     "units": {}, "version": None}
            with mock.patch.object(dashboard, "STATE", str(state)), \
                    mock.patch.object(dashboard, "CONFIG", str(config)), \
                    mock.patch.object(dashboard, "STATIC", str(static)), \
                    mock.patch.object(dashboard.ID, "CONFIG", str(config)), \
                    mock.patch.object(dashboard.ID, "REG", str(config / "codenames.json")), \
                    mock.patch.dict(dashboard._config_snapshot, blank, clear=True), \
                    mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
                dashboard._refresh_once()
                box.calls.write_text("")
                for route in self.QUIET_ROUTES:
                    status, raw, _ = fetch(base, route, token="s3cret")
                    self.assertEqual(status, 200, route)
                    self.assertEqual(box.calls.read_text(), "",
                                     f"{route} spawned a tool: {box.calls.read_text()!r}")

    def test_the_same_holds_before_the_refresher_has_ever_run(self):
        # The first seconds after a start are exactly when a page is opened and read hardest.
        mail = DashboardMailTest("test_the_feed_and_the_session_list_are_read_from_the_snapshot_not_run")
        mail.setUp()
        self.addCleanup(mail.doCleanups)
        with mail.office() as box:
            blank = {"at": None, "tried": False, "stale_since": None, "error": None,
                     "units": {}, "version": None}
            with mock.patch.dict(dashboard._config_snapshot, blank, clear=True), \
                    mock.patch.dict(dashboard._version_cache, {"value": None}), \
                    mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
                for route in ("/api/config", "/api/health", "/api/mail/boxes",
                              "/api/mail/who", "/api/mail/feed?hours=3"):
                    status, payload = fetch_json(base, route, token="s3cret")
                    self.assertEqual(status, 200, route)
                    self.assertTrue(payload["pending"], route)
                self.assertEqual(box.calls.read_text(), "")

class OneClockTest(unittest.TestCase):
    """Every time this server hands out is an ISO 8601 stamp in UTC, so two answers can be
    merged, sorted and compared. Three formats in one tab is three formats to get wrong."""

    def test_a_feed_label_becomes_a_stamp_and_rolls_back_over_the_new_year(self):
        # hq prints "21 Sep 09:14": no year, no zone, unsortable against everything else.
        new_year = time.mktime((2026, 1, 2, 10, 0, 0, 0, 1, -1))
        december = dashboard.feed_iso(time.strftime("%d %b %H:%M",
                                                    time.localtime(new_year - 20 * 86400)),
                                      now=new_year)
        january = dashboard.feed_iso(time.strftime("%d %b %H:%M",
                                                   time.localtime(new_year - 86400)),
                                     now=new_year)
        self.assertTrue(december.startswith("2025-12"), december)
        self.assertTrue(january.startswith("2026-01"), january)
        self.assertIsNone(dashboard.feed_iso("sometime"))
        self.assertIsNone(dashboard.feed_iso(None))

    def test_every_time_a_mail_answer_carries_parses_as_a_timestamp(self):
        mail = DashboardMailTest("test_the_feed_and_the_session_list_are_read_from_the_snapshot_not_run")
        mail.setUp()
        self.addCleanup(mail.doCleanups)
        with mail.office():
            dashboard._refresh_once()
            answers = [dashboard.mail_boxes(), dashboard.mail_thread("winston")[1],
                       dashboard.mail_feed(), dashboard.mail_who()]
            stamps = []
            for answer in answers:
                stamps.append(answer["at"])
                for row in (answer.get("boxes") or []):
                    stamps += [row["last_at"]]
                for row in (answer.get("messages") or []):
                    stamps += [row["at"], row["created_at"]]
                for row in (answer.get("events") or []):
                    stamps += [row["at"]] if row["at"] else []
                for row in (answer.get("sessions") or []):
                    stamps += [row["since"]]
            self.assertGreater(len(stamps), 8)
            for stamp in stamps:
                self.assertIsInstance(stamp, str, stamp)
                self.assertTrue(stamp.endswith("Z"), stamp)
                parsed = dashboard.parse_iso(stamp)
                self.assertIsNotNone(parsed, stamp)
                self.assertEqual(parsed.utcoffset().total_seconds(), 0, stamp)

    def test_a_session_says_when_it_was_last_seen_as_well_as_how_long_ago(self):
        now = 1789996000.0
        sessions = dashboard._parse_who("winston  live  updated  2.0h ago  building\n", now=now)
        self.assertEqual(sessions[0]["age_hours"], 2.0)
        self.assertEqual(sessions[0]["since"], dashboard._iso(now - 7200))

    def test_a_stale_envelope_carries_the_moment_it_stopped_being_true(self):
        mail = DashboardMailTest("test_the_feed_and_the_session_list_are_read_from_the_snapshot_not_run")
        mail.setUp()
        self.addCleanup(mail.doCleanups)
        with mail.office() as box:
            dashboard._refresh_once()
            good = dashboard.mail_boxes()
            box.fail.write_text("")
            dashboard._refresh_once()
            stale = dashboard.mail_boxes()
            self.assertEqual(stale["stale_since"], good["at"])
            self.assertIsNotNone(dashboard.parse_iso(stale["stale_since"]))

class MalformedWriteTest(unittest.TestCase):
    """A write that is wrong gets an answer saying so. do_POST catches only a broken pipe, so a
    body header it could not parse used to raise through the handler and the client was handed
    nothing at all: no status, no body, a closed connection."""

    def send_raw(self, base, path, headers, payload=b""):
        connection = http.client.HTTPConnection(base.rsplit("/", 1)[-1], timeout=10)
        try:
            connection.request("POST", path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"{}")
        finally:
            connection.close()

    def test_a_length_that_is_not_a_number_is_answered_not_dropped(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard, "agent_msg") as handler, running_server() as base:
            head = {"Authorization": "Bearer s3cret", "Content-Type": "application/json"}
            for length in ("abc", "-5", "99999999"):
                status, payload = self.send_raw(base, "/api/agent/msg",
                                                {**head, "Content-Length": length})
                self.assertEqual(status, 400, length)
                self.assertTrue(payload["error"], length)
            handler.assert_not_called()

    def test_a_body_that_is_not_a_json_object_is_answered(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard, "add_project") as handler, running_server() as base:
            handler.return_value = (200, {"name": "gamma"})
            head = {"Authorization": "Bearer s3cret"}
            for raw in (b"{oops", b'"a string"', b"[1, 2]"):
                status, payload = self.send_raw(base, "/api/projects",
                                                {**head, "Content-Length": str(len(raw))}, raw)
                self.assertEqual(status, 400, raw)
                self.assertIn("JSON", payload["error"], raw)
            handler.assert_not_called()

    def test_an_absent_body_is_still_an_empty_object(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard, "add_project",
                                  return_value=(400, {"error": "a repository is owner/name"})) \
                as handler, running_server() as base:
            status, payload = self.send_raw(base, "/api/projects",
                                            {"Authorization": "Bearer s3cret"})
            self.assertEqual(status, 400)
            handler.assert_called_once_with({})

    def test_a_handler_that_raises_still_answers(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard, "agent_msg", side_effect=RuntimeError("boom")), \
                mock.patch.object(dashboard, "projects", side_effect=RuntimeError("boom")), \
                running_server() as base:
            status, payload = fetch_json(base, "/api/agent/msg", token="s3cret", method="POST",
                                         body={"slug": "lane-1", "text": "hi"})
            self.assertEqual(status, 500)
            self.assertNotIn("Traceback", json.dumps(payload))
            self.assertNotIn("boom", json.dumps(payload))
            status, payload = fetch_json(base, "/api/projects", token="s3cret")
            self.assertEqual(status, 500)


class DashboardAccessTest(unittest.TestCase):
    """Who is allowed to change anything. The dashboard can stop an account and flip a model, so
    'it answered 200' is not the property under test here: the 403s are."""

    def _request(self, method, path, token=None, headers=None):
        server = dashboard.Server(("127.0.0.1", 0), dashboard.Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{port}{path}"
            data = b'{"mode":"auto"}' if method == "POST" else None
            request = urllib.request.Request(url, data=data, method=method)
            if token is not None:
                request.add_header("Authorization", "Bearer " + token)
            for name, value in (headers or {}).items():
                request.add_header(name, value)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read() or b"{}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_loopback_without_a_token_cannot_mutate(self):
        # "Loopback is trusted" was never true of a browser: any page the operator opens can POST
        # to 127.0.0.1, and this route stops accounts and flips models.
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", ""), \
                mock.patch.object(dashboard.MODE, "set_setting") as setter:
            status, payload = self._request("GET", "/api/access")
            self.assertEqual(status, 200)
            self.assertFalse(payload["writable"])
            self.assertIn("token", payload["reason"])
            self.assertEqual(self._request("POST", "/api/mode")[0], 403)
            setter.assert_not_called()

    def test_the_token_opens_writing_on_a_loopback_bind(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard.MODE, "set_setting"), \
                mock.patch.object(dashboard.MODE, "tick", return_value={"setting": "auto"}):
            self.assertEqual(self._request("POST", "/api/mode", token="s3cret")[0], 200)
            self.assertTrue(self._request("GET", "/api/access", token="s3cret")[1]["writable"])

    def test_a_wide_bind_without_a_token_is_read_only(self):
        with mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", ""), \
                mock.patch.object(dashboard.MODE, "set_setting") as setter:
            status, payload = self._request("GET", "/api/access")
            self.assertEqual(status, 200)
            self.assertFalse(payload["writable"])
            self.assertEqual(self._request("POST", "/api/mode")[0], 403)
            setter.assert_not_called()

    def test_a_token_is_required_when_one_is_set_and_accepted_when_correct(self):
        with mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard.MODE, "set_setting"), \
                mock.patch.object(dashboard.MODE, "tick", return_value={"setting": "auto"}):
            self.assertEqual(self._request("POST", "/api/mode")[0], 403)
            self.assertEqual(self._request("POST", "/api/mode", token="wrong")[0], 403)
            self.assertEqual(self._request("POST", "/api/mode", token="s3cret")[0], 200)
            self.assertTrue(self._request("GET", "/api/access", token="s3cret")[1]["writable"])

    def test_a_non_ascii_token_is_compared_as_bytes_not_crashed_on(self):
        # hmac.compare_digest raises TypeError on a non-ASCII str: presenting one used to kill the
        # handler mid-response, and a non-ASCII FLEET_DASH_TOKEN broke every write.
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "pa\u00dfwort"), \
                mock.patch.object(dashboard.MODE, "set_setting"), \
                mock.patch.object(dashboard.MODE, "tick", return_value={"setting": "auto"}):
            self.assertEqual(self._request("POST", "/api/mode", token="\u00fc")[0], 403)
            self.assertEqual(self._request("POST", "/api/mode", token="pa\u00dfwort")[0], 200)

    def test_a_cross_site_request_is_refused_even_with_the_token(self):
        # The attacker worth stopping is a page in another tab. It can carry a token it guessed or
        # replayed; it cannot lie about Sec-Fetch-Site or Origin, the browser sets both.
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard.MODE, "set_setting") as setter, \
                mock.patch.object(dashboard.MODE, "tick", return_value={"setting": "auto"}):
            status, payload = self._request("POST", "/api/mode", token="s3cret",
                                            headers={"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(status, 403)
            self.assertIn("cross-site", payload["error"])
            status, payload = self._request("POST", "/api/mode", token="s3cret",
                                            headers={"Origin": "http://evil.example"})
            self.assertEqual(status, 403)
            self.assertIn("cross-origin", payload["error"])
            setter.assert_not_called()
            # the page's own fetch says same-origin, and must keep working
            self.assertEqual(self._request("POST", "/api/mode", token="s3cret",
                                           headers={"Sec-Fetch-Site": "same-origin"})[0], 200)

    def test_reads_are_open_on_loopback_and_gated_once_the_bind_is_wide(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"):
            self.assertEqual(self._request("GET", "/api/identities")[0], 200)
        with mock.patch.object(dashboard, "BIND", "0.0.0.0"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"):
            # /api/agent hands out a lane's whole brief and result; it is not public.
            self.assertEqual(self._request("GET", "/api/agent?slug=x")[0], 403)
            self.assertEqual(self._request("GET", "/api/identities")[0], 403)
            self.assertEqual(self._request("GET", "/api/identities", token="s3cret")[0], 200)
            # but the shell and the access answer stay reachable, or the page could never be
            # opened with its ?token= at all
            self.assertEqual(self._request("GET", "/api/access")[0], 200)
            self.assertEqual(self._request("GET", "/api/version")[0], 200)
            self.assertEqual(self._request("GET", "/api/identities?token=s3cret")[0], 200)

    def test_which_addresses_count_as_loopback(self):
        for value in ("127.0.0.1", "127.0.1.5", "::1", "localhost"):
            self.assertTrue(dashboard.bind_is_loopback(value), value)
        for value in ("0.0.0.0", "::", "", "203.0.113.7", "not-an-address"):
            self.assertFalse(dashboard.bind_is_loopback(value), value)

    def test_an_ipv6_bind_is_actually_served(self):
        # bind_is_loopback() blessing ::1 proved nothing: the socket was AF_INET, so the server
        # died on gaierror at startup and the dashboard read as broken rather than misconfigured.
        # Decide "can this box do IPv6 at all" with a raw socket, NOT by catching the failure
        # under test: skipping on the server's own error would make this check unable to fail.
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM) if socket.has_ipv6 else None
        if probe is None:
            self.skipTest("no IPv6 on this box")
        try:
            probe.bind(("::1", 0))
        except OSError as exc:
            self.skipTest(f"no IPv6 loopback here: {exc}")
        finally:
            probe.close()
        server = dashboard.Server(("::1", 0), dashboard.Handler)
        self.assertEqual(server.address_family, socket.AF_INET6)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(dashboard, "BIND", "::1"):
                with urllib.request.urlopen(f"http://[::1]:{port}/api/version", timeout=5) as r:
                    self.assertEqual(r.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)



class HqBinaryFallbackTest(unittest.TestCase):
    def test_hq_is_found_in_the_users_bin_when_the_service_path_lacks_it(self):
        import shutil as _shutil
        with tempfile.TemporaryDirectory() as home:
            local = os.path.join(home, ".local", "bin")
            os.makedirs(local)
            hq = os.path.join(local, "hq")
            with open(hq, "w") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(hq, 0o755)
            real_which = _shutil.which
            _shutil.which = lambda name, *a, **k: None
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home
            try:
                self.assertEqual(dashboard.hq_binary(), hq)
                os.chmod(hq, 0o644)
                self.assertEqual(dashboard.hq_binary(), "")
            finally:
                _shutil.which = real_which
                if old_home is not None:
                    os.environ["HOME"] = old_home


if __name__ == "__main__":
    unittest.main()

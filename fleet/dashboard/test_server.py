import contextlib
import datetime
import glob
import http.client
import importlib.util
import io
import json
import os
import pathlib
import secrets
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


@contextlib.contextmanager
def snapshot_services(rows):
    """The services snapshot holding exactly these rows, for a test that is about what a route
    reads rather than about what the refresher found."""
    with mock.patch.dict(dashboard._services_snapshot,
                         {"at": "2026-09-22T08:00:00Z", "tried": True, "stale_since": None,
                          "error": None, "services": rows}, clear=True):
        yield


@contextlib.contextmanager
def blank_machine_snapshot():
    """The live-numbers snapshot as it is before the first pass."""
    with mock.patch.dict(dashboard._machine_snapshot,
                         {"at": None, "tried": False, "stale_since": None, "error": None,
                          "metrics": {}, "mode": {}, "sweep": {}}, clear=True):
        yield


class RecordingEvent(threading.Event):
    """An event that counts its wakes. A test cannot simply read `is_set`: another suite leaves a
    real refresher running, and that thread clears whatever event it finds whenever it pleases."""

    def __init__(self):
        super().__init__()
        self.wakes = 0

    def set(self):
        self.wakes += 1
        super().set()


@contextlib.contextmanager
def machine_snapshot(**parts):
    """The live-numbers snapshot holding exactly these readings."""
    payload = {"at": "2026-09-22T08:00:00Z", "tried": True, "stale_since": None, "error": None,
               "metrics": {}, "mode": {}, "sweep": {}}
    payload.update(parts)
    with mock.patch.dict(dashboard._machine_snapshot, payload, clear=True):
        yield


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
        # These fixtures must not ask this machine's user manager anything: every tool call
        # answers "inactive", whatever is really running here.
        patcher = mock.patch.object(
            dashboard.subprocess,
            "run",
            return_value=mock.Mock(stdout="inactive\n", returncode=3),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

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
        # the network itself: a dashboard that blocks on the vendor to draw is a dashboard that
        # hangs. Shape is pinned so the tiles cannot silently lose fields, and the
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

    def test_the_mode_and_models_routes_do_not_shadow_each_other(self):
        """Both are prefix-matched, and /api/models starts with /api/mode: route order is
        observable, so each answers with its own payload here."""
        with tempfile.TemporaryDirectory() as state:
            with (
                mock.patch.object(dashboard, "STATE", state),
                mock.patch.object(dashboard.MODELS, "listing", return_value=[{"route": "models"}]),
                machine_snapshot(mode={"route": "mode"}),
            ):
                server = dashboard.Server(("127.0.0.1", 0), dashboard.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"

                def get(path):
                    with urllib.request.urlopen(base + path) as response:
                        return json.load(response)

                try:
                    self.assertEqual(get("/api/mode"),
                                     {"route": "mode", "at": "2026-09-22T08:00:00Z",
                                      "stale_since": None, "error": None, "pending": False})
                    self.assertEqual(get("/api/models"), [{"route": "models"}])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)


class StreamTextTest(unittest.TestCase):
    """What a lane's log shows for one event of its stream."""

    def test_a_generic_engine_shows_its_words_not_its_event_type(self):
        # A streaming-json CLI may keep the words under "data"; the log used to print
        # "[text]" for every one of them.
        self.assertEqual(dashboard._stream_text({"type": "text", "data": "Opened the pull request"}),
                         "Opened the pull request")

    def test_an_error_event_shows_its_sentence(self):
        self.assertEqual(dashboard._stream_text({"type": "error", "message": "unknown model id"}),
                         "error: unknown model id")

    def test_a_claude_event_reads_as_before(self):
        event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading"}]}}
        self.assertEqual(dashboard._stream_text(event), "Reading")
        self.assertEqual(dashboard._stream_text({"type": "result", "result": "Done"}), "Done")


class PageBuildTest(unittest.TestCase):
    """The build number a tab compares with the one it was loaded from.

    The page shell's own date alone is not enough: a deploy that changed nothing but a script
    would keep the old number, and a tab opened before that deploy would never learn it was
    running old code.
    """

    def test_a_changed_script_changes_the_build(self):
        with tempfile.TemporaryDirectory() as root:
            index = os.path.join(root, "index.html")
            static = os.path.join(root, "static")
            os.makedirs(os.path.join(static, "views"))
            script = os.path.join(static, "views", "board.js")
            for path in (index, script):
                with open(path, "w") as handle:
                    handle.write("x")
                os.utime(path, (1_000_000, 1_000_000))
            with mock.patch.object(dashboard, "INDEX", index), mock.patch.object(dashboard, "STATIC", static):
                before = dashboard.page_build()
                os.utime(script, (2_000_000, 2_000_000))
                after = dashboard.page_build()
        self.assertEqual(before, "1000000")
        self.assertEqual(after, "2000000")

    def test_the_route_answers_with_it(self):
        with tempfile.TemporaryDirectory() as root:
            index = os.path.join(root, "index.html")
            static = os.path.join(root, "static")
            os.makedirs(static)
            script = os.path.join(static, "app.js")
            for path, when in ((index, 1_000_000), (script, 3_000_000)):
                with open(path, "w") as handle:
                    handle.write("x")
                os.utime(path, (when, when))
            with mock.patch.object(dashboard, "INDEX", index), mock.patch.object(dashboard, "STATIC", static):
                with running_server() as base:
                    with urllib.request.urlopen(f"{base}/api/version", timeout=5) as response:
                        body = json.loads(response.read())
        self.assertEqual(body["v"], "3000000")


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


# What `systemctl --user` really prints, which is not one format but two: a property whose NAME
# carries `USec` is formatted as a timespan, and every other monotonic timestamp is a bare count
# of microseconds since boot. A fake that printed the timespan for both hid the defect that every
# service row said it had never become active.
SYSTEMCTL_FAKE = """
unit="$3"
case "$2" in
  is-active)
    case "$unit" in
      fleet-daemon.service) echo active; exit 0;;
      fleet-sweep.timer) echo failed; exit 3;;
    esac
    echo unknown; exit 3;;
  show)
    echo "LoadState=loaded"
    echo "ActiveEnterTimestampMonotonic=${FAKE_ACTIVE_ENTER_US:-586929396}"
    echo "NextElapseUSecMonotonic=1d 1min 17.351398s"
    echo "UnitFileState=enabled"
    echo "Result=success"
    exit 0;;
esac
exit 1
"""


def monotonic_microseconds(ago):
    """CLOCK_MONOTONIC, `ago` seconds back, as systemd would print it.

    Read from the clock rather than hardcoded, so a stamp is never in the future. Under
    `steady_clock` the clock is a fixed large number, so a stamp is never before boot either: on
    a CI runner that booted forty seconds ago, "an hour ago" is before boot, systemd would never
    print it, and the server rightly reads it as never.
    """
    return str(max(0, int((time.clock_gettime(time.CLOCK_MONOTONIC) - ago) * 1e6)))


STEADY_MONOTONIC = 10_000_000.0


@contextlib.contextmanager
def steady_clock():
    """A monotonic clock that reads as if the machine had been up for months, for every stamp a
    test builds and for the server that reads them back, so the answer does not depend on how
    long ago the machine running the suite booted."""
    real = time.clock_gettime

    def read(clock):
        if clock == time.CLOCK_MONOTONIC:
            return STEADY_MONOTONIC
        return real(clock)

    with mock.patch.object(time, "clock_gettime", read):
        yield
# The session this dashboard is asked about is FLEET_DASH_SESSION's to name, so the fake answers
# for whichever one the test points it at. Hardcoding "fleet-dashboard" here meant the suite
# failed the moment anyone used the escape hatch it was written for.
TMUX_FAKE = """
case "$1 $3" in
  "has-session ${FAKE_DASH_SESSION:-fleet-dashboard}") exit 0;;
esac
exit 1
"""


class ServicesTest(unittest.TestCase):
    """The control room's three rows: the agent runner, the sweep timer and this dashboard.
    Every one of them costs a process to read, so the refresher reads them and the route serves
    what it left."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    @contextlib.contextmanager
    def farm(self, scripts=None, **env):
        blank = {"at": None, "tried": False, "stale_since": None, "error": None, "services": []}
        environment = {"FAKE_ACTIVE_ENTER_US": monotonic_microseconds(90),
                       "FAKE_DASH_SESSION": dashboard.DASH_SESSION}
        environment.update(env)
        with fake_tools({"systemctl": SYSTEMCTL_FAKE, "tmux": TMUX_FAKE}
                        if scripts is None else scripts, env=environment) as box:
            with mock.patch.dict(dashboard._services_snapshot, blank, clear=True):
                yield box

    def test_the_three_rows_carry_a_state_a_sentence_and_when_it_last_changed(self):
        with steady_clock(), self.farm() as box:
            dashboard.services_refresh()
            rows = dashboard.services()["services"]
            self.assertIn("systemctl --user is-active fleet-daemon.service",
                          box.calls.read_text())
        self.assertEqual([row["id"] for row in rows],
                         ["agent_runner", "sweep_timer", "dashboard"])
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id["agent_runner"]["state"], "active")
        self.assertEqual(by_id["sweep_timer"]["state"], "failed")
        for row in rows:
            self.assertTrue(row["detail"], row["id"])
            self.assertNotIn("Traceback", row["detail"])
        # one clock: a moment, in UTC, like every other time this server hands out
        since = dashboard.parse_iso(by_id["agent_runner"]["since"])
        self.assertIsNotNone(since)
        # and it says what the fake said: ninety seconds ago, not the epoch and not the future
        ago = time.time() - since.timestamp()
        self.assertTrue(80 < ago < 130, f"{by_id['agent_runner']['since']} is {ago}s ago")

    def test_a_monotonic_stamp_is_read_in_both_the_formats_systemd_prints(self):
        """systemd formats a property as a timespan only when its name carries `USec`.
        ActiveEnterTimestampMonotonic does not, so it arrives as raw microseconds; reading that
        as a timespan found no units in it, answered zero, and every row said `since: null`."""
        self.assertEqual(dashboard._systemd_monotonic("586929396"), 586.929396)
        self.assertEqual(dashboard._systemd_monotonic("1d 1min 17.351398s"), 86477.351398)
        self.assertEqual(dashboard._systemd_monotonic("0"), 0.0)
        self.assertEqual(dashboard._systemd_monotonic(""), 0.0)
        self.assertEqual(dashboard._systemd_monotonic(None), 0.0)
        with steady_clock():
            facts = {"LoadState": "loaded",
                     "ActiveEnterTimestampMonotonic": monotonic_microseconds(3600)}
            since = dashboard.parse_iso(dashboard._unit_since(facts))
        self.assertIsNotNone(since, "a real systemd stamp must not read as never")
        self.assertAlmostEqual(time.time() - since.timestamp(), 3600, delta=30)
        # a unit that has never been active prints a zero, and that is not a moment
        self.assertIsNone(dashboard._unit_since({"ActiveEnterTimestampMonotonic": "0"}))

    def test_every_fix_on_a_row_is_a_command_that_does_what_the_row_asks(self):
        """`fleet autosweep` takes on|off|status. A fix built as "<verb> start" sent the reader
        to `fleet autosweep start`, which prints the status and changes nothing."""
        # in this fixture the sweep timer has failed, which puts a command in front of the
        # reader
        expected = {"sweep_timer": "fleet autosweep on"}
        with self.farm():
            dashboard.services_refresh()
            rows = {row["id"]: row for row in dashboard.services()["services"]}
        for identifier, command in expected.items():
            self.assertNotEqual(rows[identifier]["state"], "active", identifier)
            self.assertEqual(rows[identifier]["fix"], command, identifier)
        # a row that is doing its work asks for nothing
        self.assertEqual(rows["agent_runner"]["state"], "active")
        self.assertEqual(rows["agent_runner"]["fix"], "")
        # and the press that the row's own button sends is the same command
        for spec in dashboard.SERVICE_UNITS:
            self.assertEqual(spec["fix"], "fleet " + " ".join(spec["start"]), spec["id"])

    def test_a_service_that_is_not_installed_still_names_the_command_that_installs_it(self):
        absent = """
unit="$3"
case "$2" in
  is-active) echo inactive; exit 3;;
  show) echo "LoadState=not-found"; exit 0;;
esac
exit 1
"""
        with self.farm({"systemctl": absent, "tmux": TMUX_FAKE}):
            dashboard.services_refresh()
            rows = {row["id"]: row for row in dashboard.services()["services"]}
        self.assertEqual(rows["sweep_timer"]["state"], "absent")
        self.assertEqual(rows["sweep_timer"]["fix"], "fleet autosweep on")

    def test_the_dashboard_row_is_read_only_and_names_the_restart_command(self):
        with self.farm():
            dashboard.services_refresh()
            row = dashboard.service_row("dashboard")
        self.assertTrue(row["read_only"])
        self.assertEqual(row["actions"], [])
        self.assertIn("fleet dashboard restart", row["refusal"])
        self.assertIn(dashboard.DASH_SESSION, row["detail"])

    def test_the_dashboard_row_follows_the_session_this_suite_was_given(self):
        """FLEET_DASH_SESSION exists so a suite can drive a dashboard of its own without reading
        the farm's. Asserting the literal "fleet-dashboard" made this the one escape hatch that
        failed on being used."""
        session = "fake-dash-" + secrets.token_hex(3)
        with mock.patch.object(dashboard, "DASH_SESSION", session):
            with self.farm() as box:
                dashboard.services_refresh()
                row = dashboard.service_row("dashboard")
                self.assertIn(f"tmux has-session -t {session}", box.calls.read_text())
        self.assertIn(session, row["detail"])
        self.assertNotIn("fleet-dashboard", row["detail"])

    def test_a_machine_with_no_user_manager_says_so_instead_of_failing(self):
        with self.farm({"tmux": TMUX_FAKE}):
            dashboard.services_refresh()
            rows = dashboard.services()["services"]
        for row in rows[:2]:
            self.assertEqual(row["state"], "absent", row["id"])
            self.assertEqual(row["actions"], [], row["id"])
            self.assertIn("systemd user manager", row["detail"])
        self.assertEqual(rows[2]["id"], "dashboard")

    def test_a_row_that_will_not_read_does_not_cost_the_page_the_others(self):
        real = dashboard._unit_row

        def one_bad(spec):
            if spec["id"] == "sweep_timer":
                raise RuntimeError("boom")
            return real(spec)

        with self.farm():
            with mock.patch.object(dashboard, "_unit_row", one_bad):
                dashboard.services_refresh()
            rows = dashboard.services()["services"]
            self.assertEqual(len(rows), 3)
            self.assertEqual(dashboard.service_row("sweep_timer")["state"], "unknown")
            self.assertEqual(dashboard.service_row("agent_runner")["state"], "active")
        self.assertNotIn("Traceback", json.dumps(rows))

    def test_the_route_serves_the_snapshot_and_says_pending_before_the_first_pass(self):
        with self.farm() as box:
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), running_server() as base:
                status, payload = fetch_json(base, "/api/services")
                self.assertEqual(status, 200)
                self.assertTrue(payload["pending"])
                self.assertEqual(payload["services"], [])
                dashboard.services_refresh()
                box.calls.write_text("")
                status, payload = fetch_json(base, "/api/services")
                self.assertEqual(status, 200)
                self.assertFalse(payload["pending"])
                self.assertEqual(len(payload["services"]), 3)
                self.assertEqual(box.calls.read_text(), "",
                                 "reading the services must not ask the machine anything")

    def test_the_listening_socket_is_decoded_from_the_kernel_word_format(self):
        """The format is the kernel's, so it can be read from a file of this test's own: an
        address is little-endian 32 bit words, a port is hex, and 0A is LISTEN. This runs
        anywhere, which the reading of this machine's own sockets below cannot."""
        v4 = self.proc_file(
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt",
            "   0: 0100007F:1EC6 00000000:0000 0A 00000000:00000000 00:00000000 1000 0 1 2",
            "   1: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 1000 0 1 2",
            "   2: 0100007F:1EC7 0100007F:BEEF 01 00000000:00000000 00:00000000 1000 0 1 2")
        v6 = self.proc_file(
            "  sl  local_address                         remote_address                    st",
            "   0: 00000000000000000000000001000000:1F91 00000000000000000000000000000000:0000"
            " 0A 00000000:00000000 00:00000000 1000 0 1 2")
        with mock.patch.object(dashboard, "PROC_TCP_FILES", ((v4, 4), (v6, 16))):
            self.assertEqual(dashboard.listening_socket(7878), "127.0.0.1:7878")
            self.assertEqual(dashboard.listening_socket(8080), "0.0.0.0:8080")
            self.assertEqual(dashboard.listening_socket(8081), "[::1]:8081")
            # 0x1EC7 is there, but as an established connection and not as a listener
            self.assertEqual(dashboard.listening_socket(7879), "")
            self.assertEqual(dashboard.listening_socket(1), "")
        # a machine that publishes no such file says nothing rather than failing
        with mock.patch.object(dashboard, "PROC_TCP_FILES",
                               ((str(pathlib.Path(self.tmp.name, "nope")), 4),)):
            self.assertEqual(dashboard.listening_socket(7878), "")

    def proc_file(self, *lines):
        path = pathlib.Path(self.tmp.name, "proc-" + secrets.token_hex(3))
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "/proc/net/tcp is published by Linux only")
    def test_the_listening_socket_is_read_from_proc_and_never_from_a_tool(self):
        with self.farm() as box:
            server = dashboard.Server(("127.0.0.1", 0), dashboard.Handler)
            try:
                port = server.server_address[1]
                box.calls.write_text("")
                self.assertTrue(dashboard.listening_socket(port).endswith(f":{port}"))
                self.assertEqual(dashboard.listening_socket(0), "")
                self.assertEqual(box.calls.read_text(), "")
            finally:
                server.server_close()


class ServiceActionTest(unittest.TestCase):
    """Starting and stopping the farm's services from the page. Every one of them is a fleet
    verb, with the words this server chose, and the dashboard's own row refuses."""

    @contextlib.contextmanager
    def farm(self, **env):
        with fake_tools({"fleet": FLEET_FAKE}, env=env or None) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                yield box

    def test_each_service_maps_to_the_verb_that_owns_it(self):
        for service, action, expected in (
                ("agent_runner", "start", "fleet daemon start"),
                ("agent_runner", "stop", "fleet daemon stop"),
                ("sweep_timer", "start", "fleet autosweep on"),
                ("sweep_timer", "stop", "fleet autosweep off")):
            with self.farm() as box:
                status, payload = dashboard.service_action({"service": service,
                                                            "action": action})
                recorded = box.calls.read_text()
            self.assertEqual(status, 200, payload)
            self.assertTrue(payload["ok"])
            self.assertIn(expected, recorded)
            # a separator would be read as a word of its own by fleet's case loop
            self.assertNotIn("--", recorded)

    def test_a_restart_is_the_stop_and_then_the_start_in_that_order(self):
        with self.farm() as box:
            status, payload = dashboard.service_action({"service": "agent_runner",
                                                        "action": "restart"})
            recorded = [line for line in box.calls.read_text().splitlines()
                        if line.startswith("fleet-parsed")]
        self.assertEqual(status, 200, payload)
        self.assertEqual(recorded, ['fleet-parsed daemon {"action": "stop"}',
                                    'fleet-parsed daemon {"action": "start"}'])

    def test_the_dashboard_refuses_and_names_the_command_that_does_it(self):
        with self.farm() as box:
            for action in ("start", "stop", "restart"):
                status, payload = dashboard.service_action({"service": "dashboard",
                                                            "action": action})
                self.assertEqual(status, 400)
                self.assertIn("fleet dashboard restart", payload["error"])
            self.assertEqual(box.calls.read_text(), "", "nothing may run for this row")

    def test_an_unknown_service_or_action_never_reaches_the_cli(self):
        with self.farm() as box:
            for body in ({"service": "postgres", "action": "start"},
                         {"service": "agent_runner", "action": "reboot"},
                         {"service": "", "action": ""},
                         {"service": "agent_runner"}):
                status, payload = dashboard.service_action(body)
                self.assertEqual(status, 400, body)
                self.assertNotIn("Traceback", json.dumps(payload))
            self.assertEqual(box.calls.read_text(), "")

    def test_a_refusing_cli_is_a_400_carrying_its_last_line(self):
        with self.farm(FLEET_FAKE_FAIL="Failed to start fleet-daemon.service: Unit not found."):
            status, payload = dashboard.service_action({"service": "agent_runner",
                                                        "action": "start"})
        self.assertEqual(status, 400)
        self.assertIn("Unit not found", payload["error"])
        self.assertNotIn("Traceback", json.dumps(payload))

    def test_the_route_needs_the_write_token_and_wakes_the_refresher(self):
        # a wake of its own: another suite leaves a real refresher running, and that thread
        # clears the shared one whenever it pleases
        wake = RecordingEvent()
        with self.farm():
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                    mock.patch.object(dashboard, "_refresh_wake", wake), \
                    running_server() as base:
                status, payload = fetch_json(base, "/api/services", method="POST",
                                             body={"service": "agent_runner", "action": "start"})
                self.assertEqual(status, 403)
                self.assertIn("token", payload["error"])
                status, payload = fetch_json(base, "/api/services", token="s3cret",
                                             method="POST",
                                             body={"service": "agent_runner", "action": "start"})
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["verb"], "fleet daemon")
                self.assertEqual(wake.wakes, 1,
                                 "the row a page draws next must be the new one")


class JobsTest(unittest.TestCase):
    """A write that can outlast a request answers with a job id and runs on a thread. The record
    is a file, so a reloaded page can still read how it ended."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        patcher = mock.patch.object(dashboard, "STATE", str(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tool(self, body):
        path = self.state / ("tool-" + secrets.token_hex(3))
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return str(path)

    def wait_for(self, job_id, state, seconds=5):
        deadline = time.time() + seconds
        while time.time() < deadline:
            status, record = dashboard.read_job(job_id)
            if status == 200 and record["state"] == state:
                return record
            time.sleep(0.02)
        self.fail(f"job {job_id} never reached {state}: {dashboard.read_job(job_id)}")

    def test_a_job_is_recorded_from_start_to_finish(self):
        status, payload = dashboard.start_job("drain", [self.tool('echo "two lanes salvaged"')],
                                              timeout=5, label="Draining the farm")
        self.assertEqual(status, 202)
        job = payload["job"]
        self.assertEqual(job["state"], "running")
        self.assertIsNotNone(dashboard.parse_iso(job["started_at"]))
        self.assertIsNone(job["ended_at"])
        done = self.wait_for(job["id"], "done")
        self.assertEqual(done["action"], "drain")
        self.assertEqual(done["exit_code"], 0)
        self.assertIn("two lanes salvaged", done["output"])
        self.assertIsNotNone(dashboard.parse_iso(done["ended_at"]))

    def test_a_job_that_fails_says_so_in_a_sentence_and_never_a_traceback(self):
        status, payload = dashboard.start_job(
            "drain", [self.tool('echo "docker: no such container" >&2\nexit 1')], timeout=5)
        self.assertEqual(status, 202)
        failed = self.wait_for(payload["job"]["id"], "failed")
        self.assertEqual(failed["exit_code"], 1)
        self.assertIn("no such container", failed["error"])
        self.assertNotIn("Traceback", json.dumps(failed))

    def test_a_second_start_of_a_running_action_is_refused_with_the_one_in_flight(self):
        gate = self.state / "gate"
        blocking = self.tool('while [ ! -f "%s" ]; do sleep 0.02; done\n' % gate)
        status, payload = dashboard.start_job("drain", [blocking], timeout=10)
        self.assertEqual(status, 202)
        running = payload["job"]["id"]
        status, refusal = dashboard.start_job("drain", [blocking], timeout=10,
                                              label="Draining the farm")
        self.assertEqual(status, 409)
        self.assertIn("already running", refusal["error"])
        self.assertEqual(refusal["job"]["id"], running)
        # a job holding a different resource is not blocked by it
        status, other = dashboard.start_job("add_project", [self.tool("true")], timeout=5)
        self.assertEqual(status, 202)
        self.assertIn(running, [record["id"] for record in dashboard.running_jobs()])
        gate.write_text("go")
        # both, and by name: waiting only for the drain left the quick one racing the last
        # assertion, which is a test that passes on a fast machine and fails on a slow one
        self.wait_for(running, "done")
        self.wait_for(other["job"]["id"], "done")
        self.assertEqual(dashboard.running_jobs(), [])

    def test_the_routes_serve_the_records_and_refuse_a_name_that_is_not_one(self):
        status, payload = dashboard.start_job("add_project", [self.tool("echo registered")],
                                              timeout=5)
        job_id = payload["job"]["id"]
        self.wait_for(job_id, "done")
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            status, payload = fetch_json(base, "/api/jobs/" + job_id, token="s3cret")
            self.assertEqual(status, 200)
            self.assertEqual(payload["state"], "done")
            self.assertEqual(fetch_json(base, "/api/jobs", token="s3cret")[1], {"jobs": []})
            self.assertEqual(fetch_json(base, "/api/jobs/ghost", token="s3cret")[0], 404)
            self.assertEqual(
                fetch_json(base, "/api/jobs/..%2f..%2fetc%2fpasswd", token="s3cret")[0], 400)

    def test_a_job_left_by_a_dashboard_that_is_gone_is_not_still_running(self):
        (self.state / "jobs").mkdir()
        (self.state / "jobs" / "drain-1.json").write_text(json.dumps(
            {"id": "drain-1", "action": "drain", "state": "running",
             "started_at": "2026-09-22T08:00:00Z", "ended_at": None, "output": "",
             "pid": 2 ** 22 - 1}))
        status, record = dashboard.read_job("drain-1")
        self.assertEqual(status, 200)
        self.assertEqual(record["state"], "failed")
        self.assertIn("the dashboard stopped", record["error"])
        self.assertEqual(dashboard.running_jobs(), [])

    def test_a_job_that_will_not_end_is_ended_by_its_own_timeout(self):
        """Every write names its own timeout, and a job that outlasts it has to end as a
        failure with a sentence: a record left running for ever disables its control for ever."""
        status, payload = dashboard.start_job("drain", [self.tool("sleep 120")], timeout=1)
        self.assertEqual(status, 202)
        failed = self.wait_for(payload["job"]["id"], "failed", seconds=20)
        self.assertEqual(failed["exit_code"], 124)
        self.assertIn("did not answer within 1s", failed["error"])
        self.assertNotIn("Traceback", json.dumps(failed))
        self.assertEqual(dashboard.running_jobs(), [])

    def test_a_finished_record_is_forgotten_after_a_day(self):
        old = self.old_record("drain-old")
        dashboard.start_job("resume", [self.tool("true")], timeout=5)
        self.assertFalse(old.exists())

    def old_record(self, job_id, state="done"):
        path = self.state / "jobs" / (job_id + ".json")
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"id": job_id, "action": "drain", "state": state,
                                    "started_at": "2026-09-01T08:00:00Z", "pid": os.getpid()}))
        os.utime(path, (time.time() - 2 * 24 * 3600,) * 2)
        return path

    def test_the_refresher_forgets_old_records_with_no_next_job_to_do_it(self):
        """On a farm whose last action was a drain, nothing else ever starts, and start_job was
        the only caller: the record sat there for ever against a document that says a day."""
        old = self.old_record("drain-old")
        still_running = self.old_record("drain-running", state="running")
        with contextlib.ExitStack() as stack:
            for name in ("config_refresh", "services_refresh", "health_refresh", "mail_refresh",
                         "who_refresh", "feed_refresh"):
                stack.enter_context(mock.patch.object(dashboard, name, lambda: None))
            dashboard._refresh_once()
        self.assertFalse(old.exists(), "a day old and finished")
        self.assertTrue(still_running.exists(), "and one that is still running is left alone")


class PowerTest(unittest.TestCase):
    """Throttle, drain, resume. Each one says what it will do before it does it, and the drain
    says it by name: the lanes it is about to salvage and stop."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        (self.state / "state").mkdir()
        self.lane("ui-1", "running", restart="until-pr")
        self.lane("server-2", "starting")
        self.lane("docs-3", "merged")           # finished: not a lane a drain would stop
        patcher = mock.patch.object(dashboard, "STATE", str(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)

    def lane(self, slug, status, restart=None):
        record = {"slug": slug, "project": "alpha", "lane": slug, "engine": "claude",
                  "by": "winston", "status": status}
        if restart:
            record["restart"] = restart
        (self.state / "state" / (slug + ".json")).write_text(json.dumps(record))

    @contextlib.contextmanager
    def farm(self, **env):
        with fake_tools({"fleet": FLEET_FAKE}, env=env or None) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                yield box

    def test_the_drain_preview_names_the_lanes_it_will_stop_and_what_is_lost(self):
        status, payload = dashboard.power_preview("drain")
        self.assertEqual(status, 200)
        self.assertEqual([lane["slug"] for lane in payload["lanes"]], ["server-2", "ui-1"])
        self.assertEqual(payload["lane_count"], 2)
        self.assertEqual(payload["lanes"][1]["restart"], "until-pr")
        text = " ".join([payload["sentence"]] + payload["warnings"])
        self.assertIn("agent runner", text)
        self.assertIn("loses", text)

    def test_the_throttle_preview_names_the_caps(self):
        status, payload = dashboard.power_preview("throttle")
        self.assertEqual(status, 200)
        self.assertEqual(payload["lanes"], [])
        self.assertIn("% of the CPU", payload["sentence"])
        self.assertIn("memory", payload["sentence"])

    def test_the_resume_preview_says_the_runner_will_spend_subscription(self):
        payload = dashboard.power_preview("resume")[1]
        self.assertIn("until-pr", payload["sentence"])
        self.assertIn("subscription", payload["sentence"])

    def test_an_action_that_is_not_one_of_the_three_is_refused(self):
        with self.farm() as box:
            for action in ("", "pause", "shutdown", "on"):
                self.assertEqual(dashboard.power_preview(action)[0], 400, action)
                self.assertEqual(dashboard.power_action({"action": action})[0], 400, action)
            self.assertEqual(box.calls.read_text(), "")

    def test_throttling_runs_the_mode_verb_and_answers_at_once(self):
        with self.farm() as box:
            status, payload = dashboard.power_action({"action": "throttle"})
            recorded = box.calls.read_text()
        self.assertEqual(status, 200, payload)
        self.assertIn('fleet-parsed mode {"mode": "balanced"}', recorded)
        self.assertNotIn("game-mode", recorded)
        self.assertEqual(dashboard.running_jobs(), [])

    def test_draining_and_resuming_are_jobs_with_the_game_mode_verb(self):
        with self.farm() as box:
            status, payload = dashboard.power_action({"action": "drain"})
            self.assertEqual(status, 202, payload)
            self.assertEqual(payload["job"]["action"], "drain")
            self.assertEqual([lane["slug"] for lane in payload["lanes"]],
                             ["server-2", "ui-1"])
            self.wait_for(payload["job"]["id"])
            status, payload = dashboard.power_action({"action": "resume"})
            self.assertEqual(status, 202, payload)
            self.wait_for(payload["job"]["id"])
            recorded = box.calls.read_text()
        self.assertIn('fleet-parsed game-mode {"action": "on"}', recorded)
        self.assertIn('fleet-parsed game-mode {"action": "off"}', recorded)

    def wait_for(self, job_id, seconds=5):
        deadline = time.time() + seconds
        while time.time() < deadline:
            record = dashboard.read_job(job_id)[1]
            if record.get("state") != "running":
                return record
            time.sleep(0.02)
        self.fail(f"job {job_id} never finished")

    def test_a_drain_and_a_resume_cannot_run_at_the_same_time(self):
        """The farm has one power state, not three. `fleet game-mode on` and
        `fleet game-mode off` are opposites, so the second press must be refused with the first
        one, whichever verb it carries."""
        gate = self.state / "gate"
        blocker = self.state / "fleet"
        blocker.write_text('#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s"\n'
                           'while [ ! -f "%s" ]; do sleep 0.02; done\n'
                           % (self.state / "ran", gate))
        blocker.chmod(0o755)
        with mock.patch.object(dashboard, "fleet_bin", return_value=str(blocker)):
            status, drain = dashboard.power_action({"action": "drain"})
            self.assertEqual(status, 202, drain)
            for action in ("resume", "drain", "throttle"):
                status, payload = dashboard.power_action({"action": action})
                self.assertEqual(status, 409, (action, payload))
                self.assertEqual(payload["job"]["id"], drain["job"]["id"],
                                 "the refusal names the press that is actually running")
                self.assertIn("Drain the farm", payload["error"])
            self.assertEqual([record["id"] for record in dashboard.running_jobs()],
                             [drain["job"]["id"]])
            gate.write_text("go")
            self.wait_for(drain["job"]["id"])
        # only the drain ever reached a command line
        self.assertEqual((self.state / "ran").read_text().strip().splitlines(),
                         ["game-mode on"])
        # and with the power state free again, the next press is taken
        with mock.patch.object(dashboard, "fleet_bin", return_value=str(blocker)):
            status, resume = dashboard.power_action({"action": "resume"})
            self.assertEqual(status, 202, resume)
            self.wait_for(resume["job"]["id"])

    def test_a_throttle_holds_the_power_state_while_it_runs(self):
        """It answers at once rather than as a job, but a drain must not start underneath it."""
        with self.farm():
            seen = []

            def slow_tool(args, timeout=None, env=None):
                seen.append(dashboard.power_action({"action": "drain"})[0])
                return 0, "balanced\n", ""

            with mock.patch.object(dashboard, "run_tool", slow_tool):
                status, payload = dashboard.power_action({"action": "throttle"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(seen, [409], "a drain must not start while the throttle is running")
        self.assertEqual(dashboard.running_jobs(), [],
                         "and the throttle lets go of it as soon as it has answered")

    def test_a_second_drain_while_one_is_running_is_refused(self):
        gate = self.state / "gate"
        blocker = self.state / "fleet"
        blocker.write_text('#!/bin/sh\nwhile [ ! -f "%s" ]; do sleep 0.02; done\n' % gate)
        blocker.chmod(0o755)
        with mock.patch.object(dashboard, "fleet_bin", return_value=str(blocker)):
            self.assertEqual(dashboard.power_action({"action": "drain"})[0], 202)
            status, payload = dashboard.power_action({"action": "drain"})
            self.assertEqual(status, 409)
            self.assertIn("already running", payload["error"])
            self.assertEqual(payload["job"]["action"], "drain")
            gate.write_text("go")
            self.wait_for(payload["job"]["id"])

    def test_the_routes_need_the_write_token_and_the_preview_is_a_read(self):
        with self.farm() as box:
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
                self.assertEqual(fetch_json(base, "/api/power", method="POST",
                                            body={"action": "throttle"})[0], 403)
                # a read, so it answers on a loopback bind with no token at all, and for every
                # action it takes: what a control is about to do must cost nothing to ask
                box.calls.write_text("")
                for action in ("throttle", "drain", "resume"):
                    status, payload = fetch_json(base, f"/api/power/preview?action={action}")
                    self.assertEqual(status, 200, action)
                    self.assertEqual(payload["action"], action)
                    self.assertTrue(payload["sentence"], action)
                self.assertEqual(payload["lane_count"], 0)
                self.assertEqual(fetch_json(base, "/api/power/preview?action=drain",
                                            token="s3cret")[1]["lane_count"], 2)
                self.assertEqual(box.calls.read_text(), "",
                                 "a preview must not run a single tool")
                status, payload = fetch_json(base, "/api/power", token="s3cret", method="POST",
                                             body={"action": "throttle"})
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["action"], "throttle")
                self.assertIn('fleet-parsed mode {"mode": "balanced"}', box.calls.read_text(),
                              "and the press that follows it does")


class LoginStateTest(unittest.TestCase):
    """Whether this farm is logged in, read from files on this machine. Asking the vendor would
    be a request per account per tick, and an account being throttled is made worse by asking."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.extra = self.home / ".fleet" / "claude-accounts"
        self.extra.mkdir(parents=True)
        (self.home / ".claude").mkdir()
        for target, value in (("HOME", str(self.home)), ("EXTRA_DIR", str(self.extra)),
                              ("FARM_ALIAS", "farm")):
            patcher = mock.patch.object(dashboard.CA, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(dashboard.CX, "AUTH", str(self.home / ".codex" / "auth.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def credentials(self, directory, expires_in):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".credentials.json").write_text(json.dumps(
            {"claudeAiOauth": {"expiresAt": (time.time() + expires_in) * 1000}}))

    def snapshot(self, rows):
        return mock.patch.object(dashboard, "accounts_snapshot",
                                 return_value={"at": 1790000000.0, "accounts": rows,
                                               "errors": {}})

    def states(self, rows=()):
        with self.snapshot(list(rows)):
            payload = dashboard.accounts_login_state()
        return {row["name"]: row for row in payload["accounts"]}, payload

    def test_a_login_that_is_there_and_in_date_is_logged_in(self):
        self.credentials(self.home / ".claude", 8 * 3600)
        rows, payload = self.states([{"name": "default", "session": 12, "read_at": 1790000000.0}])
        self.assertEqual(rows["default"]["state"], "logged_in")
        self.assertIn("Logged in", rows["default"]["sentence"])
        self.assertIsNotNone(dashboard.parse_iso(rows["default"]["read_at"]))
        self.assertIsNotNone(dashboard.parse_iso(payload["at"]))
        self.assertFalse(payload["pending"])

    def test_an_account_with_no_credentials_is_waiting_for_its_first_login(self):
        (self.extra / "farm-two").mkdir()
        rows, _ = self.states()
        self.assertEqual(rows["farm-two"]["state"], "waiting_for_login")
        self.assertIn("ssh -t farm", rows["farm-two"]["sentence"])
        self.assertIn("CLAUDE_CONFIG_DIR=" + str(self.extra / "farm-two"),
                      rows["farm-two"]["sentence"])

    def test_a_login_file_that_cannot_be_read_is_unknown_not_never_logged_in(self):
        """`CA.token_expiry` answers None for four different things, and only one of them means
        the account was never logged in. Drawing a working account as one that was never set up
        sends the operator to /login, which may replace a credential that was fine."""
        torn = self.extra / "farm-torn"
        torn.mkdir()
        (torn / ".credentials.json").write_text('{"claudeAiOauth": {"expi')
        other = self.extra / "farm-other-schema"
        other.mkdir()
        (other / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"token": "x"}}))
        empty = self.extra / "farm-empty-file"
        empty.mkdir()
        (empty / ".credentials.json").write_text("")
        never = self.extra / "farm-never"
        never.mkdir()
        rows, _ = self.states()
        for name in ("farm-torn", "farm-other-schema", "farm-empty-file"):
            self.assertEqual(rows[name]["state"], "unknown", name)
            self.assertNotIn("ssh -t farm", rows[name]["sentence"], name)
            self.assertNotIn("/login", rows[name]["sentence"], name)
        # and the one that really has no file is still told how to log in
        self.assertEqual(rows["farm-never"]["state"], "waiting_for_login")
        self.assertIn("ssh -t farm", rows["farm-never"]["sentence"])

    def test_a_login_file_this_farm_may_not_read_is_unknown(self):
        locked = self.extra / "farm-locked"
        locked.mkdir()
        path = locked / ".credentials.json"
        path.write_text(json.dumps({"claudeAiOauth": {"expiresAt": 1}}))
        path.chmod(0o000)
        self.addCleanup(path.chmod, 0o600)
        if os.access(path, os.R_OK):
            self.skipTest("this user reads every file whatever its mode")
        rows, _ = self.states()
        self.assertEqual(rows["farm-locked"]["state"], "unknown")
        self.assertIn("could not read", rows["farm-locked"]["sentence"])
        self.assertNotIn(str(locked), rows["farm-locked"]["sentence"], "never a path on a card")

    def test_a_token_whose_moment_has_passed_is_expired_even_behind_a_429(self):
        self.credentials(self.extra / "farm-one", -3600)
        rows, _ = self.states([{"name": "farm-one", "stale_error": "429 rate-limited, 9m to retry",
                                "read_at": None}])
        self.assertEqual(rows["farm-one"]["state"], "expired")
        self.assertIn("keepalive", rows["farm-one"]["sentence"])

    def test_a_throttled_account_says_the_farm_cannot_tell_rather_than_logged_out(self):
        self.credentials(self.extra / "farm-one", 8 * 3600)
        rows, _ = self.states([{"name": "farm-one",
                                "stale_error": "429 rate-limited, 9m to retry"}])
        self.assertEqual(rows["farm-one"]["state"], "rate_limited")
        self.assertIn("slow down", rows["farm-one"]["sentence"])

    def test_a_throttled_account_stays_throttled_when_the_copy_is_reworded(self):
        """The refresher rewrites every reason for a person before this row ever sees it, so
        reading the state back out of that sentence made rate_limited depend on the words "slow
        down" surviving in the copy. Reword the sentence and every throttled account silently
        became "unknown", with nothing failing."""
        self.credentials(self.extra / "farm-one", 8 * 3600)
        rows = [{"name": "farm-one", "stale_error": "HTTPError 429: too many requests"}]
        published, _ = dashboard.plain_account_trouble(rows, {})
        self.assertEqual(published[0]["trouble"], "rate_limited")
        # the copy a person reads is the page's to change, and changing it changes no state
        published[0]["stale_error"] = "The vendor has asked this farm to wait a while."
        states, _ = self.states(published)
        self.assertEqual(states["farm-one"]["state"], "rate_limited")
        self.assertNotIn("429", json.dumps(published), "no reader's text on a card")

    def test_codex_is_a_row_of_its_own_with_its_own_login_line(self):
        rows, _ = self.states()
        self.assertEqual(rows["codex"]["engine"], "codex")
        self.assertEqual(rows["codex"]["state"], "waiting_for_login")
        self.assertIn("codex login", rows["codex"]["sentence"])

    def test_every_row_is_one_of_the_five_states_and_carries_a_sentence(self):
        self.credentials(self.home / ".claude", 8 * 3600)
        (self.extra / "farm-two").mkdir()
        rows, _ = self.states()
        for row in rows.values():
            self.assertIn(row["state"], dashboard.LOGIN_STATES, row)
            self.assertTrue(row["sentence"].endswith(".") or "ssh" in row["sentence"], row)

    def test_the_route_reads_no_vendor_and_runs_no_tool(self):
        self.credentials(self.home / ".claude", 8 * 3600)
        with fake_tools({}) as box:
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), running_server() as base:
                status, payload = fetch_json(base, "/api/accounts/login-state")
            self.assertEqual(status, 200)
            self.assertEqual(box.calls.read_text(), "")
        self.assertEqual(payload["cooldown_seconds"], dashboard.ACCOUNTS_WAKE_COOLDOWN)


class AccountsRefreshTest(unittest.TestCase):
    """"Refresh now" wakes the reader this server already runs, and refuses to be leaned on."""

    def setUp(self):
        self.wake = RecordingEvent()
        for target, value in (("_accounts_wake", self.wake),):
            patcher = mock.patch.object(dashboard, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(dashboard._accounts_wake_at, {"at": 0.0}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_press_wakes_the_reader_and_the_next_one_is_refused_for_a_minute(self):
        now = 1790000000.0
        status, payload = dashboard.accounts_refresh_request(now)
        self.assertEqual(status, 200)
        self.assertEqual(self.wake.wakes, 1)
        status, payload = dashboard.accounts_refresh_request(now + 5)
        self.assertEqual(status, 429)
        self.assertEqual(self.wake.wakes, 1, "a refused press must not read the vendor")
        self.assertIn("55 seconds", payload["error"])
        self.assertEqual(payload["retry_after"], 55)
        status, _ = dashboard.accounts_refresh_request(now + 61)
        self.assertEqual(status, 200)
        self.assertEqual(self.wake.wakes, 2)

    def test_the_route_needs_the_write_token(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            self.assertEqual(fetch_json(base, "/api/accounts/refresh", method="POST")[0], 403)
            self.assertEqual(self.wake.wakes, 0)
            status, payload = fetch_json(base, "/api/accounts/refresh", token="s3cret",
                                         method="POST")
            self.assertEqual(status, 200, payload)
            self.assertEqual(self.wake.wakes, 1)
            self.assertEqual(fetch_json(base, "/api/accounts/refresh", token="s3cret",
                                        method="POST")[0], 429)


class AccountFolderTest(unittest.TestCase):
    """An added Claude account's name is also its folder. Joined to the accounts folder, "." is
    that folder itself, and removing it used to move every account's login away at once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.extra = self.home / ".fleet" / "claude-accounts"
        for name in ("alice", "bob"):
            (self.extra / name).mkdir(parents=True)
            (self.extra / name / ".credentials.json").write_text("{}")
        for target, value in (("HOME", str(self.home)), ("EXTRA_DIR", str(self.extra)),
                              ("FARM_ALIAS", "farm")):
            patcher = mock.patch.object(dashboard.CA, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in (("BIND", "127.0.0.1"), ("TOKEN", "s3cret")):
            patcher = mock.patch.object(dashboard, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def folders(self):
        return sorted(path.name for path in self.extra.iterdir())

    def post(self, base, route, name):
        return fetch_json(base, route, token="s3cret", method="POST", body={"name": name})

    def test_removing_a_name_that_is_not_a_plain_name_moves_nothing(self):
        with running_server() as base:
            for name in (".", "..", ".alice", "-x", "./alice", "", "a" * 41):
                status, payload = self.post(base, "/api/accounts/remove", name)
                self.assertEqual(status, 400, (name, payload))
            self.assertEqual(self.folders(), ["alice", "bob"])
            self.assertFalse((self.home / ".fleet" / "dead-account-backups").exists())
            status, payload = self.post(base, "/api/accounts/remove", "alice")
            self.assertEqual(status, 200, payload)
            self.assertEqual(self.folders(), ["bob"])
            # the login is kept in the backup folder, not deleted
            self.assertTrue(os.path.isfile(os.path.join(payload["backup"], ".credentials.json")))

    def test_adding_takes_the_same_rule(self):
        with running_server() as base:
            for name in (".", "..", ".hidden", "-x", "a b", "default", "auto"):
                status, payload = self.post(base, "/api/accounts/add", name)
                self.assertEqual(status, 400, (name, payload))
            self.assertEqual(self.folders(), ["alice", "bob"])
            status, payload = self.post(base, "/api/accounts/add", "carol")
            self.assertEqual(status, 200, payload)
            self.assertEqual(self.folders(), ["alice", "bob", "carol"])

    def test_the_cli_takes_the_same_rule(self):
        for name in (".", "..", ".hidden", "-x", "a b", "a/b", "default", "auto", ""):
            with contextlib.redirect_stderr(io.StringIO()) as said:
                self.assertEqual(dashboard.CA.cmd_add(name), 1, name)
            self.assertIn("plain name", said.getvalue())
        self.assertEqual(self.folders(), ["alice", "bob"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(dashboard.CA.cmd_add("carol"), 0)
        self.assertEqual(self.folders(), ["alice", "bob", "carol"])


class AccountEngineTest(unittest.TestCase):
    """Every account row says which engine spends it.

    The page has a column for it. The codex row named itself and the claude rows did not, so the
    column read "unknown" on every row but one, which is the one thing that column is for.
    """

    class StopLoop(Exception):
        """Raised out of the wait at the end of one pass, to run the refresher exactly once."""

    def one_pass(self, summaries, errors, previous=()):
        wake = mock.Mock()
        wake.wait.side_effect = self.StopLoop
        snapshot = {"at": None, "accounts": list(previous), "errors": {}}
        with mock.patch.object(dashboard, "_accounts_wake", wake), \
                mock.patch.dict(dashboard._accounts_snapshot, snapshot, clear=True), \
                mock.patch.object(dashboard.CA, "collect", return_value=(summaries, errors)), \
                mock.patch.object(dashboard.CA, "account_dirs",
                                  return_value={name: f"/farm/{name}" for name in
                                                list(summaries) + list(errors)}), \
                mock.patch.object(dashboard.CA, "display", side_effect=lambda name: name), \
                mock.patch.object(dashboard.CA, "write_cache"), \
                mock.patch.object(dashboard.CA, "token_expiry", return_value=None), \
                mock.patch.object(dashboard.CX, "snapshot_row",
                                  return_value={"name": "codex", "engine": "codex",
                                                "session": 10, "weekly": 20, "scoped": []}), \
                mock.patch.object(dashboard.CX, "merge_row", side_effect=lambda row, _p: row):
            with self.assertRaises(self.StopLoop):
                dashboard._accounts_refresher()
            return {row["name"]: row for row in dashboard.accounts_snapshot()["accounts"]}

    GOOD = {"session": 40, "weekly": 60, "session_resets": None, "weekly_resets": None,
            "scoped": []}

    def test_a_claude_account_says_which_engine_spends_it(self):
        rows = self.one_pass({"farm-one": dict(self.GOOD)}, {})
        self.assertEqual(rows["farm-one"]["engine"], "claude")
        self.assertEqual(rows["codex"]["engine"], "codex", "and codex still names itself")

    def test_an_account_that_could_not_be_read_still_says_its_engine(self):
        """Both of the other two shapes: the one that has never been read, and the one whose
        last read failed and keeps its previous numbers."""
        previous = [{"name": "farm-two", "label": "farm-two", "session": 12, "weekly": 30,
                     "scoped": [], "read_at": 1790000000.0}]
        rows = self.one_pass({}, {"farm-two": "the vendor answered 429",
                                  "farm-three": "never read"}, previous=previous)
        self.assertEqual(rows["farm-two"]["engine"], "claude")
        self.assertEqual(rows["farm-three"]["engine"], "claude")


class EnginesTest(unittest.TestCase):
    """GET /api/engines: the catalog plus whether this machine can actually run each engine.

    The page draws an On and Off switch only where the command is there, so this answer is what
    stops the dashboard offering to spawn a lane that cannot start.
    """

    CATALOG = [
        {"id": "claude", "label": "Claude Code", "engine": "claude", "enabled": True,
         "health": "ok", "health_detail": "claude CLI present", "checked_at": 1790000000},
        {"id": "codex", "label": "Codex", "engine": "codex", "enabled": True,
         "health": "unchecked", "health_detail": "", "checked_at": 0},
        {"id": "democli", "label": "Demo CLI", "engine": "generic", "bin": "democli",
         "enabled": False, "health": "unchecked", "health_detail": "", "checked_at": 0},
    ]

    def rows(self, installed=(), env=None):
        """The listing as it reads on a machine that has exactly these commands on its PATH."""
        with tempfile.TemporaryDirectory() as home:
            binaries = pathlib.Path(home) / "bin"
            binaries.mkdir()
            for name in installed:
                tool = binaries / name
                tool.write_text("#!/bin/sh\nexit 0\n")
                tool.chmod(0o755)
            environment = {"PATH": str(binaries), "HOME": home}
            environment.update(env or {})
            with mock.patch.dict(os.environ, environment, clear=False):
                for name in ("CLAUDE_BIN", "CODEX_BIN", "FLEET_CLAUDE_BIN", "FLEET_CODEX_BIN"):
                    if name not in (env or {}):
                        os.environ.pop(name, None)
                with mock.patch.object(dashboard.MODELS, "listing", return_value=self.CATALOG):
                    answer = dashboard.engines()
            return {row["id"]: row for row in answer}, pathlib.Path(home)

    def test_an_engine_that_is_not_on_this_machine_says_so_and_says_what_to_run(self):
        rows, _home = self.rows(installed=["claude"])
        self.assertTrue(rows["claude"]["installed"])
        self.assertTrue(rows["claude"]["path"].endswith("/claude"))
        for missing in ("codex", "democli"):
            self.assertFalse(rows[missing]["installed"], missing)
            self.assertEqual(rows[missing]["path"], "", missing)
            self.assertTrue(rows[missing]["install_hint"], missing)
        # a generic engine is looked for under its own command, not under its id
        self.assertIn("democli", rows["democli"]["install_hint"])

    def test_the_bin_override_is_the_path_that_counts(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            own = pathlib.Path(elsewhere) / "claude-of-my-own"
            own.write_text("#!/bin/sh\nexit 0\n")
            own.chmod(0o755)
            rows, _home = self.rows(installed=["claude"], env={"CLAUDE_BIN": str(own)})
            self.assertTrue(rows["claude"]["installed"])
            self.assertEqual(rows["claude"]["path"], str(own))
            # The env file's name for it counts the same way.
            rows, _home = self.rows(installed=["claude"], env={"FLEET_CLAUDE_BIN": str(own)})
            self.assertEqual(rows["claude"]["path"], str(own))
            # An override pointing at nothing is still what a lane would run, so the engine
            # cannot start, whatever else is on the PATH.
            rows, _home = self.rows(installed=["claude"],
                                    env={"FLEET_CLAUDE_BIN": str(own) + "-gone"})
            self.assertFalse(rows["claude"]["installed"])
            self.assertEqual(rows["claude"]["path"], "")

    def test_the_official_installers_place_comes_before_the_path(self):
        with tempfile.TemporaryDirectory() as home:
            local = pathlib.Path(home, ".local", "bin")
            local.mkdir(parents=True)
            (local / "codex").write_text("#!/bin/sh\nexit 0\n")
            (local / "codex").chmod(0o755)
            rows, _home = self.rows(installed=["claude", "codex"], env={"HOME": home})
            self.assertEqual(rows["codex"]["path"], str(local / "codex"))
            self.assertTrue(rows["claude"]["path"].endswith("/bin/claude"))
            self.assertTrue(rows["claude"]["path"].endswith("/claude"))

    def test_the_row_carries_the_switch_and_the_last_test(self):
        rows, _home = self.rows(installed=["claude", "codex", "democli"])
        self.assertIs(rows["claude"]["enabled"], True)
        self.assertIs(rows["democli"]["enabled"], False)
        self.assertIsNotNone(dashboard.parse_iso(rows["claude"]["last_test"]))
        self.assertIsNone(rows["codex"]["last_test"], "never tested is not a time")

    def test_reading_the_route_never_starts_an_engine(self):
        """A GET drawn on every tick of the machine tab must not run three CLIs a tick."""
        with mock.patch.object(dashboard.MODELS, "listing", return_value=self.CATALOG), \
                mock.patch.object(dashboard.subprocess, "run",
                                  side_effect=AssertionError("a GET started a process")):
            with running_server() as base:
                status, body = fetch_json(base, "/api/engines")
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in body], ["claude", "codex", "democli"])
        for row in body:
            for key in ("installed", "path", "install_hint", "enabled", "last_test"):
                self.assertIn(key, row, row["id"])


@contextlib.contextmanager
def own_catalog(text=None, state=None):
    """A farm with its own models.toml, or with none at all, in a directory that is thrown away.

    The catalog the tests must never touch is the one belonging to the machine running them:
    everything here points the library at a temporary FLEET_CONFIG and FLEET_STATE.
    """
    with tempfile.TemporaryDirectory() as room:
        config = pathlib.Path(room, "config", "models.toml")
        store = pathlib.Path(room, "state", "models-state.json")
        if text is not None:
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(text)
        if state is not None:
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps(state))
        with mock.patch.object(dashboard.MODELS, "CONFIG", str(config)), \
                mock.patch.object(dashboard.MODELS, "STATE", str(store)), \
                mock.patch.dict(os.environ, {"FLEET_STATE": str(pathlib.Path(room, "state"))},
                                clear=False):
            yield pathlib.Path(room)


def read_toml(path):
    import tomllib
    with open(path, "rb") as handle:
        return tomllib.load(handle)


# A contributor adds an engine by appending one dict to lib/model_presets.py's PRESETS. murmur
# itself ships only claude and codex, so the writes behind "Add a model" are checked on fictional
# contributions, put into the list for one test and taken out again.
DEMO_PRESETS = [
    {"id": "democli", "label": "Demo CLI", "color": "#3A6EA5", "kind": "key",
     "engine": "generic", "bin": "democli",
     "install_hint": "install democli so that `democli` is on this farm's PATH", "pull_hint": "",
     "auth_env": "DEMOCLI_API_KEY", "run": "{bin} -m {variant} -p {task} --output-format json",
     "health": dashboard.MODEL_PRESETS.HEALTH, "tos": "a documented non-interactive mode",
     "access": "an API key in DEMOCLI_API_KEY, billed per token",
     "variants": ["demo-large", "demo-small"], "docs": "https://example.invalid/democli"},
    {"id": "demo-local", "label": "Demo local", "color": "#4FA07A", "kind": "local",
     "engine": "generic", "bin": "demolocal",
     "install_hint": "install demolocal so that `demolocal` is on this farm's PATH",
     "pull_hint": "demolocal pull <variant>", "auth_env": "", "run": "{bin} run {variant} {task}",
     "health": dashboard.MODEL_PRESETS.HEALTH,
     "tos": "runs on this machine, so there are no service terms to keep",
     "access": "nothing: it runs on this farm's own hardware",
     "variants": ["demo-7b", "demo-13b"], "docs": "https://example.invalid/demolocal"},
    # A contribution that leaves the command to the operator.
    {"id": "demo-bare", "label": "Demo template", "color": "#8A8F98", "kind": "key",
     "engine": "generic", "bin": "", "install_hint": "", "pull_hint": "", "auth_env": "",
     "run": "", "health": dashboard.MODEL_PRESETS.HEALTH,
     "tos": "whatever the command you name allows",
     "access": "however the command you name is paid for", "variants": [],
     "docs": "https://example.invalid/demo-bare"},
]


@contextlib.contextmanager
def contributed():
    """model_presets.PRESETS with the fictional contributions appended, for one test."""
    shipped = dashboard.MODEL_PRESETS.PRESETS
    with mock.patch.object(dashboard.MODEL_PRESETS, "PRESETS",
                           shipped + [dict(p) for p in DEMO_PRESETS]):
        yield


class ModelPresetsRouteTest(unittest.TestCase):
    """GET /api/models/presets: the services a person can add, and which this farm already has."""

    CARD_FIELDS = ("label", "color", "kind", "access", "tos", "install_hint", "variants", "docs",
                   "added")

    def test_every_card_the_dialog_draws_is_served_with_what_it_needs_to_say(self):
        with own_catalog(), running_server() as base:
            status, rows = fetch_json(base, "/api/models/presets")
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in rows], ["claude", "codex"])
        for row in rows:
            for key in self.CARD_FIELDS:
                self.assertIn(key, row, row["id"])
            self.assertTrue(row["access"].strip(), row["id"])
            self.assertTrue(row["tos"].strip(), row["id"])

    def test_a_contributed_preset_is_one_more_card_with_everything_it_needs(self):
        with own_catalog(), contributed(), running_server() as base:
            status, rows = fetch_json(base, "/api/models/presets")
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in rows],
                         ["claude", "codex", "democli", "demo-local", "demo-bare"])
        for row in rows:
            for key in self.CARD_FIELDS:
                self.assertIn(key, row, row["id"])

    def test_a_service_this_farm_already_has_is_not_offered_again(self):
        # No catalog of its own: the farm runs on the shipped example, which is claude and codex.
        with own_catalog(), contributed(), running_server() as base:
            _status, rows = fetch_json(base, "/api/models/presets")
        added = {row["id"]: row["added"] for row in rows}
        self.assertTrue(added["claude"])
        self.assertTrue(added["codex"])
        self.assertFalse(added["democli"])

    def test_claude_and_codex_are_marked_added_when_this_farm_s_own_catalog_holds_them(self):
        both = ('[claude]\nlabel = "Claude Code"\nengine = "claude"\n\n'
                '[codex]\nlabel = "Codex"\nengine = "codex"\n')
        with own_catalog(both), running_server() as base:
            status, rows = fetch_json(base, "/api/models/presets")
        self.assertEqual(status, 200)
        self.assertEqual({row["id"]: row["added"] for row in rows},
                         {"claude": True, "codex": True})
        with own_catalog('[claude]\nlabel = "Claude Code"\nengine = "claude"\n'), \
                running_server() as base:
            _status, rows = fetch_json(base, "/api/models/presets")
        self.assertEqual({row["id"]: row["added"] for row in rows},
                         {"claude": True, "codex": False},
                         "a farm that took codex out is offered it again")

    def test_a_row_added_from_a_preset_marks_that_preset_whatever_it_was_named(self):
        catalog = ('[mine]\nlabel = "My Demo"\nengine = "generic"\nbin = "democli"\n'
                   'run = "{bin} -p {task}"\npreset = "democli"\nsource = "added"\n')
        with own_catalog(catalog), contributed(), running_server() as base:
            _status, rows = fetch_json(base, "/api/models/presets")
        added = {row["id"]: row["added"] for row in rows}
        self.assertTrue(added["democli"], "the card must say it is already here")
        self.assertFalse(added["demo-bare"])

    def test_reading_the_services_never_starts_anything(self):
        with own_catalog(), \
                mock.patch.object(dashboard.subprocess, "run",
                                  side_effect=AssertionError("a GET started a process")), \
                running_server() as base:
            self.assertEqual(fetch_json(base, "/api/models/presets")[0], 200)


class ModelAddRemoveTest(unittest.TestCase):
    """POST /api/models/add and /api/models/remove: the writes behind "Add a model"."""

    def setUp(self):
        patcher = contributed()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)

    def add(self, base, body):
        return fetch_json(base, "/api/models/add", token="s3cret", method="POST", body=body)

    def remove(self, base, body):
        return fetch_json(base, "/api/models/remove", token="s3cret", method="POST", body=body)

    def test_adding_a_preset_writes_the_catalog_and_answers_the_new_row(self):
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            status, payload = self.add(base, {"preset": "democli", "id": "democli",
                                              "variant": "demo-large"})
            self.assertEqual(status, 200, payload)
            row = payload["model"]
            written = read_toml(dashboard.MODELS.CONFIG)
        self.assertEqual(row["id"], "democli")
        self.assertEqual(row["source"], "added")
        self.assertEqual(row["variant"], "demo-large")
        self.assertEqual(row["command"], "democli")
        self.assertTrue(row["access"].strip())
        self.assertIn(row["status"], dashboard.MODEL_STATUSES)
        self.assertIs(row["in_catalog"], True, "a row from a preset this farm has is in the catalog")
        # the shipped example came across on the first write, so nothing was lost
        self.assertEqual(set(written), {"claude", "codex", "democli"})
        # the model picked in step 2 is on the command line, not only in the row's variant field
        self.assertEqual(written["democli"]["run"],
                         "{bin} -m {variant} -p {task} --output-format json")
        self.assertEqual(written["democli"]["variant"], "demo-large")
        self.assertEqual(written["democli"]["preset"], "democli")

    def test_a_key_in_the_body_is_refused_before_anything_is_written(self):
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            status, payload = self.add(base, {"preset": "democli", "id": "democli",
                                              "key": "sk-live-not-a-real-key"})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"],
                             "A key never goes through this page. Run: fleet models auth democli")
            self.assertFalse(os.path.exists(dashboard.MODELS.CONFIG), "nothing was written")
            self.assertNotIn("sk-live", json.dumps(payload), "the key is never echoed back")
            for field in ("api_key", "secret", "credential"):
                status, payload = self.add(base, {"preset": "democli", "id": "democli",
                                                  field: "sk-live-not-a-real-key"})
                self.assertEqual(status, 400, field)
                self.assertIn("never goes through this page", payload["error"], field)
            # without an id there is still a sentence, with the command's shape in it
            status, payload = self.add(base, {"key": "sk-live"})
            self.assertEqual(payload["error"],
                             "A key never goes through this page. Run: fleet models auth <id>")

    def test_a_key_is_refused_whatever_the_field_is_called(self):
        """The refusal is on the field's NAME, so the casing a client happens to use, or the
        punctuation in it, cannot walk a credential past it."""
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            for field in ("apiKey", "API_KEY", "Api-Key", "KEY", "Token", "access_token",
                          "Secret", "CREDENTIAL", "x-api-key"):
                status, payload = self.add(base, {"preset": "democli", "id": "g1",
                                                  "variant": "demo-large",
                                                  field: "sk-live-not-a-real-key"})
                self.assertEqual(status, 400, field)
                self.assertIn("never goes through this page", payload["error"], field)
                self.assertNotIn("sk-live", json.dumps(payload), field)
            self.assertFalse(os.path.exists(dashboard.MODELS.CONFIG), "nothing was written")

    def test_a_key_pasted_into_the_command_line_is_refused_too(self):
        """The one that was not harmless: a key in `run` was written into models.toml verbatim
        and echoed back in the row."""
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            for body in (
                {"preset": "demo-bare", "id": "c1", "bin": "echo",
                 "run": "{bin} --api-key sk-live-not-a-real-key -p {task}"},
                {"preset": "demo-bare", "id": "c2", "bin": "echo",
                 "run": "{bin} --token AAAABBBBCCCCDDDD -p {task}"},
                {"preset": "demo-bare", "id": "c3", "bin": "echo",
                 "run": "{bin} -p {task} # sk-ant-0123456789abcdef"},
            ):
                status, payload = self.add(base, body)
                self.assertEqual(status, 400, body)
                self.assertIn("never goes through this page", payload["error"], body)
                self.assertNotIn("sk-live", json.dumps(payload), body)
                self.assertNotIn("AAAABBBB", json.dumps(payload), body)
            self.assertFalse(os.path.exists(dashboard.MODELS.CONFIG), "nothing was written")

    def test_a_command_that_reads_its_key_from_the_environment_is_still_written(self):
        """The refusal has to leave the documented way of doing it alone: the command names the
        variable, `fleet models auth` puts the key in it."""
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            status, payload = self.add(base, {
                "preset": "demo-bare", "id": "mine", "bin": "mycli",
                "run": "{bin} --api-key $MY_API_KEY --output-format json -p {task}",
                "auth_env": "MY_API_KEY"})
            self.assertEqual(status, 200, payload)
            written = read_toml(dashboard.MODELS.CONFIG)
            self.assertEqual(written["mine"]["auth_env"], "MY_API_KEY")

    def test_the_answers_a_person_can_get_wrong_are_sentences_not_tracebacks(self):
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            for body, expect in (
                ({}, "pick a service"),
                ({"preset": "nope", "id": "nope"}, "no such preset"),
                ({"preset": "gemini", "id": "gemini", "variant": "gemini-2.5-pro"},
                 "no such preset"),
                ({"preset": "custom", "id": "mine", "bin": "x", "run": "x {task}"},
                 "no such preset"),
                ({"preset": "democli", "id": "Democli", "variant": "demo-large"}, "model id"),
                ({"preset": "democli", "id": "democli"}, "demo-large"),
                ({"preset": "demo-bare", "id": "mine", "bin": "x", "run": "x {task}",
                  "variant": "demo-coder"}, "{variant}"),
                ({"preset": "demo-local", "id": "local"}, "demo-7b"),
                ({"preset": "demo-bare", "id": "mine"}, "bin"),
                ({"preset": "demo-bare", "id": "mine", "bin": "x", "run": "x --go"}, "{task}"),
                ({"preset": "claude", "id": "claude"}, "already"),
            ):
                status, payload = self.add(base, body)
                self.assertEqual(status, 400, body)
                self.assertIn(expect, payload["error"], (body, payload))
                self.assertNotIn("Traceback", json.dumps(payload))

    def test_a_row_is_called_what_the_person_named_it_or_what_its_preset_is_called(self):
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            status, payload = self.add(base, {"preset": "democli", "id": "nightly",
                                              "variant": "demo-large"})
            self.assertEqual(status, 200, payload)
            status, payload = self.add(base, {"preset": "demo-bare", "id": "notes",
                                              "bin": "thirdcli", "run": "{bin} {task}",
                                              "label": "Release notes"})
            self.assertEqual(status, 200, payload)
            _status, rows = fetch_json(base, "/api/engines")
        names = {row["id"]: row["label"] for row in rows}
        self.assertEqual(names["nightly"], "Demo CLI", "no name given: the preset's own label")
        self.assertEqual(names["notes"], "Release notes")
        self.assertEqual(names["claude"], "Claude Code", "a preset keeps its own label")

    def test_a_model_this_farm_added_can_be_removed_and_a_shipped_one_cannot(self):
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            self.add(base, {"preset": "democli", "id": "democli", "variant": "demo-large"})
            secret = pathlib.Path(dashboard.MODELS._secret_path("democli"))
            secret.parent.mkdir(parents=True, exist_ok=True)
            secret.write_text("sk-not-a-real-key\n")

            status, payload = self.remove(base, {"id": "claude"})
            self.assertEqual(status, 400)
            self.assertIn("came with fleet", payload["error"])

            status, payload = self.remove(base, {"id": "democli"})
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload, {"ok": True, "removed": "democli"})
            self.assertEqual(set(read_toml(dashboard.MODELS.CONFIG)), {"claude", "codex"})
            self.assertFalse(secret.exists(), "the stored key goes with the row")

            status, payload = self.remove(base, {"id": "democli"})
            self.assertEqual(status, 404)
            self.assertIn("no such model", payload["error"])
            self.assertEqual(self.remove(base, {})[0], 400)

    def test_neither_write_is_open_to_a_page_that_cannot_write(self):
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            for path in ("/api/models/add", "/api/models/remove"):
                status, payload = fetch_json(base, path, method="POST",
                                             body={"preset": "democli", "id": "democli"})
                self.assertEqual(status, 403, path)
                self.assertIn("token", payload["error"], path)
                # a page in another tab cannot post it with a token it happens to know either
                status, _payload = fetch_json(base, path, token="s3cret", method="POST",
                                              body={"preset": "democli", "id": "democli"},
                                              headers={"Sec-Fetch-Site": "cross-site"})
                self.assertEqual(status, 403, path)
            self.assertFalse(os.path.exists(dashboard.MODELS.CONFIG))

    def test_adding_a_model_never_runs_anything(self):
        """Writing a row is data. Running the CLI is what Test is for, and it costs money."""
        with own_catalog(), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard.subprocess, "run",
                                  side_effect=AssertionError("adding a model ran a command")), \
                running_server() as base:
            self.assertEqual(self.add(base, {"preset": "democli", "id": "democli",
                                             "variant": "demo-small"})[0], 200)


class ModelOrphanTest(unittest.TestCase):
    """A row murmur no longer ships: GET /api/engines lists it, marked, and never 500s.

    A farm that added Grok Build, or wrote a Gemini CLI table by hand, before those presets were
    removed still has that table in its own models.toml. The catalog below also holds a top-level
    key that is not a table and a field of the wrong type, the way a hand edit leaves one.
    """

    CATALOG = (
        'stray = "on"\n\n'
        '[claude]\nlabel = "Claude Code"\nengine = "claude"\ndefault_on = true\n\n'
        '[codex]\nlabel = "Codex"\nengine = "codex"\ndefault_on = true\n\n'
        '[grok]\nlabel = "Grok Build"\nengine = "generic"\npreset = "grok"\nbin = "grok"\n'
        'run = "{bin} -p {task} -m {variant}"\nvariant = "grok-4.7"\nauth_env = "XAI_API_KEY"\n'
        'source = "added"\n\n'
        '[gemini]\nengine = "generic"\nbin = "gemini"\nrun = "{bin} -p {task}"\nrole = 7\n'
    )
    STATE = {"grok": "not a record", "gemini": {"enabled": True, "health": "ok"}}
    NOTE = "Not in murmur's catalog: murmur ships Claude Code and Codex."

    def check_rows(self, rows, config):
        rows = {row["id"]: row for row in rows}
        self.assertEqual(sorted(rows), ["claude", "codex", "gemini", "grok"])
        for mid in ("claude", "codex"):
            self.assertIs(rows[mid]["in_catalog"], True, mid)
            self.assertEqual(rows[mid]["catalog_note"], "", mid)
        for mid in ("grok", "gemini"):
            self.assertIs(rows[mid]["in_catalog"], False, mid)
            self.assertTrue(rows[mid]["catalog_note"].startswith(self.NOTE), mid)
            self.assertIn(f"delete its [{mid}] table from {config}", rows[mid]["catalog_note"])
            self.assertIn(rows[mid]["status"], dashboard.MODEL_STATUSES, mid)
        self.assertIn("press Remove on its row", rows["grok"]["catalog_note"])
        self.assertNotIn("Remove", rows["gemini"]["catalog_note"])
        self.assertEqual(rows["gemini"]["role"], 7)

    def test_engines_lists_the_rows_it_no_longer_ships_with_the_note(self):
        with own_catalog(self.CATALOG, self.STATE) as room:
            before = (room / "config" / "models.toml").read_bytes()
            rows = dashboard.engines()
            self.check_rows(rows, dashboard.MODELS.CONFIG)
            self.assertEqual((room / "config" / "models.toml").read_bytes(), before,
                             "reading the rows never rewrites the catalog")

    def test_the_routes_answer_over_http_and_never_500(self):
        with own_catalog(self.CATALOG, self.STATE) as room, running_server() as base:
            before = (room / "config" / "models.toml").read_bytes()
            status, body = fetch_json(base, "/api/engines")
            self.assertEqual(status, 200, body)
            self.check_rows(body, dashboard.MODELS.CONFIG)
            status, listing = fetch_json(base, "/api/models")
            self.assertEqual(status, 200, listing)
            self.assertEqual(sorted(row["id"] for row in listing),
                             ["claude", "codex", "gemini", "grok"])
            status, cards = fetch_json(base, "/api/models/presets")
            self.assertEqual(status, 200, cards)
            self.assertEqual({row["id"]: row["added"] for row in cards},
                             {"claude": True, "codex": True})
            self.assertEqual((room / "config" / "models.toml").read_bytes(), before)

    def test_an_orphan_this_farm_added_can_still_be_removed_from_the_page(self):
        with own_catalog(self.CATALOG, self.STATE), mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                running_server() as base:
            status, payload = fetch_json(base, "/api/models/remove", token="s3cret",
                                         method="POST", body={"id": "grok"})
            self.assertEqual(status, 200, payload)
            written = read_toml(dashboard.MODELS.CONFIG)
        self.assertEqual(set(written), {"stray", "claude", "codex", "gemini"})


class ModelStatusTest(unittest.TestCase):
    """GET /api/engines: one word per row, from what this machine and the catalog know."""

    CATALOG = (
        '[gone]\nlabel = "Gone"\nengine = "generic"\nbin = "gone"\n'
        'run = "{bin} -p {task}"\nsource = "added"\n\n'
        '[keyless]\nlabel = "Keyless"\nengine = "generic"\nbin = "keyless"\n'
        'run = "{bin} -p {task}"\nauth_env = "KEYLESS_API_KEY"\nsource = "added"\n\n'
        '[broken]\nlabel = "Broken"\nengine = "generic"\nbin = "broken"\n'
        'run = "{bin} -p {task}"\nsource = "added"\n\n'
        '[live]\nlabel = "Live"\nengine = "generic"\nbin = "live"\n'
        'run = "{bin} run {variant} {task}"\nvariant = "llama3.1"\n'
        'access = "nothing: it runs on this farm\'s own hardware"\nsource = "added"\n\n'
        '[resting]\nlabel = "Resting"\nengine = "generic"\nbin = "resting"\n'
        'run = "{bin} -p {task}"\nsource = "added"\n'
    )
    STATE = {"broken": {"enabled": True, "health": "fail", "health_detail": "auth rejected"},
             "live": {"enabled": True, "health": "ok"},
             "resting": {"enabled": False, "health": "ok"}}

    @contextlib.contextmanager
    def farm(self, installed, env=None):
        with own_catalog(self.CATALOG, self.STATE) as room:
            binaries = room / "bin"
            binaries.mkdir(exist_ok=True)
            for name in installed:
                tool = binaries / name
                tool.write_text("#!/bin/sh\nexit 0\n")
                tool.chmod(0o755)
            environment = {"PATH": str(binaries), "HOME": str(room)}
            environment.update(env or {})
            with mock.patch.dict(os.environ, environment, clear=False):
                for name in ("CLAUDE_BIN", "CODEX_BIN", "FLEET_CLAUDE_BIN", "FLEET_CODEX_BIN",
                             "KEYLESS_API_KEY"):
                    if name not in (env or {}):
                        os.environ.pop(name, None)
                yield room

    def rows(self, installed, env=None):
        with self.farm(installed, env):
            return {row["id"]: row for row in dashboard.engines()}

    def test_each_state_is_decided_from_the_machine_and_the_catalog(self):
        rows = self.rows(["keyless", "broken", "live", "resting"])
        self.assertEqual(rows["gone"]["status"], "not_installed")
        self.assertEqual(rows["keyless"]["status"], "needs_key")
        self.assertEqual(rows["broken"]["status"], "failing")
        self.assertEqual(rows["live"]["status"], "on")
        self.assertEqual(rows["resting"]["status"], "off")
        self.assertEqual(rows["broken"]["health_detail"], "auth rejected")

    def test_a_missing_command_outranks_every_other_answer(self):
        """A model nothing on this machine can run is not "needs a key" and not "failing"."""
        rows = self.rows([])
        for mid in ("gone", "keyless", "broken", "live", "resting"):
            self.assertEqual(rows[mid]["status"], "not_installed", mid)
            self.assertTrue(rows[mid]["install_hint"], mid)

    def test_a_key_in_the_environment_or_on_the_farm_settles_the_key_question(self):
        rows = self.rows(["keyless"], env={"KEYLESS_API_KEY": "sk-not-a-real-key"})
        self.assertEqual(rows["keyless"]["status"], "off", "keyed, switched off")
        with self.farm(["keyless"]):
            secret = pathlib.Path(dashboard.MODELS._secret_path("keyless"))
            secret.parent.mkdir(parents=True, exist_ok=True)
            secret.write_text("sk-not-a-real-key\n")
            rows = {row["id"]: row for row in dashboard.engines()}
        self.assertEqual(rows["keyless"]["status"], "off",
                         "a key stored by `fleet models auth` counts")

    def test_every_row_says_how_it_is_paid_for_and_where_it_came_from(self):
        rows = self.rows(["live"])
        self.assertEqual(rows["live"]["access"], "nothing: it runs on this farm's own hardware")
        self.assertEqual(rows["live"]["variant"], "llama3.1")
        self.assertEqual(rows["live"]["source"], "added")
        # a row whose catalog entry never said is given a sentence, never an empty cell
        self.assertIn("KEYLESS_API_KEY", rows["keyless"]["access"])
        self.assertTrue(rows["gone"]["access"].strip())
        self.assertEqual(rows["gone"]["source"], "added")

    def test_a_shipped_catalog_row_says_which_subscription_spends(self):
        with own_catalog():
            rows = {row["id"]: row for row in dashboard.engines()}
        self.assertEqual(rows["claude"]["source"], "shipped")
        self.assertIn("Claude subscription", rows["claude"]["access"])
        self.assertIn("ChatGPT subscription", rows["codex"]["access"])

    def test_the_route_answers_the_new_fields_over_http(self):
        with self.farm(["live"]), running_server() as base:
            status, body = fetch_json(base, "/api/engines")
        self.assertEqual(status, 200)
        for row in body:
            for key in ("access", "status", "source", "variant"):
                self.assertIn(key, row, row["id"])
            self.assertIn(row["status"], dashboard.MODEL_STATUSES, row["id"])


class MachineReadingTest(unittest.TestCase):
    """The machine readings are Linux only, and the page must survive being run anywhere else."""

    def test_the_metrics_route_answers_on_a_machine_with_no_proc(self):
        with tempfile.TemporaryDirectory() as state:
            real_disk = dashboard.M.disk

            def roomy_disk():
                # The question here is the missing /proc, not this runner's disk: a CI box with
                # nineteen free gigabytes blocked the spawn for the right reason and failed the
                # wrong test.
                reading = real_disk()
                reading["free_gb"] = max(float(reading.get("free_gb") or 0), 500.0)
                return reading

            with mock.patch.object(dashboard.M, "MEMINFO", os.path.join(state, "nope")), \
                 mock.patch.object(dashboard.M, "LOADAVG", os.path.join(state, "nope")), \
                 mock.patch.object(dashboard.M, "STATE", state), \
                 mock.patch.object(dashboard.M, "disk", roomy_disk), \
                 mock.patch.object(dashboard, "STATE", state), \
                 blank_machine_snapshot():
                dashboard.machine_refresh()          # the refresher reads it, the route serves it
                with running_server() as base:
                    status, body = fetch_json(base, "/api/metrics")
        self.assertEqual(status, 200)
        self.assertIsNone(body["mem"])
        self.assertIsNone(body["load"])
        self.assertTrue(body["capacity"]["can_spawn"])
        self.assertIn(dashboard.M.NO_MACHINE_READING, body["capacity"]["warnings"])

    def test_the_strip_says_pending_until_the_first_pass_instead_of_lying(self):
        with blank_machine_snapshot():
            with running_server() as base:
                for route in ("/api/metrics", "/api/mode", "/api/sweep"):
                    status, body = fetch_json(base, route)
                    self.assertEqual(status, 200, route)
                    self.assertTrue(body["pending"], route)

    def test_a_reading_that_failed_keeps_the_last_good_numbers_and_says_so(self):
        """The defect the envelope exists to prevent: an hour-old load served with `at` set to
        now, no error, and nothing on the page saying not to trust it."""
        healthy = {"load": [0.1], "mem": {"used_pct": 12}}
        with blank_machine_snapshot():
            with mock.patch.object(dashboard.M, "collect", return_value=healthy), \
                    mock.patch.object(dashboard.MODE, "status", return_value={"mode": "full"}), \
                    mock.patch.object(dashboard, "sweep_status", return_value={"enabled": True}):
                dashboard.machine_refresh()
            good = dashboard._machine_part("metrics")
            self.assertEqual(good["load"], [0.1])
            self.assertIsNone(good["error"])
            self.assertIsNone(good["stale_since"])

            time.sleep(1.1)                  # the stamps are ISO seconds, so a pass has to land
            with mock.patch.object(dashboard.M, "collect",
                                   side_effect=OSError("/proc/loadavg is gone")), \
                    mock.patch.object(dashboard.MODE, "status", return_value={"mode": "full"}), \
                    mock.patch.object(dashboard, "sweep_status", return_value={"enabled": True}):
                dashboard.machine_refresh()
                dashboard.machine_refresh()
            after = dashboard._machine_part("metrics")
            # the power mode and the sweep countdown ride the same envelope
            mode = dashboard._machine_part("mode")
        self.assertEqual(after["load"], [0.1], "the last good numbers stay on the strip")
        self.assertEqual(after["at"], good["at"], "and they are still stamped when they were true")
        self.assertEqual(after["stale_since"], good["at"])
        self.assertIn("live numbers", after["error"])
        self.assertNotIn("Traceback", json.dumps(after))
        self.assertEqual(mode["stale_since"], good["at"])
        self.assertEqual(mode["mode"], "full")

    def test_the_first_pass_failing_is_not_published_as_a_blank_success(self):
        with blank_machine_snapshot():
            with mock.patch.object(dashboard.M, "collect", side_effect=OSError("no sensors")), \
                    mock.patch.object(dashboard.MODE, "status", return_value={"mode": "full"}), \
                    mock.patch.object(dashboard, "sweep_status", return_value={"enabled": True}):
                dashboard.machine_refresh()
            answer = dashboard._machine_part("metrics")
        self.assertIsNone(answer["at"], "nothing was ever read, so nothing can be stamped")
        self.assertIn("live numbers", answer["error"])


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
                mock.patch.object(dashboard.M, "LHM_URL", ""), \
                mock.patch.object(dashboard.M, "SYS_CLASS", "/nonexistent"):
            payload = self.refreshed()
        self.assertEqual(payload["title"], "murmur")
        self.assertEqual(payload["version"], "abc1234")
        self.assertEqual(payload["hq_agent"], "dashboard")
        self.assertEqual(payload["features"], {"hq": False, "slice": False, "gpu": False,
                                               "cpu_temp": False, "forge": "unknown",
                                               "health_panel": False})

    def test_a_complete_machine_reports_each_part_it_has(self):
        systemctl = 'case "$*" in *LoadState*) echo loaded;; esac\n'
        with fake_tools({"gh": "exit 0\n", "hq": "exit 0\n", "systemctl": systemctl},
                        env={"FLEET_DASH_TITLE": "acme farm",
                             "FLEET_DASH_HQ_AGENT": "console",
                             "FLEET_DASH_HEALTH": "on"}) as box:
            write_hq_config(box)
            with mock.patch.object(dashboard.M, "NVIDIA", "/usr/bin/nvidia-smi"), \
                    mock.patch.object(dashboard.M, "LHM_URL", "http://host:8085/data.json"):
                payload = self.refreshed()
        self.assertEqual(payload["title"], "acme farm")
        self.assertEqual(payload["hq_agent"], "console")
        self.assertEqual(payload["features"], {"hq": True, "slice": True, "gpu": True,
                                               "cpu_temp": True, "forge": "github",
                                               "health_panel": True})

    def test_the_processors_linux_sensor_is_a_temperature_feature(self):
        # Most Linux machines with a sensor have one the kernel reads; no LibreHardwareMonitor.
        with tempfile.TemporaryDirectory() as sys_class:
            hwmon = pathlib.Path(sys_class, "hwmon", "hwmon0")
            hwmon.mkdir(parents=True)
            (hwmon / "name").write_text("k10temp\n")
            (hwmon / "temp1_input").write_text("47000\n")
            with fake_tools({}), mock.patch.object(dashboard.M, "LHM_URL", ""), \
                    mock.patch.object(dashboard.M, "SYS_CLASS", sys_class):
                self.assertTrue(dashboard.config_payload()["features"]["cpu_temp"])
                state, detail, _fix = dashboard._check_cpu_temp_sensor()
        self.assertEqual(state, "ok")
        self.assertIn("k10temp", detail)

    def test_the_health_section_is_off_unless_the_farm_asks_for_it(self):
        for value, expected in (("", False), ("off", False), ("0", False), ("on", True),
                                ("1", True), ("true", True), ("YES", True), (" on ", True)):
            with mock.patch.dict(os.environ, {"FLEET_DASH_HEALTH": value}):
                self.assertIs(dashboard.config_payload()["features"]["health_panel"], expected,
                              repr(value))

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
                mock.patch.object(dashboard.M, "LHM_URL", ""), \
                mock.patch.object(dashboard.M, "SYS_CLASS", "/nonexistent"):
            rows = self.rows()
        self.assertEqual(set(rows), {"gh", "tmux", "systemd_user", "linger", "hq", "claude",
                                     "codex", "gpu_sensor", "cpu_temp_sensor", "sweep_timer",
                                     "office"})
        for row in rows.values():
            self.assertIn(row["state"], ("ok", "missing", "error", "off"), row)
            self.assertTrue(row["label"], row)
            self.assertNotIn("Traceback", row["detail"])
        self.assertEqual(rows["gh"]["state"], "missing")
        self.assertIn("cli.github.com", rows["gh"]["fix"])
        self.assertEqual(rows["tmux"]["state"], "missing")
        # A machine with no user manager still runs lanes: they live in tmux. Painting that row
        # red said something untrue about what was blocked.
        for name in ("systemd_user", "linger"):
            self.assertEqual(rows[name]["state"], "off", name)
            self.assertNotIn("lanes cannot", rows[name]["detail"], name)
        self.assertIn("tmux", rows["systemd_user"]["detail"])
        for word in ("power modes", "sweep timer"):
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

    def test_an_engine_row_checks_the_file_a_lane_will_run(self):
        # FLEET_CLAUDE_BIN in the env file is what every lane runs. A claude elsewhere on the PATH
        # must not make the row say ok while each lane fails to start.
        with fake_tools({"claude": "exit 0\n", "codex": "exit 0\n"},
                        env={"FLEET_CLAUDE_BIN": "/nowhere/claude"}):
            rows = self.rows()
        self.assertEqual(rows["claude"]["state"], "off")
        self.assertEqual(rows["codex"]["state"], "ok")
        # Codex's own installer puts it in ~/.local/bin, which is not on this server's PATH.
        with fake_tools({"claude": "exit 0\n"}) as box:
            local = box.root / ".local" / "bin"
            local.mkdir(parents=True)
            (local / "codex").write_text("#!/bin/sh\nexit 0\n")
            (local / "codex").chmod(0o755)
            rows = self.rows()
        self.assertEqual(rows["codex"]["state"], "ok")
        self.assertEqual(rows["codex"]["detail"], str(local / "codex"))

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
                     "gpu_sensor", "cpu_temp_sensor", "office"):
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
        # Ten working rows must survive the eleventh, and the message a person sees is the
        # exception's text, never a stack trace.
        def boom():
            raise RuntimeError("the sensor exploded")

        table = tuple((identifier, label, boom if identifier == "gh" else check)
                      for identifier, label, check in dashboard.HEALTH_CHECKS)
        with fake_tools({}), mock.patch.object(dashboard, "HEALTH_CHECKS", table):
            rows = self.rows()
        self.assertEqual(rows["gh"]["state"], "error")
        self.assertEqual(rows["gh"]["detail"], "RuntimeError: the sensor exploded")
        self.assertEqual(len(rows), 11)

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

    def finish(self, job_id, seconds=5):
        deadline = time.time() + seconds
        while time.time() < deadline:
            record = dashboard.read_job(job_id)[1]
            if record.get("state") != "running":
                return record
            time.sleep(0.02)
        self.fail(f"job {job_id} never finished")

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

    def test_adding_a_project_is_a_job_running_the_cli(self):
        """It clones a repository, so it answers at once with a job id: a browser held open for
        five minutes loses the outcome to any reload."""
        registry = self.config / "projects.toml"
        with fake_tools({"fleet": FLEET_FAKE},
                        env={"FLEET_FAKE_REGISTRY": str(registry)}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.add_project({"name": "gamma", "repo": "acme/gamma",
                                                         "port_base": 5800})
                self.assertEqual(status, 202, payload)
                self.assertEqual(payload["name"], "gamma")
                self.assertEqual(payload["repo"], "acme/gamma")
                self.assertEqual(payload["job"]["label"], "Adding gamma")
                done = self.finish(payload["job"]["id"])
            recorded = box.calls.read_text()
        self.assertEqual(done["state"], "done", done)
        self.assertEqual([row["name"] for row in dashboard.projects()], ["gamma"])
        self.assertIn("add-project --name gamma --repo acme/gamma --port-base 5800", recorded)
        # what fleet's own option loop made of it, not just what was typed at it
        self.assertIn('fleet-parsed add-project {"branch": "main", "name": "gamma", '
                      '"port_base": "5800", "repo": "acme/gamma"}', recorded)

    def test_a_second_press_does_not_start_a_second_clone(self):
        gate = self.state / "gate"
        cloner = self.state / "fleet"
        cloner.write_text('#!/bin/sh\nprintf "ran\\n" >> "%s"\n'
                          'while [ ! -f "%s" ]; do sleep 0.02; done\n'
                          % (self.state / "ran", gate))
        cloner.chmod(0o755)
        with mock.patch.object(dashboard, "fleet_bin", return_value=str(cloner)):
            status, first = dashboard.add_project({"name": "gamma", "repo": "acme/gamma"})
            self.assertEqual(status, 202, first)
            status, refusal = dashboard.add_project({"name": "delta", "repo": "acme/delta"})
            self.assertEqual(status, 409, refusal)
            self.assertIn("Adding gamma", refusal["error"])
            self.assertEqual(refusal["job"]["id"], first["job"]["id"])
            gate.write_text("go")
            self.finish(first["job"]["id"])
        self.assertEqual((self.state / "ran").read_text().strip().splitlines(), ["ran"])

    def test_a_refused_registration_is_a_failed_job_carrying_what_the_cli_said(self):
        with fake_tools({"fleet": FLEET_FAKE},
                        env={"FLEET_FAKE_FAIL": "already registered with different settings"}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.add_project({"name": "gamma", "repo": "acme/gamma"})
                self.assertEqual(status, 202, payload)
                failed = self.finish(payload["job"]["id"])
        self.assertEqual(failed["state"], "failed")
        self.assertIn("already registered", failed["error"])
        self.assertNotIn("Traceback", json.dumps(failed))

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

class ProjectRemovalTest(unittest.TestCase):
    """Taking a project off the registry. The registry only: worktrees and checkouts are not this
    route's business, and a project with work in flight is not removed at all."""

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
        self.registry = self.config / "projects.toml"
        self.registry.write_text(
            '# the farm\'s projects, in the order they were registered\n'
            '[alpha]\n'
            'repo = "acme/alpha"\n'
            'port_base = 5200\n'
            '\n'
            '["beta"]\n'
            'repo = "acme/beta"\n'
            'port_base = 5400\n'
            '\n'
            '["beta".ports]\n'
            'vite_base = 5400\n'
            'api_base = 8400\n'
            'e2e_base = 6400\n')

    def lane(self, slug, project, status):
        (self.state / "state" / (slug + ".json")).write_text(
            json.dumps({"slug": slug, "project": project, "status": status}))

    def finish(self, job_id, seconds=5):
        deadline = time.time() + seconds
        while time.time() < deadline:
            record = dashboard.read_job(job_id)[1]
            if record.get("state") != "running":
                return record
            time.sleep(0.02)
        self.fail(f"job {job_id} never finished")

    def test_removing_a_project_drops_its_tables_and_leaves_the_file_alone(self):
        status, payload = dashboard.remove_project({"name": "beta"})
        self.assertEqual(status, 200, payload)
        text = self.registry.read_text()
        self.assertNotIn("beta", text)
        self.assertIn("# the farm's projects", text)          # the operator's own words survive
        self.assertIn("[alpha]", text)
        self.assertEqual([row["name"] for row in dashboard.projects()], ["alpha"])

    def test_the_answer_names_the_port_block_that_is_free_again(self):
        payload = dashboard.remove_project({"name": "beta"})[1]
        self.assertEqual(payload["port_base"], 5400)
        self.assertEqual(payload["freed"], "5400 to 5499")
        self.assertIn("5400 to 5499", payload["sentence"])
        self.assertIn("untouched", payload["sentence"])
        self.assertTrue(pathlib.Path(payload["backup"]).exists())
        self.assertIn("[alpha]", pathlib.Path(payload["backup"]).read_text())

    def test_a_project_with_lanes_open_is_refused_with_the_count(self):
        self.lane("beta-1", "beta", "running")
        self.lane("beta-2", "beta", "pr_open")
        self.lane("beta-3", "beta", "merged")
        status, payload = dashboard.remove_project({"name": "beta"})
        self.assertEqual(status, 409)
        self.assertIn("2 lane(s) open", payload["error"])
        self.assertEqual(payload["lanes_open"], 2)
        self.assertIn("beta", self.registry.read_text())

    def test_a_removal_waits_for_the_add_that_is_writing_the_same_file(self):
        """Both writers own `projects.toml`, and the server is threaded: a remove whose read
        landed before an add's append and whose replace landed after it dropped the new
        project, and the guard cannot see that, because it only compares against the text this
        reader read."""
        gate = pathlib.Path(self.tmp.name, "gate")
        cloner = pathlib.Path(self.tmp.name, "fleet")
        cloner.write_text('#!/bin/sh\nwhile [ ! -f "%s" ]; do sleep 0.02; done\n' % gate)
        cloner.chmod(0o755)
        before = self.registry.read_text()
        with mock.patch.object(dashboard, "fleet_bin", return_value=str(cloner)):
            status, adding = dashboard.add_project({"name": "gamma", "repo": "acme/gamma"})
            self.assertEqual(status, 202, adding)
            status, refusal = dashboard.remove_project({"name": "beta"})
            self.assertEqual(status, 409, refusal)
            self.assertIn("Adding gamma", refusal["error"])
            self.assertEqual(self.registry.read_text(), before, "and nothing was rewritten")
            gate.write_text("go")
            self.finish(adding["job"]["id"])
        # with the registry free again the removal goes through, and leaves its own record
        status, payload = dashboard.remove_project({"name": "beta"})
        self.assertEqual(status, 200, payload)
        self.assertNotIn("beta", self.registry.read_text())
        removals = [record for record in dashboard._all_jobs()
                    if record["action"] == "remove_project"]
        self.assertEqual([record["state"] for record in removals], ["done"])
        self.assertEqual(dashboard.running_jobs(), [], "and it does not hold the key after")

    def test_a_refused_removal_lets_go_of_the_registry(self):
        for body in ({"name": "ghost"}, {"name": "../../etc/passwd"}):
            dashboard.remove_project(body)
        self.lane("beta-1", "beta", "running")
        self.assertEqual(dashboard.remove_project({"name": "beta"})[0], 409)
        self.assertEqual(dashboard.running_jobs(), [])
        with mock.patch.object(dashboard, "CONFIG", str(self.config / "gone")):
            self.assertEqual(dashboard.remove_project({"name": "beta"})[0], 404)
        self.assertEqual(dashboard.running_jobs(), [])

    def test_a_name_that_is_not_registered_is_a_404_and_a_bad_one_a_400(self):
        before = self.registry.read_text()
        self.assertEqual(dashboard.remove_project({"name": "ghost"})[0], 404)
        for name in ("", "../../etc/passwd", "a b", "x" * 41):
            self.assertEqual(dashboard.remove_project({"name": name})[0], 400, name)
        self.assertEqual(self.registry.read_text(), before)

    def test_the_route_needs_the_write_token(self):
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            self.assertEqual(fetch_json(base, "/api/projects/remove", method="POST",
                                        body={"name": "beta"})[0], 403)
            status, payload = fetch_json(base, "/api/projects/remove", token="s3cret",
                                         method="POST", body={"name": "beta"})
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["name"], "beta")

    def test_the_next_port_block_is_above_the_highest_one_registered(self):
        self.assertEqual(dashboard.next_port_base(), 5500)
        self.registry.write_text("")
        self.assertEqual(dashboard.next_port_base(), 5200)

    def test_the_page_can_ask_which_block_is_free_before_the_form_is_filled_in(self):
        """The suggestion belongs to the farm. A page working one out of the table it can see
        counted the api and end-to-end bases too, which are the same numbers for every project
        here, and suggested a block ten above the port every project's API already uses."""
        with running_server() as base:
            status, payload = fetch_json(base, "/api/projects/next-port")
        self.assertEqual(status, 200)
        self.assertEqual(payload["next_port_base"], 5500)
        self.assertIn("5500", payload["sentence"])
        self.assertNotIn("8400", payload["sentence"], "the shared api base is not a suggestion")

    def test_a_farm_with_no_block_left_says_so_rather_than_suggesting_a_number(self):
        self.registry.write_text(f'[alpha]\nport_base = {dashboard.PORT_BASE_MAX}\n')
        with running_server() as base:
            status, payload = fetch_json(base, "/api/projects/next-port")
        self.assertEqual(status, 200)
        self.assertIsNone(payload["next_port_base"])
        self.assertIn(str(dashboard.PORT_BASE_MAX), payload["sentence"])

    def test_a_farm_at_the_ceiling_is_refused_rather_than_handed_the_same_block(self):
        """Clamping to PORT_BASE_MAX handed the project at the top and the one after it the same
        numbers, which is the collision this default exists to prevent."""
        self.registry.write_text(f'[alpha]\nport_base = {dashboard.PORT_BASE_MAX}\n')
        self.assertIsNone(dashboard.next_port_base())
        with fake_tools({"fleet": FLEET_FAKE}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.add_project({"name": "gamma", "repo": "acme/gamma"})
            self.assertEqual(box.calls.read_text(), "", "nothing may be cloned for this")
        self.assertEqual(status, 400, payload)
        self.assertIn(str(dashboard.PORT_BASE_MAX), payload["error"])
        self.assertEqual(dashboard.running_jobs(), [])
        # one block below the ceiling is still handed out
        self.registry.write_text(
            f'[alpha]\nport_base = {dashboard.PORT_BASE_MAX - dashboard.PORT_BLOCK_SIZE}\n')
        self.assertEqual(dashboard.next_port_base(), dashboard.PORT_BASE_MAX)

    def test_the_answer_names_the_dev_server_block_and_not_the_shared_ports(self):
        """`fleet add-project` writes port_base alone: api_base and e2e_base are the same
        numbers for every project here, and are not a project's to free."""
        payload = dashboard.remove_project({"name": "beta"})[1]
        self.assertIn("dev server port block", payload["sentence"])
        self.assertIn("5400 to 5499", payload["sentence"])
        self.assertNotIn("8400", payload["sentence"])
        self.assertNotIn("6400", payload["sentence"])

    def test_registering_without_a_port_base_takes_the_next_free_block(self):
        with fake_tools({"fleet": FLEET_FAKE},
                        env={"FLEET_FAKE_REGISTRY": str(self.registry)}) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                status, payload = dashboard.add_project({"name": "gamma",
                                                         "repo": "acme/gamma"})
                self.assertEqual(status, 202, payload)
                self.assertEqual(payload["port_base"], 5500)
                self.finish(payload["job"]["id"])
            recorded = box.calls.read_text()
        self.assertIn("--port-base 5500", recorded)


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

    def test_a_secret_in_a_lanes_brief_result_or_log_is_scrubbed(self):
        # The brief, the result and the log hold the agent's own words, and an agent can paste a
        # key into any of them. They get the scrub a job's output gets: every stored secret, and
        # the token shapes scrub.py knows.
        token = "ghp_" + "A1b2C3d4" * 5          # a GitHub token's shape, not a real token
        stored = "stored-provider-key-0123"
        (self.state / "secrets").mkdir()
        (self.state / "secrets" / "demo.key").write_text(stored + "\n")
        (self.state / "state").mkdir()
        (self.state / "state" / "lane-5.json").write_text(json.dumps(
            {"slug": "lane-5", "project": "alpha", "engine": "claude", "status": "done",
             "task": f"push with {token}", "result_text": f"pushed with {stored}",
             "last_activity": f"Bash: echo {token}"}))
        (self.state / "logs" / "lane-5.task").write_text(f"the whole brief: push with {token}")
        (self.state / "logs" / "lane-5.last").write_text(f"done, with {stored}")
        self.write("lane-5.jsonl",
                   {"type": "assistant", "message": {"content": [
                       {"type": "text", "text": f"export GH_TOKEN={token}"}]}},
                   {"type": "result", "result": f"used {stored}"})
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), running_server() as base:
            for route in ("/api/agent?slug=lane-5", "/api/agent/log?slug=lane-5", "/api/fleet"):
                status, raw, _ = fetch(base, route)
                self.assertEqual(status, 200, route)
                self.assertNotIn(token, raw.decode(), route)
                self.assertNotIn(stored, raw.decode(), route)
                self.assertIn("[redacted]", raw.decode(), route)
            detail = fetch_json(base, "/api/agent?slug=lane-5")[1]
            self.assertEqual(detail["task"], "the whole brief: push with [redacted]")
            self.assertEqual(detail["result_text"], "done, with [redacted]")

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
three = sub.add_parser("claims"); three.add_argument("--repo")
sub.add_parser("who")
sub.add_parser("inbox")
args = parser.parse_args()
if args.cmd == "msg":
    record("hq-parsed msg " + json.dumps([args.name, args.text]))
    print("sent to %s (inbox issue #7) as %s" % (args.name, os.environ.get("HQ_AGENT", "?")))
elif args.cmd == "feed":
    sys.exit("hq feed must never be called by the dashboard: it re-reads the whole office "
             "and takes longer than any timeout a page can wait behind")
elif args.cmd == "claims":
    if os.environ.get("HQ_CLAIMS_FAIL"):
        sys.exit("hq: could not fetch the claims branch")
    print("%-28s %-40s %-12s until %s  %s"
          % ("acme/dash", "dash/server", "dali", "2026-09-22T18:00:00Z", "reading it"))
    print("%-28s %-40s %-12s until %s  %s"
          % ("acme/web", "web/empty-states", "winston", "2026-09-22T12:00:00Z", ""))
    print("no active claims on acme/nothing")
elif args.cmd == "who":
    print("winston            live  updated  0.3h ago  dashboard work")
    print("dali               STALE updated  9.1h ago  ")
elif args.cmd == "inbox":
    sys.exit("hq inbox must never be called by the dashboard: it consumes an agent's mail")
'''

FLEET_FAKE = f'''#!{sys.executable}
{RECORD}
import argparse
argv = sys.argv[1:]
command, rest = (argv[0] if argv else ""), argv[1:]
failure = os.environ.get("FLEET_FAKE_FAIL", "")
if failure:
    sys.exit(failure)


def parsed(what, fields):
    record("fleet-parsed " + what + " " + json.dumps(fields, sort_keys=True))


def fixture(name):
    """What a listing prints: the file the test put there, or nothing at all."""
    path = os.environ.get(name, "")
    if not path:
        return "{{}}"
    with open(path) as handle:
        return handle.read()


def case_loop(words, flags):
    """fleet/bin/fleet parses with hand written case loops: a word starting with a dash is an
    option or a fatal error, and a bare `--` is one of the fatal ones. Mirrored here, because a
    separator the dashboard sent "to be safe" would land as a lane name."""
    found, positional = {{}}, []
    for word in words:
        if word in flags:
            found[word] = True
        elif word.startswith("-"):
            sys.exit("unknown flag: " + word)
        else:
            positional.append(word)
    return found, positional


if command == "msg":
    # fleet/bin/fleet cmd_msg: slug is "${{1:-}}", the message is "$*" after one shift.
    slug = rest[0] if rest else ""
    parsed("msg", [slug, " ".join(rest[1:])])
    print("queued for " + slug)
elif command == "add-project":
    # cmd_add_project: a case loop over long options, anything else is fatal.
    fields, pending = {{"branch": "main", "port_base": "5200"}}, list(rest)
    while pending:
        head = pending.pop(0)
        if head in ("--name", "--repo", "--path", "--branch", "--port-base") and pending:
            fields[head.lstrip("-").replace("-", "_")] = pending.pop(0)
        else:
            sys.exit("unknown " + head)
    if not fields.get("name") or not fields.get("repo"):
        sys.exit("need --name and --repo owner/name")
    parsed("add-project", fields)
    registry = os.environ.get("FLEET_FAKE_REGISTRY", "")
    if registry:
        with open(registry, "a") as handle:
            handle.write('[%s]\\nrepo = "%s"\\npath = "/srv/%s"\\nbranch = "%s"\\n'
                         % (fields["name"], fields["repo"], fields["name"], fields["branch"]))
    print("registered project '%s'" % fields["name"])
elif command == "kill":
    # cmd_kill: --retire, then anything else beginning with a dash is fatal, then the slug.
    flags, positional = case_loop(rest, {{"--retire"}})
    if not positional:
        sys.exit("usage: fleet kill [--retire] <slug>")
    parsed("kill", {{"slug": positional[0], "retire": bool(flags.get("--retire"))}})
    if flags.get("--retire"):
        print("retired lane (no live siblings)")
    print("killed " + positional[0])
elif command == "daemon":
    action = rest[0] if rest else "status"
    if action not in ("start", "on", "stop", "off", "status", "tick"):
        print("usage: fleet daemon start|stop|status|tick")     # cmd_daemon does not fail here
    else:
        parsed("daemon", {{"action": action}})
        print("fleet daemon: " + ("active" if action in ("start", "on") else "stopped"))
elif command == "autosweep":
    action = rest[0] if rest else "status"
    parsed("autosweep", {{"action": action, "minutes": rest[1] if len(rest) > 1 else ""}})
    print("autosweep " + ("ON" if action == "on" else "OFF" if action == "off" else "status"))
elif command in ("game-mode", "gamemode"):
    action = rest[0] if rest else "status"
    if action not in ("on", "off", "status"):
        sys.exit("usage: fleet game-mode on|off|status")
    parsed("game-mode", {{"action": action}})
    print("== game-mode %s ==" % action.upper())
    print("live lanes: 2" if action == "on" else "daemon started")
elif command == "mode":
    # cmd_mode hands straight to lib/mode.py, which takes one of five words or prints the mode.
    word = rest[0] if rest else ""
    if word and word not in ("auto", "full", "soft", "balanced", "hard"):
        sys.exit("fleet mode: unknown mode " + word)
    parsed("mode", {{"mode": word}})
    print("mode: %s   35%% CPU   spawns PAUSED" % (word or "auto"))
elif command == "accounts":
    parsed("accounts", {{"args": rest}})
    print("  default          session  12%  weekly  40%")
elif command == "machines":
    # The hosting CLI, as the design record's section 4 table writes it. Every branch records
    # the exact argv it was handed, so a test can assert the list and not a string.
    sub, tail = (rest[0] if rest else ""), rest[1:]
    record("fleet-argv " + json.dumps(argv))
    leak = os.environ.get("FLEET_FAKE_LEAK", "")
    if sub == "list":
        parsed("machines list", {{"json": "--json" in tail}})
        print(fixture("FLEET_FAKE_MACHINES"))
    elif sub in ("plan", "create"):
        parser = argparse.ArgumentParser(prog="fleet machines " + sub)
        parser.add_argument("--provider", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--size", required=True)
        parser.add_argument("--region", required=True)
        parser.add_argument("--pubkey-file")
        parser.add_argument("--confirm-usd")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args(tail)
        fields = vars(args)
        if args.pubkey_file:
            # What the dashboard actually handed over: the file's mode and its contents, so a
            # test can prove the key never travelled on a command line and never stayed behind.
            fields["pubkey_mode"] = oct(os.stat(args.pubkey_file).st_mode & 0o777)
            with open(args.pubkey_file) as handle:
                fields["pubkey_text"] = handle.read().strip()
        parsed("machines " + sub, fields)
        if sub == "plan":
            plan = {{"name": args.name, "size": args.size, "region": args.region,
                    "monthly_usd": 48, "price_source": "live",
                    "commands": ["doctl compute droplet create " + args.name],
                    "cloud_init": "#cloud-config\\nusers:\\n  - name: farm\\n"}}
            if leak:
                plan["detail"] = "the provider said: " + leak
                print("doctl: " + leak, file=sys.stderr)
            print(json.dumps(plan))
        else:
            print("machine '%s' is creating ($%s a month)" % (args.name, args.confirm_usd))
    elif sub == "add":
        parser = argparse.ArgumentParser(prog="fleet machines add")
        parser.add_argument("--name", required=True)
        parser.add_argument("--target", required=True)
        parser.add_argument("--port")
        args = parser.parse_args(tail)
        parsed("machines add", vars(args))
        print("registered '%s' and reached it over SSH" % args.name)
    elif sub == "destroy":
        # cmd_machines_destroy is a case loop: the name is positional, --confirm takes a value.
        flags, positional = {{}}, []
        pending = list(tail)
        while pending:
            head = pending.pop(0)
            if head == "--confirm" and pending:
                flags["confirm"] = pending.pop(0)
            elif head.startswith("-"):
                sys.exit("unknown flag: " + head)
            else:
                positional.append(head)
        if not positional or flags.get("confirm") != positional[0]:
            sys.exit("fleet machines destroy: --confirm must repeat the machine's name")
        parsed("machines destroy", {{"name": positional[0], "confirm": flags["confirm"]}})
        print("destroyed '%s'; billing has stopped" % positional[0])
    elif sub in ("check", "adopt", "forget"):
        flags, positional = case_loop(tail, set())
        if not positional:
            sys.exit("usage: fleet machines %s <name>" % sub)
        parsed("machines " + sub, {{"name": positional[0]}})
        print("%s: %s" % (sub, positional[0]))
    else:
        sys.exit("fleet machines: unknown verb " + sub)
elif command == "hosts":
    sub, tail = (rest[0] if rest else ""), rest[1:]
    record("fleet-argv " + json.dumps(argv))
    if sub == "list":
        parsed("hosts list", {{"json": "--json" in tail}})
        print(fixture("FLEET_FAKE_HOSTS"))
    elif sub == "check":
        flags, positional = case_loop(tail, set())
        if not positional:
            sys.exit("usage: fleet hosts check <provider>")
        parsed("hosts check", {{"provider": positional[0]}})
        print("%s: logged in as ada@example.com" % positional[0])
    else:
        sys.exit("fleet hosts: unknown verb " + sub)
elif command == "models":
    sub = rest[0] if rest else "list"
    if sub not in ("list", "enable", "disable", "test", "auth"):
        sys.exit("usage: fleet models [list | enable <id> | disable <id> | test <id> | auth <id>]")
    parsed("models", {{"action": sub, "id": rest[1] if len(rest) > 1 else ""}})
    print("models: " + sub)
else:
    sys.exit("unknown command " + command)
'''


class AgentKillTest(unittest.TestCase):
    """Stopping a lane from the page. Which of Stop and Retire a page may offer is the lane's
    restart policy's business, so the answer carries it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        (self.state / "state").mkdir()
        self.lane("lane-1", restart="until-pr")
        self.lane("lane-2", restart=None)
        patcher = mock.patch.object(dashboard, "STATE", str(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)

    def lane(self, slug, restart=None):
        record = {"slug": slug, "project": "alpha", "lane": "dash-v2", "status": "running"}
        if restart:
            record["restart"] = restart
        (self.state / "state" / (slug + ".json")).write_text(json.dumps(record))

    @contextlib.contextmanager
    def farm(self, **env):
        with fake_tools({"fleet": FLEET_FAKE}, env=env or None) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                yield box

    def test_stopping_a_lane_runs_the_verb_and_sends_no_separator(self):
        with self.farm() as box:
            status, payload = dashboard.agent_kill({"slug": "lane-1"})
            recorded = box.calls.read_text()
        self.assertEqual(status, 200, payload)
        self.assertIn("fleet kill lane-1", recorded)
        self.assertIn('fleet-parsed kill {"retire": false, "slug": "lane-1"}', recorded)
        # a bare `--` is an unknown flag to cmd_kill's case loop, so it is never sent
        self.assertNotIn("--", recorded)

    def test_retiring_a_lane_adds_the_flag_that_stops_the_respawns(self):
        with self.farm() as box:
            status, payload = dashboard.agent_kill({"slug": "lane-1", "retire": True})
            recorded = box.calls.read_text()
        self.assertEqual(status, 200, payload)
        self.assertIn('fleet-parsed kill {"retire": true, "slug": "lane-1"}', recorded)
        self.assertTrue(payload["retired"])
        self.assertIn("retired", payload["sentence"])

    def test_the_answer_carries_the_policy_the_confirm_has_to_word(self):
        with self.farm():
            with_policy = dashboard.agent_kill({"slug": "lane-1"})[1]
            without = dashboard.agent_kill({"slug": "lane-2"})[1]
        self.assertEqual(with_policy["restart"], "until-pr")
        self.assertIn("respawn", with_policy["sentence"])
        self.assertIsNone(without["restart"])
        self.assertIn("no restart policy", without["sentence"])

    def test_a_name_that_is_not_a_lane_never_reaches_the_cli(self):
        with self.farm() as box:
            status, payload = dashboard.agent_kill({"slug": "ghost"})
            self.assertEqual(status, 404)
            self.assertIn("no lane named", payload["error"])
            for slug in ("../etc/passwd", "-rf", "", "lane 1"):
                status, payload = dashboard.agent_kill({"slug": slug})
                self.assertEqual(status, 400, slug)
            self.assertEqual(box.calls.read_text(), "")

    def test_a_failing_cli_is_a_400_carrying_what_it_said(self):
        with self.farm(FLEET_FAKE_FAIL="no such tmux session: lane-1"):
            status, payload = dashboard.agent_kill({"slug": "lane-1"})
        self.assertEqual(status, 400)
        self.assertIn("no such tmux session", payload["error"])
        self.assertNotIn("Traceback", json.dumps(payload))

    def test_the_route_needs_the_write_token(self):
        with self.farm():
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                    running_server() as base:
                status, payload = fetch_json(base, "/api/agents/kill", method="POST",
                                             body={"slug": "lane-1"})
                self.assertEqual(status, 403)
                status, payload = fetch_json(base, "/api/agents/kill", token="s3cret",
                                             method="POST", body={"slug": "lane-1"})
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["slug"], "lane-1")


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
        # No read has woken the refresher yet, whatever an earlier test's reads did.
        cooldown = mock.patch.dict(dashboard._read_wake_at, {"at": None})
        cooldown.start()
        self.addCleanup(cooldown.stop)
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

    def test_two_inbox_issues_of_one_name_are_one_mailbox(self):
        """An office can hold two issues called `inbox: winston`. They are one mailbox: the
        newest issue is the one people write to, and the thread is every issue's comments."""
        now = time.time()
        stamp = lambda back: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - back))
        boxes = [
            {"number": 7, "title": "inbox: winston", "updatedAt": stamp(7200)},
            {"number": 21, "title": "inbox: winston", "updatedAt": stamp(1800)},
            {"number": 9, "title": "inbox: all", "updatedAt": stamp(3600)},
        ]
        comments = {
            7: [{"created_at": stamp(7200),
                 "body": "**from dali** (2026-09-21T06:00:00Z):\nthe old office issue"}],
            21: [{"created_at": stamp(1800),
                  "body": "**from rubicon** (2026-09-21T08:00:00Z):\nthe new office issue"}],
            9: [{"created_at": stamp(3600),
                 "body": "**from winston** (2026-09-21T07:00:00Z):\nthe orders lane is open"}],
        }
        with self.office(boxes=boxes, comments=comments):
            dashboard.mail_refresh()
            payload = dashboard.mail_boxes()
            names = [row["name"] for row in payload["boxes"]]
            self.assertEqual(names.count("winston"), 1)
            rows = {row["name"]: row for row in payload["boxes"]}
            # the box people write to is the newest issue of that name
            self.assertEqual(rows["winston"]["number"], 21)
            self.assertEqual(rows["winston"]["numbers"], [21, 7])
            # the day's count is both issues together, not whichever answered last
            self.assertEqual(rows["winston"]["count_24h"], 2)
            self.assertEqual(rows["winston"]["last_at"], stamp(1800))
            thread = dashboard.mail_thread("winston")[1]["messages"]
            self.assertEqual([message["sender"] for message in thread], ["dali", "rubicon"])

    def test_the_boxes_are_newest_first_with_all_pinned_to_the_top(self):
        """Twenty five code names in whatever order the forge answered is a list nobody reads."""
        now = time.time()
        stamp = lambda back: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - back))
        ages = {"dali": 20000, "all": 9000, "winston": 1800, "rubicon": 5400}
        boxes = [{"number": index + 2, "title": f"inbox: {name}", "updatedAt": stamp(back)}
                 for index, (name, back) in enumerate(ages.items())]
        comments = {index + 2: [{"created_at": stamp(back), "body": f"**from {name}** ():\nhello"}]
                    for index, (name, back) in enumerate(ages.items())}
        with self.office(boxes=boxes, comments=comments):
            dashboard.mail_refresh()
            names = [row["name"] for row in dashboard.mail_boxes()["boxes"]]
            self.assertEqual(names, ["all", "winston", "rubicon", "dali"])

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

    def test_the_mailboxes_are_published_before_a_single_thread_is_read(self):
        """The office on the farm holds ninety nine mailboxes. The list of them is one call;
        their threads are ninety nine more. Waiting for all of them before publishing anything
        left the Mail tab empty for a minute, which reads as a broken page, so the list goes
        out first and every thread as it lands."""
        now = time.time()
        stamp = lambda back: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - back))
        boxes = [{"number": number, "title": f"inbox: agent-{number}",
                  "updatedAt": stamp(60 * number)} for number in range(1, 7)]
        comments = {number: [{"created_at": stamp(60 * number),
                              "body": f"**from dali** ({stamp(60 * number)}):\nline {number}"}]
                    for number in range(1, 7)}
        watched = []
        with self.office(boxes=boxes, comments=comments):
            real = dashboard.mail_fetch_box_thread

            def watch(office, box, since):
                published = dashboard.mail_boxes()
                watched.append((len(published["boxes"]), published["pending"],
                                sum(row["count_24h"] for row in published["boxes"])))
                return real(office, box, since)

            with mock.patch.object(dashboard, "mail_fetch_box_thread", watch):
                dashboard.mail_refresh()
            final = dashboard.mail_boxes()
        self.assertEqual(len(watched), 6)
        # every mailbox is on screen, and not waiting, before the first thread is asked for
        self.assertEqual(watched[0], (6, False, 0))
        # and the messages arrive one box at a time, not all at the end
        self.assertEqual([row[2] for row in watched], [0, 1, 2, 3, 4, 5])
        self.assertEqual(sum(row["count_24h"] for row in final["boxes"]), 6)
        self.assertIsNone(final["error"])

    def test_the_office_timeline_is_assembled_here_and_never_by_running_hq_feed(self):
        # `hq feed` re-reads every mailbox in the office for itself. On the farm with ninety
        # nine of them that is eighty seven seconds, past any timeout a page can wait behind,
        # so the route answered an error and the Overview said nobody had spoken all day. The
        # timeline is built from the threads this server already holds instead.
        with self.office() as box:
            pending = dashboard.mail_feed("6")
            self.assertTrue(pending["pending"])
            self.assertEqual(pending["events"], [])
            self.assertTrue(dashboard.mail_who()["pending"])
            self.assertEqual(box.calls.read_text(), "")
            self.assertTrue(dashboard._refresh_wake.is_set(),
                            "a window nobody has asked for must wake the refresher")

            dashboard._refresh_once()
            ran = box.calls.read_text()
            self.assertNotIn("hq feed", ran)
            self.assertIn("hq who", ran)
            self.assertIn("hq claims", ran)
            box.calls.write_text("")
            feed = dashboard.mail_feed("6")
            who = dashboard.mail_who()
            self.assertEqual(box.calls.read_text(), "")
            self.assertFalse(feed["pending"])
            self.assertEqual(feed["hours"], 6.0)
            kinds = [event["kind"] for event in feed["events"]]
            self.assertEqual(kinds[:2], ["claim", "claim"])
            self.assertIn("mail", kinds)
            self.assertIn("session", kinds)
            # A claim is a fact about now, so it carries no moment, only when it runs out.
            self.assertEqual(feed["events"][0], {
                "at": None, "at_label": "held now", "kind": "claim",
                "text": "dali holds acme/dash#dash/server until 2026-09-22T18:00:00Z"})
            said = [event["text"] for event in feed["events"] if event["kind"] == "mail"]
            self.assertIn("rubicon to winston: the trials lane is green", said)
            # a comment nobody wrote through hq is still one line of the office's day
            self.assertIn("? to all: a comment with no sender prefix", said)
            # the message older than the window is not in it
            self.assertNotIn("dali to winston: the old one", said)
            stamped = [event["at"] for event in feed["events"] if event["at"]]
            self.assertEqual(stamped, sorted(stamped, reverse=True), "newest first")
            self.assertIn("winston active: dashboard work",
                          [event["text"] for event in feed["events"]])
            self.assertEqual([session["name"] for session in who["sessions"]],
                             ["winston", "dali"])
            self.assertEqual(who["sessions"][0]["age_hours"], 0.3)
            self.assertEqual(who["sessions"][0]["task"], "dashboard work")
            self.assertEqual(who["sessions"][1]["state"], "stale")

    def test_a_timeline_line_is_one_line_and_never_longer_than_a_row(self):
        now = time.time()
        stamp = lambda back: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - back))
        boxes = [{"number": 7, "title": "inbox: winston", "updatedAt": stamp(60)}]
        comments = {7: [{"created_at": stamp(60),
                         "body": "**from dali** (2026-09-21T08:00:00Z):\n"
                                 + "the report\n\n" + "word " * 200}]}
        with self.office(boxes=boxes, comments=comments):
            dashboard._refresh_once()
            line = [event for event in dashboard.mail_feed()["events"]
                    if event["kind"] == "mail"][0]
            self.assertEqual(len(line["text"]), dashboard.FEED_TEXT_LIMIT)
            self.assertNotIn("\n", line["text"])
            self.assertTrue(line["text"].startswith("dali to winston: the report word"))

    def test_the_timeline_keeps_its_messages_when_the_claims_cannot_be_read(self):
        with self.office() as box:
            with mock.patch.dict(os.environ, {"HQ_CLAIMS_FAIL": "1"}):
                dashboard._refresh_once()
            feed = dashboard.mail_feed()
            self.assertIn("hq claims", box.calls.read_text())
            self.assertIsNone(feed["error"])
            kinds = {event["kind"] for event in feed["events"]}
            self.assertEqual(kinds, {"mail", "session"})
            self.assertTrue(feed["events"])

    def test_the_default_window_is_warmed_and_the_tracked_set_stays_bounded(self):
        with self.office():
            dashboard._refresh_once()
            self.assertFalse(dashboard.mail_feed()["pending"])
            for hours in range(1, 20):
                dashboard.mail_feed(str(hours))
            self.assertLessEqual(len(dashboard._feed_windows), len(dashboard.FEED_WINDOWS))
            self.assertIn(float(dashboard.MAIL_WINDOW_HOURS), dashboard._feed_windows)

    def test_a_request_is_answered_from_one_of_a_few_fixed_windows(self):
        # A window nobody has asked for costs a pass over the office, so a caller cannot pick its
        # own. It gets the smallest fixed window that covers what it asked for.
        with self.office():
            dashboard._refresh_once()
            for asked, got in (("6", 6.0), ("5", 6.0), ("0.01", 1.0), ("-3", 1.0), ("25", 48.0),
                               ("100000", 720.0), ("", 24.0), ("junk", 24.0)):
                self.assertEqual(dashboard.mail_feed(asked)["hours"], got, asked)
            for step in range(500):
                dashboard.mail_feed(f"{0.05 + step * 1.7:g}")
            self.assertLessEqual(set(dashboard._feed_windows), set(dashboard.FEED_WINDOWS))
            self.assertEqual(len(dashboard._feed_windows), len(set(dashboard._feed_windows)))

    def test_a_burst_of_reads_for_new_windows_wakes_the_office_reader_once(self):
        # Every window nobody had asked for used to wake the refresher at once. A caller that
        # changed ?hours= on every request, with no token on a loopback bind, ran one office pass
        # (gh, hq who, hq claims) after another, from the GitHub allowance every agent shares.
        passes = []
        stop = threading.Event()
        with self.office(), mock.patch.object(dashboard, "_refresh_wake", threading.Event()), \
                mock.patch.object(dashboard, "_refresh_once",
                                  lambda: passes.append(time.monotonic())), \
                mock.patch.object(dashboard, "BIND", "127.0.0.1"), running_server() as base:
            thread = threading.Thread(target=dashboard._refresher, args=(30, stop), daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not passes and time.monotonic() < deadline:
                    time.sleep(0.01)
                for step in range(40):
                    status, _raw, _type = fetch(base, f"/api/mail/feed?hours={0.5 + step * 3.3:g}")
                    self.assertEqual(status, 200)
                    self.assertEqual(fetch(base, "/api/mail/who")[0], 200)
                    time.sleep(0.01)
                time.sleep(0.3)
            finally:
                # A refresher left running past this test would run tools in the tests after it.
                stop.set()
                dashboard._refresh_wake.set()
                thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(passes), 2, "the first pass, and one early pass for all the reads")

    def test_an_unreadable_office_keeps_the_last_timeline_and_says_since_when(self):
        """The timeline is only as good as the office read behind it, and it says so. An
        empty list with no reason is the answer that made the Overview claim a working farm
        had been silent for a day."""
        with self.office() as box:
            dashboard._refresh_once()
            good = dashboard.mail_feed()
            office = dashboard.mail_boxes()
            self.assertIsNone(good["error"])
            box.fail.write_text("")
            dashboard._refresh_once()
            stale = dashboard.mail_feed()
            self.assertEqual(stale["events"], good["events"])
            # as stale as the office read behind it, to the second, not as stale as the
            # assembly that followed it
            self.assertEqual(stale["stale_since"], office["at"])
            self.assertEqual(stale["stale_since"], dashboard.mail_boxes()["stale_since"])
            self.assertIn("could not resolve host", stale["error"])
            self.assertFalse(stale["pending"])

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

    def test_a_sent_message_wakes_the_office_reader_rather_than_waiting_a_cadence(self):
        # The message is in the office at once, but this dashboard reads the office every 45
        # seconds, so without the wake a sender watches their own message take that long to
        # appear in the thread they just sent it to.
        wake = RecordingEvent()
        with self.office():
            with mock.patch.object(dashboard, "_refresh_wake", wake):
                dashboard.mail_refresh()
                status, payload = dashboard.mail_send({"to": "winston", "text": "preview is up"})
                self.assertEqual(status, 200, payload)
                self.assertTrue(payload["refreshing"])
                self.assertEqual(wake.wakes, 1)
                self.assertEqual(dashboard.mail_send({"to": "stranger", "text": "x"})[0], 400)
                self.assertEqual(wake.wakes, 1, "a refused send has nothing to wait for")

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

        stop = threading.Event()
        with mock.patch.object(dashboard, "_refresh_once", count):
            thread = threading.Thread(target=dashboard._refresher, args=(30, stop), daemon=True)
            thread.start()
            try:
                for _ in range(200):
                    if passes:
                        break
                    time.sleep(0.01)
                dashboard._refresh_wake.set()
                for _ in range(200):
                    if len(passes) > 1:
                        break
                    time.sleep(0.01)
            finally:
                # A refresher left running past this test spawns tools into every test that
                # follows it, and moves the snapshots they are asserting about.
                stop.set()
                dashboard._refresh_wake.set()
                thread.join(timeout=5)
        self.assertGreater(len(passes), 1, "a woken refresher must not wait out its sleep")
        self.assertFalse(thread.is_alive(), "the refresher must stop when it is told to")

class ReadsCostNothingTest(unittest.TestCase):
    """The page redraws every few seconds. Every read route must therefore be pure memory and
    files: one tool call on a read path is a few thousand an hour, against the API budget every
    agent on this machine shares."""

    # EVERY read route, with none held back. The panes that ask the machine something
    # (/api/sweep, /api/mode, /api/metrics) are served from their own refreshers.
    QUIET_ROUTES = ("/", "/index.html", "/static/app.js", "/api/access", "/api/version",
                    "/api/config", "/api/health", "/api/projects", "/api/identities",
                    "/api/fleet", "/api/agent?slug=lane-1", "/api/agent/log?slug=lane-1",
                    "/api/mail/boxes", "/api/mail/thread?box=winston", "/api/mail/feed?hours=24",
                    "/api/mail/who", "/api/services",
                    "/api/sweep", "/api/mode", "/api/metrics", "/api/accounts", "/api/models",
                    "/api/jobs", "/api/jobs/drain-1", "/api/power/preview?action=drain",
                    "/api/accounts/login-state", "/api/machines", "/api/hosts")

    def test_no_read_route_runs_a_tool_touches_the_network_or_writes_to_disk(self):
        mail = DashboardMailTest("test_the_office_timeline_is_assembled_here_and_never_by_running_hq_feed")
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
            (state / "jobs").mkdir()
            (state / "jobs" / "drain-1.json").write_text(json.dumps(
                {"id": "drain-1", "action": "drain", "state": "done",
                 "started_at": "2026-09-22T08:00:00Z", "ended_at": "2026-09-22T08:01:00Z",
                 "output": "", "pid": os.getpid()}))
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
        mail = DashboardMailTest("test_the_office_timeline_is_assembled_here_and_never_by_running_hq_feed")
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

    def test_every_time_a_mail_answer_carries_parses_as_a_timestamp(self):
        mail = DashboardMailTest("test_the_office_timeline_is_assembled_here_and_never_by_running_hq_feed")
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

    def test_a_reading_that_has_not_changed_keeps_the_moment_it_already_implied(self):
        # hq reports an AGE, so deriving a stamp from it again a second later moves it a second:
        # every row carrying it redraws, and two snapshots of a quiet office never compare equal.
        mail = DashboardMailTest("test_the_office_timeline_is_assembled_here_and_never_by_running_hq_feed")
        mail.setUp()
        self.addCleanup(mail.doCleanups)
        with mail.office():
            dashboard.who_refresh()
            first = dashboard.mail_who()["sessions"]
            time.sleep(1.1)
            dashboard.who_refresh()
            self.assertEqual(dashboard.mail_who()["sessions"], first)

    def test_a_session_says_when_it_was_last_seen_as_well_as_how_long_ago(self):
        now = 1789996000.0
        sessions = dashboard._parse_who("winston  live  updated  2.0h ago  building\n", now=now)
        self.assertEqual(sessions[0]["age_hours"], 2.0)
        self.assertEqual(sessions[0]["since"], dashboard._iso(now - 7200))

    def test_a_stale_envelope_carries_the_moment_it_stopped_being_true(self):
        mail = DashboardMailTest("test_the_office_timeline_is_assembled_here_and_never_by_running_hq_feed")
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

    @staticmethod
    def _with_host(base, method, path, host, token=None):
        """(status, body) for one request carrying exactly this Host header, or none at all when
        `host` is None. urllib would fill in its own."""
        connection = http.client.HTTPConnection(base.rsplit("/", 1)[-1], timeout=10)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            if host is not None:
                connection.putheader("Host", host)
            if token is not None:
                connection.putheader("Authorization", "Bearer " + token)
            if method == "POST":
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", "15")
            connection.endheaders(b'{"mode":"auto"}' if method == "POST" else None)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_a_loopback_bind_refuses_a_request_for_any_other_host(self):
        # DNS rebinding: a website points a name it owns at 127.0.0.1, and its script then reads
        # this server as if it were that site. Reads need no token here, so the Host header,
        # which the browser fills in with the site's own name, is what refuses it.
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), \
                mock.patch.object(dashboard.MODE, "set_setting") as setter, \
                running_server() as base:
            for host in ("attacker.example", "attacker.example:7878", "127.0.0.1.nip.io:7878",
                         "localhost.attacker.example", "evil@127.0.0.1", "", None, "[::1"):
                for path in ("/api/fleet", "/api/agent?slug=x", "/api/mail/boxes", "/"):
                    status, body = self._with_host(base, "GET", path, host)
                    self.assertEqual(status, 403, (host, path))
                    self.assertIn("only answers on this machine", json.loads(body)["error"])
            # and a write is refused the same way, token or not
            status, _ = self._with_host(base, "POST", "/api/mode", "attacker.example:7878",
                                        token="s3cret")
            self.assertEqual(status, 403)
            setter.assert_not_called()

    def test_this_machines_own_names_pass_on_any_port(self):
        # The page opened on the farm, or through an ssh tunnel on any local port.
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            for host in ("127.0.0.1", "127.0.0.1:17878", "localhost", "localhost:8080",
                         "LOCALHOST:7878", "[::1]", "[::1]:7878"):
                status, body = self._with_host(base, "GET", "/api/identities", host)
                self.assertEqual(status, 200, (host, body))

    def test_a_wide_bind_answers_to_its_own_address_and_still_needs_the_token(self):
        # FLEET_DASH_BIND=tailscale binds an address like this one, and the browser sends it as
        # the Host. The token guards reads there already.
        with mock.patch.object(dashboard, "BIND", "100.64.1.2"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            status, body = self._with_host(base, "GET", "/api/identities", "100.64.1.2:7878",
                                           token="s3cret")
            self.assertEqual(status, 200, body)
            status, body = self._with_host(base, "GET", "/api/identities", "100.64.1.2:7878")
            self.assertEqual(status, 403)
            self.assertIn("token", json.loads(body)["error"])

    def test_which_host_headers_name_this_machine(self):
        for value in ("127.0.0.1", "127.0.0.1:1", "127.0.1.5:7878", "localhost", "LocalHost:80",
                      "[::1]", "[::1]:7878", " localhost:7878 "):
            self.assertTrue(dashboard.host_is_local(value), value)
        for value in ("", None, "attacker.example", "127.0.0.1.nip.io", "localhost.example",
                      "0.0.0.0:7878", "::1", "[::1", "evil@localhost", "localhost:x",
                      "203.0.113.7:7878", "localhost:7878/x"):
            self.assertFalse(dashboard.host_is_local(value), value)

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
        if not socket.has_ipv6:
            self.skipTest("this Python was built without IPv6")
        try:
            # A kernel with IPv6 switched off refuses the socket itself (EAFNOSUPPORT).
            probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        except OSError as exc:
            self.skipTest(f"no IPv6 on this box: {exc}")
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



class ModelsContractTest(unittest.TestCase):
    def test_every_preset_and_every_row_carries_a_terms_word(self):
        for preset in dashboard.MODEL_PRESETS.presets():
            self.assertIn(preset.get("tos_kind"), ("safe", "check", "blocked"), preset["id"])
        # Read from a throwaway farm, never this machine's own catalog. It holds the shipped
        # rows and two this farm wrote before their presets were removed, one with no terms.
        with own_catalog(ModelOrphanTest.CATALOG, ModelOrphanTest.STATE):
            rows = dashboard.engines()
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertIn(row.get("tos_kind"), ("safe", "check", "blocked"), row.get("id"))

    def test_the_terms_word_reads_the_sentence(self):
        kind = dashboard.MODEL_PRESETS.tos_kind
        self.assertEqual(kind("its subscription terms forbid non-interactive use"), "blocked")
        self.assertEqual(kind("HIGH risk of suspension"), "check")
        self.assertEqual(kind("a documented headless mode"), "safe")
        self.assertEqual(kind(""), "check")

    def test_config_names_the_farm_for_the_commands_the_page_hands_out(self):
        payload = dashboard.config_payload()
        self.assertEqual(payload.get("farm_alias"), dashboard.CA.FARM_ALIAS)
        self.assertTrue(payload["farm_alias"])

MACHINES_JSON = {
    "this": {"name": "homestead", "address": "100.64.0.11"},
    "total_monthly_usd": 96,
    "machines": [
        {"name": "homestead", "provider": "this-farm", "user": "farm",
         "address": "100.64.0.11", "size": "", "monthly_usd": 0, "region": "",
         "state": "ready", "detail": "this farm", "checked_at": "2026-09-23T08:00:00Z",
         "finish_command": "", "tunnel_command": ""},
        {"name": "nursery", "provider": "do-droplet", "user": "farm",
         "address": "203.0.113.7", "size": "s-4vcpu-8gb", "monthly_usd": 48, "region": "fra1",
         "state": "needs-login", "detail": "first boot finished",
         "checked_at": "2026-09-23T08:00:00Z",
         "finish_command": "ssh -t farm@203.0.113.7 'gh auth login'", "tunnel_command": ""},
        {"name": "orchard", "provider": "do-droplet", "user": "farm",
         "address": "203.0.113.9", "size": "s-4vcpu-8gb", "monthly_usd": 48, "region": "fra1",
         "state": "creating", "detail": "the provider is building it",
         "checked_at": "2026-09-23T08:00:00Z", "finish_command": "", "tunnel_command": ""},
    ],
}

HOSTS_JSON = {
    "providers": [
        {"id": "do-droplet", "label": "DigitalOcean Droplet", "job": "machine", "stage": "ga",
         "cli_installed": True, "login_state": "logged_in", "account": "ada@example.com",
         "detail": "", "checked_at": "2026-09-23T08:00:00Z",
         "login": "doctl auth init --context murmur",
         "install": "snap install doctl", "terms": "billed per second",
         "pricing": "$48 a month for 4 vCPU", "sizes": [], "regions": ["fra1"]},
        {"id": "ssh", "label": "Your own machine", "job": "machine", "stage": "ga",
         "cli_installed": False, "login_state": "not_installed", "account": None,
         "detail": "ssh is not on this farm's PATH", "checked_at": "2026-09-23T08:00:00Z",
         "login": "none: your own SSH key reaches the machine",
         "install": "ssh comes with every Linux and macOS; nothing to install",
         "terms": "your own machine", "pricing": "whatever you already pay for the box",
         "sizes": [], "regions": []},
    ],
}

PUBKEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB2kLMuFlKR6oCbHVPfZmUMZqTVpGkaAxOaCwIKgHRFC "
          "ada@laptop")


class HostingCase(unittest.TestCase):
    """The shared fixture: a farm whose FLEET_STATE, FLEET_CONFIG and HOME are all temporary,
    whose PATH holds fake tools and nothing else, and whose `fleet` prints the two JSON shapes
    of the design record's section 7 from files this test wrote.

    The provider CLIs are on that PATH too, as fakes that record and do nothing. Nothing here
    may reach a provider or spend a cent, and the cheapest proof of that is a PATH where the
    real ones cannot be found and a recording of every argv that was tried.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.state = self.root / "state"
        self.config = self.root / "config"
        (self.state / "jobs").mkdir(parents=True)
        self.config.mkdir()
        (self.config / "projects.toml").write_text('[alpha]\nrepo = "acme/alpha"\n')
        self.machines_file = self.root / "machines.json"
        self.hosts_file = self.root / "hosts.json"
        self.machines_file.write_text(json.dumps(MACHINES_JSON))
        self.hosts_file.write_text(json.dumps(HOSTS_JSON))
        for target, value in (("STATE", str(self.state)), ("CONFIG", str(self.config))):
            patcher = mock.patch.object(dashboard, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for snapshot, blank in ((dashboard._hosting_machines_snapshot,
                                 {"this": {}, "total_monthly_usd": 0, "machines": []}),
                                (dashboard._hosting_hosts_snapshot, {"providers": []})):
            payload = {"at": None, "tried": False, "stale_since": None, "error": None}
            payload.update(blank)
            patcher = mock.patch.dict(snapshot, payload, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    @contextlib.contextmanager
    def farm(self, **env):
        """The fake tools, with the two listings pointed at this test's fixture files."""
        settings = {"FLEET_FAKE_MACHINES": str(self.machines_file),
                    "FLEET_FAKE_HOSTS": str(self.hosts_file)}
        settings.update({name: value for name, value in env.items() if value is not None})
        providers = {name: 'exit 0\n' for name in
                     ("doctl", "ssh", "scp", "ssh-keygen")}
        with fake_tools(dict(providers, fleet=FLEET_FAKE), env=settings) as box:
            with mock.patch.object(dashboard, "FLEET_HOME", str(box.root)):
                self.box = box
                yield box

    def recorded(self, box):
        return [line for line in box.calls.read_text().splitlines() if line.strip()]

    def argv(self, box):
        """Every argv the fake fleet was handed, as lists."""
        return [json.loads(line[len("fleet-argv "):]) for line in self.recorded(box)
                if line.startswith("fleet-argv ")]

    def finish(self, job_id, seconds=10):
        deadline = time.time() + seconds
        while time.time() < deadline:
            record = dashboard.read_job(job_id)[1]
            if record.get("state") != "running":
                return record
            time.sleep(0.02)
        self.fail(f"job {job_id} never finished")

    def only_job(self, action):
        """The one job record this test left for `action`, read from the job directory."""
        records = [json.loads(path.read_text()) for path in (self.state / "jobs").glob("*.json")]
        records = [record for record in records if record.get("action") == action]
        self.assertEqual(len(records), 1, records)
        return records[0]

    def done(self, status, payload, seconds=10):
        """A started job, run to its end. The assertion is here so every caller reads the
        refusal rather than a KeyError when a route answers 400."""
        self.assertEqual(status, 202, payload)
        return self.finish(payload["job"]["id"], seconds)


class HostingProvidersTest(unittest.TestCase):
    """The server's guard map against the library's catalog. The server never imports the
    catalog at run time, so this test is what keeps the two from drifting: every id and job
    `fleet/lib/host_presets.py` ships must be in the guard, and the guard may name nothing the
    catalog does not ship."""

    def test_the_guard_map_is_the_catalog_ids_and_jobs(self):
        path = os.path.join(dashboard.FLEET_HOME, "lib", "host_presets.py")
        spec = importlib.util.spec_from_file_location("host_presets_under_test", path)
        catalog = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(catalog)
        shipped = {row["id"]: row["job"] for row in catalog.presets()}
        self.assertEqual(dashboard.HOSTING_PROVIDERS, shipped)


class HostingTidyTest(unittest.TestCase):
    """The hosting files: no trailing whitespace in the server and its tests, and the
    operations paragraph on the snapshot still wraps like the rest of that document."""

    def test_no_line_ends_in_whitespace(self):
        for name in ("server.py", "test_server.py"):
            with open(os.path.join(dashboard.HERE, name)) as handle:
                for number, line in enumerate(handle, 1):
                    self.assertEqual(line.rstrip("\n"), line.rstrip(), f"{name}:{number}")

    def test_the_snapshot_paragraph_wraps_near_a_hundred(self):
        path = os.path.join(dashboard.FLEET_HOME, "docs", "OPERATIONS.md")
        with open(path) as handle:
            text = handle.read()
        start = text.find("**Read, from the snapshot.**")
        if start < 0:
            self.skipTest("docs/OPERATIONS.md has no snapshot paragraph to measure")
        paragraph = text[start:text.index("\n\n", start)]
        for line in paragraph.splitlines():
            self.assertLessEqual(len(line), 100, line)


class HostingSnapshotTest(HostingCase):
    """The two listings, read on a thread and served from memory. No GET may run a tool: the
    page redraws every few seconds, and a droplet listing is a request to a provider."""

    def test_one_pass_publishes_both_listings_in_the_shape_the_page_reads(self):
        with self.farm() as box:
            dashboard.hosting_refresh()
            self.assertEqual(self.argv(box),
                             [["machines", "list", "--json"], ["hosts", "list", "--json"]])
        machines = dashboard.hosting_machines()
        self.assertFalse(machines["pending"])
        self.assertIsNone(machines["error"])
        self.assertIsNone(machines["stale_since"])
        self.assertIsNotNone(dashboard.parse_iso(machines["at"]))
        self.assertEqual(machines["this"], MACHINES_JSON["this"])
        self.assertEqual(machines["total_monthly_usd"], 96)
        self.assertEqual([row["name"] for row in machines["machines"]],
                         ["homestead", "nursery", "orchard"])
        self.assertEqual(machines["machines"][1]["state"], "needs-login")
        hosts = dashboard.hosting_hosts()
        self.assertFalse(hosts["pending"])
        self.assertEqual([row["id"] for row in hosts["providers"]], ["do-droplet", "ssh"])
        self.assertEqual(hosts["providers"][1]["login_state"], "not_installed")

    def test_the_amended_fields_reach_the_page_untouched(self):
        """Machine rows carry `provider_id`, provider rows carry `cli`, `color`, `engines` and
        `docs`, and each size carries `default`. The CLI emits them, this server passes them
        through as they are, and the page relies on them."""
        machines = json.loads(self.machines_file.read_text())
        machines["machines"][1]["provider_id"] = 4001
        machines["machines"][2]["provider_id"] = None
        self.machines_file.write_text(json.dumps(machines))
        hosts = json.loads(self.hosts_file.read_text())
        droplet = hosts["providers"][0]
        droplet.update({"cli": "doctl", "color": "#0069ff", "engines": ["claude", "codex"],
                        "docs": "https://docs.digitalocean.com/reference/doctl/"})
        droplet["sizes"] = [
            {"slug": "s-2vcpu-4gb", "monthly_usd": 24, "default": False},
            {"slug": "s-4vcpu-8gb", "monthly_usd": 48, "default": True}]
        self.hosts_file.write_text(json.dumps(hosts))
        with self.farm():
            dashboard.hosting_refresh()
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
                _, served_machines = fetch_json(base, "/api/machines", token="s3cret")
                _, served_hosts = fetch_json(base, "/api/hosts", token="s3cret")
        self.assertEqual([row.get("provider_id", "absent") for row in served_machines["machines"]],
                         ["absent", 4001, None])
        self.assertEqual(served_machines["machines"], machines["machines"])
        served = served_hosts["providers"][0]
        self.assertEqual(served["cli"], "doctl")
        self.assertEqual(served["color"], "#0069ff")
        self.assertEqual(served["engines"], ["claude", "codex"])
        self.assertEqual(served["docs"], droplet["docs"])
        self.assertEqual([size["default"] for size in served["sizes"]], [False, True])
        self.assertEqual(served_hosts["providers"], hosts["providers"])

    def test_before_the_first_pass_both_answers_say_pending_and_not_empty(self):
        for answer in (dashboard.hosting_machines(), dashboard.hosting_hosts()):
            self.assertTrue(answer["pending"])
            self.assertIsNone(answer["at"])
            self.assertIsNone(answer["error"])
        self.assertEqual(dashboard.hosting_machines()["machines"], [])
        self.assertEqual(dashboard.hosting_hosts()["providers"], [])

    def test_a_failed_pass_keeps_the_last_good_answer_and_says_when_it_was_true(self):
        with self.farm() as box:
            dashboard.hosting_refresh()
            # Each listing is a snapshot of its own, stamped when its own run ended. The two runs
            # can straddle a second, so each answer is held to its own last good time.
            good = {"machines": dashboard.hosting_machines()["at"],
                    "hosts": dashboard.hosting_hosts()["at"]}
            box.calls.write_text("")
            with mock.patch.dict(os.environ,
                                 {"FLEET_FAKE_FAIL": "doctl: 401 unable to authenticate"}):
                dashboard.hosting_refresh()
        for name, answer in (("machines", dashboard.hosting_machines()),
                             ("hosts", dashboard.hosting_hosts())):
            self.assertFalse(answer["pending"])
            self.assertIsNotNone(dashboard.parse_iso(good[name]), name)
            self.assertEqual(answer["stale_since"], good[name], name)
            self.assertEqual(answer["at"], good[name], f"{name}: a failed pass moved the clock")
            self.assertIn("unable to authenticate", answer["error"])
            self.assertEqual(answer["error"].count("\n"), 0)
            self.assertNotIn("Traceback", json.dumps(answer))
        # and the rows a person was looking at are still there, now labelled stale
        self.assertEqual(len(dashboard.hosting_machines()["machines"]), 3)
        self.assertEqual(len(dashboard.hosting_hosts()["providers"]), 2)

    def test_a_listing_that_is_not_json_is_a_sentence_and_not_a_traceback(self):
        self.machines_file.write_text("doctl: command not found\n")
        self.hosts_file.write_text("[]\n")
        with self.farm():
            dashboard.hosting_refresh()
        machines = dashboard.hosting_machines()
        self.assertEqual(machines["error"], "fleet machines list did not answer with JSON")
        self.assertEqual(machines["machines"], [])
        hosts = dashboard.hosting_hosts()
        self.assertEqual(hosts["error"], "fleet hosts list did not answer with a JSON object")
        self.assertNotIn("Traceback", json.dumps([machines, hosts]))

    def test_neither_read_route_runs_a_tool(self):
        with self.farm() as box:
            dashboard.hosting_refresh()
            box.calls.write_text("")
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
                for route in ("/api/machines", "/api/hosts", "/api/machines", "/api/hosts"):
                    status, payload = fetch_json(base, route, token="s3cret")
                    self.assertEqual(status, 200, payload)
                    self.assertFalse(payload["pending"])
                status, config = fetch_json(base, "/api/config")
                self.assertEqual(status, 200)
            self.assertEqual(box.calls.read_text(), "")
        self.assertEqual(config["hosting"], {"machines": 3})

    def test_the_config_counts_are_zero_before_the_first_pass(self):
        self.assertEqual(dashboard.config_payload()["hosting"], {"machines": 0})

    def test_the_refresher_thread_passes_and_can_be_stopped(self):
        stop = threading.Event()
        with self.farm() as box:
            thread = threading.Thread(
                target=dashboard._hosting_refresher, args=(0.01, stop), daemon=True)
            thread.start()
            deadline = time.time() + 5
            while time.time() < deadline and not dashboard.hosting_machines()["at"]:
                time.sleep(0.01)
            stop.set()
            dashboard._hosting_wake.set()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertIn(["hosts", "list", "--json"], self.argv(box))


class HostingWriteTest(HostingCase):
    """Nine writes, each a `fleet` command as a job keyed by the resource it touches. The
    assertion that matters is the argv, exactly: a list, in order, with nothing added."""

    def test_planning_a_droplet_answers_the_cli_json_synchronously(self):
        with self.farm() as box:
            status, payload = dashboard.machines_plan(
                {"provider": "do-droplet", "name": "nursery", "size": "s-4vcpu-8gb",
                 "region": "fra1", "ssh_public": PUBKEY})
            self.assertEqual(status, 200, payload)
            argv = self.argv(box)[0]
            handed = self.parsed(box, "machines plan")
        # The CLI's own JSON, at the top level and nothing added: design section 7 says the
        # route "returns its JSON", and the page reads `monthly_usd` straight off the answer.
        self.assertEqual(payload["monthly_usd"], 48)
        self.assertEqual(payload["price_source"], "live")
        self.assertIn("cloud_init", payload)
        self.assertNotIn("plan", payload)
        self.assertNotIn("job", payload)
        record = self.only_job("machines_plan")
        self.assertEqual(record["state"], "done")
        self.assertEqual(record["key"], "machine:nursery")
        key_file = argv[argv.index("--pubkey-file") + 1]
        self.assertEqual(argv, ["machines", "plan", "--provider", "do-droplet",
                                "--name", "nursery", "--size", "s-4vcpu-8gb",
                                "--region", "fra1", "--pubkey-file", key_file, "--json"])
        self.assertFalse(os.path.exists(key_file), "the key file outlived the plan")
        self.assertEqual(handed["pubkey_text"], PUBKEY)
        self.assertEqual(handed["pubkey_mode"], "0o600")

    def test_a_plan_without_a_public_key_is_still_a_plan(self):
        with self.farm() as box:
            status, payload = dashboard.machines_plan(
                {"provider": "do-droplet", "name": "nursery", "size": "s-4vcpu-8gb",
                 "region": "fra1"})
            self.assertEqual(status, 200, payload)
            self.assertEqual(self.argv(box)[0],
                             ["machines", "plan", "--provider", "do-droplet", "--name",
                              "nursery", "--size", "s-4vcpu-8gb", "--region", "fra1", "--json"])

    def test_a_refusing_plan_is_a_sentence_and_never_a_traceback(self):
        with self.farm(FLEET_FAKE_FAIL="fleet machines plan: doctl is not logged in"):
            status, payload = dashboard.machines_plan(
                {"provider": "do-droplet", "name": "nursery", "size": "s-4vcpu-8gb",
                 "region": "fra1"})
        self.assertEqual(status, 400)
        self.assertIn("not logged in", payload["error"])
        self.assertNotIn("Traceback", json.dumps(payload))

    def parsed(self, box, what):
        head = "fleet-parsed " + what + " "
        rows = [json.loads(line[len(head):]) for line in self.recorded(box)
                if line.startswith(head)]
        self.assertTrue(rows, f"the fake fleet never parsed a '{what}'")
        return rows[-1]

    def test_creating_a_droplet_names_the_price_and_hands_the_key_through_a_file(self):
        with self.farm() as box:
            status, payload = dashboard.machines_create(
                {"provider": "do-droplet", "name": "orchard", "size": "s-4vcpu-8gb",
                 "region": "fra1", "ssh_public": PUBKEY, "confirm_usd": 48})
            record = self.done(status, payload)
            argv = self.argv(box)[0]
            handed = self.parsed(box, "machines create")
        self.assertEqual(record["state"], "done", record)
        self.assertEqual(record["key"], "machine:orchard")
        self.assertEqual(payload["name"], "orchard")
        key_file = argv[argv.index("--pubkey-file") + 1]
        self.assertEqual(argv, ["machines", "create", "--provider", "do-droplet",
                                "--name", "orchard", "--size", "s-4vcpu-8gb",
                                "--region", "fra1", "--pubkey-file", key_file,
                                "--confirm-usd", "48"])
        self.assertEqual(handed["pubkey_text"], PUBKEY)
        self.assertEqual(handed["pubkey_mode"], "0o600")
        self.assertFalse(os.path.exists(key_file), "the key file outlived the job")

    def test_a_price_with_cents_reaches_the_cli_as_the_person_typed_it(self):
        with self.farm() as box:
            status, payload = dashboard.machines_create(
                {"provider": "do-droplet", "name": "orchard", "size": "s-2vcpu-4gb",
                 "region": "fra1", "ssh_public": PUBKEY, "confirm_usd": "24.5"})
            self.done(status, payload)
            self.assertEqual(self.argv(box)[0][-2:], ["--confirm-usd", "24.5"])

    def test_a_confirmed_price_is_never_reformatted_on_its_way_to_the_cli(self):
        """The CLI refuses a price that differs from the live one, so a rounding here would
        refuse a person who typed the right number."""
        for typed, handed in (("12345.67", "12345.67"), ("48.00", "48.00"), (48, "48"),
                              (" 24.5 ", "24.5"), (12.34, "12.34")):
            self.assertEqual(dashboard._confirm_usd(typed), (handed, ""), typed)
        for refused in ("1e-7", "1_000", "+48", "0x30", "inf", "48.", ".5", True):
            self.assertEqual(dashboard._confirm_usd(refused)[0], "", refused)

    def test_a_price_with_leading_zeros_is_refused_with_the_number_to_type(self):
        self.assertEqual(dashboard._confirm_usd("00048"),
                         ("", "write the price without leading zeros, as 48"))
        self.assertEqual(dashboard._confirm_usd("000.5"),
                         ("", "write the price without leading zeros, as 0.5"))
        self.assertEqual(dashboard._confirm_usd("0.5"), ("0.5", ""))

    def test_a_machine_of_your_own_is_registered_and_buys_nothing(self):
        with self.farm() as box:
            status, payload = dashboard.machines_create(
                {"provider": "ssh", "name": "attic", "target": "farm@192.0.2.4"})
            record = self.done(status, payload)
            self.assertEqual(self.argv(box)[0],
                             ["machines", "add", "--name", "attic", "--target", "farm@192.0.2.4"])
        self.assertEqual(record["state"], "done", record)
        self.assertEqual(record["key"], "machine:attic")

    def test_a_machine_of_your_own_may_name_its_port(self):
        with self.farm() as box:
            status, payload = dashboard.machines_create(
                {"provider": "ssh", "name": "attic", "target": "farm@192.0.2.4", "port": "2222"})
            self.done(status, payload)
            self.assertEqual(self.argv(box)[0],
                             ["machines", "add", "--name", "attic", "--target", "farm@192.0.2.4",
                              "--port", "2222"])

    def test_check_adopt_and_forget_are_one_verb_and_one_name(self):
        for route, verb in ((dashboard.machines_check, "check"),
                            (dashboard.machines_adopt, "adopt"),
                            (dashboard.machines_forget, "forget")):
            with self.farm() as box:
                status, payload = route({"name": "nursery"})
                record = self.done(status, payload)
                self.assertEqual(self.argv(box)[0], ["machines", verb, "nursery"], verb)
            self.assertEqual(record["state"], "done", record)
            self.assertEqual(record["key"], "machine:nursery")

    def test_destroying_repeats_the_name_to_the_cli_as_well(self):
        with self.farm() as box:
            status, payload = dashboard.machines_destroy({"name": "nursery",
                                                          "confirm": "nursery"})
            record = self.done(status, payload)
            self.assertEqual(self.argv(box)[0],
                             ["machines", "destroy", "nursery", "--confirm", "nursery"])
        self.assertEqual(record["state"], "done", record)

    def test_checking_a_provider_is_keyed_by_the_provider(self):
        with self.farm() as box:
            status, payload = dashboard.hosts_check({"provider": "do-droplet"})
            record = self.done(status, payload)
            self.assertEqual(self.argv(box)[0], ["hosts", "check", "do-droplet"])
        self.assertEqual(record["key"], "host:do-droplet")
        self.assertEqual(payload["provider"], "do-droplet")

    def test_a_second_machine_may_be_added_while_the_first_one_boots(self):
        """The interlock is the machine, not the verb: one droplet booting must not stop the
        next one from being ordered, and must stop a second press of its own Check."""
        gate = self.state / "gate"
        blocker = self.state / "slow-fleet"
        blocker.write_text('#!/bin/sh\nwhile [ ! -f "%s" ]; do sleep 0.02; done\n' % gate)
        blocker.chmod(0o755)
        with self.farm():
            with mock.patch.object(dashboard, "fleet_bin", return_value=str(blocker)):
                status, first = dashboard.machines_check({"name": "nursery"})
                self.assertEqual(status, 202, first)
                again, refusal = dashboard.machines_check({"name": "nursery"})
                self.assertEqual(again, 409)
                self.assertIn("already running", refusal["error"])
                other, second = dashboard.machines_create(
                    {"provider": "ssh", "name": "attic", "target": "farm@192.0.2.4"})
                self.assertEqual(other, 202, second)
                gate.write_text("go")
                self.finish(first["job"]["id"])
                self.finish(second["job"]["id"])

    def test_a_job_that_ends_asks_the_snapshot_to_look_again(self):
        """A row that has just gone `creating` must not sit there for 45 seconds."""
        wake = RecordingEvent()
        with self.farm(), mock.patch.object(dashboard, "_hosting_wake", wake):
            status, payload = dashboard.machines_check({"name": "nursery"})
            self.done(status, payload)
            deadline = time.time() + 5
            while time.time() < deadline and not wake.wakes:
                time.sleep(0.02)
            self.assertTrue(wake.wakes, "the snapshot was never asked to look again")

    def test_every_write_needs_the_token(self):
        bodies = [("/api/machines/plan", {"provider": "do-droplet", "name": "nursery",
                                          "size": "s-4vcpu-8gb", "region": "fra1"}),
                  ("/api/machines", {"provider": "ssh", "name": "attic",
                                     "target": "farm@192.0.2.4"}),
                  ("/api/machines/check", {"name": "nursery"}),
                  ("/api/machines/destroy", {"name": "nursery", "confirm": "nursery"}),
                  ("/api/machines/adopt", {"name": "nursery"}),
                  ("/api/machines/forget", {"name": "nursery"}),
                  ("/api/hosts/check", {"provider": "do-droplet"})]
        with self.farm() as box:
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
                for route, body in bodies:
                    status, payload = fetch_json(base, route, method="POST", body=body)
                    self.assertEqual(status, 403, route)
                    self.assertNotIn("Traceback", json.dumps(payload))
                self.assertEqual(box.calls.read_text(), "", "a refused write still ran a tool")
                # and with it, each one answers for itself
                for route, body in bodies:
                    status, payload = fetch_json(base, route, token="s3cret", method="POST",
                                                 body=body)
                    self.assertIn(status, (200, 202), (route, payload))
                    if "job" in payload:
                        self.finish(payload["job"]["id"])
                    self.assertNotIn("Traceback", json.dumps(payload))

    def test_a_cross_site_write_is_refused_whatever_token_it_carries(self):
        with self.farm() as box:
            with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                    mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
                status, payload = fetch_json(
                    base, "/api/machines/check", token="s3cret", method="POST",
                    body={"name": "nursery"}, headers={"Origin": "https://evil.example"})
                self.assertEqual(status, 403, payload)
            self.assertEqual(box.calls.read_text(), "")


class HostingRefusalTest(HostingCase):
    """Everything a body can get wrong. Each one is a 400 with a sentence, and not one word of
    any of them reaches a command line."""

    def refusals(self, route, bodies):
        with self.farm() as box:
            for body in bodies:
                status, payload = route(body)
                self.assertEqual(status, 400, (body, payload))
                self.assertIn("error", payload)
                self.assertNotIn("Traceback", json.dumps(payload))
            self.assertEqual(box.calls.read_text(), "",
                             "a refused body still reached the command line")

    def test_a_name_that_is_not_a_machine_name_never_reaches_an_argv(self):
        self.refusals(dashboard.machines_check,
                      [{}, {"name": ""}, {"name": "-rf"}, {"name": "../../etc/passwd"},
                       {"name": "Nursery"}, {"name": "n"}, {"name": "a" * 41},
                       {"name": "nursery; rm -rf /"}, {"name": "nurse ry"},
                       {"name": "nursery\nmachines destroy homestead"}])

    def test_a_provider_this_farm_does_not_know_is_refused(self):
        self.refusals(dashboard.hosts_check,
                      [{}, {"provider": ""}, {"provider": "aws"}, {"provider": "--help"},
                       {"provider": "do droplet"}])

    def test_a_provider_this_farm_does_not_ship_can_neither_plan_nor_be_checked(self):
        for provider in ("aws", "some-cloud"):
            self.refusals(dashboard.machines_plan,
                          [{"provider": provider, "name": "nursery", "size": "s-4vcpu-8gb",
                            "region": "fra1"}])
            self.refusals(dashboard.hosts_check, [{"provider": provider}])

    def test_a_listed_provider_without_a_job_is_not_a_machine(self):
        """`fleet hosts list` may report an id this server has never heard of, and the snapshot
        accepts it; a row without a `job` is still refused by the machine routes, because an
        empty job is not a match."""
        listing = json.loads(self.hosts_file.read_text())
        listing["providers"].append({"id": "hetzner", "label": "Hetzner"})
        self.hosts_file.write_text(json.dumps(listing))
        with self.farm():
            dashboard.hosting_refresh()
        self.assertIn("hetzner", [row["id"] for row in dashboard.hosting_hosts()["providers"]])
        self.refusals(dashboard.machines_plan,
                      [{"provider": "hetzner", "name": "nursery", "size": "s-4vcpu-8gb",
                        "region": "fra1"}])
        self.refusals(dashboard.machines_create,
                      [{"provider": "hetzner", "name": "nursery", "size": "s-4vcpu-8gb",
                        "region": "fra1", "ssh_public": PUBKEY, "confirm_usd": 48}])

    def test_a_size_or_a_region_that_is_not_a_slug_is_refused(self):
        base = {"provider": "do-droplet", "name": "nursery", "size": "s-4vcpu-8gb",
                "region": "fra1"}
        self.refusals(dashboard.machines_plan,
                      [dict(base, size=""), dict(base, size="s"), dict(base, size="S-4VCPU"),
                       dict(base, size="s-4vcpu-8gb; doctl"), dict(base, size="a" * 33),
                       dict(base, region=""), dict(base, region="--force"),
                       dict(base, region="fra1 nyc3")])

    def test_a_droplet_without_a_public_key_is_refused_with_the_reason(self):
        with self.farm() as box:
            status, payload = dashboard.machines_create(
                {"provider": "do-droplet", "name": "orchard", "size": "s-4vcpu-8gb",
                 "region": "fra1", "confirm_usd": 48})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"],
                             "Your SSH public key is how your laptop reaches the machine.")
            self.assertEqual(box.calls.read_text(), "")

    def test_a_public_key_that_is_not_one_is_refused(self):
        base = {"provider": "do-droplet", "name": "orchard", "size": "s-4vcpu-8gb",
                "region": "fra1", "confirm_usd": 48}
        self.refusals(dashboard.machines_create,
                      [dict(base, ssh_public="hello"),
                       dict(base, ssh_public="-----BEGIN OPENSSH PRIVATE KEY-----"),
                       dict(base, ssh_public="ssh-dss AAAAB3NzaC1kc3M= ada@laptop"),
                       dict(base, ssh_public=PUBKEY + "\nssh-rsa AAAA= second@key"),
                       dict(base, ssh_public="ssh-ed25519 $(doctl account get) ada")])

    def test_the_public_key_field_is_named_so_the_classifier_lets_it_through(self):
        """`pubkey` carries the word "key" and is refused by the models routes' classifier,
        which is exactly why the field is `ssh_public`. Both halves are the contract."""
        with self.farm() as box:
            status, payload = dashboard.machines_create(
                {"provider": "do-droplet", "name": "orchard", "size": "s-4vcpu-8gb",
                 "region": "fra1", "confirm_usd": 48, "pubkey": PUBKEY})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], dashboard.HOSTING_KEY_REFUSAL)
            self.assertEqual(box.calls.read_text(), "")

    def test_a_body_that_carries_a_secret_is_refused_and_the_secret_is_not_echoed(self):
        secret = "sk-ant-oat01-" + "z" * 40
        bodies = [{"name": "nursery", "token": secret},
                  {"name": "nursery", "api_key": secret},
                  {"name": "nursery", "CLAUDE_CODE_OAUTH_TOKEN": secret},
                  {"name": "nursery", "Provider-Secret": secret},
                  {"name": "nursery", "password": secret},
                  {"name": "nursery", "credentials": secret}]
        with self.farm() as box:
            for body in bodies:
                for route in (dashboard.machines_check, dashboard.machines_adopt,
                              dashboard.machines_forget, dashboard.machines_plan,
                              dashboard.machines_create, dashboard.hosts_check,
                              dashboard.machines_destroy,
                              lambda sent: dashboard.machines_destroy(
                                  dict(sent, confirm=sent["name"]))):
                    # destroy twice: without its confirmation, and with a matching one, so the
                    # classifier is proved to run before the confirm check and not behind it
                    status, payload = route(body)
                    self.assertEqual(status, 400, (route, body))
                    # The whole answer is that one sentence: not the value, and not the
                    # field's name either, which a page would happily draw back on screen.
                    self.assertEqual(payload, {"error": dashboard.HOSTING_KEY_REFUSAL})
                    self.assertNotIn(secret, json.dumps(payload))
            self.assertEqual(box.calls.read_text(), "")

    def test_a_token_typed_into_the_wrong_box_is_not_echoed_in_the_refusal(self):
        """The classifier reads field names, so a token pasted into `size` passes it and meets
        the slug check, whose sentence quotes what was typed. That quote is scrubbed."""
        secret = "sk-ant-oat01-" + "z" * 40
        base = {"provider": "do-droplet", "name": "nursery", "size": "s-4vcpu-8gb",
                "region": "fra1"}
        cases = [(dashboard.machines_plan, dict(base, size=secret)),
                 (dashboard.machines_plan, dict(base, region=secret)),
                 (dashboard.machines_plan, dict(base, provider=secret)),
                 (dashboard.hosts_check, {"provider": secret})]
        with self.farm() as box:
            for route, body in cases:
                status, payload = route(body)
                self.assertEqual(status, 400, (route, body))
                self.assertNotIn(secret[:20], json.dumps(payload))
                self.assertIn("[redacted]", payload["error"])
            self.assertEqual(box.calls.read_text(), "")

    def test_destroying_is_refused_unless_the_name_is_typed_back(self):
        self.refusals(dashboard.machines_destroy,
                      [{"name": "nursery"}, {"name": "nursery", "confirm": ""},
                       {"name": "nursery", "confirm": "yes"},
                       {"name": "nursery", "confirm": "homestead"},
                       {"name": "", "confirm": ""}, {"confirm": "nursery"}])

    def test_a_price_that_is_not_a_number_is_refused(self):
        base = {"provider": "do-droplet", "name": "orchard", "size": "s-4vcpu-8gb",
                "region": "fra1", "ssh_public": PUBKEY}
        self.refusals(dashboard.machines_create,
                      [base, dict(base, confirm_usd=""), dict(base, confirm_usd="free"),
                       dict(base, confirm_usd=0), dict(base, confirm_usd=-48),
                       dict(base, confirm_usd="48; doctl"), dict(base, confirm_usd="nan")])

    def test_a_target_or_a_port_that_is_not_one_is_refused(self):
        base = {"provider": "ssh", "name": "attic", "target": "farm@192.0.2.4"}
        self.refusals(dashboard.machines_create,
                      [dict(base, target=""), dict(base, target="192.0.2.4"),
                       dict(base, target="farm@192.0.2.4 rm -rf /"),
                       dict(base, target="farm@192.0.2.4;id"),
                       dict(base, target="-lroot@192.0.2.4"), dict(base, target=".x@192.0.2.4"),
                       dict(base, target="farm@-oProxyCommand"),
                       dict(base, port="0"), dict(base, port="65536"), dict(base, port="-1"),
                       dict(base, port="ssh"), dict(base, port="22 22")])

    def test_a_refused_body_leaves_no_temporary_key_file_behind(self):
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "fleet-pubkey-*")))
        with self.farm() as box:
            for body in ({"provider": "do-droplet", "name": "orchard", "size": "nope!",
                          "region": "fra1", "ssh_public": PUBKEY, "confirm_usd": 48},
                         {"provider": "do-droplet", "name": "orchard", "size": "s-4vcpu-8gb",
                          "region": "fra1", "ssh_public": PUBKEY, "confirm_usd": "free"}):
                self.assertEqual(dashboard.machines_create(body)[0], 400)
            self.assertEqual(box.calls.read_text(), "")
        self.assertEqual(set(glob.glob(os.path.join(tempfile.gettempdir(),
                                                    "fleet-pubkey-*"))), before)

    def test_a_write_that_loses_its_resource_race_leaves_no_key_file_behind(self):
        """A 409 starts no thread, so nothing would have cleaned up after it."""
        gate = self.state / "gate"
        blocker = self.state / "slow-fleet"
        blocker.write_text('#!/bin/sh\nwhile [ ! -f "%s" ]; do sleep 0.02; done\n' % gate)
        blocker.chmod(0o755)
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "fleet-pubkey-*")))
        body = {"provider": "do-droplet", "name": "orchard", "size": "s-4vcpu-8gb",
                "region": "fra1", "ssh_public": PUBKEY, "confirm_usd": 48}
        with self.farm():
            with mock.patch.object(dashboard, "fleet_bin", return_value=str(blocker)):
                status, first = dashboard.machines_create(body)
                self.assertEqual(status, 202, first)
                self.assertEqual(dashboard.machines_create(body)[0], 409)
                gate.write_text("go")
                self.finish(first["job"]["id"])
        self.assertEqual(set(glob.glob(os.path.join(tempfile.gettempdir(),
                                                    "fleet-pubkey-*"))), before)

    def test_no_hosting_route_answers_with_a_traceback(self):
        """Every route, against a body of the wrong shape entirely."""
        routes = (dashboard.machines_plan, dashboard.machines_create, dashboard.machines_check,
                  dashboard.machines_destroy, dashboard.machines_adopt,
                  dashboard.machines_forget, dashboard.hosts_check)
        with self.farm() as box:
            for route in routes:
                for body in ({}, None, {"name": None}, {"provider": None},
                             {"name": ["nursery"]}, {"provider": {"id": "do-droplet"}},
                             {"name": 7, "provider": 7, "confirm": 7}):
                    status, payload = route(body)
                    self.assertEqual(status, 400, (route, body, payload))
                    self.assertNotIn("Traceback", json.dumps(payload))
            self.assertEqual(box.calls.read_text(), "")


class HostingScrubTest(HostingCase):
    """A provider CLI that prints a token into its own error message must not leave it in this
    farm's job records or in an answer. The scrub is at the top of _finish_job and inside
    run_job_now, so the `error` sentence tool_message builds is clean too."""

    def setUp(self):
        super().setUp()
        self.secret = "demo_live_" + "q" * 32
        secrets_dir = self.state / "secrets"
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "demo.key").write_text(self.secret + "\n")
        self.shaped = "sk-ant-oat01-" + "w" * 40

    def leaky_tool(self):
        path = self.state / "leaky"
        path.write_text("#!/bin/sh\n"
                        'echo "connecting with %s"\n'
                        'echo "the provider: %s is not valid" >&2\n'
                        "exit 1\n" % (self.shaped, self.secret))
        path.chmod(0o755)
        return str(path)

    def test_neither_a_stored_secret_nor_a_token_shape_survives_into_a_job_record(self):
        status, payload = dashboard.start_job("hosts_check", [self.leaky_tool()], timeout=10)
        self.assertEqual(status, 202)
        record = None
        deadline = time.time() + 10
        while time.time() < deadline:
            record = dashboard.read_job(payload["job"]["id"])[1]
            if record.get("state") != "running":
                break
            time.sleep(0.02)
        self.assertEqual(record["state"], "failed", record)
        written = json.dumps(record)
        self.assertNotIn(self.secret, written)
        self.assertNotIn(self.shaped, written)
        self.assertIn("[redacted]", record["output"])
        # the sentence tool_message built out of what the tool said is clean as well
        self.assertEqual(record["error"], "connecting with [redacted]")
        # and so is the file on disk, which is what a later GET reads
        on_disk = (self.state / "jobs" / (record["id"] + ".json")).read_text()
        self.assertNotIn(self.secret, on_disk)
        self.assertNotIn(self.shaped, on_disk)
        with mock.patch.object(dashboard, "BIND", "127.0.0.1"), \
                mock.patch.object(dashboard, "TOKEN", "s3cret"), running_server() as base:
            status, served = fetch_json(base, "/api/jobs/" + record["id"], token="s3cret")
            self.assertEqual(status, 200)
            self.assertNotIn(self.secret, json.dumps(served))
            self.assertNotIn(self.shaped, json.dumps(served))

    def test_a_synchronous_answer_is_scrubbed_before_the_page_ever_sees_it(self):
        with self.farm(FLEET_FAKE_LEAK=self.secret) as box:
            status, payload = dashboard.machines_plan(
                {"provider": "do-droplet", "name": "nursery", "size": "s-4vcpu-8gb",
                 "region": "fra1"})
            self.assertEqual(status, 200, payload)
            self.assertNotIn(self.secret, box.calls.read_text())
        answer = json.dumps(payload)
        self.assertNotIn(self.secret, answer)
        self.assertIn("[redacted]", payload["detail"])
        record = self.only_job("machines_plan")
        self.assertNotIn(self.secret, (self.state / "jobs" /
                                       (record["id"] + ".json")).read_text())

    def test_a_stale_listing_error_carries_no_secret_either(self):
        with self.farm(FLEET_FAKE_FAIL="doctl: token %s was rejected" % self.secret):
            dashboard.hosting_refresh()
        answer = json.dumps(dashboard.hosting_machines())
        self.assertNotIn(self.secret, answer)
        self.assertIn("[redacted]", dashboard.hosting_machines()["error"])


if __name__ == "__main__":
    unittest.main()

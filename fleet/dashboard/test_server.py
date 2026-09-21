import importlib.util
import json
import pathlib
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock


SERVER_PATH = pathlib.Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("fleet_dashboard_server", SERVER_PATH)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


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


if __name__ == "__main__":
    unittest.main()

"""/murmur:farm from a laptop, against fakes: plugin/scripts/murmur_farm.py step by step.

The design record is fleet/docs/design/one-click-farm.md, and its Tests section is what this
file checks. Nothing here reaches DigitalOcean, a droplet or a tailnet: fake doctl, ssh,
ssh-keygen, ssh-add, gh, brew, tailscale, lsof and a browser opener come first on PATH
(tests/fakes/farm), and the fake ssh plays the farm from a folder of flag files. Only `ssh -G`
is the real ssh, which never connects. Every test has its own HOME.

  python3 tests/test_murmur_farm.py
"""
import ast
import json
import os
import pwd
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
import http.server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "plugin", "scripts", "murmur_farm.py")
FAKES = os.path.join(REPO, "tests", "fakes", "farm")
ADDRESS = "192.0.2.10"
TOKEN = "CANARY-dashboard-token-0001"
TS_KEY_TEXT = "tskey-auth-CANARY-tailscale-0001"


def real_ssh():
    return shutil.which("ssh", path="/usr/bin:/bin:/usr/local/bin")


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@unittest.skipUnless(real_ssh(), "ssh -G is answered by the real ssh, which is not installed")
class Laptop(unittest.TestCase):
    """A scratch laptop: its own HOME, a key, the fakes on PATH and a fake farm folder."""

    EXCLUDE = ()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="murmur-farm-test.")
        self.addCleanup(self.cleanup)
        self.bin = os.path.join(self.home, "bin")
        self.remote = os.path.join(self.home, "remote")
        self.laptop = os.path.join(self.home, "laptop")
        for folder in (self.bin, self.remote, self.laptop):
            os.makedirs(folder)
        for name in os.listdir(FAKES):
            if name not in self.EXCLUDE:
                os.symlink(os.path.join(FAKES, name), os.path.join(self.bin, name))
        self.fake_log = os.path.join(self.home, "fake-calls.jsonl")
        self.opened = os.path.join(self.home, "opened.jsonl")
        self.droplets = os.path.join(self.home, "droplets.json")
        with open(self.droplets, "w", encoding="utf-8") as handle:
            handle.write("[]")
        proc = os.path.join(self.home, "proc-version")
        with open(proc, "w", encoding="utf-8") as handle:
            handle.write("Linux version 6.8.0-45-generic (buildd@lcy02) #45-Ubuntu\n")
        self.env = {
            "HOME": self.home, "USER": "person", "LANG": "C.UTF-8",
            "PATH": self.bin + os.pathsep + "/usr/bin:/bin",
            "TZ": "Europe/Berlin",
            "FAKE_LOG": self.fake_log, "FAKE_REMOTE": self.remote, "FAKE_LAPTOP": self.laptop,
            "FAKE_OPENED": self.opened, "FAKE_DOCTL_LOGGED_IN": "1",
            "FAKE_DOCTL_DROPLETS": self.droplets,
            "FAKE_DOCTL_SSH_KEYS": os.path.join(self.home, "do-keys.json"),
            "FAKE_DOCTL_FIREWALLS": os.path.join(self.home, "firewalls.json"),
            "FAKE_DOCTL_ADDRESS": ADDRESS, "FAKE_LAPTOP_TAILSCALE": "absent",
            "FAKE_DASH_TOKEN": TOKEN,
            "MURMUR_PLATFORM": "Linux", "MURMUR_PROC_VERSION": proc,
            "MURMUR_FARM_POLL": "0.1", "MURMUR_FARM_REACH_SECONDS": "2",
            "MURMUR_FARM_OPEN_LINGER": "0.5",
            "FLEET_MACHINES_PENDING_WINDOW": "2", "FLEET_MACHINES_PENDING_POLL": "0.1",
        }
        os.makedirs(os.path.join(self.home, ".ssh"), mode=0o700)
        self.key = os.path.join(self.home, ".ssh", "id_ed25519")
        self.fake("ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-C", "person", "-f", self.key)
        self.outputs = []

    def cleanup(self):
        pids = os.path.join(self.laptop, "pids")
        if os.path.exists(pids):
            with open(pids, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        os.kill(int(line), signal.SIGTERM)
                    except (OSError, ValueError):
                        pass
        shutil.rmtree(self.home, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers

    def fake(self, name, *args):
        return subprocess.run([os.path.join(FAKES, name)] + list(args), env=self.env,
                              capture_output=True, text=True, timeout=30)

    def farm(self, *args, expect=None, **env):
        done = subprocess.run([sys.executable, SCRIPT] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL, env=dict(self.env, **env))
        self.outputs.append(done.stdout + done.stderr)
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            self.fail(f"{args}: not JSON: {done.stdout}{done.stderr}")
        answer["code"] = done.returncode
        if expect is not None:
            self.assertEqual(done.returncode, expect, json.dumps(answer, indent=2))
        return answer

    def calls(self, name=None):
        if not os.path.exists(self.fake_log):
            return []
        with open(self.fake_log, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        return [row for row in rows if name is None or row["argv"][0] == name]

    def creates(self):
        return [c["argv"] for c in self.calls("doctl") if c["argv"][1:4] == ["compute",
                                                                             "droplet",
                                                                             "create"]]

    def registry(self):
        path = os.path.join(self.home, ".config", "fleet", "machines.toml")
        if not os.path.exists(path):
            return {}
        with open(path, "rb") as handle:
            return tomllib.load(handle)

    def remote_runs(self):
        """The remote command string of every ssh that reached the farm."""
        found = []
        for call in self.calls("ssh"):
            argv = call["argv"][1:]
            if "-G" in argv or "-O" in argv:
                continue
            words, i = [], 0
            while i < len(argv):
                word = argv[i]
                if word.startswith("-") and len(word) > 1:
                    i += 2 if word[1] in "BbcDEeFIiJLlmOoPpQRSWw" and len(word) == 2 else 1
                    continue
                words = argv[i + 1:]
                break
            if words:
                found.append(" ".join(words))
        return found

    def flag(self, name):
        return os.path.exists(os.path.join(self.remote, name))

    def touch(self, name):
        with open(os.path.join(self.remote, name), "w", encoding="utf-8"):
            pass

    def remote_env(self):
        path = os.path.join(self.remote, "env")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return handle.read().splitlines()

    def events(self):
        path = os.path.join(self.remote, "events")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return handle.read().splitlines()

    def murmur(self, *parts):
        return os.path.join(self.home, ".config", "murmur", *parts)

    def answer_all(self, **overrides):
        values = {"name": "farm", "size": "", "region": "", "access": "tunnel", "codex": "no",
                  "accounts": "", "hq_repo": ""}
        values.update(overrides)
        for key, value in values.items():
            self.farm("answer", "--id", key, "--value", value, expect=0)

    def bought(self, **answers_given):
        """preflight, the answers, plan and apply: a droplet at its first boot's end."""
        self.farm("preflight", expect=0)
        self.answer_all(**answers_given)
        plan = self.farm("plan", expect=0)
        applied = self.farm("apply", "--confirm-usd", plan["price_usd"], "--quote",
                            plan["quote"], "--wait", "30", expect=0)
        self.assertEqual(applied["address"], ADDRESS)
        return plan

    def ready(self, **answers_given):
        """A farm through ssh-config and finish."""
        self.bought(**answers_given)
        self.farm("ssh-config", expect=0)
        self.touch("gh-logged-in")
        self.farm("finish", "--wait", "10", expect=0)


# ------------------------------------------------------------------------------------ steps

class Steps(Laptop):
    """Every step, and a rerun of each one that changes nothing it should not."""

    def test_the_whole_tunnel_flow_and_a_resume_after_each_step(self):
        self.assertEqual(self.farm("status")["next"], "preflight")
        pre = self.farm("preflight", expect=0)
        self.assertEqual(pre["access_options"], ["tunnel"])
        self.assertEqual(self.farm("preflight")["code"], 0)             # again: the same
        asked = self.farm("questions", expect=0)["questions"]
        self.assertEqual([q["id"] for q in asked],
                         ["name", "size", "region", "access", "codex", "accounts", "hq_repo"])
        self.assertEqual(asked[1]["default"], "s-4vcpu-8gb")
        self.assertEqual(asked[2]["default"], "fra1")
        small = asked[1]["choices"][0]["note"]
        self.assertIn("light work", small)
        self.assertIn("1 GB of memory is free", small)
        self.assertNotIn("agents at a time", small)
        self.answer_all()
        self.assertEqual(self.farm("questions")["questions"], [])
        self.assertEqual(self.farm("status")["next"], "plan")

        plan = self.farm("plan", expect=0)
        self.assertEqual(plan["sentence"], "Create farm, $48 a month until you destroy it")
        self.assertIn("#cloud-config", plan["cloud_init"])
        self.assertEqual(self.creates(), [])
        applied = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"],
                            "--wait", "30", expect=0)
        self.assertEqual(applied["next"], "ssh-config")
        self.assertEqual(self.farm("apply", "--wait", "5", expect=0)["address"], ADDRESS)
        self.assertEqual(len(self.creates()), 1)                         # resumed, not bought
        self.assertEqual(self.farm("status")["next"], "ssh-config")

        self.farm("ssh-config", expect=0)
        self.farm("ssh-config", expect=0)
        self.assertEqual(self.farm("status")["next"], "finish")

        waiting = self.farm("finish", expect=2)
        self.assertEqual(len(waiting["run_in_your_terminal"]), 1)
        self.assertIn("gh auth login", waiting["run_in_your_terminal"][0])
        self.assertFalse(self.flag("install-launches"))
        self.touch("gh-logged-in")
        done = self.farm("finish", "--wait", "10", expect=0)
        self.assertIn("installed", done["said"])
        self.assertEqual(done["next"], "logins")                       # never straight to open
        self.farm("finish", "--wait", "10", expect=0)
        with open(os.path.join(self.remote, "install-launches"), encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().splitlines()), 1)         # never twice
        self.assertIn("FLEET_DASH_BIND=127.0.0.1", self.remote_env())
        self.assertIn("FLEET_FARM_ALIAS=farm", self.remote_env())
        self.assertEqual(self.farm("status")["next"], "logins")

        waiting = self.farm("logins", expect=2)
        self.assertIn("/home/farm/.local/bin/claude", waiting["run_in_your_terminal"][0])
        self.write_accounts([{"name": "default", "logged_in": True, "email": "p@example.com"}])
        self.assertEqual(self.farm("logins", expect=0)["next"], "open")
        self.assertEqual(self.farm("status")["next"], "open")
        # Once the logins are done, a reinstall leads straight to open.
        self.assertEqual(self.farm("finish", "--wait", "10", expect=0)["next"], "open")
        opened = self.farm("open", expect=0)
        self.assertTrue(opened["url"].startswith("http://127.0.0.1:"))
        self.farm("open", "--stop", expect=0)

    def write_accounts(self, rows):
        with open(os.path.join(self.remote, "accounts.json"), "w", encoding="utf-8") as handle:
            json.dump(rows, handle)

    def test_a_failed_install_says_why_and_is_restarted_only_on_request(self):
        self.bought()
        self.farm("ssh-config", expect=0)
        self.touch("gh-logged-in")
        failed = self.farm("finish", "--wait", "5", expect=1, FAKE_SSH_INSTALL="failed")
        self.assertIn("HTTP 404", failed["said"])
        self.farm("finish", "--wait", "5", expect=1)
        os.unlink(os.path.join(self.remote, "install.failed"))
        self.farm("finish", "--reinstall", "--wait", "5", expect=0)

    def test_a_running_install_is_waited_on_and_never_started_twice(self):
        self.bought()
        self.farm("ssh-config", expect=0)
        self.touch("gh-logged-in")
        self.farm("finish", "--wait", "0.3", expect=2, FAKE_SSH_INSTALL="running")
        self.farm("finish", "--wait", "0.3", expect=2, FAKE_SSH_INSTALL="running")
        with open(os.path.join(self.remote, "install-launches"), encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().splitlines()), 1)


class Price(Laptop):
    """Nothing is bought without the price typed back, and a typed price buys one attempt."""

    def setUp(self):
        super().setUp()
        self.farm("preflight", expect=0)
        self.answer_all()

    def test_no_price_no_purchase(self):
        refused = self.farm("apply", expect=1)
        self.assertIn("price typed back", refused["said"])
        self.assertEqual(self.creates(), [])

    def test_a_price_without_the_plans_quote_is_refused(self):
        self.farm("plan", expect=0)
        refused = self.farm("apply", "--confirm-usd", "48", "--quote", "0000", expect=1)
        self.assertIn("one attempt only", refused["said"])
        self.assertEqual(self.creates(), [])

    def test_a_wrong_price_is_refused(self):
        plan = self.farm("plan", expect=0)
        refused = self.farm("apply", "--confirm-usd", "24", "--quote", plan["quote"], expect=1)
        self.assertIn("the price moved", refused["said"])
        self.assertEqual(self.creates(), [])

    def test_a_price_that_moved_after_the_plan_buys_nothing_at_the_new_price(self):
        plan = self.farm("plan", expect=0)
        self.assertEqual(plan["price_usd"], 48)
        refused = self.farm("apply", "--confirm-usd", "52", "--quote", plan["quote"],
                            "--wait", "0", FAKE_DOCTL_PRICE="52", expect=1)
        self.assertIn("the price moved", refused["said"])
        self.assertIn("run `plan` again", refused["said"])
        self.assertEqual(self.creates(), [])
        with open(self.droplets, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [])

    def test_a_price_that_moved_after_the_plan_buys_nothing_at_the_old_price(self):
        plan = self.farm("plan", expect=0)
        refused = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"],
                            "--wait", "0", FAKE_DOCTL_PRICE="52", expect=1)
        self.assertIn("the price moved", refused["said"])
        self.assertEqual(self.creates(), [])
        again = self.farm("apply", "--confirm-usd", "52", "--quote", plan["quote"], expect=1)
        self.assertIn("one attempt only", again["said"])
        self.assertEqual(self.creates(), [])

    def test_a_non_finite_or_negative_typed_price_buys_nothing(self):
        for bad in ("nan", "inf", "-48"):
            plan = self.farm("plan", expect=0)
            self.assertEqual(plan["price_usd"], 48)
            refused = self.farm("apply", "--confirm-usd", bad, "--quote", plan["quote"],
                                "--wait", "0", expect=1)
            self.assertIn("is not a price", refused["said"], bad)
            self.assertEqual(self.creates(), [], bad)
        with open(self.droplets, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [])

    def test_a_nan_price_from_doctl_buys_nothing(self):
        plan = self.farm("plan", FAKE_DOCTL_PRICE="nan", expect=0)
        self.assertEqual(plan["price_source"], "list")
        self.assertIn("not a usable number", plan["price_note"])
        refused = self.farm("apply", "--confirm-usd", plan["price_usd"], "--quote",
                            plan["quote"], "--wait", "0", FAKE_DOCTL_PRICE="nan", expect=1)
        self.assertIn("price", refused["said"])
        self.assertEqual(self.creates(), [])

    def test_a_quote_binds_the_whole_plan_not_its_price_alone(self):
        self.answer_all(region="fra1", access="tunnel", codex="no")
        plan = self.farm("plan", expect=0)
        self.assertEqual(plan["region"], "fra1")
        self.farm("answer", "--id", "region", "--value", "nyc3", expect=0)
        self.farm("answer", "--id", "codex", "--value", "yes", expect=0)
        refused = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"],
                            "--wait", "0", expect=1)
        self.assertIn("the plan changed since its quote", refused["said"])
        self.assertIn("region was fra1 and is now nyc3", refused["said"])
        self.assertIn("codex was no and is now yes", refused["said"])
        self.assertIn("cloud-init", refused["said"])
        self.assertEqual(self.creates(), [])
        with open(self.droplets, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [])
        # The old quote is spent: putting the answers back does not revive it.
        self.farm("answer", "--id", "region", "--value", "fra1", expect=0)
        self.farm("answer", "--id", "codex", "--value", "no", expect=0)
        again = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], expect=1)
        self.assertIn("one attempt only", again["said"])
        self.assertEqual(self.creates(), [])

    def test_every_term_of_the_plan_is_bound(self):
        self.env["FAKE_LAPTOP_TAILSCALE"] = "running"       # so tailscale is an answer to give
        self.farm("preflight", expect=0)
        changed = {"name": "farm2", "size": "s-8vcpu-16gb", "region": "nyc3",
                   "access": "tailscale", "codex": "yes", "hq_repo": "someone/agent-hq-office"}
        for term, value in changed.items():
            self.answer_all()
            plan = self.farm("plan", expect=0)
            self.farm("answer", "--id", term, "--value", value, expect=0)
            refused = self.farm("apply", "--confirm-usd", plan["price_usd"], "--quote",
                                plan["quote"], "--wait", "0", expect=1)
            self.assertIn("the plan changed since its quote", refused["said"], term)
            self.assertIn(f"{term} was", refused["said"], term)
            self.assertEqual(self.creates(), [], term)

    def test_a_changed_cloud_init_is_refused(self):
        plan = self.farm("plan", expect=0)
        # Another laptop key changes the cloud-init the plan showed, and nothing else.
        os.unlink(self.key)
        os.unlink(self.key + ".pub")
        self.fake("ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-C", "person-again", "-f",
                  self.key)
        refused = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"],
                            "--wait", "0", expect=1)
        self.assertIn("the cloud-init file is not the one shown", refused["said"])
        self.assertEqual(self.creates(), [])

    def test_a_quote_is_spent_by_one_attempt(self):
        plan = self.farm("plan", expect=0)
        self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], "--wait", "0",
                  FAKE_DOCTL_FAIL_AT="import", expect=1)
        again = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], expect=1)
        self.assertIn("one attempt only", again["said"])


class LostCreate(Laptop):
    """A create whose answer was lost is adopted by the rerun and never bought again."""

    def setUp(self):
        super().setUp()
        self.farm("preflight", expect=0)
        self.answer_all()

    def test_the_rerun_adopts_the_lost_create_and_a_new_farm_asks_for_the_price(self):
        plan = self.farm("plan", expect=0)
        self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], "--wait", "0",
                  FAKE_DOCTL_CREATE_LOST="1")
        resumed = self.farm("apply", "--wait", "30", expect=0)
        self.assertEqual(resumed["address"], ADDRESS)
        self.assertEqual(len(self.creates()), 1)
        self.farm("answer", "--id", "name", "--value", "farm-two", expect=0)
        refused = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], expect=1)
        self.assertIn("one attempt only", refused["said"])
        self.assertEqual(len(self.creates()), 1)

    def test_the_slow_create_is_waited_on(self):
        plan = self.farm("plan", expect=0)
        # A window far wider than the delay: the droplet appears while the attempt is young.
        first = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"],
                          "--wait", "0", FAKE_DOCTL_CREATE_LATE="1.5",
                          FLEET_MACHINES_PENDING_WINDOW="60", expect=2)
        self.assertEqual(first["next"], "apply")
        resumed = self.farm("apply", "--wait", "30", FLEET_MACHINES_PENDING_WINDOW="60",
                            expect=0)
        self.assertEqual(resumed["address"], ADDRESS)
        self.assertEqual(len(self.creates()), 1)

    def test_a_droplet_that_never_appears_needs_forget_attempt_and_a_new_price(self):
        plan = self.farm("plan", expect=0)
        self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], "--wait", "0",
                  FAKE_DOCTL_FAIL_AT="create", expect=2)
        late = self.farm("apply", "--wait", "5", expect=2)
        self.assertEqual(late["next"], "forget-attempt")
        self.assertEqual(self.farm("status")["next"], "forget-attempt")
        self.assertEqual(len(self.creates()), 1)
        forgot = self.farm("forget-attempt", expect=0)
        self.assertEqual(forgot["next"], "plan")
        self.assertEqual(self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"],
                                   expect=1)["code"], 1)
        plan = self.farm("plan", expect=0)
        self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], "--wait", "30",
                  expect=0)
        self.assertEqual(len(self.creates()), 2)


class EnvFile(unittest.TestCase):
    """The script's real env writer, run as the farm runs it: the file stays 0600 and keeps
    every line it does not rewrite, the dashboard token most of all."""

    def writer(self):
        with open(SCRIPT, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in tree.body:
            names = [getattr(target, "id", "") for target in getattr(node, "targets", [])]
            if isinstance(node, ast.Assign) and names == ["ENV_WRITER"]:
                return ast.literal_eval(node.value)
        self.fail("murmur_farm.py has no ENV_WRITER")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="murmur-env-test.")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.path = os.path.join(self.home, ".config", "fleet", "env")

    def write(self, *pairs, umask=0o002):
        def loose():
            os.umask(umask)
        done = subprocess.run([sys.executable, "-c", self.writer(), self.path] + list(pairs),
                              capture_output=True, text=True, timeout=30, preexec_fn=loose)
        self.assertEqual(done.returncode, 0, done.stderr)

    def mode(self, path=None):
        return stat.S_IMODE(os.stat(path or self.path).st_mode)

    def test_a_bind_change_keeps_0600_and_the_token(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("FLEET_DASH_TOKEN=CANARY\nFLEET_DASH_BIND=127.0.0.1\n")
        os.chmod(self.path, 0o600)
        self.write("FLEET_DASH_BIND=tailscale")
        self.assertEqual(self.mode(), 0o600)
        with open(self.path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines, ["FLEET_DASH_TOKEN=CANARY", "FLEET_DASH_BIND=tailscale"])

    def test_a_new_file_is_0600_under_any_umask(self):
        self.write("FLEET_FARM_ALIAS=farm", umask=0)
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(self.mode(os.path.dirname(self.path)) & 0o077, 0)

    def test_a_wide_file_is_narrowed_and_a_stale_temporary_never_leaks_its_mode(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("FLEET_DASH_TOKEN=CANARY\n")
        os.chmod(self.path, 0o644)
        with open(self.path + ".murmur", "w", encoding="utf-8") as handle:
            handle.write("stale\n")
        os.chmod(self.path + ".murmur", 0o666)
        self.write("FLEET_DASH_BIND=127.0.0.1", umask=0)
        self.assertEqual(self.mode(), 0o600)
        self.assertFalse(os.path.exists(self.path + ".murmur"))
        with open(self.path, encoding="utf-8") as handle:
            self.assertIn("FLEET_DASH_TOKEN=CANARY", handle.read())


class OtherFarms(Laptop):
    """Another farm's droplet is never adopted; two of this farm's stop the run."""

    def droplet(self, droplet_id, tags):
        return {"id": droplet_id, "name": "farm", "status": "active", "tags": tags,
                "region": {"slug": "fra1"}, "size_slug": "s-4vcpu-8gb",
                "size": {"slug": "s-4vcpu-8gb", "price_monthly": 48.0},
                "networks": {"v4": [{"ip_address": "198.51.100.7", "type": "public"}]},
                "created_at": "2026-09-24T10:00:00Z"}

    def farm_tag(self):
        with open(os.path.join(self.home, ".config", "fleet", "farm-id"),
                  encoding="utf-8") as handle:
            return "murmur-by-" + handle.read().strip()

    def test_another_farms_farm_is_not_adopted(self):
        self.farm("preflight", expect=0)
        self.answer_all()
        with open(self.droplets, "w", encoding="utf-8") as handle:
            json.dump([self.droplet(700, ["murmur", "murmur-by-heron-0002"])], handle)
        plan = self.farm("plan", expect=0)
        self.assertTrue(plan["buys"])
        applied = self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"],
                            "--wait", "30", expect=0)
        self.assertEqual(applied["address"], ADDRESS)
        self.assertEqual(len(self.creates()), 1)

    def test_two_of_this_farms_droplets_stop_the_run(self):
        self.farm("preflight", expect=0)
        self.answer_all()
        self.farm("plan", expect=0)                      # makes the farm id
        tag = self.farm_tag()
        with open(self.droplets, "w", encoding="utf-8") as handle:
            json.dump([self.droplet(701, [tag]), self.droplet(702, [tag])], handle)
        plan = self.farm("plan", expect=0)
        self.assertFalse(plan["buys"])
        self.assertFalse(plan["adopts"])
        self.assertNotIn("quote", plan)
        stopped = self.farm("apply", "--wait", "0", expect=1)
        self.assertIn("2 droplets named farm", stopped["said"])
        self.assertIn("nothing is bought or adopted", stopped["said"])
        self.assertEqual(self.creates(), [])
        self.assertNotIn("farm", self.registry())

    def lose_the_row(self):
        os.unlink(os.path.join(self.home, ".config", "fleet", "machines.toml"))

    def test_a_lost_row_is_adopted_with_no_price_and_the_flow_resumes(self):
        plan = self.bought()
        self.assertEqual(len(self.creates()), 1)
        droplet_id = self.registry()["farm"]["provider_id"]
        self.lose_the_row()
        replan = self.farm("plan", expect=0)
        self.assertFalse(replan["buys"])
        self.assertTrue(replan["adopts"])
        self.assertNotIn("quote", replan)
        self.assertIn("adopts it with no price and no quote", replan["said"])
        # Neither the old quote nor a typed price is needed, and neither buys anything.
        adopted = self.farm("apply", "--wait", "30", expect=0)
        self.assertEqual(adopted["address"], ADDRESS)
        self.assertEqual(len(self.creates()), 1)
        row = self.registry()["farm"]
        self.assertEqual(row["provider_id"], droplet_id)
        with open(self.murmur("farm.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["farm"]["outcome"], "adopted")
        refused = self.farm("apply", "--confirm-usd", plan["price_usd"], "--quote",
                            plan["quote"], "--wait", "0", expect=0)
        self.assertEqual(refused["address"], ADDRESS)
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(self.farm("status")["next"], "ssh-config")
        self.farm("ssh-config", expect=0)
        self.touch("gh-logged-in")
        self.farm("finish", "--wait", "10", expect=0)
        self.assertEqual(len(self.creates()), 1)

    def test_one_of_this_farms_droplets_with_no_row_is_adopted_not_bought(self):
        self.farm("preflight", expect=0)
        self.answer_all()
        stale = self.farm("plan", expect=0)            # makes the farm id, and a quote
        tag = self.farm_tag()
        with open(self.droplets, "w", encoding="utf-8") as handle:
            json.dump([self.droplet(701, [tag])], handle)
        plan = self.farm("plan", expect=0)
        self.assertFalse(plan["buys"])
        self.assertTrue(plan["adopts"])
        self.assertNotIn("quote", plan)
        self.farm("apply", "--confirm-usd", "48", "--quote", stale["quote"], "--wait", "0")
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.registry()["farm"]["provider_id"], "701")

    def test_one_farm_id_and_no_id_file_of_the_scripts_own(self):
        self.bought()
        tag = self.farm_tag()
        created = self.creates()[0]
        self.assertIn(tag, created[created.index("--tag-names") + 1].split(","))
        self.assertNotIn("farm-id", os.listdir(self.murmur()))
        with open(self.murmur("farm.json"), encoding="utf-8") as handle:
            self.assertNotIn(tag.split("murmur-by-")[1], handle.read())


# ------------------------------------------------------------------------ ssh config and keys

class SshConfig(Laptop):
    """The marked section, the host key rules on every command line, and the pinning probe."""

    def config(self, text):
        path = os.path.join(self.home, ".ssh", "config")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, 0o600)

    def read_config(self):
        with open(os.path.join(self.home, ".ssh", "config"), encoding="utf-8") as handle:
            return handle.read()

    def test_the_section_is_written_once_before_the_first_host_and_rewritten_in_place(self):
        self.config("AddKeysToAgent yes\n\nHost old\n  HostName 203.0.113.5\n  User me\n")
        self.bought()
        self.farm("ssh-config", expect=0)
        self.farm("ssh-config", expect=0)
        # The only mention of the name is the section: the name and the rehearsal still pass.
        self.farm("answer", "--id", "name", "--value", "farm", expect=0)
        self.farm("plan", expect=0)
        text = self.read_config()
        self.assertTrue(text.startswith("AddKeysToAgent yes\n"))
        self.assertEqual(text.count(">>> murmur farm"), 1)
        self.assertLess(text.index(">>> murmur farm"), text.index("Host old"))
        self.assertIn(f"Host farm\n  HostName {ADDRESS}\n  Port 22\n  User farm\n", text)
        self.assertIn("Host old\n  HostName 203.0.113.5\n  User me\n", text)
        self.assertIn(f"  UserKnownHostsFile {self.murmur('known_hosts')}\n", text)
        mode = stat.S_IMODE(os.stat(os.path.join(self.home, ".ssh", "config")).st_mode)
        self.assertEqual(mode, 0o600)

    def test_a_fresh_laptop_gets_its_folder_and_the_key_is_pinned_then_held(self):
        self.assertFalse(os.path.exists(self.murmur()))
        self.farm("preflight", expect=0)
        self.assertEqual(stat.S_IMODE(os.stat(self.murmur()).st_mode), 0o700)
        self.answer_all()
        plan = self.farm("plan", expect=0)
        self.farm("apply", "--confirm-usd", "48", "--quote", plan["quote"], "--wait", "30",
                  expect=0)
        self.farm("ssh-config", expect=0)
        found = self.fake("ssh-keygen", "-F", ADDRESS, "-f", self.murmur("known_hosts"))
        self.assertEqual(found.returncode, 0)
        self.assertIn("AAAAFAKEHOSTKEYONE", found.stdout)
        # The farm now presents another key: every later step is refused.
        changed = self.farm("finish", expect=1, FAKE_SSH_HOSTKEY="ssh-ed25519 AAAACHANGED")
        self.assertIn("ssh to farm failed", changed["said"])
        self.assertFalse(self.flag("install-launches"))
        self.assertEqual(changed["run_in_your_terminal"], [])

    def state(self):
        with open(self.murmur("farm.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def write_state(self, state):
        with open(self.murmur("farm.json"), "w", encoding="utf-8") as handle:
            json.dump(state, handle)

    def unpins(self):
        """Every ssh-keygen -R on murmur's own known_hosts file."""
        return [call for call in self.calls("ssh-keygen") if "-R" in call["argv"]
                and self.murmur("known_hosts") in call["argv"]]

    def test_a_pin_whose_record_was_lost_is_adopted_and_a_changed_key_refused(self):
        # The run stopped between the first probe (which pinned the key) and saving whom it was
        # pinned for. The rerun must hold the pin, never remove it and accept another key.
        self.bought()
        before = self.state()
        self.farm("ssh-config", expect=0)
        self.assertEqual(self.state()["farm"]["pinned_for"],
                         self.registry()["farm"]["provider_id"])
        self.write_state(before)
        self.assertNotIn("pinned_for", self.state()["farm"])
        runs = len(self.remote_runs())
        stopped = self.farm("ssh-config", expect=1, FAKE_SSH_HOSTKEY="ssh-ed25519 AAAACHANGED")
        self.assertIn("other than the one pinned", stopped["said"])
        self.assertEqual(self.remote_runs()[runs:], ["true"])      # the refused probe only
        self.assertEqual(self.unpins(), [])
        found = self.fake("ssh-keygen", "-F", ADDRESS, "-f", self.murmur("known_hosts"))
        self.assertIn("AAAAFAKEHOSTKEYONE", found.stdout)
        self.assertNotIn("AAAACHANGED", found.stdout)
        # The adopted pin is now on record, and the same farm's own key passes as before.
        self.assertEqual(self.state()["farm"]["pinned_for"],
                         self.registry()["farm"]["provider_id"])
        self.farm("ssh-config", expect=0)
        self.farm("finish", expect=1, FAKE_SSH_HOSTKEY="ssh-ed25519 AAAACHANGED")

    def test_a_rerun_for_the_same_droplet_never_removes_its_pin(self):
        self.bought()
        self.farm("ssh-config", expect=0)
        self.farm("ssh-config", expect=0)
        self.farm("ssh-config", expect=1, FAKE_SSH_HOSTKEY="ssh-ed25519 AAAACHANGED")
        self.assertEqual(self.unpins(), [])

    def test_a_pin_for_another_droplet_at_this_address_is_replaced(self):
        # DigitalOcean reuses addresses: the key pinned for an earlier droplet goes, and only
        # because the droplet id on record is not this one.
        self.bought()
        self.farm("ssh-config", expect=0)
        state = self.state()
        state["farm"]["pinned_for"] = "earlier-droplet"
        self.write_state(state)
        self.farm("ssh-config", expect=0, FAKE_SSH_HOSTKEY="ssh-ed25519 AAAANEWDROPLET")
        found = self.fake("ssh-keygen", "-F", ADDRESS, "-f", self.murmur("known_hosts"))
        self.assertIn("AAAANEWDROPLET", found.stdout)
        self.assertNotIn("AAAAFAKEHOSTKEYONE", found.stdout)
        self.assertEqual(self.state()["farm"]["pinned_for"],
                         self.registry()["farm"]["provider_id"])

    def test_a_probe_that_pins_nothing_stops_the_run(self):
        self.bought()
        stopped = self.farm("ssh-config", expect=1, FAKE_SSH_PROBE_NO_RECORD="1")
        self.assertIn("without pinning", stopped["said"])
        self.assertEqual(self.farm("status")["next"], "ssh-config")

    def test_a_hostile_config_cannot_loosen_the_host_key_rules(self):
        self.config("Host *\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n")
        self.ready()
        self.farm("open", "--no-browser", expect=0)
        self.farm("open", "--stop", expect=0)
        checked = 0
        for call in self.calls("ssh"):
            argv = call["argv"][1:]
            if "-G" in argv:
                continue
            options = []
            for i, word in enumerate(argv):
                if word == "-o":
                    options += ["-o", argv[i + 1]]
            host = "farm" if "farm" in argv else None
            if host is None:
                continue
            seen = subprocess.run([real_ssh(), "-G", "-F",
                                   os.path.join(self.home, ".ssh", "config")] + options
                                  + [host], capture_output=True, text=True, timeout=20).stdout
            self.assertIn("stricthostkeychecking accept-new", seen, argv)
            # Port 22 and user farm on the line itself: no later config change moves them.
            self.assertEqual(argv[argv.index("-p") + 1], "22", argv)
            self.assertEqual(argv[argv.index("-l") + 1], "farm", argv)
            self.assertIn(f"userknownhostsfile {self.murmur('known_hosts')}", seen, argv)
            checked += 1
        self.assertGreater(checked, 8)

    def test_a_taken_name_is_asked_again(self):
        self.config("Host farm\n  HostName 203.0.113.9\n")
        self.farm("preflight", expect=0)
        refused = self.farm("answer", "--id", "name", "--value", "farm", expect=1)
        self.assertIn("pick another name", refused["said"])
        self.farm("answer", "--id", "name", "--value", "farm-new", expect=0)

    def test_a_broken_marked_section_is_refused_and_the_file_is_left_byte_for_byte(self):
        begin = "# >>> murmur farm: written by /murmur:farm, rewritten on every run >>>"
        end = "# <<< murmur farm <<<"
        self.bought()
        path = os.path.join(self.home, ".ssh", "config")
        cases = (
            (f"{begin}\nHost farm\n  HostName 203.0.113.9\n  User farm\n\n"
             "Host oldbox\n  HostName 198.51.100.4\n  ProxyJump bastion\n",
             "line 1 opens the section and no end marker"),
            (f"Host oldbox\n  ProxyJump bastion\n{end}\n",
             "line 3 closes the section and no begin marker"),
            (f"{begin}\nHost farm\n  HostName 203.0.113.9\n{begin}\n{end}\n"
             "Host oldbox\n  ProxyJump bastion\n",
             "line 4 is a second begin marker"),
        )
        for text, fault in cases:
            self.config(text)
            with open(path, "rb") as handle:
                before = handle.read()
            runs = len(self.remote_runs())
            stopped = self.farm("ssh-config", expect=1)
            self.assertIn(fault, stopped["said"])
            self.assertIn("the file was not changed", stopped["said"])
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), before)
            self.assertEqual(len(self.remote_runs()), runs)
            self.assertFalse(os.path.exists(path + ".murmur.tmp"))

    def test_a_broken_marked_section_is_refused_at_the_name_question(self):
        self.config("# >>> murmur farm: written by /murmur:farm, rewritten on every run >>>\n"
                    "Host farm\n  HostName 203.0.113.9\n")
        self.farm("preflight", expect=0)
        refused = self.farm("answer", "--id", "name", "--value", "farm", expect=1)
        self.assertIn("line 1 opens the section", refused["said"])

    def test_a_name_routed_through_a_proxy_is_asked_again(self):
        self.farm("preflight", expect=0)
        for block in ("Host farm\n  ProxyCommand ssh -W 127.0.0.1:22 oldbox\n",
                      "Host farm\n  ProxyJump bastion\n",
                      "Host farm\n  HostKeyAlias oldbox\n",
                      "Host farm\n  HostName 203.0.113.9\n"):
            self.config(block)
            refused = self.farm("answer", "--id", "name", "--value", "farm", expect=1)
            self.assertIn("already has a block for `farm`", refused["said"], block)
            self.assertIn("~/.ssh/config line 1: Host farm", refused["said"], block)
        self.farm("answer", "--id", "name", "--value", "farm-new", expect=0)

    def test_a_name_any_line_names_is_refused_before_any_purchase(self):
        # Settings equal to ssh's defaults still make the block the person's own: the literal
        # claim, not what ssh prints, decides.
        login = pwd.getpwuid(os.getuid()).pw_name
        blocks = (f"Host farm\n  HostName farm\n  User {login}\n",
                  "Host farm\n  User existing-owner\n  IdentityFile /home/existing/key\n",
                  "Host = old \"farm\"\n  User existing-owner\n",
                  "Match originalhost farm\n  IdentityFile /home/existing/key\n",
                  "Match host old,farm user me\n  Port 2200\n")
        self.farm("preflight", expect=0)
        for block in blocks:
            self.config(block)
            refused = self.farm("answer", "--id", "name", "--value", "farm", expect=1)
            self.assertIn("already has a block for `farm`", refused["said"], block)
            self.assertIn("pick another name", refused["said"], block)
            self.assertIn(f"~/.ssh/config line 1: {block.split(chr(10))[0]}", refused["said"],
                          block)
            self.assertEqual(self.read_config(), block)
        # The whole flow with the first of these configs: nothing is bought, the file is
        # untouched.
        self.config(blocks[0])
        for key, value in (("size", ""), ("region", ""), ("access", "tunnel"), ("codex", "no"),
                           ("accounts", ""), ("hq_repo", "")):
            self.farm("answer", "--id", key, "--value", value, expect=0)
        plan = self.farm("plan")
        self.farm("apply", "--confirm-usd", "48", "--quote", plan.get("quote") or "x",
                  "--wait", "30")
        self.farm("ssh-config")
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.read_config(), blocks[0])
        self.assertNotIn("name", self.state().get("answers", {}))

    def test_a_name_an_included_file_names_is_refused(self):
        # Include as ssh reads it: relative to ~/.ssh, globs in sorted order, and nested.
        folder = os.path.join(self.home, ".ssh", "config.d")
        os.makedirs(folder)
        for file_name, text in (("10-work", "Include nested.conf\n"),
                                ("20-old", "Host oldbox\n  HostName 203.0.113.4\n")):
            with open(os.path.join(folder, file_name), "w", encoding="utf-8") as handle:
                handle.write(text)
        with open(os.path.join(self.home, ".ssh", "nested.conf"), "w",
                  encoding="utf-8") as handle:
            handle.write("# old farm\nHost farm\n  HostName 203.0.113.9\n")
        self.config("AddKeysToAgent yes\nInclude config.d/*\n\nHost other\n  User me\n")
        self.farm("preflight", expect=0)
        refused = self.farm("answer", "--id", "name", "--value", "farm", expect=1)
        self.assertIn("~/.ssh/nested.conf line 2: Host farm", refused["said"])
        self.farm("answer", "--id", "name", "--value", "oldbox", expect=1)
        self.farm("answer", "--id", "name", "--value", "farm-new", expect=0)

    def system_config(self, text, **included):
        """A scratch system config (ssh reads it after the person's own), and files in its
        ssh_config.d, pointed at through MURMUR_SYSTEM_SSH_CONFIG."""
        # Outside HOME, as /etc/ssh is: a path under HOME would be shown as ~/...
        if not getattr(self, "etc", None):
            self.etc = tempfile.mkdtemp(prefix="murmur-farm-etc-ssh.")
            self.addCleanup(shutil.rmtree, self.etc, ignore_errors=True)
        etc = self.etc
        os.makedirs(os.path.join(etc, "ssh_config.d"), exist_ok=True)
        path = os.path.join(etc, "ssh_config")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        for file_name, body in included.items():
            with open(os.path.join(etc, "ssh_config.d", file_name + ".conf"), "w",
                      encoding="utf-8") as handle:
                handle.write(body)
        self.env["MURMUR_SYSTEM_SSH_CONFIG"] = path
        return path

    def test_a_name_the_system_config_names_is_refused_before_any_quote(self):
        # An empty user config, and `Host farm` in the system config. The real ssh goes to the
        # old machine for this name, so the new farm may not take it.
        self.config("")
        system = self.system_config("Host farm\n  HostName old-farm.example\n"
                                    "  User old-owner\n")
        seen = subprocess.run([real_ssh(), "-G", "-F", system, "farm"],
                              capture_output=True, text=True, timeout=20).stdout
        self.assertIn("hostname old-farm.example\n", seen)
        self.farm("preflight", expect=0)
        refused = self.farm("answer", "--id", "name", "--value", "farm", expect=1)
        self.assertIn("already has a block for `farm`", refused["said"])
        self.assertIn(f"{system} line 1: Host farm", refused["said"])
        self.assertNotIn("name", self.state().get("answers", {}))
        self.assertNotIn("quote", self.state())
        self.farm("answer", "--id", "name", "--value", "farm-new", expect=0)

    def test_a_system_config_that_names_the_name_after_the_answer_gets_no_quote(self):
        self.config("")
        self.farm("preflight", expect=0)
        self.answer_all()
        plan = self.farm("plan", expect=0)
        # Written after the answer and the plan: plan and apply each check the name again.
        system = self.system_config("Include ssh_config.d/*.conf\n",
                                    old="# the old farm\nMatch originalhost farm\n"
                                        "  HostName old-farm.example\n")
        refused = self.farm("apply", "--confirm-usd", plan["price_usd"], "--quote",
                            plan["quote"], "--wait", "30", expect=1)
        included = os.path.join(os.path.dirname(system), "ssh_config.d", "old.conf")
        self.assertIn(f"{included} line 2: Match originalhost farm", refused["said"])
        self.assertIn("Nothing was bought", refused["said"])
        again = self.farm("plan", expect=1)
        self.assertIn("already has a block for `farm`", again["said"])
        self.assertNotIn("quote", again)
        self.assertNotIn("quote", self.state())
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.read_config(), "")

    def test_the_rehearsal_reads_the_system_config_after_the_users(self):
        self.config("")
        self.farm("preflight", expect=0)
        self.answer_all()
        # What the block sets wins over the system config, as ssh takes each setting's first
        # value: a `Host *` there with another user still leaves the farm's name to the farm.
        self.system_config("Host *\n  User someone\n  SendEnv LANG\n")
        self.farm("plan", expect=0)
        # What the block leaves unset, the system config still decides, and it is named.
        system = self.system_config("Host *\n  ProxyJump bastion\n")
        refused = self.farm("plan", expect=1)
        self.assertIn(f"it goes through ProxyJump bastion (set by {system} line 2: "
                      "ProxyJump bastion)", refused["said"])
        self.assertEqual(self.creates(), [])

    def test_the_rehearsal_reads_a_relative_include_of_the_system_config_under_its_folder(self):
        # An empty user config, and a relative Include in the system config of a file that sends
        # every name through a bastion. The real ssh finds that file under the system config's
        # folder, not under ~/.ssh, so the rehearsal must too.
        self.config("")
        # The same relative path under ~/.ssh says nothing: a rehearsal that looked there would
        # pass.
        os.makedirs(os.path.join(self.home, ".ssh", "ssh_config.d"))
        with open(os.path.join(self.home, ".ssh", "ssh_config.d", "routing.conf"), "w",
                  encoding="utf-8") as handle:
            handle.write("Host *\n  SendEnv LANG\n")
        self.farm("preflight", expect=0)
        self.answer_all()
        # Then the same file one Include deeper: a nested relative Include in the system config
        # is also found under the system config's folder.
        for top, nested in (("Include ssh_config.d/*.conf\n", None),
                            ("Include ssh_config.d/nested.conf\n",
                             "Include ssh_config.d/*ing.conf\n")):
            with self.subTest(top=top):
                system = self.system_config(top, routing="Host *\n  ProxyJump bastion\n",
                                            **({"nested": nested} if nested else {}))
                routing = os.path.join(os.path.dirname(system), "ssh_config.d", "routing.conf")
                # (`ssh -G -F <this file>` would read it as a user config and look under
                # ~/.ssh: the very mistake under test, so no plain ssh call checks it here.)
                trace = os.path.join(self.home, "ssh-g-trace.log")
                if os.path.exists(trace):
                    os.unlink(trace)
                refused = self.farm("plan", expect=1, FAKE_SSH_G_TRACE=trace)
                self.assertIn(f"it goes through ProxyJump bastion (set by {routing} line 2: "
                              "ProxyJump bastion)", refused["said"])
                self.assertIn("Nothing was bought", refused["said"])
                self.assertNotIn("quote", refused)
                self.assertNotIn("quote", self.state())
                # ssh -vvv -G on the rehearsal file read the copy of the included file and
                # applied its `Host *`; nothing it read was looked for under ~/.ssh.
                with open(trace, encoding="utf-8") as handle:
                    debug = handle.read()
                self.assertRegex(debug, r"Reading configuration data \S*/murmur-ssh-rehearsal"
                                        r"\.\w+/\d+-routing\.conf")
                self.assertRegex(debug, r"\d+-routing\.conf line 1: Applying options for \*")
                self.assertNotIn("matched no files", debug)
                self.assertNotIn(os.path.join(self.home, ".ssh", "ssh_config.d"), debug)
                # The typed price with no quote buys nothing either.
                applied = self.farm("apply", "--confirm-usd", "48", "--quote", "x",
                                    "--wait", "0")
                self.assertNotEqual(applied["code"], 0)
                self.assertEqual(self.creates(), [])
                self.assertEqual([n for n in os.listdir(self.murmur()) if "rehearsal" in n], [])
            os.unlink(os.path.join(os.path.dirname(system), "ssh_config.d", "routing.conf"))

    def test_a_name_the_config_leaves_alone_or_names_only_in_its_section_is_free(self):
        begin = "# >>> murmur farm: written by /murmur:farm, rewritten on every run >>>"
        end = "# <<< murmur farm <<<"
        section = (f"{begin}\nHost farm\n  HostName 203.0.113.9\n  User farm\n"
                   f"  IdentityFile {self.key}\n  IdentitiesOnly yes\n{end}\n")
        self.farm("preflight", expect=0)
        # Wildcards name no name, and a clean config names nothing.
        for text in ("", "AddKeysToAgent yes\n\nHost *\n  IdentityFile ~/.ssh/id_ed25519\n"
                         "  ControlPath ~/.ssh/cm-%h\n  HostName %h.example.com\n\n"
                         "Host f* !farm-old farms\n  User existing-owner\n\n"
                         "Host old\n  HostName 203.0.113.5\n  User me\n"):
            self.config(text)
            self.farm("answer", "--id", "name", "--value", "farm", expect=0)
        # Only this script's own section names it: a rerun keeps its name.
        self.config(section + "\nHost old\n  HostName 203.0.113.5\n")
        self.farm("answer", "--id", "name", "--value", "farm", expect=0)
        # The section and a block of the person's own: that block still owns the name.
        self.config(section + "\nHost farm\n  User existing-owner\n")
        refused = self.farm("answer", "--id", "name", "--value", "farm", expect=1)
        self.assertIn("~/.ssh/config line 9: Host farm", refused["said"])

    def test_a_proxy_left_in_force_after_the_write_stops_before_any_remote_command(self):
        self.bought()
        for option, value in (("ProxyCommand", "ssh -W 127.0.0.1:22 oldbox"),
                              ("ProxyJump", "bastion")):
            # Written after the questions: the section goes before this block, and ssh takes
            # a setting the section leaves unset from the first block that sets it.
            self.config(f"Host farm\n  {option} {value}\n")
            before = len(self.remote_runs())
            stopped = self.farm("ssh-config", expect=1)
            self.assertIn(f"goes through {option} {value}", stopped["said"])
            self.assertIn("nothing was run on the farm", stopped["said"])
            self.assertEqual(len(self.remote_runs()), before)
            self.assertNotIn(["true"], [c["argv"][-1:] for c in self.calls("ssh")])
            # The real ssh agrees that the proxy is still in force for this name.
            seen = subprocess.run([real_ssh(), "-G", "-F",
                                   os.path.join(self.home, ".ssh", "config"), "farm"],
                                  capture_output=True, text=True, timeout=20).stdout
            self.assertIn(f"{option.lower()} {value}", seen)
            self.assertIn(f"hostname {ADDRESS}", seen)
        self.assertNotEqual(self.farm("status")["next"], "finish")

    def test_a_block_ssh_does_not_resolve_to_the_droplet_stops_before_any_remote_command(self):
        self.bought()
        # Written after the plan: the same checks run on the real config, before any command.
        for text, fault in (("User root\n", "logs in as root, not farm (set by ~/.ssh/config "
                                             "line 1: User root)"),
                            ("Port 2222\n", "connects to port 2222, not 22 (set by "
                                             "~/.ssh/config line 1: Port 2222)")):
            self.config(text)
            before = len(self.remote_runs())
            stopped = self.farm("ssh-config", expect=1)
            self.assertIn(fault, stopped["said"])
            self.assertIn("nothing was run on the farm", stopped["said"])
            self.assertEqual(len(self.remote_runs()), before)

    def rehearsal_refuses(self, text, fault):
        """The plan refuses with this config, names the fault and its line, and buys nothing."""
        self.config(text)
        refused = self.farm("plan", expect=1)
        self.assertIn(fault, refused["said"], text)
        self.assertIn("Nothing was bought", refused["said"], text)
        self.assertNotIn("quote", refused)
        self.assertNotIn("quote", self.state())
        self.assertEqual(self.read_config(), text)
        self.assertEqual([n for n in os.listdir(self.murmur()) if "rehearsal" in n], [])

    def test_a_config_that_would_move_the_name_refuses_the_plan_and_buys_nothing(self):
        folder = os.path.join(self.home, ".ssh", "config.d")
        os.makedirs(folder)
        with open(os.path.join(folder, "all"), "w", encoding="utf-8") as handle:
            handle.write("Host *\n  User someone\n")
        self.farm("preflight", expect=0)
        self.answer_all()
        # An absolute Include, and a relative one, which the rehearsal writes as an absolute
        # path under this test's ~/.ssh, where the scan finds it too.
        cases = (
            ("Port 2222\n\nHost old\n  HostName 203.0.113.5\n",
             "it connects to port 2222, not 22 (set by ~/.ssh/config line 1: Port 2222)"),
            (f"Include {folder}/*\n\nHost old\n  HostName 203.0.113.5\n",
             "it logs in as someone, not farm (set by ~/.ssh/config.d/all line 2: User someone)"),
            ("Include config.d/*\n\nHost old\n  HostName 203.0.113.5\n",
             "it logs in as someone, not farm (set by ~/.ssh/config.d/all line 2: User someone)"),
            ("User root\n", "it logs in as root, not farm (set by ~/.ssh/config line 1: "
                            "User root)"),
            ("IdentityFile /home/other/key\n", "it offers the key /home/other/key first"),
            ("Host *\n  ProxyJump bastion\n", "it goes through ProxyJump bastion (set by "
                                               "~/.ssh/config line 2: ProxyJump bastion)"),
            ("Host *\n  ProxyCommand nc -X 5 -x proxy:1080 %h %p\n",
             "it goes through ProxyCommand nc -X 5 -x proxy:1080 %h %p"),
        )
        for text, fault in cases:
            self.rehearsal_refuses(text, fault)
        # A config that turns bad between the plan and the typed price: apply rehearses again.
        self.config("")
        plan = self.farm("plan", expect=0)
        self.config("Port 2222\n")
        refused = self.farm("apply", "--confirm-usd", plan["price_usd"], "--quote",
                            plan["quote"], "--wait", "30", expect=1)
        self.assertIn("connects to port 2222", refused["said"])
        self.assertEqual(self.creates(), [])

    def test_a_setting_the_section_wins_over_passes_and_ssh_really_goes_there(self):
        # The section goes before the first Host line and sets the port and the user itself, so
        # a later `Host *` with another port or user cannot reach the farm's name.
        text = "Host *\n  Port 2222\n  User someone\n"
        self.config(text)
        self.bought()
        self.farm("ssh-config", expect=0)
        seen = subprocess.run([real_ssh(), "-G", "-F", os.path.join(self.home, ".ssh", "config"),
                               "farm"], capture_output=True, text=True, timeout=20).stdout
        self.assertIn("port 22\n", seen)
        self.assertIn("user farm\n", seen)
        self.assertIn(f"hostname {ADDRESS}\n", seen)
        self.assertTrue(self.read_config().endswith(text))
        self.assertEqual(len(self.creates()), 1)


class Key(Laptop):
    """The key must work without a terminal, before any purchase and after boot."""

    def test_a_passphrase_key_not_in_the_agent_stops_the_preflight(self):
        waiting = self.farm("preflight", expect=2, FAKE_KEY_PASSPHRASE="1")
        self.assertEqual(waiting["run_in_your_terminal"], [f"ssh-add {self.key}"])
        self.answer_all()
        self.assertEqual(self.farm("plan", expect=0)["buys"], True)
        refused = self.farm("apply", "--confirm-usd", "48", "--quote", "x", expect=1)
        self.assertEqual(self.creates(), [])
        self.assertTrue(refused["said"])

    def test_on_macos_the_keychain_line_is_printed(self):
        waiting = self.farm("preflight", expect=2, FAKE_KEY_PASSPHRASE="1",
                            MURMUR_PLATFORM="Darwin")
        self.assertIn(f"ssh-add --apple-use-keychain {self.key}",
                      waiting["run_in_your_terminal"])

    def test_a_key_the_agent_holds_passes(self):
        agent = os.path.join(self.home, "agent-keys")
        shutil.copy(self.key + ".pub", agent)
        self.farm("preflight", expect=0, FAKE_KEY_PASSPHRASE="1", FAKE_AGENT_KEYS=agent)

    def test_a_failing_batch_probe_after_boot_stops_before_any_remote_step(self):
        self.bought()
        stopped = self.farm("ssh-config", expect=1, FAKE_SSH_BATCH_FAIL="1")
        self.assertIn("Permission denied", stopped["said"])
        self.assertEqual(self.remote_runs(), ["cloud-init status", "true"])   # the probe only

    def test_no_key_offers_to_make_one(self):
        os.unlink(self.key)
        os.unlink(self.key + ".pub")
        waiting = self.farm("preflight", expect=2)
        self.assertIn("--make-key", json.dumps(waiting))
        self.farm("preflight", "--make-key", expect=0)
        self.assertTrue(os.path.exists(self.key + ".pub"))


class Doctl(Laptop):
    EXCLUDE = ("doctl",)

    def test_on_macos_homebrew_installs_doctl_when_asked(self):
        waiting = self.farm("preflight", expect=2, MURMUR_PLATFORM="Darwin",
                            FAKE_BREW_BIN=self.bin)
        self.assertIn("brew install doctl", json.dumps(waiting))
        self.assertEqual([c["argv"] for c in self.calls("brew")], [])
        self.farm("preflight", "--install-doctl", expect=0, MURMUR_PLATFORM="Darwin",
                  FAKE_BREW_BIN=self.bin)

    def test_a_logged_out_doctl_prints_the_login_and_never_switches_context(self):
        os.symlink(os.path.join(FAKES, "doctl"), os.path.join(self.bin, "doctl"))
        waiting = self.farm("preflight", expect=2, FAKE_DOCTL_LOGGED_IN="")
        self.assertIn("doctl auth init --context murmur", waiting["run_in_your_terminal"])
        for call in self.calls("doctl"):
            self.assertNotIn("switch", call["argv"])
            self.assertEqual(call["argv"][call["argv"].index("--context") + 1], "murmur")

    def test_an_inherited_context_is_ignored_and_nothing_is_bought_under_it(self):
        # FLEET_DOCTL_CONTEXT belongs to a farm, and DIGITALOCEAN_* to doctl itself: on this
        # laptop both may name another account, and neither may choose where a droplet is bought.
        os.symlink(os.path.join(FAKES, "doctl"), os.path.join(self.bin, "doctl"))
        self.env.update({"FLEET_DOCTL_CONTEXT": "company", "DIGITALOCEAN_CONTEXT": "company",
                         "DIGITALOCEAN_ACCESS_TOKEN": "CANARY-company-token"})
        self.bought()
        calls = self.calls("doctl")
        self.assertTrue(calls)
        self.assertEqual(len(self.creates()), 1)
        for call in calls:
            argv = call["argv"]
            self.assertNotIn("company", " ".join(argv), argv)
            self.assertEqual(argv.count("--context"), 1, argv)
            self.assertEqual(argv[argv.index("--context") + 1], "murmur", argv)
            self.assertEqual(call.get("env"), {}, argv)

    def test_the_login_line_unsets_an_inherited_token(self):
        os.symlink(os.path.join(FAKES, "doctl"), os.path.join(self.bin, "doctl"))
        waiting = self.farm("preflight", expect=2, FAKE_DOCTL_LOGGED_IN="",
                            DIGITALOCEAN_ACCESS_TOKEN="CANARY-company-token")
        login = [line for line in waiting["run_in_your_terminal"] if "doctl auth init" in line]
        self.assertEqual(login, ["env -u DIGITALOCEAN_ACCESS_TOKEN doctl auth init --context murmur"])
        self.assertNotIn("CANARY", json.dumps(waiting))


# ------------------------------------------------------------------------------------ open

class Tunnel(Laptop):
    """ssh holds the tunnel through its control socket; the listener is loopback only."""

    def test_open_reuses_replaces_and_stops_the_tunnel(self):
        self.ready()
        first = self.farm("open", expect=0)
        port = first["url"].rsplit(":", 1)[1]
        sock = self.murmur("farm.sock")
        self.assertTrue(os.path.exists(sock))
        with open(self.murmur("farm.tunnel"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), port)
        starts = lambda: [c for c in self.calls("ssh") if "-f" in c["argv"]]  # noqa: E731
        self.assertEqual(len(starts()), 1)
        start = starts()[0]["argv"]
        self.assertIn(f"127.0.0.1:{port}:127.0.0.1:7878", start)
        for option in ("ExitOnForwardFailure=yes", "ServerAliveInterval=30"):
            self.assertIn(option, start)
        self.assertEqual(self.farm("open", expect=0)["url"], first["url"])
        self.assertEqual(len(starts()), 1)                         # reused
        self.assertTrue([c for c in self.calls("ssh") if "check" in c["argv"]])
        # A dead tunnel (a sleep): the socket is stale and a fresh one starts.
        with open(sock, encoding="utf-8") as handle:
            os.kill(int(handle.read().split()[0]), signal.SIGTERM)
        time.sleep(0.3)
        self.farm("open", expect=0)
        self.assertEqual(len(starts()), 2)
        self.farm("open", "--stop", expect=0)
        self.assertFalse(os.path.exists(sock))
        self.assertFalse(os.path.exists(self.murmur("farm.tunnel")))

    def test_a_forward_that_cannot_bind_is_an_error(self):
        self.ready()
        failed = self.farm("open", expect=1, FAKE_SSH_FORWARD_FAIL="1")
        self.assertIn("did not start", failed["said"])
        self.assertFalse(os.path.exists(self.murmur("farm.sock")))

    def test_gateway_ports_in_the_config_still_binds_loopback_and_a_wide_listener_closes(self):
        with open(os.path.join(self.home, ".ssh", "config"), "w", encoding="utf-8") as handle:
            handle.write("Host *\n  GatewayPorts yes\n")
        self.ready()
        failed = self.farm("open", expect=1, FAKE_SSH_LISTEN_ADDR="0.0.0.0")
        start = [c for c in self.calls("ssh") if "-f" in c["argv"]][0]["argv"]
        self.assertTrue(any(w.startswith("127.0.0.1:") for w in start))
        self.assertIn("instead of", failed["said"])
        self.assertTrue([c for c in self.calls("ssh") if "exit" in c["argv"]])
        self.assertFalse(os.path.exists(self.murmur("farm.sock")))

    def test_a_taken_7878_moves_the_tunnel_to_a_free_port(self):
        self.ready()
        with socket.socket() as holder:
            try:
                holder.bind(("127.0.0.1", 7878))
            except OSError:
                self.skipTest("7878 is in use on this machine already")
            holder.listen()
            opened = self.farm("open", "--no-browser", expect=0)
            self.assertNotIn(":7878", opened["url"])
        self.farm("open", "--stop", expect=0)


class Token(Laptop):
    """The token reaches the browser through a one-shot 0600 file, and nowhere else."""

    def test_the_token_is_on_no_stdout_no_argv_and_the_file_goes(self):
        self.ready()
        self.farm("open", expect=0)
        with open(self.opened, encoding="utf-8") as handle:
            handed = [json.loads(line) for line in handle]
        self.assertEqual(len(handed), 1)
        self.assertEqual(handed[0]["mode"], "0o600")
        self.assertIn(f"#token={TOKEN}", handed[0]["body"])
        self.assertNotIn(TOKEN, " ".join(handed[0]["argv"]))
        for call in self.calls():
            self.assertNotIn(TOKEN, " ".join(call["argv"]), call)
        for said in self.outputs:
            self.assertNotIn(TOKEN, said)
        path = handed[0]["argv"][-1]
        deadline = time.time() + 10
        while os.path.exists(path) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(os.path.exists(path), "the handoff file outlived its use")
        self.farm("open", "--stop", expect=0)


# ------------------------------------------------------------------------------- tailscale

class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


class Tailscale(Laptop):
    """Enrolment by stdin, the bind, the reach check, and the fallback to the tunnel."""

    def key_file(self, mode=0o600):
        os.makedirs(self.murmur(), mode=0o700, exist_ok=True)
        path = self.murmur("tailscale.key")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(TS_KEY_TEXT + "\n")
        os.chmod(path, mode)

    def test_wsl_offers_the_tunnel_only(self):
        proc = os.path.join(self.home, "wsl-version")
        with open(proc, "w", encoding="utf-8") as handle:
            handle.write("Linux version 5.15.167.4-microsoft-standard-WSL2\n")
        pre = self.farm("preflight", expect=0, MURMUR_PROC_VERSION=proc,
                        FAKE_LAPTOP_TAILSCALE="running")
        self.assertEqual(pre["access_options"], ["tunnel"])
        self.assertIn("WSL", pre["tailscale"])
        refused = self.farm("answer", "--id", "access", "--value", "tailscale", expect=1)
        self.assertIn("WSL", refused["said"])

    def test_the_tailnet_path_joins_by_stdin_binds_tailscale_and_opens_the_address(self):
        page = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=page.serve_forever, daemon=True).start()
        self.addCleanup(page.server_close)
        self.addCleanup(page.shutdown)
        port = str(page.server_address[1])
        env = {"FAKE_LAPTOP_TAILSCALE": "running", "MURMUR_FARM_REMOTE_PORT": port}
        self.env.update(env)
        with open(os.path.join(self.remote, "env"), "w", encoding="utf-8") as handle:
            handle.write("FLEET_DASH_BIND=127.0.0.1\n")                 # cloud-init's line
        plan = self.bought(access="tailscale")
        self.assertIn("murmur-tailscale-up", plan["cloud_init"])
        self.assertNotIn(TS_KEY_TEXT, plan["cloud_init"])
        self.farm("ssh-config", expect=0)
        self.touch("gh-logged-in")
        done = self.farm("finish", "--wait", "10", expect=0)
        self.assertEqual(done["next"], "tailscale")
        self.assertEqual([l for l in self.remote_env() if l.startswith("FLEET_DASH_BIND=")],
                         ["FLEET_DASH_BIND=tailscale"])
        waiting = self.farm("tailscale", expect=2)
        self.assertIn("tailscale.key", waiting["said"])
        self.key_file()
        joined = self.farm("tailscale", expect=0)
        self.assertEqual(joined["url"], f"http://127.0.0.1:{port}")
        self.assertEqual(joined["next"], "logins")
        with open(os.path.join(self.remote, "ts-key-received"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), TS_KEY_TEXT)
        for call in self.calls():
            self.assertNotIn("CANARY-tailscale", " ".join(call["argv"]))
        stdin_calls = [c for c in self.calls("ssh") if TS_KEY_TEXT in c["stdin"]]
        self.assertEqual(len(stdin_calls), 1)
        self.assertIn("/usr/local/sbin/murmur-tailscale-up", stdin_calls[0]["argv"][-1])
        opened = self.farm("open", expect=0)
        self.assertEqual(opened["url"], f"http://127.0.0.1:{port}")
        self.assertEqual([c for c in self.calls("ssh") if "-f" in c["argv"]], [])

    def test_a_key_file_others_can_read_is_refused(self):
        self.env["FAKE_LAPTOP_TAILSCALE"] = "running"
        self.ready(access="tailscale")
        self.key_file(mode=0o644)
        refused = self.farm("tailscale", expect=1)
        self.assertIn("chmod 600", refused["said"])
        self.assertFalse(self.flag("ts-key-received"))

    def test_the_tunnel_farm_goes_from_tailscale_to_logins(self):
        self.ready()
        self.assertEqual(self.farm("tailscale", expect=0)["next"], "logins")

    def assert_fell_back(self, answer):
        self.assertEqual(answer["access"], "tunnel")
        self.assertEqual(answer["next"], "logins")
        events = self.events()
        bind_at = events.index("env FLEET_DASH_BIND=127.0.0.1", events.index("install"))
        self.assertIn("restart", events[bind_at:])
        self.assertEqual(self.farm("status")["answers"]["access"], "tunnel")
        opened = self.farm("open", "--no-browser", expect=0)
        self.assertTrue(opened["url"].startswith("http://127.0.0.1:"))
        self.farm("open", "--stop", expect=0)

    def test_a_laptop_without_tailscale_ends_in_the_tunnel_with_the_reason(self):
        self.env["FAKE_LAPTOP_TAILSCALE"] = "running"
        self.ready(access="tailscale")
        answer = self.farm("tailscale", expect=0, FAKE_LAPTOP_TAILSCALE="absent")
        self.assertIn("not installed on this laptop", answer["said"])
        self.assert_fell_back(answer)

    def test_a_tailnet_that_cannot_reach_the_farm_ends_in_the_tunnel(self):
        closed = str(free_port())
        self.env.update({"FAKE_LAPTOP_TAILSCALE": "running", "MURMUR_FARM_REMOTE_PORT": closed})
        self.ready(access="tailscale")
        self.key_file()
        answer = self.farm("tailscale", expect=0)
        self.assertIn("cannot reach", answer["said"])
        self.assertEqual(answer["access"], "tunnel")
        events = self.events()
        self.assertLess(events.index("tailscale-up"),
                        events.index("env FLEET_DASH_BIND=127.0.0.1", events.index("install")))
        self.assertEqual(events[-1], "restart")


# ---------------------------------------------------------------------------------- logins

class Logins(Laptop):
    def write_accounts(self, rows):
        with open(os.path.join(self.remote, "accounts.json"), "w", encoding="utf-8") as handle:
            json.dump(rows, handle)

    def test_three_further_subscriptions_are_three_rows_and_three_commands(self):
        self.ready(accounts="work,home,side")
        waiting = self.farm("logins", expect=2)
        adds = [r for r in self.remote_runs() if " accounts add " in r]
        self.assertEqual(adds, [f"/home/farm/.local/bin/fleet accounts add {n}"
                                for n in ("work", "home", "side")])
        printed = waiting["run_in_your_terminal"]
        self.assertEqual(len(printed), 4)
        self.assertEqual(len(set(printed)), 4)
        for name in ("work", "home", "side"):
            self.assertTrue(any(f"CLAUDE_CONFIG_DIR=/home/farm/.fleet/claude-accounts/{name}"
                                in line for line in printed), name)
        self.farm("logins", expect=2)
        self.assertEqual(len([r for r in self.remote_runs() if " accounts add " in r]), 3)
        self.write_accounts([{"name": n, "logged_in": True, "email": f"{n}@example.com"}
                             for n in ("default", "work", "home", "side")])
        done = self.farm("logins", expect=0)
        self.assertIn("4 Claude subscriptions", done["said"])

    def test_a_missing_row_or_a_shared_email_stops_the_move(self):
        self.ready(accounts="work,home")
        self.write_accounts([{"name": "default", "logged_in": True, "email": "a@example.com"},
                             {"name": "work", "logged_in": True, "email": "b@example.com"}])
        refused = self.farm("logins", expect=1, FAKE_ACCOUNTS_ADD_NOOP="1")
        self.assertIn("no account row for home", refused["said"])
        rows = [{"name": "default", "logged_in": True, "email": "a@example.com"},
                {"name": "work", "logged_in": True, "email": "a@example.com"},
                {"name": "home", "logged_in": True, "email": "c@example.com"}]
        self.write_accounts(rows)
        refused = self.farm("logins", expect=1)
        self.assertIn("same email", refused["said"])
        self.assertIn("No lane should move", refused["said"])

    def test_codex_installs_in_the_farms_prefix_logs_in_then_links_and_runs_a_lane(self):
        self.ready(codex="yes")
        self.write_accounts([{"name": "default", "logged_in": True, "email": "a@example.com"}])
        waiting = self.farm("logins", expect=2)
        self.assertIn("npm install --prefix /home/farm/.local -g @openai/codex",
                      self.remote_runs())
        self.assertIn("FLEET_CODEX_BIN=/home/farm/.local/bin/codex", self.remote_env())
        login = [c for c in waiting["run_in_your_terminal"] if "codex login" in c]
        self.assertEqual(len(login), 1)
        self.assertIn("-L 1455:localhost:1455", login[0])
        self.assertNotIn("fleet-install", self.events())      # not before ~/.codex exists
        self.touch("codex-logged-in")
        done = self.farm("logins", "--codex-lane", "demo", "--by", "person", expect=0)
        self.assertIn("Codex is installed", done["said"])
        self.assertIn("fleet-install", self.events())
        self.assertTrue(self.flag("skills-linked"))
        spawn = [r for r in self.remote_runs() if " spawn " in r][0]
        self.assertIn("--engine codex", spawn)
        self.assertEqual(len([r for r in self.remote_runs() if r.startswith("npm ")]), 1)


# ---------------------------------------------------------------------------- remote words

class RemoteWords(Laptop):
    """Every command run or printed over ssh: absolute paths, and no `~` or `$` for a shell."""

    def test_no_tilde_no_dollar_and_absolute_programs(self):
        self.ready(accounts="work", codex="yes")
        printed = self.farm("logins", expect=2)["run_in_your_terminal"]
        self.farm("open", "--no-browser", expect=0)
        self.farm("open", "--stop", expect=0)
        runs = self.remote_runs()
        self.assertGreater(len(runs), 10)
        for remote in runs:
            self.assertNotIn("~", remote)
            self.assertNotIn("$", remote)
            words = shlex.split(remote)
            if words[0] in ("bash",) and len(words) > 2 and words[1] in ("-c", "-lc"):
                words = shlex.split(words[2].replace(";", " ; ").replace("&&", " && "))
            for index, word in enumerate(words):
                first = index == 0 or words[index - 1] in (";", "&&", "then", "else", "if")
                if first:
                    self.assertNotIn(word, ("fleet", "claude", "codex"), remote)
        recorder = os.path.join(self.home, "recorder")
        with open(recorder, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\"; done\n")
        os.chmod(recorder, 0o755)
        for line in printed:
            command = line.split("   then", 1)[0]
            self.assertTrue(command.startswith("ssh "), command)
            done = subprocess.run(["bash", "-c", recorder + command[len("ssh"):]],
                                  capture_output=True, text=True, timeout=30,
                                  env={"HOME": "/home/laptop", "PATH": "/usr/bin:/bin"})
            remote = done.stdout.splitlines()[-1]
            self.assertIn("/home/farm/", remote)
            self.assertNotIn("/home/laptop", remote)


if __name__ == "__main__":
    unittest.main(verbosity=2)

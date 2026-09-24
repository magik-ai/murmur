"""Hosting, the core half: the presets, the machine registry, the provider checks, the installer.

Nothing here reaches a real provider, spends money or touches the live farm. Every test runs
with its own FLEET_STATE, FLEET_CONFIG and HOME, and with fake `doctl`, `ssh`, `ssh-keygen`,
`sudo`, `dpkg` and `id` executables first on PATH (tests/fakes/core), which
record every call as one JSON line in $FAKE_LOG. The installer tests add tests/fakes/core/installer
(gh, hq, uv, claude, loginctl, systemctl, apt-get, curl), so farm/install.sh runs to its last
line on a scratch HOME and changes nothing.

  cd fleet && python3 tests/hosting-test.py
"""
import json
import os
import shutil
import subprocess
import tempfile
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.dirname(HERE)
ROOT = os.path.dirname(FLEET)
FAKES = os.path.join(HERE, "fakes", "core")
MACHINES = os.path.join(FLEET, "lib", "machines.py")
HOSTS = os.path.join(FLEET, "lib", "hosts.py")
sys.path.insert(0, os.path.join(FLEET, "lib"))
import host_presets  # noqa: E402


def machine_presets():
    return [row for row in host_presets.presets() if row["job"] == "machine"]


class Presets(unittest.TestCase):
    """The provider facts, as the research pass of 2026-09-23 recorded them."""

    FIELDS = ("id", "label", "summary", "color", "job", "cli", "install", "login", "whoami", "docs",
              "terms", "stage", "pricing", "sizes", "regions", "engines")

    def test_every_preset_carries_every_field(self):
        for row in host_presets.presets():
            for field in self.FIELDS:
                self.assertIn(field, row, f"{row['id']} has no {field}")
            self.assertTrue(host_presets.ID_RE.match(row["id"]), row["id"])
            self.assertEqual(row["job"], "machine", row["id"])
            self.assertIn(row["stage"], ("ga", "preview", "early access"), row["id"])
            self.assertRegex(row["color"], r"^#[0-9A-Fa-f]{6}$", row["id"])
            # A card says what the provider is in two short lines; prices and caveats wait until
            # it is picked (owner, 2026-09-24).
            self.assertLessEqual(len(row["summary"]), 90, row["id"])

    def test_murmur_ships_your_own_machine_and_a_droplet_and_nothing_else(self):
        # The owner's decision of 2026-09-24: only what has run for real. A preset added back
        # is a contribution, and it changes this list on purpose (CONTRIBUTING.md).
        self.assertEqual([row["id"] for row in host_presets.presets()], ["ssh", "do-droplet"])
        self.assertEqual([row["id"] for row in machine_presets()], ["ssh", "do-droplet"])
        self.assertFalse(hasattr(host_presets, "RUNNER_SECRETS"))

    def test_the_module_offers_the_three_calls_the_brief_names_and_nothing_else(self):
        public = sorted(name for name in vars(host_presets)
                        if callable(getattr(host_presets, name)) and not name.startswith("_")
                        and getattr(getattr(host_presets, name), "__module__", "")
                        == "host_presets")
        self.assertEqual(public, ["preset", "presets", "size"])
        done = subprocess.run([sys.executable, os.path.join(FLEET, "lib", "host_presets.py")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout), (0, ""), "no printer of its own")
        import inspect
        import hosts
        self.assertEqual(list(inspect.signature(hosts.row).parameters), ["preset"],
                         "a provider row is always checked; there is no unchecked mode")

    def test_a_whoami_is_an_argv_list_that_starts_with_the_cli(self):
        for row in host_presets.presets():
            self.assertIsInstance(row["whoami"], list, row["id"])
            self.assertEqual(row["whoami"][0], row["cli"], row["id"])

    def test_no_preset_carries_the_runner_only_fields(self):
        for row in host_presets.presets():
            for field in ("secrets", "output"):
                self.assertNotIn(field, row, row["id"])

    def test_droplet_sizes_and_prices_are_the_research_table(self):
        sizes = host_presets.preset("do-droplet")["sizes"]
        self.assertEqual([(s["slug"], s["vcpu"], s["ram_gb"], s["disk_gb"], s["monthly_usd"])
                          for s in sizes],
                         [("s-2vcpu-4gb", 2, 4, 80, 24),
                          ("s-4vcpu-8gb", 4, 8, 160, 48),
                          ("s-8vcpu-16gb", 8, 16, 320, 96)])
        self.assertEqual(host_presets.DEFAULT_SIZE, "s-4vcpu-8gb")
        self.assertEqual(host_presets.size("do-droplet", "s-4vcpu-8gb")["monthly_usd"], 48)
        self.assertIsNone(host_presets.size("do-droplet", "s-1vcpu-1gb"))
        self.assertIsNone(host_presets.size("no-such-provider", "anything"))

    def test_exactly_one_size_of_a_sized_preset_is_its_default(self):
        for row in host_presets.presets():
            for entry in row["sizes"]:
                self.assertIsInstance(entry.get("default"), bool, (row["id"], entry["slug"]))
            if row["sizes"]:
                defaults = [entry["slug"] for entry in row["sizes"] if entry["default"]]
                self.assertEqual(len(defaults), 1, row["id"])
        droplet = host_presets.preset("do-droplet")["sizes"]
        self.assertEqual([e["slug"] for e in droplet if e["default"]], [host_presets.DEFAULT_SIZE])

    def test_a_price_says_the_day_it_was_read(self):
        self.assertEqual(host_presets.LIST_PRICE_NOTE, "list price on 2026-09-23")
        for row in host_presets.presets():
            if row["sizes"]:
                self.assertIn("list price on 2026-09-23", row["pricing"], row["id"])

    def test_droplet_regions_default_to_frankfurt(self):
        regions = host_presets.preset("do-droplet")["regions"]
        self.assertEqual(regions[0], "fra1")
        self.assertEqual(sorted(regions),
                         sorted(["fra1", "ams3", "lon1", "nyc3", "sfo3", "sgp1", "tor1", "blr1",
                                 "syd1"]))

    def test_what_the_research_could_not_confirm_says_so(self):
        self.assertIn("UNVERIFIED", host_presets.preset("do-droplet")["terms"])

    def test_a_caller_cannot_edit_the_shipped_description(self):
        row = host_presets.preset("do-droplet")
        row["sizes"][0]["monthly_usd"] = 1
        row["label"] = "changed"
        self.assertEqual(host_presets.preset("do-droplet")["sizes"][0]["monthly_usd"], 24)
        self.assertEqual(host_presets.preset("do-droplet")["label"], "DigitalOcean Droplet")
        self.assertIsNone(host_presets.preset("no-such-provider"))

    def test_every_doctl_call_names_the_context_the_login_creates(self):
        for row in host_presets.presets():
            if row["cli"] != "doctl":
                continue
            self.assertIn("--context", row["whoami"], row["id"])
            self.assertIn(host_presets.DOCTL_CONTEXT, row["login"], row["id"])


class Farm(unittest.TestCase):
    """A scratch farm: its own state, config and HOME, and fake provider CLIs on PATH.

    Nothing here reaches a provider or the farm this runs on. Every call a fake sees is
    appended to $FAKE_LOG, which is what proves an argv never carried a secret.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="hosting-test.")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.state = os.path.join(self.home, "state")
        self.config = os.path.join(self.home, "config")
        os.makedirs(self.state)
        os.makedirs(self.config)
        self.fake_log = os.path.join(self.home, "fake-calls.jsonl")
        self.droplets = os.path.join(self.home, "droplets.json")
        self.write_droplets([])
        self.env = dict(
            os.environ,
            HOME=self.home,
            PATH=FAKES + os.pathsep + os.environ.get("PATH", ""),
            FLEET_STATE=self.state,
            FLEET_CONFIG=self.config,
            FAKE_LOG=self.fake_log,
            FAKE_DOCTL_LOGGED_IN="1",
            FAKE_DOCTL_DROPLETS=self.droplets,
            FAKE_DOCTL_SSH_KEYS=os.path.join(self.home, "ssh-keys.json"),
            FAKE_DOCTL_FIREWALLS=os.path.join(self.home, "firewalls.json"),
        )
        self.pubkey = os.path.join(self.home, "person.pub")
        with open(self.pubkey, "w", encoding="utf-8") as handle:
            handle.write("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPERSONPERSONPERSON person@laptop\n")

    # --------------------------------------------------------------------------- the helpers

    def machines(self, *args, **env):
        """`fleet machines ...` as its own process, so the lock and the argv are the real ones."""
        return subprocess.run([sys.executable, MACHINES] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL, env=dict(self.env, **env))

    def ok(self, *args, **env):
        done = self.machines(*args, **env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done

    def refused(self, *args, **env):
        done = self.machines(*args, **env)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        return done.stderr

    def listing(self, **env):
        return json.loads(self.ok("list", "--json", **env).stdout)

    def row(self, name, **env):
        for row in self.listing(**env)["machines"]:
            if row["name"] == name:
                return row
        return None

    def write_droplets(self, rows):
        with open(self.droplets, "w", encoding="utf-8") as handle:
            json.dump(rows, handle)

    def read_droplets(self):
        with open(self.droplets, encoding="utf-8") as handle:
            return json.load(handle)

    def calls(self):
        """Every call a fake recorded, as [{argv, stdin}]."""
        if not os.path.exists(self.fake_log):
            return []
        with open(self.fake_log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def argvs(self, binary):
        return [call["argv"] for call in self.calls() if call["argv"][0] == binary]

    def registry_text(self):
        path = os.path.join(self.config, "machines.toml")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def give_the_droplet_an_address(self, address="192.0.2.10"):
        rows = self.read_droplets()
        rows[0]["networks"] = {"v4": [{"ip_address": address, "type": "public"}]}
        rows[0]["status"] = "active"
        self.write_droplets(rows)

    def create(self, name="farm-1", price="48", **env):
        return self.ok("create", "--provider", "do-droplet", "--name", name,
                       "--size", "s-4vcpu-8gb", "--region", "fra1",
                       "--pubkey-file", self.pubkey, "--confirm-usd", price, **env)


class CloudInit(Farm):
    """What a new droplet gets, and what it must never get."""

    def rendered(self):
        plan = json.loads(self.ok("plan", "--provider", "do-droplet", "--name", "farm-1",
                                  "--size", "s-4vcpu-8gb", "--region", "fra1",
                                  "--pubkey-file", self.pubkey, "--json").stdout)
        return plan["cloud_init"]

    def test_both_keys_reach_the_new_machine(self):
        text = self.rendered()
        self.assertIn("PERSONPERSONPERSON", text)       # the person's key, from --pubkey-file
        self.assertIn("AAAAC3NzaC1lZDI1NTE5AAAAIFAKEFAKE", text)   # this farm's machines key
        self.assertIn("ssh_authorized_keys:", text)
        self.assertIn("name: farm", text)

    def test_gh_comes_from_githubs_own_repository(self):
        text = self.rendered()
        self.assertIn("https://cli.github.com/packages", text)
        self.assertIn("githubcli-archive-keyring.gpg", text)
        self.assertIn("apt-get install -y -qq gh", text)
        for package in ("git", "tmux", "python3", "curl", "ca-certificates"):
            self.assertIn(f"  - {package}", text)

    def test_the_loopback_line_is_a_runcmd_run_as_the_user(self):
        text = self.rendered()
        runcmd = text.split("runcmd:", 1)[1]
        self.assertIn("runuser -u farm -- sh -c", runcmd)
        self.assertIn("FLEET_DASH_BIND=127.0.0.1", runcmd)
        self.assertIn("loginctl enable-linger farm", runcmd)
        # write_files runs before the user exists and would leave root owning its home.
        self.assertNotIn("write_files", text)
        self.assertNotIn("/home/", text)

    def test_the_farms_own_key_is_made_once_and_never_in_the_persons_ssh_directory(self):
        self.rendered()
        key = os.path.join(self.state, "machines", "id_ed25519")
        self.assertTrue(os.path.exists(key))
        self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(key)).st_mode & 0o777, 0o700)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".ssh")))
        self.rendered()
        made = [argv for argv in self.argvs("ssh-keygen") if "-t" in argv]
        self.assertEqual(len(made), 1, made)

    def test_no_secret_is_rendered_into_the_first_boot(self):
        # A farm that stored a runner token before runners were removed still has the file.
        secrets = os.path.join(self.state, "secrets", "hosts", "railway")
        os.makedirs(secrets)
        with open(os.path.join(secrets, "GITHUB_TOKEN"), "w", encoding="utf-8") as handle:
            handle.write("ghp_" + "a" * 36)
        text = self.rendered()
        self.assertNotIn("ghp_", text)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", text)
        self.assertNotIn("GITHUB_TOKEN", text)

    def test_the_plan_prices_from_the_provider_and_says_which_price_it_is(self):
        plan = json.loads(self.ok("plan", "--provider", "do-droplet", "--name", "farm-1",
                                  "--size", "s-4vcpu-8gb", "--region", "fra1",
                                  "--json", FAKE_DOCTL_PRICE="52").stdout)
        self.assertEqual(plan["monthly_usd"], 52.0)
        self.assertEqual(plan["price_source"], "live")
        self.assertTrue(plan["warnings"], "a plan without a public key warns that create needs one")

    def test_without_doctl_the_plan_falls_back_to_the_dated_list_price(self):
        plan = json.loads(self.ok("plan", "--provider", "do-droplet", "--name", "farm-1",
                                  "--size", "s-4vcpu-8gb", "--region", "fra1", "--json",
                                  PATH=os.path.dirname(sys.executable)).stdout)
        self.assertEqual(plan["monthly_usd"], 48)
        self.assertEqual(plan["price_source"], "list")
        self.assertIn("list price on 2026-09-23", plan["price_note"])

    def test_a_size_or_region_this_farm_does_not_offer_is_refused(self):
        said = self.refused("plan", "--provider", "do-droplet", "--name", "farm-1",
                            "--size", "s-96vcpu-1tb", "--region", "fra1")
        self.assertIn("not a size this farm offers", said)
        said = self.refused("plan", "--provider", "do-droplet", "--name", "farm-1",
                            "--size", "s-4vcpu-8gb", "--region", "mars1")
        self.assertIn("not a region this farm offers", said)


class Create(Farm):
    """No droplet that costs money invisibly."""

    def test_the_row_is_written_before_the_provider_is_called(self):
        done = self.machines("create", "--provider", "do-droplet", "--name", "farm-1",
                             "--size", "s-4vcpu-8gb", "--region", "fra1",
                             "--pubkey-file", self.pubkey, "--confirm-usd", "48",
                             FAKE_DOCTL_FAIL_AT="create")
        # An error from the create itself is a lost answer, not a failure: the row stays
        # pending with its price, and nothing is bought again on its own.
        self.assertEqual(done.returncode, 3, done.stdout)
        row = self.row("farm-1")
        self.assertEqual(row["state"], "creating")
        self.assertEqual(row["provider_id"], "")
        self.assertIn("pending", row["detail"])
        self.assertEqual(row["monthly_usd"], 48.0)
        self.assertEqual(self.read_droplets(), [])

    def test_a_refusal_before_the_create_call_is_failed_and_bills_nothing(self):
        done = self.machines("create", "--provider", "do-droplet", "--name", "farm-1",
                             "--size", "s-4vcpu-8gb", "--region", "fra1",
                             "--pubkey-file", self.pubkey, "--confirm-usd", "48",
                             FAKE_DOCTL_FAIL_AT="import")
        self.assertEqual(done.returncode, 1, done.stdout)
        row = self.row("farm-1")
        self.assertEqual(row["state"], "failed")
        self.assertIn("forget farm-1", row["detail"])
        self.assertEqual(self.read_droplets(), [])

    def test_a_live_name_is_never_bought_twice(self):
        self.create()
        said = self.refused("create", "--provider", "do-droplet", "--name", "farm-1",
                            "--size", "s-4vcpu-8gb", "--region", "fra1",
                            "--pubkey-file", self.pubkey, "--confirm-usd", "48")
        self.assertIn("already has a live row", said)
        self.assertEqual(len(self.read_droplets()), 1)

    def test_two_presses_at_once_buy_one_droplet(self):
        # Every doctl call takes a second, so both presses are inside the price check at the
        # same time: the name must be taken and the row written under one lock, after it.
        argv = [sys.executable, MACHINES, "create", "--provider", "do-droplet", "--name",
                "farm-1", "--size", "s-4vcpu-8gb", "--region", "fra1",
                "--pubkey-file", self.pubkey, "--confirm-usd", "48"]
        running = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, text=True,
                                    env=dict(self.env, FAKE_DOCTL_SLEEP="1"))
                   for _ in range(2)]
        answers = [process.communicate(timeout=120) + (process.returncode,)
                   for process in running]
        self.assertEqual(sorted(code for _out, _err, code in answers), [0, 1], answers)
        self.assertTrue(any("already has a live row" in err for _out, err, _code in answers),
                        answers)
        self.assertEqual(len(self.read_droplets()), 1, self.read_droplets())

    def test_a_wrong_price_is_refused(self):
        said = self.refused("create", "--provider", "do-droplet", "--name", "farm-1",
                            "--size", "s-4vcpu-8gb", "--region", "fra1",
                            "--pubkey-file", self.pubkey, "--confirm-usd", "24")
        self.assertIn("the price moved", said)
        self.assertEqual(self.read_droplets(), [])

    def test_a_stale_price_is_refused_when_the_provider_has_moved_on(self):
        said = self.refused("create", "--provider", "do-droplet", "--name", "farm-1",
                            "--size", "s-4vcpu-8gb", "--region", "fra1",
                            "--pubkey-file", self.pubkey, "--confirm-usd", "48",
                            FAKE_DOCTL_PRICE="52")
        self.assertIn("$52", said)
        self.assertEqual(self.read_droplets(), [])

    def test_an_old_list_price_alone_never_buys_a_droplet(self):
        said = self.refused("create", "--provider", "do-droplet", "--name", "farm-1",
                            "--size", "s-4vcpu-8gb", "--region", "fra1",
                            "--pubkey-file", self.pubkey, "--confirm-usd", "48",
                            FAKE_DOCTL_LOGGED_IN="")
        self.assertIn("live price", said)

    def test_the_create_call_is_the_one_the_design_record_names(self):
        self.create()
        created = [argv for argv in self.argvs("doctl") if argv[1:4] == ["compute", "droplet",
                                                                        "create"]]
        self.assertEqual(len(created), 1)
        argv = created[0]
        self.assertNotIn("--wait", argv)
        self.assertIn("--user-data-file", argv)
        tags = argv[argv.index("--tag-names") + 1].split(",")
        # Only the tag the murmur firewall attaches by and this farm's own: no generic tag
        # another firewall could be attached by.
        self.assertEqual(len(tags), 2, tags)
        self.assertEqual(tags[0], "murmur-farm")
        self.assertTrue(tags[1].startswith("murmur-by-"), tags)
        self.assertEqual(argv[argv.index("--image") + 1], "ubuntu-24-04-x64")

    def test_the_calls_that_make_things_name_the_farms_doctl_context(self):
        self.create()
        made = [argv for argv in self.argvs("doctl")
                if argv[1:4] in (["compute", "firewall", "create"],
                                 ["compute", "droplet", "create"])]
        self.assertEqual(len(made), 2, made)
        for argv in made:
            self.assertEqual(argv[argv.index("--context") + 1], "murmur", argv)
        plan = json.loads(self.ok("plan", "--provider", "do-droplet", "--name", "farm-2",
                                  "--size", "s-4vcpu-8gb", "--region", "fra1",
                                  "--json").stdout)
        for argv in plan["commands"]:
            self.assertEqual(argv[argv.index("--context") + 1], "murmur", argv)

    def test_the_key_is_imported_once_and_the_firewall_made_once(self):
        self.create("farm-1")
        self.ok("destroy", "farm-1", "--confirm", "farm-1")
        self.create("farm-2")
        imports = [argv for argv in self.argvs("doctl") if argv[1:4] == ["compute", "ssh-key",
                                                                        "import"]]
        firewalls = [argv for argv in self.argvs("doctl") if argv[1:4] == ["compute", "firewall",
                                                                          "create"]]
        self.assertEqual(len(imports), 1, imports)
        self.assertEqual(len(firewalls), 1, firewalls)
        self.assertIn("--outbound-rules", firewalls[0])   # or the farm cannot reach GitHub

    def test_a_private_key_file_is_never_taken_for_a_public_one(self):
        private = os.path.join(self.home, "id_ed25519")
        with open(private, "w", encoding="utf-8") as handle:
            handle.write("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n"
                         "-----END OPENSSH PRIVATE KEY-----\n")
        said = self.refused("create", "--provider", "do-droplet", "--name", "farm-1",
                            "--size", "s-4vcpu-8gb", "--region", "fra1",
                            "--pubkey-file", private, "--confirm-usd", "48")
        self.assertIn("never a private key", said)


class Walk(Farm):
    """creating, preparing, needs-login, ready: one short step per pass, and no step backwards."""

    def test_a_machine_walks_to_ready_one_pass_at_a_time(self):
        self.create()
        self.assertEqual(self.row("farm-1")["state"], "creating")

        self.assertEqual(self.row("farm-1")["state"], "creating")   # no address yet
        self.give_the_droplet_an_address()

        row = self.row("farm-1")
        self.assertEqual(row["state"], "preparing")
        self.assertEqual(row["address"], "192.0.2.10")

        row = self.row("farm-1", FAKE_SSH_CLOUD_INIT="status: running")
        self.assertEqual(row["state"], "preparing")

        row = self.row("farm-1", FAKE_SSH_CLOUD_INIT="status: done")
        self.assertEqual(row["state"], "needs-login")
        self.assertIn("install.sh --remote", row["finish_command"])
        self.assertIn("farm@192.0.2.10", row["finish_command"])
        self.assertEqual(row["tunnel_command"], "")

        row = self.row("farm-1", FAKE_SSH_CAPACITY="1")
        self.assertEqual(row["state"], "ready")
        self.assertEqual(row["tunnel_command"],
                         "ssh -N -L 7878:127.0.0.1:7878 farm@192.0.2.10")
        self.assertEqual(row["finish_command"], "")

    def test_a_machine_row_carries_its_provider_id(self):
        self.create()
        self.assertEqual(self.row("farm-1")["provider_id"], "9000")
        self.ok("add", "--name", "laptop", "--target", "me@192.0.2.20", FAKE_SSH_CAPACITY="1")
        self.assertEqual(self.row("laptop")["provider_id"], "")

    def test_a_check_never_walks_a_row_backwards(self):
        self.create()
        self.give_the_droplet_an_address()
        self.row("farm-1")
        self.assertEqual(self.row("farm-1", FAKE_SSH_CLOUD_INIT="status: done")["state"],
                         "needs-login")
        # cloud-init on a machine that finished booting long ago says whatever it says; a
        # Check reads the farm instead, so the row cannot fall back to preparing.
        done = self.ok("check", "farm-1", FAKE_SSH_CLOUD_INIT="status: running")
        self.assertIn("needs-login", done.stdout)
        self.assertEqual(self.row("farm-1")["state"], "needs-login")
        self.ok("check", "farm-1", FAKE_SSH_CAPACITY="1")
        self.assertEqual(self.row("farm-1")["state"], "ready")

    def test_a_ready_machine_is_never_ssh_ed_into_by_list(self):
        self.create()
        self.give_the_droplet_an_address()
        self.row("farm-1")
        self.row("farm-1", FAKE_SSH_CLOUD_INIT="status: done")
        self.row("farm-1", FAKE_SSH_CAPACITY="1")
        before = len(self.argvs("ssh"))
        self.listing()
        self.listing()
        self.assertEqual(len(self.argvs("ssh")), before)

    def test_every_ssh_carries_the_farms_own_key_and_never_hangs(self):
        self.create()
        self.give_the_droplet_an_address()
        self.row("farm-1")
        self.row("farm-1", FAKE_SSH_CLOUD_INIT="status: done")
        for argv in self.argvs("ssh"):
            self.assertIn("-i", argv)
            self.assertIn(os.path.join(self.state, "machines", "id_ed25519"), argv)
            self.assertIn("BatchMode=yes", argv)
            self.assertIn("ConnectTimeout=5", argv)
            self.assertIn("StrictHostKeyChecking=accept-new", argv)
            self.assertIn(f"UserKnownHostsFile={self.state}/machines/known_hosts", argv)
            # A droplet's row names no port: 22 is still on the line, so no Port in a person's
            # ssh config moves it.
            self.assertEqual(argv[argv.index("-p") + 1], "22")
        forgotten = [argv for argv in self.argvs("ssh-keygen") if "-R" in argv]
        self.assertTrue(forgotten, "a recorded address forgets its old host key first")
        self.assertIn("192.0.2.10", forgotten[0])

    def test_a_pass_asks_its_machines_together_and_keeps_what_each_one_said(self):
        # Five boxes that do not answer: asked one after the other at the real 15 second SSH
        # timeout, a pass could never fit the refresher's 60 seconds.
        for index in range(5):
            self.ok("add", "--name", f"box-{index}", "--target", f"me@192.0.2.{index + 1}",
                    FAKE_SSH_FAIL="1")
        import time
        started = time.monotonic()
        rows = self.listing(FAKE_SSH_SLEEP="2", FAKE_SSH_CAPACITY="1")["machines"]
        took = time.monotonic() - started
        self.assertEqual([row["state"] for row in rows], ["ready"] * 5)
        self.assertLess(took, 6, f"five machines at 2 seconds each took {took:.1f} seconds")
        self.assertEqual(self.registry_text().count('state = "ready"'), 5)

    def test_a_step_never_writes_a_live_state_over_a_row_destroyed_while_its_ssh_ran(self):
        self.create()
        self.give_the_droplet_an_address()
        self.assertEqual(self.row("farm-1")["state"], "preparing")
        before = len(self.argvs("ssh"))
        slow = subprocess.Popen(
            [sys.executable, MACHINES, "list", "--json"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
            env=dict(self.env, FAKE_SSH_SLEEP="4", FAKE_SSH_CLOUD_INIT="status: done"))
        import time
        deadline = time.monotonic() + 30
        while not any("cloud-init status" in " ".join(argv) for argv in self.argvs("ssh")[before:]):
            self.assertLess(time.monotonic(), deadline, "the slow step never reached its SSH")
            time.sleep(0.1)
        self.ok("destroy", "farm-1", "--confirm", "farm-1")
        out, err = slow.communicate(timeout=60)
        self.assertEqual(slow.returncode, 0, out + err)
        # Read the registry itself: a second `list` would re-mark the row from the provider.
        self.assertIn('state = "destroyed"', self.registry_text())
        self.assertNotIn('state = "needs-login"', self.registry_text())
        shown = {row["name"]: row for row in json.loads(out)["machines"]}
        self.assertEqual(shown["farm-1"]["state"], "destroyed")
        self.assertEqual(json.loads(out)["total_monthly_usd"], 0)

    def test_a_droplet_that_vanished_becomes_destroyed(self):
        self.create()
        self.give_the_droplet_an_address()
        self.assertEqual(self.row("farm-1")["state"], "preparing")
        self.write_droplets([])
        row = self.row("farm-1")
        self.assertEqual(row["state"], "destroyed")
        self.assertIn("billing has stopped", row["detail"])
        self.assertEqual(self.listing()["total_monthly_usd"], 0)

    def test_a_provider_that_did_not_answer_is_the_error_section_7_names(self):
        self.create()
        self.assertEqual(self.listing()["error"], "")
        listing = self.listing(FAKE_DOCTL_FAIL_AT="list")
        self.assertIn("500", listing["error"])
        self.assertNotIn("provider_error", listing)

    def test_this_farm_is_named_by_its_alias_and_never_given_the_alias_as_an_address(self):
        this = self.listing(FLEET_FARM_ALIAS="farm")["this"]
        self.assertEqual(this["name"], "farm")
        self.assertEqual(this["address"], "")

    def test_a_creating_row_finds_its_droplet_by_name_after_a_lost_answer(self):
        self.create()
        self.assertIn('provider_id = "9000"', self.registry_text())
        text = self.registry_text().replace('provider_id = "9000"', "")
        with open(os.path.join(self.config, "machines.toml"), "w", encoding="utf-8") as handle:
            handle.write(text)
        self.assertEqual(self.row("farm-1")["provider_id"], "9000")

    def test_the_total_names_what_is_running(self):
        self.create("farm-1")
        listing = self.listing()
        self.assertEqual(listing["total_monthly_usd"], 48.0)
        # A row the provider never made a droplet for bills nothing and is not in the total.
        self.machines("create", "--provider", "do-droplet", "--name", "farm-2",
                      "--size", "s-4vcpu-8gb", "--region", "fra1",
                      "--pubkey-file", self.pubkey, "--confirm-usd", "48",
                      FAKE_DOCTL_FAIL_AT="import",
                      FAKE_DOCTL_SSH_KEYS=os.path.join(self.home, "no-keys-yet.json"))
        self.assertEqual(self.row("farm-2")["state"], "failed")
        self.assertEqual(self.listing()["total_monthly_usd"], 48.0)
        self.assertIn("$48 a month runs until this droplet is destroyed",
                      self.row("farm-1")["detail"])
        self.assertTrue(listing["this"]["name"])


class DoctlContext(Farm):
    """Every doctl call this farm makes names the context `doctl auth init --context murmur`
    made, read from the argv the fake recorded, not from the preset's text."""

    def every_doctl_call(self, **env):
        self.ok("plan", "--provider", "do-droplet", "--name", "farm-1", "--size", "s-4vcpu-8gb",
                "--region", "fra1", "--json", **env)
        self.create(**env)
        self.give_the_droplet_an_address()
        self.listing(**env)
        self.ok("check", "farm-1", **env)
        self.ok("destroy", "farm-1", "--confirm", "farm-1", **env)
        subprocess.run([sys.executable, HOSTS, "list", "--json"], capture_output=True,
                       text=True, timeout=120, env=dict(self.env, FLEET_WHOAMI_TIMEOUT="2",
                                                        **env))
        seen = self.argvs("doctl")
        verbs = {" ".join(argv[1:4]) for argv in seen}
        for verb in ("compute size list", "compute ssh-key import", "compute firewall create",
                     "compute droplet create", "compute droplet list", "compute droplet get",
                     "compute droplet delete", "account get -o"):
            self.assertIn(verb, verbs)
        return seen

    def test_every_recorded_doctl_argv_carries_the_context(self):
        for argv in self.every_doctl_call():
            self.assertIn("--context", argv, argv)
            self.assertEqual(argv[argv.index("--context") + 1], "murmur", argv)

    def test_an_empty_context_setting_removes_the_flag_from_every_call(self):
        for argv in self.every_doctl_call(FLEET_DOCTL_CONTEXT=""):
            self.assertNotIn("--context", argv, argv)


class Tags(Farm):
    """One farm never reconciles another farm's droplets."""

    def other_farms_droplet(self):
        return {"id": 7777, "name": "someone-elses", "status": "active",
                "tags": ["murmur", "murmur-farm", "murmur-by-heron-0001"],
                "region": {"slug": "fra1"}, "size_slug": "s-4vcpu-8gb",
                "size": {"price_monthly": 48.0},
                "networks": {"v4": [{"ip_address": "198.51.100.5", "type": "public"}]},
                "created_at": "2026-09-01T00:00:00Z"}

    def test_a_droplet_this_farm_made_and_lost_appears_as_unrecorded(self):
        self.create()
        os.unlink(os.path.join(self.config, "machines.toml"))
        row = self.row("farm-1")
        self.assertEqual(row["state"], "unrecorded")
        self.assertEqual(row["monthly_usd"], 48.0)
        self.assertIn("Adopt", row["detail"])
        self.assertEqual(self.listing()["total_monthly_usd"], 48.0)

    def test_an_unrecorded_and_an_adopted_droplet_carry_their_own_sizes_price(self):
        self.ok("create", "--provider", "do-droplet", "--name", "small-1", "--size",
                "s-2vcpu-4gb", "--region", "fra1", "--pubkey-file", self.pubkey,
                "--confirm-usd", "24")
        self.create("farm-1")
        os.unlink(os.path.join(self.config, "machines.toml"))
        prices = {row["name"]: row["monthly_usd"] for row in self.listing()["machines"]}
        self.assertEqual(prices, {"small-1": 24.0, "farm-1": 48.0})
        self.assertEqual(self.listing()["total_monthly_usd"], 72.0)
        self.ok("adopt", "small-1")
        self.assertIn("monthly_usd = 24.0", self.registry_text())

    def test_another_farms_droplet_is_not_ours_to_show(self):
        self.create()
        rows = self.read_droplets()
        rows.append(self.other_farms_droplet())
        self.write_droplets(rows)
        names = [row["name"] for row in self.listing()["machines"]]
        self.assertIn("farm-1", names)
        self.assertNotIn("someone-elses", names)

    def test_adopt_writes_the_row_from_the_providers_own_facts(self):
        self.create()
        self.give_the_droplet_an_address()
        os.unlink(os.path.join(self.config, "machines.toml"))
        self.ok("adopt", "farm-1")
        row = self.row("farm-1")
        self.assertEqual(row["state"], "preparing")
        self.assertEqual(row["address"], "192.0.2.10")
        self.assertEqual(row["monthly_usd"], 48.0)
        self.assertEqual(row["provider_id"], "9000")


class DestroyAndForget(Farm):
    """The two ways a row leaves, and what each of them refuses."""

    def test_destroy_needs_the_name_typed_back(self):
        self.create()
        said = self.refused("destroy", "farm-1", "--confirm", "yes")
        self.assertIn("repeat the name", said)
        self.assertEqual(len(self.read_droplets()), 1)
        self.ok("destroy", "farm-1", "--confirm", "farm-1")
        self.assertEqual(self.read_droplets(), [])
        self.assertEqual(self.row("farm-1")["state"], "destroyed")

    def test_forget_refuses_a_droplet_that_may_still_be_billing(self):
        self.create()
        said = self.refused("forget", "farm-1")
        self.assertIn("may still be billing", said)
        self.ok("destroy", "farm-1", "--confirm", "farm-1")
        self.ok("forget", "farm-1")
        self.assertIsNone(self.row("farm-1"))

    def test_forget_refuses_a_name_it_has_no_row_for(self):
        self.create()
        os.unlink(os.path.join(self.config, "machines.toml"))
        self.assertEqual(self.row("farm-1")["state"], "unrecorded")
        said = self.refused("forget", "farm-1")
        self.assertIn("no machine called farm-1", said)

    def test_forget_drops_a_failed_row_that_never_became_a_droplet(self):
        self.machines("create", "--provider", "do-droplet", "--name", "farm-1",
                      "--size", "s-4vcpu-8gb", "--region", "fra1",
                      "--pubkey-file", self.pubkey, "--confirm-usd", "48",
                      FAKE_DOCTL_FAIL_AT="import")
        self.ok("forget", "farm-1")
        self.assertIsNone(self.row("farm-1"))

    def test_your_own_machine_is_never_deleted_by_this_farm(self):
        self.ok("add", "--name", "laptop", "--target", "me@192.0.2.20", FAKE_SSH_CAPACITY="1")
        said = self.refused("destroy", "laptop", "--confirm", "laptop")
        self.assertIn("did not buy it", said)
        self.ok("forget", "laptop")
        self.assertIsNone(self.row("laptop"))


class OwnMachine(Farm):
    """A box you already have: registered and checked, never bought."""

    def test_add_registers_and_checks(self):
        done = self.ok("add", "--name", "laptop", "--target", "me@192.0.2.20",
                       FAKE_SSH_CAPACITY="1")
        self.assertIn("nothing was bought", done.stdout)
        row = self.row("laptop")
        self.assertEqual((row["state"], row["user"], row["address"], row["monthly_usd"]),
                         ("ready", "me", "192.0.2.20", 0.0))
        self.assertEqual(row["detail"], "the farm answers")

    def test_a_machine_that_does_not_answer_is_unreachable_not_ready(self):
        self.ok("add", "--name", "laptop", "--target", "me@192.0.2.20", FAKE_SSH_FAIL="1")
        self.assertEqual(self.row("laptop")["state"], "unreachable")

    def test_a_box_without_the_fleet_is_needs_login(self):
        self.ok("add", "--name", "laptop", "--target", "me@192.0.2.20")
        row = self.row("laptop")
        self.assertEqual(row["state"], "needs-login")
        self.assertIn("install.sh --remote", row["finish_command"])

    def test_a_port_and_a_target_are_checked_before_any_argv_is_built(self):
        self.assertIn("user@host", self.refused("add", "--name", "laptop", "--target", "nope"))
        self.assertIn("not a port", self.refused("add", "--name", "laptop",
                                                 "--target", "me@192.0.2.20", "--port", "no"))
        self.assertIn("machine name", self.refused("add", "--name", "Laptop; rm -rf /",
                                                   "--target", "me@192.0.2.20"))
        self.assertEqual(self.argvs("ssh"), [])

    def test_a_port_reaches_the_ssh_command_line(self):
        self.ok("add", "--name", "laptop", "--target", "me@192.0.2.20", "--port", "2222",
                FAKE_SSH_CAPACITY="1")
        self.assertIn("-p", self.argvs("ssh")[0])
        self.assertIn("2222", self.argvs("ssh")[0])


class OneWriterAtATime(Farm):
    """The registry under contention: the refresher, a job and a person, all at once."""

    def test_concurrent_writers_do_not_lose_a_row(self):
        names = [f"box-{index}" for index in range(8)]
        running = [subprocess.Popen(
            [sys.executable, MACHINES, "add", "--name", name, "--target", f"me@192.0.2.{index}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, env=dict(self.env, FAKE_SSH_CAPACITY="1")) for index, name in
            enumerate(names)]
        for process in running:
            out, err = process.communicate(timeout=120)
            self.assertEqual(process.returncode, 0, out + err)
        written = sorted(row["name"] for row in self.listing()["machines"])
        self.assertEqual(written, sorted(names))

    def test_the_registry_is_toml_a_person_can_read_and_a_quote_cannot_break(self):
        self.ok("add", "--name", "laptop", "--target", "me@192.0.2.20", FAKE_SSH_CAPACITY="1")
        text = self.registry_text()
        self.assertIn("[laptop]", text)
        self.assertIn('provider = "ssh"', text)
        self.assertEqual(os.stat(os.path.join(self.config, "machines.toml")).st_mode & 0o777,
                         0o600)

    def test_the_farm_id_is_made_once_and_kept(self):
        self.create()
        with open(os.path.join(self.config, "farm-id"), encoding="utf-8") as handle:
            first = handle.read().strip()
        self.listing()
        with open(os.path.join(self.config, "farm-id"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), first)
        self.assertRegex(first, r"^[a-z]+-[0-9a-f]{4}$")


class HostsFarm(Farm):
    """A scratch farm plus the two ways this suite asks `fleet hosts` anything."""

    def hosts(self, *args, stdin="", **env):
        return subprocess.run([sys.executable, HOSTS] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=120, input=stdin,
                              env=dict(self.env, FLEET_WHOAMI_TIMEOUT="2", **env))

    def providers(self, **env):
        done = self.hosts("list", "--json", **env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return {row["id"]: row for row in json.loads(done.stdout)["providers"]}


class Hosts(HostsFarm):
    """Is the CLI there, is it logged in, and what does a slow provider look like."""

    def test_every_provider_carries_the_fields_the_page_reads(self):
        rows = self.providers()
        self.assertEqual(sorted(rows), sorted(["ssh", "do-droplet"]))
        for row in rows.values():
            for field in ("id", "label", "job", "stage", "cli_installed", "login_state",
                          "account", "detail", "checked_at", "login",
                          "install", "terms", "pricing", "sizes", "regions",
                          # the contract amendment of the PR 40 fix round
                          "cli", "color", "engines", "docs"):
                self.assertIn(field, row, row["id"])
            # The runner-only fields went with the runners (2026-09-24).
            for field in ("secrets", "tested"):
                self.assertNotIn(field, row, row["id"])
            for entry in row["sizes"]:
                self.assertIn("default", entry, row["id"])
            self.assertIn(row["login_state"], ("logged_in", "logged_out", "not_installed",
                                               "no_answer"), row["id"])

    def test_a_logged_in_provider_names_its_account_where_it_documents_one(self):
        rows = self.providers()
        self.assertEqual(rows["do-droplet"]["login_state"], "logged_in")
        self.assertEqual(rows["do-droplet"]["account"], "owner@example.com")
        # ssh has no account at all, so this farm invents none.
        self.assertIsNone(rows["ssh"]["account"])

    def test_a_logged_out_provider_is_not_a_missing_one(self):
        rows = self.providers(FAKE_DOCTL_LOGGED_IN="")
        self.assertEqual(rows["do-droplet"]["login_state"], "logged_out")
        self.assertTrue(rows["do-droplet"]["cli_installed"])
        self.assertIn("access token", rows["do-droplet"]["detail"])

    def test_a_cli_that_is_not_there_says_how_to_install_it(self):
        rows = self.providers(PATH=os.path.dirname(sys.executable))
        self.assertEqual(rows["do-droplet"]["login_state"], "not_installed")
        self.assertFalse(rows["do-droplet"]["cli_installed"])
        done = self.hosts("check", "do-droplet", PATH=os.path.dirname(sys.executable))
        self.assertIn("docs.digitalocean.com/reference/doctl/how-to/install", done.stdout)

    def test_a_slow_provider_is_no_answer_and_never_logged_out(self):
        rows = self.providers(FAKE_DOCTL_SLEEP="8")
        self.assertEqual(rows["do-droplet"]["login_state"], "no_answer")
        self.assertIn("no answer", rows["do-droplet"]["detail"])

    def test_the_shipped_check_timeout_is_the_design_records_fifteen_seconds(self):
        done = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); import hosts; print(hosts.WHOAMI_TIMEOUT)"
             % os.path.join(FLEET, "lib")],
            capture_output=True, text=True, timeout=60,
            env={key: value for key, value in self.env.items()
                 if key != "FLEET_WHOAMI_TIMEOUT"})
        self.assertEqual(done.stdout.strip(), "15", done.stderr)

    def test_your_own_machine_has_no_account_to_log_in_to(self):
        row = self.providers()["ssh"]
        self.assertEqual(row["login_state"], "logged_in")
        self.assertIn("fleet machines check", row["detail"])



class LeftoverRunnerSecrets(HostsFarm):
    """A farm that stored a runner token before runners were removed (2026-09-24) keeps the
    file, because nothing here deletes a person's things. It is never listed, and it is still
    scrubbed out of whatever a provider CLI prints."""

    VALUE = "sandbox-secret-value-987654"

    def setUp(self):
        super().setUp()
        folder = os.path.join(self.state, "secrets", "hosts", "railway")
        os.makedirs(folder, mode=0o700)
        with open(os.path.join(folder, "CLAUDE_CODE_OAUTH_TOKEN"), "w",
                  encoding="utf-8") as handle:
            handle.write(self.VALUE)

    def test_the_old_provider_is_not_listed_and_its_file_is_kept(self):
        rows = self.providers()
        self.assertEqual(sorted(rows), ["do-droplet", "ssh"])
        self.assertTrue(os.path.exists(os.path.join(self.state, "secrets", "hosts", "railway",
                                                    "CLAUDE_CODE_OAUTH_TOKEN")))

    def test_a_provider_that_prints_a_stored_secret_is_scrubbed_before_anyone_reads_it(self):
        done = self.hosts("check", "do-droplet", FAKE_DOCTL_LOGGED_IN="",
                          FAKE_DOCTL_LEAK=self.VALUE)
        self.assertNotIn(self.VALUE, done.stdout + done.stderr)
        self.assertIn("[redacted]", done.stdout)

    def test_the_secret_command_is_gone(self):
        done = self.hosts("secret", "railway", "GITHUB_TOKEN", stdin="x" * 20)
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn("stored", done.stdout)
        self.assertIsNone(host_presets.preset("railway"))


class Installer(unittest.TestCase):
    """farm/install.sh: the preflight that stops before anything changes, and --remote.

    Nothing here installs anything: `sudo` is a fake that runs no command at all, whatever
    answer it gives, so a test that got past the preflight still changes nothing.
    """

    SCRIPT = os.path.join(ROOT, "farm", "install.sh")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="hosting-installer-test.")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.fake_log = os.path.join(self.home, "fake-calls.jsonl")
        self.config = os.path.join(self.home, "config", "fleet")
        # The installer fakes (gh, hq, uv, claude, loginctl, systemctl, apt-get, curl) come
        # first too, so a run that gets past the preflight clones, downloads and installs
        # nothing and reaches the last line on this scratch HOME.
        self.env = dict(os.environ, HOME=self.home, FAKE_LOG=self.fake_log, USER="farm",
                        FLEET_CONFIG=self.config,
                        XDG_CONFIG_HOME=os.path.join(self.home, "config"),
                        PATH=os.pathsep.join([os.path.join(FAKES, "installer"), FAKES,
                                              os.environ.get("PATH", "")]))

    def install(self, *args, **env):
        return subprocess.run(["bash", self.SCRIPT] + list(args), capture_output=True,
                              text=True, timeout=120, stdin=subprocess.DEVNULL,
                              env=dict(self.env, **env))

    def calls(self):
        if not os.path.exists(self.fake_log):
            return []
        with open(self.fake_log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_the_shell_parses(self):
        done = subprocess.run(["bash", "-n", self.SCRIPT], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_remote_is_a_flag_and_the_help_says_what_it_does(self):
        done = self.install("--remote", "--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--remote", done.stdout)
        self.assertNotIn("unknown flag", done.stdout + done.stderr)

    @unittest.skipIf(os.geteuid() == 0, "root can install packages, so the preflight lets it by")
    def test_a_user_who_cannot_install_is_told_before_anything_changes(self):
        done = self.install("--remote", FAKE_DPKG_MISSING="tmux curl")
        self.assertEqual(done.returncode, 1, done.stdout)
        said = done.stdout + done.stderr
        self.assertIn("this box is missing", said)
        self.assertIn("tmux", said)
        self.assertIn("curl", said)
        self.assertIn("sudo apt-get install -y", said)
        self.assertNotIn("1/5", said)                  # it stopped before step 1
        self.assertEqual([call["argv"] for call in self.calls() if call["argv"][0] == "sudo"],
                         [["sudo", "-n", "true"]])

    def sudo_calls(self):
        return [call["argv"] for call in self.calls() if call["argv"][0] == "sudo"]

    def env_file(self):
        path = os.path.join(self.config, "env")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    @unittest.skipIf(os.geteuid() == 0, "root takes a different path through step 1")
    def test_a_user_who_can_install_is_let_through_the_preflight(self):
        done = self.install("--remote", FAKE_DPKG_MISSING="tmux", FAKE_SUDO_OK="1")
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        self.assertNotIn("this box is missing", said)
        self.assertIn("5/5", said)
        self.assertEqual(self.sudo_calls(), [["sudo", "-n", "true"],
                                             ["sudo", "apt-get", "update", "-qq"],
                                             ["sudo", "apt-get", "install", "-y", "-qq", "tmux"]])

    @unittest.skipIf(os.geteuid() == 0, "root takes a different path through step 1")
    def test_remote_runs_to_the_end_on_loopback_and_prints_the_tunnel(self):
        # The droplet's cloud-init wrote the loopback line before the installer ever ran.
        os.makedirs(self.config)
        with open(os.path.join(self.config, "env"), "w", encoding="utf-8") as handle:
            handle.write("FLEET_DASH_BIND=127.0.0.1\n")
        done = self.install("--remote",
                            SSH_CONNECTION="198.51.100.9 50000 192.0.2.44 22")
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        self.assertIn("ssh -N -L 7878:127.0.0.1:7878 farm@192.0.2.44", said)
        self.assertNotIn("Tailscale (a private network", said)   # the question is never asked
        self.assertEqual(self.sudo_calls(), [])     # nothing was missing, so sudo was not asked
        # The bind line is still the one cloud-init wrote, and no other was added.
        lines = self.env_file().splitlines()
        self.assertEqual([line for line in lines if line.startswith("FLEET_DASH_BIND=")],
                         ["FLEET_DASH_BIND=127.0.0.1"])
        # The fleet was installed as a farm driven from elsewhere, not in single-machine mode.
        with open(os.path.join(self.home, "fleet-install.txt"), encoding="utf-8") as handle:
            self.assertNotIn("--local", handle.read())
        self.assertEqual([argv for argv in (c["argv"] for c in self.calls())
                          if argv[0] in ("curl", "apt-get")], [])

    @unittest.skipIf(os.geteuid() == 0, "root takes a different path through step 1")
    def test_remote_on_a_box_without_a_bind_line_never_writes_one(self):
        done = self.install("--remote")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("FLEET_DASH_BIND", self.env_file())
        self.assertIn("FLEET_FARM_ALIAS=farm", self.env_file())

    def install_on_a_terminal(self, *args, **env):
        """The installer as `curl ... | bash` runs it from a person's terminal: stdin is not a
        terminal, but /dev/tty is, so sudo can ask for a password there."""
        import pty
        leader, follower = pty.openpty()
        follower_name = os.ttyname(follower)
        os.close(follower)

        def own_terminal():
            os.setsid()
            os.close(os.open(follower_name, os.O_RDWR))   # the first tty opened becomes ours

        try:
            return subprocess.run(["bash", self.SCRIPT] + list(args), capture_output=True,
                                  text=True, timeout=120, stdin=subprocess.DEVNULL,
                                  env=dict(self.env, **env), preexec_fn=own_terminal)
        finally:
            os.close(leader)

    @unittest.skipIf(os.geteuid() == 0, "root takes a different path through step 1")
    def test_an_administrator_at_a_terminal_is_asked_for_the_password_not_stopped(self):
        done = self.install_on_a_terminal("--remote", FAKE_DPKG_MISSING="tmux",
                                          FAKE_ID_GROUPS="me sudo")
        said = done.stdout + done.stderr
        self.assertNotIn("this box is missing", said)
        self.assertIn("1/5", said)
        # Step 1 went to sudo for apt, where a real sudo prompts on the terminal.
        self.assertIn(["sudo", "apt-get", "update", "-qq"],
                      [call["argv"] for call in self.calls() if call["argv"][0] == "sudo"])

    @unittest.skipIf(os.geteuid() == 0, "root can install packages, so the preflight lets it by")
    def test_a_terminal_alone_is_not_permission_to_install(self):
        done = self.install_on_a_terminal("--remote", FAKE_DPKG_MISSING="tmux",
                                          FAKE_ID_GROUPS="farm")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("this box is missing", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

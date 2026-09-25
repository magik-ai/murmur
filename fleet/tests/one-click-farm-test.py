"""The one-click farm, the fleet half: the machines a laptop buys, the installer, the dashboard.

The design record is `fleet/docs/design/one-click-farm.md`; the laptop half (the plugin's
`murmur_farm.py`) is tested in `tests/test_murmur_farm.py`. Nothing here reaches a provider,
spends money or touches the farm it runs on: every test has its own HOME, FLEET_STATE and
FLEET_CONFIG, and fake CLIs first on PATH (tests/fakes/core) record every call in $FAKE_LOG.

  cd fleet && python3 tests/one-click-farm-test.py
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.dirname(HERE)
ROOT = os.path.dirname(FLEET)
FAKES = os.path.join(HERE, "fakes", "core")
MACHINES = os.path.join(FLEET, "lib", "machines.py")
sys.path.insert(0, os.path.join(FLEET, "lib"))
import machines  # noqa: E402

PERSON_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPERSONPERSONPERSON person@laptop"


class Farm(unittest.TestCase):
    """A scratch farm with the fake provider CLIs, as tests/hosting-test.py builds one."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="one-click-test.")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.state = os.path.join(self.home, "state")
        self.config = os.path.join(self.home, "config")
        os.makedirs(self.state)
        os.makedirs(self.config)
        self.fake_log = os.path.join(self.home, "fake-calls.jsonl")
        self.droplets = os.path.join(self.home, "droplets.json")
        self.firewalls = os.path.join(self.home, "firewalls.json")
        self.tags = os.path.join(self.home, "tags.json")
        self.write_json(self.droplets, [])
        self.write_json(self.tags, [])
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
            FAKE_DOCTL_FIREWALLS=self.firewalls,
            FAKE_DOCTL_TAGS=self.tags,
            FLEET_MACHINES_FIREWALL_POLL="0.1",
            FLEET_MACHINES_PENDING_WINDOW="3",
            FLEET_MACHINES_PENDING_POLL="0.2",
        )
        self.pubkey = os.path.join(self.home, "person.pub")
        with open(self.pubkey, "w", encoding="utf-8") as handle:
            handle.write(PERSON_KEY + "\n")

    def write_json(self, path, value):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(value, handle)

    def read_json(self, path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def machines(self, *args, **env):
        return subprocess.run([sys.executable, MACHINES] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL, env=dict(self.env, **env))

    def create(self, name="farm", price="48", **env):
        return self.machines("create", "--provider", "do-droplet", "--name", name,
                             "--size", "s-4vcpu-8gb", "--region", "fra1",
                             "--pubkey-file", self.pubkey, "--confirm-usd", price, **env)

    def calls(self):
        if not os.path.exists(self.fake_log):
            return []
        with open(self.fake_log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def doctl(self, *verb):
        return [c["argv"] for c in self.calls()
                if c["argv"][0] == "doctl" and tuple(c["argv"][1:1 + len(verb)]) == verb]

    def creates(self):
        return self.doctl("compute", "droplet", "create")

    def registry(self):
        listing = json.loads(self.machines("list", "--json").stdout)
        return {row["name"]: row for row in listing["machines"]}

    def farm_tag(self):
        with open(os.path.join(self.config, "farm-id"), encoding="utf-8") as handle:
            return "murmur-by-" + handle.read().strip()

    def age_the_attempt(self, name="farm", seconds=3600):
        """Move a row's created_at back, so the pending window has passed."""
        path = os.path.join(self.config, "machines.toml")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds))
        lines = []
        inside = False
        for line in text.splitlines():
            if line.startswith("["):
                inside = line.strip("[]\"") == name
            if inside and line.startswith("created_at = "):
                line = f'created_at = "{old}"'
            lines.append(line)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


class LostCreate(Farm):
    """A create whose answer was lost is pending, never failed, and never bought again."""

    def test_the_lost_create_is_adopted_on_the_rerun_and_create_is_never_called_again(self):
        done = self.create(FAKE_DOCTL_CREATE_LOST="1")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("pending", done.stderr)
        self.assertEqual(len(self.creates()), 1)
        row = self.registry()["farm"]
        self.assertEqual(row["state"], "creating")
        self.assertEqual(row["monthly_usd"], 48.0)
        # The rerun with the same typed price: the row is live, so nothing is bought.
        again = self.create()
        self.assertEqual(again.returncode, 1)
        self.assertIn("already has a live row", again.stderr)
        self.assertEqual(len(self.creates()), 1)
        # The list adopts it by name on this farm's tag.
        self.assertEqual(self.registry()["farm"]["provider_id"], "9000")
        self.assertEqual(len(self.read_json(self.droplets)), 1)

    def test_the_slow_create_is_waited_on_and_never_started_twice(self):
        done = self.create(FAKE_DOCTL_CREATE_LATE="1.5")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(self.registry()["farm"]["provider_id"], "")   # not listed yet
        row = machines_in(self.env, "wait_pending", "farm", 20, 0.2)
        self.assertEqual(row["provider_id"], "9000")
        self.assertIn("adopted", row["detail"])
        self.assertEqual(len(self.creates()), 1)

    def test_a_create_that_waits_adopts_the_droplet_that_appears(self):
        done = self.machines("create", "--provider", "do-droplet", "--name", "farm",
                             "--size", "s-4vcpu-8gb", "--region", "fra1",
                             "--pubkey-file", self.pubkey, "--confirm-usd", "48",
                             "--wait-pending", "20", FAKE_DOCTL_CREATE_LATE="1")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("adopted, not bought again", done.stdout)
        self.assertEqual(len(self.creates()), 1)

    def test_forget_attempt_is_refused_while_the_droplet_may_still_appear(self):
        done = self.create(FAKE_DOCTL_CREATE_LATE="1", FLEET_MACHINES_PENDING_WINDOW="30")
        self.assertEqual(done.returncode, 3)
        done = self.machines("forget-attempt", "farm", FLEET_MACHINES_PENDING_WINDOW="30")
        self.assertEqual(done.returncode, 1)
        self.assertIn("may still appear", done.stderr)

    def test_a_droplet_that_never_appears_waits_for_forget_attempt_and_a_new_price(self):
        done = self.create(FAKE_DOCTL_FAIL_AT="create")          # a refusal: nothing was made
        self.assertEqual(done.returncode, 3)
        row = machines_in(self.env, "wait_pending", "farm", 1, 0.2)
        self.assertEqual(row["provider_id"], "")
        self.assertIn("forget-attempt farm", row["detail"])
        self.assertEqual(len(self.creates()), 1)
        # Nothing is bought on its own, and a rerun of create is refused while it is pending.
        self.assertEqual(self.create().returncode, 1)
        self.assertEqual(len(self.creates()), 1)
        self.age_the_attempt()
        done = self.machines("forget-attempt", "farm")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("price confirmed again", done.stdout)
        self.assertNotIn("farm", self.registry())
        # A new purchase goes through the price again.
        self.assertEqual(self.create(price="24").returncode, 1)
        self.assertEqual(self.create().returncode, 0)
        self.assertEqual(len(self.creates()), 2)

    def test_forget_attempt_adopts_a_droplet_that_did_appear(self):
        self.create(FAKE_DOCTL_CREATE_LOST="1")
        # The list has not run, so the row is still pending when forget-attempt asks.
        self.age_the_attempt()
        done = self.machines("forget-attempt", "farm")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("adopted instead of forgotten", done.stdout)

    def test_forget_attempt_is_only_for_a_pending_create(self):
        self.assertEqual(self.create().returncode, 0)
        done = self.machines("forget-attempt", "farm")
        self.assertEqual(done.returncode, 1)
        self.assertIn("not a pending create", done.stderr)

    def test_a_pending_row_says_forget_attempt_on_the_list_after_the_window(self):
        self.create(FAKE_DOCTL_FAIL_AT="create")
        self.age_the_attempt()
        row = self.registry()["farm"]
        self.assertIn("forget-attempt farm", row["detail"])
        self.assertEqual(row["state"], "creating")


class Prices(Farm):
    """A price is a finite number above zero before it is compared with anything."""

    def test_the_parser_refuses_nan_inf_and_negatives(self):
        for bad in ("nan", "NaN", "inf", "-inf", "-48", "0", "", "48usd", None, True,
                    float("nan"), float("inf"), "1e400"):
            self.assertIsNone(machines.usd(bad), bad)
        self.assertEqual(machines.usd("48"), 48.0)
        self.assertEqual(machines.usd(12.5), 12.5)

    def test_a_typed_nan_inf_or_negative_price_buys_nothing(self):
        for bad in ("nan", "inf", "-48"):
            done = self.create(price=bad)
            self.assertNotEqual(done.returncode, 0, bad)
            self.assertIn("is not a price", done.stderr, bad)
        self.assertEqual(self.creates(), [])

    def test_a_nan_price_from_doctl_is_not_live_and_buys_nothing(self):
        for typed in ("nan", "48"):
            done = self.create(price=typed, FAKE_DOCTL_PRICE="nan")
            self.assertNotEqual(done.returncode, 0, typed)
        self.assertEqual(self.creates(), [])
        self.assertEqual(machines.droplet_price({"size": {"price_monthly": float("nan")},
                                                 "size_slug": "s-4vcpu-8gb"}), 48.0)


class Reconcile(Farm):
    """Before any create: this farm's tag and the name. One is adopted, more stop the run."""

    def droplet(self, droplet_id, name, tags):
        return {"id": droplet_id, "name": name, "status": "active", "tags": tags,
                "region": {"slug": "fra1"}, "size_slug": "s-4vcpu-8gb",
                "size": {"slug": "s-4vcpu-8gb", "price_monthly": 48.0},
                "networks": {"v4": [{"ip_address": "192.0.2.77", "type": "public"}]},
                "created_at": "2026-09-24T10:00:00Z"}

    def test_another_farms_droplet_with_the_same_name_is_never_adopted(self):
        machines_in(self.env, "farm_id")
        self.write_json(self.droplets, [self.droplet(501, "farm", ["murmur", "murmur-farm",
                                                                   "murmur-by-otter-0001"])])
        done = self.create()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("asked for", done.stdout)
        self.assertNotEqual(self.registry()["farm"]["provider_id"], "501")

    def test_one_droplet_on_this_farms_tag_is_adopted_not_bought(self):
        machines_in(self.env, "farm_id")
        self.write_json(self.droplets, [self.droplet(502, "farm", ["murmur", self.farm_tag()])])
        done = self.create()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("adopted, not bought again", done.stdout)
        self.assertEqual(self.creates(), [])
        row = self.registry()["farm"]
        self.assertEqual((row["provider_id"], row["address"]), ("502", "192.0.2.77"))

    def test_two_candidates_on_this_farms_tag_stop_the_run(self):
        machines_in(self.env, "farm_id")
        tag = self.farm_tag()
        self.write_json(self.droplets, [self.droplet(503, "farm", [tag]),
                                        self.droplet(504, "farm", [tag])])
        done = self.create()
        self.assertEqual(done.returncode, 1)
        self.assertIn("2 droplets named farm", done.stderr)
        self.assertIn("503", done.stderr)
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.registry()["farm"]["state"], "unrecorded")   # no row was written

    def test_a_list_that_fails_buys_nothing(self):
        done = self.create(FAKE_DOCTL_FAIL_AT="list")
        self.assertEqual(done.returncode, 1)
        self.assertIn("nothing is bought", done.stderr)
        self.assertEqual(self.creates(), [])

    def test_plan_create_and_resume_share_one_farm_id(self):
        first = machines_in(self.env, "farm_tag")
        self.create(FAKE_DOCTL_CREATE_LOST="1")
        created = self.creates()[0]
        tags = created[created.index("--tag-names") + 1].split(",")
        self.assertIn(first, tags)
        listed = self.doctl("compute", "droplet", "list")
        self.assertTrue(listed and all(argv[argv.index("--tag-name") + 1] == first
                                       for argv in listed))
        self.assertEqual(machines_in(self.env, "farm_tag"), first)


class Firewall(Farm):
    """`murmur-ssh-only` is checked by its rules and its tag, never trusted by its name."""

    def wall(self, **change):
        row = {"id": "fw-9", "name": "murmur-ssh-only", "status": "succeeded",
               "tags": ["murmur-farm"], "droplet_ids": [77],
               "inbound_rules": [{"protocol": "tcp", "ports": "22",
                                  "sources": {"addresses": ["0.0.0.0/0", "::/0"]}}],
               "outbound_rules": self.everything_out()}
        row.update(change)
        return row

    @staticmethod
    def everything_out():
        """tcp, udp and icmp to 0.0.0.0/0 and ::/0, as the API prints the rules the script
        writes: every port reads back as "0"."""
        return [{"protocol": protocol, "ports": "0",
                 "destinations": {"addresses": ["0.0.0.0/0", "::/0"]}}
                for protocol in ("tcp", "udp", "icmp")]

    def corrected(self, done):
        """The create went through, after one update, and the wall now reads back right."""
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.doctl("compute", "firewall", "update")), 1)
        wall = self.read_json(self.firewalls)[0]
        self.assertEqual(machines.firewall_faults(wall), [])
        self.assertEqual(len(self.creates()), 1)

    def bought_nothing(self, done, said="still wrong"):
        self.assertEqual(done.returncode, 1)
        self.assertIn(said, done.stderr)
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.read_json(self.droplets), [])
        self.assertEqual(self.registry()["farm"]["state"], "failed")

    def test_a_right_firewall_is_left_alone(self):
        self.write_json(self.firewalls, [self.wall()])
        self.assertEqual(self.create().returncode, 0)
        self.assertEqual(self.doctl("compute", "firewall", "update"), [])
        self.assertEqual(self.doctl("compute", "firewall", "create"), [])

    def test_the_tag_is_made_before_the_firewall_that_names_it(self):
        done = self.create()
        self.assertEqual(done.returncode, 0, done.stderr)
        verbs = [tuple(c["argv"][1:4]) for c in self.calls() if c["argv"][0] == "doctl"]
        made = verbs.index(("compute", "tag", "create"))
        self.assertLess(made, verbs.index(("compute", "firewall", "create")))
        self.assertEqual(self.read_json(self.tags), ["murmur-farm"])
        self.assertEqual(machines.firewall_faults(self.read_json(self.firewalls)[0]), [])

    def test_a_tag_that_already_exists_is_fine(self):
        self.write_json(self.tags, ["murmur-farm"])
        self.write_json(self.firewalls, [self.wall(tags=[])])
        self.corrected(self.create())

    def test_a_refused_tag_buys_nothing(self):
        self.bought_nothing(self.create(FAKE_DOCTL_FAIL_AT="tag"), said="tag")

    def test_a_deny_rule_on_22_is_corrected(self):
        self.write_json(self.firewalls, [self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "action": "deny",
             "sources": {"addresses": ["0.0.0.0/0"]}}])])
        self.corrected(self.create())

    def test_ssh_narrowed_to_other_sources_is_corrected(self):
        # The laptop's address is not known and changes: tcp 22 from one range only would sell a
        # farm the person cannot ssh into.
        self.write_json(self.firewalls, [self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["192.0.2.0/24"]}}])])
        self.corrected(self.create())
        wall = self.read_json(self.firewalls)[0]
        sources = {address for rule in wall["inbound_rules"]
                   for address in rule["sources"]["addresses"]}
        self.assertEqual(sources, {"0.0.0.0/0", "::/0"})

    def test_ssh_from_ipv4_only_is_corrected(self):
        self.write_json(self.firewalls, [self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["0.0.0.0/0"]}}])])
        self.corrected(self.create())

    def test_ssh_narrowed_by_tag_only_is_corrected(self):
        self.write_json(self.firewalls, [self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "sources": {"tags": ["bastion"]}}])])
        self.corrected(self.create())

    def test_ssh_split_over_two_rules_from_anywhere_is_left_alone(self):
        # How doctl's own create writes it: one tcp 22 rule for each address family.
        self.write_json(self.firewalls, [self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["0.0.0.0/0"]}},
            {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["::/0"]}}])])
        self.assertEqual(self.create().returncode, 0)
        self.assertEqual(self.doctl("compute", "firewall", "update"), [])

    def test_ssh_narrowed_that_cannot_be_corrected_buys_nothing(self):
        self.write_json(self.firewalls, [self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["192.0.2.0/24"]}}])])
        self.bought_nothing(self.create(FAKE_DOCTL_FAIL_AT="firewall-update"),
                            said="do not allow 0.0.0.0/0 or ::/0")

    def test_a_failed_status_is_corrected(self):
        self.write_json(self.firewalls, [self.wall(status="failed")])
        self.corrected(self.create())

    def test_a_status_that_stays_failed_buys_nothing(self):
        self.write_json(self.firewalls, [self.wall(status="failed")])
        self.bought_nothing(self.create(FAKE_DOCTL_FIREWALL_STATUS="failed"))

    def test_a_status_that_stays_waiting_buys_nothing(self):
        self.write_json(self.firewalls, [self.wall(tags=[])])
        self.bought_nothing(self.create(FAKE_DOCTL_FIREWALL_STATUS="waiting",
                                        FLEET_MACHINES_FIREWALL_READS="2"))

    def test_a_new_firewall_that_never_succeeds_buys_nothing(self):
        self.bought_nothing(self.create(FAKE_DOCTL_FIREWALL_STATUS="failed"))

    def test_a_wide_rule_is_corrected_before_the_create(self):
        self.write_json(self.firewalls, [self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["0.0.0.0/0"]}},
            {"protocol": "tcp", "ports": "7878", "sources": {"addresses": ["0.0.0.0/0"]}}])])
        done = self.create()
        self.corrected(done)
        updates = self.doctl("compute", "firewall", "update")
        self.assertEqual(updates[0][4], "fw-9")
        self.assertEqual(updates[0][updates[0].index("--droplet-ids") + 1], "77")
        wall = self.read_json(self.firewalls)[0]
        self.assertEqual([(r["protocol"], r.get("ports")) for r in wall["inbound_rules"]],
                         [("tcp", "22"), ("tcp", "22")])

    def test_a_firewall_that_lets_nothing_out_is_corrected(self):
        # DigitalOcean lets out nothing that no outbound rule allows: a box behind this wall
        # could not fetch a package, reach GitHub, join a tailnet or talk to a model.
        self.write_json(self.firewalls, [self.wall(outbound_rules=[])])
        self.assertTrue(machines.firewall_faults(self.wall(outbound_rules=[])))
        self.corrected(self.create())
        wall = self.read_json(self.firewalls)[0]
        allowed = {(rule["protocol"], address) for rule in wall["outbound_rules"]
                   for address in rule["destinations"]["addresses"]}
        self.assertEqual(allowed, {(protocol, address) for protocol in ("tcp", "udp", "icmp")
                                   for address in ("0.0.0.0/0", "::/0")})

    def test_a_firewall_that_lets_nothing_out_and_cannot_be_corrected_buys_nothing(self):
        self.write_json(self.firewalls, [self.wall(outbound_rules=[])])
        self.bought_nothing(self.create(FAKE_DOCTL_FAIL_AT="firewall-update"),
                            said="lets nothing out")

    def test_outbound_narrowed_is_corrected(self):
        cases = {
            "https only": [{"protocol": "tcp", "ports": "443",
                            "destinations": {"addresses": ["0.0.0.0/0", "::/0"]}},
                           *self.everything_out()[1:]],
            "no udp": [rule for rule in self.everything_out() if rule["protocol"] != "udp"],
            "ipv4 only": [{**rule, "destinations": {"addresses": ["0.0.0.0/0"]}}
                          for rule in self.everything_out()],
            "one range only": [{**rule, "destinations": {"addresses": ["192.0.2.0/24"]}}
                               for rule in self.everything_out()],
            "a tag only": [{**rule, "destinations": {"tags": ["bastion"]}}
                           for rule in self.everything_out()],
        }
        for case, outbound in cases.items():
            with self.subTest(case):
                self.assertTrue(machines.firewall_faults(self.wall(outbound_rules=outbound)))

    def test_outbound_split_by_address_family_is_left_alone(self):
        # How doctl's own create writes it: one rule for each protocol and address family.
        split = [{"protocol": protocol, "ports": ports, "destinations": {"addresses": [address]}}
                 for protocol, ports in (("tcp", "all"), ("udp", "1-65535"), ("icmp", "0"))
                 for address in ("0.0.0.0/0", "::/0")]
        self.assertEqual(machines.firewall_faults(self.wall(outbound_rules=split)), [])
        self.write_json(self.firewalls, [self.wall(outbound_rules=split)])
        self.assertEqual(self.create().returncode, 0)
        self.assertEqual(self.doctl("compute", "firewall", "update"), [])

    def test_an_outbound_deny_on_top_of_full_allows_is_corrected(self):
        # DigitalOcean puts a deny above every allow: this wall has all the right allows and
        # still keeps the farm off https, so off packages, GitHub and the model.
        deny = {"protocol": "tcp", "ports": "443", "action": "deny",
                "destinations": {"addresses": ["0.0.0.0/0", "::/0"]}}
        wall = self.wall(outbound_rules=self.everything_out() + [deny])
        faults = machines.firewall_faults(wall)
        self.assertEqual(len(faults), 1, faults)
        self.assertIn("deny rule on tcp port 443", faults[0])
        self.write_json(self.firewalls, [wall])
        self.corrected(self.create())
        after = self.read_json(self.firewalls)[0]
        self.assertFalse([rule for rule in after["outbound_rules"]
                          if rule.get("action", "allow") != "allow"])

    def test_an_outbound_deny_that_cannot_be_corrected_buys_nothing(self):
        deny = {"protocol": "tcp", "ports": "443", "action": "deny",
                "destinations": {"addresses": ["0.0.0.0/0", "::/0"]}}
        self.write_json(self.firewalls, [self.wall(outbound_rules=self.everything_out() + [deny])])
        self.bought_nothing(self.create(FAKE_DOCTL_FAIL_AT="firewall-update"),
                            said="deny rule on tcp port 443")

    def test_an_extra_inbound_rule_is_corrected(self):
        cases = {
            "another port": {"protocol": "tcp", "ports": "7878",
                             "sources": {"addresses": ["192.0.2.0/24"]}},
            "another protocol": {"protocol": "udp", "ports": "41641",
                                 "sources": {"addresses": ["0.0.0.0/0", "::/0"]}},
            "ssh from a tag too": {"protocol": "tcp", "ports": "22",
                                   "sources": {"tags": ["bastion"]}},
            "a deny": {"protocol": "icmp", "action": "deny",
                       "sources": {"addresses": ["0.0.0.0/0"]}},
        }
        for case, extra in cases.items():
            with self.subTest(case):
                inbound = self.wall()["inbound_rules"] + [extra]
                self.assertTrue(machines.firewall_faults(self.wall(inbound_rules=inbound)))
        extra = cases["another port"]
        self.write_json(self.firewalls,
                        [self.wall(inbound_rules=self.wall()["inbound_rules"] + [extra])])
        self.corrected(self.create())
        wall = self.read_json(self.firewalls)[0]
        self.assertEqual({(r["protocol"], r.get("ports")) for r in wall["inbound_rules"]},
                         {("tcp", "22")})

    def test_a_spec_equal_firewall_spelled_differently_is_left_alone(self):
        # The same firewall as the spec, as another doctl or the control panel might print it:
        # every-port spellings 0, all and 1-65535, icmp with and without ports, the address
        # families in the other order and split over rules, an explicit allow, a repeated tag.
        inbound = [{"protocol": "TCP", "ports": " 22 ", "action": "allow",
                    "sources": {"addresses": ["::/0"]}},
                   {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["0.0.0.0/0"]}}]
        outbound = [{"protocol": "udp", "ports": "1-65535",
                     "destinations": {"addresses": ["::/0", "0.0.0.0/0"]}},
                    {"protocol": "tcp", "ports": "all", "action": "ALLOW",
                     "destinations": {"addresses": ["::/0"]}},
                    {"protocol": "tcp", "ports": "0", "destinations": {"addresses": ["0.0.0.0/0"]}},
                    {"protocol": "icmp", "destinations": {"addresses": ["0.0.0.0/0"]}},
                    {"protocol": "icmp", "ports": "0", "destinations": {"addresses": ["::/0"]}}]
        wall = self.wall(inbound_rules=inbound, outbound_rules=outbound,
                         tags=["murmur-farm", "murmur-farm"], status="Succeeded")
        self.assertEqual(machines.normalize_firewall(wall), machines.firewall_expected())
        self.assertEqual(machines.firewall_faults(wall), [])
        self.write_json(self.firewalls, [wall])
        done = self.create()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.doctl("compute", "firewall", "update"), [])
        self.assertEqual(self.doctl("compute", "firewall", "create"), [])
        self.assertEqual(len(self.creates()), 1)

    def test_the_firewall_the_script_writes_is_the_spec(self):
        written = machines.firewall_argv()
        self.assertEqual(
            machines.normalize_rules(
                [{"protocol": fields["protocol"], "ports": fields.get("ports"),
                  "sources": {"addresses": [fields["address"]]}}
                 for fields in (dict(part.split(":", 1) for part in chunk.split(","))
                                for chunk in written[written.index("--inbound-rules") + 1].split())],
                "sources"),
            machines.firewall_expected()["inbound"])

    def test_the_firewall_the_script_writes_lets_everything_out(self):
        written = {"outbound_rules": [
            {"protocol": fields["protocol"], "ports": fields.get("ports", ""),
             "destinations": {"addresses": [fields["address"]]}}
            for fields in (dict(part.split(":", 1) for part in chunk.split(","))
                           for chunk in machines.OUTBOUND_RULES.split())]}
        self.assertEqual(machines.outbound_faults(written["outbound_rules"]), [])

    def test_a_firewall_without_the_tag_is_corrected(self):
        self.write_json(self.firewalls, [self.wall(tags=[])])
        self.corrected(self.create())
        self.assertEqual(self.read_json(self.firewalls)[0]["tags"], ["murmur-farm"])

    def test_a_correction_that_fails_creates_nothing(self):
        self.write_json(self.firewalls, [self.wall(tags=[])])
        self.bought_nothing(self.create(FAKE_DOCTL_FAIL_AT="firewall-update"),
                            said="refused the correction")

    def wide(self, **change):
        """Someone else's firewall that lets the dashboard port in from anywhere."""
        row = {"id": "fw-wide", "name": "existing-wide", "status": "succeeded",
               "tags": ["murmur-farm"], "droplet_ids": [],
               "inbound_rules": [{"protocol": "tcp", "ports": "7878",
                                  "sources": {"addresses": ["0.0.0.0/0", "::/0"]}}],
               "outbound_rules": self.everything_out()}
        row.update(change)
        return row

    def stopped_by(self, done, seeded):
        """The run stopped before any purchase, named the other firewall, and wrote nothing to
        any firewall: this farm never edits one it does not own, and not its own either."""
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("existing-wide (id fw-wide)", done.stderr)
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.read_json(self.droplets), [])
        self.assertEqual(self.registry()["farm"]["state"], "failed")
        self.assertEqual(self.doctl("compute", "firewall", "update"), [])
        self.assertEqual(self.doctl("compute", "firewall", "create"), [])
        self.assertEqual(self.read_json(self.firewalls), seeded)

    def test_a_lone_spec_firewall_passes(self):
        self.write_json(self.firewalls, [self.wall()])
        done = self.create()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.creates()), 1)

    def test_another_firewall_on_the_farm_tag_buys_nothing(self):
        # DigitalOcean adds up the allow rules of every firewall over a droplet: a right
        # murmur-ssh-only beside a wide one still leaves the dashboard port open.
        seeded = [self.wall(), self.wide()]
        self.write_json(self.firewalls, seeded)
        self.stopped_by(self.create(), seeded)

    def test_another_firewall_on_this_farms_own_tag_buys_nothing(self):
        machines_in(self.env, "farm_id")
        seeded = [self.wall(), self.wide(tags=[self.farm_tag()])]
        self.write_json(self.firewalls, seeded)
        self.stopped_by(self.create(), seeded)

    def test_another_firewall_on_this_farms_droplets_by_id_buys_nothing(self):
        machines_in(self.env, "farm_id")
        self.write_json(self.droplets, [{"id": 610, "name": "older", "tags": [self.farm_tag()],
                                         "networks": {"v4": []}}])
        seeded = [self.wall(), self.wide(tags=[], droplet_ids=[610])]
        self.write_json(self.firewalls, seeded)
        done = self.create()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("existing-wide (id fw-wide)", done.stderr)
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.read_json(self.firewalls), seeded)

    def test_another_firewall_is_named_even_when_ours_is_missing_or_wrong(self):
        for walls in ([], [self.wall(tags=[])]):
            with self.subTest(len(walls)):
                seeded = walls + [self.wide()]
                self.write_json(self.firewalls, seeded)
                self.stopped_by(self.create(), seeded)
                self.assertEqual(self.machines("forget", "farm").returncode, 0)

    def test_a_firewall_on_other_tags_only_is_not_ours_to_judge(self):
        self.write_json(self.firewalls, [self.wall(), self.wide(tags=["murmur", "web"],
                                                                droplet_ids=[77])])
        done = self.create()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.creates()), 1)
        created = self.creates()[0]
        self.assertNotIn("murmur", created[created.index("--tag-names") + 1].split(","))

    def test_two_firewalls_by_our_name_buy_nothing(self):
        seeded = [self.wall(), self.wall(id="fw-10")]
        self.write_json(self.firewalls, seeded)
        done = self.create()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("2 firewalls are named murmur-ssh-only", done.stderr)
        self.assertEqual(self.creates(), [])

    def test_the_firewalls_over_a_droplet(self):
        walls = [self.wall(), self.wide(), self.wide(id="a", tags=["other"]),
                 self.wide(id="b", tags=[], droplet_ids=[5]), self.wide(id="c", tags=[])]
        over = machines.firewalls_over(walls, ["murmur-farm", "murmur-by-x"], [5])
        self.assertEqual([row["id"] for row in over], ["fw-9", "fw-wide", "b"])

    def test_the_faults_are_named(self):
        self.assertEqual(machines.firewall_faults(self.wall()), [])
        faults = machines.firewall_faults(self.wall(tags=["other"], inbound_rules=[
            {"protocol": "udp", "ports": "0"}]))
        # udp in, ssh from nowhere, and the wrong tag.
        self.assertEqual(len(faults), 3, faults)
        narrowed = machines.firewall_faults(self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "sources": {"addresses": ["192.0.2.0/24"]}}]))
        self.assertEqual(len(narrowed), 1, narrowed)
        self.assertIn("do not allow 0.0.0.0/0 or ::/0", narrowed[0])
        self.assertTrue(machines.firewall_faults(self.wall(inbound_rules=[])))
        self.assertTrue(machines.firewall_faults(self.wall(status="failed")))
        self.assertTrue(machines.firewall_faults(self.wall(status="waiting")))
        self.assertTrue(machines.firewall_faults(self.wall(status="")))
        self.assertTrue(machines.firewall_faults(self.wall(inbound_rules=[
            {"protocol": "tcp", "ports": "22", "action": "deny"}])))


class CloudInit(unittest.TestCase):
    """Tailscale mode adds the package, the helper and its one sudoers line; nothing else."""

    def parsed(self, **kwargs):
        text = machines.cloud_init(PERSON_KEY, "ssh-ed25519 AAAAmachines m", **kwargs)
        try:
            import yaml
        except ImportError:
            return text, None
        return text, yaml.safe_load(text)

    def test_tunnel_mode_has_no_tailscale_and_no_sudo(self):
        text, _ = self.parsed()
        self.assertNotIn("tailscale", text)
        self.assertNotIn("sudoers", text)
        self.assertNotIn("nodejs", text)

    def test_tailscale_mode_installs_the_package_and_the_helper_and_no_key(self):
        text, parsed = self.parsed(tailscale=True)
        self.assertIn("apt-get install -y -qq gh tailscale", text)
        self.assertIn("pkgs.tailscale.com/stable/ubuntu/noble", text)
        self.assertNotIn("tskey", text)
        self.assertNotIn("auth-key file", text.replace('"file:$key"', ""))
        if parsed is None:
            self.skipTest("PyYAML is not installed; the text checks above ran")
        files = {entry["path"]: entry for entry in parsed["write_files"]}
        helper = files["/usr/local/sbin/murmur-tailscale-up"]
        self.assertEqual((helper["owner"], helper["permissions"]), ("root:root", "0755"))
        self.assertIn('tailscale up --auth-key "file:$key"', helper["content"])
        self.assertIn("umask 077", helper["content"])
        self.assertIn("/run/", helper["content"])
        sudoers = files["/etc/sudoers.d/murmur-tailscale"]
        self.assertEqual(sudoers["permissions"], "0440")
        self.assertEqual(sudoers["content"],
                         'farm ALL=(root) NOPASSWD: /usr/local/sbin/murmur-tailscale-up ""\n')

    def test_the_helper_takes_the_key_from_stdin_and_deletes_it(self):
        scratch = tempfile.mkdtemp(prefix="one-click-helper.")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        body = machines.TAILSCALE_HELPER_BODY.replace("/run/", scratch + "/")
        helper = os.path.join(scratch, "helper")
        with open(helper, "w", encoding="utf-8") as handle:
            handle.write(body)
        fake = os.path.join(scratch, "tailscale")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\necho \"$@\" > " + scratch + "/argv\n"
                         "cat \"${3#file:}\" > " + scratch + "/seen\n"
                         "stat -c %a \"${3#file:}\" > " + scratch + "/mode\n")
        os.chmod(fake, 0o755)
        done = subprocess.run(["sh", helper], input="tskey-auth-CANARY\n", text=True,
                              capture_output=True, timeout=30,
                              env=dict(os.environ, PATH=scratch + os.pathsep + "/usr/bin:/bin"))
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(scratch, "argv"), encoding="utf-8") as handle:
            argv = handle.read()
        self.assertNotIn("CANARY", argv)
        self.assertIn("--auth-key file:", argv)
        with open(os.path.join(scratch, "seen"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "tskey-auth-CANARY")
        with open(os.path.join(scratch, "mode"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "600")
        self.assertEqual([n for n in os.listdir(scratch) if n.startswith("murmur-tailscale")],
                         [])
        empty = subprocess.run(["sh", helper], input="", text=True, capture_output=True,
                               timeout=30, env=dict(os.environ, PATH=scratch + ":/usr/bin:/bin"))
        self.assertEqual(empty.returncode, 2)

    @unittest.skipUnless(shutil.which("visudo"), "visudo is not installed here")
    def test_the_sudoers_line_parses(self):
        scratch = tempfile.mkdtemp(prefix="one-click-sudoers.")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        path = os.path.join(scratch, "murmur-tailscale")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('farm ALL=(root) NOPASSWD: /usr/local/sbin/murmur-tailscale-up ""\n')
        os.chmod(path, 0o440)
        done = subprocess.run(["visudo", "-cf", path], capture_output=True, text=True,
                              timeout=30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_node_mode_adds_node_and_npm_from_the_distribution(self):
        text, parsed = self.parsed(node=True)
        self.assertIn("  - nodejs\n  - npm\n", text)
        self.assertNotIn("tailscale", text)


DASH_FAKES = os.path.join(FAKES, "dashboard")
INSTALLER_FAKES = os.path.join(FAKES, "installer")
INSTALL = os.path.join(ROOT, "farm", "install.sh")
RUN_SH = os.path.join(FLEET, "dashboard", "run.sh")
SERVER = os.path.join(FLEET, "dashboard", "server.py")
UNIT = os.path.join(FLEET, "systemd", "fleet-dashboard.service")
EXAMPLE_POLICY = os.path.join(FLEET, "config", "policy.example.toml")


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Scratch(unittest.TestCase):
    """A scratch HOME with the fleet's config and state inside it, and a fake log."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="one-click-scratch.")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.fake_log = os.path.join(self.home, "fake-calls.jsonl")
        self.config = os.path.join(self.home, "config", "fleet")
        self.fake_state = os.path.join(self.home, "fake-state")
        os.makedirs(self.fake_state)

    def calls(self, name=None):
        if not os.path.exists(self.fake_log):
            return []
        with open(self.fake_log, encoding="utf-8") as handle:
            rows = [json.loads(line)["argv"] for line in handle if line.strip()]
        return [row for row in rows if name is None or row[0] == name]

    def read(self, *parts):
        path = os.path.join(self.home, *parts)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()


# farm/install.sh stops at its first checks, before anything the cases below look at: on a box
# where systemd is not running ("no systemd here", a plain container), and when it runs as root
# ("run this as an ordinary user, not root: the agents run as you").
AS_ROOT = os.geteuid() == 0
SYSTEMD = os.path.isdir("/run/systemd/system")
if not SYSTEMD:
    STOPS_EARLY = ("systemd is not running here, and farm/install.sh stops at its systemd check, "
                   "before what this case checks; run the suite on a machine that booted "
                   "systemd to cover it")
elif AS_ROOT:
    STOPS_EARLY = ("farm/install.sh refuses to run as root and stops at step 1, before what this "
                   "case checks; run the suite as an ordinary user to cover it")
else:
    STOPS_EARLY = ""


class Installer(Scratch):
    """farm/install.sh: --yes never asks, --hq-repo, the Tailscale bind, the dashboard unit."""

    def setUp(self):
        super().setUp()
        self.env = dict(os.environ, HOME=self.home, FAKE_LOG=self.fake_log, USER="farm",
                        FLEET_CONFIG=self.config,
                        XDG_CONFIG_HOME=os.path.join(self.home, "config"),
                        PATH=os.pathsep.join([INSTALLER_FAKES, FAKES,
                                              os.environ.get("PATH", "")]))

    def on_a_terminal(self, *args, answers="", **env):
        """The installer with a terminal a person could answer on, and the answers typed ahead."""
        import pty
        leader, follower = pty.openpty()
        follower_name = os.ttyname(follower)
        os.close(follower)

        def own_terminal():
            os.setsid()
            os.close(os.open(follower_name, os.O_RDWR))

        if answers:
            os.write(leader, answers.encode())
        try:
            return subprocess.run(["bash", INSTALL] + list(args), capture_output=True,
                                  text=True, timeout=120, stdin=subprocess.DEVNULL,
                                  env=dict(self.env, **env), preexec_fn=own_terminal)
        finally:
            os.close(leader)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_yes_never_asks_even_at_a_terminal(self):
        done = self.on_a_terminal("--yes")
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        for question in ("Is this the only machine", "Head office repository",
                         "Your own code name", "The ssh alias"):
            self.assertIn(question, said)
        self.assertEqual(said.count("(default)"), 4, said)
        self.assertIn(["hq", "init", "--repo", "fakeuser/agent-hq-office", "--owner", "fakeuser"],
                      self.calls("hq"))

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_remote_yes_skips_the_single_machine_question_and_takes_the_hq_repo(self):
        done = self.on_a_terminal("--remote", "--yes", "--hq-repo", "owner/old-office")
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        self.assertNotIn("Is this the only machine", said)
        self.assertNotIn("Head office repository (owner/name", said)
        self.assertIn(["hq", "init", "--repo", "owner/old-office", "--owner", "fakeuser"],
                      self.calls("hq"))
        self.assertIn(["gh", "repo", "view", "owner/old-office"], self.calls("gh"))

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_a_malformed_hq_repo_is_refused(self):
        done = self.on_a_terminal("--remote", "--yes", "--hq-repo", "not a repo")
        self.assertEqual(done.returncode, 1)
        self.assertIn("--hq-repo is owner/name", done.stdout + done.stderr)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_tailscale_writes_the_tailscale_bind_and_never_0000(self):
        # Not a single machine, then three defaults, then yes to Tailscale.
        done = self.on_a_terminal(answers="no\n\n\n\nyes\n",
                                  PATH=os.pathsep.join([INSTALLER_FAKES, DASH_FAKES, FAKES,
                                                        os.environ.get("PATH", "")]),
                                  FAKE_STATE_DIR=self.fake_state)
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        env = self.read("config", "fleet", "env")
        self.assertIn("FLEET_DASH_BIND=tailscale\n", env)
        self.assertNotIn("0.0.0.0", env + said)

    def with_env(self, text):
        os.makedirs(self.config, exist_ok=True)
        with open(os.path.join(self.config, "env"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def choosing(self, tailscale):
        """Not a single machine, then three defaults, then yes or no to Tailscale."""
        return self.on_a_terminal(answers="no\n\n\n\n%s\n" % ("yes" if tailscale else "no"),
                                  PATH=os.pathsep.join([INSTALLER_FAKES, DASH_FAKES, FAKES,
                                                        os.environ.get("PATH", "")]),
                                  FAKE_STATE_DIR=self.fake_state)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_tailscale_replaces_an_old_wide_bind(self):
        # An older install wrote 0.0.0.0, and the unit loads this file: left alone, the page
        # would listen on every interface of a box with a public address.
        self.with_env("FLEET_HOME=/srv/fleet\nFLEET_DASH_BIND=0.0.0.0\nFLEET_DASH_TOKEN=CANARY\n")
        done = self.choosing(tailscale=True)
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        env = self.read("config", "fleet", "env")
        binds = [line for line in env.splitlines() if "FLEET_DASH_BIND" in line]
        self.assertEqual(binds, ["FLEET_DASH_BIND=tailscale"], env)
        self.assertIn("FLEET_HOME=/srv/fleet\n", env)
        self.assertIn("FLEET_DASH_TOKEN=CANARY\n", env)
        self.assertEqual(self.read("dashboard-run.txt"), "enable\n")

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_tailscale_replaces_every_other_bind_line(self):
        self.with_env("FLEET_DASH_BIND=127.0.0.1\nexport FLEET_DASH_BIND=::\n"
                      "FLEET_DASH_BIND=tailscale\n")
        done = self.choosing(tailscale=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        env = self.read("config", "fleet", "env")
        self.assertEqual([line for line in env.splitlines() if "FLEET_DASH_BIND" in line],
                         ["FLEET_DASH_BIND=tailscale"], env)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_the_tunnel_leaves_a_loopback_bind_alone(self):
        self.with_env("FLEET_DASH_BIND=127.0.0.1\n")
        done = self.choosing(tailscale=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        env = self.read("config", "fleet", "env")
        self.assertEqual([line for line in env.splitlines() if "FLEET_DASH_BIND" in line],
                         ["FLEET_DASH_BIND=127.0.0.1"], env)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_the_installer_installs_and_enables_the_dashboard_unit(self):
        done = self.on_a_terminal("--remote", "--yes")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.read("dashboard-run.txt"), "enable\n")
        self.assertIn("fleet-dashboard.service enabled", done.stdout)

    def example_policy(self):
        with open(EXAMPLE_POLICY, encoding="utf-8") as handle:
            return handle.read()

    def policy(self):
        return self.read("config", "fleet", "policy.toml")

    def installed_on(self, gigabytes):
        done = self.on_a_terminal("--remote", "--yes", FAKE_MEMORY_GB=str(gigabytes))
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        return said

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_a_4_gb_machine_gets_memory_limits_it_can_spawn_under(self):
        # The example stops every spawn below 6 GB free, which a 4 GB machine never has.
        said = self.installed_on(3.8)
        self.assertIn("memory limits sized for 3.8 GB", said)
        policy, example = self.policy(), self.example_policy()
        limits = tomllib.loads(policy)["limits"]
        self.assertEqual((limits["ram_min_gb"], limits["warn_ram_gb"]), (1, 2), said)
        # Only those two numbers change; every other line, comment and limit stays the example's.
        changed = [(old, new) for old, new in zip(example.splitlines(), policy.splitlines())
                   if old != new]
        self.assertEqual(len(policy.splitlines()), len(example.splitlines()))
        self.assertEqual([new.split("#")[0].split() for _old, new in changed],
                         [["ram_min_gb", "=", "1"], ["warn_ram_gb", "=", "2"]], changed)
        self.assertNotIn("max_agents", policy + said)
        # The next run finds limits that are no longer the example's and leaves them alone.
        again = self.installed_on(7.8)
        self.assertNotIn("memory limits sized", again)
        self.assertEqual(self.policy(), policy)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_an_8_gb_machine_does_not_warn_while_it_is_idle(self):
        said = self.installed_on(7.8)
        limits = tomllib.loads(self.policy())["limits"]
        self.assertEqual((limits["ram_min_gb"], limits["warn_ram_gb"]), (2, 3), said)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_limits_a_person_set_are_left_alone(self):
        mine = self.example_policy().replace("gpu_temp_max = 87", "gpu_temp_max = 80")
        self.assertNotEqual(mine, self.example_policy())
        os.makedirs(self.config, exist_ok=True)
        with open(os.path.join(self.config, "policy.toml"), "w", encoding="utf-8") as handle:
            handle.write(mine)
        said = self.installed_on(3.8)
        self.assertNotIn("memory limits sized", said)
        self.assertEqual(self.policy(), mine)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_the_logs_are_in_this_users_own_folder(self):
        # A fixed name in /tmp belongs to whoever ran the installer first, and a second user on
        # the same machine could not write it.
        cache = os.path.join(self.home, "cache")
        done = self.on_a_terminal("--remote", "--yes", XDG_CACHE_HOME=cache)
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, said)
        log = os.path.join(cache, "murmur", "fleet-install.log")
        self.assertIn(f"lines of install report in {log}", said)
        self.assertTrue(os.path.exists(os.path.join(cache, "murmur", "dashboard.log")), said)
        self.assertNotIn("/tmp/murmur", said)

    @unittest.skipIf(STOPS_EARLY, STOPS_EARLY)
    def test_a_16_gb_machine_keeps_the_example_limits(self):
        said = self.installed_on(15.6)
        self.assertNotIn("memory limits sized", said)
        self.assertEqual(self.policy(), self.example_policy())


class InstallerHelp(unittest.TestCase):
    """`--help` prints the comment at the top of farm/install.sh, word for word, also when the
    script arrives on stdin (`curl ... | bash -s -- --help`), where there is no file to read."""

    def header(self):
        with open(INSTALL, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        end = lines.index("set -euo pipefail")
        return "".join(re.sub(r"^# ?", "", line) + "\n" for line in lines[1:end])

    def test_help_through_a_pipe_prints_the_header_comment(self):
        with open(INSTALL, "rb") as script:
            done = subprocess.run(["bash", "-s", "--", "--help"], stdin=script,
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, self.header())

    def test_help_from_the_file_prints_the_same_words(self):
        done = subprocess.run(["bash", INSTALL, "--help"], capture_output=True, text=True,
                              timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, self.header())


class InstallerWithoutSystemd(Scratch):
    """A box where systemd is not running, such as a plain container, is told so first, as root
    or as anyone else, and is left as it was. A `systemctl` command alone used to let the
    installer through: it edited ~/.bashrc, made ~/.local/bin and fetched uv before it failed."""

    @unittest.skipIf(SYSTEMD, "systemd is running here; this case needs a box without it, such "
                     "as a plain container")
    def test_it_stops_before_writing_anything(self):
        # The installer fakes come first, a `systemctl` among them, so the command is there and
        # a run that got past the check would still install nothing.
        env = dict(os.environ, HOME=self.home, FAKE_LOG=self.fake_log, USER="farm",
                   FLEET_CONFIG=self.config,
                   XDG_CACHE_HOME=os.path.join(self.home, "cache"),
                   XDG_CONFIG_HOME=os.path.join(self.home, "config"),
                   PATH=os.pathsep.join([INSTALLER_FAKES, FAKES, os.environ.get("PATH", "")]))
        before = sorted(os.listdir(self.home))
        done = subprocess.run(["bash", INSTALL, "--yes"], capture_output=True, text=True,
                              timeout=120, stdin=subprocess.DEVNULL, env=env)
        said = done.stdout + done.stderr
        self.assertEqual(done.returncode, 1, said)
        self.assertTrue(done.stderr.startswith("\nstop: no systemd here"), said)
        self.assertNotIn("1/5", said)
        # No ~/.bashrc, no ~/.local/bin, no log folder, no config: nothing new at all.
        self.assertEqual(sorted(os.listdir(self.home)), before)
        self.assertEqual(self.calls(), [], "no tool was run before the check")


FLEET_INSTALL = os.path.join(FLEET, "install.sh")
SKILL = os.path.join(os.path.realpath(FLEET), "skills", "fleet")   # install.sh resolves its own path


class FleetInstallSkills(Scratch):
    """fleet/install.sh links the orchestrator skill where Claude Code and Codex read skills:
    ~/.claude/skills, and ~/.agents/skills once Codex is on the box (step 5 of the logins reruns
    it for that). ~/.codex/skills, where earlier installs put it, is no longer read."""

    def install(self, *args):
        env = dict(os.environ, HOME=self.home, FLEET_CONFIG=self.config)
        done = subprocess.run(["bash", FLEET_INSTALL, "--no-autosweep"] + list(args),
                              capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL, env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout

    def link(self, *parts):
        path = os.path.join(self.home, *parts)
        return os.readlink(path) if os.path.islink(path) else None

    def test_codex_on_the_box_gets_the_skill_in_agents_skills(self):
        os.makedirs(os.path.join(self.home, ".codex"))
        said = self.install()
        self.assertEqual(self.link(".claude", "skills", "fleet"), SKILL)
        self.assertEqual(self.link(".agents", "skills", "fleet"), SKILL)
        self.assertIn("~/.agents/skills/fleet", said)
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".codex", "skills", "fleet")))

    def test_the_old_codex_link_into_this_clone_is_removed_and_no_other(self):
        old = os.path.join(self.home, ".codex", "skills")
        os.makedirs(old)
        os.symlink(SKILL, os.path.join(old, "fleet"))
        self.install()
        self.assertIsNone(self.link(".codex", "skills", "fleet"))
        self.assertEqual(self.link(".agents", "skills", "fleet"), SKILL)
        # A link someone else made there is theirs.
        elsewhere = os.path.join(self.home, "another-skill")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(old, "fleet"))
        self.install()
        self.assertEqual(self.link(".codex", "skills", "fleet"), elsewhere)

    @unittest.skipIf(shutil.which("codex"), "codex is on this PATH, so the case has no box "
                     "without Codex to look at")
    def test_no_codex_means_no_agents_folder(self):
        self.install()
        self.assertEqual(self.link(".claude", "skills", "fleet"), SKILL)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".agents")))

    def test_no_skills_links_nothing(self):
        os.makedirs(os.path.join(self.home, ".codex"))
        self.install("--no-skills")
        self.assertIsNone(self.link(".claude", "skills", "fleet"))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".agents")))


class DashboardUnit(Scratch):
    """fleet-dashboard.service: never gives up, and `fleet dashboard start` starts it."""

    def settings(self):
        import configparser
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.optionxform = str
        with open(UNIT, encoding="utf-8") as handle:
            parser.read_string(handle.read())
        return parser

    def test_the_restart_settings_retry_forever_every_five_seconds(self):
        unit = self.settings()
        self.assertEqual(unit["Service"]["Restart"], "always")
        self.assertEqual(unit["Service"]["RestartSec"], "5")
        self.assertEqual(unit["Unit"]["StartLimitIntervalSec"], "0")
        self.assertEqual(unit["Service"]["EnvironmentFile"], "-%h/.config/fleet/env")
        self.assertEqual(unit["Install"]["WantedBy"], "default.target")

    def substituted(self):
        with open(UNIT, encoding="utf-8") as handle:
            text = handle.read()
        text = text.replace("__FLEET__", FLEET).replace("__PY__", sys.executable)
        path = os.path.join(self.home, "fleet-dashboard.service")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not installed")
    def test_systemd_analyze_verifies_the_unit(self):
        done = subprocess.run(["systemd-analyze", "--user", "verify", self.substituted()],
                              capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, SYSTEMD_LOG_LEVEL="warning"))
        complaints = [line for line in (done.stdout + done.stderr).splitlines()
                      if "fleet-dashboard" in line]
        if done.returncode != 0 and not complaints:
            self.skipTest("no user manager to verify against here: " + done.stderr.strip())
        self.assertEqual(complaints, [])
        self.assertEqual(done.returncode, 0, done.stderr)

    def run_sh(self, *args, port):
        env = dict(os.environ, HOME=self.home, FAKE_LOG=self.fake_log,
                   FLEET_CONFIG=self.config, XDG_CONFIG_HOME=os.path.join(self.home, "config"),
                   FAKE_STATE_DIR=self.fake_state, FAKE_DASH_PORT=str(port),
                   FLEET_DASH_PORT=str(port), FLEET_DASH_SESSION="one-click-test-dashboard",
                   PATH=DASH_FAKES + os.pathsep + os.environ.get("PATH", ""))
        return subprocess.run(["bash", RUN_SH] + list(args), capture_output=True, text=True,
                              timeout=60, env=env, stdin=subprocess.DEVNULL)

    def test_enable_installs_the_unit_and_start_starts_it(self):
        port = free_port()
        done = self.run_sh("enable", port=port)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        unit = self.read("config", "systemd", "user", "fleet-dashboard.service")
        self.assertIn(f"ExecStart={shutil.which('python3')} {FLEET}/dashboard/server.py", unit)
        self.assertNotIn("__FLEET__", unit)
        user = [argv[1:] for argv in self.calls("systemctl")]
        self.assertIn(["--user", "daemon-reload"], user)
        self.assertIn(["--user", "enable", "--now", "fleet-dashboard.service"], user)
        self.assertIn(f"127.0.0.1:{port}", done.stdout)
        # Stopped, then `start` goes to the unit and never to a tmux session.
        self.assertEqual(self.run_sh("stop", port=port).returncode, 0)
        done = self.run_sh("start", port=port)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("(fleet-dashboard.service)", done.stdout)
        self.assertIn(["--user", "start", "fleet-dashboard.service"],
                      [argv[1:] for argv in self.calls("systemctl")])
        self.assertEqual([argv for argv in self.calls("tmux") if "new-session" in argv], [])
        self.assertIn("active", self.run_sh("status", port=port).stdout)

    def test_without_the_unit_start_keeps_using_tmux(self):
        done = self.run_sh("start", port=free_port())
        self.assertTrue([argv for argv in self.calls("tmux") if "new-session" in argv])
        self.assertNotIn(["--user", "start", "fleet-dashboard.service"],
                         [argv[1:] for argv in self.calls("systemctl")], done.stdout)


class DashboardBind(Scratch):
    """FLEET_DASH_BIND=tailscale: the Tailscale address or no start at all, never 0.0.0.0."""

    def serve(self, answers, port, **env):
        """Start the server with a fake tailscale; (process, its stderr path)."""
        err = os.path.join(self.home, f"server-{len(os.listdir(self.home))}.err")
        full = dict(os.environ, HOME=self.home, FAKE_LOG=self.fake_log,
                    FLEET_CONFIG=self.config, FLEET_STATE=os.path.join(self.home, "state"),
                    FAKE_STATE_DIR=self.fake_state, FAKE_TAILSCALE_ANSWERS=answers,
                    FLEET_DASH_BIND="tailscale", FLEET_DASH_PORT=str(port),
                    FLEET_DASH_TOKEN="test-token-not-a-secret",
                    PATH=DASH_FAKES + os.pathsep + os.environ.get("PATH", ""))
        full.update(env)
        handle = open(err, "w", encoding="utf-8")
        self.addCleanup(handle.close)
        process = subprocess.Popen([sys.executable, SERVER], stdout=subprocess.DEVNULL,
                                   stderr=handle, stdin=subprocess.DEVNULL, env=full,
                                   cwd=os.path.dirname(SERVER))
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process, err

    def answers_on(self, address, port, seconds=20):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://{address}:{port}/api/version",
                                            timeout=2) as reply:
                    return reply.status
            except OSError:
                time.sleep(0.3)
        return None

    def test_no_address_refuses_to_start_and_the_retry_starts(self):
        port = free_port()
        first, err = self.serve("|127.0.0.1", port)
        self.assertEqual(first.wait(timeout=60), 1)
        said = self.read(os.path.basename(err))
        self.assertIn("Tailscale has no IPv4 address", said)
        # What systemd does five seconds later, with the address now there.
        second, _err = self.serve("|127.0.0.1", port)
        self.assertEqual(self.answers_on("127.0.0.1", port), 200)
        second.kill()
        second.wait(timeout=30)

    def test_an_unspecified_answer_is_never_bound(self):
        port = free_port()
        process, err = self.serve("0.0.0.0", port)
        self.assertEqual(process.wait(timeout=60), 1)
        self.assertIn("no IPv4 address", self.read(os.path.basename(err)))

    def test_the_resolver(self):
        sys.path.insert(0, os.path.join(FLEET, "dashboard"))
        scratch_env = {"HOME": self.home, "FLEET_STATE": os.path.join(self.home, "state"),
                       "FLEET_CONFIG": self.config}
        code = ("import json, sys; sys.path.insert(0, %r); import server; "
                "print(json.dumps([server.resolve_bind(v) for v in sys.argv[1:]]))"
                % os.path.join(FLEET, "dashboard"))
        done = subprocess.run([sys.executable, "-c", code, "127.0.0.1", "tailscale", "::1"],
                              capture_output=True, text=True, timeout=120,
                              env=dict(os.environ, FAKE_LOG=self.fake_log,
                                       FAKE_STATE_DIR=self.fake_state,
                                       FAKE_TAILSCALE_ANSWERS="100.64.1.2",
                                       PATH=DASH_FAKES + os.pathsep + os.environ["PATH"],
                                       **scratch_env))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [["127.0.0.1", ""], ["100.64.1.2", ""],
                                                   ["::1", ""]])


class FailureLog(Scratch):
    """A GET that raises leaves its path in the log and never its query string."""

    def test_a_canary_in_the_query_never_reaches_the_log(self):
        code = r"""
import io, json, sys, threading, urllib.request, urllib.error
sys.path.insert(0, sys.argv[1])
import server
def boom(path):
    raise ValueError("could not read CANARY-query-token here")
server.GH.get_route = boom
captured = io.StringIO()
sys.stderr = captured
httpd = server.Server(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = "http://127.0.0.1:%d/api/github/x?token=CANARY-query-token&y=2" % httpd.server_address[1]
try:
    urllib.request.urlopen(url, timeout=10)
except urllib.error.HTTPError as error:
    status = error.code
httpd.shutdown()
sys.stdout.write(json.dumps({"status": status, "log": captured.getvalue()}))
"""
        done = subprocess.run([sys.executable, "-c", code, os.path.join(FLEET, "dashboard")],
                              capture_output=True, text=True, timeout=120,
                              env=dict(os.environ, HOME=self.home, FLEET_CONFIG=self.config,
                                       FLEET_STATE=os.path.join(self.home, "state")))
        self.assertEqual(done.returncode, 0, done.stderr)
        seen = json.loads(done.stdout)
        self.assertEqual(seen["status"], 500)
        self.assertIn("GET /api/github/x failed", seen["log"])
        self.assertNotIn("CANARY", seen["log"])
        self.assertNotIn("token=", seen["log"])


class AccountsJson(Scratch):
    """`fleet accounts list --json`: one row per account, logged in or not, and its email."""

    def test_rows_name_login_and_email(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        with open(os.path.join(self.home, ".claude", ".credentials.json"), "w") as handle:
            handle.write("{}")
        with open(os.path.join(self.home, ".claude.json"), "w") as handle:
            json.dump({"oauthAccount": {"emailAddress": "one@example.com"}}, handle)
        os.makedirs(os.path.join(self.home, ".fleet", "claude-accounts", "second"))
        done = subprocess.run([sys.executable, os.path.join(FLEET, "lib", "claude_accounts.py"),
                               "list", "--json"], capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, HOME=self.home))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [
            {"name": "default", "logged_in": True, "email": "one@example.com"},
            {"name": "second", "logged_in": False, "email": ""}])


def machines_in(env, function, *args):
    """Call one machines.py function in a child process with a test's environment, since the
    module reads its paths from the environment when it is imported."""
    code = ("import json, sys; sys.path.insert(0, %r); import machines; "
            "print(json.dumps(getattr(machines, %r)(*json.loads(sys.argv[1]))))"
            % (os.path.join(FLEET, "lib"), function))
    done = subprocess.run([sys.executable, "-c", code, json.dumps(list(args))],
                          capture_output=True, text=True, timeout=120, env=env,
                          stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

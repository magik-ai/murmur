#!/usr/bin/env python3
"""The places a farm can run, one dict each.

Every preset is a machine: a whole farm, with systemd user services, tmux, worktrees, the
dashboard and the installer as it is. murmur ships two: a Linux box you already reach over SSH,
and a DigitalOcean Droplet. CONTRIBUTING.md says how to add a machine preset.

Fields, all present on every preset so a reader never has to guess:

  id        the preset's own name, and the provider name on every command line
  label     the human name, as the vendor writes it
  color     the provider's glyph colour on the hosting tables
  job       machine, the one job a preset has
  cli       the binary this farm calls
  install   the one command that puts that binary on the farm's PATH
  login     the command a person runs in their own terminal; never the page, never a chat
  whoami    the read-only check, as an argv list. `{target}` in it means the check needs an
            address and is not an account-wide login check (the `ssh` preset)
  docs      where the vendor documents the CLI
  terms     one sentence: what you are agreeing to, and what this farm has NOT verified
  stage     ga | preview | early access
  pricing   one sentence a person can read before they spend
  sizes     [{slug, label, vcpu, ram_gb, disk_gb, monthly_usd or hourly_usd, default}], may be
            empty; `default` is true on exactly one entry, the size a person gets unasked
  regions   the regions this farm offers, first is the default, may be empty
  engines   the fleet engines this hosting can run

Accuracy. Every command, flag and number below was read from the vendors' own pages on
2026-09-23. Where a page could not confirm something, the preset leaves it out rather than
inventing a flag. Prices move: the droplet numbers are labelled "list
price on 2026-09-23" and `fleet machines plan` prefers the live price from the provider.
"""
import copy
import re

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

# The date the vendors' pricing pages were read. Every number below is from that day, and every
# place that shows a price to a person shows this with it.
PRICED_ON = "2026-09-23"
LIST_PRICE_NOTE = f"list price on {PRICED_ON}"

# doctl keeps its logins in named contexts, and the login this farm hands a person to run is
# `doctl auth init --context murmur`. So every doctl call this farm makes names that context,
# and a farm that keeps its DigitalOcean login somewhere else says so once, here, by setting
# FLEET_DOCTL_CONTEXT (an empty value means doctl's own default context).
DOCTL_CONTEXT = "murmur"

# The droplet sizes this farm offers (Basic, Regular Intel).
DEFAULT_SIZE = "s-4vcpu-8gb"
DROPLET_SIZES = [
    {"slug": "s-2vcpu-4gb", "label": "2 vCPU, 4 GB, 80 GB disk",
     "vcpu": 2, "ram_gb": 4, "disk_gb": 80, "monthly_usd": 24, "default": False},
    {"slug": "s-4vcpu-8gb", "label": "4 vCPU, 8 GB, 160 GB disk",
     "vcpu": 4, "ram_gb": 8, "disk_gb": 160, "monthly_usd": 48, "default": True},
    {"slug": "s-8vcpu-16gb", "label": "8 vCPU, 16 GB, 320 GB disk",
     "vcpu": 8, "ram_gb": 16, "disk_gb": 320, "monthly_usd": 96, "default": False},
]

# fra1 first because it is the default this farm offers; the rest are the regions a person is
# most likely to want. DigitalOcean has more, and a slug this list does not carry is refused
# rather than passed on unchecked.
DROPLET_REGIONS = ["fra1", "ams3", "lon1", "nyc3", "sfo3", "sgp1", "tor1", "blr1", "syd1"]

PRESETS = [
    {
        "id": "ssh",
        "label": "Your own machine",
        "summary": "A Linux box you already reach over SSH. Nothing new to pay for.",
        "color": "#7A8699",
        "job": "machine",
        "cli": "ssh",
        "install": "ssh comes with every Linux and macOS; nothing to install",
        "login": "none: your own SSH key reaches the machine",
        # A target, not an account: there is nothing to log in to, so this check belongs to one
        # machine and is run by `fleet machines check`, not by `fleet hosts list`.
        "whoami": ["ssh", "-o", "BatchMode=yes", "{target}", "true"],
        "docs": "https://man.openbsd.org/ssh",
        "terms": "your own machine and your own agreement with whoever rents it to you",
        "stage": "ga",
        "pricing": "whatever you already pay for the box; this farm bills nothing",
        "sizes": [],
        "regions": [],
        "engines": ["claude", "codex"],
    },
    {
        "id": "do-droplet",
        "label": "DigitalOcean Droplet",
        "summary": "A cloud server that runs the whole farm, billed by the second until you destroy it.",
        "color": "#0069FF",
        "job": "machine",
        "cli": "doctl",
        # DigitalOcean's install page gives a different command for each system, so the install
        # line sends a person to that page. The terms sentence names the three it gives.
        "install": "see https://docs.digitalocean.com/reference/doctl/how-to/install/",
        "login": "doctl auth init --context murmur",
        "whoami": ["doctl", "account", "get", "-o", "json", "--context", DOCTL_CONTEXT],
        "docs": "https://docs.digitalocean.com/reference/doctl/",
        "terms": ("a real Ubuntu VM where this farm's installer runs unchanged. DigitalOcean "
                  "documents three ways to install doctl: `brew install doctl` on macOS, "
                  "`sudo snap install doctl` on Ubuntu, or the release archive from GitHub"),
        "stage": "ga",
        "pricing": ("billed per second up to the monthly cap; a powered-off droplet is still "
                    f"billed, only Destroy stops it ({LIST_PRICE_NOTE})"),
        "sizes": DROPLET_SIZES,
        "regions": DROPLET_REGIONS,
        "engines": ["claude", "codex"],
    },
]


def presets():
    """The list, copied, so a caller that annotates a row cannot edit the shipped description."""
    return copy.deepcopy(PRESETS)


def preset(preset_id):
    """One preset by id, copied, or None. A caller that got None says so; it never guesses."""
    for row in PRESETS:
        if row["id"] == preset_id:
            return copy.deepcopy(row)
    return None


def size(preset_id, slug):
    """One size of one preset, copied, or None when that provider does not offer it."""
    row = preset(preset_id)
    if not row:
        return None
    for entry in row["sizes"]:
        if entry["slug"] == slug:
            return entry
    return None

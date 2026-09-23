#!/usr/bin/env python3
"""The hostings a farm can reach, one dict each.

Two jobs, and a page that drew them as one would lie (design record
`fleet/docs/design/hosting.md`, section 1):

  machine   a whole farm: systemd user services, tmux, worktrees, the dashboard, the installer
            as it is. A DigitalOcean Droplet, or any Linux box you already reach over SSH.
  runner    one lane at a time in a remote sandbox, started and watched by a farm.

Fields, all present on every preset so a reader never has to guess:

  id        the preset's own name, and the provider name on every command line
  label     the human name, as the vendor writes it
  color     the provider's glyph colour on the hosting tables
  job       machine | runner
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
  secrets   the env names a runner needs on the remote side
  engines   the fleet engines this hosting can run
  output    runners only: stream-json or text, which picks the parser in a lane's run.sh

Accuracy. Every command, flag and number below comes from the research pass of 2026-09-23
(`internal/research/report-hosting.md` and `internal/research/report-hosting-cli.md`). Where
that pass could not confirm something from a vendor's own page, the preset says UNVERIFIED in
its `terms` rather than inventing a flag. Prices move: the droplet numbers are labelled "list
price on 2026-09-23" and `fleet machines plan` prefers the live price from the provider.
"""
import copy
import re

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

# The date the research pass read the vendors' pricing pages. Every number below is from that
# day, and every place that shows a price to a person shows this with it.
PRICED_ON = "2026-09-23"
LIST_PRICE_NOTE = f"list price on {PRICED_ON}"

# Both runner secrets, in the order a person stores them. The subscription token is what makes a
# remote agent run on a person's Claude plan instead of an API key; the GitHub token is
# read-only on purpose, so the farm's claims guard stays the only road to a branch.
RUNNER_SECRETS = ["CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN"]

# doctl keeps its logins in named contexts, and the login this farm hands a person to run is
# `doctl auth init --context murmur`. So every doctl call this farm makes names that context,
# and a farm that keeps its DigitalOcean login somewhere else says so once, here, by setting
# FLEET_DOCTL_CONTEXT (an empty value means doctl's own default context).
DOCTL_CONTEXT = "murmur"

# The droplet sizes this farm offers, exactly the research table (Basic, Regular Intel).
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
        "secrets": [],
        "engines": ["claude", "codex"],
    },
    {
        "id": "do-droplet",
        "label": "DigitalOcean Droplet",
        "color": "#0069FF",
        "job": "machine",
        "cli": "doctl",
        # The research pass read doctl's command reference, not its packaging page, so the
        # install line sends a person to the vendor rather than naming a package that may be
        # wrong on their system. The terms sentence says so.
        "install": "see https://docs.digitalocean.com/reference/doctl/how-to/install/",
        "login": "doctl auth init --context murmur",
        "whoami": ["doctl", "account", "get", "-o", "json", "--context", DOCTL_CONTEXT],
        "docs": "https://docs.digitalocean.com/reference/doctl/",
        "terms": ("a real Ubuntu VM where this farm's installer runs unchanged; the exact "
                  "package name for doctl on your system is UNVERIFIED, so the install line "
                  "sends you to DigitalOcean's own page"),
        "stage": "ga",
        "pricing": ("billed per second up to the monthly cap; a powered-off droplet is still "
                    f"billed, only Destroy stops it ({LIST_PRICE_NOTE})"),
        "sizes": DROPLET_SIZES,
        "regions": DROPLET_REGIONS,
        "secrets": [],
        "engines": ["claude", "codex"],
    },
    {
        "id": "do-agents",
        "label": "DigitalOcean Managed Agents",
        "color": "#0069FF",
        "job": "runner",
        "cli": "doctl",
        "install": "see https://docs.digitalocean.com/reference/doctl/how-to/install/",
        "login": "doctl auth init --context murmur",
        "whoami": ["doctl", "harness-runtime", "list", "-o", "json",
                   "--context", DOCTL_CONTEXT],
        "docs": "https://docs.digitalocean.com/products/managed-agents/",
        "terms": ("public preview, one Firecracker microVM per session, region RIC1 only; the "
                  "harness-runtime commands merged into doctl on 2026-09-22 and may be missing "
                  "from a released build; whether the claude-code adapter accepts "
                  "CLAUDE_CODE_OAUTH_TOKEN instead of an API key is UNVERIFIED, so a session "
                  "may fall back to DigitalOcean's own inference, billed by DigitalOcean"),
        "stage": "preview",
        "pricing": ("about $0.25 an hour for 4 vCPU and 8 GB at full allocation, plus inference; "
                    "a prepaid balance is required and sessions pause at zero, and after 15 idle "
                    f"minutes ({LIST_PRICE_NOTE})"),
        "sizes": [
            # The default is the size the pricing sentence quotes.
            {"slug": "mars-2vcpu-4gb", "label": "2 vCPU, 4 GB",
             "vcpu": 2, "ram_gb": 4, "disk_gb": 0, "hourly_usd": 0.126, "default": False},
            {"slug": "mars-4vcpu-8gb", "label": "4 vCPU, 8 GB",
             "vcpu": 4, "ram_gb": 8, "disk_gb": 0, "hourly_usd": 0.252, "default": True},
            {"slug": "mars-16vcpu-32gb", "label": "16 vCPU, 32 GB",
             "vcpu": 16, "ram_gb": 32, "disk_gb": 0, "hourly_usd": 1.008, "default": False},
        ],
        "regions": ["ric1"],
        "secrets": list(RUNNER_SECRETS),
        "engines": ["claude"],
        # `prompt` streams the adapter's own text, and no documented stream-json comes out of it,
        # so a lane on this provider reads its output with parse_generic.py.
        "output": "text",
    },
    {
        "id": "railway",
        "label": "Railway sandboxes",
        "color": "#8A63D2",
        "job": "runner",
        "cli": "railway",
        "install": "npm i -g @railway/cli",
        "login": "railway login --browserless",
        "whoami": ["railway", "whoami", "--json"],
        "docs": "https://docs.railway.com/cli/sandbox",
        "terms": ("the only provider whose live exec stream and stdin forwarding are both "
                  "documented, which is why it is this farm's reference runner; sandboxes stop "
                  "themselves after 30 idle minutes by default, and that backstop is kept; "
                  "which token a sandbox needs, RAILWAY_API_TOKEN or RAILWAY_TOKEN, is "
                  "UNVERIFIED, so log in with the CLI"),
        "stage": "early access",
        "pricing": ("$50 per vCPU-month and $50 per GB-month while a sandbox runs, on a $5 Hobby "
                    f"or $20 Pro plan ({LIST_PRICE_NOTE})"),
        # The size is chosen when a sandbox is created and capped by the plan (8 vCPU and 8 GB on
        # Hobby, 32 and 32 on Pro). Railway documents no size slugs, so this farm invents none.
        "sizes": [],
        "regions": [],
        "secrets": list(RUNNER_SECRETS),
        "engines": ["claude"],
        "output": "stream-json",
    },
    {
        "id": "vercel",
        "label": "Vercel Sandbox",
        "color": "#000000",
        "job": "runner",
        "cli": "sandbox",
        "install": "npm i -g sandbox",
        "login": "sandbox login",
        # There is no `sandbox whoami`. A `list` that answers is the documented cheapest proof
        # that the CLI has credentials; as an auth check it is UNVERIFIED.
        "whoami": ["sandbox", "list"],
        "docs": "https://vercel.com/docs/sandbox/cli-reference",
        "terms": ("one Firecracker microVM per sandbox, 2 GB of memory per vCPU, a session up to "
                  "45 minutes on Hobby and 24 hours on Pro, and processes do not survive a stop; "
                  "the docs install it as `npm i sandbox`, this farm adds -g so the binary is on "
                  "PATH; live streaming from a non-interactive exec is UNVERIFIED"),
        "stage": "ga",
        "pricing": ("about $0.128 an hour of active CPU plus $0.0212 per GB-hour, and $0.15 a GB "
                    f"sent out ({LIST_PRICE_NOTE})"),
        "sizes": [],
        # 19 regions exist and iad1 is the default; the research pass named only that one, so it
        # is the only one this farm offers by name.
        "regions": ["iad1"],
        "secrets": list(RUNNER_SECRETS),
        "engines": ["claude"],
        "output": "stream-json",
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

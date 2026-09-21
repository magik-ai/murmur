"""The GitHub side of the office: issues, read and written through `gh`.

Every call goes through `gh()`, which has one job beyond running the command:
a failure here is one line, never a stack trace. `gh` fails for ordinary
reasons - an expired token, a head office repo that does not exist yet or that
this login cannot see, GitHub being down, `gh` not installed at all - and each
of those used to surface as a `CalledProcessError` traceback ending in the full
argv. That tells an agent nothing about what to do next, and it buries the one
sentence `gh` itself printed about the cause.
"""

import json
import subprocess
import sys

from .config import require_repo
from .util import run

# How long a single `gh` call may take before hq decides GitHub is not answering.
GH_TIMEOUT = 30


def gh(args, check=True, timeout=GH_TIMEOUT):
    """Run `gh`, and turn any failure into one line naming the cause."""
    try:
        result = run(["gh", *args], check=False, timeout=timeout)
    except FileNotFoundError:
        sys.exit("hq: `gh` is not installed or not on PATH - hq needs python, git "
                 "and gh; see https://cli.github.com")
    except subprocess.TimeoutExpired:
        sys.exit(f"hq: `gh {' '.join(args[:2])}` did not answer within {timeout}s - "
                 "GitHub may be down; try again")
    if check and result.returncode != 0:
        detail = " ".join((result.stderr or "").split())[:200]
        sys.exit(f"hq: `gh {' '.join(args[:2])}` failed "
                 f"({detail or f'exit {result.returncode}'}) - check `gh auth status` "
                 "and that the head office repo exists and is visible to this login")
    return result


def gh_json(args):
    out = gh(args).stdout
    if not out.strip():
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError as error:
        sys.exit(f"hq: could not read the answer from `gh {' '.join(args[:2])}` "
                 f"({error}) - try the same command with `gh` directly")


def find_issue(title):
    # Plain list + exact match, NOT --search: the search index lags behind a
    # just-created issue, which made a fresh mailbox invisible to its reader.
    # The office keeps every mailbox and session issue open (450+ on 2026-09-14): a
    # 200-item page silently hid whichever mailbox fell off it, and the caller read
    # "inbox empty". List enough to see them all.
    items = gh_json(["issue", "list", "--repo", require_repo(), "--state", "open",
                     "--limit", "1000", "--json", "number,title"])
    for item in items:
        if item["title"] == title:
            return item["number"]
    return None


def ensure_issue(title, label, body):
    number = find_issue(title)
    if number:
        return number
    repo = require_repo()
    gh(["label", "create", label, "--repo", repo, "--force"], check=False)
    out = gh(["issue", "create", "--repo", repo, "--title", title,
              "--label", label, "--body", body]).stdout.strip()
    try:
        return int(out.rsplit("/", 1)[-1])
    except ValueError:
        sys.exit(f"hq: `gh issue create` did not print an issue url ({out!r}) - the "
                 f"issue may or may not exist; check {repo} before retrying")

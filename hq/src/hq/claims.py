"""Branch claims: files on the `claims` branch, git push as compare-and-swap.

No API, no lock server. Two agents claiming the same branch at once cannot both
win: the second push is rejected as non-fast-forward, and the retry that
follows reads the claim that landed first and stops.
"""

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta

from .config import load_config, require_repo
from .identity import identity_source, is_sovereign, require_identity
from .util import NET_TIMEOUT, detect_repo, iso, now, parse_repo, run, slug

# How long the claims push may take before hq decides the office is not answering.
# The one call whose failure is ambiguous: a push that never answered may still
# have landed, so hq says so rather than guessing.
PUSH_TIMEOUT = 30


def default_branch(cfg):
    """The head office's default branch, as the remote reports it, or "".

    Asked, never assumed: a head office may use `main`, `master` or any other
    name.
    """
    result = run(["git", "ls-remote", "--symref", cfg.clone_url(), "HEAD"],
                 check=False, timeout=NET_TIMEOUT)
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if parts[:1] == ["ref:"] and len(parts) >= 2 and parts[1].startswith("refs/heads/"):
            return parts[1][len("refs/heads/"):]
    return ""


def ensure_cache(cfg=None):
    """The head office clone hq keeps under its state dir, made on first need.

    Only the commands that read the office pay for the clone. `hq install`
    never touches it, and the head office repo holds claims and mailboxes, not
    a copy of hq.
    """
    cfg = cfg or load_config()
    require_repo(cfg)
    cfg.state.mkdir(parents=True, exist_ok=True)
    if not (cfg.cache / ".git").exists():
        branch = default_branch(cfg)
        command = ["git", "clone", "--quiet"]
        if branch:
            command += ["--branch", branch]
        result = run(command + [cfg.clone_url(), str(cfg.cache)], check=False, timeout=60)
        if result.returncode != 0:
            detail = " ".join((result.stderr or "").split())[:200]
            raise RuntimeError(f"cannot clone {cfg.repo} into {cfg.cache}: {detail}")
    # The claims branch is created lazily on the first claim.
    return cfg.cache


def fetch_claims(strict, cfg=None):
    """Sync the cache's claims branch. strict=True raises on network failure;
    strict=False (the push gate) returns False so the caller can fail open.
    A claims branch that does not exist YET is success (empty tree), not an
    error - it is born lazily on the first claim."""
    cfg = cfg or load_config()
    try:
        ensure_cache(cfg)
        result = run(["git", "fetch", "--quiet", "origin",
                      "+refs/heads/claims:refs/remotes/origin/claims"],
                     cwd=cfg.cache, timeout=NET_TIMEOUT, check=False)
        if result.returncode != 0:
            if "couldn't find remote ref" in (result.stderr or ""):
                run(["git", "update-ref", "-d", "refs/remotes/origin/claims"],
                    cwd=cfg.cache, check=False)
                return True
            raise RuntimeError(result.stderr.strip()[:200])
        return True
    except SystemExit:
        raise
    except Exception as error:
        if strict:
            sys.exit(f"hq: cannot reach {cfg.repo} ({error}) - try again")
        return False


def claims_tree(cfg=None):
    """{path: claim-dict} from origin/claims (empty when the branch is absent)."""
    cfg = cfg or load_config()
    try:
        listing = run(["git", "ls-tree", "-r", "--name-only", "origin/claims"],
                      cwd=cfg.cache).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return {}
    out = {}
    for path in listing:
        if not path.startswith("claims/") or not path.endswith(".json"):
            continue
        raw = run(["git", "show", f"origin/claims:{path}"], cwd=cfg.cache).stdout
        try:
            out[path] = json.loads(raw)
        except json.JSONDecodeError:
            continue
    return out


def claim_path(repo, branch):
    return f"claims/{slug(repo)}/{slug(branch)}.json"


def active(claim):
    try:
        return datetime.fromisoformat(claim["expires"].replace("Z", "+00:00")) > now()
    except Exception:
        return True  # malformed expiry = treat as active; humans clean it up


def commit_claims_change(writes, deletes, message, check=None):
    """Commit claim-file changes to the claims branch via index plumbing, with a
    separate index file, so the cache clone never checks out another branch.
    Push is the compare-and-swap; one retry on a lost race.

    `check` is called with the freshly fetched claims before every attempt and
    exits to refuse. A lost race means somebody else's claims commit landed
    first, so the retry must look at what landed rather than write over it."""
    cfg = load_config()
    for attempt in (1, 2):
        fetch_claims(strict=True, cfg=cfg)
        if check is not None:
            check(claims_tree(cfg))
        env = dict(os.environ, GIT_INDEX_FILE=str(cfg.claims_index))

        def git(*args, check=True):
            return subprocess.run(["git", *args], cwd=cfg.cache, env=env,
                                  capture_output=True, text=True, check=check)

        try:
            base = run(["git", "rev-parse", "--verify", "--quiet", "origin/claims"],
                       cwd=cfg.cache, check=False).stdout.strip() or None
            if base:
                git("read-tree", base)
            else:
                git("read-tree", "--empty")
            for path, content in writes.items():
                blob = subprocess.run(["git", "hash-object", "-w", "--stdin"],
                                      cwd=cfg.cache, env=env, input=content,
                                      capture_output=True, text=True,
                                      check=True).stdout.strip()
                git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
            for path in deletes:
                git("update-index", "--force-remove", path, check=False)
            tree = git("write-tree").stdout.strip()
            if base and git("rev-parse", f"{base}^{{tree}}").stdout.strip() == tree:
                return  # nothing to change
            commit_env = dict(
                env,
                GIT_AUTHOR_NAME=cfg.bot_name, GIT_AUTHOR_EMAIL=cfg.bot_email,
                GIT_COMMITTER_NAME=cfg.bot_name, GIT_COMMITTER_EMAIL=cfg.bot_email)
            parent = ["-p", base] if base else []
            commit = subprocess.run(["git", "commit-tree", tree, *parent, "-m", message],
                                    cwd=cfg.cache, env=commit_env, capture_output=True,
                                    text=True, check=True).stdout.strip()
        except (subprocess.CalledProcessError, OSError) as error:
            # Building the commit is local work on the cache clone: a corrupt
            # cache, a state dir hq may not write, a machine with no git. None
            # of them reached the office, so the claim plainly did not change,
            # and one line says so instead of a stack trace out of a plumbing
            # command nobody but hq has heard of.
            detail = " ".join(str(getattr(error, "stderr", None) or error).split())[:200]
            sys.exit(f"hq: cannot build the claims commit ({detail}) - nothing was "
                     f"pushed and no claim changed; the cache clone is {cfg.cache}")
        try:
            push = run(["git", "push", "--quiet", "origin",
                        f"{commit}:refs/heads/claims"],
                       cwd=cfg.cache, check=False, timeout=PUSH_TIMEOUT)
        except subprocess.TimeoutExpired:
            # The one failure hq must not describe as either outcome. The push
            # may have reached the office and the answer been lost, so saying
            # "not taken" could hand the branch to a second agent, and saying
            # "taken" could claim one nobody holds. Name the ambiguity and the
            # command that resolves it.
            sys.exit(f"hq: the claims push did not answer within {PUSH_TIMEOUT}s - it "
                     "may or may not have landed. Run `hq claims` to see which, "
                     "before retrying")
        if push.returncode == 0:
            return
        if attempt == 2:
            # Usually two lost races in a row, but a login without write access
            # to the office fails here the same way, so name no cause: git's
            # own words follow.
            sys.exit(f"hq: the claims push failed twice - git said:\n{push.stderr}")
        # Lost the race: someone pushed first. Re-fetch, re-check, rebuild.


def cmd_claim(args):
    cfg = load_config()
    require_repo(cfg)
    me = require_identity()
    repo = args.repo or detect_repo()
    path = claim_path(repo, args.branch)

    def not_held_by_another(tree):
        existing = tree.get(path)
        if existing and active(existing) and existing.get("owner") != me:
            holder = existing.get("owner", "?")
            sys.exit(
                f"hq: {repo}#{args.branch} is CLAIMED by {holder} "
                f"until {existing.get('expires', '?')} - talk first: "
                f"hq msg {holder} \"...\""
            )

    claim = {
        "repo": repo, "branch": args.branch, "owner": me,
        "machine": socket.gethostname(), "created": iso(now()),
        "expires": iso(now() + timedelta(hours=args.ttl)),
        "note": args.note or "",
    }
    commit_claims_change({path: json.dumps(claim, indent=2) + "\n"}, [],
                         f"claim {repo}#{args.branch} by {me}",
                         check=not_held_by_another)
    print(f"claimed {repo}#{args.branch} for {me} until {claim['expires']}")


def cmd_release(args):
    cfg = load_config()
    require_repo(cfg)
    me = require_identity()
    repo = args.repo or detect_repo()
    fetch_claims(strict=True, cfg=cfg)
    path = claim_path(repo, args.branch)
    if not claims_tree(cfg).get(path):
        print(f"no claim on {repo}#{args.branch}")
        return

    def mine_to_release(tree):
        existing = tree.get(path)
        if (existing and existing.get("owner") != me and not args.force
                and not is_sovereign(me, cfg)):
            sys.exit(f"hq: claim belongs to {existing.get('owner', '?')} - "
                     "use --force to override")

    commit_claims_change({}, [path], f"release {repo}#{args.branch} by {me}",
                         check=mine_to_release)
    print(f"released {repo}#{args.branch}")


def cmd_claims(args):
    cfg = load_config()
    require_repo(cfg)
    fetch_claims(strict=True, cfg=cfg)
    rows = [c for c in claims_tree(cfg).values()
            if not args.repo or c.get("repo") == args.repo]
    live = [c for c in rows if active(c)]
    if not live:
        print("no active claims")
        return
    for c in sorted(live, key=lambda c: (c.get("repo", ""), c.get("branch", ""))):
        print(f"{c.get('repo','?'):28} {c.get('branch','?'):40} "
              f"{c.get('owner','?'):12} until {c.get('expires','?')}  {c.get('note','')}")


def cmd_check_push(args):
    """The push gate. Exit 1 means ONE thing: a live claim by somebody else.

    The pre-push hook turns any non-zero exit into a blocked push, so a crash in
    here would not fail one push, it would freeze every push on the machine
    until somebody debugged a traceback. The known causes - a malformed config,
    an unreadable one, a config that is not UTF-8 - are each handled where they
    arise. This is the general case, for the cause nobody has thought of yet:
    whatever hq did not foresee becomes one warning line and an open gate,
    since a crash is not evidence of a claim. A deliberate block is a
    `SystemExit` and passes straight through.
    """
    try:
        gate(args)
    except Exception as error:
        print(f"hq: WARNING - the push gate failed unexpectedly "
              f"({type(error).__name__}: {error}); pushing unverified (fail-open)",
              file=sys.stderr)


def cached_claim_by_another(cfg, repo, branch, me):
    """A live claim on this branch held by somebody else, as the local cache has
    it, or None.

    The cache is hq's own copy of the claims branch under the state dir. It is
    reachable whenever the state dir is, which is to say whenever HQ_HOME or the
    home directory is - never by way of the head office, and never by way of the
    config file.
    """
    cached = claims_tree(cfg).get(claim_path(repo, branch))
    if cached and active(cached) and cached.get("owner") not in (me, None):
        return cached
    return None


def state_is_a_guess(cfg):
    """True when `cfg.state` may not be this machine's real state dir.

    `home` is a config file key, so a machine set up with `hq init --home` has
    its state dir named in the very file hq cannot read, and `cfg.state` then
    falls back to `~/.agent-hq`. The cache the gate searches is not the cache
    holding the claims: a live claim two directories away reads as silence, and
    the push is waved through on the one machine that HAS the evidence. Reading
    `home` out of a broken file would need a second, more forgiving parser, and
    hq keeps one. So the gate says the directory it searched may be the wrong
    one instead of implying it looked where the claims are. HQ_HOME settles it,
    because the environment is read whatever the file does.
    """
    return bool(cfg.error) and not os.environ.get("HQ_HOME")


def say_state_may_be_wrong(cfg):
    """One more line when the gate waved a push through out of a state dir it
    had to guess. Only on the fail-open paths: a claim FOUND in that cache is
    evidence whatever the directory was, and the block stands on its own. It is
    silence that must not be reported as absence.

    The line also says when that directory is not there at all, because it turns
    a hedge into a fact: a state dir hq never created holds no cache, so the
    silence above is certainly not an answer about this branch - and an operator
    reading `ls: no such file or directory` learns in one line what a
    `may not be` would leave them to check by hand.
    """
    if not state_is_a_guess(cfg):
        return
    where = str(cfg.state) if cfg.state.exists() else f"{cfg.state}, which does not exist,"
    print(f"    (a `home` set in that config file could not be read, so "
          f"{where} may not be this machine's state dir; set HQ_HOME if the "
          f"gate is to be sure it read the right cache)", file=sys.stderr)


def gate(args):
    # A broken config file must not fail CLOSED here. `load_config(strict=False)`
    # hands the problem back as a value instead of exiting, so one stray character
    # in config.toml warns once rather than blocking every push on the machine.
    cfg = load_config(strict=False)
    # Resolved from the config hq HAS, broken or not. `identity()` would load it
    # again, strictly, and exit 1 on the file below - and a `SystemExit` is a
    # decision, so the fail-open wrapper hands it straight to the hook as a
    # blocked push.
    me = identity_source(cfg)[0] or "unknown"
    repo = parse_repo(args.repo) or args.repo
    if cfg.error:
        print(f"hq: WARNING - {cfg.error}", file=sys.stderr)
    if cfg.error and not cfg.repo:
        # Nothing but the cache to go on: the file hq cannot read was the only
        # thing that said where the office is. Fail-open, but only after
        # looking. The claims cache is under HQ_HOME or the default state dir,
        # and a claim already in it is knowing, so apply the same rule as an
        # unreachable office: a live claim by somebody else still blocks,
        # because a config hq cannot parse is not permission. The file may ALSO
        # have named the state dir, which is what `say_state_may_be_wrong` is
        # about below: then hq searched a cache that is not this machine's own,
        # and its silence proves nothing.
        #
        # When HQ_REPO names the office, none of this applies and the gate goes
        # on to ask it, exactly as it does with the file merely ABSENT.
        cached = cached_claim_by_another(cfg, repo, args.branch, me)
        if cached:
            owner = cached.get("owner")
            if is_sovereign(me, cfg):
                print(f"hq: note - {repo}#{args.branch} is claimed by {owner} "
                      f"(from the local cache under {cfg.state}, read despite the "
                      f"config file above); sovereign push allowed", file=sys.stderr)
                return
            print(
                f"hq: PUSH BLOCKED - {repo}#{args.branch} is claimed by {owner} "
                f"until {cached.get('expires', '?')}.\n"
                f"    (read from the local cache under {cfg.state}; the config file "
                f"above could not be read, so this claim may be stale - but a config "
                f"hq cannot parse is not permission)\n"
                f"    Coordinate first:  hq msg {owner} \"...\"",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"hq: the local cache under {cfg.state} holds no live claim by "
              f"another agent for {repo}#{args.branch} either; pushing unverified "
              f"(fail-open)", file=sys.stderr)
        say_state_may_be_wrong(cfg)
        return
    if not cfg.repo:
        # The one command that must NOT exit 1 on a missing config: it is a push gate,
        # and an unconfigured hq knows nothing about any claim. Say so and fail open,
        # exactly as it does when the network is down.
        print("hq: WARNING - no head office repo configured (run `hq init --repo owner/name` "
              "or set HQ_REPO); pushing unverified", file=sys.stderr)
        return
    reachable = fetch_claims(strict=False, cfg=cfg)
    if not reachable:
        # Fail-open is for NOT KNOWING. A claim already in the local cache is knowing: it is
        # positive evidence that this branch belongs to someone else, and an outage does not make
        # it less true. Only wave the push through when the cache is silent too.
        cached = cached_claim_by_another(cfg, repo, args.branch, me)
        if cached:
            if is_sovereign(me, cfg):
                print(f"hq: note - {repo}#{args.branch} is claimed by {cached.get('owner')} "
                      f"(from cache, {cfg.repo} unreachable); sovereign push allowed",
                      file=sys.stderr)
                return
            print(
                f"hq: PUSH BLOCKED - {repo}#{args.branch} is claimed by {cached.get('owner')} "
                f"until {cached.get('expires', '?')}.\n"
                f"    (read from the local cache; {cfg.repo} is unreachable, so this claim may be "
                f"stale - but an outage is not permission)\n"
                f"    Coordinate first:  hq msg {cached.get('owner')} \"...\"",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"hq: WARNING - cannot reach {cfg.repo} and the local cache holds no live "
              f"claim by another agent for {repo}#{args.branch}; pushing unverified "
              f"(fail-open)", file=sys.stderr)
        # Reachable with a broken config file too, now that HQ_REPO carries the
        # gate past it: the office was asked and did not answer, so the cache is
        # all that is left, and it may not be this machine's cache.
        say_state_may_be_wrong(cfg)
        return
    existing = claims_tree(cfg).get(claim_path(repo, args.branch))
    if not existing or not active(existing):
        return
    owner = existing.get("owner")
    if owner == me:
        return
    if is_sovereign(me, cfg):
        print(f"hq: note - {repo}#{args.branch} is claimed by {owner}; "
              f"sovereign push allowed", file=sys.stderr)
        return
    print(
        f"hq: PUSH BLOCKED - {repo}#{args.branch} is claimed by {owner} "
        f"until {existing.get('expires', '?')}.\n"
        f"    Coordinate first:  hq msg {owner} \"...\"   "
        f"(or have {owner} run: hq release {args.branch})",
        file=sys.stderr,
    )
    sys.exit(1)

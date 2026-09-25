#!/usr/bin/env python3
"""One code name -> ONE mark (emoji + colour), forever.

Identity belongs to the INITIATOR, not to each agent: every agent spawned by
`vivaldi` must carry vivaldi's emoji and colour, so the dashboard shows at a
glance whose agents they are. Orchestrators cannot be trusted to pass the same
`--icon/--color` on every spawn (they don't), so the mark is registered on first
sight and the registry WINS from then on.

Registry: $FLEET_CONFIG/codenames.json   { "vivaldi": {"icon": "🎻", "color": "#..."} }
Change one deliberately:  fleet identity vivaldi --icon 🎻 --color '#d4a017'

The marks a new code name is drawn from are the defaults below. A deployment that wants its own
set says so in $FLEET_CONFIG/policy.toml, and nothing here needs editing:

    [identity]
    glyphs  = ["●", "■", "▲"]
    colours = ["#5b8def", "#3fb950"]
"""
import contextlib
import fcntl
import json
import os
import sys
import time

CONFIG = os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet"))
REG = os.path.join(CONFIG, "codenames.json")

DEFAULT_GLYPHS = ["🦊", "🦉", "🐢", "🐝", "🦋", "🦈", "🐙", "🦅", "🐺", "🦁", "🐬",
                  "🦕", "🐸", "🦎", "🐳", "🦇", "🦜", "🐡", "🦩", "🦥", "🐧", "🦦"]
DEFAULT_COLOURS = ["#5b8def", "#3fb950", "#d29922", "#f85149", "#a371f7", "#3fb0d9",
                   "#e685b5", "#f0883e", "#56d364", "#db61a2", "#58a6ff", "#bc8cff"]

# Re-read when policy.toml changes, so editing the palette does not need a restart, and never
# on every resolve: this is called once per spawn and once per dashboard draw.
_marks_cache = {"key": None, "value": None}


def marks():
    """(glyphs, colours) a new code name is drawn from: the deployment's, or the defaults.

    A policy file that cannot be read is one line on stderr and the defaults, never a failed
    spawn: a palette is decoration, and decoration must not stop work.
    """
    path = os.path.join(CONFIG, "policy.toml")
    try:
        key = os.path.getmtime(path)
    except OSError:
        key = None
    if _marks_cache["value"] and _marks_cache["key"] == key:
        return _marks_cache["value"]
    glyphs, colours = list(DEFAULT_GLYPHS), list(DEFAULT_COLOURS)
    if key is not None:
        try:
            import tomllib
            with open(path, "rb") as handle:
                table = tomllib.load(handle).get("identity") or {}
            if not isinstance(table, dict):
                raise ValueError("[identity] is not a TOML table")
            chosen = [str(item) for item in (table.get("glyphs") or []) if str(item).strip()]
            painted = [str(item) for item in
                       (table.get("colours") or table.get("colors") or []) if str(item).strip()]
            glyphs = chosen or glyphs
            colours = painted or colours
        except Exception as exc:
            print(f"fleet identity: using the default marks ({path}: {exc})", file=sys.stderr)
    _marks_cache["key"], _marks_cache["value"] = key, (glyphs, colours)
    return glyphs, colours


def _hash(s):
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


@contextlib.contextmanager
def _registry_lock():
    os.makedirs(CONFIG, exist_ok=True)
    with open(REG + ".lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _load_unlocked():
    try:
        with open(REG) as handle:
            reg = json.load(handle)
        if not isinstance(reg, dict):
            raise ValueError("registry root is not a JSON object")
        return reg
    except FileNotFoundError:
        return {}
    except Exception as exc:
        quarantine = f"{REG}.corrupt.{time.time_ns()}.{os.getpid()}"
        try:
            os.replace(REG, quarantine)
        except OSError as quarantine_exc:
            raise RuntimeError(
                f"cannot read or quarantine identity registry: {exc}; {quarantine_exc}"
            ) from quarantine_exc
        print(f"fleet identity: quarantined unreadable registry at {quarantine}: {exc}",
              file=sys.stderr)
        return {}


def load():
    with _registry_lock():
        return _load_unlocked()


def _save_unlocked(reg):
    os.makedirs(CONFIG, exist_ok=True)
    tmp = f"{REG}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "x") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, REG)
        directory_fd = os.open(CONFIG, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def save(reg):
    with _registry_lock():
        _save_unlocked(reg)


def resolve(name, icon="", color=""):
    """The mark for a code name. Registers it on first sight; after that the
    registry wins, whatever the caller passes."""
    if not name:
        return "", ""
    with _registry_lock():
        reg = _load_unlocked()
        if name in reg:
            e = reg[name]
            return e.get("icon", ""), e.get("color", "")
        h = _hash(name)
        glyphs, colours = marks()
        e = {"icon": icon or glyphs[h % len(glyphs)],
             "color": color or colours[h % len(colours)]}
        reg[name] = e
        _save_unlocked(reg)
        return e["icon"], e["color"]


def cli(argv):
    if not argv:                                     # list every known mark
        reg = load()
        if not reg:
            print("  (no code names registered yet: they register on first spawn)")
            return
        for k in sorted(reg):
            e = reg[k]
            print(f"  {e.get('icon','?')}  {k:<14} {e.get('color','')}")
        return
    name, icon, color = argv[0], "", ""
    a = argv[1:]
    while a:
        if a[0] == "--icon" and len(a) > 1:
            icon = a[1]; a = a[2:]
        elif a[0] == "--color" and len(a) > 1:
            color = a[1]; a = a[2:]
        else:
            a = a[1:]
    if icon or color:                                # deliberate (re)branding
        with _registry_lock():
            reg = _load_unlocked()
            e = reg.get(name, {})
            if icon:
                e["icon"] = icon
            if color:
                e["color"] = color
            reg[name] = e
            _save_unlocked(reg)
        print(f"  {e.get('icon','?')}  {name}  {e.get('color','')}   (set)")
    else:
        i, c = resolve(name)
        print(f"  {i}  {name}  {c}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if cmd == "resolve":
        i, c = resolve(*(sys.argv[2:5] + ["", "", ""])[:3])
        print(f"{i}\t{c}")
    else:
        cli(sys.argv[2:])

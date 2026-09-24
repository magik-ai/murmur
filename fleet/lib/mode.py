#!/usr/bin/env python3
"""Power modes — hand CPU back to Windows when you're using the PC, take it all when idle.

The farm runs in a WSL distro whose agents live in a systemd --user slice, `fleet.slice`
(the spawn launcher puts them there). Because that slice is in the user manager's delegated
cgroup subtree, we can cap its CPU LIVE and REVERSIBLY with `systemctl --user set-property`
— no root, no WSL restart, no killing agents. That's the whole trick.

Modes:
  full      no cap, spawns on           — the farm takes everything (default when idle)
  soft      ~50% CPU, spawns ON         — yields to a foreground game but keeps working
  balanced  ~35% CPU, spawns paused     — existing agents crawl, no new ones
  hard      ~20% CPU, spawns paused     — near-frozen; for a game that wants every frame
  auto      full when the GPU is idle; SOFT when the GPU is busy (= you're gaming)

`auto` needs a GPU sensor to have an opinion. Without one (no nvidia-smi on PATH, no
FLEET_NVIDIA_SMI) it is INERT: it resolves to full and says so once, rather than pretending
to read a game that nothing is watching for. The manual profiles work regardless.

A sensor that IS there and fails to answer (nvidia-smi timing out under load is the common
case) is a different thing entirely, and used to be treated the same: one slow read released
the cap to full, the next one throttled back to soft, and the farm yo-yoed while somebody was
gaming. A failed read keeps whatever profile is in force and leaves the hysteresis alone.

`auto` is the default and deliberately picks SOFT, never a harder profile: casually using
the PC must not stop the fleet — it just steps aside. Pick a harder profile by hand
(`fleet mode balanced|hard`, or the dashboard selector) for a serious session. A manual
pick always wins over auto until you set `fleet mode auto` again.

systemd expresses CPUQuota as a percentage of ONE core, so "50% of a 14-core box" is
CPUQuota=700%. We convert here.
"""
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time

CONFIG = os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet"))
STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
SETTING_FILE = os.path.join(STATE, "mode")             # the chosen setting (one word)
RUNTIME_FILE = os.path.join(STATE, "mode-runtime.json")  # hysteresis + last-applied
SLICE = "fleet.slice"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics as M  # noqa: E402

# cpu_quota_pct = share of the WHOLE machine (None = uncapped); cpu_weight = scheduler
# share when NOT quota-bound (100 = default, lower = yields); allow_spawn = accept new agents.
# mem_high_pct = share of machine RAM the farm may hold before the kernel starts reclaiming from
# it (None = uncapped). MemoryHigh throttles rather than kills, so a squeezed lane slows down
# instead of losing its work.
DEFAULT_PROFILES = {
    "full":     {"cpu_quota_pct": None, "cpu_weight": 100, "allow_spawn": True,
                 "mem_high_pct": None},
    "soft":     {"cpu_quota_pct": 50,   "cpu_weight": 40,  "allow_spawn": True,
                 "mem_high_pct": 60},
    "balanced": {"cpu_quota_pct": 35,   "cpu_weight": 20,  "allow_spawn": False,
                 "mem_high_pct": 40},
    "hard":     {"cpu_quota_pct": 20,   "cpu_weight": 10,  "allow_spawn": False,
                 "mem_high_pct": 25},
}
DEFAULT_AUTO = {
    "auto_enter_gpu": 25,   # GPU util % that reads as "a game is running" -> throttle
    "auto_exit_gpu": 10,    # ...and below this...
    "auto_exit_hold": 60,   # ...for this many seconds -> back to full (hysteresis)
}
VALID = ("auto", "full", "soft", "balanced", "hard")


@contextlib.contextmanager
def _mode_lock():
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "mode-runtime.lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _atomic_write(path, payload):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "x") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(directory, os.O_RDONLY)
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


def _policy():
    """Profiles + auto thresholds, overridable from policy.toml ([mode], [mode.<name>])."""
    profs = {k: dict(v) for k, v in DEFAULT_PROFILES.items()}
    auto = dict(DEFAULT_AUTO)
    fp = os.path.join(CONFIG, "policy.toml")
    if os.path.exists(fp):
        try:
            import tomllib
            with open(fp, "rb") as f:
                d = tomllib.load(f)
            m = d.get("mode", {}) or {}
            for k in DEFAULT_AUTO:
                if k in m:
                    auto[k] = m[k]
            for name in profs:
                over = m.get(name, {}) or {}
                for k in profs[name]:
                    if k in over:
                        profs[name][k] = over[k]
        except Exception:
            pass
    # TOML has no null, so an uncapped profile is written as cpu_quota_pct = 0; treat
    # 0 (or None) as "no cap". A literal 0% quota would FREEZE the slice, so never emit it.
    for name in profs:
        if not profs[name]["cpu_quota_pct"]:
            profs[name]["cpu_quota_pct"] = None
    return profs, auto


def get_setting():
    try:
        v = open(SETTING_FILE).read().strip()
        return v if v in VALID else "auto"
    except Exception:
        return "auto"


def set_setting(m):
    if m not in VALID:
        raise ValueError(f"unknown mode '{m}' ({'|'.join(VALID)})")
    with _mode_lock():
        _atomic_write(SETTING_FILE, m + "\n")


def _load_rt():
    try:
        with open(RUNTIME_FILE) as handle:
            rt = json.load(handle)
        if not isinstance(rt, dict):
            raise ValueError("runtime state is not a JSON object")
        return rt
    except FileNotFoundError:
        return {"auto_eff": "full", "below_since": None, "applied": None}
    except Exception as exc:
        quarantine = f"{RUNTIME_FILE}.corrupt.{time.time_ns()}.{os.getpid()}"
        try:
            os.replace(RUNTIME_FILE, quarantine)
        except OSError as quarantine_exc:
            raise RuntimeError(
                f"cannot read or quarantine mode runtime: {exc}; {quarantine_exc}"
            ) from quarantine_exc
        print(f"fleet mode: quarantined unreadable runtime at {quarantine}: {exc}",
              file=sys.stderr)
        return {"auto_eff": "full", "below_since": None, "applied": None}


def _save_rt(rt):
    _atomic_write(RUNTIME_FILE, json.dumps(rt, separators=(",", ":"), sort_keys=True) + "\n")


def _gpu_util():
    """GPU utilisation percent, or None when there is no reading. None is not 0: one means
    "idle, take everything", the other means "nobody is looking"."""
    try:
        g = M.gpu()
    except Exception:
        return None
    if not g:
        return None
    util = g.get("util_pct")
    return int(util) if util is not None else 0


def _gpu_sensor_present():
    """Whether a GPU sensor was configured when this module was imported. This is the ONLY
    question that separates "this box has no GPU to watch" from "the sensor is there and did not
    answer this time"; metrics.NVIDIA is resolved once, at import, exactly so it can be asked."""
    path = getattr(M, "NVIDIA", "")
    return bool(path) and os.path.exists(path)


def _warn_sensorless_once(rt):
    """Say once that `auto` has nothing to steer by. Repeating it every few seconds would bury
    the dashboard's log; never saying it leaves a mode that silently does nothing."""
    if rt.get("sensorless_warned"):
        return
    rt["sensorless_warned"] = True
    print("fleet mode: no GPU sensor (nvidia-smi not on PATH and FLEET_NVIDIA_SMI unset): "
          "`auto` is inert and stays on `full`; pick a profile by hand to throttle the farm",
          file=sys.stderr)


def _warn_unreadable_once(rt, eff):
    """Say once that the sensor is there and silent. Every few seconds it would be noise, and it
    is not an emergency: the profile in force is simply held."""
    if rt.get("unreadable_warned"):
        return
    rt["unreadable_warned"] = True
    print(f"fleet mode: the GPU sensor did not answer; holding `{eff}` until it does "
          "(a read that times out is not an idle GPU)", file=sys.stderr)


def resolve_effective(setting, gpu_util, rt, auto, sensor_present=False):
    """The profile that should be in force right now. Manual settings pin directly;
    `auto` flips full<->soft off the GPU with hysteresis so it can't yo-yo.

    `sensor_present` separates the two reasons gpu_util can be None. No sensor at all resolves
    to full, because nothing will ever throttle it. A sensor that failed THIS read keeps the
    profile already in force: releasing the cap on a timeout is how the farm used to yo-yo
    between full and soft while somebody was gaming."""
    if setting != "auto":
        return setting
    if gpu_util is None:
        if sensor_present:
            # Hold. below_since is left alone as well, so a hysteresis window in progress is
            # not restarted by a read that simply did not answer.
            return rt.get("auto_eff", "full")
        # Nothing to steer by. Resolve to full and leave the hysteresis state clean, so that
        # plugging a sensor in later starts from a known place rather than a stale `below_since`.
        rt["auto_eff"] = "full"
        rt["below_since"] = None
        return "full"
    now = time.time()
    prev = rt.get("auto_eff", "full")
    if gpu_util >= auto["auto_enter_gpu"]:            # game clearly running
        rt["auto_eff"] = "soft"; rt["below_since"] = None
        return "soft"
    if prev == "soft":                               # was throttling — hold before releasing
        if gpu_util <= auto["auto_exit_gpu"]:
            if rt.get("below_since") is None:
                rt["below_since"] = now
            if now - rt["below_since"] >= auto["auto_exit_hold"]:
                rt["auto_eff"] = "full"; rt["below_since"] = None
                return "full"
            return "soft"
        rt["below_since"] = None                      # in the hysteresis band -> stay soft
        return "soft"
    rt["auto_eff"] = "full"; rt["below_since"] = None
    return "full"



def _ram_free_gb():
    try:
        with open("/proc/meminfo") as handle:
            fields = {}
            for line in handle:
                key, _, rest = line.partition(":")
                fields[key] = int(rest.split()[0])
        available = fields.get("MemAvailable")
        if available is not None:
            return round(available / 1024 ** 2, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _machine_ram_bytes():
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 8 * 1024 ** 3


def _apply(profile_name, profs):
    """Set fleet.slice's CPU limits live via the user manager (no root). Idempotent;
    harmless if the slice doesn't exist yet (no agents) — the next spawn recreates it
    and cmd_spawn reapplies."""
    prof = profs[profile_name]
    ncores = os.cpu_count() or 1
    if prof["cpu_quota_pct"] is None:
        quota = ""                                   # empty removes the cap
        weight = ""                                  # back to default 100
    else:
        quota = f"{round(prof['cpu_quota_pct'] / 100 * ncores * 100)}%"
        weight = str(prof["cpu_weight"])
    mem_pct = prof.get("mem_high_pct")
    if mem_pct is None:
        mem_high = ""                                # empty removes the cap
    else:
        mem_high = f"{max(1, round(_machine_ram_bytes() * mem_pct / 100 / (1024 ** 2)))}M"
    subprocess.run(
        ["systemctl", "--user", "set-property", SLICE,
         f"CPUQuota={quota}", f"CPUWeight={weight}", f"MemoryHigh={mem_high}"],
        capture_output=True)


def tick(force=False):
    """Resolve the effective profile and apply it if it changed (or if forced). Called
    every few seconds by the dashboard, and force=True by cmd_spawn so a fresh slice
    inherits the current cap. Returns the status dict."""
    profs, auto = _policy()
    gpu = _gpu_util()
    have_sensor = _gpu_sensor_present()
    with _mode_lock():
        setting = get_setting()
        rt = _load_rt()
        eff = resolve_effective(setting, gpu, rt, auto, have_sensor)
        if gpu is None:
            if setting == "auto":
                if have_sensor:
                    _warn_unreadable_once(rt, eff)
                else:
                    _warn_sensorless_once(rt)
        else:
            if rt.pop("sensorless_warned", None):
                print("fleet mode: GPU sensor is back, `auto` is live again", file=sys.stderr)
            rt.pop("unreadable_warned", None)
        if force or rt.get("applied") != eff:
            _apply(eff, profs)
            rt["applied"] = eff
        _save_rt(rt)
    prof = profs[eff]
    ncores = os.cpu_count() or 1
    return {
        "setting": setting, "effective": eff, "gpu_util": gpu,
        "allow_spawn": bool(prof["allow_spawn"]),
        "cpu_quota_pct": prof["cpu_quota_pct"],
        "cpu_cores": None if prof["cpu_quota_pct"] is None
        else round(prof["cpu_quota_pct"] / 100 * ncores, 1),
        "cores_total": ncores,
        "mem_high_pct": prof.get("mem_high_pct"),
        "mem_high_gb": None if prof.get("mem_high_pct") is None
        else round(_machine_ram_bytes() * prof["mem_high_pct"] / 100 / 1024 ** 3, 1),
        "ram_total_gb": round(_machine_ram_bytes() / 1024 ** 3, 1),
        "ram_free_gb": _ram_free_gb(),
    }


def status():
    """Read-only view without re-applying (for display)."""
    profs, auto = _policy()
    with _mode_lock():
        setting = get_setting()
        rt = _load_rt()
    gpu = _gpu_util()
    # compute effective without mutating persisted hysteresis state
    eff = resolve_effective(setting, gpu, dict(rt), auto, _gpu_sensor_present())
    prof = profs[eff]
    ncores = os.cpu_count() or 1
    return {
        "setting": setting, "effective": eff, "gpu_util": gpu,
        "allow_spawn": bool(prof["allow_spawn"]),
        "cpu_quota_pct": prof["cpu_quota_pct"],
        "cpu_cores": None if prof["cpu_quota_pct"] is None
        else round(prof["cpu_quota_pct"] / 100 * ncores, 1),
        "cores_total": ncores,
        "mem_high_pct": prof.get("mem_high_pct"),
        "mem_high_gb": None if prof.get("mem_high_pct") is None
        else round(_machine_ram_bytes() * prof["mem_high_pct"] / 100 / 1024 ** 3, 1),
        "ram_total_gb": round(_machine_ram_bytes() / 1024 ** 3, 1),
        "ram_free_gb": _ram_free_gb(),
    }


def _human(st):
    q = ("uncapped" if st["cpu_quota_pct"] is None
         else f"{st['cpu_quota_pct']}% CPU (~{st['cpu_cores']} of {st['cores_total']} cores)")
    tag = st["effective"] if st["setting"] != "auto" else f"auto -> {st['effective']}"
    spawn = "spawns on" if st["allow_spawn"] else "spawns PAUSED"
    gpu = "GPU no sensor" if st["gpu_util"] is None else f"GPU {st['gpu_util']}%"
    return f"mode: {tag}   {q}   {spawn}   ({gpu})"


def cli(argv):
    if not argv or argv[0] in ("status", "show"):
        print("  " + _human(status()))
        return
    m = argv[0]
    if m not in VALID:
        print(f"unknown mode '{m}' ({'|'.join(VALID)})", file=sys.stderr)
        raise SystemExit(1)
    set_setting(m)
    st = tick(force=True)          # apply immediately, don't wait for the dashboard tick
    print("  " + _human(st))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "allow-spawn":
        st = tick()               # resolving also keeps the slice cap current
        if st["allow_spawn"]:
            print("1")
        else:
            tag = st["effective"] if st["setting"] != "auto" else f"auto->{st['effective']}"
            print(f"0\t{tag}")
    elif cmd == "reapply":
        tick(force=True)
    elif cmd == "tick":
        print(json.dumps(tick()))
    elif cmd == "status-json":
        print(json.dumps(status()))
    elif cmd == "set" and len(sys.argv) > 2:
        cli([sys.argv[2]])
    else:
        cli(sys.argv[1:])

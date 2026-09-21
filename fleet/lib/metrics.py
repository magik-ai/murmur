#!/usr/bin/env python3
"""Farm telemetry + capacity verdict for the fleet. Prints one JSON object.

Used by `fleet metrics`, the capacity guard in `fleet spawn`, and the dashboard.
Everything here is read-only and cheap enough to poll every couple of seconds.
"""
import contextlib
import fcntl
import glob
import json
import os
import shutil
import subprocess
import sys
import time

STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
CONFIG = os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet"))
# Both sensors are OPTIONAL and absent by default: a fleet is not entitled to assume a GPU or a
# temperature feed, and a hardcoded address for either is one machine's wiring baked into the tool.
#
# nvidia-smi is looked up on PATH. FLEET_NVIDIA_SMI points at it when it lives somewhere PATH does
# not reach (under WSL it is /usr/lib/wsl/lib/nvidia-smi, which is not always on a service's PATH).
NVIDIA = os.environ.get("FLEET_NVIDIA_SMI") or shutil.which("nvidia-smi")
# CPU temp cannot be read from inside WSL; a LibreHardwareMonitor web server on the Windows host
# exposes it over HTTP. Set FLEET_LHM_URL to that endpoint. Unset or unreachable -> cpu_temp is
# None, which is a warning, never a block.
LHM_URL = os.environ.get("FLEET_LHM_URL", "").strip()

# Starting points, not measurements of your machine. An agent is cheap while it thinks and
# expensive in short bursts (a front end build, a test run), so the floors exist to leave room
# for several bursts at once rather than for the agents themselves. MEASURE YOUR OWN BOX and put
# the numbers in policy.toml: watch free memory while the farm is busy, and read the throttle
# temperature from the chip's own documentation. Past a certain size the real ceiling stops
# being the hardware and becomes the subscription's usage pool.
DEFAULT_POLICY = {
    "ram_min_gb": 6,      # hard floor: below this, block spawns (headroom for in-flight bursts)
    "disk_min_gb": 20,    # state/git writes stop being trustworthy below this hard floor
    # Agent count no longer BLOCKS: hardware is the only hard gate. `warn_agents` still drives
    # an amber "watch it" signal; there is no count ceiling.
    "gpu_temp_max": 87,   # hard ceiling in C; set it a little under where your GPU throttles
    "cpu_temp_max": 92,   # hard ceiling in C; set it a little under where your CPU throttles
    "warn_ram_gb": 8,     # soft: dashboard/orchestrator warns below this (above the hard floor)
    "warn_disk_gb": 40,   # leave room for worktrees, package installs and CI images
    "warn_agents": 24,    # amber above this: advisory only, never blocks
    "warn_gpu_temp": 82,  # amber above this; below it is normal under load
    "warn_cpu_temp": 85,  # amber above this; below it is normal under load
}


def _load_policy():
    pol = dict(DEFAULT_POLICY)
    fp = os.path.join(CONFIG, "policy.toml")
    if not os.path.exists(fp):
        return pol, "defaults (policy.toml absent)"
    try:
        import tomllib
        with open(fp, "rb") as f:
            limits = tomllib.load(f).get("limits", {})
        if not isinstance(limits, dict):
            raise ValueError("[limits] is not a TOML table")
        pol.update(limits)
        return pol, fp
    except Exception as exc:
        detail = " ".join(str(exc).splitlines())
        source = f"defaults (policy.toml invalid: {detail})"
        print(f"fleet metrics: {source}", file=sys.stderr)
        return pol, source


def load_policy():
    """Compatibility API for callers that only need limits; collect() also exposes the source."""
    return _load_policy()[0]


def _atomic_write_json(path, value):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "x") as handle:
            json.dump(value, handle)
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


@contextlib.contextmanager
def _file_lock(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def gpu():
    if not NVIDIA or not os.path.exists(NVIDIA):
        return None
    try:
        out = subprocess.run(
            [NVIDIA, "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()[0]
        name, temp, util, mused, mtot = [x.strip() for x in out.split(",")]
        return {"name": name, "temp_c": int(temp), "util_pct": int(util),
                "mem_used_mb": int(mused), "mem_total_mb": int(mtot)}
    except Exception:
        return None


def cpu_temp():
    """Read CPU temp from a LibreHardwareMonitor web server named by FLEET_LHM_URL.
    Prefers the AMD Tctl/Tdie package sensor; falls back to a 'CPU Core' sensor.
    No URL configured means no sensor, which is the default."""
    if not LHM_URL:
        return None
    try:
        import urllib.request
        d = json.loads(urllib.request.urlopen(LHM_URL, timeout=1.5).read())
    except Exception:
        return None

    found = {}

    def val(v):
        try:
            return float(str(v).split("°")[0].strip().replace(",", "."))
        except Exception:
            return None

    def walk(n, path=""):
        p = (path + "/" + n.get("Text", "")).lower()
        v = n.get("Value", "")
        if isinstance(v, str) and "°C" in v:
            t = val(v)
            if t is not None:
                if ("tctl" in p or "tdie" in p) and ("ryzen" in p or "cpu" in p or "core" in p):
                    found.setdefault("tctl", t)
                elif "cpu core" in p:
                    found.setdefault("cpucore", t)
        for c in n.get("Children", []):
            walk(c, p)

    walk(d)
    return found.get("tctl") or found.get("cpucore")


def swap_churn_kbps():
    """Swap traffic in KB/s (vmstat's si+so) from /proc/vmstat page counters vs a persisted prior
    sample. This is the honest thrashing signal: 0 when swap is merely parked, high only when the
    kernel is actively moving pages to/from disk. Best-effort: any error -> 0.0."""
    import json as _json
    import time as _time
    try:
        cur = {}
        with open("/proc/vmstat") as f:
            for ln in f:
                k, _, v = ln.partition(" ")
                if k in ("pswpin", "pswpout"):
                    cur[k] = int(v.strip())
        pages = cur.get("pswpin", 0) + cur.get("pswpout", 0)   # 4KB pages, cumulative
        now = _time.time()
        sp = os.path.join(os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet")), ".swapstat.json")
        with _file_lock(sp + ".lock"):
            prev = None
            try:
                with open(sp) as handle:
                    prev = _json.load(handle)
            except Exception:
                pass
            try:
                _atomic_write_json(sp, {"ts": now, "pages": pages})
            except Exception:
                pass
        if not prev:
            return 0.0
        dt = now - prev.get("ts", now)
        dp = pages - prev.get("pages", pages)
        if dt <= 0 or dt > 120 or dp < 0:      # first/stale/counter-reset -> no rate
            return 0.0
        return round(dp * 4 / dt, 1)           # pages*4KB / seconds = KB/s
    except Exception:
        return 0.0


def mem():
    d = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, rest = line.partition(":")
            d[k] = int(rest.strip().split()[0])  # kB
    g = 1024 * 1024
    return {
        "ram_total_gb": round(d["MemTotal"] / g, 1),
        "ram_avail_gb": round(d["MemAvailable"] / g, 1),
        "ram_used_gb": round((d["MemTotal"] - d["MemAvailable"]) / g, 1),
        "swap_total_gb": round(d.get("SwapTotal", 0) / g, 1),
        "swap_used_gb": round((d.get("SwapTotal", 0) - d.get("SwapFree", 0)) / g, 1),
        "swap_churn_kbps": swap_churn_kbps(),
    }


def loadavg():
    with open("/proc/loadavg") as f:
        a = f.read().split()
    return {"load1": float(a[0]), "load5": float(a[1]), "load15": float(a[2]),
            "cores": os.cpu_count()}


def disk():
    """Disk holding fleet state/worktrees; walk to an existing parent on first install."""
    path = os.path.abspath(STATE)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    usage = shutil.disk_usage(path)
    gb = 1024 ** 3
    return {
        "path": path,
        "total_gb": round(usage.total / gb, 1),
        "used_gb": round(usage.used / gb, 1),
        "free_gb": round(usage.free / gb, 1),
    }


# Only these cost the machine anything. `pr_open` is TERMINAL: the agent opened its PR
# and exited, so it burns no RAM and no CPU. Counting it against the concurrency cap
# (as this did) blocks spawns on a farm that is 95% idle: 13 finished agents awaiting
# merge read as 13 running ones. Keep this set identical to `clean`'s.
ACTIVE = ("starting", "running")


def agents():
    """Agents actually occupying the machine, not ones that finished and left a PR."""
    n = 0
    for fp in glob.glob(os.path.join(STATE, "state", "*.json")):
        state = None
        last = None
        for attempt in range(2):
            try:
                with open(fp) as handle:
                    state = json.load(handle)
                break
            except Exception as exc:
                last = exc
                if attempt == 0:
                    time.sleep(0.01)
        if isinstance(state, dict):
            if state.get("status") in ACTIVE:
                n += 1
        else:
            # Capacity must fail closed: an unreadable card may still represent a live worker.
            n += 1
            print(f"fleet metrics: counting unreadable state as active ({fp}: {last})",
                  file=sys.stderr)
    return n


def verdict(m, pol):
    blocks = []
    warnings = []
    if m["mem"]["ram_avail_gb"] < pol["ram_min_gb"]:
        blocks.append(f"free RAM {m['mem']['ram_avail_gb']}GB < {pol['ram_min_gb']}GB")
    if m["disk"]["free_gb"] < pol["disk_min_gb"]:
        blocks.append(f"free disk {m['disk']['free_gb']}GB < {pol['disk_min_gb']}GB")
    if m["gpu"] and m["gpu"]["temp_c"] > pol["gpu_temp_max"]:
        blocks.append(f"GPU {m['gpu']['temp_c']}C > {pol['gpu_temp_max']}C")
    ct = m.get("cpu_temp_c")
    if ct is not None and ct > pol["cpu_temp_max"]:
        blocks.append(f"CPU {ct}C > {pol['cpu_temp_max']}C")
    if ct is None:
        warnings.append("CPU temp UNKNOWN (no FLEET_LHM_URL, or the sensor is unreachable)")
    if m["mem"]["ram_avail_gb"] < pol["warn_ram_gb"]:
        warnings.append(f"free RAM below warning floor ({pol['warn_ram_gb']}GB)")
    if m["disk"]["free_gb"] < pol["warn_disk_gb"]:
        warnings.append(f"free disk below warning floor ({pol['warn_disk_gb']}GB)")
    if m["agents"] >= pol["warn_agents"]:
        warnings.append(f"active agents {m['agents']} >= warning level {pol['warn_agents']}")
    if m["gpu"] and m["gpu"]["temp_c"] > pol["warn_gpu_temp"]:
        warnings.append(f"GPU above warning temperature ({pol['warn_gpu_temp']}C)")
    if ct is not None and ct > pol["warn_cpu_temp"]:
        warnings.append(f"CPU above warning temperature ({pol['warn_cpu_temp']}C)")
    # `blocks` holds only HARDWARE blocks (RAM/disk floors, GPU/CPU temp). Agent count is
    # deliberately absent: a busy farm with cool metal and free RAM keeps spawning.
    ok = not blocks
    level = "block" if not ok else ("warn" if warnings else "ok")
    return {"can_spawn": ok, "level": level, "reasons": blocks + warnings,
            "block_reasons": blocks, "warnings": warnings}


def collect():
    pol, policy_source = _load_policy()
    gpu_reading = gpu()
    cpu_reading = cpu_temp()
    unavailable = []
    if gpu_reading is None:
        unavailable.append("gpu")
    if cpu_reading is None:
        unavailable.append("cpu_temp")
    m = {"ts": int(time.time()), "load": loadavg(), "mem": mem(), "disk": disk(),
         "gpu": gpu_reading, "cpu_temp_c": cpu_reading,
         "cpu_temp_source": "librehardwaremonitor" if cpu_reading is not None else "unavailable",
         "sensors_unavailable": unavailable, "agents": agents()}
    m["capacity"] = verdict(m, pol)
    m["policy"] = pol
    m["policy_source"] = policy_source
    return m


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2 if "--pretty" in sys.argv else None))

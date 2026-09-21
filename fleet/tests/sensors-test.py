#!/usr/bin/env python3
"""Both hardware sensors are optional, and `auto` mode must degrade rather than lie.

The trap this guards: a farm with no GPU and no temperature feed used to read as "GPU idle,
0%", which is the same signal as "idle, take everything". A mode that silently does nothing
looks exactly like a mode that is working.

Run:  python3 tests/sensors-test.py
"""
import importlib
import os
import pathlib
import subprocess
import sys
import tempfile

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  -- ' + detail if detail and not ok else ''}")


def load(module, env):
    """Re-import a module under a specific environment; both read their sensors at import."""
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    sys.path.insert(0, str(LIB))
    for name in ("metrics", "mode"):
        sys.modules.pop(name, None)
    return importlib.import_module(module)


def main():
    state = tempfile.mkdtemp(prefix="fleet-sensors-")
    # The question under test is whether MISSING SENSORS block a spawn. RAM and disk floors are
    # not, and the runner this suite lands on may have less than the shipped floors, so they
    # are zeroed in a throwaway policy for the length of the test.
    config = pathlib.Path(state) / "config"
    config.mkdir()
    (config / "policy.toml").write_text("[limits]\nram_min_gb = 0\ndisk_min_gb = 0\n"
                                        "warn_ram_gb = 0\nwarn_disk_gb = 0\n")
    os.environ["FLEET_CONFIG"] = str(config)
    fake = pathlib.Path(state) / "nvidia-smi-stub"
    fake.write_text("#!/bin/sh\necho 'StubGPU, 71, 90, 1024, 16384'\n")
    fake.chmod(0o755)

    print("--- no sensors configured ---")
    metrics = load("metrics", {"FLEET_LHM_URL": None, "FLEET_NVIDIA_SMI": "",
                               "FLEET_STATE": state, "PATH": "/nonexistent"})
    check("no default LibreHardwareMonitor URL", metrics.LHM_URL == "", repr(metrics.LHM_URL))
    check("nvidia-smi is not guessed at a path", not metrics.NVIDIA, repr(metrics.NVIDIA))
    check("cpu_temp is absent, not an error", metrics.cpu_temp() is None)
    check("gpu is absent, not an error", metrics.gpu() is None)
    snapshot = metrics.collect()
    check("both sensors are reported unavailable",
          set(snapshot["sensors_unavailable"]) == {"gpu", "cpu_temp"},
          str(snapshot["sensors_unavailable"]))
    check("a sensorless farm can still spawn", snapshot["capacity"]["can_spawn"] is True,
          str(snapshot["capacity"]["reasons"]))

    mode = load("mode", {"FLEET_LHM_URL": None, "FLEET_NVIDIA_SMI": "",
                         "FLEET_STATE": state, "PATH": "/nonexistent"})
    check("a missing GPU reads as None, never as 0%", mode._gpu_util() is None)
    runtime = {"auto_eff": "soft", "below_since": 1.0, "applied": "soft"}
    check("auto without a sensor resolves to full",
          mode.resolve_effective("auto", None, runtime, mode.DEFAULT_AUTO) == "full")
    check("and leaves no stale hysteresis behind", runtime["below_since"] is None)
    check("a manual profile still wins without a sensor",
          mode.resolve_effective("hard", None, dict(runtime), mode.DEFAULT_AUTO) == "hard")

    print("--- the inert warning is said once, not every tick ---")
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "import mode\n"
        "mode._apply = lambda *a, **k: None\n"
        "mode.tick(); mode.tick(); mode.tick()\n" % str(LIB)
    )
    env = dict(os.environ, FLEET_STATE=state, PATH="/nonexistent", FLEET_NVIDIA_SMI="")
    env.pop("FLEET_LHM_URL", None)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
    said = result.stderr.count("`auto` is inert")
    check("said exactly once across three ticks", said == 1, f"said {said} times: {result.stderr}")

    print("--- a sensor that is THERE and fails to answer is not an idle GPU ---")
    broken = pathlib.Path(state) / "nvidia-smi-broken"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)
    mode = load("mode", {"FLEET_NVIDIA_SMI": str(broken), "FLEET_STATE": state,
                         "FLEET_LHM_URL": None, "PATH": "/nonexistent"})
    check("a failed read still reads as None, never as 0%", mode._gpu_util() is None)
    check("but the sensor is known to be present", mode._gpu_sensor_present() is True)
    throttling = {"auto_eff": "soft", "below_since": 123.0, "applied": "soft"}
    check("auto holds the profile in force instead of releasing to full",
          mode.resolve_effective("auto", None, throttling, mode.DEFAULT_AUTO, True) == "soft")
    check("and does not restart a hysteresis window that is running",
          throttling["below_since"] == 123.0)
    check("a missing sensor still resolves to full",
          mode.resolve_effective("auto", None, {"auto_eff": "soft"}, mode.DEFAULT_AUTO,
                                 False) == "full")

    # End to end: the applier must not flip the slice back to full on one silent read.
    applied = []
    mode._apply = lambda eff, profs: applied.append(eff)
    mode._save_rt({"auto_eff": "soft", "below_since": None, "applied": "soft"})
    mode.set_setting("auto")
    status = mode.tick()
    check("tick keeps `soft` applied while the sensor is silent",
          status["effective"] == "soft" and applied in ([], ["soft"]), f"{status['effective']} {applied}")

    print("--- a real sensor is still honoured ---")
    mode = load("mode", {"FLEET_NVIDIA_SMI": str(fake), "FLEET_STATE": state,
                         "FLEET_LHM_URL": None, "PATH": "/nonexistent"})
    check("a busy GPU still throttles auto to soft",
          mode.resolve_effective("auto", 90, {"auto_eff": "full"}, mode.DEFAULT_AUTO) == "soft")
    check("FLEET_NVIDIA_SMI is read", mode.M.gpu() is not None, str(mode.M.gpu()))

    print(f"\nRESULT pass={len(PASS)} fail={len(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

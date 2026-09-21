/* System: is this machine healthy, and is anything missing. Every sensor says which of the
   three things it is: reporting, switched off on purpose, or present and not answering.
   A tile that quietly disappears is the thing this view exists to stop. */

import {
  h, card, panel, pill, emptyState, skeletonStack, toast,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list } from "../core/api.js";

/* The four power settings, in plain words, with what each does to the machine's share. */
const POWER = [
  ["full", "Full", "Every core is available to the agents."],
  ["soft", "Shared", "The agents give way to whatever else you are doing."],
  ["balanced", "Background", "The agents keep a small share and stay out of the way."],
  ["hard", "Paused", "No new agent starts, and the running ones are held back hard."],
  ["auto", "Automatic", "The farm picks one of the four from how busy the machine is."],
];

const HEALTH_WORD = { ok: "ok", missing: "missing", error: "error", off: "off" };
const HEALTH_MEANING = { ok: "done", missing: "wait", error: "fail", off: "pause" };

const SENSOR_WORD = { done: "reporting", fail: "no answer", wait: "needs you", pause: "off" };

/* A tile says three things: what it measures, the number, and one line about the number.
   The state word stays short, because a sentence inside a pill cannot wrap and pushes the
   page sideways on a phone. */
function tile(label, value, note, meaning) {
  return card({ class: "card-pad tile", key: label },
    h("div", { class: "label" }, label, meaning ? pill(meaning, SENSOR_WORD[meaning] || meaning, note || "") : null),
    h("div", { class: "value", "data-flash": "" }, value),
    note ? h("div", { class: "muted" }, note) : null);
}

function machineTiles(context, metrics) {
  const load = metrics.load || {};
  const memory = metrics.mem || {};
  const disk = metrics.disk || {};
  return h("div", { class: "grid tiles" },
    tile("Load", fmt.decimal(load.load1, 2), `${fmt.num(load.cores)} cores`),
    tile("Memory free", fmt.gigabytes(memory.ram_avail_gb), `of ${fmt.gigabytes(memory.ram_total_gb)}`),
    tile("Disk free", fmt.gigabytes(disk.free_gb), disk.path || ""),
    tile("Agents", fmt.num(metrics.agents), "running now"));
}

/** A sensor is reporting, switched off by choice, or present and silent. Never invisible. */
function sensorTiles(context, metrics) {
  const features = context.features;
  const out = [];
  if (!features.gpu) {
    out.push(tile("Graphics card", "Not configured",
      "Power mode has no signal from it and stays on full. Set FLEET_NVIDIA_SMI to switch it on.", "pause"));
  } else if (!metrics.gpu) {
    out.push(tile("Graphics card", "No answer",
      "The sensor is configured but returned nothing on the last read.", "fail"));
  } else {
    out.push(tile("Graphics card",
      `${fmt.decimal(metrics.gpu.temp_c, 0)} C`,
      `${fmt.percent(metrics.gpu.util_pct)} busy, ${metrics.gpu.name || "unnamed card"}`, "done"));
  }
  if (!features.cpu_temp) {
    out.push(tile("Processor temperature", "Not configured",
      "No temperature sensor is enabled on this machine.", "pause"));
  } else if (metrics.cpu_temp_c == null) {
    out.push(tile("Processor temperature", "No answer",
      metrics.sensors_unavailable ? "The sensor package is not installed." : "The sensor returned nothing.", "fail"));
  } else {
    out.push(tile("Processor temperature", `${fmt.decimal(metrics.cpu_temp_c, 0)} C`,
      metrics.cpu_temp_source || "", "done"));
  }
  return h("div", { class: "grid tiles" }, out);
}

function powerControl(context) {
  if (!context.features.slice) return null;
  const resource = context.watch("/api/mode");
  return card({ class: "card-pad", key: "power", "data-write": "" },
    h("div", { class: "section-head" }, h("h2", null, "Power")),
    panel(resource, {
      loading: () => skeletonStack(3),
      ready: (mode) => [
        h("p", { class: "muted", key: "now" },
          `The setting is ${labelFor(mode.setting)}. Right now the agents are on ${labelFor(mode.effective)}.`),
        h("div", { class: "grid tiles", key: "choices" }, POWER.map(([id, label, line]) => h("button", {
          key: id,
          class: "choice",
          "aria-pressed": String(mode.setting === id),
          disabled: access.writable ? null : true,
          onclick: async () => {
            try {
              await apiPost("/api/mode", { mode: id });
              toast(`Power is now ${label}.`);
              context.refresh("/api/mode");
            } catch (error) {
              toast("The power setting was not changed.", "bad");
            }
          },
        },
          h("b", null, label),
          h("div", { class: "muted" }, line)))),
        access.writable ? null : h("p", { class: "readonly-note", key: "ro" },
          access.reason || "This dashboard is read-only."),
      ],
    }));
}

function labelFor(id) {
  const found = POWER.find((row) => row[0] === id);
  return found ? found[1] : id || "unknown";
}

function sweepTile(context) {
  const resource = context.watch("/api/sweep");
  const data = resource.data;
  if (!data) return tile("Sweep", "not known", "waiting for the machine");
  if (!data.enabled) {
    return tile("Sweep", "Off",
      "Dead worktrees are never cleared away on their own on this machine.", "pause");
  }
  return tile("Sweep",
    data.secs_left == null ? "Scheduled" : `in ${fmt.duration(data.secs_left)}`,
    data.result && data.result !== "success" ? `last run: ${data.result}` : "clears dead worktrees",
    data.result && data.result !== "success" ? "fail" : "done");
}

function facts(context) {
  const config = context.config;
  const version = context.res("/api/version").data || {};
  return card({ class: "card-pad", key: "facts" },
    h("div", { class: "section-head" }, h("h2", null, "This dashboard")),
    h("dl", { class: "kv" },
      h("dt", null, "Product"), h("dd", null, config.title || "murmur"),
      h("dt", null, "Version"), h("dd", null, config.version || version.v || "unknown"),
      h("dt", null, "Reading"), h("dd", null, access.loopback
        ? "Open to anything on this machine, because the server is bound to the loopback address."
        : "Open only to a request that carries the dashboard token, because the server is bound to the network."),
      h("dt", null, "Writing"), h("dd", null, access.writable
        ? "This page holds the write token, so it can send a message and register a project."
        : access.reason || "This page has no write token, so every form here is switched off.")));
}

function prerequisites(context) {
  const resource = context.res("/api/health");
  return card({ key: "checks" },
    h("div", { class: "card-pad" }, h("div", { class: "section-head" }, h("h2", null, "Prerequisites"))),
    panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(5)),
      isEmpty: (data) => !list(data.checks).length,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: "The server does not report its prerequisites",
        body: "The page and the server are different versions, so this table has nothing to show.",
        command: "fleet update && fleet dash --restart",
      })),
      ready: (data) => h("div", { class: "tablewrap" },
        h("table", null,
          h("thead", null, h("tr", null,
            h("th", null, "Tool"),
            h("th", null, "State"),
            h("th", null, "What it means"),
            h("th", null, "Fix"))),
          h("tbody", null, list(data.checks).map((check) => h("tr", { key: check.id },
            h("td", null, check.label || check.id),
            h("td", null, pill(HEALTH_MEANING[check.state] || "pause", HEALTH_WORD[check.state] || check.state, "")),
            h("td", { class: "wrap" }, check.detail || ""),
            h("td", { class: "mono" }, check.fix || "none needed")))))),
    }));
}

export default {
  id: "system",
  title: "System",
  needs: ["/api/health", "/api/metrics"],
  badge(context) {
    const checks = list((context.res("/api/health").data || {}).checks);
    const open = checks.filter((check) => check.state === "missing" || check.state === "error").length;
    return open || "";
  },
  render(context) {
    const metrics = context.res("/api/metrics");
    return [
      h("section", { class: "section", key: "machine" },
        h("div", { class: "section-head" }, h("h2", null, "The machine")),
        panel(metrics, {
          loading: () => h("div", { class: "grid tiles" },
            [0, 1, 2, 3].map((index) => card({ class: "card-pad", key: `sk${index}` }, skeletonStack(2)))),
          ready: (data) => [
            machineTiles(context, data),
            h("div", { class: "gap-sm", key: "gap" }),
            sensorTiles(context, data),
          ],
        })),
      h("section", { class: "section", key: "care" },
        h("div", { class: "section-head" }, h("h2", null, "Care and housekeeping")),
        h("div", { class: "grid tiles" }, sweepTile(context))),
      powerControl(context),
      h("div", { class: "gap", key: "gap2" }),
      facts(context),
      h("div", { class: "gap", key: "gap3" }),
      prerequisites(context),
    ];
  },
};

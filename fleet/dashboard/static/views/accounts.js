/* Accounts: how much subscription is left, and which engines this farm may use.
   Every limit window the server returns is drawn and labelled by its own name. This page
   knows nothing about any particular vendor's windows, and must not learn. */

import { h, card, panel, emptyState, skeletonStack, pill, widthStyle } from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { list } from "../core/api.js";
import { tone } from "../core/identity.js";

/** Every window, in the order the server gave them: the two named ones, then the scoped ones. */
export function windows(account) {
  const out = [];
  if (account.session != null || account.session_resets) {
    out.push({ name: "session", percent: account.session, resets: account.session_resets });
  }
  if (account.weekly != null || account.weekly_resets) {
    out.push({ name: "weekly", percent: account.weekly, resets: account.weekly_resets });
  }
  for (const scoped of list(account.scoped)) {
    out.push({ name: scoped.label, percent: scoped.percent, resets: scoped.resets });
  }
  return out;
}

function severity(percent) {
  if (percent == null) return "";
  if (percent >= 95) return "bad";
  if (percent >= 70) return "warn";
  return "";
}

function accountCard(account) {
  const rows = windows(account);
  return card({ class: "card-pad tile", key: account.name },
    h("div", { class: "label" },
      h("b", null, account.label || account.name),
      account.engine ? h("span", { class: "tag" }, account.engine) : null),
    account.stale_error
      ? h("p", { class: "readonly-note" },
        `These numbers are from ${fmt.ago(account.read_at)} and have not refreshed: ${account.stale_error}.`)
      : null,
    rows.length
      ? h("div", { class: "limits" }, rows.map((row) => h("div", { class: "limit", key: row.name },
        h("span", { class: "lname" }, row.name),
        h("span", { class: `bar ${severity(row.percent) === "bad" ? "fail" : severity(row.percent) === "warn" ? "wait" : ""}`.trim() },
          h("i", { style: widthStyle(row.percent) })),
        h("span", { class: `lpct ${severity(row.percent)}`.trim(), "data-flash": "" },
          `${fmt.percent(row.percent)} ${row.resets ? fmt.until(row.resets) : ""}`.trim()))))
      : h("p", { class: "muted" }, "No window has reported a number yet."),
    account.limit_reached ? pill("fail", "Out of room", "") : null);
}

/* An engine's glyph comes from the server. A missing one is written out as the engine name,
   never as a vendor logo drawn into this page, and its colour is one of the page's own
   twelve picked by what the server sent, never the value the server sent. */
function engineGlyph(model) {
  const written = [...String(model.glyph || model.icon || "").trim()].slice(0, 2).join("");
  return h("span", { class: `glyph mark-${tone(model.color || model.id || "")}` },
    written || String(model.id || "?").slice(0, 2).toUpperCase());
}

function modelCard(model) {
  const health = model.health === "ok" ? "done" : model.health === "fail" ? "fail" : "pause";
  const healthWord = model.health === "ok"
    ? "Healthy"
    : model.health === "fail" ? (model.health_detail || "Not answering") : "Not tested";
  return card({ class: "card-pad tile", key: model.id },
    h("div", { class: "label" },
      engineGlyph(model),
      h("b", null, model.label || model.id),
      h("div", { class: "spacer" }),
      pill(model.enabled ? "run" : "pause", model.enabled ? "On" : "Off", "")),
    h("div", { class: "muted mono" }, `--engine ${model.id}`),
    model.role ? h("div", { class: "muted" }, model.role) : null,
    model.models ? h("div", { class: "muted" }, String(model.models)) : null,
    h("div", { class: "label" }, pill(health, healthWord, model.health_detail || "")),
    model.limits ? h("div", { class: "muted" }, String(model.limits)) : null);
}

export default {
  id: "accounts",
  title: "Accounts",
  needs: ["/api/accounts", "/api/models"],
  render(context) {
    const accounts = context.res("/api/accounts");
    const models = context.res("/api/models");
    return [
      h("section", { class: "section", key: "accounts" },
        h("div", { class: "section-head" }, h("h2", null, "Subscriptions")),
        panel(accounts, {
          loading: () => h("div", { class: "grid cards" },
            [0, 1].map((index) => card({ class: "card-pad", key: `sk${index}` }, skeletonStack(3)))),
          isEmpty: (data) => !list(data.accounts).length,
          empty: () => emptyState({
            title: "No accounts registered",
            body: "An account is the subscription an agent spends while it works.",
            command: "fleet accounts add <name>",
          }),
          ready: (data) => h("div", { class: "grid cards" }, list(data.accounts).map(accountCard)),
        })),
      h("section", { class: "section", key: "models" },
        h("div", { class: "section-head" }, h("h2", null, "Engines")),
        panel(models, {
          loading: () => h("div", { class: "grid cards" },
            [0, 1, 2].map((index) => card({ class: "card-pad", key: `skm${index}` }, skeletonStack(3)))),
          isEmpty: (data) => !list(data).length,
          empty: () => emptyState({
            title: "No engines registered",
            body: "An engine is the command an agent runs. Register one to spawn with it.",
            command: "fleet models",
          }),
          ready: (data) => h("div", { class: "grid cards" }, list(data).map(modelCard)),
        })),
    ];
  },
};

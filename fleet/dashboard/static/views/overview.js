/* Overview answers one question: what needs me now. Everything here is a summary with a way
   into the tab that owns it. Nothing is shown here that cannot be opened somewhere else. */

import { h, card, section, panel, emptyState, skeletonStack, agentMeaning, MEANINGS } from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { list } from "../core/api.js";

const MEANING_ORDER = ["run", "wait", "fail", "done"];

function checklistItems(health) {
  return list(health && health.checks);
}

function unfinished(health) {
  return checklistItems(health).filter((check) => check.state === "missing" || check.state === "error");
}

function setupChecklist(health) {
  const open = unfinished(health);
  return card({ class: "card-pad", key: "setup" },
    h("div", { class: "section-head" },
      h("h2", null, "Finish setting up"),
      h("div", { class: "spacer" }),
      h("span", { class: "muted" }, `${open.length} of ${checklistItems(health).length} still open`)),
    h("ul", { class: "checklist" }, open.map((check) => h("li", { key: check.id },
      h("span", { class: `mark-state ${check.state}` }),
      h("div", null,
        h("div", { class: "title" }, check.label),
        check.detail ? h("div", { class: "detail" }, check.detail) : null,
        check.fix ? h("code", { class: "cmd" }, check.fix) : null)))));
}

function firstAgentCommands(projects) {
  const project = (projects || [])[0];
  const name = project ? project.name : "<project>";
  return [
    project ? null : "fleet add-project --name <project> --repo <owner>/<repo>",
    `fleet spawn --project ${name} --lane first --task "the first thing you want done"`,
    "fleet status",
  ].filter(Boolean);
}

function emptyFarm(context) {
  const health = context.res("/api/health").data;
  const projects = list(context.res("/api/projects").data);
  return [
    checklistItems(health).length && unfinished(health).length ? setupChecklist(health) : null,
    card({ class: "card-pad", key: "first" },
      h("h2", null, "No agents yet"),
      h("p", { class: "muted" },
        "This farm has never run one. These three commands produce the first agent and show it here."),
      h("div", { class: "stack" },
        firstAgentCommands(projects).map((command, index) =>
          h("code", { class: "cmd", key: `cmd${index}` }, command)))),
  ];
}

function statusCard(context) {
  const resource = context.res("/api/fleet");
  return card({ class: "card-pad", key: "agents" },
    h("div", { class: "section-head" },
      h("h2", null, "Agents"),
      h("div", { class: "spacer" }),
      h("a", { href: "#/agents" }, "Open")),
    // Four confident zeros while the farm is still being read say something that is not true.
    panel(resource, {
      loading: () => h("div", { class: "grid tiles" }, MEANING_ORDER.map((key) => h("div", {
        class: "metric",
        key,
      },
        h("span", { class: "label" }, key === "done" ? "Done today" : MEANINGS[key].label),
        h("div", { class: "skeleton value" })))),
      ready: (data) => {
        const counts = countByMeaning(list(data));
        return h("div", { class: "grid tiles" }, MEANING_ORDER.map((key) => h("a", {
          key,
          class: "metric",
          href: `#/agents?status=${key}`,
        },
          h("span", { class: "label" }, key === "done" ? "Done today" : MEANINGS[key].label),
          h("span", { class: "value", "data-flash": "" }, String(counts.get(key))))));
      },
    }));
}

function countByMeaning(rows) {
  const counts = new Map(MEANING_ORDER.map((key) => [key, 0]));
  const dayAgo = Date.now() / 1000 - 86400;
  for (const row of rows) {
    const meaning = agentMeaning(row.status);
    if (meaning === "done" && (fmt.seconds(row.updated_at || row.started_at) || 0) < dayAgo) continue;
    if (counts.has(meaning)) counts.set(meaning, counts.get(meaning) + 1);
  }
  return counts;
}

function queueCard(context) {
  const resource = context.res("/api/ci");
  return card({ class: "card-pad", key: "queue" },
    h("div", { class: "section-head" },
      h("h2", null, "Queue"),
      h("div", { class: "spacer" }),
      h("a", { href: "#/queue" }, "Open")),
    panel(resource, {
      loading: () => skeletonStack(2),
      isEmpty: (data) => !list(data.running).length && !list(data.queued).length,
      /* A quiet queue is a state, not a gap. It says so, and it says how many finished runs
         are waiting to be read, so the Open link above has something behind it. */
      empty: (data) => {
        const finished = list(data && data.recent).length;
        return h("div", { class: "metric" },
          h("span", { class: "label" }, "Nothing is being verified right now."),
          h("span", { class: "value sm", "data-flash": "" },
            finished ? `${finished} finished ${finished === 1 ? "run" : "runs"}` : "no finished run yet"),
          h("span", { class: "muted" }, finished
            ? "Open the queue to read what they decided."
            : "A change sent here shows its stages as they run."));
      },
      ready: (data) => {
        const head = list(data.running)[0] || list(data.queued)[0];
        return h("div", { class: "metric" },
          h("span", { class: "label" }, `${list(data.running).length} running, ${list(data.queued).length} waiting`),
          h("span", { class: "value sm" }, head ? `${head.project || "change"} ${head.pr ? `#${head.pr}` : ""}` : ""),
          head ? h("span", { class: "muted" }, fmt.shorten(head.branch || "", 48)) : null);
      },
    }));
}

function healthCard(context) {
  const resource = context.res("/api/metrics");
  return card({ class: "card-pad", key: "machine" },
    h("div", { class: "section-head" },
      h("h2", null, "Machine"),
      h("div", { class: "spacer" }),
      h("a", { href: "#/system" }, "Open")),
    panel(resource, {
      loading: () => skeletonStack(2),
      ready: (data) => h("div", { class: "grid tiles" },
        tile("Load", data.load ? fmt.decimal(data.load.load1, 2) : null),
        tile("Memory free", data.mem ? fmt.gigabytes(data.mem.ram_avail_gb) : null),
        tile("Disk free", data.disk ? fmt.gigabytes(data.disk.free_gb) : null),
        tile("Agents", fmt.num(data.agents))),
    }));
}

function tile(label, value) {
  return h("div", { class: "metric", key: label },
    h("span", { class: "label" }, label),
    h("span", { class: "value sm", "data-flash": "" }, value == null ? "not known" : value));
}

function accountsCard(context) {
  const resource = context.res("/api/accounts");
  return card({ class: "card-pad", key: "accounts" },
    h("div", { class: "section-head" },
      h("h2", null, "Least room left"),
      h("div", { class: "spacer" }),
      h("a", { href: "#/accounts" }, "Open")),
    panel(resource, {
      loading: () => skeletonStack(2),
      isEmpty: (data) => !list(data.accounts).length,
      empty: () => emptyState({
        title: "No accounts registered",
        body: "An account is a subscription the agents spend. Register one to see how much is left.",
        command: "fleet models",
      }),
      ready: (data) => {
        let worst = null;
        for (const account of list(data.accounts)) {
          for (const [name, value] of windowsOf(account)) {
            if (value == null) continue;
            if (!worst || value > worst.value) worst = { account, name, value };
          }
        }
        if (!worst) return h("p", { class: "muted" }, "No limit window has reported a number yet.");
        return h("div", { class: "metric" },
          h("span", { class: "label" }, `${worst.account.label || worst.account.name}, ${worst.name}`),
          h("span", { class: "value", "data-flash": "" }, fmt.percent(worst.value)),
          h("span", { class: "muted" }, "used in this window"));
      },
    }));
}

/** Every window the server returns, labelled by its own name. No window is special here. */
export function windowsOf(account) {
  const out = [];
  if (account.session != null) out.push(["session", account.session]);
  if (account.weekly != null) out.push(["weekly", account.weekly]);
  for (const scoped of list(account.scoped)) {
    if (scoped.label) out.push([scoped.label, scoped.percent]);
  }
  return out;
}

/* The office answers an envelope with the events under their own name, and each event
   carries the time as the office wrote it. A number is counted from; a line is shown. */
function events(data) {
  // The office feed carries claims, sessions and notes as well as messages. This card is about
  // what the agents said to each other, so it shows messages and leaves the rest to the Mail tab.
  return list(data && data.events).filter((item) => (item.kind || "mail") === "mail");
}

function eventTime(value) {
  if (value == null || value === "") return "recently";
  if (typeof value === "number") return fmt.ago(value);
  return Number.isNaN(Date.parse(value)) ? String(value) : fmt.ago(value);
}

function mailCard(context) {
  const resource = context.res("/api/mail/feed?hours=24");
  return card({ key: "mail" },
    h("div", { class: "card-pad" },
      h("div", { class: "section-head" },
        h("h2", null, "Last said"),
        h("div", { class: "spacer" }),
        h("a", { href: "#/mail" }, "Open"))),
    panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(3)),
      isEmpty: (data) => !events(data).length,
      empty: () => h("div", { class: "card-pad" },
        h("p", { class: "muted" }, "The agents have not said anything in the last day.")),
      ready: (data) => h("div", { class: "feed" }, events(data).slice(-5).reverse().map((item, index) =>
        h("div", { class: "item", key: `feed${index}` },
          h("span", { class: "at" }, eventTime(item.at)),
          h("span", null, fmt.shorten(item.text, 120))))),
    }));
}

export default {
  id: "overview",
  title: "Overview",
  needs: ["/api/fleet", "/api/ci", "/api/accounts", "/api/projects", "/api/mail/feed?hours=24"],
  render(context) {
    const fleet = context.res("/api/fleet");
    const health = context.res("/api/health").data;
    const rows = list(fleet.data);
    // An empty farm and a farm that will not answer look the same in a length, and they
    // are not the same thing: only a real empty list means nobody has ever run a lane.
    if (fleet.everLoaded && Array.isArray(fleet.data) && rows.length === 0) return emptyFarm(context);
    const open = unfinished(health);
    return [
      open.length ? setupChecklist(health) : null,
      section("What is happening", null,
        h("div", { class: "grid two" },
          statusCard(context),
          queueCard(context))),
      section("The machine and the money", null,
        h("div", { class: "grid two" },
          healthCard(context),
          accountsCard(context))),
      section("The office", null, mailCard(context)),
    ];
  },
};

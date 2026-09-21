/* Mail: what the agents said to each other. Three panes, newest at the bottom, and a
   timeline that replaces the thread with the whole office as one feed. The unread count is
   the reader's own business: the marker for when they last looked lives in this browser,
   and the counting is done from the list of mailboxes the tab already reads. */

import {
  h, card, panel, emptyState, skeletonStack, toast, activate,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access } from "../core/api.js";
import { mark } from "../core/identity.js";

/* How much of a thread is drawn at once. A mailbox with two thousand messages in it is a
   mailbox nobody reads from the top. */
const LAST_MESSAGES = 100;

const local = { box: "", timeline: false, seen: readSeen(), watched: "", showAll: false };

function readSeen() {
  try {
    return JSON.parse(localStorage.getItem("murmur.mail.seen") || "{}");
  } catch (error) {
    return {};
  }
}

function writeSeen() {
  try {
    localStorage.setItem("murmur.mail.seen", JSON.stringify(local.seen));
  } catch (error) { /* the counts simply restart next time */ }
}

/* Every mail route answers the same envelope: when it was read, whether the reading is old,
   what went wrong if anything, and the list under its own name. Reading the list by name in
   one place means a route that adds a field cannot quietly empty a pane. */
function listOf(data, key) {
  if (!data) return [];
  if (Array.isArray(data[key])) return data[key];
  return [];
}

/** A time from the office is either a number we can count from, or a line it already wrote. */
function when(value) {
  if (value == null || value === "") return "";
  if (typeof value === "number") return fmt.ago(value);
  return Number.isNaN(Date.parse(value)) ? String(value) : fmt.ago(value);
}

function envelopeNote(data) {
  if (!data || Array.isArray(data)) return null;
  const lines = [];
  if (data.stale_since) {
    lines.push(`The office last answered ${when(data.stale_since)}. These are the messages it gave us then.`);
  }
  if (data.error) lines.push(data.error);
  return lines.length ? h("p", { class: "readonly-note" }, lines.join(" ")) : null;
}

function threadPath(box, since) {
  const query = new URLSearchParams({ box });
  if (since) query.set("since", since);
  return `/api/mail/thread?${query.toString()}`;
}

/* ---------------------------------------------------------- the boxes */

/* How many messages a box has taken that this reader has not seen. The boxes list already
   carries the count for the last day and the time of the newest message, so this is answered
   from the one request the tab already makes. Asking every box for its own thread meant sixty
   reads of the head office every fifteen seconds on a farm with sixty code names. */
function newCount(box) {
  const day = box.count_24h || 0;
  const seen = local.seen[box.name];
  if (!seen) return day;
  const last = fmt.seconds(box.last_at);
  const visited = fmt.seconds(seen);
  if (last == null || visited == null) return 0;
  return last > visited ? day : 0;
}

function boxPane(context, boxes) {
  return card({ key: "boxes" },
    h("ul", { class: "boxlist", role: "listbox", "aria-label": "Mailboxes" }, boxes.map((box) => {
      const count = box.name === local.box ? 0 : newCount(box);
      return h("li", {
        key: box.name,
        role: "option",
        tabindex: "0",
        "aria-selected": String(box.name === local.box),
        onclick: () => select(box.name, context),
        onkeydown: activate(() => select(box.name, context)),
      },
        h("span", null, box.name),
        count ? h("span", { class: "new" }, String(count)) : null);
    })));
}

function select(name, context) {
  local.box = name;
  local.showAll = false;
  local.seen[name] = new Date().toISOString();
  writeSeen();
  context.go("mail", { box: name });
}

/* --------------------------------------------------------- the thread */

function threadPane(context) {
  if (!local.box) {
    return card({ class: "card-pad", key: "thread" },
      emptyState({
        title: "Pick a mailbox",
        body: "Each mailbox is one agent. The thread is what was said to it, oldest first.",
        command: "",
      }));
  }
  const resource = watchOne(context, threadPath(local.box, ""));
  return card({ key: "thread" },
    panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(4)),
      isEmpty: (data) => listOf(data, "messages").length === 0,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: `Nothing has been said to ${local.box}`,
        body: "A message here is how one agent tells another what it found.",
        command: `hq msg ${local.box} "your message"`,
      })),
      ready: (data) => [
        envelopeNote(data),
        h("div", { class: "thread", key: "messages" }, [
          earlier(context, listOf(data, "messages").length),
          ...drawn(listOf(data, "messages")).map((message, index) => {
          const identity = mark(message.sender);
          return h("div", { class: "msg", key: `m${index}:${message.created_at || message.at}` },
            h("div", { class: "who" },
              h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph),
              h("b", null, message.sender || "unknown"),
              h("span", { class: "at" }, when(message.created_at ?? message.at))),
            h("div", { class: "body" }, message.text || ""));
        })]),
        composer(context),
      ],
    }));
}

/* Exactly one thread is read at a time: the one on the screen. Leaving the others in the tick
   is how a badge turns into a read of the head office per mailbox per fifteen seconds. */
function watchOne(context, path) {
  if (local.watched && local.watched !== path) context.drop(local.watched);
  local.watched = path;
  return context.watch(path);
}

function drawn(messages) {
  return local.showAll ? messages : messages.slice(-LAST_MESSAGES);
}

function earlier(context, total) {
  const hidden = local.showAll ? 0 : Math.max(0, total - LAST_MESSAGES);
  if (!hidden) return null;
  return h("button", {
    key: "earlier",
    class: "ghost-button",
    onclick: () => {
      local.showAll = true;
      context.paint();
    },
  }, `Show the ${hidden} earlier messages`);
}

function composer(context) {
  const boxes = listOf(context.res("/api/mail/boxes").data, "boxes").map((box) => box.name);
  const allowed = access.writable;
  const recipients = ["all", ...boxes.filter((name) => name !== "all")];
  return h("div", { class: "composer", key: "composer", "data-write": "" },
    h("div", { class: "row" },
      h("select", { id: "mailTo", disabled: allowed ? null : true },
        recipients.map((name) => h("option", {
          key: name,
          value: name,
          selected: name === (local.box || "all"),
        }, name))),
      h("span", { class: "readonly-note" }, allowed ? "" : access.reason || "This dashboard is read-only.")),
    h("textarea", { id: "mailText", placeholder: allowed ? "Write to the office" : "", disabled: allowed ? null : true }),
    h("div", { class: "row" },
      h("button", {
        class: "button primary",
        disabled: allowed ? null : true,
        onclick: async () => {
          const field = document.getElementById("mailText");
          const to = document.getElementById("mailTo").value;
          const text = (field.value || "").trim();
          if (!text) return;
          try {
            const answer = await apiPost("/api/mail/send", { to, text });
            field.value = "";
            toast(answer && answer.detail ? answer.detail : `Sent to ${to}.`);
            context.refresh(threadPath(local.box, ""));
          } catch (error) {
            toast(error && error.status === 503
              ? "The office is still loading, try again in a moment."
              : "The office did not take that message.", "bad");
          }
        },
      }, "Send")));
}

/* -------------------------------------------------------- the timeline */

function timelinePane(context) {
  const resource = watchOne(context, "/api/mail/feed?hours=24");
  return card({ key: "timeline" },
    panel(resource, {
      loading: () => h("div", { class: "card-pad" }, skeletonStack(6)),
      isEmpty: (data) => listOf(data, "events").length === 0,
      empty: () => h("div", { class: "card-pad" }, emptyState({
        title: "The office has been quiet for a day",
        body: "The timeline shows mail, branch claims and sessions together.",
        command: "hq feed",
      })),
      ready: (data) => [
        envelopeNote(data),
        h("div", { class: "feed", key: "items" }, listOf(data, "events").slice().reverse().map((item, index) =>
          h("div", { class: "item", key: `t${index}` },
            h("span", { class: "at" }, item.at_label || when(item.at) || "recently"),
            h("span", { class: "tag" }, item.kind || "mail"),
            h("span", null, item.text || "")))),
      ],
    }));
}

/* ------------------------------------------------------------- who */

function whoPane(context) {
  const resource = context.watch("/api/mail/who");
  return card({ class: "card-pad mail-who", key: "who" },
    h("div", { class: "section-head" }, h("h2", null, "In the office now")),
    panel(resource, {
      loading: () => skeletonStack(3),
      isEmpty: (data) => listOf(data, "sessions").length === 0,
      empty: () => h("p", { class: "muted" }, "Nobody has said hello today."),
      ready: (data) => h("div", { class: "stack" }, listOf(data, "sessions").map((person) => {
        const identity = mark(person.name);
        return h("div", { class: "msg", key: person.name },
          h("div", { class: "who" },
            h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph),
            h("b", null, person.name),
            h("span", { class: "at" }, person.age_hours == null
              ? when(person.since) || person.state || ""
              : `${fmt.duration(person.age_hours * 3600)} ago`)),
          person.state === "stale" ? h("span", { class: "tag" }, "not heard from lately") : null,
          h("div", { class: "muted" }, fmt.shorten(person.task || "", 80)));
      })),
    }));
}

/* ---------------------------------------------------------------- view */

export default {
  id: "mail",
  title: "Mail",
  needs: ["/api/mail/boxes"],
  render(context) {
    const resource = context.res("/api/mail/boxes");
    const data = resource.data;
    if (data && data.unavailable) {
      return emptyState({ title: data.unavailable, body: "", command: data.fix });
    }
    const boxes = listOf(data, "boxes");
    const wanted = context.params.get("box");
    if (wanted && wanted !== local.box) {
      local.box = wanted;
      local.seen[wanted] = new Date().toISOString();
      writeSeen();
    }
    if (!local.box && boxes.length) local.box = boxes[0].name;
    return [
      h("div", { class: "section-head", key: "controls" },
        h("div", { class: "spacer" }),
        h("div", { class: "segmented" },
          h("button", {
            "aria-pressed": String(!local.timeline),
            onclick: () => {
              local.timeline = false;
              context.paint();
            },
          }, "Thread"),
          h("button", {
            "aria-pressed": String(local.timeline),
            onclick: () => {
              local.timeline = true;
              context.paint();
            },
          }, "Timeline"))),
      panel(resource, {
        loading: () => h("div", { class: "mail-panes" },
          card({ class: "card-pad", key: "s1" }, skeletonStack(5)),
          card({ class: "card-pad", key: "s2" }, skeletonStack(6))),
        isEmpty: () => boxes.length === 0,
        empty: () => emptyState({
          title: "No mailboxes yet",
          body: "A mailbox appears when an agent says hello to the head office.",
          command: "hq hello <name> --task \"what you are doing\"",
        }),
        ready: () => h("div", { class: "mail-panes" },
          boxPane(context, boxes),
          local.timeline ? timelinePane(context) : threadPane(context),
          whoPane(context)),
      }),
    ];
  },
};

/* Mail: what the agents said to each other, as three fixed panes. The page itself never
   scrolls; each pane scrolls inside its own frame, so the composer and the two headers stay
   where the reader left them. Every word on screen is a word a person uses: conversation,
   message, the office, here now. The reader's own unread marker lives in this browser. */

import {
  h, card, panel, emptyState, skeletonStack, toast, activate,
} from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, serverReason } from "../core/api.js";
import { mark } from "../core/identity.js";

/* How much of a conversation is drawn at once. A conversation with two thousand messages in
   it is one nobody reads from the top. */
const LAST_MESSAGES = 100;

/* How many conversations are listed before the reader is asked for the rest. A farm with
   twenty five code names is a list nobody reads to the bottom. */
const FIRST_NAMES = 12;

/* How long an echo of a message this page just sent is kept if the office never shows it. */
const ECHO_LIFE = 600;

const local = {
  open: "",
  timeline: false,
  seen: readSeen(),
  watched: "",
  showAll: false,
  allNames: false,
  search: "",
  peopleOpen: false,
  quietOpen: false,
  sending: false,
  echoes: [],
  bottomAt: "",
};

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

/** The name as a person reads it. The farm's catch-all conversation is everybody. */
function nameOf(conversation) {
  return conversation === "all" ? "Everyone" : conversation;
}

/* The one sentence that says a reading is old, in the reader's own terms. The office is the
   thing that answered, so the office is what the sentence is about. What the kept copy holds
   comes from the pane that draws it: the People pane lists people, not messages, and a
   sentence about messages over a list of names is a sentence about the wrong thing. */
function officeNote(data, held = "This is what it told us then.") {
  if (!data || Array.isArray(data)) return null;
  const lines = [];
  if (data.stale_since) {
    lines.push(`The office last answered ${when(data.stale_since)}. ${held}`);
  }
  if (data.error) lines.push(data.error);
  return lines.length ? h("p", { class: "readonly-note" }, lines.join(" ")) : null;
}

function threadPath(name) {
  return `/api/mail/thread?${new URLSearchParams({ box: name }).toString()}`;
}

/* Exactly one conversation is read at a time: the one on the screen. Leaving the others in
   the tick is a read of the office per name per fifteen seconds. */
function watchOne(context, path) {
  if (local.watched && local.watched !== path) context.drop(local.watched);
  local.watched = path;
  return context.watch(path);
}

/* ------------------------------------------------- the conversations pane */

/* How many messages a conversation has taken that this reader has not seen. The list already
   carries the count for the last day and the time of the newest message, so this is answered
   from the one request the tab already makes. */
function newCount(row) {
  const day = row.count_24h || 0;
  const seen = local.seen[row.name];
  if (!seen) return day;
  const last = fmt.seconds(row.last_at);
  const visited = fmt.seconds(seen);
  if (last == null || visited == null) return 0;
  return last > visited ? day : 0;
}

/* One name, one conversation. The server folds two records of one name into one row; this is
   the belt, because a name drawn twice is a key drawn twice, and a reader who opens the
   second winston has no way to tell which half of the conversation they are looking at. */
function oneRowPerName(rows) {
  const out = [];
  const seen = new Set();
  for (const row of rows) {
    const name = row && row.name;
    if (!name || seen.has(name)) continue;
    seen.add(name);
    out.push(row);
  }
  return out;
}

/** Newest first, with the conversation everybody reads pinned to the top. */
function newestFirst(rows) {
  const pinned = rows.filter((row) => row.name === "all");
  const rest = rows.filter((row) => row.name !== "all");
  rest.sort((left, right) => (fmt.seconds(right.last_at) || 0) - (fmt.seconds(left.last_at) || 0));
  return [...pinned, ...rest];
}

function searched(rows) {
  const needle = local.search.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) => String(row.name).toLowerCase().includes(needle)
    || (row.name === "all" && "everyone".includes(needle)));
}

/** The names on screen: the first twelve, the open one, and the rest once asked for. */
function shownNames(rows) {
  if (local.allNames || rows.length <= FIRST_NAMES) return rows;
  const head = rows.slice(0, FIRST_NAMES);
  const open = rows.find((row) => row.name === local.open);
  return open && !head.includes(open) ? [...head, open] : head;
}

function conversationRow(row, context) {
  const count = row.name === local.open ? 0 : newCount(row);
  const identity = mark(row.name);
  return h("li", {
    key: row.name,
    role: "option",
    tabindex: "0",
    "aria-selected": String(row.name === local.open),
    "data-conversation": row.name,
    onclick: () => select(row.name, context),
    onkeydown: activate(() => select(row.name, context)),
  },
    h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph),
    h("span", { class: "who" },
      h("span", { class: "name" }, nameOf(row.name)),
      h("span", { class: "muted" }, row.name === "all"
        ? "every agent on this farm"
        : row.last_at ? `Last seen ${when(row.last_at)}` : "nothing said yet")),
    count ? h("span", { class: "new", title: "Unread since you last looked" }, String(count)) : null);
}

function conversationsPane(context, rows) {
  const shown = shownNames(searched(rows));
  return card({ class: "mail-pane conversations-pane", key: "conversations" },
    h("div", { class: "pane-head" },
      h("h2", null, "Conversations"),
      h("div", { class: "spacer" }),
      h("span", { class: "muted" }, String(rows.length))),
    h("div", { class: "pane-tools" },
      h("input", {
        id: "mailSearch",
        type: "search",
        class: "search",
        value: local.search,
        placeholder: "Find a name",
        "aria-label": "Find a conversation by name",
        oninput: (event) => {
          local.search = event.target.value;
          context.paint();
        },
      })),
    h("div", { class: "pane-scroll" },
      h("ul", { class: "conversations", role: "listbox", "aria-label": "Conversations" },
        shown.map((row) => conversationRow(row, context))),
      rows.length > FIRST_NAMES ? h("div", { class: "pane-more" },
        h("button", {
          class: "ghost-button small",
          "aria-expanded": String(local.allNames),
          onclick: () => {
            local.allNames = !local.allNames;
            context.paint();
          },
        }, local.allNames ? "Show fewer" : `Show all ${rows.length}`)) : null));
}

function select(name, context) {
  local.open = name;
  local.showAll = false;
  local.timeline = false;
  local.seen[name] = new Date().toISOString();
  writeSeen();
  context.go("mail", { to: name });
}

/* -------------------------------------------------------- the messages */

/** The day a message belongs to, written the way a person says it. */
function daySeparator(at, now = Date.now() / 1000) {
  const seconds = fmt.seconds(at);
  if (seconds == null) return "Earlier";
  const day = new Date(seconds * 1000);
  const today = new Date(now * 1000);
  const same = (one, other) => one.toDateString() === other.toDateString();
  if (same(day, today)) return "Today";
  const yesterday = new Date((now - 86400) * 1000);
  if (same(day, yesterday)) return "Yesterday";
  return day.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** A message this page sent a moment ago, until the office shows it back to us. */
function echoes(messages) {
  const now = Date.now() / 1000;
  local.echoes = local.echoes.filter((echo) => now - echo.at < ECHO_LIFE
    && !messages.some((message) => (message.text || "").trim() === echo.text));
  return local.echoes.filter((echo) => echo.to === local.open);
}

function messageRow(message, index) {
  const identity = mark(message.sender);
  return h("div", { class: "msg", key: `m${index}:${message.created_at || message.at}` },
    h("div", { class: "who" },
      h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph),
      h("b", null, message.sender || "unknown"),
      h("span", { class: "at" }, when(message.created_at ?? message.at))),
    h("div", { class: "body" }, message.text || ""));
}

function echoRow(echo, index) {
  const identity = mark("dashboard");
  return h("div", { class: "msg echo", key: `e${index}:${echo.at}`, "data-echo": echo.state },
    h("div", { class: "who" },
      h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph),
      h("b", null, "dashboard"),
      h("span", { class: "at" }, echo.state === "sending"
        ? "sending"
        : "sent, it will show here at the next refresh")),
    h("div", { class: "body" }, echo.text));
}

function drawn(messages) {
  return local.showAll ? messages : messages.slice(-LAST_MESSAGES);
}

function earlier(context, total) {
  const hidden = local.showAll ? 0 : Math.max(0, total - LAST_MESSAGES);
  if (!hidden) return null;
  return h("button", {
    key: "earlier",
    class: "ghost-button small",
    onclick: () => {
      local.showAll = true;
      context.paint();
    },
  }, `Show the ${hidden} earlier messages`);
}

/* Newest at the bottom means the bottom is where a reader starts. The pane is put there when
   the conversation is opened, and kept there while new messages arrive, unless the reader has
   scrolled up to read something: then it is theirs and nothing moves it. */
function keepAtBottom() {
  const conversation = local.open;
  setTimeout(() => {
    const pane = document.getElementById("mailThread");
    if (!pane || local.open !== conversation) return;
    const atBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 48;
    if (local.bottomAt === conversation && !atBottom) return;
    pane.scrollTop = pane.scrollHeight;
    local.bottomAt = conversation;
  }, 0);
}

/** The messages, oldest at the top and newest at the bottom, with a line between the days. */
function messages(context, data) {
  keepAtBottom();
  const all = listOf(data, "messages");
  const shown = drawn(all);
  const out = [officeNote(data, "These are the messages it gave us then."),
    earlier(context, all.length)];
  let day = "";
  shown.forEach((message, index) => {
    const label = daySeparator(message.created_at ?? message.at);
    if (label !== day) {
      day = label;
      out.push(h("div", { class: "day", key: `d${index}:${label}` }, label));
    }
    out.push(messageRow(message, index));
  });
  for (const [index, echo] of echoes(all).entries()) out.push(echoRow(echo, index));
  return out;
}

/* ----------------------------------------------------------- the office */

function timeline(context) {
  const resource = watchOne(context, "/api/mail/feed?hours=24");
  return panel(resource, {
    loading: () => skeletonStack(6),
    isEmpty: (data) => listOf(data, "events").length === 0,
    empty: () => emptyState({
      title: "The office has been quiet for a day",
      body: "This list holds everything the office did: messages, branches taken, agents arriving.",
      command: "",
    }),
    /* The route sends it newest first, which is the order it is read in. */
    ready: (data) => [
      officeNote(data, "This is what it had done by then."),
      h("div", { class: "feed", key: "items" }, listOf(data, "events").map((item, index) =>
        h("div", { class: "item", key: `t${index}` },
          h("span", { class: "at" }, item.at_label || when(item.at) || "recently"),
          h("span", { class: "tag" }, item.kind || "message"),
          h("span", null, item.text || "")))),
    ],
  });
}

/* ------------------------------------------------------------ the thread */

function lastSeen(rows) {
  const found = rows.find((row) => row.name === local.open);
  return found && found.last_at ? `Last seen ${when(found.last_at)}` : "";
}

function threadHead(context, rows, people) {
  const identity = mark(local.open);
  return h("div", { class: "pane-head thread-head" },
    h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph),
    h("h2", null, nameOf(local.open)),
    h("span", { class: "muted" }, lastSeen(rows)),
    h("div", { class: "spacer" }),
    h("button", {
      class: "ghost-button small people-count",
      "aria-pressed": String(local.peopleOpen),
      onclick: () => {
        local.peopleOpen = !local.peopleOpen;
        context.paint();
      },
    }, `Agents (${people})`),
    h("button", {
      class: "ghost-button small",
      "data-timeline": "",
      "aria-pressed": String(local.timeline),
      onclick: () => {
        local.timeline = !local.timeline;
        context.paint();
      },
    }, "Everything the office did"));
}

function threadPane(context, rows, people) {
  /* Exactly one of the two is read: the conversation, or the office's own list. Asking for
     both means each one drops the other from the tick, every drop makes the other due again,
     and the pane repaints its way into a request a page can never finish. */
  const resource = local.open && !local.timeline ? watchOne(context, threadPath(local.open)) : null;
  return card({ class: "mail-pane thread-pane", key: "thread" },
    threadHead(context, rows, people),
    h("div", { class: "pane-scroll thread", id: "mailThread" },
      local.timeline
        ? timeline(context)
        : panel(resource, {
          loading: () => skeletonStack(5),
          isEmpty: (data) => listOf(data, "messages").length === 0 && echoes([]).length === 0,
          empty: () => emptyState({
            title: `Nothing has been said to ${nameOf(local.open)} yet`,
            body: "A message here is how one agent tells another what it found. Write the first one below.",
            command: "",
          }),
          ready: (data) => messages(context, data),
        })),
    composer(context));
}

/* ---------------------------------------------------------- the composer */

function composer(context) {
  const allowed = access.writable;
  const to = local.open || "all";
  return h("div", { class: "composer", key: "composer", "data-write": "" },
    h("label", { class: "composer-label", for: "mailText" }, `Message to ${nameOf(to)}`),
    h("textarea", {
      id: "mailText",
      rows: "2",
      placeholder: allowed ? "What do you want to tell them" : "",
      disabled: allowed ? null : true,
    }),
    h("div", { class: "row" },
      h("button", {
        class: "button primary",
        id: "mailSend",
        disabled: allowed && !local.sending ? null : true,
        onclick: () => send(context, to),
      }, local.sending ? "Sending" : "Send"),
      h("span", { class: "readonly-note" }, allowed
        ? "Sent as dashboard, not as you"
        : access.reason || "This dashboard is read-only.")));
}

/* A message appears in the conversation the moment it is sent, and says so: sending, then
   sent. A failure leaves the text where it was, because retyping it is the reader's time. */
async function send(context, to) {
  const field = document.getElementById("mailText");
  const text = (field.value || "").trim();
  if (!text) return;
  const echo = { to, text, at: Date.now() / 1000, state: "sending" };
  local.echoes.push(echo);
  local.sending = true;
  context.paint();
  try {
    await apiPost("/api/mail/send", { to, text });
    field.value = "";
    echo.state = "sent";
    local.sending = false;
    context.paint();
    await context.refresh(threadPath(local.open));
  } catch (error) {
    local.echoes = local.echoes.filter((row) => row !== echo);
    local.sending = false;
    toast(serverReason(error)
      || (error && error.status === 503
        ? "The office is still loading, try again in a moment."
        : "The office did not take that message."), "bad");
    context.paint();
  }
}

/* ------------------------------------------------------------- people */

function personRow(person) {
  const identity = mark(person.name);
  return h("div", { class: "person", key: person.name },
    h("div", { class: "who" },
      h("span", { class: `glyph mark-${identity.tone}` }, identity.glyph),
      h("b", null, person.name),
      h("span", { class: "at" }, person.age_hours == null
        ? when(person.since)
        : `Last seen ${fmt.duration(person.age_hours * 3600)} ago`)),
    person.task ? h("div", { class: "muted" }, fmt.shorten(person.task, 80)) : null);
}

function peoplePane(context) {
  const resource = context.watch("/api/mail/who");
  return card({ class: `mail-pane people-pane${local.peopleOpen ? " open" : ""}`, key: "people" },
    h("div", { class: "pane-head" },
      h("h2", null, "Agents"),
      h("div", { class: "spacer" }),
      h("button", {
        class: "ghost-button small people-close",
        onclick: () => {
          local.peopleOpen = false;
          context.paint();
        },
      }, "Close")),
    h("div", { class: "pane-scroll" }, panel(resource, {
      loading: () => skeletonStack(3),
      isEmpty: (data) => listOf(data, "sessions").length === 0,
      empty: () => h("p", { class: "muted" }, "No agent has said hello today."),
      ready: (data) => {
        const sessions = listOf(data, "sessions");
        const here = sessions.filter((person) => person.state !== "stale");
        const quiet = sessions.filter((person) => person.state === "stale");
        return [
          officeNote(data, "These are the agents it knew about then."),
          h("h3", { key: "here" }, "Here now"),
          here.length ? here.map(personRow) : h("p", { class: "muted", key: "none" }, "No agent right now."),
          quiet.length ? h("button", {
            key: "quiet-toggle",
            class: "ghost-button small",
            "aria-expanded": String(local.quietOpen),
            onclick: () => {
              local.quietOpen = !local.quietOpen;
              context.paint();
            },
          }, `Not heard from lately (${quiet.length})`) : null,
          local.quietOpen ? quiet.map(personRow) : null,
        ];
      },
    })));
}

/* ---------------------------------------------------------------- view */

export default {
  id: "mail",
  title: "Mail",
  needs: ["/api/mail/boxes"],
  /* Three panes that hold themselves to the window. The page under them never scrolls. */
  fixed: true,
  render(context) {
    const resource = context.res("/api/mail/boxes");
    const data = resource.data;
    if (data && data.unavailable) {
      return emptyState({ title: data.unavailable, body: "", command: data.fix });
    }
    const rows = newestFirst(oneRowPerName(listOf(data, "boxes")));
    const wanted = context.params.get("to") || context.params.get("box");
    if (wanted && wanted !== local.open) {
      local.open = wanted;
      local.seen[wanted] = new Date().toISOString();
      writeSeen();
    }
    if (!local.open && rows.length) local.open = rows[0].name;
    const people = listOf(context.res("/api/mail/who").data, "sessions").length;
    return h("div", { class: "mail-root" }, panel(resource, {
      loading: () => h("div", { class: "mail-app" },
        card({ class: "mail-pane card-pad", key: "s1" }, skeletonStack(5)),
        card({ class: "mail-pane card-pad", key: "s2" }, skeletonStack(6)),
        card({ class: "mail-pane card-pad", key: "s3" }, skeletonStack(3))),
      isEmpty: () => rows.length === 0,
      empty: () => emptyState({
        title: "No conversation yet",
        body: "A conversation appears when an agent says hello to the office for the first time.",
        command: "",
      }),
      ready: () => h("div", { class: `mail-app${local.peopleOpen ? " people-open" : ""}` },
        conversationsPane(context, rows),
        h("label", { class: "convo-select field-label", key: "pick" },
          h("span", { class: "sr-only" }, "Conversation"),
          h("select", {
            onchange: (event) => select(event.target.value, context),
          }, rows.map((row) => h("option", {
            key: row.name, value: row.name, selected: row.name === local.open,
          }, nameOf(row.name))))),
        threadPane(context, rows, people),
        peoplePane(context)),
    }));
  },
};

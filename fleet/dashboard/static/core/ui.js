/* Rendering. h() describes a tree, render() updates a real one in place by key.
   Updating in place is the whole point: a 3-second tick must not move a scroll position,
   close a drawer, blow away half-typed text or flicker a row the reader is looking at.
   No DOM is touched while this module is imported, so the node check can import it. */

/* ------------------------------------------------------------------ h() */

export function h(tag, props, ...children) {
  const attrs = props && props.constructor === Object ? props : {};
  const rest = props && props.constructor === Object ? children : [props, ...children];
  return { tag, props: attrs, children: flatten(rest) };
}

function flatten(children) {
  const out = [];
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false || child === true || child === "") continue;
    out.push(typeof child === "object" ? child : { text: String(child) });
  }
  return out;
}

/** Raw SVG, for the seven navigation icons. Written by this page only, never by data. */
export function svg(markup, props = {}) {
  return { tag: "svg", props: { ...props, __svg: markup }, children: [] };
}

/* -------------------------------------------------------------- render */

const SVG_NS = "http://www.w3.org/2000/svg";

function keyFor(node, index) {
  if (node.text != null) return `t${index}`;
  if (node.props.key != null) return `k${node.props.key}`;
  return `p${index}:${node.tag}`;
}

export function render(parent, children) {
  const wanted = flatten([children]);
  const existing = new Map();
  for (const node of Array.from(parent.childNodes)) {
    if (node.__vkey == null) node.remove();
    else existing.set(node.__vkey, node);
  }
  const placed = [];
  const used = new Set();
  wanted.forEach((vnode, index) => {
    let key = keyFor(vnode, index);
    /* Two children under one key is a data accident, not a page bug: one head office can hold
       two mailboxes of one name. It used to strand a node all the same, because the map above
       keeps the last of them and the first is then neither matched nor removed. */
    while (used.has(key)) key = `${key}#${index}`;
    used.add(key);
    const found = existing.get(key);
    let element = found;
    const same = found && (vnode.text != null
      ? found.nodeType === 3
      : found.nodeType === 1 && found.localName === vnode.tag);
    if (!same) {
      /* A node under this key whose tag changed is REPLACED, never joined. Leaving it behind is
         how four skeletons ended up sitting above the four numbers they stood in for: the
         placeholder is a div, the value is a link, and both answer to the same key. */
      if (found) found.remove();
      element = create(vnode);
      element.__vkey = key;
    } else {
      patch(element, vnode);
    }
    placed.push(element);
  });
  for (const [key, node] of existing) if (!used.has(key)) node.remove();
  let after = null;
  for (let index = placed.length - 1; index >= 0; index -= 1) {
    const element = placed[index];
    if (element.parentNode !== parent || element.nextSibling !== after) {
      parent.insertBefore(element, after);
    }
    after = element;
  }
}

function create(vnode) {
  if (vnode.text != null) return document.createTextNode(vnode.text);
  const inSvg = vnode.tag === "svg";
  const element = inSvg
    ? document.createElementNS(SVG_NS, "svg")
    : document.createElement(vnode.tag);
  element.__props = {};
  patch(element, vnode);
  return element;
}

function patch(element, vnode) {
  if (vnode.text != null) {
    if (element.data !== vnode.text) {
      const parent = element.parentNode;
      element.data = vnode.text;
      if (parent && parent.dataset && parent.dataset.flash != null) flash(parent);
    }
    return;
  }
  const next = vnode.props;
  const previous = element.__props || {};
  element.__props = next;
  for (const name of Object.keys(previous)) {
    if (!(name in next) && name !== "key" && !name.startsWith("__")) applyProp(element, name, null);
  }
  for (const [name, value] of Object.entries(next)) {
    if (name === "key") continue;
    if (name === "__svg") {
      if (element.innerHTML !== value) element.innerHTML = value;
      continue;
    }
    if (previous[name] === value && !name.startsWith("on")) continue;
    applyProp(element, name, value);
  }
  if (!next.__svg) render(element, vnode.children);
}

function applyProp(element, name, value) {
  if (name.startsWith("on") && name.length > 2) {
    const type = name.slice(2).toLowerCase();
    const handlers = element.__handlers || (element.__handlers = {});
    if (handlers[type]) element.removeEventListener(type, handlers[type]);
    if (typeof value === "function") {
      handlers[type] = value;
      element.addEventListener(type, value);
    } else {
      delete handlers[type];
    }
    return;
  }
  if (name === "value") {
    /* An <option> with no value attribute reports its own label as its value, and props are
       written before children exist, so at creation the property is already "" and the write
       below is skipped: the option then answers "Anyone (6)" when it is picked, and a filter
       set to a label matches no lane. The attribute is the only place an option's value is
       safe from its own text. */
    if (element.localName === "option") {
      element.setAttribute("value", value ?? "");
      return;
    }
    if (document.activeElement !== element && element.value !== String(value ?? "")) {
      element.value = value ?? "";
    }
    return;
  }
  if (name === "checked" || name === "selected") {
    element[name] = Boolean(value);
    return;
  }
  if (value == null || value === false) {
    element.removeAttribute(name === "className" ? "class" : name);
    return;
  }
  element.setAttribute(name === "className" ? "class" : name, value === true ? "" : String(value));
}

function flash(element) {
  if (element.classList.contains("flash")) return;
  element.classList.add("flash");
  setTimeout(() => element.classList.remove("flash"), 320);
}

/* -------------------------------------------------- status vocabulary */

/* Five meanings, and only five. Every raw status any producer writes lands in one of them,
   so a reader learns the colours once instead of learning one farm's dictionary. */
export const MEANINGS = {
  run: { label: "Running" },
  wait: { label: "Waiting on a person" },
  fail: { label: "Failed" },
  done: { label: "Done" },
  pause: { label: "Paused" },
};

const AGENT_MEANING = {
  running: "run",
  starting: "run",
  spawning: "run",
  pr_open: "wait",
  done_no_pr: "wait",
  review: "wait",
  blocked: "wait",
  done: "done",
  ended: "done",
  merged: "done",
  failed: "fail",
  killed: "fail",
  gave_up: "fail",
  error: "fail",
  state_unreadable: "fail",
  paused: "pause",
  held: "pause",
  queued: "pause",
};

/* The power setting, in plain words, with what each does to the machine's share. The header
   and the Board both say it, so the five words are written here once. */
export const POWER_MODES = [
  ["full", "Full", "Every core is available to the agents."],
  ["soft", "Shared", "The agents give way to whatever else you are doing."],
  ["balanced", "Background", "The agents keep a small share and stay out of the way."],
  ["hard", "Paused", "No new agent starts, and the running ones are held back hard."],
  ["auto", "Automatic", "The farm picks one of the four from how busy the machine is."],
];

export function powerLabel(id) {
  const found = POWER_MODES.find((row) => row[0] === id);
  return found ? found[1] : id || "unknown";
}

export function agentMeaning(status) {
  return AGENT_MEANING[String(status || "").toLowerCase()] || "pause";
}

const QUEUE_MEANING = {
  running: "run",
  queued: "pause",
  passed: "done",
  passed_partial: "done",
  failed: "fail",
  conflict: "fail",
  blocked: "wait",
  ejected: "pause",
  cancelled: "pause",
  skipped: "pause",
  pending: "pause",
  pass: "done",
  fail: "fail",
  pend: "wait",
  ok: "done",
  missing: "wait",
  off: "pause",
};

export function queueMeaning(state) {
  return QUEUE_MEANING[String(state || "").toLowerCase()] || "pause";
}

export function pill(meaning, label, title) {
  return h("span", { class: `pill ${meaning}`, title: title || "" },
    h("span", { class: "dot" }),
    h("span", { class: "pill-text" }, label || MEANINGS[meaning]?.label || label));
}

/* ------------------------------------------------- shared small pieces */

/**
 * Enter and Space on something that is not a button. A row and a card are opened with a mouse
 * by most readers and with a keyboard by the rest; both have to work, and the browser only
 * does this for you on a real button.
 */
export function activate(handler) {
  return (event) => {
    if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") return;
    event.preventDefault();
    handler(event);
  };
}

export function card(props, ...children) {
  const { class: extra = "", ...rest } = props || {};
  return h("div", { class: `card ${extra}`.trim(), ...rest }, ...children);
}

export function section(title, actions, ...children) {
  return h("section", { class: "section", key: `section:${title}` },
    h("div", { class: "section-head" },
      h("h2", null, title),
      actions ? h("div", { class: "spacer" }) : null,
      actions),
    ...children);
}

export function skeleton(kind = "") {
  return h("div", { class: `skeleton ${kind}`.trim() });
}

export function skeletonStack(rows = 3, kind = "row") {
  return h("div", { class: "skeleton-stack" },
    Array.from({ length: rows }, (_unused, index) => h("div", { class: `skeleton ${kind}`, key: `sk${index}` })));
}

/* The one place a number from a route is allowed to reach a style attribute: clamped to a
   percentage here, so no caller has to be trusted to do it and no string can slip through. */
export function widthStyle(percent) {
  const clamped = Math.max(0, Math.min(100, Number(percent) || 0));
  return `width:${clamped}%`;
}

/* The second and last of them: where the reader dragged the splitter on the Board. The number
   comes from a pointer and from this browser's own storage, never from a route, and it is
   clamped to the range the layout can hold before it is written anywhere. */
export const SPLIT_MIN = 25;
export const SPLIT_MAX = 75;

export function splitPercent(value, fallback = 62) {
  // A browser with nothing stored hands back null, and Number(null) is zero, not nothing:
  // read as a number it put the splitter hard against the left edge on a first visit.
  if (value == null || value === "") return fallback;
  const wanted = Number(value);
  if (!Number.isFinite(wanted)) return fallback;
  return Math.max(SPLIT_MIN, Math.min(SPLIT_MAX, Math.round(wanted)));
}

export function splitStyle(percent) {
  return `--split:${splitPercent(percent)}%`;
}

/**
 * An address a route sent, but only if it is one a browser may follow. A lane writes its own
 * state file, so its address is not the page's to trust: anything that is not plain http or
 * https is shown as text instead of being hung on a link.
 */
export function safeHref(value) {
  const written = String(value ?? "").trim();
  if (!/^https?:\/\//i.test(written)) return null;
  try {
    const parsed = new URL(written);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch (error) {
    return null;
  }
}

export function commandLine(command) {
  return command ? h("code", { class: "cmd" }, command) : null;
}

/** An empty panel says what the thing is and the one command that fills it. */
export function emptyState({ title, body, command }) {
  return h("div", { class: "state-note" },
    h("h3", null, title),
    body ? h("p", null, body) : null,
    commandLine(command));
}

/** An error panel names the tool and the command. Never a stack trace. */
export function errorState({ title, body, command }) {
  return h("div", { class: "state-note error" },
    h("h3", null, title),
    body ? h("p", null, body) : null,
    commandLine(command));
}

export function staleLine(resource) {
  if (!resource || !resource.error || !resource.everLoaded) return null;
  return h("p", { class: "readonly-note" },
    `Showing the last answer, from ${new Date((resource.at || 0) * 1000).toLocaleTimeString("en-US")}. ${resource.error.title}`);
}

/**
 * The four states of every panel in one place: loading before any answer, error when there
 * has never been one, empty when the answer is empty, ready otherwise.
 */
export function panel(resource, options) {
  if (!resource || (!resource.everLoaded && !resource.error)) {
    return options.loading ? options.loading() : skeletonStack(3);
  }
  if (!resource.everLoaded && resource.error) {
    return errorState(resource.error);
  }
  /* A snapshot route says "pending" until its first pass has run. That is a wait, not a
     failure, and it must look like one: a skeleton, never an error card. */
  if (resource.data && resource.data.pending) {
    return options.loading ? options.loading() : skeletonStack(3);
  }
  const unavailable = resource.data && resource.data.unavailable;
  if (unavailable) {
    return emptyState({ title: resource.data.unavailable, body: "", command: resource.data.fix });
  }
  if (options.isEmpty && options.isEmpty(resource.data)) {
    return [staleLine(resource), options.empty(resource.data)];
  }
  return [staleLine(resource), options.ready(resource.data)];
}

/* -------------------------------------------------------------- drawer */

let drawer = null;
let opener = null;

export function openDrawer(spec) {
  if (!drawer) opener = document.activeElement;
  drawer = spec;
  paintDrawer();
  const host = document.getElementById("drawer");
  const close = document.getElementById("drawerClose");
  // A reader who opened this from the keyboard is otherwise left behind on the list, tabbing
  // through cards they can no longer see.
  if (host && !host.contains(document.activeElement) && close) close.focus();
}

export function closeDrawer() {
  if (!drawer) return;
  if (drawer.onClose) drawer.onClose();
  drawer = null;
  paintDrawer();
  if (opener && opener.isConnected && document.contains(opener)) opener.focus();
  opener = null;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Keep Tab inside one layer. Without it the next press lands on the page behind the cover. */
export function trapFocus(container, event) {
  if (event.key !== "Tab" || !container || container.hidden) return;
  const inside = [...container.querySelectorAll(FOCUSABLE)].filter((node) => node.clientHeight > 0 || node === document.activeElement);
  if (!inside.length) return;
  const first = inside[0];
  const last = inside[inside.length - 1];
  if (!container.contains(document.activeElement)) {
    event.preventDefault();
    first.focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function openDrawerKey() {
  return drawer ? drawer.key : null;
}

/** Repainted by the tick, so an open drawer keeps up with its lane without being rebuilt. */
export function paintDrawer() {
  const host = document.getElementById("drawer");
  const scrim = document.getElementById("drawerScrim");
  if (!host || !scrim) return;
  host.hidden = !drawer;
  scrim.hidden = !drawer;
  if (!drawer) {
    render(document.getElementById("drawerBody"), []);
    return;
  }
  document.getElementById("drawerTitle").textContent = drawer.title || "";
  document.getElementById("drawerSub").textContent = drawer.sub || "";
  render(document.getElementById("drawerBody"), drawer.body());
}

/* --------------------------------------------------------------- toast */

export function toast(message, kind = "") {
  const host = document.getElementById("toasts");
  if (!host) return;
  const node = document.createElement("div");
  node.className = `toast ${kind}`.trim();
  node.textContent = message;
  host.append(node);
  setTimeout(() => node.remove(), 5000);
}

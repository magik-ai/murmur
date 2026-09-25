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

/* The vendors' own marks: Anthropic's Claude burst in its own orange, OpenAI's knot in the text
   colour so it holds in both themes. An engine without a mark here is said in words by the
   caller. */
const ENGINE_MARKS = {
  claude: ["Claude", '<path fill="#D97757" d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z"/>'],
  codex: ["Codex (OpenAI)", '<path fill="currentColor" d="M9.205 8.658v-2.26c0-.19.072-.333.238-.428l4.543-2.616c.619-.357 1.356-.523 2.117-.523 2.854 0 4.662 2.212 4.662 4.566 0 .167 0 .357-.024.547l-4.71-2.759a.797.797 0 00-.856 0l-5.97 3.473zm10.609 8.8V12.06c0-.333-.143-.57-.429-.737l-5.97-3.473 1.95-1.118a.433.433 0 01.476 0l4.543 2.617c1.309.76 2.189 2.378 2.189 3.948 0 1.808-1.07 3.473-2.76 4.163zM7.802 12.703l-1.95-1.142c-.167-.095-.239-.238-.239-.428V5.899c0-2.545 1.95-4.472 4.591-4.472 1 0 1.927.333 2.712.928L8.23 5.067c-.285.166-.428.404-.428.737v6.898zM12 15.128l-2.795-1.57v-3.33L12 8.658l2.795 1.57v3.33L12 15.128zm1.796 7.23c-1 0-1.927-.332-2.712-.927l4.686-2.712c.285-.166.428-.404.428-.737v-6.898l1.974 1.142c.167.095.238.238.238.428v5.233c0 2.545-1.974 4.472-4.614 4.472zm-5.637-5.303l-4.544-2.617c-1.308-.761-2.188-2.378-2.188-3.948A4.482 4.482 0 014.21 6.327v5.423c0 .333.143.571.428.738l5.947 3.449-1.95 1.118a.432.432 0 01-.476 0zm-.262 3.9c-2.688 0-4.662-2.021-4.662-4.519 0-.19.024-.38.047-.57l4.686 2.71c.286.167.571.167.856 0l5.97-3.448v2.26c0 .19-.07.333-.237.428l-4.543 2.616c-.619.357-1.356.523-2.117.523zm5.899 2.83a5.947 5.947 0 005.827-4.756C22.287 18.339 24 15.84 24 13.296c0-1.665-.713-3.282-1.998-4.448.119-.5.19-.999.19-1.498 0-3.401-2.759-5.947-5.946-5.947-.642 0-1.26.095-1.88.31A5.962 5.962 0 0010.205 0a5.947 5.947 0 00-5.827 4.757C1.713 5.447 0 7.945 0 10.49c0 1.666.713 3.283 1.998 4.448-.119.5-.19 1-.19 1.499 0 3.401 2.759 5.946 5.946 5.946.642 0 1.26-.095 1.88-.309a5.96 5.96 0 004.162 1.713z"/>'],
};

export function engineMark(engine) {
  const mark = ENGINE_MARKS[String(engine || "").toLowerCase()];
  if (!mark) return null;
  return svg(mark[1], { class: "engine-mark", viewBox: "0 0 24 24", role: "img", "aria-label": mark[0] });
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
  ["auto", "Automatic", "Full while the graphics card is idle, Shared while it is in use. "
    + "With no graphics card sensor it stays on Full."],
];

export function powerLabel(id) {
  const found = POWER_MODES.find((row) => row[0] === id);
  return found ? found[1] : id || "unknown";
}

export function agentMeaning(status) {
  return AGENT_MEANING[String(status || "").toLowerCase()] || "pause";
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

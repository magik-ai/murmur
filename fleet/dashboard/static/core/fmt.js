/* Formatting. Every number a person reads passes through here, so the same quantity is never
   written two ways on one screen. Pure functions, no DOM: the node check imports this file. */

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

/** Seconds since the epoch from an epoch number, an epoch in milliseconds, or an ISO string. */
export function seconds(value) {
  if (value == null || value === "") return null;
  if (typeof value === "number") return value > 1e11 ? value / 1000 : value;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

/** "4m ago", "2h ago", "just now". An unknown time is a dash, never a fake zero. */
export function ago(value, now = Date.now() / 1000) {
  const at = seconds(value);
  if (at == null) return "not known";
  const delta = Math.max(0, now - at);
  if (delta < 45) return "just now";
  return `${duration(delta)} ago`;
}

/** A span of time in the largest two units that carry information. */
export function duration(secondsSpan) {
  const total = Math.max(0, Math.round(Number(secondsSpan) || 0));
  if (total < MINUTE) return `${total}s`;
  if (total < HOUR) {
    const minutes = Math.floor(total / MINUTE);
    const rest = total % MINUTE;
    return rest && minutes < 10 ? `${minutes}m ${rest}s` : `${minutes}m`;
  }
  if (total < DAY) {
    const hours = Math.floor(total / HOUR);
    const minutes = Math.floor((total % HOUR) / MINUTE);
    return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  const days = Math.floor(total / DAY);
  const hours = Math.floor((total % DAY) / HOUR);
  return hours ? `${days}d ${hours}h` : `${days}d`;
}

/** Time left until an instant, for a limit window that resets. */
export function until(value, now = Date.now() / 1000) {
  const at = seconds(value);
  if (at == null) return "";
  const delta = at - now;
  return delta <= 0 ? "now" : `in ${duration(delta)}`;
}

/** Wall clock, for the freshness label. */
export function clock(value = Date.now() / 1000) {
  const at = seconds(value);
  if (at == null) return "not known";
  const date = new Date(at * 1000);
  const pad = (part) => String(part).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/** Whole numbers with thousands separators, so columns of them line up. */
export function num(value, fallback = "none") {
  if (value == null || value === "" || Number.isNaN(Number(value))) return fallback;
  return Number(value).toLocaleString("en-US");
}

/** One decimal, for gigabytes and dollars that would read as noise at full precision. */
export function decimal(value, places = 1, fallback = "none") {
  if (value == null || Number.isNaN(Number(value))) return fallback;
  return Number(value).toFixed(places);
}

export function percent(value, fallback = "none") {
  if (value == null || Number.isNaN(Number(value))) return fallback;
  return `${Math.round(Number(value))}%`;
}

export function money(value, fallback = "none") {
  if (value == null || Number.isNaN(Number(value))) return fallback;
  return `$${Number(value).toFixed(2)}`;
}

/** Bytes as the unit a person would say out loud. */
export function bytes(value, fallback = "none") {
  if (value == null || Number.isNaN(Number(value))) return fallback;
  let left = Number(value);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let unit = 0;
  while (left >= 1024 && unit < units.length - 1) {
    left /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? Math.round(left) : left.toFixed(1)} ${units[unit]}`;
}

export function gigabytes(value, fallback = "none") {
  return value == null || Number.isNaN(Number(value)) ? fallback : `${Number(value).toFixed(1)} GB`;
}

/** Cut long text for a card, on a word boundary when there is one nearby. */
export function shorten(value, limit = 140) {
  const text = String(value ?? "").trim().replace(/\s+/g, " ");
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit);
  const space = cut.lastIndexOf(" ");
  return `${space > limit * 0.6 ? cut.slice(0, space) : cut}…`;
}

/** A branch, a repository or a slug shown in a narrow cell. */
export function tail(value, limit = 40) {
  const text = String(value ?? "");
  return text.length <= limit ? text : `…${text.slice(-(limit - 1))}`;
}

export function titleCase(value) {
  const text = String(value ?? "").replace(/[_-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

/* Whether an account has room, in the same words on every tab. Out of room means a window every
   model shares (the session or the week) is used up, or the vendor says the limit is reached. A
   window scoped to one model (Fable) at 100 percent leaves every other model running, so it is
   named on its own: "Fable used up", never "Out of room": otherwise the Machine tab says
   logged in while the Board says out of room, for an account that only has Fable spent. */
export function room(account) {
  const one = account || {};
  const full = (value) => value != null && Number(value) >= 100;
  if (one.limit_reached || full(one.session) || full(one.weekly)) {
    return { meaning: "fail", word: "Out of room" };
  }
  const spent = (Array.isArray(one.scoped) ? one.scoped : [])
    .filter((window) => full(window.percent)).map((window) => window.label || "a model");
  if (spent.length) return { meaning: "wait", word: `${spent.join(", ")} used up` };
  return null;
}


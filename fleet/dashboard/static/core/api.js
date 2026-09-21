/* Talking to the server: the token, the access model, one cache of resources, and errors
   turned into a sentence a person can act on. No stack trace ever reaches the page. */

let tokenCache = null;

/**
 * The write token. A browser cannot read an environment variable, so it arrives once in the
 * address bar, is kept for the tab and is stripped back out. Only the token is stripped:
 * anything else in the query belongs to whoever put it there.
 */
export function token() {
  if (tokenCache != null) return tokenCache;
  tokenCache = "";
  try {
    const query = new URLSearchParams(location.search);
    const found = query.get("token");
    if (found) {
      sessionStorage.setItem("murmur.token", found);
      query.delete("token");
      const rest = query.toString();
      history.replaceState(null, "", location.pathname + (rest ? `?${rest}` : "") + location.hash);
      tokenCache = found;
    } else {
      tokenCache = sessionStorage.getItem("murmur.token") || "";
    }
  } catch (error) {
    tokenCache = "";
  }
  return tokenCache;
}

function headers(extra) {
  const out = { ...extra };
  const value = token();
  if (value) out.Authorization = `Bearer ${value}`;
  return out;
}

export class ApiError extends Error {
  constructor(status, payload, path) {
    super(payload && payload.error ? payload.error : `request failed with ${status}`);
    this.status = status;
    this.payload = payload;
    this.path = path;
    /* What the server itself said, kept apart from the message so a view can tell a sentence
       written for a person from this class's own fallback. Empty when it said nothing. */
    this.reason = payload && typeof payload.error === "string" ? payload.error.trim() : "";
  }
}

/**
 * The sentence the server gave for refusing, or "" when it gave none. A refusal is usually the
 * most useful thing on the screen: "a repository is owner/name" tells the reader what to do,
 * and "the request was refused" tells them nothing. Every caller of apiPost that has somewhere
 * to put a sentence shows this one first and keeps its own wording as the fallback.
 */
export function serverReason(error) {
  return error && typeof error.reason === "string" ? error.reason : "";
}

/* A body the page cannot decode is a failure, not an empty answer. A proxy, a captive portal
   and a restarted server all hand back a page of HTML with a 200 on it, and treating that as
   data is how a tab ends up half drawn under a header that still says the page is live. */
export const UNREADABLE = "The server answered something this page cannot read.";

async function parse(response, path) {
  const raw = await response.text();
  let payload = null;
  let decoded = true;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch (error) {
    decoded = false;
  }
  if (!response.ok) throw new ApiError(response.status, decoded ? payload : null, path);
  if (!decoded) throw new ApiError(response.status, { error: UNREADABLE }, path);
  return payload;
}

/**
 * The only two shapes a view is ever handed: an object it can read, or a failure. A route that
 * answers a bare string, a number or nothing at all is a failure, whatever its status was.
 */
export function shaped(payload, path = "") {
  if (payload === null || typeof payload !== "object") {
    throw new ApiError(200, { error: UNREADABLE }, path);
  }
  return payload;
}

/** A route that should have answered a list, reduced to one. Anything else counts as none. */
export function list(value) {
  return Array.isArray(value) ? value : [];
}

/* A request that never comes back is not a wait, it is a panel stuck on a skeleton for the life
   of the page: the resource below only ever leaves "loading" when a request settles. The farm's
   queue route reads the forge inline on its first draw, which is exactly how a live dashboard
   was left showing two grey bars with nothing to tell the reader. */
export const REQUEST_LIMIT_MS = 30000;

async function fetchBounded(path, options) {
  const bell = new AbortController();
  const timer = setTimeout(() => bell.abort(), REQUEST_LIMIT_MS);
  try {
    return await fetch(path, { ...options, signal: bell.signal });
  } finally {
    clearTimeout(timer);
  }
}

export async function apiGet(path) {
  const response = await fetchBounded(path, { headers: headers({}) });
  return parse(response, path);
}

/**
 * A write. A refusal throws, and the thrown error carries the server's own sentence on
 * `reason` whenever the refusal came back as JSON with an `error` in it. Read it with
 * serverReason(); a caller that swallows it leaves the reader guessing what was wrong.
 */
export async function apiPost(path, body) {
  const response = await fetchBounded(path, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body || {}),
  });
  return parse(response, path);
}

/* ------------------------------------------------------ error sentences */

const TOOL_HINTS = [
  [/\bgh\b/, "gh", "sudo apt install gh"],
  [/\bhq\b/, "hq", "hq init --repo <owner>/<office>"],
  [/nvidia-smi/, "nvidia-smi", "set FLEET_NVIDIA_SMI to the path of nvidia-smi"],
  [/systemd|systemctl/, "systemd", "loginctl enable-linger $USER"],
];

/** Turn any failure into a title, a sentence and the command that fixes it. */
export function normaliseError(error, path = "") {
  if (error instanceof ApiError) {
    const said = error.payload && (error.payload.error || error.payload.unavailable);
    if (error.status === 403) {
      return {
        title: "This dashboard cannot read that",
        body: said || "The server refused the request because it carried no dashboard token.",
        command: "fleet dash --print-token",
      };
    }
    if (error.status === 404) {
      return {
        title: "The server does not serve this route",
        body: `${path || error.path} is missing, so this panel has nothing to read. The page and the server are different versions.`,
        command: "fleet update && fleet dash --restart",
      };
    }
    if (said === UNREADABLE) {
      return {
        title: "The answer could not be read",
        body: `${path || error.path} answered something that is not the data this page expects. A proxy or a sign-in page in front of the farm does exactly this.`,
        command: "fleet dash --status",
      };
    }
    if (said) {
      for (const [pattern, tool, fix] of TOOL_HINTS) {
        if (pattern.test(said)) {
          return { title: `${tool} could not answer`, body: said, command: fix };
        }
      }
      return { title: "The server reported a problem", body: said, command: "" };
    }
    return {
      title: "The server reported a problem",
      body: `The request for ${path || error.path} came back with status ${error.status}.`,
      command: "",
    };
  }
  if (error && error.name === "AbortError") {
    return {
      title: "The server took too long to answer",
      body: `${path || ""} did not come back within thirty seconds, so this panel has nothing to show yet. A route that reads the forge on every farm is the usual reason.`.trim(),
      command: "fleet dash --status",
    };
  }
  return {
    title: "The dashboard server did not answer",
    body: "Nothing came back from the server, so this panel has no data. Check that it is still running.",
    command: "fleet dash --status",
  };
}

/* ----------------------------------------------------- the access model */

export const access = {
  writable: true,
  reason: "",
  checked: false,
  loopback: true,
};

export function canWrite() {
  return access.writable;
}

export function writeBlockReason() {
  return access.reason || "This dashboard is read-only.";
}

/* -------------------------------------------------------- the resources */

/* How often a path is worth asking for. The tick is 3 seconds; anything that cannot change
   that fast is asked for less often, so a page open all day is not a load on the farm. */
const INTERVALS = {
  "/api/config": 60000,
  "/api/access": 30000,
  "/api/identities": 60000,
  "/api/health": 10000,
  "/api/projects": 15000,
  "/api/models": 30000,
  "/api/accounts": 10000,
  "/api/sweep": 15000,
  "/api/mode": 5000,
  "/api/version": 30000,
  "/api/mail/boxes": 20000,
};
const DEFAULT_INTERVAL = 3000;

/* Paths that carry a query, matched by prefix. A thread and a log are asked for on their own
   rhythm: a reader looking at one does not need it re-read three times a second. */
const PREFIX_INTERVALS = [
  ["/api/mail/thread", 15000],
  ["/api/mail/feed", 15000],
  ["/api/mail/who", 15000],
  ["/api/agent/log", 10000],
  ["/api/ci/log", 10000],
];

function intervalFor(path) {
  if (path in INTERVALS) return INTERVALS[path];
  for (const [prefix, value] of PREFIX_INTERVALS) if (path.startsWith(prefix)) return value;
  return DEFAULT_INTERVAL;
}

const cache = new Map();

export function resource(path) {
  let found = cache.get(path);
  if (!found) {
    found = {
      path,
      state: "loading",
      data: null,
      error: null,
      at: null,
      everLoaded: false,
      inflight: false,
      lastTry: 0,
    };
    cache.set(path, found);
  }
  return found;
}

export function has(path) {
  return cache.has(path);
}

export function forget(path) {
  cache.delete(path);
}

export async function refresh(path) {
  const entry = resource(path);
  if (entry.inflight) return entry;
  entry.inflight = true;
  entry.lastTry = Date.now();
  try {
    entry.data = shaped(await apiGet(path), path);
    entry.error = null;
    entry.state = "ready";
    entry.everLoaded = true;
    entry.at = Date.now() / 1000;
  } catch (error) {
    entry.error = normaliseError(error, path);
    entry.state = "error";
  } finally {
    entry.inflight = false;
  }
  return entry;
}

/** Ask for everything the open view needs, respecting each path's own rhythm. */
export async function pull(paths, force = false) {
  const now = Date.now();
  const due = [...new Set(paths)].filter((path) => {
    const entry = resource(path);
    if (entry.inflight) return false;
    if (force || !entry.everLoaded) return true;
    return now - entry.lastTry >= intervalFor(path);
  });
  await Promise.all(due.map((path) => refresh(path)));
  return due;
}

/**
 * The oldest successful answer among the paths on the screen. The label speaks for the whole
 * page, so it has to speak for its worst panel: saying the page is live because one route
 * answered a moment ago, while the panel under it shows an hour-old reading, is a lie.
 */
export function oldestAt(paths) {
  let oldest = null;
  for (const path of paths) {
    const entry = cache.get(path);
    if (entry && entry.at != null && (oldest == null || entry.at < oldest)) oldest = entry.at;
  }
  return oldest;
}

/** True when any path on the screen is currently failing, which is what "stale" means here. */
export function anyFailing(paths) {
  return paths.some((path) => {
    const entry = cache.get(path);
    return Boolean(entry && entry.error);
  });
}

/**
 * The routes on screen whose answer says it is old. A snapshot route (mail, the prerequisites,
 * the settings) answers from the server's last good reading and marks it `stale_since` when the
 * pass behind it failed. That answer reaches this page perfectly well, so the page's own
 * requests are all fine, and the reader is still looking at old data: the header has to count
 * it. Each row carries where it came from, since when, and why, for the label to show.
 */
export function staleSnapshots(paths) {
  const out = [];
  for (const path of new Set(paths)) {
    const entry = cache.get(path);
    const data = entry && entry.data;
    if (!data || typeof data !== "object" || Array.isArray(data)) continue;
    if (!data.stale_since) continue;
    out.push({ path, since: data.stale_since, reason: typeof data.error === "string" ? data.error : "" });
  }
  return out;
}

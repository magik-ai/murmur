import assert from "node:assert/strict";
import fs from "node:fs";

const html = fs.readFileSync(new URL("./index.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const cardSource = script.slice(
  script.indexOf("let CI_STAGE_OPEN"),
  script.indexOf("function renderCI"),
);
const { ciCard, ciDetail, ciHasRecords, ciLogKey, ciLogs } = new Function(
  "esc",
  "span",
  `${cardSource}; return {ciCard,ciDetail,ciHasRecords,ciLogKey,ciLogs:CI_LOGS};`,
)(
  (value) =>
    String(value ?? "").replace(/[&<]/g, (character) =>
      character === "&" ? "&amp;" : "&lt;",
    ),
  (seconds) => `${Math.floor(Number(seconds) || 0)}s`,
);

const sample = {
  pr: 3210,
  repo: "your-org/demo",
  branch: "feat/local-ci",
  tier: "backend",
  started: Date.now() / 1000 - 80,
  enqueued: Date.now() / 1000 - 400,
  tiers: [
    { name: "frontend", state: "passed" },
    { name: "backend", state: "running" },
    { name: "docker", state: "pending" },
  ],
  uncovered: ["visual parity"],
};

assert.match(ciCard({ ...sample, state: "running" }, "running"), /running/);
assert.match(
  ciCard({ ...sample, state: "queued", position: 2 }, "queued"),
  /position 2/,
);
assert.match(
  ciCard({ ...sample, state: "passed", ended: Date.now() / 1000 }, "recent"),
  /passed/,
);

const verdictCards = Object.fromEntries(
  [
    ["passed", []],
    ["passed_partial", ["visual parity", "hosted browser"]],
    ["failed", []],
    ["conflict", []],
    ["ejected", []],
    ["cancelled", []],
  ].map(([state, uncovered]) => [
    state,
    ciCard(
      {
        ...sample,
        state,
        uncovered,
        reason:
          state === "passed_partial"
            ? "merge verified with hosted-only gates"
            : undefined,
      },
      "recent",
    ),
  ]),
);
assert.match(verdictCards.passed, /class="ci-card passed\b/);
assert.match(verdictCards.passed, /class="tierline passed"/);
assert.match(verdictCards.passed_partial, /class="ci-card passed_partial\b/);
assert.match(verdictCards.passed_partial, /class="tierline passed_partial"/);
assert.match(
  verdictCards.passed_partial,
  /<div class="cireason partial"><b>2 uncovered<\/b>/,
);
assert.match(verdictCards.failed, /class="ci-card failed failure-code\b/);
assert.match(verdictCards.conflict, /class="ci-card conflict failure-conflict\b/);
assert.match(verdictCards.ejected, /class="ci-card ejected\b/);
assert.doesNotMatch(verdictCards.ejected, /\bfailure-/);
assert.match(verdictCards.cancelled, /class="ci-card cancelled\b/);
assert.doesNotMatch(verdictCards.cancelled, /\bfailure-/);

const failureRecord = {
  ...sample,
  id: "ci-3210-failed",
  state: "failed",
  failure_kind: "environment",
  reason: "failed tier(s): frontend",
  base_sha: "base123",
  merge_sha: "merge456",
  tiers: [
    { name: "backend", state: "passed", started: 100, ended: 130 },
    {
      name: "frontend",
      state: "failed",
      started: 130,
      ended: 160,
      failure_kind: "environment",
      detail: "runner image is unavailable",
      log: "/tmp/fleet/ci/frontend.log",
    },
    {
      name: "docker",
      state: "skipped",
      failure_kind: null,
      detail: "paths unchanged",
    },
  ],
  failed_tests: [
    {
      tier: "frontend",
      test: "e2e/queue.spec.js:12 › shows a failure",
      log: "/tmp/fleet/ci/frontend.log",
    },
  ],
};
const failure = ciCard(failureRecord, "recent", failureRecord.id, false);
assert.match(failure, /failure-environment/);
assert.match(failure, /runner image is unavailable/);
assert.match(failure, /<b>frontend<\/b>/);
assert.match(failure, /role="button" tabindex="0"/);
assert.match(failure, /aria-expanded="false"/);
assert.doesNotMatch(failure, /e2e\/queue\.spec\.js:12/);
assert.doesNotMatch(failure, /\/tmp\/fleet\/ci\/frontend\.log/);
assert.doesNotMatch(failure, /visual parity/);
assert.doesNotMatch(failure, /<details/);

ciLogs[ciLogKey(failureRecord.id, "frontend")] = {
  status: "loaded",
  payload: {
    content: "FAIL queue.spec.js\nexpected compact card",
    truncated: false,
  },
};
const failureDetail = ciDetail(
  failureRecord,
  "recent",
  failureRecord.id,
);
const failureExpanded = ciCard(
  failureRecord,
  "recent",
  failureRecord.id,
  true,
);
assert.match(failureDetail, /base123 → merge456/);
assert.match(failureDetail, /<details class="cistage passed"/);
assert.match(failureDetail, /<details class="cistage failed"/);
assert.match(failureDetail, /<details class="cistage skipped"/);
assert.match(failureDetail, /e2e\/queue\.spec\.js:12/);
assert.match(failureDetail, /FAIL queue\.spec\.js/);
assert.doesNotMatch(failureDetail, /\/tmp\/fleet\/ci\/frontend\.log/);
assert.match(failureDetail, /Hosted gates not covered/);
assert.match(failureDetail, /visual parity/);
assert.match(failureDetail, /skipped — paths unchanged/);
assert.match(failureExpanded, /class="ci-card failed failure-environment expanded"/);
assert.match(failureExpanded, /aria-expanded="true"/);
assert.match(failureExpanded, /e2e\/queue\.spec\.js:12/);
assert.match(failureExpanded, /FAIL queue\.spec\.js/);
assert.doesNotMatch(failureExpanded, /modalp|aria-modal/);

const runningDetail = ciDetail(
  {
    ...sample,
    id: "ci-3210-running",
    state: "running",
    tiers: sample.tiers.map((tier) =>
      tier.name === "backend"
        ? { ...tier, started: Date.now() / 1000 - 80 }
        : tier,
    ),
  },
  "running",
  "ci-3210-running",
);
assert.match(runningDetail, /<details class="cistage running"/);
assert.match(runningDetail, /<span class="stagedesc">running<\/span>/);
assert.match(runningDetail, /<span class="stageduration">\d+s<\/span>/);

const queuedDetail = ciDetail(
  {
    id: "ci-3211-queued",
    pr: 3211,
    repo: "your-org/demo",
    branch: "feat/waiting",
    state: "queued",
    enqueued: Date.now() / 1000 - 30,
  },
  "queued",
);
for (const stage of ["backend", "frontend", "docker"]) {
  assert.match(
    queuedDetail,
    new RegExp(`<span class="stagename">${stage}<\\/span>[\\s\\S]*?queued`),
  );
}

const skippedBeforeEnvironmentFailure = ciCard(
  {
    ...sample,
    state: "failed",
    reason: "failed tier(s): frontend",
    tiers: [
      {
        name: "backend",
        state: "skipped",
        failure_kind: null,
        detail: "paths unchanged",
      },
      {
        name: "frontend",
        state: "failed",
        failure_kind: "environment",
        detail: "test database is unreachable",
      },
      { name: "docker", state: "skipped", failure_kind: null },
    ],
  },
  "recent",
);
assert.match(skippedBeforeEnvironmentFailure, /failure-environment/);
assert.match(
  skippedBeforeEnvironmentFailure,
  /<span class="failurekind environment">environment<\/span>/,
);
assert.doesNotMatch(skippedBeforeEnvironmentFailure, /failure-code/);

const legacyPassed = ciCard(
  { ...sample, state: "passed", ended: Date.now() / 1000 },
  "recent",
);
assert.doesNotMatch(legacyPassed, /\bstale\b|\bdivergent\b|ciflags/);
assert.equal(
  ciCard(
    {
      ...sample,
      state: "passed",
      stale: false,
      divergent: false,
      ended: Date.now() / 1000,
    },
    "recent",
  ),
  legacyPassed,
);

const stalePassed = ciCard(
  {
    ...sample,
    state: "passed",
    stale: true,
    ended: Date.now() / 1000,
  },
  "recent",
);
assert.notEqual(stalePassed, legacyPassed);
assert.match(stalePassed, /class="ci-card passed stale"/);
assert.match(stalePassed, /class="ciflag stale">stale base<\/span>/);

const divergent = ciCard(
  {
    ...sample,
    state: "passed",
    divergent: true,
    farm_verdict: "passed",
    github_verdict: "failed",
    ended: Date.now() / 1000,
  },
  "recent",
);
assert.match(divergent, /class="ci-card passed divergent"/);
assert.match(
  divergent,
  /verdict divergence · farm: passed · GitHub: failed/,
);
assert.doesNotMatch(divergent, /class="ci-card (?:failed|failure-code)/);
const observedVerdicts = ciDetail(
  {
    ...sample,
    state: "passed",
    stale: true,
    stale_reason: "verified against main@old, now main@new",
    divergent: true,
    farm_verdict: "passed",
    hosted_verdict: "failed",
  },
  "recent",
);
assert.match(observedVerdicts, /Stale verdict/);
assert.match(observedVerdicts, /verified against main@old, now main@new/);
assert.match(observedVerdicts, /Divergent verdict/);
assert.match(observedVerdicts, /farm reported passed while GitHub reported failed/);
assert.equal(ciHasRecords([], [], []), false);
assert.equal(ciHasRecords([], [], [{ state: "passed" }]), true);

// Keep the accessibility and persistence contract executable without adding a
// browser dependency to this stdlib-only dashboard.
assert.match(html, /html,body\{height:100%;overflow:hidden\}/);
assert.match(
  html,
  /\.pane\{[^}]*overflow-y:auto;overflow-x:hidden;[^}]*\}/,
);
assert.match(
  html,
  /--pane-min-w:calc\(var\(--card-w\) \+ 2 \* var\(--pane-gutter\) \+ var\(--pane-scrollbar-w\)\)/,
);
assert.match(
  html,
  /\.cards,\.ci-grid\{[^}]*minmax\(min\(100%,var\(--card-w\)\),1fr\)/,
);
assert.match(html, /#fleetview\{display:flex;flex-direction:column\}/);
assert.match(html, /\.fleet-split\{flex:1 1 auto;min-height:0;/);
assert.match(html, /\.fleet-split\.stacked\{flex-direction:column\}/);
assert.match(
  html,
  /\.ci-card\.passed_partial\{border-left-color:var\(--warn\)\}/,
);
assert.match(
  html,
  /\.ci-card\.divergent\{[^}]*border-color:var\(--divergent\)/,
);
assert.match(
  html,
  /\.ci-card\.failed,\.ci-card\.conflict\{border-left-color:var\(--block\)\}/,
);
assert.match(
  html,
  /\.ci-card\.ejected,\.ci-card\.cancelled\{border-left-color:var\(--dim\)\}/,
);
assert.match(
  html,
  /\.ci-card\.passed \.cistate\{color:var\(--ok\)\}/,
);
assert.match(
  html,
  /\.ci-card\.passed_partial \.cistate\{color:var\(--warn\)\}/,
);
assert.match(
  html,
  /\.ci-card\.failed \.cistate,\.ci-card\.conflict \.cistate\{color:var\(--block\)\}/,
);
assert.match(
  html,
  /\.ci-card\.ejected \.cistate,\.ci-card\.cancelled \.cistate\{color:var\(--dim\)\}/,
);
assert.match(
  html,
  /\.tierline\.passed_partial \.tier\.passed[^}]*color:var\(--warn\)/,
);
assert.match(html, /\.tier\.passed,\.tier\.pass\{color:var\(--ok\)\}/);
assert.match(html, /\.tier\.failed,\.tier\.fail\{color:var\(--block\)\}/);
assert.match(
  html,
  /\.tierline\.ejected \.tier,\.tierline\.cancelled \.tier\{color:var\(--dim\)/,
);
assert.match(
  html,
  /\.card\.state_unreadable \.st\{color:var\(--block\)\}/,
);
assert.match(
  script,
  /s\.status==='state_unreadable'\?`<div class="alarm">⚠ state unreadable · liveness unknown<\/div>`/,
);
assert.match(
  html,
  /id="ciRecentToggle"[^>]*type="button"[^>]*aria-expanded="false"[^>]*aria-controls="ciRecent"/,
);
assert.match(html, /<div class="ci-grid" id="ciRecent" hidden><\/div>/);
assert.match(
  html,
  /id="ciRunningSection" hidden>\s*<h3>Running[\s\S]*?id="ciQueuedSection" hidden>\s*<h3>Queued/,
);
assert.match(
  html,
  /class="splitter"[^>]*role="separator"/,
);
assert.match(html, /class="splitter"[^>]*tabindex="0"/);
assert.match(html, /class="splitter"[^>]*aria-orientation="vertical"/);
assert.match(script, /localStorage\.setItem\(SPLIT_KEY/);
assert.match(script, /localStorage\.setItem\(RECENT_KEY/);
assert.match(script, /e\.key==='Home'/);
assert.match(script, /e\.key==='End'/);
assert.match(script, /\$\('ciPane'\)\.addEventListener\('keydown'/);
assert.match(script, /e\.key!=='Enter'&&e\.key!==' '/);
assert.match(script, /e\.key!=='Escape'/);
assert.match(script, /get\('\/api\/ci\/log\?id='/);
assert.match(script, /addEventListener\('dblclick'/);
assert.match(script, /addEventListener\('pointerdown'/);
assert.match(script, /g\.available<2\*g\.min/);
assert.match(
  html,
  // metrics, then the Anthropic subscription strip (its own labelled row - these numbers
  // describe the vendor, not the machine), then the split panes
  /<div id="fleetview">\s*<div class="health" id="health"><\/div>\s*<div class="health" id="acctrow" hidden><\/div>\s*<div class="fleet-split" id="fleetSplit">/,
);
assert.match(
  html,
  /<div class="fleet-split" id="fleetSplit">\s*<section class="pane agents-pane"[\s\S]*?<div class="splitter"[\s\S]*?<section class="pane ci-pane"/,
);

function recentHarness(saved) {
  const storage = new Map();
  if (saved !== undefined) {
    storage.set("fleet.dashboard.ci.recent.open.v1", saved);
  }
  const localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
  };
  const end = script.indexOf("// RECENT_TOGGLE_END");
  assert.ok(end > 0, "index.html lost its RECENT_TOGGLE_END marker");
  const recentSource = script.slice(script.indexOf("const RECENT_KEY"), end);
  const api = new Function(
    "localStorage",
    "renderCI",
    `${recentSource}; return {
      isOpen:()=>RECENT_OPEN,
      setRecentOpen,
      storedRecentOpen,
      key:RECENT_KEY,
    };`,
  )(localStorage, () => {});
  return { ...api, storage };
}

{
  const firstLoad = recentHarness();
  assert.equal(firstLoad.isOpen(), false);
  firstLoad.setRecentOpen(true);
  assert.equal(firstLoad.storage.get(firstLoad.key), "open");
  const reload = recentHarness(firstLoad.storage.get(firstLoad.key));
  assert.equal(reload.isOpen(), true);
  reload.setRecentOpen(false);
  assert.equal(reload.storage.get(reload.key), "closed");
}

function splitHarness(saved = "0.6900000000000001") {
  const listeners = new Map();
  const classes = () => {
    const values = new Set();
    return {
      add: (...names) => names.forEach((name) => values.add(name)),
      remove: (...names) => names.forEach((name) => values.delete(name)),
      contains: (name) => values.has(name),
      toggle(name, force) {
        const on = force === undefined ? !values.has(name) : force;
        if (on) values.add(name);
        else values.delete(name);
        return on;
      },
    };
  };
  const rootStyle = new Map();
  const root = {
    style: {
      setProperty: (name, value) => rootStyle.set(name, value),
    },
  };
  const fleetSplit = {
    classList: classes(),
    clientLeft: 1,
    clientWidth: 1358,
    getBoundingClientRect() {
      return { left: 20, width: this.clientWidth + 2 };
    },
  };
  const ciPane = {
    style: {},
    offsetWidth: 600,
    clientWidth: 585,
  };
  const agentsPane = {
    style: { flexBasis: "" },
    offsetWidth: 600,
    clientWidth: 585,
  };
  const splitter = {
    classList: classes(),
    attributes: new Map(),
    addEventListener: (name, handler) => listeners.set(name, handler),
    setAttribute(name, value) {
      this.attributes.set(name, value);
    },
    setPointerCapture() {},
    getBoundingClientRect() {
      const available = fleetSplit.clientWidth - 10;
      const basis =
        Number.parseFloat(agentsPane.style.flexBasis) || available * 0.42;
      return { left: 20 + fleetSplit.clientLeft + basis, width: 10 };
    },
  };
  const elements = { fleetSplit, ciPane, agentsPane, splitter };
  const body = { classList: classes() };
  const document = { body, documentElement: root };
  const window = { addEventListener() {} };
  const storage = new Map([["fleet.dashboard.split.v1", saved]]);
  const localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
  };
  const getComputedStyle = (element) => {
    if (element === root) {
      return {
        getPropertyValue(name) {
          return (
            rootStyle.get(name) ??
            {
              "--card-w": "260px",
              "--pane-gutter": "16px",
              "--splitter-hit": "10px",
            }[name] ??
            ""
          );
        },
      };
    }
    return { borderLeftWidth: "0px", borderRightWidth: "0px" };
  };
  const splitSource = script.slice(
    script.indexOf("// Resizable canvas."),
    script.indexOf("let VER=null;"),
  );
  const api = new Function(
    "$",
    "document",
    "window",
    "localStorage",
    "getComputedStyle",
    `${splitSource}; return {
      applySplit,
      paneMin,
      splitGeometry,
      DEFAULT_SPLIT,
      getRatio:()=>splitRatio,
    };`,
  )(
    (id) => elements[id],
    document,
    window,
    localStorage,
    getComputedStyle,
  );

  function fire(name, clientX, pointerId = 1) {
    const handler = listeners.get(name);
    assert.ok(handler, `missing ${name} handler`);
    handler({
      type: name,
      clientX,
      pointerId,
      preventDefault() {},
    });
  }

  function clickAt(clientX) {
    const box = splitter.getBoundingClientRect();
    if (clientX < box.left || clientX >= box.left + box.width) return false;
    fire("pointerdown", clientX);
    fire("pointerup", clientX);
    return true;
  }

  return {
    ...api,
    clickAt,
    elements,
    fire,
    rootStyle,
    saved: () => storage.get("fleet.dashboard.split.v1"),
  };
}

{
  const ui = splitHarness();
  const beforeLeft = ui.elements.splitter.getBoundingClientRect().left;
  const beforeSaved = ui.saved();
  for (let grab = 0; grab < 5; grab += 1) {
    const box = ui.elements.splitter.getBoundingClientRect();
    assert.equal(ui.clickAt(box.left + box.width / 2), true);
  }
  assert.equal(ui.elements.splitter.getBoundingClientRect().left, beforeLeft);
  assert.equal(ui.saved(), beforeSaved);
}

{
  const ui = splitHarness("0.69");
  const box = ui.elements.splitter.getBoundingClientRect();
  const cursorX = box.left + box.width / 2;
  const firstClick = ui.clickAt(cursorX);
  const secondClick = ui.clickAt(cursorX);
  if (firstClick && secondClick) ui.fire("dblclick", cursorX);
  assert.equal(firstClick && secondClick, true);
  assert.equal(ui.getRatio(), ui.DEFAULT_SPLIT);
  assert.equal(ui.saved(), String(ui.DEFAULT_SPLIT));
}

{
  const ui = splitHarness("0.42");
  const before = ui.elements.splitter.getBoundingClientRect();
  const grabX = before.left + 2;
  ui.fire("pointerdown", grabX);
  ui.fire("pointermove", grabX + 100);
  ui.fire("pointerup", grabX + 100);
  const after = ui.elements.splitter.getBoundingClientRect();
  assert.equal(after.left - before.left, 100);
  assert.equal(Number(ui.saved()), ui.getRatio());
}

{
  const ui = splitHarness("0.69");
  const beforeBasis = ui.elements.agentsPane.style.flexBasis;
  const beforeSaved = ui.saved();
  ui.elements.fleetSplit.clientWidth = 580;
  ui.applySplit(ui.getRatio());
  assert.equal(ui.elements.fleetSplit.classList.contains("stacked"), true);
  assert.equal(ui.saved(), beforeSaved);
  ui.elements.fleetSplit.clientWidth = 1358;
  ui.applySplit(ui.getRatio());
  assert.equal(ui.elements.fleetSplit.classList.contains("stacked"), false);
  assert.equal(ui.elements.agentsPane.style.flexBasis, beforeBasis);
  assert.equal(ui.saved(), beforeSaved);
}

{
  const ui = splitHarness("0.42");
  assert.equal(ui.paneMin(), 260 + 2 * 16 + 15);
  assert.equal(ui.rootStyle.get("--pane-scrollbar-w"), "15px");
  assert.equal(
    ui.splitGeometry().available,
    ui.elements.fleetSplit.clientWidth - 10,
  );
}

// Read-only means every control that writes looks disabled, the Auto button included: it was
// the one clickable thing left bright on a page that refuses writes, and a click that silently
// does nothing reads as a broken dashboard.
{
  const rule = html.match(/body\.readonly[^{]*\{[^}]*\}/);
  assert.ok(rule, "a body.readonly rule must exist");
  for (const selector of [".modeseg button", ".autobtn", ".acct-rm", "#acct-add-btn", "[data-act]"]) {
    assert.ok(
      rule[0].includes(`body.readonly ${selector}`),
      `read-only mode must dim ${selector}`,
    );
  }
  assert.match(rule[0], /cursor:not-allowed/);
}

console.log("dashboard UI contract ok");

/* The token arrives as `#token=` as well as `?token=`, and is stripped from the address at once.
   `/murmur:farm open` hands the token over in the fragment, which never reaches the server or
   its log. Run without a browser: `location`, `history` and `sessionStorage` are stubbed, and
   each case imports a fresh copy of the module. */

import assert from "node:assert/strict";

let failures = 0;

async function tokenFrom(url) {
  const parsed = new URL(url);
  const replaced = [];
  const stored = new Map();
  globalThis.location = { search: parsed.search, hash: parsed.hash, pathname: parsed.pathname };
  globalThis.history = { replaceState: (_state, _title, next) => replaced.push(next) };
  globalThis.sessionStorage = {
    getItem: (key) => (stored.has(key) ? stored.get(key) : null),
    setItem: (key, value) => stored.set(key, String(value)),
  };
  const api = await import(`./static/core/api.js?case=${Math.random()}`);
  return { value: api.token(), again: api.token(), replaced, stored };
}

async function check(name, body) {
  try {
    await body();
    console.log(`ok    ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`FAIL  ${name}\n      ${error.message}`);
  }
}

await check("a fragment token is taken, kept for the tab and stripped", async () => {
  const seen = await tokenFrom("http://127.0.0.1:7878/#token=CANARY-fragment");
  assert.equal(seen.value, "CANARY-fragment");
  assert.equal(seen.again, "CANARY-fragment");
  assert.equal(seen.stored.get("murmur.token"), "CANARY-fragment");
  assert.deepEqual(seen.replaced, ["/"]);
});

await check("the rest of the fragment stays where it was", async () => {
  const seen = await tokenFrom("http://127.0.0.1:7878/?view=1#token=abc&x=2");
  assert.equal(seen.value, "abc");
  assert.deepEqual(seen.replaced, ["/?view=1#x=2"]);
});

await check("a query token still works and leaves a route fragment alone", async () => {
  const seen = await tokenFrom("http://127.0.0.1:7878/?token=q-token#/board");
  assert.equal(seen.value, "q-token");
  assert.deepEqual(seen.replaced, ["/#/board"]);
});

await check("a route fragment without a token is never rewritten", async () => {
  const seen = await tokenFrom("http://127.0.0.1:7878/#/machines?section=x");
  assert.equal(seen.value, "");
  assert.deepEqual(seen.replaced, []);
});

if (failures) {
  console.log(`${failures} failed`);
  process.exit(1);
}
console.log("all passed");

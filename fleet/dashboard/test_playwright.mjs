/* One way to find a chromium on this machine, shared by the browser checks. playwright is not
   vendored here: take it from FLEET_PLAYWRIGHT, from the usual resolution, or from a copy npx
   has already unpacked, and accept only a copy whose browser is actually downloaded. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export async function loadPlaywright() {
  const sources = [process.env.FLEET_PLAYWRIGHT, "playwright", "playwright-core"].filter(Boolean);
  const cache = path.join(os.homedir(), ".npm", "_npx");
  for (const entry of fs.existsSync(cache) ? fs.readdirSync(cache) : []) {
    for (const name of ["playwright", "playwright-core"]) {
      const candidate = path.join(cache, entry, "node_modules", name, "index.mjs");
      if (fs.existsSync(candidate)) sources.push(candidate);
    }
  }
  for (const source of sources) {
    try {
      const loaded = await import(source);
      if (fs.existsSync(loaded.chromium.executablePath())) return loaded;
    } catch (error) { /* try the next one */ }
  }
  throw new Error("playwright has no chromium. Run: npx playwright install chromium");
}

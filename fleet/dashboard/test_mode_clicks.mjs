// Click the load buttons like a human and require the page to SAY what happened to memory, and the
// machine to actually do it. A label that changes while nothing else does is the failure mode.
// playwright-core is not vendored here. Resolve it normally, or point FLEET_PLAYWRIGHT at a
// copy that already exists on the machine (any project's node_modules/playwright-core/index.mjs).
const { chromium } = await import(process.env.FLEET_PLAYWRIGHT || 'playwright-core')
import { execSync } from 'node:child_process'

const URL = process.env.DASH_URL || 'http://127.0.0.1:7878'
const R = []
const check = (n, p, d) => { R.push({ n, p }); console.log(`${p ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + d : ''}`) }
const memHigh = (s) => execSync(`systemctl --user show ${s} -p MemoryHigh --value`).toString().trim()
const pgUp = () => execSync("docker ps --filter name=^fleet-ci-postgres$ --format '{{.Names}}'").toString().trim() === 'fleet-ci-postgres'

const b = await chromium.launch()
const p = await b.newPage()
await p.goto(URL, { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(2000)

const label = async () => (await p.locator('#modesel').innerText()).replace(/\s+/g, ' ').trim()

check('the load buttons are on the page', await p.locator('#modesel button[data-m]').count() > 0,
      `${await p.locator('#modesel button[data-m]').count()} buttons`)

// --- click the most aggressive stop: 20%
await p.locator('#modesel button[data-m="hard"]').click()
await p.waitForTimeout(2500)
const hardLabel = await label()
check('clicking 20% says what it did to RAM', /RAM capped at [\d.]+GB/.test(hardLabel), hardLabel)
check('...and the cap is really on the slice', memHigh('fleet.slice') !== 'infinity',
      `MemoryHigh=${memHigh('fleet.slice')}`)
check('...and the test database was actually released', !pgUp() && /test DB released/.test(hardLabel),
      `pg_running=${pgUp()}`)

// --- back to full
await p.locator('#modesel button[data-m="full"]').click()
await p.waitForTimeout(2500)
const fullLabel = await label()
check('clicking full removes the cap', /RAM uncapped/.test(fullLabel), fullLabel)
check('...and the slice is really uncapped', memHigh('fleet.slice') === 'infinity',
      `MemoryHigh=${memHigh('fleet.slice')}`)

// --- auto is what runs while he plays
await p.locator('#modesel button[data-m="auto"]').click()
await p.waitForTimeout(2000)
check('auto is selectable and reports a state', /Auto/.test(await label()), await label())

await b.close()
const bad = R.filter(r => !r.p)
console.log(`\nRESULT: ${R.length - bad.length}/${R.length} passed`)
if (bad.length) process.exit(1)

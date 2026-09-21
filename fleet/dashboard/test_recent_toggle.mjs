// Clicking Recent must open the list on the spot. The pointer is over the pane when you click it,
// so a render guard keyed on "is the pane busy" will otherwise swallow exactly the repaint the
// click asked for, and the list appears only once the mouse leaves.
// playwright-core is not vendored here. Resolve it normally, or point FLEET_PLAYWRIGHT at a
// copy that already exists on the machine (any project's node_modules/playwright-core/index.mjs).
const { chromium } = await import(process.env.FLEET_PLAYWRIGHT || 'playwright-core')

const URL = process.env.DASH_URL || 'http://127.0.0.1:7901'
const R = []
const check = (n, p, d) => { R.push({ n, p }); console.log(`${p ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + d : ''}`) }

const b = await chromium.launch()
const p = await b.newPage()
await p.goto(URL, { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(1500)

const visible = () => p.evaluate(() =>
  [...document.querySelectorAll('.ci-card')].filter(c => c.getClientRects().length).length)

check('Recent starts collapsed', await visible() === 0, `${await visible()} cards visible`)

// click and DO NOT move the pointer away - that is the whole point
await p.locator('#ciRecentToggle').click()
await p.waitForTimeout(400)
const afterOpen = await visible()
check('a click opens the list at once, with the pointer left where it was', afterOpen > 0,
      `${afterOpen} cards`)

await p.locator('#ciRecentToggle').click()
await p.waitForTimeout(400)
const afterClose = await visible()
check('a second click collapses it at once', afterClose === 0, `${afterClose} cards`)

// and the poll must still be deferred while hovering, or the earlier fix is undone
await p.locator('#ciRecentToggle').click()
await p.waitForTimeout(400)
const marked = await p.evaluate(() => {
  document.querySelectorAll('.ci-card').forEach((el, i) => { el.dataset.mark = 'm' + i })
  return document.querySelectorAll('.ci-card[data-mark]').length
})
const box = await p.locator('.ci-card').first().boundingBox()
await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
await p.waitForTimeout(4000)
const survived = await p.evaluate(() => document.querySelectorAll('.ci-card[data-mark]').length)
check('polling still does not rebuild the pane under the pointer', survived === marked,
      `${survived}/${marked} survived`)

await b.close()
const bad = R.filter(r => !r.p)
console.log(`\nRESULT: ${R.length - bad.length}/${R.length} passed`)
if (bad.length) process.exit(1)

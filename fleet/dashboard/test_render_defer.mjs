// The pane must not rebuild itself while it is being used. Without this, a click lands on a node
// the poll has already replaced - which is a lost click for a human and an "element was detached
// from the DOM" timeout for anything automated.
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

// Recent starts collapsed by design, so its cards have no box to hover until it is opened.
await p.evaluate(() => {
  const t=document.getElementById('ciRecentToggle')
  if (t) t.click()
})
await p.waitForTimeout(700)

// Stamp every card so a rebuild is detectable: a re-render replaces the nodes and loses the mark.
const stamp = async () => p.evaluate(() => {
  document.querySelectorAll('.ci-card').forEach((el, i) => { el.dataset.mark = 'm' + i })
  return document.querySelectorAll('.ci-card[data-mark]').length
})
const surviving = async () => p.evaluate(() =>
  document.querySelectorAll('.ci-card[data-mark]').length)

const marked = await stamp()
check('cards are present to observe', marked > 0, `${marked} cards`)

// 1. idle: the poll is expected to redraw, so the marks are expected to go
await p.mouse.move(5, 5)
await p.waitForTimeout(4000)
const idleLeft = await surviving()
check('an idle pane still refreshes (the guard is not a freeze)', idleLeft === 0,
      `${idleLeft}/${marked} marks survived idle`)

// 2. hovered: the redraw must be deferred, so the marks must survive
await stamp()
const box = await p.locator('.ci-card').first().boundingBox()
await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
await p.waitForTimeout(4000)
const hoverLeft = await surviving()
check('a hovered pane is NOT rebuilt under the pointer', hoverLeft === marked,
      `${hoverLeft}/${marked} marks survived hover`)

// 3. and it resumes once the pointer leaves
await p.mouse.move(5, 5)
await p.waitForTimeout(4000)
const afterLeft = await surviving()
check('rendering resumes after the pointer leaves', afterLeft === 0,
      `${afterLeft}/${marked} marks survived`)

await b.close()
const bad = R.filter(r => !r.p)
console.log(`\nRESULT: ${R.length - bad.length}/${R.length} passed`)
if (bad.length) process.exit(1)

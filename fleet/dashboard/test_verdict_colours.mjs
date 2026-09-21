// playwright-core is not vendored here. Resolve it normally, or point FLEET_PLAYWRIGHT at a
// copy that already exists on the machine (any project's node_modules/playwright-core/index.mjs).
const { chromium } = await import(process.env.FLEET_PLAYWRIGHT || 'playwright-core')
const URL = process.env.DASH_URL || "http://127.0.0.1:7901"
const R=[]; const check=(n,p,d)=>{R.push({n,p});console.log(`${p?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`)}
const hue = (c) => { const m=c.match(/\d+/g); if(!m) return 'none'
  const [r,g,b]=m.map(Number)
  if (Math.abs(r-g)<18 && Math.abs(g-b)<18) return 'grey'
  if (g>r+25 && g>b+15) return 'green'
  if (r>g+40 && g>b+15) return 'amber'
  if (r>g+50) return 'red'
  if (b>r+30) return 'blue'
  return `other(${r},${g},${b})` }

const b = await chromium.launch()
const p = await (await b.newContext({viewport:{width:1600,height:1100},colorScheme:'dark'})).newPage()
await p.goto(URL,{waitUntil:'domcontentloaded'}); await p.waitForTimeout(1600)

// Recent must be COLLAPSED on first load
const rec = await p.evaluate(() => {
  const secs=[...document.querySelectorAll('.ci-pane section, .ci-pane details, [id*=Recent], [id*=recent]')]
  const el = secs.find(s => /recent/i.test(s.textContent.slice(0,40))) || document.getElementById('ciRecentSection')
  if (!el) return {found:false}
  const cards = el.querySelectorAll('.ci-card').length
  const visible = [...el.querySelectorAll('.ci-card')].filter(c=>c.getBoundingClientRect().height>0).length
  return {found:true, tag:el.tagName.toLowerCase(), open:el.open, cards, visible}
})
check('Recent starts collapsed', rec.found && (rec.open===false || rec.visible===0),
      JSON.stringify(rec))

// Running/Queued must NOT be collapsed
const rq = await p.evaluate(() => {
  const out={}
  for (const key of ['Running','Queued']) {
    const el=[...document.querySelectorAll('.ci-pane section, .ci-pane details')]
      .find(s=>new RegExp(key,'i').test(s.textContent.slice(0,30)))
    out[key]= el ? (el.tagName.toLowerCase()==='details' ? el.open!==false : true) : null
  }
  return out })
check('Running/Queued stay expanded', rq.Running!==false && rq.Queued!==false, JSON.stringify(rq))

// expand Recent, then measure the colour of each verdict
await p.evaluate(() => {
  const el=[...document.querySelectorAll('details')].find(s=>/recent/i.test(s.textContent.slice(0,40)))
  if (el) el.open = true
  const h=[...document.querySelectorAll('.ci-pane h4, .ci-pane summary, .sechead')].find(x=>/recent/i.test(x.textContent))
  if (h) h.click()
})
await p.waitForTimeout(700)

const colors = await p.evaluate(() => {
  const out={}
  for (const card of document.querySelectorAll('.ci-card, .ci-card-toggle')) {
    const t=card.innerText
    const chip=card.querySelector('.cistate, .state, [class*=state]')
    const cs=getComputedStyle(card)
    // Classify by CLASS, not by text: a RUNNING card contains "backend · passed" in its tier
    // strip, so text matching picked the wrong card and measured the wrong colour.
    const cls = card.className || ''
    const key = /\bpassed_partial\b/.test(cls) ? 'passed_partial'
      : /\bejected\b/.test(cls) ? 'ejected' : /\bcancell?ed\b/.test(cls) ? 'cancelled'
      : /\bblocked\b/.test(cls) ? 'blocked'
      : /\bfailed\b/.test(cls) ? 'failed' : /\bpassed\b/.test(cls) ? 'passed' : null
    if (key && !out[key]) out[key]={chip: chip?getComputedStyle(chip).color:null,
                                    border: cs.borderLeftColor}
  }
  return out })
for (const [state, want] of [['passed','green'],['passed_partial','amber'],
                             ['failed','red'],['ejected','grey'],['cancelled','grey'],
                             ['blocked','amber']]) {
  const c = colors[state]
  const got = c ? [hue(c.chip||''), hue(c.border||'')] : null
  check(`${state} is ${want}`, !!c && !!got && got.every(g => g === want),
        // Both, not either: chip alone passed while the border was red, which is how a
        // colour regression hides behind a test that prints the value it does not check.
        c ? `chip=${c.chip} border=${c.border} -> ${got}` : 'card not rendered')
}
await b.close()
const bad=R.filter(r=>!r.p)
console.log(`\nRESULT: ${R.length-bad.length}/${R.length} passed`)
if (bad.length) process.exit(1)

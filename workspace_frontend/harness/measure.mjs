// DEV-ONLY: measure the intrinsic width of the text cells so column tracks can
// be sized from evidence instead of guessing.
const pw = await import(process.env.PW_PATH || 'playwright')
const chromium = (pw.chromium || pw.default?.chromium)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
await page.goto('http://localhost:5199/assets/production_app/workspace/layout-harness.html', { waitUntil: 'networkidle' })
await page.waitForSelector('.wo-row')

const out = await page.evaluate(() => {
  const measure = (el) => {
    const r = document.createRange()
    r.selectNodeContents(el)
    return Math.ceil(r.getBoundingClientRect().width)
  }
  const res = {}
  const seBody = document.querySelectorAll('.wo-body')[1]
  const woBody = document.querySelectorAll('.wo-body')[0]
  // widest single-line content per cell class (clone into an unconstrained box)
  const widest = (body, sel) => {
    let max = 0, sample = ''
    body.querySelectorAll(sel).forEach((c) => {
      const probe = c.cloneNode(true)
      probe.style.cssText = 'position:absolute;left:-9999px;top:0;white-space:nowrap;width:auto;max-width:none'
      document.body.appendChild(probe)
      const w = measure(probe)
      probe.remove()
      if (w > max) { max = w; sample = c.textContent.trim().slice(0, 30) }
    })
    return { px: max, sample }
  }
  res.wo = {
    id: widest(woBody, '.c-id'),
    adonan: widest(woBody, '.c-adonan'),
    prod: widest(woBody, '.c-prod'),
    date: widest(woBody, '.c-date'),
    status: widest(woBody, '.c-status'),
    stage: widest(woBody, '.c-stage'),
    qty: widest(woBody, '.c-qty')
  }
  res.se = {
    doc: widest(seBody, '.c-doc'),
    item: widest(seBody, '.c-item'),
    qty: widest(seBody, '.c-qty'),
    wo: widest(seBody, '.c-wo'),
    batch: widest(seBody, '.c-batch'),
    owner: widest(seBody, '.c-owner'),
    status: widest(seBody, '.c-status')
  }
  return res
})
console.log(JSON.stringify(out, null, 2))
await browser.close()

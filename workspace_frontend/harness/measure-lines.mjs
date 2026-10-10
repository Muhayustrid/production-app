// DEV-ONLY: per-LINE intrinsic widths for the multi-line cells (doc/prod/owner),
// measured by rendering each text node on a short nowrap probe.
const pw = await import(process.env.PW_PATH || 'playwright')
const chromium = (pw.chromium || pw.default?.chromium)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
await page.goto('http://localhost:5199/assets/production_app/workspace/layout-harness.html', { waitUntil: 'networkidle' })
await page.waitForSelector('.wo-row')

const out = await page.evaluate(() => {
  const probeWidth = (text, styleSource) => {
    const probe = document.createElement('span')
    probe.textContent = text
    probe.style.cssText = 'position:absolute;left:-9999px;top:0;white-space:nowrap'
    const cs = getComputedStyle(styleSource)
    probe.style.font = cs.font
    probe.style.fontFamily = cs.fontFamily
    probe.style.fontSize = cs.fontSize
    probe.style.fontWeight = cs.fontWeight
    probe.style.letterSpacing = cs.letterSpacing
    document.body.appendChild(probe)
    const w = Math.ceil(probe.getBoundingClientRect().width)
    probe.remove()
    return w
  }
  const perLine = (cell) => {
    // measure each descendant text node individually
    const parts = []
    const walk = (n) => {
      if (n.nodeType === 3 && n.textContent.trim()) {
        parts.push({ text: n.textContent.trim().slice(0, 26), px: probeWidth(n.textContent.trim(), n.parentElement) })
      }
      n.childNodes.forEach(walk)
    }
    walk(cell)
    return parts
  }
  const worst = (body, sel) => {
    let best = { px: 0 }
    body.querySelectorAll(sel).forEach((c) => {
      perLine(c).forEach((p) => { if (p.px > best.px) best = { ...p, cell: sel } })
    })
    return best
  }
  const seBody = document.querySelectorAll('.wo-body')[1]
  const woBody = document.querySelectorAll('.wo-body')[0]
  return {
    se: { doc: worst(seBody, '.c-doc'), item: worst(seBody, '.c-item'), owner: worst(seBody, '.c-owner'), wo: worst(seBody, '.c-wo'), batch: worst(seBody, '.c-batch') },
    wo: { id: worst(woBody, '.c-id'), prod: worst(woBody, '.c-prod'), date: worst(woBody, '.c-date'), status: worst(woBody, '.c-status'), stage: worst(woBody, '.c-stage'), qty: worst(woBody, '.c-qty') }
  }
})
console.log(JSON.stringify(out, null, 2))
await browser.close()

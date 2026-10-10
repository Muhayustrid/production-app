// DEV-ONLY: capture the layout harness at the widths that matter.
// Usage: node harness/shoot.mjs <label>   (label = "before" | "after")
import { mkdirSync } from 'node:fs'

// DEV-ONLY: playwright lives in a scratch dir (/tmp/layoutharness) so the app's
// package.json stays clean; resolve it from there explicitly.
// The CJS build only exposes a default export, so unwrap it.
const pw = await import(process.env.PW_PATH || 'playwright')
const chromium = (pw.chromium || pw.default?.chromium)

const label = process.argv[2] || 'shot'
const OUT = (process.env.SHOTS_OUT || new URL('./shots/', import.meta.url).pathname).replace(/\/?$/, '/')
mkdirSync(OUT, { recursive: true })

const PAGE_URL = 'http://localhost:5199/assets/production_app/workspace/layout-harness.html'
const WIDTHS = [
  { name: '1400', w: 1400, h: 1250 },
  { name: '1180', w: 1180, h: 1250 },
  { name: '820', w: 820, h: 1500 }
]

const browser = await chromium.launch()
for (const { name, w, h } of WIDTHS) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 })
  await page.goto(PAGE_URL, { waitUntil: 'networkidle' })
  await page.waitForSelector('.wo-row', { timeout: 15000 })
  await page.waitForTimeout(400)

  // Full page (both tables) + per-table crops for close inspection.
  await page.screenshot({ path: `${OUT}${label}-${name}-full.png`, fullPage: true })
  const bodies = page.locator('.wo-body')
  await bodies.nth(0).screenshot({ path: `${OUT}${label}-${name}-wo.png` })
  await bodies.nth(1).screenshot({ path: `${OUT}${label}-${name}-se.png` })
  if (await bodies.count() > 2) await bodies.nth(2).screenshot({ path: `${OUT}${label}-${name}-fo.png` })

  // Report the measured column tracks + first-row text metrics.
  const geom = await page.evaluate(() => {
    const out = {}
    document.querySelectorAll('.wo-body').forEach((b, bi) => {
      const head = b.querySelector('.wo-thead')
      const row = b.querySelector('.wo-row:not(.wo-thead)')
      const key = bi === 0 ? 'wo' : 'se'
      out[key] = {
        bodyWidth: Math.round(b.getBoundingClientRect().width),
        scrollWidth: b.scrollWidth,
        headTracks: getComputedStyle(head).gridTemplateColumns,
        rowTracks: getComputedStyle(row).gridTemplateColumns
      }
      // how many lines does the first identifier cell take?
      const idCell = row.querySelector(bi === 0 ? '.c-id' : '.c-doc')
      const cs = getComputedStyle(idCell)
      out[key].idHeight = Math.round(idCell.getBoundingClientRect().height)
      out[key].idLineHeight = parseFloat(cs.lineHeight) || null
      out[key].idText = idCell.textContent.trim().slice(0, 24)
    })
    return out
  })
  console.log(`\n### width ${name}`)
  console.log(JSON.stringify(geom, null, 2))
  await page.close()
}
await browser.close()
console.log(`\nshots written to ${OUT}`)

// Pure box-allocation helpers (T37). UX checks only — server validation
// (production_app.api.handover.create_request, T35) remains authoritative.
import { fmtNum } from './format.js'

// Server default for the whole-Pack integral tolerance: handover._expected_pack_count
// uses wo.precision('produced_qty') or 3 -> tolerance = 0.5 * 10^-precision.
const DEFAULT_PRECISION = 3

// Why the Pack count is unavailable: 'conversion' = missing/invalid Pack
// conversion (displayUom/factor), 'fractional' = valid conversion but the
// Work Order output does not form whole Packs, null = count available.
export function packProblem(lot, precision = DEFAULT_PRECISION) {
  if (!lot || lot.displayUom !== 'Pack') return 'conversion'
  const factor = Number(lot.qtyInPack)
  if (!Number.isFinite(factor) || factor <= 0) return 'conversion'
  const raw = Number(lot.producedQty) / factor
  if (!Number.isFinite(raw) || raw < 0) return 'fractional'
  const tolerance = 0.5 * 10 ** -precision
  if (Math.abs(raw - Math.round(raw)) >= tolerance) return 'fractional'
  return null
}

// Whole Pack count the WO's full produced qty allocates into, or null when
// packProblem says conversion/fractional — never a factor=1 fallback (mirrors
// handover._expected_pack_count).
export function expectedPacks(lot, precision = DEFAULT_PRECISION) {
  if (packProblem(lot, precision)) return null
  return Math.round(Number(lot.producedQty) / Number(lot.qtyInPack))
}

// Mirror of handover._validate_box_allocation: Box 1 kg + Pack positive;
// Box 2 exactly 0/0 or positive/positive; Pack sum must equal `expected`
// exactly. Returns field-keyed error strings ('' -> untouched, invalid text
// -> rejected); expected=null (invalid conversion) skips only the sum check.
export function validateBoxAllocation(form, expected) {
  const errors = {}
  const num = (v) => {
    const s = String(v ?? '').trim()
    if (s === '') return null
    const n = Number(s)
    return Number.isFinite(n) ? n : NaN
  }
  const kg1 = num(form.box1)
  const packs1 = num(form.box1Pack)
  const kg2 = num(form.box2)
  const packs2 = num(form.box2Pack)
  if (kg1 == null || kg1 <= 0) errors.box1 = 'Box 1: berat kg wajib diisi dan positif.'
  if (packs1 == null || packs1 <= 0 || !Number.isInteger(packs1))
    errors.box1Pack = 'Box 1: jumlah Pack wajib bilangan bulat positif.'
  const kg2Filled = kg2 != null && kg2 > 0
  const packs2Filled = packs2 != null && packs2 > 0
  if (kg2 != null && kg2 < 0)
    errors.box2 = 'Box 2: berat kg harus angka non-negatif yang valid.'
  else if (kg2Filled !== packs2Filled)
    errors.box2 = 'Box 2 harus kosong (0 kg / 0 Pack) atau terisi keduanya.'
  else if (packs2Filled && !Number.isInteger(packs2))
    errors.box2Pack = 'Box 2: jumlah Pack wajib bilangan bulat.'
  if (
    expected != null &&
    Number.isInteger(packs1) && packs1 > 0 &&
    (packs2 == null || Number.isInteger(packs2)) &&
    packs1 + (packs2 ?? 0) !== expected
  ) errors.total = `Jumlah Pack Box 1 + Box 2 (${packs1 + (packs2 ?? 0)}) harus tepat ${expected} Pack.`
  return errors
}

// kg + Pack summary for Request/Terkirim cards and the send confirmation, e.g.
// "Box 1: 12.5 kg · 20 Pack\nBox 2: 8 kg · 19 Pack" ('' = no allocation).
// Pre-cutover rows carry kg without Pack — shown honestly, never invented.
export function boxAllocationText(row) {
  if (!row) return ''
  const lines = []
  for (const [n, kg, packs] of [[1, row.box1, row.box1Pack], [2, row.box2, row.box2Pack]]) {
    if (kg == null && packs == null) continue
    const parts = [
      kg == null ? null : `${fmtNum(kg)} kg`,
      packs == null ? null : `${fmtNum(packs)} Pack`
    ].filter(Boolean)
    lines.push(`Box ${n}: ${parts.join(' · ')}`)
  }
  return lines.join('\n')
}

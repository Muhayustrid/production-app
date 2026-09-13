// Stock quantities are authoritative; display UOM and factor come from Item metadata.
export const fmtInt = n => Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: 6 }) : '—'
export const fmtNum = fmtInt
export function hasAlternate(units) {
  return !!units?.displayUom && units.displayUom !== units.stockUom && Number.isFinite(units.qtyInPack) && units.qtyInPack > 0
}
export function packParts(qty, units) {
  if (!hasAlternate(units) || !Number.isFinite(qty)) return { str: '—', approx: false }
  const value = qty / units.qtyInPack
  const rounded = Math.round(value * 10000) / 10000
  return { str: fmtInt(rounded), approx: Math.abs(value - rounded) > 1e-9 }
}
export const packStr4 = packParts
export function qtyStack(qty, units) {
  const stock = `${fmtInt(qty)} ${units.stockUom || ''}`
  if (!hasAlternate(units)) return { main: stock, sub: '' }
  const { str, approx } = packParts(qty, units)
  return { main: `${approx ? '≈ ' : ''}${str} ${units.displayUom}`, sub: stock }
}
export function qtyMain(qty, units) {
  const { main, sub } = qtyStack(qty, units)
  return sub ? `${main} · ${sub}` : main
}
export function pcsToText(qty, unit, units) {
  if (qty == null) return { text: '', approx: false }
  if (unit === 'pcs' || !hasAlternate(units)) return { text: String(qty), approx: false }
  const value = qty / units.qtyInPack
  const rounded = Math.round(value * 10000) / 10000
  return { text: String(rounded), approx: Math.abs(value - rounded) > 1e-9 }
}
export function parseQtyText(text, unit, units) {
  const fail = error => ({ value: null, error, warn: null })
  if (String(text ?? '').trim() === '') return fail(null)
  const value = Number(String(text).replace(',', '.'))
  if (!Number.isFinite(value) || value < 0) return fail('Angka tidak valid.')
  if (unit === 'pack' && !hasAlternate(units)) return fail('Konversi satuan belum tersedia; gunakan satuan stok.')
  let qty = unit === 'pack' ? value * units.qtyInPack : value
  if (!Number.isFinite(qty)) return fail('Angka tidak valid.')
  if (units.wholeNumber) {
    const rounded = Math.round(qty)
    if (Math.abs(qty - rounded) > 1e-8) return fail(`${units.stockUom} harus bilangan bulat.`)
    qty = rounded
  }
  const fraction = qty / units.qtyInPack
  const warn = hasAlternate(units) && Math.abs(fraction - Math.round(fraction)) > 1e-8
    ? `Bukan kelipatan 1 ${units.displayUom}` : null
  return { value: qty, error: null, warn }
}

export function fmtDate(iso, short = false) {
  if (!iso) return '-'
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('id-ID', short
    ? { day: 'numeric', month: 'short' }
    : { day: 'numeric', month: 'short', year: 'numeric' })
}

export function fmtStampShort(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return `${d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} · ${t}`
}


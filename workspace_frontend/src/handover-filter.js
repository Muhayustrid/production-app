// FU50: filter mode tabel Stock Entry — murni, ter-test. Status meniru
// laneStatusMeta (form-order.js): kunci stabil utk <select> + predikat baris.
export function rowStatusKey(r) {
  if (r.lane === 'terkirim') return 'terkirim'
  if (r.flag === 'stopped') return 'stopped'
  if (r.flag === 'cancelled') return 'cancelled'
  if (r.flag === 'draft') return 'draft'
  if (r.lane === 'request') return 'request'
  return '-'
}

// opsi Item dari data papan: unik per nama, urut abjad
export function distinctItems(rows) {
  const seen = new Map()
  for (const r of rows) {
    if (r.item && !seen.has(r.item)) seen.set(r.item, r.itemCode || '')
  }
  return [...seen.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, code]) => ({ name, code }))
}

// predikat baris tabel: {status, item, from, to} — 'all'/'' berarti tidak
// memfilter. Tanggal dari createdAt (YYYY-MM-DD); baris tanpa tanggal
// dikecualikan saat rentang aktif (pola filter lot Cold Storage).
export function filterSerahRows(rows, f) {
  const status = f.status && f.status !== 'all' ? f.status : ''
  const item = f.item && f.item !== 'all' ? f.item : ''
  const dateActive = !!(f.from || f.to)
  return rows.filter((r) => {
    if (status && rowStatusKey(r) !== status) return false
    if (item && r.item !== item) return false
    if (dateActive) {
      const day = (r.createdAt || '').slice(0, 10)
      if (!day) return false
      if (f.from && day < f.from) return false
      if (f.to && day > f.to) return false
    }
    return true
  })
}

export function serahFilterCount(f) {
  return (f.status && f.status !== 'all' ? 1 : 0)
    + (f.item && f.item !== 'all' ? 1 : 0)
    + (f.from ? 1 : 0)
    + (f.to ? 1 : 0)
}

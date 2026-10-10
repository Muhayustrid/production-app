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

// MR bulk = satu baris tabel: qty dijumlah, kolom WO jadi "N WO".
// Dikirim utuh oleh send_handover, jadi tidak ada aksi per-WO.
export function groupByRequest(rows) {
  const groups = new Map()
  for (const r of rows) {
    const key = r.materialRequest || r.id
    const g = groups.get(key)
    if (!g) groups.set(key, { ...r, workOrders: [r.workOrder] })
    else {
      g.workOrders.push(r.workOrder)
      g.requestedQtyPcs = (g.requestedQtyPcs ?? 0) + (r.requestedQtyPcs ?? 0)
      g.workOrder = `${g.workOrders.length} WO`
    }
  }
  return [...groups.values()]
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

// predikat baris tabel: {statuses[], items[], from, to} — array KOSONG/'' =
// tidak memfilter (FU103: multi-nilai ala ERPNext — IN dalam satu field,
// AND antar field; pola FU100). Tanggal dari createdAt (YYYY-MM-DD); baris
// tanpa tanggal dikecualikan saat rentang aktif (pola filter lot Cold Storage).
export function filterSerahRows(rows, f) {
  const statuses = (f?.statuses || []).filter(Boolean)
  const items = (f?.items || []).filter(Boolean)
  const dateActive = !!(f?.from || f?.to)
  return rows.filter((r) => {
    if (statuses.length && !statuses.includes(rowStatusKey(r))) return false
    if (items.length && !items.includes(r.item)) return false
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
  // FU79d/FU103: rentang tanggal = SATU baris filter; field multi = satu
  // baris walau banyak nilai (badge menghitung BARIS, bukan nilai)
  return (f?.statuses?.length ? 1 : 0)
    + (f?.items?.length ? 1 : 0)
    + (f?.from || f?.to ? 1 : 0)
}

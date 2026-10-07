const VIEWS = new Set(['tabel', 'kanban'])

// nilai array bersih: array asli disaring, skalar jadi satu anggota
const arr = (v) =>
  (Array.isArray(v) ? v : v == null || v === '' ? [] : [v])
    .map((x) => String(x ?? '').trim())
    .filter(Boolean)

export function normalizeWorkOrderPreferences(values = {}) {
  const legacy = (key, fallback) => {
    // FU100: bentuk baru = array; preferensi lama (FU93, skalar 'all'/kode)
    // jadi sumber fallback bila array baru belum ada — 'all' dibuang
    const fresh = arr(values[key])
    if (fresh.length) return fresh
    const old = values[fallback]
    return old && old !== 'all' ? [String(old)] : []
  }
  return {
    q: values.q || '',
    products: legacy('products', 'product'),
    statuses: legacy('statuses', 'status'),
    stages: legacy('stages', 'stage').map((s) => (s === 'done' ? 'selesai' : s)),
    from: values.from || '',
    to: values.to || '',
    pageSize: values.pageSize,
    filterOpen: !!values.filterOpen,
    view: VIEWS.has(values.view) ? values.view : 'tabel'
  }
}

export function buildWorkOrderPreferences(values) {
  return normalizeWorkOrderPreferences(values)
}

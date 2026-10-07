// FU100: model filter ERPNext-style (pilot halaman Work Order) — murna,
// tanpa import Vue agar dites langsung (pola form-order.js).
//
// Satu key = satu baris filter; nilai SELALU array (multi-value = IN di
// server) kecuali type 'range' (objek {dari, sampai} milik RangeField).
// Field tak aktif = tidak punya key. Company TIDAK termasuk di sini —
// tetap filter global FU95 di companyFilterState.

// Rapikan draft/applied: buang key asing, skalar jadi array, kosong dihapus.
// Skalar 'all' (sentinel select lama) sengaja TIDAK dikenai — penebar lama
// memetakannya sebelum masuk sini (lihat work-order-preferences.js).
export function normalizeFilters(raw, fields) {
  const out = {}
  const known = new Set((fields || []).map((f) => f.key))
  for (const [key, value] of Object.entries(raw || {})) {
    if (!known.has(key)) continue
    const field = fields.find((f) => f.key === key)
    if (field?.type === 'range') {
      const dari = String(value?.dari ?? '')
      const sampai = String(value?.sampai ?? '')
      if (dari || sampai) out[key] = { dari, sampai }
      continue
    }
    // FU107: nilai TUNGGAL (mis. Company) — teks, bukan array; kosong
    // (mis. 'Semua company') = baris tidak aktif dan tidak ikut tersimpan
    if (field?.type === 'select') {
      const v = String(value ?? '').trim()
      if (v) out[key] = v
      continue
    }
    const list = Array.isArray(value) ? value : value == null || value === '' ? [] : [value]
    const clean = [...new Set(list.map((v) => String(v ?? '').trim()).filter(Boolean))]
    if (clean.length) out[key] = clean
  }
  return out
}

// FU102: salinan satu level draft/applied. Array (nilai MultiSelect) dan
// objek rentang WAJIB dilepas dari sumbernya — dengan salinan dangkal,
// v-model draft[key].dari menulis objek yang sama dengan applied sehingga
// draft terpakai sebelum Terapkan (dan sameFilters selalu menganggap sama).
export function cloneFilters(raw) {
  const out = {}
  for (const [key, value] of Object.entries(raw || {})) {
    out[key] = Array.isArray(value) ? [...value] : value && typeof value === 'object' ? { ...value } : value
  }
  return out
}

// badge filter = jumlah BARIS aktif (bukan jumlah nilai terpilih)
export function countFilters(filters) {
  return Object.keys(filters || {}).length
}

// bandingkan draft vs applied (commit saat panel ditutup bila berubah)
export function sameFilters(a, b) {
  return JSON.stringify(a || {}) === JSON.stringify(b || {})
}

// FU102: validasi NILAI baris rentang (dipakai FilterRows sebelum commit —
// perilaku lama Dashboard: tombol Terapkan mati sampai nilai sah). Rentang
// kosong dua-duanya = baris belum diisi (tidak pernah salah). `requireBoth`
// untuk endpoint yang wajib dari+sampai; `maxSpan` batas lebar rentang.
export function rangeFieldError(value, field) {
  const dari = String(value?.dari ?? '')
  const sampai = String(value?.sampai ?? '')
  if (!dari && !sampai) return ''
  if (field?.requireBoth && !(dari && sampai)) return 'Pilih tanggal awal dan akhir.'
  if (!dari || !sampai) return ''
  const span = (new Date(sampai) - new Date(dari)) / 86400000
  if (field?.maxSpan && span > field.maxSpan) return `Rentang maksimal ${field.maxSpan} hari.`
  return ''
}

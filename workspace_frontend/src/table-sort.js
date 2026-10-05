// FU94: sort 3-klik untuk tabel custom (wo-thead/wo-row) — siklus naik →
// turun → normal. Tabel PrimeVue memakai sortable+removableSort bawaan; yang
// hand-rolled memakai helper ini supaya perilakunya identik.

// klik berikutnya: '' → 'asc' → 'desc' → '' (kembali ke urutan asli)
export function nextSortDir(dir) {
  return dir === 'asc' ? 'desc' : dir === 'desc' ? '' : 'asc'
}

// salin+urutkan rows; dir ''/key kosong = kembalikan rows apa adanya.
// key = nama properti ATAU fungsi (row) → nilai (untuk baris bersarang).
// Nilai kosong (null/'') selalu paling bawah di kedua arah.
export function sortRows(rows, key, dir, type = 'text') {
  if (!key || !dir) return rows
  const mul = dir === 'asc' ? 1 : -1
  const val = typeof key === 'function' ? key : (row) => row[key]
  return [...rows].sort((a, b) => {
    const x = val(a)
    const y = val(b)
    const kx = x == null || x === ''
    const ky = y == null || y === ''
    if (kx && ky) return 0
    if (kx) return 1
    if (ky) return -1
    if (type === 'num') return (Number(x) - Number(y)) * mul
    return String(x).localeCompare(String(y), 'id', { numeric: true, sensitivity: 'base' }) * mul
  })
}

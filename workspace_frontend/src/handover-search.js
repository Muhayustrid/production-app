// FU44: pencarian papan Serah Terima — satu matcher untuk ketiga jenis kartu
// (lot / request / terkirim). Cocok pada nama item, nomor WO, dokumen
// (MR/SE), dan batch; kosong = semua kartu lolos.
export function boardMatch(card, query) {
  const q = (query || '').trim().toLowerCase()
  if (!q) return true
  return [card.name, card.workOrder, card.document, card.batch].some(
    (v) => (v || '').toString().toLowerCase().includes(q)
  )
}

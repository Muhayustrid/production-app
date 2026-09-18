// FU47: logika klik baris tabel Serah Terima — helper murni (tanpa akses
// store/Vue) agar ter-test terpisah. Semantik sengaja IDENTIK dengan klik
// kartu kanban (clickCard): request tanpa flag → aksi per role (multi-role
// memilih, gudang-only membatalkan, produksi mengirim); baris Terkirim
// membuka detail baca-saja (afordansi khusus tabel); flag
// draft/cancelled/stopped tidak klikabel.
export function rowClickAction(r, roles) {
  if (!r || !roles) return null
  if (r.lane === 'request' && !r.flag) {
    const gudang = !!roles.is_gudang
    const produksi = !!roles.is_produksi
    if (gudang && produksi) return 'choose'
    if (gudang) return 'cancel'
    if (produksi) return 'send'
    return null
  }
  if (r.lane === 'terkirim' && r.stockEntry) return 'done'
  return null
}

// label rute kiriman: gudang asal → tujuan; MR legacy tanpa rute eksplisit
// jatuh ke label Cold Storage / target papan.
export function seRouteLabel(r, fallbackTarget) {
  return `${r?.fromWarehouse || 'Cold Storage'} → ${r?.toWarehouse || fallbackTarget || '-'}`
}

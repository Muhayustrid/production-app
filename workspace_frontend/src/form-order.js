// Form Order helper murna (FO 2026-09-18) — tanpa import Vue agar bisa
// dites langsung (pola handover-box.js / handover-search.js).
// Server tetap otoritatif; ini hanya label/validasi tampilan.

// status Form Order dari server (form_order._orders): draf/menunggu/terkirim/batal
export function foStatusMeta(status) {
  if (status === 'terkirim') return { label: 'Terkirim', cls: 'chip-ok' }
  if (status === 'batal') return { label: 'Dibatalkan', cls: 'chip-bad' }
  if (status === 'draf') return { label: 'Draf', cls: 'chip-off' }
  return { label: 'Menunggu', cls: 'chip-warn' }
}

// status baris tabel Serah Terima dari lane/flag papan (request/terkirim/null)
export function laneStatusMeta(r) {
  if (r.lane === 'terkirim') return { label: 'Terkirim', cls: 'chip-ok' }
  if (r.flag === 'stopped') return { label: 'Dihentikan', cls: 'chip-off' }
  if (r.flag === 'cancelled') return { label: 'Dibatalkan', cls: 'chip-bad' }
  if (r.flag === 'draft') return { label: 'Draf', cls: 'chip-off' }
  if (r.lane === 'request') return { label: 'Diminta', cls: 'chip-warn' }
  return { label: '-', cls: 'chip-off' }
}

// validasi form (baris {code, qty}): '' error = tidak tampil; submit terkunci
// sampai semua baris valid — cermin ringan validasi server (qty > 0).
export function validateFormRows(rows) {
  const errors = {}
  rows.forEach((row, i) => {
    if (!row.code) errors[i] = 'Pilih item'
    else {
      const qty = Number(row.qty)
      if (!Number.isFinite(qty) || qty <= 0) errors[i] = 'Qty harus angka positif'
    }
  })
  return errors
}

export function formCanSubmit(rows, errors) {
  return rows.length > 0 && Object.keys(errors).length === 0
}

export function foItemsText(order) {
  const items = order?.items || []
  if (!items.length) return '-'
  const head = `${items[0].name} ${items[0].qty} ${items[0].uom || ''}`.trim()
  return items.length > 1 ? `${head} +${items.length - 1} item lagi` : head
}

export function foQtyTotal(order) {
  return (order?.items || []).reduce((sum, i) => sum + (Number(i.qty) || 0), 0)
}

// info item dari item_info() → masalah dini utk baris grid (server tetap
// otoritatif; pesan ini hanya memandu sebelum submit)
export function itemRowProblem(info) {
  if (!info) return ''
  if (!Number(info.is_stock_item)) return 'bukan-stok'
  if (Number(info.has_batch_no)) return 'batch'
  return ''
}

export const ITEM_PROBLEM_TEXT = {
  'bukan-stok': 'Bukan item stok — tidak bisa dipesan lewat Form Order.',
  batch: 'Item ber-batch — untuk sementara minta lewat Desk ERPNext.',
  'uom-invalid': 'Satuan tidak dikenal untuk item ini — pilih dari daftar.'
}

// FU48c: pilihan satuan valid dari info item — stock_uom + uoms, tanpa duplikat
export function uomOptions(info) {
  if (!info) return []
  const opts = [info.stock_uom]
  for (const u of info.uoms || []) {
    if (u.uom && !opts.includes(u.uom)) opts.push(u.uom)
  }
  return opts
}

// pilihan default baris: last_uom user (bila masih anggota opsi) → stock_uom;
// ganti item, satuan lama basi otomatis jatuh ke default
export function defaultUom(info) {
  const opts = uomOptions(info)
  if (info?.last_uom && opts.includes(info.last_uom)) return info.last_uom
  return info?.stock_uom || ''
}

// masalah baris: satuan terpilih bukan anggota opsi item (error baris,
// submit terkunci — cermin validasi server)
export function uomProblem(row) {
  if (!row?.info || !row.uom) return ''
  return uomOptions(row.info).includes(row.uom) ? '' : 'uom-invalid'
}

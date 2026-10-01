// FU72: helper murni Dashboard "Hari Ini" — teruji node tanpa Vue/DOM.
import { fmtId } from './format.js'

// 7 kunci sesuai kontrak dashboard_summary (selalu lengkap, boleh 0)
export const STAGES = [
  { key: 'persiapan', label: 'Persiapan' },
  { key: 'material', label: 'Material' },
  { key: 'operasi', label: 'Operasi' },
  { key: 'pre_packing', label: 'Pre-Packing' },
  { key: 'post_packing', label: 'Post-Packing' },
  { key: 'finish', label: 'Finish' },
  { key: 'selesai_hari_ini', label: 'Selesai hari ini' }
]

// daftar {uom, qty} → "401,67 Pack · 120 Kg"; kosong → "0" (nol jujur)
export function outputTotalsText(list) {
  if (!Array.isArray(list) || !list.length) return '0'
  return list.map((o) => `${fmtId(o.qty)} ${o.uom}`).join(' · ')
}

// badge nav: tahap berjalan saja, selesai_hari_ini tidak dihitung
export function activeTotal(stages) {
  return STAGES
    .filter((s) => s.key !== 'selesai_hari_ini')
    .reduce((sum, s) => sum + (Number(stages?.[s.key]) || 0), 0)
}

// kolom Qty tabel WO hari ini: kontrak FU72 format Indonesia maks 2 desimal
// (qtyStack lama tetap en-US 4 desimal untuk halaman lain). units = baris
// ter-map mapDetail: {qtyInPack, displayUom, stockUom}
export function woQtyText(qty, units) {
  const stock = units?.stockUom || ''
  if (!Number.isFinite(qty)) return { main: '-', sub: '' }
  const factor = Number(units?.qtyInPack)
  const displayUom = units?.displayUom || stock
  if (!Number.isFinite(factor) || factor <= 0 || displayUom === stock) {
    return { main: `${fmtId(qty)} ${stock}`.trim(), sub: '' }
  }
  const value = qty / factor
  const approx = Math.abs(value - Math.round(value)) > 1e-9
  return { main: `${approx ? '≈ ' : ''}${fmtId(value)} ${displayUom}`, sub: `${fmtId(qty)} ${stock}`.trim() }
}

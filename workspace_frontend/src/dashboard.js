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

// ============================================================================
// FU73: panel "Hasil per produk" + "Perlu perhatian" — helper murni teruji.
// ============================================================================

// warna segmen meter (fill bar di atas permukaan putih, kontras >= 3:1
// menurut cek WCAG: Good 5,79 · Reject 4,24 · Trial 3,25 · Sisa 3,44)
export const YIELD_LEGEND = [
  { key: 'good', label: 'Good', color: 'var(--brand)' },
  { key: 'reject', label: 'Reject', color: '#c9583f' },
  { key: 'trial', label: 'Trial', color: '#b8860b' },
  { key: 'sisa', label: 'Sisa', color: '#7e8c99' }
]

// baris produk → segmen MeterGroup: persentase terhadap rencana, segmen 0
// dibuang; max = max(100, total) supaya overproduksi tidak meluber track
export function yieldSegments(row) {
  const planned = Number(row?.planned) || 0
  const segments = YIELD_LEGEND
    .map((m) => ({
      label: m.label,
      color: m.color,
      value: planned > 0 ? Math.round(((Number(row?.[m.key]) || 0) / planned) * 1000) / 10 : 0
    }))
    .filter((s) => s.value > 0)
  const sum = segments.reduce((t, s) => t + s.value, 0)
  return { segments, max: Math.max(100, sum) }
}

// menit → "45 menit" / "3 jam" / "5 jam 20 menit"; 0 → "0 menit";
// null/undefined/tak-valid → "" (pemanggil menyembunyikan bagian tsb)
export function durationText(minutes) {
  if (minutes == null || minutes === '') return ''
  const n = Number(minutes)
  if (!Number.isFinite(n)) return ''
  const m = Math.max(0, Math.round(n))
  if (m < 60) return `${m} menit`
  const h = Math.floor(m / 60)
  const rest = m % 60
  return rest ? `${h} jam ${rest} menit` : `${h} jam`
}

// item kontrak `attention` → {title, detail}; field per kind sesuai kontrak
// server FU73. age_minutes bisa null → bagian durasi tak ditampilkan.
export function attentionText(item) {
  switch (item?.kind) {
    case 'reject_over':
      return {
        title: `${item.item_name}: reject ${fmtId(item.reject_pct)}%`,
        detail: `Di atas ambang ${fmtId(item.threshold)}% · ${item.wo}`
      }
    case 'stagnant': {
      // STAGES tak memuat 'selesai' — derive bisa balas selesai di tepi
      // presisi float (guard yang sama dipakai papan di server)
      const stage = STAGES.find((s) => s.key === item.stage)?.label
        || (item.stage === 'selesai' ? 'Selesai' : '') || item.stage
      return {
        title: `${item.wo} tertahan di ${stage}`,
        detail: [item.item_name, item.age_minutes != null ? `tanpa perkembangan ${durationText(item.age_minutes)}` : '']
          .filter(Boolean).join(' · ')
      }
    }
    case 'handover_request':
      return {
        title: 'Request gudang menunggu dikirim',
        detail: [item.mr, durationText(item.age_minutes)].filter(Boolean).join(' · ')
      }
    case 'form_order':
      return {
        title: 'Form order menunggu diproses',
        detail: [item.mr, durationText(item.age_minutes)].filter(Boolean).join(' · ')
      }
    case 'suhu':
      return {
        title: item.adonan_ke
          ? `Suhu adonan ke-${item.adonan_ke} tinggi: ${fmtId(item.suhu)}°C`
          : `Suhu adonan tinggi: ${fmtId(item.suhu)}°C`,
        detail: `${item.item_name} · batas ${fmtId(item.threshold)}°C`
      }
    case 'stopped':
      return { title: `${item.wo} berstatus Stopped`, detail: item.item_name || '' }
    default:
      return { title: item?.kind ? String(item.kind) : '', detail: '' }
  }
}

// angka % hasil bagus: "87,5%"; null/tak-valid → "-"
export function yieldPctText(pct) {
  return Number.isFinite(pct) ? `${fmtId(pct)}%` : '-'
}

// ============================================================================
// FU74: penggunaan bahan baku (dashboard panel + halaman Bahan baku) — helper
// murni teruji. Kontrak agregat: rows[{item_code,item_name,uom,planned,
// expected,consumed,variance,variance_pct|null,over,unlisted,work_orders[]}]
// ============================================================================

// baris panel: hitung dari rows — used = baris consumed > 0, over = baris over
// (epsilon 1e-9: sisa noise float gross−retur tidak dihitung "dipakai")
export function materialCounts(mu) {
  const rows = Array.isArray(mu?.rows) ? mu.rows : []
  return {
    used: rows.filter((r) => (Number(r?.consumed) || 0) > 1e-9).length,
    over: rows.filter((r) => !!r?.over).length
  }
}

// kalimat ringkasan panel: mu absen → ''; tanpa pemakaian → kalimat kosong
// jujur; ada pemakaian → jumlah bahan + (bila ada) berapa di atas rencana
export function materialSummaryText(mu) {
  if (!mu) return ''
  const { used, over } = materialCounts(mu)
  if (!used) return 'Belum ada pemakaian bahan hari ini'
  return over
    ? `${used} bahan dipakai · ${over} di atas rencana`
    : `${used} bahan dipakai · semua sesuai rencana`
}

// "Terpakai 52 kg · sesuai hasil 48 kg" — angka fmtId, UOM stok bahan
export function materialRowText(row) {
  const uom = row?.uom || ''
  return `Terpakai ${fmtId(Number(row?.consumed) || 0)}${uom ? ' ' + uom : ''} · sesuai hasil ${fmtId(Number(row?.expected) || 0)}${uom ? ' ' + uom : ''}`
}

// "+8,3%" / "−4,5%" (minus asli U+2212, koma desimal); null → '' (tanpa dasar)
export function variancePctText(row) {
  const pct = Number(row?.variance_pct)
  if (row?.variance_pct == null || !Number.isFinite(pct)) return ''
  return `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${fmtId(Math.abs(pct))}%`
}

// link halaman bahan untuk satu item (dipakai panel Dashboard & halaman)
export function bahanHref(itemCode) {
  return '#/bahan?bahan=' + encodeURIComponent(itemCode)
}

// ============================================================================
// FU76: filter rentang tanggal dashboard — preset di-resolve SERVER
// (tanggal server otoritatif); frontend hanya mengirim preset/dari/sampai.

export const RANGE_PRESETS = [
  { key: 'hari_ini', label: 'Hari ini' },
  { key: 'kemarin', label: 'Kemarin' },
  { key: 'bulan_ini', label: 'Bulan ini' },
  { key: 'bulan_kemarin', label: 'Bulan kemarin' },
  { key: 'tahun_ini', label: 'Tahun ini' },
  { key: 'kustom', label: 'Kustom' }
]

// payload rentang utk dashboard_summary: preset selalu dikirim; tanggal
// hanya utk kustom (server menolak kustom tanpa keduanya)
export function rangeParams(preset, dari, sampai) {
  const p = RANGE_PRESETS.some((r) => r.key === preset) ? preset : 'hari_ini'
  if (p !== 'kustom') return { preset: p }
  return { preset: p, dari: dari || '', sampai: sampai || '' }
}

// label rentang di page-head: satu hari → nama hari lengkap; rentang →
// "1 – 31 Oktober 2026" / "1 Sep – 31 Okt 2026" / lintas tahun lengkap
export function rangeLabel(preset, dari, sampai) {
  if (!dari || !sampai) return ''
  if (dari === sampai) {
    const d = new Date(dari + 'T00:00:00')
    return isNaN(d) ? '' : d.toLocaleDateString('id-ID', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
    })
  }
  const a = new Date(dari + 'T00:00:00')
  const b = new Date(sampai + 'T00:00:00')
  if (isNaN(a) || isNaN(b)) return ''
  const sameMonth = a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()
  const sameYear = a.getFullYear() === b.getFullYear()
  if (sameMonth) {
    return `${a.getDate()} – ${b.getDate()} ${b.toLocaleDateString('id-ID', { month: 'long', year: 'numeric' })}`
  }
  if (sameYear) {
    return `${a.getDate()} ${a.toLocaleDateString('id-ID', { month: 'long' })} – ${b.getDate()} ${b.toLocaleDateString('id-ID', { month: 'long', year: 'numeric' })}`
  }
  return `${a.toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' })} – ${b.toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' })}`
}

// label tile terakhir papan: ikut preset (server menghitung selesai dalam
// rentang); hari ini tetap berlabel harian
export function selesaiTileLabel(preset) {
  return preset === 'hari_ini' ? 'Selesai hari ini' : 'Selesai dalam rentang'
}

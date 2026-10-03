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
export function materialUsageHref(itemCode) {
  return '#/penggunaan-bahan?bahan=' + encodeURIComponent(itemCode)
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

// label tombol filter rentang: preset tak dikenal jatuh ke "Hari ini"
// (fallback sama dengan rangeParams)
export function presetLabel(preset) {
  return RANGE_PRESETS.find((r) => r.key === preset)?.label || 'Hari ini'
}

// label tile terakhir papan: ikut preset (server menghitung selesai dalam
// rentang); hari ini tetap berlabel harian
export function selesaiTileLabel(preset) {
  return preset === 'hari_ini' ? 'Selesai hari ini' : 'Selesai dalam rentang'
}

// ============================================================================
// FU78: redesign dashboard — KPI, chart, donut, kualitas per-UOM, bahan
// teratas, aktivitas, tabel WO. Semua helper murni teruji node; aturan inti:
// beda UOM TIDAK PERNAH dijumlahkan — satu UOM utama (dominant_uom server)
// untuk chart & KPI, kualitas dikelompokkan per UOM.
// ============================================================================

// bulan singkat id-ID utk label kategori chart/timeline — parsing manual dari
// string ISO (tanpa new Date agar zona waktu browser tidak menggeser hari)
const BULAN_SINGKAT = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']

// "2026-10-02" + 'harian' → "2 Okt"; "2026-10" + 'bulanan' → "Okt 2026";
// tak dikenal → apa adanya
export function periodLabel(period, granularity) {
  if (!period) return ''
  const bagian = String(period).split('-')
  const bl = BULAN_SINGKAT[Number(bagian[1]) - 1]
  if (!bl) return String(period)
  if (granularity === 'bulanan') return `${bl} ${bagian[0]}`
  return `${Number(bagian[2])} ${bl}`
}

const bulatkan = (n, desimal) => {
  const f = 10 ** desimal
  return Math.round((Number(n) || 0) * f) / f
}

// ============================================================================
// FU78b: kartu grafik filter LOKAL (endpoint dashboard_daily) — mode minggu
// (Senin s.d. Minggu, label nama hari) / bulan (1 s.d. akhir bulan, label
// tanggal); server mengirim series PER UOM sehingga krim kopi (Pcs) dan
// dough (Pack) berdampingan tanpa pernah dijumlahkan.
// ============================================================================

// pilihan filter lokal kartu grafik — kontrak mode dashboard_daily
export const DAILY_MODES = [
  { key: 'minggu', label: 'Minggu ini' },
  { key: 'bulan', label: 'Bulan ini' }
]

// nama hari id-ID — index getDay() (Minggu = 0)
const HARI = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu']

// "2026-10-02" → "Jumat"; parsing lokal (pola rangeLabel — tanpa 'Z' agar
// tidak bergeser sehari); tak valid → "" (pemanggil menyembunyikan label)
export function dayLabel(iso) {
  const d = new Date(String(iso || '') + 'T00:00:00')
  return isNaN(d) ? '' : HARI[d.getDay()]
}

// satu seri dashboard_daily → {labels, planned, produced} untuk Chart bar
// (2 desimal); mode minggu berlabel nama hari, selain itu label tanggal
export function chartDaily(series, mode) {
  const rows = Array.isArray(series?.rows) ? series.rows : []
  return {
    labels: rows.map((r) => (mode === 'minggu' ? dayLabel(r?.period) : periodLabel(r?.period))),
    planned: rows.map((r) => bulatkan(r?.planned, 2)),
    produced: rows.map((r) => bulatkan(r?.produced, 2))
  }
}

// daftar {uom, qty} → angka UOM utama (dominant / entri pertama) + sisa
// digabung " · " — panel yang butuh SATU angka besar tanpa menyembunyikan
// UOM lain (tidak pernah dijumlah)
export function uomPrimaryText(list, dominant) {
  const arr = Array.isArray(list) ? list : []
  if (!arr.length) return { main: '0', rest: '' }
  const pri = arr.find((e) => e.uom === dominant) || arr[0]
  const rest = arr
    .filter((e) => e !== pri)
    .map((e) => `${fmtId(e.qty)} ${e.uom}`)
    .join(' · ')
  return { main: `${fmtId(pri.qty)} ${pri.uom}`, rest }
}

// % pencapaian = hasil/rencana pada UOM dominan (server satu sumber);
// rencana 0 / pasangan UOM tak lengkap → null (pemanggil menampilkan "-")
export function achievementPct(plannedQty, outputToday, dominant) {
  if (!dominant) return null
  const p = (Array.isArray(plannedQty) ? plannedQty : []).find((e) => e.uom === dominant)
  const o = (Array.isArray(outputToday) ? outputToday : []).find((e) => e.uom === dominant)
  if (!p || !o || !(Number(p.qty) > 0)) return null
  return bulatkan((Number(o.qty) / Number(p.qty)) * 100, 1)
}

// chip delta "+6,4%" / "−5%" (minus U+2212, pola variancePctText); prev/cur
// absen (null/undefined) atau prev 0 → '' (tanpa dasar perbandingan).
// NB: Number(null) === 0 — null dicek eksplisit sebelum Number.
export function deltaPctText(cur, prev) {
  if (cur == null || prev == null) return ''
  const c = Number(cur)
  const p = Number(prev)
  if (!Number.isFinite(c) || !Number.isFinite(p) || !(p > 0)) return ''
  const pct = bulatkan(((c - p) / p) * 100, 1)
  return pct > 0 ? `+${fmtId(pct)}%` : pct < 0 ? `−${fmtId(Math.abs(pct))}%` : '0%'
}

// warna segmen tahap donut — palet app yang sudah ada (brand family + ok/
// warn/sisa), kontras di atas permukaan putih kartu
export const STAGE_COLORS = {
  persiapan: '#9bbdd8',
  material: '#b8860b',
  operasi: '#3368a0',
  pre_packing: '#66a3bf',
  post_packing: '#7e8c99',
  finish: '#2a5585',
  selesai_hari_ini: '#2f5940'
}

// stages papan → {segments, total} utk donut chart.js; SEMUA 7 tahap ikut
// (FU78b: legend samping menampilkan tahap kosong juga — segmen 0 tidak
// menggambar apa pun di donut); total = jumlah seluruhnya (pusat kartu)
export function donutData(stages) {
  const segments = STAGES.map((s) => ({
    key: s.key,
    label: s.label,
    value: Number(stages?.[s.key]) || 0,
    color: STAGE_COLORS[s.key]
  }))
  return { segments, total: segments.reduce((t, s) => t + s.value, 0) }
}

// baris product_yield dikelompokkan per UOM — TIDAK pernah menjumlah lintas
// UOM (aturan inti FU78). Urut total good menurun; grup pertama = utama kartu
// kualitas, sisanya diringkas kecil.
export function qualityPerUom(rows) {
  const by = new Map()
  for (const r of Array.isArray(rows) ? rows : []) {
    const k = r?.uom || ''
    const acc = by.get(k) || { uom: k, planned: 0, good: 0, reject: 0, trial: 0, sisa: 0 }
    for (const f of ['planned', 'good', 'reject', 'trial', 'sisa']) acc[f] += Number(r?.[f]) || 0
    by.set(k, acc)
  }
  return [...by.values()].sort((a, b) => b.good - a.good)
}

// panel bahan: ±n baris paling menonjol — tanpa dasar (pct null) paling atas,
// lalu |variance_pct| menurun (persen = dimensi netral lintas UOM); bahan
// yang belum terpakai (consumed 0) tidak menempati baris
export function topMaterialRows(rows, n = 6) {
  return (Array.isArray(rows) ? rows : [])
    .filter((r) => (Number(r?.consumed) || 0) > 1e-9)
    .sort((a, b) => {
      const ka = a?.variance_pct == null ? -1 : 0
      const kb = b?.variance_pct == null ? -1 : 0
      if (ka !== kb) return ka - kb
      return Math.abs(Number(b?.variance_pct) || 0) - Math.abs(Number(a?.variance_pct) || 0)
    })
    .slice(0, Number(n) || n)
}

// event recent_activity → {title, detail}: "Nama 12 Nos, Garam 2 Kg" (server
// sudah membatasi 2 item + penghitung sisanya)
function ringkasItem(event) {
  const items = Array.isArray(event?.items) ? event.items : []
  const parts = items.map((i) => `${i.item_name || i.item_code} ${fmtId(i.qty)} ${i.uom || ''}`.trim())
  if (event?.item_lain) parts.push(`+${fmtId(event.item_lain)} item lain`)
  return parts.join(', ')
}

export function activityText(event) {
  if (event?.kind === 'transfer') return { title: 'Bahan diserahkan', detail: ringkasItem(event) }
  if (event?.kind === 'manufacture') return { title: 'Hasil diposting', detail: ringkasItem(event) }
  return { title: event?.kind ? String(event.kind) : '', detail: ringkasItem(event) }
}

// ts "2026-10-02 10:05:00" → {time:"10:05", date:"2 Okt"} — manual, TZ-safe.
// NB: frappe Time bisa "9:00:00" (jam 1 digit) → dipad ke "09:00"
export function activityTime(ts) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})/.exec(String(ts || ''))
  if (!m) return { time: '', date: '' }
  const bl = BULAN_SINGKAT[Number(m[2]) - 1] || ''
  return { time: `${m[4].padStart(2, '0')}:${m[5]}`, date: bl ? `${Number(m[3])} ${bl}` : '' }
}

// % progres WO utk kolom tabel = produced/qty (1 desimal, dibatasi 100);
// qty tak valid/0 → 0 (bar tanpa dasar tetap tampil kosong, bukan mengarang)
export function woProgressPct(row) {
  const qty = Number(row?.plannedStockQty)
  const done = Number(row?.producedStockQty)
  if (!Number.isFinite(qty) || qty <= 0 || !Number.isFinite(done)) return 0
  return Math.min(100, bulatkan((done / qty) * 100, 1))
}

// target selesai telat: planned_end lewat & WO belum selesai. nowMs dari
// pemanggil agar helper murni dan teruji.
export function isOverdue(row, nowMs) {
  if (row?.stage === 'completed') return false
  const end = Date.parse(String(row?.plannedEnd || '').replace(' ', 'T'))
  return Number.isFinite(end) && end < nowMs
}

// kolom "Target selesai" dashboard: hari yang sama dgn hari ini (server) →
// jam saja ("14:00"); hari lain → tanggal singkat ("1 Okt 2026") — jam tanpa
// tanggal menyesatkan di rentang multi-hari; kosong → '-' (FU80e)
export function targetText(plannedEnd, today) {
  const s = String(plannedEnd || '')
  if (!s) return '-'
  const hari = s.slice(0, 10)
  if (today && hari === String(today)) {
    const m = /(?:^|[ T])(\d{1,2}:\d{2})/.exec(s)
    return m ? m[1] : s
  }
  return tanggalPendek(hari)
}

// ============================================================================
// FU81: sesi berakhir di tengah pemakaian SPA (logout/kick di tab lain) —
// jangan biarkan error mentah; bawa user ke login ERPNext lalu kembali.
// frappe menampik permintaan guest dgn 403 "… is not whitelisted" (pesan
// bawaan utk tamu — bukan bug whitelist); 401 = sesi kadaluarsa. 403
// "Not permitted" = user sah tanpa izin — TETAP error di halaman.
// ============================================================================

export function harusKeLogin(status, pesan) {
  if (status === 401) return true
  return status === 403 && /not whitelisted/i.test(String(pesan || ''))
}

// URL login ERPNext membawa tujuan kembali: pathname + hash — deep-link SPA
// (mis. #/wo/<id> atau #/penggunaan-bahan) pulih persis pasca-login (pola FU67)
export function loginRedirectUrl(pathname, hash) {
  const tujuan = String(pathname || '/') + String(hash || '')
  return '/login?redirect-to=' + encodeURIComponent(tujuan)
}


// ============================================================================
// FU79: rombak halaman penggunaan bahan baku (FU82: #/penggunaan-bahan) gaya
// perbandingan konsumsi, tren produksi, traceability. Semua murni & teruji;
// aturan inti terwarisi: beda UOM TIDAK PERNAH dijumlahkan/dirata-ratakan.
// ============================================================================

// label status Work Order native → Indonesia (nilai tak dikenal apa adanya)
const WO_STATUS_ID = {
  Draft: 'Draft',
  'Not Started': 'Belum mulai',
  'In Process': 'Berjalan',
  Stopped: 'Berhenti',
  Completed: 'Selesai',
  Cancelled: 'Dibatalkan'
}

export function woStatusText(status) {
  return WO_STATUS_ID[status] || status || ''
}

// daftar WO trace → sub-KPI "Order produksi": kosong → "Tidak ada order";
// semua selesai → "Semua selesai"; selain itu bagian non-nol terurut
// "1 selesai · 2 berjalan · 1 belum mulai" (status asing ikut terhitung)
export function woStatusSummary(list) {
  const arr = Array.isArray(list) ? list : []
  if (!arr.length) return 'Tidak ada order'
  const hitung = {}
  for (const w of arr) {
    const k = woStatusText(w?.status) || 'Lain'
    hitung[k] = (hitung[k] || 0) + 1
  }
  if ((hitung['Selesai'] || 0) === arr.length) return 'Semua selesai'
  // urutan tetap; status asing (tak ada di daftar) tetap tampil di belakang
  const urut = ['Selesai', 'Berjalan', 'Belum mulai', 'Draft', 'Berhenti', 'Dibatalkan', 'Lain']
  return Object.keys(hitung)
    .sort((a, b) => {
      const ia = urut.indexOf(a)
      const ib = urut.indexOf(b)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    })
    .map((k) => `${hitung[k]} ${k.toLowerCase()}`)
    .join(' · ')
}

// total per UOM dari daftar baris (kunci qty dapat diatur) — TIDAK pernah
// menjumlah lintas UOM; urut total menurun (entri pertama = UOM utama)
export function uomTotals(list, qtyKey, uomKey = 'uom') {
  const by = new Map()
  for (const r of Array.isArray(list) ? list : []) {
    const k = r?.[uomKey] || ''
    by.set(k, (by.get(k) || 0) + (Number(r?.[qtyKey]) || 0))
  }
  return [...by.entries()]
    .map(([uom, qty]) => ({ uom, qty: bulatkan(qty, 3) }))
    .sort((a, b) => b.qty - a.qty)
}

// % deviasi rata-rata tertimbang pada SATU UOM: Σvariance/Σexpected×100 —
// bobot lintas UOM tidak bermakna, hanya baris uom itu yang ikut; uom kosong
// MENOLAK (null) — menjumlah tanpa UOM = melanggar aturan inti; tanpa
// expected > 0 → null
export function weightedVarPct(rows, uom) {
  if (!uom) return null
  let varian = 0
  let dasar = 0
  for (const r of Array.isArray(rows) ? rows : []) {
    if ((r?.uom || '') !== uom) continue
    const e = Number(r?.expected) || 0
    if (e <= 0) continue
    dasar += e
    varian += Number(r?.variance) || 0
  }
  return dasar > 0 ? bulatkan((varian / dasar) * 100, 1) : null
}

// % efisiensi pada SATU UOM: Σexpected/Σconsumed×100; uom kosong → null
// (alasan sama dengan weightedVarPct); konsumsi 0 → null
export function efficiencyPct(rows, uom) {
  if (!uom) return null
  let dasar = 0
  let pakai = 0
  for (const r of Array.isArray(rows) ? rows : []) {
    if ((r?.uom || '') !== uom) continue
    dasar += Number(r?.expected) || 0
    pakai += Number(r?.consumed) || 0
  }
  return pakai > 0 ? bulatkan((dasar / pakai) * 100, 1) : null
}

// kartu perbandingan: baris dengan dasar (max dari expected/consumed) di atas
// 0, urut menurun, dipotong cap; sisanya dihitung "extra" utk catatan footer
export function comparisonRows(rows, cap = 8) {
  const list = (Array.isArray(rows) ? rows : [])
    .filter((r) => (Number(r?.expected) || 0) > 1e-9 || (Number(r?.consumed) || 0) > 1e-9)
    .sort(
      (a, b) =>
        Math.max(Number(b?.expected) || 0, Number(b?.consumed) || 0) -
        Math.max(Number(a?.expected) || 0, Number(a?.consumed) || 0)
    )
  const batas = Number(cap) || cap
  return { list: list.slice(0, batas), extra: Math.max(0, list.length - batas) }
}

// lebar bar 0-100 dari nilai terhadap maksimum baris tampil; maks ≤ 0 → 0
export function barPct(value, max) {
  const m = Number(max) || 0
  if (m <= 0) return 0
  return Math.max(0, Math.min(100, bulatkan(((Number(value) || 0) / m) * 100, 1)))
}

// warna angka selisih: over → 'over' (merah), negatif → 'under' (hijau),
// sisanya 'flat' (netral) — baris "tanpa dasar" (pct null) mengikuti row.over
export function varianceTone(row) {
  if (row?.over) return 'over'
  const v = Number(row?.variance)
  if (Number.isFinite(v) && v < -1e-9) return 'under'
  return 'flat'
}

// "+1,5 Kg" / "−0,3 Kg" (minus asli U+2212, pola variancePctText); 0 tanpa
// tanda; qty tak valid → '-'
export function signedQtyText(qty, uom) {
  const n = Number(qty)
  if (!Number.isFinite(n)) return '-'
  const tanda = n > 0 ? '+' : n < 0 ? '−' : ''
  return `${tanda}${fmtId(Math.abs(n))}${uom ? ' ' + uom : ''}`
}

// satu seri tren {rows:[{period,produced,wo}]} → {labels, data} Chart bar;
// label "2 Okt" manual TZ-safe (pola periodLabel), produced 2 desimal
export function chartTrend(series) {
  const rows = Array.isArray(series?.rows) ? series.rows : []
  return {
    labels: rows.map((r) => periodLabel(r?.period)),
    data: rows.map((r) => bulatkan(r?.produced, 2))
  }
}

// baris tren dgn hasil terbesar (seri → pertama); tanpa hasil > 0 → null
export function peakDay(rows) {
  let best = null
  for (const r of Array.isArray(rows) ? rows : []) {
    if ((Number(r?.produced) || 0) <= 0) continue
    if (!best || (Number(r.produced) || 0) > (Number(best.produced) || 0)) best = r
  }
  return best
}

// callout puncak: "Puncak output 2 Okt dengan 2.592 Nos dari 2 work order."
// (1 WO tak memakai jamak); peak kosong → '' (callout disembunyikan)
export function peakText(peak, uom) {
  if (!peak) return ''
  const n = Number(peak.wo) || 0
  const wo = n === 1 ? '1 work order' : `${n} work order`
  return `Puncak output ${periodLabel(peak.period)} dengan ${fmtId(Number(peak.produced) || 0)}${uom ? ' ' + uom : ''} dari ${wo}.`
}

// yield satu WO trace %: produced/planned_qty×100 (1 desimal); tanpa dasar → null
export function woYieldPct(wo) {
  const p = Number(wo?.planned_qty)
  const d = Number(wo?.produced_qty)
  if (!Number.isFinite(p) || p <= 0 || !Number.isFinite(d)) return null
  return bulatkan((d / p) * 100, 1)
}

// kelas warna yield: ≥100 'ok' (hijau), <90 'bad' (merah), sisanya 'flat'.
// NB: Number(null) === 0 — null dicek eksplisit (gotcha deltaPctText).
export function yieldTone(pct) {
  if (pct == null) return 'flat'
  const p = Number(pct)
  if (!Number.isFinite(p)) return 'flat'
  if (p >= 100) return 'ok'
  if (p < 90) return 'bad'
  return 'flat'
}

// "2026-10-02" → "2 Okt 2026" (kartu WO trace); bukan ISO harian apa adanya
export function tanggalPendek(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''))
  if (!m) return String(iso || '')
  const bl = BULAN_SINGKAT[Number(m[2]) - 1]
  return bl ? `${Number(m[3])} ${bl} ${m[1]}` : String(iso)
}

// transaksi terfilter satu bahan (klik baris analisis → tab transaksi)
export function txnOfMaterial(transactions, itemCode) {
  return (Array.isArray(transactions) ? transactions : []).filter(
    (t) => t?.item_code === itemCode
  )
}

// ISO "2026-10-01" → "01-10-2026" (format DD-MM-YYYY permintaan user FU79c);
// bukan ISO harian → apa adanya; kosong → ''
export function tanggalDmy(iso) {
  const s = String(iso || '')
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  return m ? `${m[3]}-${m[2]}-${m[1]}` : s
}

// pasangan dari/sampai selalu naik (to yang dipilih lebih kecil → tukar);
// nilai kosong diteruskan apa adanya
export function normalisasiRentang(a, b) {
  if (a && b && b < a) return [b, a]
  return [a, b]
}

// FU79d: hasil SATU pilihan kalender untuk field rentang tunggal (RangeField).
// fase 'dari': firstTo 'same' → satu hari [v, v] (pola bahan — endpoint wajib
// dari+sampai); 'clear' → dari aja [v, ''] (pola WO/handover — from-only
// terbuka, semantik lama utuh). fase 'sampai': to ditukar bila < dari.
export function rentangSetelahPilih(dari, sampai, v, fase, firstTo = 'clear') {
  if (fase === 'sampai') return normalisasiRentang(dari, v)
  return firstTo === 'same' ? [v, v] : [v, '']
}

// label field rentang: satu tanggal → "02-10-2026" (filter from aja);
// rentang → "01-10-2026 to 02-10-2026" (format user FU79c); kosong → ''
export function rentangDmyText(dari, sampai) {
  if (!dari && !sampai) return ''
  const [a, b] = normalisasiRentang(dari, sampai)
  const tglA = tanggalDmy(a)
  return b && b !== a ? `${tglA} to ${tanggalDmy(b)}` : tglA
}

// ---- FU80c: ekspor .xlsx penggunaan bahan — file dibangun SERVER
// (endpoint material_usage_xlsx, 4 sheet: Info/Ringkasan/Work Order/
// Transaksi, angka mentah numerik); frontend hanya menyusun nama unduhan.

// nama file unduhan: rentang → penggunaan-bahan-[<produk>-]<dari>_sd_<sampai>
// .xlsx (ISO, non-angka dibuang; produk jadi slug lowercase); satu hari tanpa
// _sd_; keduanya kosong → generik (paritas _nama_file_xlsx server)
export function materialUsageXlsxFilename(dari, sampai, produk) {
  const bersih = (v) => String(v || '').replace(/[^0-9-]/g, '')
  const slug = String(produk || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const a = bersih(dari)
  const b = bersih(sampai)
  const inti = a && b && a !== b ? `${a}_sd_${b}` : a
  if (!inti) return 'penggunaan-bahan.xlsx'
  return `penggunaan-bahan-${slug ? slug + '-' : ''}${inti}.xlsx`
}

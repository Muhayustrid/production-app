// Konversi dan format kuantitas Pack/PCS.
// Nilai tersimpan selalu PCS (Stock UOM ERPNext). Pack hanya lapisan tampilan/input.

export function fmtInt(n) {
  return Number.isFinite(n) ? n.toLocaleString('en-US') : '0'
}

export function fmtNum(n) {
  return Number.isFinite(n)
    ? n.toLocaleString('en-US', { maximumFractionDigits: 2 })
    : '0'
}

// '2026-09-12' -> '12 Sep 2026' (atau '12 Sep' bila short)
export function fmtDate(iso, short = false) {
  if (!iso) return '-'
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('id-ID', short
    ? { day: 'numeric', month: 'short' }
    : { day: 'numeric', month: 'short', year: 'numeric' })
}

// "12 Pack · 1,296 PCS". Nilai yang bukan kelipatan pack ditandai "≈" tanpa
// pernah dibulatkan secara diam-diam.
export function qtyMain(pcs, qip) {
  if (!Number.isFinite(pcs)) pcs = 0
  const { str, approx } = packParts(pcs, qip)
  return `${approx ? '≈ ' : ''}${str} Pack · ${fmtInt(pcs)} PCS`
}

// pecahan Pack untuk satu nilai PCS: { str, approx }
export function packParts(pcs, qip) {
  const p = pcs / qip
  const r2 = Math.round(p * 100)
  const exact = Math.abs(p * 100 - r2) < 1e-9
  return { str: exact ? String(r2 / 100) : p.toFixed(2), approx: !exact }
}

// dua baris untuk sel tabel: Pack di atas, PCS di bawah
export function qtyStack(pcs, qip) {
  const { str, approx } = packParts(pcs, qip)
  return {
    main: `${approx ? '≈ ' : ''}${str} Pack`,
    sub: `${fmtInt(pcs)} PCS`
  }
}

// pecahan Pack hingga 4 desimal untuk tabel ringkasan; ≈ bila bukan kelipatan eksak
export function packStr4(pcs, qip) {
  const p = pcs / qip
  const r2 = Math.round(p * 100)
  if (Math.abs(p * 100 - r2) < 1e-9) return { str: String(r2 / 100), approx: false }
  const r4 = Math.round(p * 10000)
  return { str: String(r4 / 10000), approx: true }
}

// '2026-09-12T08:41' -> '12 Sep · 08:41' (stempel waktu singkat kartu/lot)
export function fmtStampShort(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return `${d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} · ${t}`
}

// teks input untuk nilai PCS pada satuan tertentu
export function pcsToText(pcs, unit, qip) {
  if (pcs == null) return { text: '', approx: false }
  if (unit === 'pcs') return { text: String(pcs), approx: false }
  const p = pcs / qip
  const scaled = Math.round(p * 10000)
  if (Math.abs(p * 10000 - scaled) < 1e-6) return { text: String(scaled / 10000), approx: false }
  // tidak terwakili eksak dalam Pack: tampilkan 2 desimal dengan penanda ≈
  return { text: (Math.round(p * 100) / 100).toFixed(2), approx: true }
}

// parse teks input kuantitas menjadi PCS + validasi (tanpa pembulatan diam-diam)
export function parseQtyText(t, unit, qip) {
  t = String(t ?? '').trim()
  if (t === '') return { value: null, error: null, warn: null }
  const n = Number(t.replace(',', '.'))
  if (!Number.isFinite(n) || n < 0) return { value: null, error: 'Angka tidak valid.', warn: null }
  let pcs
  if (unit === 'pack') {
    pcs = n * qip
    if (!Number.isInteger(pcs)) {
      const shown = pcs.toLocaleString('en-US', { maximumFractionDigits: 4 })
      return { value: null, error: `Menghasilkan ${shown} PCS. PCS harus bilangan bulat.`, warn: null }
    }
  } else {
    if (!Number.isInteger(n)) return { value: null, error: 'PCS harus bilangan bulat.', warn: null }
    pcs = n
  }
  const warn =
    pcs % qip !== 0
      ? 'Bukan kelipatan 1 Pack'
      : null
  return { value: pcs, error: null, warn }
}

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  STAGES, activeTotal, attentionText, bahanHref, durationText, materialCounts, materialRowText,
  materialSummaryText, outputTotalsText, presetLabel, rangeParams, rangeLabel, selesaiTileLabel,
  variancePctText, yieldPctText, yieldSegments
} from '../src/dashboard.js'

test('outputTotalsText menggabungkan total per satuan', () => {
  assert.equal(
    outputTotalsText([{ uom: 'Pack', qty: 401.67 }, { uom: 'Kg', qty: 120 }]),
    '401,67 Pack · 120 Kg'
  )
  assert.equal(outputTotalsText([{ uom: 'Kg', qty: 120 }]), '120 Kg')
})

test('outputTotalsText kosong atau undefined tetap "0"', () => {
  assert.equal(outputTotalsText([]), '0')
  assert.equal(outputTotalsText(undefined), '0')
  assert.equal(outputTotalsText(null), '0')
})

test('STAGES berisi 7 tahap dengan kunci unik sesuai kontrak', () => {
  assert.equal(STAGES.length, 7)
  const keys = STAGES.map((s) => s.key)
  assert.equal(new Set(keys).size, 7)
  assert.deepEqual(keys, [
    'persiapan', 'material', 'operasi', 'pre_packing', 'post_packing', 'finish', 'selesai_hari_ini'
  ])
})

test('activeTotal menjumlah tahap berjalan tanpa selesai_hari_ini', () => {
  assert.equal(activeTotal({ persiapan: 2, material: 1, operasi: 0, pre_packing: 1, post_packing: 0, finish: 1, selesai_hari_ini: 2 }), 5)
  assert.equal(activeTotal({}), 0)
  assert.equal(activeTotal(null), 0)
})

test('woQtyText: Indonesia format, max 2 desimal, fallback stock UOM', async () => {
  const { woQtyText } = await import('../src/dashboard.js')
  // faktor 12: 1000 Pcs -> 83,33 Pack (tak bulat -> approx) + sub stock
  assert.deepEqual(woQtyText(1000, { qtyInPack: 12, displayUom: 'Pack', stockUom: 'Nos' }),
    { main: '≈ 83,33 Pack', sub: '1.000 Nos' })
  // kelipatan utuh tanpa approx
  assert.deepEqual(woQtyText(24, { qtyInPack: 12, displayUom: 'Pack', stockUom: 'Nos' }),
    { main: '2 Pack', sub: '24 Nos' })
  // tanpa faktor valid: tampil stock UOM apa adanya
  assert.deepEqual(woQtyText(5, { qtyInPack: null, displayUom: 'Pack', stockUom: 'Nos' }),
    { main: '5 Nos', sub: '' })
  // display == stock: tanpa konversi
  assert.deepEqual(woQtyText(7, { qtyInPack: 1, displayUom: 'Nos', stockUom: 'Nos' }),
    { main: '7 Nos', sub: '' })
  // hasil 0 + buang nol belakang
  assert.deepEqual(woQtyText(0, { qtyInPack: 12, displayUom: 'Pack', stockUom: 'Nos' }),
    { main: '0 Pack', sub: '0 Nos' })
  // qty tidak valid
  assert.deepEqual(woQtyText(null, { qtyInPack: 12, displayUom: 'Pack', stockUom: 'Nos' }),
    { main: '-', sub: '' })
})

test('durationText: null/undefined kosong, 0 jujur, jam bulat dan campuran', () => {
  assert.equal(durationText(null), '')
  assert.equal(durationText(undefined), '')
  assert.equal(durationText(''), '')
  assert.equal(durationText(0), '0 menit')
  assert.equal(durationText(45), '45 menit')
  assert.equal(durationText(59), '59 menit')
  assert.equal(durationText(60), '1 jam')
  assert.equal(durationText(180), '3 jam')
  assert.equal(durationText(320), '5 jam 20 menit')
})

test('yieldSegments: persen terhadap rencana, segmen 0 dibuang, max >= 100', () => {
  // overproduksi: total 128% > 100 → max mengikuti total
  const over = yieldSegments({ planned: 100, good: 120, reject: 5, trial: 0, sisa: 3 })
  assert.deepEqual(over.segments.map((s) => s.label), ['Good', 'Reject', 'Sisa'])
  assert.deepEqual(over.segments.map((s) => s.value), [120, 5, 3])
  assert.equal(over.max, 128)
  // normal: max tetap 100 meski total kecil
  const norm = yieldSegments({ planned: 90, good: 45, reject: 9, trial: 0, sisa: 0 })
  assert.deepEqual(norm.segments.map((s) => [s.label, s.value]), [['Good', 50], ['Reject', 10]])
  assert.equal(norm.max, 100)
  // planned <= 0: semua nol, tanpa segmen
  const zero = yieldSegments({ planned: 0, good: 10, reject: 0, trial: 0, sisa: 0 })
  assert.deepEqual(zero.segments, [])
  assert.equal(zero.max, 100)
  // warna & label ikut legenda, urutan tetap Good/Reject/Trial/Sisa
  const full = yieldSegments({ planned: 100, good: 60, reject: 5, trial: 5, sisa: 5 })
  assert.deepEqual(full.segments.map((s) => s.label), ['Good', 'Reject', 'Trial', 'Sisa'])
  assert.ok(full.segments.every((s) => typeof s.color === 'string' && s.color))
})

test('attentionText: rumus judul/detail per kind sesuai kontrak FU73', () => {
  assert.deepEqual(
    attentionText({ kind: 'reject_over', wo: 'WO-1', item_name: 'Roti Tawar', reject_pct: 5.5, threshold: 3 }),
    { title: 'Roti Tawar: reject 5,5%', detail: 'Di atas ambang 3% · WO-1' }
  )
  assert.deepEqual(
    attentionText({ kind: 'stagnant', wo: 'WO-2', item_name: 'Brownis', stage: 'operasi', age_minutes: 95 }),
    { title: 'WO-2 tertahan di Operasi', detail: 'Brownis · tanpa perkembangan 1 jam 35 menit' }
  )
  // tahap tak dikenal → key mentah; age null → tanpa bagian durasi
  assert.deepEqual(
    attentionText({ kind: 'stagnant', wo: 'WO-3', item_name: 'Bolu', stage: 'misteri', age_minutes: null }),
    { title: 'WO-3 tertahan di misteri', detail: 'Bolu' }
  )
  // 'selesai' di luar STAGES (tepi presisi float, guard papan server) → label resmi
  assert.deepEqual(
    attentionText({ kind: 'stagnant', wo: 'WO-6', item_name: 'Kue', stage: 'selesai', age_minutes: 60 }),
    { title: 'WO-6 tertahan di Selesai', detail: 'Kue · tanpa perkembangan 1 jam' }
  )
  assert.deepEqual(
    attentionText({ kind: 'handover_request', mr: 'MR-9', age_minutes: 45 }),
    { title: 'Request gudang menunggu dikirim', detail: 'MR-9 · 45 menit' }
  )
  assert.deepEqual(
    attentionText({ kind: 'handover_request', mr: 'MR-9', age_minutes: null }),
    { title: 'Request gudang menunggu dikirim', detail: 'MR-9' }
  )
  assert.deepEqual(
    attentionText({ kind: 'form_order', mr: 'MR-10', age_minutes: null }),
    { title: 'Form order menunggu diproses', detail: 'MR-10' }
  )
  assert.deepEqual(
    attentionText({ kind: 'suhu', wo: 'WO-4', item_name: 'Roti Manis', adonan_ke: 2, suhu: 28.5, threshold: 26 }),
    { title: 'Suhu adonan ke-2 tinggi: 28,5°C', detail: 'Roti Manis · batas 26°C' }
  )
  assert.deepEqual(
    attentionText({ kind: 'suhu', wo: 'WO-4', item_name: 'Roti Manis', adonan_ke: null, suhu: 27, threshold: 26 }),
    { title: 'Suhu adonan tinggi: 27°C', detail: 'Roti Manis · batas 26°C' }
  )
  assert.deepEqual(
    attentionText({ kind: 'stopped', wo: 'WO-5', item_name: 'Donat' }),
    { title: 'WO-5 berstatus Stopped', detail: 'Donat' }
  )
  // kind tak dikenal → fallback judul = kind
  assert.deepEqual(attentionText({ kind: 'misteri' }), { title: 'misteri', detail: '' })
})

test('yieldPctText: fmtId + persen, null → "-"', () => {
  assert.equal(yieldPctText(87.5), '87,5%')
  assert.equal(yieldPctText(100), '100%')
  assert.equal(yieldPctText(0), '0%')
  assert.equal(yieldPctText(null), '-')
  assert.equal(yieldPctText(undefined), '-')
})

// ---- FU74: penggunaan bahan baku ----

test('materialCounts: used = consumed > 0, over = baris over; field hilang ditoleransi', () => {
  assert.deepEqual(
    materialCounts({ rows: [{ consumed: 52 }, { consumed: 0, over: true }, null, {}] }),
    { used: 1, over: 1 }
  )
  // noise float (sisa gross−retur) tidak dihitung "dipakai" (review NIT FU74)
  assert.deepEqual(materialCounts({ rows: [{ consumed: 1e-13 }] }), { used: 0, over: 0 })
  assert.deepEqual(materialCounts({}), { used: 0, over: 0 })
  assert.deepEqual(materialCounts(null), { used: 0, over: 0 })
})

test('materialSummaryText: mu kosong, belum dipakai, sesuai rencana, ada over', () => {
  assert.equal(materialSummaryText(null), '')
  assert.equal(materialSummaryText(undefined), '')
  assert.equal(materialSummaryText({}), 'Belum ada pemakaian bahan hari ini')
  assert.equal(materialSummaryText({ rows: [{ consumed: 0 }] }), 'Belum ada pemakaian bahan hari ini')
  assert.equal(
    materialSummaryText({ rows: [{ consumed: 52 }, { consumed: 3.5 }] }),
    '2 bahan dipakai · semua sesuai rencana'
  )
  assert.equal(
    materialSummaryText({ rows: [{ consumed: 52, over: true }, { consumed: 3 }, { consumed: 9, over: true }] }),
    '3 bahan dipakai · 2 di atas rencana'
  )
  // baris rusak/null dihitung aman
  assert.equal(
    materialSummaryText({ rows: [null, { consumed: 5, over: true }, {}] }),
    '1 bahan dipakai · 1 di atas rencana'
  )
})

test('materialRowText: frasa tetap "Terpakai X uom · sesuai hasil Y uom" (fmtId)', () => {
  assert.equal(materialRowText({ consumed: 52, expected: 48, uom: 'kg' }), 'Terpakai 52 kg · sesuai hasil 48 kg')
  assert.equal(materialRowText({ consumed: 52.5, expected: 48, uom: 'Kg' }), 'Terpakai 52,5 Kg · sesuai hasil 48 Kg')
  assert.equal(materialRowText({ consumed: 0, expected: 0, uom: 'kg' }), 'Terpakai 0 kg · sesuai hasil 0 kg')
  assert.equal(materialRowText({ consumed: 1200, expected: 1000, uom: 'g' }), 'Terpakai 1.200 g · sesuai hasil 1.000 g')
  // uom hilang: tanpa spasi gantung
  assert.equal(materialRowText({ consumed: 2, expected: 1 }), 'Terpakai 2 · sesuai hasil 1')
})

test('variancePctText: tanda selalu tampil, minus asli, koma desimal; null → ""', () => {
  assert.equal(variancePctText({ variance_pct: 8.3 }), '+8,3%')
  assert.equal(variancePctText({ variance_pct: -4.5 }), '−4,5%')
  assert.equal(variancePctText({ variance_pct: 12 }), '+12%')
  assert.equal(variancePctText({ variance_pct: -1250.55 }), '−1.250,55%')
  assert.equal(variancePctText({ variance_pct: 0 }), '0%')
  assert.equal(variancePctText({ variance_pct: null }), '')
  assert.equal(variancePctText({}), '')
  assert.equal(variancePctText(null), '')
})

test('bahanHref: hash bahan dengan query ter-encode', () => {
  assert.equal(bahanHref('TERIGU-01'), '#/bahan?bahan=TERIGU-01')
  assert.equal(bahanHref('Tepung Terigu'), '#/bahan?bahan=Tepung%20Terigu')
  assert.equal(bahanHref('Gula & Sirup'), '#/bahan?bahan=Gula%20%26%20Sirup')
})

// ============================== FU76: filter rentang dashboard ==============================
test('rangeParams: preset dikenal diteruskan, tak dikenal → hari_ini, kustom bawa tanggal', () => {
  assert.deepEqual(rangeParams('kemarin'), { preset: 'kemarin' })
  assert.deepEqual(rangeParams('bulan_ini'), { preset: 'bulan_ini' })
  assert.deepEqual(rangeParams('tidak_ada'), { preset: 'hari_ini' })
  assert.deepEqual(rangeParams(undefined), { preset: 'hari_ini' })
  assert.deepEqual(rangeParams('kustom', '2026-10-01', '2026-10-05'), {
    preset: 'kustom', dari: '2026-10-01', sampai: '2026-10-05'
  })
  assert.deepEqual(rangeParams('kustom', '', ''), { preset: 'kustom', dari: '', sampai: '' })
})

test('rangeLabel: satu hari = nama hari lengkap, rentang sesuai bulan/tahun', () => {
  assert.equal(rangeLabel('hari_ini', '2026-10-02', '2026-10-02'), 'Jumat, 2 Oktober 2026')
  assert.equal(rangeLabel('bulan_ini', '2026-10-01', '2026-10-31'), '1 – 31 Oktober 2026')
  assert.equal(rangeLabel('kustom', '2026-09-25', '2026-10-05'), '25 September – 5 Oktober 2026')
  assert.equal(rangeLabel('kustom', '2025-12-30', '2026-01-02'), '30 Desember 2025 – 2 Januari 2026')
  assert.equal(rangeLabel('kustom', '', ''), '')
  assert.equal(rangeLabel('kemarin', 'bukan-tanggal', '2026-10-02'), '')
})

test('selesaiTileLabel: hari ini berlabel harian, rentang lain berlabel rentang', () => {
  assert.equal(selesaiTileLabel('hari_ini'), 'Selesai hari ini')
  assert.equal(selesaiTileLabel('kemarin'), 'Selesai dalam rentang')
  assert.equal(selesaiTileLabel('kustom'), 'Selesai dalam rentang')
})

test('presetLabel: label tombol filter — tak dikenal jatuh ke Hari ini', () => {
  assert.equal(presetLabel('hari_ini'), 'Hari ini')
  assert.equal(presetLabel('bulan_kemarin'), 'Bulan kemarin')
  assert.equal(presetLabel('kustom'), 'Kustom')
  assert.equal(presetLabel('tidak_ada'), 'Hari ini')
  assert.equal(presetLabel(undefined), 'Hari ini')
})

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  STAGES, activeTotal, attentionText, durationText, materialCounts, materialRowText,
  materialSummaryText, materialUsageHref, outputTotalsText, presetLabel, rangeParams,
  rangeLabel, selesaiTileLabel,
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

test('materialUsageHref: hash penggunaan-bahan dengan query ter-encode (FU82)', () => {
  assert.equal(materialUsageHref('TERIGU-01'), '#/penggunaan-bahan?bahan=TERIGU-01')
  assert.equal(materialUsageHref('Tepung Terigu'), '#/penggunaan-bahan?bahan=Tepung%20Terigu')
  assert.equal(materialUsageHref('Gula & Sirup'), '#/penggunaan-bahan?bahan=Gula%20%26%20Sirup')
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

// ============================================================================
// FU78: KPI, chart, donut, kualitas per-UOM, bahan teratas, aktivitas, tabel
// ============================================================================

test('periodLabel: harian "2 Okt", bulanan "Okt 2026" — tanpa Date (TZ-safe)', async () => {
  const { periodLabel } = await import('../src/dashboard.js')
  assert.equal(periodLabel('2026-10-02', 'harian'), '2 Okt')
  assert.equal(periodLabel('2026-01-09', 'harian'), '9 Jan')
  assert.equal(periodLabel('2026-10', 'bulanan'), 'Okt 2026')
  assert.equal(periodLabel('2026-01', 'bulanan'), 'Jan 2026')
  assert.equal(periodLabel('', 'harian'), '')
})

test('DAILY_MODES: dua pilihan filter lokal kartu grafik (kontrak server)', async () => {
  const { DAILY_MODES } = await import('../src/dashboard.js')
  assert.deepEqual(DAILY_MODES.map((m) => m.key), ['minggu', 'bulan'])
  assert.deepEqual(DAILY_MODES.map((m) => m.label), ['Minggu ini', 'Bulan ini'])
})

test('dayLabel: nama hari id-ID dari ISO (TZ-safe); tak valid → ""', async () => {
  const { dayLabel } = await import('../src/dashboard.js')
  assert.equal(dayLabel('2026-09-28'), 'Senin')
  assert.equal(dayLabel('2026-10-02'), 'Jumat')
  assert.equal(dayLabel('2026-10-03'), 'Sabtu')
  assert.equal(dayLabel('2026-10-04'), 'Minggu')
  assert.equal(dayLabel(''), '')
  assert.equal(dayLabel('bukan-tanggal'), '')
})

test('chartDaily memetakan satu seri ke labels/planned/produced (2 desimal) — minggu nama hari, bulan tanggal', async () => {
  const { chartDaily } = await import('../src/dashboard.js')
  const seri = {
    uom: 'Pack',
    rows: [
      { period: '2026-09-28', planned: 100.456, produced: 90 },
      { period: '2026-09-29', planned: 0, produced: 83.333 }
    ]
  }
  assert.deepEqual(
    chartDaily(seri, 'minggu'),
    { labels: ['Senin', 'Selasa'], planned: [100.46, 0], produced: [90, 83.33] }
  )
  assert.deepEqual(
    chartDaily(seri, 'bulan'),
    { labels: ['28 Sep', '29 Sep'], planned: [100.46, 0], produced: [90, 83.33] }
  )
  assert.deepEqual(chartDaily(null, 'minggu'), { labels: [], planned: [], produced: [] })
  assert.deepEqual(chartDaily({}, 'bulan'), { labels: [], planned: [], produced: [] })
})

test('uomPrimaryText memilih UOM dominan + sisa digabung; kosong jujur "0"', async () => {
  const { uomPrimaryText } = await import('../src/dashboard.js')
  assert.deepEqual(
    uomPrimaryText([{ uom: 'Nos', qty: 310 }, { uom: 'Pack', qty: 110.5 }], 'Pack'),
    { main: '110,5 Pack', rest: '310 Nos' }
  )
  // dominan tak ada di list → jatuh ke entri pertama
  assert.deepEqual(uomPrimaryText([{ uom: 'Nos', qty: 310 }], 'Pack'), { main: '310 Nos', rest: '' })
  assert.deepEqual(uomPrimaryText([], 'Pack'), { main: '0', rest: '' })
  assert.deepEqual(uomPrimaryText(null, null), { main: '0', rest: '' })
})

test('achievementPct: hasil/rencana pada UOM dominan; rencana 0 → null jujur', async () => {
  const { achievementPct } = await import('../src/dashboard.js')
  assert.equal(achievementPct([{ uom: 'Pack', qty: 100 }], [{ uom: 'Pack', qty: 83.333 }], 'Pack'), 83.3)
  assert.equal(achievementPct([{ uom: 'Pack', qty: 0 }], [{ uom: 'Pack', qty: 5 }], 'Pack'), null)
  assert.equal(achievementPct([], [{ uom: 'Pack', qty: 5 }], 'Pack'), null)
  assert.equal(achievementPct(null, null, 'Pack'), null)
  // UOM dominan tak ada di salah satu list → null (jangan mengarang pasangan)
  assert.equal(achievementPct([{ uom: 'Nos', qty: 5 }], [{ uom: 'Pack', qty: 5 }], 'Pack'), null)
})

test('deltaPctText: +/− (U+2212)/0; pembanding tak valid → string kosong', async () => {
  const { deltaPctText } = await import('../src/dashboard.js')
  assert.equal(deltaPctText(106.4, 100), '+6,4%')
  assert.equal(deltaPctText(95, 100), '−5%')
  assert.equal(deltaPctText(100, 100), '0%')
  assert.equal(deltaPctText(5, 0), '')
  assert.equal(deltaPctText(10, null), '')
  assert.equal(deltaPctText(null, 10), '')
})

test('donutData: SEMUA 7 tahap ikut (kosong bernilai 0 — legend samping utuh), total = jumlah', async () => {
  const { donutData, STAGES } = await import('../src/dashboard.js')
  const { segments, total } = donutData({ persiapan: 2, operasi: 1, selesai_hari_ini: 3 })
  assert.equal(segments.length, 7)
  assert.deepEqual(segments.map((s) => s.key), STAGES.map((s) => s.key))
  assert.deepEqual(segments.map((s) => s.value), [2, 0, 1, 0, 0, 0, 3])
  assert.equal(total, 6)
  assert.ok(segments.every((s) => /^#[0-9a-f]{6}$/i.test(s.color)))
  assert.equal(donutData({}).total, 0)
  assert.deepEqual(donutData({}).segments.map((s) => s.value), [0, 0, 0, 0, 0, 0, 0])
})

test('qualityPerUom mengelompokkan per UOM — TIDAK menjumlah lintas UOM', async () => {
  const { qualityPerUom } = await import('../src/dashboard.js')
  const out = qualityPerUom([
    { uom: 'Nos', good: 10, planned: 12 },
    { uom: 'Pack', good: 5, planned: 6, reject: 1 },
    { uom: 'Nos', good: 2 }
  ])
  // Nos good 12 > Pack 5 → Nos dulu; angka Pack tak pernah bercampur Nos
  assert.deepEqual(out, [
    { uom: 'Nos', planned: 12, good: 12, reject: 0, trial: 0, sisa: 0 },
    { uom: 'Pack', planned: 6, good: 5, reject: 1, trial: 0, sisa: 0 }
  ])
  assert.deepEqual(qualityPerUom([]), [])
  assert.deepEqual(qualityPerUom(null), [])
})

test('topMaterialRows: tanpa dasar paling atas lalu |variance %|, dibatasi n', async () => {
  const { topMaterialRows } = await import('../src/dashboard.js')
  const rows = [
    { item_code: 'a', variance_pct: 5, consumed: 3 },
    { item_code: 'b', variance_pct: -20, consumed: 3 },
    { item_code: 'c', variance_pct: null, consumed: 3 },
    { item_code: 'd', variance_pct: 2, consumed: 0 } // tak dipakai → dibuang
  ]
  assert.deepEqual(topMaterialRows(rows, 2).map((r) => r.item_code), ['c', 'b'])
  assert.deepEqual(topMaterialRows(null, 3), [])
})

test('activityText merangkai judul & detail per kind (+N item lain)', async () => {
  const { activityText } = await import('../src/dashboard.js')
  assert.deepEqual(
    activityText({
      kind: 'manufacture',
      items: [
        { item_name: 'Roti Tawar', qty: 120, uom: 'Nos' },
        { item_name: 'Donat', qty: 2, uom: 'Pack' }
      ],
      item_lain: 1
    }),
    { title: 'Hasil diposting', detail: 'Roti Tawar 120 Nos, Donat 2 Pack, +1 item lain' }
  )
  assert.deepEqual(
    activityText({ kind: 'transfer', items: [{ item_name: 'Tepung', qty: 50, uom: 'Kg' }], item_lain: 0 }),
    { title: 'Bahan diserahkan', detail: 'Tepung 50 Kg' }
  )
  assert.deepEqual(activityText({ kind: 'manufacture', items: [], item_lain: 0 }),
    { title: 'Hasil diposting', detail: '' })
})

test('activityTime memecah ts jadi jam & tanggal tanpa new Date', async () => {
  const { activityTime } = await import('../src/dashboard.js')
  assert.deepEqual(activityTime('2026-10-02 10:05:00'), { time: '10:05', date: '2 Okt' })
  // frappe Time bisa jam 1 digit -> dipad 2 digit
  assert.deepEqual(activityTime('2026-10-02 9:00:00'), { time: '09:00', date: '2 Okt' })
  assert.deepEqual(activityTime('2026-01-09 07:30:12.345'), { time: '07:30', date: '9 Jan' })
  assert.deepEqual(activityTime(''), { time: '', date: '' })
  assert.deepEqual(activityTime(null), { time: '', date: '' })
})

test('woProgressPct: produced/qty dibatasi 100; qty tak valid → 0', async () => {
  const { woProgressPct } = await import('../src/dashboard.js')
  assert.equal(woProgressPct({ plannedStockQty: 100, producedStockQty: 91 }), 91)
  assert.equal(woProgressPct({ plannedStockQty: 100, producedStockQty: 120 }), 100)
  assert.equal(woProgressPct({ plannedStockQty: 0, producedStockQty: 0 }), 0)
  assert.equal(woProgressPct(null), 0)
})

test('isOverdue: target lewat & belum selesai; WO selesai tak pernah telat', async () => {
  const { isOverdue } = await import('../src/dashboard.js')
  const now = Date.parse('2026-10-02T10:00:00')
  assert.equal(isOverdue({ plannedEnd: '2026-10-02 09:00:00', stage: 'finish' }, now), true)
  assert.equal(isOverdue({ plannedEnd: '2026-10-02 11:00:00', stage: 'finish' }, now), false)
  assert.equal(isOverdue({ plannedEnd: '2026-10-02 09:00:00', stage: 'completed' }, now), false)
  assert.equal(isOverdue({ plannedEnd: '', stage: 'finish' }, now), false)
  assert.equal(isOverdue(null, now), false)
})

test('harusKeLogin & loginRedirectUrl: guest 403 not-whitelisted / 401 → login; 403 permission tetap di halaman (FU81)', async () => {
  const { harusKeLogin, loginRedirectUrl } = await import('../src/dashboard.js')
  // sesi terkick/logout di luar tab: frappe menampik SPA sbg guest →
  // "Function … is not whitelisted" (pesan bawaan utk tamu, bukan bug whitelist)
  assert.equal(harusKeLogin(403, 'Function production_app.api.work_order.wo_list is not whitelisted'), true)
  assert.equal(harusKeLogin(401, 'Session expired'), true)
  // user sah tanpa izin BUKAN logout — tetap error di halaman
  assert.equal(harusKeLogin(403, 'Not permitted'), false)
  assert.equal(harusKeLogin(417, 'Rentang tidak valid'), false)
  assert.equal(harusKeLogin(500, ''), false)
  // URL login membawa tujuan kembali: pathname + hash (pola interstitial FU67)
  assert.equal(loginRedirectUrl('/production_workspace', '#/penggunaan-bahan'),
    '/login?redirect-to=%2Fproduction_workspace%23%2Fpenggunaan-bahan')
  assert.equal(loginRedirectUrl('/production_workspace', '#/wo/MFG-WO-2026-00013'),
    '/login?redirect-to=%2Fproduction_workspace%23%2Fwo%2FMFG-WO-2026-00013')
})

test('targetText: hari ini jam saja, hari lain tanggal singkat, kosong strip (FU80e)', async () => {
  const { targetText } = await import('../src/dashboard.js')
  assert.equal(targetText('2026-10-03 14:00:00', '2026-10-03'), '14:00')
  assert.equal(targetText('2026-10-03 21:30', '2026-10-03'), '21:30')
  assert.equal(targetText('2026-10-01 10:00:00', '2026-10-03'), '1 Okt 2026')
  assert.equal(targetText('', '2026-10-03'), '-')
  assert.equal(targetText(null, '2026-10-03'), '-')
  assert.equal(targetText('2026-10-03 14:00:00', ''), '3 Okt 2026')
})

// ============================================================================
// FU79: rombak halaman Bahan baku (#/bahan) — KPI 5 kartu, perbandingan
// konsumsi, tren produksi, traceability. Semua helper murni teruji; aturan
// inti terwarisi: beda UOM TIDAK PERNAH dijumlahkan/rata-ratakan bersama.
// ============================================================================

test('woStatusText & woStatusSummary: label Indonesia + ringkasan sub-KPI', async () => {
  const { woStatusText, woStatusSummary } = await import('../src/dashboard.js')
  assert.equal(woStatusText('Completed'), 'Selesai')
  assert.equal(woStatusText('In Process'), 'Berjalan')
  assert.equal(woStatusText('Not Started'), 'Belum mulai')
  assert.equal(woStatusText('Stopped'), 'Berhenti')
  assert.equal(woStatusText('Cancelled'), 'Dibatalkan')
  assert.equal(woStatusText(''), '')
  assert.equal(woStatusSummary([]), 'Tidak ada order')
  assert.equal(
    woStatusSummary([{ status: 'Completed' }, { status: 'Completed' }]),
    'Semua selesai'
  )
  assert.equal(
    woStatusSummary([
      { status: 'Completed' }, { status: 'In Process' }, { status: 'In Process' },
      { status: 'Not Started' }
    ]),
    '1 selesai · 2 berjalan · 1 belum mulai'
  )
  // status asing tak dikenal tetap terhitung, tidak menghilang
  assert.equal(woStatusSummary([{ status: 'Weird' }]), '1 weird')
})

test('uomTotals: total per UOM tanpa mencampur, urut menurun', async () => {
  const { uomTotals } = await import('../src/dashboard.js')
  assert.deepEqual(
    uomTotals(
      [
        { uom: 'Kg', produced_qty: 30 }, { uom: 'Pack', produced_qty: 12 },
        { uom: 'Kg', produced_qty: 2 }
      ],
      'produced_qty'
    ),
    [{ uom: 'Kg', qty: 32 }, { uom: 'Pack', qty: 12 }]
  )
  assert.deepEqual(uomTotals([], 'consumed'), [])
  assert.deepEqual(uomTotals(null, 'consumed'), [])
  // konsumsi baris bahan: uom default key 'uom'
  assert.deepEqual(
    uomTotals([{ uom: 'Kg', consumed: 100.5 }, { uom: 'Kg', consumed: 1.5 }], 'consumed'),
    [{ uom: 'Kg', qty: 102 }]
  )
})

test('weightedVarPct & efficiencyPct: satu UOM saja; tanpa dasar → null', async () => {
  const { weightedVarPct, efficiencyPct } = await import('../src/dashboard.js')
  const rows = [
    { uom: 'Kg', expected: 72, consumed: 73.5, variance: 1.5 },
    { uom: 'Kg', expected: 8, consumed: 8.1, variance: 0.1 },
    { uom: 'Pcs', expected: 500, consumed: 400, variance: -100 }
  ]
  // tertimbang Kg: (1,5+0,1)/(72+8) = 2% — Pcs 500 TIDAK ikut
  assert.equal(weightedVarPct(rows, 'Kg'), 2)
  // efisiensi Kg: 80/81,6 = 98,039...% → 98
  assert.equal(efficiencyPct(rows, 'Kg'), 98)
  assert.equal(efficiencyPct(rows, 'Pcs'), 125)
  assert.equal(weightedVarPct([{ uom: 'Kg', expected: 0, consumed: 5, variance: 5 }], 'Kg'), null)
  assert.equal(weightedVarPct([], 'Kg'), null)
  assert.equal(efficiencyPct([], 'Kg'), null)
  // tanpa UOM MENOLAK (null) — menjumlah tanpa UOM = melanggar aturan inti
  assert.equal(weightedVarPct(rows, null), null)
  assert.equal(efficiencyPct(rows, null), null)
})

test('comparisonRows & barPct: urut terbesar, cap + sisa, lebar 0-100', async () => {
  const { comparisonRows, barPct } = await import('../src/dashboard.js')
  const rows = [
    { expected: 72, consumed: 73.5 },   // dasar 73,5
    { expected: 0, consumed: 0 },       // dibuang (nol dua-duanya)
    { expected: 10, consumed: 10.8 },   // dasar 10,8
    { expected: 8, consumed: 0 }        // dasar 8
  ]
  const { list, extra } = comparisonRows(rows, 2)
  assert.equal(list.length, 2)
  assert.equal(list[0].expected, 72)
  assert.equal(list[1].expected, 10)
  assert.equal(extra, 1) // baris dasar-8 terpotong
  assert.deepEqual(comparisonRows([]).extra, 0)
  assert.equal(barPct(73.5, 73.5), 100)
  assert.equal(barPct(36.75, 73.5), 50)
  assert.equal(barPct(0, 73.5), 0)
  assert.equal(barPct(10, 0), 0)
  assert.equal(barPct(-5, 73.5), 0)
  assert.equal(barPct(200, 100), 100)
})

test('varianceTone & signedQtyText: warna selisih + tanda minus asli', async () => {
  const { varianceTone, signedQtyText } = await import('../src/dashboard.js')
  assert.equal(varianceTone({ over: true, variance: 1 }), 'over')
  assert.equal(varianceTone({ over: false, variance: -0.3 }), 'under')
  assert.equal(varianceTone({ over: false, variance: 0 }), 'flat')
  assert.equal(varianceTone({ over: true, variance_pct: null }), 'over') // tanpa dasar
  assert.equal(signedQtyText(1.5, 'Kg'), '+1,5 Kg')
  assert.equal(signedQtyText(-0.3, 'Kg'), '−0,3 Kg')
  assert.equal(signedQtyText(0, 'Kg'), '0 Kg')
  assert.equal(signedQtyText(NaN, 'Kg'), '-')
  assert.equal(signedQtyText(2), '+2') // selisih selalu bertanda
})

test('chartTrend & peakDay & peakText: label tanggal + kalimat puncak', async () => {
  const { chartTrend, peakDay, peakText } = await import('../src/dashboard.js')
  const seri = { rows: [{ period: '2026-10-01', produced: 100, wo: 2 }, { period: '2026-10-02', produced: 2592, wo: 2 }] }
  assert.deepEqual(chartTrend(seri), { labels: ['1 Okt', '2 Okt'], data: [100, 2592] })
  assert.deepEqual(chartTrend(null), { labels: [], data: [] })
  assert.deepEqual(peakDay(seri.rows), { period: '2026-10-02', produced: 2592, wo: 2 })
  assert.equal(peakDay([{ period: '2026-10-01', produced: 0, wo: 0 }]), null)
  assert.equal(peakDay([]), null)
  assert.equal(
    peakText({ period: '2026-10-02', produced: 2592, wo: 2 }, 'Nos'),
    'Puncak output 2 Okt dengan 2.592 Nos dari 2 work order.'
  )
  assert.equal(
    peakText({ period: '2026-10-02', produced: 1300, wo: 1 }, 'Pcs'),
    'Puncak output 2 Okt dengan 1.300 Pcs dari 1 work order.'
  )
  assert.equal(peakText(null, 'Nos'), '')
})

test('woYieldPct & yieldTone & tanggalPendek & txnOfMaterial', async () => {
  const { woYieldPct, yieldTone, tanggalPendek, txnOfMaterial } = await import('../src/dashboard.js')
  assert.equal(woYieldPct({ planned_qty: 1296, produced_qty: 1300 }), 100.3)
  assert.equal(woYieldPct({ planned_qty: 0, produced_qty: 10 }), null)
  assert.equal(woYieldPct(null), null)
  assert.equal(yieldTone(100.3), 'ok')
  assert.equal(yieldTone(95), 'flat')
  assert.equal(yieldTone(85), 'bad')
  assert.equal(yieldTone(null), 'flat')
  assert.equal(tanggalPendek('2026-10-02'), '2 Okt 2026')
  assert.equal(tanggalPendek(''), '')
  assert.equal(tanggalPendek('2026-10'), '2026-10')
  const txns = [
    { se: 'A', item_code: 'RM1' }, { se: 'B', item_code: 'RM2' }, { se: 'C', item_code: 'RM1' }
  ]
  assert.deepEqual(txnOfMaterial(txns, 'RM1').map((t) => t.se), ['A', 'C'])
  assert.deepEqual(txnOfMaterial(txns, 'XX'), [])
  assert.deepEqual(txnOfMaterial(null, 'RM1'), [])
})

// ---- FU79c: field rentang tunggal (from → to) di panel filter bahan ----
test('rentangDmyText: format DD-MM-YYYY, tunggal tanpa "to", rentang dengan "to", tukar bila terbalik', async () => {
  const { rentangDmyText } = await import('../src/dashboard.js')
  // dari saja / dari = sampai → satu tanggal (filter from aja)
  assert.equal(rentangDmyText('2026-10-02', '2026-10-02'), '02-10-2026')
  assert.equal(rentangDmyText('2026-10-02', ''), '02-10-2026')
  assert.equal(rentangDmyText('2026-10-02', null), '02-10-2026')
  // rentang → "01-10-2026 to 02-10-2026" (format user, nol-penuh)
  assert.equal(rentangDmyText('2026-10-01', '2026-10-02'), '01-10-2026 to 02-10-2026')
  // to < from → ditukar, tetap valid
  assert.equal(rentangDmyText('2026-10-02', '2026-10-01'), '01-10-2026 to 02-10-2026')
  // kosong → '' (placeholder milik pemanggil)
  assert.equal(rentangDmyText('', ''), '')
  assert.equal(rentangDmyText(null, null), '')
  // ISO rusak → apa adanya, tidak meledak
  assert.equal(rentangDmyText('2026-10', '2026-10'), '2026-10')
})

test('normalisasiRentang: pasangan dari/sampai selalu naik; kosong diteruskan', async () => {
  const { normalisasiRentang } = await import('../src/dashboard.js')
  assert.deepEqual(normalisasiRentang('2026-10-02', '2026-10-01'), ['2026-10-01', '2026-10-02'])
  assert.deepEqual(normalisasiRentang('2026-10-01', '2026-10-02'), ['2026-10-01', '2026-10-02'])
  assert.deepEqual(normalisasiRentang('2026-10-01', '2026-10-01'), ['2026-10-01', '2026-10-01'])
  assert.deepEqual(normalisasiRentang('', '2026-10-01'), ['', '2026-10-01'])
  assert.deepEqual(normalisasiRentang(null, null), [null, null])
})

// ---- FU79d: field rentang tunggal dipakai lintas halaman (komponen RangeField) ----
test('rentangSetelahPilih: fase dari — firstTo same = satu hari, clear = dari aja (to dikosongkan)', async () => {
  const { rentangSetelahPilih } = await import('../src/dashboard.js')
  // pola bahan: endpoint wajib dari+sampai → pilihan pertama langsung satu hari
  assert.deepEqual(rentangSetelahPilih('2026-10-01', '2026-10-05', '2026-10-02', 'dari', 'same'), ['2026-10-02', '2026-10-02'])
  // pola WO/handover: from-only terbuka (semantik lama utuh) → to dikosongkan
  assert.deepEqual(rentangSetelahPilih('2026-10-01', '2026-10-05', '2026-10-02', 'dari', 'clear'), ['2026-10-02', ''])
  // default firstTo = clear
  assert.deepEqual(rentangSetelahPilih('', '', '2026-10-02', 'dari'), ['2026-10-02', ''])
})

test('rentangSetelahPilih: fase sampai — tukar bila to < from, lewat normalisasiRentang', async () => {
  const { rentangSetelahPilih } = await import('../src/dashboard.js')
  assert.deepEqual(rentangSetelahPilih('2026-10-02', '', '2026-10-01', 'sampai'), ['2026-10-01', '2026-10-02'])
  assert.deepEqual(rentangSetelahPilih('2026-10-01', '', '2026-10-03', 'sampai'), ['2026-10-01', '2026-10-03'])
  assert.deepEqual(rentangSetelahPilih('2026-10-01', '', '2026-10-01', 'sampai'), ['2026-10-01', '2026-10-01'])
})

// ---- FU80c: ekspor .xlsx (endpoint server; frontend hanya menyusun nama file)
test('materialUsageXlsxFilename: ISO ber-tanggal; produk jadi slug; satu hari tanpa _sd_; kosong generik (FU82)', async () => {
  const { materialUsageXlsxFilename } = await import('../src/dashboard.js')
  assert.equal(materialUsageXlsxFilename('2026-10-01', '2026-10-02', 'Roti Tawar'), 'penggunaan-bahan-roti-tawar-2026-10-01_sd_2026-10-02.xlsx')
  assert.equal(materialUsageXlsxFilename('2026-10-01', '2026-10-02', 'Kue "Keju", Manis'), 'penggunaan-bahan-kue-keju-manis-2026-10-01_sd_2026-10-02.xlsx')
  assert.equal(materialUsageXlsxFilename('2026-10-02', '2026-10-02', 'Roti Tawar'), 'penggunaan-bahan-roti-tawar-2026-10-02.xlsx')
  assert.equal(materialUsageXlsxFilename('2026-10-02', '2026-10-02'), 'penggunaan-bahan-2026-10-02.xlsx')
  assert.equal(materialUsageXlsxFilename('', ''), 'penggunaan-bahan.xlsx')
})

// ---- FU87: nama file ekspor XLSX ketersediaan stock (paritas server) ----
test('stockXlsxFilename: slug gudang + tanggal; kosong-tanggal generik', async () => {
  const { stockXlsxFilename } = await import('../src/dashboard.js')
  assert.equal(stockXlsxFilename('Gudang Produksi', '2026-10-03T08:00:00'), 'ketersediaan-stock-gudang-produksi-2026-10-03.xlsx')
  assert.equal(stockXlsxFilename('', '2026-10-03'), 'ketersediaan-stock-2026-10-03.xlsx')
  assert.equal(stockXlsxFilename('Kedai "Kopi", Timur', '2026-10-03'), 'ketersediaan-stock-kedai-kopi-timur-2026-10-03.xlsx')
  assert.equal(stockXlsxFilename('Gudang Produksi', ''), 'ketersediaan-stock.xlsx')
})

// ---- FU90: integrasi endpoint ketersediaan stock (store, mock global fetch) ----
function mockFetch(calls, payload) {
  const asli = globalThis.fetch
  globalThis.window = { csrf_token: 'tes' }
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, body: JSON.parse(opts.body) })
    return { ok: true, json: async () => ({ message: payload }) }
  }
  return () => {
    globalThis.fetch = asli
    delete globalThis.window
  }
}

test('loadStockAvailability memanggil endpoint & mengisi state (tanpa/dgn gudang)', async () => {
  const { loadStockAvailability, stockAvailabilityState } = await import('../src/store.js')
  const calls = []
  const payload = {
    warehouse: 'Gudang Produksi', warehouses: ['Gudang Produksi'], generated_at: '2026-10-03T08:00:00',
    summary: { total: 1, aman: 1, menipis: 0, habis: 0 },
    items: [{ item_code: 'RM-A', item_name: 'A', item_group: 'Bahan Baku', stock_uom: 'kg',
      actual_qty: 10, reserved_qty: 2, available: 8, display_uom: null, qty_in_pack: null,
      min_stock: null, status: 'aman', capacity_batch: null, capacity_detail: [],
      warehouse: 'Gudang Produksi' }]
  }
  const pulih = mockFetch(calls, payload)
  try {
    stockAvailabilityState.data = null
    stockAvailabilityState.loaded = false
    await loadStockAvailability()
    assert.equal(calls[0].url, '/api/method/production_app.api.stock_availability.stock_availability')
    assert.deepEqual(calls[0].body, {}) // tanpa gudang = server resolve default
    assert.deepEqual(stockAvailabilityState.data, payload)
    assert.equal(stockAvailabilityState.loaded, true)
    assert.equal(stockAvailabilityState.error, '')
    await loadStockAvailability('Gudang Bahan')
    assert.deepEqual(calls[1].body, { warehouse: 'Gudang Bahan' })
  } finally {
    pulih()
  }
})

test('loadStockAvailability: respons stale tidak menimpa permintaan lebih baru (FU90 review P1-1)', async () => {
  const { loadStockAvailability, stockAvailabilityState } = await import('../src/store.js')
  const asli = globalThis.fetch
  globalThis.window = { csrf_token: 'tes' }
  const tunda = []
  globalThis.fetch = async () => {
    let lepas, gagal
    const p = new Promise((res, rej) => { lepas = res; gagal = rej })
    tunda.push({ lepas, gagal })
    return { ok: true, json: async () => p }
  }
  try {
    stockAvailabilityState.data = null
    stockAvailabilityState.loaded = false
    const p1 = loadStockAvailability()
    const p2 = loadStockAvailability('Gudang Bahan')
    // stale selesai duluan (gagal) setelah permintaan baru mulai → error & loading tidak menyentuh state
    tunda[0].gagal(new Error('respons lama'))
    await p1
    assert.equal(stockAvailabilityState.error, '')
    assert.equal(stockAvailabilityState.data, null)
    assert.equal(stockAvailabilityState.loading, true) // masih dimiliki p2
    // respons baru masuk → menang
    tunda[1].lepas({ message: { warehouse: 'Gudang Bahan', items: [], summary: { total: 0, aman: 0, menipis: 0, habis: 0 } } })
    await p2
    assert.equal(stockAvailabilityState.data.warehouse, 'Gudang Bahan')
    assert.equal(stockAvailabilityState.loading, false)
    assert.equal(stockAvailabilityState.error, '')
  } finally {
    globalThis.fetch = asli
    delete globalThis.window
  }
})

test('loadStockMovements mengisi cache key gudang|item_code', async () => {
  const { loadStockMovements, stockMovementsState } = await import('../src/store.js')
  const calls = []
  const rows = [{ tanggal: '2026-10-03', jenis: 'Material Receipt', referensi: 'STE-001',
    masuk: 100, keluar: 0, saldo: 100 }]
  const pulih = mockFetch(calls, rows)
  try {
    await loadStockMovements('RM-FLOUR-001', 'Gudang Produksi')
    assert.equal(calls[0].url, '/api/method/production_app.api.stock_availability.stock_movements')
    assert.deepEqual(calls[0].body, { item_code: 'RM-FLOUR-001', warehouse: 'Gudang Produksi' })
    const entri = stockMovementsState['Gudang Produksi|RM-FLOUR-001']
    assert.equal(entri.loading, false)
    assert.equal(entri.error, '')
    assert.deepEqual([...entri.data], rows)
  } finally {
    pulih()
  }
})

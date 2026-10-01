import assert from 'node:assert/strict'
import test from 'node:test'

import {
  STAGES, activeTotal, attentionText, durationText, outputTotalsText, yieldPctText, yieldSegments
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

import assert from 'node:assert/strict'
import test from 'node:test'

import { STAGES, activeTotal, outputTotalsText } from '../src/dashboard.js'

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

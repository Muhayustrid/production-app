import assert from 'node:assert/strict'
import test from 'node:test'

import { handoverCard } from '../src/handover-card.js'

const units = { stockUom: 'Pcs', displayUom: null, qtyInPack: null }

test('keeps request document and batch on separate rows', () => {
  assert.deepEqual(handoverCard({
    kind: 'request',
    workOrder: 'MFG-WO-2026-02043',
    document: 'MAT-MR-2026-00270',
    batch: 'DubaiKK-260814-012',
    adonan: 12,
    quantity: 22,
    quantityLabel: 'Diminta',
    timestampLabel: 'Waktu',
    timestamp: '2026-09-15 06:23:00',
    units
  }), {
    workOrder: 'MFG-WO-2026-02043',
    document: 'MAT-MR-2026-00270',
    batch: 'DubaiKK-260814-012',
    adonan: '12',
    quantityLabel: 'Diminta',
    quantity: '22 Pcs',
    timestampLabel: 'Waktu',
    timestamp: '15 Sep, 06:23',
    // FU96: box dipensiunkan — tanpa argumen box = tanpa pill
    box: ''
  })
})

test('omits an absent batch and shows alternate quantity on one line', () => {
  const card = handoverCard({
    kind: 'done',
    workOrder: 'MFG-WO-2026-03133',
    document: 'MAT-STE-2026-06677',
    quantity: 216,
    quantityLabel: 'Ditransfer',
    timestampLabel: 'Dikirim',
    timestamp: '2026-09-15 07:05:00',
    units: { stockUom: 'Pcs', displayUom: 'Pack', qtyInPack: 6 },
    // FU96: satu-satunya pemakaian pill kini penanda grup (W19 hidup)
    box: 'Grup HBP-00012 (3 WO)'
  })

  assert.equal(card.batch, '')
  assert.equal(card.quantity, '36 Pack · 216 Pcs')
  assert.equal(card.box, 'Grup HBP-00012 (3 WO)')
})

test('does not show a box status on Cold Storage cards', () => {
  const card = handoverCard({
    workOrder: 'MFG-WO-2026-02043',
    quantity: 22,
    quantityLabel: 'Hasil WO',
    timestampLabel: 'Selesai',
    timestamp: '2026-09-15 06:23:00',
    units
  })

  assert.equal(card.box, '')
})

test('box null/kosong tidak pernah jadi "Box kosong" (FU96 pensiun)', () => {
  assert.equal(handoverCard({ workOrder: 'W', quantity: 1, units, box: null }).box, '')
  assert.equal(handoverCard({ workOrder: 'W', quantity: 1, units, box: undefined }).box, '')
})

test('adonan 0 (kosong pasca-Int) tampil kosong, bukan nol', () => {
  assert.equal(handoverCard({
    kind: 'request',
    workOrder: 'MFG-WO-2026-00001',
    document: 'MAT-MR-2026-00001',
    batch: null,
    adonan: 0,
    quantity: 1,
    quantityLabel: 'Diminta',
    timestampLabel: 'Waktu',
    timestamp: '2026-09-30 08:00:00',
    units
  }).adonan, '')
})

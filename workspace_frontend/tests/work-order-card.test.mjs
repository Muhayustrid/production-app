import assert from 'node:assert/strict'
import test from 'node:test'

import { workOrderCard } from '../src/work-order-card.js'

test('shows Pack and stock quantity as complete separate values', () => {
  assert.deepEqual(workOrderCard({
    quantity: 1152,
    units: { stockUom: 'Pcs', displayUom: 'Pack', qtyInPack: 12 },
    adonan: 1,
    plannedDate: '2026-09-14'
  }), {
    primaryQuantity: '96 Pack',
    stockQuantity: '1,152 Pcs',
    adonan: '1',
    dateLabel: 'Jadwal',
    date: '14 Sep'
  })
})

test('omits missing Adonan and labels completed date honestly', () => {
  assert.deepEqual(workOrderCard({
    quantity: 25,
    units: { stockUom: 'Pcs' },
    adonan: null,
    completed: true,
    finishedAt: '2026-09-15'
  }), {
    primaryQuantity: '25 Pcs',
    stockQuantity: '',
    adonan: '',
    dateLabel: 'Selesai',
    date: '15 Sep'
  })
})

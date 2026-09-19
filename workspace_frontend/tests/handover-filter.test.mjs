import test from 'node:test'
import assert from 'node:assert/strict'
import { distinctItems, filterSerahRows, rowStatusKey, serahFilterCount } from '../src/handover-filter.js'

const rows = [
  { item: 'Roti Coklat', itemCode: 'RC01', lane: 'request', createdAt: '2026-09-18 08:00:00' },
  { item: 'Roti Coklat', itemCode: 'RC01', lane: 'terkirim', createdAt: '2026-09-17 07:00:00' },
  { item: 'Krim Kopi', itemCode: 'KK02', lane: 'request', flag: 'stopped', createdAt: '2026-09-16 09:00:00' },
  { item: 'Roti Keju', itemCode: 'RK03', lane: null, flag: 'cancelled', createdAt: '' },
  { item: 'Roti Keju', itemCode: 'RK03', lane: 'request', flag: 'draft', createdAt: '2026-09-19 10:00:00' }
]

test('rowStatusKey meniru laneStatusMeta', () => {
  assert.equal(rowStatusKey(rows[0]), 'request')
  assert.equal(rowStatusKey(rows[1]), 'terkirim')
  assert.equal(rowStatusKey(rows[2]), 'stopped')
  assert.equal(rowStatusKey(rows[3]), 'cancelled')
  assert.equal(rowStatusKey(rows[4]), 'draft')
  assert.equal(rowStatusKey({ lane: null }), '-')
})

test('distinctItems unik per nama, urut abjad, bawa kode', () => {
  assert.deepEqual(distinctItems(rows), [
    { name: 'Krim Kopi', code: 'KK02' },
    { name: 'Roti Coklat', code: 'RC01' },
    { name: 'Roti Keju', code: 'RK03' }
  ])
})

test('filterSerahRows tanpa filter mengembalikan semua', () => {
  assert.equal(filterSerahRows(rows, { status: 'all', item: 'all', from: '', to: '' }).length, 5)
})

test('filterSerahRows status + item', () => {
  assert.deepEqual(
    filterSerahRows(rows, { status: 'terkirim', item: 'all', from: '', to: '' }).map((r) => r.itemCode),
    ['RC01']
  )
  assert.equal(filterSerahRows(rows, { status: 'all', item: 'Roti Keju', from: '', to: '' }).length, 2)
})

test('filterSerahRows rentang tanggal createdAt; tanpa tanggal dikecualikan saat rentang aktif', () => {
  const f = { status: 'all', item: 'all', from: '2026-09-17', to: '2026-09-18' }
  assert.deepEqual(filterSerahRows(rows, f).map((r) => r.itemCode), ['RC01', 'RC01'])
  const onlyFrom = { status: 'all', item: 'all', from: '2026-09-18', to: '' }
  assert.deepEqual(filterSerahRows(rows, onlyFrom).map((r) => r.itemCode), ['RC01', 'RK03'])
})

test('serahFilterCount menghitung filter aktif', () => {
  assert.equal(serahFilterCount({ status: 'all', item: 'all', from: '', to: '' }), 0)
  assert.equal(serahFilterCount({ status: 'terkirim', item: 'all', from: '', to: '' }), 1)
  assert.equal(serahFilterCount({ status: 'all', item: 'Krim Kopi', from: '2026-09-01', to: '2026-09-30' }), 3)
})

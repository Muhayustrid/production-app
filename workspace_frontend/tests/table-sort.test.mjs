import test from 'node:test'
import assert from 'node:assert/strict'
import { nextSortDir, sortRows } from '../src/table-sort.js'

test('nextSortDir siklus 3-klik: kosong → asc → desc → kosong', () => {
  assert.equal(nextSortDir(''), 'asc')
  assert.equal(nextSortDir('asc'), 'desc')
  assert.equal(nextSortDir('desc'), '')
})

test('sortRows teks: asc lalu desc, case-insensitive + numeric-aware', () => {
  const rows = [{ v: 'WO-10' }, { v: 'wo-2' }, { v: 'WO-1' }]
  assert.deepEqual(sortRows(rows, 'v', 'asc').map(r => r.v), ['WO-1', 'wo-2', 'WO-10'])
  assert.deepEqual(sortRows(rows, 'v', 'desc').map(r => r.v), ['WO-10', 'wo-2', 'WO-1'])
})

test('sortRows angka: urut numerik, bukan leksikal', () => {
  const rows = [{ n: 10 }, { n: 2 }, { n: 1 }]
  assert.deepEqual(sortRows(rows, 'n', 'asc', 'num').map(r => r.n), [1, 2, 10])
  assert.deepEqual(sortRows(rows, 'n', 'desc', 'num').map(r => r.n), [10, 2, 1])
})

test('sortRows: nilai kosong selalu paling bawah di kedua arah', () => {
  const rows = [{ n: 3 }, { n: null }, { n: 1 }, { n: '' }]
  assert.deepEqual(sortRows(rows, 'n', 'asc', 'num').map(r => r.n ?? ''), [1, 3, '', ''])
  assert.deepEqual(sortRows(rows, 'n', 'desc', 'num').map(r => r.n ?? ''), [3, 1, '', ''])
})

test('sortRows: dir kosong / key kosong = tidak mengubah urutan (normal)', () => {
  const rows = [{ v: 'b' }, { v: 'a' }]
  assert.deepEqual(sortRows(rows, 'v', ''), rows)
  assert.deepEqual(sortRows(rows, '', 'asc'), rows)
  // tidak memutasi array sumber
  const src = [{ v: 'b' }, { v: 'a' }]
  sortRows(src, 'v', 'asc')
  assert.equal(src[0].v, 'b')
})

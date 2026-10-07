import assert from 'node:assert/strict'
import test from 'node:test'

import { countFilters, normalizeFilters, sameFilters } from '../src/filter-rows.js'

const FIELDS = [
  { key: 'produk', type: 'multi' },
  { key: 'status', type: 'multi' },
  { key: 'jadwal', type: 'range' }
]

test('normalizeFilters: skalar lama jadi array, kosong dibuang', () => {
  assert.deepEqual(
    normalizeFilters({ produk: 'ABC', status: ['', '  ', 'In Process', 'In Process'] }, FIELDS),
    { produk: ['ABC'], status: ['In Process'] }
  )
})

test('normalizeFilters: array JSON, dedupe, nilai null/whitespace dibuang', () => {
  assert.deepEqual(
    normalizeFilters({ produk: ['RP-COKLAT', 'RP-KEJU', 'RP-COKLAT', null, ' '] }, FIELDS),
    { produk: ['RP-COKLAT', 'RP-KEJU'] }
  )
})

test('normalizeFilters: key asing dibuang, field tak aktif tak punya key', () => {
  const out = normalizeFilters({ produk: ['A'], hey: ['x'] }, FIELDS)
  assert.deepEqual(out, { produk: ['A'] })
  assert.equal('status' in out, false)
})

test('normalizeFilters: range aktif bila salah satu terisi, kosong dihapus', () => {
  assert.deepEqual(
    normalizeFilters({ jadwal: { dari: '2026-10-01', sampai: '' } }, FIELDS),
    { jadwal: { dari: '2026-10-01', sampai: '' } }
  )
  assert.deepEqual(normalizeFilters({ jadwal: { dari: '', sampai: '' } }, FIELDS), {})
})

test('normalizeFilters: raw null/undefined aman', () => {
  assert.deepEqual(normalizeFilters(null, FIELDS), {})
  assert.deepEqual(normalizeFilters(undefined, FIELDS), {})
})

test('countFilters menghitung baris, bukan nilai', () => {
  assert.equal(countFilters({ produk: ['A', 'B', 'C'], status: ['Draft'] }), 2)
  assert.equal(countFilters({}), 0)
})

test('sameFilters membandingkan isi, bukan referensi', () => {
  assert.equal(sameFilters({ produk: ['A'] }, { produk: ['A'] }), true)
  assert.equal(sameFilters({ produk: ['A'] }, { produk: ['B'] }), false)
  assert.equal(sameFilters(null, {}), true)
})

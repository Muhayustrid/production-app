import assert from 'node:assert/strict'
import test from 'node:test'

import { cloneFilters, countFilters, normalizeFilters, rangeFieldError, sameFilters } from '../src/filter-rows.js'

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

// FU102: draft/applied tidak boleh berbagi objek (bocor lewat v-model
// draft[key].dari sebelum Terapkan) — klon satu level memutus keduanya
test('cloneFilters melepas array dan objek rentang dari sumbernya', () => {
  const asli = { produk: ['A', 'B'], rentang: { dari: '2026-10-01', sampai: '2026-10-02' } }
  const salinan = cloneFilters(asli)
  assert.deepEqual(salinan, asli)
  salinan.produk.push('C')
  salinan.rentang.dari = '2026-10-09'
  assert.deepEqual(asli.produk, ['A', 'B'])
  assert.equal(asli.rentang.dari, '2026-10-01')
  assert.deepEqual(cloneFilters(null), {})
})

// FU102: validasi nilai baris rentang (Dashboard: wajib dari+sampai, ≤366 hari)
test('rangeFieldError: baris kosong belum salah, wajib dua tanggal', () => {
  const f = { requireBoth: true, maxSpan: 366 }
  assert.equal(rangeFieldError({ dari: '', sampai: '' }, f), '')
  assert.equal(rangeFieldError({ dari: '2026-10-01', sampai: '' }, f), 'Pilih tanggal awal dan akhir.')
  assert.equal(rangeFieldError({ dari: '', sampai: '2026-10-02' }, f), 'Pilih tanggal awal dan akhir.')
  assert.equal(rangeFieldError({ dari: '2026-10-01', sampai: '2026-10-02' }, f), '')
})

test('rangeFieldError: batas lebar hanya saat dua tanggal terisi', () => {
  const f = { requireBoth: true, maxSpan: 366 }
  assert.equal(rangeFieldError({ dari: '2026-01-01', sampai: '2026-12-31' }, f), '') // 364 hari
  assert.equal(
    rangeFieldError({ dari: '2025-01-01', sampai: '2026-12-31' }, f),
    'Rentang maksimal 366 hari.'
  )
  assert.equal(rangeFieldError({ dari: '2026-01-01', sampai: '2026-12-31' }, {}), '') // tanpa batas
})

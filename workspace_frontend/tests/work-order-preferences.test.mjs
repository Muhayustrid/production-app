import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildWorkOrderPreferences,
  normalizeWorkOrderPreferences
} from '../src/work-order-preferences.js'

// FU100: bentuk baru = array multi-value; preferensi lama (skalar) jadi fallback
test('migrates legacy scalar preferences to arrays', () => {
  assert.deepEqual(normalizeWorkOrderPreferences({
    q: 'kopi',
    product: 'PJ260016',
    status: 'In Process',
    stage: 'finish',
    from: '2026-09-01',
    to: '2026-09-15',
    pageSize: 100,
    filterOpen: true,
    view: 'kanban'
  }), {
    q: 'kopi',
    products: ['PJ260016'],
    statuses: ['In Process'],
    stages: ['finish'],
    from: '2026-09-01',
    to: '2026-09-15',
    pageSize: 100,
    filterOpen: true,
    view: 'kanban'
  })
})

test('legacy "all" sentinels become empty arrays', () => {
  assert.deepEqual(normalizeWorkOrderPreferences({ product: 'all', status: 'all', stage: 'done' }), {
    q: '',
    products: [],
    statuses: [],
    stages: ['selesai'], // 'done' dipetakan ke token server
    from: '',
    to: '',
    pageSize: undefined,
    filterOpen: false,
    view: 'tabel'
  })
})

test('new array shape round-trips and stays clean', () => {
  const prefs = buildWorkOrderPreferences({
    q: '', products: ['A', 'B'], statuses: [], stages: ['material'], pageSize: 20, view: 'tabel'
  })
  assert.deepEqual(prefs.products, ['A', 'B'])
  assert.deepEqual(prefs.statuses, [])
  // baca balik: bentuk baru stabil
  assert.deepEqual(normalizeWorkOrderPreferences(prefs), prefs)
  // skalar di field array (payload lama) diterima sebagai satu anggota
  assert.deepEqual(normalizeWorkOrderPreferences({ products: 'A' }).products, ['A'])
})

test('keeps backward-compatible defaults and saves the selected view', () => {
  assert.equal(normalizeWorkOrderPreferences({}).view, 'tabel')
  assert.equal(normalizeWorkOrderPreferences({ view: 'unknown' }).view, 'tabel')
  assert.equal(buildWorkOrderPreferences({ view: 'kanban' }).view, 'kanban')
})

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildWorkOrderPreferences,
  normalizeWorkOrderPreferences
} from '../src/work-order-preferences.js'

test('restores a saved product before its option list is loaded', () => {
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
    product: 'PJ260016',
    status: 'In Process',
    stage: 'finish',
    from: '2026-09-01',
    to: '2026-09-15',
    pageSize: 100,
    filterOpen: true,
    view: 'kanban'
  })
})

test('keeps backward-compatible defaults and saves the selected view', () => {
  assert.equal(normalizeWorkOrderPreferences({}).view, 'tabel')
  assert.equal(normalizeWorkOrderPreferences({ view: 'unknown' }).view, 'tabel')
  assert.equal(buildWorkOrderPreferences({ product: 'PJ260016', view: 'kanban' }).view, 'kanban')
})

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { boardMatch } from '../src/handover-search.js'

test('query kosong / spasi: semua kartu lolos', () => {
  assert.equal(boardMatch({ name: 'Roti Tawar' }, ''), true)
  assert.equal(boardMatch({ name: 'Roti Tawar' }, '   '), true)
  assert.equal(boardMatch({}, null), true)
})

test('cocok nama item tanpa peduli huruf besar/kecil', () => {
  const card = { name: 'Roti Tawar Milk', workOrder: 'MFG-WO-2026-00001' }
  assert.equal(boardMatch(card, 'tawar'), true)
  assert.equal(boardMatch(card, 'MILK'), true)
})

test('cocok nomor WO, dokumen, dan batch', () => {
  const card = { name: 'Roti', workOrder: 'MFG-WO-2026-03411', document: 'MAT-MR-2026-00400', batch: 'BAT-77' }
  assert.equal(boardMatch(card, '03411'), true)
  assert.equal(boardMatch(card, 'MAT-MR-2026-00400'), true)
  assert.equal(boardMatch(card, 'bat-77'), true)
})

test('tanpa kecocokan: kartu gugur', () => {
  const card = { name: 'Roti', workOrder: 'MFG-WO-2026-03411' }
  assert.equal(boardMatch(card, 'donat'), false)
  assert.equal(boardMatch({}, 'x'), false)
})

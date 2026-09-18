import assert from 'node:assert/strict'
import { test } from 'node:test'
import { rowClickAction, seRouteLabel } from '../src/handover-se.js'

const req = (over = {}) => ({ lane: 'request', flag: null, stockEntry: null, ...over })

test('request tanpa flag: aksi baris mengikuti role (semantik kartu kanban)', () => {
  const produksi = { is_gudang: false, is_produksi: true }
  const gudang = { is_gudang: true, is_produksi: false }
  const multi = { is_gudang: true, is_produksi: true }
  assert.equal(rowClickAction(req(), produksi), 'send')
  assert.equal(rowClickAction(req(), gudang), 'cancel')
  assert.equal(rowClickAction(req(), multi), 'choose')
})

test('tanpa role gudang/produksi: baris tidak klikabel', () => {
  assert.equal(rowClickAction(req(), { is_gudang: false, is_produksi: false }), null)
})

test('flag stopped/cancelled/draft tidak klikabel (kartu mati/riwayat Desk)', () => {
  const roles = { is_gudang: true, is_produksi: true }
  assert.equal(rowClickAction(req({ flag: 'stopped' }), roles), null)
  assert.equal(rowClickAction(req({ flag: 'cancelled' }), roles), null)
  assert.equal(rowClickAction(req({ flag: 'draft' }), roles), null)
})

test('baris terkirim membuka detail baca-saat SE termuat', () => {
  const roles = { is_gudang: false, is_produksi: true }
  assert.equal(rowClickAction(req({ lane: 'terkirim', stockEntry: 'STE-2026-001' }), roles), 'done')
  // lane terkirim tanpa bukti SE termuat — tetap diam, tidak ada yang bisa dibaca
  assert.equal(rowClickAction(req({ lane: 'terkirim', stockEntry: null }), roles), null)
  // detail baca-saja tersedia untuk SEMUA role (bukan hanya produksi)
  assert.equal(rowClickAction(req({ lane: 'terkirim', stockEntry: 'STE-2026-001' }), { is_gudang: true, is_produksi: false }), 'done')
})

test('input kosong/null aman', () => {
  assert.equal(rowClickAction(null, { is_produksi: true }), null)
  assert.equal(rowClickAction(req(), null), null)
})

test('seRouteLabel: rute MR + fallback target papan / label Cold Storage', () => {
  assert.equal(seRouteLabel({ fromWarehouse: 'Cold Storage', toWarehouse: 'Gudang BJ' }), 'Cold Storage → Gudang BJ')
  assert.equal(seRouteLabel({ fromWarehouse: 'Cold Storage' }, 'Gudang BJ'), 'Cold Storage → Gudang BJ')
  assert.equal(seRouteLabel({}, 'Gudang BJ'), 'Cold Storage → Gudang BJ')
  assert.equal(seRouteLabel({}), 'Cold Storage → -')
  assert.equal(seRouteLabel(null, 'Gudang BJ'), 'Cold Storage → Gudang BJ')
})

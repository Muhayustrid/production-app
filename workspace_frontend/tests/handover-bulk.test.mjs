import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

import {
  BULK_LIMIT,
  validateBoxKg,
  validateBulkEntries,
  classifyBulkError,
  runBulkItems,
  CARD_LANE,
  bulkCardEligible,
  bulkEntryOfCard,
  toggleBulkSelection,
  selectAllBulk,
  bulkLaneActions,
  reconcileBulkSelection,
  bulkRetryAvailable,
  bulkEligibleRefs,
  bulkRequiresReload
} from '../src/handover-bulk.js'

import { call, bulkHandoverItem, handoverState, handoverLots, handoverRequests } from '../src/store.js'

// peran ganda: cek struktural (lane/duplikat/limit) tak terhalang cek peran;
// matriks peran diuji eksplisit di test tersendiri
const ROLES = { is_gudang: true, is_produksi: true }

// call() membaca window.csrf_token — sediakan global window utk uji Node
globalThis.window = { csrf_token: '' }

const cold = (wo) => ({ lane: 'cold', action: 'create_request', work_order: wo })
const reqCancel = (mr) => ({ lane: 'request', action: 'cancel_request', material_request: mr })
const reqVerify = (mr, box_1 = '', box_2 = '') => ({ lane: 'request', action: 'save_post_packing', material_request: mr, box_1, box_2 })
const siap = (mr) => ({ lane: 'siap', action: 'send_handover', material_request: mr })

// ---------------------------------------------------------------- validateBoxKg

test('validateBoxKg: blank maps to null, valid numbers pass through', () => {
  assert.equal(validateBoxKg(''), null)
  assert.equal(validateBoxKg(null), null)
  assert.equal(validateBoxKg(undefined), null)
  assert.equal(validateBoxKg(12.5), 12.5)
  assert.equal(validateBoxKg('8.25'), 8.25)
  assert.equal(validateBoxKg(0), 0)
})

test('validateBoxKg: rejects negative and non-finite values', () => {
  assert.throws(() => validateBoxKg(-1), /negatif/)
  assert.throws(() => validateBoxKg(Infinity), /angka/)
  assert.throws(() => validateBoxKg('abc'), /angka/)
  assert.throws(() => validateBoxKg(NaN), /angka/)
})

// ---------------------------------------------------------- validateBulkEntries

test('validateBulkEntries: enforces 1..20 unique entries', () => {
  assert.throws(() => validateBulkEntries([], { roles: ROLES }), /minimal/)
  const many = Array.from({ length: BULK_LIMIT + 1 }, (_, i) => cold(`MFG-WO-${i}`))
  assert.throws(() => validateBulkEntries(many, { roles: ROLES }), /Maksimal 20/)
  const exactly20 = Array.from({ length: 20 }, (_, i) => cold(`MFG-WO-${i}`))
  assert.equal(validateBulkEntries(exactly20, { roles: ROLES }).length, 20)
})

test('validateBulkEntries: rejects duplicate references', () => {
  assert.throws(() => validateBulkEntries([siap('MAT-MR-1'), siap('MAT-MR-1')], { roles: ROLES }), /lebih dari sekali/)
})

test('validateBulkEntries: rejects a mixed-lane selection', () => {
  assert.throws(() => validateBulkEntries([cold('MFG-WO-1'), siap('MAT-MR-1')], { roles: ROLES }), /satu lane/)
})

test('validateBulkEntries: rejects empty or non-string references', () => {
  assert.throws(() => validateBulkEntries([{ lane: 'cold', action: 'create_request', work_order: '' }], { roles: ROLES }), /kosong/)
  assert.throws(() => validateBulkEntries([{ lane: 'siap', action: 'send_handover', material_request: 42 }], { roles: ROLES }), /kosong/)
  assert.throws(() => validateBulkEntries([{ lane: 'siap', action: 'send_handover' }], { roles: ROLES }), /kosong/)
})

test('validateBulkEntries: rejects action not belonging to the lane', () => {
  assert.throws(() => validateBulkEntries([{ lane: 'siap', action: 'create_request', material_request: 'MAT-MR-1' }], { roles: ROLES }), /tidak sesuai/)
})

test('validateBulkEntries: role/action eligibility per spec section 3.2', () => {
  const gudang = { is_gudang: true, is_produksi: false }
  const produksi = { is_gudang: false, is_produksi: true }
  assert.doesNotThrow(() => validateBulkEntries([cold('MFG-WO-1')], { roles: gudang }))
  assert.throws(() => validateBulkEntries([cold('MFG-WO-1')], { roles: produksi }), /peran/)
  assert.doesNotThrow(() => validateBulkEntries([reqCancel('MAT-MR-1')], { roles: gudang }))
  assert.throws(() => validateBulkEntries([reqCancel('MAT-MR-1')], { roles: produksi }), /peran/)
  assert.doesNotThrow(() => validateBulkEntries([reqVerify('MAT-MR-1')], { roles: produksi }))
  assert.throws(() => validateBulkEntries([reqVerify('MAT-MR-1')], { roles: gudang }), /peran/)
  assert.doesNotThrow(() => validateBulkEntries([siap('MAT-MR-1')], { roles: produksi }))
  assert.throws(() => validateBulkEntries([siap('MAT-MR-1')], { roles: gudang }), /peran/)
  assert.throws(() => validateBulkEntries([cold('MFG-WO-1')], { roles: { is_gudang: false, is_produksi: false } }), /peran/)
})

test('validateBulkEntries: normalizes boxes and always carries both box keys', () => {
  const out = validateBulkEntries([reqVerify('MAT-MR-1', '12.5', '')], { roles: { is_gudang: false, is_produksi: true } })
  assert.deepEqual(out, [{ lane: 'request', action: 'save_post_packing', material_request: 'MAT-MR-1', box_1: 12.5, box_2: null }])
  assert.throws(() => validateBulkEntries([reqVerify('MAT-MR-1', -3)], { roles: { is_gudang: false, is_produksi: true } }), /negatif/)
})

// ------------------------------------------------------------ classifyBulkError

test('classifyBulkError: expected vs abort kinds, unknown fails safe to transport', () => {
  assert.equal(classifyBulkError({ bulkKind: 'expected' }), 'expected')
  assert.equal(classifyBulkError({ bulkKind: 'transport' }), 'transport')
  assert.equal(classifyBulkError({ bulkKind: 'timeout' }), 'transport')
  assert.equal(classifyBulkError({ bulkKind: 'malformed' }), 'malformed')
  assert.equal(classifyBulkError(new Error('raw TypeError')), 'transport')
  assert.equal(classifyBulkError(null), 'transport')
})

// ----------------------------------------------------------------- runBulkItems

// rpc tiruan: sekuensial ketat — satukan pelacakan konkurensi di satu tempat
function fakeRpc(script) {
  const calls = []
  let active = 0
  let maxActive = 0
  const rpc = async (action, entry) => {
    calls.push({ action, entry })
    active += 1
    maxActive = Math.max(maxActive, active)
    try {
      const step = script[calls.length - 1]
      if (step instanceof Error) throw step
      if (step === 'abort') throw Object.assign(new Error('ECONNRESET /api /secret traceback'), { bulkKind: 'transport' })
      if (step === 'timeout') throw Object.assign(new Error('abort timeout'), { bulkKind: 'timeout' })
      if (step === 'malformed') throw Object.assign(new Error('Unexpected token < in JSON'), { bulkKind: 'malformed' })
      if (step === 'http5xx') throw Object.assign(new Error('Server gagal memproses permintaan.'), { bulkKind: 'transport' })
      if (step === 'business') throw Object.assign(new Error('Stok tidak cukup.'), { bulkKind: 'expected' })
      return { ok: true }
    } finally {
      active -= 1
    }
  }
  return { rpc, calls, get maxActive() { return maxActive } }
}

function runner(entries, script, opts = {}) {
  const fake = fakeRpc(script)
  let reloads = 0
  const progress = []
  const promise = runBulkItems({
    entries,
    roles: opts.roles || ROLES,
    rpc: fake.rpc,
    loadBoard: () => { reloads += 1 },
    onProgress: (p) => progress.push(p),
    runId: 'BULK-TEST'
  })
  return { promise, fake, reloads: () => reloads, progress }
}

test('runBulkItems: sequential order, maxConcurrent 1, expected failures continue', async () => {
  const entries = [siap('MAT-MR-1'), siap('MAT-MR-2'), siap('MAT-MR-3'), siap('MAT-MR-4')]
  const { promise, fake, reloads, progress } = runner(entries, ['business', 'ok', 'ok', 'ok'])
  const result = await promise
  assert.equal(fake.maxActive, 1, 'never more than one in-flight request')
  assert.deepEqual(fake.calls.map(c => c.action), ['send_handover', 'send_handover', 'send_handover', 'send_handover'])
  assert.deepEqual(fake.calls.map(c => c.entry.material_request), ['MAT-MR-1', 'MAT-MR-2', 'MAT-MR-3', 'MAT-MR-4'])
  assert.deepEqual(result.results.map(r => r.status), ['failed', 'success', 'success', 'success'])
  assert.equal(result.results[0].message, 'Stok tidak cukup.')
  assert.equal(result.failures.length, 1)
  assert.equal(result.successes.length, 3)
  assert.equal(result.aborted, false)
  assert.equal(reloads(), 1, 'final reload exactly once')
})

test('runBulkItems: save_post_packing payload sends entry object with both boxes', async () => {
  const { promise, fake } = runner([reqVerify('MAT-MR-1', '12.5')], ['ok'])
  await promise
  assert.deepEqual(fake.calls[0].entry, { material_request: 'MAT-MR-1', box_1: 12.5, box_2: null })
  assert.equal(typeof fake.calls[0].entry, 'object')
})

test('runBulkItems: progress shape done/total/ref', async () => {
  const entries = [cold('MFG-WO-1'), cold('MFG-WO-2')]
  const { promise, progress } = runner(entries, ['ok', 'ok'])
  await promise
  assert.deepEqual(progress, [
    { done: 0, total: 2, ref: 'MFG-WO-1' },
    { done: 1, total: 2, ref: 'MFG-WO-2' }
  ])
})

for (const kind of ['abort', 'timeout', 'malformed', 'http5xx']) {
  test(`runBulkItems: ${kind} aborts run — uncertain current, unprocessed later, reload once`, async () => {
    const entries = [siap('MAT-MR-1'), siap('MAT-MR-2'), siap('MAT-MR-3'), siap('MAT-MR-4')]
    const { promise, fake, reloads } = runner(entries, ['ok', kind, 'ok', 'ok'])
    const result = await promise
    assert.equal(fake.calls.length, 2, 'later cards are not sent')
    assert.deepEqual(result.results.map(r => r.status), ['success', 'uncertain', 'unprocessed', 'unprocessed'])
    assert.equal(result.aborted, true)
    assert.equal(result.uncertain.ref, 'MAT-MR-2')
    assert.equal(result.unprocessed.length, 2)
    assert.ok(result.uncertain.correlationId.startsWith('BULK-TEST-'), 'correlation id present')
    // pesan generik: tidak membocorkan pesan/jejak error mentah
    assert.ok(!result.uncertain.message.includes('ECONNRESET'))
    assert.ok(!result.uncertain.message.includes('secret'))
    assert.ok(!result.uncertain.message.includes('traceback'))
    assert.equal(reloads(), 1, 'final reload exactly once even after abort')
    assert.equal(result.boardReloaded, true)
  })
}

test('runBulkItems: reload failure keeps results and reports boardReloaded false', async () => {
  let reloads = 0
  const { rpc } = fakeRpc(['ok'])
  const result = await runBulkItems({
    entries: [siap('MAT-MR-1')], roles: ROLES, rpc,
    loadBoard: () => { reloads += 1; throw new Error('board down') },
    runId: 'BULK-TEST'
  })
  assert.equal(reloads, 1)
  assert.equal(result.results[0].status, 'success', 'committed results are not lost')
  assert.equal(result.boardReloaded, false)
})

test('runBulkItems: validation failure happens before any rpc and without reload', async () => {
  const { rpc, calls } = fakeRpc([])
  let reloads = 0
  await assert.rejects(
    () => runBulkItems({ entries: [], roles: ROLES, rpc, loadBoard: () => { reloads += 1 }, runId: 'BULK-TEST' }),
    /minimal/
  )
  assert.equal(calls.length, 0)
  assert.equal(reloads, 0)
})

// ------------------------------------------------ store.js call() classification

function stubFetch(handler) {
  const requests = []
  globalThis.fetch = async (url, opts) => {
    requests.push({ url, body: JSON.parse(opts.body), signal: opts?.signal })
    return handler(requests.length)
  }
  return requests
}

const okJson = (message) => ({ ok: true, status: 200, json: async () => ({ message }) })
const frappeBusiness = (msg) => ({
  ok: false, status: 500, statusText: 'INTERNAL SERVER ERROR',
  json: async () => ({ exc_type: 'ValidationError', _server_messages: JSON.stringify([JSON.stringify({ message: msg })]) })
})

test('call(): expected business failure keeps user message and marks expected', async () => {
  stubFetch(() => frappeBusiness('Stok tidak cukup.'))
  await assert.rejects(() => call('production_app.api.handover.send_handover', {}), (e) => {
    assert.equal(e.bulkKind, 'expected')
    assert.equal(e.message, 'Stok tidak cukup.')
    return true
  })
})

test('call(): transport failure (fetch reject), HTTP 5xx without server messages, malformed JSON', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(() => call('x', {}), (e) => e.bulkKind === 'transport' && !e.message.includes('Failed'))

  stubFetch(() => ({ ok: false, status: 502, statusText: 'BAD GATEWAY', json: async () => ({ exc: 'Traceback...' }) }))
  await assert.rejects(() => call('x', {}), (e) => {
    assert.equal(e.bulkKind, 'transport')
    assert.ok(!e.message.includes('Traceback'), 'never exposes raw exception text')
    return true
  })

  stubFetch(() => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token') } }))
  await assert.rejects(() => call('x', {}), (e) => e.bulkKind === 'malformed')
})

test('call(): 200 without message envelope is malformed', async () => {
  stubFetch(() => ({ ok: true, status: 200, json: async () => ({}) }))
  await assert.rejects(() => call('x', {}), (e) => e.bulkKind === 'malformed')
})

test('bulkHandoverItem: direct boardless RPC, entry as object, no board/pending side effects', async () => {
  const requests = stubFetch(() => okJson({ material_request: 'MAT-MR-1', box_1: 1, box_2: null }))
  handoverState.pending = null
  const res = await bulkHandoverItem('save_post_packing', { material_request: 'MAT-MR-1', box_1: 1, box_2: null })
  assert.equal(res.material_request, 'MAT-MR-1')
  assert.equal(requests[0].url, '/api/method/production_app.api.handover.bulk_handover_item')
  assert.equal(typeof requests[0].body.entry, 'object', 'entry is sent as a JSON object')
  assert.deepEqual(requests[0].body.action, 'save_post_packing')
  assert.deepEqual(Object.keys(requests[0].body.entry).sort(), ['box_1', 'box_2', 'material_request'])
  assert.equal(requests[0].body.entry.material_request, 'MAT-MR-1')
  assert.equal(handoverState.pending, null, 'never touches handoverState.pending')
  assert.equal(handoverLots.length, 0, 'never applies a board')
  assert.equal(handoverRequests.length, 0, 'never applies a board')
})

// ============================ T40 phase B: selection & reconciliation helpers ============================

const selCard = (kind, ref, over = {}) => ({
  kind, ref, workOrder: kind === 'lot' ? ref : 'MFG-WO-9',
  document: kind === 'lot' ? '' : ref, name: 'Produk', live: true, pending: false, ...over
})

test('CARD_LANE maps card kinds to board lanes; kirim has no bulk action', () => {
  assert.deepEqual(CARD_LANE, { lot: 'cold', request: 'request', siap: 'siap', done: 'kirim' })
  assert.deepEqual(bulkLaneActions('kirim', { is_gudang: true, is_produksi: true }), [])
})

test('bulkCardEligible: role-aware per lane, Terkirim never selectable', () => {
  const g = { is_gudang: true, is_produksi: false }
  const p = { is_gudang: false, is_produksi: true }
  assert.ok(bulkCardEligible(selCard('lot', 'MFG-WO-1'), { roles: g }))
  assert.ok(!bulkCardEligible(selCard('lot', 'MFG-WO-1'), { roles: p }), 'cold is gudang-only')
  assert.ok(bulkCardEligible(selCard('request', 'MAT-MR-1'), { roles: g }))
  assert.ok(bulkCardEligible(selCard('request', 'MAT-MR-1'), { roles: p }))
  assert.ok(!bulkCardEligible(selCard('request', 'MAT-MR-1'), { roles: {} }), 'no role -> no action')
  assert.ok(bulkCardEligible(selCard('siap', 'MAT-MR-2'), { roles: p }))
  assert.ok(!bulkCardEligible(selCard('siap', 'MAT-MR-2'), { roles: g }), 'send is produksi-only')
  assert.ok(!bulkCardEligible(selCard('done', 'MAT-MR-3'), { roles: p }), 'Terkirim never selectable')
})

test('bulkCardEligible: live/supported/pending and lane-lock conditions', () => {
  const dual = { is_gudang: true, is_produksi: true }
  assert.ok(!bulkCardEligible(selCard('request', 'MAT-MR-1', { live: false }), { roles: dual }), 'dead/stopped card ineligible')
  assert.ok(!bulkCardEligible(selCard('lot', 'MFG-WO-1', { pending: true }), { roles: dual }), 'pending card ineligible')
  assert.ok(bulkCardEligible(selCard('request', 'MAT-MR-1'), { roles: dual, selectedLane: 'request' }))
  assert.ok(!bulkCardEligible(selCard('request', 'MAT-MR-1'), { roles: dual, selectedLane: 'cold' }), 'cross-lane locked out')
  assert.ok(!bulkCardEligible(null, { roles: dual }))
})

test('bulkEntryOfCard: flat snapshot without card objects, box keys untouched here', () => {
  const e = bulkEntryOfCard(selCard('request', 'MAT-MR-1'))
  assert.deepEqual(e, { lane: 'request', kind: 'request', ref: 'MAT-MR-1', workOrder: 'MFG-WO-9', materialRequest: 'MAT-MR-1', name: 'Produk', quantity: '', batch: '', note: '' })
  const lot = bulkEntryOfCard(selCard('lot', 'MFG-WO-1'))
  assert.equal(lot.lane, 'cold')
  assert.equal(lot.materialRequest, '', 'cold lots carry no material request')
})

test('toggleBulkSelection: first pick, toggle off, lane guard, 20-card refusal', () => {
  const a = bulkEntryOfCard(selCard('lot', 'MFG-WO-1'))
  const one = toggleBulkSelection([], a)
  assert.deepEqual(one, [a])
  assert.deepEqual(toggleBulkSelection(one, a), [], 'same card toggles off')
  assert.throws(() => toggleBulkSelection(one, bulkEntryOfCard(selCard('request', 'MAT-MR-1'))), /lane/, 'cross-lane refused')
  const full = Array.from({ length: 20 }, (_, i) => bulkEntryOfCard(selCard('lot', `MFG-WO-${i}`)))
  assert.throws(() => toggleBulkSelection(full, bulkEntryOfCard(selCard('lot', 'MFG-WO-X'))), /Maksimal 20/, 'card 21 refused with clear message')
  assert.equal(toggleBulkSelection(full, full[0]).length, 19, 'removal still allowed at cap')
})

test('selectAllBulk: only eligible visible cards in locked lane, capped at 20, merges without duplicates', () => {
  const dual = { is_gudang: true, is_produksi: true }
  const cards = [
    selCard('lot', 'MFG-WO-1'),
    selCard('lot', 'MFG-WO-2', { live: false }),
    selCard('request', 'MAT-MR-1'),
    selCard('done', 'MAT-MR-9')
  ]
  const all = selectAllBulk(cards, { roles: dual, selectedLane: 'cold' })
  assert.deepEqual(all.entries.map((e) => e.ref), ['MFG-WO-1'], 'only eligible, only locked lane')
  assert.equal(all.truncated, false)

  const many = Array.from({ length: 25 }, (_, i) => selCard('lot', `MFG-WO-${i}`))
  const capped = selectAllBulk(many, { roles: dual, selectedLane: 'cold' })
  assert.equal(capped.entries.length, 20)
  assert.equal(capped.truncated, true)

  const existing = [bulkEntryOfCard(selCard('lot', 'MFG-WO-0'))]
  const merged = selectAllBulk(many, { roles: dual, selectedLane: 'cold', selected: existing })
  assert.equal(merged.entries.length, 20)
  assert.equal(new Set(merged.entries.map((e) => e.ref)).size, 20, 'no duplicates when merging')
})

test('bulkLaneActions: full role matrix including dual-role request lane', () => {
  const g = { is_gudang: true, is_produksi: false }
  const p = { is_gudang: false, is_produksi: true }
  const d = { is_gudang: true, is_produksi: true }
  assert.deepEqual(bulkLaneActions('cold', g), ['create_request'])
  assert.deepEqual(bulkLaneActions('cold', p), [])
  assert.deepEqual(bulkLaneActions('request', g), ['cancel_request'])
  assert.deepEqual(bulkLaneActions('request', p), ['save_post_packing'])
  assert.deepEqual(bulkLaneActions('request', d), ['cancel_request', 'save_post_packing'], 'dual role gets both explicit buttons')
  assert.deepEqual(bulkLaneActions('siap', p), ['send_handover'])
  assert.deepEqual(bulkLaneActions('siap', g), [])
  assert.deepEqual(bulkLaneActions('kirim', d), [])
})

test('reconcileBulkSelection: successes always cleared; failures/unprocessed/uncertain kept only while eligible in original lane', () => {
  const selected = ['A', 'B', 'C', 'D', 'E', 'F'].map((r) => ({ lane: 'siap', ref: r }))
  const result = {
    successes: [{ ref: 'A' }, { ref: 'B' }],
    failures: [{ ref: 'C' }, { ref: 'D' }],
    uncertain: { ref: 'E' },
    unprocessed: [{ ref: 'F' }]
  }
  // server truth after reload: D left the original lane, the rest are still eligible
  const kept = reconcileBulkSelection(selected, result, (e) => e.ref !== 'D')
  assert.deepEqual(kept.map((e) => e.ref), ['C', 'E', 'F'], 'success cleared, moved-lane failure cleared, uncertain reconciled from server truth')
  // input order preserved
  const none = reconcileBulkSelection(selected, result, () => false)
  assert.deepEqual(none, [])
})

// ---------------- store.js: bulk-only timeout + 401/403 classification (review T3 minors) ----------------

test('call(): bulk-only finite timeout aborts with timeout kind; legacy callers get no AbortSignal', async () => {
  const seen = []
  globalThis.fetch = (url, opts) => new Promise((resolve, reject) => {
    seen.push(opts)
    const t = setTimeout(() => resolve(okJson({ ok: 1 })), 200)
    opts?.signal?.addEventListener('abort', () => {
      clearTimeout(t)
      reject(Object.assign(new Error('The operation was aborted'), { name: 'AbortError' }))
    })
  })
  await call('x', {})
  assert.equal(seen[0].signal, undefined, 'legacy callers: no AbortSignal, no timeout change')

  await assert.rejects(() => call('x', {}, { timeoutMs: 15 }), (e) => {
    assert.equal(e.bulkKind, 'timeout')
    assert.ok(!e.message.includes('aborted'), 'no raw engine error text')
    return true
  })
  assert.ok(seen[1].signal instanceof AbortSignal, 'bulk timeout path passes a signal')
})

test('call(): 401/403 without server messages are infrastructure aborts, not expected failures', async () => {
  for (const status of [401, 403]) {
    stubFetch(() => ({ ok: false, status, statusText: 'DENIED', json: async () => ({}) }))
    await assert.rejects(() => call('x', {}), (e) => {
      assert.equal(e.bulkKind, 'transport', `${status} must stop a bulk run as infrastructure`)
      assert.ok(!e.message.includes('DENIED'))
      return true
    })
  }
  // permission frappe.throw riding on 403 WITH _server_messages stays an expected business refusal
  stubFetch(() => ({
    ok: false, status: 403, statusText: 'FORBIDDEN',
    json: async () => ({ _server_messages: JSON.stringify([JSON.stringify({ message: 'Not permitted' })]) })
  }))
  await assert.rejects(() => call('x', {}), (e) => e.bulkKind === 'expected' && e.message === 'Not permitted')
})

test('bulkHandoverItem: bulk-only timeout is wired (signal sent) without touching board state', async () => {
  const requests = stubFetch(() => okJson({ ok: 1 }))
  await bulkHandoverItem('send_handover', { material_request: 'MAT-MR-1' })
  assert.ok(requests[0].signal instanceof AbortSignal, 'bulk adapter runs under a finite client timeout')
  assert.equal(handoverState.pending, null)
})

// ---------------- component/pure evidence: bulk path never touches pendingRequests or rebuilds the board ----------------

const boardSrc = readFileSync(new URL('../src/HandoverBoard.vue', import.meta.url), 'utf8')

test('bulk wiring evidence: board rebuilt only via one final load; pendingRequests never used in bulk run', () => {
  assert.ok(!/applyBoard\s*\(/.test(boardSrc), 'board replacement stays module-private inside store.js')
  assert.ok(!/handoverAction\s*\(/.test(boardSrc), 'component never calls the board-replacing single action adapter')
  const match = boardSrc.match(/async function runBulk\([\s\S]*?\n\}/)
  assert.ok(match, 'runBulk orchestration exists in HandoverBoard.vue')
  const body = match[0]
  assert.ok(body.includes('runBulkItems('), 'bulk run goes through the pure orchestrator')
  assert.ok(body.includes('bulkHandoverItem'), 'rpc adapter is the boardless one')
  assert.ok(!body.includes('pendingRequests'), 'bulk never mutates the optimistic pendingRequests set')
  assert.ok(!body.includes('requestLot'), 'bulk never uses the optimistic single-card path')
  assert.ok(body.includes('loadBoard()'), 'final reload goes through loadBoard')
})

// ============================== T40 phase B fix round 1 ==============================

test('bulkRetryAvailable: retry only after the mandatory reload completed with candidates left', () => {
  assert.equal(bulkRetryAvailable({ boardReloaded: true }, 2), true)
  assert.equal(bulkRetryAvailable({ boardReloaded: false }, 2), false, '§3.4: no retry while reload failed')
  assert.equal(bulkRetryAvailable({ boardReloaded: true }, 0), false, 'nothing retained -> nothing to retry')
  assert.equal(bulkRetryAvailable(null, 1), false)
})

test('bulkEligibleRefs: refs mirror rendered-card eligibility exactly', () => {
  const dual = { is_gudang: true, is_produksi: true }
  const refs = bulkEligibleRefs([
    selCard('lot', 'MFG-WO-1'),
    selCard('lot', 'MFG-WO-2', { live: false }), // filtered out / unsupported / stopped / pending
    selCard('lot', 'MFG-WO-3', { pending: true }),
    selCard('request', 'MAT-MR-1'),
    selCard('done', 'MAT-MR-9')
  ], dual)
  assert.deepEqual([...refs].sort(), ['MAT-MR-1', 'MFG-WO-1'], 'only currently rendered eligible cards')
  assert.deepEqual([...bulkEligibleRefs(null, dual)], [])
})

test('fix round 1 wiring: retry gated on reload, pre-run validation replaced the reopen path', () => {
  const retryBody = boardSrc.match(/function retryBulkFailed\([\s\S]*?\n\}/)?.[0] || ''
  assert.ok(retryBody.includes('bulkRetryReady'), 'retry handler enforces the reload gate')
  assert.ok(boardSrc.includes('v-if="bulkRetryReady"'), 'retry button hidden while boardReloaded is false')

  const runBody = boardSrc.match(/async function runBulk\([\s\S]*?\n\}/)?.[0] || ''
  assert.ok(runBody.includes('validateBulkEntries('), 'client envelope validated before the dialog closes')
  assert.ok(!runBody.includes('dlgBulk.value.showModal()'), 'stale-close-event reopen path removed')
  assert.ok(runBody.includes('dlgBulkResult.value.showModal()'), 'result dialog still opens after the run')
  assert.ok(runBody.includes('bulkEligibleRefsInLane'), 'visible eligibility pruned before running')

  const enterBody = boardSrc.match(/function enterBulk\([\s\S]*?\n\}/)?.[0] || ''
  const exitBody = boardSrc.match(/function exitBulk\([\s\S]*?\n\}/)?.[0] || ''
  assert.ok(enterBody.includes('lastAction: null') && exitBody.includes('lastAction: null'), 'lastAction reset on fresh enter/exit')
})

// ============================== T40 phase B fix round 2 ==============================

test('bulkRequiresReload: stale-truth gate derives from the latest run result', () => {
  assert.equal(bulkRequiresReload({ boardReloaded: false }), true)
  assert.equal(bulkRequiresReload({ boardReloaded: true }), false)
  assert.equal(bulkRequiresReload(null), false)
})

test('fix round 2 wiring: stale-truth gate locks every bulk entry path until reload succeeds or exit', () => {
  const runBody = boardSrc.match(/async function runBulk\([\s\S]*?\n\}/)?.[0] || ''
  const openBody = boardSrc.match(/function openBulkConfirm\([\s\S]*?\n\}/)?.[0] || ''
  const toggleBody = boardSrc.match(/function toggleBulkCard\([\s\S]*?\n\}/)?.[0] || ''
  const selectAllBody = boardSrc.match(/function selectAllPage\([\s\S]*?\n\}/)?.[0] || ''
  assert.ok(runBody.includes('bulk.requiresReload'), 'runBulk enforces the stale gate')
  assert.ok(openBody.includes('bulk.requiresReload'), 'openBulkConfirm enforces the stale gate')
  assert.ok(toggleBody.includes('bulk.requiresReload'), 'toggling blocked while stale')
  assert.ok(selectAllBody.includes('bulk.requiresReload'), 'select-all blocked while stale')
  assert.ok(boardSrc.includes('v-if="bulk.requiresReload"'), 'bar hides normal actions while stale')
  assert.ok(boardSrc.includes('@click="reloadAfterBulk"'), 'Muat ulang reachable from the bar')
  // empty-runnable notice must be reachable: checked before validateBulkEntries
  const emptyIdx = runBody.indexOf('Tidak ada kartu')
  const validateIdx = runBody.indexOf('validateBulkEntries(')
  assert.ok(emptyIdx !== -1 && validateIdx !== -1 && emptyIdx < validateIdx, 'empty-runnable check precedes validation')
})

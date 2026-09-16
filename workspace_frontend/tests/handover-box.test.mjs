import assert from 'node:assert/strict'
import test from 'node:test'

import { boxAllocationText, expectedPacks, packProblem, validateBoxAllocation } from '../src/handover-box.js'

// UX check only — server validation (create_request T35) stays authoritative.
test('expectedPacks counts whole Packs only for valid Pack-display items', () => {
  assert.equal(expectedPacks({ displayUom: 'Pack', qtyInPack: 6, producedQty: 234 }), 39)
  assert.equal(expectedPacks({ displayUom: null, qtyInPack: null, producedQty: 234 }), null)
  assert.equal(expectedPacks({ displayUom: 'Pack', qtyInPack: 6, producedQty: 235 }), null)
  // no factor=1 fallback: zero/non-finite factor or non-Pack display is invalid
  assert.equal(expectedPacks({ displayUom: 'Pack', qtyInPack: 0, producedQty: 12 }), null)
  assert.equal(expectedPacks({ displayUom: 'Pack', qtyInPack: NaN, producedQty: 12 }), null)
  assert.equal(expectedPacks({ displayUom: 'Pcs', qtyInPack: 6, producedQty: 12 }), null)
  assert.equal(expectedPacks({ displayUom: 'Pack', qtyInPack: 6, producedQty: 0 }), 0)
})

test('validateBoxAllocation accepts the exact allocation and a valid two-box split', () => {
  assert.deepEqual(validateBoxAllocation(
    { box1: '12.5', box1Pack: '39', box2: '0', box2Pack: '0' }, 39
  ), {})
  assert.deepEqual(validateBoxAllocation(
    { box1: '12.5', box1Pack: '20', box2: '8', box2Pack: '19' }, 39
  ), {})
})

test('validateBoxAllocation rejects half-filled Box 2 and below/above Pack totals', () => {
  assert.ok(validateBoxAllocation(
    { box1: '12.5', box1Pack: '38', box2: '8', box2Pack: '0' }, 39
  ).box2)
  assert.ok(validateBoxAllocation(
    { box1: '12.5', box1Pack: '20', box2: '8', box2Pack: '18' }, 39
  ).total)
  assert.ok(validateBoxAllocation(
    { box1: '12.5', box1Pack: '20', box2: '8', box2Pack: '20' }, 39
  ).total)
  assert.ok(validateBoxAllocation(
    { box1: '0', box1Pack: '39', box2: '0', box2Pack: '0' }, 39
  ).box1)
  assert.ok(validateBoxAllocation(
    { box1: '12.5', box1Pack: '38.5', box2: '0', box2Pack: '0' }, 39
  ).box1Pack)
})

test('boxAllocationText renders kg + Pack per box, kg-only pre-cutover, empty without boxes', () => {
  assert.equal(
    boxAllocationText({ box1: 12.5, box1Pack: 20, box2: 8, box2Pack: 19 }),
    'Box 1: 12.5 kg · 20 Pack\nBox 2: 8 kg · 19 Pack'
  )
  assert.equal(
    boxAllocationText({ box1: 12.5, box1Pack: null, box2: null, box2Pack: null }),
    'Box 1: 12.5 kg'
  )
  assert.equal(boxAllocationText({ box1: null, box1Pack: null, box2: null, box2Pack: null }), '')
})

test('expectedPacks uses the server integral tolerance (passed/default precision)', () => {
  // 234.0024 / 6 = 39.0004 < 0.0005 (server default precision 3) -> 39 Pack
  const lot = { displayUom: 'Pack', qtyInPack: 6, producedQty: 234.0024 }
  assert.equal(expectedPacks(lot), 39)
  assert.equal(packProblem(lot), null)
  // 39.0006 >= tolerance -> fractional, and reported as such (not "conversion")
  const over = { displayUom: 'Pack', qtyInPack: 6, producedQty: 234.0036 }
  assert.equal(expectedPacks(over), null)
  assert.equal(packProblem(over), 'fractional')
  // a passed precision narrows the tolerance like wo.precision() on the server
  assert.equal(expectedPacks(lot, 6), null)
  // missing/invalid conversion stays its own problem class
  assert.equal(packProblem({ displayUom: 'Pcs', qtyInPack: 6, producedQty: 234 }), 'conversion')
  assert.equal(packProblem({ displayUom: 'Pack', qtyInPack: 0, producedQty: 234 }), 'conversion')
  assert.equal(packProblem(null), 'conversion')
})

test('validateBoxAllocation flags negative Box 2 kg client-side', () => {
  // previously a negative kg with 0 Pack slipped through as "empty Box 2";
  // the server rejects it, so the dialog must flag it before submit
  const errors = validateBoxAllocation(
    { box1: '12.5', box1Pack: '39', box2: '-3', box2Pack: '0' }, 39
  )
  assert.match(errors.box2, /non-negatif/)
  // Box 1 negative is still flagged as missing/positive
  assert.ok(validateBoxAllocation(
    { box1: '-1', box1Pack: '39', box2: '0', box2Pack: '0' }, 39
  ).box1)
})

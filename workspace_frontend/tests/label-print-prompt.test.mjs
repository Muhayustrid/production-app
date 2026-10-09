import assert from 'node:assert/strict'
import test from 'node:test'

import { labelCountForWorkOrder } from '../src/label-print-prompt.js'

const base = { displayUom: 'Pcs', stockUom: 'Pcs', qtyInPack: 1 }

test('label count follows Pre-Packing good qty by default', () => {
  assert.equal(labelCountForWorkOrder({ ...base, prepacking: { goodQty: 40 }, postpacking: { goodQty: 38 } }), 40)
})

test('FU114: item Tanpa Pre-Packing counts labels from Post-Packing', () => {
  assert.equal(labelCountForWorkOrder({ ...base, skipPrepacking: true, prepacking: { goodQty: null }, postpacking: { goodQty: 38 } }), 38)
})

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

test('Cold Storage retains unrequested remainder when the shared pool is empty', () => {
  const source = readFileSync(new URL('../src/HandoverBoard.vue', import.meta.url), 'utf8')
  const declaration = source.match(/^const coldLots = computed\(.*$/m)?.[0]
  assert.ok(declaration)
  const context = {
    computed: (fn) => ({ get value() { return fn() } }),
    filteredLots: { value: [
      { workOrder: 'PARTIAL', availableQty: 0, unrequestedRemainder: 4 },
      { workOrder: 'DONE', availableQty: 0, unrequestedRemainder: 0 },
    ] },
    lotAvailablePcs: (lot) => lot.availableQty,
  }
  vm.createContext(context)
  vm.runInContext(`${declaration}; globalThis.result = coldLots.value`, context)
  assert.deepEqual(Array.from(context.result, (lot) => lot.workOrder), ['PARTIAL'])
})

import assert from 'node:assert/strict'
import test from 'node:test'

import { fmtId } from '../src/format.js'

test('fmtId formats angka gaya Indonesia', () => {
  assert.equal(fmtId(401.67), '401,67')
  assert.equal(fmtId(120), '120')
  assert.equal(fmtId(0.5), '0,5')
  assert.equal(fmtId(1234.5), '1.234,5')
})

test('fmtId membulatkan 2 desimal, buang nol belakang, nilai tak valid jadi strip', () => {
  assert.equal(fmtId(1.005), '1,01')
  assert.equal(fmtId(2.5), '2,5')
  assert.equal(fmtId(null), '-')
  assert.equal(fmtId(NaN), '-')
})

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  defaultUom, foItemsText, foQtyTotal, foStatusMeta, formCanSubmit, itemRowProblem, ITEM_PROBLEM_TEXT,
  laneStatusMeta, uomOptions, uomProblem, validateFormRows
} from '../src/form-order.js'

test('foStatusMeta: label + warna chip per status server', () => {
  assert.deepEqual(foStatusMeta('menunggu'), { label: 'Menunggu', cls: 'chip-warn' })
  assert.deepEqual(foStatusMeta('terkirim'), { label: 'Terkirim', cls: 'chip-ok' })
  assert.deepEqual(foStatusMeta('batal'), { label: 'Dibatalkan', cls: 'chip-bad' })
  assert.deepEqual(foStatusMeta('draf'), { label: 'Draf', cls: 'chip-off' })
  // status tak dikenal jatuh ke Menunggu (bukan crash)
  assert.deepEqual(foStatusMeta(undefined), { label: 'Menunggu', cls: 'chip-warn' })
})

test('laneStatusMeta: turunan lane/flag papan serah terima', () => {
  assert.deepEqual(laneStatusMeta({ lane: 'terkirim' }), { label: 'Terkirim', cls: 'chip-ok' })
  assert.deepEqual(laneStatusMeta({ lane: 'request' }), { label: 'Diminta', cls: 'chip-warn' })
  assert.deepEqual(laneStatusMeta({ lane: 'request', flag: 'stopped' }), { label: 'Dihentikan', cls: 'chip-off' })
  assert.deepEqual(laneStatusMeta({ lane: null, flag: 'cancelled' }), { label: 'Dibatalkan', cls: 'chip-bad' })
  assert.deepEqual(laneStatusMeta({ lane: null, flag: 'draft' }), { label: 'Draf', cls: 'chip-off' })
  assert.deepEqual(laneStatusMeta({}), { label: '-', cls: 'chip-off' })
})

test('validateFormRows: item wajib, qty angka positif', () => {
  assert.deepEqual(validateFormRows([{ code: 'ITM-1', qty: '5' }]), {})
  assert.equal(validateFormRows([{ code: '', qty: '5' }])[0], 'Pilih item')
  assert.equal(validateFormRows([{ code: 'ITM-1', qty: '' }])[0], 'Qty harus angka positif')
  assert.equal(validateFormRows([{ code: 'ITM-1', qty: '0' }])[0], 'Qty harus angka positif')
  assert.equal(validateFormRows([{ code: 'ITM-1', qty: '-2' }])[0], 'Qty harus angka positif')
  assert.equal(validateFormRows([{ code: 'ITM-1', qty: 'abc' }])[0], 'Qty harus angka positif')
  // indeks baris: error baris kedua tidak menyentuh baris pertama
  const errs = validateFormRows([{ code: 'ITM-1', qty: '1' }, { code: 'ITM-2', qty: 'x' }])
  assert.deepEqual(Object.keys(errs), ['1'])
})

test('formCanSubmit: butuh minimal satu baris valid', () => {
  assert.equal(formCanSubmit([], {}), false)
  assert.equal(formCanSubmit([{ code: 'A', qty: '1' }], {}), true)
  assert.equal(formCanSubmit([{ code: 'A', qty: '1' }], { 0: 'Qty harus angka positif' }), false)
})

test('foItemsText: item pertama + sisa, kosong = dash', () => {
  assert.equal(foItemsText(null), '-')
  assert.equal(foItemsText({ items: [] }), '-')
  assert.equal(foItemsText({ items: [{ name: 'Tepung', qty: 10, uom: 'Kg' }] }), 'Tepung 10 Kg')
  assert.equal(
    foItemsText({ items: [{ name: 'Tepung', qty: 10, uom: 'Kg' }, { name: 'Gula', qty: 2, uom: 'Kg' }, { name: 'Garam', qty: 1, uom: 'Kg' }] }),
    'Tepung 10 Kg +2 item lagi'
  )
})

test('foQtyTotal: jumlah semua baris', () => {
  assert.equal(foQtyTotal(null), 0)
  assert.equal(foQtyTotal({ items: [{ qty: 10 }, { qty: 2.5 }] }), 12.5)
})

test('itemRowProblem: penanda dini dari item_info (FO-8)', () => {
  assert.equal(itemRowProblem(null), '') // belum termuat / tanpa izin
  assert.equal(itemRowProblem({ is_stock_item: 1, has_batch_no: 0 }), '') // item normal
  assert.equal(itemRowProblem({ is_stock_item: 0, has_batch_no: 0 }), 'bukan-stok')
  assert.equal(itemRowProblem({ is_stock_item: 1, has_batch_no: 1 }), 'batch')
  // teks peringatan tersedia utk tiap masalah (tidak ada key hilang)
  for (const key of ['bukan-stok', 'batch', 'uom-invalid']) {
    assert.ok(ITEM_PROBLEM_TEXT[key].length > 10)
  }
})

// ---- FU48c: dropdown Satuan + default satuan terakhir dipakai ----

const INFO = {
  stock_uom: 'Kg',
  last_uom: null,
  uoms: [
    { uom: 'Pack', conversion_factor: 10 },
    { uom: 'Gram', conversion_factor: 1000 },
    { uom: 'Kg', conversion_factor: 1 } // server auto-append stock row → dedup wajib
  ]
}

test('uomOptions: stock_uom + konversi, tanpa duplikat', () => {
  assert.deepEqual(uomOptions(INFO), ['Kg', 'Pack', 'Gram'])
  assert.deepEqual(uomOptions({ stock_uom: 'Kg' }), ['Kg']) // tanpa baris konversi
  assert.deepEqual(uomOptions(null), []) // info belum termuat
})

test('defaultUom: last_uom valid menang; basi → stock_uom', () => {
  assert.equal(defaultUom({ ...INFO, last_uom: 'Pack' }), 'Pack') // last dipakai
  assert.equal(defaultUom({ ...INFO, last_uom: 'Sak' }), 'Kg') // basi → stock_uom
  assert.equal(defaultUom(INFO), 'Kg') // tanpa last_uom
  assert.equal(defaultUom(null), '') // info belum termuat → kosong
  // ganti item: default dihitung ulang dari info item BARU
  const itemBaru = { stock_uom: 'Pcs', last_uom: 'Pack', uoms: [{ uom: 'Dus', conversion_factor: 5 }] }
  assert.equal(defaultUom(itemBaru), 'Pcs') // Pack bukan anggota item baru
})

test('uomProblem: satuan tak valid → error baris, submit terkunci', () => {
  assert.equal(uomProblem({ info: INFO, uom: 'Pack' }), '')
  assert.equal(uomProblem({ info: INFO, uom: 'Sak' }), 'uom-invalid')
  assert.equal(uomProblem({ info: INFO, uom: '' }), '') // belum pilih (tak mungkin: select terisi)
  assert.equal(uomProblem({ info: null, uom: '' }), '') // item belum termuat
  assert.equal(uomProblem(null), '') // baris null-safe
})

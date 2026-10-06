// FU95: filter company GLOBAL — opsi select seragam (company-filter.js) dan
// gerbang preferensi per-user di store (loadCompanyFilter/whenCompanyReady/
// saveCompanyFilter). Mock global fetch (pola dashboard.test.mjs).
import test from 'node:test'
import assert from 'node:assert/strict'
import { companySelectOptions, showCompanyPicker } from '../src/company-filter.js'

test('companySelectOptions: "Semua company" selalu pertama; sentinel halaman dihormati', () => {
  const opsi = companySelectOptions(['PT. A', 'PT. B'])
  assert.deepEqual(opsi, [
    { label: 'Semua company', value: '' },
    { label: 'PT. A', value: 'PT. A' },
    { label: 'PT. B', value: 'PT. B' }
  ])
  // PrimeVue Select: '' = "tidak ada pilihan" (gotcha FU73) → sentinel ALL
  assert.deepEqual(companySelectOptions(['PT. A'], 'ALL'), [
    { label: 'Semua company', value: 'ALL' },
    { label: 'PT. A', value: 'PT. A' }
  ])
  // tanpa daftar (endpoint gagal) tetap menghasilkan opsi "Semua company"
  assert.deepEqual(companySelectOptions(null), [{ label: 'Semua company', value: '' }])
})

test('showCompanyPicker: hanya bila >1 company terlihat user', () => {
  assert.equal(showCompanyPicker(['PT. A']), false)
  assert.equal(showCompanyPicker([]), false)
  assert.equal(showCompanyPicker(null), false)
  assert.equal(showCompanyPicker(['PT. A', 'PT. B']), true)
})

function mockFetch(calls, payload) {
  const asli = globalThis.fetch
  globalThis.window = { csrf_token: 'tes' }
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, body: JSON.parse(opts.body) })
    return { ok: true, json: async () => ({ message: payload }) }
  }
  return () => {
    globalThis.fetch = asli
    delete globalThis.window
  }
}

test('loadCompanyFilter mengisi state global dari endpoint preferensi', async () => {
  const { companyFilterState, loadCompanyFilter, whenCompanyReady } = await import('../src/store.js')
  // gerbang: SEBELUM preferensi termuat, whenCompanyReady belum selesai —
  // loader halaman menunggu di sini supaya scope tersimpan tak terlewat
  companyFilterState.loaded = false
  let siap = false
  const tunggu = whenCompanyReady().then(() => { siap = true })
  await new Promise((r) => setTimeout(r, 20))
  assert.equal(siap, false)
  const calls = []
  const pulih = mockFetch(calls, { company: 'PT. Contoh', companies: ['PT. Contoh', 'PT. Lain'] })
  try {
    await loadCompanyFilter()
    assert.equal(calls[0].url, '/api/method/production_app.api.dashboard.company_preference')
    assert.deepEqual(calls[0].body, {})
    assert.equal(companyFilterState.company, 'PT. Contoh')
    assert.deepEqual(companyFilterState.companies, ['PT. Contoh', 'PT. Lain'])
    assert.equal(companyFilterState.loaded, true)
  } finally {
    pulih()
  }
  await tunggu
  assert.equal(siap, true) // gerbang terbuka setelah preferensi termuat
})

test('whenCompanyReady: menunggu sampai loaded, instan sesudahnya', async () => {
  const { companyFilterState, whenCompanyReady } = await import('../src/store.js')
  // sudah loaded → resolusi instan (tanpa fetch)
  companyFilterState.loaded = true
  const t0 = Date.now()
  await whenCompanyReady()
  assert.ok(Date.now() - t0 < 100, 'loaded=true harus instan')
})

test('saveCompanyFilter: POST nilai + sinkron balik state dari respons server', async () => {
  const { companyFilterState, saveCompanyFilter } = await import('../src/store.js')
  const calls = []
  const pulih = mockFetch(calls, { company: 'PT. Baru', companies: ['PT. Baru'] })
  try {
    companyFilterState.company = 'PT. Baru'
    await saveCompanyFilter('PT. Baru')
    assert.equal(calls[0].url, '/api/method/production_app.api.dashboard.company_preference_save')
    assert.deepEqual(calls[0].body, { company: 'PT. Baru' })
    assert.equal(companyFilterState.company, 'PT. Baru')
    assert.deepEqual(companyFilterState.companies, ['PT. Baru'])
    // lepas filter → '' terkirim apa adanya
    await saveCompanyFilter('')
    assert.deepEqual(calls[1].body, { company: '' })
  } finally {
    pulih()
  }
})

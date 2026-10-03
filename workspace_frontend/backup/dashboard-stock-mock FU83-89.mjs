// BACKUP — dipensiunkan FU90 (2026-10-03). Jangan di-import: TIDAK bagian dari
// grafik build (di luar src/, tidak direferensikan siapa pun). Disimpan murni
// sebagai arsip kode asli sesuai aturan AGENTS.md (retire hanya setelah
// pengganti terbukti + definisi asli dibackup).
//
// APA: definisi mock halaman Ketersediaan Stock — `stockStatus(available,
// minimum)` (status dari angka: habis ≤0 / menipis <min / aman) dan
// `stockMockDataset()` (128 item: 8 kurasi spesifikasi user + 120 filler
// deterministik, movement rantai saldo valid) beserta konstanta/helper
// privatnya (MOCK_*, mockItem, mockMovements).
//
// ASAL: FU83 (2026-10-03, TASKS §Z10 — halaman mock tanpa API), diperbarui
// FU88 (DIU display_uom/qty_in_pack pada filler). Dipakai halaman sampai FU89.
//
// DIPENSIUNKAN: FU90 (2026-10-03) — data live terbukti via E2E: halaman kini
// memakai endpoint server `production_app.api.stock_availability.stock_availability`
// (status diturunkan server; movement via stock_movements lazy). Pemakaian
// terakhir sudah dihapus dari src/dashboard.js dan tests/dashboard.test.mjs
// (3 test mock dibuang, 103 → 100). Test stockXlsxFilename tetap hidup.
//
// Dipulihkan dari src/dashboard.js baris 707–908 sebelum penghapusan, verbatim.

// ---- FU83: ketersediaan stock (#/ketersediaan-stock) -----------------------
// Status stock diturunkan dari ANGKA (bukan label data): available ≤ 0 = habis,
// di bawah stok minimum = menipis, sisanya aman. Tanpa minimum (null) item
// dianggap aman selama masih ada stok — sama seperti ambang reorder kosong.
export function stockStatus(available, minimum) {
  const avail = Number(available)
  if (!Number.isFinite(avail) || avail <= 0) return 'habis'
  const min = Number(minimum)
  if (Number.isFinite(min) && avail < min) return 'menipis'
  return 'aman'
}

// Dataset MOCK halaman Ketersediaan Stock (FU83 — TANPA integrasi API).
// Struktur item mengikuti respons ERPNext yang akan datang: Bin (actual_qty,
// reserved_qty) + Item (item_group, stock_uom) + Stock Ledger Entry (movement).
// Titik tukar: store.loadStockAvailability mengganti pemanggilan ini dengan
// call('production_app.api.stock_availability') tanpa mengubah halaman.
const MOCK_HARI_INI = '2026-10-03'
const MOCK_RESEP = ['Dough Coklat', 'Dough Keju', 'Roti Tawar', 'Bun Sausis', 'Donat Gula']

// 8 item kurasi: nama + angka persis spesifikasi user. Status TIDAK di-copy
// dari spesifikasi melainkan diturunkan (Mentega 34<40 → menipis, bukan aman).
const MOCK_KURASI = [
  { item_code: 'RM-FLOUR-001', item_name: 'Tepung Terigu', actual_qty: 125, reserved_qty: 20, min_stock: 100, stock_uom: 'kg', resep: [['Dough Coklat', 4], ['Dough Keju', 3]] },
  { item_code: 'RM-SUGAR-002', item_name: 'Gula Pasir', actual_qty: 74, reserved_qty: 36, min_stock: 50, stock_uom: 'kg', resep: [['Dough Coklat', 2], ['Dough Keju', 2]] },
  { item_code: 'RM-BUTTER-003', item_name: 'Mentega Tawar', actual_qty: 46, reserved_qty: 12, min_stock: 40, stock_uom: 'kg', resep: [['Dough Butter', 5]] },
  { item_code: 'RM-COCOA-004', item_name: 'Bubuk Kakao', actual_qty: 18, reserved_qty: 18, min_stock: 25, stock_uom: 'kg', resep: [['Dough Coklat', 0], ['Dough Keju', 0]] },
  { item_code: 'RM-CHEESE-005', item_name: 'Keju Cheddar', actual_qty: 32, reserved_qty: 10, min_stock: 25, stock_uom: 'kg', resep: [['Dough Keju', 3]] },
  { item_code: 'RM-YEAST-006', item_name: 'Ragi Instan', actual_qty: 22, reserved_qty: 4, min_stock: 15, stock_uom: 'kg', resep: [['Dough Coklat', 8], ['Roti Tawar', 6]] },
  { item_code: 'RM-SALT-007', item_name: 'Garam Dapur', actual_qty: 60, reserved_qty: 5, min_stock: 30, stock_uom: 'kg', resep: [['Roti Tawar', 12], ['Bun Sausis', 9]] },
  { item_code: 'RM-IMPROVER-008', item_name: 'Bread Improver', actual_qty: 12, reserved_qty: 0, min_stock: 15, stock_uom: 'kg', resep: [['Roti Tawar', 1]] }
]

// 120 filler deterministik agar kartu ringkasan = 96 aman / 21 menipis / 11
// habis persis spesifikasi (kurasi menyumbang 3/4/1). Tanpa Math.random —
// angka stabil antar-build untuk test & screenshot.
const MOCK_NAMA_BAHAN = [
  'Tepung Protein Tinggi', 'Tepung Protein Sedang', 'Gula Halus', 'Gula Dus',
  'Margarin Kue', 'Susu Bubuk Skim', 'Susu Full Cream', 'Keju Mozarella',
  'Kakao Alkali', 'Coklat Compound', 'Coklat Couverture', 'Krim Pengocok',
  'Susu Kental Manis', 'Selai Nanas', 'Selai Stroberi', 'Selai Blueberry',
  'Minyak Goreng', 'Ragi Segar', 'Baking Powder', 'Soda Kue',
  'Perisa Vanila', 'Perisa Pandan', 'Pewarna Coklat', 'Pewarna Merah',
  'Chip Coklat', 'Krimer Non Krim', 'Tepung Maizena', 'Tepung Sagu',
  'Madu Hutan', 'Glukosa Cair'
]
const MOCK_VARIAN = ['Lokal', 'Impor', 'Premium', 'Ekonomis']
const MOCK_KEMASAN = [
  'Karton Plastik PP', 'Plastic Seal 250g', 'Label Produk', 'Kertas Greaseproof',
  'Cup Paper 250ml', 'Pouch Zipper', 'Sticker Logistik', 'Dus Master 24',
  'Bubble Wrap Roll', 'Tali Rafia'
]
const MOCK_GRUP = ['Bahan Baku', 'Aditif', 'Bahan Kemasan']

function mockItem(sisa, indeks, i) {
  const kemasan = sisa === 'habis' ? false : indeks % 7 === 6 // tiap ke-7 filler = kemasan
  const grup = kemasan ? MOCK_GRUP[2] : indeks % 5 === 4 ? MOCK_GRUP[1] : MOCK_GRUP[0]
  const nama = kemasan
    ? MOCK_KEMASAN[indeks % MOCK_KEMASAN.length]
    : `${MOCK_NAMA_BAHAN[indeks % MOCK_NAMA_BAHAN.length]} ${MOCK_VARIAN[Math.floor(indeks / MOCK_NAMA_BAHAN.length) % MOCK_VARIAN.length]}`
  const uom = kemasan ? 'pcs' : indeks % 6 === 5 ? 'liter' : 'kg'
  let minimum = 15 + ((indeks * 11) % 60)
  // available DITURUNKAN dari bucket target lalu stok/reserved dihitung balik —
  // item filler dijamin mendarat di status bucket-nya (tidak bocor antar-bucket)
  let available, reserved, actual
  if (sisa === 'habis') {
    // genap: gudang kosong; ganjil: stok ada tapi seluruhnya ter-reserve
    actual = indeks % 2 ? 5 + ((indeks * 3) % 20) : 0
    reserved = actual
    available = 0
  } else if (sisa === 'menipis') {
    minimum += 10 // ambang agak jauh supaya jelas menipis
    available = 1 + ((indeks * 7) % (minimum - 2))
    reserved = 2 + ((indeks * 5) % 30)
    actual = available + reserved
  } else {
    available = minimum + 10 + ((indeks * 29) % 220)
    reserved = (indeks * 7) % 25
    actual = available + reserved
  }
  // FU88: sebagian filler ber-DIU (Default Inventory UOM) — kurasi TIDAK (kg,
  // angka spesifikasi user dipertahankan); layar menampilkan DIU dgn sub stock
  let display_uom = null
  let qty_in_pack = null
  if (!kemasan && indeks % 4 === 1) {
    display_uom = 'Pack'
    qty_in_pack = 12
  } else if (!kemasan && uom === 'kg' && indeks % 4 === 3) {
    display_uom = 'Sak'
    qty_in_pack = 25
  }
  const batchMax = sisa === 'habis' ? 0 : sisa === 'menipis' ? 1 + (indeks % 3) : 2 + ((indeks * 5) % 12)
  const nResep = indeks % 2 ? 1 : 2
  const resep = Array.from({ length: nResep }, (_, r) => {
    const p = MOCK_RESEP[(indeks + r * 2) % MOCK_RESEP.length]
    return { product: p, batches: Math.max(0, batchMax - r * (sisa === 'aman' ? 2 : 1)) }
  })
  return {
    item_code: `RM-GEN-${String(i + 1).padStart(3, '0')}`,
    item_name: nama,
    item_group: grup,
    actual_qty: actual,
    reserved_qty: reserved,
    available,
    stock_uom: uom,
    min_stock: minimum,
    display_uom,
    qty_in_pack,
    capacity_detail: resep
  }
}

// movement mock: rantai saldo DIJAMIN valid secara konstruktor — masuk dulu
// keluar kemudian, tiap saldo antara ≥ 0, baris terakhir berakhir persis di
// stok kini (actual_qty). Tanggal menurun sampai hari ini (2026-10-03).
function mockMovements(it, i) {
  const stok = it.actual_qty
  const keluar1 = 5 + ((i * 3) % 20)
  const masukTengah = i % 2 ? 0 : 6 + ((i % 4) * 4) // baris ke-4 hanya i genap
  const keluar2 = 4 + ((i * 5) % 12)
  const masukAwal = stok + keluar1 + keluar2 - masukTengah // ≥ stok ≥ 0
  const jenisKeluar = i % 3 ? 'Manufacture' : 'Material Transfer'
  const rows = [
    {
      tanggal: 3, jenis: i % 3 === 0 ? 'Purchase Receipt' : 'Material Transfer',
      referensi: i % 3 === 0 ? `MAT-PR-2026-${String(1000 + (i % 800))}` : `MAT-STE-2026-${String(10000 + (i % 900))}`,
      masuk: masukAwal, keluar: 0, saldo: masukAwal
    }
  ]
  if (masukTengah) {
    rows.push({
      tanggal: 2, jenis: 'Material Transfer',
      referensi: `MAT-STE-2026-${String(10000 + ((i + 40) % 900))}`,
      masuk: masukTengah, keluar: 0, saldo: masukAwal + masukTengah
    })
  }
  rows.push(
    {
      tanggal: masukTengah ? 1 : 2, jenis: jenisKeluar,
      referensi: jenisKeluar === 'Manufacture'
        ? `MAT-STE-2026-${String(10000 + ((i + 80) % 900))}`
        : `MAT-STE-2026-${String(10000 + ((i + 40) % 900))}`,
      masuk: 0, keluar: keluar1, saldo: masukAwal + masukTengah - keluar1
    },
    {
      tanggal: 0, jenis: jenisKeluar,
      referensi: jenisKeluar === 'Manufacture'
        ? `MAT-STE-2026-${String(10000 + ((i + 120) % 900))}`
        : `MAT-STE-2026-${String(10000 + ((i + 160) % 900))}`,
      masuk: 0, keluar: keluar2, saldo: stok
    }
  )
  const base = new Date(`${MOCK_HARI_INI}T00:00:00`).getTime()
  return rows.map((r) => ({
    ...r,
    tanggal: new Date(base - r.tanggal * 86400000).toISOString().slice(0, 10)
  }))
}

export function stockMockDataset() {
  const target = { aman: 96, menipis: 21, habis: 11 }
  const kurasiStatus = MOCK_KURASI.map(
    (k) => [k, k.actual_qty - k.reserved_qty, stockStatus(k.actual_qty - k.reserved_qty, k.min_stock)]
  )
  const sisa = {
    aman: target.aman - kurasiStatus.filter(([, , s]) => s === 'aman').length,
    menipis: target.menipis - kurasiStatus.filter(([, , s]) => s === 'menipis').length,
    habis: target.habis - kurasiStatus.filter(([, , s]) => s === 'habis').length
  }
  // urutan filler: selang-seling status agar tabel default menampilkan campuran
  const urutan = []
  const antre = { aman: [], menipis: [], habis: [] }
  let i = 0
  for (const status of ['aman', 'menipis', 'habis']) {
    for (let n = 0; n < sisa[status]; n++, i++) antre[status].push(mockItem(status, i, i))
  }
  const maks = Math.max(sisa.aman, sisa.menipis, sisa.habis)
  for (let n = 0; n < maks; n++) {
    for (const status of ['aman', 'menipis', 'habis']) {
      if (antre[status][n]) urutan.push(antre[status][n])
    }
  }
  const items = [...kurasiStatus.map(([k, avail]) => ({
    ...k,
    available: avail,
    item_group: 'Bahan Baku',
    capacity_detail: k.resep.map(([product, batches]) => ({ product, batches }))
  })), ...urutan]
  for (const it of items) {
    it.warehouse = 'Gudang Produksi'
    it.status = stockStatus(it.available, it.min_stock)
    it.capacity_batch = it.capacity_detail.reduce((m, r) => Math.max(m, r.batches), 0)
    it.movements = mockMovements(it, Number(it.item_code.replace(/\D/g, '')) || 0)
  }
  return {
    warehouse: 'Gudang Produksi',
    warehouses: ['Gudang Produksi'],
    generated_at: `${MOCK_HARI_INI}T08:00:00`,
    items,
    summary: { total: items.length, ...target }
  }
}

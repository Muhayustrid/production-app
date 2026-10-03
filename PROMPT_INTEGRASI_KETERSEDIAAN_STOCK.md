# PROMPT — Integrasi ERPNext: halaman "Ketersediaan Stock" (ganti mock → data nyata)

> Tempel seluruh isi file ini sebagai prompt pertama di sesi baru (di workspace
> `production_app`). Sesinya akan membaca TASKS.md/PROJECT_STATE.md/AGENTS.md
> secara otomatis — prompt ini menunjuk bagian yang relevan.

---

## Konteks

Halaman **Ketersediaan Stock** (`#/ketersediaan-stock`) sudah jadi (FU83–FU89)
dengan data **MOCK** di frontend. Tugas sesi ini: **ganti mock dengan data
ERPNext nyata** melalui endpoint server baru, TANPA mengubah UI/UX yang sudah
disetujui user. Baca TASKS.md §Z10–§Z16 (riwayat keputusan) dan
PROJECT_STATE.md entri FU83–FU89 sebelum menulis kode.

State halaman saat ini (semua kontrak WAJIB dipertahankan):

- Komponen: `workspace_frontend/src/StockAvailabilityPage.vue`; state:
  `stockAvailabilityState` + `loadStockAvailability()` di `store.js`; mock:
  `stockMockDataset()` + `stockStatus()` di `dashboard.js`.
- Struktur data yang dikonsumsi halaman (bentuk respons target):
  ```json
  {
    "warehouse": "Gudang Produksi",
    "warehouses": ["Gudang Produksi"],
    "generated_at": "ISO datetime",
    "summary": { "total": 0, "aman": 0, "menipis": 0, "habis": 0 },
    "items": [{
      "item_code": "RM-X", "item_name": "X", "item_group": "Bahan Baku",
      "actual_qty": 125, "reserved_qty": 20, "available": 105,
      "stock_uom": "kg",
      "display_uom": null | "Pack",
      "qty_in_pack": null | 12,
      "min_stock": 100 | null,
      "status": "aman|menipis|habis",
      "capacity_batch": 4,
      "capacity_detail": [{ "product": "Dough Coklat", "batches": 4 }],
      "movements": [{ "tanggal": "YYYY-MM-DD", "jenis": "Material Transfer",
                      "referensi": "MAT-STE-2026-00123", "masuk": 20,
                      "keluar": 0, "saldo": 125 }]
    }]
  }
  ```
- Konvensi tampilan yang SUDAH disepakati user (jangan diubah):
  - **UOM tampilan = Default Inventory UOM** (custom field
    `custom_default_inventory_unit_of_measure`, konvensi FU63/FU78): angka
    utama dalam DIU + angka kecil stock UOM (helper `woQtyText`); item tanpa
    DIU → stock UOM apa adanya.
  - **Status diturunkan dari angka** (`stockStatus`): tersedia ≤ 0 = habis;
    tersedia < minimum = menipis; sisanya aman. Minimum kosong + stok > 0 =
    aman.
  - **Minimum = Item Reorder native** (child Item Reorder di Item, baris
    warehouse = gudang produksi). Fallback kosong → `min_stock: null` → UI
    tampil "-". PERHATIAN: baris reorder punya `warehouse_uom` — bila terisi
    dan berbeda dari stock UOM, konversi dulu ke stock UOM sebelum dipakai.
  - **Tersedia = actual − reserved** (server yang menghitung).
  - **Kapasitas = unitless (Batch)**, belum ada kalkulasi BOM (mock).
  - Kolom UOM TIDAK ADA di tabel layar (satuan menempel di sel qty) — FU89.
- Export: `production_app/api/stock_availability.py::export_xlsx` adalah
  **jembatan** — halaman mengirim baris terfilter (11 field per item termasuk
  konversi DIU) dan server membungkus workbook 3 sheet. Kontrak ini boleh
  tetap dipertahankan setelah integrasi (angka file = angka layar by
  construction) — keputusan boleh didiskusikan dengan user.

## Tugas

1. **Endpoint agregat server baru** `production_app/api/stock_availability.py`
   → tambah `@frappe.whitelist() stock_availability(warehouse=None)` yang
   mengembalikan bentuk di atas dari ERPNext nyata:
   - Item: `is_stock_item=1`, `disabled=0`, satu baris per item yang punya
     Bin di warehouse terpilih.
   - Bin: `actual_qty`, `reserved_qty` (reserved native ERPNext: booking dari
     Sales Order dll — jelaskan singkat ke user di UI via srcnote yang sudah
     ada).
   - DIU: `custom_default_inventory_unit_of_measure` + faktor konversi dari
     UOM Conversion Detail item (qty stock per 1 DIU — konvensi faktor sama
     dengan dashboard FU78; lihat implementasi konversi di
     `production_app/api/dashboard.py`).
   - Minimum: Item Reorder (lihat konvensi di atas).
   - Movement: Stock Ledger Entry warehouse + item, maks ~10 baris terbaru,
     urut posting desc, `saldo = qty_after_transaction`; `jenis` =
     voucher_type; `referensi` = voucher_no. KOSONGKAN bila performa jelek —
     movement boleh dijadikan endpoint terpisah lazy (putuskan dgn user).
   - `warehouses`: daftar gudang yang punya Bin (untuk selector; saat ini
     cukup ["Gudang Produksi"]).
   - Server yang menurunkan `status` + `summary` (klien tidak menurunkan
     stage/aturan sendiri — doktrin app).
2. **Tukar mock**: `store.loadStockAvailability()` → `call(
   'production_app.api.stock_availability.stock_availability', { warehouse })`.
   Hapus/retire `stockMockDataset()` HANYA setelah terbukti live dan setelah
   definisinya di-backup (aturan AGENTS.md). Titik tukar sudah ditandai
   komentar di store.js.
3. **Export**: pertahankan jembatan (butiran di atas) atau alihkan ke agregat
   server — diskusikan singkat dengan user; jangan ubah bentuk file yang
   sudah disetujui (3 sheet, 11 kolom).
4. **Filter**: search/grup/status/gudang saat ini client-side. Bila jumlah
   item wajar (< ~2.000) biarkan client-side; bila besar, pindah ke parameter
   endpoint — putuskan dengan data nyata.
5. **Kapasitas (BOM nyata)**: spesifikasi FU83 sengaja menunda. Usulan
   (diskusikan dgn user sebelum implement): per produk jadi (FG) yang punya
   BOM aktif dan BOM-nya memakai bahan dari gudang ini →
   `kapasitas = floor(min(bahan: tersedia_i / kebutuhan_i_per_batch))`,
   dihitung internal stock UOM. Bila user hanya ingin bahan→produk sederhana,
   mock `capacity_detail` cukup diganti sumbernya. JANGAN implement tanpa
   persetujuan.

## Cara kerja sesi ini (ikuti AGENTS.md + kebiasaan proyek)

- Pilih task berikutnya dari TASKS.md; catat evidence di PROJECT_STATE.md.
- TDD: helper murni diuji `node --test tests/*.mjs` (workspace_frontend);
  server diuji test python di kontainer
  (`bench --site frontend run-tests --module production_app.tests.<modul>`,
  test delta-safe karena kelas test berbagi data hari ini).
- Deploy python: **docker cp eksplisit ke container `-backend`** (JANGAN
  fallback ke -frontend — path apps ada di sana, sudah pernah meleset, FU88),
  `docker restart` backend (reload worker tanpa ini no-op), ping 200.
- Deploy aset: build vite → docker cp index.js/index.css ke KEDUA
  container `-frontend` → verifikasi md5 HTTP = host.
- Gotcha infra aktif: nginx `client_body_buffer_size` sudah dinaikkan ke 128K
  secara LIVE (POST >21KB tadinya 500) — cek masih ada bila container pernah
  di-recreate; cookie 127.0.0.1 di-share lintas port (login 8082 menimpa
  sesi 8081).
- E2E minimal: render halaman (4 KPI, tabel, drawer), filter+popover, export
  unduh (magic PK), mobile 390 overflow 0, regresi Dashboard + Work Order.
- Commit lokal 1 commit per FU, pesan detail bahasa Indonesia; push hanya
  atas permintaan user.

## Definisi selesai

- Halaman menampilkan data Bin nyata Gudang Produksi; angka = Bin (bukan
  mock); DIU/status/minimum berperilaku sesuai konvensi di atas.
- Export file = angka layar.
- Semua test hijau (node + python), E2E lolos, TASKS/PROJECT_STATE terisi
  evidence, komit lokal rapi.

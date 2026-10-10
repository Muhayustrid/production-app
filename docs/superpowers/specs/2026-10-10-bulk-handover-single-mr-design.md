# Serah terima bulk = 1 Material Request + rapikan historis Krim Kopi — design

Date: 2026-10-10
Status: Proposed (menunggu review user)
Repository: `production_app` (utama), `warehouse_app` (penyesuaian kecil),
`AutoFetchErestoToERPNext/pos_sync` (script data historis)

## 1. Outcome

1. **Bulk request = 1 MR.** "Request grup" N Work Order (item sama) membuat SATU
   Material Request Material Transfer dengan N baris — satu baris per WO
   (`qty` = produced_qty WO, `custom_work_order` = WO).
2. **Kirim = 1 SE sesuai MR.** `send_handover(mr)` membuat SATU Stock Entry
   Material Transfer dengan N baris, tiap baris ber-link `material_request` +
   `material_request_item` ke baris MR-nya. Setelah submit, SEMUA WO di MR itu
   otomatis berstatus **Terkirim**.
3. **Historis bersih.** Krim Kopi (PJ260016) 1–8 Okt di site baru diubah ke bentuk
   yang sama: per hari 1 MR bulk (34 baris/WO) + 1 SE ber-link, angka stok tetap.
4. **MR test 9 Okt** (`MREQ-MTR-26-0193..0226`) dibatalkan + dihapus, diganti 1 MR bulk.

Di luar scope: mengubah alur request tunggal per WO (tetap 1 MR = 1 WO), item lain
selain Krim Kopi untuk perapian historis.

## 2. Keputusan user (2026-10-10)

- Bentuk MR bulk: **1 baris per WO** (bukan 1 baris total).
- Historis: **cancel & buat ulang** (SE baru ber-link MR, tanggal/jam/qty/gudang sama).
- MR test 0193..0226: **cancel + hapus, ganti 1 MR bulk**.
- `allow_negative_stock`: **boleh dinyalakan sementara** selama script historis, wajib
  `0` lagi di `finally` (saat ini sudah 0 — patch POS ter-deploy, dicek
  `get_stock_availability` PEL260076 @ Stores - RPMD = 190 = Bin).

## 3. Kode — production_app `api/handover.py`

Prinsip: MR lama (1 baris, atau grup lama via `Handover Box Plan`) tetap jalan apa adanya;
semua jalur yang sekarang membaca `mr.items[0]` diganti membaca SEMUA baris ber-WO.

| Bagian | Sekarang | Jadi |
|---|---|---|
| `create_group_request` | N MR + 1 Handover Box Plan | 1 MR, N baris (`_insert_submitted_handover_mr` versi multi-baris), tanpa box plan baru; validasi tetap (≥2 WO, satu item, lock WO urut nama, guard pool kumulatif `claimed`). Return `material_request` + `material_requests: [mr]` (kompat) + `box_plan: None`. Semua WO mendapat Link ke MR yang sama. |
| `_requests` (board) | 1 baris per MR dari `items[0]` | 1 baris per **(MR, baris ber-WO)**; tambah `group_size` = jumlah baris ber-WO di MR (>1 = bulk). Reservasi per WO/per item otomatis benar karena per baris. |
| `_handover_mr` | cek `items[0]` | semua baris wajib punya `custom_work_order`. |
| `send_handover` | 1 baris, `len(se.items) != 1` → throw | lock SEMUA WO (urut nama); `_checked_lot` per WO; cek stok rute = Σ qty per (item, gudang) / per batch; `make_mr_stock_entry` → N baris, qty & batch diset per baris sesuai baris MR; 1 transaksi. |
| `_cancel_unsent_request` / `cancel_request` | 1 WO | semua WO MR di-lock lalu MR dibatalkan utuh (bulk tidak bisa batal sebagian). |
| `_pool_reserved_now`, `_active_mr_now`, `_handover_state`, `sync_from_*` | sudah per baris / per MR | tidak berubah. |

Frontend `workspace_frontend`: `store.js` id kartu = `mr + work_order` (sekarang `mr`,
akan bentrok untuk bulk); `groupText` menampilkan `Grup <MR> (N WO)` bila `group_size > 1`.
Dialog Kirim menampilkan jumlah WO + total qty.

## 4. warehouse_app

- `gudang_request._active_request_map`: tambah ukuran grup per MR (jumlah baris ber-WO)
  supaya papan tetap menandai "group of N" dan tombol batal menjadi "Cancel Group".
- `BoardPage.vue`: batal untuk MR bulk memanggil `cancel_request(mr)` (membatalkan
  semua WO-nya); grup lama ber-`box_plan` tetap `cancel_group_request`.
- `GroupRequestDialog.vue`: toast memakai nama MR (bukan box plan).

## 5. Data historis — `pos_sync/rapikan_handover_krim_kopi.py`

Dry-run default, `--execute`, idempoten (MR baru ditandai `title =
"Serah Terima Bulk PJ260016 <YYYY-MM-DD>"`; hari yang sudah punya MR bulk ber-SE = SKIP).

Peta per hari (data live 2026-10-10):

| Tanggal | SE transfer lama (CS → GBJ) | MR lama | Qty |
|---|---|---|---|
| 1 Okt | SE-MTF-261006113 | MAT-MR-2026-00821 | 871 |
| 2 Okt | SE-MTF-261006115 | MAT-MR-2026-00890 | 872 |
| 5 Okt | SE-MTF-261006119 | MAT-MR-2026-00929 | 869 |
| 6 Okt | SE-MTF-261006121 | MAT-MR-2026-00965 | 870 |
| 7 Okt | SE-MTF-261007030 | MAT-MR-2026-01014 | 870 |
| 8 Okt | SE-MTF-261008029 | MAT-MR-2026-01043 | 869 |

Langkah:
1. **Preflight** per hari: WO Krim Kopi yang SE Manufacture-nya ber-tanggal itu (34 WO);
   Σ produced_qty == qty SE lama, kalau tidak → hari itu ABORT (tidak ditebak).
   Snapshot Bin PJ260016 semua gudang + daftar Bin negatif global.
2. **Backup** JSON semua dokumen yang akan di-cancel → `audit_logs/`.
3. `allow_negative_stock = 1` (catat nilai awal).
4. Cancel SE lama (urut terbaru dulu), lalu cancel MR lama.
5. Per hari (urut tanggal): buat MR bulk 34 baris (`transaction_date` = hari itu),
   submit; buat SE dari MR (`make_stock_entry`), `set_posting_time=1`,
   `posting_date/time` = SE lama, qty per baris = baris MR, submit.
6. **finally:** `allow_negative_stock` = nilai sebelum script (0).
7. Hapus dokumen cancelled (pola `bersih_dokumen_cancelled.py`: backup, link-check,
   `delete_linked_ledger_entries` sementara).
8. Poll `Repost Item Valuation` sampai selesai.
9. **Verifikasi (LOLOS/GAGAL):** Bin PJ260016 identik dengan snapshot; 0 Bin negatif
   global; 0 SLE PJ260016 dengan `qty_after_transaction < 0` di CS/GBJ; 204 WO
   1–8 Okt `custom_handover_status = Terkirim` dan Link = MR bulk harinya;
   setiap baris SE punya `material_request`.

9 Okt: cancel + hapus `MREQ-MTR-26-0193..0226` (dan `MREQ-MTR-26-0190` yang Stopped);
setelah fitur ter-deploy, buat 1 MR bulk untuk 34 WO 9 Okt via `create_group_request`.

Urutan rilis: kode (§3–4) → test → deploy → script historis → MR bulk 9 Okt.

## 6. Risiko

- Cancel SE backdated memicu repost GBJ/CS ke depan; nilai (valuation) SE pengganti
  dihitung ulang — qty identik, nilai Rp bisa bergeser sedikit (dilaporkan, bukan diblok).
- Nama SE/MR baru (auto) berbeda dari nama lama; nama lama tercatat di laporan + backup.
- Board lama (sebelum deploy) hanya membaca baris pertama MR — karena itu script historis
  dijalankan SETELAH deploy.

## 7. Testing

- production_app `tests/test_handover_actions.py`: grup → 1 MR N baris + semua WO Link
  sama; kirim → 1 SE N baris ber-link, semua WO Terkirim; stok kurang → zero writes;
  cancel bulk → semua WO bersih; board 1 kartu per WO dengan `group_size`; grup lama
  ber-box-plan tetap bisa kirim/batal. Jalankan di bench lokal (site dengan batch aktif).
- warehouse_app `tests/w19_gate.py` disesuaikan dengan kontrak 1 MR.
- Script historis: dry-run di cloud dulu (laporan rencana), lalu `--execute`.

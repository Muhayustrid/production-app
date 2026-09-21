# FU58 — Pengaturan gudang live (propagasi, Company, dropdown ke atas) design

Date: 2026-09-20
Status: Proposed (hanya desain — sesuai AGENTS.md tidak ada implementasi sebelum user menyetujui)
Revisi: 3 — telaah independen 2026-09-20 dijawab (return flat backward-compatible §8,
gap clear→set didokumentasikan §4.4/§5 + copy dilunakkan §9, dropdown di-bounding clipping
ancestor + max-height adaptif §7, TOCTOU jalur submitted + guard skip_transfer §4.3)
Revisi: 2 — feedback advisor 2026-09-20 diterapkan (lock jalur draft §4.3, koreksi klaim
permission §4.5, asumsi mode backflush §4.6, ketajaman query kandidat §4.2, uji tambahan §10.1)
Repository: `production_app`, branch `feat/three-lane-handover`

Basis sitasi: file `production_app/...` dan `workspace_frontend/...` dibaca langsung dari repo host
(path:baris sesuai isi file saat desain ini ditulis). Sitasi `erpnext/...` dan `frappe/...` merujuk
source ter-install di container `erpnext-new-backend-1:/home/frappe/frappe-bench/apps/`
(erpnext 16.34.2, frappe 16.33.1), diverifikasi read-only oleh peneliti FU58; salinan host
`/Users/rotiropi/erpnext-new/apps/` hanya berisi `production_app` + `warehouse_app`.

## 1. Outcome

Satu unit kerja FU58, tiga bagian:

1. **LIVE** — perubahan pengaturan gudang di panel Pengaturan Gudang otomatis diterapkan ke
   Work Order yang sedang berjalan (header dan baris bahan), tanpa menyentuh WO yang nilai
   gudangnya sudah diubah manual, plus endpoint remediasi sekali-pakai untuk WO yang sudah
   terlanjur salah (kasus nyata: `MFG-WO-2026-03410` memakai Cold Storage padahal setting sudah
   Gudang Produksi).
2. **COMPANY** — field `Company` baru pada panel Pengaturan Gudang; ke-8 default gudang hanya
   berlaku bagi company terpilih (kosong = semua company, kompatibel dengan perilaku lama).
3. **DROPDOWN** — dropdown `LinkInput` membuka ke ATAS secara default (drop-up), turun ke bawah
   hanya bila ruang atas tidak cukup; berlaku umum untuk semua pemakaian `LinkInput` di SPA.

Semua perubahan di sisi `production_app` (API Python, custom field via `upgrade.py`, SPA Vue).
Tidak menyentuh source ERPNext/Frappe core, tidak menambah DocType bisnis baru.

## 2. Keputusan bisnis terkonfirmasi

- Propagasi terjadi di dalam `warehouse_defaults_save` (satu transaksi dengan simpanan
  pengaturan) dan hanya untuk 4 field gudang yang hidup di Work Order
  (`WAREHOUSE_DEFAULT_FIELDS`: source, wip, fg, scrap — `production_app/api/work_order.py:519-523`).
- WO yang tersentuh: "berjalan" = `docstatus < 2` DAN `status not in (Completed, Stopped, Closed,
  Cancelled)` — konsisten dengan semantik native `get_status` (erpnext `work_order.py:703-746`)
  dan filter stage aplikasi (`production_app/api/work_order.py:160-165`).
- Propagasi hanya menimpa kolom yang **masih sama dengan nilai lama** (indikasi berasal dari
  default, bukan ubahan manual); baris `required_items` yang `source_warehouse`-nya sama dengan
   nilai lama ikut ditulis (builder Material Transfer native membaca gudang asal **per baris**,
  tanpa fallback ke header — erpnext `stock_entry.py:3946-3950`).
- WO draft ditulis via `document.save()` (validasi native tetap jalan); WO submitted ditulis via
  `Document.db_set` (pola native untuk header dan baris child dokumen submitted — erpnext
  `work_order.py:1798,1856,1876`); tidak ada field gudang WO yang `allow_on_submit`
  (work_order.json), jadi `save()` biasa mustahil untuk WO submitted.
- Stock Entry yang sudah dibuat tidak diubah — histori tetap benar; hanya transfer berikutnya
  yang memakai nilai baru.
- Remediasi = endpoint terpisah ber-whitelist dengan gate permission yang SAMA dengan simpan
  pengaturan (`frappe.has_permission("Manufacturing Settings", "write")` — pada site ini
  satu-satunya DocPerm write adalah Manufacturing Manager), mengembalikan daftar WO yang
  diubah sebagai jejak audit (`db_set` tidak membuat record Version —
  frappe `model/document.py:1472,1588`).
- Company: custom field baru `custom_default_company` (Link Company) di Manufacturing Settings
  via `upgrade.py`, idempoten + snapshot dulu, mengikuti pola field lama
  (`production_app/upgrade.py:224-326`).
- Dropdown: tetap `position: absolute` (tidak menggeser layout), arah dipilih otomatis dari
  ruang viewport (`getBoundingClientRect`), default ke ATAS sesuai permintaan user.

## 3. Prinsip desain

1. **Satu titik simpan, satu titik propagasi.** `warehouse_defaults_save`
   (`production_app/api/work_order.py:562-589`) adalah satu-satunya jalur tulis pengaturan;
   propagasi menempel di sana sehingga tidak ada jalur yang bisa melupakan sinkronisasi.
2. **Native tetap sumber kebenaran; histori tidak ditulis ulang.** SE/MR tersubmit dan
   `transferred_qty` per baris tidak pernah disentuh; hanya kolom rencana (header WO +
   `source_warehouse` baris) yang berubah.
3. **Konservatif pada data user.** Hanya nilai yang masih identik dengan default lama yang
   boleh ditimpa; nilai manual, baris dari BOM/item default, dan dokumen selesai tidak tersentuh.
4. **Validasi milik aplikasi saat ORM dilewati.** `db_set` melewati
   `validate_warehouse_belongs_to_company` (erpnext `work_order.py:611-619` →
   `stock/utils.py:415-421`) — cek warehouse↔company dilakukan eksplisit sebelum menulis.
5. **Snapshot-first, idempoten, aditif.** Field baru dibuat lewat `upgrade.py` pola lama;
   tidak ada migrasi destruktif; remediasi adalah alat eksplisit (dengan `dry_run`), bukan
   migrasi otomatis.
6. **Satu komponen dropdown untuk semua halaman.** Perbaikan arah ada di `LinkInput.vue` +
   `.link-results` di `styles.css`, bukan per halaman.

## 4. Propagasi live saat pengaturan disimpan

### 4.1 Alur `warehouse_defaults_save` (diperluas)

Urutan dalam satu request (satu transaksi DB — kegagalan membatalkan simpanan pengaturan):

1. Baca nilai lama ke-8 field + company dari singleton (sebelum `settings.save()`).
2. Validasi payload (lihat §6.3) lalu simpan singleton seperti sekarang.
3. Hitung diff per field `WAREHOUSE_DEFAULT_FIELDS` (4 field WO saja).
4. Untuk tiap field dengan **nilai lama non-kosong, nilai baru non-kosong, dan berbeda** →
   propagasikan (§4.3). Field settings-only (handover, handover source, form order source/target)
   tidak dipropagasikan: konsumennya membaca nilai saat aksi terjadi, dan MR yang sudah dibuat
   memakai nilai tersimpannya sendiri (`production_app/api/handover.py:1399`).
5. Kembalikan nilai flat ke-9 field **plus** kunci baru `propagated`/`failed`/`skipped`
   (§8) — bentuk flat dipertahankan agar konsumen lama tidak patah.

### 4.2 Mendefinisikan "berjalan" dan gating company

Filter SQL kandidat per field yang berubah (scan **db-level** — `frappe.db.get_all`, bukan
`frappe.get_all` yang terfilter permission sesi):

```python
filters = [
    ["Work Order", "docstatus", "<", 2],
    ["Work Order", "status", "not in", ["Completed", "Stopped", "Closed", "Cancelled"]],
    ["Work Order", "<field>", "=", old_value],
]
```

- **Kenapa db-level:** propagasi adalah konsekuensi administratif dari tulisan pengaturan yang
  sudah digate permission Manufacturing Settings write; WO berjalan yang tidak terlihat oleh
  session user (mis. penerapan permission level di masa depan) tetapi nilainya berasal dari
  default tidak boleh lolos diam-diam dari sinkronisasi. Konsistensinya dijaga di penanganan
  per-WO: WO submitted ditulis `db_set` tanpa permission check (selaras dengan scan), dan WO
  draft via `save()` yang *memang* dicek permission — WO draft yang tak bisa ditulis user
  penyimpan masuk daftar `failed` dengan alasan permission, bukan di-skip senyap.
- `"Cancelled"` pada filter status redundan terhadap `docstatus < 2` (native `get_status`
  hanya mengembalikan Cancelled untuk docstatus 2 — erpnext `work_order.py:703-746`); tidak
  berbahaya, dipertahankan sebagai pertahanan ganda terhadap data legacy.

Lalu saring company: WO kandidat hanya diproses bila `custom_default_company` kosong
(berlaku untuk semua company — perilaku lama) ATAU `wo.company == custom_default_company`.
WO company lain tidak pernah ikut ter-timpa (inti permintaan COMPANY).

### 4.3 Aturan penulisan per WO — header vs baris, draft vs submitted

Satu helper bersama `_apply_warehouse_changes(wo_name, changes)` dengan
`changes = {field: (old, new)}`, dipakai oleh propagasi dan remediasi. **Kedua jalur
(draft dan submitted) menjalankan urutan yang sama — lock, re-read, re-verifikasi,
baru tulis (menutup TOCTOU antara scan §4.2 dan tulisan):**

1. `frappe.db.get_value(DOCTYPE, name, "name", for_update=True)` — lock baris.
2. `wo = frappe.get_doc(DOCTYPE, name)` — selalu fresh dari DB, tidak pernah salinan basi.
3. **Re-verifikasi kandidat** terhadap dokumen yang baru dibaca: `docstatus < 2`, status
   masih berjalan, company masih lolos gate §4.2, dan nilai kolom masih `== old` yang
   diharapkan. Gagal salah satu → catat sebagai entri `skipped` (nama + alasan), **tanpa
   menulis apa pun**, dan jangan masukkan ke `propagated` (jejak audit jujur: WO yang
   keburu di-cancel/diubah tulisan lain tidak pernah dilaporkan sebagai terpropagasi).
4. **Validasi prapath:** untuk tiap `new` yang akan ditulis, baca `Warehouse.company`;
   bila terisi dan berbeda dengan `wo.company` → **lewati field itu untuk WO itu** dan
   catat di `failed` dengan alasan (pengganti cek native yang dilompati `db_set`).
5. **Guard `skip_transfer`:** jangan pernah menulis `wip_warehouse` ke WO dengan
   `skip_transfer == 1` — validate native selalu me-reset-nya ke None
   (`check_wip_warehouse_skip`, erpnext `work_order.py:607-609`), jadi nilai yang kita
   tulis hanya akan jadi data basi yang menyesatkan. Data live hari ini bersih
   (0 dari WO berjalan yang `skip_transfer=1` — diverifikasi bench console read-only
   2026-09-20); guard ini murni pertahanan depan.
6. **Draft (`docstatus == 0`):** set `wo.<field> = new` untuk field yang cocok, khusus
   `source_warehouse` juga set baris `required_items` dengan `source_warehouse == old`
   ke `new`, lalu `wo.save()` — lock di langkah 1 mencegah lost-update terhadap
   `prepare()` operator (pola prepare `production_app/api/work_order.py:620-622`; pola
   sama di transfer_materials `:669-671`, confirm_prepacking `:859-861`,
   finish `:1006-1008`). `save()` menjalankan `validate()` native — `set_warehouses()`
   hanya mengisi baris kosong dari header (erpnext `work_order.py:478-482`), makanya
   baris lama harus diset eksplisit lebih dulu; rebuild baris dari BOM (bila terjadi)
   tetap konvergen karena nilai baris = header WO dulu (erpnext
   `work_order.py:1760-1767`). Validasi native warehouse↔company ikut berjalan di sini.
7. **Submitted (`docstatus == 1`):** `wo.db_set(field, new)` untuk header; khusus
   `source_warehouse`, untuk tiap baris `required_items` dengan `source_warehouse == old`
   → `row.db_set("source_warehouse", new)` — meniru pola native `transferred_qty` per
   baris (erpnext `work_order.py:1798`). `db_set` meng-update `modified` dan membersihkan
   cache dokumen (frappe `model/document.py:1515-1545`, `database/database.py:988-994`)
   sehingga daftar/kartu workspace menyegarkan nilai baru.
8. `wip_warehouse`/`fg_warehouse`/`scrap_warehouse` hanya menulis header (baris tidak
   punya kolom itu; tujuan transfer diambil dari header `wip_warehouse` — erpnext
   `work_order.py:2714-2745`).

### 4.4 Yang TIDAK diubah

- **WO dengan nilai manual** (kolom ≠ nilai lama) — tidak tersentuh oleh konstruk filter
  `<field> == old`.
- **Pengosongan default** (old non-kosong → kosong) **tidak** menghapus nilai di WO: menghapus
  gudang dari WO submitted bisa merusak transfer berikutnya (baris tanpa `s_warehouse`).
  Nilai lama yang valid saat diterapkan tetap dipakai WO; untuk memperbaikinya gunakan
  remediasi setelah default diisi benar.
- **Gap yang disengaja — pola simpan DUA TAHAP (kosongkan → isi nilai baru):** karena tidak
  ada tahap yang memenuhi "old non-kosong → new non-kosong", pola ini TIDAK memicu
  propagasi apa pun dan WO berjalan tetap memegang nilai lama; jalur perbaikannya adalah
  remediasi §5 (dry_run → eksekusi). Alternatif "simpan nilai lama saat pengosongan agar
  pengisian berikutnya tetap terpropagasi" **ditolak**: menambah state turunan persisten
  (8 field riwayat di singleton) hanya demi satu urutan edit yang jalur langsung
  (ubah X → Y dalam satu simpan) sudah tutup, dan remediasi sudah menjadi jalur pemulihan
  yang aman dan ter-audit. Copy UI §9 tidak boleh menjanjikan lebih luas dari perilaku ini.
- **Pengisian dari kosong** (old kosong → terisi) tidak dipropagasikan: kolom kosong tidak
  bisa dibedakan asalnya, dan draft akan terisi otomatis oleh `prepare()` →
  `_fill_warehouse_defaults` (`production_app/api/work_order.py:636-637, 592-610`).
- **SE tersubmit, MR tersubmit, `transferred_qty`, `material_transferred_for_manufacturing`** —
  histori utuh; hanya transfer tambahan yang memakai gudang baru.
- **Job Card** — menyimpan salinan gudang sendiri saat dibuat (erpnext `work_order.py:2988,2992`);
  propagasi level WO tidak menyentuhnya (lihat risiko §12).
- **Field settings-only** (handover/form order) — lihat §4.1 butir 4.

### 4.5 Penanganan kegagalan

WO submitted secara praktis tidak gagal (`db_set` tanpa validasi, dan cek company sudah
dilakukan aplikasi). WO draft bisa gagal `save()` karena data draft invalid yang sudah ada —
kegagalan per-WO ditangkap (`try/except` per WO), dimasukkan ke `failed` dengan pesan
Indonesia, dan **tidak** membatalkan simpanan pengaturan (settings tetap tersimpan;
propagasi bisa diulang via remediasi setelah WO bermasalah dibereskan). Tanpa
`ignore_permissions`, dan realitas permission-nya asimetris (d diverifikasi live 2026-09-20,
bench console read-only site `frontend`):

- **WO submitted via `db_set`** tidak melalui permission check apa pun — aman karena
  satu-satunya pintu masuknya adalah tulisan pengaturan yang digate
  `has_permission("Manufacturing Settings", "write")`, dan satu-satunya DocPerm write
  Manufacturing Settings live adalah Manufacturing Manager.
- **WO draft via `save()`** dicek permission WO session user. DocPerm Work Order live HANYA
  berisi Manufacturing User (read/write/create/submit) dan Stock User (read) — Manufacturing
  Manager TIDAK punya baris DocPerm WO; hari ini pemegang role Manager kebetulan juga
  System Manager (jadi write effektif via System Manager). Penulis pengaturan yang tidak
  punya write WO akan melihat draft-nya masuk `failed` dengan alasan permission — perilaku
  yang benar dan eksplisit, bukan kegagalan senyap.

### 4.6 Asumsi mode backflush (keselamatan perubahan wip mid-run)

Keselamatan mengubah `wip_warehouse` pada WO yang sudah berjalan bergantung pada setting
native `backflush_raw_materials_based_on`, yang di site `frontend` terverifikasi
**"Material Transferred for Manufacture"** (dibaca via bench console read-only, 2026-09-20).
Pada mode ini konsumsi bahan di Manufacture bersifat ledger-driven — `get_available_materials`
meng-key material per `(item_code, warehouse aktual dari histori SE)` (erpnext
`stock_entry.py:4738-4777`; terverifikasi ada di container pada baris 4738) — sehingga
perubahan `wip_warehouse` mid-run tidak membuat konsumsi salah arah: SE Manufacture mengikuti
gudang tempat bahan benar-benar masuk. Pada mode **"BOM"** jalur yang dipakai adalah
`get_bom_raw_materials` (erpnext `stock_entry.py:3464`) dan perilakunya terhadap perubahan
wip mid-run **belum diverifikasi** — mode ini masuk cek gate §13.1 sebelum implementasi
mengklaim keamanan wip; bila site kelak berpindah mode, anggap perubahan wip mid-run perlu
ditinjau ulang.

Konsekuensi operasional yang harus diketahui admin (bukan kerusakan data): mengubah
`wip_warehouse`/`fg_warehouse` mid-run pada WO yang sudah transfer parsial memecah stok
WIP/FG WO itu ke **dua gudang** (bagian lama di gudang lama, bagian baru di gudang baru).
Papan serah terima dan `_batch_quantities` (`production_app/api/handover.py`) meng-key stok
per gudang aktual sehingga tetap benar — admin hanya perlu tahu bahwa barang WO parsial bisa
berada di dua lokasi sekaligus.

## 5. Remediasi WO yang sudah terlanjur salah

Endpoint baru di `production_app/api/work_order.py`:

```python
@frappe.whitelist()
def sync_warehouse_defaults_to_running_work_orders(dry_run=0):
```

- **Gate:** sama dengan simpan pengaturan — `frappe.has_permission("Manufacturing Settings",
  "write", throw=True)` dengan pesan Indonesia. Satu sumber gate untuk kedua jalur tulis
  (tidak ada asimetri keanggotaan role); pada site ini permission itu hanya dipegang
  Manufacturing Manager (diverifikasi live 2026-09-20: DocPerm Manufacturing Settings
  satu-satunya write = `('Manufacturing Manager', 0, read=1, write=1, create=1)`), sehingga
  maksud "gate role Manufacturing Manager" dari arah pemilik run tetap terpenuhi.
- **Perilaku:** terapkan default **sekarang** (4 field WO, company-gated §4.2) ke semua WO
  berjalan yang kolomnya **berbeda** dengan default (termasuk kosong). Header ditulis ke
  default; khusus `source_warehouse`, baris dengan `source_warehouse == nilai header lama`
  ikut ditulis ke default — baris yang berasal dari BOM/item default (beda dari header lama)
  dipertahankan. Draft via `document.save()`, submitted via `db_set` (helper yang sama dengan
  propagasi, §4.3, termasuk validasi warehouse↔company prapath).
- **`dry_run=1`:** mengembalikan rencana perubahan tanpa menulis apa pun — admin memeriksa
  daftar sebelum eksekusi nyata.
- **Idempoten:** kolom yang sudah == default tidak ditulis; eksekusi kedua mengembalikan
  daftar kosong.
- **Return (jejak audit pengganti Version):** `{"updated": [{"name", "docstatus", "status",
  "company", "changes": {field: [old, new]}, "rows_updated": int}], "skipped": [...],
  "failed": [...], "dry_run": bool}`.
- Tidak ada tombol UI untuk endpoint ini (menghindari tombol massal berbahaya); dipakai
  via HTTP/bench oleh admin untuk kasus user. Setelah itu propagasi otomatis mengambil alih
  **untuk pola ubah langsung lama→baru dalam satu simpan**; tiga kasus tetap membutuhkan
  remediasi eksplisit dan harus dikomunikasikan ke admin: (1) pola simpan dua tahap
  kosongkan→isi (gap §4.4), (2) WO draft yang gagal permission/validasi saat propagasi
  (masuk `failed`), (3) WO yang sengaja membawa nilai manual — remediasi pun tidak
  menimpanya kecuali memang dimaksudkan, karena remediasi menulis semua kolom yang beda
  dengan default.

## 6. Fitur Company

### 6.1 Field dan migrasi

- Custom field baru di Manufacturing Settings: `custom_default_company`, `fieldtype: Link`,
  `options: Company`, label `"Default Company (Production App)"`, description Indonesia
  ("Production App: default gudang hanya berlaku untuk company ini; kosong = semua company").
- Ditambahkan sebagai spec ke list `WAREHOUSE_DEFAULT_FIELDS` di
  `production_app/upgrade.py:224-281` sehingga dibuat oleh `ensure_warehouse_default_fields()`
  (`production_app/upgrade.py:284-326` — anchoring setelah field terakhir, idempoten, tidak
  memindahkan field lama); `apply()` sudah memanggilnya di `production_app/upgrade.py:1334`.
- Snapshot dulu (pola `snapshot_form_order` yang sudah mencakup Manufacturing Settings,
  `production_app/upgrade.py:1130-1155`): `snapshot_fu58()` menulis
  `snapshots/fu58-warehouse-company-pre.json` berisi definisi Custom Field Manufacturing
  Settings + nilai tersimpan singleton ke-8 field gudang; `apply()` menjalankannya hanya bila
  file belum ada. Tidak ada migrasi data (field mulai kosong = semua company = perilaku lama);
  remediasi data nyata adalah alat eksplisit §5, bukan bagian `apply()`.

### 6.2 Gating konsumen

Helper tunggal di `production_app/api/work_order.py`:

```python
def _company_allowed(setting_company, doc_company):
    return not setting_company or setting_company == doc_company
```

Diterapkan pada:

| Konsumen | Pemakaian | Perilaku saat company tidak cocok |
|---|---|---|
| `_fill_warehouse_defaults` (prepare, WO draft) `production_app/api/work_order.py:592-610` | default settings hanya dipakai bila company cocok; default Item tetap (scoped per item) | kolom kosong dibiarkan kosong |
| Propagasi & remediasi (§4.2, §5) | filter WO per company | WO company lain tidak tersentuh |
| `handover.py` `_target_warehouse` / `_source_warehouse` / `_pool_warehouse` (`:96-119`) dan `form_order.py` `_warehouses_or_throw` (`:140-160`) | nilai default settings dibaca hanya bila company cocok dengan WO/MR konsumen | dianggap "belum diatur" → jalur existing yang menolak aksi tanpa gudang (`_target_warehouse_or_throw` `:1050-1056`, `_warehouses_or_throw`) berjalan |

Catatan perluasan: arah pemilik run hanya mewajibkan gating di `_fill_warehouse_defaults` dan
propagasi/remediasi. Desain ini memperluas ke konsumen handover/form order karena permintaan
user ("default gudang hanya berlaku bagi company terpilih") menyasar ke-8 default, bukan hanya
4 field WO; biayanya satu pemanggilan helper per konsumen. Efek sampingnya: untuk WO/MR company
non-matching, aksi serah terima/form order akan menolak dengan pesan "belum diatur" alih-alih
memakai gudang company lain — saat ini seluruh 82 WO berjalan adalah PT. Juara Roti Indonesia
(data live), jadi tidak ada alur aktif yang berubah.

### 6.3 Validasi simpan

`warehouse_defaults_save` menambah parameter `company=None` dan:

1. `company` non-kosong harus `frappe.db.exists("Company", ...)` — jika tidak, throw pesan
   Indonesia (pola pesan gudang existing `production_app/api/work_order.py:584`).
2. Bila `company` terisi: tiap gudang non-kosong yang `Warehouse.company`-nya terisi dan
   berbeda → throw (mirror logika native `validate_warehouse_company`, erpnext
   `stock/utils.py:415-421`, karena propagasi `db_set` melewatkannya). `company` kosong tidak
   di-cross-check (kompatibel dengan gudang lintas company yang sudah berjalan selama ini).
3. Nilai kosong = `None` seperti sekarang (semantics "clear").

## 7. Dropdown drop-up (LinkInput)

- **Lokasi perubahan:** `workspace_frontend/src/LinkInput.vue` (satu-satunya komponen yang
  merender `.link-results`) + `.link-results` di `workspace_frontend/src/styles.css:1962-1982`.
  Otomatis berlaku untuk semua konsumen LinkInput — panel pengaturan
  (`WarehouseSettings.vue`), `FormOrderCreate.vue`, `stages/StageOperasi.vue` (diverifikasi
  grep: tiga file itu satu-satunya pemakai).
- **Perilaku:** tetap `position: absolute` dalam wrapper `.linkinput { position: relative }`
  (`styles.css:1961`) sehingga layout tidak pernah bergeser. Saat daftar hasil akan
  ditampilkan, ukur `inputEl.getBoundingClientRect()` DAN **batasi ruang oleh
  clipping-ancestor terdekat** (bukan hanya viewport): naik rantai `parentElement`, dan untuk
  tiap ancestor yang `getComputedStyle` overflow-x/overflow-y-nya `auto|scroll|hidden`,
  jadikan `rect`-nya batas tambahan. Ruang efektif:
  - `atas = rect.top - max(0, semua clippingTop, viewportTop)`
  - `bawah = min(viewportBottom, semua clippingBottom) - rect.bottom`
  Ini wajib karena kasus nyata sudah ada di repo: `.tbl-wrap.fo-grid-wrap` — wrapper grid
  item Form Order yang menampung baris LinkInput (`FormOrderCreate.vue:136`) —
  `overflow: visible` di desktop (fix FU52, `styles.css:2061` + komentarnya: "wrapper grid
  FO tidak memotong dropdown overlay") tetapi `overflow-x: auto` pada ≤820px
  (`styles.css:2062`) yang mengkomputasi overflow-y ikut clipping; di mobile, input dekat
  tepi atas grid "punya ruang viewport" menurut pengukuran viewport saja namun tetap
  terpotong wrapper — dan bila dua arah sama-sama terpotong, pemilihan arah tidak menolong.
- **Aturan arah:** **default ke ATAS** bila ruang atas efektif cukup (± 240px untuk
  `max-height` 220 + gap 4 + buffer — permintaan user); turun ke bawah bila ruang atas
  kurang dan ruang bawah cukup; bila keduanya kurang, pilih sisi dengan ruang efektif
  terbesar **dan** pasangkan dengan max-height adaptif di bawah.
- **Max-height adaptif:** daftar diberi `style="max-height: min(220px, ruangSisiTerpilih − 8px)"`
  sehingga bila ruang kedua sisi sempit pun daftar tetap terlihat penuh (di-scroll di
  dalamnya) dan tidak terpotong container — menutup kasus "dua arah terpotong" di grid
  mobile alih-alih hanya memilih sisi yang kurang buruk. Perilaku scroll-x mobile pada
  wrapper grid sengaja dipertahankan (perilaku FU22/FU52 yang ada; tidak mengubah CSS-nya).
- **CSS:** base `.link-results` kehilangan `top`, arah jadi modifier —
  `.link-results.up { bottom: calc(100% + 4px); }` dan `.link-results.down { top: calc(100% + 4px); }`
  (sisanya: left, z-index, width, background, radius — tidak berubah; `max-height` pindah
  ke inline style adaptif). Pengukuran dilakukan sekali saat daftar dibuka; scroll halaman
  saat daftar terbuka tidak di-ukur ulang (sama dengan perilaku sekarang — risiko minor §12).
- Placeholder/komunikasi visual lain tidak berubah.

## 8. Kontrak API

```python
# production_app/api/work_order.py

warehouse_defaults() -> {
  "source_warehouse", "wip_warehouse", "fg_warehouse", "scrap_warehouse",
  "handover_warehouse", "handover_source_warehouse",
  "form_order_source_warehouse", "form_order_target_warehouse",
  "company",                                     # BARU (None bila kosong)
}

warehouse_defaults_save(...8 field lama..., company=None) -> {
  ...9 kunci FLAT seperti warehouse_defaults()...,       # bentuk lama DIPERTAHANKAN
  "propagated": [{"name","docstatus","status","company",
                  "changes": {field: [old, new]}, "rows_updated": int}],
  "skipped":   [{"name","reason"}],
  "failed":    [{"name","error"}],
}

sync_warehouse_defaults_to_running_work_orders(dry_run=0) -> {
  "updated": [...entri sama seperti propagated...],
  "skipped": [...],
  "failed": [...],
  "dry_run": bool,
}
```

Read endpoint tetap terbuka untuk user login; write tetap digate permission Manufacturing
Settings (`production_app/api/work_order.py:556-559, 569`).

**Bentuk return save tetap flat (kesadaran Breaking-Tests):** tiga suite existing
meng-assert kunci flat pada return `warehouse_defaults_save` —
`test_handover_setup.py:478` (`saved["handover_warehouse"]`),
`test_form_order.py:285-286` (`saved["form_order_source_warehouse"]`),
`test_wo_transaction_proof.py:1154` (`saved["fg_warehouse"]`) dan `:1187`
(`cleared["fg_warehouse"]`) — dan satu-satunya konsumen non-test adalah
`WarehouseSettings.vue:74` (diverifikasi grep `src/` + `production_app/`). Membungkus
nilai ke `{"values": ...}` akan mematahkan ketiganya padahal gate §13.2 mewajibkan suite
existing hijau; kunci baru cukup DITAMBAHKAN di samping kunci flat (backward-compatible,
ketiga file tes tidak perlu berubah). Agar kunci baru tidak ikut terkirim balik saat simpan
berikutnya, `WarehouseSettings.vue` mengirim payload eksplisit 9 field (bukan `{...form}`)
dan hanya menyalin 9 kunci flat itu ke `form` (§9).

## 9. Perubahan UI dan copy

`workspace_frontend/src/WarehouseSettings.vue`:

1. **Field Company** — blok field baru di atas blok "Default Work Order":
   `LinkInput doctype="Company"` terikat `form.company`; hint: *"Default hanya berlaku untuk
   company ini — kosongkan untuk berlaku di semua company."*
2. **Callout "Default Work Order"** (`WarehouseSettings.vue:115-118`) diganti — copy jujur
   terhadap batas §4.4 (tidak menjanjikan lebih luas dari perilaku):
   > "Dipakai Work Order yang kolom gudangnya masih kosong saat Persiapan disimpan. Ubah
   > nilai langsung ke nilai baru (jangan kosongkan dulu lalu isi belakangan): perubahan
   > langsung otomatis diterapkan ke Work Order yang sedang berjalan — header dan baris
   > bahan — selama nilainya masih sama dengan nilai lama. Nilai yang sudah diubah manual
   > di Work Order tidak ditimpa; kasus lain (termasuk WO yang gagal diperbarui) perlu
   > sinkronisasi oleh admin."
3. **Lead panel** (`:89`) ditambah satu kalimat yang terukur: "Perubahan nilai default
   otomatis diterapkan ke Work Order yang sedang berjalan selama nilainya belum diubah
   manual."
4. **Feedback simpan** — `save()` mengirim payload eksplisit 9 field (bukan `{...form}`)
   dan menyalin hanya 9 kunci flat dari response ke `form` (mencegah kunci
   `propagated`/`skipped`/`failed` terkirim balik / menempel di form); lalu tampilkan:
   *"Tersimpan pada HH.MM — N Work Order berjalan diperbarui"* (nama WO ringkas bila
   sedikit, mis. 5 pertama + "…"), dan daftar `failed` sebagai pesan error per WO (tidak
   menggagalkan tersimpannya pengaturan).

Tidak ada perubahan copy lain; FormOrderCreate/StageOperasi menerima perilaku dropdown baru
tanpa perubahan kode.

## 10. Rencana uji

### 10.1 Suite baru `production_app/tests/test_warehouse_defaults_live.py`

`IntegrationTestCase` pola `test_handover_setup.py` (fixture prefix `FU58`, rollback otomatis;
WO fixture dibuat native — ikuti pola pembuatan WO di `test_wo_transaction_proof.py`):

| # | Skenario | Bukti yang wajib |
|---|---|---|
| 1 | Propagasi draft | WO draft dengan header+baris `source_warehouse == old` → simpan setting berubah → header & baris = new; `save()` native tetap jalan (Version terbuat) |
| 2 | Propagasi submitted | WO submitted `source_warehouse == old` → simpan → header db_set + semua baris `required_items` yang == old ikut; WO Completed dengan nilai sama tidak tersentuh |
| 3 | Nilai manual aman | WO dengan kolom ≠ old (nilai manual) → tidak berubah (header & baris) |
| 4 | Lingkup field | Ubah hanya `handover_warehouse`/form-order → tidak ada tulisan ke WO apa pun |
| 5 | Pengosongan tidak propagasi | old → kosong → kolom WO tetap old |
| 6 | Gate company di `_fill` | setting company A + WO company B → prepare tidak mengisi dari setting; company kosong → terisi (kompat lama) |
| 7 | Gate company di propagasi | WO company B dengan kolom == old tidak diubah saat setting company A |
| 8 | Remediasi | WO berjalan salah → `sync_...()` memperbaiki header+baris dan muncul di return; eksekusi kedua return kosong; `dry_run=1` tidak menulis; user tanpa write Manufacturing Settings (bukan Manufacturing Manager di site ini) → `PermissionError` |
| 9 | Validasi simpan | gudang tidak dikenal → throw; company tidak dikenal → throw; gudang milik company lain saat setting company terisi → throw |
| 10 | Baris BOM dipertahankan | baris `source_warehouse` beda dari header lama (dari BOM) tidak diubah propagasi/remediasi |
| 11 | Race draft (lost-update) | helper memanggil `frappe.db.get_value(DOCTYPE, name, "name", for_update=True)` sebelum `get_doc` (dibuktikan via `unittest.mock` pada pemanggilan `for_update`); setelah propagasi pada draft yang barusan di-`prepare()`, nilai Data Adonan (mis. `custom_adonan_ke`, `custom_leader_produksi`) TIDAK berubah dan hanya kolom gudang yang berubah |
| 12 | End-to-end builder (kasus user) | setelah propagasi/remediasi ke WO submitted berjalan, `erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry(name, "Material Transfer for Manufacture")` menghasilkan baris dengan `from_warehouse ==` default baru (assert pada output builder, TANPA submit SE) |
| 13 | Backward-compat return | `warehouse_defaults_save` tetap mengembalikan kunci flat (`saved["fg_warehouse"]` dsb. tetap valid — tiga suite lama tidak berubah) DAN kunci baru `propagated`/`skipped`/`failed` hadir |
| 14 | Gap clear→set (dokumentasi perilaku) | simpan #1 mengosongkan default, simpan #2 mengisi nilai baru → TIDAK ada tulisan ke WO (gap §4.4); remediasi setelahnya memperbaiki |
| 15 | TOCTOU jalur submitted | ubah WO (mis. nilai kolom atau status) SETELAH scan kandidat namun SEBELUM helper menulis (simulasi: panggil helper dengan ekspektasi `old` basi) → helper me-re-verifikasi, mencatat `skipped`, dan tidak menulis apa pun; WO tidak muncul di `propagated` |
| 16 | Guard skip_transfer | WO berjalan `skip_transfer=1` → perubahan default `wip_warehouse` tidak ditulis ke WO itu (masuk `skipped`/`failed` dengan alasan); perubahan `source_warehouse` tetap diproses |

### 10.2 Perintah (pola PROJECT_STATE: bench apps bukan bind mount — docker-cp dulu)

```bash
docker cp production_app/... erpnext-new-backend-1:/home/frappe/frappe-bench/apps/production_app/...
docker exec erpnext-new-backend-1 bench --site frontend run-tests \
  --module production_app.tests.test_warehouse_defaults_live
# gate akhir: suite penuh 2x
docker exec erpnext-new-backend-1 bench --site frontend run-tests --app production_app
```

### 10.3 Skenario bukti live + remediasi data nyata (site `frontend`, pasca-implementasi)

1. **Idempulsi simpan:** simpan ulang panel tanpa mengubah nilai → `propagated` kosong.
2. **Dry-run remediasi:** `bench --site frontend execute
   "production_app.api.work_order.sync_warehouse_defaults_to_running_work_orders"
   '{"dry_run": 1}'` → daftar rencana memuat ±11 WO yang berbeda (5 submitted: 03116, 03133,
   02391, 03410, TEST-WO001; 6 draft fg salah: 01334-01337, 02083, 02325 — dari data live
   peneliti FU58; 37 draft bersource kosong ikut terisi default).
3. **Eksekusi remediasi sekali:** verifikasi pasca via bench console (read-only):
   `MFG-WO-2026-03410` header + semua baris `source_warehouse` = "Gudang Produksi - ROPI";
   SE tersubmit milik 02391/TEST-WO001 dan `transferred_qty` tidak berubah; 6 draft fg =
   "Cold Storage Produksi - ROPI".
4. **Uji manusia panel:** ubah satu default lewat panel → kartu/daftar WO berjalan di SPA
   menunjukkan gudang baru setelah refresh; dropdown Company dan gudang membuka ke atas di
   panel, form order, dan stage operasi (desktop + mobile). **Smoke mobile wajib menyertakan
   grid item Form Order pada viewport ≤820px** — kasus clipping `.tbl-wrap.fo-grid-wrap`
   (`styles.css:2061-2062`): dropdown baris LinkInput di baris pertama dan terakhir grid
   harus terlihat penuh (arah + max-height adaptif §7), tidak terpotong wrapper scroll-x.
5. **Rollback data nyata:** nilai pra-remediasi tercatat di output `dry_run`/`updated`
   (old per field) — simpan keluaran itu sebagai jejak; tidak ada mekanisme undo otomatis.

## 11. File yang diharapkan berubah saat implementasi

- `production_app/api/work_order.py` — konstanta company, helper `_company_allowed`,
  `_apply_warehouse_changes`, validasi simpan, perluasan `warehouse_defaults`/
  `warehouse_defaults_save`, endpoint `sync_warehouse_defaults_to_running_work_orders`.
- `production_app/api/handover.py`, `production_app/api/form_order.py` — konsumsi gate
  company (swap baca setting ke helper ter-gate).
- `production_app/upgrade.py` — spec `custom_default_company`, `snapshot_fu58()`, panggilan
  di `apply()`.
- `production_app/tests/test_warehouse_defaults_live.py` — baru.
- **Tidak perlu mengubah** `test_handover_setup.py`, `test_form_order.py`,
  `test_wo_transaction_proof.py`: return `warehouse_defaults_save` tetap flat sehingga
  asersi `saved[...]`/`cleared[...]` di ketiganya tetap valid (§8); suite baru yang
  meng-assert kunci `propagated`/`skipped`/`failed` (skenario 13).
- `workspace_frontend/src/WarehouseSettings.vue`, `workspace_frontend/src/LinkInput.vue`,
  `workspace_frontend/src/styles.css` (+ hasil build ke `production_app/public/workspace`
  sesuai alur build existing).
- Dokumen eksekusi (`TASKS.md`, `PROJECT_STATE.md`).

Tidak menyentuh ERPNext/Frappe core, tidak menduplikasi override `bakery_manufacturing`,
tidak menambah dependensi/DocType baru.

## 12. Risiko dan mitigasi

| Risiko | Bukti | Mitigasi |
|---|---|---|
| Propagasi header saja tidak mengubah transfer berikutnya (builder baca per baris tanpa fallback header) | erpnext `stock_entry.py:3946-3950` | desain menulis header **dan** baris `required_items` bersama (§4.3) |
| `db_set` menembus `validate_warehouse_belongs_to_company` → gudang lintas company tertulis diam-diam, meledak di save() WO berikutnya | erpnext `work_order.py:611-619`; frappe `database/database.py:934-1003` | validasi warehouse↔company di simpan pengaturan (§6.3) **dan** prapath per-WO (skip+catat, §4.3) |
| Tulisan submitted tanpa record Version (jejak audit) | frappe `model/document.py:1472,1588` | return `propagated`/`updated` (old→new per field) ditampilkan UI dan disimpan admin untuk remediasi live (§10.3.5) |
| Draft invalid membuat `save()` gagal dan (bila tidak ditangani) memblokir simpan pengaturan | `save()` draft menjalankan validate penuh | kegagalan per-WO ditampung di `failed`; settings tetap tersimpan; remediasi bisa mengulang (§4.5) |
| Lost-update jalur draft: `get_doc → set → save()` menyimpan seluruh dokumen dari salinan basi; irisan dengan `prepare()` operator bisa mengembalikan Data Adonan draft ke nilai lama | pola lock semua endpoint mutasi (`production_app/api/work_order.py:621,670,860,1007`) | helper draft mengambil lock baris + re-read sebelum menulis (§4.3); skenario uji 11 |
| Asimetri permission: `db_set` submitted tanpa permission check, draft `save()` dicek permission WO — Manufacturing Manager TIDAK punya DocPerm WO live (hanya Manufacturing User write, Stock User read) | verifikasi live 2026-09-20 (§4.5) | submitted aman karena gate tunggal Manufacturing Settings write (= Manager); draft gagal permission masuk `failed` eksplisit; scan kandidat db-level agar tidak ada WO tersembunyi yang lolos diam-diam (§4.2) |
| Perubahan `wip_warehouse` mid-run salah arah konsumsi bila mode backflush bukan "Material Transferred for Manufacture" | asumsi §4.6 (mode live terverifikasi; jalur BOM `stock_entry.py:3464` belum diverifikasi) | mode masuk gate kontrak §13.1; konsumsi mode MTF ledger-driven per gudang aktual (`get_available_materials` `stock_entry.py:4738-4777`) |
| wip/fg berubah mid-run memecah stok WO transfer-parsial ke dua gudang (operasional, bukan korupsi) | §4.6 | papan serah terima & `_batch_quantities` meng-key per gudang aktual; konsekuensi didokumentasikan ke admin via copy/confirmation |
| WO dengan transfer parsial (02391, TEST-WO001): gudang berubah, histori SE dan baris yang sudah penuh tidak dikirim ulang dari gudang baru | erpnext `get_pending_raw_materials` hanya baris bersisa | diterima sebagai perilaku benar — hanya transfer tambahan memakai nilai baru; didokumentasikan ke user (§4.4) |
| Job Card menyimpan salinan gudang sendiri (32 WO In Process berpotensi punya Job Card gudang lama) | erpnext `work_order.py:2988,2992` | di luar lingkup FU58 (kasus user = source, tidak dipakai Job Card); dicatat sebagai keterbatasan; bila kelak wip/fg berubah pada WO ber-Job Card, sinkron Job Card jadi unit kerja tersendiri |
| Gate company di konsumen handover/form order mengubah perilaku untuk company non-matching (dari "jalan dengan gudang ROPI" jadi "belum diatur") | §6.2 | disengaja sesuai tujuan fitur; saat ini 100% WO berjalan adalah PT. Juara Roti Indonesia (data live); pesan error Indonesia menjelaskan cara isi default per company |
| Remediasi menimpa nilai yang tampak salah tapi disengaja (mis. 6 draft fg Gudang Barang Jadi) | data live peneliti | `dry_run` wajib diperiksa sebelum eksekusi; keluaran old→new disimpan sebagai jejak rollback manual |
| Dropdown dihitung sekali saat buka; scroll halaman saat terbuka bisa menggeser visual | §7 | sama dengan perilaku dropdown lama (arah bawah) — tidak ada regresi; re-measure saat scroll ditunda sampai ada laporan nyata |
| Dropdown terpotong scroll-container ancestor (konkret: `.tbl-wrap.fo-grid-wrap` `overflow-x:auto` ≤820px mengkomputasi overflow-y clipping — FU52 memang sudah memilih `overflow:visible` di desktop demi ini) | `styles.css:2061-2062`; `FormOrderCreate.vue:136` | pengukuran arah di-bounding clipping-ancestor terdekat + max-height adaptif min(220, ruang sisi) sehingga daftar selalu terlihat penuh di sisi terpilih (§7); smoke mobile ≤820px eksplisit (§10.3.4) |
| TOCTOU jalur submitted: antara scan §4.2 dan tulisan, WO bisa berubah status/nilai → `db_set` menulis ke bukan-kandidat dan tercatat di `propagated` (audit menyesatkan) | §4.3 langkah 1-3 | helper melakukan lock + get_doc + re-verifikasi kandidat untuk KEDUA jalur; mismatch → `skipped`, tanpa tulisan, tidak masuk `propagated`; skenario uji 15 |
| Menulis `wip_warehouse` via `db_set` pada WO `skip_transfer=1` menyimpan nilai yang validate native selalu reset ke None (`check_wip_warehouse_skip`) | erpnext `work_order.py:607-609`; live 2026-09-20: 0 WO berjalan `skip_transfer=1` | guard eksplisit di helper: field wip dilewati untuk WO skip_transfer (§4.3 langkah 5); skenario uji 16 |
| Gap clear→set: admin yang mengubah default lewat dua simpan (kosongkan → isi) tidak memicu propagasi; WO tetap terkunci di nilai lama tanpa jalur UI | §4.4 | didokumentasikan sebagai perilaku (alternatif menyimpan nilai-lama-saat-pengosongan ditolak — state persisten untuk kasus tepi); copy §9 mengarahkan "ubah langsung"; remediasi adalah jalur pemulihan; skenario uji 14 |
| Kinerja propagasi: loop per WO berjalan | 82 WO berjalan saat riset | jumlah kecil dan terfilter indeks (`docstatus`, `status`, kolom field); tidak menambah query per baris (baris dibaca sekali per WO yang memang cocok) |
| Verifikasi mekanisme propagasi sendiri belum pernah dieksekusi (riset hanya baca) | laporan peneliti FU58 | rencana uji §10 wajib dijalankan sebelum klaim DONE; tidak ada klaim verifikasi dari inspeksi kode saja (AGENTS.md) |

## 13. Gate implementasi

1. **Kontrak:** ulangi verifikasi source native terpasang bila versi container berubah sejak
   riset ini (path sitasi §basis), DAN verifikasi `backflush_raw_materials_based_on` masih
   "Material Transferred for Manufacture" (asumsi §4.6) — bila mode "BOM", tinjau ulang
   keamanan propagasi `wip_warehouse` sebelum implementasi.
2. **Server:** suite baru §10.1 hijau + 6 suite existing ×2 hijau di container (docker-cp
   file Python dulu).
3. **Frontend:** build SPA sukses; smoke browser desktop+mobile — panel pengaturan (company +
   feedback propagasi), Form Order, stage Operasi (dropdown ke atas tidak menutupi elemen);
   **wajib menyertakan grid item Form Order di viewport ≤820px** (baris pertama & terakhir):
   dropdown LinkInput harus terlihat penuh, tidak terpotong `.tbl-wrap.fo-grid-wrap` yang
   menjadi scroll-container di mobile (§7, `styles.css:2061-2062`).
4. **Live:** dry-run remediasi ditinjau → eksekusi sekali → verifikasi 03410 & kawan-kawan
   (§10.3) → catat evidence di PROJECT_STATE.md.

Tidak melanjutkan melewati gate yang gagal dengan mengompensasi di frontend atau melemahkan
validasi native.

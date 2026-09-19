# FU48 — production_app Murni Produksi: gudang pakai ERPNext native (interim), rename Stock Entry, Form Order pilih satuan

Direksi user: gudang TIDAK dibikinkan app — interim pakai Desk/native ERPNext; production_app pure org produksi. Direview dan disetujui advisor. Fakta terverifikasi: doc_events sync serah terima murni document-driven (hooks.py:166-176 → `_handover_state` baca `custom_work_order` + type Material Transfer) — MR manual dari Desk otomatis sinkron ke WO + papan; preferensi per-user via `set_user_default` JSON (pola `list_preferences`); grid FO-8 sudah ala child table ERPNext.

## Global constraints

- Tidak ada edit core ERPNext/Frappe; bakery_manufacturing batch override tak disentuh.
- Endpoint server gudang (`create_request`/`cancel_request`/`fulfill_form_order`) TETAP HIDUP (SPA berhenti memanggilnya; reversibel).
- `send_handover` + doc_events + DocPerm + custom fields tak diubah kecuali Property Setter FU48a.
- Metadata hanya via `upgrade.py` snapshot-first idempoten (apply ×2 konvergen) — BUKAN folder fixtures (preseden insiden stale-fixture).
- Tidak ada fallback konversi factor-1 senyap (pola T39); validasi di server otoritatif; zero-write saat validasi gagal.
- Uji backend: 6 suite (`form_order`, `handover_setup`, `handover_board`, `handover_actions`, `handover_native_proof`, `wo_transaction_proof`) — suite handover harus hijau TANPA perubahan file test; suite form_order boleh bertambah kasus.
- Deploy prosedur tetap: docker cp host→container (backend+frontend), chown frappe:frappe via -u root, `bench --site frontend clear-website-cache`, restart backend bila Python berubah, hash bundle identik 5 titik + marker.
- CLI HTTP selalu `http://127.0.0.1:8081` (proses vite lain menempati `[::1]:8081`).
- Residu fixture 0 di akhir tiap tugas; data live tak tersentuh.
- Implementer TIDAK commit — controller commit tunggal gaya FU di `feat/three-lane-handover` di akhir (preseden FU43–FU47).
- TASKS.md section K + PROJECT_STATE.md protokol: IN_PROGRESS sebelum edit, DONE hanya dengan bukti eksekusi.

## Task 1 — FU48a — Gate: guard MR yatim + pre-check izin + bukti jalur native gudang

1. `upgrade.py`: Property Setter pada MR Item `custom_work_order` — property `mandatory_depends_on`, nilai `parent.material_request_type==="Material Transfer" && !parent.custom_is_form_order` (Property Setter value = string eval tanpa prefiks `eval:`; ikuti format field depends_on native — verifikasi di source terpasang bagaimana mandatory_depends_on dievaluasi untuk field child table, termasuk aksesibilitas `parent.`). Snapshot-first, idempoten (apply ×2 "unchanged"), rollback = hapus Property Setter doc. Hati-hati: jangan pakai folder fixtures.
2. Deploy metadata: docker cp `upgrade.py` → container backend (md5 identik), restart backend, `bench --site frontend execute production_app.upgrade.apply` ×2 konvergen.
3. Bukti runtime scripted (fixture terisolasi pola FU47 — item+batch, warehouses, WO→transfer→manufacture, user gudang+produksi, settings handover):
   - Guard: (a) MR Material Transfer TANPA `custom_work_order` TANPA `custom_is_form_order` → submit ditolak (mandatory); (b) `create_form_order` (custom_is_form_order=1) tetap lolos; (c) `create_request` API (set custom_work_order) tetap lolos; (d) MR tipe lain (mis. Purchase) tidak terkena mandatory.
   - Izin gudang: `frappe.has_permission` per role Gudang Barang Jadi — MR create/cancel, SE create/submit, WO read; role punya desk_access; field custom MR permlevel 0.
   - Jalur native: MR handover dibuat manual sebagai user gudang (get_doc insert+submit, isian persis form Desk: type Material Transfer, set_from_warehouse Cold, set_warehouse target, baris item custom_work_order + box kg/jumlah) → WO ringkasan "Diminta Gudang" + muncul di lane Request (handover_board sebagai produksi); `send_handover` produksi → SE terkirim (buktikan loop penuh native-created MR bisa dikirim); cancel MR native → ringkasan/lane bersih. Fulfill FO native sebagai gudang: SE via `make_mr_stock_entry` (jalur tombol Create Desk) → FO status terkirim. Over-request → SE gagal atomik validasi stok native (zero-write).
   - Test backend permanen untuk guard mandatory (minimal 3 kasus a/b/c di atas) masuk suite form_order atau setup; suite handover 5 file TIDAK diubah.
4. Browser Desk walkthrough (controller): login gudang fixture di `/app` → buat MR handorevia form Desk UI (field custom terlihat, mandatory bekerja) → submit → verifikasi papan produksi; Create→Stock Entry untuk FO → submit. Implementer menyiapkan fixture + kredensial di file sementara (dihapus setelah).
5. Cleanup fixture residu 0 (urutan aman: SE→MR→WO→BOM→batch→item→warehouse→user; SLE/Bin sweep; settings dikembalikan). Laporkan bukti.

## Task 2 — FU48b — Strip UI gudang + rename "Serah Terima" → "Stock Entry" + redirect

1. `HandoverBoard.vue` HAPUS (bukan komentar): dialog Buat Request Gudang + Batalkan request + semua state/handlernya, drag/klik-buat-request lot (kartu lot sepenuh inert — tidak draggable/live), tab Form Order + tombol Proses + dialog fulfill + import formOrders/formOrderState dari board, chooser multi-role. PERTAHANKAN: lane Cold Storage baca-saja (lot card tampil inert), kanban 3 lane + tabel FU47, dialog kirim "Kirim Serah Terima" (judul boleh disesuaikan "Kirim Stock Entry") + detail Terkirim baca-saja, search FU44, filter/pagination lane cold, preferensi viewMode. `targetLanes`/drag logic boleh dibuang total bila tak ada lagi kartu draggable.
2. `handover-se.js`: `rowClickAction` produksi-only — request tanpa flag → 'send', terkirim+stockEntry → 'done', selainnya null (hapus branch gudang/multi/choose). `seRouteLabel` tetap. Test `handover-se.test.mjs` diperbarui.
3. `store.js`: board berhenti memanggil `create_request`/`cancel_request`/`fulfill_form_order` (fungsi store createRequest/cancelRequest/fulfillFormOrder dihapus dari board flow; store FormOrderPage — form_order_list/create/cancel/item_info — tetap utuh). `App.vue`: hapus redirect gudang-only ke `#/handover` (ganti server-side), badge nav tetap.
4. Rename label: menu sidenav+bottom nav+judul halaman+sub "Serah Terima" → "Stock Entry" (sub: kirim barang jadi ke gudang); blok Pengaturan "Serah Terima (Stock Entry)" → "Stock Entry (Kirim ke Gudang)"; shortcut manifest "Papan Serah Terima" → "Stock Entry".
5. `www/production_workspace.py`: redirect server-side — session user TANPA role {Manufacturing User, Manufacturing Manager, System Manager} dan bukan Administrator → `/app` (sebelum render, pola guest redirect). Dual-role (gudang+produksi) TETAP masuk.
6. `www/sw.js`: bump versi cache `production-workspace-v1-` → `production-workspace-v2-` (semua cache name + cleanup list).
7. Regresi: node --test semua hijau; suite backend handover (5 file) hijau tanpa perubahan; build vite; deploy (docker cp bundle+www ke kedua kontainer, chown, clear-website-cache; restart backend karena www py berubah — restart aman); hash 5 titik + marker: HADIR "Stock Entry"+"Buat & Kirim Stock Entry", ABSEN "Buat Request Gudang"/"Proses"/"Pilih Aksi".
8. Verifikasi redirect: HTTP login gudang-only → `/production_workspace` merespon redirect `/app`; produksi → 200.

## Task 3 — FU48c — Form Order: dropdown Satuan + default satuan terakhir dipakai

1. `form_order.py`:
   - `_valid_uoms(item_code)` → list `{uom, conversion_factor}` dari child table konversi UOM Item (verifikasi nama doctype "UOM Conversion Detail"/fieldname `uoms` + field `enabled` di UOM master pada source terpasang; hanya UOM enabled + faktor finite > 0; item tanpa baris → list kosong → hanya stock UOM yang dipakai).
   - `item_info` + kunci `uoms` (list di atas) + `last_uom` (dari user default JSON key `production_app_form_order_uom`, DIVALIDASI ULANG terhadap uoms aktual — basi → fallback `null`/frontend pakai stock_uom).
   - `create_form_order`: baris terima `uom` opsional (default stock_uom); validasi: uom == stock_uom ATAU anggota `_valid_uoms`; konversi eksplisit `stock_qty = qty × factor` dan MR row ditulis `uom`, `conversion_factor`, `stock_uom`, `stock_qty`, `qty`; invalid/disabled/faktor-0 → `frappe.throw` zero-write (tanpa fallback factor-1). Dalam transaksi sama: merge peta `{item_code: uom}` ke user default JSON (cap 200 entri, buang terlama).
2. `FormOrderPage.vue`: kolom Satuan → `<select>` opsi `[stock_uom, ...uoms]` (hindari duplikat); nilai default baris = `last_uom || stock_uom` saat item terpilih; ganti item → reset; payload `createFormOrder` ikut kirim `uom` per baris. `form-order.js` + test node: validasi uom (harus anggota opsi), reset saat ganti item, default terakhir.
3. Test backend (suite form_order): `_valid_uoms` normal/entri disabled/faktor-0/kosong; `item_info` uoms+last_uom+fallback basi; create satuan alternatif → MR row `uom`/`conversion_factor`/`stock_qty` benar (DB assertion); uom tak dikenal → tolak zero-write; peta last_uom tersimpan per user (user A ≠ user B) + cap 200.
4. Deploy (docker cp form_order.py + tests, restart backend) + build bundle + hash + marker ("Satuan" select / `last_uom`).

## Task 4 — FU48d — Regresi penuh, smoke browser, dokumentasi, commit

1. Backend 6 suite ×2 fresh worker (form_order bertambah) di kontainer; frontend node --test semua file.
2. Browser smoke (controller, fixture): produksi — menu "Stock Entry" baru, FU47 utuh (tabel → klik baris → form review → kirim → SE nyata via UI), tanpa kontrol gudang; Form Order — pilih satuan alternatif → submit → baris/item sama berikutnya default satuan terakhir; gudang-only → `/production_workspace` redirect `/app`; dual-role tidak redirect. Hard-refresh sekali (SW v2) lalu reload biasa.
3. TASKS.md section K (FU48 Acceptance + Result DONE dengan bukti) + PROJECT_STATE.md entri lengkap (bukti eksekusi, catatan interim, rollback, residu 0, hash bundle, catatan operator reload).
4. Commit tunggal gaya FU di `feat/three-lane-handover` (controller).

## Yang sengaja TIDAK berubah

Endpoint gudang tetap hidup; doc_events/DocPerm/`send_handover`/kanban 3 lane (Cold Storage baca-saja untuk produksi); FormOrderPage produksi; bakery override; Desk fallback; data live. Tanpa app baru; SW hanya bump versi cache.

## Batas interim (didokumentasikan di PROJECT_STATE)

Gudang mencari stok requestable via report Desk (Stock Balance/Batch), bukan FIFO board; MR manual tanpa guard stok/whole-unit/box ala `create_request` (over-request gagal atomik di validasi stok SE; box salah hanya data tampilan); partial SE dari Desk dihitung terkirim penuh oleh derivasi status.

## Rollback

SPA/metadata = revert commit + hapus Property Setter (upgrade) + migrate; redirect = satu blok get_context; server handover tak tersentuh. Bila gate FU48a gagal → strip (Task 2) ditunda sampai bloker beres (retire-after-proven).

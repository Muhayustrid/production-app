# Post-Packing sebagai tahap Work Order — business contract

Status: authorized for implementation 2026-09-14 (explicit user request, sesi SDD subagent-driven).
Sumber keputusan: permintaan user + mockup commit `67fc9dd` (`feat(production): add post-packing workflow and kanban actions`) di `/Users/rotiropi/mockup_production_app`.

Dokumen ini MENGUBAH `IMPLEMENTATION_PLAN.md` untuk poin-poin yang eksplisit bertentangan (lihat §5 Supersede). Aturan lain di dokumen itu tetap berlaku.

## 1. Perubahan bisnis inti

1. Urutan tahap manufaktur menjadi: **Persiapan → Material → Operasi (bila ada) → Pre-Packing → Post-Packing → Finish → Selesai.** Stage key server baru: `post_packing` (UI: `postpacking`), konstanta `STAGE_POST_PACKING`.
2. **Finished Goods Manufacture Stock Entry = `custom_good_qty_postpacking`** (hasil akhir Work Order setelah packing), menggantikan `custom_good_qty_prepacking`. Bahan baku tetap dari planned qty (tidak berubah). One-shot finish, process loss, overproduction allowance, batch handling — semua aturan T03/T04/T11 tidak berubah, hanya sumber angka good yang berpindah.
3. Form Post-Packing (mockup `StagePostPacking.vue`): Good/Reject/Trial (wajib), **Sisa otomatis** = good_pre − good − reject − trial, Jam Packing (Time, wajib), QC Packing (Link User, wajib). Tombol "Simpan & Lanjut ke Finish".
4. ~~Batas atas Post-Packing adalah Good Qty Pre-Packing~~ **FU41 (2026-09-17): cap pre-packing DIHAPUS** — Good/Reject/Trial/Sisa post-packing tidak lagi dibatasi Good Qty Pre-Packing (request user: total boleh melebihi prepacking). Sisa tidak pernah negatif. Batas akhir kuantitas tetap overproduksi allowance native ERPNext yang divalidasi `finish()`.
5. Pre-Packing tetap memakai aturan lama (good > 0 wajib saat konfirmasi; zero reject/trial/sisa valid). Setelah Pre-Packing dikonfirmasi, stage menjadi `post_packing` (bukan langsung `finish`).

## 2. Aturan server (`production_app/api/work_order.py`)

1. `derive_stage`: setelah prepacking confirmed, bila `custom_postpacking_confirmed` belum → `post_packing`; sudah → `finish`. Semua cabang lain tidak berubah.
2. Aksi baru `confirm_postpacking(name, values)` — pola persis `confirm_prepacking`:
   - Permission gate write WO + row lock `for_update` + re-read, guard docstatus/status.
   - Stage guard: hanya `post_packing` atau `finish` (re-edit sebelum manufacture boleh).
   - Validasi SELURUH payload sebelum tulis apa pun: good finite > 0 (**aturan zero-good diperluas: tidak ada manufacture zero-yield**); reject/trial finite ≥ 0; jam packing valid `get_time`; QC Packing User aktif. ~~good ≤ good_pre; good+reject+trial ≤ good_pre~~ (FU41: dihapus — lihat §1.4); sisa dihitung server; Validasi kuantitas setara `confirm_prepacking` (paritas, tidak menambah/mengurangi).
   - Tulis 4 qty postpacking + `custom_jam_packing` + `custom_qc_packing` + `custom_postpacking_confirmed=1` dalam satu `wo.save()` (jalur update-after-submit native).
   - Pre-Packing field tidak pernah disentuh di sini.
3. `confirm_prepacking` stage guard berubah menjadi `(pre_packing, post_packing)` — setelah postpacking confirmed, edit pre-packing DITOLAK (angka post menjadi tidak konsisten); jalur perbaikan = edit postpacking.
4. `finish()`: good = `custom_good_qty_postpacking`; guard `custom_postpacking_confirmed` + good > 0 (pesan error menyebut Post-Packing). Pre-check overproduction, pembelian RM restore, pemilihan baris FG, batch, atomicity — tidak berubah.
5. `wo_list`/`_stage_filters`: filter stage `post_packing` (prepacking_confirmed=1, postpacking_confirmed=0) dan `finish` kini = kedua marker = 1. `LIST_FIELDS` menambah `custom_postpacking_confirmed`.
6. `wo_detail` sudah mengembalikan seluruh field WO (`as_dict`); pastikan payload memuat blok postpacking + marker (tanpa duplikasi query).

## 3. Konflik writer handover (WAJIB diselesaikan)

`api/handover.py` `save_post_packing` saat ini memirror qty/jam/qc postpacking MR ke field Work Order (`WO_MIRROR_FIELDS`). Setelah tahap ini, field itu milik workspace Work Order (ditulis SEBELUM manufacture); mirror handover (ditulis SETELAH manufacture, di-cap oleh qty request) menjadi **competing writer** dan memalsukan "hasil akhir Work Order".

- HAPUS dari `WO_MIRROR_FIELDS`: `custom_good_qty_postpacking`, `custom_reject_qty_postpacking`, `custom_trial_qty_postpacking`, `custom_sisa_qty_postpacking`, `custom_jam_packing`, `custom_qc_packing`.
- PERTAHANKAN mirror `custom_box_1`/`custom_box_2` (keputusan user FU7: box identifier diisi saat serah terima, mirror ke WO).
- Blok postpacking pada MR, cap §4.5, `send_handover` (good dari MR), board — tidak berubah.
- Redesign UI papan Serah Terima versi mockup (dialog "Verifikasi Siap Kirim") DI LUAR scope ini — user meminta fokus Work Order.

## 4. Data & migration (`production_app/upgrade.py`)

- Tambah Custom Field `custom_postpacking_confirmed` (Check, allow_on_submit=1) pada Work Order — pola `custom_prepacking_confirmed` (T05).
- Aktifkan `allow_on_submit` untuk `custom_jam_packing` dan `custom_qc_packing` (dibutuhkan `wo.save()` update-after-submit; hari ini hanya di-write via `db_set` handover yang melewati validasi itu).
- Field qty postpacking sudah ada (Float, allow_on_submit). Snapshot metadata sebelum ubah; apply() dua kali idempoten.

## 5. Supersede terhadap IMPLEMENTATION_PLAN.md

- §1 "Finished goods quantity comes from `custom_good_qty_prepacking`" → **good postpacking** (request user 2026-09-14).
- §1 "Postpacking remains stored on the WO but is not a prerequisite for finishing manufacture" → **postpacking confirmed kini PRASYARAT finish**.
- §6 baris "Postpacking differs | Manufacture still uses prepacking; postpacking values remain intact" → diganti: "Postpacking < Prepacking | Manufacture memakai good postpacking; nilai pre/post tetap utuh; sisa tercatat".
- Baseline §2 "stock_entry_fg_from_wo ... reads good postpacking" — script tetap DISABLED (backup T17); workspace kini server-side memakai postpacking, jadi tidak ada rencana re-enable.

## 6. Frontend SPA (`workspace_frontend/src/`)

- `Workspace.vue`: urutan tahap + komponen `stages/StagePostPacking.vue` baru (adaptasi mockup; QC Packing pakai `LinkInput` User seperti pola existing, bukan teks bebas).
- `StagePacking.vue`: lanjutan setelah simpan → tahap Post-Packing (label tombol/teks menyesuaikan mockup).
- `StageFinish.vue`: ringkasan GANDA Pre-Packing + Post-Packing (Good/Reject/Trial/Sisa + total masing-masing), "Masuk Cold Storage" = good postpacking.
- `store.js`: mapping stage `post_packing`, `confirmPostPacking`, `producedQty` = post ?? pre ?? 0 (fallback DISPLAY hanya untuk WO completed legacy — tampilan jujur, tidak ada backfill).
- `WorkOrderKanban.vue`: lane Post-Packing + drag ke lane berikutnya; `WorkOrderList.vue`: opsi filter stage.
- Build/deploy mengikuti prosedur container yang tercatat (docker cp → yarn build di container → sync assets backend+frontend → verify md5).

## 7. Legacy & kejujuran data

- WO completed lama (postpacking kosong): tampilan memakai fallback pre (display only).
- WO in-flight dengan prepacking confirmed: setelah deploy berada di tahap `post_packing` — operator wajib mengisi Post-Packing sebelum Finish. Tidak ada backfill, tidak ada jal finishes diam-diam.

## 8. Acceptance (ringkas)

1. Validasi penuh confirm_postpacking (good=0, good>pre, total>pre, jam/qc invalid → 0 tulis; nilai lama utuh).
2. Finish memakai good post: SE FG row = good post, process loss = sisa target − good post, batch = good post, RM planned.
3. Stage: prepacking confirmed → post_packing; postpacking confirmed → finish; selesai setelah manufacture.
4. Handover: save_post_packing TIDAK lagi mengubah field postpacking WO; box mirror tetap; send tetap benar.
5. Legacy in-flight → tahap post_packing; completed → tampilan fallback.
6. Suite regresi lama tetap hijau setelah penyesuaian kontrak (37 test wo_transaction diperbarui ke kontrak baru).

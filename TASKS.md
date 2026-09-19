# Work Order implementation tasks

Business contract: `IMPLEMENTATION_PLAN.md`. Progress and evidence: `PROJECT_STATE.md`.

Handover scope: section E (T21–T26) is governed by `HANDOVER_PLAN.md`; the rules there apply to those tasks.
All tasks below are initially TODO. This file describes work; only the state file owns status.

## Execution rules

1. Read the plan and state, inspect current git changes, then choose the first unfinished task whose dependencies are DONE. Work on one task at a time.
2. Before editing, set the active task and status IN_PROGRESS in the state file. Describe the concrete change, not a broad phase.
3. Complete the stated scope and smallest sufficient verification. Reuse preceding checks and extend them; do not create a test framework or duplicate tests per task.
4. Update state with files, exact command/result, and next action. DONE means its acceptance criterion passed. Implemented but untested remains IN_PROGRESS or BLOCKED.
5. When blocked, record the exact error, failed assumption, evidence, and required resolution. Do not weaken validation to advance. A tooling failure is not a business failure.
6. Phase boundaries are proof gates, not automatic permission prompts. Continue after passing them when implementation is authorized. No production deployment, commit, or push is included.

## A. Establish the real transaction contract

### T01 — Confirm environment and ownership

Depends on: none.

Scope: confirm host repo, runtime mount mapping, site, installed apps, applicable instructions, and current git changes. Recheck the relevant custom fields and active hooks/scripts. Read the two previously unread WO scripts. Inspect representative WOs read-only for actual manufacturing configurations; avoid collecting unrelated business data.

Acceptance: state records verified paths and effective behavior, any baseline drift, and which WO configurations need support. No settings or operational documents changed. Verify how local files reach the runtime; never assume the two checkouts are identical.

### T02 — Trace native methods and define the action contract

Depends on: T01.

Scope: trace WO submission, transfer creation, Job Card timers/completion, manufacture validation, loss/status/Production Plan updates, cancellation, and batch creation. Identify real method names/signatures and their permissions/side effects. Define minimal list/detail and action inputs/outputs, derived stage rules, and how confirmed prepacking is identified. Record this compact contract in the state file; avoid a generic endpoint framework.

Acceptance: each proposed action references a verified source path/symbol; authoritative data and stage evidence are identified, including existing submitted WOs. No invented APIs, guessed status writes, or ambiguous completion markers.

### T03 — Prove quantities without operations

Depends on: T02.

Scope: create/reuse a small isolated Frappe integration check. Exercise transfer and manufacture for a planned run with good below, equal to, and above plan within current native allowance. Exercise an above-limit attempt. Use test-only records and clean rollback/teardown; never use operational WOs as write tests.

Acceptance: executed proof shows planned raw material consumption unchanged, correct actual FG/stock/batch quantities, correct process loss/WO/Production Plan results, and over-limit rollback. Report the actual current allowance; if no positive overage is allowed, record the rejection and test an allowed positive overage only on an isolated test site with restored test settings. Never alter operational allowance for a test. No forced Completed or planned-qty rewriting.

### T04 — Prove operations and batch compatibility

Depends on: T03.

Scope: extend the same check to a WO with native Job Cards. Prove start/stop/completed qty and the finish interaction with operation loss/limits. Verify `bakery_manufacturing`'s effective bundle override and the relevant inward rows. Record how actual configurations from T01 are supported or explicitly rejected before mutation.

Acceptance: with-operations flow passes with actual stock/status evidence, and no second batch override is introduced. Common required configurations cannot be deferred silently. If native behavior cannot meet the business rule, report the precise failing layer before building UI.

Gate A: T01–T04 DONE. Transaction correctness must be established before product UI work.

## B. Data and server actions

### T05 — Version required fields and safe migration

Depends on: T04.

Scope: add `custom_box_1`/`custom_box_2` as Float kg fields, migrate `custom_leader_produksi` from Int to Data, and enable only needed after-submit edits. Reuse existing field names and take a narrowly scoped snapshot before changing metadata. Use supported Frappe custom-field/migration mechanisms and an idempotent upgrade.

Acceptance: applying the migration twice is safe; historical values are preserved; decimal box weights and leader names persist. Document rollback limitations: restoring Int after names are entered cannot be lossless, so do not propose a blind downcast. Export only owned/required definitions.

### T06 — Read APIs and derived stage

Depends on: T05.

Scope: permission-filtered, paginated WO list/search/filter and detail data for the existing UI. Derive stage from current WO, submitted transfers, Job Cards, and confirmed prepacking evidence. Add only a minimal missing persisted marker if T02 proved it necessary.

Acceptance: unauthorized WOs are absent; detail access is checked independently; existing submitted/completed/cancelled WOs map correctly after reload. No full-table download, stored duplicate workflow, or fabricated mock defaults.

### T07 — Preparation action

Depends on: T06.

Scope: validate/save adonan, time, temperature, valid penimbang User, crew count, and leader name. Preserve stock-UOM conversion and warehouse defaults verified in T01. Submit a draft WO through native behavior; handle an already-submitted WO without resubmitting. Keep native status separate from UI stage.

Acceptance: valid data persists, invalid input rolls back, and a repeat action does not duplicate Job Cards or resubmit. Leader is name text, not a numeric/User-ID assumption.

### T08 — Material transfer action

Depends on: T07.

Scope: create/submit the native material transfer for the remaining planned requirement, using actual submitted transfer data. Respect verified transfer-against behavior and warehouse/company/stock checks. Do not submit unrelated existing drafts automatically.

Acceptance: materials actually move once; shortage/error leaves no partial action; existing transfers and repeated requests do not cause excess transfer. Next stage comes from refreshed documents.

### T09 — Job Card actions

Depends on: T08.

Scope: native start and stop/complete with quantity; use Job Card IDs, actual timestamps, and native validations. Multiple Job Cards with identical operation labels must stay distinct. Reuse installed timer behavior.

Acceptance: time logs and completed quantity survive reload; repeated start/finish does not duplicate logs; other WO cards cannot be modified through this action. Required unfinished work prevents progression.

### T10 — Prepacking action and Box weights

Depends on: T09.

Scope: save/confirm good/reject/trial/sisa, freezing time, QC User, and optional Box 1/2 kg weights. Good must be finite and >0; other quantities/weights finite and >=0. Follow stock-UOM rules for production quantities, independently of decimal kg weights.

Acceptance: good=0 is rejected before saving any part of the payload, prior stored values remain unchanged, and no finish document is created. Zero reject/trial/sisa are accepted. Decimal kg values persist within field precision and are never converted to PCS or used to alter consumption. Postpacking remains untouched.

### T11 — Finish action

Depends on: T10.

Scope: implement the transaction proven in T03/T04 using confirmed prepacking good, planned materials, and native settings. Select the real FG rows safely. Keep batch handling in its existing owner. Verify all prerequisites again on the server.

Acceptance: the action creates/submits exactly the intended Manufacture, returns document references and refreshed state, and satisfies quantity/status/loss/valuation tests. Good=0, unfinished operations, and over-limit errors create no partial writes. Postpacking cannot override this output.

### T12 — Retry, permissions, and cancellation verification

Depends on: T11.

Scope: exercise server actions with duplicate and concurrent requests, denied permissions, a submission failure, stale form data, and native cancellation. Use transactional locking in native-compatible order; add a narrow document link only if necessary for reliable duplicate detection.

Acceptance: no duplicate transfers/manufacture/time logs, no deadlock introduced by reversed plan/WO locks, no unauthorized writes, and cancellation recomputes stage. Record actual concurrency evidence, not just disabled-button checks. Fix failures in the responsible action and rerun only affected checks.

Gate B: T05–T12 DONE. Backend correctness is independent of browser scripts.

## C. Connect the supplied UI

### T13 — Mount the Work Order frontend

Depends on: T12.

Scope: integrate existing Vue components/styles into the Frappe app using verified session, route, and build mechanisms. Remove handover/simulation dependencies from this release. Do not mutate the source mockup repository or add a second backend/auth system.

Acceptance: authenticated route loads the real app and builds with the existing compatible tooling; no mock WOs, fake transactions, handover page, or broken navigation remains. Record the verified URL and build command.

### T14 — Connect list, filters, and workspace reads

Depends on: T13.

Scope: wire list/detail reads, table/kanban selection, search/filters/pagination, stage review, and WO navigation. Reuse the mockup design and Indonesian wording.

Acceptance: real data agrees across table, kanban, and detail after reload; permission errors, empty lists, and missing WO are handled. Completed-stage review is read-only.

### T15 — Connect preparation, material, and operations

Depends on: T14.

Scope: wire existing panels and kanban dialogs to T07–T09. Use one action path per operation across both views. Show pending/error states and retain useful input after failure.

Acceptance: operator performs preparation, real transfer, and Job Card actions without leaving the workspace. Clicking or dragging only opens/invokes valid actions and cannot bypass server prerequisites.

### T16 — Connect prepacking, kg inputs, and Finish

Depends on: T15.

Scope: wire T10/T11. Add two compact kg inputs to Pre-Packing and show them in review. Keep kg independent of Pack/PCS toggles. Preserve the existing finish confirmation and actual-yield summary.

Acceptance: zero good cannot be saved, server errors retain form input, leader displays as a name, kg decimals round-trip, and Selesai appears only after successful Manufacture. No link to an unimplemented handover page.

Gate C: T13–T16 DONE. Both supported flows work in table/kanban/workspace views.

## D. Cutover and handoff

### T17 — Retire conflicting scripts safely

Depends on: T16.

Scope: back up exact relevant script definitions and enabled state. Replace/retire `stock_entry_fg_from_wo` so native form access cannot restore the postpacking override. Preserve useful UOM/default/filter behavior across native and custom forms. Remove other scripts only when their replacement and relevance are demonstrated.

Acceptance: one effective FG source, no postpacking rewrite on native form load/save, no batch override deletion, no unrelated script removal. Record exact changed script names and restoration procedure. Test the transition locally before deployment; do not leave both incompatible writers active.

### T18 — Acceptance run and final state

Depends on: T17.

Scope: run the plan's acceptance matrix and a desktop/mobile smoke check using the real backend. Check reload, touch/keyboard controls, Pack/PCS, kg, actual documents, and native cancellation. Inspect app and core diffs; summarize exact local migration/build/rollback steps.

Acceptance: every required case has executable or observed evidence; limitations and untested configurations are explicit. No unexplained core edits, operational-data changes, unrelated dependencies, or cloud deployment claim. Update PROJECT_STATE.md to COMPLETE only when all required checks pass. Stop; do not start Stock Entry/handover.

## E. Serah Terima / Stock Entry handover (cold storage → barang jadi)

Business contract: `HANDOVER_PLAN.md`. Same execution rules as above (dependency order, one active task, state-file protocol).

### T21 — Prove the native MR → SE handover path

Depends on: none.

Scope: on isolated test records (test item/batch/warehouses or dedicated test warehouses), execute the full native path: MR (type Material Transfer, set_from_warehouse = Cold Storage lot warehouse, set_warehouse = target, item row with from_warehouse/warehouse), `make_stock_entry` from it, batch set on the SE row (old batch fields vs bundle — whichever the installed v16 actually uses), submit, and verify batch-wise stock movement into the target warehouse plus MR `ordered_qty`/status updates. Exercise MR stop and MR cancel. Verify the bakery bundle override does not interfere with outward transfer rows. Resolve and record the qtyInPack source per item (same one the WO workspace uses) and the Manufacture-SE → batch resolution query for a WO.

Acceptance: executed proof with stock/status evidence and the permission matrix (Stock User vs a bare user); MR fields used by the design confirmed native (`Material Request Item.from_warehouse`); no operational documents touched.

### T22 — Fields, role, permissions, and warehouse-default setting

Depends on: T21.

Scope: extend `upgrade.py` idempotently (snapshot first): Role "Gudang Barang Jadi"; custom DocPerms (MR + MR Item for the new role and Manufacturing User read/write; Work Order/Batch/Stock Entry read for the new role); MR custom fields (`custom_work_order` on item; header boxes + post-packing block + confirmed Check, allow_on_submit); `custom_default_handover_warehouse` on Manufacturing Settings exposed via the existing Pengaturan save/read API.

Acceptance: apply() twice is safe; permission checks behave per matrix (gudang can create/cancel MR, cannot send; Manufacturing User can read/write MR, cannot create/cancel); setting persists and is filtered by write permission; rollback documented.

### T23 — Board read API and derivation

Depends on: T22.

Scope: `production_app/api/handover.py` `handover_board`: lots (batches with stock in Cold Storage warehouses, FIFO by Manufacture SE posting datetime, item/adonan/WO/qtyInPack enrichment, physical/reserved/available math), request lanes derived from MR/SE state, role flags for the session user, target warehouse from the setting.

Acceptance: board matches documents after each mutation performed directly in tests; permission-filtered for each role; legacy/multi-batch WO handled with explicit unsupported flags, not errors or silent omission.

### T24 — Actions: create, cancel, post-packing, send

Depends on: T23.

Scope: `create_request` (validate under WO row lock: available, whole-PCS, boxes text; insert+submit MR), `cancel_request` (only pre-verification; native cancel), `save_post_packing` (caps, sisa auto, QC User valid, write MR custom block + mirror to WO post-packing fields), `send_handover` (lock, re-verify, resolve batch, SE from native builder with qty = good, atomic submit, stop MR when good < requested; return SE refs + refreshed board). Integration tests for the acceptance matrix including racing requests, duplicate send, insufficient stock rollback, and permission denials.

Acceptance: Gate E2 — server correctness independent of the browser; all matrix rows in `HANDOVER_PLAN.md` section 6 covered with executed evidence.

### T25 — Frontend Stock Entry page

Depends on: T24.

Scope: mount the mockup `HandoverBoard.vue` into the existing SPA (route `#/handover`, menu "Stock Entry", mobile bottom nav), strip the role-simulation/fail controls and bind real roles from the server, wire the four dialogs to T24 actions with loading/error/pending states and input retention, role-based navigation (Gudang Barang Jadi: only Stock Entry and lands there; Manufacturing User: Work Orders + Stock Entry). Build and sync assets per the established container procedure.

Acceptance: both test roles complete the loop interactively (request → post-packing → send; cancel path); reload/switch views show server truth; no mock data or simulation controls remain.

### T26 — Acceptance run and final state

Depends on: T25.

Scope: execute the full acceptance matrix and a desk/mobile smoke with a gudang test user and a produksi test user; verify native desk cancel of an SE recomputes the board and the stopped-MR limitation is visible/documented; inspect diffs; record migration/rollback and remaining limitations; clean up all test users/documents/warehouses.

Acceptance: every matrix row has executed or observed evidence; PROJECT_STATE.md updated; stop — further work only on a new request.

## F. Post-Packing sebagai tahap Work Order (FG Manufacture = good postpacking)

Business contract: `POSTPACKING_PLAN.md` (mengubah poin tertentu di IMPLEMENTATION_PLAN.md — lihat §5 di sana). Eksekusi SDD subagent-driven, sesi 2026-09-14. Aturan eksekusi sama (urutan dependensi, satu task aktif, protokol state file).

### T27 — Server: tahap post_packing + confirm_postpacking + finish dari postpacking

Depends on: none (section F).

Scope: `upgrade.py` (marker `custom_postpacking_confirmed` Check allow_on_submit + aktifkan allow_on_submit `custom_jam_packing`/`custom_qc_packing`; snapshot; idempoten). `api/work_order.py`: `STAGE_POST_PACKING`, `derive_stage`, `LIST_FIELDS`+`_stage_filters`, `POSTPACKING_FIELD_MAP`+validasi+aksi `confirm_postpacking` (pola confirm_prepacking + cap good/total ≤ good_pre + sisa server), guard `confirm_prepacking` → `(pre_packing, post_packing)`, `finish()` good = postpacking + marker. Tests: perbarui suite wo_transaction ke kontrak baru + test baru (validasi, cap, stage, finish qty/loss/batch, legacy in-flight, re-edit).

Acceptance: semua test hijau ×2; finish terbukti memakai good postpacking (baris FG SE, process loss, batch); pelanggaran validasi = 0 tulis; apply() 2× idempoten.

### T28 — Handover: hapus mirror qty postpacking WO (competing writer)

Depends on: T27.

Scope: `api/handover.py` — `WO_MIRROR_FIELDS` tinggal box 1/2; docstring diperbarui; blok MR + cap + send + board tidak berubah. Perbarui `test_handover_actions.py` (mirror qty/jam/qc TIDAK terjadi; box tetap mirror). Board tests tetap hijau.

Acceptance: suite handover + regresi hijau ×2; tidak ada lagi writer kedua ke field postpacking WO.

### T29 — Frontend SPA: tahap Post-Packing

Depends on: T27 (kontrak API), T28.

Scope: `Workspace.vue` (urutan + komponen), `stages/StagePostPacking.vue` baru (adaptasi mockup 67fc9dd; QC Packing LinkInput User), `stages/StagePacking.vue` (lanjut ke Post-Packing), `stages/StageFinish.vue` (ringkasan ganda pre+post), `store.js` (stage map, `confirmPostPacking`, producedQty fallback display), `WorkOrderKanban.vue` (lane + dialog), `WorkOrderList.vue` (filter). Build + deploy container + verify md5 bundle.

Acceptance: alur penuh pre→post→finish via HTTP-level loop (pola T25); stage hanya dari server; error menahan input; reload = server truth.

### T30 — Acceptance run + final state section F

Depends on: T29.

Scope: 5 suite fresh ×2; HTTP loop end-to-end (termasuk legacy in-flight → post_packing); browser smoke interaktif oleh controller; update IMPLEMENTATION_PLAN.md (addendum supersede), PROJECT_STATE.md; catat migrasi/rollback; bersihkan fixture test.

Acceptance: setiap baris §8 POSTPACKING_PLAN.md punya bukti eksekusi/observasi; dokumen proyek konsisten; berhenti — pekerjaan lanjutan hanya atas request baru.

## G. Stock Entry kanban WO-centric (serah terima tanpa batch)

Business contract: `STOCKENTRY_KANBAN_PLAN.md` (amendemen alur §4 HANDOVER_PLAN.md — request full qty WO, verifikasi box-only kg, SE qty WO, setting source warehouse). Eksekusi SDD subagent-driven; aturan eksekusi sama.

### T31 — Server: setting source warehouse + box Float kg + board/aksi WO-referenced

Depends on: none (section G).

Scope: `upgrade.py` (field `custom_default_handover_source_warehouse`; migrasi box Data→Float kg di Work Order + Material Request, snapshot `box-kg-pre.json`, NULL-kan nilai lama sebelum alter kolom; spesifikasi field box jadi Float kg). `api/work_order.py` (read/save settings + `handover_source_warehouse`). `api/handover.py` (payload board `source_warehouse`/`produced_qty`/`completed_at`; pool & reservasi batchless pakai source setting dengan keying per-lot WO; `create_request(work_order)` qty = `produced_qty` + guard request aktif ganda; `save_post_packing` box-only kg; `send_handover` qty = diminta, hapus short-close/stop). Tests: 5 suite diperbarui + kasus baru.

Acceptance: apply() 2× idempoten (snapshot tertulis); 5 suite hijau ×2; jalur batch-tracked tidak berubah; tanpa perubahan permission; residu fixture 0. Live apply() dijalankan HANYA setelah kode writer box selesai (urutan R8).

### T32 — Frontend SPA: papan WO-centric + Verifikasi Siap Kirim + deploy

Depends on: T31.

Scope: `WarehouseSettings.vue` (input ke-6 Source Warehouse (Stock Entry)); `store.js` (payload/signature baru); `HandoverBoard.vue` (kartu Hasil WO + Selesai; drag/klik lot = langsung buat request tanpa dialog, error via modal global FU14; dialog Post-Packing diganti "Verifikasi Siap Kirim" box kg saja; dialog kirim tanpa branch stop; hapus dialog request lama). Build + deploy container + md5 5 titik + marker bundle + restart backend. HTTP loop 2 user fixture (batchless + batch item).

Acceptance: loop HTTP hijau end-to-end; bundle terverifikasi; tanpa sisa dialog request/goodQty di bundle; state papan selalu server truth.

### T33 — Acceptance run + final state section G

Depends on: T32.

Scope: 5 suite fresh ×2; browser smoke interaktif controller (pengaturan 6 input; kartu Hasil WO/Selesai; drag request tanpa dialog; verifikasi box; kirim → SE; reload; mobile 390); desk view box Float; update HANDOVER_PLAN.md (addendum), TASKS.md, PROJECT_STATE.md; catat rollback; bersihkan fixture; final whole-branch review.

Acceptance: setiap baris punya bukti eksekusi/observasi; dokumen konsisten; berhenti — pekerjaan lanjutan hanya atas request baru.

## H. Stock Entry three-lane handover

Business contract: `docs/superpowers/specs/2026-09-16-stock-entry-three-lane-handover-design.md`.
Implementation plan: `docs/superpowers/plans/2026-09-16-stock-entry-three-lane-handover.md`.

### T34 — Preflight, baseline, and execution ledger
Depends on: none.
Acceptance: branch/base/runtime verified; five suites pass once before edits; warm board query/time baseline recorded.

### T35 — Server metadata, three-lane derivation, and atomic actions
Depends on: T34.
Acceptance: ordered migration applies twice; server tests cover fields, lanes, validation, cancellation, send, permissions, retry, batch/batchless, and compatibility.

### T36 — Performance and concurrency gate
Depends on: T35.
Acceptance: FU34 query-shape tests pass; concurrent create/send produce at most one document; comparable warm benchmark has no material regression.

### T37 — Three-lane frontend and local asset deployment
Depends on: T36.
Acceptance: frontend tests/build pass; three-lane bundle is deployed and hash-identical at all served points; old Siap/verify path is absent.

### T38 — End-to-end acceptance and handoff
Depends on: T37.
Acceptance: five backend suites pass twice, HTTP and browser matrices pass, fixture residue is zero, docs and rollback are complete.
Result: **DONE (2026-09-17), release-candidate browser closure completed.** Automated/data: 5 suite ×2 fresh worker = 112/112 (7+16+31+10+48), lalu final fix wave + fresh verification = backend **114/114** dan frontend **13/13** + build; hash 5 titik final `index.js` `90c491a4…` / `index.css` `cf180377…`; HTTP matrix alur SPA 43/44 + 1 driver artifact (membership batch diverifikasi offline); native Desk 11/11; race/concurrent create-send tepat 1 dokumen; benchmark final pasca-cleanup **0,1452 s / 30 SQL / 9 071 B** (gate ≤0,1918/≤32 lulus). Browser RC ulang dengan fixture `Z5KYTK`: gudang membuat request nyata dari WO `MFG-WO-2026-03392` → MR `MAT-MR-2026-00336` dengan `6 kg · 6 Pack`; logout/login produksi melalui GUI lalu mengirim request langsung → SE `MAT-STE-2026-07025` dan kartu/dialog Terkirim menampilkan MR/SE/qty/box; screenshot mobile 390×844 membuktikan horizontal lane scroller, bottom nav tidak menutup kartu, dan dialog kirim usable. Drag dan chooser multi-role tidak diulang (jalur click + kedua aksi dasar telah terbukti). Fixture RC kemudian dibersihkan: 16 kategori residu nol dan enam Manufacturing Settings pulih persis. **Post-acceptance (17 Sep):** diinstal di site `frontend` dari commit `6bb38d3` (migrate SUCCESS + `upgrade.apply` ×2 konvergen + restart + ping + metadata 6 field + hash asset 5 titik + guest redirect); insiden fixture stale khusus kontainer (impor ulang oleh migrate mengganti perm inti `Serial and Batch Bundle`/`Job Card` → 10 error suite actions) dibereskan lengkap (backup → hapus folder fixtures kontainer → hapus 20 baris hidup ulang → clear cache → migrate ulang bersih); verifikasi ulang **114/114** di site terinstal; branch + tag di-push ke origin `feat/three-lane-handover` (branch `N` tidak disentuh). Detail di PROJECT_STATE work log 17 Sep.

## I. Form Order + Serah Terima tampilan tabel (rename menu, tabel, Form Order)

Business contract: permintaan user 2026-09-18 + rencana tersetujui (ExitPlanMode sesi yang sama): rename menu "Stock Entry" → "Serah Terima"; papan mendapat tampilan Tabel di samping kanban (antrian kerja per role); menu baru "Form Order" khusus Manufacturing User/Manager — produksi meminta barang dari gudang (MR native type Material Transfer, free-form TANPA `custom_work_order`, gudang asal/tujuan dari input baru Pengaturan). Eksekusi aturan sama (urutan dependensi, satu task aktif, protokol state file). Desain mengikuti konsultasi advisor: modul API baru `form_order.py`, flag role baru `is_manajer_produksi` (is_produksi TIDAK dilebarkan), alur tiga lajur lama tidak berubah.

### FO-1 — Verifikasi data (gate desain)
Depends on: none.
Acceptance: item stock batch vs non-batch, daftar warehouse, DocPerm MR/MR Item/SE saat ini terverifikasi dari DB; keputusan penolakan item batch v1 + daftar DocPerm yang perlu ditambah terkunci.
Result: **DONE (2026-09-18).** 403 item stock, hanya 8 batch-tracked (6 Produk Jadi, 1 Add-on, 1 Peralatan — tidak ada bahan baku) → tolak item batch di v1 aman; DocPerm: Mfg User MR r/w tanpa create/submit/cancel, Mfg Manager tanpa baris MR, Gudang Barang Jadi SE read-only; MR sudah punya `custom_note` Small Text (reuse); warehouse ROPI lengkap (Gudang Bahan Baku/Produksi/WIP/Cold Storage/Barang Jadi). Bukti di PROJECT_STATE work log 18 Sep.

### FO-2 — Server metadata & role
Depends on: FO-1.
Acceptance: upgrade.py idempoten (snapshot-first) menambah `custom_is_form_order` (MR), 2 field gudang Form Order (Manufacturing Settings), DocPerm MR create/submit/cancel utk Manufacturing User & Manufacturing Manager (+MR Item), DocPerm SE utk Gudang Barang Jadi; `_roles()` + `is_manajer_produksi`; settings API +2 field. apply() ×2 konvergen.
Result: **DONE (2026-09-18).** Hak role berubah dinaikkan langsung di DOCPERM_MATRIX (satu sumber, tanpa flip-flop antar apply) + FO_DOCPERMS baru utk Manufacturing Manager; snapshot `snapshots/form-order-pre.json`; apply ×2 "unchanged" semua termasuk `form_order_fields`/`form_order_permissions` (dibuktikan suite + bench execute live).

### FO-3 — API form_order.py
Depends on: FO-2.
Acceptance: `form_order_list` (scope per role, status dari dokumen), `create_form_order` (guard role, validasi item/qty/gudang, insert+submit MR native tanpa ignore_permissions), `cancel_form_order` (owner/manager, guard SE), `fulfill_form_order` (guard gudang, lock+recheck, SE dari builder native, atomik). MR free-form terbukti no-op terhadap mirror WO.
Result: **DONE (2026-09-18).** `production_app/api/form_order.py` — status menunggu/terkirim/batal/draf diturunkan dokumen (reuse `_sent_se_by_mr`), lock baris MR + recheck SE Detail `for_update` (pola T36), `_retry_on_deadlock`, `custom_is_form_order=1` TANPA `custom_work_order`. Bukti: test_form_order.py 7/7 ×2 + smoke HTTP 2 role + mirror no-op (Error Log `method` count stabil).

### FO-4 — Frontend rename + tabel Serah Terima
Depends on: FO-3 (endpoint list form order).
Acceptance: label menu (sidenav+bottom nav+judul+Pengaturan) jadi "Serah Terima"; toggle segmented Kanban|Tabel tersimpan per-user; tabel = antrian request kolom lengkap + aksi per-role; tab "Form Order" di tampilan tabel; kanban tidak berubah; apple-design (segmented control, chip status, sticky header translucent, mobile aman, reduced-motion).
Result: **DONE (2026-09-18).** Toggle reuse `.viewswitch` (konsisten daftar WO) + preferensi `handover.viewMode`; tabel `Antrian Serah Terima` (status chip dari lane/flag, aksi Kirim/Batalkan/Pilih Aksi per role) + tab `Form Order`; header tabel sticky `backdrop-filter` + fallback `prefers-reduced-transparency`; bundle `bd380574…` identik 5 titik; kanban tiga lajur tidak berubah (browser smoke gudang).

### FO-5 — Halaman Form Order
Depends on: FO-3.
Acceptance: route `#/form-order` + menu tampil hanya produksi/manager (server tetap guard); form item multi-baris + tanggal + note; daftar status + batalkan; error menahan isian; state selalu server truth.
Result: **DONE (2026-09-18).** `FormOrderPage.vue` + helper murni `form-order.js` (node:test) + store `formOrderState`/aksi (pola handoverAction); menu `canFormOrder = is_produksi || is_manajer_produksi` (default tersembunyi sampai role termuat — pihak tak berhak tak pernah melihat); browser smoke: form item (LinkInput saran), qty, tanggal default besok, submit aktif hanya saat valid, MR nyata tercipta + riwayat Menunggu + Batalkan.

### FO-6 — Test
Depends on: FO-3 (backend), FO-4/FO-5 (frontend).
Acceptance: suite backend baru test_form_order.py hijau (validasi, scope, cancel guard, anti-dobel/konkurensi, permission, sync no-op) + 5 suite lama ×2; vitest frontend hijau.
Result: **DONE (2026-09-18).** Backend **124/124 ×2 fresh** (form_order 7 + setup 7 + board 16 + actions 34 + native 10 + wo 50) di kontainer; test T22 di-update kontrak FO (prod user siklus MR penuh, gudang SE create, MM row baru); frontend node:test **24/24** (18 lama + 6 baru form-order). Fakta framework: IntegrationTestCase v16 satu transaksi per class (bin assertion DELTA), Error Log title disimpan di kolom `method`.

### FO-7 — Build, deploy, acceptance, dokumentasi
Depends on: FO-6.
Acceptance: deploy sesuai prosedur (docker cp, restart backend, upgrade.apply ×2, vite build, hash bundle terverifikasi, smoke browser dua role); TASKS/PROJECT_STATE lengkap; commit gaya FO; residu fixture 0.
Result: **DONE (2026-09-18).** Deploy: docker cp python (restart backend + ping 200), vite build 1747 modul, bundle `index.js` sha256 `bd380574b796ed1a6ef6a25ceac62d3e15dcc215576b0934a05c6ec8be68ef65` + `index.css` `7892e08e…` identik 5 titik (host public, sites/assets backend & frontend, HTTP 8081) + marker ("Serah Terima"/"Form Order"/`#/form-order`/`is_manajer_produksi`; sisa "Stock Entry" hanya referensi dokumen). HTTP smoke 2 user role nyata: create 200 → MR `MAT-MR-2026-00337`, list scoped, fulfill produksi 403, fulfill gudang ditolak validasi native (valuation rate, atomik 0 SE), cancel owner 200. Browser smoke IAB nyata: produksi → menu Serah Terima+Form Order, halaman Form Order fungsional (buat MR via UI, riwayat Menunggu, Batalkan), tabel Serah Terima + aksi Kirim per-role; gudang → landing #/handover, TANPA menu Form Order, tabel tab FO tombol Proses → dialog konfirmasi → error native tampil dalam dialog (screenshot artifacts); kanban tiga lajur utuh. Catatan IAB: klik semantik timeout (preseden T38) → interaksi via evaluate; insiden redirect logout ke `http://localhost` (port 80) mematikan tab — pulih dengan tab baru + logout fetch CSRF. Cleanup: MR+user fixture dihapus, settings FO kembali NULL, helper kontainer+lokal dihapus, residu **0** semua kategori; snapshot form-order-pre.json disalin ke host.

### FO-8 — Input Form Order jadi grid ala ERPNext (follow-up user)
Depends on: FO-7.
Acceptance: form item berbentuk tabel child-grid ERPNext (kolom Item|Qty|Satuan, "Tambah Baris" di dalam tabel, nama item + satuan tampil di baris); peringatan dini item ber-batch/non-stok inline; server/validasi tidak berubah; test backend + frontend hijau; bundle terverifikasi; smoke browser.
Result: **DONE (2026-09-18).** `api/form_order.py` + `item_info(item_code)` kecil (item_name/stock_uom/penanda, read-gated, None tanpa izin); `FormOrderPage.vue` — field induk (tanggal/catatan) di atas, grid `table.fo-grid` kolom **Item|Qty|Satuan|aksi**, baris **"+ Tambah Baris"** DI DALAM tabel (pola child table ERPNext), nama item via `displayLabel` LinkInput, Satuan terisi otomatis dari `item_info`, error per-baris sebagai sub-row; helper `itemRowProblem` + `ITEM_PROBLEM_TEXT` (murni, ter-test). Test: backend `test_fo_item_info` (info normal/batch/tak-dikenal/tanpa Izin-baca) — suite **8/8 ×2**; frontend **25/25** (1 test baru). Build+deploy: bundle `f21d69343466b7fcb15dc1160dabf46361c6affbb2c96ad1431c16dc4bf1c8e2` identik 5 titik + marker ("Tambah Baris"/"Satuan"/`item_info`). Browser smoke IAB: grid render, pilih item → nama + Satuan "Pcs" otomatis, Tambah Baris → baris 2 + error inline, hapus baris, qty 3 → submit → **MR nyata tercipta via UI** ("Tersimpan", riwayat Menunggu; screenshot artifacts). Cleanup residu 0.

### T39 — Universal count unit (Pack atau Pcs) + rename field bebas satuan
Depends on: T38 (installed RC).
Acceptance: input box mengikuti UOM gudang item (stock UOM faktor 1 eksak ATAU alternatif ber-konversi valid; tanpa konversi tetap ditolak; guard pecahan & jumlah-persis & zero-write tetap); field WO `custom_box_{1,2}_pack` di-rename `_qty` label netral via migrasi snapshot-first + copy + drop kolom; dialog label dinamis per item; suite backend + frontend lulus; migrasi live site konvergen.
Result: **DONE (2026-09-17).** Server `_expected_unit_count` universal + pesan ber-satuan; `create_request(box_1_qty/box_2_qty)`; payload request +`display_uom`; `migrate_box_qty_rename()` di apply() (snapshot `box-qty-rename-pre.json` 5 WO live → copy NULL-only → delete Custom Field + DROP kolom — verified live: kolom `custom_box%` tinggal `_qty`, label "Box 1 (Jumlah)"); apply ×2 "unchanged". Frontend helper universal (`unitProblem`/`expectedUnits`/`unitLabel`) + dialog dinamis + kartu ber-satuan; build `index.js` `8e7c2c87…` identik 5 titik (HTTP 200; marker `box1Qty`/`box_1_qty`/`harus tepat` ada, `box1Pack`/`box_1_pack`/`packProblem` nol). Test: backend **115/115** di site ter-migrate (setup 7 + board 16 + actions 34 — termasuk `test_t39_stock_uom_item_requests_in_pcs` jalur Pcs + `test_t39_invalid_alternate_conversion_rejected_zero_writes` + guard universal — native 10 + wo 48); frontend **14/14** (RED import lama gagal → GREEN, termasuk jalur stock-UOM & satuan alternatif valid). GUI live (sesi read-only user, tanpa submit): dialog WO MFG-WO-2026-02043 item PJ260008 menampilkan **"Box 1 (Pcs)"**, hint "harus tepat 22 Pcs", error konversi HILANG, isian 15+7=22 Pcs → tombol **Buat Request Gudang aktif**; zero-write terbukti (hanya MR legacy 00270; ringkasan WO utuh; screenshot gagal — keterbatasan IAB, bukti DOM terekam). Catatan: WO user masih memegang MR legacy aktif MAT-MR-2026-00270 (15 Sep, tanpa jumlah) — perlu dibatalkan gudang dulu sebelum membuat request baru.

## J. Serah Terima tabel → form review Stock Entry (FU47)

### FU47 — Mode tabel: klik baris → form review Stock Entry (dialog Kirim upgrade)
Depends on: FO-4 (tabel Serah Terima terpasang), T35–T38 (`send_handover` teruji: lock WO, guard anti-dobel, pre-check stok, mapper native `make_mr_stock_entry`, satu transaksi).
Keputusan (user + advisor): satu app production_app (tanpa app gudang terpisah; Desk tetap fallback); dialog review + submit (MR selalu 1 baris — tanpa halaman grid); qty terkunci ke MR (tanpa partial fulfillment). **0 perubahan server** — payload board sudah membawa rute asal→tujuan, batch, box, stok rute (FU29).
Acceptance: (1) baris tabel serah klikabel dengan semantik sama klik kartu kanban (request tanpa flag → produksi `openSendDialog` / gudang `openCancelDialog` / multi `openChooseDialog`; terkirim → dialog baca-saja panel SE; flag draft/cancelled/stopped tidak klikabel; sel aksi `@click.stop`); (2) dialog Kirim menjadi form review Stock Entry eksplisit (sum-row: MR, WO, Item kode+nama, Batch, Rute, Box, Qty terkunci + keterangan, waktu otomatis; callout stok rute FU29; tombol "Buat & Kirim Stock Entry"; panel sukses dipakai juga mode baca-saja baris Terkirim); (3) default view role-aware: sesi produksi tanpa preferensi tersimpan mulai di 'tabel', gudang-only 'kanban', preferensi eksplisit tetap menang; (4) helper murni `handover-se.js` (`rowClickAction` + label rute) + test node:test; seluruh test frontend hijau + 6 suite backend ×2 hijau (regresi, server tak berubah); (5) build + deploy + hash bundle identik 5 titik + marker; (6) smoke browser dua role nyata (produksi: SE nyata tercipta via UI dari klik baris; gudang: default kanban + baris → dialog Batalkan); (7) residu fixture 0; PROJECT_STATE/TASKS lengkap; commit gaya FU.
Result: **DONE (2026-09-18).** 0 perubahan server (md5 `api/` identik host-container; `send_handover` + payload board tak tersentuh — semua field sudah termuat `mapRequest`). Frontend: `HandoverBoard.vue` — `rowAction` (klik baris, semantik `rowClickAction` murni) + `openSentDialog` (baris Terkirim → panel baca-saja "Detail Stock Entry"), dialog Kirim jadi form review (dlg-context MR/Item+kode/Rute `seRouteLabel`/Batch/Box; boxgroup "Stock Entry — Material Transfer" + Qty terkunci + callout FU29; tombol "Buat & Kirim Stock Entry"), default viewMode role-aware (watch roles; preferensi tersimpan menang); helper `handover-se.js` + CSS `tr.rowlink`. Test: frontend node:test **31/31** (25 + 6 baru); backend **125/125 ×2**. Bundle `index.js` sha256 `dcab0ffd9d7de5b47993e7a9a5780abf48a0a033bdb5c8f6696453eb96257fda` + css `ca86086f…` identik 5 titik + marker ("Buat & Kirim Stock Entry"/"Kirim Serah Terima"/"Detail Stock Entry"/`rowlink`). Browser smoke IAB nyata 2 user fixture: gudang default **Kanban** (3 lane) → toggle Tabel → klik baris `MAT-MR-2026-00337` → dialog Batalkan (ditutup tanpa aksi); produksi default **Tabel** → klik baris → form review lengkap (rute FU47 Cold→Target, batch 0C7E999, Box 10 kg·20 Pack, Qty 20 Pack·100 Pcs terkunci) → submit → **SE nyata `MAT-STE-2026-07032` via UI** (docstatus 1 Material Transfer owner produksi, qty 100 Cold→Target, WO mirror Terkirim) → baris chip Terkirim → klik → detail baca-saja tanpa tombol kirim (screenshot artifact). Cleanup rantai fixture penuh (SE×4/MR/WO/BOM/batch/item×2/warehouse×4/user×2/Bin/SLE/sesi/settings dikembalikan) residu **0**; data live utuh. Catatan: teardown live harus cancel/delete dokumen DULU, warehouse terakhir (cancel butuh warehouse ada) + commit per fase; `bench execute` menelan exception asli (fallback eval `NameError`) — debug via runner python langsung.

## K. FU48 — production_app murni produksi (gudang native Desk interim, rename Stock Entry, satuan Form Order)

Business contract: permintaan user 2026-09-19 + rencana advisor-approved `docs/superpowers/plans/2026-09-19-fu48-produksi-only-spa.md`. Gudang TIDAK dibikinkan app — interim pakai Desk/native ERPNext; production_app pure org produksi; endpoint server gudang (`create_request`/`cancel_request`/`fulfill_form_order`) TETAP hidup. Eksekusi SDD subagent-driven; aturan eksekusi sama.

### FU48a — Gate: guard MR yatim + pre-check izin + bukti jalur native gudang
Depends on: FU47.
Acceptance: Property Setter MR Item `custom_work_order` `mandatory_depends_on` scope `material_request_type==="Material Transfer" && !custom_is_form_order` via `upgrade.py` snapshot-first idempoten (apply ×2 konvergen; BUKAN fixtures); bukti runtime scripted fixture terisolasi — guard 4 kasus (MR transfer tanpa WO tanpa FO ditolak; `create_form_order` lolos; `create_request` lolos; tipe MR lain bebas), izin role gudang (Desk access, MR create/cancel, SE create/submit, WO read, custom field permlevel 0), loop native penuh (MR handover manual oleh gudang → WO ringkasan + lane Request papan → `send_handover` produksi → SE; fulfill FO jalur builder Desk → status terkirim; cancel MR native → recompute; over-request → SE gagal atomik zero-write); test backend permanen guard (suite form_order, 5 file suite handover tak diubah); browser Desk walkthrough oleh controller; residu fixture 0.
Result: **DONE (2026-09-19).** Property Setter via `upgrade.py` (snapshot `snapshots/fu48a-mr-guard-pre.json`, apply ×2 konvergen created→unchanged; TANPA fixtures). **Ruling (verifikasi source v16):** `mandatory_depends_on` = **client-side Desk** (dievaluasi save.js/layout/grid_row; prefiks `eval:` wajib — string tanpa prefiks tak pernah aktif) — jalur ancaman aktual (manusia di Desk) tertutup; insert server-side memang bypass (negatif-kontrol jujur: orphan MR submit sukses lalu dibersihkan) dan kedua jalur API memang selalu mengisi field. Bukti scripted fixture FU48A: guard 4 kasus; izin gudang (Desk access, MR create/cancel, SE create/submit, WO read, permlevel 0); loop native penuh — MR manual gudang `MAT-MR-2026-00344` → doc_events sinkron WO "Diminta Gudang" + lane Request → `send_handover` produksi → SE `MAT-STE-2026-07034` (WO Terkirim); FO fulfill jalur builder Desk → terkirim; cancel MR native → lane bersih; over-request → SE gagal atomik native ("Stok batch … hanya 40.0", zero-write). Test permanen +2 di suite form_order (10/10 ×2; 5 file suite handover tak tersentuh). **Walkthrough browser Desk (controller)**: login gudang → form MR baru → Material Transfer + ITEM00208 qty 10 tanpa WO → Save **ditolak "Missing Fields: In Items, Work Order is required in every row"** → WO diisi → draft `MAT-MR-2026-00349` sukses (owner gudang). Temuan: gudang murni tak bisa hapus draft MR (→ ditindak FU48c); dialog "No permission for Company" = artefak user satu-role (gudang produksi memegang Stock User). Teardown residu 0; 36 item bocor suite FO runs 18 Sep ikut terbersihkan (purge `item_name` fix).

### FU48b — Strip UI gudang + rename "Serah Terima" → "Stock Entry" + redirect
Depends on: FU48a (retire-after-proven).
Acceptance: hapus dialog Buat Request/Batalkan, drag/klik-buat-request lot, tab Form Order + Proses + dialog fulfill, chooser multi-role; pertahankan lane Cold Storage baca-saja + kanban/tabel + dialog kirim FU47 + detail Terkirim; `handover-se.js` produksi-only + test; board berhenti memanggil endpoint gudang (store FormOrderPage utuh); rename menu/judul/manifest → "Stock Entry"; redirect gudang-only server-side di `www/production_workspace.py` (tanpa {Mfg User, Mfg Manager, System Manager} & bukan Administrator → `/app`; dual-role lolos); bump SW cache v1→v2; node --test hijau + suite handover 5 file hijau tanpa perubahan; build + deploy + hash 5 titik + marker (hadir "Stock Entry"/"Buat & Kirim Stock Entry"; absen "Buat Request Gudang"/"Proses"/"Pilih Aksi"); verifikasi HTTP redirect 2 role.
Result: **DONE (2026-09-19).** `HandoverBoard.vue` strip total (dialog Buat Request/Batalkan/chooser, drag & drop, tab Form Order + Proses + dialog fulfill; Cold Storage tetap baca-saja, kanban/tabel + dialog kirim FU47 + detail Terkirim utuh); `handover-se.js` produksi-only; store bersih (`createRequest`/`cancelRequest`/`fulfillFormOrder` dihapus — endpoint server tetap hidup); rename menu/judul/Pengaturan/manifest → "Stock Entry"; redirect gudang-only server-side `/app` (301; **diverifikasi curl**: respons membawa `Cache-Control: no-store,no-cache,must-revalidate,max-age=0` — browser tidak meng-cache, aman untuk role-change); SW cache v1→v2. Frontend 30/30 (31 lama − semantik gudang); `git diff` 0 file `api/` berubah; suite sampel handover_actions 34/34; bundle `823e5d0a…` 5 titik + marker (absen "Buat Request Gudang"/"Pilih Aksi"/"Batalkan Request?"/"Serah Terima"); HTTP redirect: gudang 301→`/app`, produksi 200, dual-role 200; user fixture redirect-test dihapus residu 0.

### FU48c — Form Order: dropdown Satuan + default satuan terakhir dipakai
Depends on: FU48b.
Acceptance: `form_order.py` — `_valid_uoms` (child table konversi UOM item; enabled + faktor finite > 0), `item_info` +`uoms`+`last_uom` (user default JSON `production_app_form_order_uom`, divalidasi ulang), `create_form_order` terima `uom` + tulis eksplisit `uom`/`conversion_factor`/`stock_uom`/`stock_qty=qty×factor`, tolak tanpa fallback factor-1 (pola T39), peta last-uom per-user dalam transaksi sama cap 200; `FormOrderPage.vue` kolom Satuan `<select>` default `last_uom || stock_uom`, reset saat ganti item, payload +uom; test backend (uoms/last_uom/fallback basi/alternatif benar di MR row/invalid zero-write/per-user+cap) + test node; deploy + hash + marker.
Result: **DONE (2026-09-19).** `form_order.py` — `_valid_uoms` (child table "UOM Conversion Detail" fieldname `uoms`; UOM `enabled` terverifikasi ada di v16 + faktor finite > 0), `item_info` +`uoms`+`last_uom` (divalidasi ulang vs set valid; basi → null; tanpa izin baca Item tetap None), `create_form_order` terima `uom` (kosong → stock_uom), tolak di luar keanggotaan, tulis eksplisit `uom`/`stock_uom`/`conversion_factor`/`qty`/`stock_qty=qty×factor` (verifikasi source: native `set_missing_item_details` hanya mengisi field None — tulisan eksplisit selamat), zero-write, peta last-uom per-user pasca-submit cap 200 FIFO (verifikasi: `set_user_default` tanpa internal commit — satu transaksi). `upgrade.py` DocPerm MR `delete=1` Gudang Barang Jadi — **Ruling: `if_owner=0`** (if_owner frappe berlaku ke SELURUH baris perm → scope baca MR gudang runtuh, 2 suite gagal; envelope T22 sudah row-wide; snapshot `fu48c-mr-delete-pre.json`, apply ×2 konvergen). `FormOrderPage.vue` select Satuan (default `last_uom || stock_uom`, reset saat ganti item) + helper `form-order.js`. Test: form_order **15** (+5: valid_uoms/item_info/create alternatif+invalid zero-write/regresi tanpa uom/per-user+cap), 6 suite hijau; frontend **33/33**; bundle `f4b17bce…` 5 titik + marker `last_uom`/`fo-uom-select`.

### FU48d — Regresi penuh, smoke browser, dokumentasi, commit
Depends on: FU48c.
Acceptance: backend 6 suite ×2 fresh (form_order bertambah) + frontend node --test semua; browser smoke — produksi (menu baru + FU47 utuh → SE nyata via UI + FO satuan alternatif → default terakhir), gudang-only redirect `/app`, dual-role tidak, hard-refresh sekali (SW v2); TASKS/PROJECT_STATE lengkap (bukti eksekusi, batas interim terdokumentasi, rollback); residu fixture 0; satu commit gaya FU di `feat/three-lane-handover`.
Result: **DONE (2026-09-19).** Regresi **6 suite ×2 semua OK** (form_order 15 / handover_setup 7 / handover_board 16 / handover_actions 34 / handover_native_proof 10 / wo_transaction_proof 50; dua blok output terpotong tail diulang eksplisit OK) + frontend node **33/33**. **Browser smoke controller (fixture FU48A rebuild DRK5T5)**: produksi — menu "Stock Entry" (badge 2), tabel default, klik baris `MAT-MR-2026-00351` → dialog "Kirim Stock Entry" lengkap (MR/Item/Rute Cold→Target/Batch 531C668/Box 10 kg·20 Pack/Qty terkunci 20 Pack·100 Pcs) → submit → **SE nyata `MAT-STE-2026-07039` via UI** (panel Terkirim: SE/MR/Rute/Batch/waktu); Form Order — dropdown Satuan (Pcs/Pack) → **Pack** qty 2 → **MR `MAT-MR-2026-00352` via UI** (DB: uom Pack, conversion_factor 10, stock_qty 20) → pilih item sama lagi → **Satuan default Pack otomatis** (tabDefaultValue user `{"ITEM00239":"Pack"}`); gudang-only buka `/production_workspace` → **mendarat `/desk`** (redirect terbukti di browser); dual-role 200 (HTTP, Task 2). Hard-refresh + reload normal di bawah SW v2. Teardown rebuild+smoke residu **0** (10 kategori, ×2 siklus); data live utuh (MR pending 00269 tidak disentuh). **Final whole-branch review: COMMIT READY** (0 Critical/Important; minor semuanya PARK di ledger .superpowers/sdd/2026-09-19-fu48-produksi-only-spa/progress.md — dead CSS/exports handover-box batch ke edit frontend berikutnya, race info-fetch contained server, dll). Commit tunggal FU-style.

### FU49 — Restyle halaman Stock Entry mengikuti gaya halaman Work Order
Depends on: FU48b (halaman Stock Entry produksi-only).
Acceptance: halaman Stock Entry (kanban + tabel + toolbar) memakai pola layout/kelas gaya halaman Work Order yang sudah ada (reuse CSS — tanpa design system baru): seluruh test frontend hijau; build + deploy + hash 5 titik; verifikasi visual browser (screenshot before/after); tanpa perubahan server; commit gaya FU.
Result: **DONE (2026-09-19).** Tabel Stock Entry (HandoverBoard) memakai pola halaman Work Order via reuse kelas: `.wo-body.se-queue` (kartu kaca radius 14px + blur) + `.wo-thead` (header mini uppercase) + `.wo-row` (hover tint + bar kiri + chevron geser) — CSS baru HANYA `se-queue` modifier (grid 8 kolom Doc/Item/Qty/WO/Batch/Oleh/Status/arrow + area mobile ≤820px, selebihnya reuse). Baris: `c-doc` MR + small SE mono, `wo-prod` nama + kode, `wo-qty` bertumpuk qmain/qsub (`qtyStack` reuse), chip status, chevron HANYA di baris klikabel (Dibatalkan tanpa — konsisten FU47); kolom tombol "Kirim" eksplisit dihapus (klik baris = affordance, semantik FU47 utuh — terbukti dialog "Kirim Stock Entry" + tombol "Buat & Kirim Stock Entry"). Toolbar diurut search → Filter (kanban-only) → viewswitch (pola WO). Empty state `.empty-inset` ("Belum ada request"). Kanban TIDAK disentuh (kartu sudah identik pola WO kanban). Perbaikan lebar kolom pasca-verifikasi: WO 106→134px + Batch 82→128px — DOM `scrollWidth>clientWidth` = **0** untuk semua sel (WO `MFG-WO-2026-03127` penuh; batch `DubaiKK-260814-012`/`DC-260715004` penuh). Test: frontend **33/33**; **0 perubahan server** (JS/CSS only; suite backend tidak diulang, preseden FU42/FU45). Deploy: bundle JS `960f4ceecc533d00` + CSS `ad9b670928ab6f59` identik 4 titik (host build, sites/assets backend & frontend, HTTP 8081) + marker `se-queue-row`; clear-website-cache; backend TIDAK direstart. Browser (IAB, fixture produksi `fu49.tmp`): 7 baris grid 8 kolom, gaya kaca, qty bertumpuk, chevron 6/7 baris, klik baris live `MAT-MR-2026-00269` → dialog review lengkap → Batal (data live utuh); analisis visual screenshot: WO/batch tanpa truncation, chip/chevron/kaca rapi. Screenshot before/after di artifacts sesi. Cleanup: user fixture dihapus, residu User/Sessions/MR/SE/WO = **0**. Commit gaya FU.

### FU50 — Filter tampil di mode Tabel + filter diperluas dan dirapikan
Depends on: FU49 (tabel Stock Entry gaya Work Order).
Acceptance: tombol Filter tampil di KEDUA mode (kanban + tabel); panel filter menyesuaikan mode — tabel: Status (Diminta/Terkirim/Dibatalkan/Dihentikan/Draf) + Item (dinamis dari data) + Tanggal dibuat dari/s.d. (+ Hari ini/Semua tanggal/Hapus semua filter), kanban: tanggal lot masuk (existing); preferensi tersimpan per-user (pola FU18/pola filter halaman WO); helper murni ter-test node; seluruh test frontend hijau; build + deploy + hash 4 titik + marker; verifikasi browser (panel tabel + kanban, filter aktif memfilter baris, badge count, empty state); tanpa perubahan server; commit gaya FU.
Result: **DONE (2026-09-19).** Tombol Filter tampil di KEDUA mode (`v-if` kanban-only dihapus); panel menyesuaikan mode — **Tabel**: Status (Semua/Diminta/Terkirim/Dibatalkan/Dihentikan/Draf — cermin `laneStatusMeta`), Item (dinamis `distinctItems` dari papan, label `kode · nama`, opsi basa tetap tampil pola fProduct WO), Dibuat dari/s.d. (slice createdAt), aksi cepat Hari ini/Semua tanggal, Hapus semua filter; **Kanban**: tanggal lot masuk (FU18, tak berubah). Badge count mode-aware (`activeFilterCount`); filter tabel tersimpan per-user (`seStatus/seItem/seFrom/seTo` di `listPreferences.handover`, restore di apply, watch → save); empty state tabel membedakan "Belum ada request" vs "Tidak ada request untuk filter saat ini. Ubah filter atau kata pencarian." Helper murni baru `handover-filter.js` (`rowStatusKey`/`distinctItems`/`filterSerahRows`/`serahFilterCount`). Test: frontend **39/39** (33 + 6 baru handover-filter); **0 perubahan server** (JS only; CSS tak berubah `ad9b6709…`). Deploy: bundle JS `8404331007999610` identik 4 titik (host, backend, frontend, HTTP) + marker `Semua status` ×2. Browser (IAB, fixture `fu50.tmp` Manufacturing User): tombol Filter VISIBLE di mode Tabel (defect asli terbukti fixed), panel lengkap & rapih; Status=Diminta → **1 baris** (chip Diminta) badge 1 + tombol active; Status=Draf → 0 baris + empty state baru; **reload → filter bertahan** (0 baris + badge 1); Hapus semua filter → 7 baris kembali; Item `PJ260008 · Krim Kopi 700gr` → 1 baris badge 1; mode Kanban → panel `Lot masuk dari/s.d.` (behavior lama utuh), 3 lane render; analisis visual screenshot: struktur panel Status→Item→tanggal→aksi sesuai desain, toolbar cari→Filter→Kanban|Tabel. Cleanup: `fu50.tmp` dihapus, residu User/Sessions/MR = **0**; data live utuh (MR 00269 tidak disentuh). Commit gaya FU.

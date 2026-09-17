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

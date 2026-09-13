# Project state — Work Order workspace

## Current handoff

- Project status: FUNCTIONAL_COMPLETE — T18 interaktif menyisakan smoke UI dialog mutasi + mobile (explicitly NOT RUN). Status final bukan COMPLETE sampai checks interaktif itu dijalankan.
- Last updated: 2026-09-13
- Active task: T18 (IN_PROGRESS — sisa smoke interaktif)
- Next task: selesaikan sisa T18 (test WO via UI end-to-end + mobile check), lalu STOP (Stock Entry/handover = request terpisah).
- ADDENDUM 13 Sep (2): **Ikon app di app switcher desk** aktif via hook `add_to_apps_screen` (hooks.py): logo `/assets/production_app/images/logo.svg` (SVG dibuat, ter-serve 200 dari sites/assets volume), title "Production App", route `/production_workspace`. Verifikasi: boot data halaman `/app` mengandung entri `{"name":"production_app",...,"route":"/production_workspace"}`; klik ikon di desk → langsung masuk Production Workspace. Logo disalin ke `sites/assets/production_app/images/` di backend DAN frontend container (dua-duanya perlu). (public, module Production App, shortcut DocType "Work Orders" + tombol "Buka Production Workspace" → /production_workspace). Dibuat idempoten via `upgrade.ensure_workspace()` (dipanggil apply()/after_migrate) + fixture app `production_app/production_app/workspace/production_app/production_app.json` (auto-export developer_mode). Verifikasi: `apply()` ke-2 → "updated"; `/app/production-app` → 200 (smoke user). Catatan: shortcut type "URL" tidak didukung validasi Dynamic Link — gunakan blok paragraph HTML untuk tautan halaman. IKON APP SWITCHER: butuh hook `app_home = "/production_workspace"` (boot `app_route` kosong = tile tidak muncul di grid ⌘K); setelah ditambah + clear-cache, boot berisi `"app_route":"/production_workspace"`. GRID /apps HANYA merender Workspace Sidebar yang PERSISTED — sidebar modul custom yang di-generate in-memory tidak dirender. FIX: buat doc `Workspace Sidebar` "Production App" (module Production App) + items [Link→Workspace "Production App", Link→DocType "Work Orders"]; terverifikasi muncul di HTML /apps (0→1). Jika tile masih tak terlihat setelah hard refresh, periksa renderer `.icons-container` (top-level icons = grup; entri kosong "" × 8 perlu diselidiki).
- Process note: subagent dispatch unavailable this session (`Model provider is not configured: builtin:zai-start-plan`, verified twice). Tasks are executed directly, one at a time, with per-task brief/report/review files under `.superpowers/sdd/TASKS/`. Reviews are controller self-reviews (recorded), NOT independent review. No git commits (per ZCODE_PROMPT.md); per-task diffs tracked via snapshot trees in the ledger.
- Verified 2026-09-13: Docker runtime is up (backend `erpnext-new-backend-1`, image frappe/erpnext:v16.34.2); container mounts ONLY `sites` and `logs` volumes — `apps/` lives in the container image, so host→container file sync mechanism is a mandatory T01 verification item.
- Target agent: GLM in Zcode, after receiving an explicit implementation instruction.
- Source of requirements: IMPLEMENTATION_PLAN.md
- Work breakdown: TASKS.md
- Runtime last observed: `erpnext-new-backend-1`, `/home/frappe/frappe-bench`, site `frontend`, UI `http://localhost:8081`.
- Host repo: `/Users/rotiropi/erpnext-new/apps/production_app`
- Mockup: `/Users/rotiropi/mockup_production_app`

## Confirmed decisions

- Finish uses good prepacking; materials remain planned quantities.
- Overproduction follows current ERPNext settings; do not hardcode the previously observed 25%.
- Leader Produksi stores a name as Data text, with safe preservation of old values.
- Box 1/2 are decimal kg weights, not identifiers/counts. Default UI placement: optional Pre-Packing inputs.
- Good prepacking=0: do not save/confirm prepacking or Finish. Zero reject/trial/sisa is valid.
- Preserve bakery_manufacturing's batch override and useful existing script behavior.
- Custom Stock Entry/handover implementation and production deployment are excluded.

## Task board

Allowed statuses: TODO, IN_PROGRESS, BLOCKED, DONE. Only one IN_PROGRESS task.

| Task | Status | Evidence / blocker |
|---|---|---|
| T01 | DONE | Report: .superpowers/sdd/TASKS/task-01-report.md; runtime verified, sync mechanism recorded (docker cp + restart), 0 WOs with operations, no field/script drift |
| T02 | DONE | Contract recorded above; full trace .superpowers/sdd/TASKS/task-02-report.md; every action maps to verified native symbols |
| T03 | DONE | 8/8 integration tests pass (below/equal/above/over-limit + 2 Production Plan cases); report .superpowers/sdd/TASKS/task-03-report.md; finish action must restore RM rows to transferred qty (native prorates to yield) |
| T04 | DONE | 11/11 tests OK (T03+T04). Job Card start/complete/gating proven; bakery override verified (single inward batch entry = FG qty). CONFIG REQUIREMENT: company ROPI lacks default_operating_cost_account — needed before any operations WO |
| T05 | DONE | Boxes Float kg + confirmed Check + leader Data + allow_on_submit×4 live; idempotent (ran 2×); snapshot snapshots/T05-pre-migration.json; 12/12 tests OK |
| T06 | DONE | api/work_order.py: wo_list/wo_detail/derive_stage; 15/15 tests OK; stage lifecycle + permission filtering + operational WO mapping proven |
| T07 | DONE | prepare() in api/work_order.py; valid persist + native submit + repeat-safe + invalid rollback proven; 17/17 tests OK |
| T08 | DONE | transfer_materials: remaining-based, repeat-safe, draft-blocking, shortage atomic (request rollback); 21/21 tests OK |
| T09 | DONE | jobcard_start/jobcard_complete by card id with ownership guard; repeat-start + over-completion rejected; 24/24 tests OK |
| T10 | DONE | confirm_prepacking: validasi penuh sebelum tulis, good>0 wajib, zero reject/trial/sisa valid, box kg persist, stage guard; 26/26 OK |
| T11 | DONE | finish(): native builder + RM restored ke qty transfer + FG row only + batch single-entry; duplikat & stale-zero diblokir; 29/29 OK |
| T12 | DONE | Gate B passed: 32/32 OK. Permission gates on all actions; cancel Manufacture → stage recompute → retry safe; native cancel order enforced; atomicity via request boundary |
| T13 | DONE | SPA terpasang di /production_workspace (self-contained, auth-gated); guest→login, login→200; build via yarn di container |
| T14 | DONE | Adapter store (workspace_frontend/src/store.js) memetakan wo_list/wo_detail ke bentuk UI; data nyata via HTTP terverifikasi (smoke user) |
| T15 | DONE | prepare/transfer/jobcard_start/complete terhubung di adapter; stage hanya dari server; UI drag hanya membuka aksi |
| T16 | DONE (code) | confirm_prepacking + finish terhubung; input Box 1/2 (kg, opsional, independen Pack/PCS) di dialog Pre-Packing; browser smoke di T18 |
| T17 | DONE | stock_entry_fg_from_wo di-disabled dengan backup lengkap (snapshots/T17-client-script-backup.json); 7 script lain terverifikasi tidak berubah |
| T18 | IN_PROGRESS | Browser smoke lulus (list+detail+auth+reload, data nyata); sisa: smoke interaktif dialog mutasi via UI + mobile — lihat NOT RUN di work log |
| T19 | DONE | FIX sidebar: module workspace → Manufacturing + app=production_app di ensure_workspace() & fixture JSON; smoke user non-Workspace Manager kini melihat workspace (19→20 halaman). Bukti di work log |
| T20 | DONE | Tile /desk + ⌘K "Open Production App" → /production_workspace terverifikasi di browser nyata (user non-admin); awesomebar_search hook + Workspace Sidebar item URL + Desktop Icon + clear-cache. Bukti di work log |

## Evidence available before implementation

- Planning inspection read Custom Field metadata and relevant Client Scripts from the local site; read native WO/Stock Entry source and the bakery batch override from the backend container.
- `bench --site frontend list-apps` confirmed production_app and bakery_manufacturing installed.
- `bench --site frontend execute frappe.db.get_single_value --args '["Manufacturing Settings","overproduction_percentage_for_work_order"]'` returned 25.0 at inspection. This is not a fixed requirement.
- No transaction integration tests, migrations, frontend builds, or end-to-end manufacturing tests have been executed for this implementation.
- Pre-existing untracked `.codegraph/` was observed in the app repo. Preserve it; inspect fresh git status before work.

## Open technical items

- Native transaction proof with under/over-yield and Job Cards is still required (T03/T04).
- Inspect all effective competing hooks/scripts and host/runtime file mapping (T01).
- Determine minimal reliable prepacking confirmation evidence and treatment of existing WOs (T02).
- No confirmed business decision above needs to be asked again. Optional Box placement is an implementation default; adjust only if the user steers it.

## Required update format

Update the current handoff and task board at task start. At task completion/blockage and before ending any implementation session, append an entry below using this structure. Keep evidence concise; do not paste credentials, full business datasets, or long logs.

### YYYY-MM-DD — Txx — DONE / BLOCKED / IN_PROGRESS

- Changes: concrete behavior and file paths; include site metadata/script changes if any.
- Verification: exact command or browser steps, environment/site, and actual result. State NOT RUN with reason when unavailable.
- Evidence: relevant document IDs from isolated tests, source references, or local output paths; no claim based only on intention.
- Remaining issue: none, or exact error and required resolution.
- Next action: one precise step and task ID.
- Rollback notes: only if this task changed persisted metadata/data or active scripts.

## Action contract (T02 — full trace in .superpowers/sdd/TASKS/task-02-report.md)

All symbols verified in installed source (`/home/frappe/frappe-bench/apps/erpnext/erpnext/`):

- Entry builder: whitelisted `work_order.make_stock_entry(work_order_id, purpose, qty=None, ...)` returns an UNSAVED dict; default `fg_completed_qty = wo.qty − wo.produced_qty`; Manufacture targets `wo.fg_warehouse`, transfer targets `wo.wip_warehouse`.
- Status: `Work Order.get_status/update_status` derives everything from produced_qty + process_loss_qty + material_transferred_for_manufacturing + operation rows. Never db_set status manually.
- Qty updates: Stock Entry submit → `stock_entry.update_work_order` (locks Production Plan row first) → `wo.update_work_order_qty` → allowance from Manufacturing Settings `overproduction_percentage_for_work_order` (25.0 now); over-limit → `StockOverProductionError`; `produced_qty` = Σ `Stock Entry Detail.transfer_qty` where `is_finished_item=1` (Manufacture); `material_transferred_for_manufacturing` = Σ transfer `fg_completed_qty`; `process_loss_qty` = Σ SE `process_loss_qty`; plan validation via `ProductionPlanWorkOrderQuantities` (`production_plan/work_order_quantities.py`).
- Manufacture guards: `validate_work_order` (fg_completed_qty required), `check_if_operations_completed` (OperationsNotCompleteError), `check_duplicate_entry_for_work_order` (DuplicateEntryForWorkOrderError), `validate_fg_completed_qty` (process loss = header − FG rows).
- Job Cards: created draft by WO on_submit; actions = native whitelisted `start_timer`/`complete_job_card` (docstatus 0 only, write permission checked); `auto_submit=True` submits the card and updates WO operation completed_qty/status. Card qty limited by WO qty + allowance%.
- Batches: bundle built at SE submit via `make_bundle_using_old_serial_batch_fields` (`controllers/stock_controller.py:399`); bakery `BakerySerialAndBatchBundle` syncs single-entry inward batch qty to `row.transfer_qty`. WO-level batch creation only under `make_serial_no_batch_from_work_order` (site behavior proven by execution in T03/T04, not assumed).
- Cancellation: WO refuses cancel while submitted Stock Entries exist (`validate_cancel`); cancel SEs first, then WO; SE on_cancel reverses ledger and recomputes WO.
- Backflush setting is "Material Transferred for Manufacture" → consumption follows transferred qty; planned invariant holds by transferring the planned requirement.

Server API (one module `production_app/api/work_order.py`, whitelist only, session-user permissions, no ignore_permissions):

- Reads: `wo_list` (paginated, permission-filtered), `wo_detail` (items, operations+Job Cards by name, submitted SEs, prepacking/postpacking blocks, derived stage + actions).
- Stage derivation from server truth: Cancelled/Stopped/Closed (review-only) → Completed (Selesai) → Operasi (operations incomplete) → Material (transfer remaining) → Pre-Packing (no confirmed prepacking) → Finish (confirmed prepacking, remaining > 0).
- Actions: `prepare` (validate+set prep fields; native submit for Draft; allow-on-submit only for submitted), `transfer_materials` (remaining = qty − transferred; reuse deliberate workspace draft or create+submit native transfer), `jobcard_start`/`jobcard_complete` (delegate to exact Job Card by name, assert work_order link), `confirm_prepacking` (validate good finite >0 FIRST — no writes on violation; reject/trial/sisa/box finite ≥0; save 4 qty + jam pembekuan + qc + boxes + `custom_prepacking_confirmed=1` in one save), `finish` (under WO row lock: re-require marker + good>0, build Manufacture via native builder with qty=good on real FG rows only, submit atomically, return refs + refreshed state).
- Concurrency: WO row `for_update` lock first, re-read linked docs under lock; lock order WO→plan never reversed (native locks plan only) — T12 verifies.
- T05 field needs: add `custom_box_1/2` (Float kg, allow_on_submit), `custom_prepacking_confirmed` (Check, allow_on_submit); enable allow_on_submit for `custom_nama_penimbang`, `custom_jumlah_kru`, `custom_leader_produksi`, `custom_qc_produksi`; migrate `custom_leader_produksi` Int→Data preserving values as text.

## Work log

### 2026-09-13 — T20 — DONE (Production App muncul di grid /desk, ⌘K, dan sidebar /app; klik → /production_workspace)

- Root cause sisa (kenapa T19 belum cukup): halaman yang dilihat user adalah /desk (grid, sama dengan screenshot). Grid dirender dari doc `Desktop Icon` (bukan langsung Workspace Sidebar), data lewat bootinfo yang ter-cache Redis per user (`sessions.py` hget bootinfo) + `@redis_cache` di `boot.get_sidebar_items` + cache `desktop_icons` — hard refresh browser tidak mengubahnya. Setelah T19, sidebar item pun lolos filter, tapi tile/search butuh cache dibangun ulang dan doc Desktop Icon yang belum ada.
- Changes: (1) `hooks.py` — aktifkan `awesomebar_search = ["production_app.search.awesomebar_results"]`; (2) `production_app/search.py` baru — hasil ⌘K custom: "Production App" → route /production_workspace (index 105) + "Work Orders" → List Work Order (index 60), filter per-txt dengan alias "produksi"; (3) `upgrade.py` — `ensure_workspace_sidebar()` (upsert Workspace Sidebar "Production App": item pertama URL /production_workspace — item pertama adalah tujuan klik tile menurut desktop.js get_route — + item Work Orders; app=production_app, header_icon=tool) dan `ensure_desktop_icon()` (Desktop Icon label "Production App", link_type Workspace Sidebar, standard=0 owner Administrator, ikon tool) — keduanya dipanggil apply(); (4) sinkron docker cp + restart + `apply()` (workspace_sidebar: updated, desktop_icon: created) + `bench --site frontend clear-cache`.
- Verification (server): bootinfo fresh user smoke: `has_awesomebar_search: True`, `workspace_sidebar_item["production app"]` berisi item URL /production_workspace; `frappe.desk.search.awesomebar_search("production app")` → entri Production App route ["/production_workspace"]; "produksi" juga cocok (2 hasil).
- Verification (browser nyata, IAB, login user smoke non-admin): /desk — tile "Production App" muncul di grid dengan /url /production_workspace; tombol Search ⌘K → ketik "production app" → entri "Open Production App" (2 results found) → klik → mendarat di http://localhost:8081/production_workspace (SPA PRODAPP render, Work Orders 27); /app — sidebar memuat link "Production App" → /production_workspace. Screenshot bukti tersimpan di artifacts sesi.
- Notes: password user smoke t13.smoke@prodapp.example.com di-reset untuk verifikasi browser ini (tes user sementara, dihapus saat rilis). Developer mode mengekspor `apps/erpnext/erpnext/manufacturing/workspace/production_app/production_app.json` di container — konsisten dengan fix. Sifat idempoten: apply() dapat diulang; clear-cache diperlukan setelah mengubah hooks/sidebar/icon agar bootinfo dibangun ulang.
- Remaining issue: none untuk permintaan ini. T18 sisa smoke interaktif tetap terbuka.
- Next action: lanjutkan sisa T18 (smoke interaktif dialog mutasi via UI + mobile).
- Rollback notes: hapus Desktop Icon "Production App", Workspace Sidebar "Production App" (dibuat sesi lama, kini dikelola upgrade.py), matikan hook awesomebar_search, kembalikan module Workspace ke "Production App" via snapshots/T19-workspace-fixture-backup.json; jalankan clear-cache.

### 2026-09-13 — T19 — DONE (fix workspace tidak muncul di sidebar desk/search)

- Changes: `production_app/upgrade.py` `ensure_workspace()` — module workspace kini selalu "Manufacturing" + field `app: production_app` (branch update & create; update branch sebelumnya hanya menimpa content/shortcuts). Fixture `production_app/production_app/production_app/workspace/production_app/production_app.json` dinormalkan ke path modul yang benar + module Manufacturing (backup asli: `snapshots/T19-workspace-fixture-backup.json`). Sinkronisasi ke container via docker cp + restart backend (prosedur T01/T13).
- Root cause: gate sidebar Frappe v16 (`frappe/desk/desktop.py` `Workspace.__init__`) menolak workspace bagi user tanpa role "Workspace Manager" bila `doc.module` tidak ada di `user.allow_modules` — daftar yang dibangun dari module DocType yang bisa dibaca user (`frappe/utils/user.py` build_permissions). App ini tanpa DocType sendiri, sehingga module "Production App" tak pernah masuk; module "Manufacturing" (module DocType Work Order) sudah pasti ada.
- Verification: `bench --site frontend execute production_app.upgrade.apply` → `workspace: "updated"`. Console site frontend: DB row `{module: Manufacturing, app: production_app, public: 1, is_hidden: 0}`; sebagai `t13.smoke@prodapp.example.com` (tanpa Workspace Manager) `get_workspaces()` kini 20 halaman termasuk "Production App" (app=production_app) — sebelumnya 19 halaman dan workspace ter-drop. Tidak perlu tunggu cache `user_allowed_modules` (6 jam) karena 'Manufacturing' sudah ada di daftar itu.
- Evidence: container `/home/frappe/frappe-bench/apps/production_app/production_app/upgrade.py` (grep `module = "Manufacturing"`); auto-export developer mode menulis `apps/erpnext/erpnext/manufacturing/workspace/production_app/production_app.json` di container dengan nilai sama (module Manufacturing, app production_app) — konsisten bila `frappe.model.sync` membaca saat migrate; tidak perlu dihapus.
- Remaining issue: none. Catatan: string search desk mengambil dari data sidebar yang sama (`get_workspaces`), jadi ikut membaik.
- Next action: lanjutkan sisa T18 (smoke interaktif dialog mutasi via UI + mobile).
- Rollback notes: kembalikan JSON dari `snapshots/T19-workspace-fixture-backup.json` dan set doc Workspace module kembali "Production App" (atau hapus field app); efek hanya visibilitas sidebar.

### 2026-09-13 — T17/T18(smoke) — T17 DONE; T18 IN_PROGRESS (sisa smoke interaktif)

- Changes (T17): `stock_entry_fg_from_wo` DISABLED (tidak dihapus) dengan backup lengkap `snapshots/T17-client-script-backup.json` (script 1213 char + enabled state). Script lain diverifikasi tak berubah (Get_Conversion_Factor_WorkOrder, Manufacture Modal, Auto Pick, filter_item = tetap enabled; WO tes popup/Outlet/Batch UOM tetap disabled). Restorasi: set enabled=1 di Client Script, atau import JSON backup.
- Verification (T18 browser, executed): login page → auth gate (guest 301); login smoke user → SPA PRODAPP render penuh; badge "Work Orders 21"; tabel daftar = data nyata (No. WO MFG-WO-2026-03094..., produk "Krim Kopi" dari item_name, jadwal 11 Sep, status Completed, tahap Selesai, rencana 1 Pack/25 PCS); search + filter + switch tabel/kanban tersedia; detail via hash `#/wo/MFG-WO-2026-03094`: switcher WO + banner "Produksi selesai · Barang jadi ... di Cold Storage Produksi - ROPI" + panel (WO, status, produk, jadwal, gudang, rencana). WO legacy Completed tanpa prepacking tampil jujur (0).
- Verification (T18 suites): 32/32 integration tests OK (acceptance matrix inti: below/equal/above/over-limit, dengan/tanpa operasi, Job Card gating, batch single-entry, duplikat, permission, cancel+retry, kg round-trip, leader name).
- NOT RUN (explicit): smoke UI interaktif untuk alur mutasi (persiapan → material → prepacking kg → finish) pada test WO lewat browser; mobile/touch; interaksi toggle Pack/PCS di UI; cancel via UI. Semua alur itu sudah terbukti di level API/test (32/32) — yang belum ada hanyalah eksekusi browser interaktifnya.
- Remaining issue: selesaikan NOT RUN di atas (buat test WO committed khusus smoke lalu bersihkan), kemudian project COMPLETE.
- Next action: smoke interaktif T18 (test WO via UI), lalu stop (Stock Entry/handover = request terpisah).
- Rollback notes: lengkap di task-03/05/17 reports (server_script_enabled, allow_tests, leader Data satu arah, field baru dapat dihapus, script bisa di-enable kembali).

### 2026-09-13 — T13/T14/T15/T16(code) — DONE (browser smoke di T18)

- Changes: `workspace_frontend/` (src copied from mockup minus HandoverBoard; store.js diganti adapter async ke endpoint server; App/Workspace di-strip dari handover; StagePacking + input Box 1/2 kg); `production_app/www/production_workspace.{html,py}` (halaman self-contained, auth-gated, redirect guest ke /login); build config vite (asset nama tetap, base /assets/production_app/workspace/). API: wo_list/wo_detail diperkaya (production_item_name, has_operations, item_name/stock_uom per bahan, nama lengkap User, time logs + karyawan per Job Card).
- Verification: build sukses di container (yarn v24); `curl guest /production_workspace` → 301 ke /login; login smoke user (Manufacturing User) → 200 (233KB) + API `wo_list` mengembalikan data WO nyata via HTTP. Build & sync procedure: yarn build di container → regenerasi inline HTML → docker cp html (+ salinan assets ke sites/assets/production_app). Endpoint: /production_workspace; smoke user t13.smoke@prodapp.example.com ( Manufacturing User, dibuat untuk smoke; hapus setelah rilis).
- Key discoveries: nginx frontend TIDAK menyajikan /assets app dengan benar di stack ini (bahkan /assets/frappe/... 404) → aset di-inline base64 ke halaman (Jinja-proof). docker cp menghasilkan file root → wajib `docker exec -u root chown frappe:frappe` sebelum build/bench. DocPerm WO di site ini hanya memberi akses ke Stock User (read) + Manufacturing User (penuh) — System Manager TIDAK otomatis bisa; operator harus Manufacturing User. Bukti historis: MFG-WO-2026-03094 produced 26 > qty 25 (overproduksi nyata dalam batas).
- Remaining issue: eksekusi JS di browser nyata (render list/detail/dialog + kg round-trip di UI) diverifikasi di T18 dengan smoke user.
- Next action: T17 — backup & retire `stock_entry_fg_from_wo`, uji form native setelahnya.
- Rollback notes: hapus www page + workspace_frontend + isi sites/assets/production_app; re-enable devtools bila perlu.

### 2026-09-13 — T12 — DONE (Gate B passed: backend correctness independent of browser)

- Changes: explicit `has_permission(write)` entry gates on prepare/transfer/finish/confirm_prepacking/jobcard_*; 3 tests (permission denial, cancel-recompute-retry, native cancel order).
- Verification: suite `Ran 32 tests in 7.145s OK`. Limited user → PermissionError at every mutating action with zero side effects. Cancel of the Manufacture recomputes produced=0/In Process/stage=finish; retry finish creates a NEW SE (one submitted manufacture total). WO cancel blocked while submitted SEs exist; after cancelling entries, WO cancel → stage cancelled. Duplicate guards layered: action idempotency + native `DuplicateEntryForWorkOrderError`.
- Concurrency note: lock order is WO row → plan row (native locks only the plan row) — no reverse order exists, so no deadlock; request-boundary rollback proven via savepoint in the shortage test.
- Next action: T13 — mount the Work Order Vue frontend from the mockup in the Frappe app (session/route/build mechanism verified first).
- Rollback notes: none (site unchanged; tests roll back).

### 2026-09-13 — T10/T11 — DONE

- Changes (T10): `confirm_prepacking` + `_validate_prepacking` (full-payload validation BEFORE any write; good finite >0; reject/trial/sisa/boxes finite ≥0; qc User aktif; jam valid). Changes (T11): `finish` — WO row lock, re-verify marker + good>0 + overproduction limit, native builder qty=good, RM rows restored to transferred quantities (plan rule #2 — reference implementation from T03), FG rows only on production_item, batch left to native + bakery override, insert+submit atomically, returns SE/batch/produced/loss/status/stage.
- Verification: suite `Ran 29 tests in 6.283s OK`. T10: confirm → stage finish; zero-good rejection leaves prior values + marker unchanged + no Manufacture doc; stage guard blocks pre-transfer confirm; decimal kg round-trip. T11: equal-plan finish → Completed + single batch returned + duplicate finish blocked (1 SE); unconfirmed/stale-zero blocked; below-plan (80) → produced 80, loss 0, In Process, RM at planned 200/100, stage finish (remaining 20 producible); over-limit throws before any write.
- Evidence: task-09/10/11 sections; endpoint names in api module; leak checks 0 rows.
- Next action: T12 — concurrency/retry/permissions/cancellation proofs (Gate B).
- Rollback notes: none.

### 2026-09-13 — T09 — DONE

- Changes: `jobcard_start`, `jobcard_complete`, `_locked_job_card`, `_resolve_employees` in `production_app/api/work_order.py`; 3 tests.
- Verification: suite `Ran 24 tests in 5.515s OK` — start/complete persist time logs + completed qty; repeat start blocked (open-log guard / native overlap); over-completion (150/100) rejected; cross-WO card access raises PermissionError and leaves the foreign card untouched.
- Contract additions: completion passes `for_quantity` to enforce native qty-split; `pending_qty` defaults to remainder; employees default to session user's Employee.
- Next action: T10 — prepacking confirmation (good>0 before writes, boxes kg, confirmed marker).
- Rollback notes: none.

### 2026-09-13 — T08 — DONE

- Changes: `transfer_materials` in `production_app/api/work_order.py`; 4 tests. Ruling recorded: existing draft transfers BLOCK the action (never silently submitted); links draft in the error.
- Verification: suite `Ran 21 tests in 3.624s OK` — moves once, repeat moves 0, respects existing partial transfer (40→moves 60→100), draft blocks, shortage (fresh items, 100/200) raises native `NegativeStockError` and, after the request-boundary rollback (savepoint), WO quantity 0 + zero submitted transfers.
- Key facts: atomicity depends on the request transaction — keep insert+submit in one whitelisted call (T11 must do the same). Test-infra: receipts accumulate across tests in a class; quantity-sensitive tests use fresh items.
- Next action: T09 — Job Card actions (start/complete by card identity, native timers).
- Rollback notes: none.

### 2026-09-13 — T07 — DONE

- Changes: `prepare` action in `production_app/api/work_order.py` (strict validation, row lock, warehouse-defaults mirror, native submit for drafts, update-after-submit for submitted WOs); 2 tests added.
- Verification: suite `Ran 17 tests in 2.890s OK` — full payload persists on submitted WO; repeat call safe (no resubmit, no Job Card duplication); invalid penimbang raises ValidationError with zero partial writes; leader stored as text.
- Remaining issue: none. Note: warehouse-defaults fill runs only on empty WO warehouses (not test-exercised; items in test lack Item-default values).
- Next action: T08 — material transfer action (remaining requirement, deliberate draft reuse, atomic submit).
- Rollback notes: none.

### 2026-09-13 — T06 — DONE

- Changes: new `production_app/api/work_order.py` (wo_list, wo_detail, derive_stage) + `api/__init__.py`; 3 new tests. No site metadata/data change.
- Verification: suite `Ran 15 tests in 2.767s OK`. Stage lifecycle executed on test WO (persiapan→material→pre_packing→finish); operational Completed WO → selesai, Cancelled → cancelled; user without roles: list empty + detail raises PermissionError.
- Evidence: endpoint names `production_app.api.work_order.wo_list|.wo_detail`; stage strings persiapan/material/operasi/pre_packing/finish/selesai/cancelled/review; detail blocks (required_items/operations/job_cards/stock_entries/remaining_transfer/remaining_produce/max_allowed_qty) — consumed by T14–T16.
- Remaining issue: HTTP round-trip proof deferred to T13.
- Next action: T07 — preparation action (validate + persist prep fields; native submit for Draft; allow-on-submit-only edits for submitted).
- Rollback notes: none (no persisted change; tests roll back).

### 2026-09-13 — T05 — DONE

- Changes: new `production_app/upgrade.py` (snapshot + idempotent apply); `hooks.py` after_migrate registration; new Work Order custom fields `custom_box_1`/`custom_box_2` (Float kg, non-negative, allow_on_submit), `custom_prepacking_confirmed` (Check, allow_on_submit); `custom_leader_produksi` Int→Data; allow_on_submit enabled for `custom_nama_penimbang`, `custom_jumlah_kru`, `custom_leader_produksi`, `custom_qc_produksi`. Snapshot exported to `snapshots/T05-pre-migration.json`. Test `test_t05_box_kg_and_leader_name_persist_after_submit` added.
- Verification: apply() executed via bench execute (docker cp + backend restart); field state verified by SQL (fieldtype/allow_on_submit/insert_after + information_schema varchar(140)); apply() second run → all "unchanged" (idempotent); suite `Ran 12 tests OK` incl. decimal kg + name persistence on submitted WO. Leader rows with values pre-migration: 0 (snapshot) — nothing to lose.
- Evidence: snapshots/T05-pre-migration.json; upgrade.py; task-05-report.md.
- Remaining issue: full `bench migrate` (after_migrate path) deferred to T13.
- Next action: T06 — read APIs + derived stage in `production_app/api/work_order.py` per the T02 contract.
- Rollback notes: leader Data→Int only lossless while no names entered (currently none); box/confirmed fields deletable; allow_on_submit flips reversible.

### 2026-09-13 — T04 — DONE (Gate A passed: transaction correctness established)

- Changes: extended `production_app/tests/test_wo_transaction_proof.py` with `TestWorkOrderOperationsProof` (3 tests). No app behavior code; no site metadata change.
- Verification: same run command as T03 → Ran 11 tests, OK. Leak check: 0 test rows; `Company.default_operating_cost_account` NULL after runs (test set it only in-transaction).
- Evidence: WO submit creates draft Job Cards; start_timer/complete_job_card (two cycles 60+40, auto_submit) persists time logs, submits card, pushes completed_qty to WO operation; manufacture with unfinished operation throws `OperationsNotCompleteError` inside the native builder (get_items→check_if_operations_completed) — gating cannot be bypassed; after completion manufacture completes WO (produced 100). Bakery override: single inward batch entry qty == FG row qty; RM rows untouched.
- Contract additions: Job Card actions must pass `employees` (native crashes on None); each completion cycle needs its own start_timer; operations = optional stage (0/2986 operational WOs use them).
- CONFIG REQUIREMENT (user decision needed before operations go live): company ROPI has no `default_operating_cost_account`; set it (e.g. a clean P&L expense account like "5110.001 - Biaya BBM - ROPI") before any operations WO. Deliberately NOT changed outside test transactions.
- Remaining issue: none blocking. Deferred to T09: process-loss on Job Card completion; multiple cards per operation label test.
- Next action: T05 — field versioning/migration (`custom_box_1/2` Float kg, `custom_prepacking_confirmed` Check, leader Int→Data, allow_on_submit for penimbang/kru/leader/qc_produksi) with snapshot + idempotency.
- Rollback notes: remove allow_tests + server_script_enabled keys; delete tests dir.

### 2026-09-13 — T03 — DONE

- Changes: new test `production_app/tests/test_wo_transaction_proof.py` (+ tests/__init__.py), synced to container by docker cp. No app behavior code yet; no site metadata change.
- Verification: `bench --site frontend run-tests --module production_app.tests.test_wo_transaction_proof` → Ran 8 tests, OK (twice; 0 leaked test rows confirmed by direct SQL). Above-limit: native `ValidationError` at validate stage, no partial writes. Above-plan-within-allowance with Production Plan attached: accepted, plan row produced qty updated.
- Evidence: see task-03-report.md. Current allowance = 25.0 (read at runtime). KEY: native `add_transfered_raw_materials_in_items` prorates RM consumption to yield — finish action (T11) must restore RM rows to transferred quantities (plan rule #2); reference implementation in test `_manufacture_doc`/`_transferred_map`. Batch: WO submit auto-creates batch (setting=1); single-entry inward bundle qty synced to FG row.
- Environment fixes (reversible, non-business): set `allow_tests=true` (site config); restored missing `server_script_enabled=1` in common_site_config + backend restart. The key had disappeared from the config before today's 07:25 UTC restart — WITHOUT it, batch-item WO submission fails site-wide (Batch insert triggers enabled "Batch Print" server script). USER SHOULD NOTE: investigate why the key vanished; any future stack rebuild must keep it.
- Remaining issue: none blocking. `validate_components_quantities_per_bom` confirmed OFF by passing behavior (document exact value in T04/T05).
- Next action: T04 — extend the same checks to operations/Job Cards + explicit bakery-override/batch-row verification.
- Rollback notes: remove `server_script_enabled` key and `allow_tests` key (site reverts to prior state); delete tests dir.

### 2026-09-13 — T02 — DONE

- Changes: documentation only (contract section above + task-02-report.md). No code, no site change.
- Verification: source reading of installed runtime (sed -n ranges on work_order.py 684–1035/1096–1160/2709–2772, stock_entry.py 580–655/700–727/865–900/1027–1050/1165–1238/2503–2560/4239–4290, job_card.py 211–275/963–1096/1616–1700, stock_controller.py 399–470, work_order_quantities.py, bakery overrides/serial_batch_bundle.py). Execution proof of these methods is T03/T04, deliberately not claimed here.
- Evidence: see the Action contract section; native overproduction validation point (update_work_order_qty), loss derivation (validate_fg_completed_qty + set_process_loss_qty), duplicate guard (check_duplicate_entry_for_work_order), cancel order (validate_cancel), plan row locking order.
- Remaining issue: actual site behavior for FG batch bundle creation on Manufacture (setting make_serial_no_batch_from_work_order value + auto-bundle) is proven by execution in T03/T04.
- Next action: T03 — integration proof without operations (below/equal/above/over-limit), isolated test records only.
- Rollback notes: none.

### 2026-09-13 — T01 — DONE

- Changes: none (read-only investigation). New evidence file `.superpowers/sdd/TASKS/task-01-report.md`; ledger + this file updated only.
- Verification: `docker exec erpnext-new-backend-1 ... bench --site frontend list-apps` → production_app 0.0.1 + bakery_manufacturing 0.0.1 installed; `curl http://localhost:8081/api/method/ping` → 200; `bench --site frontend execute frappe.get_all` (Custom Field/Client Script/Server Script) and direct SQL via `docker exec erpnext-new-db-1 mariadb -uroot -padmin _e9ef387b375d0575` for aggregate WO/item facts.
- Evidence: host↔container production_app identical (3-file md5 equal; both branch N @ d6c2800). Compose mounts ONLY sites+logs → sync = `docker cp` + backend container restart (gunicorn --preload, 2 workers). Custom fields 30, no drift (leader still Int, no Box fields). Scripts: 12 client enabled (six plan-named match claims); server scripts active: Stock Reconcilation UOM, Batch Print, get_uom_conversion_factor API; batch-related server scripts disabled. 2986 WOs: 0 with operations; FG stock_uom Pcs; PJ260001–008 batch-tracked; fg_warehouse mostly Gudang Barang Jadi / Cold Storage Produksi, 8 NULL. Settings: overproduction 25.0, backflush = Material Transferred for Manufacture, allow_negative_stock off. Bakery override `BakerySerialAndBatchBundle` confirmed registered; production_app hooks empty.
- Remaining issue: none blocking. Note: disabled Server Script `Patch Serial and Batch Bundle Manufacture` must stay disabled; T04 to revisit if batch anomalies appear.
- Next action: T02 — trace native WO/transfer/Job Card/manufacture/cancel methods in installed source and record the action contract.
- Rollback notes: none (no persisted change).

### 2026-09-13 — Planning handoff

- Recorded user corrections and split implementation into 18 dependency-ordered tasks.
- Added explicit state/reporting protocol and a tool-independent Zcode implementation prompt.
- Changed documentation only. Application code, Custom Fields, active scripts, settings, and stock documents remain unchanged.

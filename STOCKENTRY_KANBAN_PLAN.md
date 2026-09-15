# Stock Entry Kanban (Serah Terima) — WO-centric board + box kg + source warehouse

Plan date: 2026-09-14. Business contract for task section G (T31–T33) in `TASKS.md`.
Amends the Serah Terima contract in `HANDOVER_PLAN.md` (§4 request/post-packing/send
flow); `IMPLEMENTATION_PLAN.md` scope is untouched. Progress/evidence: `PROJECT_STATE.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Project process overrides: NO git commits (ZCODE_PROMPT.md) — per-task diffs are
> tracked via saved `git diff` snapshots in the SDD workspace; browser-interactive
> verification is controller-only; runtime is Docker `erpnext-new-backend-1`, site
> `frontend`.

**Goal:** Make the Serah Terima board fully Work-Order-referenced while items are not
batch-tracked: a configurable source warehouse, Cold Storage cards showing the WO's
finished-goods qty + completion date, a drag-to-request that creates the Material
Request in the background with the WO's full qty, a box-only (kg) "Verifikasi Siap
Kirim" step, and a background Stock Entry on Terkirim that moves the WO's qty —
with the existing batch seam kept intact for future batch adoption.

**Architecture:** All board truth stays server-derived from documents (`api/handover.py`,
pattern §4.1 HANDOVER_PLAN). The WO→(batch | batchless pool) resolution in
`_wo_lot_rows` remains THE single seam: batch-tracked items keep lot identity and
`get_batch_qty` math untouched; batchless items resolve stock against the new source
warehouse setting. Metadata changes ship through the existing idempotent, snapshot-first
`upgrade.py`.

**Tech stack:** Frappe/ERPNext v16 custom app (Python whitelisted APIs), Vue 3 SPA in
`workspace_frontend/`, native MR→SE builder, no core edits.

## Global constraints

- No git commit/push; no ERPNext/Frappe core edits; no second stock ledger; reuse native
  builders (`make_stock_entry` from MR, `update_status`). Preserve permissions gates:
  every action runs as the session user behind explicit role gates (gudang create/cancel,
  produksi verify/send), no `ignore_permissions`.
- Migrations: snapshot-first, idempotent, `apply()` twice converges; never rewrite
  operational data inventively (existing box values are NULLed, preserved in snapshot).
- UI text Indonesian; repo docs/comments English. Errors hold input; server messages in
  Indonesian per existing patterns.
- Runtime verification only via `docker exec erpnext-new-backend-1 bench --site frontend ...`;
  host→container sync = `docker cp` + backend restart (T01 mechanism). Assets: build with
  yarn in backend container, deploy to host repo `production_app/public/workspace/assets/`
  + `sites/assets` in backend AND frontend containers, verify identical md5 at all points
  incl. served HTTP. Operators must hard-refresh once after deploy.
- Box 1/2 are Float kg weights (decimal, ≥ 0), independent of Pack/PCS conversions —
  never converted to PCS, never altering consumption.
- Batch scalability rule: batch-tracked math (lot identity, `get_batch_qty`, SE `batch_no`
  row) must remain the primary path; the batchless WO-qty basis is the fallback branch,
  not a replacement.

## Decisions (rulings, advisor-checked 2026-09-14)

- R1: SE posting datetime = the actual send moment (move to Terkirim). Native `now()`
  default; no back-dating from the earlier Siap Kirim move.
- R2: New setting `custom_default_handover_source_warehouse` (key
  `handover_source_warehouse`). When set it overrides ONLY (a) the MR/source resolution
  for batchless pools (`_item_stock` warehouse, `_reserved_by_item` keying) and (b) the
  MR `from_warehouse`/item `from_warehouse` written by `create_request`. Batch-tracked
  lot identity and `get_batch_qty` stay SE-derived (batch seam untouched). When empty,
  current behavior (SE-derived lot warehouse) is the fallback — the board never hard-fails
  on an unset source.
  - Reservation keying must be WO-lot-based, not MR-`from_warehouse`-based, so MRs created
    before the setting existed still reserve the pool correctly after it appears.
- R3: Request = the WO's FULL `produced_qty`, no qty dialog (drag/click = direct action).
  Server blocks a second ACTIVE (unshipped, unstopped) request for the same WO.
  Availability guard remains: batchless pool / batch qty may be smaller than the WO qty →
  clear Indonesian error (diminta vs tersedia), zero writes.
- R4: The Siap Kirim step becomes the mockup's "Verifikasi Siap Kirim" dialog: context
  rows (Diminta, Hasil akhir Work Order) + Box 1 & Box 2 kg inputs only. Good/Reject/
  Trial/Sisa/QC Packing/Jam Packing are NOT shown or asked — they are already recorded on
  the Work Order Post-Packing stage (T27, before Finish). UI requires both boxes
  (mockup `*`); server accepts optional floats (finite, ≥ 0).
- R5: Endpoint names stay (`create_request`, `save_post_packing`, `send_handover`);
  signatures change: `create_request(work_order)`, `save_post_packing(material_request,
  box_1=None, box_2=None)`, `send_handover(material_request)` (unchanged). Docstrings
  updated. MR post-packing qty/jam/qc custom fields stay on the doctype, unwritten by
  this flow (history).
- R6: Send qty = the MR's requested qty (== WO produced_qty at request time; produced_qty
  cannot change after completion). The short-close/stop-MR branch is removed (dead code).
  Batch-tracked SE rows keep `batch_no` (definitely-from-that-WO); batchless keeps the
  pool pre-check.
- R7: Cold Storage card: primary qty = WO `produced_qty` ("Hasil WO"), completion stamp =
  LATEST Manufacture SE posting (`completed_at`, shown "Selesai …"); `entered_at`
  (earliest) stays FIFO-sort-only. Pool availability/reserved stays as the smaller note
  line (both lines labelled — numbers may differ by design, documented FU8 limitation).
- R8: Box migration (Data → Float kg) on BOTH Work Order and Material Request: snapshot
  distinct values first; then NULL ALL existing values (old semantics = text identifiers,
  not kg; snapshot is the recovery); then flip fieldtype + `change_column_type` to
  decimal. Order matters: nullify BEFORE alter (MariaDB strict mode). Per-field
  fieldtype check = idempotency. Ship the writer code change in the SAME working session
  before running live `apply()` (old `_box_text` writes would crash against a decimal
  column) — i.e. live `apply()` runs only after the server task's code is complete.

## File structure

- Modify `production_app/upgrade.py` — source-warehouse setting field; box Data→Float
  migration (WO + MR); WORKSPACE_FIELDS/MR_CUSTOM_FIELDS box specs → Float kg.
- Modify `production_app/api/work_order.py` — settings read/save gains
  `handover_source_warehouse`.
- Modify `production_app/api/handover.py` — board payload (source_warehouse,
  produced_qty, completed_at), pool/reservation keying, `create_request`,
  `save_post_packing`, `send_handover`.
- Modify `workspace_frontend/src/WarehouseSettings.vue` — 6th setting input.
- Modify `workspace_frontend/src/store.js` — adapter for the new payloads/signatures.
- Modify `workspace_frontend/src/HandoverBoard.vue` — card content, direct request,
  Verifikasi Siap Kirim dialog, kirim dialog, removed request dialog.
- Modify tests: `test_handover_setup.py`, `test_handover_board.py`,
  `test_handover_actions.py`, `test_handover_native_proof.py`,
  `test_wo_transaction_proof.py`.

---

### Task 1 (T31) — Server: setting, box kg migration, WO-referenced board & actions

**Files:** `production_app/upgrade.py`, `production_app/api/work_order.py`,
`production_app/api/handover.py`, the five test files above.

**Interfaces produced (consumed by T32/T33):**

- `warehouse_defaults()` / `warehouse_defaults_save(..., handover_source_warehouse=None)`
  — returns keys incl. `handover_source_warehouse`.
- Board payload: `{"source_warehouse": str|None, ...}`; lot rows add
  `produced_qty` (float), `completed_at` ("YYYY-MM-DD HH:MM:SS" str).
- `create_request(work_order)` → `{"ok", "material_request", "qty", "board"}`.
- `save_post_packing(material_request, box_1=None, box_2=None)` →
  `{"ok", "material_request", "box_1", "box_2", "board"}` (floats or None).
- `send_handover(material_request)` → `{"ok", "material_request", "stock_entry",
  "batch", "qty", "board"}` (keys `good`/`requested`/`stopped` removed).

**Steps:**

1. `upgrade.py`: add `custom_default_handover_source_warehouse` (Link Warehouse) to
   `WAREHOUSE_DEFAULT_FIELDS`; add `ensure_box_kg_fields()` — snapshot
   `snapshots/box-kg-pre.json` (box Custom Field defs + distinct stored values for WO
   and MR), then per field: skip if already Float; else `UPDATE ... SET <f>=NULL WHERE
   <f> IS NOT NULL` (record count), set fieldtype Float, `change_column_type` to
   `decimal(18,6)` (nullable — verify actual column after, record it). Update
   WORKSPACE_FIELDS + MR_CUSTOM_FIELDS box specs to Float kg (label "Box 1/2",
   description "Berat Box X (kg) saat serah terima", `non_negative: 0`). Wire into
   `apply()` BEFORE the field upserts (FU7 ordering pattern).
2. `api/work_order.py`: `HANDOVER_SOURCE_FIELD = "custom_default_handover_source_warehouse"`;
   extend `SETTING_WAREHOUSE_FIELDS` (+ key `handover_source_warehouse`) and
   `warehouse_defaults_save` (validate exists, empty clears).
3. `api/handover.py`:
   - `_source_warehouse()` (single-value read, `or None`); `_build_board` adds
     `"source_warehouse"`.
   - `_wo_lot_rows`: fetch `produced_qty`; history loop also tracks the LATEST posting
     → `row.completed_at`; rows keep SE-derived `warehouse`.
   - `_lots`: batchless pool key/`_item_stock` use `_source_warehouse() or row.warehouse`;
     `_reserved_by_item(requests, wo_rows)` keys by the WO lot row's pool warehouse
     (fallback `r["from_warehouse"]` when the WO has no lot row) — transition-safe.
   - `create_request(work_order)`: role/perm gates + `_target_warehouse_or_throw()`
     unchanged; WO row lock; `qty = flt(wo.produced_qty)` (≤0 → throw "belum punya hasil
     barang jadi"); duplicate-active guard (requests re-derived under the lock: same WO,
     lane request/siap_kirim, no flag → throw with the existing MR name); batchless Item
     lock + re-derive (existing pattern, guard re-checked after); whole-UOM + availability
     checks with qty; MR `from_warehouse` = `_source_warehouse() or lot.warehouse`;
     `transaction_date = now()`; insert+submit in one transaction.
   - `save_post_packing(material_request, box_1=None, box_2=None)`: keep role/read/write/
     lock/confirmed/sent guards; `_box_kg(value, label)` (None/""→None; float() parse
     error → "{label} harus angka kg yang valid"; finite; <0 → "{label} tidak boleh
     negatif"); `db_set` boxes + `custom_postpacking_confirmed=1`; WO box mirror
     (`WO_MIRROR_FIELDS`) unchanged; response per interface. Delete `_box_text`.
   - `send_handover(material_request)`: keep gates/locks/`_checked_lot`/duplicate/Stopped/
     confirmed guards; `qty = flt(mr.items[0].stock_qty or mr.items[0].qty)` (≤0 →
     throw); physical check (batchless: pool warehouse resolution; batch:
     `get_batch_qty(batch, lot.warehouse)`); SE row qty/transfer_qty = qty; batch row
     only when tracked; DELETE the short-close/stop branch and `update_mr_status` import;
     response per interface.
4. Tests (extend the five suites; follow existing fixture/cleanup discipline):
   - setup: source field created; box fields Float on WO+MR (readback); apply() 2×.
   - board: `produced_qty`/`completed_at` present & correct; `source_warehouse` in
     payload; batchless pool reads the SETTING warehouse (stock there counts, stock
     elsewhere does not); legacy MR (from_warehouse = SE-derived) still reserves when
     the setting is set.
   - actions: create_request full-WO qty + from_warehouse follows setting (and falls
     back when unset); duplicate-active blocked (zero writes); pool-short blocked with
     diminta/tersedia message; save_post_packing box floats persist + mirror + repeat
     blocked + negative/text rejected + gudang 403; send qty == requested, batchless
     pool drained exactly, batch item → SE row `batch_no`, MR NOT stopped, duplicate
     send blocked.
   - native_proof: PLANNED_MR_FIELDS box fieldtype updated to Float.
   - wo_transaction_proof: T05 box test returns to Float kg semantics (decimal
     round-trip; never converted to PCS).
5. Verify in container: `bench --site frontend execute production_app.upgrade.apply` —
   run it ONLY after step 3 code is complete (R8 ordering); second run converges; then
   all five suites ×2 green; `git diff --check`. No commit.
6. Report to the task report file; controller saves `git diff HEAD` snapshot for review.

**Acceptance:** apply() 2× idempotent with box-kg-pre.json snapshot written; all suites
green ×2; batch-tracked paths untouched (batch tests still green); no permission changes;
zero residue from test fixtures.

---

### Task 2 (T32) — Frontend SPA: Pengaturan field, WO cards, direct request, Verifikasi Siap Kirim

**Files:** `workspace_frontend/src/WarehouseSettings.vue`, `store.js`,
`HandoverBoard.vue` (+ `styles.css` only if needed).

**Interfaces consumed:** T31 endpoints/payloads exactly as specified above.

**Steps:**

1. `WarehouseSettings.vue`: 6th field `{ key: 'handover_source_warehouse', label:
   'Source Warehouse (Stock Entry)', desc: 'Asal pengiriman serah terima (Cold Storage) — halaman Stock Entry.' }`.
2. `store.js`: `mapLot` + `producedQty` (`l.produced_qty`), `completedAt`
   (`l.completed_at`); `applyBoard` + `sourceWarehouse`; `createRequest(workOrder)` (no
   qty); `savePostPacking(materialRequest, { box1, box2 })` numeric (no String() trim);
   ACTION_LABELS + `create_request: 'Request Gudang'`.
3. `HandoverBoard.vue`:
   - `lotCard`: `ql: 'Hasil WO'`, qty from `producedQty`; `meta: 'Selesai ' +
     fmtStampShort(completedAt || enteredAt)`; keep the batchless/reserved note line;
     pill unchanged (Adonan [+ ' · tanpa batch']).
   - Lot → Request Gudang: drop AND click call `createRequest(workOrder)` directly (no
     dialog). Pending state disables the card; failure → `setActionError` (global modal,
   FU14 pattern) with input-free retry.
   - DELETE the request dialog block (dlgReq, reqQty, useMaxQty, FIFO hint code) — FIFO
     ordering stays server-side (sort unchanged).
   - Replace the Post-Packing dialog with mockup's "Verifikasi Siap Kirim": header
     (PackageCheck), dlg-sub WO · item · MR (+ batch); context rows Diminta
     (`requestedQtyPcs`) and "Hasil akhir Work Order" (`lot.producedQty`); Box 1/Box 2
     `input type="number" step="any" min="0"` REQUIRED (both, mockup `*`), labels
     "Box 1 (kg)" / "Box 2 (kg)"; hint: "Box disimpan pada Work Order. Stock Entry baru
     dibuat saat request dipindahkan ke Terkirim."; button "Siapkan Kirim"; errors hold
     input. Validation: both non-empty, numeric ≥ 0.
   - `reqCard`: meta adds request creation time (jam permintaan); pill keeps box count.
   - `siapCard`/`doneCard`: qty = `requestedQtyPcs` (drop postPacking.goodQty reads);
     box pill shows kg values when present (e.g. `Box 12.5 / 8 kg`, else '—').
   - Kirim dialog: Box row shows kg values; success view: Ditransfer = requested qty;
     remove stopped-callout branch (server never stops now).
   - Multi-role choose dialog: options "Batalkan (Gudang)" / "Verifikasi Siap Kirim
     (Produksi)".
4. Build & deploy per the container procedure; md5 identical (build output, host repo,
   backend sites/assets, frontend container, served); grep served bundle for
   `Verifikasi Siap Kirim`, `Hasil WO`, `handover_source_warehouse`; restart backend.
5. HTTP-level loop as two fixture users (gudang + produksi; one batchless item, one
   batch-tracked item) hitting exactly the SPA endpoints: board → create_request (assert
   qty = WO produced, from = setting, date today) → duplicate blocked → verify (box kg
   floats persist + WO mirror) → send (SE qty, batch row for the tracked item, MR not
   stopped, posting ≈ now) → reload board = server truth; cancel path. Cleanup residue 0.
6. Report; controller saves diff snapshot for review.

**Acceptance:** loop green end-to-end at HTTP level; bundle verified 5 points; no
`goodQty`/request-dialog remnants in the bundle; stage/board state always from server.

---

### Task 3 (T33) — Acceptance run + final state (controller)

**Steps:** all five suites fresh ×2; regression sweep; browser-interactive smoke by the
controller (Pengaturan shows 6 inputs incl. Source Warehouse (Stock Entry); board cards
show Hasil WO + Selesai; drag Cold Storage → Request Gudang creates MR without dialog;
Verifikasi Siap Kirim box-only dialog; drag → Terkirim creates SE; reload = server
truth; mobile 390×844); desk view of migrated box fields (Float); docs updates
(`HANDOVER_PLAN.md` addendum, `TASKS.md` statuses, `PROJECT_STATE.md` work log,
rollback notes); fixture cleanup residue 0; final whole-branch review dispatch.

**Acceptance:** every matrix row above has executed/observed evidence; docs consistent;
stop — further work only on a new request.

## Rollback

- Code: revert the five app files + tests, rebuild/resync bundle, restart backend.
- Metadata: box fields back to Data is NOT lossless after kg values exist — restore
  definitions from `snapshots/box-kg-pre.json` only with a deliberate migration (FU7
  warning still applies); drop `custom_default_handover_source_warehouse` Custom Field
  (additive; safe to just clear its value).
- Documents: MRs/SEs created by the flow are ordinary native documents; cancel via Desk
  (SE first, then MR).

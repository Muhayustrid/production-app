# Bulk Handover = 1 Material Request — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A group handover request of N Work Orders creates ONE Material Request (one row per WO); sending it creates ONE Stock Entry whose rows link to the MR rows and marks every WO Terkirim; Krim Kopi history 1–8 Okt on the new site is rewritten into that shape.

**Architecture:** `production_app/api/handover.py` stops assuming `mr.items[0]`: every handover path iterates the MR's WO-bound rows. Legacy MRs (one row, or member of a `Handover Box Plan`) keep working. `warehouse_app` reads group size from MR rows. History is fixed by a standalone REST script in `AutoFetchErestoToERPNext/pos_sync/`.

**Tech Stack:** Frappe/ERPNext v16 (Python), Vue 3 SPA (`workspace_frontend`, `warehouse_app/frontend`), node `--test`, Python `requests` (pos_sync).

**Spec:** `production_app/docs/superpowers/specs/2026-10-10-bulk-handover-single-mr-design.md`

## Global Constraints

- Branch `feat/bulk-handover-single-mr` in `production_app` and in `warehouse_app`.
- Legacy MRs (single row; or `custom_handover_box_plan` set) behave exactly as before — no data migration of them.
- A bulk MR contains rows of ONE item only; minimum 2 WOs; each row `qty` = WO `produced_qty`, `custom_work_order` = WO.
- New bulk MRs set NO `custom_handover_box_plan`.
- Errors stay Indonesian and zero-write (one transaction; throw before any insert).
- Lock order: Work Orders sorted by name, then Item row (batchless) — same as today.
- Site baru: `allow_negative_stock` stays 0 except inside the history script, restored in `finally` to its prior value.
- pos_sync script: dry-run default, `--execute`, idempotent, secrets from `/tmp/eresto_prod.env` only, max 10 workers, 3 retries.

## Review Focus

1. Batch-tracked item in a bulk MR where WOs have different batches → each SE row carries its own WO's batch (Task 3 test).
2. Total stock short although each row alone fits → send refused, zero SE (Task 3 test).
3. A WO in the bulk already has an active single request → create refused, zero MR (Task 1 test).
4. Board with a bulk MR → one card per WO, no duplicate keys (Task 2 + Task 4 tests).
5. History day whose Σ WO produced_qty ≠ old SE qty, or a rerun after success → that day is skipped, nothing cancelled (Task 6 dry-run assertions).

---

### Task 0: Test environment

**Files:** none (local site config only).

- [ ] **Step 1:** In container `frappe-backend-1`, site `erp.localhost`: set `Stock Settings.enable_serial_and_batch_no_for_item = 1` (the T24 `setUpClass` creates batch items and currently fails with "Cannot enable Has Batch No").
- [ ] **Step 2:** Copy the branch's `handover.py` + tests into the container (`docker cp`, `-u root chown 1000:0`) and run
  `bench --site erp.localhost run-tests --module production_app.tests.test_handover_actions`
  Expected: baseline result recorded (all pass or a list of pre-existing failures to ignore).

### Task 1: `create_group_request` → one MR, N rows

**Files:**
- Modify: `production_app/api/handover.py` (`_insert_submitted_handover_mr` ~1113, `create_group_request` ~1325)
- Test: `production_app/tests/test_handover_actions.py`

**Interfaces:**
- Produces: `_insert_submitted_handover_mr(rows, source, target, company, box_plan=None) -> Document` where `rows = [(wo, amount, stock_uom), ...]`; sets `custom_handover_material_request` on every WO, then `_sync_handover_summary([all wo names])`. `create_request` calls it with one row.
- Produces: `create_group_request(...)` returns `{"ok", "material_request": str, "material_requests": [str], "box_plan": None, "expected_unit_count", "board"}`.

- [ ] **Step 1: Failing tests** (replace `test_fu96_group_request_plan_members_and_board` and `test_fu96_group_request_plan_cancel`):
  - `test_bulk_group_request_one_mr_rows_per_wo`: `_group_ready(60, 40)` → result has one MR; `len(mr.items) == 2`; `{i.custom_work_order: flt(i.qty)} == {wo1: 60, wo2: 40}`; `mr.custom_handover_box_plan` falsy; `result["box_plan"] is None`; both WO summaries Link == MR, status "Diminta Gudang"; produksi user → PermissionError, 0 MR.
  - `test_bulk_group_request_rejects_wo_with_active_request`: `_request(wo1)` then group (wo1, wo2) → ValidationError "sudah punya permintaan aktif"; `_bound_mr_count(wo2.name) == 0`.
  - Keep `test_fu96_group_request_rejections_are_zero_write` (assert no MR, and no new Handover Box Plan).
- [ ] **Step 2:** Run the module (Task 0 command). Expected: the new tests FAIL (2 MRs created / box_plan set).
- [ ] **Step 3: Implement** — validation loop unchanged; after it, one `_insert_submitted_handover_mr(members, _pool_warehouse(first_lot), target, company)`; delete the Handover Box Plan insert. Each MR row: `item_code, qty, uom, stock_uom, from_warehouse, warehouse, schedule_date, custom_work_order`.
- [ ] **Step 4:** Legacy group tests (`test_fu96_group_member_cancel_blocked_until_group_cancel`, `test_fu96_group_cancel_leaves_shipped_members_alone`) build their group through a new test helper `_legacy_group(wos)` that inserts a `Handover Box Plan` and calls `_insert_submitted_handover_mr([(wo, qty, uom)], ..., box_plan=plan)` per WO — they must pass unchanged otherwise.
- [ ] **Step 5:** Run module. Expected: PASS (plus baseline).
- [ ] **Step 6: Commit** `feat(handover): group request creates one MR with a row per WO`

### Task 2: Board, reservation and cancel read every row

**Files:**
- Modify: `production_app/api/handover.py` (`_requests` ~367–570, `_handover_mr` ~1485, `_cancel_unsent_request` ~1245, `cancel_request` ~1282)
- Test: `production_app/tests/test_handover_actions.py`, `production_app/tests/test_handover_board.py`

**Interfaces:**
- Produces: `_requests(...)` returns one dict per (MR, WO-bound row) with the existing keys, `qty` from that row, plus `group_size` = number of WO-bound rows of a bulk MR (legacy plan MRs keep the plan-derived `group_size`; single MR → `None`); `box_plan` stays for legacy rows.
- Produces: `_handover_mr(name)` requires every row to have `custom_work_order`.
- Produces: `cancel_request(mr)` on a bulk MR locks all its WOs (sorted) and cancels the whole MR; summaries of all WOs cleared.

- [ ] **Step 1: Failing tests**
  - `test_bulk_board_one_row_per_wo_and_reservation`: bulk (60, 40) → `handover_board()` has two request rows with the same `mr`, `work_order` wo1/wo2, `qty` 60/40, `group_size == 2`; each lot `reserved_qty` = its own qty; batchless pool `available_qty` reduced by 100.
  - `test_bulk_cancel_clears_every_wo`: gudang `cancel_request(mr)` → MR docstatus 2; both summaries Link None, status falsy.
- [ ] **Step 2:** Run. Expected: FAIL (board shows one row; second WO keeps Link).
- [ ] **Step 3: Implement** — in `_requests` loop over `bound_items[m.name]` instead of `first`; per-row `lot`, `qty`, `work_order`. `_cancel_unsent_request`: collect all WO names of the MR, `has_permission` once, lock sorted, sync all. `cancel_request` legacy plan sibling guard untouched.
- [ ] **Step 4:** Run both modules. Expected: PASS.
- [ ] **Step 5: Commit** `feat(handover): board, reservation and cancel cover every MR row`

### Task 3: `send_handover` → one SE, N rows

**Files:**
- Modify: `production_app/api/handover.py` (`send_handover` ~1511)
- Test: `production_app/tests/test_handover_actions.py`

**Interfaces:**
- Consumes: `_handover_mr`, `_checked_lot(wo_name)`, `_item_stock`, `get_batch_qty`, `make_mr_stock_entry`.
- Produces: `send_handover(material_request, company=None)` returns `{"ok", "material_request", "stock_entry", "qty": total, "work_orders": [names], "batch": first-or-None, "board"}`.

- [ ] **Step 1: Failing tests**
  - `test_bulk_send_one_se_links_rows_all_wo_terkirim` (batchless, 60/40): one SE, 2 rows, each `material_request == mr` and `material_request_item` = matching MR row, qty 60/40; Cold −100 / Target +100 in SLE; MR status Transferred; both WO `custom_handover_status == "Terkirim"`; second send → ValidationError "duplikat", still 1 SE.
  - `test_bulk_send_batch_rows_keep_own_batch` (batch FG `self.fg`, two WOs): each SE row `batch_no`/bundle = its WO lot batch.
  - `test_bulk_send_total_short_zero_writes`: bulk (60, 40), drain pool to 70 (pattern from `test_t31_pool_short_blocked_zero_writes`) → send ValidationError mentioning "tidak bisa mengirim"; 0 SE linked to MR.
- [ ] **Step 2:** Run. Expected: FAIL ("harus satu baris item").
- [ ] **Step 3: Implement** — lock all WOs sorted; Stopped/duplicate guards unchanged; per row `_checked_lot`; shortage check sums qty per `("i", item, route_wh)` or `("b", batch, route_wh)` against physical; `make_mr_stock_entry` then map `se.items` to MR rows by `material_request_item` (throw if counts differ), set `qty`, `transfer_qty`, batch per row; insert/submit; `_sync_handover_summary(all WOs)`.
- [ ] **Step 4:** Run full `test_handover_actions` + `test_handover_board`. Expected: PASS (single-MR tests unchanged).
- [ ] **Step 5: Commit** `feat(handover): send bulk MR as one Stock Entry, all WOs Terkirim`

### Task 4: production_app SPA

**Files:**
- Modify: `workspace_frontend/src/store.js:685,770` (card id), `workspace_frontend/src/HandoverBoard.vue:92` (`groupText`), Kirim dialog (WO count + total)
- Test: `workspace_frontend/tests/handover-card.test.mjs` (or the test covering the store mapper)

**Interfaces:**
- Produces: request/done row `id = mr + '|' + work_order`, `materialRequest = mr`, `groupSize = group_size`.

- [ ] **Step 1: Failing test**: mapping two server rows with the same `mr` and different `work_order` yields two distinct ids; `groupText({materialRequest:'MR-1', groupSize:2})` → `'Grup MR-1 (2 WO)'`; legacy `{boxPlan:'HBP-1', groupSize:2}` → `'Grup HBP-1 (2 WO)'`.
- [ ] **Step 2:** `cd workspace_frontend && node --test tests/*.test.mjs` → FAIL.
- [ ] **Step 3: Implement**; every place that passed `r.id` to `sendHandover`/`cancelRequest` passes `r.materialRequest`.
- [ ] **Step 4:** node tests PASS; `npm run build` OK.
- [ ] **Step 5: Commit** `feat(workspace): bulk MR shows one card per WO`

### Task 5: warehouse_app

**Files:**
- Modify: `warehouse_app/warehouse_app/gudang_request.py` (`_active_request_map` ~322, picker rows), `frontend/src/pages/BoardPage.vue` (~277–290, 482, 541–548), `frontend/src/components/GroupRequestDialog.vue:60`
- Test: `warehouse_app/warehouse_app/tests/w19_gate.py`

**Interfaces:**
- Produces: picker rows expose `group_size` = WO-bound row count of the active MR when > 1 (else legacy plan size); `box_plan` only for legacy.
- Cancel of a row with `group_size > 1` and no `box_plan` → `cancelRequest(mr)`; label "Cancel Group".

- [ ] **Step 1:** Update `w19_gate` checks 3 and 6 to the new contract (one MR, two rows; `cancel_request` cancels the group). Run gate → `ok=false` on those checks.
- [ ] **Step 2:** Implement server + frontend; toast `Group request created: <MR> · N Work Orders`.
- [ ] **Step 3:** Gate `ok=true`; `npm run build` OK.
- [ ] **Step 4: Commit** `feat(gudang): group request is one MR`

### Task 6: Deploy

- [ ] **Step 1:** Local stacks: `docker cp` changed files into all `frappe-*` containers that carry the apps, chown, `bench --site erp.localhost clear-cache`, restart backend, ping 200; SPA assets copied; md5 host == container.
- [ ] **Step 2:** Merge both branches to `main`, push (user approval already given for this flow). User deploys on Frappe Cloud.
- [ ] **Step 3:** Cloud check (REST, read-only): `create_group_request` exists (whitelisted method 417 with bad args, not 404/“not whitelisted”), board loads.

### Task 7: History script Krim Kopi + 9 Okt cleanup

**Files:**
- Create: `AutoFetchErestoToERPNext/pos_sync/rapikan_handover_krim_kopi.py`
- Update: `AutoFetchErestoToERPNext/PROJECT_STATE.md`

**Interfaces:**
- Consumes: `prod_common.Client`, `load_env`; ERPNext REST: `erpnext.stock.doctype.material_request.material_request.make_stock_entry`.
- Constants: `ITEM = "PJ260016"`, `CS = "Cold Storage Produksi - JURI"`, `GBJ = "Gudang Barang Jadi - JURI"`, `DAYS` = spec §5 table (date → old SE, old MR, qty). Idempotency key: MR `title = "Serah Terima Bulk PJ260016 <date>"`.

- [ ] **Step 1: Dry-run** builds the per-day plan: WOs = Krim Kopi WOs whose submitted SE Manufacture into CS has that `posting_date`; prints `date, n_wo, Σqty, old SE qty, ACTION|SKIP_EXISTS|ABORT_MISMATCH`. Expected live: 6 days × 34 WO, Σ == SE qty, all `ACTION`.
- [ ] **Step 2: `--execute`**: snapshot Bin (all PJ260016 rows + global negatives); backup JSON of old SEs/MRs to `audit_logs/`; remember `allow_negative_stock`, set 1; cancel old SEs newest→oldest, then old MRs; per day oldest→newest: create+submit bulk MR (`transaction_date`, `schedule_date` = day, rows per WO), `make_stock_entry` → set `set_posting_time=1`, `posting_date`/`posting_time` = old SE, row qty per MR row, submit; `finally` restore `allow_negative_stock`.
- [ ] **Step 3:** Delete cancelled docs with the `bersih_dokumen_cancelled.py` procedure (backup + `delete_linked_ledger_entries` temp + restore). Poll `Repost Item Valuation` until none Queued/In Progress.
- [ ] **Step 4: Verify** prints LOLOS/GAGAL: Bin PJ260016 == snapshot; 0 Bin negative; 0 SLE PJ260016 at CS/GBJ with `qty_after_transaction < 0`; 204 WOs status "Terkirim" and Link = their day's bulk MR; every new SE row has `material_request`; `allow_negative_stock == 0`; rerun dry-run → all `SKIP_EXISTS`.
- [ ] **Step 5:** 9 Okt: cancel + delete `MREQ-MTR-26-0190`, `0193..0226` (flag `--cleanup-9okt`), then `create_group_request` for the 34 WO 9 Okt (as gudang API user) → 1 MR; summaries "Diminta Gudang".
- [ ] **Step 6:** Update `PROJECT_STATE.md` (changelog + known issues); commit script + report.

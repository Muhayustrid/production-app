# Partial Production Handover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow explicitly confirmed Gudang Barang Jadi (GBJ) handover requests for available finished goods while preserving production output, legitimate other-destination requests (e.g. R&D), outstanding handover quantities, and existing batch identity across `production_app` and `warehouse_app`.

**Architecture:** Scope batchless pool reservations strictly by `(item_code, source_warehouse)` across all active Material Transfers (both WO-linked and external/unlinked), deducting already-fulfilled Stock Entry Detail quantities to eliminate double deduction. Provide a read-only preview API with deterministic sorted-WO allocation that surfaces external reservations and remainder quantities. Support explicit allocation confirmation under sorted-WO and Item locks, and allow sequential partial Stock Entry fulfillment without corrupting requested quantities or falsely claiming full WO completion.

**Tech Stack:** Python 3.14 / Frappe v16, MariaDB transactions with `for_update=True`, Vue 3 / Vite SPA, Node built-in test runner (`node --test`), Python unittest with Frappe mocks.

**Spec:** `/Users/rotiropi/erpnext-new/apps/production_app/docs/superpowers/specs/2026-10-28-partial-production-handover-design.md`

## Global Constraints

- Work ONLY in `/Users/rotiropi/erpnext-new/apps/production_app` and `/Users/rotiropi/erpnext-new/apps/warehouse_app`.
- No core Frappe/ERPNext edits; no added external dependencies.
- No production writes or unsafe site mutations; existing sites are treated as unsafe production copies.
- Keep all git changes uncommitted; commit and push are strictly prohibited without separate explicit user approval.
- Do not untrack or rewrite tracked, oversized `PROJECT_STATE.md` files; minimally record active task state.
- No cross-app Python imports in `warehouse_app` production code.
- Group contract is ONE Material Request containing multiple Material Request Item child rows (one per Work Order).
- Retain exact 43-WO characterization (1,096 Pcs produced across 43 WOs, 1,096 physical stock, 4 Pcs reserved by external R&D MR, 1,092 Pcs pool available; allocations: 1,071 Pcs to first 42 WOs, 21 Pcs to 43rd WO with 4 Pcs unrequested remainder against unchanged produced qty of 25). Do not reinterpret 21/25 as UOM conversion factor.

## Review Focus

1. **Unlinked external MR reservation:** An unlinked active MR in the same source warehouse deducts from pool availability without mutating any specific WO or disappearing on board reload.
2. **Double deduction prevention:** A submitted Stock Entry Detail decreases physical stock and must not simultaneously be subtracted as an outstanding reservation.
3. **Multi-SE sequential send:** An MR partially fulfilled by a prior Stock Entry allows subsequent sends for remaining rows/quantities without throwing "Pengiriman duplikat" or overwriting mapped remaining quantities.
4. **Deterministic allocation across pools:** Sorting WOs deterministically by name ensures reproducible partial allocation without skipping or over-allocating across disparate source warehouses.
5. **Lock re-verification rollback:** If pool availability or WO status changes between preview and confirmation, the transaction fails with zero writes rather than creating a silent over-allocation.

---

### Task 1: Source-Scoped Pool Reservation and Double-Deduction Prevention

**Files:**
- Modify: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/api/handover.py`
- Test: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/tests/test_handover_actions.py`

**Interfaces:**
- Consumes: Frappe DB query interfaces (`frappe.db.sql`, `frappe.get_all`).
- Produces:
  - `_pool_reserved_now(item_code, warehouse=None) -> float`: CURRENT outstanding reservations for `(item_code, warehouse)` across all active Material Transfers, subtracting submitted SED fulfilled quantities.
  - `_reserved_by_item(requests, wo_rows, external_reservations=None) -> dict[tuple[str, str], float]`: Warehouse-scoped board reservation map including external active requests.

- [ ] **Step 1: Write failing unit test for warehouse-scoped pool reservation and external MR deduction**

In `production_app/tests/test_handover_actions.py`, add `test_pool_reserved_scopes_by_warehouse_and_subtracts_fulfilled_se` asserting:
1. An active MR in `Gudang A` does NOT reserve `Gudang B`.
2. An unlinked external MR (no WO link) in `Gudang A` for 4 Pcs reserves exactly 4 Pcs.
3. Once an SE transfers 2 Pcs of an MR, outstanding reservation is 2 Pcs, not 4 Pcs.

- [ ] **Step 2: Run test to verify it fails**

Run test via bench/unittest and confirm failure due to item-wide aggregation and lack of SED subtraction in `_pool_reserved_now`.

- [ ] **Step 3: Implement warehouse-scoped reservation in `production_app/api/handover.py`**

Update `_pool_reserved_now(item_code, warehouse=None)`:
```python
def _pool_reserved_now(item_code, warehouse=None):
    wh_clause = "and coalesce(mri.from_warehouse, mr.set_from_warehouse) = %s" if warehouse else ""
    params = [item_code, warehouse] if warehouse else [item_code]
    query = f"""
        select coalesce(sum(
            greatest(0.0, mri.stock_qty - coalesce((
                select sum(sed.transfer_qty)
                  from `tabStock Entry Detail` sed
                 where sed.material_request = mr.name
                   and sed.material_request_item = mri.name
                   and sed.docstatus = 1
            ), 0.0))
        ), 0.0)
          from `tabMaterial Request Item` mri
          join `tabMaterial Request` mr on mr.name = mri.parent
         where mri.item_code = %s
           and mr.docstatus = 1
           and mr.status not in ('Stopped', 'Transferred', 'Issued')
           and mr.material_request_type = 'Material Transfer'
           {wh_clause}
         for update
    """
    return flt(frappe.db.sql(query, tuple(params))[0][0])
```
Also update `_reserved_by_item` to incorporate external active Material Transfers in the same source warehouse.

- [ ] **Step 4: Run test to verify it passes**

Ensure `test_pool_reserved_scopes_by_warehouse_and_subtracts_fulfilled_se` passes.

---

### Task 2: Additive Read-Only Preview API and Deterministic Allocation

**Files:**
- Modify: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/api/handover.py`
- Test: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/tests/test_handover_actions.py`

**Interfaces:**
- Consumes: `_checked_lot`, `_pool_reserved_now`, `_pool_warehouse`, `_expected_unit_count`.
- Produces:
  - `@frappe.whitelist() preview_handover_request(work_orders, company=None) -> dict`: Returns `{ok: True, allocations: [...], pool_available: float, external_reservations: [...], total_requested: float}`.

- [ ] **Step 1: Write failing test for 43-WO characterization (1,096 / 4 / 1,092 / 1,071 / 21)**

In `production_app/tests/test_handover_actions.py`, add `test_preview_43_work_orders_characterization`:
- 43 Work Orders producing 1,096 Pcs. Physical source stock = 1,096 Pcs.
- External R&D Material Request reserves 4 Pcs in the same source warehouse.
- Call `preview_handover_request(wo_names)`.
- Assert `pool_available == 1092`.
- Assert sum of first 42 WO allocations == 1071.
- Assert 43rd WO allocation == 21, remaining_unrequested == 4.
- Assert 21/25 is quantity allocation, not UOM conversion factor.

- [ ] **Step 2: Run test to verify it fails**

Confirm `preview_handover_request` is not defined.

- [ ] **Step 3: Implement `preview_handover_request` in `production_app/api/handover.py`**

Implement deterministic allocation:
1. Sort `work_orders` by name.
2. Load each WO and lot under read permission.
3. Derive eligible unrequested remainder per WO: `flt(wo.produced_qty) - cumulative_transferred - active_requested`.
4. Group by `(production_item, source_warehouse)`.
5. For each group, compute physical stock and active reservations (including external MRs). Available pool = `physical - reserved`.
6. Allocate pool budget greedily in sorted WO-name order.
7. Return per-WO allocation, remaining unrequested, and external reservation summaries (anonymized if lacking read permission).

- [ ] **Step 4: Run test to verify it passes**

Ensure `test_preview_43_work_orders_characterization` passes with exact numbers.

---

### Task 3: Explicit Allocation Confirmation on Create Handover Request

**Files:**
- Modify: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/api/handover.py`
- Test: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/tests/test_handover_actions.py`

**Interfaces:**
- Consumes: `preview_handover_request`, `_pool_reserved_now`, `_insert_submitted_handover_mr`.
- Modifies:
  - `create_request(work_order, requested_qty=None, preview_context=None, company=None)`
  - `create_group_request(work_orders, allocations=None, preview_context=None, company=None)`

- [ ] **Step 1: Write failing tests for explicit allocation confirmation and stale preview rejection**

Add tests in `test_handover_actions.py`:
- `test_create_group_request_with_explicit_allocations`: creates group request with 1,071 on first 42 WOs and 21 on 43rd WO. Verifies MR has 43 rows with those exact quantities.
- `test_create_request_rejects_stale_preview_under_lock`: if stock decreases between preview and confirmation, creation throws error and makes zero writes.

- [ ] **Step 2: Run test to verify failure**

Confirm rejection or signature mismatch.

- [ ] **Step 3: Update `create_request` and `create_group_request` in `production_app/api/handover.py`**

Allow optional explicit allocations/requested_qty:
1. If not provided, fallback to full eligible unrequested remainder (backwards compatible).
2. If provided, validate against locked WO and current pool availability.
3. Skip rows with 0 allocation; fail if all rows are 0.
4. Insert submitted MR with explicit stock_qty and conversion_factor.

- [ ] **Step 4: Run tests to verify they pass**

Ensure both tests pass.

---

### Task 4: Partial Transfer Send and Multiple Stock Entries Lifecycle

**Files:**
- Modify: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/api/handover.py`
- Test: `/Users/rotiropi/erpnext-new/apps/production_app/production_app/tests/test_handover_actions.py`

**Interfaces:**
- Consumes: `make_mr_stock_entry`, `_sent_se_by_mr`.
- Modifies:
  - `send_handover(material_request, company=None)`
  - `_handover_state(wo_names)`

- [ ] **Step 1: Write failing test for partial send and subsequent send of remaining quantity**

In `production_app/tests/test_handover_actions.py`, add `test_partial_send_allows_subsequent_send`:
1. Create MR for 25 Pcs.
2. Simulate partial transfer of 20 Pcs via Stock Entry.
3. Call `send_handover(mr.name)` for remaining 5 Pcs.
4. Verify send succeeds, creating a second Stock Entry for 5 Pcs.
5. Verify `_handover_state` flags `LANE_KIRIM` only when cumulative transferred covers `produced_qty`.

- [ ] **Step 2: Run test to verify failure**

Confirm `send_handover` throws duplicate send error due to earlier SE.

- [ ] **Step 3: Update `send_handover` and `_handover_state` in `production_app/api/handover.py`**

1. In `send_handover`:
   - Replace blanket duplicate check with check for whether MR is already fully transferred (`mr.status == 'Transferred'` or `mr.per_transferred >= 100`).
   - Use mapped `se.items` quantities directly from `make_mr_stock_entry` rather than overwriting with original MRI qty.
2. In `_handover_state`:
   - Compute cumulative transferred qty from submitted SEDs for each WO.
   - If cumulative transferred >= produced_qty -> `LANE_KIRIM`.
   - If active MR exists with unfulfilled qty -> `LANE_REQUEST`.

- [ ] **Step 4: Run tests to verify they pass**

Ensure partial send and state transitions pass.

---

### Task 5: Warehouse App Picker and History Adaptation

**Files:**
- Modify: `/Users/rotiropi/erpnext-new/apps/warehouse_app/warehouse_app/warehouse_app/gudang_request.py`
- Test: `/Users/rotiropi/erpnext-new/apps/warehouse_app/warehouse_app/tests/w19_gate.py`

**Interfaces:**
- Modifies:
  - `_active_request_map(rows)`
  - `requestable_work_orders(search=None, filters=None, limit_start=0, limit_page_length=50, paginated=0)`

- [ ] **Step 1: Write failing test for partial shipped WO in picker**

In `warehouse_app/tests/w19_gate.py`, add test verifying that a WO with produced 25 and transferred 21 has:
- `request_shipped == False` (or `partially_shipped == True`)
- `remaining_qty == 4`
- Remains discoverable and requestable for the remaining 4 Pcs.

- [ ] **Step 2: Run test to verify failure**

Confirm `request_shipped` is currently True whenever any submitted SE exists.

- [ ] **Step 3: Update `_active_request_map` and `requestable_work_orders` in `gudang_request.py`**

Calculate cumulative transfers per WO:
```python
r.transferred_qty = flt(transferred_by_wo.get(r.name, 0.0))
r.remaining_qty = max(0.0, flt(r.produced_qty) - r.transferred_qty)
r.request_shipped = r.remaining_qty <= 0 and r.transferred_qty > 0
r.request_partial = r.transferred_qty > 0 and r.remaining_qty > 0
```

- [ ] **Step 4: Run test to verify it passes**

Ensure picker exposes honest remainder quantities.

---

### Task 6: Warehouse App Frontend Selection and Confirmation Dialogs

**Files:**
- Modify: `/Users/rotiropi/erpnext-new/apps/warehouse_app/frontend/src/pages/BoardPage.vue`
- Modify: `/Users/rotiropi/erpnext-new/apps/warehouse_app/frontend/src/components/RequestDialog.vue`
- Modify: `/Users/rotiropi/erpnext-new/apps/warehouse_app/frontend/src/components/GroupRequestDialog.vue`

**Interfaces:**
- Calls: `production_app.api.handover.preview_handover_request` before confirmation.
- Submits: explicit allocations to `create_request` / `create_group_request`.

- [ ] **Step 1: Update `isSelectable` in `BoardPage.vue`**

Change `const isSelectable = (r) => !r.request_active && (!r.request_shipped || r.remaining_qty > 0)` and display partial badge (`Partially Transferred`) when `r.request_partial`.

- [ ] **Step 2: Update `RequestDialog.vue` and `GroupRequestDialog.vue`**

1. On open, fetch preview via `preview_handover_request`.
2. Display allocated vs remaining unrequested quantities.
3. Show warning banner if external reservations reduce pool availability.
4. Pass explicit confirmed allocations to server on submit.

- [ ] **Step 3: Run Vite build for warehouse_app**

Run: `cd /Users/rotiropi/erpnext-new/apps/warehouse_app/frontend && npm run build`
Expected: Build succeeds with 0 errors.

---

### Task 7: Production App Board Display and Verification Suite

**Files:**
- Modify: `/Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend/src/HandoverBoard.vue`
- Modify: `/Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend/src/format.js`
- Test: `/Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend/tests/handover-card.test.mjs`

**Interfaces:**
- Consumes: updated lot card fields (`physical_qty`, `reserved_qty`, `available_qty`, `unrequested_qty`).

- [ ] **Step 1: Write failing frontend unit test for partial handover card display**

In `workspace_frontend/tests/handover-card.test.mjs`, add tests asserting that partial status and unrequested remainder are rendered correctly without corrupting UOM display.

- [ ] **Step 2: Run test to verify failure**

Run: `node --test /Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend/tests/handover-card.test.mjs`
Confirm failure.

- [ ] **Step 3: Update `HandoverBoard.vue` and format helper**

Render partial lane status and remainder notes.

- [ ] **Step 4: Run all frontend unit tests and Vite build for production_app**

Run:
`node --test /Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend/tests/*.test.mjs`
`cd /Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend && npm run build`
Expected: All tests pass, build succeeds.

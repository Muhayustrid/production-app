# Work Order workspace implementation plan

Status: planning only. No application code, Custom Field, Client Script, settings, or stock transaction has been changed for this plan.

Execution documents: `TASKS.md` defines the ordered work packages; `PROJECT_STATE.md` records actual progress and evidence; `ZCODE_PROMPT.md` is the implementation handoff. This plan owns business rules; tasks must not override them.

### Confirmed user decisions (latest)

- Overproduction follows the effective ERPNext settings and validations. The observed 25% is a historical snapshot, not an application constant. Do not add a separate limit or change the setting.
- Leader Produksi stores a person's name: use Data text, not Int and not a mandatory User link.
- Box 1 and Box 2 store weight in **kg**: proposed fieldnames `custom_box_1` and `custom_box_2`, type Float. They are not box identifiers or counts.
- Zero production output is not saved: when good prepacking is zero, reject the prepacking save/confirmation and Finish before any writes. Keep the current form input available for correction; preserve previously stored values. This does not prohibit legitimate zero reject/trial/sisa values.

## 1. Approved outcome and scope

Operators complete an existing Work Order inside one production workspace:

Persiapan → Material → Operasi (when present) → Pre-Packing → Finish → Selesai.

- Reuse the table, kanban, dialogs, workspace, and visual design from `/Users/rotiropi/mockup_production_app`.
- Production Plan and Work Order creation remain in ERPNext.
- Material transfer and Manufacture Stock Entries, and Job Cards, remain real ERPNext documents. Operators perform their actions through the workspace without navigating between documents.
- Finished goods quantity comes from `custom_good_qty_prepacking`.
- Raw materials remain based on the Work Order plan, even when actual finished goods are lower or higher.
- Manufacture targets the Work Order finished-goods warehouse; the mockup calls it Cold Storage. Do not hardcode a warehouse name.
- Record two new Work Order fields: **Box 1** and **Box 2**. This request currently authorizes recording the requirement, not creating the fields during planning.
- The user permits removing old scripts. Remove only explicitly identified scripts whose relevant behavior has been replaced and tested.

Excluded: custom Stock Entry/handover page, postpacking workflow, Material Requests, FIFO allocation/reservations, box inventory, Production Plan UI, POS, reports, dashboards, batch redesign, and production deployment.

Do not infer future handover requirements from the mockup as authorization to implement them now. Postpacking remains stored on the WO but is not a prerequisite for finishing manufacture.

## 2. Verified baseline

Inspected on 2026-09-13. Recheck before implementation; source and site state may change.

| Evidence | Verified fact |
|---|---|
| Local endpoint | `http://localhost:8081`, Docker frontend `erpnext-new-frontend-1` |
| Runtime | Backend `erpnext-new-backend-1`, bench `/home/frappe/frappe-bench`, site `frontend` |
| Installed apps | `production_app` and `bakery_manufacturing` are installed, alongside ERPNext/Frappe |
| Host repository | `/Users/rotiropi/erpnext-new/apps/production_app`; still an app skeleton |
| Mockup | Vue 3/Vite; in-memory actions in `src/store.js`; no backend integration |
| WO custom fields | 30 entries including layout fields; eight pre/postpacking quantity fields exist as Float |
| Quantity editing | All eight packing quantities permit changes after submit |
| Other editing | QC Produksi, QC Packing, Nama Penimbang, Jumlah Kru, and Leader Produksi currently do not allow changes after submit |
| Leader Produksi | Currently Int, while mockup expects a person's name |
| Adonan | `custom_adonan_ke` is Data; separate `custom_adonan` is Int; do not conflate them |
| UOM | Existing `custom_uom`, `custom_conversion_factor`, `custom_qty_in_uom` fields and conversion client script |
| Overproduction | Work Order allowance was 25% at inspection; always use current native settings and validations |

### Existing script behavior

- `stock_entry_fg_from_wo` is enabled. On a new Manufacture form with a Work Order, it reads good **postpacking** and changes `qty` on every row with no source warehouse and a target warehouse. It leaves header `fg_completed_qty` unchanged, skips zero values, and only runs in the browser. This is not an adequate server-side contract for the new workspace.
- `Get_Conversion_Factor_WorkOrder` is enabled. It handles alternate-UOM conversion and defaults warehouses from Item. Preserve that useful behavior; do not delete without replacement.
- `Stock Entry Manufacture Modal` is enabled. It is a separate quick-fill wizard based on Item/BOM, quantity, warehouses, and `get_items`. It is not the custom handover page.
- `Auto Pick Warehouse Work Order` and `filter_item_to_manufacture_workorder` are enabled. Their bodies still need inspection before any cleanup decision.
- `WO tes popup`, `Stock Entry Outlet`, and `Stock Entry Batch UOM` are disabled. Disabled does not mean safe to delete unrelated history.
- No Work Order Server Script appeared in the inspected list. This does not prove absence of all app-level behavior.

### Installed core behavior, read from source

Paths below are relative to the runtime bench:

- `apps/erpnext/erpnext/manufacturing/doctype/work_order/work_order.py`: `make_stock_entry` creates entries from the WO and calls native item/batch preparation. `get_status` uses produced quantity plus process loss to determine Completed. `get_transferred_or_manufactured_qty` sums finished-item `transfer_qty` for manufactured quantity. `update_work_order_qty` validates overproduction.
- `apps/erpnext/erpnext/stock/doctype/stock_entry/stock_entry.py`: `validate_fg_completed_qty` can infer process loss when the header quantity exceeds finished-item quantity. `update_work_order` updates WO quantities/status and interacts with Production Plan quantity locking.
- These source observations are not yet an executed proof of the proposed workflow, particularly with operations, process loss, and Production Plan constraints.

### Existing batch override: preserve ownership

`apps/bakery_manufacturing/bakery_manufacturing/hooks.py` registers `BakerySerialAndBatchBundle` from `overrides/serial_batch_bundle.py`.

It synchronizes the single bundle entry to `row.transfer_qty` for inward, batch-tracked Manufacture rows, then always calls the native method. It does not read good prepacking/postpacking. It skips multiple-entry bundles and is not explicitly limited to the main finished item.

Keep this override in `bakery_manufacturing`. Do not duplicate it, register a competing bundle override, uninstall the app, or remove it with Client Script cleanup. Change it only if a reproducible failure requires a narrowly scoped fix under that repository's instructions. Historical statements in its AGENTS.md differ from current hooks; use current source as evidence of active behavior.

## 3. Data decisions

| UI input | Storage / decision |
|---|---|
| Adonan ke | Reuse `custom_adonan_ke`; do not repurpose `custom_adonan` |
| Jam/suhu adonan | Reuse `custom_jam_adonan`, `custom_suhu_adonan` |
| Penimbang | Reuse `custom_nama_penimbang`, Link User; show user names but save valid User IDs |
| Jumlah kru | Reuse `custom_jumlah_kru` |
| Leader produksi | Reuse `custom_leader_produksi`, migrate Int to Data for a person's name; preserve old values as text, do not invent names for old numbers |
| Prepacking | Reuse all four `custom_*_qty_prepacking` fields |
| Pembekuan / QC | Reuse `custom_jam_pembekuan` and `custom_qc_produksi` |
| Box 1 / Box 2 | `custom_box_1`, `custom_box_2`, Float weights in kg; labels Box 1 (kg), Box 2 (kg) |

Implementation default for unspecified Box UI details: optional inputs in Pre-Packing, saved with that form. Accept finite non-negative decimal kg. No pack/PCS conversion for these fields, no conversion between weight and finished-goods quantity, no required equality to any total, and no stock movement. Do not invent gross/tare/net calculations. The kg meaning is confirmed; optional placement is an implementation default, not a claimed user instruction.

Only enable Allow on Submit for fields that the approved workflow must edit after WO submission. Do not bypass update-after-submit validation globally. Preserve existing values when exporting/versioning fields; never export every site's customization indiscriminately.

Server actions must distinguish saved/confirmed prepacking from default zero fields. First look for existing persisted evidence. If none exists, add the minimum explicit confirmation marker needed, not a separate workflow engine or duplicate status system. Zero is not evidence that the user completed a form.

## 4. Non-negotiable behavior

1. The server reads current ERPNext documents and determines the active stage. UI drag/drop expresses an action; it never saves arbitrary stages or statuses.
2. WO planned quantity stays intact. Actual yield must not rescale planned raw-material consumption.
3. Only the actual finished-item row(s), identified by native flags and the production item, receive the good prepacking quantity. Never apply good quantity to all inward rows, scrap, or by-products.
4. Produced quantity, process loss, batch quantity, valuation, and WO/Production Plan updates must agree. Never force `status = Completed`, fake produced quantity, or create a stock adjustment merely to make the screen finish.
5. Good prepacking must be finite and strictly positive when saving/confirming prepacking or finishing. Reject/trial/sisa must be finite and non-negative; zero is valid for these fields. Their sum is not forced to equal the plan. Do not automatically interpret reject/trial/sisa as scrap stock movements or process loss.
6. Persist quantities in the Item's stock UOM. For PCS items enforce whole PCS. Alternate units are input/display only; reject invalid or missing conversion instead of silently assuming factor 1 or rounding.
7. Final submission succeeds atomically or rolls back. Reload after an error or retry must show server truth, without duplicate transfer/manufacture documents or duplicated Job Card time logs.
8. Use ordinary ERPNext permission and document validation for every action, including linked WO/Job Card, company, and warehouse checks. No `ignore_permissions` shortcut for operator actions.
9. Cancellation through native ERPNext must update the workspace from current documents. A custom cancellation UI is out of scope; stale completed markers must not survive as false evidence.

## 5. Implementation sequence and gates

### Phase 1 — Prove the transaction path before building the UI

Read the remaining relevant installed source: WO submit/Job Card creation, Job Card start/stop/complete, transfer-against settings, material consumption, process-loss derivation with operations, and effective hooks. Inspect representative existing WOs read-only to identify actual configurations.

On isolated test records, prove a complete planned run with actual good quantity below/equal/above plan, both with and without operations. Start from the native WO entry builder with planned quantity and adjust only the final yield where appropriate. Confirm whether retaining planned header quantity and native loss handling meets the invariant; do not declare this implementation correct from source reading alone.

Check all stock and plan effects, not just submission success. Follow current ERPNext overproduction settings and validations. An over-limit attempt must fail with the native reason and no partial writes; it does not trigger a request to raise the allowance. Do not hardcode 25% or promise unlimited overproduction.

If good prepacking is zero, reject both saving/confirming that prepacking payload and Finish before mutation. Leave prior stored data unchanged and keep unsaved input in the UI for correction. Do not create a zero-yield transaction, fake output, or discard zero reject/trial/sisa fields.

Gate: demonstrated quantity/status/batch behavior and an explicit record of unresolved business decisions. If the proof fails, fix the responsible layer or report the exact blocker; do not compensate in frontend code.

### Phase 2 — Persist minimal data and implement server actions

- Version only the necessary fields, migrate Leader Produksi to Data safely, and add the two Float Box fields in kg. Snapshot existing values before metadata changes; preserve historical numeric leader values as text without guessing names.
- Provide list/detail reads plus concrete actions for preparation, material transfer, Job Card start/finish, prepacking confirmation, and manufacture finish.
- Prefer one small API module; split only when a distinct owner or substantial logic justifies it. Reuse native methods rather than reproducing document controllers.
- Persist preparation before submitting a draft WO. For already-submitted WOs, use the permitted editable fields without resubmitting.
- Compute remaining transfer from submitted documents. Reuse appropriate existing drafts deliberately; do not silently submit an unrelated user-created draft.
- Keep native Job Card records/timers and save actual completed quantity. Map by document identity, not operation label; multiple cards may share an operation.
- Prevent duplicate writes through transactional locks and rechecking linked documents under the lock. Respect existing Production Plan/WO lock ordering. No global lock, custom queue, or generic idempotency service.
- Use a precise link/marker only if existing document relationships cannot reliably distinguish this workspace's one-time action. Do not use timing heuristics.

Gate: targeted integration checks pass through server actions, including permission denial and retry behavior. No UI dependency for business correctness.

### Phase 3 — Integrate the existing mockup

- Serve the Work Order Vue interface from `production_app` using the existing Frappe session. Verify the installed asset/route mechanism first; no separate backend or authentication service.
- Reuse WorkOrderList, WorkOrderKanban, Workspace, QtyInput, and relevant stage components. Replace mock data/actions with the server contract.
- Keep the supplied layout and Indonesian labels. Do not redesign or add another frontend framework, state-management dependency, or workflow library.
- Remove handover navigation and simulation controls from this release. Do not carry coldStorageLots/handoverRequests mock stores into the backend.
- Implement loading, clear errors, pending-action button disabling, and refresh after actions. Preserve field input on recoverable failure.
- Stage review is read-only. Table, kanban, and workspace invoke the same server actions.
- Preserve Pack/PCS input behavior and mobile/touch access. No optimistic transition to Selesai before successful server submission.

Gate: an operator completes both supported WO flows from the workspace; reload and switching views show the same saved state.

### Phase 4 — Remove conflicts and verify the release

- Export the exact old scripts and field definitions before replacing them.
- Retire `stock_entry_fg_from_wo` when the prepacking implementation is effective. Test native form access so it cannot reapply postpacking or undo a workspace transaction.
- Preserve conversion, filtering, and warehouse defaults unless their replacement covers every affected caller, including the native WO form. Keep the standalone Manufacture modal unless there is a demonstrated conflict or an explicit decision to retire it.
- Do not sweep-delete disabled scripts or unrelated server scripts. Do not delete batch behavior.
- Run the acceptance matrix below, inspect the diff, and document migration and rollback. Local verification does not imply cloud deployment.

Gate: no competing quantity writer, no modified ERPNext/Frappe core files, and exact migration/rollback steps recorded. Stop when the Work Order scope is satisfied.

## 6. Smallest sufficient acceptance matrix

Use the installed Frappe test infrastructure and isolated records; do not submit or cancel existing operational documents as tests.

| Scenario | Required proof |
|---|---|
| No operations | Material → prepacking → Manufacture; no fabricated Job Card |
| With operations | Native start/stop, qty and completion saved per card; prepacking cannot bypass unfinished required work |
| Good below/equal/above plan | Same planned raw materials; actual FG/batch stock; correct native loss/status/plan updates; above case within permitted limits |
| Above limit | Specific validation error, no partial writes; no automatic settings changes |
| Postpacking differs | Manufacture still uses prepacking; postpacking values remain intact |
| Box values | Both decimal kg values survive save/reload within configured precision; negatives/non-finite values rejected; no PCS/Pack conversion or stock effects |
| Leader name | A person's name saves/reloads; existing numeric data is preserved without fabricated names |
| Zero good output | Prepacking save and Finish reject before writes; prior values/documents unchanged; zero reject/trial/sisa remain valid |
| Quantity input | PCS/Pack conversion, non-pack-multiple PCS, fractional PCS rejection, negatives/missing input |
| Double click/retry/concurrency | At most one intended final Manufacture and no duplicate material/time transactions |
| Permission/error | Unauthorized action or failed submission leaves no partial document/quantity changes |
| Native cancel | Recomputed state and quantities reflect cancellation; retry does not double-count |
| Existing WO/data | Existing submitted transfers/cards are recognized; legacy completed WOs are not reopened because a new marker is absent |
| Batch | Single-batch compatibility with the existing override; no mistaken modification of other inward items |

Partial manufacture, multiple batches, secondary items, semi-finished-goods tracking, skip-transfer, transfer against Job Card, and required inspections must first be classified against actual WOs. Reuse native support when it meets the contract. If a configuration cannot yet be handled, show a clear unsupported-action message and native document link before any mutation. Do not silently flatten it or claim full coverage. Any common configuration required by the user's actual workflow must be resolved before declaring this release complete.

## 7. Agent execution boundaries

- Planning is complete when this document is delivered. Do not implement merely because a plan contains commands or phases.
- Once implementation is requested, work through the phases in order; phase gates are evidence checks, not automatic requests for repeated approval.
- Before coding, read applicable AGENTS.md and relevant skills. Use CodeGraph first only where an index exists; never create an index without the user's request.
- Only touch `production_app` by default. A demonstrated cross-app defect requires naming the responsible file and following that app's rules.
- No direct edits to ERPNext/Frappe core, global allowance changes, unrelated migrations, blanket script deletion, historical data rewrites, or production deployment.
- Do not invent method names, field names beyond explicit proposals, or completed tests. Separate verified facts, proposed choices, and blockers.
- Do not add microservices, generic workflow engines, duplicate stock ledgers, new business DocTypes for existing ERPNext records, plugin architectures, or broad refactors.
- Deliver the implemented behavior, tests actually run, remaining limitations, and exact changes. Do not expand into the Stock Entry/handover release after finishing Work Order.

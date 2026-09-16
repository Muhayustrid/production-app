# Stock Entry three-lane handover design

Date: 2026-09-16
Status: Implemented and verified on `feat/three-lane-handover`
Repository: `production_app`, based on branch `N`

## 1. Outcome

Simplify the finished-goods handover board from four lanes to three:

```text
Cold Storage -> Request Gudang -> Terkirim
```

The separate `Siap Kirim` lane is retired. Moving a Work Order from Cold Storage to Request Gudang opens a warehouse-owned form that records the weight and Pack allocation of Box 1 and Box 2. A submitted native Material Request is created only after the form passes server validation. Moving a request to Terkirim creates and submits the native Stock Entry through the existing Material Request builder.

The design keeps ERPNext documents authoritative, preserves the existing bulk/scoped query optimization, and adds no business DocType or workflow framework.

## 2. Confirmed business decisions

- Warehouse staff (`Gudang Barang Jadi` or native `Stock User`) fill and confirm the box form.
- Box 1 and Box 2 weights remain kilograms stored as Float values on Work Order.
- Add one non-negative integer Pack count for each box.
- `Box 1 Pack + Box 2 Pack` must equal the Work Order's full requested Pack total.
- Pack counts must be whole numbers.
- Box 1 is required and must have weight greater than zero and Pack count greater than zero.
- Box 2 may be unused only as exactly zero kilograms and zero Pack. If its Pack count is greater than zero, its weight must also be greater than zero.
- Pack values are stored on Work Order only. Do not add Pack custom fields to Material Request.
- Add a Work Order Link to the active/latest non-cancelled handover Material Request. Keep the Link after successful delivery; clear it when an unsent request is cancelled.
- Cancelling a pre-delivery request clears the Work Order Material Request Link, both box weights, and both Pack counts. If an abnormal native state has a cancelled MR while its Stock Entry is still submitted, the submitted Stock Entry remains authoritative and the summary is retained until recovery starts by cancelling the Stock Entry.
- Existing Material Request box fields are retained for compatibility and historical data but are no longer written by the new flow.
- The prior query optimization must not regress.

## 3. Design principles

1. **Native documents remain the source of truth.** A submitted Material Request means requested; a submitted linked Stock Entry means sent. Board lanes are derived from those documents.
2. **One operational summary, one historical relation.** `Material Request Item.custom_work_order` remains the authoritative relation for all request history. The Work Order Link is a materialized pointer to the currently relevant request, not workflow state.
3. **One transaction per business action.** Box validation, Material Request creation, and Work Order summary updates either all succeed or all roll back.
4. **One concurrency boundary.** Mutating actions lock the Work Order first and re-read relevant documents under that lock.
5. **Bulk reads, scoped validation.** Board loading uses bulk queries. Action validation reads only the affected Work Order and, for batchless pooled stock, only the necessary sibling Work Orders.
6. **No destructive migration.** Existing MR fields and historical values remain intact. New fields are additive and migration is idempotent.
7. **No speculative abstraction.** Extend the current `api/handover.py`, `upgrade.py`, and Vue board; do not add a custom DocType, repository layer, workflow engine, or new dependency.

## 4. Data model

### 4.1 New Work Order fields

| Fieldname | Type | Meaning | Rules |
|---|---|---|---|
| `custom_handover_material_request` | Link / Material Request | Active or latest successfully sent handover request | Read-only in Desk; allow on submit; cleared when the linked unsent request is cancelled |
| `custom_box_1_pack` | Int | Whole Pack count allocated to Box 1 | Read-only in Desk; allow on submit; non-negative |
| `custom_box_2_pack` | Int | Whole Pack count allocated to Box 2 | Read-only in Desk; allow on submit; non-negative |

Reuse existing Work Order fields:

- `custom_box_1`: Float kilograms for Box 1.
- `custom_box_2`: Float kilograms for Box 2.

The four box fields and Material Request Link are maintained only by the handover server actions and synchronization path. Making them read-only in Desk prevents manual edits from creating an inconsistent summary.

### 4.2 Existing Material Request relation

Retain `Material Request Item.custom_work_order` as the historical and queryable relation from each handover request to its Work Order. This supports cancelled requests, replacements, audit, and native document navigation.

Do not add Pack fields to Material Request. Retain existing MR fields such as `custom_box_1`, `custom_box_2`, and `custom_postpacking_confirmed` without deleting or repurposing them; the three-lane flow stops writing them.

### 4.3 Source-of-truth matrix

| Question | Authoritative evidence |
|---|---|
| Has the WO been requested? | Submitted handover Material Request linked by `Material Request Item.custom_work_order`, with no submitted Stock Entry |
| Has the WO been sent? | Submitted Stock Entry Detail linked to the Material Request |
| Which request is operationally relevant? | `Work Order.custom_handover_material_request`, verified against the native MR state |
| What is the request history? | All linked Material Request Items and their parent MRs |
| What are the current box allocations? | Four Work Order box fields |
| What quantity moves? | Material Request item stock quantity, created from the Work Order's full produced quantity |

The Work Order Link and `custom_handover_status` are materialized summaries only. They must never independently determine board lanes or authorize a stock movement.

## 5. State model

### 5.1 Lane derivation

- **Cold Storage:** a supported manufactured Work Order lot has available stock and no active unsent handover request.
- **Request Gudang:** a submitted handover Material Request exists and no submitted Stock Entry exists against it. This includes legacy requests that previously appeared in `Siap Kirim`.
- **Terkirim:** a submitted Stock Entry exists against the handover Material Request. Submitted Stock Entry evidence has precedence over Material Request `docstatus`; even an abnormal cancelled-MR/submitted-SE combination remains Terkirim until the Stock Entry is cancelled.
- Draft and cancelled Material Requests without a submitted Stock Entry stay available for audit but do not appear in an active lane.
- A stopped MR without a submitted Stock Entry remains an explicit edge state in Request Gudang, consistent with current behavior, and reserves no stock.

Remove `LANE_SIAP` from new board and status derivation. A legacy `custom_postpacking_confirmed` value does not create another lane and is not required to send. Both `_requests` and `_handover_lanes` must evaluate submitted Stock Entry evidence before rejecting/skipping a cancelled MR so their lane precedence remains identical. Add a regression test for cancelled MR plus submitted SE.

### 5.2 Work Order status mirror

Keep `custom_handover_status` as a fail-safe derivative used by the Work Order workspace:

- submitted MR without SE -> `Diminta Gudang`
- submitted linked SE -> `Terkirim`
- no qualifying MR -> empty

Retire `Siap Kirim` from the active Select options in one ordered, idempotent migration: first add the new fields, then resynchronize affected Work Orders from live MR/SE documents while the old option is still valid, and only then remove `Siap Kirim` from the Select options. Re-running the migration must converge. This order prevents Work Order validation failures caused by a persisted value that is no longer an allowed Select option.

## 6. Server action contract

### 6.1 `create_request`

Proposed signature:

```text
create_request(
  work_order,
  box_1,
  box_1_pack,
  box_2=0,
  box_2_pack=0
)
```

Role: warehouse side only (`Gudang Barang Jadi` or `Stock User`).

Processing order:

1. Require the warehouse role and ordinary read permission for the relevant documents.
2. Acquire the Work Order row lock.
3. Re-read the submitted Work Order, its Manufacture evidence, lot/warehouse, produced quantity, current Work Order Link, and linked requests under the lock.
4. Verify the Link. If it points to a cancelled or missing MR, clear the stale summary in the same transaction and continue. If a qualifying active unsent request exists, reject the duplicate with its MR name.
5. Resolve the Pack conversion through the same shared unit-enrichment path already used by the Work Order and handover APIs.
6. Calculate expected Pack count from the exact stock quantity that will be written to the MR.
7. Validate all box fields before any business write.
8. Recheck stock availability and batch/batchless reservation rules through the current scoped `_checked_lot` path.
9. Create and submit one native Material Request of type Material Transfer, with the existing Work Order relation on the item row and configured source/target warehouses.
10. Save the MR Link and four box values on Work Order in the same database transaction.
11. Synchronize the handover status summary.
12. Return the created MR reference plus one refreshed full board.

The existing Work Order lock and duplicate check remain mandatory. A browser pending state is not a concurrency control.

### 6.2 `cancel_request`

Role: warehouse side only. Cancellation remains allowed only before a submitted Stock Entry exists.

Processing order:

1. Resolve the Work Order from the Material Request item relation.
2. Acquire the Work Order row lock, then re-read the MR and any linked submitted SE.
3. Reject cancellation if sent.
4. Perform native MR cancellation.
5. If the Work Order Link points to this MR, clear the Link and all four box fields.
6. Synchronize the status summary.
7. Return one refreshed full board.

Native Desk cancellation of an unsent MR must converge to the same clearing behavior through `sync_from_material_request`. Document-event mirrors are intentionally fail-safe and cannot veto native transactions, so the next application action also verifies and repairs a stale Link under the Work Order lock. If Desk or an integration produces an abnormal state where the MR is cancelled while a linked Stock Entry remains submitted, `sync_from_material_request` must retain the Link and box summary because the submitted Stock Entry still makes the handover Terkirim. Recovery follows native document dependency order: cancel the Stock Entry first, then clear/cancel the unsent request state; never erase the audit summary while stock is still transferred.

### 6.3 `send_handover`

Role: production side (`Manufacturing User`).

Preserve the current native and performance-critical flow:

1. Resolve and lock the Work Order associated with the MR.
2. Re-read the submitted MR and reject cancelled, stopped, or already-sent requests as currently defined.
3. Do not require `custom_postpacking_confirmed`; box verification happened before MR creation.
4. Recheck route stock at the MR's actual source warehouse.
5. Build the Stock Entry from the native MR builder.
6. Move exactly the MR requested quantity.
7. Preserve batch assignment and batchless pool behavior.
8. Submit atomically and synchronize the status summary.
9. Keep the Work Order MR Link and box data after success.
10. Return the Stock Entry reference plus one refreshed full board.

### 6.4 Legacy `save_post_packing`

The frontend no longer calls this action. During a compatibility window, the endpoint should reject new use with a clear Indonesian message directing callers to create the request with box data. It must not silently mutate MR or WO fields under the retired four-lane contract.

Do not immediately remove the function if deployed clients may still have a cached bundle. Retire it only after the new bundle is deployed and compatibility evidence shows no supported caller remains. The compatibility stub must reject before acquiring a Work Order lock or writing any field, avoiding lock-order inversion with new WO-first actions.

## 7. Validation contract

All validation runs on the server before MR or Work Order business fields are written.

### 7.1 Pack conversion

- Use the existing shared Pack/stock-UOM conversion source; do not duplicate UOM logic.
- Conversion factor must exist, be finite, and be greater than zero. Validate the raw factor returned by the shared enrichment path; never calculate expected Packs from `_wo_lot_rows.qty_in_pack`, because that display field currently falls back through `display_conversion_factor or 1` and could turn a missing conversion into an incorrect factor of one.
- Requested stock quantity is the full Work Order produced quantity used to create the MR.
- Expected Packs = requested stock quantity / stock units per Pack.
- Expected Packs must be integral using the same explicit precision rule in every caller. Compare the computed decimal quantity with its nearest integer using a documented tolerance derived from Frappe quantity precision; values outside that tolerance are rejected. Do not silently round a fractional Pack.
- `box_1_pack` and `box_2_pack` must parse as integers and be non-negative.
- `box_1_pack + box_2_pack` must exactly equal expected Packs.

A missing conversion or fractional result returns an actionable Indonesian validation error and performs zero writes.

### 7.2 Weight and Pack pairing

- Box 1: kilograms finite and `> 0`; Pack count `> 0`.
- Box 2 unused: kilograms exactly `0` and Pack count exactly `0`.
- Box 2 used: kilograms `> 0` and Pack count `> 0`.
- Mixed Box 2 states, such as `0 Pack / 8 kg` or `2 Pack / 0 kg`, are rejected.
- Kilograms are not converted to PCS or Pack and do not affect stock quantity, valuation, consumption, or batch quantity.

## 8. Permissions and trust boundaries

- Warehouse users continue to create/cancel handover requests; production users continue to send.
- The handover API may update the read-only Work Order summary because the explicitly role-gated business action owns that summary. It must still verify the user's permission to read the Work Order and create/submit/cancel the native MR as applicable.
- Do not grant broad Work Order write permission merely to maintain these controlled fields.
- No `ignore_permissions` for MR or Stock Entry creation/submission.
- No client-provided warehouse, requested quantity, expected Pack total, lane, Work Order status, batch balance, or sent state is trusted.

## 9. Frontend design

### 9.1 Board

Render exactly three lanes:

1. Cold Storage
2. Request Gudang
3. Terkirim

Remove the `Siap Kirim` lane, its card mapper, drag target, and production verification dialog. Existing request cards with legacy post-packing confirmation still render in Request Gudang.

### 9.2 Cold Storage to Request Gudang form

Clicking or dragging a supported Cold Storage card opens a form instead of immediately creating the MR. It displays read-only context:

- Work Order
- item name
- batch when applicable
- requested quantity in Pack and PCS
- final Work Order output in Pack and PCS

Inputs:

- Box 1 (kg)
- Box 1 (Pack)
- Box 2 (kg), default `0`
- Box 2 (Pack), default `0`

The client provides immediate required/type/pair/sum feedback for usability, but the server repeats every rule. On recoverable failure, retain all four inputs. Disable duplicate submission while the action is pending. Do not optimistically move the card before the server accepts the form because the new action has user-entered data that must remain visible on error.

### 9.3 Request Gudang interactions

- Warehouse role: click/drag back to Cold Storage opens the cancellation confirmation.
- Production role: click or drag to Terkirim opens the send confirmation.
- A multi-role user is shown a clear action choice, preserving the existing role-aware pattern.
- The send confirmation shows the Work Order, MR, requested quantity, both box weights, and both Pack allocations.

### 9.4 Terkirim cards

Show the native Stock Entry link, sent timestamp, transferred quantity, box weights, and Pack allocation from the Work Order summary. Historical lane state remains document-derived.

## 10. Performance contract

The optimization introduced by commit `8e104b9` is an architectural constraint, not an incidental implementation detail.

Preserve:

- `_batch_quantities` bulk loading through one ERPNext v16 query pair.
- `_wo_lot_rows(wo_names=...)` scoped reads for action validation.
- `_requests(..., wo_names=.../item_codes=...)` scoped request reads.
- `_checked_lot` without `_build_board`.
- Batchless sibling expansion only for the affected item pool.
- Reservation helpers and targeted lookup treat only the merged Request Gudang lane as active; remove every stale `LANE_SIAP` tuple check without broadening the scan.
- Exactly one full `_build_board()` after each successful mutation for the response.
- No per-card Work Order, Material Request, batch, box, or Link query.

Read the new Link and box fields in the existing bulk Work Order fetch and map them in memory. The full board still derives lanes from MR/SE relations in bulk.

Regression gates on a comparable fixture:

- Bulk batch balances invoke `get_available_batches` once and `get_stock_ledgers_batches` once.
- `_checked_lot` never invokes `_build_board`.
- `create_request` performs no unrelated global Work Order scan before its final response.
- Board payload and query count do not grow linearly with the number of batch-tracked lots.
- Runtime should not regress materially from the recorded warm baseline of approximately 0.141 seconds and 28 queries for the same dataset. Record before/after numbers; treat a material regression as a blocker, not an accepted trade-off.

## 11. Migration and backward compatibility

Implement through the existing snapshot-first, idempotent `upgrade.py` path.

1. Snapshot relevant Work Order field definitions, handover-status Select options, and distinct existing box values before metadata changes.
2. Add the Link and two Int fields with read-only and allow-on-submit semantics while the old `Siap Kirim` option is still valid.
3. Preserve existing MR fields and data.
4. Backfill `custom_handover_material_request` only where a deterministic request exists:
   - choose the latest submitted non-cancelled handover MR linked through `Material Request Item.custom_work_order`;
   - include requests already sent;
   - do not fabricate box Pack allocations for historical WOs.
5. Leave historical Pack fields empty when no authoritative Pack allocation exists.
6. Resynchronize `custom_handover_status` from live MR/SE documents, including submitted-SE precedence over an abnormal cancelled MR.
7. Only after no Work Order retains `Siap Kirim`, remove that value from the Select options.
8. Make applying the complete migration twice converge without rewriting already-correct fields.

In-flight behavior at cutover:

- Legacy Request Gudang and Siap Kirim MRs without SE both appear in Request Gudang.
- They remain sendable using their native requested quantity.
- Historical box display may fall back to the retained MR box values only for presentation during the compatibility period; do not copy ambiguous legacy values into new Pack fields. The board must bulk-map new WO box values through the existing Work Order result set and use MR values only as a legacy fallback, never with a per-card query.
- An old cached frontend calls `create_request(work_order)` without box arguments. The new endpoint must reject that call with an actionable Indonesian validation message and zero writes; it must not create an incomplete request.
- Submitted SEs remain Terkirim.
- Cancelled MRs remain audit history and do not occupy a lane.

## 12. Failure handling and recovery

- Validation failure: zero writes; form inputs retained.
- MR insert/submit failure: Work Order summary and MR both roll back.
- Work Order summary update failure: MR creation rolls back in the same request transaction.
- Stock shortage or SE submission failure: no partial Stock Entry or status change.
- Duplicate create/send: reject with existing document references.
- Doc-event mirror failure: log without breaking unrelated native transactions; subsequent app action repairs stale summary after verification.
- Native SE cancellation: board recomputes from documents. The Work Order MR Link remains because the MR still exists; the request returns to Request Gudang according to native state unless a stopped-MR edge requires the existing manual recovery path.
- Abnormal MR cancellation with a submitted SE: retain Link and box summary, keep the lane derived as Terkirim, and require native recovery in dependency order (SE first).

## 13. Smallest sufficient acceptance matrix

| Scenario | Required proof |
|---|---|
| One box | Box 1 kg/Pack positive, Box 2 exactly 0/0; MR and WO summary save atomically |
| Two boxes | Positive kg/Pack pairs; Pack sum equals expected total |
| Invalid pair | Pack without kg or kg without Pack rejected with zero writes |
| Invalid total | Pack sum below/above expected rejected with zero writes |
| Invalid conversion | Missing, zero, or non-integral Pack conversion rejected before writes |
| Create request | Full produced quantity used; MR submitted; WO Link and box summary set |
| Duplicate/concurrent create | At most one active request and one Work Order summary |
| Cancel via app | Native MR cancelled; Link and four box fields cleared |
| Cancel via Desk | Unsent MR clears summary; event failure cannot veto native cancel; next action self-repairs stale Link; submitted-SE anomaly retains summary and Terkirim state |
| Send | Native MR builder creates one submitted SE for requested quantity; Link/boxes retained |
| Duplicate send | Existing submitted SE detected; no second SE |
| Three lanes | No Siap lane; legacy confirmed request appears in Request; submitted SE appears in Terkirim, including submitted-SE precedence over an abnormal cancelled MR |
| Roles | Warehouse can create/cancel but not send; production can send but not create/cancel |
| Batch tracked | Existing batch identity, bulk balance, route precheck, and bundle behavior preserved |
| Batchless | Pool stock and sibling reservations remain correct |
| Performance | Bulk query pair and scoped action tests pass; comparable warm benchmark recorded without material regression |
| Migration | Apply twice converges; historical fields preserved; deterministic Links backfilled; no invented Pack values |
| Reload | Board and Work Order summaries agree with current documents after every action and native cancellation |

## 14. Files expected to change during implementation

Keep the implementation focused:

- `production_app/upgrade.py`
- `production_app/api/handover.py`
- relevant handover setup/board/action tests
- `workspace_frontend/src/store.js`
- `workspace_frontend/src/HandoverBoard.vue`
- focused frontend presentation/validation tests, if existing seams allow them
- project execution documents (`TASKS.md`, `PROJECT_STATE.md`, and the applicable handover plan addendum)

Do not edit ERPNext/Frappe core, duplicate the bakery batch override, add a new dependency, or introduce a new business DocType.

## 15. Implementation gates

1. **Contract gate:** verify current installed ERPNext method signatures, effective permissions, metadata, and live query baseline before edits.
2. **Server gate:** migration, actions, concurrency, native cancellation, compatibility, and performance tests pass without frontend dependency.
3. **Frontend gate:** three-lane interaction works for warehouse, production, and multi-role users; errors retain input; mobile remains usable.
4. **Acceptance gate:** full server suite twice, frontend tests/build, HTTP loop, browser desktop/mobile smoke, query benchmark, asset hash verification, and fixture cleanup all pass.

No implementation should proceed past a failed gate by compensating in the frontend or weakening native validation.

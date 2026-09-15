# Stock Entry / Serah Terima implementation plan

Status: planning only. No application code, Custom Field, Custom DocPerm, Role, setting, or stock transaction has been changed for this plan.

Execution documents: `TASKS.md` section E (T21–T26) defines the ordered work packages; `PROJECT_STATE.md` records actual progress and evidence; `ZCODE_PROMPT_HANDOVER.md` is the implementation handoff prompt for a fresh session. `IMPLEMENTATION_PLAN.md` remains the business contract for the completed Work Order scope. This plan owns the handover business rules; tasks must not override them.

### Confirmed user decisions (2026-09-13)

- Approach: **full-native mapping, no new business DocType**. The request is a native Material Request; the delivery is a native Stock Entry created from it; the lot is the finished-goods Batch in Cold Storage. Board state is always derived from documents, never stored.
- Roles: **one new Role "Gudang Barang Jadi"** for the warehouse side, plus the existing **Manufacturing User** as the production side. Gudang Barang Jadi sees only the Stock Entry page in this app.
- ADDENDUM (user decision, implemented 2026-09-14): the gudang side of the handover is ALSO triggered by the native **Stock User** role. Semantics: Manufacturing User + Stock User = Work Orders + Stock Entry with BOTH handover sides (multi-role chooser); Stock User only = sees only the Stock Entry page and can only create/cancel requests (post-packing/send stay Manufacturing-User-gated); Manufacturing User only = as before (produksi side). "Gudang Barang Jadi" remains supported as an equivalent gudang-side role. Required one additive custom DocPerm: Stock User → Batch read (board derivation reads the FG batch; native perms lack it).
- Box 1 / Box 2 in the request dialog are **text box identifiers** (e.g. BX-2201), stored as Data custom fields on the Material Request. They are unrelated to `custom_box_1/2` on Work Order, which are Float kg weights.
- After sending with Good < requested (sisa/reject/trial > 0), the Material Request is **stopped (short-closed) natively** so it does not linger as open demand/reservation.
- Cancelling a request (before verification) is a **native Material Request cancel**; the document remains as audit history and the card leaves the board.
- The handover target warehouse is **not hardcoded**: a fifth warehouse default on Manufacturing Settings, editable in the workspace "Pengaturan" menu (same pattern and permission rules as the four existing defaults).
- The UI reuses `/Users/rotiropi/mockup_production_app` `HandoverBoard.vue` (page "Stock Entry", 4-lane kanban) with the role-simulation strip replaced by real Frappe roles.

## 1. Approved outcome and scope

Warehouse (Gudang Barang Jadi) and production (Produksi) complete the finished-goods handover inside one page of the existing production workspace SPA:

Cold Storage (lots, FIFO) → Request Gudang (Material Request by gudang) → Siap Kirim (Post-Packing verification by produksi) → Terkirim (Stock Entry Material Transfer by produksi).

- Real-world serah terima becomes: gudang creates a **Material Request** (type Material Transfer) for a single Work Order lot; produksi verifies physical goods (**Post-Packing**) and sends, creating the **Stock Entry** from Cold Storage Produksi to Gudang Barang Jadi.
- Good Post-Packing is the only quantity that moves stock. Requested, pre-packing, and post-packing quantities are never forced equal; Reject/Trial/Sisa are recorded notes only.
- Reserving stock happens by creating the request: available = physical batch stock in Cold Storage − active reservations (open MRs). One lot may serve many requests while stock remains.
- The Work Order Post-Packing fields (`custom_*_postpacking`, Jam Packing, QC Packing) mirror the **last** verification summary only; full history lives on the Material Requests.

Excluded: multi-Work-Order (multi-allocation) requests — one request serves one WO/lot; undo after Terkirim (native desk cancel only, with documented follow-up); automatic FIFO enforcement beyond the informational hint; box inventory/tracking beyond the two identifier fields; POS, reports, dashboards; production deployment.

## 2. Verified baseline

Inspected read-only on 2026-09-13 (SQL on site DB + installed source in `erpnext-new-backend-1`). Recheck before implementation.

| Evidence | Verified fact |
|---|---|
| Warehouses | `Cold Storage Produksi - ROPI` and `Gudang Barang Jadi - ROPI` exist, enabled |
| Stock Entry DocPerm | Manufacturing User and Stock User have full create/read/write/submit/cancel |
| Material Request DocPerm | Only Purchase User/Manager and Stock User/Manager; **Manufacturing User has none** → both new permissions are custom DocPerms |
| MR custom fields today | Only `custom_note` + a section break |
| MR → SE builder | `material_request.py:936 make_stock_entry`: for Material Transfer, `s_warehouse = item.from_warehouse`, `t_warehouse = item.warehouse`, SE header from `set_from_warehouse`/`set_warehouse`; qty defaults to `stock_qty − ordered_qty` |
| Batch utils | `batch.py:236 get_batch_qty(batch_no, warehouse)`; `get_batches_by_oldest` exists |
| WO Post-Packing fields | `custom_{good,reject,trial,sisa}_qty_postpacking` (Float), `custom_jam_packing` (Time), `custom_qc_packing` (Link) already exist on Work Order |
| Roles | No Gudang/Produksi-like role exists yet; operators run as Manufacturing User |
| Batch per WO | One-shot Finish (previous scope) produces one Manufacture SE per WO with a single auto-created FG batch; bundle sync by the bakery override is proven |
| Lot display inputs | The existing WO API already resolves item_name, Pack/PCS conversion (qtyInPack), and user full names — reuse the same helpers |

Implementation-time verification items (do not assume): MR status transitions incl. `update_status`/Stop for Material Transfer; Stock Entry item batch handling in v16 (old `batch_no` fields vs Serial and Batch Bundle) and non-interference with the `bakery_manufacturing` override on outward transfer rows; `allow_on_submit` coverage of the WO Post-Packing mirror fields; native `Material Request Item.from_warehouse` behavior; exact qtyInPack source per item (same one the WO workspace uses).

## 3. Data decisions

| Concept | Storage / decision |
|---|---|
| Lot identity | FG Batch of the WO's Manufacture SE in the Cold Storage warehouse; remaining = live ledger (`get_batch_qty`), entered timestamp = Manufacture SE posting datetime; FIFO by that timestamp |
| Request | MR type Material Transfer; header `set_from_warehouse` = lot warehouse, `set_warehouse` = handover target; one item row: item, qty (stock UOM Pcs), `from_warehouse` → `warehouse` |
| Lot binding | `custom_work_order` (Link Work Order) on the MR item row |
| Boxes | `custom_box_1`, `custom_box_2` (Data) on MR header; optional, trimmed, empty dropped from display |
| Post-Packing | On MR header, allow_on_submit: `custom_good_qty_postpacking`, `custom_reject_qty_postpacking`, `custom_trial_qty_postpacking`, `custom_sisa_qty_postpacking` (Float), `custom_jam_packing` (Time), `custom_qc_packing` (Link User), `custom_postpacking_confirmed` (Check) |
| WO mirror | Same fieldnames already on Work Order are updated as the last-summary mirror; never a manufacture prerequisite |
| Target warehouse | `custom_default_handover_warehouse` (Link Warehouse) on Manufacturing Settings; edited via the Pengaturan menu (Manufacturing Manager write, all workspace users read — same rules as existing defaults) |
| Roles/DocPerms | Role "Gudang Barang Jadi": MR create/read/write/submit/cancel(+amend) + MR Item create/read; read on Work Order, Batch, Stock Entry, Item. Manufacturing User: MR read/write + MR Item read (no create/cancel). ADDENDUM 2026-09-14: gudang side equivalently triggered by native Stock User (MR/SE/WO/Item/Warehouse reads are native; added only Batch read via idempotent `upgrade.py` `ensure_stock_user_batch_read`, snapshot `snapshots/stockuser-batch-read-pre.json`). All via idempotent `upgrade.py` with a pre-change snapshot |

Snapshot and export rules follow the previous scope: version only owned/required definitions; applying twice is safe; rollback documented.

## 4. Non-negotiable behavior

1. The board renders server-derived truth from current MR/SE/batch documents. Drag or click only opens a business dialog; no client-side state writes.
2. Lot remaining is the live ledger quantity of the batch in the Cold Storage warehouse — never a stored counter. Cancellations and any native stock movements are reflected automatically.
3. Reservation is derived: Σ qty of MRs that are submitted, not stopped/cancelled, without a Stock Entry, bound to the WO. `create_request` re-validates availability under the Work Order row lock (same locking pattern as `finish()`).
4. The Stock Entry moves exactly Good Post-Packing of the linked batch. Reject/Trial/Sisa never move stock and never create adjustments.
5. Good must be finite, > 0, and ≤ requested; Good + Reject + Trial ≤ requested; Sisa is computed = requested − good − reject − trial. Whole-PCS rules for Pcs items follow the existing QtyInput/UOM contract.
6. Post-Packing is written once (Request Gudang → Siap Kirim). Cancel is allowed only before Post-Packing. Send requires Post-Packing and no existing SE against the MR.
7. Send is atomic in one request transaction: build SE from the MR (native builder), set qty = good, set the batch, submit, then stop the MR if good < requested. Failure rolls back with no partial documents.
8. Every action passes ordinary Frappe permission checks for the session user and the linked documents (company, warehouse, item, batch, MR). No `ignore_permissions`.
9. A WO with multiple Manufacture SEs/batches (legacy partial history) gets an explicit unsupported-action message with native links before any mutation — no silent flattening.
10. Do not edit ERPNext/Frappe core, do not duplicate or displace the `bakery_manufacturing` bundle override, do not hardcode warehouse names, do not rewrite historical documents.

## 5. Implementation sequence and gates

### Phase H1 — Prove the native path before building anything

On isolated test records: create an MR (Material Transfer) with from/to warehouses and the planned custom fields as a draft schema check; build the SE via native `make_stock_entry`; set the batch; submit; verify batch-wise stock movement Cold Storage → target, `ordered_qty`/MR status updates; stop and cancel paths; permission matrix as Gudang-role and Manufacturing-user test users; confirm the bakery override does not interfere with outward transfer rows.

Gate: executed proof of the request→send transaction and permissions, with unresolved business decisions recorded.

### Phase H2 — Metadata and server actions

`upgrade.py`: role, DocPerms, MR custom fields, warehouse-default setting (idempotent, snapshot first). `production_app/api/handover.py`: `handover_board` (lots FIFO + three request lanes + role flags + target warehouse), `create_request`, `cancel_request`, `save_post_packing`, `send_handover`. Integration tests covering the acceptance matrix below, including concurrency (two simultaneous requests; double send), permission denials, and rollback atomicity.

Gate: server correctness proven without UI; board derivation matches documents after each action and after native cancels.

### Phase H3 — Frontend

Mount `HandoverBoard.vue` from the mockup into the existing SPA (route `#/handover`, menu "Stock Entry", mobile bottom nav two destinations). Replace the role-simulation strip with server-provided roles; remove simulation controls. Role-based navigation: Gudang Barang Jadi sees only Stock Entry (and lands there); Manufacturing User sees Work Orders + Stock Entry as before. Wire dialogs to the API actions with loading, clear errors, pending-state disabling, refresh after success, input retention on recoverable failure.

Gate: interactive browser run of the full loop by both test roles; reload shows the same state.

### Phase H4 — Acceptance and handoff

Run the acceptance matrix, desk/mobile smoke with two test users, inspect diffs, record migration/rollback and remaining limitations. Clean up all test records.

## 6. Smallest sufficient acceptance matrix

| Scenario | Required proof |
|---|---|
| Create request | MR submitted with warehouses/box/work-order fields; full and partial qty; qty > available rejected with no writes; two racing requests cannot over-reserve |
| Post-Packing | Simple path (request = whole remaining) and full form; caps enforced; sisa auto-computed; WO mirror updated; repeat blocked |
| Send | Batch stock moves Cold Storage → target for exactly good qty; SE linked to MR; MR stopped when good < requested; MR left open (Transferred) when good = requested; duplicate send blocked |
| Cancel request | Only before Post-Packing; MR docstatus 2; reservation released; board updated |
| Permissions | Gudang role cannot send/post-pack/access WO actions; Manufacturing User cannot create/cancel MR; user without either role gets read-only or empty board per permission rules |
| Errors atomic | Insufficient batch stock, batch conflict, validation failure → zero partial documents/quantities |
| Board derivation | Lane mapping from documents only; FIFO order; reserved/available math; hint for older lot of same item |
| Native interactions | SE cancelled on desk → board recomputes (MR stays stopped; documented manual unstop path); native MR cancel/stop reflected |
| Legacy edge | WO with multiple batches → explicit unsupported message, no mutation |
| Boxes | Text identifiers persist and redisplay; empty values dropped; never parsed as numbers |

## 7. Agent execution boundaries

- This plan is planning output. Implementation starts only on an explicit user instruction; then work T21–T26 in order, one at a time, recording state in `PROJECT_STATE.md` per its protocol.
- Only `production_app` is touched; no core edits, no commits, no production deployment claims.
- Known limitation to document, not solve: after a native desk cancel of the SE, the stopped MR needs a manual desk unstop to become requestable again; the board must not resurrect it silently.

## ADDENDUM 2026-09-14 — Section G (STOCKENTRY_KANBAN_PLAN.md): WO-centric board, box kg, source setting

Supersedes the following §4/§6 rows for the implemented flow (contract: `STOCKENTRY_KANBAN_PLAN.md`, rulings R1–R8; evidence: PROJECT_STATE T31–T33):

- **Request (R3):** `create_request(work_order)` — qty is the WO's FULL `produced_qty` (no qty dialog; drag/click = direct action). Duplicate ACTIVE (unshipped, unstopped) request per WO blocked under the WO row lock. Availability guard unchanged (diminta/tersedia). §4 request-with-box and partial-qty matrix rows are obsolete.
- **Warehouses (R2):** new setting `custom_default_handover_source_warehouse` (Pengaturan input #6). When set it overrides the batchless pool resolution (`_item_stock` warehouse, `_reserved_by_item` keyed by the WO lot row) and the MR `from_warehouse`; batch-tracked lot identity and `get_batch_qty` stay SE-derived (batch seam untouched). When empty, previous SE-derived behavior applies. Reservation keying is WO-lot-based so MRs predating the setting still reserve.
- **Post-Packing → Verifikasi (R4/R5):** `save_post_packing(material_request, box_1, box_2)` — Box-only. Good/Reject/Trial/Sisa/QC/Jam are NOT asked or written by the board (they live on the WO Post-Packing stage, T27). Dialog is the mockup's "Verifikasi Siap Kirim" (Diminta + Hasil akhir WO context; Box 1/2 kg required in UI; server accepts optional finite ≥0).
- **Boxes (R8):** `custom_box_1/2` on Work Order AND Material Request are Float kg again (FU7 identifier semantics superseded by user request 2026-09-14). Migration NULLed all old text values (snapshot `snapshots/box-kg-pre.json`; 0 live rows had values). §6 "Boxes = text identifiers" row is obsolete.
- **Send (R1/R6):** `send_handover` moves qty = the MR's requested qty (== WO produced at request time) at posting time = the actual send moment; batch rows keep `batch_no`; the short-close/stop-MR branch is deleted (§6 "MR stopped when good < requested" row is obsolete — full-qty sends never stop).
- **Board:** Cold Storage cards show the WO's finished-goods qty ("Hasil WO", `produced_qty`) and `completed_at` (LATEST Manufacture posting, "Selesai …"); `entered_at` (earliest) remains the FIFO sort key. Board payload adds `source_warehouse`.
- Batch scalability: the WO→(batch | batchless pool) resolution in `_wo_lot_rows` stays the single seam; batch-tracked paths are unchanged, so enabling batch tracking on items requires no code change.

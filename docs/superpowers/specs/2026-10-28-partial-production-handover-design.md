# Partial production handover — design

Date: 2026-10-28
Status: Written specification approved by the user; autonomous local planning, implementation and review authorized. Commit, push, deployment and production mutation remain unauthorized. Real-database release verification remains open.

## Outcome and boundaries

Allow an explicitly confirmed GBJ request for available finished goods while preserving production output, legitimate other-destination requests, outstanding handover quantities, and existing batch identity. Work spans production_app and warehouse_app. No new fields, dependencies, stock ledger, automatic external-request cancellation, negative stock, or invented batchless provenance.

Historical incident: 43 selected WOs produced 1,096 Pcs; physical source stock 1,096; an unlinked R&D MR reserved 4; the first group allocations totalled 1,071 and the last WO requested 25 against 21 available. These are supplied historical findings, not refreshed live state.

## Verified local defects

- `production_app/api/handover.py:_reserved_by_item` derives board reservations from WO-linked requests; `_pool_reserved_now` includes external MRs but aggregates item-wide, not by source warehouse.
- `create_group_request` requires full produced_qty for every member and manually accumulates claims before inserting one multi-row MR.
- `_handover_state` marks every linked WO transferred when any submitted SE exists for its MR, regardless of row quantities.
- `send_handover` rejects any MR with a submitted SE and resets mapped quantities to original requested quantities rather than remaining quantities.
- warehouse_app picker `_active_request_map` uses the WO's single summary MR pointer and any-SE evidence; BoardPage disables remaining requests after any shipment.

Current group contract is one MR with a row per WO, not the older one-MR-per-WO plan. Older project documentation does not override current inspected code.

## Reservation and quantity model

All quantities below are stock-UOM quantities; display conversion is explicit and uses existing finite-factor and whole-UOM guards.

For each MR item, derive actual fulfillment from submitted linked Stock Entry Detail transfer quantities using material_request_item identity. Native ordered_qty is a consistency/reference field, not a reason to discard an entire partially fulfilled MR. Reservation is the nonnegative unfulfilled portion of a submitted, active Material Transfer request. Stopped, cancelled, and terminal completed requests contribute no outstanding reservation. Actual submitted transfers remain actual evidence even in abnormal cancelled-MR states. Cancelling an SE removes its transfer evidence and restores outstanding reservation only if its MR remains active.

For batchless pools, key reservations by item and the stored MR row source warehouse, falling back to the MR header source. Do not relocate historical reservations to a WO's current source setting. Requests with no resolvable source must be surfaced as unresolved rather than guessed into a pool. Include every destination and requests without WO links. Keep existing batch identity and native batch validation; do not allocate unlinked batchless demand to a batch or WO.

Pool availability = current physical source stock minus outstanding reservations. Transferred stock has already left physical stock and must not be subtracted again as a reservation. Board, preview, creation and transfer checks use compatible source-scoped semantics. Sending an existing request excludes its own outstanding reservation when checking protection for other requests.

Per WO, derive GBJ actual transfers, active outstanding linked requests, unrequested remainder and not-yet-transferred remainder across relevant history, not just the latest summary Link. Do not use produced minus all historical requested quantities: stopped/cancelled unfulfilled portions must be requestable again. Destination distinctions remain explicit; linked other-destination evidence is shown separately and cannot be relabelled GBJ. Unlinked external demand is pool-level only, never deducted from a particular WO's accounting as proven provenance.

## Preview, allocation and confirmation

Add an additive read-only preview API in production_app and optional explicit allocation confirmation on create_request/create_group_request. Existing callers without confirmation retain fail-honest full eligible-remainder requests; they never receive silent partial fulfillment. Preserve existing response keys and one-MR group structure.

Preview returns selected production output, eligible unrequested quantities, physical stock per source, outstanding reservation details including MR, destination, source and quantity, available new-request quantity, and proposed per-WO allocation. Reservation detail disclosure must respect native read permissions; inability to disclose a reference must not remove its quantity from availability. Indicate restricted details honestly.

Allocate proposed GBJ quantities in the backend's existing sorted WO-name order, bounded by each WO's eligible remainder and its source pool. Multiple source pools are budgeted separately, never with one item-wide claimed counter. Apply existing stock/display UOM validity rules to proposed allocations; do not round stock upward or silently discard an unrepresentable residual.

For the exact characterization, allocate 1,071 to preceding members and 21 to the last member, leaving 4 unrequested against that WO's unchanged output of 25. This is an administrative GBJ request allocation, not evidence that R&D consumed the last WO's output. Show this distinction and the row allocation before confirmation. Skip zero-allocation rows while preserving their outstanding quantities; fail if every allocation is zero.

Confirmation sends the displayed explicit row allocations and relevant preview context. Under existing ordered WO locks and pool protection, recompute history, source, target, UOM and availability. Reject changed/ineligible/over-budget allocations with a refresh-required error and zero writes; never lower the confirmed quantities automatically. Duplicate/replayed confirmation must not create another request. Keep existing active-request-per-WO protection; later remainder can be requested after the previous request completes or is stopped/cancelled appropriately.

## Transfer, cancellation and status

Use native MR-to-SE mapping for only still-unfulfilled MR rows. Preserve batch fields and native permissions, stock/valuation validation and atomicity. A previously partially fulfilled native MR may send its remaining rows/quantities; a completed MR rejects another send. Current locking rereads and deadlock retry must protect duplicate/concurrent sends, rather than blanket rejection based on any SE.

Use existing native stop/cancel operations. Do not implement partial cancellation by rewriting submitted request quantities or production output. Preserve group cancellation compatibility and prevent cancelling submitted transfer evidence through custom shortcuts.

WO fully transferred means its relevant cumulative GBJ actual transfer covers its production output, not that a partial request or SE exists. Retain existing summary Select values without migration: incomplete linked activity remains `Diminta Gudang`; use derived quantity payloads and partial labels for honest UI. A closed/stopped request with remaining WO output is not fully transferred. The summary Link remains navigation metadata, not the accounting source. Maintain fail-safe document-event mirrors without blocking unrelated native operations.

Warehouse and production boards display production output separately from requested, transferred and remaining quantities. Rows with eligible remainder remain discoverable/selectable after prior request completion, even if pool stock is currently zero; availability governs confirmation, not whether the obligation disappears. Partial rows must appear in a usable existing filter category with clear partial labels. Preserve current pagination contract; do not expand into unrelated pagination redesign.

## Scope

- production_app handover helpers, board, preview/create/send/cancel guards, summary derivation and direct frontend consumers of changed quantities/status.
- warehouse_app picker/history derivation, board adapter, individual/group confirmation dialogs, quantity/status/selection/filter presentation.
- Existing handover tests, warehouse gates/fixtures affected by the contract, frontend helper/UI tests and built assets according to repository conventions.
- No core edits or cross-app Python imports in warehouse_app production code.

## Verification and safety

Write failing regression tests before product changes. Retain an exact 43-WO fixture totalling 1,096 with preceding sum 1,071 and last output 25; do not reinterpret 21/25 as UOM conversion factors.

Required coverage: external unlinked reserve 4 gives preview and backend 1,092; explicit partial then eligible remainder; different source does not reserve this pool; partial/completed/stopped/cancelled MR; row-level partial fulfillment in bulk MR; no double deduction after transfer; changed preview; duplicate create/send and real concurrent transactions; WO status and visibility with remainder; full handover and batch regression; display-UOM validity; permissions on reservation details.

Pure unit tests and mocked UI tests can run without a site. They do not prove SQL isolation, rollback, SLE integrity or concurrency. Identify a verified disposable test site before integration tests; existing restored sites are unsafe by default. Do not create a production request for reproduction. Production access, if needed, is read-only and uses approved environment credentials without printing secrets.

Preserve ordered locks and CURRENT rereads. Native external MR submission does not demonstrably share the custom Item lock; inspect and test this boundary on the installed test runtime. Do not claim global serialization or add a native behavior-changing hook without separate approval. Document any residual race boundary and block release if required safety cannot be demonstrated.

## Deployment and outstanding gates

No schema migration is planned. Existing persisted WO summaries may need an explicitly authorized document-derived resynchronization after deployment; do not run it as part of local tests. Deploy matching backend and frontend builds together and refresh cached clients. Historical MR/SE and produced quantities remain untouched.

The user approved the written specification and explicitly requested autonomous planning, implementation and review through dynamic workflows, without repeated plan-approval prompts. Commit and push remain separately gated; this specification is not committed. Record active task state without untracking or wholesale rewriting the existing tracked, oversized PROJECT_STATE.md files. Validate installed test runtime and local tooling rather than relying on historical environment descriptions. Local mock tests/builds do not close the real-database release gate.

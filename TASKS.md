# Work Order implementation tasks

Business contract: `IMPLEMENTATION_PLAN.md`. Progress and evidence: `PROJECT_STATE.md`.
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

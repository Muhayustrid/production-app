# Partial production handover — local proof (2026-10-29)

**Status: RELEASE BLOCKED / UNCOMMITTED / NOT DEPLOYED.**

The dedicated native sandbox demonstrated overreservation by an external native Material Request: physical10, custom request10 accepted, external request4 accepted afterward, outstanding14. Custom locks do not provide a global native reservation guarantee. No native behavior-changing hook was added; that requires separate authorization. Production was not mutated and historical MREQ-MTR-26-0655 was not cancelled or modified.

## Scope and runtime

Working trees:
- `/Users/rotiropi/erpnext-new/apps/production_app`
- `/Users/rotiropi/erpnext-new/apps/warehouse_app`

Authorized disposable project: `partial-handover-test`; site `partial-handover-test.localhost`; company `Partial Proof` (`PHP`). Frappe16.52.0, ERPNext16.51.1, Python3.14.8, MariaDB11.8, REPEATABLE-READ. Installed apps: frappe, erpnext, production_app, warehouse_app. Negative stock remains0. No workers/scheduler or HTTP server were started. No browser E2E was run.

All sites/logs/database/cache/queue volumes are new `partial-handover-test_*` volumes, not existing dev/prod/restore volumes. The dedicated Docker network is not configured `internal:true`; network egress is not claimed to be blocked. Credentials stay in the ignored dedicated environment file and are not reproduced here. Resources are preserved, not pruned/deleted.

Local-only operator files:
- `/Users/rotiropi/ERPNext-Project/docker/compose.partial-handover-test.yaml`
- `/Users/rotiropi/ERPNext-Project/docker/.env.partial-handover-test`
- `/Users/rotiropi/ERPNext-Project/docker/partial-handover-proof.py`

The proof script is a stateful phase runner, with existing-document IDs in later phases. It is **not** an idempotent fresh-site test suite. Do not blindly rerun historical phases after their documents have been transferred/cancelled. Failed assertions after explicit commits leave those sandbox documents available for inspection.

## Business characterization demonstrated with native documents

Native fixture setup used real Company/Item/Warehouse/BOM/Work Order and Manufacture documents, with legitimate raw-material fixture receipt inside this new sandbox only. No fake produced_qty, direct SLE edits, balancing receipts or negative-stock override were used. Setup required native Indonesia fixtures, Fiscal Year2026 and sandbox batch support. ERPNext emitted batch deprecation warnings.

1. 43 submitted WOs/Manufactures: first21 output26 each, next22 output25 each, total1096. First42 total1071; lastWO `MFG-WO-2026-00043` output25.
2. Unlinked R&D MR `MAT-MR-2026-00001`, source `Proof Source - PHP`, target `Proof RD - PHP`, qty4.
3. Preview physical1096, outstanding4, available1092; preceding allocations1071, last21, last unrequested remainder4.
4. Explicit group confirmation produced one43-row MR `MAT-MR-2026-00002`.
5. Native partial SE10 on the first MRI; remaining reservations1086 = custom1082 + R&D4. Custom send created `MAT-STE-2026-00046` for1082. Source4 and reserve4. LastWO actual21 was not labelled fully transferred.
6. This exposed a real preview bug: remainder was25 instead of4 after transfer. Unit RED→GREEN changed remainder from produced−allocation to eligible−allocation.
7. Cancelling the **sandbox** R&D fixture released4; explicit request `MAT-MR-2026-00003` and send4 completed the lastWO, source0 and summary `Terkirim`. This is test setup, not a proposed production remediation.

These figures reproduce supplied historical inputs; no new production snapshot was obtained.

## Other native proofs

| Check | Observed result |
|---|---|
| Duplicate create, two independent DB processes/barrier | One accepted, one stale-preview ValidationError. Latest fixture WO50/MR11, physical10/reserve10 before sandbox cancellation. |
| Duplicate send, two independent processes | One SE accepted (`MAT-STE-2026-00056`), second completed-request rejection. Source0. |
| Partial fulfillment, stop/reopen/cancel, SE cancel | MRI3 from `Proof Other - PHP`; native transfer1 leaves reserve2; SE cancel restores3; stop0, reopen3, MR cancel0. Source pool unaffected. MR10/SE59. |
| Batch single flow | WO49/batch `PHP-BATCH-00001`, request/send5, SE58, source0/target5. Native batch fields preserved. |
| Cancellation summary | Real LinkExistsError exposed cancelled MR Link surviving on WO. Cancelled/no-transfer state now releases summary Link; native cancel succeeded after fix. |
| Protection of other reserve at send | physical10, own10, external4: original send10 succeeded (test rolled back), then patched guard rejected with no new SE. Later duplicate-send test cancelled that sandbox external request to exercise valid send. |
| Final actual-MRI remainder | WO51/MR12: native transfer2 from request5, deliberately oversized mapped5 rejected with no new SE; valid custom send3 completed WO. |
| Final batch isolation | Native batch WO52 moved out by native transfer without fulfilling GBJ; WO53 has another batch5 at source. Preview allocates WO52=0, WO53=5, rather than borrowing the other batch. |

`final-regression` first encountered a runner TypeError because installed native mapper returns a StockEntry document, not a subscriptable dict. The already committed partial fixture was identified read-only and reused. Runner corrected; final outputs:

```text
FINAL_PARTIAL_PASS {"work_order":"MFG-WO-2026-00051","material_request":"MAT-MR-2026-00012","remainder_sent":3.0}
FINAL_BATCH_PREVIEW_PASS {"empty_batch_work_order":"MFG-WO-2026-00052","available_batch_work_order":"MFG-WO-2026-00053","allocations":{"MFG-WO-2026-00052":0.0,"MFG-WO-2026-00053":5.0}}
```

The mapper guard was subsequently tightened in local code to reject undersized as well as oversized mapped remainders; focused unit RED→GREEN covers3 vs actual4 and25 vs actual4. Native source-copy verification after the final suite is recorded below when run.

## Concrete release blocker: native external MR boundary

The two-process ordered test lets custom create commit10, then lets native external MR submit4 in a fresh transaction. Both succeed. This is a valid ordering, independent of earlier simultaneous-run deadlocks:

```text
EXTERNAL_ORDERED_STATE {"handover_request":"MAT-MR-2026-00007","physical":10.0,"reserved":14.0}
AssertionError: ('NATIVE_EXTERNAL_RACE_OVERRESERVED', 10.0, 14.0)
```

Earlier simultaneous attempts encountered MariaDB1213 deadlock and tabSeries1020 under an old snapshot. Those were not counted as safety proof; retrying the native transaction exposed the accepted overreservation. `_retry_on_deadlock` uses up to three immediate retries after rollback; there is **no exponential backoff/jitter**.

Protection at custom send does not prevent native MR creation. No schema, durable idempotency table, global native reservation service or native hook was introduced. Do not release with a claim that external/native concurrency is safe.

## Independent final review and fix pass

One read-only independent reviewer assessed the whole patch. Six important findings were validated and fixed locally:

1. Derive own outstanding reserve from submitted linked SED per MRI/source, not mapped qty. Reject native mapping drift before insert.
2. Bound preview allocations by actual batch availability; unsupported lot history allocates0, never another batch's stock.
3. Include company in warehouse picker payload so different companies do not group accidentally.
4. Bind fingerprint to company, target, batch, stock/display UOM and conversion, plus physical/reserved/available pool context. Per-row token also binds its relevant pool. Tokens remain16 hex characters; no persistent nonce/schema added.
5. Empty row source falls back to header through NULLIF; unresolved source reservations are disclosed separately and permission-masked, without assigning warehouse/WO provenance.
6. Production coldLots retains eligible unrequested remainder even at pool availability0.

An additional fail-closed regression showed `_lots` counted other-destination transfers when target was unset; it now returns no GBJ transfer evidence in that configuration.

RED→GREEN evidence is in the focused tests and local ledger `.superpowers/sdd/2026-10-28-partial-production-handover/progress.md`. The VM visibility test executes the real declaration; dialog tests execute compiled SFC setup control flow. These are not browser tests. Template disclosure checks are structural, not rendered-accessibility proof.

## Fresh local checks

Focused Python command runs the two test modules with the explicit local `frappe_stub`, target repos prepended to sys.path, and cwd `/tmp`. This avoids importing the unrelated local bench package from the session cwd. The initial naive discovery command failed imports; it was not counted as a product failure or pass.

```text
production_app/tests/test_partial_handover_unit.py: 28 tests
warehouse_app/tests/test_partial_picker.py: 7 tests
Ran 35 tests
OK
```

```bash
node --test /Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend/tests/*.test.mjs
node --test /Users/rotiropi/erpnext-new/apps/warehouse_app/frontend/tests/*.test.mjs
npm --prefix /Users/rotiropi/erpnext-new/apps/production_app/workspace_frontend run build
npm --prefix /Users/rotiropi/erpnext-new/apps/warehouse_app/frontend run build
```

- Production Node121/121; warehouse compiled-dialog5/5.
- Vite7.3.6 production build:1985 modules,2.41s.
- Vite5.4.21 warehouse build:1993 modules,2.01s; www postbuild updated.
- Both builds emit >500kB chunk warnings; not warning-free.
- Both `git diff --check` passed after focused Python changes.
- Logs: `/tmp/partial-review-node.log`, `/tmp/partial-review-production-build.log`, `/tmp/partial-review-warehouse-build.log`.

### Existing native action suite (not app-wide)

```bash
docker exec -w /home/frappe/frappe-bench partial-handover-test-backend-1 \
  bench --site partial-handover-test.localhost run-tests --app production_app \
  --module production_app.tests.test_handover_actions --skip-before-tests
```

First invocation was disabled by site configuration (no tests executed). Enabled allow_tests on the dedicated site only. Next invocation failed setUpClass because sandbox lacked Pack UOM (0 tests). Added native Pack fixture on the dedicated site.

First full run: **50 tests,19 pass,4 fail,26 errors,1 skipped** in122.850s. All26 errors are IndexError in the old fixture's Batch.reference_name=WO lookup; installed native batches derive from Manufacture bundle, not that reference. Four failures: duplicate-send message, duplicate-create message, cancelled-request message, and a shared-item pool fixture expected40 but actual33 because prior native reservations were previously ignored. Corrected fixture lookup to actual Manufacture bundle, isolated that test's pool, and changed message assertions without weakening quantity/document checks.

Second run: **50 tests,45 pass,1 fail,3 errors,1 skipped** in173.592s (`/tmp/partial-review-native-actions-final.log`). Fixed a test wrapper missing the company keyword and the remaining duplicate-create message assertion. Two obsolete tests attempted another full production handover after fully transferring output and moving stock back; rewritten to legitimate partial30 → send30 → request remaining30, without replacement stock moves.

Third run: **50 tests,48 pass,1 error,1 skipped** in165.199s (`/tmp/partial-review-native-actions-current.log`). The remaining error was real: cancelling an unsent remainder after an earlier partial transfer retained the cancelled MR as the WO summary Link, causing native LinkExistsError. A focused regression failed for both partial30/60 and completed60/60 history. The resolver now selects a submitted MR with actual SE evidence for transferred-history navigation, or no Link when no such candidate exists; it never uses the cancelled remainder as that Link. Focused suite is now **36 pass** (production29 + picker7).

Final native rerun: **50 tests,49 passed,1 skipped,0 failures/errors** in178.179s, exit0 (`/tmp/partial-review-native-actions-verified.log`). The skipped test is `test_bulk_group_request_rejects_mixed_company`: this dedicated site has only one Company. The previously failing cancelled-remainder lifecycle now passes, as do partial re-request, batch, cancellation, permission-matrix and atomic shortage tests in this selected module. This is not the full app-wide suite and does not close the demonstrated external-native reservation blocker. Host/container SHA256 parity verified for the exact source under test:
- `production_app/api/handover.py`: `c49338c6271811435703c17cdba0de83adf84759af6f11c980cf4a8f033373c2`.
- `production_app/tests/test_handover_actions.py`: `e57d5e4a5be92ac3233e6b919f79c25cd464ebb0e41824196fe00aeaff4325f4`.

Fresh Node rerun: production121 pass and warehouse5 pass, no failures/skips (`/tmp/partial-review-node-verified.log`). Both working-tree `git diff --check` commands also passed.

## Continuation 2026-10-29: broad modules, browser E2E, final-source races

The hashes above were superseded by the fixes below. Final host/container SHA256 parity (all MATCH):
- `production_app/api/handover.py`: `d8c62d0c808695ac483cf97442f5a01eaa912e584126e612c1a4040ae6e37bd6`.
- `production_app/tests/test_handover_actions.py`: `e57d5e4a5be92ac3233e6b919f79c25cd464ebb0e41824196fe00aeaff4325f4` (unchanged).
- `production_app/tests/test_handover_board.py`: `6a033f544f6aa8dc5a4a978ab8f790489523cb1326e2b344535a8086fef8b426`.
- `warehouse_app/warehouse_app/gudang_request.py`: `f3438e80190bd2ee1d711c69be8c8b5cc2ae9b58c8fa94dea5363b59b57275cb`.

Broad native run (`/tmp/partial-app-suite-20261029.log`): the 21 local `production_app/tests/test_*.py` modules (stub unit module excluded; image-only modules not run), one process per module. 12 exit0; 9 exit1:
- `test_handover_board` — now fixed, see below.
- `test_dashboard` (2 errors: native `validate_work_order_status_for_return` rejects returns for non-Completed/Closed WOs), `test_docperm_matrix` and `test_handover_setup` (2 errors) (setUp `upgrade.apply` → native validation refuses editing the archived Workspace Sidebar), `test_form_order` (fixture UOM conversion <= 0 rejected natively), `test_warehouse_defaults_live`, `test_wo_finish_duplicate_rm`, `test_wo_skip_prepacking`, `test_wo_transaction_proof` (setUpClass helper finds no WO matching its config query although 53 submitted WOs exist). These are in untouched code/fixtures; no baseline A/B was run, so "pre-existing" is not proven. Not fixed (outside this task).

Board module fixes (18 tests: initially 12 pass, 2 fail, 4 errors):
- Fixture batch lookup moved from `Batch.reference_name` to the Manufacture SED → Serial and Batch Entry join (4 errors).
- `test_t31_batchless_pool_follows_source_setting`: old expectation moved historical MR reserve into the newly configured pool; the approved spec keeps the recorded source. Assertion corrected.
- Product bug: a fully fulfilled MR row forced to abnormal docstatus 2 lost its `terkirim` lane in `_requests`. Fixed (cancelled + done_qty > 0 + outstanding <= 0 → terkirim); observed request lane None before, terkirim after.
- `test_t35`: a 40/100 WO is no longer asserted as fully Terkirim; asserts actual 40 and remainder 60. Its lot read is target-scoped, and the sandbox global target is `Proof GBJ - PHP` while the fixture sends to its own target; the board read is now pinned with `_pin_settings(handover_warehouse=self.target_wh)` (fixture fix; destination filter kept).
- Final: **18/18 OK** in 29.676s.

Browser E2E (local Chrome via installed Playwright, `channel: 'chrome'`, private storage state; HTTP `bench serve` on 127.0.0.1:18083 of the dedicated site only):
- `/gudang` rendered native data; no page/console errors. Row selection via checkbox shows `Create Request (2)` for WO-00052/00053 (PHP-BATCH).
- Preview dialog (`/tmp/partial-handover-preview-batches.png`, inspected): WO-00053 5 Nos, WO-00052 0 Nos (sisa 5); API matched native batch proof.
- Submit exposed a real bug: `create_group_request` called `_checked_lot` before skipping a 0-allocation member, so a depleted-batch member aborted the whole group (417 "tidak punya lot tersedia"). Fix: lot check runs after the zero skip. Regression `test_create_group_request_skips_zero_allocation_member_without_lot` RED (early check restored) → GREEN.
- After restarting the server on the fixed code: MAT-MR-2026-00013 created with one row WO-00053 qty 5 (`/tmp/partial-handover-browser-create.png`); WO-00052 stays Ready without a link; no browser errors.

Final-source concurrency (`docker/partial-handover-proof.py`, fresh fixtures, separate processes, barrier):
- `race-create` on new WO-00054 (10): one accepted (MAT-MR-2026-00014), other rejected by stale fingerprint; reserve 10.
- `race-final`: overlapping groups {WO-00055, WO-00056} vs {WO-00056, WO-00057}: one accepted (MAT-MR-2026-00015), other stale-rejected; reserve 20 <= physical 50, one active row per WO. Duplicate send of MAT-MR-2026-00015: one SE (MAT-STE-2026-00071, 20), other rejected as already transferred; reserve back to 0.

Final checks on this source: native actions **50 tests, 49 pass, 1 skip** (183.022s); board **18/18**; focused stub **37 pass** (production 30 + picker 7); Node production 121 pass, warehouse 5 pass; both `git diff --check` OK.

## Remaining limits and decisions

- RELEASE BLOCKED: demonstrated native external overreservation, not merely an untested possibility.
- Full native permission integration and the 8 non-handover broad-module failures above are not proven/fixed. Production workspace browser smoke not run.
- Minor (deferred, pre-existing in HEAD): RequestDialog result title reads "Partially created" even when every request succeeded.
- Mixed selections submitted individually fail closed if a preceding request changes the same pool fingerprint; retry requires fresh preview. This can reduce bulk completion, not silently lower confirmed quantities.
- Unresolved-source demand is disclosed without reducing a guessed pool. Global fulfillment safety cannot be guaranteed for requests with absent source.
- Persisted production WO summary resynchronization remains a separately authorized deployment action.
- Existing tracked oversized PROJECT_STATE histories were not truncated/untracked. Only current task entries were replaced.
- No commit, push, deployment, existing-stack mutation or production write performed. Sandbox volumes retained intentionally.

## Continuation 2026-10-29: native external MR guard (blocker closed in bench copy)

Authorized by the user ("perbaiki celahnya"). Work moved to the dev image source
`/Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/production_app`; **this erpnext-new copy is now
stale** (no ab7f44b merge, no test-mock fix, no guard).

- New `doc_events` Material Request `before_submit` → `handover.guard_pool_reservation`: for Material Transfer
  rows drawn from the configured handover source warehouse and without `custom_work_order`, reject when
  requested stock qty > Bin actual_qty − active pool reservations (self excluded: still docstatus 0). Same
  Item row lock (`for update`) as create_request. Handover rows are skipped (already guarded by create /
  create_group_request; a first version that also checked them double-counted and broke 2 tests).
- RED: `test_native_mr_cannot_overreserve_pool` (physical 10, handover 10, native 4) — ValidationError not raised.
  GREEN after the hook. Free-stock native MR (4 before the handover) still accepted.
- Sandbox: native actions 52 tests OK (1 skip), board 18/18, focused stub 37 OK, `git diff --check` OK.
- `external-ordered` proof: native worker rejected ("diminta 4.0, tersedia 0.0"), physical 10 / reserved 10
  (first rerun hit a leftover sandbox fixture MR holding the pool; that sandbox MR was cancelled and rerun).
- `race-external` (simultaneous): create accepted, native got MariaDB 1213 deadlock and rolled back;
  physical 20 / reserved 20. A retried native submit then meets the guard.
- Dev rebuilt; backend/queue-short/scheduler hashes match host (handover.py `452c744cdf8c`, hooks.py
  `506353e49b32`); hook registered; read-only dev check: 0 over-reserved pool items.
- Limit: reopening a Stopped MR (`update_status`) does not run submit hooks and is not guarded.

## Browser E2E 2026-10-29 (Playwright, 4 parallel agents)

Sandbox `partial-handover-test.localhost` (current image), one fresh item per scenario; dev read-only.
Screenshots/scripts: `/tmp/phb/{s1,s2,s3,dev}` (local, not kept).
- S1 (E2E-R1-A, 2 WO x 10): desk R&D MR 4 accepted (MR-00023). /gudang group preview: physical 20,
  reserved 4, available 16, alloc 10 + 6 (sisa 4) with external-reservation notice; one MR-00024 (2 rows, 16).
  Late desk R&D MR 1 rejected "diminta 1.0, tersedia 0.0", stays Draft. Final: Source 20 = 4 + 16 reserved.
- S2 (E2E-R1-B, 1 WO x 10): /gudang request 10 (MR-00020); desk R&D MR 4 rejected "tersedia 0.0", Draft;
  /production_workspace send -> SE-00085 (10 to GBJ), MR Transferred.
- S3 (E2E-R1-C, existing R&D MR-00019 for 4): preview physical 10 / reserved 4 / alloc 6 / sisa 4; MR-00021 (6)
  sent SE-00083; R&D cancelled in desk; second preview 4 -> MR-00022 sent SE-00084; WO Shipped, GBJ 10.
- Dev read-only (write routes blocked): /gudang, preview dialog cancelled, handover board, MR list, settings
  source "Cold Storage Produksi - JURI"; zero blocked writes attempted.
- UX note: while a partial request is open, /gudang shows "Requested"; "Partial (N left)" appears only after
  the first transfer (one active request per WO).
- Sandbox side effect: an agent set Installed Application frappe `is_setup_complete = 1` (sandbox only) to
  open desk forms.

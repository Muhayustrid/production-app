# Stock Entry Three-Lane Handover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four-lane finished-goods handover with `Cold Storage -> Request Gudang -> Terkirim`, collecting validated Box kg and whole-Pack allocations on Work Order before creating the native Material Request.

**Architecture:** Native Material Request and Stock Entry documents remain authoritative for lanes and audit history. `Material Request Item.custom_work_order` remains the historical relation; one Work Order Link plus four box summary fields are controlled materialized state written atomically behind the existing Work Order lock. The existing bulk batch lookup, scoped action validation, and single final board rebuild from commit `8e104b9` remain mandatory.

**Tech Stack:** Frappe/ERPNext v16, Python whitelisted APIs, MariaDB transactions, Vue 3/Vite SPA, Node built-in test runner, Docker runtime `erpnext-new-backend-1`, site `frontend`.

**Spec:** `docs/superpowers/specs/2026-09-16-stock-entry-three-lane-handover-design.md`

## Global Constraints

- Work only on `feat/three-lane-handover`, whose base must remain branch `N` commit `891d00b4d4aa31afacc37bf79be0e4a140026fc5`.
- Do not edit ERPNext/Frappe core, duplicate the `bakery_manufacturing` batch override, add a business DocType, add a dependency, or create another workflow/state store.
- Do not add Pack fields to Material Request. Retain all existing MR fields and historical data, but stop writing MR box/post-packing fields in the new flow.
- Box 1/2 kg and Box 1/2 Pack are Work Order summary fields. Box 1 must be positive; Box 2 may be exactly `0 kg / 0 Pack`, otherwise both values must be positive.
- `Box 1 Pack + Box 2 Pack` must equal the integral Pack count computed on the server from the full requested stock quantity and the raw, valid Pack conversion factor.
- Board lanes derive from native documents. Work Order Link and `custom_handover_status` are summaries and never authorize a lane or stock movement.
- Lock order for every mutation is Work Order first, then Item only for a batchless shared pool; native MR/SE work follows under that boundary. Do not introduce an MR-to-WO lock inversion.
- Preserve `_batch_quantities` as one ERPNext v16 query pair, scoped `_wo_lot_rows`/`_requests`, `_checked_lot` without `_build_board`, and exactly one full board build after each successful mutation.
- Migration is snapshot-first and idempotent. Sync runtime code before the first live `upgrade.apply`; never expose new metadata to an old writer.
- Use ordinary permissions for Material Request and Stock Entry. No `ignore_permissions`. The role-gated API may use controlled `db_set`/`frappe.db.set_value` for read-only Work Order summary fields because warehouse users deliberately lack broad Work Order write permission.
- Do not mutate operational documents in tests. Use isolated prefixed fixtures and prove cleanup residue is zero.
- Keep one active task in `PROJECT_STATE.md`. Record actual commands/results; a skipped check is `NOT RUN`, never `PASS`.
- Do not commit or push. At each task gate, save a diff/report under `.superpowers/sdd/THREE_LANE_HANDOVER/` and keep the working tree reviewable.

---

## File Structure

- Modify `production_app/upgrade.py`: additive Work Order fields, snapshot/backfill/status-option migration, idempotent apply ordering.
- Modify `production_app/api/handover.py`: three-lane derivation, Work Order summary mapping, Pack/box validation, create/cancel/send contracts, compatibility stub, fail-safe summary synchronization.
- Modify `production_app/tests/test_handover_setup.py`: metadata, snapshot, ordered migration, idempotency, and permissions assertions.
- Modify `production_app/tests/test_handover_board.py`: three-lane derivation, submitted-SE precedence, bulk Work Order box mapping, legacy MR fallback, and existing performance seams.
- Modify `production_app/tests/test_handover_actions.py`: validation, atomic summary writes, cancellation, send, retries, roles, batch/batchless behavior, and compatibility calls.
- Modify `production_app/tests/test_handover_native_proof.py`: retain native MR->SE and metadata compatibility coverage.
- Modify `production_app/tests/test_wo_transaction_proof.py`: Work Order field round-trip and read-only/allow-on-submit contract.
- Create `workspace_frontend/src/handover-box.js`: pure client presentation/validation helper for expected Packs and box allocation.
- Create `workspace_frontend/tests/handover-box.test.mjs`: runnable checks for the pure helper.
- Modify `workspace_frontend/src/store.js`: three-lane payload adapter and new `createRequest(workOrder, boxes)` signature; remove supported calls to `save_post_packing`.
- Modify `workspace_frontend/src/HandoverBoard.vue`: three lanes, request form, direct Request->Terkirim action, cancellation, and responsive display.
- Modify `workspace_frontend/tests/handover-card.test.mjs`: box kg/Pack display contract.
- Modify `TASKS.md`, `PROJECT_STATE.md`, and `HANDOVER_PLAN.md`: execution tasks, evidence, final addendum, migration/rollback notes.
- Generated by the existing Vite build: `production_app/public/workspace/assets/index.js` and `production_app/public/workspace/assets/index.css`.

---

### Task 0 / T34: Preflight, Baseline, and Execution Ledger

**Files:**
- Modify: `TASKS.md` after T33
- Modify: `PROJECT_STATE.md:3-10`, task board, and work log
- Create: `.superpowers/sdd/THREE_LANE_HANDOVER/progress.md`
- Create: `.superpowers/sdd/THREE_LANE_HANDOVER/task-34-report.md`

**Interfaces:**
- Consumes: branch `N` at `891d00b`, the approved spec, the Docker runtime, the five existing backend suites.
- Produces: dependency-ordered tasks T34-T38, verified host/container mapping, a before-change test result, and a warm board benchmark used by T38.

- [ ] **Step 1: Verify branch ancestry and preserve unrelated state**

Run:

```bash
git branch --show-current
git rev-parse HEAD
git rev-parse N
git merge-base --is-ancestor N HEAD
git status --short
```

Expected: current branch is `feat/three-lane-handover`; `HEAD` and `N` are `891d00b4d4aa31afacc37bf79be0e4a140026fc5`; ancestry exits zero; only the approved `docs/` work is untracked before execution-document edits.

- [ ] **Step 2: Verify runtime and host-to-container mapping**

Run:

```bash
docker ps --format '{{.Names}}' | grep -E '^erpnext-new-(backend|frontend)-1$'
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend list-apps'
shasum -a 256 production_app/api/handover.py
docker exec erpnext-new-backend-1 sha256sum /home/frappe/frappe-bench/apps/production_app/production_app/api/handover.py
```

Expected: both containers are running; `production_app`, `erpnext`, and `bakery_manufacturing` are installed. If host/container hashes differ before edits, record the difference and use the proven `docker cp` synchronization procedure; do not assume a bind mount.

- [ ] **Step 3: Add execution tasks to the project ledger**

Append section H to `TASKS.md`:

```markdown
## H. Stock Entry three-lane handover

Business contract: `docs/superpowers/specs/2026-09-16-stock-entry-three-lane-handover-design.md`.
Implementation plan: `docs/superpowers/plans/2026-09-16-stock-entry-three-lane-handover.md`.

### T34 — Preflight, baseline, and execution ledger
Depends on: none.
Acceptance: branch/base/runtime verified; five suites pass once before edits; warm board query/time baseline recorded.

### T35 — Server metadata, three-lane derivation, and atomic actions
Depends on: T34.
Acceptance: ordered migration applies twice; server tests cover fields, lanes, validation, cancellation, send, permissions, retry, batch/batchless, and compatibility.

### T36 — Performance and concurrency gate
Depends on: T35.
Acceptance: FU34 query-shape tests pass; concurrent create/send produce at most one document; comparable warm benchmark has no material regression.

### T37 — Three-lane frontend and local asset deployment
Depends on: T36.
Acceptance: frontend tests/build pass; three-lane bundle is deployed and hash-identical at all served points; old Siap/verify path is absent.

### T38 — End-to-end acceptance and handoff
Depends on: T37.
Acceptance: five backend suites pass twice, HTTP and browser matrices pass, fixture residue is zero, docs and rollback are complete.
```

Update `PROJECT_STATE.md` so T34 is the only `IN_PROGRESS` task and add a work-log entry with the branch/base/spec/plan paths.

- [ ] **Step 4: Run the five backend suites once before edits**

Run each module in the backend container:

```bash
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_handover_setup'
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_handover_board'
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_handover_actions'
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_handover_native_proof'
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_wo_transaction_proof'
```

Expected: all five modules pass. Record exact test counts. A pre-existing failure blocks implementation until its cause is separated from this feature.

- [ ] **Step 5: Record a comparable warm query/time baseline**

Run `handover_board()` once to warm metadata, then five measured calls as Administrator while wrapping the bound `frappe.db.sql` method with a counter. Use `time.perf_counter()`, roll back after measurement, and record for each call: elapsed seconds, SQL count, lot count, request count, and serialized payload bytes. Use the same script unchanged in T36.

Acceptance thresholds for T36:

```text
query_count_after <= query_count_before + 2
median_time_after <= max(median_time_before * 1.20, median_time_before + 0.050 seconds)
payload growth is explained only by the new Link/box Pack keys
```

The historical `0.141 seconds / 28 queries` is context; the before-change result on the current dataset is the comparison baseline.

- [ ] **Step 6: Close T34 and save evidence**

Write `.superpowers/sdd/THREE_LANE_HANDOVER/task-34-report.md` with actual commands/results, update `PROJECT_STATE.md` to T34 `DONE` and T35 `IN_PROGRESS`, then run:

```bash
git diff --check
git diff HEAD -- TASKS.md PROJECT_STATE.md docs/superpowers > .superpowers/sdd/THREE_LANE_HANDOVER/task-34.diff
```

Do not commit.

---

### Task 1 / T35: Server Metadata, Three-Lane Derivation, and Atomic Actions

**Files:**
- Modify: `production_app/upgrade.py:30-66, 91-153, 816-862`
- Modify: `production_app/api/handover.py:43-45, 58-74, 142-323, 326-487, 519-758, 799-1137`
- Modify: `production_app/tests/test_handover_setup.py`
- Modify: `production_app/tests/test_handover_board.py`
- Modify: `production_app/tests/test_handover_actions.py`
- Modify: `production_app/tests/test_handover_native_proof.py`
- Modify: `production_app/tests/test_wo_transaction_proof.py`
- Create after first migration: `snapshots/three-lane-handover-pre.json`
- Create: `.superpowers/sdd/THREE_LANE_HANDOVER/task-35-report.md`

**Interfaces:**
- Consumes: current `_enrich_units`, `_checked_lot`, `_requests`, `_sent_se_by_mr`, native MR `make_stock_entry`, Work Order-first lock ordering, role constants.
- Produces:
  - `create_request(work_order, box_1=None, box_1_pack=None, box_2=0, box_2_pack=0)`
  - unchanged `cancel_request(material_request)` and `send_handover(material_request)` names with three-lane semantics
  - compatibility `save_post_packing(...)` that always rejects before locking/writing
  - board request rows with `box_1`, `box_1_pack`, `box_2`, `box_2_pack`
  - Work Order fields `custom_handover_material_request`, `custom_box_1_pack`, `custom_box_2_pack`
  - status options `Diminta Gudang` and `Terkirim` only

#### T35A — Write RED metadata and migration tests

- [ ] **Step 1: Add failing field-contract assertions**

In `test_handover_setup.py`, assert after `upgrade.apply()`:

```python
wo_meta = frappe.get_meta("Work Order", cached=False)
expected = {
    "custom_handover_material_request": ("Link", "Material Request"),
    "custom_box_1_pack": ("Int", None),
    "custom_box_2_pack": ("Int", None),
}
for fieldname, (fieldtype, options) in expected.items():
    df = wo_meta.get_field(fieldname)
    self.assertIsNotNone(df)
    self.assertEqual(df.fieldtype, fieldtype)
    self.assertEqual(df.options or None, options)
    self.assertTrue(df.allow_on_submit)
    self.assertTrue(df.read_only)

for fieldname in ("custom_box_1", "custom_box_2"):
    self.assertTrue(wo_meta.get_field(fieldname).read_only)

self.assertEqual(
    wo_meta.get_field("custom_handover_status").options,
    "\nDiminta Gudang\nTerkirim",
)
```

Also assert the migration result is unchanged on the second apply, and the snapshot contains the old status options plus distinct kg/status values.

- [ ] **Step 2: Run the metadata test and verify RED**

Run:

```bash
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_handover_setup --test test_t22_apply_idempotent_and_drift_reconciled'
```

Expected: failure because the three new fields do not exist and `Siap Kirim` is still an option.

#### T35B — Write RED three-lane/read-model tests

- [ ] **Step 3: Replace four-lane expectations with document precedence tests**

In `test_handover_board.py`, add/adjust checks so:

```python
self.assertEqual(request_row["lane"], "request")
self.assertNotIn("siap_kirim", {r["lane"] for r in board["requests"] if r["lane"]})
```

Create a legacy MR with `custom_postpacking_confirmed=1` and no SE; it must still be `request`. Create a submitted SE, then force the MR to the test-only abnormal `docstatus=2`; both `_requests` and `_handover_lanes` must still return `terkirim`. A cancelled MR without SE must have `lane=None`, `flag="cancelled"`.

Add a bulk summary test with two WOs/MRs:

```python
wo1.db_set("custom_handover_material_request", mr1.name)
wo1.db_set("custom_box_1", 12.5)
wo1.db_set("custom_box_1_pack", 20)
wo1.db_set("custom_box_2", 8.0)
wo1.db_set("custom_box_2_pack", 19)
row = self._req(handover_board(), mr1.name)
self.assertEqual((row["box_1"], row["box_1_pack"]), (12.5, 20))
self.assertEqual((row["box_2"], row["box_2_pack"]), (8.0, 19))
```

For a pre-cutover MR whose WO Link is empty, assert kg falls back to existing MR kg fields while both Pack values remain empty. Patch `frappe.db.get_value` for Work Order inside request-row mapping and assert no per-card Work Order lookup occurs.

- [ ] **Step 4: Run the board tests and verify RED**

Run:

```bash
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_handover_board'
```

Expected: failures for the legacy confirmed lane, submitted-SE precedence, and missing Work Order summary keys.

#### T35C — Write RED action tests

- [ ] **Step 5: Give successful fixtures an explicit Pack conversion**

Update action-test Items used by successful request creation so their Item default display UOM is exactly `Pack` and their Item UOM conversion factor is `5`. Do not use the presentation fallback factor. Update `_request` to send a valid one-box allocation by default:

```python
def _request(self, wo, box_1=10, box_1_pack=None, box_2=0, box_2_pack=0):
    packs = box_1_pack if box_1_pack is not None else int(flt(wo.produced_qty) / 5)
    frappe.set_user(self.gudang)
    try:
        return create_request(
            wo.name,
            box_1=box_1,
            box_1_pack=packs,
            box_2=box_2,
            box_2_pack=box_2_pack,
        )
    finally:
        frappe.set_user("Administrator")
```

Create a separate Item with no Pack conversion for rejection tests.

- [ ] **Step 6: Add failing validation and atomicity cases**

Cover all of these with exact zero-write assertions (`Material Request Item` count and Work Order summary before/after):

```text
create_request(work_order) from an old cached client -> Indonesian validation error, zero writes
missing/default UOM not Pack -> error, zero writes
missing/zero/non-finite conversion -> error, zero writes
produced qty 7 with factor 5 -> fractional Pack error, zero writes
Box 1 kg <= 0 or Pack <= 0 -> error, zero writes
Box 2 (0 Pack, positive kg) or (positive Pack, 0 kg) -> error, zero writes
negative, fractional, NaN, or infinite Pack input -> error, zero writes
Box Pack sum below/above expected -> error, zero writes
```

Cover valid one-box and two-box writes:

```python
result = self._request(wo, box_1=12.5, box_1_pack=12, box_2=8.25, box_2_pack=8)
summary = frappe.db.get_value(
    "Work Order", wo.name,
    ["custom_handover_material_request", "custom_box_1", "custom_box_1_pack", "custom_box_2", "custom_box_2_pack"],
    as_dict=True,
)
self.assertEqual(summary.custom_handover_material_request, result["material_request"])
self.assertEqual((flt(summary.custom_box_1), summary.custom_box_1_pack), (12.5, 12))
self.assertEqual((flt(summary.custom_box_2), summary.custom_box_2_pack), (8.25, 8))
mr = frappe.get_doc("Material Request", result["material_request"])
self.assertFalse(mr.custom_postpacking_confirmed)
self.assertEqual(flt(mr.custom_box_1), 0)
```

Add cancellation checks: app cancel and native unsent Desk cancel clear Link plus four box fields; sent handover retains them. `save_post_packing` must raise the compatibility message and mutate neither MR nor WO. `send_handover` must not require `custom_postpacking_confirmed`.

- [ ] **Step 7: Run action tests and verify RED**

Run:

```bash
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend run-tests --app production_app --module production_app.tests.test_handover_actions'
```

Expected: failures from the old signature, old writer, `siap_kirim`, and absent Work Order summary fields.

#### T35D — Implement the minimum metadata/migration contract

- [ ] **Step 8: Add the Work Order field specs**

In `WORKSPACE_FIELDS`, keep existing fieldnames and use this order:

```python
_field(
    "custom_box_1", "Box 1 (kg)", "Float", "custom_leader_produksi",
    allow_on_submit=1, read_only=1, non_negative=1,
    description="Berat Box 1 (kg) untuk request serah terima aktif/terakhir",
),
_field(
    "custom_box_1_pack", "Box 1 (Pack)", "Int", "custom_box_1",
    allow_on_submit=1, read_only=1, non_negative=1,
),
_field(
    "custom_box_2", "Box 2 (kg)", "Float", "custom_box_1_pack",
    allow_on_submit=1, read_only=1, non_negative=1,
    description="Berat Box 2 (kg) untuk request serah terima aktif/terakhir",
),
_field(
    "custom_box_2_pack", "Box 2 (Pack)", "Int", "custom_box_2",
    allow_on_submit=1, read_only=1, non_negative=1,
),
_field(
    "custom_handover_material_request", "Material Request Serah Terima", "Link",
    "custom_box_2_pack", options="Material Request", allow_on_submit=1,
    read_only=1, print_hide=1,
),
```

Change `custom_handover_status` insertion to follow the Link and set options to `"\nDiminta Gudang\nTerkirim"`.

- [ ] **Step 9: Add one ordered migration function**

Create `THREE_LANE_SNAPSHOT = snapshots/three-lane-handover-pre.json` and an idempotent `ensure_three_lane_handover()` that:

1. snapshots the affected Custom Field definitions/options and distinct live values once;
2. assumes `ensure_app_fields(create_only=True)` has already created missing fields without changing options on existing fields;
3. bulk-resolves handover MRs through `Material Request Item.custom_work_order`;
4. selects submitted-SE evidence first even if the MR is abnormally cancelled, otherwise the newest submitted non-cancelled MR;
5. backfills only an empty `custom_handover_material_request` and never invents Pack allocations;
6. resynchronizes every linked WO plus every WO currently holding `Siap Kirim` while that option remains valid;
7. verifies no WO retains `Siap Kirim`;
8. only then lets the later full `ensure_app_fields()` call remove `Siap Kirim` from the Select options, while returning stable `created/updated/unchanged` evidence.

Wire it in `apply()` after `ensure_app_fields(create_only=True)` and before the final `ensure_app_fields()`:

```python
result = {"fields": ensure_app_fields(create_only=True), "leader": "unchanged"}
result["three_lane_handover"] = ensure_three_lane_handover()
# existing type migrations
result["fields"] = ensure_app_fields()
```

Do not execute live `apply()` yet; finish the server writer first.

#### T35E — Implement one shared three-lane state derivation

- [ ] **Step 10: Remove `LANE_SIAP` from active logic**

Keep only:

```python
LANE_REQUEST = "request"
LANE_KIRIM = "terkirim"
HANDOVER_STATUS_LABEL = {
    LANE_REQUEST: "Diminta Gudang",
    LANE_KIRIM: "Terkirim",
}
```

In `_requests`, use precedence:

```python
if se:
    lane = LANE_KIRIM
elif m.docstatus == 2:
    flag = "cancelled"
elif m.docstatus == 0:
    flag = "draft"
elif m.status == "Stopped":
    lane, flag = LANE_REQUEST, "stopped"
else:
    lane = LANE_REQUEST
```

In `_handover_lanes`, evaluate `m.name in sent` before checking `docstatus`; otherwise include only submitted MRs as Request. Remove `custom_postpacking_confirmed` from lane decisions and remove all `(LANE_REQUEST, LANE_SIAP)` reservation/duplicate/pool checks in favor of `r["lane"] == LANE_REQUEST` with the existing flag rules.

- [ ] **Step 11: Bulk-map Work Order summary fields**

Add these fields to the existing `_wo_lot_rows` Work Order query:

```python
"custom_handover_material_request",
"custom_box_1", "custom_box_1_pack",
"custom_box_2", "custom_box_2_pack",
```

Copy them to each lot row. In `_requests`, use Work Order values only when `lot.custom_handover_material_request == m.name`; otherwise fall back to MR kg values and leave Pack values empty. This mapping must use `wo_by_name` only and perform no Work Order lookup inside the MR loop.

- [ ] **Step 12: Extend fail-safe synchronization to the summary Link**

Implement one internal state resolver reused by `_handover_lanes` and summary synchronization so lane and Link precedence cannot drift. Keep `sync_handover_status(wo_names)` as a compatibility entry point, but make it synchronize status plus Link. Clearing rules:

```text
unsent current MR cancelled and no replacement -> clear Link and all four box values
submitted SE still exists -> keep Link and box values, status Terkirim
another submitted request exists -> point Link to the selected request; do not invent Pack values
```

`sync_from_material_request` and `sync_from_stock_entry` remain fail-safe wrappers that catch/log errors. Direct application actions call the internal synchronizer fail-honestly inside their transaction after the native mutation.

#### T35F — Implement strict Pack/box validation and action changes

- [ ] **Step 13: Add server validation helpers**

Use the raw fields populated by `_enrich_units`; never use `qty_in_pack` because it has an `or 1` display fallback.

```python
def _expected_pack_count(wo, lot, amount):
    factor = flt(lot.display_conversion_factor)
    if lot.display_uom != "Pack" or not math.isfinite(factor) or factor <= 0:
        frappe.throw(_("Item {0} belum memiliki konversi Pack yang valid.").format(wo.production_item))
    precision = wo.precision("produced_qty") or 3
    raw = amount / factor
    expected = round(raw)
    tolerance = 0.5 * (10 ** (-precision))
    if abs(raw - expected) >= tolerance:
        frappe.throw(_("Hasil Work Order {0} tidak membentuk Pack utuh.").format(wo.name))
    return int(expected)


def _whole_pack(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        frappe.throw(_("{0} harus bilangan Pack bulat.").format(label))
    if not math.isfinite(number) or number < 0 or number != int(number):
        frappe.throw(_("{0} harus bilangan Pack bulat non-negatif.").format(label))
    return int(number)
```

Use a finite kg parser and one `_validate_box_allocation(...)` helper that enforces Box 1 positive, Box 2 `0/0` or positive/positive, and exact Pack sum.

- [ ] **Step 14: Change `create_request` to own the box form**

Change the signature to:

```python
@frappe.whitelist()
def create_request(work_order, box_1=None, box_1_pack=None, box_2=0, box_2_pack=0):
```

Under the existing WO lock and optional Item lock:

1. derive the scoped lot and active requests;
2. compute/validate expected Packs and all box fields before writes;
3. preserve stock/UOM/warehouse checks;
4. create and submit the native MR without writing any MR box/post-packing custom field;
5. atomically `db_set` the MR Link and four Work Order box values;
6. fail-honestly synchronize summary/status;
7. return MR, qty, expected Pack count, box values, and one final `_build_board()`.

Do not manually commit. Any failure after MR insertion must roll back at the Frappe request transaction boundary.

- [ ] **Step 15: Change cancellation, send, and compatibility behavior**

For `cancel_request`:

- resolve the WO from `Material Request Item.custom_work_order`;
- lock the WO first, then re-read MR and submitted SE evidence;
- remove the `custom_postpacking_confirmed` cancellation guard;
- reject if a submitted SE exists;
- native-cancel MR, then fail-honestly synchronize Link/status/box clearing;
- return one final board.

For `send_handover`:

- resolve and lock WO before mutable MR work;
- remove the `custom_postpacking_confirmed` requirement;
- preserve native builder, route warehouse stock precheck, batch/batchless handling, duplicate-SE protection, and exact MR quantity;
- preserve Work Order Link/boxes and synchronize `Terkirim` after submit;
- return one final board.

Replace `save_post_packing` body with a compatibility rejection before any lock/write:

```python
frappe.throw(_(
    "Verifikasi Siap Kirim sudah dipindahkan ke form Request Gudang. "
    "Muat ulang halaman sebelum melanjutkan."
))
```

#### T35G — Sync, migrate, and turn RED tests GREEN

- [ ] **Step 16: Sync all writer and migration code before live apply**

Copy `upgrade.py`, `api/handover.py`, and changed tests to the backend app path, then set ownership to `frappe:frappe`. Verify host/container hashes match. Do not copy metadata alone ahead of the writer.

- [ ] **Step 17: Run ordered migration twice**

Run:

```bash
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend execute production_app.upgrade.apply'
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site frontend execute production_app.upgrade.apply'
```

Expected: first run writes `snapshots/three-lane-handover-pre.json`, creates/backfills fields, clears live `Siap Kirim` values through document derivation, then removes the option. Second run reports convergence and does not rewrite correct Links/values.

Verify read-only:

```text
all three new Work Order fields exist with the specified types/options
all five summary fields are read-only and allow-on-submit
custom_handover_status options contain no Siap Kirim
zero Work Orders retain custom_handover_status = Siap Kirim
MR field definitions and values are unchanged
```

- [ ] **Step 18: Run targeted server suites until GREEN**

Run setup, board, and actions modules. Then run native proof and Work Order transaction proof. Expected: all pass, including old FU34 query-shape tests and bakery/native batch tests.

- [ ] **Step 19: Verify permission and zero-write paths**

Explicitly confirm:

```text
warehouse role: create/cancel allowed; send/compat verify denied or rejected
production role: send allowed; create/cancel denied
bare user: all mutations denied
old cached create_request(work_order): zero MR and unchanged WO summary
all validation failures: zero MR and unchanged WO summary
```

- [ ] **Step 20: Close T35 and save evidence**

Update `PROJECT_STATE.md` to T35 `DONE`, T36 `IN_PROGRESS`; write the report with migration output, field readback, test counts, and rollback notes. Save:

```bash
git diff --check
git diff HEAD -- production_app/upgrade.py production_app/api/handover.py production_app/tests snapshots TASKS.md PROJECT_STATE.md > .superpowers/sdd/THREE_LANE_HANDOVER/task-35.diff
```

Do not commit.

---

### Task 2 / T36: Performance and Concurrency Gate

**Files:**
- Modify if a failure is reproduced: `production_app/api/handover.py`
- Modify: `production_app/tests/test_handover_board.py`
- Modify: `production_app/tests/test_handover_actions.py`
- Create: `.superpowers/sdd/THREE_LANE_HANDOVER/task-36-report.md`

**Interfaces:**
- Consumes: T35 server contract and T34 benchmark script.
- Produces: measured proof that summary fields add no fan-out and concurrent creates/sends remain single-document operations.

- [ ] **Step 1: Add an explicit no-fan-out regression test**

Patch the bulk seams around `_wo_lot_rows` and `_requests` for multiple WOs and assert:

```text
get_available_batches call count = 1
get_stock_ledgers_batches call count = 1
_checked_lot never calls _build_board
no Work Order get_value/get_doc occurs inside the per-MR mapping loop
new Link/kg/Pack fields are present from the single bulk Work Order result set
```

Retain the current FU34 parity test for Stock Reservation Entry behavior.

- [ ] **Step 2: Add real concurrent request coverage**

Use two independent HTTP sessions or two isolated Frappe request contexts against the same fixture WO, synchronized to call `create_request` with the same valid box allocation. Expected result:

```text
one response succeeds
one response fails with the existing active-request reference
exactly one submitted MR is linked to the WO
WO Link points to that MR
box summary is one complete allocation, never mixed
```

For a batchless pool, run two different WOs of the same Item whose combined requests exceed available stock. The Work Order -> Item lock order must allow only the valid reservation total.

- [ ] **Step 3: Add concurrent duplicate-send coverage**

Call `send_handover` concurrently for one MR as two production sessions. Expected: exactly one submitted Stock Entry; the loser receives the duplicate-send validation; WO Link/boxes remain intact; board is Terkirim.

- [ ] **Step 4: Run performance/concurrency tests**

Run `test_handover_board` and `test_handover_actions` twice. Treat deadlock, lock timeout, duplicate MR/SE, or partial summary as a blocker.

- [ ] **Step 5: Repeat the T34 warm benchmark unchanged**

Use the same user, current dataset, warm-up, five measurements, SQL wrapper, and payload calculation. Gate:

```text
SQL count <= T34 count + 2
median elapsed <= max(T34 median * 1.20, T34 median + 0.050 seconds)
no query count that grows with card count
```

If the gate fails, profile the additional calls and repair the bulk/scoped seam; do not cache stale board state or remove correctness checks.

- [ ] **Step 6: Close T36 and save evidence**

Record before/after numbers and concurrency document counts, update state to T36 `DONE` and T37 `IN_PROGRESS`, then save the server diff snapshot. Do not commit.

---

### Task 3 / T37: Three-Lane Frontend and Local Asset Deployment

**Files:**
- Create: `workspace_frontend/src/handover-box.js`
- Create: `workspace_frontend/tests/handover-box.test.mjs`
- Modify: `workspace_frontend/src/store.js:384-490`
- Modify: `workspace_frontend/src/HandoverBoard.vue`
- Modify: `workspace_frontend/tests/handover-card.test.mjs`
- Modify only if the 390 px smoke proves it necessary: `workspace_frontend/src/styles.css`
- Generated: `production_app/public/workspace/assets/index.js`
- Generated: `production_app/public/workspace/assets/index.css`
- Create: `.superpowers/sdd/THREE_LANE_HANDOVER/task-37-report.md`

**Interfaces:**
- Consumes: T35 board keys and action signatures.
- Produces: exactly three lanes; a warehouse-owned request form with four inputs; Request->Terkirim send; box kg/Pack display; no supported `save_post_packing` caller.

- [ ] **Step 1: Write failing pure-helper tests**

Create `handover-box.test.mjs` with these cases:

```javascript
assert.equal(expectedPacks({ displayUom: 'Pack', qtyInPack: 6, producedQty: 234 }), 39)
assert.equal(expectedPacks({ displayUom: null, qtyInPack: null, producedQty: 234 }), null)
assert.equal(expectedPacks({ displayUom: 'Pack', qtyInPack: 6, producedQty: 235 }), null)
assert.deepEqual(validateBoxAllocation(
  { box1: '12.5', box1Pack: '39', box2: '0', box2Pack: '0' }, 39
), {})
assert.ok(validateBoxAllocation(
  { box1: '12.5', box1Pack: '38', box2: '8', box2Pack: '0' }, 39
).box2)
```

Also test a valid two-box split and below/above Pack totals.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench/apps/production_app/workspace_frontend && node --test tests/*.test.mjs'
```

Expected: module-not-found for `handover-box.js`.

- [ ] **Step 3: Implement the pure helper**

Create exports:

```javascript
export function expectedPacks(lot) { /* returns non-negative integer or null */ }
export function validateBoxAllocation(form, expected) { /* returns field-keyed errors */ }
export function boxAllocationText(row) { /* kg + Pack summary */ }
```

`expectedPacks` accepts only `displayUom === 'Pack'`, finite factor `> 0`, and an integral quotient. This is a UX check only; server validation remains authoritative.

- [ ] **Step 4: Update the store adapter**

Map new payload values:

```javascript
box1: r.box_1,
box1Pack: r.box_1_pack,
box2: r.box_2,
box2Pack: r.box_2_pack,
```

Change the action adapter:

```javascript
export function createRequest(workOrder, v) {
  return handoverAction('create_request', {
    work_order: workOrder,
    box_1: Number(v.box1),
    box_1_pack: Number(v.box1Pack),
    box_2: Number(v.box2),
    box_2_pack: Number(v.box2Pack)
  })
}
```

Remove `savePostPacking` from supported exports/imports. Keep server errors unwrapped so the form can retain input.

- [ ] **Step 5: Reduce the board to three lanes**

Use only:

```javascript
const lanes = [
  { key: 'cold', title: 'Cold Storage', icon: Snowflake, empty: 'Belum ada lot' },
  { key: 'request', title: 'Request Gudang', icon: ClipboardList, empty: 'Belum ada request' },
  { key: 'kirim', title: 'Terkirim', icon: CheckCircle2, tone: 'ok', empty: 'Belum ada terkirim' }
]
```

Delete `siapCard`, `siap` filtering, `LANE_SIAP` drag targets, and the verification dialog. Request cards are production-sendable and warehouse-cancellable. For a multi-role user, the choice is `Batalkan Request` or `Kirim ke Gudang`.

- [ ] **Step 6: Move the box form to Cold Storage -> Request**

Click/drop a Cold Storage card opens a request dialog rather than immediately calling the API. Initialize:

```javascript
{ box1: '', box1Pack: '', box2: '0', box2Pack: '0' }
```

Show Work Order, Item, MR preview text (`dibuat setelah disimpan`), requested/output quantities in Pack and PCS, and the four inputs. Disable submit when conversion is invalid, field validation fails, or `handoverState.pending` is set. On API failure, keep the dialog and all input values. On success, close only after the server board replaces local state.

Remove the optimistic pending-request card path; user-entered form state must remain visible until success/failure is known.

- [ ] **Step 7: Update card and send summaries**

Use `boxAllocationText` for Request and Terkirim cards and the send confirmation, for example:

```text
Box 1: 12.5 kg · 20 Pack
Box 2: 8 kg · 19 Pack
```

The send dialog uses requested MR quantity, native document references, and Work Order summary values. It never reads MR post-packing confirmation.

- [ ] **Step 8: Run frontend tests and build**

Run:

```bash
docker exec erpnext-new-backend-1 bash -lc 'cd /home/frappe/frappe-bench/apps/production_app/workspace_frontend && node --test tests/*.test.mjs && yarn build'
```

Expected: all tests pass and Vite emits the existing fixed asset names.

- [ ] **Step 9: Deploy assets locally using the proven five-point procedure**

Copy changed frontend source into the backend app, build there, copy generated `index.js`/`index.css` to:

1. host repository `production_app/public/workspace/assets/`;
2. backend `sites/assets/production_app/workspace/assets/`;
3. frontend container `sites/assets/production_app/workspace/assets/`.

Restart backend because Python whitelist code changed earlier. Verify identical hashes at build output, host public assets, backend served assets, frontend served assets, and HTTP `http://localhost:8081/assets/production_app/workspace/assets/index.js`.

Bundle markers:

```text
present: Box 1 (Pack), Box 2 (Pack), Buat Request Gudang
absent: Siap Kirim lane title, Verifikasi Siap Kirim dialog action, supported save_post_packing call
```

- [ ] **Step 10: Close T37 and save evidence**

Record test/build counts, hashes, marker checks, and any CSS change justified by the 390 px layout. Update state to T37 `DONE`, T38 `IN_PROGRESS`; save the frontend diff. Do not commit.

---

### Task 4 / T38: End-to-End Acceptance and Handoff

**Files:**
- Modify: `HANDOVER_PLAN.md` with a final three-lane addendum
- Modify: `TASKS.md` task statuses/evidence
- Modify: `PROJECT_STATE.md` current handoff and final work log
- Create: `.superpowers/sdd/THREE_LANE_HANDOVER/task-38-report.md`
- Create only as ignored test support: `.superpowers/sdd/THREE_LANE_HANDOVER/fixtures/` helpers/manifest without credentials

**Interfaces:**
- Consumes: T35 server, T36 performance/concurrency evidence, T37 deployed SPA.
- Produces: complete acceptance evidence, clean fixture teardown, migration/rollback instructions, and a reviewable branch with no production deployment.

- [ ] **Step 1: Run all five backend suites twice from a fresh worker**

Run the five T34 module commands twice after restarting the backend. Record exact counts for both runs. Any intermittent failure blocks completion.

- [ ] **Step 2: Run frontend tests and production build once more**

Run `node --test tests/*.test.mjs` and `yarn build`; verify generated/served hashes still match and marker checks still pass.

- [ ] **Step 3: Build isolated HTTP fixtures**

Create prefixed test-only batch-tracked and batchless Items, each with valid `Pack` conversion, Work Orders with Manufacture output, dedicated source/WIP/cold/target warehouses, and users for warehouse, production, multi-role, and bare roles. Snapshot all six Manufacturing Settings warehouse values before overriding handover source/target. Store credentials only in a temporary ignored file and delete it during cleanup.

- [ ] **Step 4: Execute the real HTTP action matrix**

Using the same cookie/CSRF flow as the SPA, prove:

```text
warehouse create one-box request -> MR submitted, WO Link/boxes set
warehouse create two-box request -> exact Pack sum and distinct values persist
old cached create without boxes -> Indonesian error, zero writes
invalid sum/pair/fractional Pack/missing conversion -> zero writes
warehouse cancel -> native MR cancelled, reservation and WO summary cleared
production send directly from Request -> one native SE, exact MR qty, Link/boxes retained
legacy custom_postpacking_confirmed MR -> Request lane, sendable
batch row -> correct batch/bundle; batchless row -> correct pool movement
role denials for warehouse/production/bare users
duplicate create and duplicate send -> no second document
reload -> same server-derived board
```

Run concurrent create and send requests in this HTTP driver and retain document-count proof.

- [ ] **Step 5: Verify native Desk interactions**

On isolated records:

```text
native unsent MR cancel -> board returns Cold Storage and clears summary
native SE cancel -> request returns to Request Gudang; Link/boxes remain
abnormal cancelled-MR/submitted-SE fixture -> board/status remain Terkirim and summary remains
recovery order -> cancel SE first, then cancel/clear unsent MR state
```

Do not alter operational MRs/SEs to perform these checks.

- [ ] **Step 6: Run controller-owned browser smoke**

Desktop and `390x844` checks:

1. warehouse login lands on Stock Entry and sees exactly three lanes;
2. click and drag Cold Storage both open the four-input request form;
3. invalid Box 2 pairing and Pack sum show inline errors without losing input;
4. valid one-box and two-box submissions create Request cards;
5. production user sends Request directly to Terkirim;
6. multi-role chooser offers cancel/send, not verification;
7. Terkirim shows MR, SE, kg, Pack, and timestamp;
8. reload preserves server truth;
9. lane scroller, dialog inputs, actions, and bottom navigation remain usable at 390 px.

Capture screenshots or DOM evidence. If browser tooling cannot dispatch interactions, record the exact limitation as `NOT RUN`; automated/HTTP checks do not replace this gate.

- [ ] **Step 7: Repeat final performance benchmark**

Run the unchanged T34/T36 benchmark after the browser/HTTP fixture state is settled. Record query count and median. The T36 thresholds still apply.

- [ ] **Step 8: Clean every fixture and prove residue zero**

Restore all six Manufacturing Settings values first, cancel/delete test SEs then MRs/WOs/BOMs/Items/Warehouses/Users in native dependency order, remove temporary credentials/helpers, clear cache, and query every fixture prefix. Required result: zero users, items, warehouses, WOs, MRs, SEs, batches, bundles, SLEs, and BOMs; settings match the pre-test snapshot.

- [ ] **Step 9: Document migration and rollback**

Add a final `HANDOVER_PLAN.md` addendum covering:

```text
three-lane precedence and roles
new Work Order fields and MR historical relation
ordered migration and legacy behavior
Pack/box validation
native MR->SE path
performance guard and measured result
```

Rollback procedure:

1. revert app/frontend code and rebuild/resync assets;
2. keep additive Work Order fields unless a deliberate data migration exports their values first;
3. restore field definitions/options from `snapshots/three-lane-handover-pre.json` only after converting live `Diminta Gudang/Terkirim` summaries deliberately;
4. never blindly drop Link/Pack columns or rewrite historical MR/SE documents;
5. native test documents are cancelled/deleted in SE -> MR -> WO order.

- [ ] **Step 10: Run final audits**

Run:

```bash
git diff --check
git status --short
git diff --name-only HEAD
```

Verify no file under ERPNext/Frappe core changed, no dependency manifest changed, no credentials are present, no production deployment is claimed, and only scoped app/docs/generated assets/snapshot files changed.

- [ ] **Step 11: Complete state and final review**

Mark T38 `DONE` only when every required gate has evidence. Update `PROJECT_STATE.md` with commands/results, remaining limitations, rollback, and `Next action: STOP`. Save the final whole-branch diff/report under `.superpowers/sdd/THREE_LANE_HANDOVER/`. Do not commit or push.

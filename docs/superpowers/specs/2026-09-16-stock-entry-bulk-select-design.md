# Stock Entry Kanban bulk select design

Status: product decisions approved in conversation on 2026-09-16. Transaction design revised after safety review.

## 1. Goal

Allow operators to select multiple cards on the Stock Entry Kanban and run the lane's existing business action without combining ERPNext documents or weakening per-document validation.

The feature covers these active lanes:

- Cold Storage → create Material Requests.
- Request Gudang → cancel requests for gudang-side users or verify Box weights for produksi users.
- Siap Kirim → create and submit Stock Entries.
- Terkirim stays read-only.

Selection is limited to one source lane at a time. A mixed selection across lanes is not supported.

## 2. Product decisions

Confirmed decisions:

- Entry into bulk mode uses a toolbar button labelled **Pilih**.
- Cold Storage, Request Gudang, and Siap Kirim support bulk actions.
- The first selected card locks the selection to its lane.
- Processing is partial-success: one failed card does not undo successful cards.
- Box 1 and Box 2 are entered separately for every selected Request Gudang card.
- Each selected card continues to create or mutate its own native ERPNext document. There is no combined Material Request or combined Stock Entry.

Implementation decisions:

- Maximum 20 selected cards per bulk run. This is the authoritative browser-orchestrator limit for the initial synchronous implementation; the single-card server endpoint intentionally has no multi-card session to count.
- `Pilih semua di halaman` selects only eligible cards visible on the current rendered page and in the locked lane.
- Failed cards remain selected after the final board refresh only when they are still eligible in the original source lane.
- Successful cards are always cleared from selection, even when the same Material Request appears in a later lane.
- Cards are processed sequentially in input order.
- Each card uses a separate HTTP request and therefore a separate Frappe database transaction. This is required for durable partial success and native transaction-callback safety.

## 3. User experience

### 3.1 Selection mode

The Stock Entry toolbar gains a **Pilih** button. Pressing it enables selection mode.

In selection mode:

- Eligible cards display a checkbox affordance.
- The first selected card establishes `selectedLane`.
- Cards in other lanes are dimmed and cannot be selected until the selection is cleared.
- Terkirim cards never become selectable.
- A sticky bulk action bar shows the selected count, `Pilih semua di halaman`, `Kosongkan`, `Batal`, and permitted action buttons.
- The UI refuses a twenty-first card and explains the 20-card limit.
- Leaving selection mode clears all selection and unsaved bulk form values.

Eligibility means all of the following:

- the card is currently rendered;
- its lane has an action for the session role flags;
- the card is `live`, supported, not stopped, and not already pending;
- the bulk selection is empty or locked to the card's lane.

The gudang side is any user for whom the board returns `is_gudang`, which includes `Gudang Barang Jadi` or native `Stock User`.

Normal card click and drag/drop behavior remains unchanged outside selection mode. In selection mode, clicking an eligible card toggles selection and does not open its normal dialog.

### 3.2 Role-aware actions

| Selected lane | Gudang side (`Gudang Barang Jadi` or `Stock User`) | Produksi (`Manufacturing User`) | User with both sides |
|---|---|---|---|
| Cold Storage | Buat Request Gudang | unavailable | Buat Request Gudang |
| Request Gudang | Batalkan Request | Verifikasi Siap Kirim | both buttons, user chooses one |
| Siap Kirim | unavailable | Kirim Barang | Kirim Barang |
| Terkirim | unavailable | unavailable | unavailable |

Eligibility is presentation guidance only. The server rechecks roles and document permissions for every selected card.

### 3.3 Confirmation dialogs

#### Cold Storage

Show a compact list of selected Work Orders and total card count. Confirm button: **Buat N Request Gudang**.

#### Request Gudang — cancel

Show Material Request and Work Order references for every selected card. Confirm button: **Batalkan N Request**.

#### Request Gudang — verify

Show one responsive row or mobile panel per selected request:

- Work Order
- Material Request
- product and requested quantity
- optional Box 1 (kg)
- optional Box 2 (kg)

Blank Box inputs map to the current stored-zero convention. Supplied values must be finite and non-negative. Every supplied value is validated client-side before processing starts; existing server validation remains authoritative per card.

#### Siap Kirim

Show Material Request, Work Order, quantity, batch when applicable, and route warehouse warning when present. Confirm button: **Kirim N Barang**.

### 3.4 Processing feedback

While the bulk run is active:

- selected cards show pending treatment;
- all other handover actions are disabled;
- cards are not moved optimistically;
- the action bar reports progress, for example `3 dari 8 diproses`.

After all card requests finish:

- the client loads the full board once;
- successful cards are removed from selection;
- failed cards stay selected only if they remain actionable in the original source lane;
- failures that moved lane, became stopped, disappeared, or became ineligible are cleared;
- a result dialog reports `N berhasil, M gagal`;
- each expected failure displays its Work Order or Material Request and a translated user-facing server message;
- **Coba lagi yang gagal** is available when failed cards remain actionable.

If an infrastructure failure aborts the run, entries after the uncertain in-flight card are tracked as `unprocessed`, not `failed`. The result reports `N berhasil, M gagal, K belum diproses`. The uncertain in-flight reference and all unprocessed references cannot be retried until the board reload completes. After reload, unprocessed cards stay selected only when they remain eligible in the original lane; the uncertain in-flight reference is reconciled strictly from server truth before it can be selected again.

If the final board reload fails, committed card results are not lost. The UI shows the result summary plus `Papan gagal dimuat. Muat ulang untuk melihat data terbaru.` and offers a reload action.

## 4. Transaction architecture

### 4.1 Why one HTTP request is not used

Database savepoints inside one Frappe request do not create independent transactions. A late error, request rollback, or savepoint-unaware transaction callback could undo or contaminate earlier apparent successes. Therefore the bulk feature must not process several native submissions inside one request transaction.

### 4.2 Per-card transaction boundary

The browser sends one request per card, sequentially. Each request is committed or rolled back by Frappe independently before the next card begins.

Sequence:

1. Validate the complete client-side selection and optional Box inputs.
2. For each selected entry in stable input order:
   - call the single-card bulk action endpoint;
   - wait for its HTTP result before starting the next entry;
   - record success or expected failure locally.
3. Call `handover_board` once after all entries complete.
4. Reconcile selection against the original source lane and show the result summary.

Sequential execution is deliberate:

- a successful batchless request changes the shared pool before the next request validates;
- lock duration is limited to one card transaction;
- there is no new multi-card deadlock order;
- a browser interruption leaves already committed documents truthful and visible after reload.

## 5. Server contract

Add one whitelisted single-card dispatch endpoint in `production_app/api/handover.py`:

```python
bulk_handover_item(action, entry)
```

Despite its name, this endpoint accepts exactly one card. The browser orchestration provides the bulk behavior.

Allowed actions:

- `create_request`
- `cancel_request`
- `save_post_packing`
- `send_handover`

Input examples:

```json
{
  "action": "create_request",
  "entry": {"work_order": "MFG-WO-..."}
}
```

```json
{
  "action": "cancel_request",
  "entry": {"material_request": "MAT-MR-..."}
}
```

```json
{
  "action": "save_post_packing",
  "entry": {
    "material_request": "MAT-MR-...",
    "box_1": 12.5,
    "box_2": 8.25
  }
}
```

```json
{
  "action": "send_handover",
  "entry": {"material_request": "MAT-MR-..."}
}
```

The endpoint response is the existing action-specific payload without `board`. Examples include `material_request`, `qty`, `box_1`, `box_2`, `stock_entry`, and `batch` where the current single action returns them.

The endpoint does not accept lane, quantity, warehouse, batch, role, or status from the browser.

## 6. Shared action refactor

Extract the mutation portion of each existing endpoint into internal helpers:

- `_create_request(work_order)`
- `_cancel_request(material_request)`
- `_save_post_packing(material_request, box_1, box_2)`
- `_send_handover(material_request)`

Each helper returns the exact existing action payload minus `board`.

Whitelisted single endpoints retain their current signatures and exact response shapes:

- call the shared helper once;
- append one full `board` payload;
- return all existing action-specific fields unchanged.

`bulk_handover_item` strictly validates `action` and `entry`, dispatches to the allowlisted helper once, and returns its boardless payload. It never calls another whitelisted endpoint over HTTP and never uses `ignore_permissions`.

### 6.1 Handover Material Request invariant

Before any cancel, verify, or send mutation, the shared Material Request loader must establish:

- `material_request_type == "Material Transfer"`;
- `docstatus == 1`;
- exactly one item row;
- exactly one non-empty `custom_work_order` binding;
- non-empty and internally consistent source/target route fields required by the action.

The loader continues to apply normal document read permission. Action helpers apply their existing write, cancel, create, and submit permissions.

### 6.2 Locking and rechecks

Bulk mode does not introduce a multi-card transaction or hold locks across cards. The shared helpers must harden every mutation to use this order wherever the records apply:

1. Work Order row.
2. Material Request row.
3. Item row for a batchless shared pool.
4. Native ERPNext locks acquired during insert, submit, or cancel.

Create locks Work Order, then Item when batchless. Cancel, verify, and send resolve the bound Work Order first, lock that Work Order, then lock and re-read the Material Request. Under those locks they must recheck `docstatus`, Material Transfer type, single-row binding, confirmation state, stopped state, submitted Stock Entry existence, route fields, and the action's other lane prerequisites before mutation.

No helper may acquire Material Request and then Work Order in the reverse order. Locking is scoped to one HTTP/card transaction. Concurrency tests cover duplicate request, verify-versus-cancel, and send-versus-cancel/send races and prove at most one valid mutation survives.

## 7. Validation and error disclosure

### 7.1 Client envelope

Before processing starts:

- selection contains 1–20 unique references;
- every reference belongs to one source lane;
- selected cards are currently eligible;
- the chosen action is allowed for that source lane and role flags;
- required reference keys are non-empty strings;
- per-request Box inputs are either blank or finite non-negative numbers.

### 7.2 Server item envelope

For each HTTP request:

- `action` is one of the four allowlisted values;
- `entry` is one object;
- required keys match the action;
- unknown keys are rejected;
- references are non-empty strings;
- Box values are validated by existing `_box_kg` logic.

Per-card business validation remains the current server behavior: role, permission, docstatus, lane prerequisite, duplicate guard, row lock, stock availability, route, batch, native insert/submit/cancel, hooks, and status synchronization.

### 7.3 Expected and unexpected failures

Expected validation and permission failures return the translated Frappe user-facing message already produced by the action. The frontend records that card as failed and continues.

Unexpected internal errors, database connection failures, deadlocks, lock timeouts, malformed server responses, and network failures are not converted into raw card messages. The frontend records a generic message with a request correlation identifier when available, stops the remaining run, and instructs the operator to reload. It never displays SQL, traceback, filesystem path, or raw exception representation.

Stopping on infrastructure failure avoids reporting later operations against an uncertain connection state. Cards committed by prior HTTP requests remain committed and are rediscovered by the final reload.

## 8. Frontend state and API adapter

Add a boardless item adapter in `workspace_frontend/src/store.js` that calls `bulk_handover_item`. It must not use `handoverAction`, because `handoverAction` replaces the board after every current single action.

`HandoverBoard.vue` owns temporary UI state:

- `selectionMode`
- `selectedLane`
- selected references
- Box values keyed by Material Request
- bulk progress and pending state
- successes, expected failures, uncertain in-flight reference, unprocessed references, and abort state

The existing Cold Storage single action retains its optimistic `pendingRequests` behavior outside selection mode. Bulk submission uses separate pending state, never populates `pendingRequests`, never moves cards optimistically, and replaces the board only through the one final `loadBoard()` call.

Selection reconciliation uses the locked source lane after the mandatory board reload:

- clear every successful reference;
- retain expected failures and unprocessed references only when they remain eligible in the original source lane;
- reconcile an uncertain in-flight reference exclusively from server truth before allowing retry;
- clear every reference that moved lanes, disappeared, became stopped, or became ineligible.

No selection state is persisted across reloads or sessions.

## 9. Accessibility and responsive behavior

- Checkbox labels contain the Work Order or Material Request reference.
- Bulk toolbar buttons expose action names and selected counts.
- Keyboard users can enter selection mode, toggle cards, and submit dialogs without drag/drop.
- Disabled cross-lane cards communicate that selection is locked to another lane.
- The sticky action bar stays above the mobile bottom navigation.
- Verify rows become stacked request panels on narrow screens; Box labels remain associated with their request.
- Result failures remain readable without horizontal scrolling.

## 10. Testing and acceptance

### Backend integration tests

Cover:

- dispatch allowlist and strict one-entry schema;
- role and permission denial for every action;
- handover MR invariant failures before mutation;
- helper extraction preserves exact single-endpoint payloads;
- boardless endpoint never calls `_build_board`;
- create, cancel, verify, and send success paths;
- duplicate request/send and insufficient stock failures;
- batch and batchless behavior;
- native hooks and status sync remain effective;
- concurrency for duplicate create, verify-versus-cancel, and send-versus-cancel/send;
- no `ignore_permissions` or combined documents.

### Frontend unit tests

Extract pure helpers where practical and cover:

- first selection locks the lane;
- cross-lane selection is rejected;
- select-all includes only eligible visible cards;
- 20-card maximum;
- role-aware actions including dual-role Request Gudang;
- optional per-request Box payload generation and validation;
- sequential orchestration continues after expected card failures;
- infrastructure/network failure aborts later cards and distinguishes uncertain in-flight from unprocessed entries;
- final board is loaded once;
- successful references are cleared and only eligible failures/unprocessed references are retained after reload;
- bulk flow does not touch `pendingRequests`.

### Browser smoke

Run with gudang-side, produksi, and dual-role users:

- desktop and mobile selection mode;
- bulk create;
- bulk cancel;
- bulk verify with different optional Box values per request;
- bulk send;
- mixed expected failure summary and retry failed;
- infrastructure-abort message if a safe test seam exists;
- reload shows server truth;
- no optimistic bulk movement or duplicate documents.

Measure a 20-card bulk send in the local runtime. If it approaches the configured web/proxy timeout or creates unacceptable lock contention, reduce the cap before release; do not raise it without evidence.

## 11. Non-goals

- Selecting cards across multiple lanes in one operation.
- Selecting Terkirim history cards.
- Combining multiple Work Orders into one Material Request or Stock Entry.
- One-request multi-card savepoint processing.
- Parallel card requests.
- Background jobs, queues, progress WebSockets, or resumable bulk sessions.
- Persisting selection between reloads.
- Partial quantities or changing the current full-produced-quantity request rule.
- Changing Box semantics, warehouse defaults, batch mapping, or handover roles.

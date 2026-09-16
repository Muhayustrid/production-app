# Bulk Select Stock Entry Kanban — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan mode pilih banyak kartu pada Stock Entry Kanban untuk membuat request, membatalkan request, memverifikasi Box 1/2, dan mengirim barang secara berurutan dengan partial success yang tahan terhadap kegagalan per kartu.

**Architecture:** Browser menjadi orchestrator dan memanggil satu kartu per HTTP request melalui endpoint `bulk_handover_item(action, entry)`. Setiap request merupakan transaksi Frappe mandiri; endpoint mengembalikan payload aksi tanpa `board`, kemudian frontend memuat ulang board tepat sekali setelah run selesai atau terhenti.

**Tech Stack:** Frappe/ERPNext v16, Python, Vue 3 Composition API, Vite, Node test runner, Docker lokal.

**Spec:** `docs/superpowers/specs/2026-09-16-stock-entry-bulk-select-design.md`

## Global Constraints

- Lane aktif: Cold Storage, Request Gudang, dan Siap Kirim; Terkirim read-only.
- Pilihan pertama mengunci satu source lane; akun dual-role pada Request Gudang memilih Batalkan atau Verifikasi.
- Maksimum 20 kartu per run, ditegakkan browser orchestrator. `Pilih semua di halaman` hanya memilih kartu eligible yang dirender.
- Satu kartu per HTTP request, sequential; tidak ada multi-card savepoint, transaksi gabungan, paralelisme, background job, atau optimistic movement.
- Partial success: business/permission/state failure melanjutkan kartu berikutnya; infrastructure/protocol failure menghentikan run dan membedakan uncertain in-flight dari unprocessed.
- Lock order per kartu: Work Order → Material Request bila ada → Item untuk batchless pool → native ERPNext locks.
- Box 1/2 per Material Request bersifat opsional; nilai yang diberikan wajib finite dan non-negatif dalam kg.
- Tidak memakai `ignore_permissions`, tidak mengedit core ERPNext/Frappe, tidak menduplikasi override batch `bakery_manufacturing`, dan tidak mengubah response endpoint lama.
- Pertahankan FU36/FU37 termasuk fail-safe doc-events. Tidak ada commit, push, cloud deployment, atau mutasi dokumen operasional.
- Gunakan fixture terisolasi dan bersihkan setelah acceptance.

---

### Task 0: Branch and execution documents

**Files:**
- Create: `docs/superpowers/specs/2026-09-16-stock-entry-bulk-select-design.md`
- Create: `docs/superpowers/plans/2026-09-16-stock-entry-bulk-select.md`
- Modify: `TASKS.md`
- Modify: `PROJECT_STATE.md`

**Interfaces:**
- Consumes: branch `N@f8f3b5a`, preserved FU36/FU37 state addition, spec from `refs/stash^3`.
- Produces: branch `feat/stock-entry-bulk-select-fu38`, task IDs T38–T42, exactly one active task.

- [x] Preserve the unstaged FU36/FU37 `PROJECT_STATE.md` work log.
- [x] Create `feat/stock-entry-bulk-select-fu38` from `N@f8f3b5a` without resetting or force-pushing the stale feature branch.
- [x] Recover only the approved spec payload from `refs/stash^3`; do not apply stale code from the stash.
- [x] Add T38 backend contract, T39 backend locking/invariants, T40 frontend orchestrator/UI, T41 acceptance, and T42 handoff to `TASKS.md`.
- [x] Set T38 `IN_PROGRESS`, all later tasks `TODO`, and update Current handoff in `PROJECT_STATE.md`.
- [x] Verify branch, diff, and absence of stale stash code. Do not commit or push.

---

### Task 1: Boardless single-card backend contract

**Files:**
- Modify: `production_app/api/handover.py`
- Modify: `production_app/tests/test_handover_actions.py`

**Interfaces:**
- Consumes: existing `create_request`, `cancel_request`, `save_post_packing`, `send_handover` semantics.
- Produces: `bulk_handover_item(action, entry)` and internal `_create_request`, `_cancel_request`, `_save_post_packing`, `_send_handover`; helpers return current action payload minus `board`.

- [ ] Add RED tests for unknown action, non-object entry, missing/blank required key, and unknown key, proving validation occurs before mutation.
- [ ] Add RED tests for all four bulk success paths with `_build_board` patched to fail; assert responses contain no `board`.
- [ ] Add regression tests that existing public endpoints preserve their exact response fields including one board.
- [ ] Add role/permission parity tests for gudang, produksi, dual-role, and bare users.
- [ ] Implement strict JSON-object parsing and per-action allowlisted schema:

```python
{"create_request": {"work_order"}}
{"cancel_request": {"material_request"}}
{"save_post_packing": {"material_request", "box_1", "box_2"}}
{"send_handover": {"material_request"}}
```

- [ ] Extract each mutation into one boardless helper. Existing endpoints call one helper and append `_build_board()` once. `bulk_handover_item` calls only the allowlisted helper and never catches action exceptions.
- [ ] Run the targeted action suite and `git diff --check`.

---

### Task 2: Lock ordering and Material Request invariants

**Files:**
- Modify: `production_app/api/handover.py`
- Modify: `production_app/tests/test_handover_actions.py`
- Create only if clearer: `production_app/tests/test_handover_bulk.py`

**Interfaces:**
- Consumes: boardless helpers from Task 1.
- Produces: shared MR loader validating Material Transfer, submitted docstatus, exactly one item, one non-empty WO binding, and internally consistent route; per-action WO→MR→Item lock order.

- [ ] Add RED malformed-MR tests for type, docstatus, item count, empty/mismatched WO binding, item/qty mismatch, and inconsistent source/target route; prove zero writes.
- [ ] Add RED lock tracing for create (WO→Item when batchless) and existing-MR actions (pre-read binding→WO→MR→Item when batchless).
- [ ] Pre-read only enough MR data to resolve its Work Order, lock WO first, lock MR second, re-read and validate the complete invariant under lock.
- [ ] For create, lock WO, recheck active request and lot, then lock Item for batchless and rederive pool availability. Do not introduce unnecessary MR locks contrary to spec §6.2.
- [ ] For save post-packing, remove the existing MR→WO lock inversion.
- [ ] For send, lock WO then MR, lock Item for batchless, rederive lot, and recheck confirmation, stopped status, duplicate SE, route stock, and native builder prerequisites.
- [ ] Preserve FU37 metadata guard and fail-safe status-mirror hooks.
- [ ] Cover duplicate create/send, verify-vs-cancel, send-vs-cancel/send, batch and batchless pools, native failure rollback, and at-most-one valid mutation.
- [ ] Run action, board, and native proof suites.

---

### Task 3: Testable frontend orchestrator and boardless adapter

**Files:**
- Create: `workspace_frontend/src/handover-bulk.js`
- Create: `workspace_frontend/tests/handover-bulk.test.mjs`
- Modify: `workspace_frontend/src/store.js`

**Interfaces:**
- Produces:

```javascript
export const BULK_LIMIT = 20
export function validateBoxKg(value) {}
export function validateBulkEntries(entries) {}
export function classifyBulkError(error) {}
export async function runBulkItems(options) {}
export async function bulkHandoverItem(action, entry) {}
```

- [ ] Add RED tests for sequential order and `maxConcurrent === 1`.
- [ ] Add RED tests for 1–20 unique entries, non-empty refs, one source lane, role/action eligibility, and Box finite/non-negative/blank validation.
- [ ] Add RED tests proving expected failures continue while transport, timeout, HTTP 5xx, and malformed response abort with `uncertain` and `unprocessed`.
- [ ] Add RED tests for progress/result shape and final reload callback exactly once.
- [ ] Implement pure, dependency-injected runner and safe error classification; never expose SQL, traceback, path, or raw exception.
- [ ] Add `bulkHandoverItem` direct RPC adapter. It must not call `handoverAction`, mutate `handoverState.pending`, call `applyBoard`, or touch `pendingRequests`.
- [ ] Run all Node tests.

---

### Task 4: HandoverBoard selection UX

**Files:**
- Modify: `workspace_frontend/src/HandoverBoard.vue`
- Modify: `workspace_frontend/src/styles.css`
- Modify: `workspace_frontend/tests/handover-bulk.test.mjs` when pure selection helpers are extracted.

**Interfaces:**
- Consumes: Task 3 runner/adapter.
- Produces: temporary selection state, role-aware confirmation dialogs, per-request Box forms, progress/result/retry UI.

- [ ] Add toolbar button `Pilih`; Terkirim never selectable.
- [ ] First card locks source lane. Cross-lane cards dim/disable. In selection mode, card click toggles and drag/single-card actions are disabled.
- [ ] Implement role actions: Cold→create for gudang; Request→cancel for gudang / verify for produksi / both explicit buttons for dual-role; Siap→send for produksi.
- [ ] Add semantic checkbox/button labels, keyboard support, `aria-selected`, selected count, `Pilih semua di halaman`, `Kosongkan`, `Batal`, and clear-unsaved-values on exit.
- [ ] Refuse card 21 with a clear 20-card message.
- [ ] Add confirm views for bulk create, cancel, per-request Box verify, and send. Retain Box input after expected failure.
- [ ] Run with separate bulk pending state, no optimistic movement, no `pendingRequests` mutation.
- [ ] After the run, load board exactly once and reconcile failures/unprocessed/uncertain strictly against server truth and original lane.
- [ ] Show `N berhasil, M gagal, K belum diproses`, safe per-card errors, retry for still-eligible failed/unprocessed cards, and reload failure message.
- [ ] Add responsive sticky action bar above mobile navigation and stacked verify panels at 390 px.
- [ ] Run Node tests and Vite build.

---

### Task 5: Acceptance, assets, and handoff

**Files:**
- Generated: `production_app/public/workspace/assets/index.js`
- Generated: `production_app/public/workspace/assets/index.css`
- Modify: `PROJECT_STATE.md`
- Modify: `TASKS.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: verified local runtime and T38–T42 evidence.

- [ ] Run targeted backend action/board/native tests, then the full production_app suite twice.
- [ ] Run `node --test tests/*.test.mjs` and `npm run build`.
- [ ] Sync bundles to local backend/frontend containers and verify hashes at source/public/backend/frontend/HTTP points; restart only if needed.
- [ ] Browser-smoke isolated gudang, produksi, and dual-role fixtures on desktop and 390 px: create, cancel, per-card verify, send, dual-role action choice, expected partial failure, safe infrastructure abort seam, limit/select-all, reload truth, and no duplicate MR/SE.
- [ ] Measure a 20-card run; reduce the cap before release if local proxy/runtime evidence shows the chosen cap is unsafe.
- [ ] Clean fixtures and prove zero residue.
- [ ] Run `git diff --check`; inspect for core edits, dependency additions, stale stash files, credentials, or operational data.
- [ ] Record exact commands/results, lock/race/partial-success evidence, bundle hashes, browser results, cleanup, limitations, and rollback notes in `PROJECT_STATE.md`; mark tasks DONE only from execution evidence.
- [ ] Leave working tree on `feat/stock-entry-bulk-select-fu38`. Do not commit or push.

**Definition of done:** Hingga 20 kartu dari satu source lane/action diproses satu per satu dalam transaksi terpisah; business failures tidak membatalkan keberhasilan, infrastructure failures menghentikan kartu selanjutnya, Box tersimpan per kartu, final state direkonsiliasi dari server, dan seluruh alur lama tetap lulus regresi.

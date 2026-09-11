# AGENTS.md — production_app

Ground rules for coding agents working in this repository.

## Hard boundaries

- Never edit `frappe`/`erpnext` core, other apps under `apps/` (e.g.
  `pos_next`, `bakery_manufacturing`), or `sites/common_site_config.json`.
- `posnext.localhost` is PRODUCTION. Never install/migrate/test on it. The
  development and test target is `proof.localhost`.
- Local git commits are allowed. NEVER `git push` without explicit approval.
  Same for deployment or any change to production sites: approval gate first.
- Never rely on a core method's behavior from memory — read the source of the
  installed version first and, for binding claims, prove them on the test site
  (Phase 1 proof methodology).

## Commands

```bash
bench --site proof.localhost run-tests --app production_app   # must stay green
bench --site proof.localhost migrate                          # after doctype/fixture changes
bench --site proof.localhost export-fixtures --app production_app
bench build --app production_app                              # only when assets change
```

## App-specific contracts (binding: design spec Revisi 5.1)

- Backend API (Tahap 3) is COMPLETE — the 9 whitelisted endpoints in
  `api.py` (spec §7) are the SPA's only backend surface. Do not add
  endpoints, parameters, or fields outside spec §7/§8; keep error messages
  Indonesian (operator dictionary §3.1) with the machine codes
  `STATE_CHANGED` / `NEEDS_ALLOWANCE`.
- SPA (`vue/`, Tahap 4): build output goes to
  `production_app/public/production/` (committed, sourcemaps OFF) and
  `production_app/www/production-app.html`. `yarn test` (node --test) covers
  the idempotency-key retry semantics; operator-facing labels use the §3.1
  vocabulary only — technical core terms (fg_completed_qty, process loss,
  backflush, WIP) must never reach the UI.
- Stock Entry custom fields `custom_p_*` are app-owned (fixtures). Work Order
  summary fields are the SITE's Customize-Form fields (spec 8.1) — never
  export them from this app: `custom_good_qty_postpacking`,
  `custom_reject_qty_postpacking`, `custom_trial_qty_postpacking`,
  `custom_sisa_qty_postpacking`, `custom_good_qty_prepacking`,
  `custom_reject_qty_prepacking`, `custom_trial_qty_prepacking`,
  `custom_sisa_qty_prepacking`, `custom_qc_packing`, `custom_jam_packing`.
  On a site without these WO fields, recompute skips them with one WO comment.
- Idempotency ledger: `Production Request Log.idempotency_key` is unique at
  the DB level; duplicate raw inserts raise `MySQLdb.IntegrityError`
  (mysqlclient driver — NOT pymysql). ORM-level duplicates surface as
  `frappe.exceptions.DuplicateEntryError` / `UniqueValidationError`.
- Permission matrix (spec 11.3): Operator/Supervisor = read-only on Work
  Order and Stock Entry; Job Card read/create/write/submit for both;
  Job Card cancel = Supervisor ONLY. Prove changes via
  `tests/test_fixtures_roles.py`.

## Vocabulary (operator terms -> technical)

- HASIL BAIK (good) = packed-OK output -> FG stock (FG row / `custom_p_good_qty`).
- REJECT / TRIAL / SISA = output categories, recorded only, no separate stock.
- BAHAN DIPAKAI = actual material consumption per row (never auto-changed).
- SISA BAHAN DI WIP = WIP remaining net = transferred - consumed.
- LOSS EKSPLISIT = operator-entered process loss (`fg_completed_qty = good + loss`).
- SESI PACKING = one packing transaction = one Manufacture Stock Entry (Jalur A).
- BELUM DIPRODUKSI = `wo.qty - produced_qty - process_loss_qty`.

## Conventions

- English for code, comments, tests, and docs.
- Repository Markdown/code comments/test names in English.
- Tests: `frappe.tests.IntegrationTestCase` in `production_app/tests/`;
  factories in `tests/factories.py` (PDTC-prefixed data, idempotent).
  `setUpClass` data is committed by the framework and persists on the test
  site by design; per-test documents are rolled back at class end.

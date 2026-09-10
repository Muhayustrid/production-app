# Production App

ERPNext v16 manufacturing proxy app: a one-page production terminal for Work
Orders (packing sessions with actual quantities, idempotent mutations, and a
Work Order packing summary kept in sync by Stock Entry hooks).

- Required apps: `frappe`, `erpnext`.
- License: MIT.
- Design authority: `docs/specs/2026-09-10-production-app-design.md` (Revisi 5.1)
  in the project repository (outside this app repo).

## Scope status (Tahap 2)

- **Implemented**: `production_app/wo_summary.py` (Work Order packing summary
  aggregation, wired via `doc_events` on Stock Entry submit/cancel),
  `Production Request Log` doctype (idempotency ledger), fixtures (Stock Entry
  `custom_p_*` fields, roles, Custom DocPerms).
- **Stubs only (Tahap 3)**: `api.py`, `access.py`, `qty.py`, `cancel.py` raise
  `NotImplementedError` on purpose. Do not "finish" them outside Tahap 3.

## Key contracts

- Work Order summary fields (`custom_p_good_qty`, `custom_p_reject_qty`,
  `custom_p_trial_qty`, `custom_p_sisa_qty`, `custom_qc_packing`,
  `custom_jam_packing`) are **site-owned** (spec 8.3): they are NOT shipped as
  fixtures. `wo_summary.recompute` skips absent fields with one Work Order
  comment.
- `Production Request Log.idempotency_key` has a DB-level unique constraint
  AND names the document (autoname `field:`). Raw duplicates raise
  `MySQLdb.IntegrityError` (frappe v16 driver = mysqlclient).
- Permissions (spec 11.3): Production Operator/Supervisor get read on Work
  Order and Stock Entry; read/create/write/submit on Job Card; Job Card
  **cancel is Supervisor only**. No write/create on Stock Entry, no
  write/cancel on Work Order.

## Commands (run inside the bench container)

```bash
bench --site proof.localhost run-tests --app production_app   # all tests
bench --site proof.localhost migrate                          # sync doctypes + fixtures
bench --site proof.localhost export-fixtures --app production_app
bench build --app production_app                              # only when assets change
```

Tests target the isolated proof site (`proof.localhost`). Never install,
migrate, or test against `posnext.localhost` (production).

## Contributing

This app uses `pre-commit` for code formatting and linting (ruff, eslint,
prettier, pyupgrade): run `pre-commit install` once after cloning.

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

- Work Order summary fields are **site-owned** Customize-Form fields
  (spec 8.1/8.3), NOT shipped as fixtures: `custom_good_qty_postpacking`,
  `custom_reject_qty_postpacking`, `custom_trial_qty_postpacking`,
  `custom_sisa_qty_postpacking`, `custom_good_qty_prepacking`,
  `custom_reject_qty_prepacking`, `custom_trial_qty_prepacking`,
  `custom_sisa_qty_prepacking`, `custom_qc_packing`, `custom_jam_packing`.
  On a site where these Work Order fields are absent, `wo_summary.recompute`
  skips them with one Work Order comment (never silent).
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

## Development & Build (frontend SPA)

The frontend is a Vue 3 + Vite + frappe-ui single-page app in `vue/`,
mirroring the pos_next serving pattern:

- Source: `vue/` (Vite + Vue 3 + vue-router + frappe-ui + lucide-vue-next +
  Tailwind).
- Build output: `production_app/public/production/` (committed; `node_modules`
  is ignored).
- Entry page: the build rewrites/copies its `index.html` to
  `production_app/www/production-app.html`, which Frappe serves as a standard
  www page at **`/production-app`** (with a Jinja boot block injected by the
  frappe-ui vite plugin). Deep links (`/production-app/...`) are mapped to the
  SPA via `website_route_rules` in `hooks.py` — same mechanism as pos_next's
  `/pos`.
- Login gate: the SPA checks the `user_id` session cookie in a router guard
  and redirects guests to `/login`. No custom backend endpoints are used; the
  placeholder screen fetches the user via the existing core method
  `frappe.auth.get_logged_user`.

Build commands (inside the bench container):

```bash
# Reproducible build (installs deps per vue/yarn.lock, outputs to
# public/production + www/production-app.html). bench also runs this
# automatically:
bench build --app production_app

# Equivalent manual steps:
cd vue && yarn install && yarn build

# Dev server with hot reload:
yarn dev   # from vue/ (proxies /api,/assets to the local bench)
```

Note: a plain `bench serve` pins the site to `default_site`
(`posnext.localhost`). To serve the proof site over HTTP use
`bench --site proof.localhost serve --port 8001` and open
`http://127.0.0.1:8001/production-app` from inside the container.

## Contributing

This app uses `pre-commit` for code formatting and linting (ruff, eslint,
prettier, pyupgrade): run `pre-commit install` once after cloning.

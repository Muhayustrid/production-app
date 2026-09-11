# Production App

ERPNext v16 manufacturing proxy app: a one-page production terminal for Work
Orders (packing sessions with actual quantities, idempotent mutations, and a
Work Order packing summary kept in sync by Stock Entry hooks).

- Required apps: `frappe`, `erpnext`.
- License: MIT.
- Design authority: `docs/specs/2026-09-10-production-app-design.md` (Revisi 5.1)
  in the project repository (outside this app repo).

## Scope status (Tahap 5)

- **Backend (Tahap 2-3, complete)**: `wo_summary.py`, `access.py`, `qty.py`,
  `cancel.py`, `mutation.py` and the 9 whitelisted endpoints in `api.py`
  (see "API Endpoints" below).
- **Frontend (Tahap 4-5)**: UI foundation in `vue/` — API layer with
  idempotency-key retry semantics, central error handling (`STATE_CHANGED`
  auto-reload, `NEEDS_ALLOWANCE`), the Work Order list screen (spec 9.1) and
  the detail skeleton with 5-tab bar + smart action bar (spec 9.2),
  responsive basics (spec 9.3). Tab contents land with tasks 18-19.
- **Hardening (Tahap 5)**: Closed-WO guard on `cancel_production`
  (Indonesian, before any reversal), `notify_update()` parity with core on
  close, role-name constants (`access.PRODUCTION_ROLES` / `SUPERVISOR_ONLY`),
  one-surface list-error handling in the SPA (banner XOR toast), verified
  permission matrix (table below), guest sweep (all endpoints 403), and an
  Error Log review (no app-origin entries on a green suite).

## API Endpoints

Module `production_app/api.py` — the SPA's ONLY backend surface (full
contract: design spec §7). All endpoints are whitelisted without guest and
gated by `access.py` (roles Production Operator / Production Supervisor);
error messages are Indonesian; mutating endpoints additionally accept a
client-generated `idempotency_key` (UUID, spec 10.2: reuse it when retrying
the same action, regenerate for the next action) and are re-authorized on
replay.

| Endpoint | Contract (spec) |
|---|---|
| `get_open_work_orders(search)` | 7.1 — open Work Orders in the user's scope: item, qty/produced/belum diproduksi, step badge, blocked reasons. |
| `get_work_order_detail(work_order)` | 7.2 — WO summary, production metadata, materials, operations, job cards, stock entries, packing summary, `next_action`, blocked reasons. |
| `save_production_data(work_order, data, idempotency_key)` | 7.3 — save editable WO production metadata (strict 8.2 whitelist). |
| `transfer_material(work_order, items_aktual, idempotency_key)` | 7.4 — material transfer with the operator's ACTUAL picked quantities. |
| `complete_operation(work_order, job_card, qty, is_final, idempotency_key, started_at, loss)` | 7.5 — one-tap operation completion, actual qty, honest duration. |
| `finish_production(work_order, packing, idempotency_key)` | 7.6 — packing session = one Manufacture Stock Entry (Jalur A). |
| `cancel_last_step(work_order, expected_target, idempotency_key)` | 7.7 — Supervisor; cancel the newest step after a state match. |
| `cancel_production(work_order, expected_fingerprint, idempotency_key)` | 7.7 — Supervisor; cancel the whole production atomically. |
| `close_work_order(work_order, reason, idempotency_key)` | 7.8 — Supervisor; close the Work Order with a reason. |

Machine-readable error codes: `STATE_CHANGED` (confirmed state moved — the UI
reloads and the operator re-confirms) and `NEEDS_ALLOWANCE` (result exceeds
the site's production tolerance).

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

### Permission matrix (verified on-site, task 22)

Fixture: `fixtures/custom_docperm.json` (Custom DocPerm, permlevel 0).
Verified live with `frappe.has_permission` as users holding exactly the two
production roles:

| Doctype | Permission | Production Operator | Production Supervisor |
|---|---|---|---|
| Work Order | read | yes | yes |
| Work Order | write / create / submit / cancel / delete | no | no |
| Stock Entry | read | yes | yes |
| Stock Entry | write / create / submit / cancel / delete | no | no |
| Job Card | read / create / write / submit | yes | yes |
| Job Card | cancel | no | **yes** |
| Serial and Batch Bundle | read / create / write / submit | yes | yes |
| Serial and Batch Bundle | cancel | no | **yes** |

Consequences (hardening guarantees):

- Operators can NOT create or edit Stock Entries from Desk — read only; SEs
  are written exclusively by the app's endpoints (11.2/11.4).
- Operators can NOT create Work Orders; the roles never cancel Work Orders or
  Stock Entries via Desk — the only cancellation path is the app's
  Supervisor-only `cancel_last_step` / `cancel_production`, which run the
  core reversal under an already-gated `authorized_ignore` (11.3).
- Guests: every app endpoint rejects with HTTP 403 (curl sweep, task 22).

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

# Dev server with hot reload (from vue/):
yarn dev
```

Dev-proxy note: `yarn dev` proxies `/api`, `/assets`, `/files`, ... to the
local bench web server on `127.0.0.1:8000` (frappe-ui `frappeProxy` reads
`webserver_port` from `common_site_config.json`). A plain `bench serve`
always pins THAT port to `default_site` — `posnext.localhost`, the
PRODUCTION site — so never develop against it. Start a proof-pinned server
and point the proxy at it instead:

```bash
bench --site proof.localhost serve --port 8001   # proof site (container)
FRAPPE_WEB_SERVER_PORT=8001 yarn dev             # from vue/, proxies to proof
```

Note: a plain `bench serve` pins the site to `default_site`
(`posnext.localhost`). To serve the proof site over HTTP use
`bench --site proof.localhost serve --port 8001` and open
`http://127.0.0.1:8001/production-app` from inside the container.

## Contributing

This app uses `pre-commit` for code formatting and linting (ruff, eslint,
prettier, pyupgrade): run `pre-commit install` once after cloning.

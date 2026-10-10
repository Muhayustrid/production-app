# DEV-ONLY layout harness

Purpose: screenshot the workspace tables (Work Order, Stock Entry, Form Order
history) at real widths to verify the column geometry in `src/styles.css`
**without logging into ERPNext**.

It is not part of the shipped app: it lives in a separate HTML entry
(`layout-harness.html` → `harness/main.js`), is never imported by
`index.html`/`main.js`, and `npm run build` does not emit it.

## Run

Two terminals, from `workspace_frontend/`:

```bash
# 1) dev server (note: vite base prefixes the URL)
npx vite --port 5199 --strictPort
#    http://localhost:5199/assets/production_app/workspace/layout-harness.html

# 2) screenshots — playwright lives in a scratch dir so package.json stays clean
mkdir -p /tmp/layoutharness && (cd /tmp/layoutharness && npm init -y && npm i playwright@1.64.0)
(cd /tmp/layoutharness && npx playwright install chromium)

PW_PATH=/tmp/layoutharness/node_modules/playwright/index.js \
  node harness/shoot.mjs before   # label = before | after
```

Output: `harness/shots/<label>-<width>-<table>.png` plus a printed JSON of the
computed `grid-template-columns` per table per width and the first identifier
cell's rendered height (2 lines = wrapping).

## Measuring intrinsic text widths

`node harness/measure.mjs` (whole-cell, two-line cells report the stacked
width) and `node harness/measure-lines.mjs` (per text line) print the px a
column needs for its longest real content, so tracks are chosen from evidence
rather than guessed. Both need the same `PW_PATH`.

## Scope note

Sample rows mirror real payloads (WO-JURI-261009061, MREQ-MTR-26-0233,
"PT. JUARA ROTI INDONESIA") — that is what reproduced the reported defects.

"""Quantity contract & validation (spec section 3) - Tahap 3.

Contract (3.2, one packing session = one transaction):
- good            = physically packed OK output -> FG stock (FG row, stok).
- reject          = defect output, recorded only, no separate stock (3.6).
- trial           = trial output, recorded only, no separate stock.
- sisa            = leftover output, recorded only, no separate stock.
- loss_eksplisit  = operator-entered process loss; never fabricated (INV1).
- *_pre           = optional pre-packing readings (recorded only).
- bahan_dipakai   = ACTUAL material consumption; never auto-changed by results
  (INV5); default per material = WIP remaining net (transferred - used).

Core equation kept intact: fg_completed_qty = good + loss_eksplisit (V1).
Validation: all quantities finite >= 0 at field precision; good > 0 (good = 0
rejected with directions, 3.6, until decision #3); overproduction needs core
allowance, else NEEDS_ALLOWANCE (3.4).
"""


def validate_packing_payload(packing):
	"""Validate a finish_production payload (7.6 step 2): finite >= 0 at field
	precision, good > 0, categories recorded-only; return normalized values.
	Raise frappe.ValidationError with an Indonesian message otherwise."""
	raise NotImplementedError("Tahap 3")


def validate_materials(work_order, bahan_dipakai):
	"""Validate actual material consumption per material (3.2, INV5): finite
	>= 0; nothing forced; remaining WIP net per material = transferred - used
	(INV10) computed for the response."""
	raise NotImplementedError("Tahap 3")


def wip_remaining(work_order):
	"""Per-material remaining WIP net (transferred net - consumed by submitted
	SEs, net of returns) - the default for 'Bahan Dipakai' (section 5)."""
	raise NotImplementedError("Tahap 3")

"""Quantity contract & validation (spec 3, 13) - Tahap 3.

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
rejected with directions, 3.6, until decision #3); overproduction is
pre-checked against the core allowance math (3.4 -> NEEDS_ALLOWANCE) and the
unbooked operation/BOM loss is pre-checked (6.7) so operators get one clear
Indonesian message instead of the confusing core throw at SE submit.
"""

import math

import frappe
from frappe.utils import cint, flt

from production_app.exceptions import NeedsAllowanceError

# Payload field -> operator-facing label (spec 3.1 vocabulary, Indonesian).
NUMERIC_FIELDS = {
	"good": "Hasil Baik",
	"reject": "Reject",
	"trial": "Trial",
	"sisa": "Sisa",
	"good_pre": "Hasil Baik (Pre-Packing)",
	"reject_pre": "Reject (Pre-Packing)",
	"trial_pre": "Trial (Pre-Packing)",
	"sisa_pre": "Sisa (Pre-Packing)",
	"loss_eksplisit": "Loss Eksplisit",
}


def validate_packing(wo_doc, packing):
	"""Validate a finish_production packing payload (7.6 step 2-3, spec 3).

	Returns (normalized, warnings). Raises frappe.ValidationError with an
	Indonesian message for bad numbers / good = 0 (3.6) / the loss pre-check
	(6.7), and NeedsAllowanceError (code NEEDS_ALLOWANCE) when the result
	exceeds the target and the site's core allowance (3.4). A pre != post
	total is only a recorded warning, never an error.

	Assumes wo_doc was freshly read after the WO lock (10.1) so produced_qty
	mirrors the cumulative quantity core compares at submit."""
	packing = packing or {}
	precision = wo_doc.precision("qty")
	normalized = frappe._dict()
	for fieldname, label in NUMERIC_FIELDS.items():
		normalized[fieldname] = _normalize(packing.get(fieldname), precision, label)
	normalized.is_final = cint(packing.get("is_final"))

	# 3.6: good = 0 is rejected with directions until decision #3; no SE.
	if normalized.good <= 0:
		frappe.throw(
			"Hasil Baik harus lebih besar dari 0. Bila seluruh hasil tidak layak, minta Supervisor "
			"menyelesaikan Work Order melalui dokumen produksi - sesi packing tidak dibuat."
		)

	# 8.4: petugas defaults to the session user; Link User must exist.
	petugas = packing.get("petugas_packing") or frappe.session.user
	if not frappe.db.exists("User", petugas):
		frappe.throw(f"Petugas Packing '{petugas}' tidak ditemukan - pilih petugas yang terdaftar.")
	normalized.petugas_packing = petugas

	warnings = _cross_check_totals(normalized)
	_overproduction_check(wo_doc, normalized)
	_pending_loss_check(wo_doc, normalized)
	return normalized, warnings


def compute_session_materials(wo_doc, explicit=None):
	"""Session material rows (3.2, INV5/INV10): default = remaining WIP net
	per material; `explicit` (the operator's actual consumption) replaces the
	default per item. Enforces 0 <= dipakai <= sisa WIP net per item; extra
	physical material outside the WIP transfer gate is out of scope (6.8,
	open decision #10) - the error says where it belongs. Leftover stays in
	WIP (INV10); materials with nothing left are omitted (core rejects
	qty-0 rows)."""
	remaining = wip_remaining(wo_doc)
	session = dict(remaining)
	if not explicit:
		return session
	precision = wo_doc.precision("qty")
	for item_code, used in explicit.items():
		used = _normalize(used, precision, f"Bahan Dipakai {item_code}")
		left = flt(remaining.get(item_code, 0), precision)
		if used > left:
			frappe.throw(
				f"Bahan Dipakai {item_code} ({_fmt(used)}) melebihi sisa bahan di WIP ({_fmt(left)}). "
				"Bahan tambahan di luar yang diambil ke WIP tidak dapat dicatat di sini - simpan di "
				"gudang asal atau hubungi Supervisor."
			)
		if used > 0:
			session[item_code] = used
		else:
			session.pop(item_code, None)  # operator says 0 -> no qty-0 row
	return session


def wip_remaining(wo_doc):
	"""Per-material remaining WIP net (5, INV10): everything that entered the
	WIP warehouse minus everything that left, over submitted Stock Entries of
	this Work Order (returns net out naturally)."""
	se_names = frappe.get_all(
		"Stock Entry",
		filters={"docstatus": 1, "work_order": wo_doc.name},
		pluck="name",
	)
	if not se_names:
		return {}
	rows = frappe.get_all(
		"Stock Entry Detail",
		fields=["item_code", "qty", "s_warehouse", "t_warehouse"],
		filters={"parenttype": "Stock Entry", "parent": ("in", se_names)},
	)
	precision = wo_doc.precision("qty")
	net = {}
	for row in rows:
		delta = flt(row.qty, precision)
		if row.t_warehouse == wo_doc.wip_warehouse:
			net[row.item_code] = flt(net.get(row.item_code, 0) + delta, precision)
		if row.s_warehouse == wo_doc.wip_warehouse:
			net[row.item_code] = flt(net.get(row.item_code, 0) - delta, precision)
	return {item: amount for item, amount in net.items() if amount > 0}


def remaining_target(wo_doc):
	"""Sisa target belum diproduksi = qty - produced - loss (3.2)."""
	return flt(
		flt(wo_doc.qty) - flt(wo_doc.produced_qty) - flt(wo_doc.process_loss_qty),
		wo_doc.precision("qty"),
	)


def _normalize(value, precision, label):
	"""Finite >= 0 at field precision; Indonesian message otherwise."""
	value = flt(value, precision)
	if not math.isfinite(value):
		frappe.throw(f"{label} harus berupa angka yang valid.")
	if value < 0:
		frappe.throw(f"{label} tidak boleh kurang dari 0.")
	return value


def _cross_check_totals(normalized):
	"""8.4: pre-packing readings are optional; a mismatch with the packing
	result is recorded as a warning, never an error."""
	pre = sum(normalized[f] for f in ("good_pre", "reject_pre", "trial_pre", "sisa_pre"))
	post = sum(normalized[f] for f in ("good", "reject", "trial", "sisa"))
	if flt(pre, 6) != flt(post, 6):
		return [
			f"Jumlah pembacaan pre-packing ({_fmt(pre)}) berbeda dengan jumlah hasil packing ({_fmt(post)}) - dicatat sebagai catatan."
		]
	return []


def _overproduction_check(wo_doc, normalized):
	"""3.4: mirror the core submit-time gate [F] (update_work_order_qty:
	cumulative produced quantity vs qty x (1 + overproduction_percentage_for_work_order%))
	so the operator gets the NEEDS_ALLOWANCE message BEFORE insert/submit -
	core throws 'For quantity X should not be greater than allowed quantity Y'
	only at SE submit (proof P1b/P2)."""
	sisa = remaining_target(wo_doc)
	good, loss = normalized.good, normalized.loss_eksplisit
	if flt(good + loss, 9) <= flt(sisa, 9):
		return
	allowance = flt(
		frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order")
	)
	projected = flt(wo_doc.produced_qty) + good
	allowed = flt(wo_doc.qty) * (1 + allowance / 100)
	if projected > allowed:
		raise NeedsAllowanceError(
			"Hasil melebihi target dan toleransi produksi yang tersedia - hubungi admin untuk persetujuan."
		)


def _pending_loss_check(wo_doc, normalized):
	"""6.7: with unbooked operation loss or a BOM process_loss_percentage,
	core injects that loss into a loss-0 session and then throws its
	confusing 'you should reduce the quantity' message (proof P13h). Reject
	first with one clear message; a session with explicit loss > 0 passes
	(operating loss wins - proof P13h-H1, BOM pct - proof P11)."""
	if normalized.loss_eksplisit > 0:
		return
	uom = wo_doc.get("stock_uom")
	pending = _pending_operation_loss(wo_doc)
	if pending > 0:
		frappe.throw(
			f"Ada loss operasi sebesar {_fmt(pending)} {uom} yang belum tercatat pada Work Order ini. "
			f"Isi Loss Eksplisit sebesar {_fmt(pending)} {uom}, atau hubungi Supervisor bila loss "
			"sudah ditangani."
		)
	bom_pct = (
		flt(frappe.db.get_value("BOM", wo_doc.bom_no, "process_loss_percentage")) if wo_doc.bom_no else 0.0
	)
	if bom_pct > 0:
		expected = flt(normalized.good * bom_pct / 100, wo_doc.precision("qty"))
		frappe.throw(
			f"Resep (BOM) menetapkan loss {bom_pct}% yang akan tercatat otomatis (sekitar {_fmt(expected)} "
			f"{uom}). Isi Loss Eksplisit sebesar {_fmt(expected)} {uom}, atau hubungi admin untuk "
			"mengubah resep."
		)


def _pending_operation_loss(wo_doc):
	"""[F] Mirror of core get_pending_process_loss_qty (no job card):
	MAX(WO Operation process_loss_qty) - wo.process_loss_qty, floored at 0."""
	rows = frappe.get_all(
		"Work Order Operation",
		filters={"parent": wo_doc.name, "parenttype": "Work Order"},
		fields=[{"MAX": "process_loss_qty", "as": "process_loss_qty"}],
	)
	max_loss = flt(rows[0].process_loss_qty) if rows else 0.0
	return max(max_loss - flt(wo_doc.process_loss_qty), 0)


def _fmt(value):
	return f"{value:g}"

"""Work Order packing summary aggregation (spec section 8.1).

Doc_events on Stock Entry (on_submit / on_cancel) keep the Work Order summary
fields in sync so the projection stays consistent even for entries made from
Desk without the app's custom_p_* fields.

recompute() is a pure re-aggregation of all submitted manufacturing stock
entries of the Work Order, therefore idempotent: the same set of submitted
entries always produces the same summary, no matter how often or in which
order it runs. It runs inside the caller's transaction (spec 10.3) and never
commits.
"""

import frappe
from frappe.utils import flt

GUARD_PURPOSES = ("Manufacture", "Material Consumption for Manufacture")

# Work Order summary fields written by recompute() - the SITE's existing
# Customize-Form fields (spec section 8.1).
# These fields are SITE-OWNED (spec 8.3): they are not shipped by this app as
# fixtures. If a field is absent from the Work Order meta it is skipped and
# one Work Order comment records the skip (never silent).
# - *_postpacking totals: aggregate of the submitted app-style packing
#   sessions (post values).
# - *_prepacking totals: aggregate of the optional pre-packing readings.
# - custom_qc_packing / custom_jam_packing: petugas and posting time of the
#   last manufacturing stock entry of the Work Order.
WO_SUMMARY_FIELDS = (
	"custom_good_qty_postpacking",
	"custom_reject_qty_postpacking",
	"custom_trial_qty_postpacking",
	"custom_sisa_qty_postpacking",
	"custom_good_qty_prepacking",
	"custom_reject_qty_prepacking",
	"custom_trial_qty_prepacking",
	"custom_sisa_qty_prepacking",
	"custom_qc_packing",
	"custom_jam_packing",
)

# Stock Entry per-transaction fields read during aggregation. Post-good total
# is NOT read from custom_p_good_qty: it comes from the FG rows (see
# recompute - identical for app entries by spec 7.6, correct fallback for
# Desk entries per spec 8.1). Pre values are read from the SE fields.
SE_SUMMARY_FIELDS = (
	"custom_p_reject_qty",
	"custom_p_trial_qty",
	"custom_p_sisa_qty",
	"custom_p_good_qty_pre",
	"custom_p_reject_qty_pre",
	"custom_p_trial_qty_pre",
	"custom_p_sisa_qty_pre",
	"custom_p_petugas_packing",
)


def on_submit(doc, method=None):
	"""Stock Entry on_submit hook (narrow guard, see hooks.doc_events)."""
	_recompute_guarded(doc)


def on_cancel(doc, method=None):
	"""Stock Entry on_cancel hook (narrow guard, see hooks.doc_events)."""
	_recompute_guarded(doc)


def _recompute_guarded(doc):
	if doc.purpose in GUARD_PURPOSES and doc.get("work_order"):
		recompute(doc.work_order)


def recompute(work_order):
	"""Re-aggregate the packing summary of `work_order` from submitted stock
	entries and write it to the Work Order summary fields.

	Mapping (spec 8.1):
	- good (post): per entry, the sum of its finished-goods rows (core
	  derived). For app-style entries the FG row qty equals custom_p_good_qty
	  by contract (spec 7.6 step 5), so the aggregate is identical either way;
	  for Desk entries without the custom fields this is the specified
	  fallback - and since Float fields default to 0 (never NULL) there is no
	  reliable way to tell "app entry with good 0" from "Desk entry", so the
	  FG rows are used for all entries. Consumption entries have no FG rows
	  -> contribute 0.
	- reject / trial / sisa (post): categories come from app-style entries
	  only (0 on Desk entries, which is correct: categories are app-only,
	  spec 8.1).
	- *_pre totals: sums of the optional pre-packing readings
	  (custom_p_*_pre) - app-style entries only.
	- custom_qc_packing / custom_jam_packing: petugas (custom_p_petugas_packing
	  else entry owner) and posting datetime of the LAST entry.

	Fields missing from the Work Order meta are skipped with a single Work
	Order comment listing them (spec 8.3, test 14.13b).
	"""
	missing = _missing_wo_fields()
	rows = _submitted_entries(work_order)

	good = reject = trial = sisa = 0.0
	pre_good = pre_reject = pre_trial = pre_sisa = 0.0
	for row in rows:
		good += row.fg_qty
		reject += flt(row.get("custom_p_reject_qty"))
		trial += flt(row.get("custom_p_trial_qty"))
		sisa += flt(row.get("custom_p_sisa_qty"))
		pre_good += flt(row.get("custom_p_good_qty_pre"))
		pre_reject += flt(row.get("custom_p_reject_qty_pre"))
		pre_trial += flt(row.get("custom_p_trial_qty_pre"))
		pre_sisa += flt(row.get("custom_p_sisa_qty_pre"))

	last = rows[-1] if rows else None
	values = {
		"custom_good_qty_postpacking": good,
		"custom_reject_qty_postpacking": reject,
		"custom_trial_qty_postpacking": trial,
		"custom_sisa_qty_postpacking": sisa,
		"custom_good_qty_prepacking": pre_good,
		"custom_reject_qty_prepacking": pre_reject,
		"custom_trial_qty_prepacking": pre_trial,
		"custom_sisa_qty_prepacking": pre_sisa,
		"custom_qc_packing": (last and (last.get("custom_p_petugas_packing") or last.owner)) or None,
		"custom_jam_packing": _posting_datetime(last) if last else None,
	}

	if missing:
		values = {k: v for k, v in values.items() if k not in missing}
		_comment_missing_fields(work_order, missing)
	if values:
		frappe.db.set_value("Work Order", work_order, values, update_modified=False)


def _submitted_entries(work_order):
	"""Submitted Manufacture / Consumption entries of the WO, oldest first."""
	has_p_fields = frappe.get_meta("Stock Entry")
	fields = ["name", "owner", "posting_date", "posting_time"]
	fields += [f for f in SE_SUMMARY_FIELDS if has_p_fields.has_field(f)]
	rows = frappe.get_all(
		"Stock Entry",
		filters={
			"work_order": work_order,
			"docstatus": 1,
			"purpose": ("in", GUARD_PURPOSES),
		},
		fields=fields,
		order_by="posting_date asc, posting_time asc, creation asc, name asc",
	)
	# Finished-goods row totals per entry (core derived, spec 8.1 fallback).
	fg_totals = {}
	if rows:
		for row in frappe.get_all(
			"Stock Entry Detail",
			filters={
				"parent": ("in", [r.name for r in rows]),
				"parenttype": "Stock Entry",
				"is_finished_item": 1,
			},
			fields=["parent", "qty"],
		):
			fg_totals[row.parent] = fg_totals.get(row.parent, 0) + flt(row.qty)
	for row in rows:
		row.fg_qty = fg_totals.get(row.name, 0.0)
	return rows


def _posting_datetime(row):
	return frappe.utils.get_datetime(f"{row.posting_date} {row.posting_time}")


def _missing_wo_fields():
	wo_meta = frappe.get_meta("Work Order")
	return [f for f in WO_SUMMARY_FIELDS if not wo_meta.has_field(f)]


def _comment_missing_fields(work_order, missing):
	wo = frappe.get_doc("Work Order", work_order)
	wo.add_comment(
		"Comment",
		text=(
			"production_app: Work Order summary field(s) missing from meta - "
			f"skipped: {', '.join(missing)}. Run 'bench migrate' or contact admin."
		),
	)

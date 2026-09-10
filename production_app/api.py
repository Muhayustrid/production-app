"""Whitelisted SPA endpoints (spec section 7) - Tahap 3.

Convention for every endpoint: whitelisted without guest; access gate
(access.py) runs before anything; mutating endpoints take `idempotency_key`
(10.2) and are re-authorized on replay; state is re-read AFTER the Work Order
lock (10.1); user-facing errors are Indonesian (term dictionary 3.1); error
codes `STATE_CHANGED` (UI reloads) and `NEEDS_ALLOWANCE` (3.4).
"""

import frappe


@frappe.whitelist()
def get_open_work_orders(search=None):
	"""List view (7.1): docstatus-1 Work Orders in status Not Started / In
	Process / Stopped / Stock Reserved / Stock Partially Reserved, scoped to the
	user's access. Per WO: item, qty, produced, "belum diproduksi", status,
	expected_delivery_date, step badge, has_operations, skip_transfer,
	blocked_reasons. Sorted by expected_delivery_date, untouched first."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def get_work_order_detail(work_order):
	"""Detail screen (7.2): WO summary + production metadata (8.2); materials
	(required / transferred net / used / WIP remaining / indicative stock);
	operations; job cards; stock entries incl. custom_p_*; packing_summary
	(aggregation per 8.1); next_action; blocked_reasons (section 6)."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def save_production_data(work_order, data):
	"""Save WO production metadata (7.3, fields per 8.2). Only fields present
	in meta; validated types (finite >= 0, Link exists); rejected once the WO
	is Completed / Closed / Cancelled."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def transfer_material(work_order, items, idempotency_key=None):
	"""Material transfer (7.4): operator's ACTUAL picked quantities per
	material; over-transfer gate (6.8); insert/submit via make_stock_entry dict
	with ignore_permissions after the app gate; batch picking left to core."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def complete_operation(work_order, job_card, qty, is_final, idempotency_key=None):
	"""Complete one operation (7.5): actual qty, honest duration (single-tap =
	time_in_mins 0), pending_qty kept as remainder; choreography per proof P13
	(add_time_log -> reload -> complete_job_card(qty, end_time,
	process_loss_qty, pending_qty, auto_submit=1))."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def finish_production(work_order, packing, idempotency_key=None):
	"""Packing session (7.6): Jalur A single Manufacture SE - material rows =
	actual used, FG row qty = good (explicit batch_no, proof P7a-3),
	process_loss_qty = explicit loss; writes custom_p_* ; WO summary synced by
	the Stock Entry hook in the same transaction (8.1)."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def cancel_last_step(work_order, expected_target, idempotency_key=None):
	"""Cancel the newest cancelable step (7.7, order per section 12);
	`expected_target` mismatch -> STATE_CHANGED, nothing cancelled.
	Supervisor only."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def cancel_production(work_order, expected_fingerprint, idempotency_key=None):
	"""Cancel the whole production in one request (7.7): verify fingerprint of
	the docstatus-1 document list, loop pre-checks until clean, then cancel;
	failure midway -> total rollback. Supervisor only."""
	raise NotImplementedError("Tahap 3")


@frappe.whitelist()
def close_work_order(work_order, reason, idempotency_key=None):
	"""Close WO (7.8): Supervisor; rejected while a Job Card is WIP submitted;
	executed via document methods (4.2) without permission bypass; reason
	recorded as a Work Order comment."""
	raise NotImplementedError("Tahap 3")

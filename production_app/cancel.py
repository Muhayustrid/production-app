"""Cancel target resolution + pre-checks (spec section 12).

Contract:
- Fixed type order v1 (12): Manufacture SE -> (Jalur B) Consumption SE ->
  Transfer SE -> submitted Job Card -> Work Order. It is the only order that
  passes core validation for the app lifecycle (proof P8).
- Within a type the target is the newest by posting_datetime (Job Cards:
  newest creation) - the "langkah terakhir" of the WO.
- `expected_target` / `expected_fingerprint` (7.7) are compared by the
  endpoints AFTER the Work Order lock and re-read: mismatch -> STATE_CHANGED,
  nothing is cancelled (not even partly; includes SE-A confirmed, SE-B
  created by someone else).
- Pre-checks BLOCK with an Indonesian reason: FG already consumed by another
  transaction (batch-aware get_batch_qty, expired excluded), WIP net too
  small to reverse a transfer (item breakdown), derived Disassemble SE,
  Desk returns (is_return), additional-transfer entries - out-of-pattern
  documents are detected and BLOCKED, never auto-cancelled.
- Execution via .cancel(): core reverses stock/batch/WO status/costing
  (V15, proof P8-1); the WO packing summary is re-synced by the Stock Entry
  hook in the same transaction (8.1).
- Supervisor only (11).
"""

import hashlib

import frappe
from frappe.utils import flt

from production_app import qty
from production_app.access import authorized_ignore

# Fixed cancel type order v1 (spec 12).
SE_PURPOSES_IN_ORDER = (
	"Manufacture",
	"Material Consumption for Manufacture",
	"Material Transfer for Manufacture",
)

# Core negative-stock wording family (proof P8-2 generic + P8-4 batch variant);
# markers survive the HTML links core embeds in these messages.
_NEGATIVE_STOCK_MARKERS = (
	"negative stock",
	"needed in",
)


def _wo_name(work_order):
	return work_order if isinstance(work_order, str) else work_order.name


def resolve_targets(work_order):
	"""Docstatus-1 members of the FIRST fixed type (12) that still has any,
	newest first. Empty list = nothing cancelable. Members of later types are
	NOT candidates while an earlier type is active."""
	wo = _wo_name(work_order)
	for purpose in SE_PURPOSES_IN_ORDER:
		names = frappe.get_all(
			"Stock Entry",
			filters={"work_order": wo, "docstatus": 1, "purpose": purpose},
			pluck="name",
			order_by="posting_date desc, posting_time desc, creation desc, name desc",
		)
		if names:
			return [frappe._dict(doctype="Stock Entry", name=name) for name in names]
	return [
		frappe._dict(doctype="Job Card", name=name)
		for name in frappe.get_all(
			"Job Card",
			filters={"work_order": wo, "docstatus": 1},
			pluck="name",
			order_by="creation desc, name desc",
		)
	]


def next_cancel_target(work_order):
	"""The concrete newest target document of the first cancelable type (or
	None). Out-of-pattern documents surface through precheck_cancel, which
	blocks with a reason instead of cancelling."""
	members = resolve_targets(work_order)
	if not members:
		return None
	return frappe.get_doc(members[0].doctype, members[0].name)


def all_members(work_order):
	"""EVERY docstatus-1 Stock Entry + Job Card of the WO (any purpose) - the
	list `production_fingerprint` binds the confirmation to (7.7)."""
	wo = _wo_name(work_order)
	members = [
		frappe._dict(doctype="Stock Entry", name=name)
		for name in frappe.get_all("Stock Entry", filters={"work_order": wo, "docstatus": 1}, pluck="name")
	]
	members += [
		frappe._dict(doctype="Job Card", name=name)
		for name in frappe.get_all("Job Card", filters={"work_order": wo, "docstatus": 1}, pluck="name")
	]
	return members


def production_fingerprint(work_order):
	"""SHA-256 over the sorted "name:doctype" list of all docstatus-1 SE + JC
	of the WO - the `expected_fingerprint` of 7.7."""
	payload = "\n".join(sorted(f"{m.name}:{m.doctype}" for m in all_members(work_order)))
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def precheck_cancel(target):
	"""None when the target is clean to cancel, else the Indonesian block
	reason (12): out-of-pattern Desk documents first, then the stock the
	reversal needs (core keeps the final say at cancel)."""
	for check in (
		_derived_disassemble_reason,
		_desk_return_reason,
		_additional_transfer_reason,
		_stock_reversal_reason,
	):
		reason = check(target)
		if reason:
			return reason
	return None


def cancel_doc(doc):
	"""Cancel an already-gated Stock Entry / Job Card (11.2 step 5).

	The SE's Serial and Batch Bundles are cancelled by core on a FRESH
	document (serial_batch_bundle.cancel_serial_and_batch_bundle), so the
	framework "cancel" check runs on Serial and Batch Bundle itself - the
	Supervisor fixture grants exactly that (Task 15 residual, report).

	A Job Card cancel propagates onto the Work Order with a plain wo.save()
	(job_card.update_work_order_data) - the same core-internal bookkeeping
	complete_operation waives via api._core_wo_propagation (deferred import:
	api imports this module)."""
	with authorized_ignore(doc):
		if doc.doctype == "Job Card":
			from production_app.api import _core_wo_propagation

			with _core_wo_propagation():
				doc.cancel()
		else:
			doc.cancel()


def cancel_work_order(work_order):
	"""Cancel the Work Order itself (last step of cancel_production): the
	roles deliberately hold NO Work Order cancel permission (11.3); the
	doc-instance ignore_permissions flag covers this completion of the
	authorized action. Fresh fetch - the SE/Job Card cancels above db_set WO
	fields, so the caller's copy is stale (would fail the version check)."""
	wo = frappe.get_doc("Work Order", _wo_name(work_order))
	with authorized_ignore(wo):
		wo.cancel()
	return wo


def map_cancel_error(error):
	"""Map the core negative-stock rejection (P8-2/P8-4 wording) to the
	Indonesian wrong-order/usage message; any other ValidationError is
	re-raised untouched (user-facing messages must not be masked)."""
	text = str(error)
	if any(marker in text for marker in _NEGATIVE_STOCK_MARKERS):
		frappe.throw(
			"Urutan pembatalan salah atau bahan sudah terpakai transaksi lain - stok tidak mencukupi "
			f"untuk pembalikan ini. Rincian: {text}"
		)
	raise error


# ------------------------------------------------------------------ prechecks


def _derived_disassemble_reason(target):
	"""A derived Disassemble SE submitted against this SE - cancelling the
	source alone would orphan it."""
	if target.doctype != "Stock Entry":
		return None
	derived = frappe.get_all(
		"Stock Entry", filters={"source_stock_entry": target.name, "docstatus": 1}, pluck="name"
	)
	if derived:
		return (
			f"SE {target.name} memiliki transaksi turunan (Disassemble) {', '.join(derived)} - "
			"batalkan transaksi turunan tersebut lewat Desk terlebih dulu."
		)
	return None


def _desk_return_reason(target):
	"""Any submitted return SE on the WO is a Desk transaction the app never
	created - it must be resolved (or kept) by an admin, not auto-cancelled."""
	names = frappe.get_all(
		"Stock Entry",
		filters={"work_order": target.work_order, "docstatus": 1, "is_return": 1},
		pluck="name",
	)
	if names:
		return (
			f"Ada pengembalian bahan {', '.join(names)} pada Work Order ini - "
			"selesaikan pengembaliannya lewat Desk terlebih dulu."
		)
	return None


def _additional_transfer_reason(target):
	"""Additional transfers (beyond the WO allowance, Desk-made) are outside
	the app pattern - never auto-cancelled."""
	names = frappe.get_all(
		"Stock Entry",
		filters={"work_order": target.work_order, "docstatus": 1, "is_additional_transfer_entry": 1},
		pluck="name",
	)
	if names:
		return (
			f"SE {', '.join(names)} adalah transfer bahan tambahan di luar pola aplikasi - "
			"pembatalan harus dilakukan lewat Desk. Hubungi Supervisor."
		)
	return None


def _stock_reversal_reason(target):
	"""Stock the reversal needs: FG untouched at the FG warehouse for
	Manufacture/Consumption, WIP net sufficient for a Transfer reversal."""
	if target.doctype != "Stock Entry":
		return None
	wo = frappe.get_doc("Work Order", target.work_order)
	if target.purpose == "Material Transfer for Manufacture":
		return _wip_shortfall_reason(wo, target)
	return _fg_used_reason(wo, target)


def _fg_used_reason(wo, se):
	"""Batch-aware FG check (12): net get_batch_qty at the FG warehouse
	(expired batches excluded by core) must still cover the SE's FG rows -
	P8-4: FG already issued elsewhere makes the reversal negative."""
	precision = wo.precision("qty")
	fg_qty = flt(sum(flt(row.qty) for row in se.items if row.item_code == wo.production_item), precision)
	if fg_qty <= 0:
		return None  # Jalur-B consumption has no FG row to reverse
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	batches = get_batch_qty(item_code=wo.production_item, warehouse=wo.fg_warehouse) or []
	net = flt(sum(flt(batch.qty) for batch in batches), precision)
	if net < fg_qty:
		return (
			f"FG sudah terpakai transaksi lain: {wo.production_item} di gudang {wo.fg_warehouse} "
			f"tersisa {net:g} (butuh {fg_qty:g} untuk membatalkan {se.name}). "
			"Selesaikan pengembalian FG lewat Desk terlebih dulu."
		)
	return None


def _wip_shortfall_reason(wo, se):
	"""WIP net (in - out over the WO's submitted SEs) must cover every row the
	transfer reversal would pull out of the WIP warehouse - P8-2 pre-empted
	with the item breakdown instead of the core negative-stock throw."""
	precision = wo.precision("qty")
	remaining = qty.wip_remaining(wo)
	shortages = []
	for row in se.items:
		need = flt(row.qty, precision)
		have = flt(remaining.get(row.item_code, 0), precision)
		if have < need:
			shortages.append(f"{row.item_code} kurang {flt(need - have, precision):g} di {wo.wip_warehouse}")
	if shortages:
		return (
			f"Pembatalan {se.name} akan membuat stok WIP negatif (urutan pembatalan salah): "
			+ "; ".join(shortages)
			+ ". Batalkan langkah yang lebih dulu sesuai urutan."
		)
	return None

"""Whitelisted SPA endpoints (spec section 7) - Tahap 3.

Convention for every endpoint: whitelisted without guest; access gate
(access.py) runs before anything; mutating endpoints take `idempotency_key`
(10.2) and are re-authorized on replay; state is re-read AFTER the Work Order
lock (10.1); user-facing errors are Indonesian (term dictionary 3.1); error
codes `STATE_CHANGED` (UI reloads) and `NEEDS_ALLOWANCE` (3.4).
"""

import frappe
from frappe.utils import cint, flt, getdate, today

from production_app import access, qty, wo_summary
from production_app.mutation import run_mutation

# 7.1: the statuses that still show up in the operator's list (Completed /
# Closed / Cancelled are never loaded).
OPEN_STATUSES = ("Not Started", "In Process", "Stopped", "Stock Reserved", "Stock Partially Reserved")

# Spec 8.2 production metadata the app may WRITE via save_production_data
# (7.3). Read-only display fields (custom_qty_in_uom, custom_uom,
# custom_conversion_factor, custom_item_name_information) are served by the
# detail endpoint but never accepted for saving. All are site-owned (8.3):
# absent fields are simply skipped.
EDITABLE_METADATA_FIELDS = (
	"custom_adonan_ke",
	"custom_adonan",
	"custom_jam_adonan",
	"custom_suhu_adonan",
	"custom_nama_penimbang",
	"custom_jam_pembekuan",
	"custom_qc_produksi",
	"custom_jumlah_kru",
	"custom_leader_produksi",
)
DISPLAY_METADATA_FIELDS = (
	"custom_qty_in_uom",
	"custom_uom",
	"custom_conversion_factor",
	"custom_item_name_information",
)
NUMERIC_FIELDTYPES = frozenset({"Int", "Float", "Decimal", "Currency", "Percent"})
DATETIME_FIELDTYPES = frozenset({"Datetime", "Date", "Time"})
# Editability (8.4): metadata stays editable while the WO is open / Stopped.
FINISHED_STATUSES = ("Completed", "Closed", "Cancelled")

_LIST_FIELDS = (
	"name",
	"production_item",
	"item_name",
	"qty",
	"produced_qty",
	"process_loss_qty",
	"status",
	"expected_delivery_date",
	"skip_transfer",
	"material_transferred_for_manufacturing",
	"wip_warehouse",
	"source_warehouse",
	"transfer_material_against",
	"track_semi_finished_goods",
	"reserve_stock",
	"bom_no",
	"creation",
)


@frappe.whitelist()
def get_open_work_orders(search=None):
	"""List view (7.1): docstatus-1 Work Orders in status Not Started / In
	Process / Stopped / Stock Reserved / Stock Partially Reserved, scoped to the
	user's access. Per WO: item, qty, produced, "belum diproduksi", status,
	expected_delivery_date, step badge, has_operations, skip_transfer,
	blocked_reasons. Sorted by expected_delivery_date, untouched first."""
	access.require_role("Production Operator", "Production Supervisor")
	filters = {"docstatus": 1, "status": ("in", OPEN_STATUSES)}
	order_by = "expected_delivery_date asc, creation asc"
	or_filters = None
	if search and str(search).strip():
		like = f"%{str(search).strip()}%"
		or_filters = [
			["Work Order", "name", "like", like],
			["Work Order", "production_item", "like", like],
			["Work Order", "item_name", "like", like],
		]
	# Same get_list scope as access.list_wos_scope; the direct call is only
	# needed because the search needs or_filters (item/item_name/name).
	if or_filters:
		rows = frappe.get_list(
			"Work Order", filters=filters, or_filters=or_filters, fields=list(_LIST_FIELDS), order_by=order_by
		)
	else:
		rows = access.list_wos_scope(filters=filters, fields=list(_LIST_FIELDS), order_by=order_by)

	names = [r.name for r in rows]
	ops_by_wo = _operations_by_wo(names)
	wip_net = _wip_net_by_wo(names, {r.name: r.get("wip_warehouse") for r in rows})

	return {
		"work_orders": [
			{
				"name": row.name,
				"item": row.production_item,
				"item_name": row.item_name,
				"qty": row.qty,
				"produced": row.produced_qty,
				"belum_diproduksi": flt(flt(row.qty) - flt(row.produced_qty) - flt(row.process_loss_qty), 3),
				"status": row.status,
				"expected_delivery_date": row.expected_delivery_date,
				"badge": _list_badge(row, ops_by_wo.get(row.name, []), wip_net.get(row.name, 0.0)),
				"has_operations": bool(ops_by_wo.get(row.name)),
				"skip_transfer": cint(row.skip_transfer),
				"blocked_reasons": access.config_blocked_reasons(row)[0],
			}
			for row in rows
		]
	}


@frappe.whitelist()
def get_work_order_detail(work_order):
	"""Detail screen (7.2): WO summary + production metadata (8.2); materials
	(required / transferred net / used / WIP remaining / indicative stock);
	operations; job cards; stock entries incl. custom_p_*; packing_summary
	(aggregation per 8.1); next_action; blocked_reasons (section 6)."""
	access.require_role("Production Operator", "Production Supervisor")
	wo = access.check_wo_access(work_order, "read")
	reasons, _bom_pct = access.config_blocked_reasons(wo)

	materials = _detail_materials(wo)
	operations, job_cards = _detail_operations(wo)

	# packing_summary: the same aggregation the Stock Entry hook writes to the
	# WO (8.1) - read here without writing, limited to fields present in meta.
	summary = wo_summary.compute_summary(wo.name)
	packing_summary = {k: v for k, v in summary.items() if wo.meta.has_field(k)}

	metadata = {
		f: wo.get(f) for f in EDITABLE_METADATA_FIELDS + DISPLAY_METADATA_FIELDS if wo.meta.has_field(f)
	}

	entries = _detail_stock_entries(wo)

	return {
		"work_order": {
			"name": wo.name,
			"item": wo.production_item,
			"item_name": wo.item_name,
			"qty": wo.qty,
			"produced": wo.produced_qty,
			"belum_diproduksi": qty.remaining_target(wo),
			"status": wo.status,
			"expected_delivery_date": wo.expected_delivery_date,
			"skip_transfer": cint(wo.skip_transfer),
			"has_operations": bool(wo.operations),
			"wip_warehouse": wo.wip_warehouse,
			"fg_warehouse": wo.fg_warehouse,
			"source_warehouse": wo.source_warehouse,
		},
		"production_metadata": metadata,
		"materials": materials,
		"operations": operations,
		"job_cards": job_cards,
		"stock_entries": entries,
		"packing_summary": packing_summary,
		"next_action": _next_action(wo, reasons, materials, operations),
		"blocked_reasons": reasons,
	}


@frappe.whitelist()
def save_production_data(work_order, data, idempotency_key=None):
	"""Save WO production metadata (7.3, fields per 8.2) via run_mutation
	(action save_production_data). Strict whitelist: only EDITABLE_METADATA_FIELDS
	present in the Work Order meta; validated types (finite >= 0 at field
	precision, Link User exists); rejected once the WO is Completed / Closed /
	Cancelled (Stopped still editable, 8.4). frappe.db.set_value keeps the
	session user as modified_by."""
	payload = frappe.parse_json(data) if isinstance(data, str) else data
	if payload is None:
		payload = {}
	if not isinstance(payload, dict):
		frappe.throw("Data harus berupa objek (dict).", frappe.ValidationError)

	def fn():
		access.require_role("Production Operator", "Production Supervisor")
		wo = access.check_wo_access(work_order, "read")
		if wo.status in FINISHED_STATUSES:
			frappe.throw(
				f"Work Order sudah {wo.status} - data produksi tidak dapat diubah lagi.",
				frappe.ValidationError,
			)
		values = _validate_metadata(wo, payload)
		if values:
			# One set_value for the batch: updates modified/modified_by to the
			# session user (audit identity = session, spec 11.4). db.set_value
			# MUTATES the dict (adds modified/modified_by) - report the clean copy.
			saved = dict(values)
			frappe.db.set_value("Work Order", wo.name, values)
		else:
			saved = {}
		return {
			"work_order": wo.name,
			"saved": saved,
			"reference_doctype": "Work Order",
			"reference_doc": wo.name,
		}

	return run_mutation(work_order, "save_production_data", idempotency_key, payload, fn)


@frappe.whitelist()
def transfer_material(work_order, items, idempotency_key=None):
	"""Material transfer (7.4): operator's ACTUAL picked quantities per
	material; over-transfer gate (6.8); insert/submit via make_stock_entry dict
	with ignore_permissions after the app gate; batch picking left to core."""
	raise NotImplementedError("Tahap 4")


@frappe.whitelist()
def complete_operation(work_order, job_card, qty, is_final, idempotency_key=None):
	"""Complete one operation (7.5): actual qty, honest duration (single-tap =
	time_in_mins 0), pending_qty kept as remainder; choreography per proof P13
	(add_time_log -> reload -> complete_job_card(qty, end_time,
	process_loss_qty, pending_qty, auto_submit=1))."""
	raise NotImplementedError("Tahap 4")


@frappe.whitelist()
def finish_production(work_order, packing, idempotency_key=None):
	"""Packing session (7.6): Jalur A single Manufacture SE - material rows =
	actual used, FG row qty = good (explicit batch_no, proof P7a-3),
	process_loss_qty = explicit loss; writes custom_p_* ; WO summary synced by
	the Stock Entry hook in the same transaction (8.1)."""
	raise NotImplementedError("Tahap 4")


@frappe.whitelist()
def cancel_last_step(work_order, expected_target, idempotency_key=None):
	"""Cancel the newest cancelable step (7.7, order per section 12);
	`expected_target` mismatch -> STATE_CHANGED, nothing cancelled.
	Supervisor only."""
	raise NotImplementedError("Tahap 4")


@frappe.whitelist()
def cancel_production(work_order, expected_fingerprint, idempotency_key=None):
	"""Cancel the whole production in one request (7.7): verify fingerprint of
	the docstatus-1 document list, loop pre-checks until clean, then cancel;
	failure midway -> total rollback. Supervisor only."""
	raise NotImplementedError("Tahap 4")


@frappe.whitelist()
def close_work_order(work_order, reason, idempotency_key=None):
	"""Close WO (7.8): Supervisor; rejected while a Job Card is WIP submitted;
	executed via document methods (4.2) without permission bypass; reason
	recorded as a Work Order comment."""
	raise NotImplementedError("Tahap 4")


# --------------------------------------------------------------------- list


def _operations_by_wo(names):
	"""Work Order Operation rows of `names`, grouped per WO, pick order first
	(sequence_id then sheet order, spec 5)."""
	if not names:
		return {}
	ops = frappe.get_all(
		"Work Order Operation",
		filters={"parent": ("in", names), "parenttype": "Work Order"},
		fields=["parent", "name", "operation", "sequence_id", "idx", "completed_qty", "process_loss_qty"],
		order_by="parent asc, idx asc",
	)
	grouped = {}
	for op in ops:
		grouped.setdefault(op.parent, []).append(op)
	return grouped


def _op_order_key(op):
	return (cint(op.get("sequence_id")), op.get("idx") or 0)


def _wip_net_by_wo(names, wip_by_wo):
	"""Net material still in each WO's WIP warehouse over ALL submitted Stock
	Entries (spec 5 "bahan sudah dipindah" second source of truth)."""
	net = dict.fromkeys(names, 0.0)
	if not names:
		return net
	ses = frappe.get_all(
		"Stock Entry", filters={"docstatus": 1, "work_order": ("in", names)}, fields=["name", "work_order"]
	)
	if not ses:
		return net
	wo_by_se = {se.name: se.work_order for se in ses}
	rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ("in", list(wo_by_se)), "parenttype": "Stock Entry"},
		fields=["parent", "qty", "s_warehouse", "t_warehouse"],
	)
	for row in rows:
		wo_name = wo_by_se[row.parent]
		wip = wip_by_wo.get(wo_name)
		if not wip:
			continue
		if row.t_warehouse == wip:
			net[wo_name] += flt(row.qty)
		if row.s_warehouse == wip:
			net[wo_name] -= flt(row.qty)
	return net


def _list_badge(row, operations, wip_net):
	"""Next-step badge (7.1, derivation per spec 5): Menunggu Bahan until the
	transfer step happened, then Operasi k/N while any operation is unfinished,
	then Menunggu Packing while target remains, finally Selesai."""
	ordered = sorted(operations, key=_op_order_key)
	if not cint(row.skip_transfer) and flt(row.material_transferred_for_manufacturing) <= 0 and wip_net <= 0:
		return "Menunggu Bahan"
	for position, op in enumerate(ordered, 1):
		if flt(op.completed_qty) + flt(op.process_loss_qty) < flt(row.qty):
			return f"Operasi {position}/{len(ordered)}"
	if flt(flt(row.qty) - flt(row.produced_qty) - flt(row.process_loss_qty), 3) > 0:
		return "Menunggu Packing"
	return "Selesai"


# ------------------------------------------------------------------- detail


def _detail_materials(wo):
	"""Per required item (7.2): BOM requirement vs net transferred vs net
	consumed ("dipakai", term dictionary 3.1), WIP remaining, remaining to
	transfer, and INDICATIVE stock at the source warehouse (Bin / batches per
	the core pick setting; expired batches flagged and excluded from tersedia)."""
	transfer_net, used_net = _material_nets(wo)

	materials = []
	for row in wo.required_items or []:
		item = row.item_code
		transferred = flt(transfer_net.get(item, 0), wo.precision("qty"))
		used = flt(used_net.get(item, 0), wo.precision("qty"))
		warehouse = row.source_warehouse or wo.source_warehouse
		materials.append(
			{
				"item_code": item,
				"required_qty": flt(row.required_qty, wo.precision("qty")),
				"transferred_net": transferred,
				"dipakai": used,
				# INV10 keeps used <= transferred on transfer-based WOs, so the
				# floor never bites there; on skip_transfer WOs there is no
				# transfer leg and sisa_wip is simply never negative.
				"sisa_wip": flt(max(transferred - used, 0), wo.precision("qty")),
				# What the WO still needs: on transfer-based WOs that is driven
				# by transferred_net (used is its subset per INV10); on
				# skip_transfer WOs direct consumption already covers it.
				"sisa_perlu": flt(
					max(flt(row.required_qty) - max(transferred, used), 0), wo.precision("qty")
				),
				"stok_gudang_asal": _indicative_stock(item, warehouse),
			}
		)
	return materials


def _material_nets(wo):
	"""(transferred_net, used_net) per item over submitted Stock Entries of the
	WO. transferred_net: purpose Material Transfer for Manufacture, warehouse
	net against the WIP warehouse (is_return flows out naturally). used_net is
	dipakai per spec 5 ("sum of consumption rows, docstatus 1" - NO warehouse
	qualifier): Manufacture + Consumption rows count positive when they LEAVE
	the WIP warehouse; on a skip_transfer Work Order core books those rows
	directly FROM the source warehouse (make_stock_entry: from_warehouse =
	source_warehouse when skip_transfer and not from_wip_warehouse), so those
	count too; a consumption row RETURNING to the WIP warehouse subtracts."""
	ses = frappe.get_all(
		"Stock Entry",
		filters={"docstatus": 1, "work_order": wo.name},
		fields=["name", "purpose"],
	)
	transfer_se, consume_se = set(), set()
	for se in ses:
		if se.purpose == "Material Transfer for Manufacture":
			transfer_se.add(se.name)
		elif se.purpose in ("Manufacture", "Material Consumption for Manufacture"):
			consume_se.add(se.name)
	if not transfer_se and not consume_se:
		return {}, {}

	rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ("in", list(transfer_se | consume_se)), "parenttype": "Stock Entry"},
		fields=["parent", "item_code", "qty", "s_warehouse", "t_warehouse"],
	)
	precision = wo.precision("qty")
	transfer_net, used_net = {}, {}
	wip, source = wo.wip_warehouse, wo.source_warehouse
	skip_transfer = cint(wo.skip_transfer)
	for row in rows:
		into_wip = bool(wip) and row.t_warehouse == wip
		out_wip = bool(wip) and row.s_warehouse == wip
		if row.parent in transfer_se:
			# Transferred net: into the WIP warehouse counts positive, returns flow out.
			if not (into_wip or out_wip):
				continue
			bucket, sign = transfer_net, 1 if into_wip else -1
		else:
			# dipakai (3.1): consumption OUT of the WIP warehouse counts
			# positive - or straight out of the source warehouse on a
			# skip_transfer WO.
			from_source = skip_transfer and source and row.s_warehouse == source
			if not (out_wip or from_source or into_wip):
				continue
			bucket, sign = used_net, -1 if into_wip else 1
		bucket[row.item_code] = flt(bucket.get(row.item_code, 0) + sign * flt(row.qty), precision)
	return transfer_net, used_net


def _indicative_stock(item_code, warehouse):
	"""Indicative availability at the source warehouse (7.2): Bin actual_qty;
	for batch items the per-batch qty in the core pick order
	(pick_serial_and_batch_based_on) with expired batches flagged `expired`
	and excluded from `tersedia` (numbers are indicative, never a promise)."""
	stock = {"warehouse": warehouse, "bin_qty": None, "tersedia": None, "batches": []}
	if not warehouse:
		return stock
	stock["bin_qty"] = frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
	)
	if frappe.db.get_value("Item", item_code, "has_batch_no"):
		# for_stock_levels=True keeps expired batches visible so they can be
		# flagged; ordering follows the site's pick_serial_and_batch_based_on.
		# ponytail: one call per batched item - fine at recipe scale.
		from erpnext.stock.doctype.batch.batch import get_batch_qty

		stock["batches"] = [
			{
				"batch_no": b.batch_no,
				"qty": b.qty,
				"expiry_date": b.expiry_date,
				"expired": bool(b.expiry_date and getdate(b.expiry_date) < getdate(today())),
			}
			for b in get_batch_qty(item_code=item_code, warehouse=warehouse, for_stock_levels=True)
		]
		stock["tersedia"] = sum(flt(b["qty"]) for b in stock["batches"] if not b["expired"])
	return stock


def _detail_operations(wo):
	"""Per operation (7.2): actual progress vs qty, the operation's OPEN
	(docstatus 0) job card, and whether an additional card is needed
	(remaining > 0 with no open card)."""
	job_cards = frappe.get_all(
		"Job Card",
		filters={"work_order": wo.name},
		fields=[
			"name",
			"operation",
			"operation_id",
			"status",
			"docstatus",
			"total_completed_qty",
			"process_loss_qty",
			"total_time_in_mins",
		],
		order_by="creation asc, name asc",
	)
	open_by_op = {jc.operation_id: jc for jc in job_cards if jc.docstatus == 0}

	operations = []
	for op in sorted(wo.operations or [], key=_op_order_key):
		open_jc = open_by_op.get(op.name)
		sisa = flt(flt(wo.qty) - flt(op.completed_qty) - flt(op.process_loss_qty), wo.precision("qty"))
		operations.append(
			{
				"operation": op.operation,
				"sequence_id": op.sequence_id,
				"completed_qty": op.completed_qty,
				"process_loss_qty": op.process_loss_qty,
				"qty": wo.qty,
				"sisa": sisa,
				"open_job_card": open_jc.name if open_jc else None,
				"perlu_kartu_tambahan": sisa > 0 and not open_jc,
			}
		)
	cards = [
		{
			"name": jc.name,
			"operation": jc.operation,
			"status": jc.status,
			"docstatus": jc.docstatus,
			"total_completed_qty": jc.total_completed_qty,
			"process_loss_qty": jc.process_loss_qty,
		}
		for jc in job_cards
	]
	return operations, cards


def _detail_stock_entries(wo):
	"""Submitted Stock Entries of the WO, oldest first (7.2): Transfer,
	Consumption and Manufacture incl. the custom_p_* packing details, petugas
	(custom_p_petugas_packing else entry owner) and posting time (8.1)."""
	meta = frappe.get_meta("Stock Entry")
	fields = [
		"name",
		"purpose",
		"docstatus",
		"posting_date",
		"posting_time",
		"owner",
		"is_return",
		"fg_completed_qty",
	]
	# custom_p_* are app fixtures; still guard the query the way wo_summary
	# does so a half-migrated site degrades to empty values instead of crashing.
	# SE_SUMMARY_FIELDS omits custom_p_good_qty (recompute reads good from the
	# FG rows); the detail endpoint reports it, so list it explicitly.
	packing_fields = ["custom_p_good_qty", *wo_summary.SE_SUMMARY_FIELDS, "custom_p_packing_note"]
	fields += [f for f in packing_fields if meta.has_field(f)]
	rows = frappe.get_all(
		"Stock Entry",
		filters={"docstatus": 1, "work_order": wo.name},
		fields=fields,
		order_by="posting_date asc, posting_time asc, creation asc, name asc",
	)
	return [
		{
			"name": row.name,
			"purpose": row.purpose,
			"docstatus": row.docstatus,
			"is_return": row.is_return,
			"posting_datetime": wo_summary._posting_datetime(row),
			"petugas_packing": row.get("custom_p_petugas_packing") or row.owner,
			"good": row.get("custom_p_good_qty"),
			"reject": row.get("custom_p_reject_qty"),
			"trial": row.get("custom_p_trial_qty"),
			"sisa": row.get("custom_p_sisa_qty"),
			"good_pre": row.get("custom_p_good_qty_pre"),
			"reject_pre": row.get("custom_p_reject_qty_pre"),
			"trial_pre": row.get("custom_p_trial_qty_pre"),
			"sisa_pre": row.get("custom_p_sisa_qty_pre"),
			"packing_note": row.get("custom_p_packing_note"),
		}
		for row in rows
	]


def _next_action(wo, reasons, materials, operations):
	"""Derived next step (7.2, spec 5): blocked first, then transfer, then the
	next unfinished operation's open job card, then packing, then done."""
	if reasons:
		return "blocked:" + reasons[0]
	if not cint(wo.skip_transfer) and any(m["sisa_perlu"] > 0 for m in materials):
		return "transfer_material"
	for op in operations:
		if op["sisa"] > 0 and op["open_job_card"]:
			return f"complete_operation:{op['open_job_card']}"
	if qty.remaining_target(wo) > 0:
		return "finish_production"
	return "done"


# --------------------------------------------------------------------- save


def _validate_metadata(wo, payload):
	"""Strict 7.3 whitelist: only EDITABLE_METADATA_FIELDS that exist in the
	Work Order meta are accepted; everything else is silently dropped (the SPA
	owns the field list, unknown keys must never hit the WO). Types follow the
	field's meta fieldtype: numbers finite >= 0 at field precision (3.1),
	Link User must exist, datetimes must parse; None/"" clears the field."""
	values = {}
	for fieldname in EDITABLE_METADATA_FIELDS:
		if fieldname not in payload or not wo.meta.has_field(fieldname):
			continue
		field = wo.meta.get_field(fieldname)
		value = payload[fieldname]
		if value is None or value == "":
			values[fieldname] = None
			continue
		if field.fieldtype in NUMERIC_FIELDTYPES:
			precision = 0 if field.fieldtype == "Int" else wo.precision(fieldname)
			values[fieldname] = qty._normalize(value, precision, field.label)
		elif field.fieldtype == "Link":
			if not frappe.db.exists(field.options or "User", value):
				frappe.throw(f"{field.label} '{value}' tidak ditemukan - pilih petugas yang terdaftar.")
			values[fieldname] = value
		elif field.fieldtype in DATETIME_FIELDTYPES:
			try:
				frappe.utils.get_datetime(value)
			except Exception:
				frappe.throw(f"{field.label} tidak valid.")
			values[fieldname] = value
		else:
			values[fieldname] = value
	return values

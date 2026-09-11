"""Whitelisted SPA endpoints (spec section 7) - Tahap 3.

Convention for every endpoint: whitelisted without guest; access gate
(access.py) runs before anything; mutating endpoints take `idempotency_key`
(10.2) and are re-authorized on replay; state is re-read AFTER the Work Order
lock (10.1); user-facing errors are Indonesian (term dictionary 3.1); error
codes `STATE_CHANGED` (UI reloads) and `NEEDS_ALLOWANCE` (3.4).
"""

import contextlib
import uuid

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from production_app import access, cancel, qty, wo_summary
from production_app.hooks import CUSTOM_P_FIELDS
from production_app.mutation import assert_state, run_mutation

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
	(aggregation per 8.1); next_action; blocked_reasons (section 6); cancel
	bookkeeping (7.7): is_supervisor, cancel_fingerprint, cancel_next_target."""
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

	# Cancel bookkeeping for the Riwayat tab (7.7, task 19): the SERVER stays
	# the sole authority over cancel intent (poka-yoke) - the UI renders the
	# concrete target / fingerprint but never computes them locally.
	# is_supervisor gates the supervisor-only buttons client-side; the server
	# re-checks the role on every cancel/close call regardless.
	cancel_targets = cancel.resolve_targets(wo)
	user_roles = set(frappe.get_roles())

	return {
		"is_supervisor": "System Manager" in user_roles or "Production Supervisor" in user_roles,
		"cancel_fingerprint": cancel.production_fingerprint(wo.name),
		"cancel_next_target": (
			{"doctype": cancel_targets[0].doctype, "name": cancel_targets[0].name} if cancel_targets else None
		),
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
def transfer_material(work_order, items_aktual=None, idempotency_key=None):
	"""Material transfer (7.4): operator's ACTUAL picked quantities per
	material; over-transfer gate (6.8); insert/submit via make_stock_entry dict
	with ignore_permissions after the app gate; batch picking left to core."""
	parsed = frappe.parse_json(items_aktual) if isinstance(items_aktual, str) else items_aktual
	if parsed is None:
		parsed = {}
	if not isinstance(parsed, dict):
		frappe.throw("Items harus berupa objek (dict) kode bahan -> jumlah.", frappe.ValidationError)

	def fn():
		access.require_role("Production Operator", "Production Supervisor")
		wo = access.check_wo_access(work_order, "read")
		reasons, _bom_pct = access.config_blocked_reasons(wo)
		if reasons:
			frappe.throw(reasons[0])
		_reject_if_not_open(wo, "transfer bahan", BLOCKED_TRANSFER_STATUSES)
		if cint(wo.skip_transfer):
			frappe.throw("Work Order ini tidak memerlukan pengambilan bahan (skip transfer).")
		if not any(m["sisa_perlu"] > 0 for m in _detail_materials(wo)):
			frappe.throw("Semua bahan sudah diambil - tidak ada lagi yang perlu ditransfer.")

		from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

		# V8: the dict carries ONLY the still-pending materials, default qty = sisa
		# perlu; operator overrides win per item.
		se = frappe.get_doc(make_stock_entry(wo.name, "Material Transfer for Manufacture"))
		for item_code, value in parsed.items():
			row = next((r for r in se.items if r.item_code == item_code), None)
			if row is None:
				frappe.throw(f"Bahan {item_code} tidak memiliki sisa kebutuhan transfer pada Work Order ini.")
			row.qty = row.transfer_qty = qty._normalize(
				value, wo.precision("qty"), f"Bahan Diambil {item_code}"
			)
			if row.qty <= 0:
				frappe.throw(f"Bahan Diambil {item_code} harus lebih besar dari 0.")

		# gate + stock pre-checks speak for themselves; only the submit's core
		# errors need mapping (user-facing messages must not be masked)
		_over_transfer_gate(wo, se)
		_check_indicative_stock(wo, se)
		try:
			# 11.2 step 5 / 11.4: the SE is the authorized document; the Serial
			# and Batch Bundles core spawns during submit are covered by the
			# production roles' Custom DocPerm (fixtures).
			with access.authorized_ignore(se):
				se.insert()
				se.submit()
		except frappe.ValidationError as e:
			if "cannot be greater than planned quantity" in str(e):
				# the 6.8 gate should have caught this pre-submit; map it anyway
				frappe.throw(
					"Total bahan yang diambil melebihi batas transfer Work Order. Kurangi jumlah yang "
					"diambil, simpan bahan ekstra di gudang asal (Stores), atau hubungi admin untuk "
					"menyetel toleransi transfer."
				)
			frappe.log_error(title="Production App: transfer_material", message=frappe.get_traceback())
			frappe.throw("Transfer bahan gagal karena kesalahan tak terduga - coba lagi atau hubungi admin.")

		wo.reload()
		materials = _detail_materials(wo)
		operations, _job_cards = _detail_operations(wo)
		return {
			"work_order": wo.name,
			"stock_entry": se.name,
			"materials": materials,
			"next_action": _next_action(wo, [], materials, operations),
			"reference_doctype": "Stock Entry",
			"reference_doc": se.name,
		}

	return run_mutation(work_order, "transfer_material", idempotency_key, {"items_aktual": parsed}, fn)


@frappe.whitelist()
def complete_operation(work_order, job_card, qty, is_final, idempotency_key=None, started_at=None, loss=None):
	"""Complete one operation in one tap (7.5): ACTUAL qty, honest duration
	(single tap = time_in_mins 0; `started_at` makes it real, P13c), pending_qty
	kept as the operation remainder - a final tap NEVER inflates the completed
	qty (P13d). Choreography per proof P13/V22 on a docstatus-0 Job Card:
	add_time_log(start_time) -> reload -> complete_job_card(qty, end_time,
	process_loss_qty, pending_qty, auto_submit=1). A partial completion leaves
	the operation short of the WO qty with its card submitted, so the follow-up
	card for the remainder is created immediately (P13e payload: `operation`
	MUST be passed explicitly - core get_operation_details omits it)."""
	completion = _parse_number(qty, "Jumlah Selesai")
	loss_value = _parse_number(loss, "Loss Operasi")
	final = _to_bool(is_final)

	def fn():
		access.require_role("Production Operator", "Production Supervisor")
		wo = access.check_wo_access(work_order, "read")
		reasons, _bom_pct = access.config_blocked_reasons(wo)
		if reasons:
			frappe.throw(reasons[0])
		_reject_if_not_open(wo, "penyelesaian operasi", BLOCKED_COMPLETE_STATUSES)

		jc = frappe.get_doc("Job Card", job_card)
		access.check_relation(jc, wo.name)
		if jc.docstatus != 0:
			frappe.throw("Kartu operasi sudah selesai/dibatalkan.")
		op = next((row for row in wo.operations if row.name == jc.operation_id), None)
		if op is None:
			frappe.throw("Job Card tidak terkait dengan operasi pada Work Order ini.")

		precision = wo.precision("qty")
		q = flt(completion, precision)
		loss_qty = flt(loss_value, precision)
		if q <= 0:
			frappe.throw("Jumlah selesai harus lebih besar dari 0.")
		# completed + loss + pending must add up to the card qty (core
		# validate_time_logs_present) - the remainder stays pending (7.5).
		pending = flt(flt(jc.for_quantity) - q - loss_qty, precision)
		if pending < 0:
			frappe.throw(
				f"Jumlah selesai ({q:g}) + loss ({loss_qty:g}) melebihi jumlah kartu operasi "
				f"({flt(jc.for_quantity, precision):g})."
			)
		_sequence_precheck(wo, op, q)

		if not jc.time_logs:
			# V22: the open child row is persisted directly by add_time_log
			# (the parent is NOT saved) - reload before completing. The end
			# time is captured AFTER the log opens (P13 order): a single-tap
			# window [start, end] must never have start > end.
			jc.add_time_log(
				frappe._dict({"start_time": _parse_start(started_at), "employees": [], "completed_qty": 0})
			)
			jc = frappe.get_doc("Job Card", jc.name)
		end = now_datetime()
		try:
			from erpnext.manufacturing.doctype.job_card.job_card import OperationSequenceError, OverlapError

			with _core_wo_propagation():
				jc.complete_job_card(
					qty=q, end_time=end, process_loss_qty=loss_qty, pending_qty=pending, auto_submit=1
				)
		except OperationSequenceError:
			# backstop behind _sequence_precheck (core keeps the final say)
			frappe.throw("Operasi sebelumnya belum selesai - selesaikan operasi sebelumnya dulu.")
		except OverlapError:
			frappe.throw("Jadwal workstation bentrok dengan job card lain - coba lagi beberapa saat.")

		wo.reload()
		op = next((row for row in wo.operations if row.name == jc.operation_id), None)
		kartu_tambahan = _ensure_additional_card(wo, op)
		materials = _detail_materials(wo)
		operations, _cards = _detail_operations(wo)
		# the `qty` parameter shadows the qty module in this scope - inline
		# remaining_target (3.2: qty - produced - loss)
		remaining = flt(flt(wo.qty) - flt(wo.produced_qty) - flt(wo.process_loss_qty), precision)
		return {
			"work_order": wo.name,
			"job_card": jc.name,
			"operation": op.operation,
			"operation_completed": flt(op.completed_qty, precision),
			"operation_loss": flt(op.process_loss_qty, precision),
			"operation_qty": flt(wo.qty, precision),
			"kartu_tambahan": kartu_tambahan,
			"status": wo.status,
			"remaining_target": remaining,
			"needs_close_decision": bool(final) and remaining > 0,
			"next_action": _next_action(wo, [], materials, operations),
			"reference_doctype": "Job Card",
			"reference_doc": jc.name,
		}

	payload = {
		"job_card": job_card,
		"qty": completion,
		"is_final": final,
		"started_at": started_at,
		"loss": loss_value,
	}
	return run_mutation(work_order, "complete_operation", idempotency_key, payload, fn)


@frappe.whitelist()
def finish_production(work_order, packing=None, idempotency_key=None):
	"""Packing session (7.6): Jalur A single Manufacture SE - material rows =
	actual used, FG row qty = good (explicit batch_no, proof P7a-3),
	process_loss_qty = explicit loss; writes custom_p_* ; WO summary synced by
	the Stock Entry hook in the same transaction (8.1)."""
	payload = frappe.parse_json(packing) if isinstance(packing, str) else packing
	if payload is None:
		payload = {}
	if not isinstance(payload, dict):
		frappe.throw("Packing harus berupa objek (dict).", frappe.ValidationError)

	def fn():
		access.require_role("Production Operator", "Production Supervisor")
		wo = access.check_wo_access(work_order, "read")
		reasons, _bom_pct = access.config_blocked_reasons(wo)
		if reasons:
			frappe.throw(reasons[0])
		_reject_if_not_open(wo, "sesi packing", BLOCKED_FINISH_STATUSES)
		if qty.remaining_target(wo) <= 0:
			frappe.throw("Target produksi sudah tercapai - tidak ada sesi packing yang perlu dibuat.")
		_require_packing_schema()

		normalized, warnings = qty.validate_packing(wo, payload)
		_operations_coverage_check(wo, normalized)
		session = _session_materials(
			wo, normalized.good + normalized.loss_eksplisit, payload.get("bahan_dipakai")
		)
		if not session:
			# a Manufacture SE without any material row is rejected by core with a
			# confusing message - reject here with directions instead
			frappe.throw(
				"Belum ada bahan yang tersedia untuk dikonsumsi pada Work Order ini - "
				"pastikan bahan sudah tersedia, atau hubungi Supervisor."
			)

		from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

		rows = []
		try:
			se = frappe.get_doc(
				make_stock_entry(wo.name, "Manufacture", qty=normalized.good + normalized.loss_eksplisit)
			)
			# V17: explicit loss prevents the BOM pct fallback in set_process_loss_qty.
			se.process_loss_qty = normalized.loss_eksplisit

			for row in se.items:
				if row.item_code == wo.production_item:
					row.qty = row.transfer_qty = normalized.good
					if frappe.db.get_value("Item", row.item_code, "has_batch_no"):
						# proof P7a-3: core's FG auto-batch is broken (Serial and Batch
						# Bundle built without company) - the app creates the batch
						# explicitly; core then fills the bundle with qty = good.
						row.use_serial_batch_fields = 1
						row.batch_no = _create_fg_batch(row.item_code)
					rows.append(row)
				elif row.item_code in session:
					row.qty = row.transfer_qty = session[row.item_code]
					rows.append(row)
				# else: drop the row - INV5, never consume BOM defaults the session
				# did not confirm.
			se.set("items", rows)
			_apply_packing_fields(se, normalized, payload)
			# 11.2 step 5 / 11.4: the SE is the authorized document; the Serial
			# and Batch Bundles core spawns during submit are covered by the
			# production roles' Custom DocPerm (fixtures).
			with access.authorized_ignore(se):
				se.insert()
				se.submit()
		except frappe.ValidationError as e:
			# the duplicate gate fires at SE validate (so already during insert),
			# not only at submit - the mapping must span build + submit
			if "Stock Entries already created for Work Order" in str(e):
				# duplicate gate [F] check_duplicate_entry_for_work_order
				frappe.throw("Target sesi sebelumnya sudah mencapai batas Work Order - hubungi admin.")
			frappe.log_error(title="Production App: finish_production", message=frappe.get_traceback())
			frappe.throw("Sesi packing gagal karena kesalahan tak terduga - coba lagi atau hubungi admin.")

		if warnings:
			wo.add_comment("Comment", text=" ".join(warnings))
		wo.reload()
		remaining = qty.remaining_target(wo)
		return {
			"work_order": wo.name,
			"stock_entry": se.name,
			"produced": flt(wo.produced_qty, wo.precision("qty")),
			"loss": flt(wo.process_loss_qty, wo.precision("qty")),
			"remaining_target": remaining,
			"status": wo.status,
			"sisa_wip": qty.wip_remaining(wo),
			"warnings": warnings,
			# 3.4: final session short of target -> explicit close decision, no
			# automatic action whatsoever (7.8).
			"needs_close_decision": bool(normalized.is_final) and remaining > 0,
			"reference_doctype": "Stock Entry",
			"reference_doc": se.name,
		}

	return run_mutation(work_order, "finish_production", idempotency_key, payload, fn)


@frappe.whitelist()
def cancel_last_step(work_order, expected_target, idempotency_key=None):
	"""Cancel the newest cancelable step (7.7, order per 12); Supervisor only.
	After the lock the resolved target must still be `expected_target`:
	mismatch (or nothing left to cancel) -> STATE_CHANGED, nothing cancelled -
	including SE-A confirmed, SE-B created by someone else (SE-B stays intact).
	Pre-checks block with an Indonesian reason; core reverses stock, WO status
	and costing (P8-1) and the hook re-syncs the packing summary (8.1)."""

	def fn():
		access.require_role("Production Supervisor")
		wo = access.check_wo_access(work_order, "read")
		reasons, _bom_pct = access.config_blocked_reasons(wo)
		if reasons:
			frappe.throw(reasons[0])
		cancel.assert_not_stopped(wo)
		target = cancel.next_cancel_target(wo)
		assert_state(
			target is not None and target.name == expected_target,
			"Dokumen target berubah - muat ulang halaman dan konfirmasi ulang.",
		)
		reason = cancel.precheck_cancel(target)
		if reason:
			frappe.throw(reason)
		try:
			cancel.cancel_doc(target)
		except frappe.ValidationError as e:
			cancel.map_cancel_error(e)

		wo.reload()
		materials = _detail_materials(wo)
		operations, _job_cards = _detail_operations(wo)
		return {
			"work_order": wo.name,
			"cancelled": {"doctype": target.doctype, "name": target.name},
			"produced": flt(wo.produced_qty, wo.precision("qty")),
			"loss": flt(wo.process_loss_qty, wo.precision("qty")),
			"belum_diproduksi": qty.remaining_target(wo),
			"status": wo.status,
			"materials": materials,
			"next_action": _next_action(wo, [], materials, operations),
			# the fingerprint of the post-cancel state pre-fills the next
			# confirmation dialog (7.7)
			"fingerprint": cancel.production_fingerprint(wo.name),
			"reference_doctype": target.doctype,
			"reference_doc": target.name,
		}

	return run_mutation(
		work_order, "cancel_last_step", idempotency_key, {"expected_target": expected_target}, fn
	)


@frappe.whitelist()
def cancel_production(work_order, expected_fingerprint, idempotency_key=None):
	"""Cancel the whole production in one atomic request (7.7/12); Supervisor
	only. The docstatus-1 fingerprint is verified after the lock (mismatch ->
	STATE_CHANGED, no change at all), then the loop walks the fixed order:
	resolve newest target -> pre-check -> cancel - until no docstatus-1 SE/JC
	remains - and finally cancels the WO (draft Job Cards stay). Any failure
	midway propagates: frappe's request rollback wipes everything (10.3)."""

	def fn():
		access.require_role("Production Supervisor")
		wo = access.check_wo_access(work_order, "read")
		reasons, _bom_pct = access.config_blocked_reasons(wo)
		if reasons:
			frappe.throw(reasons[0])
		cancel.assert_not_stopped(wo)
		assert_state(
			cancel.production_fingerprint(wo.name) == expected_fingerprint,
			"Daftar dokumen produksi berubah - muat ulang halaman dan konfirmasi ulang.",
		)
		cancelled = []
		# one successful cancel per iteration; the bound keeps the loop finite
		for _ in range(len(cancel.all_members(wo.name))):
			target = cancel.next_cancel_target(wo)
			if target is None:
				break
			reason = cancel.precheck_cancel(target)
			if reason:
				frappe.throw(reason)
			try:
				cancel.cancel_doc(target)
			except frappe.ValidationError as e:
				cancel.map_cancel_error(e)
			cancelled.append({"doctype": target.doctype, "name": target.name})

		wo_doc = cancel.cancel_work_order(wo)
		return {
			"work_order": wo.name,
			"cancelled": cancelled,
			"status": wo_doc.status,
			"reference_doctype": "Work Order",
			"reference_doc": wo.name,
		}

	return run_mutation(
		work_order, "cancel_production", idempotency_key, {"expected_fingerprint": expected_fingerprint}, fn
	)


@frappe.whitelist()
def close_work_order(work_order, reason, idempotency_key=None):
	"""Close WO (7.8): Supervisor only; rejected while a submitted Job Card is
	still "Work In Progress" (mirror of the core close gate). Executed via
	document methods (4.2): update_status db_sets the status directly and
	on_close_or_cancel runs the close bookkeeping - NO Work Order save, so the
	production roles' read-only Work Order access suffices; `reason` is
	recorded as a Work Order comment."""
	reason = str(reason or "").strip()

	def fn():
		access.require_role("Production Supervisor")
		if not reason:
			frappe.throw("Alasan penutupan wajib diisi.")
		wo = access.check_wo_access(work_order, "read")
		if wo.docstatus != 1:
			frappe.throw(f"Work Order {wo.name} bukan dokumen yang sudah disubmit - penutupan ditolak.")
		if wo.status == "Closed":
			frappe.throw("Work Order sudah Closed.")
		if wo.get("operations"):
			# mirror of the core close gate (work_order.close_work_order)
			wip = frappe.get_all(
				"Job Card",
				filters={"work_order": wo.name, "status": "Work In Progress", "docstatus": 1},
				pluck="name",
			)
			if wip:
				frappe.throw(
					f"Selesaikan atau batalkan job card {', '.join(wip)} dulu sebelum menutup Work Order."
				)
		# update_status accepts Closed from any submitted status incl. Stopped
		# (core keeps status untouched only when already Closed) - traced from
		# work_order.update_status: db_set("status", "Closed") + update_required_items.
		wo.update_status("Closed")
		wo.on_close_or_cancel()
		wo.add_comment("Comment", text=f"Work Order ditutup. Alasan: {reason}")
		wo.reload()
		return {
			"work_order": wo.name,
			"status": wo.status,
			"produced": flt(wo.produced_qty, wo.precision("qty")),
			"loss": flt(wo.process_loss_qty, wo.precision("qty")),
			"belum_diproduksi": qty.remaining_target(wo),
			"reference_doctype": "Work Order",
			"reference_doc": wo.name,
		}

	return run_mutation(work_order, "close_work_order", idempotency_key, {"reason": reason}, fn)


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
			# WO coverage (core-maintained): qty fallback for Desk-made
			# Manufacture rows (no custom_p_good_qty) and the only per-entry
			# qty the Transfer/Consumption chronology rows have (task 19).
			"fg_completed_qty": flt(row.fg_completed_qty, wo.precision("qty")),
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


# ----------------------------------------------------------------- mutations


# 7.4: transfer only while the WO can still move material; 7.6: packing also
# stops at Completed (is_final leftovers go through the close decision, 3.4);
# 7.5: operation taps stop at Stopped (core rejects JC transactions there) and
# Closed alike.
BLOCKED_TRANSFER_STATUSES = ("Stopped", "Closed")
BLOCKED_FINISH_STATUSES = ("Stopped", *FINISHED_STATUSES)
BLOCKED_COMPLETE_STATUSES = ("Stopped", "Closed")


def _reject_if_not_open(wo, action, blocked_statuses):
	"""Post-lock status gate (7.4/7.6 step 1): submitted document, none of the
	blocked statuses."""
	if wo.docstatus != 1:
		frappe.throw(f"Work Order {wo.name} bukan dokumen yang sudah disubmit - {action} ditolak.")
	if wo.status in blocked_statuses:
		frappe.throw(f"Work Order dalam status {wo.status} - {action} tidak dapat dilakukan.")


def _transfer_allowance_pct():
	"""6.8: overproduction percentage, falling back to the transfer-extra knob
	ONLY when overproduction is 0 (core precedence in update_work_order_qty)."""
	pct = flt(
		frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order")
	)
	if not pct:
		pct = flt(frappe.db.get_single_value("Manufacturing Settings", "transfer_extra_materials_percentage"))
	return pct


def _over_transfer_gate(wo, se):
	"""6.8 pre-check (brief: cumulative transferred + requested qty vs
	qty x (1 + pct%)). Indicative only - the binding validation stays with core.

	After the check, the SE's WO-coverage claim (fg_completed_qty) is bounded to
	the remaining transfer allowance: core's own default claim (qty - produced)
	is FULL-target even on a partial pick, its coverage cap is skipped whenever
	the cumulative claim would exceed the allowance (stock_entry.py
	_cap_completed_qty_to_material_coverage), and the next update_work_order_qty
	then throws on claims alone - blocking a legitimate second partial transfer.
	The actual booked quantity still comes from core's coverage cap."""
	request = flt(sum(flt(row.qty) for row in se.items), wo.precision("qty"))
	transferred = flt(wo.material_transferred_for_manufacturing)
	pct = _transfer_allowance_pct()
	allowed = flt(flt(wo.qty) * (1 + pct / 100), wo.precision("qty"))
	if flt(transferred + request, 9) > flt(allowed, 9):
		frappe.throw(
			f"Total bahan yang diambil ({transferred + request:g}) melebihi batas transfer Work Order "
			f"({allowed:g} = target {wo.qty:g} + toleransi {pct:g}%). Simpan bahan ekstra di gudang "
			"asal (Stores), atau hubungi admin untuk menyetel toleransi transfer."
		)
	se.fg_completed_qty = flt(allowed - transferred, wo.precision("qty"))


def _check_indicative_stock(wo, se):
	"""Indicative stock pre-check at the source warehouse (7.4 step 3); the
	binding validation is core's at submit."""
	for row in se.items:
		warehouse = row.get("s_warehouse") or wo.source_warehouse
		if not warehouse:
			continue
		bin_qty = flt(
			frappe.db.get_value("Bin", {"item_code": row.item_code, "warehouse": warehouse}, "actual_qty")
		)
		if bin_qty < flt(row.qty, wo.precision("qty")):
			uom = row.get("stock_uom") or frappe.db.get_value("Item", row.item_code, "stock_uom")
			frappe.throw(
				f"Bahan {row.item_code} kurang {flt(flt(row.qty) - bin_qty, wo.precision('qty')):g} {uom} "
				f"di Gudang {warehouse} - hubungi gudang."
			)


def _session_materials(wo, fg_qty, explicit):
	"""Session material rows (3.2, INV5): a default per material plus the
	operator's explicit overrides; rows the session does not confirm must never
	carry core's proportional defaults.

	- normal WOs: default = WIP remaining net, capped at that balance
	  (qty.compute_session_materials);
	- skip_transfer WOs: material never passes the WIP warehouse (core books the
	  Manufacture rows straight from the source warehouse), so qty.wip_remaining
	  is structurally empty. Default = the BOM requirement scaled to the session
	  qty - exactly the rows core fills in the Manufacture dict. The WIP cap is
	  not meaningful here; core validates the actual stock at submit.
	"""
	if not cint(wo.skip_transfer):
		return qty.compute_session_materials(wo, explicit)

	precision = wo.precision("qty")
	session = {}
	for row in wo.required_items:
		if flt(row.required_qty) > 0:
			session[row.item_code] = flt(flt(row.required_qty) * fg_qty / flt(wo.qty), precision)
	if explicit:
		for item_code, used in explicit.items():
			if item_code not in session:
				frappe.throw(f"Bahan Dipakai {item_code} bukan kebutuhan Work Order ini.")
			used = qty._normalize(used, precision, f"Bahan Dipakai {item_code}")
			if used > 0:
				session[item_code] = used
			else:
				session.pop(item_code, None)
	return session


def _require_packing_schema():
	"""8.4: every custom_p_* field must exist on the Stock Entry meta before a
	packing session can be recorded."""
	missing = [f for f in CUSTOM_P_FIELDS if not frappe.get_meta("Stock Entry").has_field(f)]
	if missing:
		frappe.throw("Field packing belum terpasang - jalankan bench migrate / hubungi admin.")


def _operations_coverage_check(wo, normalized):
	"""INV6 mirror of core check_if_operations_completed: fg_completed_qty
	(good + loss) + produced vs each operation's completed + loss + allowance.
	Core still enforces this at submit; the app pre-empts it with one friendly
	Indonesian message instead of the core throw."""
	if not wo.operations:
		return
	allowance_pct = flt(
		frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order")
	)
	total = flt(wo.produced_qty) + normalized.good + normalized.loss_eksplisit
	for op in wo.operations:
		covered = (
			flt(op.completed_qty) + flt(op.process_loss_qty) + (allowance_pct / 100 * flt(op.completed_qty))
		)
		if flt(total, 9) > flt(covered, 9):
			frappe.throw(
				f"Operasi {op.operation} baru tercatat selesai untuk "
				f"{flt(op.completed_qty + op.process_loss_qty, wo.precision('qty')):g} {wo.stock_uom}. "
				f"Selesaikan operasi ini untuk {flt(total - covered, wo.precision('qty')):g} "
				f"{wo.stock_uom} lagi dulu sebelum packing."
			)


def _create_fg_batch(item_code):
	"""Fresh FG batch per packing session (proof P7a-3c recipe): the app owns
	batch creation because every core auto-batch path crashes on v16 (Serial
	and Batch Bundle built without the mandatory company)."""
	batch = frappe.new_doc("Batch")
	batch.item = item_code
	batch.batch_id = f"{item_code}-{uuid.uuid6()}"
	batch.insert(ignore_permissions=True)
	return batch.name


# --------------------------------------------------------------- complete_operation


def _parse_number(value, label):
	"""HTTP form fields arrive as strings; parse at max precision for the
	idempotency fingerprint (so "60" and 60 bind to one request). Unparseable
	input is rejected, never coerced (qty._normalize)."""
	return qty._normalize(value, 9, label)


def _to_bool(value):
	"""Boolean HTTP form field: "1"/"true"/"yes" (any case) are truthy."""
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes")
	return bool(value)


def _parse_start(started_at):
	"""`started_at` (7.5): the operator's real start of the tap -> honest
	duration (P13c); invalid input is rejected, never silently treated as now."""
	if not started_at:
		return now_datetime()
	try:
		start = get_datetime(started_at)
	except Exception:
		frappe.throw("Waktu mulai tidak valid.")
	# get_datetime happily parses ISO strings carrying "Z"/"+00:00" into an
	# AWARE datetime - which then crashes at the naive MySQL write of the
	# TimeLog from_time (raw 500). The SPA contract is naive DEVICE-LOCAL
	# time, so anything with a timezone is rejected in Indonesian instead.
	if start.tzinfo is not None:
		frappe.throw(
			"Waktu mulai tidak boleh membawa zona waktu - gunakan waktu perangkat apa adanya."
		)
	return start


def _sequence_precheck(wo, op, q):
	"""Friendly mirror of core validate_sequence_id (P13f): a previous
	operation counts by completed_qty only (process loss is NOT counted -
	P13 core surprise 3). Starting this card before the previous operation has
	caught up is rejected in Indonesian; core keeps the final say (the
	OperationSequenceError mapping below is the backstop)."""
	op_key = _op_order_key(op)
	for row in sorted(wo.operations, key=_op_order_key):
		if _op_order_key(row) >= op_key:
			break
		if flt(row.completed_qty) < q:
			frappe.throw(f"Selesaikan operasi {row.operation} dulu.")


def _ensure_additional_card(wo, op):
	"""7.5 / P13e: an operation short of the WO qty whose card was just
	submitted gets its follow-up Job Card immediately (the remainder can only
	be tapped on a new card). Payload per proof: `operation` explicitly -
	core get_operation_details omits it; pending_qty = qty so core
	validate_operation_data passes. Returns the new card name or None."""
	if op is None:
		return None
	precision = wo.precision("qty")
	sisa = flt(flt(wo.qty) - flt(op.completed_qty) - flt(op.process_loss_qty), precision)
	if sisa <= 0:
		return None
	open_card = {"work_order": wo.name, "operation_id": op.name, "docstatus": 0}
	if frappe.db.exists("Job Card", open_card):
		return None
	from erpnext.manufacturing.doctype.work_order.work_order import make_job_card

	make_job_card(wo.name, [{"name": op.name, "operation": op.operation, "qty": sisa, "pending_qty": sisa}])
	return frappe.get_value("Job Card", open_card, "name")


@contextlib.contextmanager
def _core_wo_propagation():
	"""11.2 step 5 / 11.4: the P13 choreography's core submit propagates the
	completion onto the Work Order with a plain wo.save() (job_card
	update_work_order_data) - permissions the production roles deliberately do
	NOT hold (WO read-only, 11.3): that save asserts write AND, because the WO
	is docstatus 1 (update-after-submit transition check), submit. The save is
	core-internal bookkeeping of the already-gated mutation (role / WO access /
	relation / docstatus / sequence all checked before this point), not a user
	action, so exactly those two assertions are waived while it runs. Every
	other permission check - including Job Card create/write/submit on the
	card itself - runs untouched.

	ponytail: class-level waiver - a concurrent Desk WO save in another thread
	during this window would also pass; acceptable at proxy-app traffic, move
	the propagation to a queued job if that ever matters."""

	def patched(doc, permtype="read", permlevel=None):
		if doc.doctype == "Work Order" and permtype in ("write", "submit"):
			return
		original(doc, permtype, permlevel)

	original, Document.check_permission = Document.check_permission, patched
	try:
		yield
	finally:
		Document.check_permission = original


def _apply_packing_fields(se, normalized, payload):
	"""8.1: record the session's packing categories + petugas on the Stock
	Entry (schema presence guaranteed by _require_packing_schema)."""
	se.custom_p_good_qty = normalized.good
	se.custom_p_reject_qty = normalized.reject
	se.custom_p_trial_qty = normalized.trial
	se.custom_p_sisa_qty = normalized.sisa
	se.custom_p_good_qty_pre = normalized.good_pre
	se.custom_p_reject_qty_pre = normalized.reject_pre
	se.custom_p_trial_qty_pre = normalized.trial_pre
	se.custom_p_sisa_qty_pre = normalized.sisa_pre
	se.custom_p_petugas_packing = normalized.petugas_packing
	se.custom_p_packing_note = payload.get("note")

# Work Order workspace server API — read side (T06) and shared stage rules.
#
# Contract: IMPLEMENTATION_PLAN.md + PROJECT_STATE.md "Action contract".
# All endpoints run as the session user; permissions come from frappe.get_list
# / has_permission. The stage is ALWAYS derived from current documents here —
# the UI never saves or sends a stage.

import frappe
from frappe import _
from frappe.utils import flt

DOCTYPE = "Work Order"

LIST_FIELDS = [
	"name",
	"status",
	"docstatus",
	"production_item",
	"qty",
	"produced_qty",
	"process_loss_qty",
	"material_transferred_for_manufacturing",
	"fg_warehouse",
	"wip_warehouse",
	"source_warehouse",
	"stock_uom",
	"planned_start_date",
	"planned_end_date",
	"actual_start_date",
	"actual_end_date",
	"custom_uom",
	"custom_conversion_factor",
	"custom_qty_in_uom",
	"custom_prepacking_confirmed",
]

STAGE_PERSIAPAN = "persiapan"
STAGE_MATERIAL = "material"
STAGE_OPERASI = "operasi"
STAGE_PREPACKING = "pre_packing"
STAGE_FINISH = "finish"
STAGE_SELESAI = "selesai"
STAGE_CANCELLED = "cancelled"
STAGE_REVIEW = "review"

# stage-filter scan cap: exact stage needs child-table truth, so stage-filtered
# lists scan at most this many permission-visible rows before slicing a page
STAGE_SCAN_LIMIT = 500


def _overproduction_allowance():
	return flt(
		frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order")
	)


def _operations_complete(operations, wo_qty, allowance):
	"""Mirror the native check_if_operations_completed tolerance per operation."""
	for op in operations:
		completed = flt(op.get("completed_qty")) + flt(op.get("process_loss_qty"))
		allowed = flt(op.get("completed_qty")) + (allowance / 100 * flt(op.get("completed_qty")))
		if completed < wo_qty and completed < allowed:
			return False
	return True


def _has_operations(name):
	return bool(
		frappe.get_all("Work Order Operation", filters={"parent": name}, limit=1, pluck="name")
	)


def derive_stage(wo, operations=None):
	"""Derive the workspace stage from server truth. `wo` is a dict/doc of the
	Work Order; `operations` (optional) avoids refetching child rows."""
	if wo.get("docstatus") == 2:
		return STAGE_CANCELLED
	if wo.get("status") in ("Stopped", "Closed"):
		return STAGE_REVIEW
	if wo.get("docstatus") == 0:
		return STAGE_PERSIAPAN

	qty = flt(wo.get("qty"))
	if qty > 0 and flt(wo.get("produced_qty")) + flt(wo.get("process_loss_qty")) >= qty:
		return STAGE_SELESAI

	if operations is None and wo.get("name"):
		operations = frappe.get_all(
			"Work Order Operation",
			filters={"parent": wo.get("name")},
			fields=["completed_qty", "process_loss_qty", "status"],
		)

	if operations and not _operations_complete(operations, qty, _overproduction_allowance()):
		return STAGE_OPERASI

	if flt(wo.get("material_transferred_for_manufacturing")) < qty:
		return STAGE_MATERIAL

	if not wo.get("custom_prepacking_confirmed"):
		return STAGE_PREPACKING
	return STAGE_FINISH


def _base_filters(search=None, production_item=None):
	filters, or_filters = [], []
	if search:
		or_filters.extend(
			[
				[DOCTYPE, "name", "like", f"%{search}%"],
				[DOCTYPE, "production_item", "like", f"%{search}%"],
			]
		)
	if production_item:
		filters.append([DOCTYPE, "production_item", "=", production_item])
	return filters, or_filters


def _stage_filters(stage):
	"""SQL-side narrowing per stage; exact matching happens in derive_stage."""
	filters = []
	if stage == STAGE_PERSIAPAN:
		filters.append([DOCTYPE, "docstatus", "=", 0])
	elif stage == STAGE_MATERIAL:
		filters.append([DOCTYPE, "docstatus", "=", 1])
		filters.append([DOCTYPE, "status", "not in", ["Completed", "Stopped", "Closed"]])
	elif stage in (STAGE_OPERASI, STAGE_PREPACKING, STAGE_FINISH):
		filters.append([DOCTYPE, "docstatus", "=", 1])
		filters.append([DOCTYPE, "status", "not in", ["Completed", "Stopped", "Closed"]])
		if stage == STAGE_FINISH:
			filters.append([DOCTYPE, "custom_prepacking_confirmed", "=", 1])
		elif stage == STAGE_PREPACKING:
			filters.append([DOCTYPE, "custom_prepacking_confirmed", "=", 0])
	elif stage == STAGE_SELESAI:
		filters.append([DOCTYPE, "docstatus", "=", 1])
		filters.append([DOCTYPE, "status", "=", "Completed"])
	elif stage == STAGE_CANCELLED:
		filters.append([DOCTYPE, "docstatus", "=", 2])
	return filters


@frappe.whitelist()
def wo_list(search=None, production_item=None, stage=None, start=0, page_len=20):
	"""Permission-filtered, paginated Work Order list for the workspace."""
	start, page_len = int(start), int(page_len)
	filters, or_filters = _base_filters(search, production_item)
	if stage:
		filters.extend(_stage_filters(stage))

	def fetch(start_at, limit):
		try:
			return frappe.get_list(
				DOCTYPE,
				filters=filters,
				or_filters=or_filters or None,
				fields=LIST_FIELDS,
				order_by="planned_start_date desc, creation desc",
				start=start_at,
				page_length=limit,
			)
		except frappe.PermissionError:
			# user cannot read Work Orders at all — empty list, not a hard error
			return []

	if not stage:
		rows = fetch(start, page_len)
	else:
		rows = fetch(0, STAGE_SCAN_LIMIT)
		rows = [r for r in rows if derive_stage(r) == stage]

	_batch_enrich(rows)
	for row in rows:
		row["stage"] = derive_stage(row)
	return rows[start : start + page_len] if stage else rows


def _batch_enrich(rows):
	"""Attach display-only fields for the list: item names and has-operations."""
	if not rows:
		return
	items = {r.production_item for r in rows if r.get("production_item")}
	names = frappe._dict()
	if items:
		for d in frappe.get_all(
			"Item", filters={"name": ("in", list(items))}, fields=["name", "item_name"], limit=0
		):
			names[d.name] = d.item_name
	parents = [r.name for r in rows]
	with_ops = set(
		frappe.get_all(
			"Work Order Operation",
			filters={"parent": ("in", parents)},
			pluck="parent",
			distinct=True,
		)
	)
	for r in rows:
		r.production_item_name = names.get(r.production_item) or r.production_item
		r.has_operations = r.name in with_ops


@frappe.whitelist()
def wo_detail(name):
	"""Full workspace detail for one Work Order; independent permission check."""
	if not frappe.has_permission(DOCTYPE, "read", doc=name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	wo = frappe.get_doc(DOCTYPE, name)
	data = wo.as_dict()
	allowance = _overproduction_allowance()

	operations = frappe.get_all(
		"Work Order Operation",
		filters={"parent": name},
		fields=["name", "operation", "status", "completed_qty", "process_loss_qty", "pending_qty"],
		order_by="idx",
	)

	job_cards = frappe.get_all(
		"Job Card",
		filters={"work_order": name},
		fields=[
			"name",
			"operation",
			"operation_id",
			"status",
			"docstatus",
			"for_quantity",
			"total_completed_qty",
			"pending_qty",
			"process_loss_qty",
			"workstation",
			"time_logs",
		],
		order_by="creation",
	)
	for card in job_cards:
		card["time_logs"] = frappe.get_all(
			"Job Card Time Log",
			filters={"parent": card.name},
			fields=["from_time", "to_time", "completed_qty"],
			order_by="idx",
		)
		employee_names = frappe.get_all(
			"Job Card Employee",
			filters={"parent": card.name},
			fields=["employee_name"],
		)
		card["employees"] = employee_names

	stock_entries = frappe.get_all(
		"Stock Entry",
		filters={"work_order": name, "docstatus": ("<", 2)},
		fields=["name", "purpose", "docstatus", "fg_completed_qty", "creation"],
		order_by="creation",
	)

	required_items = frappe.get_all(
		"Work Order Item",
		filters={"parent": name, "parenttype": DOCTYPE},
		fields=[
			"item_code", "item_name", "stock_uom",
			"required_qty", "transferred_qty", "consumed_qty", "source_warehouse",
		],
		order_by="idx",
	)

	# display names for people fields (Link User stores the id)
	users = [d for d in (data.get("custom_nama_penimbang"), data.get("custom_qc_produksi"), data.get("custom_qc_packing")) if d]
	full = frappe._dict(
		[(u.name, u.full_name) for u in frappe.get_all(
			"User", filters={"name": ("in", users)}, fields=["name", "full_name"], limit=0
		)]
	) if users else frappe._dict()
	data["custom_nama_penimbang_full"] = full.get(data.get("custom_nama_penimbang"))
	data["custom_qc_produksi_full"] = full.get(data.get("custom_qc_produksi"))
	data["custom_qc_packing_full"] = full.get(data.get("custom_qc_packing"))

	data["required_items"] = required_items
	data["operations"] = operations
	data["job_cards"] = job_cards
	data["stock_entries"] = stock_entries
	data["stage"] = derive_stage(data, operations)
	data["remaining_transfer"] = max(
		flt(data["qty"]) - flt(data["material_transferred_for_manufacturing"]), 0
	)
	data["remaining_produce"] = max(
		flt(data["qty"]) - flt(data["produced_qty"]) - flt(data["process_loss_qty"]), 0
	)
	data["max_allowed_qty"] = flt(data["qty"]) * (1 + allowance / 100)
	data["allowance_percentage"] = allowance

	return data


# --------------------------------------------------------------- T07 prepare

PREP_FIELD_MAP = {
	"adonan_ke": "custom_adonan_ke",  # Data
	"adonan": "custom_adonan",  # Int
	"jam_adonan": "custom_jam_adonan",  # Time
	"suhu_adonan": "custom_suhu_adonan",  # Float
	"penimbang": "custom_nama_penimbang",  # Link User
	"jumlah_kru": "custom_jumlah_kru",  # Int
	"leader": "custom_leader_produksi",  # Data (person's NAME, not a User/Int)
}


def _validate_prep_values(values):
	"""Return {fieldname: value} of validated prep inputs; raises on invalid."""
	cleaned = {}
	for key, value in values.items():
		if key not in PREP_FIELD_MAP:
			frappe.throw(_("Unknown preparation field: {0}").format(key))
		if value in (None, ""):
			continue
		fieldname = PREP_FIELD_MAP[key]
		if key == "penimbang":
			if not frappe.db.exists("User", value) or frappe.db.get_value(
				"User", value, "enabled"
			) in (0, None):
				frappe.throw(_("Penimbang harus User aktif: {0}").format(value))
			cleaned[fieldname] = value
		elif key == "leader":
			name = str(value).strip()
			if not name:
				continue
			cleaned[fieldname] = name  # person's name as text; never cast to number
		elif key == "adonan_ke":
			cleaned[fieldname] = str(value)
		elif key in ("adonan", "jumlah_kru"):
			cleaned[fieldname] = int(value)
			if cleaned[fieldname] < 0:
				frappe.throw(_("{0} tidak boleh negatif").format(key))
		elif key == "suhu_adonan":
			cleaned[fieldname] = float(value)
		elif key == "jam_adonan":
			frappe.utils.get_time(value)  # raises on garbage
			cleaned[fieldname] = value
	return cleaned


def _fill_warehouse_defaults(wo):
	"""Server-side mirror of the Auto Pick Warehouse behavior: fill empty WO
	warehouses from the production item's defaults (never override user data)."""
	item = frappe.db.get_value(
		"Item",
		wo.production_item,
		["custom_default_source_warehouse", "custom_default_wip_warehouse", "custom_default_fg_warehouse"],
		as_dict=True,
	)
	if not item:
		return
	if not wo.source_warehouse and item.custom_default_source_warehouse:
		wo.source_warehouse = item.custom_default_source_warehouse
	if not wo.wip_warehouse and item.custom_default_wip_warehouse:
		wo.wip_warehouse = item.custom_default_wip_warehouse
	if not wo.fg_warehouse and item.custom_default_fg_warehouse:
		wo.fg_warehouse = item.custom_default_fg_warehouse


@frappe.whitelist()
def prepare(name, values, submit=0):
	"""Persist preparation data; optionally submit a draft WO natively.

	Repeated calls are safe: a submitted WO is only updated via its
	allow-on-submit fields and is never resubmitted."""
	# lock the row first, then re-read the document under the lock
	frappe.has_permission(DOCTYPE, "write", doc=name, throw=True)
	frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
	wo = frappe.get_doc(DOCTYPE, name)
	if wo.docstatus == 2 or wo.status in ("Stopped", "Closed"):
		frappe.throw(_("Work Order {0} tidak bisa disiapkan").format(name))

	cleaned = _validate_prep_values(frappe.parse_json(values) or {})
	if wo.docstatus == 0:
		_fill_warehouse_defaults(wo)
	for fieldname, value in cleaned.items():
		wo.set(fieldname, value)

	submitted_now = False
	if wo.docstatus == 0 and frappe.utils.cint(submit):
		wo.submit()
		submitted_now = True
	else:
		wo.save()  # submitted WOs: validate_update_after_submit enforces the field list

	return {
		"name": wo.name,
		"docstatus": wo.docstatus,
		"status": wo.status,
		"stage": derive_stage(wo),
		"submitted_now": submitted_now,
		"job_cards": frappe.get_all("Job Card", filters={"work_order": wo.name}, pluck="name"),
	}


# -------------------------------------------------- T08 material transfer

@frappe.whitelist()
def transfer_materials(name):
	"""Create and submit the native Material Transfer for Manufacture for the
	REMAINING planned requirement. Existing submitted transfers are respected;
	existing DRAFT transfers block the action (never silently submitted)."""
	from erpnext.manufacturing.doctype.work_order.work_order import (
		make_stock_entry as make_wo_stock_entry,
	)

	frappe.has_permission(DOCTYPE, "write", doc=name, throw=True)
	frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
	wo = frappe.get_doc(DOCTYPE, name)
	if wo.docstatus != 1 or wo.status in ("Stopped", "Closed"):
		frappe.throw(_("Material transfer tidak tersedia untuk Work Order {0}").format(name))

	transferred_before = flt(wo.material_transferred_for_manufacturing)
	remaining = max(flt(wo.qty) - transferred_before, 0)

	draft = frappe.db.get_value(
		"Stock Entry",
		{"work_order": name, "purpose": "Material Transfer for Manufacture", "docstatus": 0},
		"name",
	)
	if draft:
		frappe.throw(
			_("Selesaikan atau batalkan draft transfer {0} terlebih dahulu").format(
				frappe.utils.get_link_to_form("Stock Entry", draft)
			)
		)

	moved = 0
	entry_name = None
	if remaining > 0:
		se = frappe.get_doc(make_wo_stock_entry(name, "Material Transfer for Manufacture", qty=remaining))
		se.insert()
		se.submit()  # native shortage/validation errors roll the whole request back
		moved = remaining
		entry_name = se.name

	wo.reload()
	return {
		"name": wo.name,
		"stock_entry": entry_name,
		"transferred_now": moved,
		"material_transferred_for_manufacturing": flt(wo.material_transferred_for_manufacturing),
		"stage": derive_stage(wo),
	}


# ------------------------------------------------- T09 Job Card actions

def _locked_job_card(name, job_card):
	"""Fetch the exact Job Card and prove it belongs to this Work Order."""
	frappe.has_permission(DOCTYPE, "write", doc=name, throw=True)
	wo = frappe.get_doc(DOCTYPE, name)
	if wo.docstatus != 1 or wo.status in ("Stopped", "Closed"):
		frappe.throw(_("Job Card actions tidak tersedia untuk Work Order {0}").format(name))

	card = frappe.get_doc("Job Card", job_card)  # raises DoesNotExistError on wrong id
	if card.work_order != name:
		frappe.throw(
			_("Job Card {0} bukan milik Work Order {1}").format(job_card, name),
			frappe.PermissionError,
		)
	return card


def _resolve_employees(employees):
	"""Normalize the employees payload; fall back to the session user's Employee."""
	parsed = frappe.parse_json(employees) if isinstance(employees, str) else employees
	if parsed:
		return [{"employee": e.get("employee") if isinstance(e, dict) else e} for e in parsed]
	if frappe.session.user not in ("Guest", "Administrator"):
		self_employee = frappe.db.get_value(
			"Employee", {"user": frappe.session.user, "status": "Active"}, "name"
		)
		if self_employee:
			return [{"employee": self_employee}]
	frappe.throw(_("Data karyawan (Employee) diperlukan untuk mulai Job Card"))


@frappe.whitelist()
def jobcard_start(name, job_card, start_time=None, employees=None):
	"""Start the native timer on exactly this Job Card."""
	card = _locked_job_card(name, job_card)
	if any(not t.to_time for t in (card.time_logs or [])):
		frappe.throw(_("Job Card {0} sudah berjalan (time log masih terbuka)").format(job_card))
	card.start_timer(start_time=start_time or frappe.utils.now(), employees=_resolve_employees(employees))
	card.reload()
	return {
		"name": card.name,
		"status": card.status,
		"time_logs": [
			{"from_time": str(t.from_time), "to_time": str(t.to_time or ""), "completed_qty": flt(t.completed_qty)}
			for t in (card.time_logs or [])
		],
	}


@frappe.whitelist()
def jobcard_complete(name, job_card, qty=None, end_time=None, auto_submit=1, pending_qty=None, process_loss_qty=None):
	"""Complete (a cycle of) this Job Card with quantity; delegates to the
	native complete_job_card, which enforces docstatus, overlaps and the
	per-operation overproduction allowance."""
	card = _locked_job_card(name, job_card)
	qty = flt(qty) if qty is not None else 0
	remaining = flt(card.for_quantity) - flt(card.total_completed_qty)
	if pending_qty is None and process_loss_qty is None:
		# single-action completion: everything not completed this cycle is pending
		pending_qty = remaining - qty
	if pending_qty is not None and pending_qty < 0 or qty > remaining:
		frappe.throw(
			_("Qty selesai ({0}) melebihi sisa qty Job Card ({1})").format(qty, remaining)
		)
	kwargs = frappe._dict(
		qty=qty,
		for_quantity=flt(card.for_quantity),  # forces the native qty-split validation
		end_time=end_time or frappe.utils.now(),
		pending_qty=pending_qty,
		process_loss_qty=process_loss_qty,
		auto_submit=frappe.utils.cint(auto_submit),
	)
	card.complete_job_card(**kwargs)
	card.reload()
	wo = frappe.get_doc(DOCTYPE, name)
	return {
		"name": card.name,
		"docstatus": card.docstatus,
		"status": card.status,
		"total_completed_qty": flt(card.total_completed_qty),
		"pending_qty": flt(card.pending_qty),
		"work_order_status": wo.status,
		"work_order_stage": derive_stage(wo),
	}


# ------------------------------------------- T10 prepacking confirmation

PREPACKING_FIELD_MAP = {
	"good": "custom_good_qty_prepacking",  # stock UOM (Pcs), must be > 0
	"reject": "custom_reject_qty_prepacking",
	"trial": "custom_trial_qty_prepacking",
	"sisa": "custom_sisa_qty_prepacking",
	"jam_pembekuan": "custom_jam_pembekuan",  # Time
	"qc_produksi": "custom_qc_produksi",  # Link User
	"box_1": "custom_box_1",  # kg, display-only weight
	"box_2": "custom_box_2",
}


def _validate_prepacking(values):
	"""Validate the ENTIRE payload before any mutation. Returns cleaned dict."""
	cleaned = {}
	for key, value in values.items():
		if key not in PREPACKING_FIELD_MAP:
			frappe.throw(_("Field pre-packing tidak dikenal: {0}").format(key))
		if value in (None, ""):
			continue
		fieldname = PREPACKING_FIELD_MAP[key]
		if key == "good":
			good = float(value)
			if good != good or good in (float("inf"), float("-inf")) or good <= 0:
				frappe.throw(_("Good Qty pre-packing harus angka lebih besar dari 0"))
			cleaned[fieldname] = good
		elif key in ("reject", "trial", "sisa", "box_1", "box_2"):
			amount = float(value)
			if amount != amount or amount in (float("inf"), float("-inf")) or amount < 0:
				frappe.throw(_("{0} harus angka desimal >= 0").format(key))
			cleaned[fieldname] = amount
		elif key == "qc_produksi":
			if not frappe.db.exists("User", value) or not frappe.db.get_value("User", value, "enabled"):
				frappe.throw(_("QC Produksi harus User aktif: {0}").format(value))
			cleaned[fieldname] = value
		elif key == "jam_pembekuan":
			frappe.utils.get_time(value)  # raises on garbage
			cleaned[fieldname] = value
	return cleaned


@frappe.whitelist()
def confirm_prepacking(name, values):
	"""Save/confirm the prepacking block. good must be finite and > 0 — the
	validation completes BEFORE anything is written. Zero reject/trial/sisa is
	valid. Postpacking fields are never touched here."""
	frappe.has_permission(DOCTYPE, "write", doc=name, throw=True)
	frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
	wo = frappe.get_doc(DOCTYPE, name)
	if wo.docstatus != 1 or wo.status in ("Stopped", "Closed"):
		frappe.throw(_("Pre-packing tidak tersedia untuk Work Order {0}").format(name))

	stage = derive_stage(wo)
	if stage not in (STAGE_PREPACKING, STAGE_FINISH):
		frappe.throw(
			_("Pre-packing belum tersedia: tahap sekarang {0} (selesaikan material/operasi dulu)").format(stage)
		)

	cleaned = _validate_prepacking(frappe.parse_json(values) or {})
	if PREPACKING_FIELD_MAP["good"] not in cleaned:
		frappe.throw(_("Good Qty pre-packing wajib diisi (> 0)"))

	for fieldname, value in cleaned.items():
		wo.set(fieldname, value)
	wo.set("custom_prepacking_confirmed", 1)
	wo.save()  # update-after-submit: native allow_on_submit enforcement

	return {
		"name": wo.name,
		"stage": derive_stage(wo),
		"good": flt(wo.custom_good_qty_prepacking),
		"box_1": flt(wo.custom_box_1),
		"box_2": flt(wo.custom_box_2),
	}


# ------------------------------------------------------- T11 finish action

@frappe.whitelist()
def finish(name):
	"""Submit the Manufacture for the confirmed prepacking quantity.

	Re-validates every prerequisite server-side, locks the WO row, reuses the
	proven T03/T04 transaction shape: native entry builder with qty = confirmed
	good, raw-material rows restored to the transferred (planned) quantities,
	finished-goods rows only on the real FG item, batch handling left to the
	native flow + bakery_manufacturing override. Atomic: insert+submit in one
	request, so any failure rolls back everything."""
	from erpnext.manufacturing.doctype.work_order.work_order import (
		make_stock_entry as make_wo_stock_entry,
	)
	frappe.has_permission(DOCTYPE, "write", doc=name, throw=True)
	frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
	wo = frappe.get_doc(DOCTYPE, name)
	if wo.docstatus != 1 or wo.status in ("Stopped", "Closed"):
		frappe.throw(_("Finish tidak tersedia untuk Work Order {0}").format(name))

	good = flt(wo.custom_good_qty_prepacking)
	if not wo.custom_prepacking_confirmed or good <= 0:
		frappe.throw(_("Pre-packing harus dikonfirmasi dengan Good Qty > 0 sebelum finish"))

	# native guards re-checked here for clear errors before building the entry
	allowance = flt(
		frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order")
	)
	if good > flt(wo.qty) * (1 + allowance / 100):
		frappe.throw(
			_("Good Qty {0} melebihi batas overproduksi ({1})").format(
				good, flt(wo.qty) * (1 + allowance / 100)
			)
		)

	# native guards (operations complete, duplicate entry, overproduction) throw
	# from the builder itself — surfaced to the operator as-is
	se = frappe.get_doc(make_wo_stock_entry(name, "Manufacture", qty=good))

	# workspace consumption rule (plan non-negotiable #2): restore RM rows to
	# the transferred (planned) quantities — native backflush prorates to yield
	transferred = frappe._dict()
	for r in frappe.get_all(
		"Stock Entry Detail",
		filters={
			"parent": ("in", frappe.get_all(
				"Stock Entry",
				filters={
					"work_order": name,
					"purpose": "Material Transfer for Manufacture",
					"docstatus": 1,
				},
				pluck="name",
			)),
			"docstatus": 1,
		},
		fields=["item_code", "qty"],
	):
		transferred[r.item_code] = transferred.get(r.item_code, 0.0) + flt(r.qty)

	fg_item = wo.production_item
	for row in se.items:
		if row.is_finished_item:
			if row.item_code != fg_item:
				frappe.throw(_("Baris barang jadi tidak valid: {0}").format(row.item_code))
		elif row.item_code in transferred:
			row.qty = transferred[row.item_code]
			row.transfer_qty = row.qty * flt(row.conversion_factor or 1)

	se.insert()
	se.submit()  # StockOverProductionError / valuation failures roll the request back

	wo.reload()
	batch = None
	for row in frappe.get_doc("Stock Entry", se.name).items:
		if row.is_finished_item and row.serial_and_batch_bundle:
			entries = frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": row.serial_and_batch_bundle},
				fields=["batch_no", "qty"],
			)
			if len(entries) == 1:
				batch = entries[0].batch_no

	return {
		"name": wo.name,
		"stock_entry": se.name,
		"batch": batch,
		"produced_qty": flt(wo.produced_qty),
		"process_loss_qty": flt(wo.process_loss_qty),
		"status": wo.status,
		"stage": derive_stage(wo),
	}

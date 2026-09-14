# T05 — Work Order custom field upgrade (idempotent)
#
# Adds the workspace fields required by IMPLEMENTATION_PLAN.md and migrates
# custom_leader_produksi from Int to Data (person's name, preserved as text).
#
# Idempotency: apply() only creates missing fields, only flips properties that
# differ, and only converts the leader column when it is still Int — running it
# any number of times converges to the same state. Registered on after_migrate
# and safe to run ad hoc via `bench --site <site> execute production_app.upgrade.apply`.

import json
import os

import frappe

DOCTYPE = "Work Order"

WORKSPACE_FIELDS = [
	# fieldname, label, fieldtype, insert_after, allow_on_submit, extra
	{
		"fieldname": "custom_box_1",
		"label": "Box 1",
		"fieldtype": "Data",
		"insert_after": "custom_sisa_qty_prepacking",
		"allow_on_submit": 1,
		"non_negative": 0,
		"description": "Identifier Box 1 serah terima (teks, contoh BX-2201)",
	},
	{
		"fieldname": "custom_box_2",
		"label": "Box 2",
		"fieldtype": "Data",
		"insert_after": "custom_box_1",
		"allow_on_submit": 1,
		"non_negative": 0,
		"description": "Identifier Box 2 serah terima (teks, contoh BX-2202)",
	},
	{
		"fieldname": "custom_prepacking_confirmed",
		"label": "Pre-Packing Confirmed",
		"fieldtype": "Check",
		"insert_after": "custom_box_2",
		"allow_on_submit": 1,
		"print_hide": 1,
		"description": "Marker: prepacking block was deliberately saved/confirmed",
	},
	{
		"fieldname": "custom_postpacking_confirmed",
		"label": "Post-Packing Confirmed",
		"fieldtype": "Check",
		"insert_after": "custom_qc_packing",
		"allow_on_submit": 1,
		"print_hide": 1,
		"description": "Marker: postpacking block was deliberately saved/confirmed",
	},
]

# allow-on-submit enablement required by the workspace actions (submitted WOs)
ALLOW_ON_SUBMIT_FIELDS = [
	"custom_nama_penimbang",
	"custom_jumlah_kru",
	"custom_leader_produksi",
	"custom_qc_produksi",
	"custom_jam_packing",  # T27: confirm_postpacking wo.save() after submit
	"custom_qc_packing",  # T27: confirm_postpacking wo.save() after submit
]

LEADER_FIELDNAME = "custom_leader_produksi"

BOX_FIELDNAMES = ("custom_box_1", "custom_box_2")

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "snapshots")


def snapshot():
	"""Narrow snapshot of exactly what this upgrade may touch. Run BEFORE apply()."""
	os.makedirs(SNAPSHOT_DIR, exist_ok=True)
	path = os.path.join(SNAPSHOT_DIR, "T05-pre-migration.json")

	fields = frappe.get_all(
		"Custom Field",
		filters={"dt": DOCTYPE},
		fields=[
			"name",
			"fieldname",
			"label",
			"fieldtype",
			"insert_after",
			"allow_on_submit",
			"non_negative",
			"options",
		],
		order_by="idx",
	)

	leader_fieldtype = frappe.db.get_value(
		"Custom Field", {"dt": DOCTYPE, "fieldname": LEADER_FIELDNAME}, "fieldtype"
	)
	leader_rows = frappe.get_all(
		DOCTYPE,
		filters={LEADER_FIELDNAME: ("is", "set")},
		fields=["name", f"{LEADER_FIELDNAME} as value"],
	)
	distinct = {}
	for row in leader_rows:
		key = str(row.value)
		distinct[key] = distinct.get(key, 0) + 1

	snapshot_data = {
		"doctype": DOCTYPE,
		"captured_at": frappe.utils.now(),
		"custom_fields": fields,
		"leader_produksi": {
			"fieldtype": leader_fieldtype,
			"rows_with_value": len(leader_rows),
			"distinct_values": distinct,
		},
	}

	with open(path, "w") as f:
		json.dump(snapshot_data, f, indent=2, sort_keys=True, default=str)
	return path


def _upsert_field(dt, spec):
	existing = frappe.db.get_value(
		"Custom Field", {"dt": dt, "fieldname": spec["fieldname"]}, "name"
	)
	if existing:
		changed = False
		cf = frappe.get_doc("Custom Field", existing)
		for key, value in spec.items():
			if cf.get(key) != value:
				cf.db_set(key, value)
				changed = True
		return ("updated" if changed else "unchanged", existing)

	doc = frappe.get_doc({"doctype": "Custom Field", "dt": dt, **spec})
	doc.insert()
	return ("created", doc.name)


# Production App warehouse defaults live on the native Manufacturing Settings
# single (no new DocType); applied by prepare() to Work Orders with empty
# warehouse fields. Fieldnames mirror the Work Order form fields.
WAREHOUSE_DEFAULT_FIELDS = [
	{
		"fieldname": "custom_default_source_warehouse",
		"label": "Default Source Warehouse (Production App)",
		"fieldtype": "Link",
		"options": "Warehouse",
		"description": "Production App: gudang bahan baku default untuk Work Order",
	},
	{
		"fieldname": "custom_default_wip_warehouse",
		"label": "Default WIP Warehouse (Production App)",
		"fieldtype": "Link",
		"options": "Warehouse",
		"description": "Production App: gudang proses produksi (WIP) default",
	},
	{
		"fieldname": "custom_default_fg_warehouse",
		"label": "Default Target Warehouse (Production App)",
		"fieldtype": "Link",
		"options": "Warehouse",
		"description": "Production App: gudang barang jadi default",
	},
	{
		"fieldname": "custom_default_scrap_warehouse",
		"label": "Default Scrap Warehouse (Production App)",
		"fieldtype": "Link",
		"options": "Warehouse",
		"description": "Production App: gudang scrap default",
	},
	{
		"fieldname": "custom_default_handover_warehouse",
		"label": "Default Handover Warehouse (Production App)",
		"fieldtype": "Link",
		"options": "Warehouse",
		"description": "Production App: gudang serah terima default (MR Material Transfer ke gudang ini)",
	},
]


def ensure_warehouse_default_fields():
	"""Create the Production App warehouse-default custom fields on
	Manufacturing Settings, anchored after the doctype's current last field
	(last Custom Field if any, else last standard DocField). Idempotent;
	existing fields are never moved or relabeled."""
	anchor = frappe.get_all(
		"Custom Field",
		filters={"dt": "Manufacturing Settings"},
		order_by="idx desc",
		limit=1,
		pluck="fieldname",
	)
	if not anchor:
		anchor = frappe.get_all(
			"DocField",
			filters={"parent": "Manufacturing Settings"},
			order_by="idx desc",
			limit=1,
			pluck="fieldname",
		)
	anchor = anchor[0]
	out = []
	for spec in WAREHOUSE_DEFAULT_FIELDS:
		existing = frappe.db.get_value(
			"Custom Field",
			{"dt": "Manufacturing Settings", "fieldname": spec["fieldname"]},
			"name",
		)
		if existing:
			out.append(f"{spec['fieldname']}: unchanged")
			continue
		doc = frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "Manufacturing Settings",
			"insert_after": anchor,
			**spec,
		})
		doc.insert()
		anchor = spec["fieldname"]
		out.append(f"{spec['fieldname']}: created")
	if out:
		frappe.clear_cache(doctype="Manufacturing Settings")
	return out


def ensure_batch_permission():
	"""Manufacturing User (operator workspace role) must read/create Batch:
	native Work Order submission creates the FG batch for batch-tracked items,
	and the doctype's stock DocPerm only grants Item Manager — without this the
	Persiapan submit fails for every operator. Minimal grant: read + create."""
	snap_path = os.path.join(SNAPSHOT_DIR, "T18-batch-perms-pre.json")
	if not os.path.exists(snap_path):
		os.makedirs(SNAPSHOT_DIR, exist_ok=True)
		with open(snap_path, "w") as f:
			json.dump(
				{
					"captured_at": frappe.utils.now(),
					"docperm": frappe.get_all(
						"DocPerm", filters={"parent": "Batch"},
						fields=["role", "permlevel", "read", "write", "create", "submit"],
					),
					"custom_docperm": frappe.get_all(
						"Custom DocPerm", filters={"parent": "Batch"},
						fields=["role", "permlevel", "read", "write", "create", "submit"],
					),
				},
				f, indent=2, sort_keys=True, default=str,
			)

	existing = frappe.db.get_value(
		"Custom DocPerm", {"parent": "Batch", "role": "Manufacturing User"}, "name"
	)
	if existing:
		return "unchanged"
	frappe.get_doc({
		"doctype": "Custom DocPerm",
		"parent": "Batch",
		"role": "Manufacturing User",
		"permlevel": 0,
		"read": 1,
		"create": 1,
	}).insert()
	frappe.clear_cache(doctype="Batch")
	return "created"


def ensure_stock_user_batch_read():
	"""Stock User as the gudang side of Serah Terima (user decision 2026-09-14):
	the board derivation and create_request read the FG Batch (get_batch_qty +
	batch gate in _wo_lot_rows); native Batch DocPerms grant only Item/Stock
	Manager. Minimal additive grant: read. Snapshot-first, idempotent."""
	snap_path = os.path.join(SNAPSHOT_DIR, "stockuser-batch-read-pre.json")
	if not os.path.exists(snap_path):
		os.makedirs(SNAPSHOT_DIR, exist_ok=True)
		with open(snap_path, "w") as f:
			json.dump(
				{
					"captured_at": frappe.utils.now(),
					"docperm": frappe.get_all(
						"DocPerm", filters={"parent": "Batch"},
						fields=["role", "permlevel", "read", "write", "create", "submit"],
					),
					"custom_docperm": frappe.get_all(
						"Custom DocPerm", filters={"parent": "Batch"},
						fields=["role", "permlevel", "read", "write", "create", "submit"],
					),
				},
				f, indent=2, sort_keys=True, default=str,
			)

	if frappe.db.exists("Custom DocPerm", {"parent": "Batch", "role": "Stock User"}):
		return "unchanged"
	frappe.get_doc({
		"doctype": "Custom DocPerm",
		"parent": "Batch",
		"role": "Stock User",
		"permlevel": 0,
		"read": 1,
	}).insert()
	frappe.clear_cache(doctype="Batch")
	return "created"


# ---------------------------------------------------------------------------
# T22 — Serah Terima handover metadata (HANDOVER_PLAN.md §3, task-22-brief):
# Role "Gudang Barang Jadi", custom DocPerms (incl. reconciling the pre-existing
# Manufacturing User MR row down to read/write), the 10 MR custom fields T21
# left on the site, and the 5th warehouse default. All idempotent.
# ---------------------------------------------------------------------------

HANDOVER_ROLE = "Gudang Barang Jadi"

# Formalizes exactly what T21 created on the site (task-21-report §4); the
# specs below mirror those live definitions, so the first apply() is a no-op.
MR_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_box_1",
		"label": "Box 1",
		"fieldtype": "Data",
		"insert_after": "custom_note",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_box_2",
		"label": "Box 2",
		"fieldtype": "Data",
		"insert_after": "custom_box_1",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_good_qty_postpacking",
		"label": "Good Qty Post-Packing",
		"fieldtype": "Float",
		"insert_after": "custom_box_2",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_reject_qty_postpacking",
		"label": "Reject Qty Post-Packing",
		"fieldtype": "Float",
		"insert_after": "custom_good_qty_postpacking",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_trial_qty_postpacking",
		"label": "Trial Qty Post-Packing",
		"fieldtype": "Float",
		"insert_after": "custom_reject_qty_postpacking",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_sisa_qty_postpacking",
		"label": "Sisa Qty Post-Packing",
		"fieldtype": "Float",
		"insert_after": "custom_trial_qty_postpacking",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_jam_packing",
		"label": "Jam Packing",
		"fieldtype": "Time",
		"insert_after": "custom_sisa_qty_postpacking",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_qc_packing",
		"label": "QC Packing",
		"fieldtype": "Link",
		"options": "User",
		"insert_after": "custom_jam_packing",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_postpacking_confirmed",
		"label": "Post-Packing Confirmed",
		"fieldtype": "Check",
		"insert_after": "custom_qc_packing",
		"allow_on_submit": 1,
	},
	{
		"fieldname": "custom_work_order",
		"label": "Work Order",
		"fieldtype": "Link",
		"options": "Work Order",
		"insert_after": "from_warehouse",
		"allow_on_submit": 0,
	},
]

# Permission matrix (HANDOVER_PLAN.md §3). Rights not listed stay/stored 0 on
# upsert. Gudang Barang Jadi: full MR lifecycle + read everywhere it must see.
# Manufacturing User: read/write on MR only (drift fix — the pre-existing
# custom row granted create/submit; snapshot T22-pre-migration.json holds the
# before-state for rollback).
DOCPERM_MATRIX = {
	"Material Request": {
		HANDOVER_ROLE: {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1},
		"Manufacturing User": {"read": 1, "write": 1, "create": 0, "submit": 0, "cancel": 0, "amend": 0},
	},
	"Material Request Item": {
		HANDOVER_ROLE: {"read": 1, "create": 1},
		"Manufacturing User": {"read": 1},
	},
	"Work Order": {HANDOVER_ROLE: {"read": 1}},
	"Batch": {HANDOVER_ROLE: {"read": 1}},
	"Stock Entry": {HANDOVER_ROLE: {"read": 1}},
	"Item": {HANDOVER_ROLE: {"read": 1}},
	# Ruling 6 check: no standard DocPerm grants Warehouse read to the new role
	# (role is new — zero rows anywhere); without it the MR warehouse links and
	# desk pickers are unusable for gudang users. Additive only.
	"Warehouse": {HANDOVER_ROLE: {"read": 1}},
}

DOCPERM_RIGHTS = ("read", "write", "create", "submit", "cancel", "amend")

T22_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "T22-pre-migration.json")

# T27 — Work Order postpacking stage: pre-change snapshot of the Work Order
# custom fields this upgrade may touch (marker creation, allow_on_submit flips).
POSTPACKING_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "postpacking-pre.json")

# Follow-up user 2026-09-14 (FU10) — Nama Penimbang & QC Produksi become a
# person's NAME as free text (Data), the same semantics as Leader Produksi;
# they were Link User. Existing values (User ids) are preserved as text —
# nothing is rewritten and no names are invented.
NAME_TEXT_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "penimbang-qc-text-pre.json")
QC_PACKING_TEXT_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "qc-packing-text-pre.json")
NAME_TEXT_FIELDNAMES = ("custom_nama_penimbang", "custom_qc_produksi")


def snapshot_t27():
	"""Pre-change snapshot of the Work Order custom fields (full list, ordered),
	so the T27 metadata change is reversible. Runs BEFORE any change; apply()
	calls it only when the file is absent (idempotent)."""
	os.makedirs(SNAPSHOT_DIR, exist_ok=True)
	data = {
		"captured_at": frappe.utils.now(),
		"custom_fields": frappe.get_all(
			"Custom Field",
			filters={"dt": DOCTYPE},
			fields=[
				"fieldname", "label", "fieldtype", "insert_after",
				"allow_on_submit", "options", "non_negative", "print_hide", "description",
			],
			order_by="idx",
		),
	}
	with open(POSTPACKING_SNAPSHOT, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True, default=str)
	return POSTPACKING_SNAPSHOT


def snapshot_t22():
	"""Pre-change snapshot of everything the T22 upgrade may touch: DocPerms
	(standard + custom) on MR / MR Item, the custom fields, and role existence.
	Runs BEFORE any metadata change (apply() calls it when the file is absent)."""
	os.makedirs(SNAPSHOT_DIR, exist_ok=True)
	data = {
		"captured_at": frappe.utils.now(),
		"roles": {
			role: bool(frappe.db.exists("Role", role))
			for role in (HANDOVER_ROLE, "Manufacturing User")
		},
		"custom_fields": frappe.get_all(
			"Custom Field",
			filters={"dt": ("in", ["Material Request", "Material Request Item", "Manufacturing Settings"])},
			fields=["dt", "fieldname", "label", "fieldtype", "options", "insert_after", "allow_on_submit"],
			order_by="dt, idx",
		),
	}
	for dt in ("Material Request", "Material Request Item"):
		for kind, doctype in (("docperm", "DocPerm"), ("custom_docperm", "Custom DocPerm")):
			data.setdefault(kind, {})[dt] = frappe.get_all(
				doctype,
				filters={"parent": dt},
				fields=["role", "permlevel", "read", "write", "create", "submit", "cancel", "amend"],
				order_by="role",
			)
	with open(T22_SNAPSHOT, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True, default=str)
	return T22_SNAPSHOT


def _ensure_docperm(doctype, role, flags):
	"""Upsert one Custom DocPerm row to the matrix flags (unmanaged rights are
	never touched). Explicit 0 flags clear drifted grants (the T22 drift fix)."""
	existing = frappe.db.get_value(
		"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}, "name"
	)
	if not existing:
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": doctype, "role": role, "permlevel": 0, **flags}
		).insert()
		return "created"
	doc = frappe.get_doc("Custom DocPerm", existing)
	changed = False
	for right, value in flags.items():
		if int(doc.get(right) or 0) != value:
			doc.db_set(right, value)
			changed = True
	return "updated" if changed else "unchanged"


def ensure_handover_permissions():
	"""Role "Gudang Barang Jadi" + the DOCPERM_MATRIX custom DocPerms. Idempotent."""
	out = []
	if not frappe.db.exists("Role", HANDOVER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": HANDOVER_ROLE, "desk_access": 1}).insert()
		out.append(f"role {HANDOVER_ROLE}: created")

	touched = set()
	for doctype, roles in DOCPERM_MATRIX.items():
		for role, flags in roles.items():
			out.append(f"{doctype}/{role}: {_ensure_docperm(doctype, role, flags)}")
			touched.add(doctype)
	for doctype in touched:
		frappe.clear_cache(doctype=doctype)
	return out


def ensure_handover_mr_fields():
	"""Formalize the 10 MR custom fields idempotently (create-if-missing,
	update-if-different — the T21-created set converges as 'unchanged')."""
	out = []
	for spec in MR_CUSTOM_FIELDS:
		dt = "Material Request Item" if spec["fieldname"] == "custom_work_order" else "Material Request"
		action, name = _upsert_field(dt, spec)
		out.append(f"{dt}.{spec['fieldname']}: {action}")
	frappe.clear_cache(doctype="Material Request")
	frappe.clear_cache(doctype="Material Request Item")
	return out


def ensure_box_identifier_fields():
	"""Follow-up user 2026-09-14: Box 1/2 on Work Order become TEXT identifiers
	(e.g. BX-2201) written by the Serah Terima Post-Packing step — they were
	Float kg prepacking weights no row ever used (the snapshot records the
	non-zero count; verified 0 before this shipped). decimal(21,9) NOT NULL
	becomes varchar(140) NULL like the leader migration. Runs BEFORE the
	WORKSPACE_FIELDS upsert in apply() so the fieldtype flip and the column
	ALTER land together; the upsert then converges label/non_negative/
	description. Snapshot-first, idempotent."""
	snap_path = os.path.join(SNAPSHOT_DIR, "box-text-pre.json")
	if not os.path.exists(snap_path):
		os.makedirs(SNAPSHOT_DIR, exist_ok=True)
		with open(snap_path, "w") as f:
			json.dump(
				{
					"captured_at": frappe.utils.now(),
					"custom_fields": frappe.get_all(
						"Custom Field",
						filters={"dt": DOCTYPE, "fieldname": ("in", BOX_FIELDNAMES)},
						fields=["name", "fieldname", "label", "fieldtype", "non_negative", "allow_on_submit", "description"],
						order_by="fieldname",
					),
					"rows_with_box_value": sum(
						frappe.db.count(DOCTYPE, {f: ("!=", 0)}) for f in BOX_FIELDNAMES
					),
				},
				f, indent=2, sort_keys=True, default=str,
			)

	out = {}
	for fieldname in BOX_FIELDNAMES:
		cf = frappe.db.get_value(
			"Custom Field", {"dt": DOCTYPE, "fieldname": fieldname}, ["name", "fieldtype"], as_dict=True
		)
		if not cf:
			out[fieldname] = "missing (created by WORKSPACE_FIELDS as Data)"
		elif cf.fieldtype == "Data":
			out[fieldname] = "unchanged"
		else:
			has_values = frappe.db.count(DOCTYPE, {fieldname: ("!=", 0)}) > 0
			frappe.db.set_value("Custom Field", cf.name, "fieldtype", "Data")
			frappe.db.change_column_type(DOCTYPE, fieldname, "varchar(140)", nullable=True)
			if not has_values:
				# the decimal default 0 casts to a '0'/'0.000000000' string — no
				# row held a real value (snapshot proves it), so NULL them like a
				# fresh Data field instead of showing fake identifiers
				frappe.db.sql(f"update `tab{DOCTYPE}` set {fieldname}=NULL where {fieldname} is not null")
			out[fieldname] = "migrated Float -> Data" + (" (values kept as text)" if has_values else "")
	frappe.clear_cache(doctype=DOCTYPE)
	return out


def snapshot_fu10():
	"""Pre-change snapshot for the FU10 Link User -> Data flip: field
	definitions plus the distinct stored values (with counts) so the old
	meaning of each value stays on record. Runs BEFORE any change; apply()
	calls it only when the file is absent (idempotent)."""
	os.makedirs(SNAPSHOT_DIR, exist_ok=True)
	data = {
		"captured_at": frappe.utils.now(),
		"custom_fields": frappe.get_all(
			"Custom Field",
			filters={"dt": DOCTYPE, "fieldname": ("in", NAME_TEXT_FIELDNAMES)},
			fields=["name", "fieldname", "label", "fieldtype", "options", "allow_on_submit"],
			order_by="fieldname",
		),
		"stored_values": {},
	}
	for fieldname in NAME_TEXT_FIELDNAMES:
		distinct = {}
		for row in frappe.get_all(
			DOCTYPE,
			filters={fieldname: ("is", "set")},
			fields=[f"{fieldname} as value"],
		):
			key = str(row.value)
			distinct[key] = distinct.get(key, 0) + 1
		data["stored_values"][fieldname] = distinct
	with open(NAME_TEXT_SNAPSHOT, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True, default=str)
	return NAME_TEXT_SNAPSHOT


def snapshot_qc_packing_text():
	os.makedirs(SNAPSHOT_DIR, exist_ok=True)
	data = {
		"captured_at": frappe.utils.now(),
		"custom_fields": frappe.get_all(
			"Custom Field",
			filters={"dt": DOCTYPE, "fieldname": "custom_qc_packing"},
			fields=["name", "fieldname", "label", "fieldtype", "options", "allow_on_submit"],
		),
		"stored_values": frappe.get_all(
			DOCTYPE,
			filters={"custom_qc_packing": ("is", "set")},
			fields=["name", "custom_qc_packing"],
		),
	}
	with open(QC_PACKING_TEXT_SNAPSHOT, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True, default=str)
	return QC_PACKING_TEXT_SNAPSHOT


def ensure_qc_packing_text_field():
	cf = frappe.db.get_value(
		"Custom Field", {"dt": DOCTYPE, "fieldname": "custom_qc_packing"},
		["name", "fieldtype", "options"], as_dict=True,
	)
	if not cf:
		return "missing (site-managed field expected to exist)"
	if cf.fieldtype == "Data" and not (cf.options or "").strip():
		return "unchanged"
	frappe.db.set_value("Custom Field", cf.name, {"fieldtype": "Data", "options": ""})
	col = frappe.db.sql(
		"select column_type from information_schema.columns where table_name = %s and column_name = %s",
		(f"tab{DOCTYPE}", "custom_qc_packing"),
	)
	col_type = col[0][0] if col else None
	if col_type and "varchar" not in col_type:
		frappe.db.change_column_type(DOCTYPE, "custom_qc_packing", "varchar(140)", nullable=True)
	return f"migrated {cf.fieldtype} -> Data (column {col_type or 'n/a'})"


def ensure_name_text_fields():
	"""FU10: Nama Penimbang & QC Produksi Link User -> Data (a person's name
	as free text, same semantics as Leader Produksi). Link and Data share the
	varchar(140) column, so no row data moves — only fieldtype/options flip
	(the column type is verified and only altered if it is somehow not
	varchar). Existing User-id values are kept as text, honestly, without
	rewriting them into names. Snapshot-first, idempotent."""
	out = {}
	for fieldname in NAME_TEXT_FIELDNAMES:
		cf = frappe.db.get_value(
			"Custom Field",
			{"dt": DOCTYPE, "fieldname": fieldname},
			["name", "fieldtype", "options"],
			as_dict=True,
		)
		if not cf:
			out[fieldname] = "missing (site-managed field expected to exist)"
			continue
		if cf.fieldtype == "Data" and not (cf.options or "").strip():
			out[fieldname] = "unchanged"
			continue
		frappe.db.set_value("Custom Field", cf.name, "fieldtype", "Data")
		if (cf.options or "").strip():
			frappe.db.set_value("Custom Field", cf.name, "options", "")
		col = frappe.db.sql(
			"select column_type from information_schema.columns"
			" where table_name = %s and column_name = %s",
			(f"tab{DOCTYPE}", fieldname),
		)
		col_type = col[0][0] if col else None
		if col_type and "varchar" not in col_type:
			frappe.db.change_column_type(DOCTYPE, fieldname, "varchar(140)", nullable=True)
			out[fieldname] = f"migrated {cf.fieldtype} -> Data (column {col_type} -> varchar(140))"
		else:
			out[fieldname] = f"migrated {cf.fieldtype} -> Data (column {col_type or 'n/a'} kept)"
	frappe.clear_cache(doctype=DOCTYPE)
	return out


def apply():
	"""Create/upgrade the workspace fields; migrate leader to Data. Idempotent."""
	if not os.path.exists(T22_SNAPSHOT):
		snapshot_t22()  # never change handover metadata without a pre-state
	if not os.path.exists(POSTPACKING_SNAPSHOT):
		snapshot_t27()  # never change postpacking metadata without a pre-state
	if not os.path.exists(NAME_TEXT_SNAPSHOT):
		snapshot_fu10()  # never change penimbang/qc metadata without a pre-state
	if not os.path.exists(QC_PACKING_TEXT_SNAPSHOT):
		snapshot_qc_packing_text()
	result = {"fields": [], "leader": "unchanged"}

	result["box_fields"] = ensure_box_identifier_fields()
	result["name_text_fields"] = ensure_name_text_fields()
	result["qc_packing_text"] = ensure_qc_packing_text_field()
	for spec in WORKSPACE_FIELDS:
		action, name = _upsert_field(DOCTYPE, spec)
		result["fields"].append(f"{spec['fieldname']}: {action}")

	for fieldname in ALLOW_ON_SUBMIT_FIELDS:
		name = frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": fieldname}, "name")
		if name and not frappe.db.get_value("Custom Field", name, "allow_on_submit"):
			frappe.db.set_value("Custom Field", name, "allow_on_submit", 1)
			result["fields"].append(f"{fieldname}: allow_on_submit enabled")

	leader = frappe.db.get_value(
		"Custom Field", {"dt": DOCTYPE, "fieldname": LEADER_FIELDNAME}, ["name", "fieldtype"], as_dict=True
	)
	if leader and leader.fieldtype == "Data":
		pass  # already migrated
	elif leader:
		# Int -> Data: numbers stay numbers as text; nothing is invented.
		frappe.db.set_value("Custom Field", leader.name, "fieldtype", "Data")
		frappe.db.change_column_type(DOCTYPE, LEADER_FIELDNAME, "varchar(140)", nullable=True)
		result["leader"] = "migrated Int -> Data"

	ws = ensure_workspace()
	result["workspace"] = ws["workspace"]
	sidebar = ensure_workspace_sidebar()
	result["workspace_sidebar"] = sidebar["workspace_sidebar"]
	result["desktop_icon"] = ensure_desktop_icon()
	result["batch_permission"] = ensure_batch_permission()
	result["stock_user_batch_read"] = ensure_stock_user_batch_read()
	result["warehouse_default_fields"] = ensure_warehouse_default_fields()
	result["handover_mr_fields"] = ensure_handover_mr_fields()
	result["handover_permissions"] = ensure_handover_permissions()
	frappe.clear_cache(doctype=DOCTYPE)
	frappe.db.commit()
	return result

def ensure_workspace():
	"""Desk workspace "Production App" (sidebar) with a Work Order shortcut and
	a button into the /production_workspace SPA. Idempotent upsert."""
	# Sidebar gate (frappe/desk/desktop.py): users without the "Workspace Manager"
	# role only see workspaces whose module is in their allow_modules, which is built
	# from the modules of DocTypes they can read. This app defines no DocTypes, so
	# anchor the workspace to Manufacturing (the Work Order doctype's module).
	# `app` keeps the sidebar grouped under production_app, not erpnext.
	module = "Manufacturing"
	app = "production_app"
	shortcuts = [{"label": "Work Orders", "type": "DocType", "link_to": "Work Order", "color": "Blue"}]
	content = frappe.as_json([
		{"id": "pa-header", "type": "header", "data": {"text": "<span class=\"h4\"><b>Production App</b></span>", "col": 12}},
		{"id": "pa-p", "type": "paragraph", "data": {"text": "<p>Work Order workspace: persiapan \u2192 material \u2192 operasi \u2192 pre-packing \u2192 finish. Semua stage dihitung server dari dokumen ERPNext.</p><p><a class=\"btn btn-primary\" href=\"/production_workspace\">Buka Production Workspace</a></p>", "col": 12}},
	])

	ws_name = frappe.db.get_value("Workspace", {"label": "Production App"}, "name")
	if ws_name:
		doc = frappe.get_doc("Workspace", ws_name)
		doc.content = content
		doc.set("shortcuts", shortcuts)
		doc.module = module
		doc.app = app
		doc.flags.ignore_permissions = 1
		doc.save()
		return {"workspace": "updated"}

	doc = frappe.get_doc({
		"doctype": "Workspace",
		"label": "Production App",
		"title": "Production App",
		"module": module,
		"app": app,
		"public": 1,
		"is_hidden": 0,
		"parent_page": "",
		"content": content,
		"shortcuts": shortcuts,
	})
	if not doc.parent_page:
		doc.parent_page = "Modules"
	doc.flags.ignore_permissions = 1
	doc.insert()
	frappe.db.commit()
	return {"workspace": "created"}


def ensure_workspace_sidebar():
	"""/apps grid + ⌘K tile "Production App" (boot.workspace_sidebar_item).

	Frappe only renders PERSISTED Workspace Sidebar docs on the /apps screen; the
	first Link item is what a tile click opens (frappe/desk/page/desktop/desktop.js
	get_route), so the first item is a URL item straight into the /production_workspace
	SPA. Items are replaced wholesale on every run (idempotent)."""
	title = "Production App"
	items = [
		{"type": "Link", "label": "Production App", "link_type": "URL", "url": "/production_workspace"},
		{"type": "Link", "label": "Work Orders", "link_type": "DocType", "link_to": "Work Order"},
	]

	name = frappe.db.get_value("Workspace Sidebar", title, "name")
	if name:
		doc = frappe.get_doc("Workspace Sidebar", name)
		doc.set("items", items)
		if doc.app != "production_app":
			doc.app = "production_app"
		if not doc.header_icon:
			doc.header_icon = "tool"
		doc.flags.ignore_permissions = 1
		doc.save()
		return {"workspace_sidebar": "updated"}

	doc = frappe.get_doc({
		"doctype": "Workspace Sidebar",
		"title": title,
		"app": "production_app",
		"header_icon": "tool",
		"standard": 0,
		"items": items,
	})
	doc.flags.ignore_permissions = 1
	doc.insert()
	frappe.db.commit()
	return {"workspace_sidebar": "created"}


def ensure_desktop_icon():
	"""/desk grid tile. The grid renders Desktop Icon docs; get_desktop_icons shows
	standard icons plus non-standard ones owned by Administrator. Tile click follows
	the linked Workspace Sidebar's first Link item (URL → /production_workspace)."""
	name = frappe.db.get_value("Desktop Icon", {"label": "Production App"}, "name")
	if name:
		return "unchanged"

	doc = frappe.get_doc({
		"doctype": "Desktop Icon",
		"label": "Production App",
		"icon_type": "Link",
		"link_type": "Workspace Sidebar",
		"link_to": "Production App",
		"icon": "tool",
		"bg_color": "blue",
		"standard": 0,
		"app": "production_app",
	})
	doc.flags.ignore_permissions = 1
	doc.insert()
	frappe.db.commit()
	return "created"

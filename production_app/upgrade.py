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
		"label": "Box 1 (kg)",
		"fieldtype": "Float",
		"insert_after": "custom_sisa_qty_prepacking",
		"allow_on_submit": 1,
		"non_negative": 1,
		"description": "Berat Box 1 dalam kg",
	},
	{
		"fieldname": "custom_box_2",
		"label": "Box 2 (kg)",
		"fieldtype": "Float",
		"insert_after": "custom_box_1",
		"allow_on_submit": 1,
		"non_negative": 1,
		"description": "Berat Box 2 dalam kg",
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
]

# allow-on-submit enablement required by the workspace actions (submitted WOs)
ALLOW_ON_SUBMIT_FIELDS = [
	"custom_nama_penimbang",
	"custom_jumlah_kru",
	"custom_leader_produksi",
	"custom_qc_produksi",
]

LEADER_FIELDNAME = "custom_leader_produksi"

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
]


def ensure_warehouse_default_fields():
	"""Create the Production App warehouse-default custom fields on
	Manufacturing Settings, anchored after the doctype's current last field.
	Idempotent; existing fields are never moved or relabeled."""
	anchor = frappe.get_all(
		"DocField",
		filters={"parent": "Manufacturing Settings"},
		order_by="idx desc",
		limit=1,
		pluck="fieldname",
	)[0]
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


def apply():
	"""Create/upgrade the workspace fields; migrate leader to Data. Idempotent."""
	result = {"fields": [], "leader": "unchanged"}

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
	result["warehouse_default_fields"] = ensure_warehouse_default_fields()
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

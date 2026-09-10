"""Layered authorization + supported-configuration gates (spec 6 and 11).

Layers, applied in order BEFORE any ignore_permissions (11.2):
1. Role gate: `require_role`.
2. Doc-level: `check_wo_access` -> frappe.has_permission on the Work Order,
   which applies the user's User Permissions (e.g. Company). No User
   Permission = unrestricted [T V23].
3. List-level: `list_wos_scope` -> frappe.get_list applies the permission
   query conditions; has_permission alone does NOT.
4. Relation: `check_relation` - a Job Card / Stock Entry must belong to the
   Work Order being mutated.
5. Bypass: `authorized_ignore` - only for documents already authorized for
   that exact action.

Blocked configurations (spec 6) are reported by `config_blocked_reasons` as
Indonesian reasons, checked at detail load and re-checked on every mutation.
"""

import contextlib

import frappe
from frappe.utils import cint, flt

RESERVED_STATUSES = ("Stock Reserved", "Stock Partially Reserved")


def require_role(*roles):
	"""Role gate (11.1): pass when the session user holds any of `roles`;
	System Manager passes everything. Otherwise frappe.PermissionError."""
	user_roles = set(frappe.get_roles())
	if "System Manager" in user_roles or user_roles.intersection(roles):
		return
	frappe.throw("Anda tidak memiliki hak untuk melakukan aksi ini.", frappe.PermissionError)


def check_wo_access(work_order, ptype="read"):
	"""Doc-level access (11.2 step 2): frappe.has_permission on the Work
	Order, applying the user's User Permissions (e.g. Company). Accepts a
	name or a Document; returns the fetched Document."""
	if isinstance(work_order, str):
		work_order = frappe.get_doc("Work Order", work_order)
	if not frappe.has_permission("Work Order", ptype, doc=work_order):
		frappe.throw("Anda tidak berhak mengakses Work Order ini", frappe.PermissionError)
	return work_order


def list_wos_scope(filters=None, fields=None, order_by=None):
	"""List-level scope (11.2 step 3): frappe.get_list applies the permission
	query conditions, so Work Orders invisible to the user never come back.
	Helper for the list endpoint (7.1); keep results framework-scoped."""
	return frappe.get_list(
		"Work Order",
		filters=filters,
		fields=fields or ["name"],
		order_by=order_by,
	)


def check_relation(doc, wo):
	"""Relation check (11.2 step 4): the Job Card / Stock Entry must belong
	to the Work Order being mutated."""
	if doc.get("work_order") != wo:
		frappe.throw("Dokumen ini bukan bagian dari Work Order tersebut.", frappe.PermissionError)


def config_blocked_reasons(work_order):
	"""Configurations the app refuses (spec 6), as Indonesian reasons for this
	Work Order. Returns (reasons, bom_pct).

	The BOM process_loss_percentage is NOT an absolute block (6.4 rev5.1): it
	only bites a session that enters loss 0, which qty.py pre-checks (6.7) -
	so it is returned separately instead of being listed as a reason here.
	`validate_components_quantities_per_bom` (6.6) is a site-wide
	Manufacturing Setting, reported globally on every check."""
	if isinstance(work_order, str):
		work_order = frappe.get_doc("Work Order", work_order)
	reasons = []
	if work_order.get("transfer_material_against") == "Job Card":
		reasons.append(
			"Transfer bahan untuk Work Order ini dikendalikan lewat Job Card - tidak didukung. Hubungi admin."
		)
	if cint(work_order.get("track_semi_finished_goods")):
		reasons.append(
			"Work Order ini dikonfigurasi melacak barang setengah jadi - tidak didukung. Hubungi admin."
		)
	if cint(work_order.get("reserve_stock")) or work_order.get("status") in RESERVED_STATUSES:
		reasons.append(
			"Stok untuk Work Order ini sedang direservasi - aplikasi produksi tidak mendukung reservasi stok."
		)
	if cint(frappe.db.get_single_value("Manufacturing Settings", "validate_components_quantities_per_bom")):
		reasons.append(
			"Pengaturan sistem saat ini memaksa pemakaian bahan sesuai resep BOM - pencatatan bahan "
			"aktual tidak didukung. Minta admin mengubah pengaturan manufaktur."
		)
	bom_pct = (
		flt(frappe.db.get_value("BOM", work_order.get("bom_no"), "process_loss_percentage"))
		if work_order.get("bom_no")
		else 0.0
	)
	return reasons, bom_pct


@contextlib.contextmanager
def authorized_ignore(doc):
	"""Permission bypass for an ALREADY-authorized document/action (11.2
	step 5, 11.4): call only AFTER require_role / check_wo_access /
	check_relation passed for this exact action. Restores the flag after the
	block so the bypass never leaks beyond the authorized operation."""
	doc.flags.ignore_permissions = True
	try:
		yield doc
	finally:
		doc.flags.ignore_permissions = False

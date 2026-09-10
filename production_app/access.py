"""Role gate + document access + supported-configuration checks (spec
sections 6 and 11) - Tahap 3.

Contract:
- Production Operator: read/list, save_production_data, transfer_material,
  complete_operation, finish_production.
- Production Supervisor: all of the above + cancel_last_step,
  cancel_production, close_work_order. System Manager passes everything.
- Layered checks BEFORE any ignore_permissions (11.2): role gate -> doc-level
  frappe.has_permission (applies User Permissions) -> list-level via
  frappe.get_list (permission query conditions) -> relation checks
  (SE/JC belong to the WO) -> bypass limited to the authorized documents.
- Blocked configurations (section 6) rejected with an Indonesian reason,
  checked at app init and re-checked on every mutation, including
  validate_components_quantities_per_bom == 1 (6.6).
"""


def require_role(user, action):
	"""Role gate per section 11.1. Raise frappe.PermissionError for actions the
	user's role does not carry (supervisor-only actions for operators)."""
	raise NotImplementedError("Tahap 3")


def assert_can_access(work_order, ptype, user):
	"""Doc-level + list-level access checks (11.2 steps 2-4): has_permission on
	the document, get_list visibility, and SE/JC-to-WO relation checks."""
	raise NotImplementedError("Tahap 3")


def blocked_reasons(work_order):
	"""Configurations the app refuses (section 6) as a list of Indonesian
	reasons for the current Work Order (transfer_against=Job Card,
	track_semi_finished_goods, reserve_stock/Reserved status, conditional
	loss gates, good=0 until decision #3, site setting 6.6)."""
	raise NotImplementedError("Tahap 3")

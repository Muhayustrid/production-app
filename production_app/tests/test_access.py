"""Tests for access.py - layered authorization + config gates (spec 6, 11).

Covers: the role gate (11.1), doc-level + list-level access with Company User
Permissions (11.2 [T] V23: no User Permission = unrestricted), the SE/JC-to-WO
relation check, the blocked-configuration reasons (6.1-6.3, 6.6) and the
CONDITIONAL BOM process_loss_percentage (6.4 rev5.1: reported separately, not
an absolute block).
"""

import frappe
from frappe.tests import IntegrationTestCase

from production_app import access
from production_app.tests import factories


class TestAccess(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		factories.setup_second_company()
		cls.operator = factories.make_user("pdtc.operator@example.com", roles=["Production Operator"])
		cls.supervisor = factories.make_user("pdtc.supervisor@example.com", roles=["Production Supervisor"])
		cls.outsider = factories.make_user("pdtc.outsider@example.com")
		cls.wo = factories.make_wo()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_role_gate(self):
		# 11.1: a user without production roles is denied.
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			access.require_role("Production Operator", "Production Supervisor")
		# Operator passes the shared gate but not the supervisor-only gate.
		frappe.set_user(self.operator)
		access.require_role("Production Operator", "Production Supervisor")
		with self.assertRaises(frappe.PermissionError):
			access.require_role("Production Supervisor")
		# Supervisor passes the supervisor-only gate...
		frappe.set_user(self.supervisor)
		access.require_role("Production Supervisor")
		# ...and System Manager passes everything.
		frappe.set_user("Administrator")
		access.require_role("Production Supervisor")

	def test_doc_and_list_access_with_company_user_permission(self):
		# V23 baseline: no User Permission = unrestricted.
		frappe.set_user(self.operator)
		access.check_wo_access(self.wo)
		scope = access.list_wos_scope(filters=[["name", "=", self.wo]])
		self.assertEqual([self.wo], [d.name for d in scope])

		# User Permission on a DIFFERENT company denies doc and list access
		# (create the permission as Administrator - operators cannot).
		frappe.set_user("Administrator")
		perm = factories.make_user_permission(self.operator, "Company", factories.SECOND_COMPANY)
		self.addCleanup(frappe.delete_doc, "User Permission", perm)
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.PermissionError):
			access.check_wo_access(self.wo)
		self.assertEqual([], access.list_wos_scope(filters=[["name", "=", self.wo]]))

		# A matching-company permission grants doc-level access again.
		frappe.set_user("Administrator")
		perm = factories.make_user_permission(self.operator, "Company", factories.COMPANY)
		self.addCleanup(frappe.delete_doc, "User Permission", perm)
		frappe.set_user(self.operator)
		access.check_wo_access(self.wo, "read")
		with self.assertRaises(frappe.PermissionError):
			access.check_wo_access(self.wo, "submit")  # roles are read-only on WO

	def test_relation_mismatch_denied(self):
		other_wo = factories.make_wo()
		access.check_relation(frappe._dict(doctype="Stock Entry", work_order=other_wo), other_wo)
		with self.assertRaises(frappe.PermissionError):
			access.check_relation(frappe._dict(doctype="Stock Entry", work_order=other_wo), self.wo)

	def test_config_blocked_variants(self):
		self.assertEqual(([], 0.0), access.config_blocked_reasons(self.wo))

		frappe.db.set_value("Work Order", self.wo, "transfer_material_against", "Job Card")
		self.addCleanup(frappe.db.set_value, "Work Order", self.wo, "transfer_material_against", "Work Order")
		reasons, _ = access.config_blocked_reasons(self.wo)
		self.assertEqual(len(reasons), 1)
		self.assertIn("Job Card", reasons[0])

		frappe.db.set_value("Work Order", self.wo, "transfer_material_against", "Work Order")
		frappe.db.set_value("Work Order", self.wo, "track_semi_finished_goods", 1)
		self.addCleanup(frappe.db.set_value, "Work Order", self.wo, "track_semi_finished_goods", 0)
		reasons, _ = access.config_blocked_reasons(self.wo)
		self.assertEqual(len(reasons), 1)
		self.assertIn("setengah jadi", reasons[0])

		frappe.db.set_value("Work Order", self.wo, "track_semi_finished_goods", 0)
		frappe.db.set_value("Work Order", self.wo, "reserve_stock", 1)
		self.addCleanup(frappe.db.set_value, "Work Order", self.wo, "reserve_stock", 0)
		reasons, _ = access.config_blocked_reasons(self.wo)
		self.assertEqual(len(reasons), 1)
		self.assertIn("reservasi", reasons[0])

		frappe.db.set_value("Work Order", self.wo, "reserve_stock", 0)
		frappe.db.set_value("Work Order", self.wo, "status", "Stock Reserved")
		self.addCleanup(frappe.db.set_value, "Work Order", self.wo, "status", "Not Started")
		reasons, _ = access.config_blocked_reasons(self.wo)
		self.assertEqual(len(reasons), 1)
		self.assertIn("reservasi", reasons[0])

		frappe.db.set_value("Work Order", self.wo, "status", "Not Started")
		# 6.6: site-wide Manufacturing Setting, reported globally.
		original = frappe.db.get_single_value(
			"Manufacturing Settings", "validate_components_quantities_per_bom"
		)
		frappe.db.set_single_value("Manufacturing Settings", "validate_components_quantities_per_bom", 1)
		self.addCleanup(
			frappe.db.set_single_value,
			"Manufacturing Settings",
			"validate_components_quantities_per_bom",
			original,
		)
		reasons, _ = access.config_blocked_reasons(self.wo)
		self.assertEqual(len(reasons), 1)
		self.assertIn("admin", reasons[0])

	def test_bom_pct_conditional_not_absolute_block(self):
		# 6.4 rev5.1: BOM pct>0 must NOT appear as a blocked reason; it is
		# returned separately so qty.py can pre-check the loss-0 combination.
		bom = frappe.db.get_value("Work Order", self.wo, "bom_no")
		original = frappe.db.get_value("BOM", bom, "process_loss_percentage")
		frappe.db.set_value("BOM", bom, "process_loss_percentage", 5)
		self.addCleanup(frappe.db.set_value, "BOM", bom, "process_loss_percentage", original)

		reasons, bom_pct = access.config_blocked_reasons(self.wo)
		self.assertEqual(bom_pct, 5.0)
		self.assertFalse(any("loss" in reason.lower() for reason in reasons))

	def test_authorized_ignore_restores_flag(self):
		wo = frappe.get_doc("Work Order", self.wo)
		with access.authorized_ignore(wo):
			self.assertTrue(wo.flags.ignore_permissions)
		self.assertFalse(wo.flags.ignore_permissions)

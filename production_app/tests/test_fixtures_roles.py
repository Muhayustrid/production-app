"""Proof of the fixture permission matrix (spec 11.3).

Assertions use frappe.has_permission with real test users holding the
fixture roles - the same check the framework performs on every request.

Matrix (spec 11.3 minimum per action):
- Work Order: read only, both roles (no write / cancel / submit).
- Stock Entry: read only, both roles (app-only mutations; NO write).
- Job Card: read + create + write + submit for both; cancel SUPERVISOR ONLY.
"""

import frappe
from frappe.tests import IntegrationTestCase

OPERATOR = "prod-operator@test.example.com"
SUPERVISOR = "prod-supervisor@test.example.com"
BYPASSER = "prod-norole@test.example.com"


class TestFixturesRoles(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._make_user(OPERATOR, "Production Operator")
		cls._make_user(SUPERVISOR, "Production Supervisor")
		cls._make_user(BYPASSER, None)

	@staticmethod
	def _make_user(email, role):
		if frappe.db.exists("User", email):
			return
		doc = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
		})
		if role:
			doc.append("roles", {"role": role})
		doc.insert(ignore_permissions=True)

	def check(self, user, doctype, ptype, expected):
		frappe.local.role_permissions = {}
		self.assertEqual(
			frappe.has_permission(doctype, ptype, user=user),
			expected,
			f"{user}: {doctype} {ptype} expected {expected}",
		)

	def test_roles_and_docperms_exist(self):
		for role in ("Production Operator", "Production Supervisor"):
			self.assertTrue(frappe.db.exists("Role", {"role_name": role}), f"role fixture missing: {role}")
		perms = frappe.get_all(
			"Custom DocPerm",
			filters={"role": ("in", ["Production Operator", "Production Supervisor"])},
			fields=["role", "parent", "read", "write", "create", "submit", "cancel"],
		)
		by_key = {(p.role, p.parent): p for p in perms}
		self.assertIn(("Production Operator", "Work Order"), by_key)
		self.assertIn(("Production Supervisor", "Work Order"), by_key)
		self.assertIn(("Production Operator", "Stock Entry"), by_key)
		self.assertIn(("Production Supervisor", "Stock Entry"), by_key)
		self.assertIn(("Production Operator", "Job Card"), by_key)
		self.assertIn(("Production Supervisor", "Job Card"), by_key)
		# JC cancel is Supervisor ONLY (spec 11.3)
		self.assertFalse(by_key[("Production Operator", "Job Card")].cancel)
		self.assertTrue(by_key[("Production Supervisor", "Job Card")].cancel)

	def test_operator_matrix(self):
		c = self.check
		c(OPERATOR, "Work Order", "read", True)
		c(OPERATOR, "Work Order", "write", False)
		c(OPERATOR, "Work Order", "cancel", False)
		c(OPERATOR, "Work Order", "submit", False)
		c(OPERATOR, "Stock Entry", "read", True)
		c(OPERATOR, "Stock Entry", "write", False)
		c(OPERATOR, "Stock Entry", "create", False)
		c(OPERATOR, "Stock Entry", "cancel", False)
		c(OPERATOR, "Job Card", "read", True)
		c(OPERATOR, "Job Card", "create", True)
		c(OPERATOR, "Job Card", "write", True)
		c(OPERATOR, "Job Card", "submit", True)
		c(OPERATOR, "Job Card", "cancel", False)  # Supervisor ONLY

	def test_supervisor_matrix(self):
		c = self.check
		c(SUPERVISOR, "Work Order", "read", True)
		c(SUPERVISOR, "Work Order", "write", False)
		c(SUPERVISOR, "Work Order", "cancel", False)
		c(SUPERVISOR, "Stock Entry", "read", True)
		c(SUPERVISOR, "Stock Entry", "write", False)
		c(SUPERVISOR, "Stock Entry", "create", False)
		c(SUPERVISOR, "Job Card", "read", True)
		c(SUPERVISOR, "Job Card", "create", True)
		c(SUPERVISOR, "Job Card", "write", True)
		c(SUPERVISOR, "Job Card", "submit", True)
		c(SUPERVISOR, "Job Card", "cancel", True)  # Supervisor ONLY

	def test_roleless_user_denied(self):
		# Access comes from the fixture Custom DocPerms, not core defaults.
		c = self.check
		c(BYPASSER, "Work Order", "read", False)
		c(BYPASSER, "Stock Entry", "read", False)
		c(BYPASSER, "Job Card", "write", False)

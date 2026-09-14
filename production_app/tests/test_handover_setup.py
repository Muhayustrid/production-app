# T22 handover setup — metadata + permission matrix (upgrade.py extensions)
#
# Proves by execution on the installed runtime:
# - production_app.upgrade.apply() is idempotent (run twice, second run changes
#   nothing) and reconciles the pre-existing Manufacturing User Material Request
#   Custom DocPerm down to read/write (task-21-report §3.8 drift);
# - the full T22 permission matrix behaves per HANDOVER_PLAN.md §3:
#   "Gudang Barang Jadi" runs the MR lifecycle (create/submit/cancel) but has
#   read-only reach into Work Order / Batch / Stock Entry and no Stock Entry
#   create; "Manufacturing User" reads/writes MR (incl. allow_on_submit fields
#   on submitted docs) but cannot create/cancel/submit;
# - the 5th warehouse default (`custom_default_handover_warehouse`) persists via
#   the Pengaturan save API with write permission (Manufacturing Manager), the
#   read API stays open, and saving without permission throws.
#
# Every record created here is test-only (users t22.* prefixed, warehouses/items
# "T22 ..." prefixed); the Frappe test framework rolls each run back.

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now, random_string

from production_app import upgrade
from production_app.api.work_order import warehouse_defaults, warehouse_defaults_save

PREFIX = "T22"
HANDOVER_ROLE = "Gudang Barang Jadi"


def _company_and_group():
	name = frappe.db.get_value("Work Order", {"docstatus": 1}, "name", order_by="creation desc")
	company = frappe.db.get_value("Work Order", name, "company")
	parent = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1}, "name")
	return company, parent


def _mr_flags(doctype, role):
	name = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role}, "name")
	if not name:
		return None
	row = frappe.db.get_value(
		"Custom DocPerm", name,
		["read", "write", "create", "submit", "cancel", "amend"], as_dict=True,
	)
	return {k: int(row.get(k) or 0) for k in ("read", "write", "create", "submit", "cancel", "amend")}


def _make_user(local, role=None):
	suffix = random_string(6).upper()
	user = (
		frappe.get_doc(
			{
				"doctype": "User",
				"email": f"t22.{local}.{suffix.lower()}@prodapp.example.com",
				"first_name": f"T22 {local}",
				"send_welcome_email": 0,
			}
		)
		.insert()
	)
	if role:
		user.append("roles", {"role": role})
	user.save()
	return user.name


class TestHandoverSetup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company, cls.parent_wh = _company_and_group()
		suffix = random_string(6).upper()
		cls.src_wh = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": f"{PREFIX} Source {suffix}",
					"company": cls.company,
					"parent_warehouse": cls.parent_wh,
					"is_group": 0,
				}
			)
			.insert()
			.name
		)
		cls.dst_wh = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": f"{PREFIX} Handover {suffix}",
					"company": cls.company,
					"parent_warehouse": cls.parent_wh,
					"is_group": 0,
				}
			)
			.insert()
			.name
		)
		cls.item = (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"{PREFIX}-ITEM-{suffix}",
					"item_name": f"{PREFIX} Item {suffix}",
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": frappe.db.get_value(
						"Work Order", {"docstatus": 1}, "stock_uom", order_by="creation desc"
					),
					"is_stock_item": 1,
					"is_purchase_item": 0,
					"is_sales_item": 0,
					"is_fixed_asset": 0,
				}
			)
			.insert()
			.name
		)

	@classmethod
	def tearDownClass(cls):
		"""The apply() idempotency test commits mid-class (by design — metadata),
		which persists the class fixtures past the framework rollback. Purge the
		T22 leftovers explicitly (they carry no ledger entries)."""
		frappe.db.rollback()  # discard uncommitted per-test data (users, MRs)
		frappe.set_user("Administrator")
		for doctype, field, pattern in (
			("Warehouse", "warehouse_name", f"{PREFIX} %"),
			("Item", "item_code", f"{PREFIX}-%"),
		):
			for name in frappe.get_all(doctype, filters={field: ("like", pattern)}, pluck="name"):
				frappe.delete_doc(doctype, name, force=True)
		frappe.db.commit()
		super().tearDownClass()

	# ------------------------------------------------------------- fixtures

	def _make_mr(self, qty=10):
		mr = frappe.get_doc(
			{
				"doctype": "Material Request",
				"material_request_type": "Material Transfer",
				"company": self.company,
				"transaction_date": now(),
				"schedule_date": add_days(now(), 1),
				"set_from_warehouse": self.src_wh,
				"set_warehouse": self.dst_wh,
				"items": [
					{
						"item_code": self.item,
						"qty": qty,
						"uom": frappe.db.get_value("Item", self.item, "stock_uom"),
						"from_warehouse": self.src_wh,
						"warehouse": self.dst_wh,
						"schedule_date": add_days(now(), 1),
					}
				],
			}
		)
		mr.insert()
		mr.submit()
		return mr

	# ------------------------------------------------------- idempotency

	def test_t22_apply_idempotent_and_drift_reconciled(self):
		"""apply() twice: no error; the second run reports every handover step
		'unchanged'; the Manufacturing User MR row is read/write only."""
		r1 = upgrade.apply()
		r2 = upgrade.apply()
		for key in ("handover_mr_fields", "handover_permissions", "warehouse_default_fields"):
			self.assertTrue(
				all(entry.endswith(": unchanged") for entry in r2[key]),
				f"{key} not idempotent: {r2[key]}",
			)
		# drift fix: Manufacturing User MR = read/write ONLY (no create/submit/cancel)
		mfg = _mr_flags("Material Request", "Manufacturing User")
		self.assertEqual(
			mfg, {"read": 1, "write": 1, "create": 0, "submit": 0, "cancel": 0, "amend": 0}
		)
		self.assertTrue(frappe.db.exists("Role", HANDOVER_ROLE))
		# 5th warehouse default field exists on Manufacturing Settings
		self.assertTrue(
			frappe.get_meta("Manufacturing Settings").has_field("custom_default_handover_warehouse")
		)
		# and the full matrix landed at the DocPerm level
		self.assertEqual(
			_mr_flags("Material Request", HANDOVER_ROLE),
			{"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1},
		)
		self.assertEqual(_mr_flags("Material Request Item", HANDOVER_ROLE)["create"], 1)
		self.assertEqual(_mr_flags("Material Request Item", "Manufacturing User")["create"], 0)
		# follow-up 7: WO box fields are TEXT identifiers (Data, allow_on_submit)
		# written at Post-Packing; MR boxes became allow_on_submit (submitted MR)
		wo_meta = frappe.get_meta("Work Order")
		for fieldname in ("custom_box_1", "custom_box_2"):
			df = wo_meta.get_field(fieldname)
			self.assertEqual(df.fieldtype, "Data", fieldname)
			self.assertTrue(df.allow_on_submit, fieldname)
		self.assertEqual(
			frappe.get_meta("Material Request").get_field("custom_box_1").allow_on_submit, 1
		)

	# ------------------------------------------------ permission: gudang

	def test_t22_gudang_runs_mr_lifecycle_but_cannot_send(self):
		"""Gudang Barang Jadi: MR create/submit/cancel allowed; Stock Entry
		create denied; Work Order write denied; masters read-only visible."""
		gudang = _make_user("gudang", HANDOVER_ROLE)

		self.assertTrue(frappe.has_permission("Material Request", "create", user=gudang))
		self.assertTrue(frappe.has_permission("Material Request", "submit", user=gudang))
		self.assertTrue(frappe.has_permission("Material Request", "cancel", user=gudang))
		# child-table checks resolve via parent_doctype (frappe.permissions
		# has_child_permission); the MR Item DocPerm rows themselves are
		# asserted at DB level in the idempotency test
		self.assertTrue(
			frappe.has_permission(
				"Material Request Item", "read", parent_doctype="Material Request", user=gudang
			)
		)
		self.assertTrue(
			frappe.has_permission(
				"Material Request Item", "create", parent_doctype="Material Request", user=gudang
			)
		)
		for doctype in ("Work Order", "Batch", "Stock Entry", "Item", "Warehouse"):
			self.assertTrue(
				frappe.has_permission(doctype, "read", user=gudang), f"{doctype} read"
			)
		self.assertFalse(frappe.has_permission("Stock Entry", "create", user=gudang))
		self.assertFalse(frappe.has_permission("Work Order", "write", user=gudang))

		frappe.set_user(gudang)
		try:
			mr = self._make_mr(10)  # create + submit
			self.assertEqual(mr.docstatus, 1)
			frappe.get_doc("Material Request", mr.name).cancel()  # no sends yet
			self.assertEqual(frappe.db.get_value("Material Request", mr.name, "docstatus"), 2)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(
					{
						"doctype": "Stock Entry",
						"stock_entry_type": "Material Receipt",
						"company": self.company,
						"items": [],
					}
				).insert()
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------- permission: prod user

	def test_t22_prod_user_reads_and_writes_but_cannot_create(self):
		"""Manufacturing User: MR read/write incl. allow_on_submit fields on a
		SUBMITTED MR; create/cancel/submit denied; MR Item read-only."""
		prod = _make_user("prod", "Manufacturing User")
		self.assertFalse(frappe.has_permission("Material Request", "create", user=prod))
		self.assertFalse(frappe.has_permission("Material Request", "cancel", user=prod))
		self.assertFalse(frappe.has_permission("Material Request", "submit", user=prod))
		self.assertTrue(frappe.has_permission("Material Request", "read", user=prod))
		self.assertTrue(frappe.has_permission("Material Request", "write", user=prod))
		self.assertTrue(
			frappe.has_permission(
				"Material Request Item", "read", parent_doctype="Material Request", user=prod
			)
		)
		self.assertFalse(
			frappe.has_permission(
				"Material Request Item", "create", parent_doctype="Material Request", user=prod
			)
		)

		mr = self._make_mr(5)
		frappe.set_user(prod)
		try:
			doc = frappe.get_doc("Material Request", mr.name)
			# write YES on the submitted doc; submit NO (native: a full doc.save()
			# of a submitted doc needs "submit" — check_docstatus_transition 1->1)
			self.assertTrue(frappe.has_permission("Material Request", "write", doc=doc))
			# allow_on_submit write path for a write-only role: db_set on the
			# allowed fields (T24's postpacking action must gate write itself)
			doc.db_set("custom_good_qty_postpacking", 3.5)
			doc.db_set("custom_postpacking_confirmed", 1)
			doc.reload()
			self.assertEqual(doc.custom_good_qty_postpacking, 3.5)
			self.assertEqual(doc.custom_postpacking_confirmed, 1)
			with self.assertRaises(frappe.PermissionError):
				doc.save()  # submit-less role cannot run the full save path
			with self.assertRaises(frappe.PermissionError):
				self._make_mr(1)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Material Request", mr.name).cancel()
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------- permission: bare user

	def test_t22_bare_user_cannot_read_mr(self):
		"""A user with no roles has no Material Request access at all."""
		bare = _make_user("bare")
		self.assertFalse(frappe.has_permission("Material Request", "read", user=bare))
		frappe.set_user(bare)
		try:
			with self.assertRaises(frappe.PermissionError):
				self._make_mr(1)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------- 5th warehouse default (API)

	def test_t22_handover_warehouse_setting_via_api(self):
		"""warehouse_defaults_save persists custom_default_handover_warehouse for
		a Manufacturing Settings writer; plain user save throws; read is open."""
		if not frappe.db.exists("Role", "Manufacturing Manager"):
			self.skipTest("no Manufacturing Manager role on site")
		manager = _make_user("manager", "Manufacturing Manager")

		self.assertIn("handover_warehouse", warehouse_defaults())  # read open

		frappe.set_user(manager)
		try:
			saved = warehouse_defaults_save(handover_warehouse=self.dst_wh)
			self.assertEqual(saved["handover_warehouse"], self.dst_wh)
			self.assertEqual(
				frappe.db.get_single_value("Manufacturing Settings", "custom_default_handover_warehouse"),
				self.dst_wh,
			)
		finally:
			frappe.set_user("Administrator")

		bare = _make_user("bare2")
		frappe.set_user(bare)
		try:
			with self.assertRaises(frappe.PermissionError):
				warehouse_defaults_save(handover_warehouse=self.dst_wh)
		finally:
			frappe.set_user("Administrator")

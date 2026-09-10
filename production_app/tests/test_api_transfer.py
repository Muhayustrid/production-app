"""Tests for api.transfer_material (spec 7.4).

Contract proven per test:
- happy path with defaults: rows == pending materials (V8), WO coverage
  updated, next_action advances;
- explicit operator actuals override per item; a following default transfer
  carries only the still-pending remainder;
- over-transfer gate 6.8 (cumulative + request vs qty x (1 + tolerance))
  rejects with an Indonesian message and NO Stock Entry;
- indicative stock shortfall names the item, deficit, uom and warehouse;
- idempotent replay returns duplicate=True with a single Stock Entry;
- both Production Operator and Production Supervisor may transfer.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from production_app import api
from production_app.tests import factories

OPERATOR = "pdtc.transfer.operator@example.com"
SUPERVISOR = "pdtc.transfer.supervisor@example.com"
NOBODY = "pdtc.transfer.nobody@example.com"


class TestTransferMaterial(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls.supervisor = factories.make_user(SUPERVISOR, roles=["Production Supervisor"])
		cls.nobody = factories.make_user(NOBODY)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		self.keys = []
		self.addCleanup(self._cleanup)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _cleanup(self):
		frappe.set_user("Administrator")
		for key in self.keys:
			if frappe.db.exists("Production Request Log", key):
				frappe.delete_doc("Production Request Log", key, ignore_permissions=True, force=True)

	def _key(self):
		key = "TEST-" + frappe.utils.random_string(10)
		self.keys.append(key)
		return key

	def _wo_with_stock(self, rm1_qty=10, rm2_qty=2):
		"""WO 100 (BOM 10 + 2) with exactly the recipe stocked in Stores."""
		wo = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, rm1_qty, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, rm2_qty, 500)
		return wo

	def _transfer(self, wo, items=None):
		frappe.set_user(self.operator)
		return api.transfer_material(wo, items, self._key())

	def _se_rows(self, wo_name):
		"""SUM of transferred qty per item over ALL submitted transfer SEs."""
		names = frappe.get_all(
			"Stock Entry",
			filters={"work_order": wo_name, "purpose": "Material Transfer for Manufacture", "docstatus": 1},
			pluck="name",
		)
		rows = {}
		for name in names:
			for row in frappe.get_all(
				"Stock Entry Detail",
				filters={"parent": name, "parenttype": "Stock Entry"},
				fields=["item_code", "qty"],
			):
				rows[row.item_code] = rows.get(row.item_code, 0.0) + flt(row.qty)
		return rows

	# ------------------------------------------------------------ happy path

	def test_happy_path_defaults_to_pending_rows(self):
		wo = self._wo_with_stock()
		result = self._transfer(wo)

		self.assertFalse(result.get("duplicate"))
		self.assertEqual(self._se_rows(wo), {factories.RM1: 10.0, factories.RM2: 2.0})
		self.assertEqual(result["next_action"], "finish_production")
		by_item = {m["item_code"]: m for m in result["materials"]}
		self.assertEqual(by_item[factories.RM1]["transferred_net"], 10.0)
		self.assertEqual(by_item[factories.RM1]["sisa_perlu"], 0.0)
		# the WO coverage field carries the SE's fg_completed_qty claim (100 = the
		# full target), while the per-material transferred_net shows the 10 actually moved
		self.assertEqual(
			frappe.db.get_value("Work Order", wo, "material_transferred_for_manufacturing"), 100.0
		)

	def test_explicit_override_then_default_covers_only_pending(self):
		wo = self._wo_with_stock()

		# Operator picks 5 of RM1 (RM2 keeps its pending default of 2).
		self._transfer(wo, {factories.RM1: 5})
		self.assertEqual(self._se_rows(wo), {factories.RM1: 5.0, factories.RM2: 2.0})

		# Second transfer carries ONLY the pending remainder (5 of RM1, no RM2).
		self._transfer(wo)
		rows = self._se_rows(wo)
		self.assertEqual(rows[factories.RM1], 10.0)  # 5 + 5 over both entries
		self.assertEqual(rows[factories.RM2], 2.0)

		# Everything picked: a third transfer is refused without a new SE.
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.transfer_material(wo, None, self._key())
		self.assertIn("Semua bahan sudah diambil", str(cm.exception))

	def test_operator_and_supervisor_both_allowed(self):
		wo = self._wo_with_stock()
		frappe.set_user(self.operator)
		result = api.transfer_material(wo, None, self._key())
		self.assertEqual(result["stock_entry"], self._transfer_se_name(wo))

		frappe.set_user("Administrator")
		wo2 = self._wo_with_stock()
		frappe.set_user(self.supervisor)
		result = api.transfer_material(wo2, None, self._key())
		self.assertTrue(result["stock_entry"])

		frappe.set_user(self.nobody)
		with self.assertRaises(frappe.PermissionError):
			api.transfer_material(wo, None, self._key())

	def _transfer_se_name(self, wo_name):
		return frappe.get_all(
			"Stock Entry",
			filters={"work_order": wo_name, "purpose": "Material Transfer for Manufacture", "docstatus": 1},
			pluck="name",
		)[0]

	# ----------------------------------------------------------------- gates

	def test_over_transfer_gate_rejects_without_stock_entry(self):
		wo = factories.make_wo()
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.transfer_material(wo, {factories.RM1: 1000}, self._key())
		message = str(cm.exception)
		self.assertIn("melebihi batas transfer", message)
		self.assertIn("gudang asal", message)  # directive per open decision #10
		self.assertEqual(
			frappe.get_all("Stock Entry", filters={"work_order": wo}, pluck="name"),
			[],
		)

	def test_indicative_stock_shortfall_message(self):
		wo = factories.make_wo()  # nothing stocked for THIS WO's needs
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.transfer_material(wo, None, self._key())
		message = str(cm.exception)
		# the class transaction may hold leftovers from earlier tests: the message
		# must name item, deficit (request - whatever is in Stores), uom, warehouse
		bin_qty = flt(
			frappe.db.get_value(
				"Bin", {"item_code": factories.RM1, "warehouse": factories.STORES}, "actual_qty"
			)
		)
		self.assertIn(f"Bahan {factories.RM1} kurang {flt(10 - bin_qty):g} Nos", message)
		self.assertIn(factories.STORES, message)
		self.assertIn("hubungi gudang", message)
		self.assertEqual(
			frappe.get_all("Stock Entry", filters={"work_order": wo}, pluck="name"),
			[],
		)

	def test_stopped_wo_rejected(self):
		wo = self._wo_with_stock()
		frappe.db.set_value("Work Order", wo, "status", "Stopped")
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.transfer_material(wo, None, self._key())
		self.assertIn("Stopped", str(cm.exception))

	# ------------------------------------------------------------ idempotency

	def test_replay_returns_duplicate_with_single_stock_entry(self):
		wo = self._wo_with_stock()
		frappe.set_user(self.operator)
		key = self._key()
		first = api.transfer_material(wo, None, key)
		replay = api.transfer_material(wo, None, key)

		self.assertTrue(replay["duplicate"])
		self.assertEqual(replay["stock_entry"], first["stock_entry"])
		self.assertEqual(
			len(frappe.get_all("Stock Entry", filters={"work_order": wo, "docstatus": 1})),
			1,
		)

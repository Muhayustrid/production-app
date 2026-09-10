"""Tests for api.finish_production (spec 7.6, numbers from the proof suite).

Contract proven per test:
- P1a recipe 95/5 with the 10+2 recipe materials: FG row 95, explicit loss 5,
  produced 95 / WO loss 5 / status Completed, custom_p_* and petugas recorded,
  default session materials = full WIP remaining (10 + 2);
- bahan dipakai 9.5 of the transferred 10 leaves 0.5 as WIP (INV10);
- overproduction beyond the allowance -> NEEDS_ALLOWANCE, no Stock Entry;
- unbooked operation loss with loss 0 -> the 6.7 pre-check message;
- good = 0 -> rejected with directions (3.6);
- FG batch item: the app creates the Batch (proof P7a-3) and the bundle qty
  follows good;
- core duplicate gate mapped to Indonesian (draft Manufacture SE covering the
  full qty already present);
- operations not completed -> friendly message;
- replay -> duplicate=True with a single Manufacture SE;
- pre != post mismatch -> recorded once as a Work Order comment.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from production_app import api
from production_app.exceptions import NeedsAllowanceError
from production_app.tests import factories

OPERATOR = "pdtc.finish.operator@example.com"
SUPERVISOR = "pdtc.finish.supervisor@example.com"


class TestFinishProduction(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls.supervisor = factories.make_user(SUPERVISOR, roles=["Production Supervisor"])
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

	def _wo_with_transfer(self):
		"""WO 100 (BOM 10 + 2), recipe stocked in Stores, materials transferred."""
		wo = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, 10, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 2, 500)
		frappe.set_user(self.operator)
		api.transfer_material(wo, None, self._key())
		return wo

	def _finish(self, wo, packing, user=None):
		frappe.set_user(user or self.operator)
		return api.finish_production(wo, packing, self._key())

	def _manufacture_ses(self, wo_name):
		return frappe.get_all(
			"Stock Entry",
			filters={"work_order": wo_name, "purpose": "Manufacture", "docstatus": 1},
			pluck="name",
		)

	def _se(self, se_name):
		return frappe.get_doc("Stock Entry", se_name)

	# ------------------------------------------------------------ happy paths

	def test_p1a_95_5_with_default_materials(self):
		wo = self._wo_with_transfer()
		result = self._finish(wo, {"good": 95, "loss_eksplisit": 5, "reject": 1, "trial": 0.5, "sisa": 2})

		self.assertFalse(result.get("duplicate"))
		self.assertEqual((result["produced"], result["loss"], result["remaining_target"]), (95.0, 5.0, 0.0))
		self.assertEqual(result["status"], "Completed")
		self.assertFalse(result.get("needs_close_decision"))

		se = self._se(result["stock_entry"])
		fg = next(r for r in se.items if r.item_code == factories.FG)
		self.assertEqual((flt(fg.qty), se.fg_completed_qty, flt(se.process_loss_qty)), (95.0, 100.0, 5.0))
		materials = {r.item_code: flt(r.qty) for r in se.items if r.item_code != factories.FG}
		self.assertEqual(materials, {factories.RM1: 10.0, factories.RM2: 2.0})  # actuals, not BOM x 95%
		# custom_p_* recorded, petugas defaults to the session user (INV9)
		self.assertEqual(
			(se.custom_p_good_qty, se.custom_p_reject_qty, se.custom_p_trial_qty, se.custom_p_sisa_qty),
			(95.0, 1.0, 0.5, 2.0),
		)
		self.assertEqual(se.custom_p_petugas_packing, self.operator)

		wo_fields = frappe.db.get_value(
			"Work Order", wo, ["produced_qty", "process_loss_qty", "status"], as_dict=True
		)
		self.assertEqual(
			(wo_fields.produced_qty, wo_fields.process_loss_qty, wo_fields.status), (95, 5, "Completed")
		)

	def test_used_9_5_leaves_0_5_in_wip(self):
		wo = self._wo_with_transfer()
		result = self._finish(wo, {"good": 95, "bahan_dipakai": {factories.RM1: 9.5}})

		self.assertEqual(result["produced"], 95.0)
		self.assertEqual(result["sisa_wip"], {factories.RM1: 0.5})
		se = self._se(result["stock_entry"])
		materials = {r.item_code: flt(r.qty) for r in se.items if r.item_code != factories.FG}
		self.assertEqual(materials, {factories.RM1: 9.5, factories.RM2: 2.0})
		# RM1 is a batch item: core picks the outward batch (nothing set by the app)
		rm1 = next(r for r in se.items if r.item_code == factories.RM1)
		self.assertTrue(rm1.serial_and_batch_bundle or rm1.batch_no)

	def test_fg_batch_created_by_app_with_bundle_qty_good(self):
		wo = self._wo_with_transfer()
		result = self._finish(wo, {"good": 95})

		se = self._se(result["stock_entry"])
		fg = next(r for r in se.items if r.item_code == factories.FG)
		self.assertEqual(fg.use_serial_batch_fields, 1)
		self.assertTrue(fg.batch_no)
		self.assertTrue(frappe.db.exists("Batch", fg.batch_no))
		self.assertEqual(frappe.db.get_value("Batch", fg.batch_no, "item"), factories.FG)
		from erpnext.stock.doctype.batch.batch import get_batch_qty

		self.assertEqual(flt(get_batch_qty(fg.batch_no, factories.FG_WH) or 0), 95.0)

	def test_replay_returns_duplicate_with_single_manufacture_se(self):
		wo = self._wo_with_transfer()
		frappe.set_user(self.operator)
		key = self._key()
		first = api.finish_production(wo, {"good": 40}, key)
		replay = api.finish_production(wo, {"good": 40}, key)

		self.assertTrue(replay["duplicate"])
		self.assertEqual(replay["stock_entry"], first["stock_entry"])
		self.assertEqual(len(self._manufacture_ses(wo)), 1)
		self.assertEqual(frappe.db.get_value("Work Order", wo, "produced_qty"), 40)

	def test_warning_pre_post_mismatch_becomes_one_wo_comment(self):
		wo = self._wo_with_transfer()
		result = self._finish(wo, {"good": 95, "good_pre": 97})

		self.assertEqual(len(result["warnings"]), 1)
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Order", "reference_name": wo, "comment_type": "Comment"},
			pluck="content",
		)
		self.assertEqual(len(comments), 1)
		self.assertIn("pre-packing", comments[0])

	def test_is_final_short_of_target_flags_close_decision(self):
		wo = self._wo_with_transfer()
		result = self._finish(wo, {"good": 60, "is_final": True})
		self.assertTrue(result["needs_close_decision"])
		self.assertEqual(result["remaining_target"], 40.0)
		self.assertNotEqual(result["status"], "Closed")  # no automatic action, 3.4

	# ------------------------------------------------------- input validation

	def test_good_zero_rejected_with_directions(self):
		wo = self._wo_with_transfer()
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.finish_production(wo, {"good": 0}, self._key())
		self.assertIn("Hasil Baik", str(cm.exception))
		self.assertIn("Supervisor", str(cm.exception))

	def test_overproduction_without_allowance_no_stock_entry(self):
		wo = self._wo_with_transfer()
		frappe.set_user(self.operator)
		with self.assertRaises(NeedsAllowanceError) as cm:
			api.finish_production(wo, {"good": 105}, self._key())
		self.assertEqual(cm.exception.code, "NEEDS_ALLOWANCE")
		self.assertEqual(self._manufacture_ses(wo), [])

	def test_pending_operation_loss_precheck(self):
		wo = self._wo_with_transfer()
		factories.add_wo_operation(wo, process_loss_qty=5)
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.finish_production(wo, {"good": 95}, self._key())  # loss 0 -> core would inject 5
		self.assertIn("loss operasi", str(cm.exception))
		self.assertEqual(self._manufacture_ses(wo), [])

	def test_operations_not_completed_friendly_message(self):
		wo = self._wo_with_transfer()
		factories.add_wo_operation(wo, process_loss_qty=0)  # completed 0 of 100
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.finish_production(wo, {"good": 95}, self._key())
		message = str(cm.exception)
		self.assertIn(factories.OPERATION, message)
		self.assertIn("Selesaikan operasi", message)
		self.assertEqual(self._manufacture_ses(wo), [])

	# ---------------------------------------------------------- core mappings

	def test_duplicate_gate_mapped_to_indonesian(self):
		wo = self._wo_with_transfer()  # WIP holds the full 10 + 2, produced 0

		# A Desk draft already covering the full qty trips the core duplicate gate
		# (check_duplicate_entry_for_work_order counts docstatus != 2).
		from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

		frappe.set_user("Administrator")  # operator has no SE create permission
		frappe.get_doc(make_stock_entry(wo, "Manufacture", qty=100)).insert()

		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.finish_production(wo, {"good": 10}, self._key())
		self.assertIn("Target sesi sebelumnya sudah mencapai batas", str(cm.exception))

	def test_completed_wo_rejected(self):
		wo = self._wo_with_transfer()
		self._finish(wo, {"good": 95, "loss_eksplisit": 5})  # -> Completed
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.finish_production(wo, {"good": 1}, self._key())
		self.assertIn("Completed", str(cm.exception))

	def test_empty_session_precheck_message(self):
		wo = factories.make_wo()  # no transfer -> nothing in WIP to consume
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.finish_production(wo, {"good": 10}, self._key())
		self.assertIn("Belum ada bahan yang tersedia untuk dikonsumsi", str(cm.exception))
		self.assertEqual(self._manufacture_ses(wo), [])

	def test_skip_transfer_finish_defaults_to_bom_rows_from_source(self):
		wo = factories.make_wo()
		frappe.db.set_value("Work Order", wo, "skip_transfer", 1)
		factories.stock_in(factories.RM1, factories.STORES, 10, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 2, 500)
		result = self._finish(wo, {"good": 95})

		self.assertEqual(result["produced"], 95.0)
		self.assertEqual(result["status"], "In Process")
		se = self._se(result["stock_entry"])
		# default session = BOM requirement scaled to the session qty (10 -> 9.5,
		# 2 -> 1.9), booked straight from the source warehouse - no WIP involved
		materials = {r.item_code: flt(r.qty) for r in se.items if r.item_code != factories.FG}
		self.assertEqual(materials, {factories.RM1: 9.5, factories.RM2: 1.9})
		rm1 = next(r for r in se.items if r.item_code == factories.RM1)
		self.assertEqual(rm1.s_warehouse, factories.STORES)

	def test_skip_transfer_finish_explicit_override_wins(self):
		wo = factories.make_wo()
		frappe.db.set_value("Work Order", wo, "skip_transfer", 1)
		factories.stock_in(factories.RM1, factories.STORES, 10, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 2, 500)
		result = self._finish(wo, {"good": 50, "bahan_dipakai": {factories.RM1: 8}})

		se = self._se(result["stock_entry"])
		materials = {r.item_code: flt(r.qty) for r in se.items if r.item_code != factories.FG}
		self.assertEqual(materials, {factories.RM1: 8.0, factories.RM2: 1.0})
		self.assertEqual(result["produced"], 50.0)

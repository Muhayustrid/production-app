"""Tests for qty.py - quantity contract validation (spec 3, 6.7, 13).

Covers: normalization (finite >= 0, field precision), good = 0 rejection with
directions (3.6), over-production NEEDS_ALLOWANCE without/with enough core
allowance incl. the cumulative produced quantity (3.4), the unbooked
operation/BOM loss pre-check (6.7, proofs P11/P13h), pre != post as a warning
only, and the session material defaults / explicit override / WIP-net cap
(INV5, INV10).
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from production_app import qty
from production_app.exceptions import NeedsAllowanceError
from production_app.tests import factories


class TestQty(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		factories.setup_operation()

	def _wo(self):
		"""Fresh WO per test: target 100, produced 0, loss 0."""
		return frappe.get_doc("Work Order", factories.make_wo())

	def _allowance(self, pct):
		original = frappe.db.get_single_value(
			"Manufacturing Settings", "overproduction_percentage_for_work_order"
		)
		frappe.db.set_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order", pct)
		self.addCleanup(
			frappe.db.set_single_value,
			"Manufacturing Settings",
			"overproduction_percentage_for_work_order",
			original,
		)

	def test_happy_path_and_defaults(self):
		wo = self._wo()
		normalized, warnings = qty.validate_packing(
			wo,
			{
				"good": 10,
				"reject": 1,
				"trial": 0.5,
				"sisa": 2,
				"good_pre": 10,
				"reject_pre": 1,
				"trial_pre": 0.5,
				"sisa_pre": 2,
				"is_final": True,
			},
		)
		self.assertEqual(normalized.good, 10.0)
		self.assertEqual(normalized.reject, 1.0)
		self.assertEqual(normalized.loss_eksplisit, 0.0)  # default 0 (INV1)
		self.assertEqual(normalized.petugas_packing, "Administrator")  # session user default
		self.assertEqual(normalized.is_final, 1)
		self.assertEqual(warnings, [])
		# Validation never mutates the WO: the sisa target is untouched.
		self.assertEqual(qty.remaining_target(wo), 100.0)

	def test_invalid_numbers_rejected(self):
		wo = self._wo()
		with self.assertRaises(frappe.ValidationError):
			qty.validate_packing(wo, {"good": -1})
		with self.assertRaises(frappe.ValidationError):
			qty.validate_packing(wo, {"good": 10, "reject": -0.5})
		# NaN/Infinity (float AND string) are rejected by the isfinite gate on
		# the PARSED value - flt would coerce them to 0 under legacy rounding
		# and silently accept junk like reject="NaN" as 0 (task 22 review)
		for bad in (float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity"):
			with self.assertRaises(frappe.ValidationError) as cm:
				qty.validate_packing(wo, {"good": 10, "reject": bad})
			self.assertIn("Reject harus berupa angka yang valid", str(cm.exception))
		# unparseable strings are rejected, never coerced to 0
		with self.assertRaises(frappe.ValidationError) as cm:
			qty.validate_packing(wo, {"good": 10, "reject": "abc"})
		self.assertIn("Reject", str(cm.exception))
		self.assertIn("harus berupa angka yang valid", str(cm.exception))
		# precision follows the field
		normalized, _ = qty.validate_packing(wo, {"good": 10.123456789})
		self.assertEqual(normalized.good, flt(10.123456789, wo.precision("qty")))
		self.assertNotEqual(normalized.good, 10.123456789)

	def test_good_zero_rejected_with_directions(self):
		wo = self._wo()
		with self.assertRaises(frappe.ValidationError) as cm:
			qty.validate_packing(wo, {"good": 0})
		self.assertIn("Hasil Baik", str(cm.exception))
		self.assertIn("Supervisor", str(cm.exception))

	def test_overproduction_without_allowance(self):
		wo = self._wo()
		with self.assertRaises(NeedsAllowanceError) as cm:
			qty.validate_packing(wo, {"good": 105})  # target 100, allowance 0
		self.assertEqual(cm.exception.code, "NEEDS_ALLOWANCE")

	def test_overproduction_with_allowance(self):
		self._allowance(10)
		wo = self._wo()
		qty.validate_packing(wo, {"good": 105})  # within 100 * 1.10 = 110
		# The core gate compares the CUMULATIVE produced quantity (3.4 [F]):
		# 60 + 55 = 115 > 110 even though 55 alone is within tolerance.
		frappe.db.set_value("Work Order", wo.name, "produced_qty", 60)
		wo.reload()
		with self.assertRaises(NeedsAllowanceError):
			qty.validate_packing(wo, {"good": 55})

	def test_pending_operation_loss_precheck(self):
		wo = self._wo()
		factories.add_wo_operation(wo.name, process_loss_qty=5)
		with self.assertRaises(frappe.ValidationError) as cm:
			qty.validate_packing(wo, {"good": 10})  # loss 0 -> core would inject 5
		self.assertIn("loss operasi", str(cm.exception))
		# Explicit loss wins over the operation loss (proof P13h-H1).
		qty.validate_packing(wo, {"good": 10, "loss_eksplisit": 7})

	def test_bom_pct_loss_precheck(self):
		wo = self._wo()
		original = frappe.db.get_value("BOM", wo.bom_no, "process_loss_percentage")
		frappe.db.set_value("BOM", wo.bom_no, "process_loss_percentage", 5)
		self.addCleanup(frappe.db.set_value, "BOM", wo.bom_no, "process_loss_percentage", original)
		with self.assertRaises(frappe.ValidationError) as cm:
			qty.validate_packing(wo, {"good": 100})  # loss 0 -> core would inject 100*5%
		self.assertIn("BOM", str(cm.exception))
		# Gross mapping with explicit loss == BOM pct passes (proof P11-v2).
		qty.validate_packing(wo, {"good": 100, "loss_eksplisit": 5})

	def test_pre_post_mismatch_is_warning_not_error(self):
		wo = self._wo()
		normalized, warnings = qty.validate_packing(wo, {"good": 10, "good_pre": 12})
		self.assertEqual(normalized.good, 10.0)
		self.assertEqual(len(warnings), 1)
		self.assertIn("pre-packing", warnings[0])

	def test_compute_session_materials_default_and_override(self):
		wo_name = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 100, 500)
		factories.se_transfer(wo_name, materials={factories.RM1: 100, factories.RM2: 50})
		wo = frappe.get_doc("Work Order", wo_name)

		# Session 1 defaults: full WIP remaining per material.
		self.assertEqual(qty.compute_session_materials(wo), {factories.RM1: 100.0, factories.RM2: 50.0})
		# Explicit override per item; unlisted items keep their default.
		session = qty.compute_session_materials(wo, {factories.RM1: 95.5})
		self.assertEqual(session, {factories.RM1: 95.5, factories.RM2: 50.0})

		# Session 1 consumes 95.5 / 50 -> session 2 sees the net remainder.
		factories.se_manufacture(wo_name, good=90, materials={factories.RM1: 95.5, factories.RM2: 50})
		wo.reload()
		self.assertEqual(qty.compute_session_materials(wo), {factories.RM1: 4.5})

	def test_compute_session_materials_overuse_rejected(self):
		wo_name = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 100, 500)
		factories.se_transfer(wo_name, materials={factories.RM1: 100, factories.RM2: 20})
		wo = frappe.get_doc("Work Order", wo_name)

		with self.assertRaises(frappe.ValidationError):
			qty.compute_session_materials(wo, {factories.RM1: 100.5})  # > WIP net
		with self.assertRaises(frappe.ValidationError):
			qty.compute_session_materials(wo, {factories.RM2: -1})  # negative
		with self.assertRaises(frappe.ValidationError):
			qty.compute_session_materials(wo, {"PDTC-UNKNOWN-ITEM": 1})  # never in WIP
		with self.assertRaises(frappe.ValidationError) as cm:
			qty.compute_session_materials(wo, {factories.RM1: "abc"})  # unparseable
		self.assertIn("harus berupa angka yang valid", str(cm.exception))

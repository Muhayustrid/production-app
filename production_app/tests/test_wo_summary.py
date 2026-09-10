"""Tests for wo_summary.recompute (spec 8.1).

Covers: aggregation of app-style entries + a Desk entry without custom_p_*
(good falls back to core FG rows), post AND pre totals, cancel reducing the
summary, and the missing-Work-Order-field path (skip + one Work Order
comment, never silent).

WO summary fields are the SITE's Customize-Form fields (spec 8.1):
custom_*_postpacking / custom_*_prepacking totals, custom_qc_packing,
custom_jam_packing.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from production_app import wo_summary
from production_app.tests import factories


def _summary(wo):
	return frappe.db.get_value(
		"Work Order",
		wo,
		[
			"custom_good_qty_postpacking",
			"custom_reject_qty_postpacking",
			"custom_trial_qty_postpacking",
			"custom_sisa_qty_postpacking",
			"custom_good_qty_prepacking",
			"custom_reject_qty_prepacking",
			"custom_trial_qty_prepacking",
			"custom_sisa_qty_prepacking",
			"custom_qc_packing",
			"custom_jam_packing",
		],
		as_dict=True,
	)


class TestWoSummary(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		cls._ensure_wo_summary_fields()

	@staticmethod
	def _ensure_wo_summary_fields():
		"""Work Order summary fields are site-owned (spec 8.3) - the tests
		install the spec 8.1 totals if the site does not have them yet
		(custom_qc_packing / custom_jam_packing already exist on this site)."""
		from frappe.custom.doctype.custom_field.custom_field import create_custom_field

		missing = wo_summary._missing_wo_fields()
		if not missing:
			return
		types = {
			"custom_good_qty_postpacking": "Float",
			"custom_reject_qty_postpacking": "Float",
			"custom_trial_qty_postpacking": "Float",
			"custom_sisa_qty_postpacking": "Float",
			"custom_good_qty_prepacking": "Float",
			"custom_reject_qty_prepacking": "Float",
			"custom_trial_qty_prepacking": "Float",
			"custom_sisa_qty_prepacking": "Float",
			"custom_qc_packing": "Link",
			"custom_jam_packing": "Datetime",
		}
		for fieldname in missing:
			props = {
				"fieldname": fieldname,
				"label": fieldname,
				"fieldtype": types[fieldname],
				"insert_after": "project",
			}
			if types[fieldname] == "Link":
				props["options"] = "User"
			create_custom_field("Work Order", props)
		frappe.clear_cache("doctype", "Work Order")

	def test_two_app_sessions_plus_desk_entry(self):
		wo = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 100, 500)
		factories.se_transfer(wo, materials={factories.RM1: 100, factories.RM2: 100})

		# App-style session 1: good=60 reject=2 trial=1 sisa=3, pre good=100;
		# no petugas -> owner.
		factories.se_manufacture(
			wo,
			good=60,
			materials={factories.RM1: 10, factories.RM2: 2},
			packing={
				"custom_p_good_qty": 60,
				"custom_p_reject_qty": 2,
				"custom_p_trial_qty": 1,
				"custom_p_sisa_qty": 3,
				"custom_p_good_qty_pre": 100,
				"custom_p_reject_qty_pre": 2,
				"custom_p_trial_qty_pre": 1,
				"custom_p_sisa_qty_pre": 4,
			},
		)
		s = _summary(wo)
		self.assertEqual(s.custom_good_qty_postpacking, 60)
		self.assertEqual(
			(s.custom_reject_qty_postpacking, s.custom_trial_qty_postpacking, s.custom_sisa_qty_postpacking),
			(2, 1, 3),
		)
		self.assertEqual(s.custom_good_qty_prepacking, 100)  # SE pre reading -> WO pre total
		self.assertEqual(
			(s.custom_reject_qty_prepacking, s.custom_trial_qty_prepacking, s.custom_sisa_qty_prepacking),
			(2, 1, 4),
		)
		self.assertEqual(s.custom_qc_packing, "Administrator")  # petugas falls back to owner

		# App-style session 2: good=30 sisa=5, pre good=50 sisa_pre=2, petugas set.
		factories.se_manufacture(
			wo,
			good=30,
			materials={factories.RM1: 10, factories.RM2: 2},
			packing={
				"custom_p_good_qty": 30,
				"custom_p_sisa_qty": 5,
				"custom_p_petugas_packing": "Administrator",
				"custom_p_good_qty_pre": 50,
				"custom_p_sisa_qty_pre": 2,
			},
		)
		s = _summary(wo)
		self.assertEqual(s.custom_good_qty_postpacking, 90)
		self.assertEqual(
			(s.custom_reject_qty_postpacking, s.custom_trial_qty_postpacking, s.custom_sisa_qty_postpacking),
			(2, 1, 8),
		)
		self.assertEqual(s.custom_good_qty_prepacking, 150)
		self.assertEqual(
			(s.custom_reject_qty_prepacking, s.custom_trial_qty_prepacking, s.custom_sisa_qty_prepacking),
			(2, 1, 6),
		)
		self.assertEqual(s.custom_qc_packing, "Administrator")
		self.assertIsNotNone(s.custom_jam_packing)

		# Desk entry WITHOUT custom_p_*: good falls back to its core FG row (10),
		# categories and pre readings unchanged.
		factories.se_manufacture(wo, good=10, materials={factories.RM1: 10, factories.RM2: 2})
		s = _summary(wo)
		self.assertEqual(s.custom_good_qty_postpacking, 100)
		self.assertEqual(
			(s.custom_reject_qty_postpacking, s.custom_trial_qty_postpacking, s.custom_sisa_qty_postpacking),
			(2, 1, 8),
		)
		self.assertEqual(s.custom_good_qty_prepacking, 150)
		self.assertEqual(
			(s.custom_reject_qty_prepacking, s.custom_trial_qty_prepacking, s.custom_sisa_qty_prepacking),
			(2, 1, 6),
		)

	def test_cancel_reduces_summary(self):
		wo = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 100, 500)
		factories.se_transfer(wo, materials={factories.RM1: 100, factories.RM2: 100})

		factories.se_manufacture(
			wo,
			good=60,
			materials={factories.RM1: 10, factories.RM2: 2},
			packing={"custom_p_good_qty": 60, "custom_p_good_qty_pre": 100},
		)
		self.assertEqual(_summary(wo).custom_good_qty_postpacking, 60)

		se2 = factories.se_manufacture(
			wo,
			good=30,
			materials={factories.RM1: 10, factories.RM2: 2},
			packing={"custom_p_good_qty": 30, "custom_p_reject_qty": 4, "custom_p_good_qty_pre": 40},
		)
		self.assertEqual(_summary(wo).custom_good_qty_postpacking, 90)
		self.assertEqual(_summary(wo).custom_good_qty_prepacking, 140)

		se2.cancel()  # hook fires on_cancel -> recompute drops the entry
		s = _summary(wo)
		self.assertEqual(s.custom_good_qty_postpacking, 60)
		self.assertEqual(s.custom_reject_qty_postpacking, 0)
		self.assertEqual(s.custom_good_qty_prepacking, 100)

	def test_missing_wo_fields_commented_not_silent(self):
		wo = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 100, 500)
		factories.se_transfer(wo, materials={factories.RM1: 100, factories.RM2: 100})
		factories.se_manufacture(
			wo,
			good=25,
			materials={factories.RM1: 10, factories.RM2: 2},
			packing={"custom_p_good_qty": 25},
		)

		# Simulate a site whose Work Order meta lacks one summary field (spec 8.3).
		bogus = "custom_p_bogus_field"
		fields = (wo_summary.WO_SUMMARY_FIELDS[0], bogus)
		with patch.object(wo_summary, "WO_SUMMARY_FIELDS", fields):
			wo_summary.recompute(wo)

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Order", "reference_name": wo},
			pluck="content",
		)
		matching = [c for c in comments if bogus in c]
		self.assertTrue(matching, "missing-field skip must leave one Work Order comment")
		# Present fields are still written.
		self.assertEqual(_summary(wo).custom_good_qty_postpacking, 25)

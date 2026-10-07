# FU100 — uji multi-value filter wo_list (pilot Work Order).
# Read-only terhadap data live (tanpa fixture tulis): parser murni + ekuivalensi
# skalar-lama vs list, gabungan multi = jumlah tunggal, [] = tanpa filter,
# melebihi batas = ValidationError. Delta-safe: hanya SELECT.
import json
import unittest

import frappe

from production_app.api.work_order import _filter_list, wo_list


class TestWoMultiFilter(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		rows = frappe.get_all(
			"Work Order",
			filters={"docstatus": ["<", 2]},
			fields=["production_item", "status"],
			order_by="creation desc",
			limit_page_length=500,
		)
		if not rows:
			raise unittest.SkipTest("tidak ada Work Order live")
		seen, cls.items = set(), []
		for r in rows:
			if r.production_item and r.production_item not in seen:
				seen.add(r.production_item)
				cls.items.append(r.production_item)
		cls.statuses = sorted({r.status for r in rows if r.status})

	def test_filter_list_parser(self):
		self.assertEqual(_filter_list(None, "x"), [])
		self.assertEqual(_filter_list("", "x"), [])
		self.assertEqual(_filter_list("   ", "x"), [])
		self.assertEqual(_filter_list("ABC", "x"), ["ABC"])  # skalar lama
		self.assertEqual(_filter_list('["A","B"]', "x"), ["A", "B"])  # string JSON
		self.assertEqual(_filter_list(["A", "A", " ", "", "B"], "x"), ["A", "B"])  # dedupe
		self.assertEqual(_filter_list([" A ", None], "x"), ["A"])  # trim
		with self.assertRaises(frappe.ValidationError):
			_filter_list(123, "x")  # type salah
		with self.assertRaises(frappe.ValidationError):
			_filter_list([f"X{i}" for i in range(101)], "x")  # lewat batas

	def test_scalar_legacy_equals_single_item_list(self):
		if not self.items:
			self.skipTest("tidak ada item")
		item = self.items[0]
		via_scalar = wo_list(production_item=item, meta=1)
		via_list = wo_list(production_item=[item], meta=1)
		via_json = wo_list(production_item=json.dumps([item]), meta=1)
		self.assertEqual(via_scalar["total"], via_list["total"])
		self.assertEqual(via_scalar["total"], via_json["total"])

	def test_multi_value_equals_union_of_singles(self):
		if len(self.items) < 2:
			self.skipTest("butuh >=2 produk")
		a, b = self.items[:2]
		multi = wo_list(production_item=[a, b], meta=1)["total"]
		single = wo_list(production_item=a, meta=1)["total"] + wo_list(production_item=b, meta=1)["total"]
		self.assertEqual(multi, single)

	def test_status_list_union(self):
		if len(self.statuses) < 2:
			self.skipTest("butuh >=2 status")
		s1, s2 = self.statuses[:2]
		multi = wo_list(status=[s1, s2], meta=1)["total"]
		single = wo_list(status=s1, meta=1)["total"] + wo_list(status=s2, meta=1)["total"]
		self.assertEqual(multi, single)

	def test_empty_list_means_no_filter(self):
		all_total = wo_list(meta=1)["total"]
		self.assertEqual(wo_list(production_item=[], meta=1)["total"], all_total)
		self.assertEqual(wo_list(production_item="  ", meta=1)["total"], all_total)

	def test_over_limit_throws(self):
		with self.assertRaises(frappe.ValidationError):
			wo_list(production_item=[f"X{i}" for i in range(101)], meta=1)

# F03 — finish(): baris RM duplikat (item sama pada 2 baris BOM) harus BERBAGI
# sisa rencana (transferred − consumed), bukan masing-masing menerima sisa penuh.
#
# Bug pra-fix: kedua baris RM dengan item_code sama mendapat transfer_qty penuh
# (mis. 60 dan 60 padahal saldonya 60) → konsumsi RM berlipat tanpa error.
# Kontrak non-negotiable #2 proyek: konsumsi mengikuti rencana.
#
# Fixture: prefix TESTF03-, seluruhnya dibuat di dalam transaksi test
# (IntegrationTestCase me-rollback seluruh kelas saat teardown — tidak ada
# dokumen operasional atau Master yang tersentuh setelah run).
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, now, nowdate, nowtime, random_string

PREFIX = "TESTF03-"


def _first_existing_wo_config():
	"""Read-only: reuse the company/warehouses/UOM an existing WO already uses."""
	name = frappe.db.get_value(
		"Work Order",
		{"docstatus": 1, "fg_warehouse": ("is", "set"), "wip_warehouse": ("is", "set")},
		"name",
		order_by="creation desc",
	)
	if not name:
		frappe.throw("No submitted Work Order exists to derive a test configuration from")
	return frappe.db.get_value(
		"Work Order",
		name,
		["company", "fg_warehouse", "wip_warehouse", "source_warehouse", "stock_uom"],
		as_dict=True,
	)


class TestWoFinishDuplicateRm(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cfg = _first_existing_wo_config()
		cls.company = cfg.company
		cls.fg_wh = cfg.fg_warehouse
		cls.wip_wh = cfg.wip_warehouse
		cls.src_wh = cfg.source_warehouse or cfg.wip_warehouse
		cls.uom = cfg.stock_uom
		cls.currency = frappe.db.get_value("Company", cls.company, "default_currency")
		# companies with enable_item_wise_inventory_account need an inventory
		# account on the new items (or their group) before any SE can be submitted
		cls.inventory_account = (
			frappe.db.get_value(
				"Item Default",
				{"company": cls.company, "default_inventory_account": ("is", "set")},
				"default_inventory_account",
			)
			or frappe.db.get_value("Company", cls.company, "default_inventory_account")
		)

	def _make_item(self, tag, group):
		# item code/name follows the site naming series (field:item_code + series override),
		# so the created name is read back instead of assumed
		defaults = {"company": self.company, "default_warehouse": self.src_wh}
		if self.inventory_account:
			defaults["default_inventory_account"] = self.inventory_account
		return (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_name": f"{PREFIX}{tag}-{random_string(6).upper()}",
					"item_group": group,
					"stock_uom": self.uom,
					"is_stock_item": 1,
					"is_purchase_item": 0,
					"is_sales_item": 0,
					"has_batch_no": 0,
					"standard_rate": 10,
					"is_fixed_asset": 0,
					"opening_stock": 0,
					"item_defaults": [defaults],
				}
			)
			.insert()
			.name
		)

	def _receipt(self, item, qty, warehouse):
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"posting_date": nowdate(),
				"posting_time": nowtime(),
				"items": [
					{
						"item_code": item,
						"qty": qty,
						"basic_rate": 10,
						"t_warehouse": warehouse,
						"use_serial_batch_fields": 0,
					}
				],
			}
		)
		se.insert()
		se.submit()
		return se

	def _make_operations(self, count):
		"""`count` distinct operations on one fresh workstation — two BOM rows of the
		same item tagged to different operations stay two rows in the native
		Manufacture (get_bom_items_as_dict groups by item_code+stock_uom+operation)."""
		suf = random_string(4).upper()
		self.workstation = (
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": f"{PREFIX}WS-{suf}",
					"production_capacity": 10,
					"hour_rate": 100,
				}
			)
			.insert()
			.name
		)
		ops = []
		for i in range(count):
			code = f"{PREFIX}OP-{i}-{suf}"
			ops.append(
				frappe.get_doc(
					{
						"doctype": "Operation",
						"name": code,
						"operation_name": code,
						"workstation": self.workstation,
					}
				)
				.insert()
				.name
			)
		return ops

	def _bom_two_rows(self, fg, rm, ops):
		"""Dua baris item RM sama (60/40 dari qty 1), masing-masing tertaut ke satu
		operasi — bentuk BOM yang menghasilkan dua baris RM duplikat di Manufacture."""
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": fg,
				"company": self.company,
				"currency": self.currency,
				"quantity": 1,
				"with_operations": 1,
				"items": [
					{
						"item_code": rm,
						"qty": 0.6,
						"rate": 10,
						"uom": self.uom,
						"stock_uom": self.uom,
						"source_warehouse": self.src_wh,
						"operation": ops[0],
					},
					{
						"item_code": rm,
						"qty": 0.4,
						"rate": 10,
						"uom": self.uom,
						"stock_uom": self.uom,
						"source_warehouse": self.src_wh,
						"operation": ops[1],
					},
				],
				"operations": [
					{"operation": ops[0], "workstation": self.workstation, "time_in_mins": 60, "hour_rate": 100},
					{"operation": ops[1], "workstation": self.workstation, "time_in_mins": 30, "hour_rate": 100},
				],
			}
		)
		bom.insert()
		bom.submit()
		return bom.name

	def _bom_single_row(self, fg, rm):
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": fg,
				"company": self.company,
				"currency": self.currency,
				"quantity": 1,
				"items": [
					{
						"item_code": rm,
						"qty": 2,
						"rate": 10,
						"uom": self.uom,
						"stock_uom": self.uom,
						"source_warehouse": self.src_wh,
					}
				],
			}
		)
		bom.insert()
		bom.submit()
		return bom.name

	def _make_wo(self, fg, bom, qty=100):
		wo = frappe.get_doc(
			{
				"doctype": "Work Order",
				"production_item": fg,
				"bom_no": bom,
				"qty": qty,
				"company": self.company,
				"fg_warehouse": self.fg_wh,
				"wip_warehouse": self.wip_wh,
				"source_warehouse": self.src_wh,
				"scrap_warehouse": self.fg_wh,
				"stock_uom": self.uom,
				"planned_start_date": now(),
				"transfer_material_against": "Work Order",
				"use_multi_level_bom": 0,
			}
		)
		wo.get_items_and_operations_from_bom()
		wo.insert()
		wo.submit()
		return wo

	def _complete_job_cards(self, wo):
		from production_app.api.work_order import jobcard_complete, jobcard_start

		for card in frappe.get_all(
			"Job Card", filters={"work_order": wo.name}, fields=["name"], order_by="creation"
		):
			employee = frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": f"{PREFIX}Op {random_string(4)}",
					"employee_name": f"{PREFIX}Operator {random_string(4)}",
					"company": self.company,
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
				}
			).insert().name
			jobcard_start(wo.name, card.name, employees=[{"employee": employee}])
			jobcard_complete(wo.name, card.name, qty=flt(wo.qty), auto_submit=1)

	def _transferred(self, wo):
		"""item -> Σ transfer_qty transfer SE (persis seperti finish() membacanya)."""
		names = frappe.get_all(
			"Stock Entry",
			filters={"work_order": wo.name, "purpose": "Material Transfer for Manufacture", "docstatus": 1},
			pluck="name",
		)
		amounts = frappe._dict()
		if not names:
			return amounts
		for r in frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": ("in", names), "docstatus": 1},
			fields=["item_code", "transfer_qty"],
		):
			amounts[r.item_code] = amounts.get(r.item_code, 0.0) + flt(r.transfer_qty)
		return amounts

	def _consumed(self, wo):
		amounts = frappe._dict()
		for r in wo.required_items:
			amounts[r.item_code] = amounts.get(r.item_code, 0.0) + flt(r.consumed_qty)
		return amounts

	def _balance(self, wo, item):
		return flt(self._transferred(wo).get(item)) - flt(self._consumed(wo).get(item, 0.0))

	def test_f03_duplicate_rm_rows_share_the_remaining_balance(self):
		"""BOM dengan item RM sama di 2 baris (60/40, dua operasi): Manufacture hasil
		finish() harus membagi transferred − consumed ke kedua baris RM. Pra-fix
		kedua baris masing-masing menerima seluruh sisa (Σ = 2× sisa)."""
		from production_app.api.work_order import (
			confirm_postpacking,
			confirm_prepacking,
			finish,
			transfer_materials,
		)

		rm = self._make_item("A-RM", "Bahan Baku")
		fg = self._make_item("A-FG", "Produk Jadi Pabrik")
		self._receipt(rm, 1000, self.src_wh)
		# headroom WIP: overshoot pra-fix (2× sisa) tidak boleh mati di NegativeStockError
		# supaya SE yang salah benar-benar terbentuk dan angkanya bisa dibuktikan
		self._receipt(rm, 1000, self.wip_wh)

		ops = self._make_operations(2)
		bom = self._bom_two_rows(fg, rm, ops)
		wo = self._make_wo(fg, bom, 100)
		self.assertEqual(
			[flt(r.required_qty) for r in wo.required_items],
			[60.0, 40.0],
			"fixture harus punya 2 baris required item yang sama (60 + 40)",
		)

		self._complete_job_cards(wo)
		transfer_materials(wo.name)
		confirm_prepacking(wo.name, values={"good": 100, "reject": 0, "trial": 0})
		confirm_postpacking(wo.name, values={"good": 80, "reject": 0, "trial": 0})

		balance = self._balance(wo, rm)
		self.assertGreater(balance, 0, "fixture harus menyisakan saldo RM belum terpakai")

		result = finish(wo.name)
		se = frappe.get_doc("Stock Entry", result["stock_entry"])
		self.assertEqual(se.docstatus, 1)
		rows = [r for r in se.items if not r.is_finished_item and r.item_code == rm]
		self.assertEqual(len(rows), 2, "fixture harus menghasilkan 2 baris RM duplikat di Manufacture")

		shares = sorted(flt(r.transfer_qty) for r in rows)
		self.assertAlmostEqual(
			sum(shares), balance, places=6, msg="Σ transfer_qty baris RM duplikat harus = transferred − consumed"
		)
		self.assertLess(max(shares), balance, "satu baris tidak boleh menyerap seluruh saldo saat item duplikat")
		# pembagian proporsional bobot baris (60/40)
		self.assertAlmostEqual(shares[0], balance * 0.4, places=6)
		self.assertAlmostEqual(shares[1], balance * 0.6, places=6)

	def test_f03_single_rm_row_keeps_the_old_formula(self):
		"""Satu baris per item: hasil finish() identik dengan rumus lama
		transfer_qty = transferred − consumed (tanpa pembagian apa pun)."""
		from production_app.api.work_order import (
			confirm_postpacking,
			confirm_prepacking,
			finish,
			transfer_materials,
		)

		rm = self._make_item("B-RM", "Bahan Baku")
		fg = self._make_item("B-FG", "Produk Jadi Pabrik")
		self._receipt(rm, 1000, self.src_wh)

		bom = self._bom_single_row(fg, rm)
		wo = self._make_wo(fg, bom, 100)
		transfer_materials(wo.name)
		confirm_prepacking(wo.name, values={"good": 100, "reject": 0, "trial": 0})
		confirm_postpacking(wo.name, values={"good": 80, "reject": 0, "trial": 0})

		balance = self._balance(wo, rm)
		self.assertGreater(balance, 0)

		result = finish(wo.name)
		se = frappe.get_doc("Stock Entry", result["stock_entry"])
		rows = [r for r in se.items if not r.is_finished_item]
		self.assertEqual(len(rows), 1, "fixture single-row harus menghasilkan 1 baris RM")
		self.assertAlmostEqual(
			flt(rows[0].transfer_qty), balance, places=6, msg="baris tunggal = rumus lama (transferred − consumed)"
		)
		self.assertAlmostEqual(
			flt(rows[0].qty), balance / flt(rows[0].conversion_factor or 1), places=6
		)

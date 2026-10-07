# Outlet single-level BOM guard suite (insiden cloud 2026-10-07, FU100 —
# WO-RPMD-261007001 gagal "Valuation Rate for Item BB260055 is required"
# karena use_multi_level_bom=1 meledakkan resep dough ke bahan pabrik).
#
# Proves by execution on the installed runtime:
# - WO item grup "Produk Jadi Outlet" yang dibuat TANPA set use_multi_level_bom
#   (= default ERPNext 1, persis pos_next start_production) dipaksa 0 dan
#   required_items dibangun ulang di level tunggal (baris sub-assembly
#   dough/krim, BUKAN bahan mentah pabrik);
# - jalur Production Plan native (insert dengan flags.ignore_validate=1 dan
#   baris hasil ledakan sudah terpasang) ikut kena rebuild — before_validate
#   tidak dilewati flags.ignore_validate;
# - item grup lain (pabrik) tidak disentuh: mlb=1 bertahan;
# - SE Manufacture dari builder native mengonsumsi HANYA baris single-level
#   dan insert+submit sampai WO Completed (kasus gagal cloud: baris meledak
#   tanpa valuation / stok).
#
# Records wear the OSB- prefix; the Frappe test framework rolls each class
# back, so no operational document or setting is touched.

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, now, random_string

from erpnext.manufacturing.doctype.work_order.work_order import (
	make_stock_entry as make_wo_stock_entry,
)

from production_app.api.work_order import OUTLET_ITEM_GROUP

PREFIX = "OSB-"


def _root_group():
	return frappe.db.get_value("Item Group", {"is_group": 1}, "name", order_by="lft")


def _ensure_group(name, parent=None):
	if frappe.db.exists("Item Group", name):
		return name
	frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": name,
			"parent_item_group": parent or _root_group(),
		}
	).insert()
	return name


def _first_existing_wo_config():
	"""Read-only: reuse the company/warehouse an existing WO already uses."""
	name = frappe.db.get_value(
		"Work Order",
		{"docstatus": 1, "fg_warehouse": ("is", "set")},
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


def _company_warehouse(company, prefer=None):
	"""Warehouse non-grup milik company — `prefer` dipakai bila memang miliknya.

	WAJIB eksplisit di Item Default: situs ini punya default global
	`default_warehouse` (Stores - JURI, company PT. JURI) yang di-inject
	frappe ke baris Item Default kosong; bila company turunan berbeda
	(WO outlet DELANGGU), validasi link Item melempar
	"Stores - JURI doesn't belong to Company ...".
	"""
	if prefer and frappe.db.get_value("Warehouse", prefer, "company", cache=True) == company:
		return prefer
	name = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name", order_by="lft"
	)
	if not name:
		frappe.throw(f"No non-group Warehouse found for company {company}")
	return name


def _make_item(code, group, company, warehouse):
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"is_purchase_item": 0,
			"is_sales_item": 0,
			"standard_rate": 10,
			# Situs ini enable_item_wise_inventory_account=1 — tanpa baris ini
			# Stock Entry ditolak "Please set default inventory account".
			# default_warehouse eksplisit: default global situs (Stores - JURI)
			# akan di-inject ke baris kosong dan pecah bila company berbeda.
			"item_defaults": [
				{
					"company": company,
					"default_warehouse": warehouse,
					"default_inventory_account": frappe.db.get_value(
						"Company", company, "default_inventory_account"
					),
					"inventory_account_currency": frappe.db.get_value(
						"Company", company, "default_currency"
					),
				}
			],
		}
	)
	doc.insert()
	# Item doctype situs ini autoname lewat naming_series grup → doc.name bisa
	# berbeda dari item_code; semua pemanggil memakai doc.name.
	return doc.name


def _make_bom(item, company, rows):
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": item,
			"company": company,
			"currency": frappe.db.get_value("Company", company, "default_currency"),
			"quantity": 1,
			"items": rows,
		}
	)
	bom.insert()
	bom.submit()
	return bom.name


class TestOutletSingleLevelBom(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cfg = _first_existing_wo_config()
		cls.company = cfg.company
		cls.warehouse = _company_warehouse(cls.company, cfg.source_warehouse or cfg.fg_warehouse)
		suffix = random_string(6).upper()
		cls.plant_group = _ensure_group(f"{PREFIX}PLANT-GRP-{suffix}")
		_ensure_group(OUTLET_ITEM_GROUP)

		cls.raw = _make_item(f"{PREFIX}RAW-{suffix}", cls.plant_group, cls.company, cls.warehouse)
		cls.semi = _make_item(f"{PREFIX}SEMI-{suffix}", cls.plant_group, cls.company, cls.warehouse)
		cls.fg_out = _make_item(f"{PREFIX}FG-OUT-{suffix}", OUTLET_ITEM_GROUP, cls.company, cls.warehouse)
		cls.fg_plant = _make_item(f"{PREFIX}FG-PLANT-{suffix}", cls.plant_group, cls.company, cls.warehouse)

		# Resep berjenjang: RAW -> SEMI (child BOM), SEMI -> FG-OUT (sub-assembly).
		cls.semi_bom = _make_bom(cls.semi, cls.company, [{"item_code": cls.raw, "qty": 2, "rate": 10}])
		cls.out_bom = _make_bom(
			cls.fg_out,
			cls.company,
			[{"item_code": cls.semi, "qty": 1, "rate": 10, "bom_no": cls.semi_bom}],
		)
		cls.plant_bom = _make_bom(cls.fg_plant, cls.company, [{"item_code": cls.semi, "qty": 1, "rate": 10}])

	def _make_wo(self, item, bom, qty=3, pre_exploded=False):
		"""WO persis pola pemanggil lama: TIDAK menyentuh use_multi_level_bom.

		pre_exploded=True meniru Production Plan native: baris hasil ledakan
		sudah terpasang + flags.ignore_validate sebelum insert.
		"""
		wo = frappe.get_doc(
			{
				"doctype": "Work Order",
				"production_item": item,
				"bom_no": bom,
				"qty": qty,
				"company": self.company,
				"stock_uom": "Nos",
				"source_warehouse": self.warehouse,
				"fg_warehouse": self.warehouse,
				"skip_transfer": 1,
				"planned_start_date": now(),
				"transfer_material_against": "Work Order",
			}
		)
		if pre_exploded:
			wo.use_multi_level_bom = 1
			wo.append(
				"required_items",
				{"item_code": self.raw, "required_qty": 2, "source_warehouse": self.warehouse},
			)
			wo.flags.ignore_validate = True
			wo.flags.ignore_mandatory = True
		wo.insert()
		return wo

	def _row_codes(self, wo_name):
		return {
			r.item_code: flt(r.required_qty)
			for r in frappe.get_all(
				"Work Order Item", filters={"parent": wo_name}, fields=["item_code", "required_qty"]
			)
		}

	def test_pos_next_path_forced_single_level_and_rows_rebuilt(self):
		wo = self._make_wo(self.fg_out, self.out_bom)
		stored = frappe.get_doc("Work Order", wo.name)
		self.assertEqual(stored.use_multi_level_bom, 0)
		# Hanya baris sub-assembly (SEMI), bahan mentah pabrik (RAW) TIDAK ikut.
		self.assertEqual(self._row_codes(wo.name), {self.semi: 3.0})

	def test_plan_path_rebuilds_pre_exploded_rows(self):
		wo = self._make_wo(self.fg_out, self.out_bom, pre_exploded=True)
		stored = frappe.get_doc("Work Order", wo.name)
		self.assertEqual(stored.use_multi_level_bom, 0)
		self.assertEqual(self._row_codes(wo.name), {self.semi: 3.0})

	def test_factory_item_untouched(self):
		wo = self._make_wo(self.fg_plant, self.plant_bom)
		stored = frappe.get_doc("Work Order", wo.name)
		self.assertEqual(stored.use_multi_level_bom, 1)

	def test_manufacture_entry_consumes_single_level_only(self):
		# Stok SEMI di gudang tunggal (source==fg, pola outlet skip_transfer);
		# RAW sengaja 0 — kalau baris meledak lolos, submit manufacture gagal.
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"items": [
					{
						"item_code": self.semi,
						"qty": 30,
						"basic_rate": 10,
						"t_warehouse": self.warehouse,
						"use_serial_batch_fields": 0,
					}
				],
			}
		)
		se.insert()
		se.submit()

		wo = self._make_wo(self.fg_out, self.out_bom)
		wo.submit()
		self.assertEqual(frappe.db.get_value("Work Order", wo.name, "use_multi_level_bom"), 0)

		entry = frappe.get_doc(make_wo_stock_entry(wo.name, "Manufacture", qty=3))
		self.assertEqual(entry.use_multi_level_bom, 0)
		raw_rows = {
			r.item_code: flt(r.qty)
			for r in entry.items
			if r.s_warehouse and not r.is_finished_item
		}
		self.assertEqual(raw_rows, {self.semi: 3.0})  # RAW tidak pernah dikonsumsi
		entry.insert()
		entry.submit()

		stored = frappe.get_doc("Work Order", wo.name)
		self.assertEqual(stored.status, "Completed")
		self.assertEqual(flt(stored.produced_qty), 3.0)

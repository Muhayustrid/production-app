# FO Form Order suite (TASKS.md section I, 2026-09-18)
#
# Proves by execution on the installed runtime:
# - upgrade.apply() is idempotent for the FO steps and lands the FO permission
#   matrix: Manufacturing User creates MRs (Form Order), Manufacturing Manager
#   gets full MR rights, Gudang Barang Jadi can create/submit Stock Entry to
#   fulfill; the marker custom_is_form_order + 2 Pengaturan fields exist;
# - create_form_order validates BEFORE any write (qty, item stock non-batch,
#   missing Pengaturan route = clear error, zero MR rows written);
# - form_order_list scoping: gudang/manager see all, plain produksi only own;
# - cancel_form_order: owner/manager only, refused once an SE exists;
# - fulfill_form_order: gudang only, moves stock once (duplicate refused
#   through the locking SE re-check), status derives to terkirim;
# - free-form FO MRs never touch the Work Order handover mirror (doc_events
#   no-op, no Error Log entries).
#
# Test-only records carry the FO prefix; the Frappe test framework rolls each
# run back (class fixtures are purged in tearDownClass — apply() commits).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, now, random_string

from production_app import upgrade
from production_app.api import form_order
from production_app.api.handover import SYNC_ERROR_TITLE, _roles
from production_app.api.work_order import warehouse_defaults, warehouse_defaults_save

PREFIX = "FO"
ROLE_GUDANG = "Gudang Barang Jadi"


def _company_and_group():
	name = frappe.db.get_value("Work Order", {"docstatus": 1}, "name", order_by="creation desc")
	company = frappe.db.get_value("Work Order", name, "company")
	parent = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1}, "name")
	return company, parent


def _make_user(local, role=None):
	suffix = random_string(6).upper()
	user = (
		frappe.get_doc(
			{
				"doctype": "User",
				"email": f"fo.{local}.{suffix.lower()}@prodapp.example.com",
				"first_name": f"FO {local}",
				"send_welcome_email": 0,
			}
		)
		.insert()
	)
	if role:
		user.append("roles", {"role": role})
		user.save()
	return user.name


class TestFormOrder(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company, cls.parent_wh = _company_and_group()
		suffix = random_string(6).upper()

		def wh(label):
			return (
				frappe.get_doc(
					{
						"doctype": "Warehouse",
						"warehouse_name": f"{PREFIX} {label} {suffix}",
						"company": cls.company,
						"parent_warehouse": cls.parent_wh,
						"is_group": 0,
					}
				)
				.insert()
				.name
			)

		cls.src_wh = wh("Source")
		cls.dst_wh = wh("Target")

		def item(label, extra=None):
			return (
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": f"{PREFIX}-{label}-{suffix}",
						"item_name": f"{PREFIX} {label} {suffix}",
						"item_group": frappe.db.get_value("Item Group", {}, "name"),
						"stock_uom": frappe.db.get_value(
							"Work Order", {"docstatus": 1}, "stock_uom", order_by="creation desc"
						),
						"is_stock_item": 1,
						"is_purchase_item": 0,
						"is_sales_item": 0,
						"is_fixed_asset": 0,
						**(extra or {}),
					}
				)
				.insert()
				.name
			)

		cls.item = item("Item")
		cls.item_batch = item("Batch", {"has_batch_no": 1, "create_new_batch": 0})
		cls.item_service = item("Service", {"is_stock_item": 0})

	@classmethod
	def tearDownClass(cls):
		"""apply() commits mid-class (metadata) which persists the class
		fixtures past the framework rollback — purge them explicitly (they
		carry no ledger entries once the per-test receipts rolled back)."""
		frappe.db.rollback()
		frappe.set_user("Administrator")
		for doctype, field, pattern in (
			("Warehouse", "warehouse_name", f"{PREFIX} %"),
			("Item", "item_code", f"{PREFIX}-%"),
		):
			for name in frappe.get_all(doctype, filters={field: ("like", pattern)}, pluck="name"):
				frappe.delete_doc(doctype, name, force=True)
		frappe.db.commit()
		super().tearDownClass()

	# ------------------------------------------------------------- helpers

	def _set_route(self):
		"""Pengaturan route utk fixture warehouses (in-transaction, rolled back)."""
		frappe.set_user("Administrator")
		try:
			warehouse_defaults_save(
				form_order_source_warehouse=self.src_wh,
				form_order_target_warehouse=self.dst_wh,
			)
		finally:
			frappe.set_user("Administrator")

	def _fo_count(self):
		return frappe.db.count("Material Request", {"custom_is_form_order": 1})

	def _receipt(self, qty=20):
		uom = frappe.db.get_value("Item", self.item, "stock_uom")
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"items": [
					{
						"item_code": self.item,
						"qty": qty,
						"uom": uom,
						"stock_uom": uom,
						"conversion_factor": 1,
						"basic_rate": 10,
						"t_warehouse": self.src_wh,
					}
				],
			}
		)
		se.insert()
		se.submit()
		return se

	def _bin_qty(self, warehouse):
		return frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": warehouse}, "actual_qty") or 0

	# ------------------------------------------------------ idempotency

	def test_fo_apply_idempotent_and_matrix(self):
		r1 = upgrade.apply()
		r2 = upgrade.apply()
		for key in ("form_order_fields", "form_order_permissions"):
			entries = r2[key].values() if isinstance(r2[key], dict) else r2[key]
			self.assertTrue(
				all(entry.endswith(": unchanged") for entry in entries),
				f"{key} not idempotent: {r2[key]}",
			)
		self.assertTrue(frappe.get_meta("Material Request").has_field("custom_is_form_order"))
		for fieldname in (
			"custom_default_form_order_source_warehouse",
			"custom_default_form_order_target_warehouse",
		):
			self.assertTrue(frappe.get_meta("Manufacturing Settings").has_field(fieldname))

		def flags(doctype, role):
			name = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role}, "name")
			row = frappe.db.get_value(
				"Custom DocPerm", name,
				["read", "write", "create", "submit", "cancel", "amend"], as_dict=True,
			)
			return {k: int(row.get(k) or 0) for k in ("read", "write", "create", "submit", "cancel", "amend")}

		# FO raises Manufacturing User to the full MR lifecycle (Form Order)
		self.assertEqual(
			flags("Material Request", "Manufacturing User"),
			{"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 0},
		)
		self.assertEqual(flags("Material Request Item", "Manufacturing User")["create"], 1)
		# Manufacturing Manager: full MR (previously no row at all)
		self.assertEqual(
			flags("Material Request", "Manufacturing Manager"),
			{"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 0},
		)
		self.assertEqual(flags("Material Request Item", "Manufacturing Manager")["create"], 1)
		# Gudang Barang Jadi fulfills via Stock Entry create/submit (FO)
		self.assertEqual(
			flags("Stock Entry", ROLE_GUDANG),
			{"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 0},
		)
		self.assertTrue(frappe.get_meta("Material Request").get_field("custom_is_form_order").read_only)

	def test_fo_settings_roundtrip_and_role_flag(self):
		defaults = warehouse_defaults()
		self.assertIn("form_order_source_warehouse", defaults)
		self.assertIn("form_order_target_warehouse", defaults)

		frappe.set_user("Administrator")
		try:
			saved = warehouse_defaults_save(
				form_order_source_warehouse=self.src_wh,
				form_order_target_warehouse=self.dst_wh,
			)
			self.assertEqual(saved["form_order_source_warehouse"], self.src_wh)
			self.assertEqual(saved["form_order_target_warehouse"], self.dst_wh)
			self.assertEqual(
				frappe.db.get_single_value(
					"Manufacturing Settings", "custom_default_form_order_source_warehouse"
				),
				self.src_wh,
			)
		finally:
			frappe.set_user("Administrator")

		bare = _make_user("bare", "Manufacturing User")
		frappe.set_user(bare)
		try:
			self.assertFalse(_roles()["is_manajer_produksi"])  # flag baru: tidak melebar
			self.assertTrue(_roles()["is_produksi"])
			with self.assertRaises(frappe.PermissionError):
				warehouse_defaults_save(form_order_source_warehouse=self.src_wh)
		finally:
			frappe.set_user("Administrator")
		manager = _make_user("mgr", "Manufacturing Manager")
		frappe.set_user(manager)
		try:
			self.assertTrue(_roles()["is_manajer_produksi"])
			self.assertFalse(_roles()["is_produksi"])  # tidak otomatis produksi
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------- create: zero-write contract

	def test_fo_item_info(self):
		"""FO-8: info tampilan grid — nama/satuan/penanda; tanpa izin baca Item
		→ None (bukan error); item tak dikenal → None."""
		info = form_order.item_info(self.item)
		self.assertTrue(info.item_name.startswith("FO Item"))
		self.assertTrue(info.stock_uom)
		self.assertEqual(int(info.is_stock_item), 1)
		self.assertEqual(int(info.has_batch_no), 0)
		self.assertEqual(int(form_order.item_info(self.item_batch).has_batch_no), 1)
		self.assertIsNone(form_order.item_info("TIDAK-ADA-ITEM"))

		bare = _make_user("bareinfo")
		frappe.set_user(bare)
		try:
			self.assertIsNone(form_order.item_info(self.item))  # tanpa Item read
		finally:
			frappe.set_user("Administrator")

	def test_fo_create_validations_write_nothing(self):
		self._set_route()
		prod = _make_user("prod", "Manufacturing User")
		frappe.set_user(prod)
		try:
			before = self._fo_count()

			def expect_throw(**kwargs):
				with self.assertRaises(frappe.ValidationError):
					form_order.create_form_order(**kwargs)
				self.assertEqual(self._fo_count(), before)  # zero-write

			expect_throw(items=[])  # minimal satu baris
			expect_throw(items=[{"item_code": self.item, "qty": 0}])
			expect_throw(items=[{"item_code": self.item, "qty": -5}])
			expect_throw(items=[{"item_code": self.item, "qty": "abc"}])
			expect_throw(items=[{"item_code": "TIDAK-ADA", "qty": 1}])
			expect_throw(items=[{"item_code": self.item_service, "qty": 1}])  # bukan item stok
			expect_throw(items=[{"item_code": self.item_batch, "qty": 1}])  # ber-batch v1
			expect_throw(items=[{"item_code": self.item, "qty": 1}], schedule_date="bukan-tanggal")

			# rute Pengaturan kosong = error jelas, tetap zero-write
			frappe.db.set_single_value(
				"Manufacturing Settings", "custom_default_form_order_source_warehouse", None
			)
			with self.assertRaises(frappe.ValidationError):
				form_order.create_form_order(items=[{"item_code": self.item, "qty": 1}])
			self.assertEqual(self._fo_count(), before)
		finally:
			frappe.set_user("Administrator")

	def test_fo_gudang_cannot_create_produksi_cannot_fulfill(self):
		self._set_route()
		gudang = _make_user("gd", ROLE_GUDANG)
		frappe.set_user(gudang)
		try:
			with self.assertRaises(frappe.PermissionError):
				form_order.create_form_order(items=[{"item_code": self.item, "qty": 1}])
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------- create + list scope + sync no-op

	def test_fo_create_list_scope_and_mirror_noop(self):
		self._set_route()
		prod = _make_user("prod", "Manufacturing User")
		prod2 = _make_user("prod2", "Manufacturing User")
		manager = _make_user("mgr", "Manufacturing Manager")
		gudang = _make_user("gd", ROLE_GUDANG)

		err_before = frappe.db.count("Error Log", {"method": SYNC_ERROR_TITLE})
		frappe.set_user(prod)
		try:
			res = form_order.create_form_order(
				items=[{"item_code": self.item, "qty": 12}], note="  uji FO  "
			)
			mr_name = res["material_request"]
		finally:
			frappe.set_user("Administrator")

		mr = frappe.get_doc("Material Request", mr_name)
		self.assertEqual(mr.docstatus, 1)
		self.assertEqual(mr.material_request_type, "Material Transfer")
		self.assertEqual(mr.custom_is_form_order, 1)
		self.assertEqual(mr.custom_note, "uji FO")
		self.assertEqual(mr.set_from_warehouse, self.src_wh)
		self.assertEqual(mr.set_warehouse, self.dst_wh)
		# default besok (log_error-style: seluruh class SATU transaksi — jangan
		# andalkan tanggal bergeser antar test)
		self.assertEqual(str(mr.schedule_date), str(getdate(add_days(now(), 1))))
		for row in mr.items:  # free-form: TIDAK pernah terikat Work Order
			self.assertFalse(row.custom_work_order)
		self.assertIn(mr.company, (self.company,))  # company dari warehouse asal

		def list_as(user):
			frappe.set_user(user)
			try:
				return form_order.form_order_list()["orders"]
			finally:
				frappe.set_user("Administrator")

		for user in (prod, manager, gudang):
			rows = list_as(user)
			hit = [o for o in rows if o["mr"] == mr_name]
			self.assertEqual(len(hit), 1, f"{user} harus melihat {mr_name}")
			self.assertEqual(hit[0]["status"], "menunggu")
		self.assertNotIn(mr_name, [o["mr"] for o in list_as(prod2)])  # produksi lain: hanya miliknya

		# mirror serah terima tidak tersentuh MR free-form (doc_events no-op)
		self.assertEqual(frappe.db.count("Error Log", {"method": SYNC_ERROR_TITLE}), err_before)

		# pembuat membatalkan request yang belum diproses
		frappe.set_user(prod)
		try:
			form_order.cancel_form_order(mr_name)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Material Request", mr_name, "docstatus"), 2)
		rows = list_as(prod)
		self.assertEqual([o["status"] for o in rows if o["mr"] == mr_name], ["batal"])
		self.assertEqual(frappe.db.count("Error Log", {"method": SYNC_ERROR_TITLE}), err_before)

	def test_fo_cancel_guards_owner_and_processed(self):
		self._set_route()
		prod = _make_user("prod", "Manufacturing User")
		prod2 = _make_user("prod2", "Manufacturing User")
		manager = _make_user("mgr", "Manufacturing Manager")

		frappe.set_user(prod)
		try:
			mr_name = form_order.create_form_order(
				items=[{"item_code": self.item, "qty": 3}]
			)["material_request"]
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(prod2)  # produksi lain: tolak (bukan owner, bukan manager)
		try:
			with self.assertRaises(frappe.PermissionError):
				form_order.cancel_form_order(mr_name)
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(manager)  # manager boleh
		try:
			form_order.cancel_form_order(mr_name)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Material Request", mr_name, "docstatus"), 2)

		# sudah diproses (ada SE) → tolak walau owner
		frappe.set_user(prod)
		try:
			mr_name = form_order.create_form_order(
				items=[{"item_code": self.item, "qty": 2}]
			)["material_request"]
		finally:
			frappe.set_user("Administrator")
		self._receipt(qty=5)
		gudang = _make_user("gd", ROLE_GUDANG)
		frappe.set_user(gudang)
		try:
			form_order.fulfill_form_order(mr_name)
		finally:
			frappe.set_user("Administrator")
		frappe.set_user(prod)
		try:
			with self.assertRaises(frappe.ValidationError):
				form_order.cancel_form_order(mr_name)
		finally:
			frappe.set_user("Administrator")

	def test_fo_fulfill_moves_stock_once(self):
		self._set_route()
		prod = _make_user("prod", "Manufacturing User")
		gudang = _make_user("gd", ROLE_GUDANG)

		# seluruh class berbagi SATU transaksi (pola suite handover) — bin
		# ditegaskan DELTA terhadap kondisi awal test ini, bukan nilai absolut
		src_before = self._bin_qty(self.src_wh)
		dst_before = self._bin_qty(self.dst_wh)
		self._receipt(qty=20)
		frappe.set_user(prod)
		try:
			mr_name = form_order.create_form_order(
				items=[{"item_code": self.item, "qty": 15}], schedule_date="2026-10-01"
			)["material_request"]
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(prod)  # produksi tidak bisa memproses sendiri
		try:
			with self.assertRaises(frappe.PermissionError):
				form_order.fulfill_form_order(mr_name)
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(gudang)
		try:
			res = form_order.fulfill_form_order(mr_name)
			se_name = res["stock_entry"]
			# anti-dobel: SE yang sudah ada (recheck di bawah lock) menolak ulang
			with self.assertRaises(frappe.ValidationError):
				form_order.fulfill_form_order(mr_name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Stock Entry", se_name, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", se_name, "stock_entry_type"), "Material Transfer")
		self.assertEqual(self._bin_qty(self.src_wh) - src_before, 5)  # 20 - 15
		self.assertEqual(self._bin_qty(self.dst_wh) - dst_before, 15)

		frappe.set_user(prod)
		try:
			rows = form_order.form_order_list()["orders"]
		finally:
			frappe.set_user("Administrator")
		hit = [o for o in rows if o["mr"] == mr_name]
		self.assertEqual(hit[0]["status"], "terkirim")
		self.assertEqual(hit[0]["stock_entry"], se_name)
		self.assertTrue(hit[0]["sent_at"])

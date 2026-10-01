# FU72 dashboard "Hari Ini" — agregat read-only + param `company` di wo_list.
#
# Membuktikan dengan eksekusi pada runtime terpasang:
# - wo_list(company=...) memfilter per company (kode lama: TypeError — bukti
#   merah asli bagian ini);
# - dashboard_summary: bentuk kontrak lengkap, hari kosong company fixture =
#   semua nol, konversi Default Inventory UOM server-side (faktor 12 → 1000
#   Pcs = 83,33 Pack), fallback stock UOM saat field default kosong, UOM beda
#   TIDAK pernah dijumlahkan, Item master terhapus hanya men-skip baris itu
#   (pola FU65), User Permission Company membatasi cakupan user, hitungan
#   stage per derive_stage (draft → persiapan; aktif → lajur papan; selesai
#   hari ini → selesai_hari_ini; selesai kemarin → TIDAK masuk papan), dan
#   handover_menunggu / form_order_menunggu dari MR nyata + filter company.
#
# FU73 menambah dua kunci: product_yield (agregat hasil post-packing per
# produk, konversi satuan display) dan attention (baris mentah per kind —
# reject_over/stagnant/handover_request/form_order/suhu/stopped — dirangkai
# judulnya oleh frontend).
#
# Semua record test berprefix FU72; framework test me-rollback tiap run
# (tanpa commit — tearDownClass hanya sapu defensif ala test_form_order).

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, now, now_datetime, random_string, today

from erpnext.manufacturing.doctype.work_order.work_order import (
	make_stock_entry as make_wo_stock_entry,
)
from erpnext.stock.doctype.material_request.material_request import (
	make_stock_entry as make_mr_stock_entry,
)

from production_app.api.work_order import (
	STAGE_FINISH,
	STAGE_MATERIAL,
	STAGE_OPERASI,
	STAGE_POST_PACKING,
	STAGE_PREPACKING,
	STAGE_PERSIAPAN,
	wo_list,
)

PREFIX = "FU72"
STAGE_SELESAI_HARI_INI = "selesai_hari_ini"

SHAPE_KEYS = {
	"today",
	"companies",
	"wo_planned_today",
	"output_today",
	"adonan_terakhir",
	"stages",
	"handover_menunggu",
	"form_order_menunggu",
	"product_yield",
	"attention",
}
STAGE_KEYS = {
	STAGE_PERSIAPAN,
	STAGE_MATERIAL,
	STAGE_OPERASI,
	STAGE_PREPACKING,
	STAGE_POST_PACKING,
	STAGE_FINISH,
	STAGE_SELESAI_HARI_INI,
}


def _summary(company=None):
	"""Import lambat supaya RED terukur per-kasus (modul belum ada → ImportError),
	bukan satu ImportError di level file yang menelan bukti TypeError wo_list."""
	from production_app.api.dashboard import dashboard_summary

	return dashboard_summary(company=company)


def _uom_qty(summary, uom):
	"""Qty hasil hari ini untuk satu UOM (None bila tidak ada entri)."""
	return next((e["qty"] for e in summary["output_today"] if e["uom"] == uom), None)


def _yield_row(rows, item_code):
	"""Baris product_yield satu produk dari daftar baris (None bila kosong)."""
	return next((r for r in rows if r["item_code"] == item_code), None)


def _yield_base(rows, item_code):
	"""Nilai dasar yield satu produk sebelum penambahan uji (0 bila belum ada
	barisnya) — runner frappe v16 TIDAK rollback antar test method (rollback
	hanya setelah seluruh class), jadi asersi yield memakai delta, pola yang
	sama dengan test_03-test_09."""
	row = _yield_row(rows, item_code) or {}
	return {k: flt(row.get(k)) for k in ("planned", "good", "reject", "trial", "sisa")}


def _attention_kinds(summary, kind):
	"""Semua baris attention satu kind."""
	return [e for e in summary["attention"] if e["kind"] == kind]


class TestDashboard(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.suffix = random_string(6).upper()
		cls.company_a = frappe.db.get_value("Company", {}, "name")
		cls.uom_base = frappe.db.get_value("Work Order", {"docstatus": 1}, "stock_uom") or "Nos"
		country = frappe.db.get_value("Company", cls.company_a, "country")
		currency = frappe.db.get_value("Company", cls.company_a, "default_currency")

		# ---- company fixture B (ringan: tanpa chart of accounts, tanpa perpetual)
		frappe.local.flags.ignore_chart_of_accounts = True
		try:
			cls.company_b = (
				frappe.get_doc(
					{
						"doctype": "Company",
						"company_name": f"{PREFIX} Company {cls.suffix}",
						"abbr": cls.suffix[:4],
						"country": country,
						"default_currency": currency,
						"enable_perpetual_inventory": 0,
					}
				)
				.insert()
				.name
			)
		finally:
			frappe.local.flags.ignore_chart_of_accounts = False

		def warehouse(company, parent, name, group=False):
			return (
				frappe.get_doc(
					{
						"doctype": "Warehouse",
						"warehouse_name": f"{PREFIX} {name} {cls.suffix}",
						"company": company,
						"parent_warehouse": parent,
						"is_group": 1 if group else 0,
					}
				)
				.insert()
				.name
			)

		parent_a = frappe.db.get_value(
			"Warehouse", {"company": cls.company_a, "is_group": 1}, "name"
		)
		cls.src_wh = warehouse(cls.company_a, parent_a, "Source")
		cls.wip_wh = warehouse(cls.company_a, parent_a, "WIP")
		cls.fg_wh = warehouse(cls.company_a, parent_a, "FG")
		root_b = warehouse(cls.company_b, None, "B Root", group=True)
		cls.b_src_wh = warehouse(cls.company_b, root_b, "B Source")
		cls.b_wip_wh = warehouse(cls.company_b, root_b, "B WIP")
		cls.b_fg_wh = warehouse(cls.company_b, root_b, "B FG")

		# ---- UOM fixture (nama unik per run; UOM "Pack" global TIDAK diasumsikan)
		def uom(name):
			return (
				frappe.get_doc({"doctype": "UOM", "uom_name": f"{PREFIX} {name} {cls.suffix}"})
				.insert()
				.name
			)

		cls.uom_pack = uom("Pack")
		cls.uom_yest = uom("UYest")
		cls.uom_del = uom("UDel")

		# ---- item + BOM
		cls.rm = cls._make_item("RM", cls.uom_base)

		def item_with_uom(label, stock_uom, display_uom=None, factor=None):
			code = cls._make_item(label, stock_uom)
			if display_uom:
				item = frappe.get_cached_doc("Item", code)
				item.custom_default_inventory_unit_of_measure = display_uom
				if factor:
					item.append("uoms", {"uom": display_uom, "conversion_factor": factor})
				item.save()
			return code

		# produk utama: Default Inventory UOM faktor 12 (kontrak contoh 1000 Pcs)
		cls.fg_pack = item_with_uom("FGPack", cls.uom_base, cls.uom_pack, 12)
		# produk tanpa field default → fallback stock UOM
		cls.fg_plain = cls._make_item("FGPlain", cls.uom_base)
		# produk untuk WO selesai KEMARIN (UOM unik: kehadirannya terbaca jelas)
		cls.fg_yest = item_with_uom("FGYest", cls.uom_base, cls.uom_yest, 5)
		# produk yang master-nya "terhapus" dari SE (pola FU65: rewrite item_code)
		cls.fg_del = item_with_uom("FGDel", cls.uom_base, cls.uom_del, 3)

		cls.bom_pack = cls._make_bom(cls.fg_pack)
		cls.bom_plain = cls._make_bom(cls.fg_plain)
		cls.bom_yest = cls._make_bom(cls.fg_yest)
		cls.bom_del = cls._make_bom(cls.fg_del)
		cls.bom_plain_b = cls._make_bom(cls.fg_plain, company=cls.company_b)

		# persediaan RM untuk seluruh run
		cls._receipt(cls.rm, 6000, cls.src_wh)

		# ---- WO company B: submit lalu cancel — tampil di wo_list(company=B),
		# tidak pernah masuk papan stage (docstatus 2) → company B tetap "kosong"
		cls.wo_b = cls._make_wo(
			cls.bom_plain_b,
			5,
			cls.fg_plain,
			company=cls.company_b,
			wip_wh=cls.b_wip_wh,
			fg_wh=cls.b_fg_wh,
			src_wh=cls.b_src_wh,
		)
		cls.wo_b.submit()
		cls.wo_b.cancel()

		# ---- user dengan User Permission Company=B (persona multi-company FU66)
		cls.user_email = f"fu72.up.{cls.suffix.lower()}@prodapp.example.com"
		cls.user_up = (
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.user_email,
					"first_name": f"FU72 UP {cls.suffix}",
					"send_welcome_email": 0,
				}
			)
			.insert()
			.name
		)
		user = frappe.get_doc("User", cls.user_up)
		for role in ("Manufacturing User", "Accounts User"):
			user.append("roles", {"role": role})
		user.save()
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": cls.user_up,
				"allow": "Company",
				"for_value": cls.company_b,
			}
		).insert()

		# ---- user produksi biasa (Manufacturing User, TANPA User Permission)
		# persona scope owner Form Order (FU73): bukan gudang, bukan manajer
		cls.user_prod = (
			frappe.get_doc(
				{
					"doctype": "User",
					"email": f"fu72.prod.{cls.suffix.lower()}@prodapp.example.com",
					"first_name": f"FU72 PROD {cls.suffix}",
					"send_welcome_email": 0,
				}
			)
			.insert()
			.name
		)
		user_prod = frappe.get_doc("User", cls.user_prod)
		user_prod.append("roles", {"role": "Manufacturing User"})
		user_prod.save()

	@classmethod
	def tearDownClass(cls):
		"""Sapu defensif EXACT-NAME (semua doc sebenarnya ikut rollback
		framework; pola ini hanya menjebak commit liar masa depan — pattern
		LIKE sengaja dihindari agar tidak menyentuh data committed lain)."""
		frappe.db.rollback()
		frappe.set_user("Administrator")
		items = (cls.rm, cls.fg_pack, cls.fg_plain, cls.fg_yest, cls.fg_del)
		uoms = (cls.uom_pack, cls.uom_yest, cls.uom_del)
		warehouses = (cls.src_wh, cls.wip_wh, cls.fg_wh, cls.b_src_wh, cls.b_wip_wh, cls.b_fg_wh)
		for doctype, field, names in (
			("User Permission", "user", [cls.user_up]),
			("User", "name", [cls.user_up, cls.user_prod]),
			("Item", "name", items),
			("Warehouse", "name", warehouses),
			("Company", "name", [cls.company_b]),
			("UOM", "name", uoms),
		):
			for name in names:
				if name and frappe.db.exists(doctype, name):
					frappe.delete_doc(doctype, name, force=True)
		frappe.db.commit()
		super().tearDownClass()

	# ------------------------------------------------------------- fixtures

	@staticmethod
	def _pin_posting(se, posting_date, posting_time):
		"""Urutan posting dibuat deterministik: receipt kemarin 07:00 <
		transfer 09:00 < manufacture 10:00 (pola pinning T23)."""
		se.set_posting_time = 1
		se.posting_date = posting_date
		se.posting_time = posting_time

	@classmethod
	def _make_item(cls, label, stock_uom):
		return (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"{PREFIX}-{label}-{cls.suffix}",
					"item_name": f"{PREFIX} {label} {cls.suffix}",
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": stock_uom,
					"is_stock_item": 1,
					"is_purchase_item": 0,
					"is_sales_item": 0,
					"has_batch_no": 0,
					"is_fixed_asset": 0,
					"standard_rate": 10,
				}
			)
			.insert()
			.name
		)

	@classmethod
	def _make_bom(cls, fg_item, company=None):
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": fg_item,
				"company": company or cls.company_a,
				"currency": frappe.db.get_value("Company", company or cls.company_a, "default_currency"),
				"quantity": 1,
				"items": [
					{
						"item_code": cls.rm,
						"qty": 1,
						"rate": 10,
						"uom": cls.uom_base,
						"stock_uom": cls.uom_base,
					}
				],
			}
		)
		bom.insert()
		bom.submit()
		return bom.name

	@classmethod
	def _receipt(cls, item, qty, warehouse_):
		# posting KEMARIN 07:00 supaya transfer/produksi backdated WO kemarin
		# lolos cek stok; Material Receipt tidak menyentuh metrik dashboard
		# (hanya purpose Manufacture yang dihitung)
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": cls.company_a,
				"items": [
					{
						"item_code": item,
						"qty": qty,
						"basic_rate": 10,
						"t_warehouse": warehouse_,
						"uom": cls.uom_base,
						"stock_uom": cls.uom_base,
					}
				],
			}
		)
		cls._pin_posting(se, add_days(today(), -1), "07:00:00")
		se.insert()
		se.submit()
		return se

	@classmethod
	def _make_wo(
		cls, bom, qty, item, adonan=None, planned=None, company=None, wip_wh=None, fg_wh=None, src_wh=None
	):
		wo = frappe.get_doc(
			{
				"doctype": "Work Order",
				"production_item": item,
				"bom_no": bom,
				"qty": qty,
				"company": company or cls.company_a,
				"fg_warehouse": fg_wh or cls.fg_wh,
				"wip_warehouse": wip_wh or cls.wip_wh,
				"source_warehouse": src_wh or cls.src_wh,
				"scrap_warehouse": fg_wh or cls.fg_wh,
				"stock_uom": cls.uom_base,
				"planned_start_date": planned or now(),
				"transfer_material_against": "Work Order",
				"use_multi_level_bom": 0,
				**({"custom_adonan_ke": adonan} if adonan else {}),
			}
		)
		wo.get_items_and_operations_from_bom()
		wo.insert()
		return wo

	@classmethod
	def _transfer(cls, wo, posting_date=None):
		se = frappe.get_doc(make_wo_stock_entry(wo.name, "Material Transfer for Manufacture"))
		cls._pin_posting(se, posting_date or today(), "09:00:00")
		se.insert()
		se.submit()
		return se

	@classmethod
	def _manufacture(cls, wo, good, posting_date=None):
		"""Submit Manufacture hari `posting_date` (default hari ini); baris bahan
		mengikuti rencana transfer (aturan konsumsi workspace, pola finish/T23)."""
		se = frappe.get_doc(make_wo_stock_entry(wo.name, "Manufacture", qty=good))
		cls._pin_posting(se, posting_date or today(), "10:00:00")
		transferred = frappe._dict()
		for r in frappe.get_all(
			"Stock Entry Detail",
			filters={
				"parent": ("in", frappe.get_all(
					"Stock Entry",
					filters={
						"work_order": wo.name,
						"purpose": "Material Transfer for Manufacture",
						"docstatus": 1,
					},
					pluck="name",
				)),
				"docstatus": 1,
			},
			fields=["item_code", "transfer_qty"],
		):
			transferred[r.item_code] = transferred.get(r.item_code, 0.0) + flt(r.transfer_qty)
		for row in se.items:
			if not row.is_finished_item and row.item_code in transferred:
				row.qty = transferred[row.item_code]
				row.transfer_qty = row.qty * flt(row.conversion_factor or 1)
		se.insert()
		se.submit()
		return se

	@classmethod
	def _confirm_postpacking(cls, wo, good=0.0, reject=0.0, trial=0.0, sisa=0.0):
		"""Tandai post-packing terkonfirmasi langsung di DB — dokumen audit
		konfirmasi T27 diuji di modulnya; dashboard cukup membaca state."""
		wo.db_set(
			{
				"custom_good_qty_postpacking": good,
				"custom_reject_qty_postpacking": reject,
				"custom_trial_qty_postpacking": trial,
				"custom_sisa_qty_postpacking": sisa,
				"custom_postpacking_confirmed": 1,
			}
		)
		return wo

	@classmethod
	def _make_mr(cls, wo, form_order=False):
		"""MR Material Transfer nyata: serah terima (row.custom_work_order) atau
		Form Order (custom_is_form_order) — bentuk fixture T23/test_form_order."""
		row = {
			"item_code": cls.fg_plain,
			"qty": 5,
			"uom": cls.uom_base,
			"stock_uom": cls.uom_base,
			"conversion_factor": 1,
			"from_warehouse": cls.src_wh,
			"warehouse": cls.fg_wh,
			"schedule_date": add_days(now(), 1),
		}
		doc = {
			"doctype": "Material Request",
			"material_request_type": "Material Transfer",
			"company": cls.company_a,
			"transaction_date": now(),
			"schedule_date": add_days(now(), 1),
			"set_from_warehouse": cls.src_wh,
			"set_warehouse": cls.fg_wh,
			"items": [row],
		}
		if form_order:
			doc["custom_is_form_order"] = 1
		else:
			row["custom_work_order"] = wo.name
		mr = frappe.get_doc(doc)
		mr.insert()
		mr.submit()
		return mr

	# ------------------------------------------------------------ helper asersi

	def _assert_full_shape(self, summary):
		self.assertEqual(set(summary.keys()), SHAPE_KEYS)
		self.assertEqual(set(summary["stages"].keys()), STAGE_KEYS)
		self.assertEqual(summary["today"], today())
		self.assertIsInstance(summary["output_today"], list)

	# ----------------------------------------------- 1. param company di wo_list

	def test_01_wo_list_company_param(self):
		"""wo_list(company=...) hanya memuat WO company itu; tanpa param semua
		terlihat. Lawan kode lama: TypeError unexpected keyword 'company'."""
		rows_b = wo_list(company=self.company_b, page_len=2500)
		self.assertEqual([r.name for r in rows_b], [self.wo_b.name])
		rows_a = wo_list(company=self.company_a, page_len=2500)
		self.assertNotIn(self.wo_b.name, [r.name for r in rows_a])
		all_rows = wo_list(page_len=2500)
		self.assertIn(self.wo_b.name, [r.name for r in all_rows])

	# ------------------------------------- 2. hari kosong company fixture: nol

	def test_02_hari_kosong_semua_nol(self):
		"""Company fixture tanpa dokumen hidup → seluruh angka nol + bentuk
		kontrak lengkap (endpoint tetap 200-shape di hari sepi)."""
		s = _summary(company=self.company_b)
		self._assert_full_shape(s)
		self.assertIn(self.company_b, s["companies"])
		self.assertEqual(s["wo_planned_today"], 0)
		self.assertEqual(s["output_today"], [])
		self.assertEqual(s["adonan_terakhir"], 0)
		self.assertEqual(s["handover_menunggu"], 0)
		self.assertEqual(s["form_order_menunggu"], 0)
		self.assertEqual(s["product_yield"], [])
		self.assertEqual(s["attention"], [])
		for key in STAGE_KEYS:
			self.assertEqual(s["stages"][key], 0, key)

	# ------------------------------------- 3. konversi Default Inventory UOM

	def test_03_output_pack_faktor_12(self):
		"""1000 Pcs (faktor 12) hari ini → satu entri Pack 83,33 (server-side
		konversi, float mentah — frontend yang format)."""
		before = _uom_qty(_summary(company=self.company_a), self.uom_pack) or 0.0
		wo = self._make_wo(self.bom_pack, 1000, self.fg_pack, adonan=1)
		wo.submit()
		self._transfer(wo)
		self._manufacture(wo, 1000)
		after = _summary(company=self.company_a)
		qty = _uom_qty(after, self.uom_pack)
		self.assertIsNotNone(qty)
		self.assertAlmostEqual(qty, before + 1000 / 12, places=6)

	# ------------------------------------- 4. fallback stock UOM

	def test_04_output_fallback_stock_uom(self):
		"""Produk TANPA field Default Inventory UOM → entri dalam stock UOM,
		qty apa adanya (tidak dikonversi, tidak di-skip)."""
		before = _uom_qty(_summary(company=self.company_a), self.uom_base) or 0.0
		wo = self._make_wo(self.bom_plain, 250, self.fg_plain)
		wo.submit()
		self._transfer(wo)
		self._manufacture(wo, 250)
		after = _summary(company=self.company_a)
		qty = _uom_qty(after, self.uom_base)
		self.assertIsNotNone(qty)
		self.assertAlmostEqual(qty, before + 250, places=6)

	# ------------------------------------- 5. UOM beda tidak pernah dijumlahkan

	def test_05_output_uom_terpisah(self):
		"""Dua produk beda satuan tampil → dua entri terpisah (tidak digabung
		menjadi satu baris UOM pertama)."""
		before_pack = _uom_qty(_summary(company=self.company_a), self.uom_pack) or 0.0
		before_base = _uom_qty(_summary(company=self.company_a), self.uom_base) or 0.0
		wo1 = self._make_wo(self.bom_pack, 120, self.fg_pack)
		wo1.submit()
		self._transfer(wo1)
		self._manufacture(wo1, 120)
		wo2 = self._make_wo(self.bom_plain, 60, self.fg_plain)
		wo2.submit()
		self._transfer(wo2)
		self._manufacture(wo2, 60)
		after = _summary(company=self.company_a)
		pack = _uom_qty(after, self.uom_pack)
		base = _uom_qty(after, self.uom_base)
		self.assertIsNotNone(pack)
		self.assertIsNotNone(base)
		self.assertAlmostEqual(pack, before_pack + 10, places=6)  # 120/12
		self.assertAlmostEqual(base, before_base + 60, places=6)

	# ------------------------------------- 6. Item master terhapus: skip per baris

	def test_06_item_master_terhapus_skip(self):
		"""SE memegang item_code yang master-nya sudah tidak ada → baris itu di-
		skip dari total (tanpa konversi karangan), endpoint tetap hidup penuh
		bentuknya (pola FU65)."""
		wo = self._make_wo(self.bom_del, 90, self.fg_del)
		wo.submit()
		self._transfer(wo)
		self._manufacture(wo, 90)
		before = _summary(company=self.company_a)
		self.assertAlmostEqual(_uom_qty(before, self.uom_del) or 0, 30, places=6)  # 90/3
		# simulate admin deletion tanpa cascade teardown (pola FU65):
		# rewrite referensi item_code di baris SE jadi kode yang tak pernah ada
		for name in frappe.get_all(
			"Stock Entry Detail", filters={"item_code": self.fg_del}, pluck="name"
		):
			frappe.db.set_value("Stock Entry Detail", name, "item_code", f"{PREFIX}-DELETED-{self.suffix}")
		after = _summary(company=self.company_a)
		self._assert_full_shape(after)
		self.assertIsNone(_uom_qty(after, self.uom_del))

	# ------------------------------------- 7. User Permission company

	def test_07_user_permission_company(self):
		"""User ber-UP Company=B hanya melihat/menghitung company-nya; filter
		eksplisit tetap bekerja dalam batas UP (A tetap tersembunyi), admin
		dengan company=A melihat angka A."""
		try:
			frappe.set_user(self.user_up)
			s = _summary()
			self.assertEqual(s["companies"], [self.company_b])
			self.assertEqual(s["wo_planned_today"], 0)
			self.assertEqual(s["output_today"], [])
			for key in STAGE_KEYS:
				self.assertEqual(s["stages"][key], 0, key)
			# UP ∩ filter eksplisit: A tersembunyi meski dipaksa, B tetap 0-shape
			self.assertEqual(_summary(company=self.company_a)["wo_planned_today"], 0)
			self.assertEqual(_summary(company=self.company_b)["wo_planned_today"], 0)
			# param company juga bekerja di wo_list untuk user yang sama
			rows_b = wo_list(company=self.company_b, page_len=2500)
			self.assertEqual([r.name for r in rows_b], [self.wo_b.name])
		finally:
			frappe.set_user("Administrator")
		# admin: filter eksplisit company A memuat hasil fixture (WO plan hari ini)
		admin_a = _summary(company=self.company_a)
		self.assertGreater(admin_a["wo_planned_today"], 0)

	# ------------------------------------- 8. hitungan stage per derive_stage

	def test_08_stages_papan(self):
		"""Papan hari ini: draft → persiapan; submitted aktif → material; selesai
		hari ini (Manufacture SE hari ini) → selesai_hari_ini; selesai kemarin
		TIDAK masuk papan; adonan_terakhir = max adonan WO today."""
		before = _summary(company=self.company_a)["stages"]

		wo_draft = self._make_wo(self.bom_plain, 40, self.fg_plain, adonan=7)
		after_draft = _summary(company=self.company_a)
		self.assertEqual(after_draft["stages"][STAGE_PERSIAPAN], before[STAGE_PERSIAPAN] + 1)
		self.assertEqual(after_draft["adonan_terakhir"], 7)

		wo_mat = self._make_wo(self.bom_plain, 41, self.fg_plain)
		wo_mat.submit()
		after_mat = _summary(company=self.company_a)
		self.assertEqual(after_mat["stages"][STAGE_MATERIAL], before[STAGE_MATERIAL] + 1)

		wo_done = self._make_wo(self.bom_pack, 200, self.fg_pack, adonan=2)
		wo_done.submit()
		self._transfer(wo_done)
		self._manufacture(wo_done, 200)
		after_done = _summary(company=self.company_a)
		self.assertEqual(
			after_done["stages"][STAGE_SELESAI_HARI_INI], before[STAGE_SELESAI_HARI_INI] + 1
		)
		self.assertEqual(after_done["stages"][STAGE_MATERIAL], before[STAGE_MATERIAL] + 1)  # wo_mat

		# selesai KEMARIN: SE Manufacture posting kemarin → tidak menaikkan apa pun
		yesterday = add_days(today(), -1)
		wo_yest = self._make_wo(
			self.bom_yest, 100, self.fg_yest, planned=f"{yesterday} 08:00:00"
		)
		wo_yest.submit()
		self._transfer(wo_yest, posting_date=yesterday)
		self._manufacture(wo_yest, 100, posting_date=yesterday)
		after_yest = _summary(company=self.company_a)
		for key in STAGE_KEYS:
			self.assertEqual(after_yest["stages"][key], after_done["stages"][key], key)
		self.assertEqual(after_yest["adonan_terakhir"], 7)  # wo_yest bukan WO today

		# rencana hari ini bertambah: draft + mat + done (bukan wo_yest)
		self.assertEqual(after_yest["wo_planned_today"], after_done["wo_planned_today"])

	# ------------------------------------- 9. handover & form order menunggu

	def test_09_handover_form_order_menunggu(self):
		"""handover_menunggu = MR Material Transfer terikat WO (docstatus 1, bukan
		Stopped, tanpa SE); form_order_menunggu = MR custom_is_form_order
		submitted tanpa SE; keduanya mengikuti filter company."""
		wo = self._make_wo(self.bom_plain, 42, self.fg_plain)
		wo.submit()
		before = _summary(company=self.company_a)

		self._make_mr(wo)  # MR serah terima nyata (lane request)
		self._make_mr(wo, form_order=True)  # MR Form Order nyata
		after = _summary(company=self.company_a)
		self.assertEqual(after["handover_menunggu"], before["handover_menunggu"] + 1)
		self.assertEqual(after["form_order_menunggu"], before["form_order_menunggu"] + 1)
		# filter company: company B tidak menghitung MR company A
		self.assertEqual(_summary(company=self.company_b)["handover_menunggu"], 0)
		self.assertEqual(_summary(company=self.company_b)["form_order_menunggu"], 0)

	# ------------------------------------ FU73: product_yield per produk
	# Runner frappe v16 TIDAK rollback antar test method (hanya setelah
	# seluruh class) — semua asersi FU73 delta (snapshot before → after),
	# disiplin yang sama dengan test lama.

	def test_10_yield_dasar_per_produk(self):
		"""WO post-packing terkonfirmasi → baris produk: planned/good/reject/
		trial/sisa mentah (frontend memformat), yield_pct & reject_pct persen,
		over mengikuti ambang."""
		base = _yield_base(_summary(company=self.company_a)["product_yield"], self.fg_plain)
		wo = self._make_wo(self.bom_plain, 40, self.fg_plain)
		self._confirm_postpacking(wo, good=30, reject=3, trial=1, sisa=2)
		row = _yield_row(_summary(company=self.company_a)["product_yield"], self.fg_plain)
		self.assertIsNotNone(row)
		self.assertEqual(row["item_name"], f"{PREFIX} FGPlain {self.suffix}")
		self.assertEqual(row["uom"], self.uom_base)
		planned, good, reject = base["planned"] + 40, base["good"] + 30, base["reject"] + 3
		self.assertAlmostEqual(row["planned"], planned, places=6)
		self.assertAlmostEqual(row["good"], good, places=6)
		self.assertAlmostEqual(row["reject"], reject, places=6)
		self.assertAlmostEqual(row["trial"], base["trial"] + 1, places=6)
		self.assertAlmostEqual(row["sisa"], base["sisa"] + 2, places=6)
		self.assertAlmostEqual(row["yield_pct"], round(good / planned * 100, 6), places=6)
		self.assertAlmostEqual(row["reject_pct"], round(reject / planned * 100, 6), places=6)
		self.assertEqual(row["over"], reject / planned * 100 > 3.0)  # 7.5% > ambang

	def test_11_yield_faktor_pack_12(self):
		"""120 Pcs dengan Default Inventory UOM faktor 12 → nilai tampil
		dikonversi (+10 Pack), yield gabungan 100%, tidak over."""
		base = _yield_base(_summary(company=self.company_a)["product_yield"], self.fg_pack)
		wo = self._make_wo(self.bom_pack, 120, self.fg_pack)
		self._confirm_postpacking(wo, good=120)
		row = _yield_row(_summary(company=self.company_a)["product_yield"], self.fg_pack)
		self.assertIsNotNone(row)
		self.assertEqual(row["uom"], self.uom_pack)
		planned, good = base["planned"] + 10.0, base["good"] + 10.0  # 120/12
		self.assertAlmostEqual(row["planned"], planned, places=6)
		self.assertAlmostEqual(row["good"], good, places=6)
		self.assertAlmostEqual(row["yield_pct"], good / planned * 100, places=6)
		self.assertEqual(row["over"], base["reject"] / planned * 100 > 3.0)

	def test_12_yield_lebih_dari_rencana(self):
		"""Hasil melebihi rencana → yield_pct di atas 100 (tidak pernah di-
		cap); pakai produk lain (fg_yest) agar penggabungan lintas test tidak
		mengaburkan rasio."""
		wo = self._make_wo(self.bom_yest, 100, self.fg_yest)
		self._confirm_postpacking(wo, good=110)
		row = _yield_row(_summary(company=self.company_a)["product_yield"], self.fg_yest)
		self.assertIsNotNone(row)
		self.assertEqual(row["uom"], self.uom_yest)
		self.assertAlmostEqual(row["planned"], 20.0, places=6)  # 100/5
		self.assertAlmostEqual(row["good"], 22.0, places=6)  # 110/5
		self.assertAlmostEqual(row["yield_pct"], 110.0, places=6)

	def test_13_yield_uom_beda_tidak_dijumlahkan(self):
		"""Dua produk beda satuan tampil → dua baris terpisah, nilai masing-
		masing dikonversi dengan faktornya sendiri."""
		before = _summary(company=self.company_a)["product_yield"]
		base_pack = _yield_base(before, self.fg_pack)
		base_plain = _yield_base(before, self.fg_plain)
		wo1 = self._make_wo(self.bom_pack, 120, self.fg_pack)
		self._confirm_postpacking(wo1, good=120)
		wo2 = self._make_wo(self.bom_plain, 60, self.fg_plain)
		self._confirm_postpacking(wo2, good=60)
		rows = _summary(company=self.company_a)["product_yield"]
		pack = _yield_row(rows, self.fg_pack)
		plain = _yield_row(rows, self.fg_plain)
		self.assertIsNotNone(pack)
		self.assertIsNotNone(plain)
		self.assertEqual({pack["uom"], plain["uom"]}, {self.uom_pack, self.uom_base})
		self.assertAlmostEqual(pack["planned"], base_pack["planned"] + 10.0, places=6)  # 120/12
		self.assertAlmostEqual(plain["planned"], base_plain["planned"] + 60.0, places=6)

	def test_14_yield_item_master_terhapus(self):
		"""Item master hilang dari WO → baris produk itu hilang, produk lain
		tetap dihitung, bentuk endpoint tetap utuh (pola FU65)."""
		summary = _summary(company=self.company_a)
		self.assertIsNone(_yield_row(summary["product_yield"], self.fg_del))
		base_plain = _yield_base(summary["product_yield"], self.fg_plain)
		wo_del = self._make_wo(self.bom_del, 90, self.fg_del)
		self._confirm_postpacking(wo_del, good=90)
		wo_ok = self._make_wo(self.bom_plain, 50, self.fg_plain)
		self._confirm_postpacking(wo_ok, good=50)
		before = _summary(company=self.company_a)
		self.assertAlmostEqual(
			_yield_row(before["product_yield"], self.fg_del)["planned"], 30.0, places=6
		)  # 90/3
		# simulate admin deletion: rewrite referensi item di WO (pola FU65)
		frappe.db.set_value(
			"Work Order", wo_del.name, "production_item", f"{PREFIX}-DELETED-{self.suffix}"
		)
		after = _summary(company=self.company_a)
		self._assert_full_shape(after)
		self.assertIsNone(_yield_row(after["product_yield"], self.fg_del))
		self.assertAlmostEqual(
			_yield_row(after["product_yield"], self.fg_plain)["planned"],
			base_plain["planned"] + 50.0,
			places=6,
		)

	def test_15_yield_wo_tanpa_postpacking(self):
		"""WO hari ini TANPA konfirmasi post-packing tidak masuk yield; yang
		terkonfirmasi tetap dihitung, dan satu produk tetap SATU baris walau
		beberapa WO menumpuk."""
		summary = _summary(company=self.company_a)
		base = _yield_base(summary["product_yield"], self.fg_plain)
		self._make_wo(self.bom_plain, 30, self.fg_plain)  # tanpa konfirmasi
		wo_yes = self._make_wo(self.bom_plain, 20, self.fg_plain)
		self._confirm_postpacking(wo_yes, good=20)
		rows = _summary(company=self.company_a)["product_yield"]
		hit = [r for r in rows if r["item_code"] == self.fg_plain]
		self.assertEqual(len(hit), 1)  # agregat per item, bukan per WO
		self.assertAlmostEqual(hit[0]["planned"], base["planned"] + 20.0, places=6)

	# ------------------------------------ FU73: attention per kind

	def test_16_attention_reject_over(self):
		"""reject per-WO di atas ambang → kind reject_over (bad) membawa
		reject_pct + threshold; WO lain di bawah ambang → tidak muncul."""
		before = {e["wo"] for e in _attention_kinds(_summary(company=self.company_a), "reject_over")}
		wo_hi = self._make_wo(self.bom_plain, 40, self.fg_plain)
		self._confirm_postpacking(wo_hi, good=30, reject=3)  # 7.5% > 3%
		wo_lo = self._make_wo(self.bom_plain, 100, self.fg_plain)
		self._confirm_postpacking(wo_lo, good=100, reject=2)  # 2% <= 3%
		rows = _attention_kinds(_summary(company=self.company_a), "reject_over")
		self.assertEqual({e["wo"] for e in rows} - before, {wo_hi.name})
		self.assertNotIn(wo_lo.name, {e["wo"] for e in rows})
		row = next(e for e in rows if e["wo"] == wo_hi.name)
		self.assertEqual(row["severity"], "bad")
		self.assertEqual(row["link"], f"#/wo/{wo_hi.name}")
		self.assertEqual(row["item_name"], f"{PREFIX} FGPlain {self.suffix}")
		self.assertAlmostEqual(row["reject_pct"], 7.5, places=6)
		self.assertEqual(row["threshold"], 3.0)

	def test_17_attention_stagnant(self):
		"""WO submitted aktif yang modified-nya lebih tua dari ambang → kind
		stagnant (warn, stage derive, umur menit); WO segar tidak stagnant."""
		before = {e["wo"] for e in _attention_kinds(_summary(company=self.company_a), "stagnant")}
		wo_old = self._make_wo(self.bom_plain, 40, self.fg_plain)
		wo_old.submit()
		frappe.db.set_value(
			"Work Order",
			wo_old.name,
			"modified",
			now_datetime() - timedelta(hours=5),
			update_modified=False,
		)
		wo_fresh = self._make_wo(self.bom_plain, 41, self.fg_plain)
		wo_fresh.submit()
		rows = _attention_kinds(_summary(company=self.company_a), "stagnant")
		self.assertEqual({e["wo"] for e in rows} - before, {wo_old.name})
		self.assertNotIn(wo_fresh.name, {e["wo"] for e in rows})
		row = next(e for e in rows if e["wo"] == wo_old.name)
		self.assertEqual(row["severity"], "warn")
		self.assertEqual(row["link"], f"#/wo/{wo_old.name}")
		self.assertEqual(row["stage"], STAGE_MATERIAL)
		self.assertEqual(row["item_name"], f"{PREFIX} FGPlain {self.suffix}")
		self.assertGreaterEqual(row["age_minutes"], 4 * 60)

	def test_18_attention_handover_request(self):
		"""MR serah terima menunggu → kind handover_request dengan umur dari
		creation; setelah SE terkirim (builder native MR→SE) → hilang."""
		before = {e["mr"] for e in _attention_kinds(_summary(company=self.company_a), "handover_request")}
		wo = self._make_wo(self.bom_plain, 42, self.fg_plain)
		wo.submit()
		mr = self._make_mr(wo)
		rows = _attention_kinds(_summary(company=self.company_a), "handover_request")
		self.assertEqual({e["mr"] for e in rows} - before, {mr.name})
		row = next(e for e in rows if e["mr"] == mr.name)
		self.assertEqual(row["severity"], "warn")
		self.assertEqual(row["link"], "#/handover")
		self.assertIsNotNone(row["age_minutes"])
		# kirim via builder native MR → SE (material_request tercatat di baris
		# SE); isi dulu stok item MR di gudang asal agar SE lolos validasi
		self._receipt(self.fg_plain, 10, self.src_wh)
		se = frappe.get_doc(make_mr_stock_entry(mr.name))
		se.insert()
		se.submit()
		after = {e["mr"] for e in _attention_kinds(_summary(company=self.company_a), "handover_request")}
		self.assertNotIn(mr.name, after)

	def test_19_attention_form_order_owner_scope(self):
		"""form_order attention mengikuti scope owner PERSIS count lama:
		produksi biasa hanya melihat Form Order buatannya sendiri."""
		wo = self._make_wo(self.bom_plain, 43, self.fg_plain)
		wo.submit()
		mr_admin = self._make_mr(wo, form_order=True)  # owner Administrator
		try:
			frappe.set_user(self.user_prod)
			before = {e["mr"] for e in _attention_kinds(_summary(), "form_order")}
			self.assertNotIn(mr_admin.name, before)  # milik orang lain tak tampak
			mr_own = self._make_mr(wo, form_order=True)  # owner sendiri
			rows = _attention_kinds(_summary(), "form_order")
			self.assertEqual({e["mr"] for e in rows} - before, {mr_own.name})
			row = next(e for e in rows if e["mr"] == mr_own.name)
			self.assertEqual(row["severity"], "warn")
			self.assertEqual(row["link"], "#/form-order")
			self.assertIsNotNone(row["age_minutes"])
		finally:
			frappe.set_user("Administrator")
		admin_names = {
			e["mr"] for e in _attention_kinds(_summary(company=self.company_a), "form_order")
		}
		self.assertIn(mr_admin.name, admin_names)
		self.assertIn(mr_own.name, admin_names)

	def test_20_attention_suhu(self):
		"""Suhu adonan di atas ambang → kind suhu (warn); kosong atau tepat/
		<= ambang → tidak muncul; adonan_ke dikirim apa adanya (default kolom
		Int = 0 bila tak pernah diisi). Urutan array global: baris tanpa umur
		paling belakang, tie-break link (urut suhu hanya menentukan cap)."""
		before = {e["wo"] for e in _attention_kinds(_summary(company=self.company_a), "suhu")}
		wo_hot = self._make_wo(self.bom_plain, 10, self.fg_plain, adonan=5)
		wo_hot.db_set("custom_suhu_adonan", 33.5)
		wo_edge = self._make_wo(self.bom_plain, 11, self.fg_plain, adonan=2)
		wo_edge.db_set("custom_suhu_adonan", 32.0)  # tepat ambang: tidak masuk
		self._make_wo(self.bom_plain, 12, self.fg_plain)  # tanpa suhu: tidak masuk
		wo_hot2 = self._make_wo(self.bom_plain, 13, self.fg_plain)
		wo_hot2.db_set("custom_suhu_adonan", 34.5)  # adonan_ke kosong
		rows = [
			e
			for e in _attention_kinds(_summary(company=self.company_a), "suhu")
			if e["wo"] not in before
		]
		# tanpa umur → paling belakang; sesama suhu tie-break link (nama WO)
		self.assertEqual([e["wo"] for e in rows], sorted([wo_hot.name, wo_hot2.name]))
		self.assertEqual(rows[0]["severity"], "warn")
		self.assertEqual(rows[0]["link"], f"#/wo/{rows[0]['wo']}")
		self.assertEqual(rows[0]["item_name"], f"{PREFIX} FGPlain {self.suffix}")
		self.assertAlmostEqual(rows[0]["suhu"], 33.5, places=6)
		self.assertEqual(rows[0]["threshold"], 32.0)
		self.assertEqual(rows[0]["adonan_ke"], 5)
		self.assertAlmostEqual(rows[1]["suhu"], 34.5, places=6)
		self.assertEqual(rows[1]["adonan_ke"], 0)  # kosong → default kolom 0
		self.assertNotIn(
			wo_edge.name,
			{e["wo"] for e in _attention_kinds(_summary(company=self.company_a), "suhu")},
		)

	def test_21_attention_stopped(self):
		"""WO di-stop (submitted, status Stopped) → kind stopped (bad) TANPA
		field umur (tidak ada timestamp stop native); WO aktif biasa tidak."""
		before = {e["wo"] for e in _attention_kinds(_summary(company=self.company_a), "stopped")}
		wo = self._make_wo(self.bom_plain, 44, self.fg_plain)
		wo.submit()
		wo.db_set("status", "Stopped")
		rows = _attention_kinds(_summary(company=self.company_a), "stopped")
		self.assertEqual({e["wo"] for e in rows} - before, {wo.name})
		row = next(e for e in rows if e["wo"] == wo.name)
		self.assertEqual(row["severity"], "bad")
		self.assertEqual(row["link"], f"#/wo/{wo.name}")
		self.assertEqual(row["item_name"], f"{PREFIX} FGPlain {self.suffix}")
		self.assertNotIn("age_minutes", row)
		wo_ok = self._make_wo(self.bom_plain, 45, self.fg_plain)
		wo_ok.submit()
		rows = _attention_kinds(_summary(company=self.company_a), "stopped")
		self.assertEqual({e["wo"] for e in rows} - before, {wo.name})

	def test_22_attention_yield_company_dan_user_permission(self):
		"""Kunci baru ikut filter company dan User Permission: company B
		tetap kosong; user ber-UP Company=B tidak melihat attention/product_
		yield company A."""
		wo = self._make_wo(self.bom_plain, 46, self.fg_plain)
		wo.submit()
		wo.db_set("status", "Stopped")
		names_a = {e["wo"] for e in _attention_kinds(_summary(company=self.company_a), "stopped")}
		self.assertIn(wo.name, names_a)
		s_b = _summary(company=self.company_b)
		self.assertEqual(s_b["product_yield"], [])
		self.assertEqual(s_b["attention"], [])
		try:
			frappe.set_user(self.user_up)
			s_up = _summary()
			self.assertEqual(s_up["product_yield"], [])
			self.assertEqual(s_up["attention"], [])
		finally:
			frappe.set_user("Administrator")

	def test_23_attention_urutan_severity_dan_umur(self):
		"""Urutan array: severity bad dulu lalu warn; dalam satu severity umur
		terlama dulu (tanpa umur paling belakang); baris uji muncul sesuai
		urutan itu (stopped → stagnant 6 jam → handover_request baru)."""
		wo_stop = self._make_wo(self.bom_plain, 50, self.fg_plain)
		wo_stop.submit()
		wo_stop.db_set("status", "Stopped")
		wo_stag = self._make_wo(self.bom_plain, 51, self.fg_plain)
		wo_stag.submit()
		frappe.db.set_value(
			"Work Order",
			wo_stag.name,
			"modified",
			now_datetime() - timedelta(hours=6),
			update_modified=False,
		)
		mr = self._make_mr(wo_stop)  # handover_request: umur ~0 menit
		entries = _summary(company=self.company_a)["attention"]
		# invarian global: semua bad sebelum semua warn
		severities = [e["severity"] for e in entries]
		self.assertEqual(severities, sorted(severities, key=lambda s: s != "bad"))
		# dalam warn: umur tak naik (baris tanpa umur hanya ber-severity bad)
		warn_ages = [
			e["age_minutes"]
			for e in entries
			if e["severity"] == "warn" and e.get("age_minutes") is not None
		]
		self.assertEqual(warn_ages, sorted(warn_ages, reverse=True))
		# baris uji berurutan sesuai aturan
		ident = [e.get("wo") or e.get("mr") for e in entries]
		self.assertLess(ident.index(wo_stop.name), ident.index(wo_stag.name))
		self.assertLess(ident.index(wo_stag.name), ident.index(mr.name))


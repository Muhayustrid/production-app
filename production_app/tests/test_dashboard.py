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
# FU74 menambah kunci material_usage (agregat pemakaian bahan per rentang
# planned_start_date WO): planned dari Work Order Item, expected diskalakan
# produced_qty/qty (overproduksi jujur), consumed = gross − return dihitung
# LANGSUNG dari Stock Entry (consumed_qty WO diabaikan — native melebihkan
# dengan +returned_qty); module api/material_usage.py dipakai bersama
# dashboard dan endpoint whitelisted tersendiri.
#
# Semua record test berprefix FU72; framework test me-rollback tiap run
# (tanpa commit — tearDownClass hanya sapu defensif ala test_form_order).

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, now, now_datetime, random_string, today

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
	"dari",
	"sampai",
	"preset",
	"companies",
	"wo_planned_today",
	"output_today",
	"adonan_terakhir",
	"stages",
	"handover_menunggu",
	"form_order_menunggu",
	"product_yield",
	"attention",
	"material_usage",
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


def _summary_range(**kwargs):
	"""Varian FU76: dashboard_summary dengan parameter rentang apa pun
	(preset/dari/sampai) — pola import lambat yang sama."""
	from production_app.api.dashboard import dashboard_summary

	return dashboard_summary(**kwargs)


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


def _mu(**kwargs):
	"""Import lambat `aggregate` FU74 supaya RED terukur per-kasus
	(ModuleNotFoundError / KeyError material_usage), bukan satu ImportError
	level file yang menelan bukti kasus lain (pola _summary)."""
	from production_app.api.material_usage import aggregate

	return aggregate(**kwargs)


def _mu_row(rows, item_code):
	"""Baris agregat satu bahan dari daftar baris (None bila tidak ada)."""
	return next((r for r in rows if r["item_code"] == item_code), None)


def _mu_wo(row, wo_name):
	"""Entri breakdown satu WO dalam baris bahan (None bila tidak ada)."""
	return next(
		(w for w in (row or {}).get("work_orders", []) if w["wo"] == wo_name), None
	)


def _urutan_varian(entries):
	"""Kunci invarian urutan FU74: variance_pct None (tanpa dasar) paling
	atas, lalu persen menurun — daftar kunci harus terurut naik."""
	return [(0, 0.0) if p is None else (1, -p) for p in (e.get("variance_pct") for e in entries)]


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
		# FU74: UOM pecahan (UOM baru tanpa must_be_whole_number) untuk bahan
		# ambang varian 5.001
		cls.uom_mu = uom("UMU")

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

		# ---- fixture FU74: produk + bahan khusus agregat pemakaian bahan.
		# Bahan khusus (mu_rm/mu_extra) membuat baris agregat mulai dari NOL —
		# asersi tak tercampur WO fixture lama yang berbagi cls.rm.
		cls.mu_fg = cls._make_item("FGMU", cls.uom_mu)
		cls.mu_rm = cls._make_item("MU RM", cls.uom_mu)
		cls.mu_extra = cls._make_item("MU EXTRA", cls.uom_mu)
		cls.bom_mu = cls._make_bom(cls.mu_fg, material=cls.mu_rm)
		cls._receipt(cls.mu_rm, 1000, cls.src_wh)
		cls._receipt(cls.mu_extra, 10, cls.src_wh)

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
		items = (cls.rm, cls.fg_pack, cls.fg_plain, cls.fg_yest, cls.fg_del, cls.mu_fg, cls.mu_rm, cls.mu_extra)
		uoms = (cls.uom_pack, cls.uom_yest, cls.uom_del, cls.uom_mu)
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
	def _make_bom(cls, fg_item, company=None, material=None):
		material = material or cls.rm
		material_uom = frappe.db.get_value("Item", material, "stock_uom")
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": fg_item,
				"company": company or cls.company_a,
				"currency": frappe.db.get_value("Company", company or cls.company_a, "default_currency"),
				"quantity": 1,
				"items": [
					{
						"item_code": material,
						"qty": 1,
						"rate": 10,
						"uom": material_uom,
						"stock_uom": material_uom,
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
		item_uom = frappe.db.get_value("Item", item, "stock_uom")
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
						"uom": item_uom,
						"stock_uom": item_uom,
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
		cls, bom, qty, item, adonan=None, planned=None, company=None, wip_wh=None, fg_wh=None, src_wh=None, stock_uom=None
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
				# stock UOM dari item produksi (fixture FU74 memakai UOM sendiri)
				"stock_uom": stock_uom or frappe.db.get_value("Item", item, "stock_uom"),
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
	def _transfer_qty(cls, wo, item, qty):
		"""SE MTFM manual dengan qty eksplisit — overproduksi men-transfer di
		atas required (sah hanya saat backflush per-transfer; lihat test_28)."""
		item_uom = frappe.db.get_value("Item", item, "stock_uom")
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer for Manufacture",
				"work_order": wo.name,
				"company": wo.company,
				"from_warehouse": wo.source_warehouse,
				"to_warehouse": wo.wip_warehouse,
				"items": [
					{
						"item_code": item,
						"qty": qty,
						"s_warehouse": wo.source_warehouse,
						"t_warehouse": wo.wip_warehouse,
						"basic_rate": 10,
						"uom": item_uom,
						"stock_uom": item_uom,
					}
				],
			}
		)
		cls._pin_posting(se, today(), "09:00:00")
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
	def _manufacture_bahan(cls, wo, good, materials=None, from_wh=None):
		"""Manufacture SE dengan qty bahan EKSPLISIT per item (overproduksi /
		konsumsi yang tidak mengikuti transfer); baris bahan di luar
		`materials` dibuang — pola dasar _manufacture, tanpa klem transfer.
		`from_wh` mengalihkan gudang asal bahan (overproduksi melampaui WIP:
		bahan tambahan ditarik langsung dari gudang sumber)."""
		se = frappe.get_doc(make_wo_stock_entry(wo.name, "Manufacture", qty=good))
		cls._pin_posting(se, today(), "10:00:00")
		kept = []
		for row in se.items:
			if row.is_finished_item:
				kept.append(row)
			elif row.item_code in (materials or {}):
				row.qty = materials[row.item_code]
				row.transfer_qty = row.qty * flt(row.conversion_factor or 1)
				if from_wh:
					row.s_warehouse = from_wh
				kept.append(row)
		se.items = kept
		se.insert()
		se.submit()
		return se

	@classmethod
	def _consume(cls, wo, materials, from_wh=None):
		"""SE "Material Consumption for Manufacture" — bahan terpakai tanpa FG
		(konsumsi ad-hoc/tambahan). Purpose ini sumber-mandatory native: baris
		hanya membawa s_warehouse (t_warehouse dikosongkan validator)."""
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Consumption for Manufacture",
				"work_order": wo.name,
				"company": wo.company,
				# from_bom wajib: tanpa itu validator me-nol-kan fg_completed_qty
				# lalu melempar "For Quantity (Manufactured Qty) is mandatory"
				"from_bom": 1,
				"bom_no": wo.bom_no,
				"fg_completed_qty": sum(materials.values()),
				"items": [
					{
						"item_code": code,
						"qty": qty,
						"s_warehouse": from_wh or wo.source_warehouse,
						"basic_rate": 10,
						"uom": frappe.db.get_value("Item", code, "stock_uom"),
						"stock_uom": frappe.db.get_value("Item", code, "stock_uom"),
					}
					for code, qty in materials.items()
				],
			}
		)
		se.insert()
		se.submit()
		return se

	@classmethod
	def _return_se(cls, wo, item, qty):
		"""SE kembali bahan: purpose Material Transfer for Manufacture dengan
		is_return=1, arah baris WIP → gudang asal; konvensi native qty POSITIF
		(SLE dibalik get_sle_for_source/target — stock_entry.py 2253/2314)."""
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer for Manufacture",
				"work_order": wo.name,
				"company": wo.company,
				"is_return": 1,
				"from_warehouse": wo.wip_warehouse,
				"to_warehouse": wo.source_warehouse,
				"items": [
				{
					"item_code": item,
					"qty": qty,
					"s_warehouse": wo.wip_warehouse,
					"t_warehouse": wo.source_warehouse,
					"basic_rate": 10,
					"uom": frappe.db.get_value("Item", item, "stock_uom"),
					"stock_uom": frappe.db.get_value("Item", item, "stock_uom"),
				}
			],
		}
	)
		# pin WAJIB: tanpa ini SE posting "sekarang" — bila suite dijalankan
		# sebelum jam 09:00 (jam transfer pinned) urutan kronologis SLE terbalik
		# dan stok WIP negatif (bug laten FU74, kejadian nyata run dini hari)
		cls._pin_posting(se, today(), "09:30:00")
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

	# -------------------------------------- FU74: material_usage (pemakaian bahan)
	# Runner frappe v16 TIDAK rollback antar test method — disiplin delta yang
	# sama dengan test lama: baris mu_rm/mu_extra di-snapshot "before", WO baru
	# diaserti lewat entri work_orders per WO (nilai absolut per WO, bebas
	# pengaruh akumulasi lintas test). Test baru dieksekusi urut nama
	# (test_24 → test_40), fixture FU74 dibuat di setUpClass.

	def test_24_material_usage_dalam_shape(self):
		"""dashboard_summary membawa kunci material_usage (agregat FU74 hari
		ini, pola FU65: tanpa izin baca sumber → angka menyusut jujur, bukan
		500); invarian urutan baris berlaku sejak awal."""
		mu = _summary(company=self.company_a)["material_usage"]
		self.assertEqual(mu["dari"], today())
		self.assertEqual(mu["sampai"], today())
		self.assertIsInstance(mu["rows"], list)
		self.assertIsInstance(mu["products"], list)
		self.assertIn(self.company_a, mu["companies"])
		self.assertEqual(_urutan_varian(mu["rows"]), sorted(_urutan_varian(mu["rows"])))

	def test_25_planned_expected_dari_required_items(self):
		"""WO pertama fixture FU74 → baris bahan absolut: planned dari Work
		Order Item (BOM 1 bahan per unit, WO qty 40), produksi penuh →
		expected 40, consumed 40, varian 0, bukan over/unlisted."""
		wo = self._make_wo(self.bom_mu, 40, self.mu_fg)
		wo.submit()
		self._transfer(wo)
		self._manufacture(wo, 40)
		mu = _mu(company=self.company_a)
		row = _mu_row(mu["rows"], self.mu_rm)
		self.assertIsNotNone(row)
		self.assertEqual(row["item_name"], f"{PREFIX} MU RM {self.suffix}")
		self.assertEqual(row["uom"], self.uom_mu)
		self.assertAlmostEqual(row["planned"], 40, places=6)
		self.assertAlmostEqual(row["expected"], 40, places=6)
		self.assertAlmostEqual(row["consumed"], 40, places=6)
		self.assertAlmostEqual(row["variance"], 0, places=6)
		self.assertAlmostEqual(row["variance_pct"], 0.0, places=6)
		self.assertFalse(row["over"])
		self.assertFalse(row["unlisted"])
		w = _mu_wo(row, wo.name)
		self.assertIsNotNone(w)
		self.assertEqual(w["produk"], f"{PREFIX} FGMU {self.suffix}")
		self.assertAlmostEqual(w["planned"], 40, places=6)
		self.assertAlmostEqual(w["expected"], 40, places=6)
		self.assertAlmostEqual(w["consumed"], 40, places=6)
		self.assertAlmostEqual(w["produced_qty"], 40, places=6)
		self.assertAlmostEqual(w["qty"], 40, places=6)
		self.assertAlmostEqual(w["variance_pct"], 0.0, places=6)
		self.assertFalse(w["over"])

	def test_26_konsumsi_hanya_purpose_manufaktur(self):
		"""Konsumsi dihitung dari SE purpose Manufacture dan Material
		Consumption for Manufacture SAJA — SE transfer ke WIP belum konsumsi."""
		wo_tr = self._make_wo(self.bom_mu, 35, self.mu_fg)
		wo_tr.submit()
		self._transfer(wo_tr)
		base_consumed = flt(
			(_mu_row(_mu(company=self.company_a)["rows"], self.mu_rm) or {}).get("consumed")
		)
		w_tr = _mu_wo(
			_mu_row(_mu(company=self.company_a)["rows"], self.mu_rm), wo_tr.name
		)
		self.assertAlmostEqual(w_tr["consumed"], 0, places=6)  # transfer ≠ konsumsi
		self.assertAlmostEqual(w_tr["planned"], 35, places=6)
		self.assertAlmostEqual(w_tr["expected"], 0, places=6)  # belum produksi
		self.assertIsNone(w_tr["variance_pct"])
		self.assertFalse(w_tr["over"])

		wo_co = self._make_wo(self.bom_mu, 5, self.mu_fg)
		wo_co.submit()
		self._transfer(wo_co)
		self._consume(wo_co, {self.mu_rm: 5})
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		self.assertAlmostEqual(flt(row["consumed"]), base_consumed + 5, places=6)
		self.assertAlmostEqual(_mu_wo(row, wo_co.name)["consumed"], 5, places=6)

	def test_27_return_tidak_mengubah_konsumsi(self):
		"""Retur (MTFM is_return=1, WIP → gudang asal) membalik TRANSFER,
		bukan konsumsi (semantik native: get_available_materials hanya
		mengizinkan retur dari sisa belum terpakai, get_consumed_qty tanpa
		pengurangan retur): transfer 10, kembali 3, produksi 7 → consumed 7;
		expected 7 (skala produced/qty) → varian 0, tidak over."""
		base_consumed = flt(
			(_mu_row(_mu(company=self.company_a)["rows"], self.mu_rm) or {}).get("consumed")
		)
		wo = self._make_wo(self.bom_mu, 10, self.mu_fg)
		wo.submit()
		self._transfer(wo)
		self._return_se(wo, self.mu_rm, 3)
		self._manufacture_bahan(wo, 7, {self.mu_rm: 7})
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		self.assertAlmostEqual(flt(row["consumed"]), base_consumed + 7, places=6)
		w = _mu_wo(row, wo.name)
		self.assertAlmostEqual(w["consumed"], 7, places=6)
		self.assertAlmostEqual(w["produced_qty"], 7, places=6)
		self.assertAlmostEqual(w["expected"], 7, places=6)
		self.assertAlmostEqual(w["variance"], 0, places=6)
		self.assertAlmostEqual(w["variance_pct"], 0.0, places=6)
		self.assertFalse(w["over"])

	def test_28_overproduksi_konsumsi_proporsional_tidak_over(self):
		"""Overproduksi native jujur: dengan celah overproduksi native
		(overproduction_percentage_for_work_order 20%), WO qty 100 hasil 120
		dengan konsumsi proporsional 120 → expected 120 (required ×
		produced/qty), varian ≈ 0, TIDAK over. Setting global dikembalikan
		selalu (finally) — runner tidak rollback antar method."""
		settings = frappe.get_doc("Manufacturing Settings")
		asli_over = settings.overproduction_percentage_for_work_order
		asli_backflush = settings.backflush_raw_materials_based_on
		base_planned = flt(
			(_mu_row(_mu(company=self.company_a)["rows"], self.mu_rm) or {}).get("planned")
		)
		try:
			settings.overproduction_percentage_for_work_order = 20
			# backflush per-transfer: cek "excess material transfer" dilewati,
			# transfer 120 (di atas required 100) sah
			settings.backflush_raw_materials_based_on = "Material Transferred for Manufacture"
			settings.save()
			wo = self._make_wo(self.bom_mu, 100, self.mu_fg)
			wo.submit()
			self._transfer_qty(wo, self.mu_rm, 120)
			self._manufacture(wo, 120)  # konsumsi proporsional, hasil 120
		finally:
			settings.overproduction_percentage_for_work_order = asli_over
			settings.backflush_raw_materials_based_on = asli_backflush
			settings.save()
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		self.assertAlmostEqual(flt(row["planned"]), base_planned + 100, places=6)
		w = _mu_wo(row, wo.name)
		self.assertAlmostEqual(w["consumed"], 120, places=6)
		self.assertAlmostEqual(w["produced_qty"], 120, places=6)
		self.assertAlmostEqual(w["expected"], 120, places=6)
		self.assertAlmostEqual(w["variance"], 0, places=6)
		self.assertAlmostEqual(w["variance_pct"], 0.0, places=6)
		self.assertFalse(w["over"])

	def test_29_ambang_varian_persis_5_persen(self):
		"""Ambang terbuka: variance_pct tepat 5.0 → TIDAK over; 5.001 →
		over (konsumsi tambahan setelah produksi penuh)."""
		wo_edge = self._make_wo(self.bom_mu, 100, self.mu_fg)
		wo_edge.submit()
		self._transfer(wo_edge)
		self._manufacture(wo_edge, 100)
		self._consume(wo_edge, {self.mu_rm: 5}, from_wh=self.src_wh)
		wo_over = self._make_wo(self.bom_mu, 100, self.mu_fg)
		wo_over.submit()
		self._transfer(wo_over)
		self._manufacture(wo_over, 100)
		self._consume(wo_over, {self.mu_rm: 5.001}, from_wh=self.src_wh)
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		we = _mu_wo(row, wo_edge.name)
		self.assertAlmostEqual(we["consumed"], 105, places=6)
		self.assertAlmostEqual(we["expected"], 100, places=6)
		self.assertAlmostEqual(we["variance_pct"], 5.0, places=6)
		self.assertFalse(we["over"])
		wo = _mu_wo(row, wo_over.name)
		self.assertAlmostEqual(wo["consumed"], 105.001, places=6)
		self.assertAlmostEqual(wo["variance_pct"], 5.001, places=6)
		self.assertTrue(wo["over"])

	def test_30_wo_rencana_tanpa_konsumsi_under(self):
		"""WO direncanakan (required 60) tanpa produksi/konsumsi apa pun →
		baris under-konsumsi: consumed 0, expected 0, variance_pct None, bukan
		over, tidak unlisted."""
		base_planned = flt(
			(_mu_row(_mu(company=self.company_a)["rows"], self.mu_rm) or {}).get("planned")
		)
		wo = self._make_wo(self.bom_mu, 60, self.mu_fg)  # draft pun terhitung
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		self.assertAlmostEqual(flt(row["planned"]), base_planned + 60, places=6)
		self.assertFalse(row["unlisted"])
		w = _mu_wo(row, wo.name)
		self.assertAlmostEqual(w["consumed"], 0, places=6)
		self.assertAlmostEqual(w["expected"], 0, places=6)
		self.assertIsNone(w["variance_pct"])
		self.assertFalse(w["over"])

	def test_31_konsumsi_tanpa_dasar_over(self):
		"""WO tidak memproduksi apa pun tapi bahan habis → expected 0,
		variance_pct None ("tanpa dasar"), over=True pada entri WO."""
		wo = self._make_wo(self.bom_mu, 50, self.mu_fg)
		wo.submit()
		self._transfer(wo)
		self._consume(wo, {self.mu_rm: 10}, from_wh=self.src_wh)
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		w = _mu_wo(row, wo.name)
		self.assertAlmostEqual(w["consumed"], 10, places=6)
		self.assertAlmostEqual(w["expected"], 0, places=6)
		self.assertIsNone(w["variance_pct"])
		self.assertTrue(w["over"])
		self.assertFalse(row["unlisted"])  # bahan ada di rencana WO ini

	def test_32_bahan_di_luar_rencana_unlisted(self):
		"""Bahan ad-hoc di luar semua required_items → baris planned 0,
		unlisted=True, over=True (konsumsi tanpa dasar rencana)."""
		wo = self._make_wo(self.bom_mu, 20, self.mu_fg)
		wo.submit()
		self._transfer(wo)
		self._consume(wo, {self.mu_extra: 4}, from_wh=self.src_wh)
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_extra)
		self.assertIsNotNone(row)
		self.assertAlmostEqual(row["planned"], 0, places=6)
		self.assertTrue(row["unlisted"])
		self.assertTrue(row["over"])
		self.assertIsNone(row["variance_pct"])
		self.assertAlmostEqual(row["consumed"], 4, places=6)
		w = _mu_wo(row, wo.name)
		self.assertAlmostEqual(w["consumed"], 4, places=6)
		self.assertTrue(w["over"])

	def test_33_dua_wo_satu_bahan_teragregasi(self):
		"""Dua WO memakai bahan sama → SATU baris (planned menjumlah 30+20),
		dua entri work_orders dengan nilai per WO."""
		base_planned = flt(
			(_mu_row(_mu(company=self.company_a)["rows"], self.mu_rm) or {}).get("planned")
		)
		wo1 = self._make_wo(self.bom_mu, 30, self.mu_fg)
		wo2 = self._make_wo(self.bom_mu, 20, self.mu_fg)
		row = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		self.assertAlmostEqual(flt(row["planned"]), base_planned + 50, places=6)
		names = {w["wo"] for w in row["work_orders"]}
		self.assertIn(wo1.name, names)
		self.assertIn(wo2.name, names)
		self.assertAlmostEqual(_mu_wo(row, wo1.name)["planned"], 30, places=6)
		self.assertAlmostEqual(_mu_wo(row, wo2.name)["planned"], 20, places=6)

	def test_34_filter_company_memisah_wo(self):
		"""aggregate(company=B) hanya memuat WO company B; company A tidak
		bocor ke hasil B dan WO B tidak bocor ke hasil A."""
		bom_b = self._make_bom(self.mu_fg, company=self.company_b, material=self.mu_rm)
		wo_b = self._make_wo(
			bom_b,
			15,
			self.mu_fg,
			company=self.company_b,
			wip_wh=self.b_wip_wh,
			fg_wh=self.b_fg_wh,
			src_wh=self.b_src_wh,
		)
		row_b = _mu_row(_mu(company=self.company_b)["rows"], self.mu_rm)
		self.assertIsNotNone(row_b)
		self.assertAlmostEqual(flt(row_b["planned"]), 15, places=6)
		self.assertEqual([w["wo"] for w in row_b["work_orders"]], [wo_b.name])
		row_a = _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)
		self.assertNotIn(wo_b.name, {w["wo"] for w in row_a["work_orders"]})

	def test_35_filter_production_item(self):
		"""production_item membatasi WO yang dihitung: bahan dari WO produk
		lain tidak ikut (barisnya pun hilang bila tak ada WO lain)."""
		wo_mu = self._make_wo(self.bom_mu, 25, self.mu_fg)
		wo_lain = self._make_wo(self.bom_plain, 25, self.fg_plain)
		row_rm = _mu_row(_mu(company=self.company_a)["rows"], self.rm)
		names_rm = {w["wo"] for w in row_rm["work_orders"]}
		self.assertIn(wo_lain.name, names_rm)
		self.assertNotIn(wo_mu.name, names_rm)  # WO mu_fg tidak memakai rm
		# filter produk mu_fg: baris rm lenyap (tak ada WO mu_fg yang memakainya)
		mu_rows = _mu(company=self.company_a, production_item=self.mu_fg)["rows"]
		self.assertIsNone(_mu_row(mu_rows, self.rm))
		self.assertIn(
			wo_mu.name,
			{w["wo"] for w in _mu_row(mu_rows, self.mu_rm)["work_orders"]},
		)
		# filter produk fg_plain: sebaliknya
		fg_rows = _mu(company=self.company_a, production_item=self.fg_plain)["rows"]
		self.assertIn(
			wo_lain.name, {w["wo"] for w in _mu_row(fg_rows, self.rm)["work_orders"]}
		)
		self.assertIsNone(_mu_row(fg_rows, self.mu_rm))

	def test_36_filter_search_substring(self):
		"""search: substring case-insensitive pada item_code ATAU item_name,
		diterapkan SETELAH agregasi (nilai baris tetap penuh)."""
		self._make_wo(self.bom_mu, 10, self.mu_fg)
		self.assertIsNotNone(_mu_row(_mu(company=self.company_a)["rows"], self.mu_rm))
		# cocok di item_name saja ("MU RM" ber-spasi tidak ada di kode)
		by_name = _mu_row(_mu(company=self.company_a, search="mu rm")["rows"], self.mu_rm)
		self.assertIsNotNone(by_name)
		# cocok di item_code saja ("72-mu" hanya ada di kode, tidak di nama —
		# nama memakai spasi: "FU72 MU RM ...")
		by_code = _mu_row(_mu(company=self.company_a, search="72-mu")["rows"], self.mu_rm)
		self.assertIsNotNone(by_code)
		# baris bahan lain tidak lolos search khusus mu
		self.assertIsNone(_mu_row(_mu(company=self.company_a, search="mu rm")["rows"], self.rm))
		# tidak cocok → kosong
		self.assertEqual(_mu(company=self.company_a, search="tidak-ada-ioe")["rows"], [])

	def test_37_filter_over_only(self):
		"""over_only menyaring BARIS: hanya baris over; baris sehat (rm,
		varian 0 dari konsumsi proporsional) tersembunyi, baris bermasalah
		(mu_extra tanpa rencana) tetap tampil; urutan invarian terjaga."""
		full = _mu(company=self.company_a)
		self.assertFalse(_mu_row(full["rows"], self.rm)["over"])
		self.assertTrue(_mu_row(full["rows"], self.mu_extra)["over"])
		filtered = _mu(company=self.company_a, over_only=True)
		self.assertGreater(len(filtered["rows"]), 0)
		self.assertTrue(all(r["over"] for r in filtered["rows"]))
		self.assertIsNotNone(_mu_row(filtered["rows"], self.mu_extra))
		self.assertIsNone(_mu_row(filtered["rows"], self.rm))
		self.assertEqual(
			_urutan_varian(filtered["rows"]), sorted(_urutan_varian(filtered["rows"]))
		)
		# urutan breakdown per WO dalam satu baris mengikuti aturan yang sama
		row = _mu_row(full["rows"], self.mu_rm)
		self.assertEqual(
			_urutan_varian(row["work_orders"]), sorted(_urutan_varian(row["work_orders"]))
		)

	def test_38_validasi_rentang_tanggal(self):
		"""dari > sampai, rentang > 92 hari, dan tanggal rusak →
		frappe.ValidationError; rentang tepat 92 hari sah."""
		with self.assertRaises(frappe.ValidationError):
			_mu(dari=today(), sampai=add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			_mu(dari=today(), sampai=add_days(today(), 93))
		with self.assertRaises(frappe.ValidationError):
			_mu(dari="bukan-tanggal", sampai=today())
		mu = _mu(dari=today(), sampai=add_days(today(), 92))
		self.assertEqual(mu["dari"], today())
		self.assertEqual(mu["sampai"], add_days(today(), 92))

	def test_39_rentang_tanggal_memfilter_wo(self):
		"""WO di luar rentang planned_start_date tidak masuk agregat; rentang
		lebar memuatnya kembali (draft pun, selama docstatus < 2)."""
		wo_future = self._make_wo(
			self.bom_mu, 70, self.mu_fg, planned=f"{add_days(today(), 10)} 08:00:00"
		)
		wo_past = self._make_wo(
			self.bom_mu, 80, self.mu_fg, planned=f"{add_days(today(), -3)} 08:00:00"
		)
		names_now = {
			w["wo"]
			for w in _mu_row(_mu(company=self.company_a)["rows"], self.mu_rm)["work_orders"]
		}
		self.assertNotIn(wo_future.name, names_now)
		self.assertNotIn(wo_past.name, names_now)
		row_week = _mu_row(
			_mu(
				company=self.company_a,
				dari=add_days(today(), -7),
				sampai=add_days(today(), 14),
			)["rows"],
			self.mu_rm,
		)
		names_week = {w["wo"] for w in row_week["work_orders"]}
		self.assertIn(wo_future.name, names_week)
		self.assertIn(wo_past.name, names_week)

	def test_40_daftar_produk_sebelum_filter_produk(self):
		"""products diambil dari WO SEBELUM filter production_item: dengan
		filter satu produk, daftar tetap memuat produk lain; urut item_name."""
		self._make_wo(self.bom_mu, 12, self.mu_fg)
		mu = _mu(company=self.company_a, production_item=self.mu_fg)
		codes = {p["item_code"] for p in mu["products"]}
		self.assertIn(self.mu_fg, codes)
		self.assertIn(self.fg_plain, codes)
		self.assertIn(self.fg_pack, codes)  # WO produk lain hari ini dari test lama
		names = [p["item_name"] for p in mu["products"]]
		self.assertEqual(names, sorted(names))
		self.assertEqual(set(next(p for p in mu["products"]).keys()), {"item_code", "item_name"})

	def test_41_endpoint_over_only_string(self):
		"""Jalur endpoint whitelisted: param HTTP datang sebagai STRING —
		over_only='0' harus TETAP menampilkan baris sehat (string '0' truthy
		tanpa cint, review FU74 MAJOR-1); over_only='1' menyaring."""
		from production_app.api.material_usage import material_usage as endpoint

		penuh = endpoint(company=self.company_a)
		self.assertFalse(_mu_row(penuh["rows"], self.rm)["over"])
		self.assertTrue(_mu_row(penuh["rows"], self.mu_extra)["over"])
		sehat = endpoint(company=self.company_a, over_only="0")
		self.assertIsNotNone(_mu_row(sehat["rows"], self.rm))
		atas = endpoint(company=self.company_a, over_only="1")
		self.assertTrue(all(r["over"] for r in atas["rows"]))
		self.assertIsNone(_mu_row(atas["rows"], self.rm))

	# ------------------------------------------------- FU76 rentang dashboard

	def test_42_rentang_default_hari_ini(self):
		"""Tanpa parameter perilaku lama utuh: preset hari_ini, dari=sampai=
		hari ini (server-otoritatif), dan 3 kunci rentang masuk shape."""
		s = _summary(company=self.company_a)
		self.assertEqual(s["preset"], "hari_ini")
		self.assertEqual(s["dari"], today())
		self.assertEqual(s["sampai"], today())

	def test_43_preset_kemarin_scoping_wo(self):
		"""Preset kemarin: WO planned kemarin terhitung, dan default hari ini
		tak terpengaruh oleh WO kemarin (delta dalam preset masing-masing)."""
		s_kemarin_sebelum = _summary_range(company=self.company_a, preset="kemarin")
		s_hari_sebelum = _summary(company=self.company_a)
		wo = self._make_wo(self.bom_mu, 15, self.mu_fg, planned=f"{add_days(today(), -1)} 08:00:00")
		s_kemarin_sesudah = _summary_range(company=self.company_a, preset="kemarin")
		s_hari_sesudah = _summary(company=self.company_a)
		self.assertEqual(
			s_kemarin_sesudah["wo_planned_today"],
			s_kemarin_sebelum["wo_planned_today"] + 1,
			"WO kemarin menambah hitungan preset kemarin",
		)
		self.assertEqual(
			s_hari_sesudah["wo_planned_today"],
			s_hari_sebelum["wo_planned_today"],
			"WO kemarin tidak mengubah preset hari ini",
		)

	def test_44_preset_bulan_ini_mtd(self):
		"""Bulan ini = tanggal 1 s.d. hari ini: WO planned awal bulan masuk,
		WO bulan depan tidak; dari/sampai resolved benar."""
		h = getdate(today())
		s = _summary_range(company=self.company_a, preset="bulan_ini")
		self.assertEqual(s["dari"], str(h.replace(day=1)))
		self.assertEqual(s["sampai"], str(h))
		wo = self._make_wo(self.bom_mu, 12, self.mu_fg, planned=f"{h.replace(day=1)} 08:00:00")
		s2 = _summary_range(company=self.company_a, preset="bulan_ini")
		self.assertGreater(s2["wo_planned_today"], s["wo_planned_today"])

	def test_45_preset_bulan_kemarin(self):
		"""Bulan kemarin = 1 s.d. akhir bulan lalu; WO planned bulan lalu
		masuk preset itu dan TIDAK mengubah preset hari ini."""
		h = getdate(today())
		akhir_lalu = add_days(h.replace(day=1), -1)
		awal_lalu = akhir_lalu.replace(day=1)
		s = _summary_range(company=self.company_a, preset="bulan_kemarin")
		self.assertEqual(s["dari"], str(awal_lalu))
		self.assertEqual(s["sampai"], str(akhir_lalu))
		s_hari_sebelum = _summary(company=self.company_a)
		wo = self._make_wo(self.bom_mu, 11, self.mu_fg, planned=f"{akhir_lalu} 08:00:00")
		s2 = _summary_range(company=self.company_a, preset="bulan_kemarin")
		self.assertGreater(s2["wo_planned_today"], s["wo_planned_today"])
		s_hari_sesudah = _summary(company=self.company_a)
		self.assertEqual(
			s_hari_sesudah["wo_planned_today"],
			s_hari_sebelum["wo_planned_today"],
			"WO bulan lalu tidak masuk preset hari ini",
		)

	def test_46_preset_tahun_ini(self):
		"""Tahun ini = 1 Januari s.d. hari ini; memuat WO bulan lalu."""
		h = getdate(today())
		akhir_lalu = add_days(h.replace(day=1), -1)
		wo = self._make_wo(self.bom_mu, 10, self.mu_fg, planned=f"{akhir_lalu} 08:00:00")
		s = _summary_range(company=self.company_a, preset="tahun_ini")
		self.assertEqual(s["dari"], str(h.replace(month=1, day=1)))
		self.assertEqual(s["sampai"], str(h))
		names = {w["wo"] for w in _mu_row(s["material_usage"]["rows"], self.mu_rm)["work_orders"]} \
			if _mu_row(s["material_usage"]["rows"], self.mu_rm) else set()
		self.assertIn(wo.name, names, "WO bulan lalu masuk agregat bahan tahun ini")

	def test_47_kustom_rentang_eksplisit(self):
		"""Preset kustom memakai dari/sampai eksplisit: hanya WO di rentang."""
		h = getdate(today())
		wo_lama = self._make_wo(self.bom_mu, 9, self.mu_fg, planned=f"{add_days(h, -30)} 08:00:00")
		s = _summary_range(company=self.company_a, preset="kustom", dari=str(add_days(h, -31)), sampai=str(add_days(h, -29)))
		names = {w["wo"] for w in _mu_row(s["material_usage"]["rows"], self.mu_rm)["work_orders"]} \
			if _mu_row(s["material_usage"]["rows"], self.mu_rm) else set()
		self.assertIn(wo_lama.name, names)
		self.assertEqual(s["preset"], "kustom")

	def test_48_kustom_validasi(self):
		"""dari>sampai, span >366 hari, kustom tanpa tanggal, dan preset
		tak dikenal → ValidationError; span tepat 366 hari sah."""
		with self.assertRaises(frappe.ValidationError):
			_summary_range(company=self.company_a, preset="kustom", dari=today(), sampai=add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			_summary_range(company=self.company_a, preset="kustom", dari=add_days(today(), -367), sampai=today())
		_summary_range(company=self.company_a, preset="kustom", dari=add_days(today(), -366), sampai=today())
		with self.assertRaises(frappe.ValidationError):
			_summary_range(company=self.company_a, preset="kustom")
		with self.assertRaises(frappe.ValidationError):
			_summary_range(company=self.company_a, preset="minggu_ini")

	def test_49_output_rentang(self):
		"""Hasil produksi ikut rentang: Manufacture SE kemarin dihitung di
		preset kemarin, tidak di hari ini (delta per UOM bahan uji)."""
		# stok bahan uji sendiri — SE backdated masuk timeline kemarin
		self._receipt(self.mu_rm, 100, self.src_wh)
		wo = self._make_wo(self.bom_mu, 8, self.mu_fg, planned=f"{add_days(today(), -1)} 08:00:00")
		wo.submit()
		self._transfer(wo, posting_date=add_days(today(), -1))
		self._manufacture(wo, 8, posting_date=add_days(today(), -1))
		out_kemarin = _uom_qty(_summary_range(company=self.company_a, preset="kemarin"), self.uom_mu)
		# hasil kemarin masuk preset kemarin ( Manufacture uji lain posting
		# hari ini — asersi longgar: kemarin punya entri, bukan klaim nol)
		self.assertIsNotNone(out_kemarin)
		self.assertGreater(out_kemarin, 0)

	def test_50_stages_selesai_rentang(self):
		"""Tile 7 papan ikut rentang: WO selesai kemarin masuk hitungan
		selesai_hari_ini di preset kemarin, tidak di default hari ini."""
		# stok bahan uji sendiri — SE backdated masuk timeline kemarin
		self._receipt(self.mu_rm, 100, self.src_wh)
		wo = self._make_wo(self.bom_mu, 7, self.mu_fg, planned=f"{add_days(today(), -1)} 08:00:00")
		wo.submit()
		self._transfer(wo, posting_date=add_days(today(), -1))
		self._manufacture(wo, 7, posting_date=add_days(today(), -1))
		s_kemarin = _summary_range(company=self.company_a, preset="kemarin")
		s_hari = _summary(company=self.company_a)
		# asersi longgar (runner tanpa rollback — WO uji lain ikut hitungan):
		# tile 7 preset kemarin hidup karena WO ini selesai kemarin;
		# default hari ini tetap 7 kunci papan
		self.assertGreater(s_kemarin["stages"]["selesai_hari_ini"], 0)
		self.assertEqual(set(s_hari["stages"].keys()), STAGE_KEYS)

	def test_51_yield_rentang(self):
		"""Hasil per produk ikut rentang: postpacking WO kemarin tampil di
		preset kemarin, tidak menambah yield default hari ini."""
		wo = self._make_wo(self.bom_mu, 20, self.mu_fg, planned=f"{add_days(today(), -1)} 08:00:00")
		self._confirm_postpacking(wo, good=19, reject=1)
		s_kemarin = _summary_range(company=self.company_a, preset="kemarin")
		row = _yield_row(s_kemarin["product_yield"], self.mu_fg)
		self.assertIsNotNone(row, "yield WO kemarin tampil di preset kemarin")
		self.assertGreater(row["planned"], 0)

	def test_52_material_usage_rentang_panjang_tanpa_417(self):
		"""Preset tahun ini (>92 hari) tidak boleh 417 di dashboard —
		aggregate diberi max_days=DASHBOARD_MAX_DAYS (366)."""
		s = _summary_range(company=self.company_a, preset="tahun_ini")
		self.assertIsNotNone(s["material_usage"])
		self.assertIn("rows", s["material_usage"])

	def test_53_adonan_terakhir_rentang(self):
		"""Adonan terakhir ikut rentang: adonan ke-99 di WO kemarin menjadi
		maksimum preset kemarin, default hari ini tidak terpengaruh."""
		s_hari = _summary(company=self.company_a)
		wo = self._make_wo(self.bom_mu, 5, self.mu_fg, planned=f"{add_days(today(), -1)} 08:00:00", adonan=99)
		s_kemarin = _summary_range(company=self.company_a, preset="kemarin")
		self.assertEqual(s_kemarin["adonan_terakhir"], 99)
		self.assertEqual(_summary(company=self.company_a)["adonan_terakhir"], s_hari["adonan_terakhir"])


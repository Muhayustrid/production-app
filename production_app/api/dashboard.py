# Dashboard "Hari Ini" (FU72) — agregat read-only satu round-trip untuk layar
# pertama SPA (supervisor/manajer produksi). Semua angka diturunkan dari
# dokumen saat baca (server truth, pola papan serah terima); UI tidak pernah
# menyimpan stage. Permission native `frappe.get_list` cukup — tanpa gate
# role tambahan; bila satu sumber tidak terbaca angkanya menyusut jujur,
# endpoint tetap hidup (pola FU65).
#
# Custom field selalu lewat get_list/get_cached_doc + .get() — bukan
# db.get_value berdaftar kolom custom (pelajaran InvalidColumnName FU58).
# Konversi satuan hasil memakai resolver `production_plan._conversion_factor`
# (varian + validasi finite>0) — semantik display = qty / faktor. Rantai
# fallback hasil = item-level: custom_default_inventory_unit_of_measure (W21)
# → stock_uom. Link tengah `custom_uom` dari _enrich_units SENGAJA tidak
# dipakai di sini: itu berlingkup baris WO, sedangkan agregat menjumlah
# lintas WO per item — satu item satu satuan (keputusan review FU72).

import frappe
from frappe.utils import cint, flt, today

from production_app.api.handover import (
	ROLE_MANAJER_PRODUKSI,
	ROLES_GUDANG,
	_sent_se_by_mr,
)
from production_app.api.production_plan import _conversion_factor
from production_app.api.work_order import (
	STAGE_FINISH,
	STAGE_MATERIAL,
	STAGE_OPERASI,
	STAGE_POST_PACKING,
	STAGE_PREPACKING,
	STAGE_PERSIAPAN,
	STAGE_SELESAI,
	derive_stage,
)

# Kunci papan di luar konstanta stage work_order: WO yang BARU selesai hari
# ini dipisah dari antrian "selesai" papan (riwayat selesai lama tidak tampil).
STAGE_SELESAI_HARI_INI = "selesai_hari_ini"

# WO submitted dengan status ini bukan antrian kerja (turunan filter stage
# aplikasi di work_order._stage_filters); Stopped/Closed = jalur review Desk.
ACTIVE_EXCLUDED_STATUSES = ("Completed", "Stopped", "Closed")


@frappe.whitelist()
def dashboard_summary(company=None):
	"""Ringkasan "Hari Ini" untuk dashboard SPA (FU72). Read-only; `company`
	opsional mempersempit semua angka ke satu company. Kontrak shape dipatok
	oleh frontend (tests/test_dashboard.py)."""
	day = today()
	planned, adonan = _wo_today(day, company)
	return {
		"today": day,
		"companies": _companies(),
		"wo_planned_today": planned,
		"output_today": _output_today(day, company),
		"adonan_terakhir": adonan,
		"stages": _stages(day, company),
		"handover_menunggu": _handover_menunggu(company),
		"form_order_menunggu": _form_order_menunggu(company),
	}


def _companies():
	"""Daftar company yang terlihat user (User Permission otomatis lewat
	get_list, urut nama); tanpa izin Company daftar kosong, bukan error."""
	try:
		return frappe.get_list("Company", pluck="name", order_by="name")
	except frappe.PermissionError:
		return []


def _wo_today(day, company):
	"""(jumlah WO planned hari ini, adonan terakhir) — satu query; docstatus
	< 2 (draft ikut direncanakan, cancelled tidak)."""
	filters = [
		["docstatus", "<", 2],
		["planned_start_date", ">=", day],
		["planned_start_date", "<=", f"{day} 23:59:59"],
	]
	if company:
		filters.append(["company", "=", company])
	try:
		rows = frappe.get_list(
			"Work Order",
			filters=filters,
			fields=["name", "custom_adonan_ke"],
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return 0, 0
	adonan = max([cint(r.get("custom_adonan_ke")) for r in rows] or [0])
	return len(rows), adonan


def _stages(day, company):
	"""Papan tahap per derive_stage (satu sumber aturan stage, tidak digandakan).

	Baris yang dihitung:
	- draft (docstatus 0) → persiapan — antrian yang tertahan, tanpa batas
	  tanggal (sama dengan aktif);
	- submitted aktif (status bukan Completed/Stopped/Closed) → derive per
	  baris dengan operasi preload sekali (hindari N+1);
	- WO selesai HARI INI (Manufacture SE posting hari ini, docstatus 1) →
	  masuk selesai_hari_ini hanya bila derive_stage == selesai. WO selesai
	  sebelum hari ini tidak pernah tampil di papan.

	Skala: memindai seluruh WO terbuka tanpa batas — hitungan papan tidak
	boleh terpotong; batasi dengan tanggal bila backlog membengkak."""
	counts = {
		STAGE_PERSIAPAN: 0,
		STAGE_MATERIAL: 0,
		STAGE_OPERASI: 0,
		STAGE_PREPACKING: 0,
		STAGE_POST_PACKING: 0,
		STAGE_FINISH: 0,
		STAGE_SELESAI_HARI_INI: 0,
	}
	filters = [["docstatus", "<", 2]]
	if company:
		filters.append(["company", "=", company])
	try:
		rows = frappe.get_list(
			"Work Order",
			filters=filters,
			fields=[
				"name",
				"docstatus",
				"status",
				"qty",
				"produced_qty",
				"process_loss_qty",
				"material_transferred_for_manufacturing",
				"skip_transfer",
				"custom_prepacking_confirmed",
				"custom_postpacking_confirmed",
			],
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return counts

	drafts, actives = [], []
	for row in rows:
		if row.docstatus == 0:
			drafts.append(row)
		elif row.status not in ACTIVE_EXCLUDED_STATUSES:
			actives.append(row)

	# preload operasi SEKALI untuk seluruh baris aktif, dikelompokkan per parent
	operations = {}
	parents = [r.name for r in actives]
	if parents:
		for op in frappe.get_all(
			"Work Order Operation",
			filters={"parent": ("in", parents)},
			fields=["parent", "completed_qty", "process_loss_qty", "status"],
		):
			operations.setdefault(op.parent, []).append(op)

	for _row in drafts:
		counts[STAGE_PERSIAPAN] += 1
	for row in actives:
		# guard papan 7 kunci: derive bisa balas selesai di tepi presisi float
		# (ERPNext membandingkan dengan precision kolom, derive dengan float
		# mentah) — kunci di luar papan dibuang, bukan KeyError 500 (review 3)
		stage = derive_stage(row, operations.get(row.name, []))
		if stage in counts:
			counts[stage] += 1

	for row in _finished_today_rows(day, company):
		# derive memotong di cek qty selesai sebelum menyentuh operasi, jadi
		# daftar operasi kosong cukup untuk pembandingan terhadap "selesai"
		if derive_stage(row, []) == STAGE_SELESAI:
			counts[STAGE_SELESAI_HARI_INI] += 1
	return counts


def _finished_today_rows(day, company):
	"""WO yang Manufacture SE-nya posting hari ini (docstatus 1) — kandidat
	selesai_hari_ini; dibaca permission-filtered, dibatasi company param."""
	se_filters = [
		["purpose", "=", "Manufacture"],
		["docstatus", "=", 1],
		["posting_date", "=", day],
	]
	if company:
		se_filters.append(["company", "=", company])
	try:
		wo_names = {
			n for n in frappe.get_list(
				"Stock Entry", filters=se_filters, pluck="work_order", limit_page_length=0
			)
			if n
		}
	except frappe.PermissionError:
		return []
	if not wo_names:
		return []
	wo_filters = [["name", "in", sorted(wo_names)]]
	if company:
		wo_filters.append(["company", "=", company])
	return frappe.get_list(
		"Work Order",
		filters=wo_filters,
		fields=[
			"name",
			"docstatus",
			"status",
			"qty",
			"produced_qty",
			"process_loss_qty",
			"material_transferred_for_manufacturing",
			"skip_transfer",
			"custom_prepacking_confirmed",
			"custom_postpacking_confirmed",
		],
		limit_page_length=0,
	)


def _output_today(day, company):
	"""Total hasil Manufacture hari ini per satuan tampil gudang. Qty SED
	dijumlah per item dalam stock UOM (transfer_qty = qty stock), lalu tiap
	item dikonversi server-side ke Default Inventory UOM — rantai item-level:
	W21 (custom_default_inventory_unit_of_measure) → stock_uom. Link tengah
	`custom_uom` dari _enrich_units sengaja tidak dipakai: itu berlingkup
	baris WO, agregat menjumlah lintas WO per item, jadi satu item satu
	satuan (tabel WO hari ini boleh tampil custom_uom per WO — deviasi
	dokumentasi review FU72). Item beda UOM tidak pernah dijumlahkan; item
	tanpa faktor valid dan item master terhapus di-skip per baris (FU65)."""
	se_filters = [
		["purpose", "=", "Manufacture"],
		["docstatus", "=", 1],
		["posting_date", "=", day],
	]
	if company:
		se_filters.append(["company", "=", company])
	try:
		ses = frappe.get_list(
			"Stock Entry", filters=se_filters, pluck="name", limit_page_length=0
		)
	except frappe.PermissionError:
		return []
	if not ses:
		return []

	totals = {}
	for r in frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ("in", ses), "is_finished_item": 1},
		fields=["item_code", "transfer_qty", "qty"],
	):
		totals.setdefault(r.item_code, 0.0)
		totals[r.item_code] += flt(r.transfer_qty or r.qty)

	by_uom = {}
	for code, qty in totals.items():
		try:
			item = frappe.get_cached_doc("Item", code)
		except frappe.DoesNotExistError:
			continue  # SE riwayat memegang item terhapus — skip baris itu saja
		alternate = (
			item.get("custom_default_inventory_unit_of_measure") or item.stock_uom
		)
		factor = _conversion_factor(item, alternate)
		if not factor:
			continue  # tanpa konversi valid: skip, jangan mengarang faktor
		by_uom[alternate] = by_uom.get(alternate, 0.0) + qty / factor
	return sorted(
		({"uom": uom, "qty": qty} for uom, qty in by_uom.items()),
		key=lambda e: e["qty"],
		reverse=True,
	)


def _handover_menunggu(company):
	"""Jumlah permintaan serah terima menunggu — kondisi PERSIS lane "request"
	aktif handover_board (api/handover.py): MR Material Transfer docstatus 1,
	bukan Stopped (cancelled = docstatus 2), terikat Work Order lewat
	Material Request Item.custom_work_order, tanpa bukti Stock Entry. Tanpa
	izin baca MR/SE angkanya 0 — papan tetap hidup (pola yang sama)."""
	try:
		mr_names = sorted(
			set(
				frappe.get_all(
					"Material Request Item",
					filters={"custom_work_order": ("is", "set")},
					pluck="parent",
				)
			)
		)
		if not mr_names:
			return 0
		filters = {
			"name": ("in", mr_names),
			"material_request_type": "Material Transfer",
			"docstatus": 1,
			"status": ("!=", "Stopped"),
		}
		if company:
			filters["company"] = company
		mrs = frappe.get_list("Material Request", filters=filters, pluck="name", limit_page_length=0)
	except frappe.PermissionError:
		return 0
	if not mrs or not frappe.has_permission("Stock Entry", "read"):
		return 0  # lane tak bisa diturunkan jujur tanpa visibilitas SE
	sent = _sent_se_by_mr(mrs)
	return sum(1 for name in mrs if name not in sent)


def _form_order_menunggu(company):
	"""Jumlah Form Order menunggu — kondisi status "menunggu" PERSIS
	form_order_list (api/form_order.py): MR custom_is_form_order submitted
	yang belum punya SE pengiriman (sumber bukti sama: _sent_se_by_mr;
	tanpa izin baca SE daftar tetap menghitung, persis _orders). Scope lihat
	juga PERSIS _orders: gudang & manajer produksi melihat semua, produksi
	biasa hanya buatannya sendiri — angka papan harus sama dengan isi
	halaman Form Order (angka global untuk user yang dibatasi owner =
	mismatch, review FU72)."""
	roles = frappe.get_roles()
	scoped = any(r in roles for r in ROLES_GUDANG) or ROLE_MANAJER_PRODUKSI in roles
	filters = {"custom_is_form_order": 1, "docstatus": 1}
	if not scoped:
		filters["owner"] = frappe.session.user
	if company:
		filters["company"] = company
	try:
		mrs = frappe.get_list("Material Request", filters=filters, pluck="name", limit_page_length=0)
	except frappe.PermissionError:
		return 0
	if not mrs:
		return 0
	sent = (
		_sent_se_by_mr(mrs)
		if frappe.has_permission("Stock Entry", "read")
		else {}
	)
	return sum(1 for name in mrs if name not in sent)

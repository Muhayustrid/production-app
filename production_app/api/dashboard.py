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
#
# FU73 menambah `product_yield` (agregat hasil post-packing per produk,
# konversi satuan display) dan `attention` (baris mentah per kind — judul
# dan format angka DIRANGKAI FRONTEND, server hanya data terstruktur).
#
# FU74 menambah `material_usage` — agregat pemakaian bahan hari ini dari
# api/material_usage.aggregate; tanpa izin baca WO/SE → None (panel
# disembunyikan frontend, pola FU65/FU73).

from datetime import timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime, today

from production_app.api.handover import (
	ROLE_MANAJER_PRODUKSI,
	ROLES_GUDANG,
	_sent_se_by_mr,
)
from production_app.api.material_usage import aggregate
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

# FU73 (keputusan owner via mockup): ambang % reject post-packing terhadap
# planned — di atas ini produk ditandai `over` dan WO masuk attention
# `reject_over`.
REJECT_THRESHOLD_PCT = 3.0
# FU73: WO aktif tanpa perubahan apa pun (modified) selama berjam-jam
# dianggap mandek → attention `stagnant`.
STAGNANT_HOURS = 4
# FU73 (keputusan owner via mockup): suhu adonan (°C) di atas ini masuk
# attention `suhu`; field OPSIONAL — kosong/0 tidak pernah dihitung.
SUHU_ADONAN_MAX = 32.0

# Kolom baris WO papan — satu sumber untuk _stages dan attention FU73
# (custom field lewat get_list + .get(), bukan db.get_value berdaftar kolom
# custom, pelajaran InvalidColumnName FU58).
WO_ROW_FIELDS = (
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
)


# Kolom baris WO hari ini — satu query untuk yield, reject_over, suhu, dan
# hitungan WO direncanakan (review FU73 #2: jangan scan berulang per request).
TODAY_WO_FIELDS = (
	"name",
	"production_item",
	"item_name",
	"qty",
	"custom_adonan_ke",
	"custom_postpacking_confirmed",
	"custom_good_qty_postpacking",
	"custom_reject_qty_postpacking",
	"custom_trial_qty_postpacking",
	"custom_sisa_qty_postpacking",
	"custom_suhu_adonan",
)


@frappe.whitelist()
def dashboard_summary(company=None):
	"""Ringkasan "Hari Ini" untuk dashboard SPA (FU72/FU73). Read-only; `company`
	opsional mempersempit semua angka ke satu company. Kontrak shape dipatok
	oleh frontend (tests/test_dashboard.py). Baris WO dan MR dibaca SEKALI per
	request lalu dibagikan ke semua bagian (review FU73 #2)."""
	day = today()
	rows = _wo_rows(company, extra_fields=("modified", "item_name"))
	today_rows = _wo_today_rows(day, company)
	handover = _handover_mrs(company)
	form_orders = _form_order_mrs(company)
	planned, adonan = _wo_today(today_rows)
	# FU74: agregat pemakaian bahan hari ini. Tanpa izin baca WO/SE → None:
	# frontend menyembunyikan panelnya (degradasi jujur, pola FU65/FU73),
	# endpoint tetap hidup — PermissionError sengaja TIDAK ditelan di dalam
	# aggregate sendiri.
	try:
		material_usage = aggregate(company=company, dari=day, sampai=day)
	except frappe.PermissionError:
		material_usage = None
	return {
		"today": day,
		"companies": _companies(),
		"wo_planned_today": planned,
		"output_today": _output_today(day, company),
		"adonan_terakhir": adonan,
		"stages": _stages(day, company, rows),
		"handover_menunggu": len(handover),
		"form_order_menunggu": len(form_orders),
		"product_yield": _product_yield(today_rows),
		"attention": _attention(rows, today_rows, handover, form_orders),
		"material_usage": material_usage,
	}


def _companies():
	"""Daftar company yang terlihat user (User Permission otomatis lewat
	get_list, urut nama); tanpa izin Company daftar kosong, bukan error."""
	try:
		return frappe.get_list("Company", pluck="name", order_by="name")
	except frappe.PermissionError:
		return []


def _wo_today(today_rows):
	"""(jumlah WO planned hari ini, adonan terakhir) dari baris yang sudah
	dibaca dashboard_summary; docstatus < 2 (draft ikut direncanakan,
	cancelled tidak)."""
	adonan = max([cint(r.get("custom_adonan_ke")) for r in today_rows] or [0])
	return len(today_rows), adonan


def _wo_rows(company, extra_fields=()):
	"""Baris WO docstatus < 2 (seluruh backlog terlihat user, User Permission
	otomatis lewat get_list); PermissionError → kosong, papan tetap hidup.
	Satu sumber baris untuk _stages dan attention FU73."""
	filters = [["docstatus", "<", 2]]
	if company:
		filters.append(["company", "=", company])
	try:
		return frappe.get_list(
			"Work Order",
			filters=filters,
			fields=list(WO_ROW_FIELDS) + list(extra_fields),
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return []


def _operations_by_parent(parents):
	"""Operasi WO dikelompokkan per parent — preload SEKALI untuk seluruh
	baris (hindari N+1); dipakai _stages dan attention `stagnant`."""
	operations = {}
	if parents:
		for op in frappe.get_all(
			"Work Order Operation",
			filters={"parent": ("in", parents)},
			fields=["parent", "completed_qty", "process_loss_qty", "status"],
		):
			operations.setdefault(op.parent, []).append(op)
	return operations


def _stages(day, company, rows):
	"""Papan tahap per derive_stage (satu sumber aturan stage, tidak digandakan).
	`rows` = baris WO docstatus < 2 hasil _wo_rows (sudah permission-filtered).

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

	drafts, actives = [], []
	for row in rows:
		if row.docstatus == 0:
			drafts.append(row)
		elif row.status not in ACTIVE_EXCLUDED_STATUSES:
			actives.append(row)

	operations = _operations_by_parent([r.name for r in actives])

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
	try:
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
	except frappe.PermissionError:
		# tanpa izin baca WO papan tetap hidup (perilaku _stages di HEAD —
		# review FU73 MAJOR-1: jalur ini tak lagi tertutup early-return _wo_rows)
		return []


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


def _mr_menunggu_rows(filters, butuh_se=False):
	"""(name, creation) MR submitted sesuai `filters` yang belum ada bukti SE
	terkirim (_sent_se_by_mr). Satu kondisi untuk angka papan dan item
	attention FU73 — hitungan lama tidak berubah. `butuh_se`: lane serah
	terima menuntut izin baca SE agar bisa diturunkan jujur (tanpa izin →
	kosong); Form Order justru tetap dihitung tanpa izin SE (persis _orders)."""
	try:
		rows = frappe.get_list(
			"Material Request", filters=filters, fields=["name", "creation"], limit_page_length=0
		)
	except frappe.PermissionError:
		return []
	if not rows:
		return []
	se_ok = frappe.has_permission("Stock Entry", "read")
	if butuh_se and not se_ok:
		return []
	sent = _sent_se_by_mr([r.name for r in rows]) if se_ok else {}
	return [r for r in rows if r.name not in sent]


def _handover_mrs(company):
	"""(name, creation) MR lane "request" menunggu — kondisi PERSIS lane aktif
	handover_board (api/handover.py): MR Material Transfer docstatus 1, bukan
	Stopped (cancelled = docstatus 2), terikat Work Order lewat
	Material Request Item.custom_work_order, tanpa bukti Stock Entry."""
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
	except frappe.PermissionError:
		return []
	if not mr_names:
		return []
	filters = {
		"name": ("in", mr_names),
		"material_request_type": "Material Transfer",
		"docstatus": 1,
		"status": ("!=", "Stopped"),
	}
	if company:
		filters["company"] = company
	return _mr_menunggu_rows(filters, butuh_se=True)


def _form_order_mrs(company):
	"""(name, creation) Form Order menunggu — kondisi status "menunggu" PERSIS
	form_order_list (api/form_order.py): MR custom_is_form_order submitted
	yang belum punya SE pengiriman (sumber bukti sama: _sent_se_by_mr).
	Scope lihat PERSIS _orders: gudang & manajer produksi melihat semua,
	produksi biasa hanya buatannya sendiri. Angka papan = len(...) harus sama
	dengan isi halaman Form Order (angka global untuk user yang dibatasi
	owner = mismatch, review FU72)."""
	roles = frappe.get_roles()
	scoped = any(r in roles for r in ROLES_GUDANG) or ROLE_MANAJER_PRODUKSI in roles
	filters = {"custom_is_form_order": 1, "docstatus": 1}
	if not scoped:
		filters["owner"] = frappe.session.user
	if company:
		filters["company"] = company
	return _mr_menunggu_rows(filters)


# ------------------------------------------------------------ FU73 yield

def _wo_today_rows(day, company):
	"""WO hari ini (docstatus < 2 — draft ikut, cancelled tidak;
	planned_start_date hari ini, lingkup sama dengan "WO hari ini") dengan
	kolom gabungan TODAY_WO_FIELDS — satu query untuk yield, reject_over,
	suhu, dan hitungan WO direncanakan; PermissionError → kosong (endpoint
	tetap hidup, pola FU65)."""
	filters = [
		["docstatus", "<", 2],
		["planned_start_date", ">=", day],
		["planned_start_date", "<=", f"{day} 23:59:59"],
	]
	if company:
		filters.append(["company", "=", company])
	try:
		return frappe.get_list(
			"Work Order", filters=filters, fields=list(TODAY_WO_FIELDS), limit_page_length=0
		)
	except frappe.PermissionError:
		return []


def _product_yield(today_rows):
	"""Agregat hasil per produk (FU73): WO hari ini dengan post-packing
	terkonfirmasi, dijumlah lintas WO per item lalu dikonversi ke satuan
	display rantai item-level W21 → stock_uom (pola _output_today; item beda
	UOM TIDAK pernah dijumlahkan). Item master terhapus / faktor invalid →
	skip baris WO itu saja. yield_pct terbesar dulu; angka float mentah —
	frontend yang memformat."""
	per_item = {}
	for row in today_rows:
		if not row.get("custom_postpacking_confirmed"):
			continue
		try:
			item = frappe.get_cached_doc("Item", row.production_item)
		except frappe.DoesNotExistError:
			continue  # WO memegang item master terhapus — skip baris WO itu saja
		alternate = item.get("custom_default_inventory_unit_of_measure") or item.stock_uom
		factor = _conversion_factor(item, alternate)
		if not factor:
			continue  # tanpa konversi valid: skip, jangan mengarang faktor
		acc = per_item.setdefault(
			row.production_item,
			{
				"item_code": row.production_item,
				"item_name": item.get("item_name") or row.production_item,
				"uom": alternate,
				"planned": 0.0,
				"good": 0.0,
				"reject": 0.0,
				"trial": 0.0,
				"sisa": 0.0,
			},
		)
		acc["planned"] += flt(row.qty) / factor
		for key in ("good", "reject", "trial", "sisa"):
			acc[key] += flt(row.get(f"custom_{key}_qty_postpacking")) / factor
	out = []
	for acc in per_item.values():
		planned = acc["planned"]
		yield_pct = round(acc["good"] / planned * 100, 6) if planned > 0 else 0.0
		reject_pct = round(acc["reject"] / planned * 100, 6) if planned > 0 else 0.0
		out.append(
			{
				**acc,
				"yield_pct": yield_pct,
				"reject_pct": reject_pct,
				"over": reject_pct > REJECT_THRESHOLD_PCT,
			}
		)
	return sorted(out, key=lambda e: e["yield_pct"], reverse=True)


# --------------------------------------------------------- FU73 attention

def _age_minutes(creation):
	"""Umur dokumen dalam menit, dibulatkan ke bawah."""
	return int((now_datetime() - get_datetime(creation)).total_seconds() // 60)


def _attention_reject_over(today_rows):
	"""Per-WO (BUKAN gabungan per produk): WO hari ini terkonfirmasi post-
	packing dengan reject_pct melewati REJECT_THRESHOLD_PCT. Rasio % kebal
	konversi satuan (pembilang & penyebut sama-sama stock UOM). Cap 10."""
	out = []
	for row in today_rows:
		if not row.get("custom_postpacking_confirmed"):
			continue
		planned = flt(row.qty)
		reject_pct = round(flt(row.get("custom_reject_qty_postpacking")) / planned * 100, 6) if planned > 0 else 0.0
		if reject_pct <= REJECT_THRESHOLD_PCT:
			continue
		out.append(
			{
				"kind": "reject_over",
				"severity": "bad",
				"link": f"#/wo/{row.name}",
				"wo": row.name,
				"item_name": row.item_name,
				"reject_pct": reject_pct,
				"threshold": REJECT_THRESHOLD_PCT,
			}
		)
	out.sort(key=lambda e: e["reject_pct"], reverse=True)
	return out[:10]


def _attention_stagnant(rows):
	"""WO submitted aktif yang modified-nya lebih tua dari STAGNANT_HOURS —
	stage dari derive_stage (operasi preload, aturan sama dengan papan).
	Umur paling lama dulu. Cap 5. `rows` = baris _wo_rows dengan kolom
	tambahan modified + item_name."""
	cutoff = now_datetime() - timedelta(hours=STAGNANT_HOURS)
	stagnant = [
		r
		for r in rows
		if r.docstatus == 1
		and r.status not in ACTIVE_EXCLUDED_STATUSES
		and get_datetime(r.modified) < cutoff
	]
	operations = _operations_by_parent([r.name for r in stagnant])
	out = [
		{
			"kind": "stagnant",
			"severity": "warn",
			"link": f"#/wo/{row.name}",
			"wo": row.name,
			"item_name": row.item_name,
			"stage": derive_stage(row, operations.get(row.name, [])),
			"age_minutes": _age_minutes(row.modified),
		}
		for row in sorted(stagnant, key=lambda r: get_datetime(r.modified))
	]
	return out[:5]


def _attention_handover(handover_rows):
	"""MR lane request menunggu (kondisi PERSIS _handover_menunggu). Cap 5."""
	out = [
		{
			"kind": "handover_request",
			"severity": "warn",
			"link": "#/handover",
			"mr": mr.name,
			"age_minutes": _age_minutes(mr.creation),
		}
		for mr in handover_rows
	]
	out.sort(key=lambda e: e["age_minutes"], reverse=True)
	return out[:5]


def _attention_form_order(form_rows):
	"""Form Order menunggu (kondisi PERSIS _form_order_menunggu, termasuk
	scope owner untuk non-gudang/non-manajer). Cap 5."""
	out = [
		{
			"kind": "form_order",
			"severity": "warn",
			"link": "#/form-order",
			"mr": mr.name,
			"age_minutes": _age_minutes(mr.creation),
		}
		for mr in form_rows
	]
	out.sort(key=lambda e: e["age_minutes"], reverse=True)
	return out[:5]


def _attention_suhu(today_rows):
	"""WO hari ini (draft boleh) dengan suhu adonan terisi di atas
	SUHU_ADONAN_MAX; adonan_ke boleh 0/None — dikirim apa adanya. Urut suhu
	terbesar dulu. Cap 5."""
	out = []
	for row in today_rows:
		suhu = row.get("custom_suhu_adonan")
		if suhu in (None, "") or flt(suhu) <= SUHU_ADONAN_MAX:
			continue
		out.append(
			{
				"kind": "suhu",
				"severity": "warn",
				"link": f"#/wo/{row.name}",
				"wo": row.name,
				"item_name": row.item_name,
				"adonan_ke": row.get("custom_adonan_ke"),
				"suhu": flt(suhu),
				"threshold": SUHU_ADONAN_MAX,
			}
		)
	out.sort(key=lambda e: e["suhu"], reverse=True)
	return out[:5]


def _attention_stopped(rows):
	"""WO dihentikan (docstatus 1, status Stopped). Tanpa field umur: tidak
	ada timestamp stop native — jangan mengarang. Cap 10."""
	out = [
		{
			"kind": "stopped",
			"severity": "bad",
			"link": f"#/wo/{row.name}",
			"wo": row.name,
			"item_name": row.item_name,
		}
		for row in rows
		if row.docstatus == 1 and row.status == "Stopped"
	]
	return out[:10]


def _attention(rows, today_rows, handover_rows, form_rows):
	"""Baris attention FU73 — data mentah terstruktur per kind; judul/detail
	berbahasa Indonesia DIRANGKAI FRONTEND. Semua baris dibaca sekali di
	dashboard_summary (review FU73 #2). Urutan: severity `bad` dulu lalu
	`warn`; dalam satu severity umur terlama dulu (tanpa umur paling
	belakang); tie-break deterministik kind lalu link."""
	items = [
		*_attention_reject_over(today_rows),
		*_attention_stagnant(rows),
		*_attention_handover(handover_rows),
		*_attention_form_order(form_rows),
		*_attention_suhu(today_rows),
		*_attention_stopped(rows),
	]

	def order(entry):
		age = entry.get("age_minutes")
		return (
			entry["severity"] != "bad",
			age is None,
			-(age or 0),
			entry["kind"],
			entry.get("link") or "",
		)

	return sorted(items, key=order)

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
#
# FU76 menambah filter rentang: preset server-resolved (hari_ini default =
# perilaku lama, kemarin, bulan_ini MTD, bulan_kemarin, tahun_ini, kustom)
# atau dari+sampai eksplisit. Semua bagian tanggal-sensitif mengikuti
# rentang; papan tahap 1-6 TETAP kondisi live (backlog terbuka semua
# tanggal — jangan sembunyikan yang tertahan), hanya tile "selesai" yang
# ikut rentang (label dinamis di frontend). Nama kunci lama dipertahankan
# (wo_planned_today/output_today/adonan_terakhir) — bermakna "dalam
# rentang terpilih", bukan hanya hari ini.
#
# FU78 menambah kunci KPI & grafik: planned_qty (total rencana per satuan
# display — satu sumber baris dengan hitungan wo_planned_today agar KPI dan
# sub-teks "dari N WO" berparitas), dominant_uom (satu UOM utama untuk chart
# & KPI pencapaian, dihitung SEKALI di server), daily (seri rencana vs hasil
# per hari/bulan — HANYA item ber-UOM dominan di KEDUA seri, beda UOM tidak
# pernah dijumlahkan), output_prev (window sebelumnya, hanya preset hari
# ini — dasar chip "+x% vs kemarin") dan recent_activity (Manufacture/MTFM
# terbaru dalam rentang, retur dibuang).
#
# FU78b memindah seri grafik ke endpoint whitelisted tersendiri
# `dashboard_daily` — filter LOKAL kartu (mode minggu = Senin..Minggu pekan
# ini, bulan = 1..akhir bulan berjalan, harian zero-fill) yang lepas dari
# filter rentang halaman, dan mengembalikan SEMUA satuan display sebagai
# `series` per UOM (krim kopi Pcs vs dough Pack tidak pernah dijumlahkan;
# frontend menyediakan pemilih UOM, default dominant_uom milik window).

from datetime import date, datetime, timedelta

import frappe
from frappe.defaults import get_user_default, set_user_default
from frappe.utils import (
	add_days,
	cint,
	flt,
	get_datetime,
	get_last_day,
	getdate,
	now_datetime,
	today,
)

from production_app.api.filter_params import filter_list as _filter_list
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

# FU76: preset rentang dashboard + batas rentangnya (lebih longgar dari
# halaman penggunaan-bahan 92 hari — preset "tahun ini" wajib muat; tetap dibatasi
# sebagai pelindung beban query SE).
PRESET_HARI_INI = "hari_ini"
PRESET_KEMARIN = "kemarin"
PRESET_BULAN_INI = "bulan_ini"
PRESET_BULAN_KEMARIN = "bulan_kemarin"
PRESET_TAHUN_INI = "tahun_ini"
PRESET_KUSTOM = "kustom"
DASHBOARD_PRESETS = (
	PRESET_HARI_INI,
	PRESET_KEMARIN,
	PRESET_BULAN_INI,
	PRESET_BULAN_KEMARIN,
	PRESET_TAHUN_INI,
)
DASHBOARD_MAX_DAYS = 366
# FU78b: window filter LOKAL kartu grafik (lepas dari filter rentang halaman)
# — "minggu" = Senin..Minggu pekan ini (label nama hari di frontend), "bulan"
# = 1..akhir bulan berjalan; keduanya harian dan zero-fill.
DAILY_MODE_MINGGU = "minggu"
DAILY_MODE_BULAN = "bulan"

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


# Kolom baris WO dalam rentang — satu query untuk yield, reject_over, suhu,
# dan hitungan WO direncanakan (review FU73 #2: jangan scan berulang per
# request); FU76: lingkup generalized hari ini → rentang.
RANGE_WO_FIELDS = (
	"name",
	"production_item",
	"item_name",
	"qty",
	"planned_start_date",
	"custom_adonan_ke",
	"custom_postpacking_confirmed",
	"custom_good_qty_postpacking",
	"custom_reject_qty_postpacking",
	"custom_trial_qty_postpacking",
	"custom_sisa_qty_postpacking",
	"custom_suhu_adonan",
)


def _satu_nilai(value, name):
	"""FU102: param halaman Dashboard bernilai TUNGGAL (preset/dari/sampai/
	mode) — perluasan FU100 yang sama: terima skalar lama (termasuk date/
	datetime native dari pemanggil lama, distringkan dulu), list satu nilai,
	atau string JSON satu nilai. Daftar kosong = param tidak dikirim
	(perilaku lama/default server). Dua nilai atau lebih ditolak (limit 1):
	satu rentang/window tidak bisa digabung dari beberapa nilai, jadi server
	menolak alih-alih diam-diam memilih satu."""
	if value is None:
		return None
	if isinstance(value, (date, datetime)):  # pemanggil lama: date/datetime native
		value = str(value)
	values = _filter_list(value, name, limit=1)
	return values[0] if values else None


def _rentang_preset(preset, dari, sampai):
	"""(dari, sampai, preset) resolved ISO dari preset FU76 atau tanggal
	kustom; default hari ini = perilaku lama. Tanggal server yang
	otoritatif — preset di-resolve di sini, bukan di jam browser user.
	dari>sampai / span > DASHBOARD_MAX_DAYS / kustom tanpa tanggal /
	preset tak dikenal → ValidationError (HTTP 417 konvensi app).

	FU102: ketiga param lolos `_satu_nilai` dulu — skalar lama, list satu
	nilai, dan string JSON satu nilai semuanya diterima; rentang adalah
	nilai TUNGGAL, jadi dua nilai atau lebih ditolak (bukan digabung)."""
	preset = _satu_nilai(preset, "preset")
	dari = _satu_nilai(dari, "dari")
	sampai = _satu_nilai(sampai, "sampai")
	hari = getdate(today())
	if not preset or preset == PRESET_HARI_INI:
		return str(hari), str(hari), PRESET_HARI_INI
	if preset == PRESET_KUSTOM:
		if not dari or not sampai:
			frappe.throw(
				"Rentang kustom butuh tanggal awal dan akhir.", exc=frappe.ValidationError
			)
		tgl_dari, tgl_sampai = getdate(dari), getdate(sampai)
	elif preset == PRESET_KEMARIN:
		kemarin = add_days(hari, -1)
		tgl_dari, tgl_sampai = kemarin, kemarin
	elif preset == PRESET_BULAN_INI:
		tgl_dari, tgl_sampai = hari.replace(day=1), hari
	elif preset == PRESET_BULAN_KEMARIN:
		akhir_lalu = add_days(hari.replace(day=1), -1)
		tgl_dari, tgl_sampai = akhir_lalu.replace(day=1), akhir_lalu
	elif preset == PRESET_TAHUN_INI:
		tgl_dari, tgl_sampai = hari.replace(month=1, day=1), hari
	else:
		frappe.throw("Preset rentang tidak dikenal.", exc=frappe.ValidationError)
	if tgl_dari > tgl_sampai:
		frappe.throw(
			"Tanggal awal (dari) tidak boleh setelah tanggal akhir (sampai).",
			exc=frappe.ValidationError,
		)
	if (tgl_sampai - tgl_dari).days > DASHBOARD_MAX_DAYS:
		frappe.throw(
			f"Rentang tanggal maksimal {DASHBOARD_MAX_DAYS} hari.",
			exc=frappe.ValidationError,
		)
	return str(tgl_dari), str(tgl_sampai), preset


@frappe.whitelist()
def dashboard_summary(company=None, preset=None, dari=None, sampai=None):
	"""Ringkasan produksi untuk dashboard SPA (FU72/FU73/FU76). Read-only;
	`company` opsional mempersempit ke satu company; `preset`+`dari`+`sampai`
	FU76 memilih rentang (default hari ini = perilaku lama). Kontrak shape
	dipatok frontend (tests/test_dashboard.py); kunci bernama *_today
	(wo_planned_today/output_today/adonan_terakhir) bermakna "dalam rentang
	terpilih" — nama lama dipertahankan demi shape stabil. Baris WO dan MR
	dibaca SEKALI per request lalu dibagikan ke semua bagian (review FU73)."""
	day = today()
	dari, sampai, preset = _rentang_preset(preset, dari, sampai)
	rows = _wo_rows(company, extra_fields=("modified", "item_name"))
	range_rows = _wo_range_rows(dari, sampai, company)
	handover = _handover_mrs(company)
	form_orders = _form_order_mrs(company)
	planned, adonan = _wo_today(range_rows)
	# FU78: satu rantai konversi display untuk output & rencana; UOM utama
	# (chart + KPI pencapaian) dihitung sekali di sini.
	output = _output_range(dari, sampai, company)
	planned_qty = _planned_qty(range_rows)
	dominant = _dominant_uom(output, planned_qty)
	# FU74: agregat pemakaian bahan per rentang. Tanpa izin baca WO/SE →
	# None: frontend menyembunyikan panelnya (degradasi jujur, pola
	# FU65/FU73), endpoint tetap hidup — PermissionError sengaja TIDAK
	# ditelan di dalam aggregate sendiri. max_days ikut batas dashboard
	# (preset "tahun ini" melebihi batas 92 hari halaman penggunaan-bahan).
	try:
		material_usage = aggregate(
			company=company, dari=dari, sampai=sampai, max_days=DASHBOARD_MAX_DAYS
		)
	except frappe.PermissionError:
		material_usage = None
	return {
		"today": day,
		"dari": dari,
		"sampai": sampai,
		"preset": preset,
		"companies": _companies(),
		"wo_planned_today": planned,
		"output_today": output,
		# FU78: dasar chip "+x% vs kemarin" — hanya hari ini yang punya window
		# pembanding alami; preset lain kosong (jangan mengarang perbandingan)
		"output_prev": (
			_output_range(add_days(getdate(dari), -1), add_days(getdate(dari), -1), company)
			if preset == PRESET_HARI_INI
			else []
		),
		"planned_qty": planned_qty,
		"dominant_uom": dominant,
		"adonan_terakhir": adonan,
		"stages": _stages(dari, sampai, company, rows),
		"handover_menunggu": len(handover),
		"form_order_menunggu": len(form_orders),
		"product_yield": _product_yield(range_rows),
		"attention": _attention(rows, range_rows, handover, form_orders),
		"material_usage": material_usage,
		"recent_activity": _recent_activity(dari, sampai, company),
	}


def _companies():
	"""Daftar company yang terlihat user (User Permission otomatis lewat
	get_list, urut nama); tanpa izin Company daftar kosong, bukan error."""
	try:
		return frappe.get_list("Company", pluck="name", order_by="name")
	except frappe.PermissionError:
		return []


# FU95: filter company GLOBAL dari halaman workspace — satu pilihan yang
# dipakai SEMUA halaman (WO/SE/Form Order/Ketersediaan Stock/Dashboard/Bahan).
# Disimpan sebagai preferensi PER-USER (pola ui_preferences FU70: user default
# JSON per-user, tanpa gate role — hanya preferensi milik pemanggil). '' =
# "Semua company". Diletakkan di dashboard.py karena daftar company yang
# terlihat user sudah di sini (_companies) dan work_order.py mengimpornya
# balik lewat dashboard (impor melingkar bila dibalik).
COMPANY_PREFERENCE_KEY = "production_app_company_filter"


@frappe.whitelist()
def company_preference():
	"""FU95 — preferensi filter company global: nilai tersimpan + daftar
	company yang terlihat user (satu panggilan — sumber opsi semua <select>
	company halaman). Company tersimpan yang tidak lagi terlihat → ''
	(self-heal senyap; jangan pernah menunjuk company di luar izin user)."""
	companies = _companies()
	saved = str(get_user_default(COMPANY_PREFERENCE_KEY) or "")
	if companies and saved and saved not in companies:
		saved = ""
	return {"company": saved, "companies": companies}


@frappe.whitelist()
def company_preference_save(company=None):
	"""FU95 — simpan filter company global per-user; '' = semua company.
	Company di luar daftar terlihat user ditolak (ValidationError) — preferensi
	tersimpan tidak boleh menunjuk ke luar izin pemiliknya."""
	value = str(company or "").strip()
	companies = _companies()
	if value and value not in companies:
		frappe.throw("Company tidak ditemukan: {}".format(value), exc=frappe.ValidationError)
	set_user_default(COMPANY_PREFERENCE_KEY, value)
	return {"company": value, "companies": companies}


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


def _stages(dari, sampai, company, rows):
	"""Papan tahap per derive_stage (satu sumber aturan stage, tidak digandakan).
	`rows` = baris WO docstatus < 2 hasil _wo_rows (sudah permission-filtered).

	Baris yang dihitung:
	- draft (docstatus 0) → persiapan — antrian yang tertahan, tanpa batas
	  tanggal (sama dengan aktif);
	- submitted aktif (status bukan Completed/Stopped/Closed) → derive per
	  baris dengan operasi preload sekali (hindari N+1);
	- WO selesai DALAM RENTANG (FU76; Manufacture SE posting dari..sampai,
	  docstatus 1) → masuk tile terakhir hanya bila derive_stage == selesai.
	  Tile 1-6 tetap kondisi live semua tanggal — jangan sembunyikan
	  yang tertahan hanya karena filter rentang aktif.

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

	for row in _finished_range_rows(dari, sampai, company):
		# derive memotong di cek qty selesai sebelum menyentuh operasi, jadi
		# daftar operasi kosong cukup untuk pembandingan terhadap "selesai"
		if derive_stage(row, []) == STAGE_SELESAI:
			counts[STAGE_SELESAI_HARI_INI] += 1
	return counts


def _finished_range_rows(dari, sampai, company):
	"""WO yang Manufacture SE-nya posting dalam rentang (docstatus 1) —
	kandidat tile "selesai" papan; permission-filtered, dibatasi company."""
	se_filters = [
		["purpose", "=", "Manufacture"],
		["docstatus", "=", 1],
		["posting_date", ">=", dari],
		["posting_date", "<=", sampai],
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


def _item_display_uom(item):
	"""(satuan display, faktor) satu item: rantai item-level W21 → stock_uom.
	faktor None bila konversi tidak valid — pemanggil memutuskan skip atau
	fallback stock (jangan mengarang faktor). Dipakai semua agregat FU78 agar
	konversi tidak bisa berbeda antar-panel."""
	alternate = item.get("custom_default_inventory_unit_of_measure") or item.stock_uom
	return alternate, _conversion_factor(item, alternate)


def _output_range(dari, sampai, company):
	"""Total hasil Manufacture dalam rentang per satuan tampil gudang. Qty SED
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
		["posting_date", ">=", dari],
		["posting_date", "<=", sampai],
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
		alternate, factor = _item_display_uom(item)
		if not factor:
			continue  # tanpa konversi valid: skip, jangan mengarang faktor
		by_uom[alternate] = by_uom.get(alternate, 0.0) + qty / factor
	return sorted(
		({"uom": uom, "qty": qty} for uom, qty in by_uom.items()),
		key=lambda e: e["qty"],
		reverse=True,
	)


def _planned_qty(range_rows):
	"""Total rencana WO dalam rentang per satuan display item (FU78) — sumber
	baris SAMA dengan hitungan wo_planned_today (`range_rows`) sehingga angka
	KPI dan sub-teks "dari N WO" berparitas. Konversi & skip mengikuti pola
	_output_range; item beda UOM tidak pernah dijumlahkan."""
	totals = {}
	for row in range_rows:
		totals[row.production_item] = totals.get(row.production_item, 0.0) + flt(row.qty)
	by_uom = {}
	for code, qty in totals.items():
		try:
			item = frappe.get_cached_doc("Item", code)
		except frappe.DoesNotExistError:
			continue
		alternate, factor = _item_display_uom(item)
		if not factor:
			continue
		by_uom[alternate] = by_uom.get(alternate, 0.0) + qty / factor
	return sorted(
		({"uom": uom, "qty": qty} for uom, qty in by_uom.items()),
		key=lambda e: e["qty"],
		reverse=True,
	)


def _dominant_uom(output, planned):
	"""Satu UOM utama untuk kartu grafik & KPI pencapaian (FU78): total hasil
	terbesar dulu; tanpa hasil → rencana terbesar; dua-duanya kosong → None.
	Dihitung SEKALI di server — chart, KPI, dan caption memakai nilai yang
	sama agar tidak bisa berbeda. max() + tie-break nama: tidak bergantung
	urutan list dan deterministik saat seri."""
	if output:
		return max(output, key=lambda e: (flt(e["qty"]), e["uom"]))["uom"]
	if planned:
		return max(planned, key=lambda e: (flt(e["qty"]), e["uom"]))["uom"]
	return None


@frappe.whitelist()
def dashboard_daily(company=None, mode=None):
	"""Seri kartu grafik "Rencana vs hasil" (FU78b) — filter LOKAL kartu yang
	lepas dari filter rentang halaman: mode `minggu` = Senin..Minggu pekan
	ini, `bulan` = 1..akhir bulan berjalan (tanggal server otoritatif);
	granularitas selalu harian dan hari tanpa kejadian tetap dikirim
	(zero-fill) agar label Senin s.d. Minggu / tanggal 1..31 di frontend
	tidak bolong. SEMUA satuan display dikembalikan sebagai `series`
	terpisah — krim kopi (Pcs) dan dough (Pack) berdampingan TANPA pernah
	dijumlahkan; frontend menampilkan satu UOM per chart (pemilih UOM) dengan
	default `dominant_uom` milik window ini (dihitung server, satu sumber,
	seri pertama). Basis tanggal sengaja berbeda: hasil = posting_date SE
	Manufacture, rencana = planned_start_date WO — di-caption frontend.
	Permission native get_list: tanpa izin → series kosong (endpoint tetap
	hidup, pola FU65). Mode tak dikenal → ValidationError (417 konvensi).

	FU102: `mode` juga lolos `_satu_nilai` — skalar/list-satu/JSON-satu sama,
	daftar kosong jatuh ke default minggu (perilaku lama)."""
	mode = _satu_nilai(mode, "mode")
	mode = DAILY_MODE_MINGGU if not mode else str(mode)
	hari = getdate(today())
	if mode == DAILY_MODE_MINGGU:
		tgl_dari = add_days(hari, -hari.weekday())  # Senin pekan ini
		tgl_sampai = add_days(tgl_dari, 6)
	elif mode == DAILY_MODE_BULAN:
		tgl_dari = hari.replace(day=1)
		tgl_sampai = getdate(get_last_day(hari))
	else:
		frappe.throw("Mode grafik tidak dikenal.", exc=frappe.ValidationError)
	series = _daily_series(str(tgl_dari), str(tgl_sampai), company)
	uoms = [s["uom"] for s in series]
	if not uoms and mode == DAILY_MODE_MINGGU:
		# FU100a: pekan kosong tetap mengirim kandidat UOM dari bulan berjalan
		# agar pemilih UOM di caption tetap tampil di KEDUA mode (permintaan
		# user) — chart-nya tetap kosong; mode bulan tak butuh fallback karena
		# window-nya sudah bulan berjalan sendiri.
		uoms = [
			s["uom"]
			for s in _daily_series(str(hari.replace(day=1)), str(get_last_day(hari)), company)
		]
	return {
		"mode": mode,
		"dari": str(tgl_dari),
		"sampai": str(tgl_sampai),
		"granularity": "harian",
		"dominant_uom": series[0]["uom"] if series else None,
		"uoms": uoms,
		"series": series,
	}


def _daily_series(dari, sampai, company):
	"""Semua satuan display dalam window → satu seri baris harian per UOM
	(zero-fill penuh dari..sampai); hasil & rencana tidak pernah dicampur
	antar-UOM (perumuman _daily FU78 yang sebelumnya memfilter satu UOM
	dominan). Urutan seri: total hasil menurun, lalu rencana, lalu nama UOM
	— seri pertama = dominan window."""
	span = (getdate(sampai) - getdate(dari)).days
	periods = [str(add_days(getdate(dari), i)) for i in range(span + 1)]

	def display_uom(code):
		try:
			item = frappe.get_cached_doc("Item", code)
		except frappe.DoesNotExistError:
			return None, None
		return _item_display_uom(item)

	# ---- hasil: baris fg SE Manufacture per tanggal posting (pola _output_range)
	se_filters = [
		["purpose", "=", "Manufacture"],
		["docstatus", "=", 1],
		["posting_date", ">=", dari],
		["posting_date", "<=", sampai],
	]
	if company:
		se_filters.append(["company", "=", company])
	try:
		ses = frappe.get_list(
			"Stock Entry", filters=se_filters, fields=["name", "posting_date"], limit_page_length=0
		)
	except frappe.PermissionError:
		ses = []
	produced = {}  # (uom, period) → qty display
	if ses:
		se_date = {s.name: s.posting_date for s in ses}
		totals = {}
		for r in frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": ("in", [s.name for s in ses]), "is_finished_item": 1},
			fields=["parent", "item_code", "transfer_qty", "qty"],
		):
			key = (r.parent, r.item_code)
			totals[key] = totals.get(key, 0.0) + flt(r.transfer_qty or r.qty)
		for (se_name, code), qty in totals.items():
			alternate, factor = display_uom(code)
			if not factor:
				continue  # tanpa konversi valid: skip, jangan mengarang faktor
			k = (alternate, str(se_date[se_name]))
			produced[k] = produced.get(k, 0.0) + qty / factor

	# ---- rencana: qty WO per tanggal mulai, dikelompokkan per satuan display
	planned = {}
	uom_by_item = {}
	for row in _wo_range_rows(dari, sampai, company):
		if row.production_item not in uom_by_item:
			uom_by_item[row.production_item] = display_uom(row.production_item)
		alternate, factor = uom_by_item[row.production_item]
		if not factor:
			continue
		k = (alternate, str(getdate(row.planned_start_date)))
		planned[k] = planned.get(k, 0.0) + flt(row.qty) / factor

	def total(peta, uom):
		return sum(v for (u, _), v in peta.items() if u == uom)

	uoms = sorted(
		{u for u, _ in produced} | {u for u, _ in planned},
		key=lambda u: (-total(produced, u), -total(planned, u), u),
	)
	return [
		{
			"uom": uom,
			"rows": [
				{
					"period": p,
					"planned": flt(planned.get((uom, p))),
					"produced": flt(produced.get((uom, p))),
				}
				for p in periods
			],
		}
		for uom in uoms
	]


def _recent_activity(dari, sampai, company, limit=10):
	"""Aktivitas terbaru dalam rentang (FU78): SE submitted yang terikat
	pekerjaan — purpose Manufacture (hasil diposting; baris fg-nya) dan
	Material Transfer for Manufacture (bahan diserahkan; baris keluar-nya).
	Retur (is_return=1) dibuang — itu pembalikan transfer, bukan kejadian
	serah terima (semantik FU74). work_order bisa kosong (SE manual sah
	secara native) → link None; frontend tidak boleh merender jangkar mati.
	Data mentah terstruktur; judul dirangkai frontend (pola attention FU73).
	Tanpa izin baca SE → [] (pola _finished_range_rows)."""
	se_filters = [
		["purpose", "in", ["Manufacture", "Material Transfer for Manufacture"]],
		["docstatus", "=", 1],
		["posting_date", ">=", dari],
		["posting_date", "<=", sampai],
		["is_return", "=", 0],
	]
	if company:
		se_filters.append(["company", "=", company])
	try:
		ses = frappe.get_list(
			"Stock Entry",
			filters=se_filters,
			fields=["name", "purpose", "posting_date", "posting_time", "work_order"],
			order_by="posting_date desc, posting_time desc, creation desc",
			limit_page_length=limit,
		)
	except frappe.PermissionError:
		return []
	if not ses:
		return []

	def display_uom(code):
		try:
			item = frappe.get_cached_doc("Item", code)
		except frappe.DoesNotExistError:
			return None, None
		return _item_display_uom(item)

	# baris SED per event: fg utk Manufacture, baris keluar utk MTFM
	details = {}  # se -> {item_code: (qty, item_name)}
	for purpose, baris_fg in (("Manufacture", True), ("Material Transfer for Manufacture", False)):
		parents = [s.name for s in ses if s.purpose == purpose]
		if not parents:
			continue
		extra = {"is_finished_item": 1} if baris_fg else {"s_warehouse": ("is", "set")}
		for d in frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": ("in", parents), **extra},
			fields=["parent", "item_code", "item_name", "transfer_qty", "qty"],
		):
			per = details.setdefault(d.parent, {})
			qty, nama = per.get(d.item_code, (0.0, None))
			per[d.item_code] = (qty + flt(d.transfer_qty or d.qty), d.item_name or nama)

	out = []
	for s in ses:
		items, others = [], 0
		for code, (qty, nama) in sorted(
			details.get(s.name, {}).items(), key=lambda kv: kv[1][0], reverse=True
		):
			if len(items) >= 2:
				others += 1
				continue
			alternate, factor = display_uom(code)
			if not factor:
				continue  # tanpa konversi valid: baris item ini dilewati
			items.append(
				{"item_code": code, "item_name": nama or code, "qty": round(qty / factor, 3), "uom": alternate}
			)
		out.append(
			{
				"se": s.name,
				"kind": "manufacture" if s.purpose == "Manufacture" else "transfer",
				"ts": f"{s.posting_date} {s.posting_time or '00:00:00'}",
				"wo": s.work_order or None,
				"link": f"#/wo/{s.work_order}" if s.work_order else None,
				"items": items,
				"item_lain": others,
			}
		)
	return out


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

def _wo_range_rows(dari, sampai, company):
	"""WO dalam rentang (docstatus < 2 — draft ikut, cancelled tidak;
	planned_start_date dari..sampai 23:59:59) dengan kolom gabungan
	RANGE_WO_FIELDS — satu query untuk yield, reject_over, suhu, dan
	hitungan WO direncanakan; PermissionError → kosong (endpoint tetap
	hidup, pola FU65)."""
	filters = [
		["docstatus", "<", 2],
		["planned_start_date", ">=", dari],
		["planned_start_date", "<=", f"{sampai} 23:59:59"],
	]
	if company:
		filters.append(["company", "=", company])
	try:
		return frappe.get_list(
			"Work Order", filters=filters, fields=list(RANGE_WO_FIELDS), limit_page_length=0
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
		alternate, factor = _item_display_uom(item)
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

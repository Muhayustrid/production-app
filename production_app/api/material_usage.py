# FU74 — agregat pemakaian bahan per Work Order (read-only).
#
# Menjawab satu pertanyaan supervisor: bahan apa yang terpakai MELEBIHI
# dasar rencananya? Tiga angka per bahan:
# - planned  = Σ required_qty (Work Order Item, stock UOM) atas WO dalam
#   rentang planned_start_date;
# - expected = planned diskalakan hasil native: required_qty ×
#   produced_qty / qty (preseden native scale-to-output stock_qty /
#   bom.quantity × qty) — overproduksi WAJAR tidak dihukum;
# - consumed = Σ Stock Entry Detail.transfer_qty (baris s_warehouse terisi)
#   untuk purpose Manufacture / Material Consumption for Manufacture,
#   dihitung LANGSUNG dari Stock Entry karena Work Order Item.consumed_qty
#   TIDAK andal (native melebihkan dengan +returned_qty, work_order.py, dan
#   konsumsi ad-hoc di luar required_items tak pernah tercatat di sana).
#   Retur (MTFM is_return=1) TIDAK mengurangi konsumsi — native membalik
#   TRANSFER, bukan konsumsi: get_available_materials hanya mengizinkan
#   retur dari sisa yang belum terpakai, dan get_consumed_qty tidak
#   mengurangi retur apa pun (quirk +returned_qty diperbaiki dengan
#   menghilangkannya, bukan menegasinya). Transfer biasa (MTFM non-return)
#   juga bukan konsumsi.
#
# Baris dengan variance_pct > MATERIAL_OVER_PCT atau konsumsi tanpa dasar
# (expected 0 tapi bahan jalan) ditandai `over`; bahan di luar semua
# required_items (`unlisted`, planned 0) dilaporkan terpisah. Urutan baris
# dan breakdown per WO: persen varian terbesar dulu, None (tanpa dasar)
# paling atas — paling memprihatinkan; seri → nama naik.
#
# Permission native `frappe.get_list` cukup (User Permission otomatis);
# PermissionError SENGAJA dibiarkan naik — pemanggil yang memutuskan
# degradasinya (dashboard menyembunyikan panel, pola FU65/FU73).
#
# FU79 — trace halaman penggunaan-bahan: aggregate(include_trace=True) menambah 3 kunci
# untuk kartu referensi baru di #/penggunaan-bahan (dashboard_summary sengaja TIDAK
# lewat flag agar payload dashboard tidak berubah — dipatok test):
# - work_orders  : WO dalam scope (rentang planned_start_date + produk +
#   company) dengan planned/produced terkonversi display UOM (pola
#   _planned_qty) — kartu "Penggunaan bahan"/"Work order";
# - transactions : baris konsumsi per SE Detail (purpose konsumsi,
#   s_warehouse terisi — definisi konsumsi yang sama dengan agregat) dengan
#   batch_no apa adanya, urut tanggal+nama desc, cap TRACE_TXN_CAP;
# - series       : hasil harian per display UOM zero-fill dari..sampai +
#   hitungan WO unik per hari (_tren_series, basis posting_date SE
#   Manufacture — beda basis dari work_orders, di-caption frontend).

import re
from io import BytesIO

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, today

from production_app.api.filter_params import filter_list as _filter_list
from production_app.api.production_plan import _conversion_factor

# Ambang `over` (% varian terhadap expected) — keputusan owner via mockup.
MATERIAL_OVER_PCT = 5.0
# Batas rentang query (dari..sampai) dalam hari — pelindung beban endpoint.
MAX_RANGE_DAYS = 92
# Batas baris `transactions` (pelindung payload; terbaru yang dipertahankan).
TRACE_TXN_CAP = 1000

# Konsumsi: bahan benar-benar terpakai produksi (query konsumsi WO native,
# work_order.get_consumed_qty — tanpa pengurangan retur, lihat docstring).
PURPOSIS_KONSUMSI = ("Manufacture", "Material Consumption for Manufacture")


def _display_uom_fn():
	"""Fungsi (item_code) → (satuan display, faktor) satu item — jembatan ke
	dashboard._item_display_uom. Import LAZY: dashboard mengimpor aggregate
	dari modul ini di level atas, import balik di level file melingkar."""

	def ambil(code):
		from production_app.api.dashboard import _item_display_uom

		try:
			item = frappe.get_cached_doc("Item", code)
		except frappe.DoesNotExistError:
			return None, None
		return _item_display_uom(item)

	return ambil


@frappe.whitelist()
def material_usage(
	dari=None,
	sampai=None,
	company=None,
	production_item=None,
	search=None,
	over_only=None,
	include_trace=None,
):
	"""Endpoint FU74 (+FU79) — agregat pemakaian bahan per rentang tanggal WO.
	Read-only; kontrak shape dipatok frontend (tests/test_dashboard.py):
	today/dari/sampai, companies, products (sebelum filter produk), rows
	per bahan (planned/expected/consumed/variance/variance_pct/over/unlisted
	+ breakdown work_orders per WO); include_trace → +work_orders/
	transactions/series untuk halaman #/penggunaan-bahan."""
	return aggregate(
		company=company,
		dari=dari,
		sampai=sampai,
		production_item=production_item,
		search=search,
		# param HTTP datang sebagai string — '0' truthy kalau tak di-cint
		# (review FU74 MAJOR-1; konvensi app bool(cint(...)), work_order.py)
		over_only=cint(over_only),
		include_trace=cint(include_trace),
	)


def _companies():
	"""Daftar company yang terlihat user (User Permission otomatis lewat
	get_list, urut nama); tanpa izin Company daftar kosong, bukan error.
	 Salinan pola dashboard._companies — diimpor balik akan melingkar karena
	dashboard justru mengimpor aggregate dari sini."""
	try:
		return frappe.get_list("Company", pluck="name", order_by="name")
	except frappe.PermissionError:
		return []


def _validasi_rentang(dari, sampai, max_days=None):
	"""(dari, sampai) sebagai string ISO ter-validasi; default keduanya hari
	ini. Tanggal rusak, terbalik, atau span > batas → ValidationError (HTTP
	417 konvensi app) — jangan diam-diam memotong rentang. `max_days`
	menimpa batas default MAX_RANGE_DAYS (dashboard FU76 memakai 366 agar
	preset "tahun ini" muat; halaman penggunaan-bahan tetap 92)."""
	batas = MAX_RANGE_DAYS if max_days is None else cint(max_days)
	try:
		tgl_dari = getdate(dari or today())
		tgl_sampai = getdate(sampai or today())
	except Exception:
		frappe.throw(
			"Tanggal tidak valid. Gunakan format YYYY-MM-DD.", exc=frappe.ValidationError
		)
	if tgl_dari > tgl_sampai:
		frappe.throw(
			"Tanggal awal (dari) tidak boleh setelah tanggal akhir (sampai).",
			exc=frappe.ValidationError,
		)
	if (tgl_sampai - tgl_dari).days > batas:
		frappe.throw(
			f"Rentang tanggal maksimal {batas} hari.",
			exc=frappe.ValidationError,
		)
	return str(tgl_dari), str(tgl_sampai)


def _kunci_varian(pct, nama):
	"""Kunci urut varian: None (tanpa dasar) paling atas, lalu persen
	menurun; seri → nama naik. Pembanding (False < True) menaruh None dulu."""
	return (pct is not None, -(pct or 0.0), nama or "")


def aggregate(
	company=None, dari=None, sampai=None, production_item=None, search=None, over_only=False,
	max_days=None, include_trace=False,
):
	"""Inti FU74 — lihat docstring modul untuk semantik angka. WO scope:
	docstatus < 2, planned_start_date dalam [dari, sampai 23:59:59], company
	opsional (get_list, User Permission otomatis); production_item (FU106:
	menerima LIST ala FU100 — IN, daftar kosong = tanpa filter) & search
	& over_only meneruskan hasil agregasi (bukan query). `max_days` (FU76)
	menimpa batas rentang default 92 hari — dashboard memakai 366.
	`include_trace` (FU79) menambah kunci work_orders/transactions/series —
	dipakai endpoint #/penggunaan-bahan, TIDAK oleh dashboard (payload tetap ramping)."""
	dari, sampai = _validasi_rentang(dari, sampai, max_days)
	produk_diminta = _filter_list(production_item, "produk")

	filters = [
		["docstatus", "<", 2],
		["planned_start_date", ">=", dari],
		["planned_start_date", "<=", f"{sampai} 23:59:59"],
	]
	if company:
		filters.append(["company", "=", company])
	wos = frappe.get_list(
		"Work Order",
		filters=filters,
		fields=[
			"name",
			"production_item",
			"item_name",
			"qty",
			"produced_qty",
			"company",
			# FU79: untuk kunci trace work_orders
			"bom_no",
			"status",
			"stock_uom",
			"planned_start_date",
		],
		limit_page_length=0,
	)

	# Daftar produk diambil SEBELUM filter production_item (kontrak FU74).
	produk_map = {}
	for w in wos:
		if w.production_item:
			produk_map.setdefault(w.production_item, w.item_name or w.production_item)

	if produk_diminta:
		wos = [w for w in wos if w.production_item in produk_diminta]

	wo_names = [w.name for w in wos]
	wo_by = {w.name: w for w in wos}

	# ---- rencana: Work Order Item child, satu get_all untuk semua WO
	planned = {}  # (wo, item) -> required_qty (stock UOM)
	expected = {}  # (wo, item) -> required_qty × produced/qty (qty <= 0 → 0)
	req_name, req_uom = {}, {}  # item_code -> nama/satuan dari rencana
	if wo_names:
		for r in frappe.get_all(
			"Work Order Item",
			filters={"parent": ("in", wo_names)},
			fields=["parent", "item_code", "item_name", "stock_uom", "required_qty"],
		):
			w = wo_by[r.parent]
			key = (r.parent, r.item_code)
			planned[key] = planned.get(key, 0.0) + flt(r.required_qty)
			# skala native ke hasil aktual; qty <= 0 tak punya dasar → 0
			proporsi = flt(w.produced_qty) / flt(w.qty) if flt(w.qty) > 0 else 0.0
			expected[key] = expected.get(key, 0.0) + flt(r.required_qty) * proporsi
			req_name.setdefault(r.item_code, r.item_name)
			req_uom.setdefault(r.item_code, r.stock_uom)

	# ---- realisasi: Stock Entry langsung (consumed_qty WO tidak andal)
	# Retur tidak diambil sama sekali — native membalik transfer, bukan
	# konsumsi (docstring modul). original_item dipakai agar BOM substitution
	# tetap terhitung pada bahan yang direncanakan (pola get_consumed_qty).
	gross = {}  # (wo, item) -> transfer_qty purpose konsumsi
	se_name, se_uom = {}, {}  # item_code -> nama/satuan fallback dari SE
	txn_raw = []  # FU79: baris konsumsi mentah (stock qty) utk kunci transactions
	if wo_names:
		ses = frappe.get_list(
			"Stock Entry",
			filters=[
				["work_order", "in", wo_names],
				["docstatus", "=", 1],
				["purpose", "in", list(PURPOSIS_KONSUMSI)],
			],
			fields=["name", "work_order", "posting_date"],
			limit_page_length=0,
		)
		# parent = nama SE; WO asalnya ikut dibaca dari baris SE
		se_wo_by = {s.name: s.work_order for s in ses}
		se_tgl = {s.name: str(getdate(s.posting_date)) for s in ses}
		if ses:
			for d in frappe.get_all(
				"Stock Entry Detail",
				filters={"parent": ("in", [s.name for s in ses]), "s_warehouse": ("is", "set")},
				fields=[
					"parent",
					"item_code",
					"original_item",
					"transfer_qty",
					"item_name",
					"stock_uom",
					"batch_no",
				],
			):
				code = d.original_item or d.item_code
				key = (se_wo_by[d.parent], code)  # parent dijamin anggota ses
				gross[key] = gross.get(key, 0.0) + flt(d.transfer_qty)
				se_name.setdefault(code, d.item_name)
				se_uom.setdefault(code, d.stock_uom)
				txn_raw.append(
					{
						"se": d.parent,
						"wo": key[0],
						"item_code": code,
						"item_name": d.item_name,
						"qty": flt(d.transfer_qty),
						"stock_uom": d.stock_uom,
						"batch": d.batch_no or None,
						"tanggal": se_tgl.get(d.parent),
					}
				)

	# ---- rangkai baris per bahan
	per_item = {}
	for key in set(planned) | set(gross):
		wo_name, code = key
		acc = per_item.setdefault(
			code,
			{"planned": 0.0, "expected": 0.0, "consumed": 0.0, "wo": []},
		)
		w = wo_by[wo_name]
		cons = gross.get(key, 0.0)
		exp = expected.get(key, 0.0)
		var = cons - exp
		pct = round(var / exp * 100, 6) if exp > 0 else None
		acc["planned"] += planned.get(key, 0.0)
		acc["expected"] += exp
		acc["consumed"] += cons
		acc["wo"].append(
			{
				"wo": wo_name,
				"produk": w.item_name or w.production_item,
				"planned": planned.get(key, 0.0),
				"expected": exp,
				"consumed": cons,
				"variance": var,
				"variance_pct": pct,
				"over": (pct is not None and pct > MATERIAL_OVER_PCT)
				or (exp <= 0 and cons > 0),
				"produced_qty": flt(w.produced_qty),
				"qty": flt(w.qty),
			}
		)

	rows = []
	for code, acc in per_item.items():
		planned_total = acc["planned"]
		expected_total = acc["expected"]
		consumed_total = acc["consumed"]
		variance_total = consumed_total - expected_total
		pct_total = (
			round(variance_total / expected_total * 100, 6) if expected_total > 0 else None
		)
		rows.append(
			{
				"item_code": code,
				"item_name": req_name.get(code) or se_name.get(code) or code,
				"uom": req_uom.get(code) or se_uom.get(code) or "",
				"planned": planned_total,
				"expected": expected_total,
				"consumed": consumed_total,
				"variance": variance_total,
				"variance_pct": pct_total,
				"over": (pct_total is not None and pct_total > MATERIAL_OVER_PCT)
				or (expected_total <= 0 and consumed_total > 0),
				"unlisted": planned_total == 0,
				"work_orders": sorted(
					acc["wo"], key=lambda e: _kunci_varian(e["variance_pct"], e["wo"])
				),
			}
		)
	rows.sort(key=lambda r: _kunci_varian(r["variance_pct"], r["item_code"]))

	# FU78: konversi baris ke Default Inventory UOM item (rantai W21 →
	# stock_uom, pola dashboard) — dashboard DAN halaman penggunaan-bahan menampilkan
	# satuan yang sama (keputusan owner FU78). Tanpa faktor valid → baris
	# TETAP stock UOM (baris tidak pernah dibuang); variance_pct kebal
	# konversi karena pembilang & penyebut terbagi faktor sama.
	for row in rows:
		try:
			item = frappe.get_cached_doc("Item", row["item_code"])
		except frappe.DoesNotExistError:
			continue
		alternate = item.get("custom_default_inventory_unit_of_measure") or item.stock_uom
		factor = _conversion_factor(item, alternate)
		if not factor or alternate == row["uom"]:
			continue
		for k in ("planned", "expected", "consumed"):
			row[k] = round(flt(row[k]) / factor, 3)
		row["variance"] = round(row["consumed"] - row["expected"], 3)
		row["uom"] = alternate
		for w in row["work_orders"]:
			for k in ("planned", "expected", "consumed"):
				w[k] = round(flt(w[k]) / factor, 3)
			w["variance"] = round(w["consumed"] - w["expected"], 3)

	# search & over_only menyaring HASIL agregasi (nilai baris tetap penuh)
	if search:
		cari = search.strip().lower()
		rows = [
			r
			for r in rows
			if cari in r["item_code"].lower() or cari in (r["item_name"] or "").lower()
		]
	if over_only:
		rows = [r for r in rows if r["over"]]

	hasil = {
		"today": today(),
		"dari": dari,
		"sampai": sampai,
		"companies": _companies(),
		"products": [
			{"item_code": code, "item_name": nama}
			for code, nama in sorted(produk_map.items(), key=lambda kv: kv[1])
		],
		"rows": rows,
	}

	if include_trace:
		hasil["work_orders"] = _trace_work_orders(wos, _display_uom_fn())
		hasil["transactions"] = _trace_transactions(txn_raw, _display_uom_fn())
		hasil["series"] = _tren_series(dari, sampai, company)
	return hasil


def _trace_work_orders(wos, display_uom):
	"""FU79: WO scope rentang+produk → kartu trace #/penggunaan-bahan. planned/produced
	dikonversi display UOM (pola _planned_qty: qty stock ÷ faktor; tanpa
	faktor valid → tetap stock UOM, baris tidak dibuang). Urut tanggal mulai
	desc lalu nama — baris terbaru di atas."""
	out = []
	for w in wos:
		alternate, factor = display_uom(w.production_item)
		f = factor or 1
		out.append(
			{
				"wo": w.name,
				"produk": w.item_name or w.production_item,
				"bom": w.bom_no or "",
				"status": w.status or "",
				"tanggal": str(getdate(w.planned_start_date)),
				"planned_qty": round(flt(w.qty) / f, 3),
				"produced_qty": round(flt(w.produced_qty) / f, 3),
				"uom": alternate or w.stock_uom or "",
			}
		)
	out.sort(key=lambda e: (e["tanggal"], e["wo"]), reverse=True)
	return out


def _trace_transactions(txn_raw, display_uom):
	"""FU79: baris konsumsi per SE Detail — definisi konsumsi yang SAMA dengan
	aparit agregat (purpose konsumsi, s_warehouse terisi). Qty dikonversi
	display UOM (pola _planned_qty; tanpa faktor → stock UOM). Urut tanggal
	desc lalu nama SE desc, cap TRACE_TXN_CAP terbaru."""
	out = []
	for t in txn_raw:
		alternate, factor = display_uom(t["item_code"])
		f = factor or 1
		out.append(
			{
				"se": t["se"],
				"tanggal": t["tanggal"],
				"wo": t["wo"],
				"item_code": t["item_code"],
				"item_name": t["item_name"] or t["item_code"],
				"qty": round(t["qty"] / f, 3),
				"uom": alternate or t["stock_uom"] or "",
				"batch": t["batch"],
			}
		)
	out.sort(key=lambda e: (e["tanggal"] or "", e["se"]), reverse=True)
	return out[:TRACE_TXN_CAP]


def _tren_series(dari, sampai, company):
	"""FU79: hasil harian per display UOM untuk kartu "Tren produksi" — qty
	fg SE Manufacture per posting_date + banyaknya WO unik yang memproduksi
	hari itu (SE tanpa WO tidak masuk hitungan WO). Zero-fill penuh
	dari..sampai agar label tanggal frontend tidak bolong. Basis tanggal
	berbeda dari kunci work_orders (planned_start_date) — di-caption
	frontend. PermissionError → [] (pola FU65)."""
	span = (getdate(sampai) - getdate(dari)).days
	periods = [str(add_days(getdate(dari), i)) for i in range(span + 1)]
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
			"Stock Entry",
			filters=se_filters,
			fields=["name", "posting_date", "work_order"],
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return []
	qty = {}  # (uom, period) -> total hasil (display)
	wo_harian = {}  # (uom, period) -> set nama WO
	if ses:
		display_uom = _display_uom_fn()
		se_meta = {s.name: s for s in ses}
		for r in frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": ("in", [s.name for s in ses]), "is_finished_item": 1},
			fields=["parent", "item_code", "transfer_qty", "qty"],
		):
			alternate, factor = display_uom(r.item_code)
			if not factor:
				continue  # tanpa konversi valid: skip, jangan mengarang faktor
			m = se_meta[r.parent]
			k = (alternate, str(m.posting_date))
			qty[k] = qty.get(k, 0.0) + flt(r.transfer_qty or r.qty) / factor
			if m.work_order:
				wo_harian.setdefault(k, set()).add(m.work_order)

	def total(uom):
		return sum(v for (u, _), v in qty.items() if u == uom)

	uoms = sorted({u for u, _ in qty}, key=lambda u: (-total(u), u))
	return [
		{
			"uom": uom,
			"rows": [
				{
					"period": p,
					"produced": flt(qty.get((uom, p))),
					"wo": len(wo_harian.get((uom, p)) or ()),
				}
				for p in periods
			],
		}
		for uom in uoms
	]


# ---- FU80c: ekspor .xlsx laporan pemakaian bahan (mengganti CSV FU80
# atas permintaan user) ------------------------------------------------------

# Terjemahan status WO utk laporan (paritas woStatusText frontend).
STATUS_WO_ID = {
	"Draft": "Draft",
	"Not Started": "Belum mulai",
	"In Process": "Berjalan",
	"Stopped": "Berhenti",
	"Completed": "Selesai",
	"Cancelled": "Dibatalkan",
}


def _yield_persen(planned, produced):
	"""Persen hasil thd rencana (1 desimal, pola woYieldPct frontend);
	rencana 0 → None (sel kosong, bukan nol palsu)."""
	p, h = flt(planned), flt(produced)
	if p <= 0:
		return None
	return round(h / p * 100, 1)


def _keterangan_bahan(r):
	"""Keterangan baris ringkasan — paritas Keterangan CSV FU80."""
	if r.get("unlisted"):
		return "tanpa rencana"
	if r.get("variance_pct") is None:
		return "tanpa dasar"
	return ""


def _nama_file_xlsx(produk, dari, sampai):
	"""penggunaan-bahan-[<produk-slug>-]<dari|dari_sd_sampai> — paritas
	bahanXlsxFilename frontend (slug lowercase, non-alfanumerik → '-')."""
	slug = re.sub(r"[^a-z0-9]+", "-", (produk or "").lower()).strip("-")
	inti = dari if dari == sampai else f"{dari}_sd_{sampai}"
	return "penggunaan-bahan" + (f"-{slug}" if slug else "") + f"-{inti}"


@frappe.whitelist()
def material_usage_xlsx(
	dari=None,
	sampai=None,
	company=None,
	production_item=None,
	search=None,
	over_only=None,
):
	"""FU80c — unduh .xlsx laporan pemakaian bahan (ganti CSV FU80): 4 sheet
	Info (meta filter + waktu cetak), Ringkasan per Bahan, Work Order
	(riwayat produksi per order), Transaksi (konsumsi per SE Detail).
	Data = aggregate(include_trace) dgn parameter SAMA dgn halaman #/penggunaan-bahan →
	angka file = angka layar. Angka mentah numerik (bukan teks berformat)
	supaya bisa dihitung ulang di Excel/Sheets; rentang di-validasi sama
	(ValidationError 417 bila terbalik/terlalu panjang).
	FU106: production_item menerima LIST ala FU100 (frontend mengirim JSON
	array lewat query string — filter_list yang mem-parse); label Info dan
	slug nama file mengikuti: satu produk → namanya, banyak → "N produk"
	(nama file generik tanpa slug, paritas materialUsageXlsxFilename)."""
	data = aggregate(
		company=company,
		dari=dari,
		sampai=sampai,
		production_item=production_item,
		search=search,
		over_only=cint(over_only),
		include_trace=True,
	)

	d, s = data["dari"], data["sampai"]
	tgl = lambda t: getdate(t).strftime("%d-%m-%Y")  # noqa: E731
	rentang = tgl(d) if d == s else f"{tgl(d)} s.d. {tgl(s)}"
	# FU106: label produk untuk Info + slug nama file — satu produk pakai
	# namanya (paritas frontend), banyak produk = generik tanpa slug
	produk_diminta = _filter_list(production_item, "produk")
	nama_produk = None
	if len(produk_diminta) == 1:
		kode = produk_diminta[0]
		for p in data.get("products") or []:
			if p.get("item_code") == kode:
				nama_produk = p.get("item_name") or kode
				break
		nama_produk = nama_produk or kode
	elif len(produk_diminta) > 1:
		nama_produk = f"{len(produk_diminta)} produk"
	produk_label = nama_produk or ""
	nama_produk = nama_produk if len(produk_diminta) <= 1 else ""

	info = [
		["Ekspor Penggunaan Bahan Baku", ""],
		["Rentang", rentang],
		["Company", company or "Semua company"],
		["Produk", produk_label or "Semua produk"],
	]
	if (search or "").strip():
		info.append(["Pencarian", search.strip()])
	if cint(over_only):
		info.append(["Hanya di atas rencana", "Ya"])
	info.append(["Dicetak", now_datetime().strftime("%d-%m-%Y %H:%M")])

	ringkasan = [
		["Kode", "Nama", "UOM", "Teoritis", "Aktual", "Selisih", "Selisih %", "Status", "Keterangan"]
	]
	for r in data.get("rows") or []:
		pct = r.get("variance_pct")
		ringkasan.append(
			[
				r.get("item_code") or "",
				r.get("item_name") or r.get("item_code") or "",
				r.get("uom") or "",
				flt(r.get("expected")),
				flt(r.get("consumed")),
				flt(r.get("variance")),
				round(flt(pct), 3) if pct is not None else None,
				"Over" if r.get("over") else "Normal",
				_keterangan_bahan(r),
			]
		)

	wo_rows = [
		["Work Order", "Tanggal", "Produk", "BOM", "Rencana", "Hasil", "UOM", "Yield %", "Status"]
	]
	for w in data.get("work_orders") or []:
		wo_rows.append(
			[
				w.get("wo") or "",
				w.get("tanggal") or "",
				w.get("produk") or "",
				w.get("bom") or "",
				flt(w.get("planned_qty")),
				flt(w.get("produced_qty")),
				w.get("uom") or "",
				_yield_persen(w.get("planned_qty"), w.get("produced_qty")),
				STATUS_WO_ID.get(w.get("status"), w.get("status") or ""),
			]
		)

	trx = [["Stock Entry", "Tanggal", "Work Order", "Bahan", "Kode", "Qty", "UOM", "Batch"]]
	for t in data.get("transactions") or []:
		trx.append(
			[
				t.get("se") or "",
				t.get("tanggal") or "",
				t.get("wo") or "",
				t.get("item_name") or "",
				t.get("item_code") or "",
				flt(t.get("qty")),
				t.get("uom") or "",
				t.get("batch") or "",
			]
		)

	# multi-sheet: satu workbook di-share ke make_xlsx (frappe menutup hanya
	# workbook buatannya sendiri — punya sendiri ditutup manual di sini);
	# import berat hanya saat benar-benar mengekspor
	import xlsxwriter
	from frappe.desk.utils import provide_binary_file
	from frappe.utils.xlsxutils import make_xlsx

	bio = BytesIO()
	wb = xlsxwriter.Workbook(bio, {"in_memory": True})
	for nama_sheet, baris in (
		("Info", info),
		("Ringkasan per Bahan", ringkasan),
		("Work Order", wo_rows),
		("Transaksi", trx),
	):
		make_xlsx(baris, nama_sheet, wb=wb)
	wb.close()
	provide_binary_file(
		_nama_file_xlsx(nama_produk, d, s), "xlsx", bio.getvalue()
	)

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

import frappe
from frappe.utils import cint, flt, getdate, today

# Ambang `over` (% varian terhadap expected) — keputusan owner via mockup.
MATERIAL_OVER_PCT = 5.0
# Batas rentang query (dari..sampai) dalam hari — pelindung beban endpoint.
MAX_RANGE_DAYS = 92

# Konsumsi: bahan benar-benar terpakai produksi (query konsumsi WO native,
# work_order.get_consumed_qty — tanpa pengurangan retur, lihat docstring).
PURPOSIS_KONSUMSI = ("Manufacture", "Material Consumption for Manufacture")


@frappe.whitelist()
def material_usage(
	dari=None, sampai=None, company=None, production_item=None, search=None, over_only=None
):
	"""Endpoint FU74 — agregat pemakaian bahan per rentang tanggal WO.
	Read-only; kontrak shape dipatok frontend (tests/test_dashboard.py):
	today/dari/sampai, companies, products (sebelum filter produk), rows
	per bahan (planned/expected/consumed/variance/variance_pct/over/unlisted
	+ breakdown work_orders per WO)."""
	return aggregate(
		company=company,
		dari=dari,
		sampai=sampai,
		production_item=production_item,
		search=search,
		# param HTTP datang sebagai string — '0' truthy kalau tak di-cint
		# (review FU74 MAJOR-1; konvensi app bool(cint(...)), work_order.py)
		over_only=cint(over_only),
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
	preset "tahun ini" muat; halaman bahan tetap 92)."""
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
	max_days=None,
):
	"""Inti FU74 — lihat docstring modul untuk semantik angka. WO scope:
	docstatus < 2, planned_start_date dalam [dari, sampai 23:59:59], company
	opsional (get_list, User Permission otomatis); production_item & search
	& over_only meneruskan hasil agregasi (bukan query). `max_days` (FU76)
	menimpa batas rentang default 92 hari — dashboard memakai 366."""
	dari, sampai = _validasi_rentang(dari, sampai, max_days)

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
		fields=["name", "production_item", "item_name", "qty", "produced_qty", "company"],
		limit_page_length=0,
	)

	# Daftar produk diambil SEBELUM filter production_item (kontrak FU74).
	produk_map = {}
	for w in wos:
		if w.production_item:
			produk_map.setdefault(w.production_item, w.item_name or w.production_item)

	if production_item:
		wos = [w for w in wos if w.production_item == production_item]

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
	if wo_names:
		ses = frappe.get_list(
			"Stock Entry",
			filters=[
				["work_order", "in", wo_names],
				["docstatus", "=", 1],
				["purpose", "in", list(PURPOSIS_KONSUMSI)],
			],
			fields=["name", "work_order"],
			limit_page_length=0,
		)
		# parent = nama SE; WO asalnya ikut dibaca dari baris SE
		se_wo_by = {s.name: s.work_order for s in ses}
		if ses:
			for d in frappe.get_all(
				"Stock Entry Detail",
				filters={"parent": ("in", [s.name for s in ses]), "s_warehouse": ("is", "set")},
				fields=["parent", "item_code", "original_item", "transfer_qty", "item_name", "stock_uom"],
			):
				code = d.original_item or d.item_code
				key = (se_wo_by[d.parent], code)  # parent dijamin anggota ses
				gross[key] = gross.get(key, 0.0) + flt(d.transfer_qty)
				se_name.setdefault(code, d.item_name)
				se_uom.setdefault(code, d.stock_uom)

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

	return {
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

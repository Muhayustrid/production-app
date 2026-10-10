# FU87 — ekspor XLSX halaman "Ketersediaan Stock" (#/ketersediaan-stock).
#
# Data halaman MASIH MOCK di frontend (store.loadStockAvailability →
# dashboard.stockMockDataset; struktur item = respons ERPNext nanti: Bin
# actual/reserved + Item grup/uom + SLE movement). Endpoint ini JEMBATAN:
# halaman mengirim baris yang sedang tampil (sudah terfilter) → angka file =
# angka layar by construction. Saat integrasi ERPNext nyata, agregasi pindah
# ke server dan endpoint tinggal memanggil agregat itu — bentuk sheet tetap.
#
# 3 sheet: Info (meta + ringkasan KPI + waktu cetak), Stock Bahan Baku
# (kolom = tabel layar, angka MENTAH numerik supaya bisa dihitung ulang di
# Excel/Sheets), Kapasitas per Resep (capacity_detail diratakan per resep).

import json
import math
import re
from io import BytesIO

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from production_app.api.production_plan import _conversion_factor

STATUS_LABEL = {"aman": "Aman", "menipis": "Menipis", "habis": "Habis"}


def _siapkan_sheet(items, summary, warehouse):
	"""Susun baris ketiga sheet (pure — teruji tanpa konteks request/DB)."""
	info = [
		["Ekspor Ketersediaan Stock Bahan Baku", ""],
		["Gudang", warehouse or "Gudang Produksi"],
		["Jumlah Item", len(items)],
		["Stock Aman", cint(summary.get("aman"))],
		["Stock Menipis", cint(summary.get("menipis"))],
		["Stock Habis", cint(summary.get("habis"))],
		["Dicetak", now_datetime().strftime("%d-%m-%Y %H:%M")],
	]
	# FU88: 4 kolom qty mengikuti layar = UOM tampilan (Default Inventory UOM,
	# dikonversi klien); kolom terakhir menyimpan stok mentah stock UOM (ledger)
	baris = [
		[
			"Kode Item", "Nama Item", "Grup Item", "Stok", "Reserved", "Tersedia",
			"UOM", "Stok Minimum", "Status", "Kapasitas (Batch)", "Stok (Stock UOM)",
		]
	]
	kapasitas = [["Kode Item", "Nama Item", "Produk Resep", "Kapasitas (Batch)"]]
	for it in items:
		baris.append(
			[
				it.get("item_code") or "",
				it.get("item_name") or "",
				it.get("item_group") or "",
				flt(it.get("stok_diu")),
				flt(it.get("reserved_diu")),
				flt(it.get("tersedia_diu")),
				it.get("uom_tampilan") or it.get("stock_uom") or "",
				"" if it.get("minimum_diu") is None else flt(it.get("minimum_diu")),
				STATUS_LABEL.get(it.get("status"), it.get("status") or ""),
				"" if it.get("capacity_batch") is None else cint(it.get("capacity_batch")),
				flt(it.get("actual_qty")),
			]
		)
		for r in it.get("capacity_detail") or []:
			kapasitas.append(
				[
					it.get("item_code") or "",
					it.get("item_name") or "",
					r.get("product") or "",
					cint(r.get("batches")),
				]
			)
	return info, baris, kapasitas


def _nama_file_xlsx(gudang=None):
	"""Paritas dgn stockXlsxFilename di frontend (workspace_frontend/src/dashboard.js)."""
	slug = re.sub(r"[^a-z0-9]+", "-", (gudang or "").lower()).strip("-")
	return f"ketersediaan-stock-{slug + '-' if slug else ''}{nowdate()}.xlsx"


@frappe.whitelist()
def export_xlsx(items=None, summary=None, warehouse=None):
	"""FU87 — unduh .xlsx Ketersediaan Stock: halaman mengirim baris terfilter
	yang sedang tampil (mock FU83) + ringkasan KPI; server membungkusnya jadi
	workbook 3 sheet (Info / Stock Bahan Baku / Kapasitas per Resep)."""
	if isinstance(items, str):
		items = json.loads(items or "[]")
	if isinstance(summary, str):
		summary = json.loads(summary or "{}")
	info, baris, kapasitas = _siapkan_sheet(items or [], summary or {}, warehouse)

	# import berat hanya saat benar-benar mengekspor (pola material_usage_xlsx)
	import xlsxwriter
	from frappe.desk.utils import provide_binary_file
	from frappe.utils.xlsxutils import make_xlsx

	bio = BytesIO()
	wb = xlsxwriter.Workbook(bio, {"in_memory": True})
	for nama_sheet, sheet_rows in (
		("Info", info),
		("Stock Bahan Baku", baris),
		("Kapasitas per Resep", kapasitas),
	):
		make_xlsx(sheet_rows, nama_sheet, wb=wb)
	wb.close()
	provide_binary_file(_nama_file_xlsx(warehouse), "xlsx", bio.getvalue())


# FU90 — integrasi ERPNext nyata utk halaman Ketersediaan Stock
# (PROMPT_INTEGRASI_KETERSEDIAAN_STOCK.md): stock_availability() menggantikan
# mock frontend (Bin + Item + Item Reorder + BOM nyata); movement jadi
# endpoint lazy TERPISAH stock_movements(). export_xlsx di atas TETAP
# JEMBATAN (keputusan terkunci — jangan disentuh). Helper murni
# (_status_stock/_min_stock_item/_kapasitas_dari_bom/_peta_movement) tanpa
# DB supaya bisa diuji plain unittest; bacaan field custom lewat SELECT *
# (pelajaran FU58 — kolom custom jangan pernah disebut di daftar kolom).


def _warehouses_ber_bin(company=None):
	"""Gudang yang punya Bin, urut abjad (sumber selector halaman).
	FU95: company opsional — hanya gudang milik company itu (Bin tidak punya
	kolom company; scope lewat Warehouse.company)."""
	warehouses = frappe.get_all("Bin", distinct=True, pluck="warehouse", order_by="warehouse")
	if company and warehouses:
		warehouses = frappe.get_all(
			"Warehouse",
			filters={"name": ("in", warehouses), "company": company},
			pluck="name",
			order_by="name",
		)
	return warehouses


def _gudang_default(warehouses):
	"""Default gudang bila halaman tak mengirim param: setting gudang asal
	bahan baku FU58 (Manufacturing Settings.custom_default_source_warehouse)
	bila terisi dan ber-Bin; kalau tidak gudang pertama urut abjad ber-Bin."""
	from production_app.api.work_order import _warehouse_defaults  # dibuka malas (rantai impor berat)

	source = (_warehouse_defaults() or {}).get("source_warehouse")
	if source and source in warehouses:
		return source
	return warehouses[0] if warehouses else None


def _status_stock(available, min_stock):
	"""Doktrin halaman (stockStatus FU83): tersedia ≤ 0 habis; di bawah
	minimum menipis; sisanya aman (minimum kosong tak pernah menipis)."""
	if available <= 0:
		return "habis"
	if min_stock is not None and available < min_stock:
		return "menipis"
	return "aman"


def _min_stock_item(item, rows, warehouse):
	"""Minimum stok (stock UOM) dari baris Item Reorder utk gudang ini.
	warehouse_uom terisi dan ≠ stock_uom → konversi dgn faktor item-specific
	(`item` harus punya .uoms — doc penuh); faktor tak valid → None (jangan
	mengarang). Tanpa baris gudang ini → None. Catatan v16 terpasang: Item
	Reorder TANPA kolom warehouse_uom — dibaca .get() defensif supaya tak
	pernah InvalidColumnName; cabang konversi hidup bila versi menambahkan."""
	for row in rows:
		if row.get("warehouse") != warehouse:
			continue
		level = flt(row.get("warehouse_reorder_level"))
		row_uom = row.get("warehouse_uom")
		if not row_uom or row_uom == item.get("stock_uom"):
			return level
		factor = _conversion_factor(item, row_uom)
		return level * factor if factor else None
	return None


def _kapasitas_dari_bom(available, boms):
	"""Kapasitas produksi per bahan (pure). available: {item_code: tersedia
	stock UOM}; boms: [(nama produk FG, [(item_code, kebutuhan stock/batch)])].
	Satu batch = satu eksekusi penuh BOM (tanpa normalisasi qty). Baris
	kebutuhan ≤ 0 di-skip; bahan di luar gudang (tak ada di available)
	diabaikan; FG tanpa bahan gudang ini tidak masuk. Batch per FG = min
	floor(tersedia/kebutuhan); per bahan capacity_batch = max antar-FG.
	Return {item_code: (capacity_batch, detail urut batches desc, nama asc)}."""
	terkumpul = {}
	for produk, rows in boms:
		fg_batches = {}
		for code, need in rows:
			if need <= 0 or code not in available:
				continue
			# ponytail: clamp 0 — tersedia negatif tak menghasilkan batch negatif
			bisa = max(0, math.floor(flt(available[code]) / need))
			fg_batches[code] = min(fg_batches.get(code, bisa), bisa)
		for code, batches in fg_batches.items():
			per_fg = terkumpul.setdefault(code, {})
			per_fg[produk] = max(per_fg.get(produk, 0), batches)
	return {
		code: (
			max(per_fg.values()),
			sorted(
				({"product": p, "batches": b} for p, b in per_fg.items()),
				key=lambda e: (-e["batches"], e["product"]),
			),
		)
		for code, per_fg in terkumpul.items()
	}


def _peta_movement(row):
	"""Satu SLE → baris movement drawer (masuk/keluar positif, saldo ledger)."""
	qty = flt(row.get("actual_qty"))
	tanggal = row.get("posting_date")
	return {
		"tanggal": tanggal.isoformat() if tanggal else None,
		"jenis": row.get("voucher_type"),
		"referensi": row.get("voucher_no"),
		"masuk": qty if qty > 0 else 0.0,
		"keluar": -qty if qty < 0 else 0.0,
		"saldo": flt(row.get("qty_after_transaction")),
	}


def _bom_resep_gudang(codes, company=None):
	"""Resep (BOM docstatus 1 + is_active 1) yang memakai bahan dari set
	kode gudang ini → [(nama FG, [(item_code, kebutuhan stock/batch)])].
	Satu BOM per FG: is_default menang, lalu nama pertama. Kebutuhan =
	qty × conversion_factor baris BOM Item (kedua kolom terverifikasi ada
	di v16 terpasang — hasil stock UOM). FG tanpa baris bahan gudang ini
	tidak masuk (pemanggil memutuskan dari daftar kosong).
	FU95: company opsional — kapasitas hanya dari resep company itu."""
	rows = frappe.get_all(
		"BOM Item",
		filters={"parenttype": "BOM", "item_code": ("in", codes)},
		fields=["parent", "item_code", "qty", "conversion_factor"],
	)
	if not rows:
		return []
	bom_filters = {
		"name": ("in", sorted({r.parent for r in rows})),
		"docstatus": 1,
		"is_active": 1,
	}
	if company:
		bom_filters["company"] = company
	headers = frappe.get_all(
		"BOM",
		filters=bom_filters,
		fields=["name", "item", "is_default"],
		order_by="is_default desc, name asc",
	)
	if not headers:
		return []
	terpilih = {}
	for h in headers:  # is_default dulu, lalu nama — first wins per FG
		terpilih.setdefault(h.item, h.name)
	nama_fg = {
		d.name: d.item_name
		for d in frappe.get_all(
			"Item", filters={"name": ("in", sorted(terpilih))}, fields=["name", "item_name"]
		)
	}
	kebutuhan = {}
	for r in rows:
		if r.parent in terpilih.values():
			kebutuhan.setdefault(r.parent, []).append(
				(r.item_code, flt(r.qty) * flt(r.conversion_factor))
			)
	return [(nama_fg.get(fg, fg), kebutuhan.get(bom, [])) for fg, bom in terpilih.items()]


@frappe.whitelist()
def stock_availability(warehouse=None, company=None):
	"""FU90 — data halaman Ketersediaan Stock dari ERPNext nyata: Bin
	(actual/reserved) + Item + Item Reorder (minimum) + BOM (kapasitas).
	Kebijakan akses: pengguna login workspace dengan izin baca Item (server
	sumber kebenaran — pola gate eksplisit dashboard.py). Movement lazy di
	stock_movements() — sengaja TIDAK ikut di sini. Angka float mentah (flt)
	tanpa pembulatan — klien yang memformat.
	FU95: `company` opsional (filter company global) — daftar gudang &
	kapasitas resep ikut ter-scope company itu; warehouse kosong → gudang
	default DALAM scope company."""
	if not frappe.has_permission("Item", "read"):
		frappe.throw(_("Tidak punya izin membaca Item"), frappe.PermissionError)
	warehouses = _warehouses_ber_bin(company)
	if not warehouse:
		warehouse = _gudang_default(warehouses)
	elif company and warehouse not in warehouses:
		# FU95: gudang terpilih di luar scope company (klien baru ganti company)
		# → kembali ke default DALAM scope; tanpa company, perilaku lama
		# dipertahankan apa adanya (gudang tak dikenal tetap dijawab kosong).
		warehouse = _gudang_default(warehouses) or None

	bins = []
	if warehouse:
		bins = frappe.get_all(
			"Bin",
			filters={"warehouse": warehouse},
			fields=["item_code", "actual_qty", "reserved_qty"],
			order_by="item_code",
		)
	codes = [b.item_code for b in bins]
	bin_by_code = {b.item_code: b for b in bins}

	item_rows = {}
	if codes:
		# SELECT * — kolom custom jangan pernah disebut di daftar kolom (FU58)
		for row in frappe.db.get_values(
			"Item",
			{"name": ("in", codes), "is_stock_item": 1, "disabled": 0},
			"*",
			order_by="name",
		):
			item_rows[row.name] = row

	available = {
		code: flt(bin_by_code[code].actual_qty) - flt(bin_by_code[code].reserved_qty)
		for code in item_rows
	}

	reorder = {}
	if codes:
		for r in frappe.get_all(
			"Item Reorder",
			filters={"parenttype": "Item", "parent": ("in", codes)},
			fields=["parent", "warehouse", "warehouse_reorder_level"],
		):
			reorder.setdefault(r.parent, []).append(r)

	from production_app.api.dashboard import _item_display_uom  # dibuka malas (pola material_usage)

	kapasitas = _kapasitas_dari_bom(available, _bom_resep_gudang(sorted(available), company)) if available else {}

	items = []
	for code in sorted(available):
		row = item_rows[code]
		actual = flt(bin_by_code[code].actual_qty)
		reserved = flt(bin_by_code[code].reserved_qty)
		diu = row.get("custom_default_inventory_unit_of_measure")
		display_uom = qty_in_pack = None
		if diu:
			_, factor = _item_display_uom(frappe.get_cached_doc("Item", code))
			if factor:
				display_uom, qty_in_pack = diu, factor
		rows = reorder.get(code) or []
		if any(r.get("warehouse_uom") not in (None, "", row.stock_uom) for r in rows):
			# cabang konversi butuh doc penuh (.uoms) — tak pernah terjadi di
			# v16 terpasang (Item Reorder tanpa kolom itu), dipertahankan utk versi depan
			min_stock = _min_stock_item(frappe.get_cached_doc("Item", code), rows, warehouse)
		else:
			min_stock = _min_stock_item(row, rows, warehouse)
		cap_batch, cap_detail = kapasitas.get(code, (None, []))
		items.append(
			{
				"item_code": code,
				"item_name": row.get("item_name"),
				"item_group": row.get("item_group"),
				"stock_uom": row.stock_uom,
				"actual_qty": actual,
				"reserved_qty": reserved,
				"available": actual - reserved,
				"display_uom": display_uom,
				"qty_in_pack": qty_in_pack,
				"min_stock": min_stock,
				"status": _status_stock(actual - reserved, min_stock),
				"capacity_batch": cap_batch,
				"capacity_detail": cap_detail,
				"warehouse": warehouse,
			}
		)

	summary = {"total": len(items)}
	for status in ("aman", "menipis", "habis"):
		summary[status] = sum(1 for i in items if i["status"] == status)
	return {
		"warehouse": warehouse,
		"warehouses": warehouses,
		"generated_at": now_datetime().isoformat(),
		"summary": summary,
		"items": items,
	}


@frappe.whitelist()
def stock_movements(item_code=None, warehouse=None):
	"""FU90 — drawer Stock Movement: ≤10 Stock Ledger Entry terbaru gudang
	itu (posting terbaru dulu; saldo = qty_after_transaction ledger).
	Kebijakan akses: pengguna login workspace dengan izin baca Stock Ledger
	Entry (server sumber kebenaran — pola gate eksplisit dashboard.py).
	is_cancelled ada di SLE v16 terpasang → ledger batal tidak ditampilkan."""
	if not frappe.has_permission("Stock Ledger Entry", "read"):
		frappe.throw(_("Tidak punya izin melihat pergerakan stok"), frappe.PermissionError)
	if not item_code:
		frappe.throw(_("Pilih item dulu untuk melihat pergerakan stok"))
	warehouses = _warehouses_ber_bin()
	if not warehouse:
		warehouse = _gudang_default(warehouses)
	if not warehouse:
		return []
	rows = frappe.get_all(
		"Stock Ledger Entry",
		filters={"item_code": item_code, "warehouse": warehouse, "is_cancelled": 0},
		fields=["posting_date", "voucher_type", "voucher_no", "actual_qty", "qty_after_transaction"],
		order_by="posting_date desc, posting_time desc, creation desc, name desc",
		limit_page_length=10,
	)
	return [_peta_movement(r) for r in rows]

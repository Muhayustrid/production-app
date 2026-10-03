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
import re
from io import BytesIO

import frappe
from frappe.utils import cint, flt, now_datetime, nowdate

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
				flt(it.get("minimum_diu")),
				STATUS_LABEL.get(it.get("status"), it.get("status") or ""),
				cint(it.get("capacity_batch")),
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

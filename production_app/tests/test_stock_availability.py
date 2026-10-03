# FU87 — ekspor XLSX Ketersediaan Stock: JEMBATAN baris tampilan halaman
# (mock FU83) → workbook 3 sheet. _siapkan_sheet/_nama_file_xlsx pure
# (tanpa DB — plain unittest); export_xlsx dibuktikan menghasilkan binary
# zip dgn nama file paritas helper frontend (pola test FU80c di test_dashboard).

import unittest
from io import BytesIO

import frappe

from production_app.api.stock_availability import (
	_nama_file_xlsx,
	_siapkan_sheet,
	export_xlsx,
)

# FU88: klien mengonversi qty ke UOM tampilan (DIU) sebelum mengirim —
# stok_diu/reserved_diu/tersedia_diu/minimum_diu + uom_tampilan; actual_qty
# tetap stock UOM utk kolom "Stok (Stock UOM)".
SAMPLE_ITEMS = [
	{
		"item_code": "RM-FLOUR-001",
		"item_name": "Tepung Terigu",
		"item_group": "Bahan Baku",
		"actual_qty": 125,
		"stock_uom": "kg",
		"uom_tampilan": "kg",
		"stok_diu": 125,
		"reserved_diu": 20,
		"tersedia_diu": 105,
		"minimum_diu": 100,
		"status": "aman",
		"capacity_batch": 4,
		"capacity_detail": [
			{"product": "Dough Coklat", "batches": 4},
			{"product": "Dough Keju", "batches": 3},
		],
	},
	{
		"item_code": "RM-YEAST-006",
		"item_name": "Ragi Instan",
		"item_group": "Bahan Baku",
		"actual_qty": 22,
		"stock_uom": "kg",
		"uom_tampilan": "Pack",
		"stok_diu": 5.5,
		"reserved_diu": 1,
		"tersedia_diu": 4.5,
		"minimum_diu": 3.75,
		"status": "aman",
		"capacity_batch": 8,
		"capacity_detail": [{"product": "Dough Coklat", "batches": 8}],
	},
	{
		"item_code": "RM-COCOA-004",
		"item_name": "Bubuk Kakao",
		"item_group": "Bahan Baku",
		"actual_qty": 18,
		"stock_uom": "kg",
		"uom_tampilan": "kg",
		"stok_diu": 18,
		"reserved_diu": 18,
		"tersedia_diu": 0,
		"minimum_diu": 25,
		"status": "habis",
		"capacity_batch": 0,
		"capacity_detail": [{"product": "Dough Coklat", "batches": 0}],
	},
]


class TestStockAvailabilitySheet(unittest.TestCase):
	"""Pure sheet-building — tanpa fixture DB."""

	def test_siapkan_sheet_tiga_sheet_kontrak(self):
		info, baris, kapasitas = _siapkan_sheet(
			SAMPLE_ITEMS, {"aman": 96, "menipis": 21, "habis": 11}, "Gudang Produksi"
		)
		# Info: judul + ringkasan KPI + gudang
		self.assertEqual(info[0][0], "Ekspor Ketersediaan Stock Bahan Baku")
		label = {r[0]: r[1] for r in info[1:]}
		self.assertEqual(label["Gudang"], "Gudang Produksi")
		self.assertEqual(label["Jumlah Item"], 3)
		self.assertEqual((label["Stock Aman"], label["Stock Menipis"], label["Stock Habis"]), (96, 21, 11))
		self.assertIn("Dicetak", label)
		# Stock Bahan Baku: header 11 kolom (FU88: qty = UOM tampilan + kolom
		# penutup Stok (Stock UOM)); angka MENTAH numerik
		self.assertEqual(
			baris[0],
			["Kode Item", "Nama Item", "Grup Item", "Stok", "Reserved", "Tersedia",
			 "UOM", "Stok Minimum", "Status", "Kapasitas (Batch)", "Stok (Stock UOM)"],
		)
		tepung = baris[1]  # tanpa DIU → diu = stock, UOM = stock
		self.assertEqual(tepung[0], "RM-FLOUR-001")
		self.assertIsInstance(tepung[3], float)  # stok numerik (flt)
		self.assertEqual(tepung[5], 105.0)  # tersedia = stok − reserved
		self.assertEqual(tepung[6], "kg")
		self.assertEqual(tepung[8], "Aman")  # label Indonesia dari status angka
		self.assertEqual(tepung[10], 125.0)  # stok mentah stock UOM
		ragi = baris[2]  # ber-DIU: qty dalam Pack, stok mentah tetap kg
		self.assertEqual(ragi[3], 5.5)
		self.assertEqual(ragi[6], "Pack")
		self.assertEqual(ragi[10], 22.0)
		kakao = baris[3]
		self.assertEqual(kakao[8], "Habis")
		self.assertEqual(kakao[9], 0)
		# Kapasitas per Resep: diratakan 1 baris per resep (4 baris data)
		self.assertEqual(
			kapasitas[0],
			["Kode Item", "Nama Item", "Produk Resep", "Kapasitas (Batch)"],
		)
		self.assertEqual(len(kapasitas), 5)
		self.assertEqual(kapasitas[1][2], "Dough Coklat")
		self.assertEqual(kapasitas[1][3], 4)
		self.assertEqual(kapasitas[2][2], "Dough Keju")  # resep kedua Tepung
		self.assertEqual(kapasitas[4][2], "Dough Coklat")  # satu-satunya resep Kakao

	def test_siapkan_sheet_kosong_tahan(self):
		info, baris, kapasitas = _siapkan_sheet([], {}, None)
		self.assertEqual(len(baris), 1)  # hanya header
		self.assertEqual(len(kapasitas), 1)
		self.assertEqual(info[1][1], "Gudang Produksi")  # default tanpa gudang

	def test_siapkan_sheet_fallback_tanpa_uom_tampilan(self):
		# item lama tanpa kunci FU88 → UOM fallback stock_uom, diu 0.0 (flt)
		_, baris, _ = _siapkan_sheet(
			[{"item_code": "RM-LAMA", "stock_uom": "kg", "status": "aman"}], {}, None
		)
		self.assertEqual(baris[1][6], "kg")
		self.assertEqual(baris[1][10], 0.0)


class TestStockAvailabilityExport(unittest.TestCase):
	def test_nama_file_paritas_frontend(self):
		self.assertEqual(
			_nama_file_xlsx("Gudang Produksi"),
			f"ketersediaan-stock-gudang-produksi-{frappe.utils.nowdate()}.xlsx",
		)
		self.assertEqual(
			_nama_file_xlsx(None), f"ketersediaan-stock-{frappe.utils.nowdate()}.xlsx"
		)

	def test_export_xlsx_binary_tiga_sheet(self):
		"""Endpoint men-set frappe.response binary (provide_binary_file):
		filecontent bytes mulai magic PK zip, nama .xlsx paritas frontend."""
		export_xlsx(items=SAMPLE_ITEMS, summary={"aman": 96, "menipis": 21, "habis": 11}, warehouse="Gudang Produksi")
		self.assertEqual(frappe.response["type"], "binary")
		content = frappe.response["filecontent"]
		self.assertIsInstance(content, bytes)
		self.assertTrue(content.startswith(b"PK"))  # magic zip .xlsx
		self.assertTrue(frappe.response["filename"].startswith("ketersediaan-stock-gudang-produksi"))
		self.assertTrue(frappe.response["filename"].endswith(".xlsx"))
		# workbook valid: 3 sheet sesuai kontrak (buka balik via openpyxl)
		from openpyxl import load_workbook

		wb = load_workbook(BytesIO(content))
		self.assertEqual(wb.sheetnames, ["Info", "Stock Bahan Baku", "Kapasitas per Resep"])
		self.assertEqual(wb["Stock Bahan Baku"].max_row, 4)  # header + 3 item

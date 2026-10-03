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

SAMPLE_ITEMS = [
	{
		"item_code": "RM-FLOUR-001",
		"item_name": "Tepung Terigu",
		"item_group": "Bahan Baku",
		"actual_qty": 125,
		"reserved_qty": 20,
		"available": 105,
		"stock_uom": "kg",
		"min_stock": 100,
		"status": "aman",
		"capacity_batch": 4,
		"capacity_detail": [
			{"product": "Dough Coklat", "batches": 4},
			{"product": "Dough Keju", "batches": 3},
		],
	},
	{
		"item_code": "RM-COCOA-004",
		"item_name": "Bubuk Kakao",
		"item_group": "Bahan Baku",
		"actual_qty": 18,
		"reserved_qty": 18,
		"available": 0,
		"stock_uom": "kg",
		"min_stock": 25,
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
		self.assertEqual(label["Jumlah Item"], 2)
		self.assertEqual((label["Stock Aman"], label["Stock Menipis"], label["Stock Habis"]), (96, 21, 11))
		self.assertIn("Dicetak", label)
		# Stock Bahan Baku: header 10 kolom = kolom tabel layar; angka MENTAH
		self.assertEqual(
			baris[0],
			["Kode Item", "Nama Item", "Grup Item", "Stok", "Reserved", "Tersedia",
			 "UOM", "Stok Minimum", "Status", "Kapasitas (Batch)"],
		)
		tepung = baris[1]
		self.assertEqual(tepung[0], "RM-FLOUR-001")
		self.assertIsInstance(tepung[3], float)  # stok numerik (flt)
		self.assertEqual(tepung[5], 105.0)  # tersedia = stok − reserved
		self.assertEqual(tepung[8], "Aman")  # label Indonesia dari status angka
		kakao = baris[2]
		self.assertEqual(kakao[8], "Habis")
		self.assertEqual(kakao[9], 0)
		# Kapasitas per Resep: diratakan 1 baris per resep (3 baris data)
		self.assertEqual(
			kapasitas[0],
			["Kode Item", "Nama Item", "Produk Resep", "Kapasitas (Batch)"],
		)
		self.assertEqual(len(kapasitas), 4)
		self.assertEqual(kapasitas[1][2], "Dough Coklat")
		self.assertEqual(kapasitas[1][3], 4)
		self.assertEqual(kapasitas[2][2], "Dough Keju")  # resep kedua Tepung
		self.assertEqual(kapasitas[3][2], "Dough Coklat")  # satu-satunya resep Kakao

	def test_siapkan_sheet_kosong_tahan(self):
		info, baris, kapasitas = _siapkan_sheet([], {}, None)
		self.assertEqual(len(baris), 1)  # hanya header
		self.assertEqual(len(kapasitas), 1)
		self.assertEqual(info[1][1], "Gudang Produksi")  # default tanpa gudang


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
		self.assertEqual(wb["Stock Bahan Baku"].max_row, 3)  # header + 2 item

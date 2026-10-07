# FU102 — uji perluasan param filter halaman Dashboard (rentang) mengikuti
# pola FU100: satu rentang = nilai TUNGGAL, jadi param `preset`/`dari`/`sampai`
# (dashboard_summary) dan `mode` (dashboard_daily) menerima skalar lama, list
# satu nilai, serta string JSON satu nilai — ketiganya harus menghasilkan
# jawaban IDENTIK. Daftar kosong = param tidak dikirim (default server).
# Dua nilai atau lebih DITOLAK (tidak ada gabungan interval). Batas
# DASHBOARD_MAX_DAYS tetap berlaku lewat bentuk list.
#
# Read-only delta-safe: hanya SELECT (dashboard_summary/dashboard_daily tidak
# menulis apa pun) — tanpa fixture tulis, aman dijalankan pada data nyata.
import json
import unittest

import frappe

from production_app.api.dashboard import _satu_nilai, dashboard_daily, dashboard_summary


class TestDashboardFilterParams(unittest.TestCase):
	def test_satu_nilai_parser(self):
		# skalar lama, list satu nilai, JSON satu nilai — sama semua
		self.assertIsNone(_satu_nilai(None, "x"))
		self.assertIsNone(_satu_nilai("", "x"))
		self.assertIsNone(_satu_nilai("   ", "x"))
		self.assertIsNone(_satu_nilai([], "x"))  # daftar kosong = tanpa filter
		self.assertEqual(_satu_nilai("hari_ini", "x"), "hari_ini")  # skalar lama
		self.assertEqual(_satu_nilai(["hari_ini"], "x"), "hari_ini")  # list
		self.assertEqual(_satu_nilai('["hari_ini"]', "x"), "hari_ini")  # JSON
		self.assertEqual(_satu_nilai([" hari_ini "], "x"), "hari_ini")  # trim
		# pemanggil lama mengirim date/datetime native (mis. add_days(today()))
		# — distringkan, bukan ditolak
		self.assertEqual(_satu_nilai(frappe.utils.getdate("2026-10-01"), "x"), "2026-10-01")
		# rentang = nilai tunggal: lebih dari satu nilai ditolak, bukan digabung
		with self.assertRaises(frappe.ValidationError):
			_satu_nilai(["hari_ini", "kemarin"], "x")
		with self.assertRaises(frappe.ValidationError):
			_satu_nilai(["2026-10-01", "2026-10-02"], "dari")
		with self.assertRaises(frappe.ValidationError):
			_satu_nilai({"a": 1}, "x")  # tipe salah

	def test_preset_scalar_equals_single_item_list(self):
		"""Skalar lama ≡ list-satu ≡ JSON-satu: rentang resolved identik."""
		scalar = dashboard_summary(preset="hari_ini")
		as_list = dashboard_summary(preset=["hari_ini"])
		as_json = dashboard_summary(preset=json.dumps(["hari_ini"]))
		self.assertEqual(scalar["dari"], as_list["dari"])
		self.assertEqual(scalar["sampai"], as_list["sampai"])
		self.assertEqual(scalar["preset"], as_list["preset"])
		self.assertEqual(scalar["dari"], as_json["dari"])
		self.assertEqual(scalar["sampai"], as_json["sampai"])
		self.assertEqual(scalar["preset"], as_json["preset"])

	def test_kustom_scalar_equals_list(self):
		"""dari/sampai kustom: bentuk list ≡ skalar (tanggal sama)."""
		hari = frappe.utils.getdate(frappe.utils.today())
		dari, sampai = str(hari), str(hari)
		scalar = dashboard_summary(preset="kustom", dari=dari, sampai=sampai)
		as_list = dashboard_summary(preset=["kustom"], dari=[dari], sampai=[sampai])
		self.assertEqual(scalar["dari"], as_list["dari"])
		self.assertEqual(scalar["sampai"], as_list["sampai"])
		self.assertEqual(scalar["preset"], as_list["preset"])
		self.assertEqual(scalar["today"], as_list["today"])

	def test_daftar_kosong_setara_tanpa_param(self):
		"""Daftar kosong pada preset tak boleh mengubah perilaku default."""
		polos = dashboard_summary()
		kosong = dashboard_summary(preset=[])
		self.assertEqual(polos["dari"], kosong["dari"])
		self.assertEqual(polos["sampai"], kosong["sampai"])
		self.assertEqual(polos["preset"], kosong["preset"])

	def test_multi_nilai_ditolak(self):
		"""Dua preset sekaligus = permintaan gabungan interval — ditolak."""
		with self.assertRaises(frappe.ValidationError):
			dashboard_summary(preset=["hari_ini", "kemarin"])
		with self.assertRaises(frappe.ValidationError):
			dashboard_summary(preset="kustom", dari=["2026-10-01", "2026-10-02"], sampai="2026-10-03")

	def test_batas_hari_tetap_berlaku_lewat_list(self):
		"""Batas DASHBOARD_MAX_DAYS (366) tetap menembak pada bentuk list."""
		with self.assertRaises(frappe.ValidationError):
			dashboard_summary(preset=["kustom"], dari=["2025-01-01"], sampai=["2026-12-31"])

	def test_mode_daily_scalar_equals_list(self):
		"""dashboard_daily: mode skalar ≡ list-satu (window resolved identik)."""
		scalar = dashboard_daily(mode="minggu")
		as_list = dashboard_daily(mode=["minggu"])
		as_json = dashboard_daily(mode=json.dumps(["minggu"]))
		self.assertEqual(scalar["mode"], as_list["mode"])
		self.assertEqual(scalar["dari"], as_list["dari"])
		self.assertEqual(scalar["sampai"], as_list["sampai"])
		self.assertEqual(scalar["mode"], as_json["mode"])
		self.assertEqual(scalar["dari"], as_json["dari"])
		self.assertEqual(scalar["sampai"], as_json["sampai"])

	def test_mode_daily_kosong_setara_default(self):
		"""Mode kosong/daftar kosong = default minggu (perilaku lama)."""
		polos = dashboard_daily()
		kosong = dashboard_daily(mode=[])
		self.assertEqual(polos["mode"], kosong["mode"])
		self.assertEqual(polos["dari"], kosong["dari"])
		self.assertEqual(polos["sampai"], kosong["sampai"])


if __name__ == "__main__":
	unittest.main()

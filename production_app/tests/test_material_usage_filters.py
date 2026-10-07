# FU106 — uji perluasan param filter halaman Penggunaan Bahan Baku
# (rollout FU100 halaman 5/5): `production_item` (endpoint material_usage dan
# material_usage_xlsx) kini menerima LIST multi-nilai ala FU100 lewat helper
# bersama filter_list — skalar lama, list asli, dan string JSON semuanya
# sepadan; daftar kosong = tanpa filter; dua nilai = union WO kedua produk;
# lebih dari 100 nilai ditolak.
#
# Read-only delta-safe: aggregate/endpoint hanya SELECT; memakai rentang
# berpenghuni (bulan berjalan — data WO nyata) tanpa menulis apa pun.
import json
import unittest

import frappe

from production_app.api.material_usage import aggregate, material_usage


class TestMaterialUsageFilters(unittest.TestCase):
	def _bulan(self):
		hari = frappe.utils.getdate(frappe.utils.today())
		return str(hari.replace(day=1)), str(frappe.utils.get_last_day(hari))

	def test_parser_scalar_equals_list_equals_json(self):
		"""Skalar lama ≡ list-satu ≡ JSON-satu: hasil agregat identik."""
		dari, sampai = self._bulan()
		produk = (aggregate(dari=dari, sampai=sampai, include_trace=True).get("products") or [])
		if not produk:
			self.skipTest("tidak ada WO dalam bulan berjalan di situs ini")
		kode = produk[0]["item_code"]

		skalar = aggregate(dari=dari, sampai=sampai, production_item=kode, include_trace=True)
		sebagai_list = aggregate(dari=dari, sampai=sampai, production_item=[kode], include_trace=True)
		sebagai_json = aggregate(dari=dari, sampai=sampai, production_item=json.dumps([kode]), include_trace=True)
		self.assertEqual(
			[k["item_code"] for k in skalar["rows"]],
			[k["item_code"] for k in sebagai_list["rows"]],
		)
		self.assertEqual(
			[k["item_code"] for k in skalar["rows"]],
			[k["item_code"] for k in sebagai_json["rows"]],
		)
		self.assertEqual(
			[w["wo"] for w in skalar["work_orders"]],
			[w["wo"] for w in sebagai_list["work_orders"]],
		)

	def test_daftar_kosong_setara_tanpa_filter(self):
		"""[] dan '' = tanpa filter (perilaku lama)."""
		dari, sampai = self._bulan()
		polos = aggregate(dari=dari, sampai=sampai, include_trace=True)
		kosong = aggregate(dari=dari, sampai=sampai, production_item=[], include_trace=True)
		teks_kosong = aggregate(dari=dari, sampai=sampai, production_item="", include_trace=True)
		self.assertEqual(len(polos["rows"]), len(kosong["rows"]))
		self.assertEqual(len(polos["rows"]), len(teks_kosong["rows"]))
		self.assertEqual(len(polos["work_orders"]), len(kosong["work_orders"]))

	def test_multi_nilai_union_dua_produk(self):
		"""pilihan A sendiri + B sendiri = A∪B (union), bukan irisan/kosong."""
		dari, sampai = self._bulan()
		produk = (aggregate(dari=dari, sampai=sampai, include_trace=True).get("products") or [])
		if len(produk) < 2:
			self.skipTest("kurang dari 2 produk ber-WO di bulan berjalan")
		a, b = produk[0]["item_code"], produk[1]["item_code"]
		pa = aggregate(dari=dari, sampai=sampai, production_item=a, include_trace=True)
		pb = aggregate(dari=dari, sampai=sampai, production_item=b, include_trace=True)
		pab = aggregate(dari=dari, sampai=sampai, production_item=[a, b], include_trace=True)
		wo_union = {w["wo"] for w in pa["work_orders"]} | {w["wo"] for w in pb["work_orders"]}
		self.assertEqual({w["wo"] for w in pab["work_orders"]}, wo_union)
		# baris bahan = gabungan baris tiap produk (kode unik per hasil agregat)
		union_rows = {r["item_code"] for r in pa["rows"]} | {r["item_code"] for r in pb["rows"]}
		self.assertTrue({r["item_code"] for r in pab["rows"]} <= union_rows)

	def test_endpoint_list_dan_kosong(self):
		"""Endpoint whitelisted menerima bentuk list dan daftar kosong."""
		dari, sampai = self._bulan()
		out = material_usage(dari=dari, sampai=sampai, production_item="[]", include_trace="1")
		self.assertIn("rows", out)
		out2 = material_usage(dari=dari, sampai=sampai, production_item=json.dumps(["TIDAK-ADA"]), include_trace="1")
		self.assertEqual(out2["rows"], [])
		self.assertEqual(out2["work_orders"], [])

	def test_batas_100_nilai_ditolak(self):
		"""Lebih dari 100 nilai = ValidationError (batas filter_list)."""
		with self.assertRaises(frappe.ValidationError):
			aggregate(dari="2026-01-01", sampai="2026-01-02", production_item=[f"X{i}" for i in range(101)])


if __name__ == "__main__":
	unittest.main()

# FU95 — filter company GLOBAL halaman workspace:
#   (1) preferensi per-user (pola ui_preferences FU70): roundtrip, self-heal
#       preferensi basi, tolak company di luar izin user;
#   (2) scope company di endpoint papan serah terima / Form Order / Ketersediaan
#       Stock (delta-safe: tanpa angka eksak — bentuk + konsistensi internal).

import unittest

import frappe
from frappe.defaults import set_user_default
from frappe.tests import IntegrationTestCase

from production_app.api.dashboard import _companies


class TestCompanyPreference(IntegrationTestCase):
	def test_default_roundtrip_selfheal_dan_validasi(self):
		from production_app.api.dashboard import company_preference, company_preference_save

		# user sementara: preferensi tersimpan per-user (rollback per class)
		user = frappe.get_doc(
			{"doctype": "User", "email": "testfu95@prodapp.example.com", "first_name": "FU95"}
		).insert().name
		frappe.set_user(user)
		try:
			companies = _companies()
			first = company_preference()
			self.assertEqual(set(first), {"company", "companies"})
			self.assertEqual(first["company"], "")  # user baru = tanpa filter
			self.assertEqual(first["companies"], companies)
			if not companies:
				return  # site tanpa izin Company: kontrak tetap utuh (daftar kosong)

			target = companies[0]
			saved = company_preference_save(target)
			self.assertEqual(saved["company"], target)
			self.assertEqual(saved["companies"], companies)
			self.assertEqual(company_preference()["company"], target)

			# lepas filter → '' (semua company)
			self.assertEqual(company_preference_save("")["company"], "")
			self.assertEqual(company_preference()["company"], "")

			# self-heal: preferensi menunjuk company di luar daftar terlihat →
			# dibaca balik sebagai '' (jangan pernah menunjuk di luar izin user)
			set_user_default(
				"production_app_company_filter", "Company Tidak Terlihat FU95"
			)
			self.assertEqual(company_preference()["company"], "")

			# simpan company tak dikenal → ValidationError (tanpa tulisan)
			with self.assertRaises(frappe.ValidationError):
				company_preference_save("Company Tidak Terlihat FU95")
		finally:
			frappe.set_user("Administrator")


class TestCompanyScopeLive(unittest.TestCase):
	"""Delta-safe di live site: filter company harus benar-benar menyaring
	baris (setiap baris hasil = company terpilih) dan company tak dikenal
	menghasilkan koleksi kosong — bukan error."""

	def test_handover_board_scope_company(self):
		from production_app.api.handover import handover_board

		full = handover_board()
		tampil = sorted(
			{r["company"] for r in full["lots"] + full["requests"] if r.get("company")}
		)
		for c in tampil:
			scoped = handover_board(company=c)
			self.assertTrue(all(r["company"] == c for r in scoped["lots"]))
			self.assertTrue(all(r["company"] == c for r in scoped["requests"]))
			# baris yang lebih sempit/lebih luas: scope ⊆ penuh (per nama baris)
			names_full = {r["work_order"] for r in full["lots"]}
			self.assertLessEqual({r["work_order"] for r in scoped["lots"]}, names_full)
		empty = handover_board(company="__FU95_TIDAK_ADA__")
		self.assertEqual(empty["lots"], [])
		self.assertEqual(empty["requests"], [])
		# tanpa company = perilaku lama utuh (semua baris kembali)
		self.assertEqual(len(handover_board()["lots"]), len(full["lots"]))

	def test_form_order_list_scope_company(self):
		from production_app.api.form_order import form_order_list

		full = form_order_list()["orders"]
		tampil = sorted({o["company"] for o in full if o.get("company")})
		for c in tampil:
			scoped = form_order_list(company=c)["orders"]
			self.assertTrue(all(o["company"] == c for o in scoped))
		self.assertEqual(form_order_list(company="__FU95_TIDAK_ADA__")["orders"], [])

	def test_stock_availability_scope_company(self):
		from production_app.api.stock_availability import stock_availability

		full = stock_availability()
		if not full["warehouses"]:
			self.assertEqual(full["items"], [])  # site tanpa Bin: kontrak utuh
			return
		wh_company = {
			w: frappe.db.get_value("Warehouse", w, "company") for w in full["warehouses"]
		}
		for c in sorted({v for v in wh_company.values() if v}):
			scoped = stock_availability(company=c)
			self.assertTrue(scoped["warehouses"])  # ada minimal 1 gudang company itu
			for w in scoped["warehouses"]:
				self.assertEqual(wh_company.get(w), c)
			for it in scoped["items"]:
				self.assertIn(it["warehouse"], scoped["warehouses"])
			# gudang in-scope tetap dihormati
			w0 = scoped["warehouses"][0]
			keep = stock_availability(warehouse=w0, company=c)
			self.assertEqual(keep["warehouse"], w0)
			# gudang LUAR scope → jatuh ke default DALAM scope, bukan bocor
			out = next(
				(w for w, co in wh_company.items() if co and co != c), None
			)
			if out:
				fallback = stock_availability(warehouse=out, company=c)
				self.assertIn(fallback["warehouse"], scoped["warehouses"])
		# company tanpa gudang ber-Bin → kosong, bukan error
		lain = next((x for x in _companies() if x not in set(wh_company.values())), None)
		if lain:
			kosong = stock_availability(company=lain)
			self.assertEqual(kosong["warehouses"], [])
			self.assertEqual(kosong["items"], [])
			self.assertEqual(kosong["summary"], {"total": 0, "aman": 0, "menipis": 0, "habis": 0})

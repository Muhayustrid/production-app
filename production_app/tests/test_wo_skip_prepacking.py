# FU114 — Item "Tanpa Pre-Packing" (custom_skip_prepacking): WO melompati tahap
# Pre-Packing; Post-Packing bisa disimpan tanpa marker prepacking dan finish
# membuat Manufacture dari good Post-Packing. Item biasa tetap wajib Pre-Packing.
# Fixture dipinjam dari test F03 (rollback penuh oleh IntegrationTestCase).
import frappe
from frappe.utils import flt

# impor modul (bukan kelas) agar runner tidak ikut menjalankan ulang kelas F03
from production_app.tests import test_wo_finish_duplicate_rm as f03


class TestWoSkipPrepacking(f03.TestWoFinishDuplicateRm):
	# flag setup kelas induk terwarisi → setUpClass IntegrationTestCase return
	# dini tanpa mendaftarkan rollback; reset per subkelas agar fixture tidak bocor
	_integration_test_case_class_setup_done = False
	def _wo(self, tag, skip):
		rm = self._make_item(f"{tag}-RM", "Bahan Baku")
		fg = self._make_item(f"{tag}-FG", "Produk Jadi Pabrik")
		frappe.db.set_value("Item", fg, "custom_skip_prepacking", 1 if skip else 0)
		self._receipt(rm, 1000, self.src_wh)
		wo = self._make_wo(fg, self._bom_single_row(fg, rm), 100)
		from production_app.api.work_order import transfer_materials

		transfer_materials(wo.name)
		return frappe.get_doc("Work Order", wo.name)

	def test_skip_item_goes_straight_to_postpacking_and_finishes(self):
		from production_app.api.work_order import (
			STAGE_POST_PACKING,
			confirm_postpacking,
			derive_stage,
			finish,
			wo_detail,
			wo_list,
		)

		wo = self._wo("S", skip=True)
		self.assertEqual(derive_stage(wo), STAGE_POST_PACKING)
		self.assertTrue(wo_detail(wo.name)["skip_prepacking"])
		listed = wo_list(stage="post_packing", search=wo.name, meta=1)["rows"]
		self.assertIn(wo.name, [r.name for r in listed])

		confirm_postpacking(wo.name, values={"good": 90, "reject": 0, "trial": 0})
		result = finish(wo.name)
		se = frappe.get_doc("Stock Entry", result["stock_entry"])
		fg_rows = [r for r in se.items if r.is_finished_item]
		self.assertEqual(flt(fg_rows[0].transfer_qty), 90)
		self.assertFalse(frappe.db.get_value("Work Order", wo.name, "custom_prepacking_confirmed"))

	def test_normal_item_still_requires_prepacking(self):
		from production_app.api.work_order import STAGE_PREPACKING, confirm_postpacking, derive_stage

		wo = self._wo("N", skip=False)
		self.assertEqual(derive_stage(wo), STAGE_PREPACKING)
		with self.assertRaises(frappe.ValidationError):
			confirm_postpacking(wo.name, values={"good": 90})

	# test F03 milik induk tidak dijalankan ulang di kelas ini
	test_f03_duplicate_rm_rows_share_the_remaining_balance = None
	test_f03_single_rm_row_keeps_the_old_formula = None


class TestSkipPrepackingSettings(f03.TestWoFinishDuplicateRm):
	# flag setup kelas induk terwarisi → setUpClass IntegrationTestCase return
	# dini tanpa mendaftarkan rollback; reset per subkelas agar fixture tidak bocor
	_integration_test_case_class_setup_done = False
	test_f03_duplicate_rm_rows_share_the_remaining_balance = None
	test_f03_single_rm_row_keeps_the_old_formula = None

	def test_set_and_list(self):
		from production_app.api.work_order import skip_prepacking_items, skip_prepacking_set

		fg = self._make_item("L-FG", "Produk Jadi Pabrik")
		self.assertIn(fg, [r.name for r in skip_prepacking_set(fg, 1)])
		self.assertEqual(frappe.db.get_value("Item", fg, "custom_skip_prepacking"), 1)
		self.assertNotIn(fg, [r.name for r in skip_prepacking_set(fg, 0)])
		self.assertNotIn(fg, [r.name for r in skip_prepacking_items()])
		with self.assertRaises(frappe.ValidationError):
			skip_prepacking_set("TIDAK-ADA-XYZ", 1)

	def test_requires_settings_write(self):
		from production_app.api.work_order import skip_prepacking_set

		fg = self._make_item("P-FG", "Produk Jadi Pabrik")
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				skip_prepacking_set(fg, 1)
		finally:
			frappe.set_user("Administrator")

# T24/T31 handover mutation actions — create/cancel request, verify, send
#
# Proves, by execution (task-24-brief coverage as amended by T31, R1-R8):
# 1. create_request(work_order): qty = the Work Order's FULL produced_qty (no
#    qty param); from_warehouse follows the source setting (and falls back to
#    the SE-derived lot warehouse when unset); transaction_date today; a
#    second ACTIVE request for the same WO is blocked with ZERO writes; a
#    pool shorter than the WO qty is blocked (diminta/tersedia, zero writes).
# 2. save_post_packing(material_request, box_1, box_2): box-only kg floats —
#    persist on the MR and mirror to the WO; repeat blocked; negative and
#    non-numeric rejected; gudang role 403.
# 3. send_handover: moves EXACTLY the requested qty (SLE + batch qty both
#    warehouses); batch-tracked rows carry batch_no; MR is NOT stopped (R6 —
#    the short-close branch is gone); duplicate send blocked; SE posting is
#    the send moment (R1 — date == today, no back-dating).
# 4. cancel_request: pre-verification only (native cancel, reservation
#    released); after verification blocked; with SE blocked; produksi denied.
# 5. Permissions: gudang cannot verify/send/touch WO mutations; produksi
#    cannot create/cancel MR; bare user denied everything, empty board.
# 6. Errors atomic: insufficient batch stock -> zero partial SE/SLE;
#    unsupported legacy WO -> refused before mutation.
# 7. Native desk SE cancel -> board recomputes; a re-send works afterwards.
# 8. Boxes: kg floats persist + redisplay; never converted to PCS.
# 9. Legacy edge: WO with two Manufacture SEs -> create AND send refuse.
#
# Every record is test-only (T24/t24-prefixed); the Frappe test framework rolls
# the run back. The two real warehouses are never touched.

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, now, random_string, today

from erpnext.manufacturing.doctype.work_order.work_order import (
    make_stock_entry as make_wo_stock_entry,
)
from erpnext.stock.doctype.batch.batch import get_batch_qty

from production_app.api.handover import (
    _item_stock,
    cancel_request,
    create_request,
    handover_board,
    save_post_packing,
    send_handover,
)
from production_app.api.work_order import finish, warehouse_defaults_save

PREFIX = "T24"


class TestHandoverActions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		name = frappe.db.get_value(
			"Work Order", {"docstatus": 1, "fg_warehouse": ("is", "set")}, "name",
			order_by="creation desc",
		)
		cfg = frappe.db.get_value("Work Order", name, ["company", "stock_uom", "fg_warehouse"], as_dict=True)
		cls.company = cfg.company
		cls.uom = cfg.stock_uom
		cls.group = frappe.db.get_value("Item Group", {}, "name")
		parent = frappe.db.get_value("Warehouse", cfg.fg_warehouse, "parent_warehouse")
		suffix = random_string(6).upper()

		def warehouse(label):
			return (
				frappe.get_doc(
					{
						"doctype": "Warehouse",
						"warehouse_name": f"{PREFIX} {label} {suffix}",
						"company": cls.company,
						"parent_warehouse": parent,
						"is_group": 0,
					}
				)
				.insert()
				.name
			)

		cls.src_wh = warehouse("Source")
		cls.wip_wh = warehouse("WIP")
		cls.cold_wh = warehouse("Cold Storage")
		cls.target_wh = warehouse("Target")

		cls.rm = cls._make_item(f"{PREFIX}-RM-{suffix}", batch=False)
		cls.fg = cls._make_item(f"{PREFIX}-FG-{suffix}")
		# follow-up 8: a batchless FG item — stock pools at item level
		cls.fg_nb = cls._make_item(f"{PREFIX}-FGNB-{suffix}", batch=False)
		cls.bom = cls._make_bom(cls.fg)
		cls.bom_nb = cls._make_bom(cls.fg_nb)
		# FU29: a SECOND batchless item — the fu29 drift test ships from its own
		# pool so its target_wh balance cannot leak into T31's pool accounting
		cls.fg_nb2 = cls._make_item(f"{PREFIX}-FGNB2-{suffix}", batch=False)
		cls.bom_nb2 = cls._make_bom(cls.fg_nb2)
		cls._receipt(cls.rm, 20000, cls.src_wh)  # covers the run (no per-test rollback)

		cls.prior_target = frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_warehouse"
		)
		cls.prior_source = frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_source_warehouse"
		)
		warehouse_defaults_save(handover_warehouse=cls.target_wh)

		cls.gudang = cls._make_user(f"t24.gudang.{suffix.lower()}@prodapp.example.com", ["Gudang Barang Jadi"])
		cls.prod = cls._make_user(f"t24.prod.{suffix.lower()}@prodapp.example.com", ["Manufacturing User"])
		cls.bare = cls._make_user(f"t24.bare.{suffix.lower()}@prodapp.example.com", [])

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		warehouse_defaults_save(
			handover_warehouse=cls.prior_target, handover_source_warehouse=cls.prior_source
		)  # defensive restore
		super().tearDownClass()  # class-level rollback discards the run

	# ------------------------------------------------------------- fixtures

	@classmethod
	def _make_item(cls, code, batch=True):
		return (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": cls.group,
					"stock_uom": cls.uom,
					"is_stock_item": 1,
					"is_purchase_item": 0,
					"is_sales_item": 0,
					"has_batch_no": 1 if batch else 0,
					"create_new_batch": 1 if batch else 0,
					"standard_rate": 100,
					"is_fixed_asset": 0,
					"opening_stock": 0,
				}
			)
			.insert()
			.name
		)

	@classmethod
	def _make_bom(cls, fg_item):
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": fg_item,
				"company": cls.company,
				"currency": frappe.db.get_value("Company", cls.company, "default_currency"),
				"quantity": 1,
				"items": [
					{
						"item_code": cls.rm,
						"qty": 1,
						"rate": 10,
						"uom": cls.uom,
						"stock_uom": cls.uom,
						"source_warehouse": cls.src_wh,
					}
				],
			}
		)
		bom.insert()
		bom.submit()
		return bom.name

	@staticmethod
	def _pin_posting(se, posting_time):
		"""Pinned fixture movements post YESTERDAY, so every real-time
		operation (action sends, desk transfers, cancels — all at now()) sorts
		strictly AFTER them in the stock ledger regardless of the wall clock;
		equal-timestamp ties inside the ledger are avoided entirely."""
		se.set_posting_time = 1
		se.posting_date = add_days(today(), -1)
		se.posting_time = posting_time

	@classmethod
	def _receipt(cls, item, qty, wh):
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": cls.company,
				"items": [
					{"item_code": item, "qty": qty, "basic_rate": 10, "t_warehouse": wh, "use_serial_batch_fields": 0}
				],
			}
		)
		cls._pin_posting(se, "08:00:00")
		se.insert()
		se.submit()
		return se

	@classmethod
	def _make_wo(cls, qty, item=None):
		if item in (None, cls.fg):
			bom_no = cls.bom
		elif item == cls.fg_nb:
			bom_no = cls.bom_nb
		else:
			bom_no = cls.bom_nb2
		wo = frappe.get_doc(
			{
				"doctype": "Work Order",
				"production_item": item or cls.fg,
				"bom_no": bom_no,
				"qty": qty,
				"company": cls.company,
				"fg_warehouse": cls.cold_wh,
				"wip_warehouse": cls.wip_wh,
				"source_warehouse": cls.src_wh,
				"scrap_warehouse": cls.cold_wh,
				"stock_uom": cls.uom,
				"planned_start_date": now(),
				"transfer_material_against": "Work Order",
				"use_multi_level_bom": 0,
				"custom_adonan_ke": "1",
			}
		)
		wo.get_items_and_operations_from_bom()
		wo.insert()
		wo.submit()
		return wo

	@classmethod
	def _transfer(cls, wo):
		se = frappe.get_doc(make_wo_stock_entry(wo.name, "Material Transfer for Manufacture"))
		cls._pin_posting(se, "09:00:00")
		se.insert()
		se.submit()
		return se

	@classmethod
	def _manufacture(cls, wo, good, restore_rm=True):
		se = frappe.get_doc(make_wo_stock_entry(wo.name, "Manufacture", qty=good))
		cls._pin_posting(se, "10:00:00")
		if restore_rm:
			for row in se.items:
				if not row.is_finished_item:
					row.qty = flt(wo.qty)  # plan qty (1:1 BOM)
					row.transfer_qty = row.qty
		se.insert()
		se.submit()
		return se

	@classmethod
	def _make_user(cls, email, roles):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		)
		for role in roles:
			user.append("roles", {"role": role})
		user.insert()
		return user.name

	@classmethod
	def _lot_in_cold(cls, wo):
		return frappe.get_all("Batch", filters={"reference_name": wo.name}, pluck="name")[0]

	@classmethod
	def _lot_ready(cls, qty):
		"""WO + transfer + Manufacture -> a lot of `qty` pcs in Cold Storage."""
		wo = cls._make_wo(qty)
		cls._transfer(wo)
		cls._manufacture(wo, qty)
		return wo, cls._lot_in_cold(wo)

	def _request(self, wo):
		"""create_request as the gudang actor (the matrix role)."""
		frappe.set_user(self.gudang)
		try:
			return create_request(wo.name)
		finally:
			frappe.set_user("Administrator")

	def _postpack(self, mr, box_1=None, box_2=None):
		frappe.set_user(self.prod)
		try:
			return save_post_packing(mr.name, box_1=box_1, box_2=box_2)
		finally:
			frappe.set_user("Administrator")

	def _send(self, mr):
		frappe.set_user(self.prod)
		try:
			return send_handover(mr.name)
		finally:
			frappe.set_user("Administrator")

	def _lot(self, board, wo_name):
		return next(l for l in board["lots"] if l["work_order"] == wo_name)

	def _req(self, board, mr_name):
		return next(r for r in board["requests"] if r["mr"] == mr_name)

	def _bound_mr_count(self, wo_name):
		return len(frappe.get_all("Material Request Item", filters={"custom_work_order": wo_name}))

	@classmethod
	def _desk_mr(cls, wo_name, item_code, qty):
		"""A handover MR built directly (desk-style fixture, T23 pattern)."""
		mr = frappe.get_doc(
			{
				"doctype": "Material Request",
				"material_request_type": "Material Transfer",
				"company": cls.company,
				"transaction_date": now(),
				"schedule_date": add_days(now(), 1),
				"set_from_warehouse": cls.cold_wh,
				"set_warehouse": cls.target_wh,
				"items": [
					{
						"item_code": item_code,
						"qty": qty,
						"uom": cls.uom,
						"from_warehouse": cls.cold_wh,
						"warehouse": cls.target_wh,
						"schedule_date": add_days(now(), 1),
						"custom_work_order": wo_name,
					}
				],
			}
		)
		mr.insert()
		mr.submit()
		return mr

	# -------------------------------------------------- 1. create_request

	def test_fu34_create_request_never_scans_unrelated_work_orders(self):
		wo, _batch = self._lot_ready(35)
		from production_app.api import handover

		original = handover._wo_lot_rows

		global_scans = 0

		def tracked(wo_names=None):
			nonlocal global_scans
			if wo_names is None:
				global_scans += 1
			return original(wo_names=wo_names)

		with patch.object(handover, "_wo_lot_rows", side_effect=tracked):
			result = self._request(wo)

		self.assertEqual(flt(result["qty"]), 35)
		self.assertEqual(self._bound_mr_count(wo.name), 1)
		self.assertEqual(global_scans, 1)  # one final server-truth response only

	def test_t31_create_request_full_wo_qty_source_and_duplicate_guard(self):
		"""R3: create_request(work_order) requests the WO's FULL produced qty —
		no qty param; from_warehouse falls back to the SE-derived lot warehouse
		when the source setting is unset and follows the setting when set;
		transaction_date is today; a second ACTIVE request is blocked with
		ZERO writes."""
		wo, batch = self._lot_ready(100)

		result = self._request(wo)
		self.assertEqual(flt(result["qty"]), 100)  # == WO produced_qty
		mr = frappe.get_doc("Material Request", result["material_request"])
		self.assertEqual(mr.docstatus, 1)
		self.assertEqual(mr.material_request_type, "Material Transfer")
		self.assertEqual(mr.set_from_warehouse, self.cold_wh)  # fallback (unset)
		self.assertEqual(mr.set_warehouse, self.target_wh)
		self.assertEqual(mr.items[0].from_warehouse, self.cold_wh)
		self.assertEqual(mr.items[0].warehouse, self.target_wh)
		self.assertEqual(mr.items[0].custom_work_order, wo.name)
		self.assertEqual(flt(mr.items[0].qty), 100)
		self.assertEqual(str(mr.transaction_date)[:10], today())
		self.assertEqual(flt(mr.custom_box_1), 0)  # pure request: kg boxes come at verify
		board = result["board"]
		req = self._req(board, mr.name)
		self.assertEqual(req["lane"], "request")
		lot = self._lot(board, wo.name)
		self.assertEqual(flt(lot["reserved_qty"]), 100)
		self.assertEqual(flt(lot["available_qty"]), 0)
		self.assertEqual(flt(get_batch_qty(batch, self.cold_wh)), 100)  # request moves no stock

		# duplicate ACTIVE request for the same WO: blocked, zero writes
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._request(wo)
		self.assertIn("sudah punya permintaan aktif", str(ctx.exception))
		self.assertEqual(self._bound_mr_count(wo.name), 1)

		# from_warehouse follows the source setting when set (R2)
		wo2, _ = self._lot_ready(80)
		prior = frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_source_warehouse"
		)
		try:
			# the save API writes every key — pass the target through unchanged
			warehouse_defaults_save(
				handover_warehouse=self.target_wh, handover_source_warehouse=self.src_wh
			)
			result2 = self._request(wo2)
			mr2 = frappe.get_doc("Material Request", result2["material_request"])
			self.assertEqual(mr2.set_from_warehouse, self.src_wh)
			self.assertEqual(mr2.items[0].from_warehouse, self.src_wh)
			self.assertEqual(flt(result2["qty"]), 80)
		finally:
			warehouse_defaults_save(
				handover_warehouse=self.target_wh, handover_source_warehouse=prior
			)

	def test_fu34_batchless_targeted_lot_counts_sibling_reservations(self):
		suffix = random_string(4).upper()
		fg = self._make_item(f"{PREFIX}-FGPOOL-{suffix}", batch=False)
		bom = self._make_bom(fg)
		cls = type(self)
		original_bom = cls.bom_nb2
		cls.bom_nb2 = bom
		try:
			wo1 = self._make_wo(60, item=fg)
			self._transfer(wo1)
			self._manufacture(wo1, 60)
			self._request(wo1)

			wo2 = self._make_wo(40, item=fg)
			self._transfer(wo2)
			self._manufacture(wo2, 40)
			pool = flt(_item_stock(fg, self.cold_wh))
			drain_qty = pool - 60
			if drain_qty > 0:
				se = frappe.get_doc(
					{
						"doctype": "Stock Entry",
						"stock_entry_type": "Material Transfer",
						"company": self.company,
						"items": [{
							"item_code": fg,
							"qty": drain_qty,
							"basic_rate": 10,
							"s_warehouse": self.cold_wh,
							"t_warehouse": self.target_wh,
							"use_serial_batch_fields": 0,
						}],
					}
				)
				self._pin_posting(se, "11:10:00")
				se.insert()
				se.submit()

			with self.assertRaises(frappe.ValidationError) as ctx:
				self._request(wo2)
			self.assertIn("tersedia 0", str(ctx.exception))
			self.assertEqual(self._bound_mr_count(wo2.name), 0)
		finally:
			cls.bom_nb2 = original_bom

	def test_t31_pool_short_blocked_zero_writes(self):
		"""R3: the availability guard still holds at the WO's full qty — a
		batchless pool shorter than the produced qty is rejected with the
		diminta/tersedia message and ZERO writes."""
		wo1 = self._make_wo(60, item=self.fg_nb)
		self._transfer(wo1)
		self._manufacture(wo1, 60)
		wo2 = self._make_wo(40, item=self.fg_nb)
		self._transfer(wo2)
		self._manufacture(wo2, 40)
		pool = flt(_item_stock(self.fg_nb, self.cold_wh))
		self.assertGreaterEqual(pool, 100)

		# drain the pool to 50 at the desk (plain transfer, batchless shape)
		drain_qty = pool - 50
		if drain_qty > 0:
			se = frappe.get_doc(
				{
					"doctype": "Stock Entry",
					"stock_entry_type": "Material Transfer",
					"company": self.company,
					"items": [
						{
							"item_code": self.fg_nb,
							"qty": drain_qty,
							"basic_rate": 10,
							"s_warehouse": self.cold_wh,
							"t_warehouse": self.target_wh,
							"use_serial_batch_fields": 0,
						}
					],
				}
			)
			self._pin_posting(se, "11:00:00")
			se.insert()
			se.submit()
		self.assertEqual(flt(_item_stock(self.fg_nb, self.cold_wh)), 50)

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._request(wo1)  # produced 60 > available 50
		self.assertIn("diminta", str(ctx.exception))
		self.assertIn("tersedia", str(ctx.exception))
		self.assertEqual(self._bound_mr_count(wo1.name), 0)  # zero writes

	# ------------------------------------- 9. + 6. unsupported / setting guard

	def test_t24_unsupported_legacy_and_unset_setting_refuse_before_mutation(self):
		"""WO with two Manufacture SEs: create AND send refuse with the §4.9
		message (native SE links), zero mutation; a never-manufactured WO and an
		unset target setting also refuse before any write."""
		legacy = self._make_wo(100)
		self._transfer(legacy)
		self._manufacture(legacy, 40, restore_rm=False)
		self._manufacture(legacy, 30, restore_rm=False)

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._request(legacy)
		self.assertIn(legacy.name, str(ctx.exception))
		self.assertEqual(self._bound_mr_count(legacy.name), 0)  # zero mutation

		never = self._make_wo(50)  # submitted but no Manufacture yet
		with self.assertRaises(frappe.ValidationError):
			self._request(never)
		self.assertEqual(self._bound_mr_count(never.name), 0)

		# send-side refusal on the same legacy WO (MR planted as on the desk)
		mr = self._desk_mr(legacy.name, legacy.production_item, 40)
		frappe.db.set_value("Material Request", mr.name, "custom_postpacking_confirmed", 1)
		frappe.set_user(self.prod)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				send_handover(mr.name)
			self.assertIn(legacy.name, str(ctx.exception))
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(
			len(frappe.get_all("Stock Entry", filters={"material_request": mr.name})), 0
		)

		# unset target setting -> clear error, zero writes
		prior = frappe.db.get_single_value("Manufacturing Settings", "custom_default_handover_warehouse")
		frappe.db.set_single_value("Manufacturing Settings", "custom_default_handover_warehouse", None)
		try:
			ready, _ = self._lot_ready(50)
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._request(ready)
			self.assertIn("Pengaturan", str(ctx.exception))
			self.assertEqual(self._bound_mr_count(ready.name), 0)
		finally:
			frappe.db.set_single_value("Manufacturing Settings", "custom_default_handover_warehouse", prior)

	# -------------------------------------------------- 2. save_post_packing

	def test_t31_post_packing_box_only(self):
		"""R4/R8: Verifikasi Siap Kirim records ONLY Box 1/2 kg floats — they
		persist on the MR and mirror to the WO; repeat blocked; negative and
		non-numeric rejected; gudang (wrong side) denied with nothing written."""
		wo, _ = self._lot_ready(100)
		result = self._request(wo)
		mr = frappe.get_doc("Material Request", result["material_request"])

		# gudang (wrong side) denied, nothing written
		frappe.set_user(self.gudang)
		try:
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(mr.name)
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("Material Request", mr.name, "custom_postpacking_confirmed"))

		# validation failures leave the MR untouched (blank boxes stay VALID —
		# optional floats, R4); negative and non-finite/non-numeric throw
		for kwargs in ({"box_1": -2.5}, {"box_2": "inf"}):
			with self.assertRaises(frappe.ValidationError):
				self._postpack(mr, **kwargs)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._postpack(mr, box_1="bukan angka")
		self.assertIn("harus angka kg", str(ctx.exception))
		mr.reload()
		self.assertFalse(mr.custom_postpacking_confirmed)
		self.assertEqual(flt(mr.custom_box_1), 0)

		# kg floats persist + confirm flips the lane
		result = self._postpack(mr, box_1=12.5, box_2=8.25)
		self.assertEqual(flt(result["box_1"]), 12.5)
		self.assertEqual(flt(result["box_2"]), 8.25)
		mr.reload()
		self.assertEqual(mr.custom_postpacking_confirmed, 1)
		self.assertEqual(flt(mr.custom_box_1), 12.5)
		self.assertEqual(flt(mr.custom_box_2), 8.25)
		self.assertEqual(self._req(result["board"], mr.name)["lane"], "siap_kirim")

		# the boxes mirror to the Work Order (kg, R8)
		mirror = frappe.db.get_value(
			"Work Order", wo.name, ["custom_box_1", "custom_box_2"], as_dict=True
		)
		self.assertEqual(flt(mirror.custom_box_1), 12.5)
		self.assertEqual(flt(mirror.custom_box_2), 8.25)

		# repeat verify blocked (written ONCE)
		with self.assertRaises(frappe.ValidationError):
			self._postpack(mr, box_1=1)

	def test_t28_wo_postpacking_not_touched_by_handover(self):
		"""T28: the WO postpacking fields (written by the workspace
		confirm_postpacking BEFORE manufacture, T27) survive the verify step;
		only Box 1/2 mirror; the MR box fields hold the handover truth."""
		wo, _ = self._lot_ready(100)
		# plant the workspace-written postpacking values directly on the WO
		frappe.db.set_value(
			"Work Order", wo.name,
			{
				"custom_good_qty_postpacking": 100,
				"custom_reject_qty_postpacking": 2,
				"custom_trial_qty_postpacking": 1,
				"custom_sisa_qty_postpacking": -3,  # whatever the workspace wrote — NOT ours to touch
				"custom_jam_packing": "08:00:00",
				"custom_qc_packing": "Administrator",
			},
		)
		mr = frappe.get_doc("Material Request", self._request(wo)["material_request"])

		self._postpack(mr, box_1=10.5, box_2=4.25)

		wob = frappe.db.get_value(
			"Work Order", wo.name,
			["custom_good_qty_postpacking", "custom_reject_qty_postpacking", "custom_trial_qty_postpacking", "custom_sisa_qty_postpacking", "custom_jam_packing", "custom_qc_packing", "custom_box_1", "custom_box_2"],
			as_dict=True,
		)
		self.assertEqual(flt(wob.custom_good_qty_postpacking), 100)  # NOT touched
		self.assertEqual(flt(wob.custom_reject_qty_postpacking), 2)
		self.assertEqual(flt(wob.custom_trial_qty_postpacking), 1)
		self.assertEqual(flt(wob.custom_sisa_qty_postpacking), -3)
		self.assertEqual(str(wob.custom_jam_packing), "8:00:00")
		self.assertEqual(wob.custom_qc_packing, "Administrator")
		self.assertEqual(flt(wob.custom_box_1), 10.5)  # box mirror stays (R8)
		self.assertEqual(flt(wob.custom_box_2), 4.25)
		mr.reload()  # the MR keeps its own box block
		self.assertEqual(flt(mr.custom_box_1), 10.5)
		self.assertEqual(flt(mr.custom_box_2), 4.25)
		self.assertEqual(mr.custom_postpacking_confirmed, 1)

	# --------------------------------------------------------- 3. send

	def test_t31_send_requested_qty_mr_not_stopped(self):
		"""R6: send moves EXACTLY the requested qty (== WO produced_qty), the
		MR goes Transferred and is NEVER stopped (the short-close branch is
		gone); duplicate send blocked; SE posts at the send moment (R1)."""
		wo, batch = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo)["material_request"])
		self._postpack(mr, box_1=12.5, box_2=8)
		result = self._send(mr)
		self.assertNotIn("stopped", result)  # dead keys removed
		self.assertNotIn("good", result)
		self.assertEqual(flt(result["qty"]), 100)
		se = frappe.get_doc("Stock Entry", result["stock_entry"])
		self.assertEqual(se.docstatus, 1)
		self.assertEqual(se.purpose, "Material Transfer")
		self.assertEqual(se.items[0].s_warehouse, self.cold_wh)
		self.assertEqual(se.items[0].t_warehouse, self.target_wh)
		self.assertEqual(se.items[0].batch_no, batch)  # v16: old field kept + bundle built
		self.assertTrue(se.items[0].serial_and_batch_bundle)
		ledger = {
			r.warehouse: flt(r.actual_qty)
			for r in frappe.get_all(
				"Stock Ledger Entry", filters={"voucher_no": se.name, "is_cancelled": 0},
				fields=["warehouse", "actual_qty"],
			)
		}
		self.assertEqual(ledger.get(self.cold_wh), -100)
		self.assertEqual(ledger.get(self.target_wh), 100)
		self.assertEqual(flt(get_batch_qty(batch, self.cold_wh) or 0), 0)
		self.assertEqual(flt(get_batch_qty(batch, self.target_wh)), 100)
		mr.reload()
		self.assertEqual(mr.status, "Transferred")  # NOT stopped
		self.assertEqual(flt(mr.per_ordered), 100)
		# R1: the SE posting is the actual send moment — never back-dated
		self.assertEqual(str(se.posting_date), today())
		board = handover_board()
		req = self._req(board, mr.name)
		self.assertEqual(req["lane"], "terkirim")
		self.assertEqual(req["stock_entry"], se.name)
		self.assertEqual(flt(self._lot(board, wo.name)["reserved_qty"]), 0)

		# duplicate send blocked, still exactly one SE
		with self.assertRaises(frappe.ValidationError):
			self._send(mr)
		self.assertEqual(
			len(frappe.get_all("Stock Entry Detail", filters={"material_request": mr.name, "docstatus": 1})), 1
		)

	# ------------------------------- FU8. batchless lots: pool + no-batch send

	def test_t31_batchless_pool_actions_and_send(self):
		"""Batchless FG — the pool is item-level: requests from TWO WOs of the
		same item draw one balance and fill it exactly; send creates a NO-batch
		Stock Entry that drains exactly the requested qty; the MR is not
		stopped; boxes mirror to the batchless WO like the batch path."""
		wo1 = self._make_wo(60, item=self.fg_nb)
		self._transfer(wo1)
		self._manufacture(wo1, 60)
		wo2 = self._make_wo(40, item=self.fg_nb)
		self._transfer(wo2)
		self._manufacture(wo2, 40)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.cold_wh)), 100)  # one pool

		result = self._request(wo1)  # qty == produced 60, from the shared pool
		self.assertEqual(flt(result["qty"]), 60)
		mr1 = frappe.get_doc("Material Request", result["material_request"])
		lot2 = self._lot(result["board"], wo2.name)
		self.assertTrue(lot2["batchless"])
		self.assertIsNone(lot2["batch"])
		self.assertEqual(flt(lot2["available_qty"]), 40)  # 100 - 60, same pool

		# the second WO's full qty fills the pool exactly
		result2 = self._request(wo2)
		self.assertEqual(flt(result2["qty"]), 40)
		board = handover_board()
		self.assertEqual(flt(self._lot(board, wo1.name)["reserved_qty"]), 100)
		self.assertEqual(flt(self._lot(board, wo1.name)["available_qty"]), 0)

		self._postpack(mr1, box_1=5.5)
		res = self._send(mr1)
		self.assertIsNone(res["batch"])
		self.assertEqual(flt(res["qty"]), 60)
		se = frappe.get_doc("Stock Entry", res["stock_entry"])
		self.assertFalse(se.items[0].batch_no)  # batchless: no batch anywhere
		self.assertFalse(se.items[0].serial_and_batch_bundle)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.cold_wh)), 40)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.target_wh)), 60)
		mr1.reload()
		self.assertEqual(mr1.status, "Transferred")  # full qty: never stopped (R6)
		# box mirrors to the batchless WO exactly like the batch path
		self.assertEqual(
			flt(frappe.db.get_value("Work Order", wo1.name, "custom_box_1")), 5.5
		)

		# duplicate send still blocked; pool unchanged by the failed attempt
		with self.assertRaises(frappe.ValidationError):
			self._send(mr1)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.cold_wh)), 40)

	# --------------------------------------------------------- 4. cancel

	def test_t24_cancel_request_only_before_verification(self):
		"""Cancel pre-verification (native, reservation released, board updated);
		blocked after verification and after send; produksi denied."""
		wo, _ = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo)["material_request"])
		self.assertEqual(flt(self._lot(handover_board(), wo.name)["available_qty"]), 0)

		frappe.set_user(self.gudang)
		try:
			result = cancel_request(mr.name)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(result["ok"])
		mr.reload()
		self.assertEqual(mr.docstatus, 2)
		req = self._req(result["board"], mr.name)
		self.assertIsNone(req["lane"])
		self.assertEqual(req["flag"], "cancelled")
		self.assertEqual(flt(self._lot(result["board"], wo.name)["reserved_qty"]), 0)  # released
		self.assertEqual(flt(self._lot(result["board"], wo.name)["available_qty"]), 100)

		# after verification -> blocked
		wo2, _ = self._lot_ready(100)
		mr2 = frappe.get_doc("Material Request", self._request(wo2)["material_request"])
		self._postpack(mr2, box_1=1.5)
		frappe.set_user(self.gudang)
		try:
			with self.assertRaises(frappe.ValidationError):
				cancel_request(mr2.name)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Material Request", mr2.name, "docstatus"), 1)

		# with a submitted SE -> blocked (clear error before the native guard)
		self._send(mr2)
		frappe.set_user(self.gudang)
		try:
			with self.assertRaises(frappe.ValidationError):
				cancel_request(mr2.name)
		finally:
			frappe.set_user("Administrator")

		# produksi (Manufacturing User) denied — `wo` again: its MR was
		# cancelled, so the lot is unreserved and the request passes availability
		mr3 = frappe.get_doc("Material Request", self._request(wo)["material_request"])
		frappe.set_user(self.prod)
		try:
			with self.assertRaises(frappe.PermissionError):
				cancel_request(mr3.name)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Material Request", mr3.name, "docstatus"), 1)

	# ------------------------------------------------------- 5. permissions

	def test_t24_permission_matrix_all_actions(self):
		"""Gudang cannot verify/send/touch WO mutation paths; produksi cannot
		create/cancel; bare user denied everything with an empty board."""
		wo, _ = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo)["material_request"])

		# gudang: verify and send denied
		frappe.set_user(self.gudang)
		try:
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(mr.name)
			with self.assertRaises(frappe.PermissionError):
				send_handover(mr.name)
			self.assertFalse(frappe.has_permission("Work Order", "write"))
			with self.assertRaises(frappe.PermissionError):
				finish(wo.name)  # WO mutation path
		finally:
			frappe.set_user("Administrator")

		# produksi: create + cancel denied
		frappe.set_user(self.prod)
		try:
			with self.assertRaises(frappe.PermissionError):
				create_request(wo.name)
			with self.assertRaises(frappe.PermissionError):
				cancel_request(mr.name)
		finally:
			frappe.set_user("Administrator")

		# bare user: everything denied, board readable-but-empty
		frappe.set_user(self.bare)
		try:
			with self.assertRaises(frappe.PermissionError):
				create_request(wo.name)
			with self.assertRaises(frappe.PermissionError):
				cancel_request(mr.name)
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(mr.name)
			with self.assertRaises(frappe.PermissionError):
				send_handover(mr.name)
			board = handover_board()  # must not raise
			self.assertEqual(board["lots"], [])
			self.assertEqual(board["requests"], [])
		finally:
			frappe.set_user("Administrator")

	# -------------------------------- 5b. role semantics: Stock User (user decision 2026-09-14)

	def test_t24_stock_user_role_semantics(self):
		"""Sisi gudang = Stock User JUGA (bukan hanya Gudang Barang Jadi):
		Stock-only -> hanya request (verify/send ditolak, flag gudang murni);
		Manufacturing+Stock -> dua sisi sekaligus (loop penuh satu akun)."""
		stock = self._make_user("t24.stock.role@prodapp.example.com", ["Stock User"])
		both = self._make_user("t24.both.role@prodapp.example.com", ["Stock User", "Manufacturing User"])
		wo, _ = self._lot_ready(120)

		# stock-only: flag gudang murni, boleh request, ditolak verify/send
		frappe.set_user(stock)
		try:
			board = handover_board()
			self.assertTrue(board["roles"]["is_gudang"])
			self.assertFalse(board["roles"]["is_produksi"])
			result = create_request(wo.name)
			self.assertEqual(flt(result["qty"]), 120)
			stock_mr = frappe.get_doc("Material Request", result["material_request"])
			self.assertEqual(stock_mr.docstatus, 1)
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(stock_mr.name)
			with self.assertRaises(frappe.PermissionError):
				send_handover(stock_mr.name)
		finally:
			frappe.set_user("Administrator")

		# manufacturing+stock: dua flag aktif, loop penuh dalam satu akun
		# (fresh WO — the duplicate-active guard blocks a second request on wo)
		wo2, _ = self._lot_ready(40)
		frappe.set_user(both)
		try:
			board = handover_board()
			self.assertTrue(board["roles"]["is_gudang"])
			self.assertTrue(board["roles"]["is_produksi"])
			both_mr = frappe.get_doc(
				"Material Request", create_request(wo2.name)["material_request"]
			)
			save_post_packing(both_mr.name, box_1=2, box_2=1)
			res = send_handover(both_mr.name)
			self.assertTrue(res["ok"])
			self.assertEqual(flt(res["qty"]), 40)
			self.assertEqual(res["stock_entry"], frappe.db.get_value(
				"Stock Entry Detail", {"material_request": both_mr.name}, "parent"
			))
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------- 6. atomicity: shortage

	def test_t24_send_insufficient_batch_stock_is_atomic(self):
		"""Batch drained after verification -> send refuses; zero partial
		documents survive (request-boundary rollback)."""
		wo, batch = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo)["material_request"])
		self._postpack(mr, box_1=12.5)

		# consume the batch at the desk AFTER verification
		drain = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer",
				"company": self.company,
				"items": [
					{
						"item_code": self.fg,
						"qty": 100,
						"basic_rate": 10,
						"s_warehouse": self.cold_wh,
						"t_warehouse": self.target_wh,
						"use_serial_batch_fields": 1,
						"batch_no": batch,
					}
				],
			}
		)
		drain.insert()
		drain.submit()

		frappe.db.savepoint("t24_shortage")
		try:
			with self.assertRaises(frappe.ValidationError):
				self._send(mr)
		finally:
			frappe.db.rollback(save_point="t24_shortage")

		self.assertEqual(
			len(frappe.get_all("Stock Entry Detail", filters={"material_request": mr.name})), 0
		)
		mr.reload()
		self.assertEqual(mr.status, "Pending")  # untouched, still reserved
		self.assertEqual(flt(mr.per_ordered), 0)

	# ---------------------------------- 7. native desk cancel of the SE

	def test_t24_desk_cancel_se_recomputes_board(self):
		"""Native desk SE cancel of a full send: the board returns the request
		to siap_kirim and a re-send works (derived truth: no submitted SE, still
		confirmed)."""
		wo, batch = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo)["material_request"])
		self._postpack(mr, box_1=12.5)
		result = self._send(mr)
		frappe.get_doc("Stock Entry", result["stock_entry"]).cancel()
		board = handover_board()
		self.assertEqual(flt(self._lot(board, wo.name)["physical_qty"]), 100)  # stock restored
		req = self._req(board, mr.name)
		self.assertEqual(req["lane"], "siap_kirim")  # nothing submitted against the MR anymore
		self.assertIsNone(req["stock_entry"])

		# re-send works
		result2 = self._send(mr)
		self.assertTrue(frappe.db.exists("Stock Entry", result2["stock_entry"]))
		self.assertEqual(flt(get_batch_qty(batch, self.target_wh)), 100)

	def test_fu23_wo_native_handover_status_field_syncs(self):
		"""FU23: Work Order.custom_handover_status (Select read-only di form
		Desk) mengikuti alur serah terima lewat doc_events + save_post_packing:
		belum -> Diminta Gudang -> Siap Kirim -> Terkirim; cancel mengosongkan;
		cancel SE (Desk) menurunkan kembali ke Siap Kirim."""
		status = lambda name: frappe.db.get_value(
			"Work Order", name, "custom_handover_status"
		)

		wo, _ = self._lot_ready(100)
		self.assertFalse(status(wo.name))  # belum pernah diminta (None/'' kosong)

		mr = frappe.get_doc("Material Request", self._request(wo)["material_request"])
		self.assertEqual(status(wo.name), "Diminta Gudang")  # MR on_submit

		# cancel dari lane request -> kembali kosong (MR on_cancel)
		frappe.set_user(self.gudang)
		try:
			cancel_request(mr.name)
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(status(wo.name))

		# alur lengkap: request -> verify -> send
		mr2 = frappe.get_doc("Material Request", self._request(wo)["material_request"])
		self.assertEqual(status(wo.name), "Diminta Gudang")
		self._postpack(mr2, box_1=12.5, box_2=8.25)  # db_set -> sync manual
		self.assertEqual(status(wo.name), "Siap Kirim")
		result = self._send(mr2)
		self.assertEqual(status(wo.name), "Terkirim")  # SE on_submit

		# desk SE cancel menurunkan state (SE on_cancel)
		frappe.get_doc("Stock Entry", result["stock_entry"]).cancel()
		self.assertEqual(status(wo.name), "Siap Kirim")

	# ------------------- FU29. pre-check gudang rute + route_available board

	def test_fu29_send_blocked_when_route_warehouse_lacks_batch(self):
		"""FU29 root cause (kasus nyata MR 00270): stok lot ada di gudang asal
		SE, tetapi rute request mengarah ke source setting yang kosong.
		send_handover wajib menolak terhadap from_warehouse RUTE (pesan
		Indonesia menyebut gudangnya, nol tulis) — bukan mati di submit native
		dengan error Inggris mentah."""
		wo, batch = self._lot_ready(50)
		prior = frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_source_warehouse"
		)
		try:
			warehouse_defaults_save(
				handover_warehouse=self.target_wh, handover_source_warehouse=self.src_wh
			)
			result = self._request(wo)
			mr = frappe.get_doc("Material Request", result["material_request"])
			self.assertEqual(mr.items[0].from_warehouse, self.src_wh)  # origin rute

			# peringatan dini di board: stok batch ini di gudang rute = 0
			req = self._req(result["board"], mr.name)
			self.assertEqual(flt(req["route_available"]), 0)

			self._postpack(mr, box_1=1)
			frappe.db.savepoint("fu29_blocked")
			try:
				with self.assertRaises(frappe.ValidationError) as ctx:
					self._send(mr)
			finally:
				frappe.db.rollback(save_point="fu29_blocked")
			self.assertIn("gudang asal", str(ctx.exception))
			self.assertIn(self.src_wh, str(ctx.exception))  # menyebut gudang rutenya
			self.assertEqual(
				len(frappe.get_all("Stock Entry Detail", filters={"material_request": mr.name})), 0
			)
		finally:
			warehouse_defaults_save(
				handover_warehouse=self.target_wh, handover_source_warehouse=prior
			)

	def test_fu29_route_available_full_and_send_still_ok(self):
		"""Rute = tempat batch berada (fallback lot warehouse): tanpa peringatan
		(route_available == qty) dan kirim tetap sukses — regresi jalur sehat."""
		wo, batch = self._lot_ready(30)
		result = self._request(wo)  # setting unset -> rute fallback ke lot warehouse
		mr = frappe.get_doc("Material Request", result["material_request"])
		req = self._req(result["board"], mr.name)
		self.assertEqual(flt(req["route_available"]), 30)
		self._postpack(mr, box_1=1)
		res = self._send(mr)
		self.assertEqual(flt(res["qty"]), 30)

	def test_fu29_batchless_send_follows_route_not_current_setting(self):
		"""Batchless drift (FU29): request dibuat saat source setting menunjuk
		pool yang berisi; setting LALU berubah -> kirim tetap mengikuti RUTE
		(MR from_warehouse) yang benar-benar dipakai SE, bukan pool setting
		baru. Kode lama memeriksa pool setting terkini dan salah memblokir."""
		wo = self._make_wo(40, item=self.fg_nb2)
		self._transfer(wo)
		self._manufacture(wo, 40)
		prior = frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_source_warehouse"
		)
		try:
			warehouse_defaults_save(
				handover_warehouse=self.target_wh, handover_source_warehouse=self.cold_wh
			)
			result = self._request(wo)  # rute = cold_wh, pool berisi 40
			mr = frappe.get_doc("Material Request", result["material_request"])
			self.assertEqual(mr.items[0].from_warehouse, self.cold_wh)
			req = self._req(result["board"], mr.name)
			self.assertEqual(flt(req["route_available"]), 40)

			# setting berubah SETELAH request dibuat — rute MR tidak ikut pindah
			warehouse_defaults_save(
				handover_warehouse=self.target_wh, handover_source_warehouse=self.src_wh
			)
			board = handover_board()
			self.assertEqual(flt(self._req(board, mr.name)["route_available"]), 40)

			self._postpack(mr)
			res = self._send(mr)  # route berisi: kirim sah walau setting kini src_wh
			self.assertEqual(flt(res["qty"]), 40)
		finally:
			warehouse_defaults_save(
				handover_warehouse=self.target_wh, handover_source_warehouse=prior
			)

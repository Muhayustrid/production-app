# T24 handover mutation actions — create/cancel request, post-packing, send
#
# Proves, by execution (task-24-brief 9-item coverage):
# 1. create_request: full + partial qty; over-available rejected with ZERO
#    writes; racing requests cannot over-reserve. Concurrency evidence follows
#    the T12 pattern from test_wo_transaction_proof.py — SEQUENTIAL calls under
#    the Work Order row lock (that runner used savepoints, not threads); the
#    for_update lock serializes concurrent creates and the second one
#    re-derives the reservation from the first one's committed MR.
# 2. save_post_packing: simple + full form (sisa computed server-side), caps
#    rejected with zero writes, WO boxes mirror (T28: qty/jam/qc postpacking
#    WO fields are NOT touched — owned by the workspace confirm_postpacking),
#    repeat blocked, gudang denied.
# 3. send_handover: stock moves Cold Storage -> target for EXACTLY good (SLE +
#    batch qty both warehouses), SE linked to MR, partial good -> MR Stopped,
#    full good -> MR Transferred (NOT stopped), duplicate send blocked,
#    reject/trial/sisa never move stock.
# 4. cancel_request: pre-verification only (native cancel, reservation
#    released); after post-packing blocked; with SE blocked; produksi denied.
# 5. Permissions: gudang cannot send/post-pack/touch WO mutations; produksi
#    cannot create/cancel MR; bare user denied everything, empty board.
# 6. Errors atomic: insufficient batch stock -> zero partial SE/SLE;
#    unsupported legacy WO -> refused before mutation.
# 7. Native desk SE cancel -> board recomputes; for a stopped MR the desk SE
#    cancel itself is natively blocked until a manual unstop — the limitation
#    is asserted (NO silent resurrection).
# 8. Boxes: text identifiers persist + redisplay, empties dropped, never
#    parsed ("12345" stays text).
# 9. Legacy edge: WO with two Manufacture SEs -> create AND send refuse.
#
# Every record is test-only (T24/t24-prefixed); the Frappe test framework rolls
# the run back. The two real warehouses are never touched.

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, now, random_string, today

from erpnext.manufacturing.doctype.work_order.work_order import (
    make_stock_entry as make_wo_stock_entry,
)
from erpnext.stock.doctype.batch.batch import get_batch_qty
from erpnext.stock.doctype.material_request.material_request import (
    update_status as update_mr_status,
)

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
		cls._receipt(cls.rm, 20000, cls.src_wh)  # covers the run (no per-test rollback)

		cls.prior_target = frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_warehouse"
		)
		warehouse_defaults_save(handover_warehouse=cls.target_wh)

		cls.gudang = cls._make_user(f"t24.gudang.{suffix.lower()}@prodapp.example.com", ["Gudang Barang Jadi"])
		cls.prod = cls._make_user(f"t24.prod.{suffix.lower()}@prodapp.example.com", ["Manufacturing User"])
		cls.bare = cls._make_user(f"t24.bare.{suffix.lower()}@prodapp.example.com", [])

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		warehouse_defaults_save(handover_warehouse=cls.prior_target)  # defensive restore
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
		wo = frappe.get_doc(
			{
				"doctype": "Work Order",
				"production_item": item or cls.fg,
				"bom_no": cls.bom if item in (None, cls.fg) else cls.bom_nb,
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

	def _request(self, wo, qty):
		"""create_request as the gudang actor (the matrix role)."""
		frappe.set_user(self.gudang)
		try:
			return create_request(wo.name, qty)
		finally:
			frappe.set_user("Administrator")

	def _postpack(self, mr, good, jam="13:00:00", qc="Administrator", reject=0, trial=0, **boxes):
		frappe.set_user(self.prod)
		try:
			return save_post_packing(mr.name, good, jam, qc, reject_qty=reject, trial_qty=trial, **boxes)
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

	# -------------------------------------------------- 1. create_request

	def test_t24_create_request_paths_boxes_and_zero_writes_on_reject(self):
		"""Full + partial qty; over-available and fractional-PCS rejected with
		ZERO writes; the request is PURE — no boxes on the MR (they moved to
		Post-Packing, user decision 2026-09-14)."""
		wo, batch = self._lot_ready(100)

		result = self._request(wo, 100)
		mr = frappe.get_doc("Material Request", result["material_request"])
		self.assertEqual(mr.docstatus, 1)
		self.assertEqual(mr.material_request_type, "Material Transfer")
		self.assertEqual(mr.set_from_warehouse, self.cold_wh)
		self.assertEqual(mr.set_warehouse, self.target_wh)
		self.assertEqual(mr.items[0].from_warehouse, self.cold_wh)
		self.assertEqual(mr.items[0].warehouse, self.target_wh)
		self.assertEqual(mr.items[0].custom_work_order, wo.name)
		self.assertEqual(flt(mr.items[0].qty), 100)
		self.assertIsNone(mr.custom_box_1)  # pure request: boxes come at Post-Packing
		self.assertIsNone(mr.custom_box_2)
		board = result["board"]
		req = self._req(board, mr.name)
		self.assertEqual(req["lane"], "request")
		self.assertEqual(req["boxes"], [])
		lot = self._lot(board, wo.name)
		self.assertEqual(flt(lot["reserved_qty"]), 100)
		self.assertEqual(flt(lot["available_qty"]), 0)
		self.assertEqual(flt(get_batch_qty(batch, self.cold_wh)), 100)  # request moves no stock

		# partial qty on a fresh lot
		wo2, _ = self._lot_ready(100)
		result2 = self._request(wo2, 30)
		board2 = result2["board"]
		self.assertEqual(flt(self._lot(board2, wo2.name)["reserved_qty"]), 30)
		self.assertEqual(flt(self._lot(board2, wo2.name)["available_qty"]), 70)

		# over-available -> rejected, zero writes (only the 30-qty MR exists)
		with self.assertRaises(frappe.ValidationError):
			self._request(wo2, 71)
		self.assertEqual(self._bound_mr_count(wo2.name), 1)

		# whole-PCS: fractional rejected when the stock UOM must be whole
		if frappe.db.get_value("UOM", self.uom, "must_be_whole_number"):
			with self.assertRaises(frappe.ValidationError):
				self._request(wo2, 0.5)
			self.assertEqual(self._bound_mr_count(wo2.name), 1)

	def test_t24_create_request_racing_cannot_over_reserve(self):
		"""Two requests cannot over-reserve. Evidence pattern (recorded):
		SEQUENTIAL calls under the WO row lock, as in test_wo_transaction_proof
		(T12): each create re-derives the committed reservation inside the
		for_update lock, so the second request sees the first one's MR."""
		wo, _ = self._lot_ready(100)
		self._request(wo, 60)
		with self.assertRaises(frappe.ValidationError):
			self._request(wo, 60)  # only 40 left -> cannot over-reserve
		result = self._request(wo, 40)  # exactly fills the lot
		self.assertEqual(flt(self._lot(result["board"], wo.name)["reserved_qty"]), 100)
		with self.assertRaises(frappe.ValidationError):
			self._request(wo, 1)
		self.assertEqual(self._bound_mr_count(wo.name), 2)

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
			self._request(legacy, 40)
		self.assertIn(legacy.name, str(ctx.exception))
		self.assertEqual(self._bound_mr_count(legacy.name), 0)  # zero mutation

		never = self._make_wo(50)  # submitted but no Manufacture yet
		with self.assertRaises(frappe.ValidationError):
			self._request(never, 10)
		self.assertEqual(self._bound_mr_count(never.name), 0)

		# send-side refusal on the same legacy WO (MR planted as on the desk)
		mr = self._desk_mr(legacy.name, legacy.production_item, 40)
		frappe.db.set_value("Material Request", mr.name, "custom_postpacking_confirmed", 1)
		frappe.db.set_value("Material Request", mr.name, "custom_good_qty_postpacking", 40)
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
				self._request(ready, 10)
			self.assertIn("Pengaturan", str(ctx.exception))
			self.assertEqual(self._bound_mr_count(ready.name), 0)
		finally:
			frappe.db.set_single_value("Manufacturing Settings", "custom_default_handover_warehouse", prior)

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

	# -------------------------------------------------- 2. save_post_packing

	def test_t24_post_packing_caps_sisa_mirror_and_write_once(self):
		"""Simple path + full form (sisa auto server-side), caps rejected with
		zero writes, WO boxes mirrored only (qty/jam/qc postpacking on WO
		untouched, T28), repeat blocked, gudang denied."""
		wo, _ = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo, 100)["material_request"])

		# gudang (wrong side) denied, nothing written
		frappe.set_user(self.gudang)
		try:
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(mr.name, 100, "13:00:00", "Administrator")
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("Material Request", mr.name, "custom_postpacking_confirmed"))

		# every cap/validation failure leaves the MR untouched
		bad_inputs = [
			dict(good=0),  # good must be > 0
			dict(good=101),  # good > requested
			dict(good=60, reject=30, trial=15),  # good+reject+trial > requested
			dict(good=60, reject=-1),  # negative
			dict(good=60, jam="bukan jam"),  # garbage time
			dict(good=60, qc="t24.nosuch.user"),  # invalid QC user
		]
		for kwargs in bad_inputs:
			with self.assertRaises(frappe.ValidationError):
				self._postpack(mr, **kwargs)
		mr.reload()
		self.assertFalse(mr.custom_postpacking_confirmed)
		self.assertEqual(flt(mr.custom_good_qty_postpacking), 0)
		self.assertEqual(flt(frappe.db.get_value("Work Order", wo.name, "custom_good_qty_postpacking")), 0)

		# simple path: request = whole remaining, sisa computed server-side;
		# boxes arrive HERE (produksi), not at the request — numeric-looking
		# text stays text, never parsed
		result = self._postpack(
			mr, 100, jam="09:30:00", qc="Administrator", box_1="BX-2026-A", box_2=" 12345 "
		)
		self.assertEqual(result["postpacking"]["sisa"], 0)
		self.assertEqual(result["postpacking"]["box_1"], "BX-2026-A")
		self.assertEqual(result["postpacking"]["box_2"], "12345")
		mr.reload()
		self.assertEqual(mr.custom_postpacking_confirmed, 1)
		self.assertEqual(flt(mr.custom_good_qty_postpacking), 100)
		self.assertEqual(flt(mr.custom_sisa_qty_postpacking), 0)
		self.assertEqual(mr.custom_box_1, "BX-2026-A")
		self.assertEqual(mr.custom_box_2, "12345")
		self.assertEqual(self._req(result["board"], mr.name)["lane"], "siap_kirim")
		self.assertEqual(self._req(result["board"], mr.name)["boxes"], ["BX-2026-A", "12345"])

		# T28: the WO postpacking qty/jam/qc fields are NOT mirrored (owned by
		# the workspace confirm_postpacking, before manufacture); ONLY boxes
		# edit the Work Order
		mirror = frappe.db.get_value(
			"Work Order", wo.name,
			["custom_good_qty_postpacking", "custom_reject_qty_postpacking", "custom_jam_packing", "custom_qc_packing", "custom_box_1", "custom_box_2"],
			as_dict=True,
		)
		self.assertEqual(flt(mirror.custom_good_qty_postpacking), 0)  # untouched
		self.assertIsNone(mirror.custom_jam_packing)
		self.assertIsNone(mirror.custom_qc_packing)
		self.assertEqual(mirror.custom_box_1, "BX-2026-A")
		self.assertEqual(mirror.custom_box_2, "12345")

		# repeat post-packing blocked (written ONCE)
		with self.assertRaises(frappe.ValidationError):
			self._postpack(mr, 50)

		# full form on a fresh request: good+reject+trial, sisa = 100-60-10-5;
		# single box -> the empty one is dropped everywhere
		wo2, _ = self._lot_ready(100)
		mr2 = frappe.get_doc("Material Request", self._request(wo2, 100)["material_request"])
		result2 = self._postpack(mr2, 60, jam="14:15:00", qc=self.prod, reject=10, trial=5, box_1="BX-2026-B")
		self.assertEqual(result2["postpacking"]["sisa"], 25)
		mr2.reload()
		self.assertEqual(flt(mr2.custom_sisa_qty_postpacking), 25)
		self.assertEqual(self._req(result2["board"], mr2.name)["boxes"], ["BX-2026-B"])
		mirror2 = frappe.db.get_value(
			"Work Order", wo2.name,
			["custom_good_qty_postpacking", "custom_reject_qty_postpacking", "custom_trial_qty_postpacking", "custom_sisa_qty_postpacking", "custom_box_1", "custom_box_2"],
			as_dict=True,
		)
		self.assertEqual(flt(mirror2.custom_good_qty_postpacking), 0)  # untouched (T28)
		self.assertEqual(flt(mirror2.custom_reject_qty_postpacking), 0)
		self.assertEqual(flt(mirror2.custom_trial_qty_postpacking), 0)
		self.assertEqual(flt(mirror2.custom_sisa_qty_postpacking), 0)
		self.assertEqual(mirror2.custom_box_1, "BX-2026-B")
		self.assertIsNone(mirror2.custom_box_2)

	def test_t28_wo_postpacking_not_touched_by_handover(self):
		"""T28: the WO postpacking fields (written by the workspace
		confirm_postpacking BEFORE manufacture, T27) survive save_post_packing;
		only Box 1/2 mirror; the MR block holds the handover truth (60)."""
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
		mr = frappe.get_doc("Material Request", self._request(wo, 60)["material_request"])

		result = self._postpack(mr, 60, jam="14:00:00", qc="Administrator", box_1="BX-28-A", box_2="BX-28-B")

		wob = frappe.db.get_value(
			"Work Order", wo.name,
			["custom_good_qty_postpacking", "custom_reject_qty_postpacking", "custom_trial_qty_postpacking", "custom_sisa_qty_postpacking", "custom_jam_packing", "custom_qc_packing", "custom_box_1", "custom_box_2"],
			as_dict=True,
		)
		self.assertEqual(flt(wob.custom_good_qty_postpacking), 100)  # NOT capped to the MR's 60
		self.assertEqual(flt(wob.custom_reject_qty_postpacking), 2)
		self.assertEqual(flt(wob.custom_trial_qty_postpacking), 1)
		self.assertEqual(flt(wob.custom_sisa_qty_postpacking), -3)
		self.assertEqual(str(wob.custom_jam_packing), "8:00:00")
		self.assertEqual(wob.custom_qc_packing, "Administrator")
		self.assertEqual(wob.custom_box_1, "BX-28-A")  # box mirror stays (FU7)
		self.assertEqual(wob.custom_box_2, "BX-28-B")
		mr.reload()  # the MR keeps its own block
		self.assertEqual(flt(mr.custom_good_qty_postpacking), 60)
		self.assertEqual(flt(mr.custom_sisa_qty_postpacking), 0)
		self.assertEqual(mr.custom_postpacking_confirmed, 1)

	# --------------------------------------------------------- 3. send

	def test_t24_send_full_partial_duplicate_exact_quantities(self):
		"""Full send: exactly good moves Cold Storage -> target (ledger + batch
		qty), MR Transferred (NOT stopped); partial: MR Stopped; duplicate send
		blocked; reject/trial/sisa never move stock."""
		# full: good = requested
		wo, batch = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo, 100)["material_request"])
		self._postpack(mr, 100)
		result = self._send(mr)
		self.assertFalse(result["stopped"])
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
		self.assertEqual(mr.status, "Transferred")
		self.assertEqual(flt(mr.per_ordered), 100)
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

		# partial: good < requested -> MR stopped (short-closed)
		wo2, _ = self._lot_ready(100)
		mr2 = frappe.get_doc("Material Request", self._request(wo2, 100)["material_request"])
		self._postpack(mr2, 60)
		result2 = self._send(mr2)
		self.assertTrue(result2["stopped"])
		mr2.reload()
		self.assertEqual(mr2.status, "Stopped")
		self.assertEqual(flt(mr2.per_ordered), 60)
		self.assertEqual(self._req(result2["board"], mr2.name)["lane"], "terkirim")

		# reject/trial/sisa never move stock: only the good movement exists
		wo3, batch3 = self._lot_ready(100)
		mr3 = frappe.get_doc("Material Request", self._request(wo3, 100)["material_request"])
		self._postpack(mr3, 80, reject=10, trial=5)  # sisa 5
		result3 = self._send(mr3)
		sles = frappe.get_all(
			"Stock Ledger Entry", filters={"voucher_no": result3["stock_entry"], "is_cancelled": 0},
			fields=["warehouse", "actual_qty"],
		)
		self.assertEqual(len(sles), 2)  # exactly one out + one in
		self.assertEqual(sorted(flt(s.actual_qty) for s in sles), [-80, 80])
		self.assertEqual(flt(get_batch_qty(batch3, self.target_wh)), 80)

	# ------------------------------- FU8. batchless lots: pool + no-batch send

	def test_fu8_batchless_pool_actions_and_send(self):
		"""Follow-up 8: batchless FG — the pool is item-level: requests from TWO
		WOs of the same item draw one balance and cannot over-reserve it;
		post-packing works; send creates a NO-batch Stock Entry that moves
		exactly good out of the pool; short-close stops the MR."""
		wo1 = self._make_wo(60, item=self.fg_nb)
		self._transfer(wo1)
		self._manufacture(wo1, 60)
		wo2 = self._make_wo(40, item=self.fg_nb)
		self._transfer(wo2)
		self._manufacture(wo2, 40)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.cold_wh)), 100)  # one pool

		result = self._request(wo1, 70)  # reserves from the shared pool
		mr = frappe.get_doc("Material Request", result["material_request"])
		lot2 = self._lot(result["board"], wo2.name)
		self.assertTrue(lot2["batchless"])
		self.assertIsNone(lot2["batch"])
		self.assertEqual(flt(lot2["available_qty"]), 30)  # 100 - 70, same pool

		# over-pool via the OTHER WO: rejected, zero writes (pool, not per-WO)
		with self.assertRaises(frappe.ValidationError):
			self._request(wo2, 31)
		self.assertEqual(self._bound_mr_count(wo2.name), 0)

		self._postpack(mr, 50, jam="08:20:00", qc="Administrator", box_1="BX-NB-1")
		res = self._send(mr)
		self.assertIsNone(res["batch"])
		se = frappe.get_doc("Stock Entry", res["stock_entry"])
		self.assertFalse(se.items[0].batch_no)  # batchless: no batch anywhere
		self.assertFalse(se.items[0].serial_and_batch_bundle)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.cold_wh)), 50)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.target_wh)), 50)
		self.assertTrue(res["stopped"])  # 50 < 70 short-closed
		# box mirrors to the batchless WO exactly like the batch path
		self.assertEqual(
			frappe.db.get_value("Work Order", wo1.name, "custom_box_1"), "BX-NB-1"
		)

		# duplicate send still blocked; pool unchanged by the failed attempt
		with self.assertRaises(frappe.ValidationError):
			self._send(mr)
		self.assertEqual(flt(_item_stock(self.fg_nb, self.cold_wh)), 50)

	# --------------------------------------------------------- 4. cancel

	def test_t24_cancel_request_only_before_verification(self):
		"""Cancel pre-verification (native, reservation released, board updated);
		blocked after post-packing and after send; produksi denied."""
		wo, _ = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo, 40)["material_request"])
		self.assertEqual(flt(self._lot(handover_board(), wo.name)["available_qty"]), 60)

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

		# after post-packing -> blocked
		wo2, _ = self._lot_ready(100)
		mr2 = frappe.get_doc("Material Request", self._request(wo2, 40)["material_request"])
		self._postpack(mr2, 40)
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

		# produksi (Manufacturing User) denied
		mr3 = frappe.get_doc("Material Request", self._request(wo2, 10)["material_request"])
		frappe.set_user(self.prod)
		try:
			with self.assertRaises(frappe.PermissionError):
				cancel_request(mr3.name)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Material Request", mr3.name, "docstatus"), 1)

	# ------------------------------------------------------- 5. permissions

	def test_t24_permission_matrix_all_actions(self):
		"""Gudang cannot post-pack/send/touch WO mutation paths; produksi cannot
		create/cancel; bare user denied everything with an empty board."""
		wo, _ = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo, 40)["material_request"])

		# gudang: post-pack and send denied
		frappe.set_user(self.gudang)
		try:
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(mr.name, 40, "13:00:00", "Administrator")
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
				create_request(wo.name, 10)
			with self.assertRaises(frappe.PermissionError):
				cancel_request(mr.name)
		finally:
			frappe.set_user("Administrator")

		# bare user: everything denied, board readable-but-empty
		frappe.set_user(self.bare)
		try:
			with self.assertRaises(frappe.PermissionError):
				create_request(wo.name, 10)
			with self.assertRaises(frappe.PermissionError):
				cancel_request(mr.name)
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(mr.name, 10, "13:00:00", "Administrator")
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
		Stock-only -> hanya request (post-pack/send ditolak, flag gudang murni);
		Manufacturing+Stock -> dua sisi sekaligus (loop penuh satu akun)."""
		stock = self._make_user("t24.stock.role@prodapp.example.com", ["Stock User"])
		both = self._make_user("t24.both.role@prodapp.example.com", ["Stock User", "Manufacturing User"])
		wo, _ = self._lot_ready(120)

		# stock-only: flag gudang murni, boleh request, ditolak post-pack/send
		frappe.set_user(stock)
		try:
			board = handover_board()
			self.assertTrue(board["roles"]["is_gudang"])
			self.assertFalse(board["roles"]["is_produksi"])
			stock_mr = frappe.get_doc(
				"Material Request", create_request(wo.name, 30)["material_request"]
			)
			self.assertEqual(stock_mr.docstatus, 1)
			with self.assertRaises(frappe.PermissionError):
				save_post_packing(stock_mr.name, 30, "13:00:00", "Administrator")
			with self.assertRaises(frappe.PermissionError):
				send_handover(stock_mr.name)
		finally:
			frappe.set_user("Administrator")

		# manufacturing+stock: dua flag aktif, loop penuh dalam satu akun
		frappe.set_user(both)
		try:
			board = handover_board()
			self.assertTrue(board["roles"]["is_gudang"])
			self.assertTrue(board["roles"]["is_produksi"])
			both_mr = frappe.get_doc(
				"Material Request", create_request(wo.name, 40)["material_request"]
			)
			save_post_packing(both_mr.name, 40, "13:00:00", "Administrator")
			res = send_handover(both_mr.name)
			self.assertTrue(res["ok"])
			self.assertEqual(res["stock_entry"], both_mr.name and frappe.db.get_value(
				"Stock Entry Detail", {"material_request": both_mr.name}, "parent"
			))
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------- 6. atomicity: shortage + conflict

	def test_t24_send_insufficient_batch_stock_is_atomic(self):
		"""Batch drained after post-packing -> send refuses; zero partial
		documents survive (request-boundary rollback)."""
		wo, batch = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo, 100)["material_request"])
		self._postpack(mr, 100)

		# consume the batch at the desk AFTER post-packing
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
		"""Native desk SE cancel: full send -> board returns the request to
		siap_kirim and a re-send works; partial send -> the MR is Stopped and
		NOTHING resurrects it: the board keeps flag "stopped", send refuses,
		and even the native desk SE cancel is natively blocked until a MANUAL
		desk unstop (sharper than the documented limitation — the unstop must
		come FIRST, then the SE cancel)."""
		# full send, then desk-cancel the SE
		wo, batch = self._lot_ready(100)
		mr = frappe.get_doc("Material Request", self._request(wo, 100)["material_request"])
		self._postpack(mr, 100)
		result = self._send(mr)
		frappe.get_doc("Stock Entry", result["stock_entry"]).cancel()
		board = handover_board()
		self.assertEqual(flt(self._lot(board, wo.name)["physical_qty"]), 100)  # stock restored
		req = self._req(board, mr.name)
		self.assertEqual(req["lane"], "siap_kirim")  # nothing submitted against the MR anymore
		self.assertIsNone(req["stock_entry"])

		# re-send works (derived truth: no submitted SE, still confirmed)
		result2 = self._send(mr)
		self.assertTrue(frappe.db.exists("Stock Entry", result2["stock_entry"]))
		self.assertEqual(flt(get_batch_qty(batch, self.target_wh)), 100)

		# partial send -> stopped; no silent resurrection anywhere
		wo2, _ = self._lot_ready(100)
		mr2 = frappe.get_doc("Material Request", self._request(wo2, 100)["material_request"])
		self._postpack(mr2, 60)
		result3 = self._send(mr2)
		self.assertTrue(result3["stopped"])
		se2_name = result3["stock_entry"]
		# stopped WITH a submitted SE: the board keeps it in terkirim (lane by
		# SE existence; the flag-"stopped" dead-request state is the SE-less
		# case, T23) — and nothing resurrects it
		req2 = self._req(handover_board(), mr2.name)
		self.assertEqual(req2["lane"], "terkirim")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._send(mr2)
		self.assertIn("Stopped", str(ctx.exception))

		# even the native desk SE cancel is blocked while the MR is stopped
		# (the guard fires mid-cancel; a real request rolls the docstatus write
		# back, so the boundary is emulated with a savepoint, T21 pattern)
		frappe.db.savepoint("t24_stopblock")
		try:
			with self.assertRaises(frappe.InvalidStatusError):
				frappe.get_doc("Stock Entry", se2_name).cancel()
		finally:
			frappe.db.rollback(save_point="t24_stopblock")

		# manual desk unstop, THEN the SE cancel works; board recomputes
		update_mr_status(mr2.name, "Pending")
		frappe.get_doc("Stock Entry", se2_name).cancel()
		board3 = handover_board()
		self.assertEqual(flt(self._lot(board3, wo2.name)["physical_qty"]), 100)
		req3 = self._req(board3, mr2.name)
		self.assertEqual(req3["lane"], "siap_kirim")
		self.assertEqual(
			len(frappe.get_all("Stock Entry Detail", filters={"material_request": mr2.name, "docstatus": 1})), 0
		)

"""Task 21 - end-to-end integration through the APP layer (spec 7 endpoints).

Every Phase-1 proof scenario is re-run through the app's own whitelisted
endpoints (api.py) instead of core calls, with the proof's mandatory numbers,
asserting FINAL state (Bin / Work Order / packing summary), not just return
values:

- P1a via app (S1): transfer(aktual 10+2) -> finish(95/5) -> Bin FG 95,
  produced 95, loss 5, Completed, consumption 2000 (rows + FG SLE + balanced
  GL), custom_p_* + petugas recorded, WO summary hook correct;
- P1b-v1 via app (S2): good 105 without allowance -> NEEDS_ALLOWANCE
  (Indonesian), no Stock Entry, nothing moved;
- P4 via app (S3): staged transfers 62.5+12.5 / 37+7.4 / 5.5+1.1 and three
  partial sessions 600/360/40 -> produced 1000 Completed, material_transferred
  1050, sum dipakai 100/20, WIP left 5/1, Stores net 0, value 20000;
- P5 via app (S4): dipakai 9.5/2 -> WIP left 0.5, valuation 1950 (SLE);
- P10 via app (S5): good = 0 rejected with supervisor directions (the
  consumption route stays DEACTIVATED), nothing recorded;
- P13 via app (S6): 2-operation WO, one-tap complete_operation (duration ~0)
  x2 -> finish -> Completed; the 950/1000 variant does NOT inflate completed,
  pending 50 -> close_work_order -> Closed with 950 kept;
- P8 via app (S7): transfer+finish -> cancel_last_step(expected_target taken
  from the DETAIL endpoint) reverses stock/status/summary; FG used elsewhere
  -> blocked with the "terpakai" reason; cancel_production atomically cancels
  everything -> WO Cancelled;
- T5.2b (S9): replay same key+payload -> duplicate:true with a single effect;
  same key, different payload -> rejected;
- T5.2c (S10): a Desk-made Manufacture SE (no custom_p_*) on an app WO keeps
  detail + summary consistent (good core-derived); Desk-cancel re-syncs via
  the hook;
- T5.2d (S11): Stopped / Reserved WOs blocked in Indonesian on the mutation
  endpoints (and listed in detail blocked_reasons);
- STATE_CHANGED (S12): stale expected_target -> StateChangedError, nothing
  cancelled;
- T5.2a (S8, TestE2EConcurrency): two operators finish the SAME work order in
  TRUE PARALLEL - two threads, each with its own full frappe site context
  (frappe.init + frappe.connect) and its own DB transaction/commit, released
  through a barrier. Serialization is the app's Work Order row lock (10.1):
  exactly ONE session completes fully, the loser re-reads state AFTER the lock
  and is gated (NEEDS_ALLOWANCE) - never a double produced_qty, sum of SEs ==
  the one valid input, never a raw 500. This is the P9 primitive exercised
  through the app endpoints themselves (no sequential simulation needed).

Isolation, two layers:
- Company/items/BOM are the shared PDTC fixtures, but every scenario runs in
  its own E2E- Warehouses (empty FIFO queues at proof rates RM1=100 / RM2=500).
  The shared PDTC Stores/WIP hold committed foreign stock (0-rate fixture
  receipts, leftovers of earlier runs) whose FIFO units would otherwise be
  consumed first and break the proof's valuation numbers (2000/1950/20000);
  queues are per (item, warehouse), so own warehouses make the numbers
  deterministic forever.
- S1-S7/S9-S12 never commit (class transaction rolls back at class end;
  shared-warehouse numbers asserted as DELTAS). S8 commits by design (the race
  needs committed visibility) and therefore verifies its own full cleanup
  INLINE - leftover committed stock on this site has repeatedly poisoned other
  suites (task-19 review round), so it must fail loudly, never linger.
Test data carries the E2E- prefix (users, idempotency keys, warehouses).
"""

import os
import threading

import frappe
from erpnext.stock.doctype.batch.batch import get_batch_qty
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, random_string

from production_app import api
from production_app.exceptions import NeedsAllowanceError, StateChangedError
from production_app.tests import factories

OPERATOR1 = "e2e.operator1@example.com"
OPERATOR2 = "e2e.operator2@example.com"
SUPERVISOR = "e2e.supervisor@example.com"
E2E_STORES = "E2E Stores - PDTC"
E2E_WIP = "E2E WIP - PDTC"
E2E_FG = "E2E FG - PDTC"


class E2EFixture(IntegrationTestCase):
	"""Shared setup + app-layer helpers (no test methods of its own)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		factories.make_bom()
		cls._setup_warehouses()
		cls.operator1 = factories.make_user(OPERATOR1, roles=["Production Operator"])
		cls.operator2 = factories.make_user(OPERATOR2, roles=["Production Operator"])
		cls.supervisor = factories.make_user(SUPERVISOR, roles=["Production Supervisor"])
		frappe.db.commit()

	@staticmethod
	def _setup_warehouses():
		"""Own E2E warehouses under the PDTC Stores group: empty FIFO queues so
		the proof's valuation numbers (konsumsi 2000, SLE 1950, 20000) hold no
		matter what committed stock the shared PDTC warehouses carry. Each
		warehouse gets its OWN stock account (mirroring the PDTC setup) - with a
		shared account every intra-E2E transfer/manufacture nets Dr==Cr on one
		account and core writes no GL rows at all (proof P1a asserts a balanced
		2000 voucher)."""
		root = frappe.db.get_value(
			"Account", {"company": factories.COMPANY, "account_name": "Stock Assets", "is_group": 1}
		)
		for name, acct_name in (
			(E2E_STORES, "E2E Stores Stock"),
			(E2E_WIP, "E2E WIP Stock"),
			(E2E_FG, "E2E FG Stock"),
		):
			account = f"{acct_name} - {factories.ABBR}"
			if not frappe.db.exists("Account", account):
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": acct_name,
						"account_type": "Stock",
						"parent_account": root,
						"company": factories.COMPANY,
						"account_currency": "USD",
					}
				).insert()
			if not frappe.db.exists("Warehouse", name):
				frappe.get_doc(
					{
						"doctype": "Warehouse",
						"warehouse_name": name[: -len(" - PDTC")],
						"company": factories.COMPANY,
						"parent_warehouse": factories.STORES,
						"account": account,
					}
				).insert()
			elif frappe.db.get_value("Warehouse", name, "account") != account:
				frappe.db.set_value("Warehouse", name, "account", account)

	def setUp(self):
		super().setUp()
		self.keys = []
		self.addCleanup(self._cleanup)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	# ---------------------------------------------------------------- helpers

	def _cleanup(self):
		frappe.set_user("Administrator")
		for key in self.keys:
			if frappe.db.exists("Production Request Log", key):
				frappe.delete_doc("Production Request Log", key, ignore_permissions=True, force=True)

	def _key(self):
		key = "E2E-" + random_string(10)
		self.keys.append(key)
		return key

	def _as(self, user):
		frappe.set_user(user)

	def _issue_out(self, item, warehouse, qty, batch_no=None):
		"""Desk Material Issue out of an E2E warehouse (in-class, rolled back)."""
		self._as("Administrator")
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Issue",
				"purpose": "Material Issue",
				"company": factories.COMPANY,
				"items": [
					{
						"item_code": item,
						"s_warehouse": warehouse,
						"qty": qty,
						"use_serial_batch_fields": 1 if batch_no else 0,
						"batch_no": batch_no,
					}
				],
			}
		)
		se.insert()
		se.submit()

	def _drain_e2e_fg_and_wip(self):
		"""Empty the E2E FG/WIP leftovers of earlier scenarios so a scenario's
		consumption/cancel numbers are exactly its own transfer (batch-aware:
		RM1 and FG are batch items, the pre-checks net per warehouse)."""
		for item, warehouse, batched in (
			(factories.FG, E2E_FG, True),
			(factories.RM1, E2E_WIP, True),
			(factories.RM2, E2E_WIP, False),
		):
			if batched:
				for batch in get_batch_qty(item_code=item, warehouse=warehouse) or []:
					if flt(batch.qty) > 0:
						self._issue_out(item, warehouse, batch.qty, batch.batch_no)
			else:
				left = self._bin(item, warehouse)
				if left > 0:
					self._issue_out(item, warehouse, left)

	def _stock_recipe(self, rm1_qty=10, rm2_qty=2):
		"""Proof recipe stocked into the E2E Stores at proof rates."""
		factories.stock_in(factories.RM1, E2E_STORES, rm1_qty, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, E2E_STORES, rm2_qty, 500)

	def _make_wo(self, qty=100):
		"""Draft + submit WO over the E2E warehouses (BOM FG 100 = RM1 10 + RM2 2)."""
		wo = frappe.get_doc(
			{
				"doctype": "Work Order",
				"naming_series": "PDTC-WO-.####",
				"company": factories.COMPANY,
				"production_item": factories.FG,
				"bom_no": factories.make_bom(),
				"qty": qty,
				"stock_uom": "Nos",
				"wip_warehouse": E2E_WIP,
				"fg_warehouse": E2E_FG,
				"source_warehouse": E2E_STORES,
			}
		)
		wo.insert()
		wo.submit()
		return wo.name

	def _make_wo_operations(self, bom_no, qty=100):
		"""Operations WO over the E2E warehouses; one Job Card per operation."""
		wo = frappe.get_doc(
			{
				"doctype": "Work Order",
				"naming_series": "PDTC-WO-.####",
				"company": factories.COMPANY,
				"production_item": factories.FG,
				"bom_no": bom_no,
				"qty": qty,
				"stock_uom": "Nos",
				"wip_warehouse": E2E_WIP,
				"fg_warehouse": E2E_FG,
				"source_warehouse": E2E_STORES,
			}
		)
		wo.insert()
		wo.get_items_and_operations_from_bom()
		wo.submit()
		job_cards = frappe.get_all(
			"Job Card",
			filters={"work_order": wo.name},
			fields=["name", "operation", "operation_id", "for_quantity", "docstatus"],
			order_by="creation asc, name asc",
		)
		return wo.name, job_cards

	def _wo_with_transfer(self, items_aktual=None):
		"""WO 100 (BOM 10 + 2), recipe stocked, materials picked via the app."""
		wo = self._make_wo()
		self._stock_recipe()
		self._as(self.operator1)
		api.transfer_material(wo, items_aktual, self._key())
		return wo

	def _transfer(self, wo, items_aktual=None, user=None):
		self._as(user or self.operator1)
		return api.transfer_material(wo, items_aktual, self._key())

	def _finish(self, wo, packing, user=None):
		self._as(user or self.operator1)
		return api.finish_production(wo, packing, self._key())

	def _cancel_last(self, wo, expected, user=None):
		self._as(user or self.supervisor)
		return api.cancel_last_step(wo, expected, self._key())

	def _close(self, wo, reason, user=None):
		self._as(user or self.supervisor)
		return api.close_work_order(wo, reason, self._key())

	def _detail(self, wo, user=None):
		self._as(user or self.operator1)
		return api.get_work_order_detail(wo)

	def _wo(self, name):
		return frappe.get_doc("Work Order", name)

	def _bin(self, item, warehouse):
		return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))

	def _batch_qty(self, batch_no, warehouse):
		return flt(get_batch_qty(batch_no, warehouse) or 0)

	def _snapshot(self):
		"""E2E-warehouse levels; scenarios assert DELTAS of these (one
		transaction per class - earlier scenarios leave their numbers in)."""
		return {
			"fg": self._bin(factories.FG, E2E_FG),
			"stores_rm1": self._bin(factories.RM1, E2E_STORES),
			"stores_rm2": self._bin(factories.RM2, E2E_STORES),
			"wip_rm1": self._bin(factories.RM1, E2E_WIP),
			"wip_rm2": self._bin(factories.RM2, E2E_WIP),
			"wip_brm1": self._batch_qty(factories.BATCH_RM1, E2E_WIP),
		}

	def _manufacture_ses(self, wo_name):
		return frappe.get_all(
			"Stock Entry",
			filters={"work_order": wo_name, "purpose": "Manufacture", "docstatus": 1},
			order_by="creation asc",
			pluck="name",
		)

	def _material_rows(self, se_name):
		rows = frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": se_name, "parenttype": "Stock Entry", "is_finished_item": 0},
			fields=["item_code", "qty", "amount"],
		)
		return {r.item_code: (flt(r.qty, 3), flt(r.amount)) for r in rows}

	def _fg_row(self, se_name):
		row = frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": se_name, "parenttype": "Stock Entry", "is_finished_item": 1},
			fields=["qty", "amount"],
		)[0]
		return flt(row.qty), flt(row.amount)

	def _fg_sle_valuation(self, se_names):
		"""FG stock-value from the SLEs (proof semantics: SLE valuation of the
		finished goods = consumption value actually capitalized)."""
		return flt(
			sum(
				flt(r.stock_value_difference)
				for r in frappe.get_all(
					"Stock Ledger Entry",
					filters={
						"voucher_type": "Stock Entry",
						"voucher_no": ("in", se_names),
						"item_code": factories.FG,
						"is_cancelled": 0,
					},
					fields=["stock_value_difference"],
				)
			)
		)

	def _gl_totals(self, se_name):
		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": se_name, "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		return flt(sum(r.debit for r in rows)), flt(sum(r.credit for r in rows))

	def _fg_batch_of(self, se_name):
		return frappe.db.get_value(
			"Stock Entry Detail", {"parent": se_name, "item_code": factories.FG}, "batch_no"
		)


class TestE2EProofScenarios(E2EFixture):
	"""S1-S7 and S9-S12 (sequential; nothing commits, class rollback cleans)."""

	# ------------------------------------------------------- S1 - P1a via app

	def test_s1_p1a_full_flow_via_app(self):
		before = self._snapshot()
		wo = self._wo_with_transfer(items_aktual={factories.RM1: 10, factories.RM2: 2})
		result = self._finish(
			wo,
			{
				"good": 95,
				"loss_eksplisit": 5,
				"reject": 1,
				"trial": 0.5,
				"sisa": 2,
				"bahan_dipakai": {factories.RM1: 10, factories.RM2: 2},
			},
		)

		self.assertFalse(result.get("duplicate"))
		self.assertEqual(result["stock_entry"], self._manufacture_ses(wo)[0])

		# FINAL state: stock, work order, per-session batch
		self.assertEqual(self._bin(factories.FG, E2E_FG), before["fg"] + 95.0)
		self.assertEqual(self._bin(factories.RM1, E2E_WIP), before["wip_rm1"])  # 10 in, 10 out
		self.assertEqual(self._bin(factories.RM2, E2E_WIP), before["wip_rm2"])
		self.assertEqual(self._batch_qty(self._fg_batch_of(result["stock_entry"]), E2E_FG), 95.0)
		wo_doc = self._wo(wo)
		self.assertEqual(
			(wo_doc.produced_qty, wo_doc.process_loss_qty, wo_doc.status), (95.0, 5.0, "Completed")
		)

		# consumption 2000: actual material rows (NOT BOM-proportional), FG value,
		# FG SLE valuation, balanced GL voucher
		materials = self._material_rows(result["stock_entry"])
		self.assertEqual(
			{item: qty for item, (qty, _amount) in materials.items()},
			{factories.RM1: 10.0, factories.RM2: 2.0},
		)
		self.assertEqual(flt(sum(amount for _q, amount in materials.values())), 2000.0)
		self.assertEqual(self._fg_row(result["stock_entry"]), (95.0, 2000.0))
		self.assertEqual(self._fg_sle_valuation([result["stock_entry"]]), 2000.0)
		debit, credit = self._gl_totals(result["stock_entry"])
		self.assertEqual((debit, credit), (2000.0, 2000.0))

		# custom_p_* + petugas persisted on the Stock Entry
		se = frappe.get_doc("Stock Entry", result["stock_entry"])
		self.assertEqual(
			(se.custom_p_good_qty, se.custom_p_reject_qty, se.custom_p_trial_qty, se.custom_p_sisa_qty),
			(95.0, 1.0, 0.5, 2.0),
		)
		self.assertEqual(se.custom_p_petugas_packing, self.operator1)

		# WO packing summary synced by the Stock Entry hook, served by the detail
		wo_doc.reload()
		self.assertEqual(wo_doc.custom_good_qty_postpacking, 95.0)
		self.assertEqual(wo_doc.custom_reject_qty_postpacking, 1.0)
		self.assertEqual(wo_doc.custom_trial_qty_postpacking, 0.5)
		self.assertEqual(wo_doc.custom_sisa_qty_postpacking, 2.0)
		self.assertEqual(wo_doc.custom_qc_packing, self.operator1)
		detail = self._detail(wo)
		self.assertEqual(detail["packing_summary"]["custom_good_qty_postpacking"], 95.0)
		entry = next(e for e in detail["stock_entries"] if e["name"] == result["stock_entry"])
		self.assertEqual((entry["good"], entry["petugas_packing"]), (95.0, self.operator1))

	# -------------------------------------------------- S2 - P1b-v1 via app

	def test_s2_p1b_overproduction_needs_allowance(self):
		wo = self._wo_with_transfer()
		before = self._snapshot()
		with self.assertRaises(NeedsAllowanceError) as cm:
			self._finish(wo, {"good": 105})
		self.assertEqual(cm.exception.code, "NEEDS_ALLOWANCE")
		self.assertIn("toleransi produksi", str(cm.exception))

		# FINAL state: nothing happened at all
		self.assertEqual(self._manufacture_ses(wo), [])
		self.assertEqual(self._wo(wo).produced_qty, 0.0)
		self.assertEqual(self._snapshot(), before)

	# -------------------------------------------------------- S3 - P4 via app

	def test_s3_p4_three_partial_sessions(self):
		wo = self._make_wo(qty=1000)
		self._stock_recipe(rm1_qty=105, rm2_qty=21)
		before = self._snapshot()
		# transfers move the WHOLE staged pick out of Stores (proof: Stores -105)
		after_transfer_stores_rm1 = before["stores_rm1"] - 105.0

		initial_extra = frappe.db.get_single_value(
			"Manufacturing Settings", "transfer_extra_materials_percentage"
		)
		frappe.db.set_single_value("Manufacturing Settings", "transfer_extra_materials_percentage", 5.5)
		try:
			# staged picks, proof P4 numbers (sum 105/21 = requirement + 5%)
			self._transfer(wo, {factories.RM1: 62.5, factories.RM2: 12.5})
			self._transfer(wo, {factories.RM1: 37, factories.RM2: 7.4})
			self._transfer(wo, {factories.RM1: 5.5, factories.RM2: 1.1})
			self.assertEqual(self._wo(wo).material_transferred_for_manufacturing, 1050.0)
			self.assertEqual(self._bin(factories.RM1, E2E_STORES), after_transfer_stores_rm1)

			# three packing sessions with per-session actual consumption
			sessions = [
				self._finish(wo, {"good": 600, "bahan_dipakai": {factories.RM1: 60, factories.RM2: 12}}),
				self._finish(wo, {"good": 360, "bahan_dipakai": {factories.RM1: 36, factories.RM2: 7.2}}),
				self._finish(wo, {"good": 40, "bahan_dipakai": {factories.RM1: 4, factories.RM2: 0.8}}),
			]
		finally:
			frappe.db.set_single_value(
				"Manufacturing Settings", "transfer_extra_materials_percentage", initial_extra
			)
		self.assertEqual(
			frappe.db.get_single_value("Manufacturing Settings", "transfer_extra_materials_percentage"),
			initial_extra,
		)

		self.assertEqual([r["produced"] for r in sessions], [600.0, 960.0, 1000.0])
		self.assertEqual([r["status"] for r in sessions], ["In Process", "In Process", "Completed"])

		# FINAL state: no double consumption, staged transfer respected, WIP left
		ses = self._manufacture_ses(wo)
		self.assertEqual(len(ses), 3)
		used = {factories.RM1: 0.0, factories.RM2: 0.0}
		value = 0.0
		for se_name in ses:
			for item, (qty, amount) in self._material_rows(se_name).items():
				used[item] = flt(used[item] + qty)
				value += amount
		self.assertEqual(used, {factories.RM1: 100.0, factories.RM2: 20.0})  # sum dipakai, no doubling
		self.assertEqual(value, 20000.0)  # 100x100 + 20x500
		self.assertEqual(self._fg_sle_valuation(ses), 20000.0)
		self.assertEqual(self._bin(factories.RM1, E2E_WIP), before["wip_rm1"] + 5.0)  # not forced to 0
		self.assertEqual(self._bin(factories.RM2, E2E_WIP), before["wip_rm2"] + 1.0)
		self.assertEqual(self._bin(factories.FG, E2E_FG), before["fg"] + 1000.0)
		self.assertEqual(self._bin(factories.RM1, E2E_STORES), after_transfer_stores_rm1)
		wo_doc = self._wo(wo)
		self.assertEqual((wo_doc.produced_qty, wo_doc.status), (1000.0, "Completed"))
		self.assertEqual(wo_doc.custom_good_qty_postpacking, 1000.0)

	# -------------------------------------------------------- S4 - P5 via app

	def test_s4_p5_used_less_than_transferred(self):
		wo = self._make_wo()
		self._stock_recipe()
		after_stock_in = self._snapshot()
		self._transfer(wo)
		result = self._finish(wo, {"good": 95, "bahan_dipakai": {factories.RM1: 9.5}})

		self.assertEqual((result["produced"], result["status"]), (95.0, "In Process"))
		self.assertEqual(result["sisa_wip"], {factories.RM1: 0.5})
		# FINAL state: WIP keeps the 0.5 the operator did not use; Stores paid 10
		self.assertEqual(self._bin(factories.RM1, E2E_WIP), after_stock_in["wip_rm1"] + 0.5)
		self.assertEqual(self._bin(factories.RM2, E2E_WIP), after_stock_in["wip_rm2"])
		self.assertEqual(self._bin(factories.RM1, E2E_STORES), after_stock_in["stores_rm1"] - 10.0)

		# costing follows ACTUALS: 9.5x100 + 2x500 = 1950 (FG SLE valuation), GL balanced
		se_name = result["stock_entry"]
		self.assertEqual(self._fg_row(se_name), (95.0, 1950.0))
		self.assertEqual(self._fg_sle_valuation([se_name]), 1950.0)
		debit, credit = self._gl_totals(se_name)
		self.assertEqual((debit, credit), (1950.0, 1950.0))

	# ---------------------------------------------- S5 - P10 good=0 via app

	def test_s5_p10_good_zero_rejected_via_app(self):
		wo = self._wo_with_transfer()
		before = self._snapshot()
		with self.assertRaises(frappe.ValidationError) as cm:
			self._finish(wo, {"good": 0})
		message = str(cm.exception)
		self.assertIn("Hasil Baik", message)
		self.assertIn("Supervisor", message)  # directions: supervisor closes the WO instead

		# the consumption route stays DEACTIVATED: only the transfer SE exists
		purposes = frappe.get_all("Stock Entry", filters={"work_order": wo, "docstatus": 1}, pluck="purpose")
		self.assertNotIn("Material Consumption for Manufacture", purposes)
		self.assertEqual(len(purposes), 1)
		self.assertEqual(self._snapshot(), before)
		self.assertEqual(self._wo(wo).produced_qty, 0.0)

	# ------------------------------------------------------- S6 - P13 via app

	def _wo_two_operations(self, qty=100):
		suffix = random_string(5)
		operations = [
			(factories.OPERATION, factories.make_workstation(f"PDTC WS E2E {suffix} A")),
			(factories.OPERATION2, factories.make_workstation(f"PDTC WS E2E {suffix} B")),
		]
		bom = factories.make_bom_operations(operations)
		return self._make_wo_operations(bom, qty=qty)

	def _tap(self, wo, job_card, qty, is_final, user=None):
		self._as(user or self.operator1)
		return api.complete_operation(wo, job_card, qty, is_final, self._key())

	def test_s6_p13_two_operations_one_tap_then_finish(self):
		wo, jcs = self._wo_two_operations()
		self._stock_recipe()
		after_stock_in = self._snapshot()
		self._transfer(wo)

		self._tap(wo, jcs[0].name, 100, True)
		second = self._tap(wo, jcs[1].name, 100, True)
		for jc_name in (jcs[0].name, jcs[1].name):
			jc = frappe.get_doc("Job Card", jc_name)
			self.assertEqual(jc.docstatus, 1)
			self.assertEqual(round(jc.total_time_in_mins), 0)  # one tap = honest ~zero duration
		self.assertEqual(second["next_action"], "finish_production")

		result = self._finish(wo, {"good": 95, "loss_eksplisit": 5})
		self.assertEqual((result["produced"], result["loss"], result["status"]), (95.0, 5.0, "Completed"))
		self.assertFalse(result["needs_close_decision"])
		# FINAL state: operations kept 100/100, stock + costing + summary correct
		self.assertEqual(self._bin(factories.FG, E2E_FG), after_stock_in["fg"] + 95.0)
		self.assertEqual(
			flt(frappe.db.get_value("Work Order Operation", jcs[0].operation_id, "completed_qty")), 100.0
		)
		self.assertEqual(
			flt(frappe.db.get_value("Work Order Operation", jcs[1].operation_id, "completed_qty")), 100.0
		)
		self.assertEqual(self._fg_sle_valuation([result["stock_entry"]]), 2000.0)
		self.assertEqual(self._wo(wo).custom_good_qty_postpacking, 95.0)

	def test_s6_p13_final_partial_950_close(self):
		wo, jcs = self._wo_two_operations(qty=1000)
		self._stock_recipe(rm1_qty=100, rm2_qty=20)
		self._transfer(wo)

		first = self._tap(wo, jcs[0].name, 950, True)
		self._tap(wo, jcs[1].name, 950, True)
		self.assertTrue(first["needs_close_decision"])
		# the final tap never inflates completed: 950 recorded, 50 stay pending
		self.assertEqual(
			flt(frappe.db.get_value("Work Order Operation", jcs[0].operation_id, "completed_qty")), 950.0
		)
		self.assertEqual(flt(frappe.get_doc("Job Card", jcs[0].name).pending_qty), 50.0)

		result = self._finish(wo, {"good": 950, "is_final": True})
		self.assertEqual((result["produced"], result["status"]), (950.0, "In Process"))
		self.assertEqual(result["remaining_target"], 50.0)
		self.assertTrue(result["needs_close_decision"])

		closed = self._close(wo, "sisa 50 tidak jadi diproduksi")
		self.assertEqual(closed["status"], "Closed")
		wo_doc = self._wo(wo)
		self.assertEqual((wo_doc.status, wo_doc.produced_qty), ("Closed", 950.0))
		self.assertEqual(
			flt(frappe.db.get_value("Work Order Operation", jcs[0].operation_id, "completed_qty")), 950.0
		)

	# ------------------------------------------------- S7 - P8 cancel via app

	def test_s7_p8_cancel_last_step_reverses_everything(self):
		self._drain_e2e_fg_and_wip()  # leftovers would make the session consume more than 10+2
		before_transfer = self._snapshot()
		wo = self._wo_with_transfer()
		self._finish(wo, {"good": 95, "loss_eksplisit": 5})

		# expected_target comes from the DETAIL endpoint (server is the authority)
		detail = self._detail(wo)
		target = detail["cancel_next_target"]
		self.assertEqual(target["doctype"], "Stock Entry")
		self.assertEqual(detail["packing_summary"]["custom_good_qty_postpacking"], 95.0)

		result = self._cancel_last(wo, target["name"])
		self.assertEqual(result["cancelled"], target)
		self.assertEqual((result["produced"], result["loss"], result["status"]), (0.0, 0.0, "In Process"))
		# FINAL state: stock, work order and summary all reverted
		self.assertEqual(frappe.db.get_value("Stock Entry", target["name"], "docstatus"), 2)
		self.assertEqual(self._bin(factories.FG, E2E_FG), before_transfer["fg"])
		self.assertEqual(self._bin(factories.RM1, E2E_WIP), before_transfer["wip_rm1"] + 10.0)
		self.assertEqual(self._bin(factories.RM2, E2E_WIP), before_transfer["wip_rm2"] + 2.0)
		self.assertEqual(self._batch_qty(factories.BATCH_RM1, E2E_WIP), before_transfer["wip_brm1"] + 10.0)
		self.assertEqual(self._wo(wo).custom_good_qty_postpacking, 0.0)
		detail = self._detail(wo)
		self.assertEqual(detail["packing_summary"]["custom_good_qty_postpacking"], 0.0)
		materials = {m["item_code"]: m["sisa_wip"] for m in detail["materials"]}
		self.assertEqual(materials, {factories.RM1: 10.0, factories.RM2: 2.0})

	def test_s7_p8_fg_used_blocks_cancel(self):
		self._drain_e2e_fg_and_wip()  # net FG batches must be THIS session's only
		wo = self._wo_with_transfer()
		se_m = self._finish(wo, {"good": 95, "loss_eksplisit": 5})["stock_entry"]
		fg_batch = self._fg_batch_of(se_m)

		# FG consumed by an external (Desk) transaction - P8-4
		self._as("Administrator")
		issue = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Issue",
				"purpose": "Material Issue",
				"company": factories.COMPANY,
				"items": [
					{
						"item_code": factories.FG,
						"s_warehouse": E2E_FG,
						"qty": 95,
						"use_serial_batch_fields": 1,
						"batch_no": fg_batch,
					}
				],
			}
		)
		issue.insert()
		issue.submit()

		with self.assertRaises(frappe.ValidationError) as cm:
			self._cancel_last(wo, se_m)
		self.assertIn("terpakai", str(cm.exception))
		# nothing cancelled
		self.assertEqual(frappe.db.get_value("Stock Entry", se_m, "docstatus"), 1)
		self.assertEqual(self._wo(wo).produced_qty, 95.0)

	def test_s7_p8_cancel_production_atomic(self):
		self._drain_e2e_fg_and_wip()  # exact 10+2 consumption -> exact full reversal
		before_transfer = self._snapshot()
		wo = self._wo_with_transfer()
		self._finish(wo, {"good": 95, "loss_eksplisit": 5})

		fingerprint = self._detail(wo, user=self.supervisor)["cancel_fingerprint"]
		self._as(self.supervisor)
		result = api.cancel_production(wo, fingerprint, self._key())

		self.assertEqual(result["status"], "Cancelled")
		self.assertEqual(frappe.db.get_value("Work Order", wo, "docstatus"), 2)
		cancelled = {(c["doctype"], c["name"]) for c in result["cancelled"]}
		self.assertEqual(
			sum(1 for doctype, _name in cancelled if doctype == "Stock Entry"), 2
		)  # transfer + manufacture
		# FINAL state: fully reversed production (the picked 10+2 come back to
		# Stores with the transfer cancel; the recipe receipts stay)
		self.assertEqual(self._bin(factories.FG, E2E_FG), before_transfer["fg"])
		self.assertEqual(self._bin(factories.RM1, E2E_WIP), before_transfer["wip_rm1"])
		self.assertEqual(self._bin(factories.RM2, E2E_WIP), before_transfer["wip_rm2"])
		self.assertEqual(self._bin(factories.RM1, E2E_STORES), before_transfer["stores_rm1"] + 10.0)
		self.assertEqual(self._bin(factories.RM2, E2E_STORES), before_transfer["stores_rm2"] + 2.0)
		self.assertEqual(self._wo(wo).custom_good_qty_postpacking, 0.0)

	# ------------------------------------------------- S9 - T5.2b idempotency

	def test_s9_t52b_retry_idempotent_via_app(self):
		wo = self._wo_with_transfer()
		self._as(self.operator1)
		key = self._key()
		first = api.finish_production(wo, {"good": 40}, key)
		replay = api.finish_production(wo, {"good": 40}, key)

		self.assertTrue(replay["duplicate"])
		self.assertEqual(replay["stock_entry"], first["stock_entry"])
		# effect exactly once
		self.assertEqual(len(self._manufacture_ses(wo)), 1)
		self.assertEqual(self._wo(wo).produced_qty, 40.0)

		# same key, DIFFERENT payload -> hard rejection, state untouched
		with self.assertRaises(frappe.ValidationError) as cm:
			api.finish_production(wo, {"good": 50}, key)
		self.assertIn("aksi/payload berbeda", str(cm.exception))
		self.assertEqual(len(self._manufacture_ses(wo)), 1)
		self.assertEqual(self._wo(wo).produced_qty, 40.0)

	# --------------------------------------------------- S10 - T5.2c Desk SE

	def test_s10_t52c_desk_manufacture_stays_consistent(self):
		wo = self._wo_with_transfer()
		before_transfer = self._snapshot()

		self._as("Administrator")
		se = factories.se_manufacture(wo, good=60, materials={factories.RM1: 6, factories.RM2: 1.2})
		detail = self._detail(wo)
		entry = next(e for e in detail["stock_entries"] if e["name"] == se.name)
		# no custom_p_good_qty on a Desk entry: Float reads back 0 (the summary
		# deliberately cannot tell "app entry with good 0" from "Desk entry")
		self.assertEqual(flt(entry["good"]), 0.0)
		self.assertEqual(entry["fg_completed_qty"], 60.0)  # core-derived coverage
		self.assertEqual(entry["petugas_packing"], "Administrator")
		# summary + work order consistent, good derived from the FG rows
		self.assertEqual(detail["packing_summary"]["custom_good_qty_postpacking"], 60.0)
		self.assertEqual(self._wo(wo).produced_qty, 60.0)
		self.assertEqual(self._bin(factories.FG, E2E_FG), before_transfer["fg"] + 60.0)

		# Desk-cancel -> the hook re-syncs the summary and the WO
		self._as("Administrator")
		se.cancel()
		detail = self._detail(wo)
		self.assertEqual(detail["packing_summary"]["custom_good_qty_postpacking"], 0.0)
		self.assertEqual(self._wo(wo).produced_qty, 0.0)
		self.assertEqual(self._bin(factories.FG, E2E_FG), before_transfer["fg"])
		# the Desk-cancel restores the Desk session's 6 RM1 (WIP back to its
		# post-transfer level)
		self.assertEqual(self._bin(factories.RM1, E2E_WIP), before_transfer["wip_rm1"])

	# -------------------------------------------- S11 - T5.2d Stopped/Reserved

	def test_s11_t52d_stopped_and_reserved_blocked(self):
		# Stopped: mutations refused with the Indonesian status message
		wo = self._wo_with_transfer()
		frappe.get_doc("Work Order", wo).update_status("Stopped")
		with self.assertRaises(frappe.ValidationError) as cm:
			self._transfer(wo, {factories.RM1: 1})
		self.assertIn("dalam status Stopped", str(cm.exception))
		with self.assertRaises(frappe.ValidationError) as cm:
			self._finish(wo, {"good": 10})
		self.assertIn("dalam status Stopped", str(cm.exception))
		self.assertEqual(self._wo(wo).produced_qty, 0.0)

		# Reserved: config reason listed on the detail AND enforced on mutations
		self._as("Administrator")
		wo_r = self._make_wo()
		frappe.db.set_value("Work Order", wo_r, "reserve_stock", 1)
		detail = self._detail(wo_r)
		self.assertTrue(any("reservasi" in r for r in detail["blocked_reasons"]))
		with self.assertRaises(frappe.ValidationError) as cm:
			self._transfer(wo_r)
		self.assertIn("reservasi", str(cm.exception))
		with self.assertRaises(frappe.ValidationError) as cm:
			self._finish(wo_r, {"good": 10})
		self.assertIn("reservasi", str(cm.exception))

	# -------------------------------------------------- S12 - STATE_CHANGED

	def test_s12_state_changed_stale_expected_target(self):
		wo = self._wo_with_transfer()
		se_m = self._finish(wo, {"good": 40})["stock_entry"]

		self._as(self.supervisor)
		with self.assertRaises(StateChangedError) as cm:
			api.cancel_last_step(wo, "MAT-STE-E2E-STALE", self._key())
		self.assertEqual(cm.exception.code, "STATE_CHANGED")
		self.assertIn("berubah", str(cm.exception))
		# nothing was cancelled
		self.assertEqual(frappe.db.get_value("Stock Entry", se_m, "docstatus"), 1)
		self.assertEqual(self._wo(wo).produced_qty, 40.0)


class TestE2EConcurrency(E2EFixture):
	"""S8 - T5.2a: two operators finishing the SAME work order in true parallel.

	Approach (documented per the brief): TWO REAL PARALLEL SESSIONS, not a
	sequential simulation. Each racer runs in its OWN thread with a fresh frappe
	site context (frappe.init + frappe.connect = own DB connection +
	transaction) and COMMITS its own outcome; a threading.Barrier releases both
	at the same instant. Serialization is exactly the production mechanism -
	the app's `SELECT ... FOR UPDATE` on the Work Order row (spec 10.1): the
	loser blocks inside lock_work_order until the winner commits, then re-reads
	the Work Order AFTER the lock and is gated by the NEEDS_ALLOWANCE pre-check
	(its good 60 no longer fits the remaining 40). Committed visibility is what
	makes the race real, so THIS test commits its setup and outcome and reverses
	everything INLINE (the request's own rollback replica) - verified against
	the baseline snapshot so leaked committed stock can never linger silently.
	"""

	def _racer(self, barrier, results, label, site, sites_path, wo, user, packing, key):
		"""One operator session: full site context, finish, own commit."""

		def run():
			frappe.init(site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user(user)
				barrier.wait(timeout=60)
				result = api.finish_production(wo, packing, key)
				frappe.db.commit()
				results[label] = {"ok": True, "result": result}
			except Exception as e:  # replicate the request wrapper's rollback
				frappe.db.rollback()
				results[label] = {"ok": False, "error": e, "code": getattr(e, "code", None)}
			finally:
				frappe.destroy()

		thread = threading.Thread(target=run, name=label, daemon=True)
		thread.start()
		return thread

	def _revert_committed(self, wo, receipts, keys, baseline):
		"""Cancel + delete every committed document of the race, then PROVE the
		E2E warehouses are back to baseline (leaks here poisoned other suites)."""
		frappe.set_user("Administrator")
		# fixed cancel order (12): Manufacture/Consumption first, then Transfer
		ses = frappe.get_all("Stock Entry", filters={"work_order": wo, "docstatus": 1}, pluck="name")
		ses.sort(
			key=lambda n: (
				0 if "Manufacture" in (frappe.db.get_value("Stock Entry", n, "purpose") or "") else 1
			)
		)
		for se_name in ses + receipts:
			se = frappe.get_doc("Stock Entry", se_name)
			if se.docstatus == 1:
				se.flags.ignore_permissions = True
				se.cancel()
		wo_doc = frappe.get_doc("Work Order", wo)
		if wo_doc.docstatus == 1:
			wo_doc.flags.ignore_permissions = True
			wo_doc.cancel()
		fg_batches = frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": ("in", ses + receipts), "item_code": factories.FG},
			pluck="batch_no",
		)
		for se_name in ses + receipts:
			frappe.delete_doc("Stock Entry", se_name, ignore_permissions=True, force=True)
		frappe.delete_doc("Work Order", wo, ignore_permissions=True, force=True)
		for key in keys:
			if frappe.db.exists("Production Request Log", key):
				frappe.delete_doc("Production Request Log", key, ignore_permissions=True, force=True)
		for batch_no in fg_batches:  # the app-created empty FG session batch
			if batch_no and frappe.db.exists("Batch", batch_no):
				frappe.delete_doc("Batch", batch_no, ignore_permissions=True, force=True)
		frappe.db.commit()
		self.assertEqual(self._snapshot(), baseline, "committed race data was not fully reverted")

	def test_s8_t52a_two_parallel_finishes_serialize(self):
		baseline = self._snapshot()
		wo = self._make_wo()
		receipt_rm1 = factories.stock_in(factories.RM1, E2E_STORES, 10, 100, batch_no=factories.BATCH_RM1)
		receipt_rm2 = factories.stock_in(factories.RM2, E2E_STORES, 2, 500)
		receipts = [receipt_rm1.name, receipt_rm2.name]
		self._transfer(wo)
		after_transfer = self._snapshot()
		frappe.db.commit()  # the racers need committed visibility of the setup

		site = frappe.local.site
		sites_path = getattr(frappe.local, "sites_path", None) or os.path.join(os.getcwd(), "sites")
		barrier = threading.Barrier(2)
		results = {}
		key_a, key_b = self._key(), self._key()
		try:
			thread_a = self._racer(
				barrier, results, "A", site, sites_path, wo, self.operator1, {"good": 60}, key_a
			)
			thread_b = self._racer(
				barrier, results, "B", site, sites_path, wo, self.operator2, {"good": 60}, key_b
			)
			thread_a.join(timeout=120)
			thread_b.join(timeout=120)

			# no crashes, no 500s: exactly one full success, one clean gate
			self.assertEqual(sorted(results), ["A", "B"])
			winners = [label for label, r in results.items() if r["ok"]]
			self.assertEqual(len(winners), 1, f"expected exactly one winner, got {results}")
			loser = results["B" if winners == ["A"] else "A"]
			self.assertFalse(loser["ok"])
			self.assertEqual(loser["code"], "NEEDS_ALLOWANCE", f"loser was not gated cleanly: {loser}")

			# FINAL state: one production, numbers == the ONE valid input
			manufacture_ses = self._manufacture_ses(wo)
			self.assertEqual(len(manufacture_ses), 1)
			self.assertEqual(manufacture_ses[0], results[winners[0]]["result"]["stock_entry"])
			self.assertEqual(self._wo(wo).produced_qty, 60.0)
			self.assertEqual(self._wo(wo).custom_good_qty_postpacking, 60.0)
			self.assertEqual(self._bin(factories.FG, E2E_FG), after_transfer["fg"] + 60.0)
			# WIP fully consumed by the winner (default session = full remaining)
			self.assertEqual(self._bin(factories.RM1, E2E_WIP), after_transfer["wip_rm1"] - 10.0)
			self.assertEqual(self._bin(factories.RM2, E2E_WIP), after_transfer["wip_rm2"] - 2.0)
			fg_batch = self._fg_batch_of(manufacture_ses[0])
			self.assertEqual(self._batch_qty(fg_batch, E2E_FG), 60.0)
		finally:
			self._revert_committed(wo, receipts, [key_a, key_b], baseline)

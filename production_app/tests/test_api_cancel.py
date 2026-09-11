"""Tests for api.cancel_last_step + api.cancel_production (spec 7.7/12).

Contract proven per test:
- full reversal (P8-1 numbers): transfer + finish(95/5) -> cancel the
  Manufacture SE -> FG gone (Bin -95, session batch 0), WIP back +10/+2 (RM1
  batch back), produced 0, status In Process, WO packing summary back to 0
  via the Stock Entry hook (8.1); cancel the Transfer SE -> Stores restored,
  WO "Not Started"; cancel_production -> WO Cancelled WITHOUT any Work Order
  cancel permission on the roles (11.3, doc-instance authorized_ignore);
- Serial and Batch Bundle cancel path (Task 15 residual): the fixtures grant
  the Supervisor (only) "cancel" on Serial and Batch Bundle; the submitted
  bundles are cancelled (docstatus 2) with the SE;
- expected_target mismatch (SE-A confirmed, SE-B created after): STATE_CHANGED,
  nothing cancelled, SE-B intact; the corrected expectation then cancels SE-B
  (newest by posting_datetime), never SE-A;
- wrong order rejected: core refuses the Transfer-SE cancel while the
  Manufacture SE is active (P8-2, batch-level negative stock) and the app maps
  it to the Indonesian message; nothing changed; the same mapping is proven
  through the FULL endpoint when an external WIP drain is invisible to the
  WO-scoped pre-check (Task 16 wiring);
- Stopped WO: refused on BOTH cancel endpoints with the Indonesian message
  before any target resolution (Task 16);
- FG consumed by another transaction -> blocked with the "terpakai" reason;
- Desk return SE (is_return) detected -> blocked with the Desk reason;
- cancel_production fingerprint mismatch -> STATE_CHANGED, nothing cancelled;
- happy path atomically cancels SEs + the submitted Job Card (operation
  completion reversed) and leaves the DRAFT follow-up Job Card; the WO ends
  "Cancelled";
- WIP shortfall from an external Material Issue -> the pre-check blocks with
  the item breakdown and the request rolls back totally (10.3);
- operator denied; replay returns the stored result without a second cancel.

Concurrency note: IntegrationTestCase keeps ONE transaction per class (rolled
back at class end), so warehouse-level numbers are asserted as DELTAS around
each action; throws are wrapped in a SAVEPOINT = the request boundary whose
rollback is what production gets from frappe's request wrapper (10.3).
"""

import frappe
from erpnext.stock.doctype.batch.batch import get_batch_qty
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from production_app import api, cancel
from production_app.exceptions import StateChangedError
from production_app.tests import factories
from production_app.tests.test_api_operation import OperationFixture

OPERATOR = "pdtc.cancel.operator@example.com"
SUPERVISOR = "pdtc.cancel.supervisor@example.com"


class TestCancelApi(OperationFixture):
	"""Reuses the WO-with-operations helpers and the ledger-key cleanup
	contract; its own users so runs stay independent."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls.supervisor = factories.make_user(SUPERVISOR, roles=["Production Supervisor"])
		frappe.db.commit()

	# ---------------------------------------------------------------- helpers

	def _bin(self, item, warehouse):
		return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))

	def _batch_qty(self, batch_no, warehouse):
		return flt(get_batch_qty(batch_no, warehouse) or 0)

	def _snapshot(self):
		"""Warehouse-level quantities of the shared PDTC warehouses - tests
		assert DELTAS of these around each action (class-shared transaction)."""
		return {
			"fg_bin": self._bin(factories.FG, factories.FG_WH),
			"stores_rm1": self._bin(factories.RM1, factories.STORES),
			"stores_rm2": self._bin(factories.RM2, factories.STORES),
			"wip_rm1": self._bin(factories.RM1, factories.WIP),
			"wip_rm2": self._bin(factories.RM2, factories.WIP),
			"wip_brm1": self._batch_qty(factories.BATCH_RM1, factories.WIP),
		}

	def _se_batch(self, se_name, item_code):
		return frappe.db.get_value(
			"Stock Entry Detail", {"parent": se_name, "item_code": item_code}, "batch_no"
		)

	def _wo_with_transfer(self):
		"""WO 100 (BOM 10 + 2), recipe stocked in Stores, materials transferred
		via the app; returns (wo_name, transfer_se_name)."""
		wo = factories.make_wo()
		factories.stock_in(factories.RM1, factories.STORES, 10, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 2, 500)
		frappe.set_user(self.operator)
		se_t = api.transfer_material(wo, None, self._key())["stock_entry"]
		return wo, se_t

	def _finish(self, wo, packing):
		frappe.set_user(self.operator)
		return api.finish_production(wo, packing, self._key())

	def _cancel_last(self, wo, expected, user=None):
		frappe.set_user(user or self.supervisor)
		return api.cancel_last_step(wo, expected, self._key())

	def _cancel_production(self, wo, fingerprint=None, user=None):
		frappe.set_user(user or self.supervisor)
		return api.cancel_production(wo, fingerprint or cancel.production_fingerprint(wo), self._key())

	def _issue_out(self, item, warehouse, qty, batch_no=None, work_order=None):
		"""Desk Material Issue out of a warehouse (the external transaction the
		pre-checks must notice); `work_order` links it to the WO so the WO-scoped
		WIP net sees it."""
		frappe.set_user("Administrator")
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Issue",
				"purpose": "Material Issue",
				"company": factories.COMPANY,
				"work_order": work_order,
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
		return se

	# ---------------------------------------------------------- full reversal

	def test_full_reversal_p8_numbers_with_packing_summary_decrease(self):
		wo, se_t = self._wo_with_transfer()
		result = self._finish(wo, {"good": 95, "loss_eksplisit": 5})
		se_m = result["stock_entry"]
		fg_batch = self._se_batch(se_m, factories.FG)
		self.assertTrue(fg_batch)

		# SABB cancel path (Task 15 residual): fixture grants the Supervisor
		# (only) cancel on Serial and Batch Bundle; the SE carries bundles.
		self.assertTrue(frappe.has_permission("Serial and Batch Bundle", "cancel", user=self.supervisor))
		self.assertFalse(frappe.has_permission("Serial and Batch Bundle", "cancel", user=self.operator))
		bundles = frappe.get_all(
			"Serial and Batch Bundle",
			filters={"voucher_type": "Stock Entry", "voucher_no": se_m, "docstatus": 1},
			pluck="name",
		)
		self.assertTrue(bundles)
		# premise: the roles hold NO Work Order cancel permission (11.3)
		self.assertFalse(frappe.has_permission("Work Order", "cancel", user=self.supervisor))

		# pre-state (P8-1 setup): the session's FG batch holds 95, WIP emptied
		self.assertEqual(self._batch_qty(fg_batch, factories.FG_WH), 95.0)
		self.assertEqual(flt(frappe.db.get_value("Work Order", wo, "custom_good_qty_postpacking")), 95.0)
		before = self._snapshot()

		res1 = self._cancel_last(wo, se_m)
		self.assertEqual(res1["cancelled"], {"doctype": "Stock Entry", "name": se_m})
		self.assertEqual(
			(res1["produced"], res1["loss"], res1["belum_diproduksi"], res1["status"]),
			(0.0, 0.0, 100.0, "In Process"),
		)
		# stock reversed (P8-1): FG -95, materials back in WIP, RM1 batch back
		self.assertEqual(self._bin(factories.FG, factories.FG_WH), before["fg_bin"] - 95.0)
		self.assertEqual(self._batch_qty(fg_batch, factories.FG_WH), 0.0)
		self.assertEqual(self._bin(factories.RM1, factories.WIP), before["wip_rm1"] + 10.0)
		self.assertEqual(self._bin(factories.RM2, factories.WIP), before["wip_rm2"] + 2.0)
		self.assertEqual(self._batch_qty(factories.BATCH_RM1, factories.WIP), before["wip_brm1"] + 10.0)
		# the Stock Entry hook re-synced the packing summary DOWN (8.1)
		self.assertEqual(flt(frappe.db.get_value("Work Order", wo, "custom_good_qty_postpacking")), 0.0)
		# the submitted bundles went with the SE
		self.assertEqual(
			frappe.get_all(
				"Serial and Batch Bundle", filters={"name": ("in", bundles), "docstatus": 1}, pluck="name"
			),
			[],
		)

		before_t_cancel = self._snapshot()
		res2 = self._cancel_last(wo, se_t)
		self.assertEqual(res2["cancelled"], {"doctype": "Stock Entry", "name": se_t})
		self.assertEqual(res2["status"], "Not Started")
		self.assertEqual(self._bin(factories.RM1, factories.STORES), before_t_cancel["stores_rm1"] + 10.0)
		self.assertEqual(self._bin(factories.RM2, factories.STORES), before_t_cancel["stores_rm2"] + 2.0)
		self.assertEqual(self._bin(factories.RM1, factories.WIP), before_t_cancel["wip_rm1"] - 10.0)
		self.assertEqual(
			flt(frappe.db.get_value("Work Order", wo, "material_transferred_for_manufacturing")), 0.0
		)

		# WO cancel via cancel_production - without WO cancel permission
		res3 = self._cancel_production(wo)
		self.assertEqual(res3["status"], "Cancelled")
		self.assertEqual(frappe.db.get_value("Work Order", wo, "docstatus"), 2)

	def test_se_b_cancelled_not_stale_se_a_on_mismatch(self):
		wo, _se_t = self._wo_with_transfer()
		# two sessions SPLIT the WIP (default session = full remaining, so an
		# explicit split is what leaves material for the second session)
		se_a = self._finish(wo, {"good": 40, "bahan_dipakai": {factories.RM1: 4, factories.RM2: 0.8}})[
			"stock_entry"
		]
		se_b = self._finish(wo, {"good": 60, "bahan_dipakai": {factories.RM1: 6, factories.RM2: 1.2}})[
			"stock_entry"
		]

		with self.assertRaises(StateChangedError) as cm:
			self._cancel_last(wo, se_a)  # UI confirmed SE-A, world moved on
		self.assertEqual(cm.exception.code, "STATE_CHANGED")
		# nothing cancelled - SE-B (the replacement) stays intact
		self.assertEqual(frappe.db.get_value("Stock Entry", se_a, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", se_b, "docstatus"), 1)

		# the corrected expectation cancels the NEWEST session (SE-B)
		res = self._cancel_last(wo, se_b)
		self.assertEqual(res["cancelled"]["name"], se_b)
		self.assertEqual(frappe.db.get_value("Stock Entry", se_a, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", se_b, "docstatus"), 2)

	# ------------------------------------------------------------ wrong order

	def _drain_wip(self):
		"""Empty the SHARED WIP warehouse of RM1/RM2 leftovers so a test's
		stock math is deterministic (class-shared transaction)."""
		frappe.set_user("Administrator")
		for item, batched in ((factories.RM1, True), (factories.RM2, False)):
			batches = get_batch_qty(item_code=item, warehouse=factories.WIP) or [] if batched else [None]
			for batch in batches:
				left = flt((batch.qty if batch else self._bin(item, factories.WIP)) or 0, 3)
				if left > 0:
					self._issue_out(item, factories.WIP, left, batch_no=(batch.batch_no if batch else None))

	def test_wrong_order_rejected_and_mapped_to_indonesian(self):
		self._drain_wip()  # leftovers would make the wrong-order cancel legal
		wo, se_t = self._wo_with_transfer()
		frappe.set_user("Administrator")
		factories.se_manufacture(wo, 95)  # consumes 9.5 of the WIP RM1 (P8-2 setup)
		se_m = frappe.get_all(
			"Stock Entry", filters={"work_order": wo, "purpose": "Manufacture", "docstatus": 1}, pluck="name"
		)[0]
		before = self._snapshot()

		# direct transfer cancel (order violation): core keeps the final say.
		# Savepoint = request boundary: core may have written partial reversals
		# before throwing - undone exactly like the request rollback would.
		frappe.db.savepoint("pdtc_wrong_order")
		frappe.set_user(self.supervisor)
		with self.assertRaises(frappe.ValidationError) as cm:
			cancel.cancel_doc(frappe.get_doc("Stock Entry", se_t))
		frappe.db.rollback(save_point="pdtc_wrong_order")
		# the endpoint mapping turns the core wording into the Indonesian message
		with self.assertRaises(frappe.ValidationError) as mapped:
			cancel.map_cancel_error(cm.exception)
		self.assertIn("Urutan pembatalan salah", str(mapped.exception))

		# nothing changed
		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", se_m, "docstatus"), 1)
		self.assertEqual(self._snapshot(), before)

	def test_wrong_order_mapped_through_full_endpoint(self):
		"""Task 16 wiring: the ENDPOINT's try/except -> map_cancel_error path
		(the earlier test covers only the helper). The WIP batch was issued out
		by an external Material Issue - its work_order link is stripped by core,
		so the WO-scoped WIP-net pre-check still passes and CORE rejects the
		cancel (negative batch stock); the endpoint surfaces it as the mapped
		Indonesian message and nothing changes."""
		self._drain_wip()  # leftovers would keep the batch reversal legal
		wo, se_t = self._wo_with_transfer()
		self._issue_out(factories.RM1, factories.WIP, 10, batch_no=factories.BATCH_RM1)
		before = self._snapshot()

		# savepoint = request boundary: partial reversals before the throw are
		# undone exactly like the frappe request rollback would (10.3)
		frappe.db.savepoint("pdtc_endpoint_wrong_order")
		with self.assertRaises(frappe.ValidationError) as cm:
			self._cancel_last(wo, se_t)
		frappe.db.rollback(save_point="pdtc_endpoint_wrong_order")

		self.assertIn("Urutan pembatalan salah", str(cm.exception))
		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 1)
		self.assertEqual(self._snapshot(), before)

	def _transfer_out_of_wip(self, wo, item, qty, batch_no=None):
		"""Desk Material Transfer WIP -> Stores linked to the WO. Plain
		"Material Transfer" is the one purpose core does NOT strip the
		work_order link from (stock_entry.validate_work_order:1022-1028), so
		the WO-scoped WIP net (and thus the pre-check) sees the drain."""
		frappe.set_user("Administrator")
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer",
				"purpose": "Material Transfer",
				"company": factories.COMPANY,
				"work_order": wo,
				"items": [
					{
						"item_code": item,
						"s_warehouse": factories.WIP,
						"t_warehouse": factories.STORES,
						"qty": qty,
						"use_serial_batch_fields": 1 if batch_no else 0,
						"batch_no": batch_no,
					}
				],
			}
		)
		se.insert()
		se.submit()
		return se

	def test_cancel_production_blocked_on_wip_shortfall_and_rolls_back(self):
		wo, se_t = self._wo_with_transfer()
		self._transfer_out_of_wip(wo, factories.RM1, 8, batch_no=factories.BATCH_RM1)
		fingerprint = cancel.production_fingerprint(wo)
		before = self._snapshot()

		# savepoint = the request boundary: what the endpoint's exception rolls
		# back in production (10.3) is undone here the same way
		frappe.db.savepoint("pdtc_cancel_atomic")
		frappe.set_user(self.supervisor)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.cancel_production(wo, fingerprint, self._key())
		frappe.db.rollback(save_point="pdtc_cancel_atomic")

		message = str(cm.exception)
		self.assertIn("stok WIP negatif", message)
		self.assertIn(factories.RM1, message)
		self.assertIn("8", message)
		# atomic: nothing was cancelled and the ledger row is gone
		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Work Order", wo, "docstatus"), 1)
		self.assertEqual(self._snapshot(), before)
		self.assertFalse(
			frappe.db.get_value("Production Request Log", {"work_order": wo, "action": "cancel_production"})
		)

	# ------------------------------------------------------------- pre-checks

	def test_stopped_wo_blocked_in_indonesian_on_both_cancel_endpoints(self):
		"""Task 16 pre-check: a Stopped WO is refused BEFORE any target is
		resolved, in Indonesian (core's own rejection only fires at the first
		SE cancel, in English); nothing is cancelled on either endpoint."""
		wo, se_t = self._wo_with_transfer()
		frappe.db.set_value("Work Order", wo, "status", "Stopped")
		frappe.set_user(self.supervisor)

		with self.assertRaises(frappe.ValidationError) as cm:
			self._cancel_last(wo, se_t)
		self.assertIn("Work Order dihentikan", str(cm.exception))
		with self.assertRaises(frappe.ValidationError) as cm2:
			self._cancel_production(wo)
		self.assertIn("Work Order dihentikan", str(cm2.exception))

		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Work Order", wo, "docstatus"), 1)

	def test_fg_consumed_by_other_transaction_blocks(self):
		wo, _se_t = self._wo_with_transfer()
		se_m = self._finish(wo, {"good": 95, "loss_eksplisit": 5})["stock_entry"]
		fg_batch = self._se_batch(se_m, factories.FG)
		self._issue_out(factories.FG, factories.FG_WH, 95, batch_no=fg_batch)  # P8-4

		with self.assertRaises(frappe.ValidationError) as cm:
			self._cancel_last(wo, se_m)
		self.assertIn("terpakai", str(cm.exception))
		self.assertEqual(frappe.db.get_value("Stock Entry", se_m, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Work Order", wo, "produced_qty"), 95)

	def test_desk_return_se_detected_and_blocks(self):
		wo, se_t = self._wo_with_transfer()
		ret = "PDTC-RET-" + frappe.generate_hash(8)
		# minimal db-level return row: the pre-check is detection-only (brief)
		frappe.db.sql(
			"""insert into `tabStock Entry`
				(name, docstatus, purpose, stock_entry_type, is_return, work_order, company,
				 owner, modified_by, creation, modified)
				values (%s, 1, 'Material Transfer for Manufacture', 'Material Transfer for Manufacture',
				 1, %s, %s, 'Administrator', 'Administrator', now(), now())""",
			(ret, wo, factories.COMPANY),
		)

		with self.assertRaises(frappe.ValidationError) as cm:
			self._cancel_last(wo, se_t)
		message = str(cm.exception)
		self.assertIn("pengembalian", message)
		self.assertIn("Desk", message)
		self.assertIn(ret, message)
		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 1)

	# ------------------------------------------------------ cancel_production

	def test_cancel_production_fingerprint_mismatch_changes_nothing(self):
		wo, se_t = self._wo_with_transfer()
		stale = cancel.production_fingerprint(wo)
		self._finish(wo, {"good": 40})  # the member set changes afterwards

		frappe.set_user(self.supervisor)
		with self.assertRaises(StateChangedError) as cm:
			api.cancel_production(wo, stale, self._key())
		self.assertEqual(cm.exception.code, "STATE_CHANGED")
		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Work Order", wo, "docstatus"), 1)

	def test_cancel_production_atomic_with_submitted_jc_and_draft_left(self):
		wo, jcs = self._wo()
		factories.stock_in(factories.RM1, factories.STORES, 10, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 2, 500)
		frappe.set_user(self.operator)
		se_t = api.transfer_material(wo, None, self._key())["stock_entry"]
		self._complete(wo, jcs[0].name, 60, False)  # card submitted, follow-up draft
		follow_up = frappe.get_all("Job Card", filters={"work_order": wo, "docstatus": 0}, pluck="name")
		self.assertEqual(len(follow_up), 1)
		before = self._snapshot()

		res = self._cancel_production(wo)
		cancelled = {(c["doctype"], c["name"]) for c in res["cancelled"]}
		self.assertIn(("Stock Entry", se_t), cancelled)
		self.assertIn(("Job Card", jcs[0].name), cancelled)
		self.assertEqual(res["status"], "Cancelled")
		self.assertEqual(frappe.db.get_value("Work Order", wo, "docstatus"), 2)
		# the submitted card is cancelled, its operation reversed, the DRAFT
		# follow-up card is left alone (12)
		self.assertEqual(frappe.db.get_value("Job Card", jcs[0].name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Job Card", follow_up[0], "docstatus"), 0)
		self.assertEqual(
			flt(frappe.db.get_value("Work Order Operation", jcs[0].operation_id, "completed_qty")), 0.0
		)
		# stores restored
		self.assertEqual(self._bin(factories.RM1, factories.STORES), before["stores_rm1"] + 10.0)
		self.assertEqual(self._bin(factories.RM2, factories.STORES), before["stores_rm2"] + 2.0)

	# ---------------------------------------------------- access + idempotency

	def test_operator_denied(self):
		wo, se_t = self._wo_with_transfer()
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.PermissionError) as cm:
			api.cancel_last_step(wo, se_t, self._key())
		self.assertIn("tidak memiliki hak", str(cm.exception))
		with self.assertRaises(frappe.PermissionError):
			self._cancel_production(wo, user=self.operator)
		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 1)

	def test_replay_returns_duplicate_without_second_cancel(self):
		wo, se_t = self._wo_with_transfer()
		frappe.set_user(self.supervisor)
		key = self._key()
		first = api.cancel_last_step(wo, se_t, key)
		replay = api.cancel_last_step(wo, se_t, key)

		self.assertTrue(replay["duplicate"])
		self.assertEqual(replay["cancelled"], first["cancelled"])
		self.assertEqual(frappe.db.get_value("Stock Entry", se_t, "docstatus"), 2)
		# a fresh request afterwards finds nothing cancelable -> STATE_CHANGED
		with self.assertRaises(StateChangedError):
			api.cancel_last_step(wo, se_t, self._key())

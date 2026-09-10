"""Tests for the read endpoints api.get_open_work_orders (7.1) and
api.get_work_order_detail (7.2).

Contract proven per test:
- list: role gate, access-scoped rows, open statuses only (Completed never
  listed, Stopped is), operator payload vocabulary (belum_diproduksi), step
  badges per spec 5, search over name/item/item_name, per-WO blocked_reasons;
- detail: the full two-session fixture - dipakai vs transferred net per
  material, indicative source stock with an expired batch flagged and excluded
  from tersedia, operations with open job card / perlu_kartu_tambahan,
  stock_entries with custom_p_* details, packing_summary equal to the shared
  compute_summary aggregation, next_action in every state, blocked_reasons.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from production_app import api, wo_summary
from production_app.tests import factories

OPERATOR = "pdtc.read.operator@example.com"
NOBODY = "pdtc.read.nobody@example.com"


def _progressed_wo(qty=100):
	"""WO with stock, a full transfer and TWO packing sessions (spec 3.3
	partial scenario): produced 60 + 30, consumed RM1 25 / RM2 5."""
	wo = factories.make_wo(qty=qty)
	factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
	factories.stock_in(factories.RM2, factories.STORES, 100, 500)
	factories.se_transfer(wo, materials={factories.RM1: 100, factories.RM2: 100})
	factories.se_manufacture(
		wo,
		good=60,
		materials={factories.RM1: 10, factories.RM2: 2},
		packing={
			"custom_p_good_qty": 60,
			"custom_p_reject_qty": 2,
			"custom_p_trial_qty": 1,
			"custom_p_good_qty_pre": 65,
		},
	)
	factories.se_manufacture(
		wo,
		good=30,
		materials={factories.RM1: 15, factories.RM2: 3},
		packing={
			"custom_p_good_qty": 30,
			"custom_p_sisa_qty": 4,
			"custom_p_petugas_packing": OPERATOR,
		},
	)
	return wo


def _insert_open_job_card(wo, operation, operation_id):
	"""Minimal OPEN Job Card row for read assertions (raw insert, mirroring
	factories.add_wo_operation: the submitted WO is not re-validated)."""
	name = f"PDTC-JC-{frappe.utils.random_string(8)}"
	frappe.db.sql(
		"""insert into `tabJob Card`
            (name, work_order, operation, operation_id, for_quantity, stock_uom, status, docstatus,
             total_completed_qty, process_loss_qty, total_time_in_mins,
             owner, modified_by, creation, modified)
            values (%s, %s, %s, %s, 100, 'Nos', 'Open', 0, 0, 0, 0,
             'Administrator', 'Administrator', now(), now())""",
		(name, wo, operation, operation_id),
	)
	return name


class TestGetOpenWorkOrders(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls.nobody = factories.make_user(NOBODY)
		cls.wo = factories.make_wo()
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _rows(self, search=None):
		return {w["name"]: w for w in api.get_open_work_orders(search=search)["work_orders"]}

	# ---------------------------------------------------------------- access

	def test_requires_operator_role(self):
		frappe.set_user(self.nobody)
		with self.assertRaises(frappe.PermissionError):
			api.get_open_work_orders()

	# --------------------------------------------------------------- payload

	def test_fresh_wo_payload_and_badge(self):
		frappe.set_user(self.operator)
		row = self._rows()[self.wo]
		self.assertEqual(row["item"], factories.FG)
		self.assertEqual((row["qty"], row["produced"], row["belum_diproduksi"]), (100, 0, 100))
		self.assertEqual(row["status"], "Not Started")
		self.assertEqual(
			(row["badge"], row["has_operations"], row["skip_transfer"]), ("Menunggu Bahan", False, 0)
		)
		self.assertEqual(row["blocked_reasons"], [])

	def test_completed_never_listed_stopped_is(self):
		wo_done = factories.make_wo()
		wo_stopped = factories.make_wo()
		frappe.db.set_value("Work Order", wo_done, "status", "Completed")
		frappe.db.set_value("Work Order", wo_stopped, "status", "Stopped")
		frappe.set_user(self.operator)
		rows = self._rows()
		self.assertNotIn(wo_done, rows)
		self.assertEqual(rows[wo_stopped]["status"], "Stopped")

	def test_badges_for_transfer_operations_and_done(self):
		wo_packed = _progressed_wo()  # transferred, no operations, target left
		wo_done = _progressed_wo()
		frappe.db.set_value("Work Order", wo_done, "produced_qty", 100)
		# operations step only shows once the materials were transferred
		wo_ops = factories.make_wo()
		factories.add_wo_operation(wo_ops, 0)
		factories.add_wo_operation(wo_ops, 0)
		factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 100, 500)
		factories.se_transfer(wo_ops)

		frappe.set_user(self.operator)
		rows = self._rows()
		self.assertEqual(rows[wo_packed]["badge"], "Menunggu Packing")
		self.assertEqual(rows[wo_done]["badge"], "Selesai")
		self.assertEqual(rows[wo_ops]["badge"], "Operasi 1/2")
		self.assertTrue(rows[wo_ops]["has_operations"])

	def test_blocked_reasons_reported_per_row(self):
		wo = factories.make_wo()  # own WO: the flag must not leak into other tests
		frappe.db.set_value("Work Order", wo, "reserve_stock", 1)
		frappe.set_user(self.operator)
		reasons = self._rows()[wo]["blocked_reasons"]
		self.assertTrue(any("reservasi" in r for r in reasons))

	# ---------------------------------------------------------------- search

	def test_search_filters_by_name_and_item(self):
		frappe.set_user(self.operator)
		by_name = self._rows(search=self.wo)
		self.assertIn(self.wo, by_name)
		self.assertTrue(all(self.wo == n for n in by_name))  # exact name matches alone
		by_item = self._rows(search="PDTC-FG")
		self.assertIn(self.wo, by_item)
		self.assertEqual(self._rows(search="PDTC-ZZZNOPE"), {})

	def test_search_with_whitespace_only_is_ignored(self):
		frappe.set_user(self.operator)
		self.assertIn(self.wo, self._rows(search="   "))


class TestGetWorkOrderDetail(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls.nobody = factories.make_user(NOBODY)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	# ---------------------------------------------------------------- access

	def test_requires_operator_role(self):
		wo = factories.make_wo()
		frappe.set_user(self.nobody)
		with self.assertRaises(frappe.PermissionError):
			api.get_work_order_detail(wo)

	# ------------------------------------------------------------- materials

	def test_materials_two_sessions_dipakai_vs_transferred(self):
		wo = _progressed_wo()
		frappe.set_user(self.operator)
		materials = {m["item_code"]: m for m in api.get_work_order_detail(wo)["materials"]}

		rm1 = materials[factories.RM1]
		self.assertEqual(rm1["required_qty"], 10)  # BOM: 10 per 100 FG
		self.assertEqual(rm1["transferred_net"], 100)
		self.assertEqual(rm1["dipakai"], 25)  # 10 + 15 across the two sessions
		self.assertEqual(rm1["sisa_wip"], 75)
		self.assertEqual(rm1["sisa_perlu"], 0)

		rm2 = materials[factories.RM2]
		self.assertEqual((rm2["required_qty"], rm2["transferred_net"], rm2["dipakai"]), (2, 100, 5))

	def test_skip_transfer_wo_dipakai_from_source_warehouse(self):
		"""skip_transfer WO (supported config, spec 6): core books the
		Manufacture material rows directly FROM the source warehouse - no WIP
		leg ever exists (make_stock_entry: from_warehouse = source_warehouse
		when skip_transfer and not from_wip_warehouse). dipakai must still
		count those rows (spec 5 has no warehouse qualifier), sisa_wip floors
		at 0 and sisa_perlu decreases with the consumption."""
		wo = factories.make_wo()
		frappe.db.set_value("Work Order", wo, "skip_transfer", 1)
		factories.stock_in(factories.RM1, factories.STORES, 100, 100, batch_no=factories.BATCH_RM1)
		factories.stock_in(factories.RM2, factories.STORES, 100, 500)
		factories.se_manufacture(wo, good=60, materials={factories.RM1: 6, factories.RM2: 1.2})

		frappe.set_user(self.operator)
		detail = api.get_work_order_detail(wo)
		rm1 = next(m for m in detail["materials"] if m["item_code"] == factories.RM1)
		self.assertEqual(rm1["transferred_net"], 0)  # no transfer leg by design
		self.assertEqual(rm1["dipakai"], 6)  # consumed straight from Stores
		self.assertEqual(rm1["sisa_wip"], 0)
		self.assertEqual(rm1["sisa_perlu"], 4)  # required 10 - 6 consumed
		self.assertEqual(detail["next_action"], "finish_production")

	def test_expired_batch_flagged_and_excluded_from_tersedia(self):
		wo = _progressed_wo()
		factories.stock_in(factories.RM1, factories.STORES, 50, 100, batch_no="PDTC-B-RM1-EXPIRED")
		frappe.db.set_value("Batch", "PDTC-B-RM1-EXPIRED", "expiry_date", add_days(today(), -1))

		frappe.set_user(self.operator)
		rm1 = next(m for m in api.get_work_order_detail(wo)["materials"] if m["item_code"] == factories.RM1)
		stock = rm1["stok_gudang_asal"]
		self.assertEqual(stock["warehouse"], factories.STORES)
		expired = next(b for b in stock["batches"] if b["batch_no"] == "PDTC-B-RM1-EXPIRED")
		self.assertTrue(expired["expired"])
		self.assertGreater(expired["qty"], 0)
		# expired qty flagged but never counted as available; the Bin shows the
		# whole truth (>= the batches view).
		self.assertEqual(stock["tersedia"], sum(b["qty"] for b in stock["batches"] if not b["expired"]))
		self.assertGreaterEqual(flt(stock["bin_qty"]), stock["tersedia"] + expired["qty"])

	# -------------------------------------------------- operations, entries

	def test_operations_open_job_card_and_tambahan_flag(self):
		wo = factories.make_wo()
		factories.add_wo_operation(wo, 0)
		operation_id = frappe.get_all("Work Order Operation", filters={"parent": wo}, pluck="name")[0]

		frappe.set_user(self.operator)
		detail = api.get_work_order_detail(wo)
		op = detail["operations"][0]
		self.assertEqual((op["operation"], op["sisa"]), (factories.OPERATION, 100))
		self.assertIsNone(op["open_job_card"])
		self.assertTrue(op["perlu_kartu_tambahan"])

		jc = _insert_open_job_card(wo, factories.OPERATION, operation_id)
		detail = api.get_work_order_detail(wo)
		self.assertEqual(detail["operations"][0]["open_job_card"], jc)
		self.assertFalse(detail["operations"][0]["perlu_kartu_tambahan"])
		self.assertIn(jc, [c["name"] for c in detail["job_cards"]])

	def test_stock_entries_report_custom_p_details(self):
		wo = _progressed_wo()
		frappe.set_user(self.operator)
		entries = api.get_work_order_detail(wo)["stock_entries"]
		self.assertEqual(len(entries), 3)  # 1 transfer + 2 packing sessions
		purposes = [e["purpose"] for e in entries]
		self.assertEqual(purposes.count("Manufacture"), 2)
		app_session = entries[-1]
		self.assertEqual(app_session["petugas_packing"], OPERATOR)
		self.assertEqual((app_session["good"], app_session["sisa"]), (30, 4))
		self.assertIsNotNone(app_session["posting_datetime"])

	def test_packing_summary_equals_shared_computation(self):
		wo = _progressed_wo()
		frappe.set_user(self.operator)
		summary = api.get_work_order_detail(wo)["packing_summary"]
		self.assertEqual(summary, wo_summary.compute_summary(wo))
		self.assertEqual(summary["custom_good_qty_postpacking"], 90)
		self.assertEqual(summary["custom_reject_qty_postpacking"], 2)
		self.assertEqual(summary["custom_trial_qty_postpacking"], 1)
		self.assertEqual(summary["custom_sisa_qty_postpacking"], 4)

	# ------------------------------------------------------------ next action

	def test_next_action_states(self):
		fresh = factories.make_wo()
		packed = _progressed_wo()
		done = _progressed_wo()
		frappe.db.set_value("Work Order", done, "produced_qty", 100)
		blocked = _progressed_wo()
		frappe.db.set_value("Work Order", blocked, "reserve_stock", 1)

		frappe.set_user(self.operator)
		details = {w: api.get_work_order_detail(w) for w in (fresh, packed, done, blocked)}
		self.assertEqual(details[fresh]["next_action"], "transfer_material")
		self.assertEqual(details[packed]["next_action"], "finish_production")
		self.assertEqual(details[done]["next_action"], "done")
		self.assertTrue(details[blocked]["next_action"].startswith("blocked:"))
		self.assertTrue(details[blocked]["blocked_reasons"])

	def test_next_action_complete_operation_with_open_card(self):
		wo = factories.make_wo()
		frappe.db.set_value("Work Order", wo, "skip_transfer", 1)
		factories.add_wo_operation(wo, 0)
		operation_id = frappe.get_all("Work Order Operation", filters={"parent": wo}, pluck="name")[0]
		jc = _insert_open_job_card(wo, factories.OPERATION, operation_id)

		frappe.set_user(self.operator)
		detail = api.get_work_order_detail(wo)
		self.assertEqual(detail["next_action"], f"complete_operation:{jc}")

	def test_production_metadata_only_fields_in_meta(self):
		wo = factories.make_wo()
		frappe.set_user(self.operator)
		metadata = api.get_work_order_detail(wo)["production_metadata"]
		allowed = set(api.EDITABLE_METADATA_FIELDS + api.DISPLAY_METADATA_FIELDS)
		self.assertTrue(set(metadata).issubset(allowed))

"""Tests for api.complete_operation (spec 7.5) - numbers per proof P13.

Contract proven per test:
- one-tap choreography (P13a): draft Job Card -> submitted, >= 1 time log with
  from == to (duration ~ 0), WO operation row completed_qty = actual qty;
- started_at -30 minutes -> time_in_mins ~ 30 (P13c);
- final partial 950/1000 does NOT inflate completed (P13d): completed 950,
  pending 50, close decision flagged;
- partial 60 creates the additional card for 40 (P13e, explicit `operation`
  payload) and completing it brings the operation to 100;
- sequence violation -> Indonesian message, nothing recorded (P13f);
- enforce_time_logs=1 still passes (from & to both set, P13b);
- optional `loss` is recorded as the operation process_loss_qty;
- replay -> duplicate=True, single effect;
- operator AND supervisor allowed, roleless denied;
- Stopped WO / already-submitted card / wrong WO relation rejected.

Each test builds its Work Order on its own workstation(s): with the site's
capacity planning enabled, every Job Card carries scheduled time windows and
validate_time_logs rejects taps overlapping another card's windows on the
SAME workstation (mapped OverlapError in production, avoided in tests here).
"""

from datetime import UTC

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, flt, now_datetime

from production_app import api
from production_app.tests import factories

OPERATOR = "pdtc.operation.operator@example.com"
SUPERVISOR = "pdtc.operation.supervisor@example.com"
OUTSIDER = "pdtc.operation.outsider@example.com"


class OperationFixture(IntegrationTestCase):
	"""Shared fixtures/helpers (no test methods of its own): WOs with
	operations on fresh workstations + the ledger-key cleanup contract."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		factories.setup_operation()
		factories.make_operation(factories.OPERATION2, workstation=factories.WORKSTATION)
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls.supervisor = factories.make_user(SUPERVISOR, roles=["Production Supervisor"])
		cls.outsider = factories.make_user(OUTSIDER)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		self.keys = []
		self.addCleanup(self._cleanup)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _cleanup(self):
		frappe.set_user("Administrator")
		for key in self.keys:
			if frappe.db.exists("Production Request Log", key):
				frappe.delete_doc("Production Request Log", key, ignore_permissions=True, force=True)

	def _key(self):
		key = "TEST-" + frappe.utils.random_string(10)
		self.keys.append(key)
		return key

	def _wo(self, n_ops=1, qty=100):
		"""WO with operations, each on its own fresh workstation (see module
		docstring); returns (wo_name, job_cards)."""
		suffix = frappe.utils.random_string(5)
		operations = [(factories.OPERATION, factories.make_workstation(f"PDTC WS {suffix} A"))]
		if n_ops == 2:
			operations.append((factories.OPERATION2, factories.make_workstation(f"PDTC WS {suffix} B")))
		bom = factories.make_bom_operations(operations)
		return factories.make_wo_operations(bom, qty=qty)

	def _complete(self, wo, job_card, qty, is_final, user=None, **kwargs):
		frappe.set_user(user or self.operator)
		return api.complete_operation(wo, job_card, qty, is_final, self._key(), **kwargs)

	def _op_completed(self, operation_id, field="completed_qty"):
		return flt(frappe.db.get_value("Work Order Operation", operation_id, field))


class TestCompleteOperation(OperationFixture):
	# ------------------------------------------------------------ happy paths

	def test_one_tap_happy_path(self):
		wo, jcs = self._wo()
		result = self._complete(wo, jcs[0].name, 100, True)

		jc = frappe.get_doc("Job Card", jcs[0].name)
		self.assertEqual(jc.docstatus, 1)
		self.assertGreaterEqual(len(jc.time_logs), 1)
		self.assertEqual(round(jc.total_time_in_mins), 0)  # one tap = ~zero duration
		self.assertEqual(flt(jc.total_completed_qty), 100.0)
		self.assertEqual(flt(jc.pending_qty), 0.0)
		self.assertEqual(self._op_completed(jcs[0].operation_id), 100.0)

		self.assertEqual(result["job_card"], jc.name)
		self.assertEqual(result["operation_completed"], 100.0)
		self.assertIsNone(result["kartu_tambahan"])
		self.assertEqual(result["status"], "In Process")
		# nothing transferred yet: material pickup stays the next step
		self.assertEqual(result["next_action"], "transfer_material")

	def test_started_at_gives_real_duration(self):
		wo, jcs = self._wo()
		started = add_to_date(now_datetime(), minutes=-30)
		self._complete(wo, jcs[0].name, 100, True, started_at=started)

		jc = frappe.get_doc("Job Card", jcs[0].name)
		mins = flt(jc.time_logs[0].time_in_mins)
		self.assertLessEqual(abs(mins - 30), 1)

	def test_tz_aware_started_at_rejected(self):
		"""A started_at carrying a timezone ("...Z" / "...+00:00", e.g. a
		toISOString() client) must be rejected in Indonesian: get_datetime
		parses it into an AWARE datetime that crashes at the naive MySQL write
		of the TimeLog from_time (raw 500). The contract is naive device-local
		time (spec 7.5 P13c)."""
		from datetime import timezone

		wo, jcs = self._wo()
		aware = now_datetime().replace(tzinfo=UTC).isoformat()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._complete(wo, jcs[0].name, 100, True, started_at=aware)
		self.assertIn("zona waktu", str(ctx.exception))
		# nothing recorded on the card
		self.assertEqual(frappe.get_doc("Job Card", jcs[0].name).time_logs, [])

	def test_final_partial_does_not_inflate_completed(self):
		wo, jcs = self._wo(qty=1000)
		result = self._complete(wo, jcs[0].name, 950, True)

		jc = frappe.get_doc("Job Card", jcs[0].name)
		self.assertEqual((flt(jc.total_completed_qty), flt(jc.pending_qty)), (950.0, 50.0))
		self.assertEqual(self._op_completed(jcs[0].operation_id), 950.0)  # NOT 1000
		self.assertTrue(result["needs_close_decision"])

	def test_partial_creates_additional_card(self):
		wo, jcs = self._wo()
		first = self._complete(wo, jcs[0].name, 60, False)

		self.assertTrue(first["kartu_tambahan"])
		extra = frappe.get_doc("Job Card", first["kartu_tambahan"])
		self.assertEqual((extra.docstatus, flt(extra.for_quantity)), (0, 40.0))
		self.assertEqual(extra.operation, factories.OPERATION)

		second = self._complete(wo, extra.name, 40, True)
		self.assertIsNone(second["kartu_tambahan"])
		self.assertEqual(self._op_completed(jcs[0].operation_id), 100.0)
		self.assertEqual(
			sorted(
				r.docstatus
				for r in frappe.get_all("Job Card", filters={"work_order": wo}, fields=["docstatus"])
			),
			[1, 1],
		)

	def test_loss_recorded_as_operation_process_loss(self):
		wo, jcs = self._wo()
		self._complete(wo, jcs[0].name, 95, True, loss=5)

		jc = frappe.get_doc("Job Card", jcs[0].name)
		self.assertEqual((flt(jc.process_loss_qty), flt(jc.pending_qty)), (5.0, 0.0))
		self.assertEqual(self._op_completed(jcs[0].operation_id, "process_loss_qty"), 5.0)

	def test_enforce_time_logs_one_tap_still_passes(self):
		wo, jcs = self._wo()
		initial = frappe.db.get_single_value("Manufacturing Settings", "enforce_time_logs")
		frappe.db.set_single_value("Manufacturing Settings", "enforce_time_logs", 1)
		try:
			self._complete(wo, jcs[0].name, 100, True)
			jc = frappe.get_doc("Job Card", jcs[0].name)
			self.assertEqual(jc.docstatus, 1)  # strict mode passed
			self.assertTrue(all(row.from_time and row.to_time for row in jc.time_logs))
		finally:
			frappe.db.set_single_value("Manufacturing Settings", "enforce_time_logs", initial)

	# ---------------------------------------------------------------- rejects

	def test_sequence_violation_rejected_in_indonesian(self):
		wo, jcs = self._wo(n_ops=2)
		self.assertEqual(jcs[1].operation, factories.OPERATION2)

		with self.assertRaises(frappe.ValidationError) as cm:
			self._complete(wo, jcs[1].name, 100, True)  # op2 before op1
		message = str(cm.exception)
		self.assertIn("Selesaikan operasi", message)
		self.assertIn(factories.OPERATION, message)

		# nothing recorded
		self.assertEqual(frappe.db.get_value("Job Card", jcs[1].name, "docstatus"), 0)
		self.assertEqual(self._op_completed(jcs[1].operation_id), 0.0)

		# correct order goes through
		self._complete(wo, jcs[0].name, 100, True)
		self._complete(wo, jcs[1].name, 100, True)
		self.assertEqual(self._op_completed(jcs[1].operation_id), 100.0)

	def test_stopped_wo_rejected(self):
		wo, jcs = self._wo()
		frappe.get_doc("Work Order", wo).update_status("Stopped")
		with self.assertRaises(frappe.ValidationError) as cm:
			self._complete(wo, jcs[0].name, 100, True)
		self.assertIn("Stopped", str(cm.exception))
		self.assertEqual(frappe.db.get_value("Job Card", jcs[0].name, "docstatus"), 0)

	def test_already_submitted_card_rejected(self):
		wo, jcs = self._wo()
		self._complete(wo, jcs[0].name, 100, True)
		with self.assertRaises(frappe.ValidationError) as cm:
			self._complete(wo, jcs[0].name, 1, True)
		self.assertIn("Kartu operasi sudah selesai/dibatalkan", str(cm.exception))

	def test_card_of_another_wo_rejected(self):
		_wo_a, jcs_a = self._wo()
		wo_b, _jcs_b = self._wo()
		with self.assertRaises(frappe.PermissionError) as cm:
			self._complete(wo_b, jcs_a[0].name, 100, True)
		self.assertIn("bukan bagian dari Work Order", str(cm.exception))

	def test_qty_over_card_qty_rejected(self):
		wo, jcs = self._wo()
		with self.assertRaises(frappe.ValidationError) as cm:
			self._complete(wo, jcs[0].name, 90, True, loss=20)  # 90 + 20 > card 100
		self.assertIn("melebihi jumlah kartu operasi", str(cm.exception))

	def test_qty_zero_rejected(self):
		wo, jcs = self._wo()
		with self.assertRaises(frappe.ValidationError) as cm:
			self._complete(wo, jcs[0].name, 0, True)
		self.assertIn("harus lebih besar dari 0", str(cm.exception))

	# ------------------------------------------------------- roles + idempotency

	def test_operator_and_supervisor_allowed_outsider_denied(self):
		wo, jcs = self._wo()
		result = self._complete(wo, jcs[0].name, 100, True, user=self.supervisor)
		self.assertEqual(result["operation_completed"], 100.0)

		frappe.set_user("Administrator")  # fixtures are built as Administrator
		wo2, jcs2 = self._wo()
		with self.assertRaises(frappe.PermissionError):
			self._complete(wo2, jcs2[0].name, 100, True, user=self.outsider)

	def test_replay_returns_duplicate_with_single_effect(self):
		wo, jcs = self._wo()
		frappe.set_user(self.operator)
		key = self._key()
		first = api.complete_operation(wo, jcs[0].name, 60, False, key)
		replay = api.complete_operation(wo, jcs[0].name, 60, False, key)

		self.assertTrue(replay["duplicate"])
		self.assertEqual(replay["job_card"], first["job_card"])
		self.assertEqual(replay["kartu_tambahan"], first["kartu_tambahan"])
		self.assertEqual(self._op_completed(jcs[0].operation_id), 60.0)
		self.assertEqual(
			frappe.get_all("Job Card", filters={"work_order": wo, "docstatus": 1}, pluck="name"),
			[first["job_card"]],
		)

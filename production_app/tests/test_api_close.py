"""Tests for api.close_work_order (spec 7.8) - method-doc path (4.2).

Contract proven per test:
- supervisor closes WITHOUT Work Order write permission (the fixtures grant
  the roles read-only WO access; update_status db_sets the status, so the
  method-doc path needs no bypass);
- core gate mirrored: a submitted Job Card still "Work In Progress" blocks
  the close (core close_work_order query), WO status untouched;
- operator denied (Supervisor only);
- `reason` recorded as a Work Order comment;
- Stopped WO CAN be closed directly (traced core update_status: Closed is
  accepted from any submitted status incl. Stopped);
- after a final partial tap (P13d) the close keeps the operation's completed
  qty (950 of 1000);
- empty reason / double close rejected.
"""

import frappe
from frappe.tests import IntegrationTestCase

from production_app import api
from production_app.tests import factories
from production_app.tests.test_api_operation import OperationFixture

SUPERVISOR = "pdtc.close.supervisor@example.com"
OPERATOR = "pdtc.close.operator@example.com"


class TestCloseWorkOrder(OperationFixture):
	"""Reuses the WO-with-operations helpers and ledger cleanup contract;
	different users so the runs stay independent."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls.supervisor = factories.make_user(SUPERVISOR, roles=["Production Supervisor"])
		frappe.db.commit()

	def _close(self, wo, reason="target tidak tercapai", user=None):
		frappe.set_user(user or self.supervisor)
		return api.close_work_order(wo, reason, self._key())

	# ------------------------------------------------------------ happy paths

	def test_supervisor_closes_without_wo_write(self):
		wo, jcs = self._wo()
		self._complete(wo, jcs[0].name, 100, True)  # submitted card reads Completed

		# the fixtures intentionally keep the WO read-only for the roles
		self.assertFalse(
			frappe.has_permission("Work Order", "write", user=self.supervisor),
			"test premise: supervisor must NOT hold Work Order write",
		)
		result = self._close(wo)

		self.assertEqual(result["status"], "Closed")
		self.assertEqual(
			frappe.db.get_value(
				"Work Order", wo, ["status", "produced_qty", "process_loss_qty"], as_dict=True
			),
			{"status": "Closed", "produced_qty": 0.0, "process_loss_qty": 0.0},
		)
		self.assertEqual(result["belum_diproduksi"], 100.0)

	def test_close_after_final_partial_keeps_completed(self):
		wo, jcs = self._wo(qty=1000)
		self._complete(wo, jcs[0].name, 950, True)  # P13d: pending 50
		result = self._close(wo, "sisa 50 dibatalkan")

		self.assertEqual(result["status"], "Closed")
		# produced only moves with packing sessions; the full target stays open
		self.assertEqual((result["produced"], result["belum_diproduksi"]), (0.0, 1000.0))
		# the close never inflates what the operations actually completed
		self.assertEqual(self._op_completed(jcs[0].operation_id), 950.0)

	def test_reason_recorded_as_wo_comment(self):
		wo, _jcs = self._wo()
		self._close(wo, "mesin rusak, produksi dihentikan")

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Order", "reference_name": wo, "comment_type": "Comment"},
			pluck="content",
		)
		self.assertEqual(len(comments), 1)
		self.assertIn("mesin rusak, produksi dihentikan", comments[0])

	def test_stopped_wo_can_be_closed(self):
		wo, _jcs = self._wo()
		frappe.get_doc("Work Order", wo).update_status("Stopped")
		result = self._close(wo)  # core accepts Closed from Stopped
		self.assertEqual(result["status"], "Closed")

	# ---------------------------------------------------------------- rejects

	def test_wip_submitted_job_card_blocks_close(self):
		wo, jcs = self._wo()
		self._complete(wo, jcs[0].name, 60, False)
		# a submitted JC is "Completed" on app-supported WOs (no items); force
		# the core gate's exact input to exercise the mirror
		frappe.db.set_value("Job Card", jcs[0].name, "status", "Work In Progress")

		with self.assertRaises(frappe.ValidationError) as cm:
			self._close(wo)
		self.assertIn("Selesaikan atau batalkan job card", str(cm.exception))
		self.assertIn(jcs[0].name, str(cm.exception))
		self.assertNotEqual(frappe.db.get_value("Work Order", wo, "status"), "Closed")

	def test_operator_cannot_close(self):
		wo, _jcs = self._wo()
		with self.assertRaises(frappe.PermissionError) as cm:
			self._close(wo, user=self.operator)
		self.assertIn("tidak memiliki hak", str(cm.exception))

	def test_missing_reason_rejected(self):
		wo, _jcs = self._wo()
		with self.assertRaises(frappe.ValidationError) as cm:
			self._close(wo, "   ")
		self.assertIn("Alasan penutupan wajib", str(cm.exception))
		self.assertNotEqual(frappe.db.get_value("Work Order", wo, "status"), "Closed")

	def test_double_close_rejected(self):
		wo, _jcs = self._wo()
		self._close(wo)
		with self.assertRaises(frappe.ValidationError) as cm:
			self._close(wo, "second try")
		self.assertIn("sudah Closed", str(cm.exception))

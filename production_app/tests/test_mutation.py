"""Tests for the mutation engine mutation.py (spec 10.1, 10.2, 10.3).

Contract proven per test:
- one idempotency key = one side effect. The side effect is the lightest real
  document creation the brief allows: one core `Note` per key (title is keyed,
  so the per-test effect count is countable);
- replay returns the stored result with duplicate=True after a LIGHT access
  re-check; binding mismatches (payload/action/user/WO) and the Processing
  window are rejected with firm Indonesian messages (10.2);
- fingerprint canonicalization: 10 == 10.0, key order irrelevant, None != "";
- per-WO row lock serializes a second raw connection (P9a recipe);
- fn raising leaves NO ledger row - the key is cleanly retryable (10.3, P9b).
"""

import frappe
import pymysql
from frappe.tests import IntegrationTestCase

from production_app import mutation
from production_app.tests import factories


class TestMutation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		factories.setup_second_company()
		cls.operator = factories.make_user("pdtc.operator@example.com", roles=["Production Operator"])
		cls.wo = factories.make_wo()
		# Commit fixtures: test_fn_exception simulates the request-error
		# rollback (10.3); without this commit it would wipe the class
		# fixtures for every later test (same reason super().setUpClass()
		# commits its own setup).
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		self.notes = []  # Note names created by the test fn (side effects)
		self.keys = []  # idempotency keys used (ledger rows to clean up)
		self.addCleanup(self._cleanup)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _cleanup(self):
		"""Per-test cleanup: the class-level rollback only runs at class end."""
		frappe.set_user("Administrator")
		for name in self.notes:
			if frappe.db.exists("Note", name):
				frappe.delete_doc("Note", name, ignore_permissions=True, force=True)
		for key in self.keys:
			if frappe.db.exists("Production Request Log", key):
				frappe.delete_doc("Production Request Log", key, ignore_permissions=True, force=True)

	def _key(self):
		key = "TEST-" + frappe.utils.random_string(10)
		self.keys.append(key)
		return key

	def _fn(self, key, crash=False):
		"""fn = lightest real side effect: create one core Note keyed by the
		idempotency key. ignore_permissions mirrors every endpoint fn (bypass
		only AFTER the gates, 11.2 step 5); crash=True dies AFTER the side
		effect, simulating a worker failure mid-mutation."""

		def fn():
			note = frappe.get_doc(
				{"doctype": "Note", "title": f"PDTC-mut-{key}", "content": "mutation side effect"}
			).insert(ignore_permissions=True)
			self.notes.append(note.name)
			if crash:
				raise RuntimeError("simulated crash after the side effect")
			return {"note": note.name, "reference_doctype": "Note", "reference_doc": note.name}

		return fn

	def _effect_count(self, key):
		return frappe.db.count("Note", {"title": f"PDTC-mut-{key}"})

	# ------------------------------------------------------------- happy path

	def test_happy_path_creates_done_log_and_one_effect(self):
		key, payload = self._key(), {"good": 10.0}
		result = mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))

		self.assertFalse(result.get("duplicate"))
		row = frappe.db.get_value(
			"Production Request Log",
			key,
			[
				"status",
				"user",
				"action",
				"work_order",
				"payload_fingerprint",
				"reference_doctype",
				"reference_doc",
			],
			as_dict=True,
		)
		self.assertEqual(row.status, "Done")
		self.assertEqual(row.user, frappe.session.user)  # Administrator
		self.assertEqual(row.action, "transfer_material")
		self.assertEqual(row.work_order, self.wo)
		self.assertEqual(row.payload_fingerprint, mutation.payload_fingerprint(payload))
		self.assertEqual(row.reference_doctype, "Note")
		self.assertEqual(row.reference_doc, result["note"])
		self.assertEqual(self._effect_count(key), 1)  # exactly one effect

	def test_replay_returns_duplicate_without_second_effect(self):
		key, payload = self._key(), {"good": 5}
		first = mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))
		second = mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))

		self.assertTrue(second["duplicate"])
		self.assertEqual(first["note"], second["note"])  # identical stored result
		self.assertEqual(self._effect_count(key), 1)  # no second effect

	def test_replay_rejected_after_wo_read_revoked(self):
		frappe.set_user(self.operator)
		key, payload = self._key(), {"good": 7}
		mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))

		# Revoke the operator's WO read via a User Permission on another
		# company (proven pattern from test_access).
		frappe.set_user("Administrator")
		perm = factories.make_user_permission(self.operator, "Company", factories.SECOND_COMPANY)
		self.addCleanup(frappe.delete_doc, "User Permission", perm)
		frappe.set_user(self.operator)

		with self.assertRaises(frappe.ValidationError) as ctx:
			mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))
		self.assertIn("tidak berhak melihat hasil", str(ctx.exception))
		self.assertEqual(self._effect_count(key), 1)

	# ------------------------------------------------------- binding mismatch

	def test_same_key_different_payload_rejected(self):
		key = self._key()
		mutation.run_mutation(self.wo, "transfer_material", key, {"good": 1}, self._fn(key))
		with self.assertRaises(frappe.ValidationError) as ctx:
			mutation.run_mutation(self.wo, "transfer_material", key, {"good": 2}, self._fn(key))
		self.assertIn("dipakai untuk aksi/payload berbeda", str(ctx.exception))
		self.assertEqual(self._effect_count(key), 1)  # no effect from the rejected call

	def test_same_key_different_action_rejected(self):
		key, payload = self._key(), {"good": 1}
		mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))
		with self.assertRaises(frappe.ValidationError) as ctx:
			mutation.run_mutation(self.wo, "finish_production", key, payload, self._fn(key))
		self.assertIn("dipakai untuk aksi/payload berbeda", str(ctx.exception))
		self.assertEqual(self._effect_count(key), 1)

	def test_processing_status_rejected_with_try_again(self):
		key, payload = self._key(), {"good": 2}
		mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))
		# Force the crash-only "Processing" window (no-commit policy, 10.3).
		frappe.db.set_value("Production Request Log", key, "status", "Processing")
		with self.assertRaises(frappe.ValidationError) as ctx:
			mutation.run_mutation(self.wo, "transfer_material", key, payload, self._fn(key))
		self.assertIn("sedang diproses", str(ctx.exception))
		self.assertEqual(self._effect_count(key), 1)

	# ------------------------------------------------------------ fingerprint

	def test_fingerprint_canonicalization(self):
		# 10.0 == 10 (numbers normalized, not raw json)
		self.assertEqual(
			mutation.payload_fingerprint({"good": 10.0}), mutation.payload_fingerprint({"good": 10})
		)
		# dict key order irrelevant
		self.assertEqual(
			mutation.payload_fingerprint({"a": 1, "b": 2}), mutation.payload_fingerprint({"b": 2, "a": 1})
		)
		# None vs "" consistently distinguished
		self.assertNotEqual(
			mutation.payload_fingerprint({"x": None}), mutation.payload_fingerprint({"x": ""})
		)
		# nested structures + float noise beyond 9 decimals collapse
		self.assertEqual(
			mutation.payload_fingerprint({"rows": [{"q": 0.1 + 0.2}]}),
			mutation.payload_fingerprint({"rows": [{"q": 0.3}]}),
		)

	# --------------------------------------------------------------- locking

	def test_wo_row_lock_serializes_second_connection(self):
		"""P9a recipe: while A (frappe conn) holds FOR UPDATE on the WO row,
		a second raw pymysql connection times out (1205); after A releases,
		B acquires the lock. Credentials read at runtime, never printed."""
		self.assertEqual(mutation.lock_work_order(self.wo), self.wo)  # A holds the lock

		conf = frappe.conf
		conn = pymysql.connect(
			host=conf.get("db_host") or "localhost",
			port=int(conf.get("db_port") or 3306),
			user=conf.db_name,
			password=conf.get("db_password"),
			database=conf.db_name,
		)
		try:
			with conn.cursor() as cur:
				cur.execute("SET SESSION innodb_lock_wait_timeout = 3")
				blocked = None
				try:
					cur.execute("select name from `tabWork Order` where name=%s for update", (self.wo,))
				except pymysql.err.OperationalError as e:
					blocked = e
				self.assertEqual(blocked.args[0], 1205)  # lock wait timeout while A holds
				conn.commit()
				frappe.db.rollback()  # A releases the lock WITHOUT committing test data
				cur.execute("select name from `tabWork Order` where name=%s for update", (self.wo,))
				self.assertEqual(cur.fetchone()[0], self.wo)  # B succeeds after release
				conn.commit()
		finally:
			conn.close()

	# ------------------------------------------------- atomicity / retry (10.3)

	def test_fn_exception_leaves_no_log_and_key_retryable(self):
		key, payload = self._key(), {"good": 3}
		with self.assertRaises(RuntimeError):
			mutation.run_mutation(self.wo, "finish_production", key, payload, self._fn(key, crash=True))

		frappe.db.rollback()  # what the request wrapper does on an unhandled error
		self.assertIsNone(frappe.db.get_value("Production Request Log", key))  # log gone
		self.assertEqual(self._effect_count(key), 0)  # side effect rolled back too

		retry = mutation.run_mutation(self.wo, "finish_production", key, payload, self._fn(key))
		self.assertFalse(retry.get("duplicate"))  # clean retry, not a replay
		self.assertEqual(self._effect_count(key), 1)
		self.assertEqual(frappe.db.get_value("Production Request Log", key, "status"), "Done")

	# ------------------------------------------------------- input validation

	def test_input_validation(self):
		fn = self._fn(self._key())
		with self.assertRaises(frappe.ValidationError):
			mutation.run_mutation(self.wo, "transfer_material", "", {}, fn)  # empty key
		with self.assertRaises(frappe.ValidationError):
			mutation.run_mutation(self.wo, "transfer_material", "bad key with spaces!", {}, fn)
		with self.assertRaises(frappe.ValidationError):
			mutation.run_mutation(self.wo, "not_an_action", self._key(), {}, fn)
		with self.assertRaises(frappe.ValidationError):
			mutation.run_mutation(self.wo, "transfer_material", self._key(), [], fn)  # not a dict

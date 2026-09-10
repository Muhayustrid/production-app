"""Tests for the Production Request Log idempotency ledger (spec 10.2).

The binding guarantee is at the database level: idempotency_key carries a
unique constraint, so a duplicate insert is rejected even when it bypasses
all ORM checks. Driver on frappe v16 is mysqlclient, so the raw backstop
exception is MySQLdb.IntegrityError (proof P9b).
"""

import MySQLdb
import frappe
from frappe.exceptions import DuplicateEntryError
from frappe.tests import IntegrationTestCase


def _log_doc(key):
	doc = frappe.get_doc({
		"doctype": "Production Request Log",
		"idempotency_key": key,
		"user": "Administrator",
		"action": "finish_production",
		"work_order": None,
		"payload_fingerprint": "deadbeef",
		"status": "Processing",
	})
	return doc


class TestProductionRequestLog(IntegrationTestCase):
	def test_insert_and_defaults(self):
		key = "TEST-" + frappe.utils.random_string(10)
		doc = _log_doc(key)
		doc.insert()
		self.assertEqual(doc.name, key)  # autoname field:idempotency_key
		self.assertEqual(frappe.db.get_value("Production Request Log", key, "status"), "Processing")

	def test_orm_duplicate_rejected(self):
		key = "TEST-" + frappe.utils.random_string(10)
		_log_doc(key).insert()
		with self.assertRaises(DuplicateEntryError):
			_log_doc(key).insert()

	def test_unique_constraint_rejected_at_db_level(self):
		"""Same key under a different primary key must hit the DB unique index.

		Raw INSERT via frappe.db.sql (the P9b method): higher-level inserts
		(db_insert / doc.insert) translate the driver error into frappe's
		UniqueValidationError / DuplicateEntryError, hiding MySQLdb.
		"""
		key = "TEST-" + frappe.utils.random_string(10)
		_log_doc(key).insert()
		now = frappe.utils.now()
		with self.assertRaises(MySQLdb.IntegrityError):
			frappe.db.sql(
				"""insert into `tabProduction Request Log`
					(name, owner, creation, modified, modified_by, docstatus, idx,
					 idempotency_key, `user`, action, status)
					values (%(name)s, %(owner)s, %(now)s, %(now)s, %(owner)s, 0, 0,
						%(key)s, %(owner)s, %(action)s, %(status)s)""",
				{"name": key + "-other", "owner": "Administrator", "now": now, "key": key,
				 "action": "finish_production", "status": "Processing"},
			)

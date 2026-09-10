# Copyright (c) 2026, Rotiri Project and contributors
# License: MIT

import frappe
from frappe.model.document import Document


class ProductionRequestLog(Document):
	"""Idempotency ledger (spec 10.2) - not a state machine.

	`idempotency_key` carries a DB-level unique constraint (docfield
	unique=1) AND names the document (autoname field:), so a duplicate
	request is rejected by the database even if it bypasses every ORM
	check. The raw backstop exception with the mysqlclient driver is
	MySQLdb.IntegrityError (proof P9b).
	"""

	pass

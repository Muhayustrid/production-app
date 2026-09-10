"""Mutation engine (spec 10) - Tahap 3.

Every mutating SPA endpoint routes through `run_mutation` (10.2):
- The Work Order row is locked FIRST (10.1, `lock_work_order`), so two
  sessions mutating the same WO serialize and the ledger check happens
  under the lock; no ledger row can be observed mid-flight.
- The request is bound in `Production Request Log` to (user, action,
  work_order, payload fingerprint); the DB unique constraint on
  `idempotency_key` (autoname field:) is the final backstop (P9b).
- Replay of a Done request re-runs ONLY a light access gate (role + WO
  read) before returning the stored result - never the mutation itself.
- Binding mismatch (same key, different user/action/WO/payload) is a hard
  client error; a "Processing" row answers "try again" (defense in depth:
  under this module's no-commit policy the window is crash-only).
- `fn` (access gate + actual action) runs inside the caller's transaction.
  On exception everything propagates and frappe's request rollback wipes
  the ledger row too (10.3) - the key is cleanly retryable (P9b).
- `run_mutation` NEVER commits (10.3); the request wrapper commits once
  after the endpoint returns.
"""

import hashlib
import json
import re

import frappe

from production_app.access import check_wo_access, require_role
from production_app.exceptions import StateChangedError

# All mutating endpoints (10.2); api.py validates `action` against this set.
ACTIONS = frozenset(
	{
		"transfer_material",
		"finish_production",
		"complete_operation",
		"cancel_last_step",
		"cancel_production",
		"close_work_order",
		"save_production_data",
	}
)

PROCESSED = "Done"
PROCESSING = "Processing"

# Ledger rows are named by the key (autoname field:), so keep it DocType-name
# safe: UUIDs (hex + dashes) and similar client-generated tokens pass.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,139}$")


def lock_work_order(wo_name):
	"""Row lock the Work Order (10.1). MUST be the first DB touch of any
	mutation: the ledger check/insert runs under this lock, and state is
	re-read only after it. Returns the WO name (None if it does not exist)."""
	return frappe.db.get_value("Work Order", wo_name, "name", for_update=True)


def _canonicalize(value):
	"""JSON-canonical form of `payload`: dict keys sorted, every number
	normalized to a fixed 9-decimal string (so 10 == 10.0 and 0.1 + 0.2 ==
	0.3), None kept distinct from "" (both serialize differently)."""
	if isinstance(value, bool):
		return value  # before the int check: bool is an int subclass
	if isinstance(value, (int, float)):
		return format(round(float(value), 9), ".9f")
	if isinstance(value, dict):
		return {str(k): _canonicalize(value[k]) for k in sorted(value, key=str)}
	if isinstance(value, (list, tuple)):
		return [_canonicalize(v) for v in value]
	if value is None or isinstance(value, str):
		return value
	return str(value)  # dates etc. - deterministic repr is enough


def payload_fingerprint(payload):
	"""SHA-256 hex of the canonical JSON (10.2 binding component)."""
	canonical = json.dumps(_canonicalize(payload), separators=(",", ":"), sort_keys=True, ensure_ascii=False)
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assert_state(condition, message):
	"""Raise STATE_CHANGED (7.7, 10.1) when the post-lock re-read state does
	not match what the user confirmed. Helper for the Task 13+ endpoints."""
	if not condition:
		raise StateChangedError(message)


def run_mutation(work_order, action, idempotency_key, payload, fn):
	"""Full 10.2 idempotency contract for one mutating endpoint call.

	`fn` performs the access gate + the actual action and returns a
	JSON-serializable dict; it MAY include `reference_doctype`/`reference_doc`
	(stored on the ledger for traceability). Returns the fn result, or on
	replay the stored result with `"duplicate": True`. Never commits (10.3).
	"""
	if isinstance(idempotency_key, str):
		idempotency_key = idempotency_key.strip()  # the trimmed key is what gets bound
	if not _KEY_PATTERN.match(idempotency_key or ""):
		frappe.throw("Idempotency key tidak valid.", frappe.ValidationError)
	if action not in ACTIONS:
		frappe.throw(f"Aksi tidak dikenal: {action}", frappe.ValidationError)
	if not isinstance(payload, dict):
		frappe.throw("Payload harus berupa objek (dict).", frappe.ValidationError)

	# Lock BEFORE reading any state (10.1) - ledger included.
	lock_work_order(work_order)
	fingerprint = payload_fingerprint(payload)

	log = frappe.db.get_value(
		"Production Request Log",
		idempotency_key,
		["user", "action", "work_order", "payload_fingerprint", "status", "result_json"],
		as_dict=True,
	)
	if log is None:
		return _run_first_time(work_order, action, idempotency_key, fingerprint, fn)

	# Same key: ALL four binding components must match (10.2).
	bound = (
		log.user == frappe.session.user
		and log.action == action
		and log.work_order == work_order
		and log.payload_fingerprint == fingerprint
	)
	if not bound:
		frappe.throw("Idempotency key dipakai untuk aksi/payload berbeda.", frappe.ValidationError)
	if log.status == PROCESSING:
		frappe.throw("Permintaan sedang diproses - coba lagi sebentar.", frappe.ValidationError)

	# Done + bound = replay: light re-authorization (10.2) so a leaked key
	# cannot hand out someone else's result; the mutation itself never re-runs.
	try:
		require_role("Production Operator", "Production Supervisor")
		check_wo_access(work_order, "read")
	except frappe.PermissionError:
		frappe.throw("Anda tidak berhak melihat hasil aksi ini.", frappe.ValidationError)

	result = json.loads(log.result_json) if log.result_json else {}
	if not isinstance(result, dict):  # fn contract violation must not break replay
		result = {}
	result["duplicate"] = True
	return result


def _run_first_time(work_order, action, idempotency_key, fingerprint, fn):
	"""Fresh request: open the Processing ledger row, run fn, mark Done.
	No commit anywhere (10.3): if fn raises, the request rollback removes the
	ledger row with the side effects and the key stays retryable (P9b)."""
	frappe.get_doc(
		{
			"doctype": "Production Request Log",
			"idempotency_key": idempotency_key,
			"user": frappe.session.user,
			"action": action,
			"work_order": work_order,
			"payload_fingerprint": fingerprint,
			"status": PROCESSING,
		}
	).insert(ignore_permissions=True)  # internal ledger of an authorized action
	result = fn() or {}
	frappe.db.set_value(
		"Production Request Log",
		idempotency_key,
		{
			"status": PROCESSED,
			"result_json": frappe.as_json(result),
			"reference_doctype": result.get("reference_doctype"),
			"reference_doc": result.get("reference_doc"),
		},
	)
	return result

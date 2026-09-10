"""Cancel target resolution + pre-checks (spec section 12) - Tahap 3.

Contract:
- Fixed type order v1: Manufacture SE -> (Jalur B: Consumption SE) ->
  Transfer SE -> Job Card -> (Work Order).
- Within a type the target is the newest by posting_datetime.
- `expected_target` / `expected_fingerprint` (7.7) compared AFTER the lock and
  re-read: mismatch -> STATE_CHANGED, nothing is cancelled (not even partly).
- Pre-checks block with an Indonesian reason: FG stock (batch-aware,
  get_batch_qty excludes expired) < SE qty; WIP net insufficient to reverse a
  transfer; derived Disassemble entries; reserve_stock; SEs outside the app's
  patterns (Desk returns is_return, is_additional_transfer_entry) are
  detected and BLOCKED, never auto-cancelled.
- Execution via .cancel() (framework checks permission); core reverses stock,
  status, costing (V15); the WO summary is re-synced by the Stock Entry hook
  in the same transaction.
- Supervisor only.
"""


def next_cancel_target(work_order):
	"""First cancelable type with docstatus-1 members for the WO; returns the
	concrete newest target document (or None). Out-of-pattern documents make
	the WO cancel-blocked with a reason."""
	raise NotImplementedError("Tahap 3")


def precheck_cancel(target):
	"""Pre-checks for cancelling one concrete document; return None when clean
	or an Indonesian block reason."""
	raise NotImplementedError("Tahap 3")


def production_fingerprint(work_order):
	"""SHA-256 over the sorted docstatus-1 document list that
	cancel_production would cancel - the `expected_fingerprint` of 7.7."""
	raise NotImplementedError("Tahap 3")

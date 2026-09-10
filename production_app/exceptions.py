"""App-specific validation errors carrying machine-readable codes (spec 7).

The SPA keys its behavior off the code:
- NEEDS_ALLOWANCE: the result exceeds the target AND the site's production
  tolerance; an admin must raise `overproduction_percentage_for_work_order`
  (3.4, open decision #9).
- STATE_CHANGED: the confirmed target/fingerprint no longer matches the
  re-read state; the UI reloads and re-confirms (7.7, 10.1). Nothing was
  mutated.
"""

import frappe


class NeedsAllowanceError(frappe.ValidationError):
	"""Over-production beyond the core allowance gate (spec 3.4)."""

	code = "NEEDS_ALLOWANCE"


class StateChangedError(frappe.ValidationError):
	"""Concurrent mutation: expected target != re-read state (spec 7.7)."""

	code = "STATE_CHANGED"

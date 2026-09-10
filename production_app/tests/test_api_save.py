"""Tests for api.save_production_data (spec 7.3, fields per 8.2).

Contract proven per test:
- happy path through run_mutation: fields saved, session user is modified_by,
  modified timestamp advances, ledger row Done;
- strict whitelist: non-whitelisted and display-only keys are dropped, fields
  absent from meta are skipped (site-owned 8.3);
- type validation: finite >= 0 numbers, Link User must exist, garbage
  rejected;
- editability: Stopped WO accepts metadata, Completed WO rejects it;
- idempotency: replay returns duplicate=True without a second write; a bound
  key with a different payload is rejected; a missing key is rejected.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase

from production_app import api
from production_app.tests import factories

OPERATOR = "pdtc.save.operator@example.com"

# Site-owned 8.2 fields (spec 8.3): installed here like the wo_summary tests
# install the site's summary fields, so the save whitelist can be exercised.
FIELD_TYPES = {
	"custom_adonan_ke": ("Int", None),
	"custom_adonan": ("Data", None),
	"custom_jam_adonan": ("Time", None),
	"custom_suhu_adonan": ("Float", None),
	"custom_nama_penimbang": ("Link", "User"),
	"custom_jam_pembekuan": ("Datetime", None),
	"custom_qc_produksi": ("Link", "User"),
	"custom_jumlah_kru": ("Int", None),
	"custom_leader_produksi": ("Link", "User"),
}


class TestSaveProductionData(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factories.setup_company()
		factories.make_items()
		cls.operator = factories.make_user(OPERATOR, roles=["Production Operator"])
		cls._ensure_metadata_fields()
		cls.wo = factories.make_wo()
		frappe.db.commit()

	@staticmethod
	def _ensure_metadata_fields():
		from frappe.custom.doctype.custom_field.custom_field import create_custom_field

		meta = frappe.get_meta("Work Order")
		for fieldname, (fieldtype, options) in FIELD_TYPES.items():
			if meta.has_field(fieldname):
				continue
			props = {
				"fieldname": fieldname,
				"label": fieldname,
				"fieldtype": fieldtype,
				"insert_after": "project",
			}
			if options:
				props["options"] = options
			create_custom_field("Work Order", props)
		frappe.clear_cache("doctype", "Work Order")

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

	# ------------------------------------------------------------ happy path

	def test_happy_path_saves_fields_and_modified_by(self):
		frappe.set_user(self.operator)
		before = frappe.db.get_value("Work Order", self.wo, ["modified", "modified_by"], as_dict=True)
		payload = {
			"custom_adonan_ke": 3,
			"custom_suhu_adonan": 12.5,
			"custom_adonan": "Adonan pagi",
			"custom_nama_penimbang": self.operator,
		}
		result = api.save_production_data(self.wo, payload, self._key())

		self.assertFalse(result.get("duplicate"))
		self.assertEqual(set(result["saved"]), set(payload))
		saved = frappe.db.get_value(
			"Work Order",
			self.wo,
			["custom_adonan_ke", "custom_suhu_adonan", "custom_adonan", "custom_nama_penimbang"],
			as_dict=True,
		)
		self.assertEqual(
			(
				saved.custom_adonan_ke,
				saved.custom_suhu_adonan,
				saved.custom_adonan,
				saved.custom_nama_penimbang,
			),
			(3, 12.5, "Adonan pagi", self.operator),
		)
		after = frappe.db.get_value("Work Order", self.wo, ["modified", "modified_by"], as_dict=True)
		self.assertEqual(after.modified_by, self.operator)  # audit identity = session
		self.assertNotEqual(after.modified, before.modified)
		self.assertEqual(frappe.db.get_value("Production Request Log", self.keys[-1], "status"), "Done")

	def test_json_string_payload_accepted(self):
		frappe.set_user(self.operator)
		result = api.save_production_data(self.wo, json.dumps({"custom_jumlah_kru": 5}), self._key())
		self.assertEqual(result["saved"], {"custom_jumlah_kru": 5})
		self.assertEqual(frappe.db.get_value("Work Order", self.wo, "custom_jumlah_kru"), 5)

	# -------------------------------------------------------------- whitelist

	def test_non_whitelisted_and_display_fields_dropped(self):
		frappe.set_user(self.operator)
		payload = {"qty": 999, "status": "Completed", "custom_qty_in_uom": 5, "total_operational_cost": 1}
		result = api.save_production_data(self.wo, payload, self._key())
		self.assertEqual(result["saved"], {})
		self.assertEqual(frappe.db.get_value("Work Order", self.wo, ["qty", "status"]), (100, "Not Started"))

	def test_field_absent_from_meta_skipped(self):
		frappe.set_user(self.operator)
		# Simulate a site whose Work Order meta lacks one 8.2 field (8.3):
		# the key must be skipped, not written.
		real_get_meta = frappe.get_meta

		def without_jam_pembekuan(doctype, *args, **kwargs):
			meta = real_get_meta(doctype, *args, **kwargs)
			if doctype == "Work Order":
				real_has_field = meta.has_field
				meta.has_field = lambda f: f != "custom_jam_pembekuan" and real_has_field(f)
			return meta

		from unittest.mock import patch

		with patch("frappe.get_meta", side_effect=without_jam_pembekuan):
			result = api.save_production_data(
				self.wo, {"custom_jam_pembekuan": "2026-01-01 08:00:00"}, self._key()
			)
		self.assertEqual(result["saved"], {})

	# ------------------------------------------------------------ validation

	def test_invalid_link_user_rejected(self):
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as ctx:
			api.save_production_data(self.wo, {"custom_qc_produksi": "tidak-ada@nowhere"}, self._key())
		self.assertIn("tidak ditemukan", str(ctx.exception))

	def test_invalid_numbers_rejected(self):
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError):
			api.save_production_data(self.wo, {"custom_suhu_adonan": "bukan-angka"}, self._key())
		with self.assertRaises(frappe.ValidationError):
			api.save_production_data(self.wo, {"custom_jumlah_kru": -2}, self._key())

	# ------------------------------------------------------------ editability

	def test_stopped_wo_still_editable(self):
		wo = factories.make_wo()  # own WO: status mutation must not leak to the class WO
		frappe.db.set_value("Work Order", wo, "status", "Stopped")
		frappe.set_user(self.operator)
		result = api.save_production_data(wo, {"custom_adonan": "masih boleh"}, self._key())
		self.assertEqual(result["saved"], {"custom_adonan": "masih boleh"})

	def test_completed_wo_rejected(self):
		wo = factories.make_wo()
		frappe.db.set_value("Work Order", wo, "status", "Completed")
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError) as ctx:
			api.save_production_data(wo, {"custom_adonan": "terlambat"}, self._key())
		self.assertIn("sudah Completed", str(ctx.exception))

	# ------------------------------------------------------------ idempotency

	def test_replay_returns_duplicate_without_second_write(self):
		frappe.set_user(self.operator)
		key, payload = self._key(), {"custom_adonan_ke": 7}
		api.save_production_data(self.wo, payload, key)
		modified_after_first = frappe.db.get_value("Work Order", self.wo, "modified")

		replay = api.save_production_data(self.wo, payload, key)
		self.assertTrue(replay["duplicate"])
		self.assertEqual(replay["saved"], {"custom_adonan_ke": 7})
		self.assertEqual(frappe.db.get_value("Work Order", self.wo, "modified"), modified_after_first)

	def test_same_key_different_payload_rejected(self):
		frappe.set_user(self.operator)
		key = self._key()
		api.save_production_data(self.wo, {"custom_adonan_ke": 1}, key)
		with self.assertRaises(frappe.ValidationError) as ctx:
			api.save_production_data(self.wo, {"custom_adonan_ke": 2}, key)
		self.assertIn("berbeda", str(ctx.exception))

	def test_missing_key_rejected(self):
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError):
			api.save_production_data(self.wo, {"custom_adonan_ke": 1}, None)

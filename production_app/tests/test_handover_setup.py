# T22 handover setup — metadata + permission matrix (upgrade.py extensions)
#
# Proves by execution on the installed runtime:
# - production_app.upgrade.apply() is idempotent (run twice, second run changes
#   nothing) and reconciles the pre-existing Manufacturing User Material Request
#   Custom DocPerm down to read/write (task-21-report §3.8 drift);
# - the full T22 permission matrix behaves per HANDOVER_PLAN.md §3:
#   "Gudang Barang Jadi" runs the MR lifecycle (create/submit/cancel) but has
#   read-only reach into Work Order / Batch / Stock Entry and no Stock Entry
#   create; "Manufacturing User" reads/writes MR (incl. allow_on_submit fields
#   on submitted docs) but cannot create/cancel/submit;
# - the 5th warehouse default (`custom_default_handover_warehouse`) persists via
#   the Pengaturan save API with write permission (Manufacturing Manager), the
#   read API stays open, and saving without permission throws.
#
# Every record created here is test-only (users t22.* prefixed, warehouses/items
# "T22 ..." prefixed); the Frappe test framework rolls each run back.

from unittest.mock import MagicMock, patch

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now, random_string

from production_app import hooks, upgrade
from production_app.api.work_order import (
	LIST_FIELDS,
	POSTPACKING_FIELD_MAP,
	PREPACKING_FIELD_MAP,
	PREP_FIELD_MAP,
	warehouse_defaults,
	warehouse_defaults_save,
)

PREFIX = "T22"
HANDOVER_ROLE = "Gudang Barang Jadi"


def _company_and_group():
	name = frappe.db.get_value("Work Order", {"docstatus": 1}, "name", order_by="creation desc")
	company = frappe.db.get_value("Work Order", name, "company")
	parent = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1}, "name")
	return company, parent


def _mr_flags(doctype, role):
	name = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role}, "name")
	if not name:
		return None
	row = frappe.db.get_value(
		"Custom DocPerm", name,
		["read", "write", "create", "submit", "cancel", "amend"], as_dict=True,
	)
	return {k: int(row.get(k) or 0) for k in ("read", "write", "create", "submit", "cancel", "amend")}


def _make_user(local, role=None):
	"""role: satu nama atau list nama — FU64 persona legacy jujur membawa
	pasangan native (mis. ["Gudang Barang Jadi", "Stock User"], hasil migrasi
	ensure_legacy_gudang_stock_user)."""
	suffix = random_string(6).upper()
	user = (
		frappe.get_doc(
			{
				"doctype": "User",
				"email": f"t22.{local}.{suffix.lower()}@prodapp.example.com",
				"first_name": f"T22 {local}",
				"send_welcome_email": 0,
			}
		)
		.insert()
	)
	if role:
		for name in role if isinstance(role, (list, tuple)) else [role]:
			user.append("roles", {"role": name})
	user.save()
	return user.name


class TestHandoverSetup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company, cls.parent_wh = _company_and_group()
		suffix = random_string(6).upper()
		cls.src_wh = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": f"{PREFIX} Source {suffix}",
					"company": cls.company,
					"parent_warehouse": cls.parent_wh,
					"is_group": 0,
				}
			)
			.insert()
			.name
		)
		cls.dst_wh = (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": f"{PREFIX} Handover {suffix}",
					"company": cls.company,
					"parent_warehouse": cls.parent_wh,
					"is_group": 0,
				}
			)
			.insert()
			.name
		)
		cls.item = (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"{PREFIX}-ITEM-{suffix}",
					"item_name": f"{PREFIX} Item {suffix}",
					"item_group": frappe.db.get_value("Item Group", {}, "name"),
					"stock_uom": frappe.db.get_value(
						"Work Order", {"docstatus": 1}, "stock_uom", order_by="creation desc"
					),
					"is_stock_item": 1,
					"is_purchase_item": 0,
					"is_sales_item": 0,
					"is_fixed_asset": 0,
				}
			)
			.insert()
			.name
		)

	@classmethod
	def tearDownClass(cls):
		"""The apply() idempotency test commits mid-class (by design — metadata),
		which persists the class fixtures past the framework rollback. Purge the
		T22 leftovers explicitly (they carry no ledger entries)."""
		frappe.db.rollback()  # discard uncommitted per-test data (users, MRs)
		frappe.set_user("Administrator")
		for doctype, field, pattern in (
			("Warehouse", "warehouse_name", f"{PREFIX} %"),
			("Item", "item_code", f"{PREFIX}-%"),
		):
			for name in frappe.get_all(doctype, filters={field: ("like", pattern)}, pluck="name"):
				frappe.delete_doc(doctype, name, force=True)
		frappe.db.commit()
		super().tearDownClass()

	# ------------------------------------------------------------- fixtures

	def _make_mr(self, qty=10):
		mr = frappe.get_doc(
			{
				"doctype": "Material Request",
				"material_request_type": "Material Transfer",
				"company": self.company,
				"transaction_date": now(),
				"schedule_date": add_days(now(), 1),
				"set_from_warehouse": self.src_wh,
				"set_warehouse": self.dst_wh,
				"items": [
					{
						"item_code": self.item,
						"qty": qty,
						"uom": frappe.db.get_value("Item", self.item, "stock_uom"),
						"from_warehouse": self.src_wh,
						"warehouse": self.dst_wh,
						"schedule_date": add_days(now(), 1),
					}
				],
			}
		)
		mr.insert()
		mr.submit()
		return mr

	# ------------------------------------------------------- idempotency

	def test_cloud_fresh_install_contract_is_self_contained(self):
		required_wo = {
			fieldname
			for fieldname in (
				*LIST_FIELDS,
				*PREP_FIELD_MAP.values(),
				*PREPACKING_FIELD_MAP.values(),
				*POSTPACKING_FIELD_MAP.values(),
			)
			if fieldname.startswith("custom_")
		}
		migrated_wo = {spec["fieldname"] for spec in upgrade.WORKSPACE_FIELDS}
		self.assertEqual(required_wo - migrated_wo, set())
		required_layout = {
			"custom_item_name_information",
			"custom_column_break_fdsxk",
			"custom_detail_produksi",
			"custom_sebelum",
			"custom_column_break_khnwb",
			"custom_section_break_b0phj",
			"custom_column_break_8rt2c",
			"custom_detail_produksi_lain",
		}
		self.assertEqual(required_layout - migrated_wo, set())

		# 29 Sep: custom_default_uom_warehouse dipensiunkan dari spec (digantikan
		# custom_default_inventory_unit_of_measure milik warehouse_app, W21) —
		# yang dijamin spec ini tinggal rantai gudang.
		required_item = {
			"custom_default_source_warehouse",
			"custom_default_wip_warehouse",
			"custom_default_fg_warehouse",
		}
		migrated_item = {spec["fieldname"] for spec in upgrade.ITEM_FIELDS}
		self.assertEqual(required_item - migrated_item, set())
		self.assertNotIn("custom_default_uom_warehouse", migrated_item)
		self.assertEqual(hooks.required_apps, ["erpnext"])
		self.assertEqual(hooks.after_install, "production_app.upgrade.apply")

		upgrade.apply()
		wo_meta = frappe.get_meta("Work Order", cached=False)
		item_meta = frappe.get_meta("Item", cached=False)
		self.assertTrue(all(wo_meta.has_field(fieldname) for fieldname in required_wo))
		self.assertTrue(all(item_meta.has_field(fieldname) for fieldname in required_item))

	def test_cloud_workspace_creation_has_no_missing_parent_link(self):
		doc = MagicMock()
		doc.parent_page = ""
		with (
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(frappe, "get_doc", return_value=doc),
		):
			upgrade.ensure_workspace()
		self.assertFalse(doc.parent_page)

	def test_t22_apply_idempotent_and_drift_reconciled(self):
		"""apply() twice: no error; the second run reports every handover step
		'unchanged' (incl. retired_box_fields — FU96); the Manufacturing User
		MR row runs the full FO lifecycle with delete; MR Item has NO custom
		rows (FU64 — child table is parent-governed)."""
		r1 = upgrade.apply()
		r2 = upgrade.apply()
		for key in ("handover_mr_fields", "docperm_matrix", "warehouse_default_fields"):
			entries = r2[key].values() if isinstance(r2[key], dict) else r2[key]
			self.assertTrue(
				all(entry.endswith(": unchanged") for entry in entries),
				f"{key} not idempotent: {r2[key]}",
			)
		# FU96: box retirement converges — second apply neither deletes nor
		# re-anchors anything again
		self.assertEqual(r2["retired_box_fields"], "unchanged")
		# FU97: drop kolom arsip juga konvergen — apply ke-2 tak menyentuh DDL
		self.assertEqual(r2["dropped_box_columns"], "unchanged")
		# FU64: retirement konvergen — apply ke-2 tidak menghapus apa pun lagi
		self.assertEqual(r2["retired_docperms"], [])
		# FU64: kelima doctype retired benar-benar bersih dari Custom DocPerm
		for doctype in upgrade.RETIRED_DOCPERM_DOCTYPES:
			self.assertEqual(
				frappe.db.count("Custom DocPerm", {"parent": doctype}),
				0,
				f"{doctype} must have no custom DocPerm rows",
			)
		# FO 2026-09-18 (Form Order): Manufacturing User kini menjalankan siklus
		# MR penuh (create/submit/cancel) — ruling T22 lama (read/write saja)
		# digantikan; before-state tersimpan di form-order-pre.json.
		mfg = _mr_flags("Material Request", "Manufacturing User")
		self.assertEqual(
			mfg, {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 0}
		)
		self.assertTrue(frappe.db.exists("Role", HANDOVER_ROLE))
		# 5th + 6th warehouse default fields exist on Manufacturing Settings
		self.assertTrue(
			frappe.get_meta("Manufacturing Settings").has_field("custom_default_handover_warehouse")
		)
		self.assertTrue(
			frappe.get_meta("Manufacturing Settings").has_field(
				"custom_default_handover_source_warehouse"
			)
		)
		# and the full matrix landed at the DocPerm level
		self.assertEqual(
			_mr_flags("Material Request", HANDOVER_ROLE),
			{"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1},
		)
		# FU64: MR Item (child table) TANPA Custom DocPerm — has_child_permission
		# mengabaikan perm child; akses sepenuhnya parent-governed. Stock Entry
		# juga retired — set native 4 role yang berlaku.
		self.assertIsNone(_mr_flags("Material Request Item", HANDOVER_ROLE))
		self.assertIsNone(_mr_flags("Material Request Item", "Manufacturing User"))
		self.assertIsNone(_mr_flags("Stock Entry", HANDOVER_ROLE))
		# FU96 + FU97: Box 1..3 (kg + jumlah) DIPENSIUNKAN TOTAL — definisi
		# Custom Field DAN kolom DB-nya sudah hilang dari Work Order maupun
		# Material Request (permintaan user "data lama hapus aja, karna nanti
		# bener2 fresh"; report warehouse_app W38 berhenti membacanya dulu).
		wo_meta = frappe.get_meta("Work Order", cached=False)
		mr_meta = frappe.get_meta("Material Request", cached=False)
		for fieldname in (
			"custom_box_1", "custom_box_1_qty", "custom_box_2", "custom_box_2_qty",
			"custom_box_3", "custom_box_3_qty",
		):
			self.assertIsNone(
				frappe.db.exists("Custom Field", {"dt": "Work Order", "fieldname": fieldname}),
				f"Work Order.{fieldname} harus terhapus (FU96)",
			)
			self.assertFalse(
				frappe.db.has_column("Work Order", fieldname),
				f"kolom Work Order.{fieldname} harus sudah DIHAPUS (FU97)",
			)
		for fieldname in ("custom_box_1", "custom_box_2"):
			self.assertIsNone(
				frappe.db.exists("Custom Field", {"dt": "Material Request", "fieldname": fieldname}),
				f"Material Request.{fieldname} harus terhapus (FU96)",
			)
			self.assertFalse(
				frappe.db.has_column("Material Request", fieldname),
				f"kolom Material Request.{fieldname} harus sudah DIHAPUS (FU97)",
			)
		# T35 (narrowed FU96): tiga-lane handover metadata — Link saja; TIDAK
		# ada lagi field count box
		expected = {
			"custom_handover_material_request": ("Link", "Material Request"),
		}
		for fieldname, (fieldtype, options) in expected.items():
			df = wo_meta.get_field(fieldname)
			self.assertIsNotNone(df)
			self.assertEqual(df.fieldtype, fieldtype)
			self.assertEqual(df.options or None, options)
			self.assertTrue(df.allow_on_submit)
			self.assertTrue(df.read_only)
		# Link field tidak menggantung: anchor harus field yang masih ada
		link_cf = frappe.db.get_value(
			"Custom Field",
			{"dt": "Work Order", "fieldname": upgrade.THREE_LANE_LINK_FIELD},
			["insert_after"],
			as_dict=True,
		)
		self.assertTrue(
			frappe.get_meta("Work Order", cached=False).get_field(link_cf.insert_after),
			f"anchor {link_cf.insert_after} harus field yang ada",
		)

		self.assertEqual(
			wo_meta.get_field("custom_handover_status").options,
			"\nDiminta Gudang\nTerkirim",
		)
		# the migration converges: the second apply reports every three-lane
		# step unchanged and never rewrites correct Links/values
		entries = (
			r2["three_lane_handover"].values()
			if isinstance(r2["three_lane_handover"], dict)
			else [r2["three_lane_handover"]]
		)
		self.assertTrue(
			all(str(entry).endswith(": unchanged") for entry in entries),
			f"three_lane_handover not idempotent: {r2['three_lane_handover']}",
		)
		# snapshot-first: the evidence must agree with its own data — the OLD
		# "Siap Kirim" option is required ONLY while the stored status values
		# prove pre-cutover data; a fresh-install capture holds the current
		# narrowed options/contract instead (it never saw the old option).
		with open(upgrade.THREE_LANE_SNAPSHOT) as f:
			snap = json.load(f)
		# snapshot historis (pre-FU96) boleh memuat kunci box (T39/T31); capture
		# baru hanya link+status. Yang diuji: key set ⊆ kandidat yang dikenal.
		known = {
			"custom_handover_status",
			upgrade.THREE_LANE_LINK_FIELD,
			"custom_box_1", "custom_box_1_pack", "custom_box_1_qty",
			"custom_box_2", "custom_box_2_pack", "custom_box_2_qty",
			"custom_box_3", "custom_box_3_qty",
		}
		self.assertLessEqual(set(snap["stored_values"]), known)
		self.assertIn("custom_handover_status", snap["stored_values"])
		self.assertIn(upgrade.THREE_LANE_LINK_FIELD, snap["stored_values"])
		status_fields = [
			cf for cf in snap["custom_fields"] if cf["fieldname"] == "custom_handover_status"
		]
		stored_status = snap["stored_values"]["custom_handover_status"]
		if upgrade.RETIRED_STATUS_VALUE in stored_status:
			# live-site pre-cutover evidence: old options present, and ONLY
			# values the old options allowed
			self.assertTrue(status_fields, "snapshot missed custom_handover_status")
			self.assertIn(upgrade.RETIRED_STATUS_VALUE, status_fields[0].get("options") or "")
			self.assertLessEqual(
				set(stored_status),
				{"Diminta Gudang", upgrade.RETIRED_STATUS_VALUE, "Terkirim"},
			)
		else:
			# fresh-install evidence: no retired value anywhere; a captured
			# definition already carries the narrowed options
			self.assertNotIn(upgrade.RETIRED_STATUS_VALUE, stored_status)
			if status_fields:
				self.assertEqual(
					status_fields[0].get("options"), "\nDiminta Gudang\nTerkirim"
				)
		for fieldname in ("custom_handover_status", upgrade.THREE_LANE_LINK_FIELD):
			self.assertIsInstance(snap["stored_values"][fieldname], dict)

	# ------------------------------------------------ permission: gudang

	def test_t22_gudang_runs_mr_lifecycle_and_can_fulfill_se(self):
		"""Persona gudang pasca-FU64 (legacy + Stock User — hasil migrasi
		ensure_legacy_gudang_stock_user): MR create/submit/cancel; Stock Entry
		create/submit (native SU — FO fulfill); Work Order/Batch/Item/Warehouse
		read (native + matrix); Work Order write denied."""
		gudang = _make_user("gudang", [HANDOVER_ROLE, "Stock User"])

		self.assertTrue(frappe.has_permission("Material Request", "create", user=gudang))
		self.assertTrue(frappe.has_permission("Material Request", "submit", user=gudang))
		self.assertTrue(frappe.has_permission("Material Request", "cancel", user=gudang))
		# child-table checks resolve via parent_doctype (frappe.permissions
		# has_child_permission); the MR Item DocPerm rows themselves are
		# asserted at DB level in the idempotency test
		self.assertTrue(
			frappe.has_permission(
				"Material Request Item", "read", parent_doctype="Material Request", user=gudang
			)
		)
		self.assertTrue(
			frappe.has_permission(
				"Material Request Item", "create", parent_doctype="Material Request", user=gudang
			)
		)
		for doctype in ("Work Order", "Batch", "Stock Entry", "Item", "Warehouse"):
			self.assertTrue(
				frappe.has_permission(doctype, "read", user=gudang), f"{doctype} read"
			)
		# FO 2026-09-18: gudang memproses Form Order (SE create/submit/cancel)
		self.assertTrue(frappe.has_permission("Stock Entry", "create", user=gudang))
		self.assertTrue(frappe.has_permission("Stock Entry", "submit", user=gudang))
		self.assertFalse(frappe.has_permission("Work Order", "write", user=gudang))

		frappe.set_user(gudang)
		try:
			mr = self._make_mr(10)  # create + submit
			self.assertEqual(mr.docstatus, 1)
			frappe.get_doc("Material Request", mr.name).cancel()  # no sends yet
			self.assertEqual(frappe.db.get_value("Material Request", mr.name, "docstatus"), 2)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------- permission: prod user

	def test_t22_prod_user_runs_mr_lifecycle_fo(self):
		"""Manufacturing User: MR read/write + create/submit/cancel (FO
		2026-09-18 — Form Order; dulu read/write saja); MR Item read+create."""
		prod = _make_user("prod", "Manufacturing User")
		self.assertTrue(frappe.has_permission("Material Request", "create", user=prod))
		self.assertTrue(frappe.has_permission("Material Request", "cancel", user=prod))
		self.assertTrue(frappe.has_permission("Material Request", "submit", user=prod))
		self.assertTrue(frappe.has_permission("Material Request", "read", user=prod))
		self.assertTrue(frappe.has_permission("Material Request", "write", user=prod))
		self.assertTrue(
			frappe.has_permission(
				"Material Request Item", "read", parent_doctype="Material Request", user=prod
			)
		)
		self.assertTrue(
			frappe.has_permission(
				"Material Request Item", "create", parent_doctype="Material Request", user=prod
			)
		)

		frappe.set_user(prod)
		try:
			mr = self._make_mr(5)  # FO: create + submit kini diizinkan
			self.assertEqual(mr.docstatus, 1)
			# allow_on_submit write path tetap: db_set pada field yang diizinkan
			doc = frappe.get_doc("Material Request", mr.name)
			doc.db_set("custom_good_qty_postpacking", 3.5)
			doc.db_set("custom_postpacking_confirmed", 1)
			doc.reload()
			self.assertEqual(doc.custom_good_qty_postpacking, 3.5)
			self.assertEqual(doc.custom_postpacking_confirmed, 1)
			doc.cancel()  # cancel perm kini ada (FO); owner-scope diterapkan API
			self.assertEqual(frappe.db.get_value("Material Request", mr.name, "docstatus"), 2)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------- permission: bare user

	def test_t22_bare_user_cannot_read_mr(self):
		"""A user with no roles has no Material Request access at all."""
		bare = _make_user("bare")
		self.assertFalse(frappe.has_permission("Material Request", "read", user=bare))
		frappe.set_user(bare)
		try:
			with self.assertRaises(frappe.PermissionError):
				self._make_mr(1)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------- 5th warehouse default (API)

	def test_t22_handover_warehouse_setting_via_api(self):
		"""warehouse_defaults_save persists custom_default_handover_warehouse for
		a Manufacturing Settings writer; plain user save throws; read is open."""
		if not frappe.db.exists("Role", "Manufacturing Manager"):
			self.skipTest("no Manufacturing Manager role on site")
		manager = _make_user("manager", "Manufacturing Manager")

		self.assertIn("handover_warehouse", warehouse_defaults())  # read open

		frappe.set_user(manager)
		try:
			saved = warehouse_defaults_save(handover_warehouse=self.dst_wh)
			self.assertEqual(saved["handover_warehouse"], self.dst_wh)
			self.assertEqual(
				frappe.db.get_single_value("Manufacturing Settings", "custom_default_handover_warehouse"),
				self.dst_wh,
			)
		finally:
			frappe.set_user("Administrator")

		bare = _make_user("bare2")
		frappe.set_user(bare)
		try:
			with self.assertRaises(frappe.PermissionError):
				warehouse_defaults_save(handover_warehouse=self.dst_wh)
		finally:
			frappe.set_user("Administrator")

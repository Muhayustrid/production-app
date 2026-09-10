"""Test data factory for production_app (pytest-style).

Adapted from docs/proofs/scripts/proof_lib.py (Phase 1 proof recipes).
All objects are PDTC-prefixed so leftovers are identifiable; every setup
function is idempotent (frappe IntegrationTestCase commits setUpClass data
and only rolls back at class end).
"""

import frappe

COMPANY = "PDTC Co"
ABBR = "PDTC"
STORES = "Stores - PDTC"
WIP = "Work In Progress - PDTC"
FG_WH = "Finished Goods - PDTC"
RM1, RM2, FG = "PDTC-RM1", "PDTC-RM2", "PDTC-FG"
BATCH_RM1 = "PDTC-B-RM1"
BATCH_FG = "PDTC-B-FG"
ITEM_GROUP = "PDTC Items"
SECOND_COMPANY = "PDTC Second Co"
SECOND_ABBR = "PDTC2"
WORKSTATION = "PDTC Workstation"
OPERATION = "PDTC Assembly"


def setup_company():
	"""Company PDTC Co with standard warehouses, WIP/FG defaults, perpetual
	inventory accounts and an active fiscal year (bare-site prerequisites)."""
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 0)
	# required by Serial and Batch Bundle validation (v16 setting)
	frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc(
			{"doctype": "Warehouse Type", "__newname": "Transit", "warehouse_name": "Transit"}
		).insert()
	for name in (
		"Material Receipt",
		"Material Transfer",
		"Material Transfer for Manufacture",
		"Material Consumption for Manufacture",
		"Manufacture",
	):
		if not frappe.db.exists("Stock Entry Type", name):
			frappe.get_doc(
				{"doctype": "Stock Entry Type", "__newname": name, "purpose": name, "is_standard": 1}
			).insert()
	if frappe.db.exists("Company", COMPANY):
		return COMPANY
	frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": COMPANY,
			"abbr": ABBR,
			"default_currency": "USD",
			"country": "United States",
		}
	).insert()
	cc = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 0})
	if not cc:
		root_cc = frappe.db.get_value(
			"Cost Center", {"company": COMPANY, "parent_cost_center": ("is", "not set")}
		)
		cc = (
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": "Main",
					"company": COMPANY,
					"parent_cost_center": root_cc,
					"is_group": 0,
				}
			)
			.insert()
			.name
		)
	frappe.db.set_value(
		"Company",
		COMPANY,
		{
			"default_wip_warehouse": WIP,
			"default_fg_warehouse": FG_WH,
			"cost_center": cc,
		},
	)
	root_inv = frappe.db.get_value(
		"Account", {"company": COMPANY, "account_name": "Stock Assets", "is_group": 1}
	)
	for wh, acct_name in ((STORES, "Stores Stock"), (WIP, "WIP Stock"), (FG_WH, "Finished Goods Stock")):
		acct = f"{acct_name} - {ABBR}"
		if not frappe.db.exists("Account", acct):
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": acct_name,
					"account_type": "Stock",
					"parent_account": root_inv,
					"company": COMPANY,
					"account_currency": "USD",
				}
			).insert()
		frappe.db.set_value("Warehouse", wh, "account", acct)
	frappe.db.set_value(
		"Company",
		COMPANY,
		{
			"enable_perpetual_inventory": 1,
			"default_inventory_account": f"Stores Stock - {ABBR}",
		},
	)
	from frappe.utils import get_year_ending, get_year_start, getdate, today

	year = str(getdate(today()).year)
	if not frappe.db.exists("Fiscal Year", year):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": year,
				"year_start_date": get_year_start(today()),
				"year_end_date": get_year_ending(today()),
				"companies": [{"company": COMPANY}],
			}
		).insert()
	elif not frappe.db.exists("Fiscal Year Company", {"parent": year, "company": COMPANY}):
		# Phase-1 proof leftovers: companies deleted but their FY child rows
		# remain; saving the FY would fail link validation on those orphans.
		frappe.db.sql(
			"delete from `tabFiscal Year Company` where parenttype='Fiscal Year' and company not in (select name from tabCompany)"
		)
		fy = frappe.get_doc("Fiscal Year", year)
		fy.append("companies", {"company": COMPANY})
		fy.save()
	return COMPANY


def make_items():
	"""PDTC-RM1 (batched), PDTC-RM2 (unbatched), PDTC-FG (batched); UOM Nos."""
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": ITEM_GROUP, "is_group": 1}).insert()
	if not frappe.db.exists("UOM", "Nos"):
		frappe.get_doc({"doctype": "UOM", "uom_name": "Nos", "must_be_whole_number": 0}).insert()
	else:
		frappe.db.set_value("UOM", "Nos", "must_be_whole_number", 0)
	for code, batched in ((RM1, 1), (RM2, 0), (FG, 1)):
		if frappe.db.exists("Item", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": ITEM_GROUP,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"has_batch_no": batched,
			}
		).insert()


def stock_in(item, warehouse, qty, rate, batch_no=None):
	"""Submitted Material Receipt with explicit basic_rate (deterministic valuation)."""
	if batch_no:
		_ensure_batch(item, batch_no)
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"purpose": "Material Receipt",
			"company": COMPANY,
			"items": [
				{
					"item_code": item,
					"t_warehouse": warehouse,
					"qty": qty,
					"basic_rate": rate,
					"use_serial_batch_fields": 1 if batch_no else 0,
					"batch_no": batch_no,
				}
			],
		}
	)
	se.insert()
	se.submit()
	return se


def make_bom():
	"""1-level BOM: FG 100 Nos = RM1 10 + RM2 2 (the spec 3.3 recipe)."""
	name = frappe.db.get_value("BOM", {"item": FG, "docstatus": ("<", 2)})
	if name:
		return name
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": FG,
			"company": COMPANY,
			"quantity": 100,
			"uom": "Nos",
			"currency": "USD",
			"is_active": 1,
			"is_default": 1,
			"items": [
				{"item_code": RM1, "qty": 10, "uom": "Nos"},
				{"item_code": RM2, "qty": 2, "uom": "Nos"},
			],
		}
	).insert()
	bom.submit()
	return bom.name


def make_wo(qty=100):
	"""Draft + submit Work Order: source=Stores, wip=WIP, fg=Finished Goods."""
	make_bom()
	wo = frappe.get_doc(
		{
			"doctype": "Work Order",
			"naming_series": "PDTC-WO-.####",
			"company": COMPANY,
			"production_item": FG,
			"bom_no": frappe.db.get_value("BOM", {"item": FG, "docstatus": 1}),
			"qty": qty,
			"stock_uom": "Nos",
			"wip_warehouse": WIP,
			"fg_warehouse": FG_WH,
			"source_warehouse": STORES,
		}
	)
	wo.insert()
	wo.submit()
	return wo.name


def se_transfer(wo, materials=None, qty=None):
	"""Material Transfer for Manufacture (Stores -> WIP); materials={item: qty}
	overrides row quantities; qty claims WO coverage (fg_completed_qty)."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	w = frappe.get_doc("Work Order", wo)
	se = frappe.get_doc(make_stock_entry(w.name, "Material Transfer for Manufacture", qty=qty))
	for row in se.items:
		if materials and row.item_code in materials:
			row.qty = row.transfer_qty = materials[row.item_code]
		if _has_batch(row.item_code):
			row.use_serial_batch_fields = 1
			row.batch_no = row.batch_no or _pick_batch(row.item_code, row.s_warehouse)
	se.insert()
	se.submit()
	return se


def se_manufacture(wo, good, loss=0, materials=None, packing=None):
	"""Manufacture SE: FG row qty=good, process_loss_qty=loss; materials
	overrides raw-material rows; packing={custom_p_* fieldname: value} marks an
	app-style session (None = Desk entry without the app fields)."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	w = frappe.get_doc("Work Order", wo)
	se = frappe.get_doc(make_stock_entry(w.name, "Manufacture", qty=good))
	se.process_loss_qty = loss
	for row in se.items:
		if row.item_code == w.production_item:
			row.qty = row.transfer_qty = good
			if _has_batch(row.item_code):
				row.use_serial_batch_fields = 1
				row.batch_no = _ensure_batch(row.item_code, BATCH_FG)
		elif materials and row.item_code in materials:
			row.qty = row.transfer_qty = materials[row.item_code]
	for fieldname, value in (packing or {}).items():
		se.set(fieldname, value)
	se.insert()
	se.submit()
	return se


def _has_batch(item):
	return frappe.db.get_value("Item", item, "has_batch_no")


def _ensure_batch(item, batch_id):
	if not frappe.db.exists("Batch", batch_id):
		frappe.get_doc({"doctype": "Batch", "batch_id": batch_id, "item": item}).insert()
	return batch_id


def _pick_batch(item, warehouse):
	"""Batch with positive stock at the warehouse (v16: qty lives in Serial
	and Batch Bundle entries)."""
	bundles = frappe.get_all(
		"Serial and Batch Bundle",
		filters={"docstatus": 1, "is_cancelled": 0, "item_code": item, "warehouse": warehouse},
		pluck="name",
	)
	if not bundles:
		return None
	rows = frappe.get_all(
		"Serial and Batch Entry",
		filters={"parent": ("in", bundles), "parenttype": "Serial and Batch Bundle", "qty": (">", 0)},
		fields=["batch_no", "qty"],
	)
	if not rows:
		return None
	totals = {}
	for r in rows:
		totals[r.batch_no] = totals.get(r.batch_no, 0) + r.qty
	return max(totals, key=totals.get)


def make_user(email, roles=()):
	"""Idempotent enabled User with the given roles (access tests)."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert()
	return email


def make_user_permission(user, allow, for_value):
	"""Idempotent User Permission (11.2); returns its name for cleanup."""
	name = frappe.db.get_value("User Permission", {"user": user, "allow": allow, "for_value": for_value})
	if name:
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": allow,
				"for_value": for_value,
				"apply_to_all_doctypes": 1,
			}
		)
		.insert()
		.name
	)


def setup_second_company():
	"""Bare second Company for User Permission tests (11.2 [T] V23); only the
	Company record itself is needed."""
	if not frappe.db.exists("Company", SECOND_COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": SECOND_COMPANY,
				"abbr": SECOND_ABBR,
				"default_currency": "USD",
				"country": "United States",
			}
		).insert()
	return SECOND_COMPANY


def setup_operation():
	"""Workstation + Operation so a Work Order Operation row (operation loss)
	can be attached to a Work Order in tests (6.7 pre-check)."""
	if not frappe.db.exists("Workstation", WORKSTATION):
		frappe.get_doc(
			{"doctype": "Workstation", "workstation_name": WORKSTATION, "production_capacity": 1}
		).insert()
	if not frappe.db.exists("Operation", OPERATION):
		frappe.get_doc(
			{
				"doctype": "Operation",
				"__newname": OPERATION,
				"operation_name": OPERATION,
				"workstation": WORKSTATION,
			}
		).insert()


def add_wo_operation(wo, process_loss_qty):
	"""Attach an operation row carrying booked loss to a SUBMITTED Work Order.
	Raw insert: the submitted parent must not be re-saved/re-validated; only
	name columns the 6.7 pre-check query reads are populated."""
	frappe.db.sql(
		"""insert into `tabWork Order Operation`
			(name, parent, parentfield, parenttype, owner, modified_by, creation, modified,
			 operation, time_in_mins, completed_qty, process_loss_qty, docstatus, idx)
			values (%s, %s, 'operations', 'Work Order', 'Administrator', 'Administrator', now(), now(),
			 %s, 60, 0, %s, 1, 1)""",
		(f"PDTC-OP-{frappe.generate_hash(length=8)}", wo, OPERATION, process_loss_qty),
	)

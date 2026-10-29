# Serah Terima (handover) board — read API (T23).
#
# SERVER-DERIVED truth (HANDOVER_PLAN §4.1): every lane, quantity and flag is
# recomputed from current MR/SE/batch documents on each call; the UI never
# writes state. T24 mutations reuse _build_board() as their refresh response;
# T25 consumes the payload documented in
# .superpowers/sdd/HANDOVER_PLAN/task-23-report.md.
#
# - MR.transfer_status is never read (not maintained by the MR->SE flow, T21).
# - Permission-filtered per session user, no ignore_permissions: without
#   Work Order / Material Request read the board is empty, not an error (§4.8).
# - No hardcoded warehouses: the lot warehouse is the WO's Manufacture SE
#   finished-row t_warehouse (WO fg_warehouse fallback); the send target comes
#   from Manufacturing Settings custom_default_handover_warehouse (§4.10).
# - T31 (ruling R2): the batchless pool source and new MRs' from_warehouse come
#   from Manufacturing Settings custom_default_handover_source_warehouse when
#   set, else the SE-derived lot warehouse; batch-tracked lots stay SE-derived.
#   Requests carry the Work Order's FULL produced_qty (R3); send moves the MR's
#   requested qty and never stops the MR (R6).
# - T35 three-lane cutover: TWO lanes derive from native documents only —
#   request (submitted MR without SE evidence) and terkirim (submitted Stock
#   Entry evidence, which outranks even an abnormally cancelled MR). The
#   retired postpacking confirmation advances nothing. Box kg + whole count
#   allocations live on the Work Order summary (Link + 4 fields), written
#   atomically by create_request behind the WO lock; the MR stays a pure
#   request document. T39: the count unit is UNIVERSAL — the item's warehouse
#   display UOM (the stock UOM itself at exact factor 1, or any alternate
#   display UOM with a valid conversion row). Count math uses the RAW
#   _enrich_units factor — never the `or 1` display fallback.

from collections import defaultdict

import functools

import hashlib

import json

import math

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_link_to_form, now

from erpnext.stock.doctype.batch.batch import get_batch_qty
from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
	get_available_batches,
	get_stock_ledgers_batches,
	update_available_batches,
)

from production_app.api.work_order import (
	_enrich_units,
)

# Sisi gudang serah terima: role legacy "Gudang Barang Jadi" ATAU pasangan
# native Stock User/Stock Manager (keputusan user 2026-09-14; FU64 2026-09-29
# gudang resmi pindah ke role native — Stock Manager diterima di SEMUA gate;
# dulu tidak, sehingga create/cancel request & fulfill Form Order ditolak
# untuk pemegang SM). Data access mereka lewat hak native + matrix upgrade.
ROLE_GUDANG = "Gudang Barang Jadi"
ROLES_GUDANG = ("Gudang Barang Jadi", "Stock User", "Stock Manager")
ROLE_PRODUKSI = "Manufacturing User"
# FO 2026-09-18: flag terpisah untuk Manufacturing Manager — is_produksi TIDAK
# dilebarkan (isGudangOnly/landing & aksi kirim di UI tidak berubah); menu Form
# Order tampil untuk produksi ATAU manager, guard server tetang otoritatif.
ROLE_MANAJER_PRODUKSI = "Manufacturing Manager"

LANE_REQUEST = "request"
LANE_KIRIM = "terkirim"


def _time_str(value):
    """Zero-padded HH:MM:SS for DB Time values (arrive as timedelta; str()
    renders single-digit hours, which would mis-sort FIFO across hours)."""
    if hasattr(value, "total_seconds"):
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return str(value)


@frappe.whitelist()
def handover_board(company=None):
    """Three-lane Serah Terima board (Cold Storage lots -> Request Gudang ->
    Terkirim) for the session user. FU95: `company` opsional — filter company
    global halaman workspace (lot mengikuti company WO, request company MR)."""
    return _build_board(company)


def _build_board(company=None):
    """Board payload; T24 actions return this as the refreshed board.
    FU95: company None = papan penuh (perilaku lama — kompatibel)."""
    wo_rows = _wo_lot_rows(company=company)
    requests = _requests(wo_rows, company=company)
    return {
        "target_warehouse": _target_warehouse(),
        "source_warehouse": _source_warehouse(),
        "roles": _roles(),
        "lots": _lots(wo_rows, requests),
        "requests": requests,
    }


def _target_warehouse(company=None):
	return (
		frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_warehouse"
		)
		or None
	)


def _source_warehouse():
	"""T31 (R2): gudang asal serah terima. Empty -> None; every caller falls
	back to the SE-derived lot warehouse (the board never hard-fails)."""
	return (
		frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_source_warehouse"
		)
		or None
	)


def _pool_warehouse(lot_row):
    """The batchless pool source: the source setting overrides the SE-derived
    lot warehouse; when unset the fallback keeps current behavior (R2).
    FU61: gate company dipensiunkan — setting berlaku langsung."""
    return _source_warehouse() or lot_row.warehouse


def _roles():
    roles = frappe.get_roles()
    return {
        "is_gudang": any(r in roles for r in ROLES_GUDANG),
        "is_produksi": ROLE_PRODUKSI in roles,
        "is_manajer_produksi": ROLE_MANAJER_PRODUKSI in roles,
        # FU64: kapabilitas, bukan nama role — menu Pengaturan mengikuti
        # izin write Manufacturing Settings yang sama yang di-cek server
        # saat simpan (native: Manufacturing Manager).
        "can_settings": frappe.has_permission("Manufacturing Settings", "write"),
    }


def _batch_quantities(requirements):
	"""Physical batch quantity by (batch, warehouse), preserving the old
	get_batch_qty(batch, warehouse) semantics without its per-lot queries."""
	requirements = {
		(item_code, batch_no, warehouse)
		for item_code, batch_no, warehouse in requirements
		if item_code and batch_no and warehouse
	}
	if not requirements:
		return defaultdict(float)

	kwargs = frappe._dict(
		item_code=sorted({item_code for item_code, _batch, _warehouse in requirements}),
		batch_no=sorted({batch_no for _item, batch_no, _warehouse in requirements}),
		warehouse=sorted({warehouse for _item, _batch, warehouse in requirements}),
		based_on=frappe.get_single_value("Stock Settings", "pick_serial_and_batch_based_on"),
		for_stock_levels=False,
		consider_negative_batches=False,
	)
	batches = get_available_batches(kwargs)
	update_available_batches(batches, get_stock_ledgers_batches(kwargs))

	wanted = {(batch_no, warehouse) for _item, batch_no, warehouse in requirements}
	quantities = defaultdict(float)
	for row in batches:
		key = (row.batch_no, row.warehouse)
		if key in wanted and flt(row.qty) > 0:
			quantities[key] += flt(row.qty)
	return quantities


def _wo_lot_rows(wo_names=None, company=None):
	"""One lot row per Work Order that has Manufacture history, enriched with
	the shared qtyInPack logic (_enrich_units) and item display names.

	Lot identity (§3): the FG batch of the WO's single Manufacture SE in that
	SE's finished-item warehouse; entered_at = the SE posting datetime (FIFO).
	A WO with multiple Manufacture SEs / batches (legacy partial history) gets
	an explicit unsupported card instead of an error or silent flattening
	(§4.9). Follow-up 8: an FG item WITHOUT batch tracking yields a BATCHLESS
	lot (batch=None) — all its WOs share one item-level stock pool (see
	_lots), and multiple Manufactures are harmless. Numeric lot fields stay
	None until _lots() applies the reservation. T31 (R7): produced_qty is the
	WO's finished-goods total and completed_at the LATEST Manufacture posting
	(rows iterate ascending, so the stamp is overwritten each iteration).
	"""
	filters = {"docstatus": 1}
	# FU95: filter company global — scope baris WO sebelum deret turunannya
	if company:
		filters["company"] = company
	if wo_names is not None:
		wo_names = sorted({name for name in wo_names if name})
		if not wo_names:
			return []
		filters["name"] = ("in", wo_names)
	try:
		wos = frappe.get_list(
			"Work Order",
			filters=filters,
			fields=[
				"name", "production_item", "qty", "produced_qty", "custom_adonan_ke",
				"fg_warehouse", "creation", "company",
				# T35 summary block: bulk-loaded once, mapped onto request rows
				"custom_handover_material_request",
			],
			order_by="creation desc",
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return []
	if not wos:
		return []
	# lots are SE/batch derivatives; both roles that read WOs also read these
	# (T22 matrix) — without them the Cold Storage lane is not derivable
	if not frappe.has_permission("Stock Entry", "read") or not frappe.has_permission(
		"Batch", "read"
	):
		return []

	ses = frappe.get_all(
		"Stock Entry",
		filters={
			"work_order": ("in", [w.name for w in wos]),
			"purpose": "Manufacture",
			"docstatus": 1,
		},
		fields=["name", "work_order", "posting_date", "posting_time"],
		order_by="posting_date asc, posting_time asc, creation asc",
	)
	if not ses:
		return []
	fg_rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ("in", [s.name for s in ses]), "is_finished_item": 1},
		fields=["parent", "t_warehouse", "serial_and_batch_bundle"],
	)
	rows_by_se = {}
	for r in fg_rows:
		rows_by_se.setdefault(r.parent, []).append(r)
	batches_by_bundle = {}
	bundles = [r.serial_and_batch_bundle for r in fg_rows if r.serial_and_batch_bundle]
	if bundles:
		for e in frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": ("in", bundles)},
			fields=["parent", "batch_no"],
		):
			batches_by_bundle.setdefault(e.parent, []).append(e.batch_no)

	history = {}
	for s in ses:  # ascending posting -> first seen is the earliest entry
		cur = history.setdefault(
			s.work_order,
			{
				"manufactures": 0,
				"batches": [],
				"warehouse": None,
				"entered_at": None,
				"completed_at": None,
			},
		)
		cur["manufactures"] += 1
		stamp = f"{s.posting_date} {_time_str(s.posting_time)}"
		if cur["entered_at"] is None:
			cur["entered_at"] = stamp
		cur["completed_at"] = stamp  # ascending: the last write is the LATEST
		for r in rows_by_se.get(s.name, []):
			cur["warehouse"] = cur["warehouse"] or r.t_warehouse
			if r.serial_and_batch_bundle:
				cur["batches"].extend(batches_by_bundle.get(r.serial_and_batch_bundle, []))
			else:
				cur["batches"].append(None)

	# follow-up 8: an FG item without batch tracking produces bundle-less rows —
	# those WOs become BATCHLESS lots (stock pool per item, see _lots). The flag
	# comes from the Item master, not the rows, so a legacy bundle-less history
	# on an item that IS batch-tracked stays unsupported (transition guard).
	try:
		item_batch_flags = {
			r["name"]: r["has_batch_no"]
			for r in frappe.get_all(
				"Item",
				filters={"name": ("in", sorted({w.production_item for w in wos}))},
				fields=["name", "has_batch_no"],
			)
		}
	except frappe.PermissionError:
		return []  # same policy as the SE/Batch gate: no read, empty board

	rows = []
	for w in wos:
		cur = history.get(w.name)
		if not cur:
			continue  # never manufactured — the WO workspace's domain, not a lot
		row = frappe._dict(
			{
				"batch": None,
				"batchless": False,
				"work_order": w.name,
				# FU60: WAJIB ikut — gate company FU58 (_pool_warehouse dst.)
				# membaca lot_row.company; tanpa ini selalu None dan setiap
				# setting company non-kosong mematikan pool override.
				"company": w.company,
				"item_code": w.production_item,
				"production_item": w.production_item,  # consumed by _enrich_units
				"custom_uom": None,
				"qty": flt(w.qty),
				"produced_qty": flt(w.produced_qty),
				"adonan_ke": w.custom_adonan_ke or None,  # FU69: 0 = kosong
				"warehouse": cur["warehouse"] or w.fg_warehouse,
				"entered_at": str(cur["entered_at"]),
				"completed_at": cur["completed_at"],
				"physical_qty": None,
				"reserved_qty": None,
				"available_qty": None,
				"unsupported": False,
				"unsupported_reason": None,
				"has_older_lot_same_item": False,
				"custom_handover_material_request": w.custom_handover_material_request,
			}
		)
		unique = {b for b in cur["batches"] if b}
		batchless_rows = None in cur["batches"]
		if batchless_rows and not unique and not item_batch_flags.get(w.production_item):
			# no batch dimension exists for this item: every Manufacture lands in
			# one ITEM-level stock pool, so multiple Manufactures flatten honestly
			row.batchless = True
		elif batchless_rows and not unique:
			row.unsupported = True
			row.unsupported_reason = _(
				"Work Order {0}: FG tanpa batch padahal itemnya kini berbatch (transisi) — selaraskan stok lewat Desk."
			).format(w.name)
		elif cur["manufactures"] > 1 or batchless_rows or len(unique) != 1:
			parts = [_("{0} Manufacture").format(cur["manufactures"])]
			if unique:
				parts.append(_("{0} batch").format(len(unique)))
			if batchless_rows:
				parts.append(
					_("{0} baris FG tanpa batch").format(sum(1 for b in cur["batches"] if b is None))
				)
			row.unsupported = True
			row.unsupported_reason = _(
				"Work Order {0}: {1} — tidak bisa dipetakan ke satu lot; selesaikan lewat Desk."
			).format(w.name, " / ".join(parts))
		else:
			row.batch = next(iter(unique))
		rows.append(row)

	batch_qty = _batch_quantities(
		(r.item_code, r.batch, r.warehouse)
		for r in rows
		if r.batch and not r.unsupported
	)
	for row in rows:
		if row.batch and not row.unsupported:
			row.physical_qty = flt(batch_qty.get((row.batch, row.warehouse), 0))

	_enrich_units(rows)  # shared qtyInPack source — UOM logic not duplicated
	names = _item_names({r.item_code for r in rows})
	for row in rows:
		row.item_name = names.get(row.item_code) or row.item_code
		row.qty_in_pack = flt(row.display_conversion_factor or 1)
	return rows


def _requests(wo_rows, wo_names=None, item_codes=None, company=None):
	"""Handover request rows — one per Material Request bound to a Work Order
	via Material Request Item.custom_work_order (T22 field).

	Lane mapping (documents only, T35): terkirim = a submitted Stock Entry
	exists against the MR (Stock Entry Detail `material_request` link, T21) —
	even if the MR is abnormally cancelled AFTER that send; else request =
	submitted and not stopped. The retired postpacking confirmation advances
	nothing. Edge states are never omitted and never raise: draft and
	cancelled MRs come back with lane=None plus a flag; a stopped MR without
	SE is a dead request (needs a manual desk unstop) parked in the request
	lane with flag="stopped" — visible, but reserving nothing (§4.3).

	Box summary (T35): kg + whole count (item's warehouse display UOM, T39)
	come from the BULK Work Order lot rows while the WO Link points at the MR;
	pre-cutover MRs (empty Link) fall back to their own kg fields with BOTH
	count values empty. No per-card Work Order lookup happens in this loop.
	"""
	item_filters = {"custom_work_order": ("is", "set")}
	if wo_names is not None:
		wo_names = sorted({name for name in wo_names if name})
		if not wo_names:
			return []
		item_filters["custom_work_order"] = ("in", wo_names)
	if item_codes is not None:
		item_codes = sorted({code for code in item_codes if code})
		if not item_codes:
			return []
		item_filters["item_code"] = ("in", item_codes)
	mr_names = frappe.get_all("Material Request Item", filters=item_filters, pluck="parent")
	if not mr_names:
		return []
	try:
		mr_filters = {
			"name": ("in", sorted(set(mr_names))),
			"material_request_type": "Material Transfer",
		}
		# FU95: filter company global — MR punya field company native sendiri
		# (bind sejalur dengan lot saat keduanya di-scope)
		if company:
			mr_filters["company"] = company
		mrs = frappe.get_list(
			"Material Request",
			filters=mr_filters,
			fields=[
				"name", "docstatus", "status", "owner", "creation",
				"set_from_warehouse", "set_warehouse",
				"company",
				# FU96/FU97: field box MR legacy (custom_box_1/2) dipensiunkan
				# total (definisi + kolom DB) — request = dokumen qty murni
				"custom_good_qty_postpacking", "custom_reject_qty_postpacking",
				"custom_trial_qty_postpacking", "custom_sisa_qty_postpacking",
				"custom_jam_packing", "custom_qc_packing",
				"custom_postpacking_confirmed",
				"custom_handover_box_plan",
			],
			order_by="creation desc",
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return []
	if not mrs or not frappe.has_permission("Stock Entry", "read"):
		return []  # lanes cannot be derived truthfully without SE visibility

	bound_items = {}
	for it in frappe.get_all(
		"Material Request Item",
		filters={
			"parent": ("in", [m.name for m in mrs]),
			"custom_work_order": ("is", "set"),
		},
		fields=[
			"name", "parent", "item_code", "item_name", "qty", "stock_qty", "stock_uom",
			"custom_work_order", "from_warehouse",
		],
		order_by="idx asc",
	):
		bound_items.setdefault(it.parent, []).append(it)
	if not bound_items:
		return []

	wo_by_name = {r.work_order: r for r in wo_rows}
	sent = _sent_se_by_mr([m.name for m in mrs])
	all_mri_names = [it.name for items in bound_items.values() for it in items if getattr(it, "name", None)]
	transferred_by_mri = dict(
		frappe.db.sql(
			"""select sed.material_request_item, coalesce(sum(sed.transfer_qty), 0)
				 from `tabStock Entry Detail` sed
				where sed.material_request_item in %s
				  and sed.docstatus = 1
				group by sed.material_request_item""",
			(tuple(all_mri_names),),
			as_list=True,
		)
	) if all_mri_names else {}
	users = _user_names(
		{m.owner for m in mrs} | {m.custom_qc_packing for m in mrs if m.custom_qc_packing}
	)

	# W19 groups (FU96: tanpa box): sisi klien hanya butuh identitas grup +
	# jumlah anggota HIDUP — bulk-loaded ONCE per call saat ada MR berplan
	group_size_by_plan = {}
	box_plan_names = sorted({m.custom_handover_box_plan for m in mrs if m.custom_handover_box_plan})
	if box_plan_names:
		# group_size = LIVE members only: submitted (active request OR shipped);
		# cancelled/draft members never counted (one grouped query)
		for r in frappe.get_all(
			"Material Request",
			filters={"custom_handover_box_plan": ("in", box_plan_names), "docstatus": 1},
			fields=[{"COUNT": "name", "as": "group_size"}, "custom_handover_box_plan"],
			group_by="custom_handover_box_plan",
			limit=0,
		):
			group_size_by_plan[r.custom_handover_box_plan] = r.group_size

	rows = []
	for m in mrs:
		items = bound_items.get(m.name)
		if not items:
			continue  # not a handover MR (no Work Order binding)
		se = sent.get(m.name)
		for it in items:  # 2026-10-10: bulk MR = one row per WO
			req_qty = flt(it.stock_qty or it.qty)
			done_qty = flt(transferred_by_mri.get(it.name, 0.0))
			outstanding = max(0.0, req_qty - done_qty)
			source_wh = it.from_warehouse or m.set_from_warehouse or None
			lane, flag = None, None
			if m.docstatus == 2:
				flag = "cancelled"
				if done_qty > 0 and outstanding <= 0:
					lane = LANE_KIRIM
			elif m.docstatus == 0:
				flag = "draft"  # not yet submitted — no reservation, no action
			elif m.status == "Stopped":
				lane, flag = LANE_REQUEST, "stopped"
			elif outstanding <= 0 or m.status in ("Transferred", "Issued"):
				lane = LANE_KIRIM
			else:
				lane = LANE_REQUEST
			lot = wo_by_name.get(it.custom_work_order)
			qty_in_pack, adonan_ke = (lot.qty_in_pack, lot.adonan_ke) if lot else (None, None)
			if lot is None:
				# WO has no lot row (never manufactured / not submitted): the mockup
				# dialogs still read qtyInPack + adonan off the request's item, so
				# resolve it the same way instead of handing the UI a blank factor
				enriched = frappe._dict(production_item=it.item_code, custom_uom=None)
				_enrich_units([enriched])
				qty_in_pack = flt(enriched.display_conversion_factor or 1)
				display_uom = enriched.display_uom or enriched.stock_uom
			else:
				display_uom = lot.display_uom or lot.stock_uom
			remainder = max(0.0, flt(lot.produced_qty) - done_qty) if lot else outstanding
			rows.append(
				{
					"mr": m.name,
					"docstatus": m.docstatus,
					"status": m.status,
					"lane": lane,
					"flag": flag,
					"item_code": it.item_code,
					"item_name": it.item_name or it.item_code,
					"qty": req_qty,  # stock UOM (Pcs)
					"outstanding_qty": outstanding,
					"transferred_qty": done_qty,
					"remainder": remainder,
					"stock_uom": it.stock_uom,
					"work_order": it.custom_work_order,
					# FU95: ikut terkirim supaya klien/uji bisa membuktikan scope
					# company baris (filter tetap server-side)
					"company": m.company,
					"batch": lot.batch if lot and not lot.unsupported else None,
					"qty_in_pack": qty_in_pack,
					"display_uom": display_uom,
					"adonan_ke": adonan_ke,
					# FU96: field box (kg/jumlah) dipensiunkan — grup request tetap
					# dikenali lewat plan + jumlah anggota (mekanisme W19 hidup)
					"box_plan": m.custom_handover_box_plan or None,
					"group_size": (
						group_size_by_plan.get(m.custom_handover_box_plan, 0)
						if m.custom_handover_box_plan
						else (len(items) if len(items) > 1 else None)
					),
					"from_warehouse": source_wh,
					"to_warehouse": m.set_warehouse or None,
					"postpacking": {
						"good": flt(m.custom_good_qty_postpacking),
						"reject": flt(m.custom_reject_qty_postpacking),
						"trial": flt(m.custom_trial_qty_postpacking),
						"sisa": flt(m.custom_sisa_qty_postpacking),
						"jam_packing": _time_str(m.custom_jam_packing)
						if m.custom_jam_packing
						else None,
						"qc_packing": m.custom_qc_packing or None,
						"qc_packing_name": users.get(m.custom_qc_packing),
						"confirmed": bool(m.custom_postpacking_confirmed),
					},
				"stock_entry": se.name if se else None,
				"sent_at": f"{se.posting_date} {_time_str(se.posting_time)}" if se else None,
				"owner": m.owner,
				"owner_name": users.get(m.owner),
				"creation": str(m.creation),
			}
			)

	# FU29: live stock at the ROUTE origin (MR from_warehouse) so request
	# cards can warn BEFORE a send is attempted; cached per (kind, key) — the
	# same quantities send_handover re-checks under the lock.
	route_cache = {}
	for r in rows:
		if r["lane"] != LANE_REQUEST or not r["from_warehouse"]:
			continue
		lot = wo_by_name.get(r["work_order"])
		if not lot or lot.unsupported or (not lot.batchless and not r["batch"]):
			continue
		if lot.batchless:
			key = ("i", r["item_code"], r["from_warehouse"])
			if key not in route_cache:
				route_cache[key] = _item_stock(r["item_code"], r["from_warehouse"])
		else:
			key = ("b", r["batch"], r["from_warehouse"])
			if key not in route_cache:
				route_cache[key] = flt(get_batch_qty(r["batch"], r["from_warehouse"]) or 0)
		r["route_available"] = route_cache[key]
	return rows


def _sent_se_by_mr(mr_names):
	"""Earliest submitted Stock Entry per MR. `material_request` lives on
	Stock Entry Detail (the link the native MR->SE builder sets, T21), so the
	lookup goes through the detail rows and re-checks the submitted headers."""
	links = frappe.get_all(
		"Stock Entry Detail",
		filters={
			"material_request": ("in", mr_names),
			"docstatus": 1,
			"parenttype": "Stock Entry",
		},
		fields=["parent", "material_request"],
	)
	if not links:
		return {}
	link_by_se = {d.parent: d.material_request for d in links}
	sent = {}
	for r in frappe.get_all(
		"Stock Entry",
		filters={"name": ("in", list(link_by_se)), "docstatus": 1},
		fields=["name", "posting_date", "posting_time"],
		order_by="posting_date asc, posting_time asc, creation asc",
	):
		sent.setdefault(link_by_se[r.name], r)
	return sent


# ------------------------------------------------ FU23: field native di WO
# Penanda serah terima di form Work Order Desk (custom_handover_status).
# Workspace TETAP memakai derivasi live (work_order._handover_enrich) supaya
# tidak pernah drift; field ini adalah cermin yang disinkronkan doc_events.

HANDOVER_STATUS_FIELD = "custom_handover_status"
# nilai Select = label Indonesia (persis options Custom Field upgrade.py)
HANDOVER_STATUS_LABEL = {
	LANE_REQUEST: "Diminta Gudang",
	LANE_KIRIM: "Terkirim",
}

# FU37: judul Error Log untuk kegagalan mirror doc_events (tidak dinaikkan).
SYNC_ERROR_TITLE = "Production App: sinkronisasi status serah terima gagal"


def _handover_sync_ready():
	"""FU37 (insiden MAT-STE-2026-06920): doc_events mirror butuh metadata
	app — MRI.custom_work_order + WO.custom_handover_status. Saat kode sudah
	terpasang tetapi migrate belum dijalankan, keduanya absen dari meta dan
	query mirror meledak "Unknown column" yang membatalkan submit Stock
	Entry native. Mirror adalah data TURUNAN: kalau meta belum siap, sync
	dilewati, bukan menggagalkan transaksi dokumen lain."""
	return (
		frappe.get_meta("Material Request Item").has_field("custom_work_order")
		and frappe.get_meta("Work Order").has_field(HANDOVER_STATUS_FIELD)
	)


def _handover_state(wo_names):
	"""SATU resolver status+Link serah terima per Work Order (dipakai
	_handover_lanes, sinkronisasi ringkasan, dan migrasi T35 supaya preseden
	lane dan Link tidak bisa drift). Kandidat diiterasi TERBARU lebih dulu.
	Preseden:
	- Terkirim (LANE_KIRIM) HANYA bila transfer kumulatif GBJ telah menutup produced_qty;
	- tanpa pemenuhan penuh: MR submitted aktif (docstatus 1, belum Transferred/Stopped)
	  menentukan LANE_REQUEST;
	- WO dengan sisa unrequested output dan tanpa MR aktif memiliki lane None
	  sehingga tetap dapat diminta kembali.

	Mengembalikan {wo_name: {"lane": ..., "mr": ...}}; {} saat kosong/tanpa
	izin (pemanggil menampilkan tanpa flag, tanpa error)."""
	wo_names = [n for n in wo_names if n]
	if not wo_names:
		return {}
	try:
		items = frappe.get_all(
			"Material Request Item",
			filters={"custom_work_order": ("in", wo_names)},
			fields=["parent", "custom_work_order"],
			limit=0,
		)
		mr_names = sorted({i.parent for i in items})
		mrs = (
			frappe.get_all(
				"Material Request",
				filters={
					"name": ("in", mr_names),
					"material_request_type": "Material Transfer",
				},
				fields=["name", "docstatus", "status", "creation"],
				order_by="creation desc",
				limit=0,
			)
			if mr_names
			else []
		)
		wo_produced = dict(
			frappe.get_all(
				"Work Order",
				filters={"name": ("in", wo_names)},
				fields=["name", "produced_qty"],
				as_list=True,
				limit=0,
			)
		)
		target_wh = _target_warehouse()
		if not target_wh:
			transferred_by_wo = {}
		else:
			transferred_by_wo = dict(
				frappe.db.sql(
					"""select mri.custom_work_order, coalesce(sum(sed.transfer_qty), 0)
						 from `tabStock Entry Detail` sed
						 join `tabMaterial Request Item` mri on mri.name = sed.material_request_item
						where mri.custom_work_order in %s
						  and sed.docstatus = 1
						  and coalesce(sed.t_warehouse, '') = %s
						group by mri.custom_work_order""",
					(tuple(wo_names), target_wh),
					as_list=True,
				)
			) if wo_names else {}
	except frappe.PermissionError:
		return {}
	if not mrs:
		return {}
	sent = _sent_se_by_mr(mr_names)
	wos_by_mr = defaultdict(list)
	for i in items:
		wos_by_mr[i.parent].append(i.custom_work_order)
	state = {}
	for wo_name in wo_names:
		produced = flt(wo_produced.get(wo_name, 0.0))
		transferred = flt(transferred_by_wo.get(wo_name, 0.0))
		# Matching MRs for this WO (newest first)
		matching_mrs = [m for m in mrs if wo_name in wos_by_mr.get(m.name, ())]
		if not matching_mrs:
			continue
		newest_mr = matching_mrs[0]
		transferred_mr = next((m.name for m in matching_mrs if m.docstatus == 1 and m.name in sent), None)

		if produced > 0 and transferred >= produced:
			# Fully covered by cumulative transfers; cancelled requests cannot own the Link.
			state[wo_name] = {"lane": LANE_KIRIM, "mr": transferred_mr}
		else:
			# Active request pending fulfillment (excludes Issued consistently)
			active_candidate = next(
				(m for m in matching_mrs if m.docstatus == 1 and m.status not in ("Stopped", "Cancelled", "Transferred", "Issued")),
				None
			)
			if active_candidate:
				state[wo_name] = {"lane": LANE_REQUEST, "mr": active_candidate.name}
			elif transferred > 0:
				# Partially transferred, no open active MR currently
				state[wo_name] = {"lane": None, "mr": transferred_mr, "partial": True}
			elif newest_mr.docstatus == 1:
				# Keep submitted terminal requests navigable, but release cancelled links.
				state[wo_name] = {"lane": None, "mr": newest_mr.name}
	return state


def _handover_lanes(wo_names):
	"""FU23: lane serah terima paling maju per Work Order — kini pembungkus
	tipis di atas _handover_state bersama (satu derivasi untuk flag workspace,
	field native, dan ringkasan Link). Tanpa kandidat → {}."""
	return {
		wo_name: state["lane"]
		for wo_name, state in _handover_state(wo_names).items()
		if state.get("lane")
	}


# FU96/FU97: field box WO (custom_box_1..3 + _qty) dipensiunkan total —
# definisi DAN kolom DB sudah dihapus (upgrade.drop_box_columns). Ringkasan
# serah terima kini HANYA Link + status.
WO_SUMMARY_FIELDS = ("custom_handover_material_request",)


def _sync_handover_summary(wo_names):
	"""Fail-honest summary writer: derive status + Link per Work Order from
	documents (_handover_state) and write ONLY actual diffs. The summary
	fields are read_only on the form — this controlled db write is the gate
	(the role-gated actions + this sync + the migration share it). Clearing
	rule (T35, FU96): a WO whose only evidence vanished (unsent cancelled MR,
	no replacement) loses the Link and the status. Returns the WO names
	actually written."""
	wo_names = sorted({n for n in wo_names if n})
	if not wo_names:
		return []
	states = _handover_state(wo_names)
	priors = frappe.get_all(
		"Work Order",
		filters={"name": ("in", wo_names)},
		fields=["name", HANDOVER_STATUS_FIELD, *WO_SUMMARY_FIELDS],
		limit=0,
	)
	written = []
	for prior in priors:
		link = prior.custom_handover_material_request or None
		status = prior.get(HANDOVER_STATUS_FIELD) or None
		state = states.get(prior.name)
		values = {}
		if state:
			if link != state["mr"]:
				values["custom_handover_material_request"] = state["mr"]
			label = HANDOVER_STATUS_LABEL.get(state["lane"], "Diminta Gudang")
			if status != label:
				values[HANDOVER_STATUS_FIELD] = label
		else:
			if status is not None:
				values[HANDOVER_STATUS_FIELD] = None
			if link:
				# the current Link has no SE evidence (else state would exist):
				# cancelled unsent request with no replacement -> clear the Link
				values["custom_handover_material_request"] = None
		if values:
			frappe.db.set_value("Work Order", prior.name, values, update_modified=False)
			written.append(prior.name)
	return written


def sync_handover_status(wo_names):
	"""Kompatibilitas (doc_events + migrasi T35): tulis status + Link ringkasan
	serah terima di Work Order dari derivasi dokumen. WO tanpa lane aktif
	dikosongkan (semua MR batal). Mengembalikan nama WO yang berubah."""
	return _sync_handover_summary(wo_names)


def sync_from_material_request(doc, method=None):
	"""doc_events Material Request (submit/cancel/update) → WO terikat item.
	FU37 fail-safe: mirror tidak boleh menggagalkan transaksi MR native —
	skip saat metadata app belum termigrasi; error lain (termasuk dari
	pemeriksaan metadata itu sendiri) dicatat ke Error Log, tidak dinaikkan."""
	try:
		if not _handover_sync_ready():
			return
		sync_handover_status(
			[i.custom_work_order for i in (doc.items or []) if i.get("custom_work_order")]
		)
	except Exception:
		frappe.log_error(
			title=SYNC_ERROR_TITLE,
			message=f"Material Request {doc.name}\n\n{frappe.get_traceback()}",
		)


def guard_pool_reservation(doc, method=None):
	"""doc_events Material Request before_submit: a native Material Transfer
	MR (desk R&D, other warehouses) drawing from the configured handover
	source pool may not reserve more than physical minus every other active
	reservation. Same Item row lock as create_request, so the two serialize.
	Handover rows (custom_work_order) are skipped: create_request /
	create_group_request already guard them under that lock.
	shortcut: reopen of a Stopped MR (update_status) bypasses submit hooks,
	add an on_update guard if reopen over a drained pool becomes real."""
	source = _source_warehouse()
	if not source or doc.material_request_type != "Material Transfer":
		return
	wanted = {}
	for d in doc.items or []:
		if not d.get("custom_work_order") and (d.from_warehouse or doc.set_from_warehouse) == source:
			wanted[d.item_code] = wanted.get(d.item_code, 0.0) + flt(d.stock_qty or d.qty)
	for item_code in sorted(wanted):
		frappe.db.get_value("Item", item_code, "name", for_update=True)  # pool lock
		# self is still docstatus 0 here, so it is not in the reserved sum
		available = _item_stock(item_code, source) - _pool_reserved_now(item_code, source, for_update=True)
		if wanted[item_code] > available:
			frappe.throw(
				_("Qty {0} dari {1} melebihi stok tersedia: diminta {2}, tersedia {3}.").format(
					item_code, source, wanted[item_code], max(0.0, available)
				),
				frappe.ValidationError,
			)


def sync_from_stock_entry(doc, method=None):
	"""doc_events Stock Entry (submit/cancel) → MR terikat → WO terikat.
	FU37 fail-safe: Stock Entry manual/reguler tidak pernah gagal karena
	mirror serah terima — skip saat metadata app belum termigrasi; error
	lain (termasuk dari pemeriksaan metadata itu sendiri) dicatat ke Error
	Log, tidak dinaikkan."""
	try:
		if not _handover_sync_ready():
			return
		mrs = sorted({d.material_request for d in (doc.items or []) if d.get("material_request")})
		if not mrs:
			return
		sync_handover_status(frappe.get_all(
			"Material Request Item",
			filters={"parent": ("in", mrs), "custom_work_order": ("is", "set")},
			pluck="custom_work_order",
			distinct=True,
			limit=0,
		))
	except Exception:
		frappe.log_error(
			title=SYNC_ERROR_TITLE,
			message=f"Stock Entry {doc.name}\n\n{frappe.get_traceback()}",
		)


def backfill_handover_status():
	"""Sekali (bench execute): sinkronkan field untuk WO yang pernah terikat MR."""
	wos = frappe.get_all(
		"Material Request Item",
		filters={"custom_work_order": ("is", "set")},
		pluck="custom_work_order",
		distinct=True,
		limit=0,
	)
	sync_handover_status(wos)
	return len(wos)


def _reserved_by_wo(requests):
	"""§4.3: reservation = Σ outstanding qty of active, not stopped/cancelled MRs
	without complete Stock Entry, bound to the Work Order."""
	reserved = {}
	for r in requests:
		if r["lane"] == LANE_REQUEST and not r["flag"]:
			reserved[r["work_order"]] = reserved.get(r["work_order"], 0.0) + flt(r.get("outstanding_qty", r["qty"]))
	return reserved


def _reserved_by_item(requests, wo_rows):
	"""Batchless pool reservation: active MRs hold reservation against the item
	scoped to the MR row's source warehouse, preventing historical reservations from
	shifting if setting changes."""
	reserved = {}
	for r in requests:
		if r["lane"] == LANE_REQUEST and not r["flag"]:
			warehouse = r.get("from_warehouse")
			if warehouse:
				key = (r["item_code"], warehouse)
				reserved[key] = reserved.get(key, 0.0) + flt(r.get("outstanding_qty", r["qty"]))
	return reserved


def _item_stock(item_code, warehouse):
	"""Live item+warehouse balance from Bin (RECO rows post actual_qty=0 with
	the balance only in qty_after_transaction, so SUM(SLE.actual_qty)
	under-reports once a reconciliation exists)."""
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
		or 0
	)


def _lots(wo_rows, requests):
	"""Finish the lot cards: live reserved/available math, the drop rule and
	the FIFO hint. physical_qty is the live ledger quantity of the batch in the
	lot warehouse (§4.2 — never a stored counter); available is never clamped,
	negative availability surfaces as-is.

	Follow-up 8: a BATCHLESS lot (FG item without batch tracking) cannot own
	stock — the item's whole balance in the POOL warehouse (source setting
	override, R2) is one pool shared by every WO of that item, and reservations
	pool the same way. All batchless WO-cards of an item therefore show the
	same honest pool numbers."""
	reserved = _reserved_by_wo(requests)
	reserved_item = _reserved_by_item(requests, wo_rows)
	pool_stock = {}
	# a request bound to a lane keeps its (even empty) lot listed
	bound = {r["work_order"] for r in requests if r["lane"]}
	wo_names = [r.work_order for r in wo_rows if not getattr(r, "unsupported", False)]
	target_wh = _target_warehouse()
	target_clause = "and coalesce(sed.t_warehouse, '') = %s" if target_wh else ""
	params = [tuple(wo_names), target_wh] if target_wh else [tuple(wo_names)]
	transferred_by_wo = dict(
		frappe.db.sql(
			f"""select mri.custom_work_order, coalesce(sum(sed.transfer_qty), 0)
				 from `tabStock Entry Detail` sed
				 join `tabMaterial Request Item` mri on mri.name = sed.material_request_item
				where mri.custom_work_order in %s
				  and sed.docstatus = 1
				  {target_clause}
				group by mri.custom_work_order""",
			tuple(params),
			as_list=True,
		)
	) if wo_names and target_wh else {}
	lots = []
	for row in wo_rows:
		if row.unsupported:
			lots.append(row)
			continue
		transferred = flt(transferred_by_wo.get(row.work_order, 0.0))
		active_req = flt(reserved.get(row.work_order, 0.0))
		row.transferred_qty = transferred
		rem = max(0.0, flt(row.produced_qty) - transferred - active_req)
		row.unrequested_remainder = rem if (transferred > 0 or active_req > 0) and rem > 0 else 0.0
		if row.batchless:
			pool_wh = _pool_warehouse(row)
			key = (row.item_code, pool_wh)
			if key not in pool_stock:
				pool_stock[key] = _item_stock(row.item_code, pool_wh)
			row.physical_qty = pool_stock[key]
			row.reserved_qty = _pool_reserved_now(row.item_code, pool_wh, for_update=False)
		else:
			row.reserved_qty = active_req
		row.available_qty = row.physical_qty - row.reserved_qty
		# FU30: penanda manual "Gudang Confirmed" dipensiunkan — lot turun murni
		# dari stok (physical 0) / Status Serah Terima; kecuali masih diikat
		# permintaan aktif (dialognya butuh data lot).
		if row.physical_qty <= 0 and row.work_order not in bound and row.unrequested_remainder <= 0:
			continue  # empty lot nobody references — drops off the lane
		lots.append(row)

	lots.sort(key=lambda r: (r.unsupported, r.entered_at, r.work_order))
	seen_item = set()
	for row in lots:  # FIFO walk: a still-listed earlier lot hints newer ones
		if row.unsupported:
			continue
		row.has_older_lot_same_item = row.item_code in seen_item
		seen_item.add(row.item_code)
	return lots


def _item_names(codes):
	if not codes:
		return {}
	return {
		d.name: d.item_name
		for d in frappe.get_all(
			"Item", filters={"name": ("in", list(codes))}, fields=["name", "item_name"], limit=0
		)
	}


def _user_names(names):
    names = [n for n in names if n]
    if not names:
        return {}
    return {
        u.name: u.full_name
        for u in frappe.get_all(
            "User", filters={"name": ("in", names)}, fields=["name", "full_name"]
        )
    }


# ----------------------------------------------------- T24 mutation actions
#
# Contracts (task-24-brief): validate EVERYTHING before any write (T10 style);
# each action runs as the session user through ordinary permission checks (no
# ignore_permissions) behind an explicit role gate; success returns
# {"ok": True, ...refs, "board": <full _build_board() payload>}.
# Availability/lot truth is re-derived from the same board builders the read
# API uses (§4.1 server truth) AFTER the Work Order row is locked for update
# (the finish() pattern), so racing requests serialize on the row lock and the
# second one re-derives the reservation from the first one's committed MR.

from erpnext.stock.doctype.material_request.material_request import (
    make_stock_entry as make_mr_stock_entry,
)


def _require_role(role, message):
    """role: satu nama atau tuple nama — lolos jika session user punya salah satunya."""
    roles = frappe.get_roles()
    allowed = (role,) if isinstance(role, str) else tuple(role)
    if not any(r in roles for r in allowed):
        frappe.throw(message, frappe.PermissionError)


def _retry_on_deadlock(action):
    """T36: snapshot REPEATABLE-READ tidak melihat kompetitor yang commit
    SELAMA request ini menunggu lock baris — dan MariaDB menjawab locking
    read dengan ER 1020/1213 (frappe.QueryDeadlockError). Rollback + jalankan
    ulang aksi memberi setiap guard snapshot BARU: guard dihitung ulang,
    tidak pernah dilewati. Tiga percobaan cukup untuk duel dua sesi —
    kompetitor hanya commit sekali, sehingga percobaan berikutnya pasti
    melihatnya; kegagahan terakhir tetap raise jujur."""
    @functools.wraps(action)
    def wrapper(*args, **kwargs):
        for attempt in (0, 1, 2):
            try:
                return action(*args, **kwargs)
            except frappe.QueryDeadlockError:
                if attempt == 2:
                    raise
                frappe.db.rollback()
    return wrapper


def _active_mr_now(mr_name):
    """CURRENT (locking) active-request check for one MR: submitted, not
    stopped/transferred/cancelled, and has unfulfilled quantity remaining."""
    docstatus, status, per_ordered = frappe.db.get_value(
        "Material Request", mr_name, ["docstatus", "status", "per_ordered"], for_update=True
    ) or (None, None, None)
    if docstatus != 1 or status in ("Stopped", "Transferred", "Cancelled", "Issued") or flt(per_ordered) >= 100.0:
        return False
    # Check if there is remaining unfulfilled quantity across items
    mri_outstanding = frappe.db.sql(
        """select coalesce(sum(
               greatest(0.0, mri.stock_qty - coalesce((
                   select sum(sed.transfer_qty)
                     from `tabStock Entry Detail` sed
                    where sed.material_request = mr.name
                      and sed.material_request_item = mri.name
                      and sed.docstatus = 1
               ), 0.0))
           ), 0.0)
              from `tabMaterial Request Item` mri
              join `tabMaterial Request` mr on mr.name = mri.parent
             where mr.name = %s""",
        (mr_name,),
    )[0][0]
    return flt(mri_outstanding) > 0.0


def _compute_outstanding_reservation(stock_qty, fulfilled_qty=0.0):
    """Reservation is the nonnegative unfulfilled portion of a submitted, active MR item."""
    return max(0.0, flt(stock_qty) - flt(fulfilled_qty))


def _allocate_pool_budget(wo_rows, pool_available):
    """Deterministic sorted-WO pool budget allocation.
    Allocates available pool budget greedily in sorted Work Order name order,
    bounded by each Work Order's unrequested eligible remainder.
    Returns (allocations_dict, remaining_budget).
    """
    sorted_wos = sorted(wo_rows, key=lambda w: w.get("work_order") if isinstance(w, dict) else w.work_order)
    remaining_budget = max(0.0, flt(pool_available))
    allocations = {}
    for w in sorted_wos:
        wo_name = w.get("work_order") if isinstance(w, dict) else w.work_order
        produced = flt(w.get("produced_qty") if isinstance(w, dict) else w.produced_qty)
        unrequested = flt(w.get("unrequested_qty", produced) if isinstance(w, dict) else getattr(w, "unrequested_qty", produced))
        alloc = min(remaining_budget, unrequested, flt(w.get("allocation_limit", unrequested)))
        remaining_budget = max(0.0, remaining_budget - alloc)
        allocations[wo_name] = {
            "work_order": wo_name,
            "produced_qty": produced,
            "allocated_qty": alloc,
            "unrequested_remainder": max(0.0, unrequested - alloc),
        }
    return allocations, remaining_budget


def _derive_wo_handover_state(produced_qty, cumulative_transferred=0.0, active_mr=None, active_mr_qty=0.0):
    """Derive Work Order handover lane and partial remainder truth.
    A WO is fully transferred (LANE_KIRIM) only when cumulative GBJ transfers cover produced_qty.
    """
    produced = flt(produced_qty)
    transferred = flt(cumulative_transferred)
    mr_qty = flt(active_mr_qty)
    if transferred >= produced and produced > 0:
        return {
            "lane": LANE_KIRIM,
            "mr": active_mr,
            "remaining_unrequested": 0.0,
            "is_partial": False,
        }
    if active_mr:
        rem = max(0.0, produced - transferred - mr_qty)
        return {
            "lane": LANE_REQUEST,
            "mr": active_mr,
            "remaining_unrequested": rem,
            "is_partial": transferred > 0,
        }
    rem = max(0.0, produced - transferred)
    return {
        "lane": None,
        "mr": None,
        "remaining_unrequested": rem,
        "is_partial": transferred > 0,
    }


def _pool_reserved_now(item_code, warehouse=None, for_update=False):
    """CURRENT total of ACTIVE pool reservations for the item in the source warehouse.
    Deducts fulfilled Stock Entry Detail transfer quantities so transferred stock (which has
    already left physical inventory) is not double-deducted as an outstanding reservation.
    When warehouse is omitted, scopes across all source warehouses for backwards compatibility.
    """
    wh_clause = "and coalesce(nullif(mri.from_warehouse, ''), nullif(mr.set_from_warehouse, '')) = %s" if warehouse else ""
    params = [item_code, warehouse] if warehouse else [item_code]
    lock = " for update" if for_update else ""
    return flt(
        frappe.db.sql(
            f"""select coalesce(sum(
                   greatest(0.0, mri.stock_qty - coalesce((
                       select sum(sed.transfer_qty)
                         from `tabStock Entry Detail` sed
                        where sed.material_request = mr.name
                          and sed.material_request_item = mri.name
                          and sed.docstatus = 1
                   ), 0.0))
               ), 0.0)
                  from `tabMaterial Request Item` mri
                  join `tabMaterial Request` mr on mr.name = mri.parent
                 where mri.item_code = %s
                   and mr.docstatus = 1
                   and mr.status not in ('Stopped', 'Transferred', 'Issued')
                   and mr.material_request_type = 'Material Transfer'
                   {wh_clause}
                   {lock}""",
            tuple(params),
        )[0][0]
    )


def _enforce_whole_uom(amount, stock_uom, label):
    """Whole-PCS per the QtyInput/UOM contract: integer when the stock UOM is
    marked must_be_whole_number (Pcs); free UOMs are untouched."""
    if frappe.get_cached_value("UOM", stock_uom, "must_be_whole_number") and amount != int(
        amount
    ):
        frappe.throw(_("{0} harus bilangan bulat dalam {1} (dapat {2}).").format(label, stock_uom, amount))


def _lot_for_wo(board, wo_name):
    return next((l for l in board["lots"] if l["work_order"] == wo_name), None)


def _checked_lot(wo_name):
    """Server-truth lot for one locked Work Order. Batchless reservations expand
    only to Work Orders sharing the item, instead of rebuilding the whole board."""
    wo_rows = _wo_lot_rows([wo_name])
    raw_lot = next((row for row in wo_rows if row.work_order == wo_name), None)
    if raw_lot is not None and raw_lot.unsupported:
        _throw_unsupported(raw_lot)

    requests = _requests(wo_rows, wo_names=[wo_name])
    if raw_lot is not None and raw_lot.batchless:
        requests = _requests(wo_rows, item_codes=[raw_lot.item_code])
        pool_wos = {
            r["work_order"]
            for r in requests
            if r["lane"] == LANE_REQUEST and not r["flag"]
        }
        pool_wos.add(wo_name)
        wo_rows = _wo_lot_rows(pool_wos)
        requests = _requests(wo_rows, item_codes=[raw_lot.item_code])

    lot = next((row for row in _lots(wo_rows, requests) if row.work_order == wo_name), None)
    if lot is not None and not lot.unsupported:
        return lot
    if lot is not None and lot.unsupported:
        _throw_unsupported(lot)
    frappe.throw(
        _("Work Order {0} tidak punya lot tersedia untuk diminta (belum ada Manufacture atau stok habis).").format(
            wo_name
        )
    )


def _throw_unsupported(lot):
    ses = frappe.get_all(
        "Stock Entry",
        filters={"work_order": lot.work_order, "purpose": "Manufacture", "docstatus": 1},
        pluck="name",
    )
    links = ", ".join(get_link_to_form("Stock Entry", s) for s in ses)
    frappe.throw(_("{0} ({1})").format(lot.unsupported_reason, links or "tanpa SE Manufacture"))


def _target_warehouse_or_throw(company=None):
    target = _target_warehouse()
    if not target:
        frappe.throw(
            _("Gudang tujuan serah terima belum diatur; isi 'Gudang Serah Terima' di menu Pengaturan.")
        )
    return target


def _expected_unit_count(wo, lot, amount):
    """Whole count of the full `amount` in the item's warehouse display UOM
    (T39 universal: the stock UOM itself at EXACT factor 1 — not a fallback —
    or any alternate display UOM with a valid conversion row), computed from
    the RAW _enrich_units fields (never qty_in_pack — its `or 1` display
    fallback would silently accept unconverted items)."""
    unit = lot.display_uom or lot.stock_uom
    if unit == lot.stock_uom:
        factor = 1.0
    else:
        factor = flt(lot.display_conversion_factor)
        if not math.isfinite(factor) or factor <= 0:
            frappe.throw(
                _("Item {0} belum memiliki konversi {1} yang valid.").format(
                    wo.production_item, unit
                )
            )
    precision = wo.precision("produced_qty") or 3
    raw = amount / factor
    expected = round(raw)
    tolerance = 0.5 * (10 ** (-precision))
    if abs(raw - expected) >= tolerance:
        frappe.throw(_("Hasil Work Order {0} tidak membentuk {1} utuh.").format(wo.name, unit))
    return int(expected)


def _insert_submitted_handover_mr(rows, target, company, box_plan=None):
    """Shared tail of create_request / create_group_request: insert + submit
    ONE native Material Transfer MR with one row per Work Order (`rows` =
    [(wo, amount, stock_uom, source), ...]; full produced qty, the WO's own
    pool source (header source only when every row shares it), target
    setting, row custom_work_order), then write every Work Order summary in
    the SAME transaction (read_only field: the controlled db_set gate) and
    sync the status. `box_plan` only for legacy plan-group fixtures. Returns
    the submitted MR."""
    sources = {source for _wo, _amount, _uom, source in rows}
    mr = frappe.get_doc(
        {
            "doctype": "Material Request",
            "material_request_type": "Material Transfer",
            "company": company,
            "transaction_date": now(),
            "schedule_date": add_days(now(), 1),
            "set_from_warehouse": next(iter(sources)) if len(sources) == 1 else None,
            "set_warehouse": target,
            **({"custom_handover_box_plan": box_plan} if box_plan else {}),
            "items": [
                {
                    "item_code": wo.production_item,
                    "qty": amount,
                    "uom": stock_uom,
                    "stock_uom": stock_uom,
                    "from_warehouse": source,
                    "warehouse": target,
                    "schedule_date": add_days(now(), 1),
                    "custom_work_order": wo.name,
                }
                for wo, amount, stock_uom, source in rows
            ],
        }
    )
    mr.insert()  # session user; submit below — one transaction, native perms
    mr.submit()
    wo_names = [row[0].name for row in rows]
    for name in wo_names:
        frappe.db.set_value(
            "Work Order", name, {"custom_handover_material_request": mr.name}, update_modified=False
        )
    _sync_handover_summary(wo_names)  # fail-honest: status Diminta Gudang
    return mr


def _compute_preview_fingerprint(allocations, groups=None):
    """Deterministic canonical context hash for preview allocations and pool state."""
    alloc_items = [
        (
            str(a.get("work_order") or "").strip(),
            str(a.get("item_code") or "").strip(),
            str(a.get("source_warehouse") or "").strip(),
            str(a.get("target_warehouse") or ""),
            str(a.get("company") or ""),
            str(a.get("stock_uom") or ""),
            str(a.get("display_uom") or ""),
            flt(a.get("qty_in_pack") or 1),
            str(a.get("batch") or ""),
            round(flt(a.get("allocated_qty") or 0.0), 4),
            round(flt(a.get("unrequested_remainder") or 0.0), 4),
        )
        for a in (allocations or [])
    ]
    alloc_items.sort(key=lambda x: x[0])
    group_items = []
    if groups:
        group_items = [
            (
                str(g.get("item_code") or "").strip(),
                str(g.get("source_warehouse") or "").strip(),
                round(flt(g.get("physical_stock") or 0.0), 4),
                round(flt(g.get("available_pool") or 0.0), 4),
                round(flt(g.get("outstanding_reservations") or 0.0), 4),
            )
            for g in groups
        ]
        group_items.sort(key=lambda x: (x[0], x[1]))
    canonical = json.dumps({"a": alloc_items, "g": group_items}, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@frappe.whitelist()
def preview_handover_request(work_orders, company=None):
    """Additive read-only preview of proposed GBJ handover request allocations.
    Calculates eligible unrequested quantities, physical stock per source warehouse,
    active reservations (including external MRs like R&D), and deterministic per-WO allocations
    sorted by Work Order name.
    """
    _require_role(
        ROLES_GUDANG,
        _("Hanya peran gudang (Stock User / Stock Manager / Gudang Barang Jadi) yang dapat melihat preview permintaan serah terima."),
    )
    if isinstance(work_orders, str):
        try:
            work_orders = json.loads(work_orders)
        except Exception:
            work_orders = [work_orders]
    work_orders = sorted({str(w).strip() for w in (work_orders or []) if str(w or "").strip()})
    if not work_orders:
        return {"ok": True, "fingerprint": "", "allocations": [], "groups": []}

    frappe.has_permission("Work Order", "read", throw=True)
    for w in work_orders:
        frappe.has_permission("Work Order", "read", doc=w, throw=True)
    wos = [frappe.get_doc("Work Order", w) for w in work_orders]

    target_wh = _target_warehouse()
    if not target_wh:
        transferred_by_wo = {}
    else:
        transferred_by_wo = dict(
            frappe.db.sql(
                """select mri.custom_work_order, coalesce(sum(sed.transfer_qty), 0)
                     from `tabStock Entry Detail` sed
                     join `tabMaterial Request Item` mri on mri.name = sed.material_request_item
                    where mri.custom_work_order in %s
                      and sed.docstatus = 1
                      and coalesce(sed.t_warehouse, '') = %s
                    group by mri.custom_work_order""",
                (tuple(work_orders), target_wh),
                as_list=True,
            )
        )

    active_mrs = frappe.db.sql(
        """select mri.custom_work_order,
                  greatest(0.0, mri.stock_qty - coalesce((
                      select sum(sed.transfer_qty)
                        from `tabStock Entry Detail` sed
                       where sed.material_request = mr.name
                         and sed.material_request_item = mri.name
                         and sed.docstatus = 1
                  ), 0.0)) as outstanding_qty
             from `tabMaterial Request Item` mri
             join `tabMaterial Request` mr on mr.name = mri.parent
            where mri.custom_work_order in %s
              and mr.docstatus = 1
              and mr.status not in ('Stopped', 'Transferred', 'Issued')
              and mr.material_request_type = 'Material Transfer'""",
        (tuple(work_orders),),
        as_dict=True,
    )
    active_req_by_wo = defaultdict(float)
    for row in active_mrs:
        active_req_by_wo[row["custom_work_order"]] += flt(row["outstanding_qty"])

    wo_rows = _wo_lot_rows(work_orders)
    lot_by_wo = {r.work_order: r for r in wo_rows}

    groups = defaultdict(list)
    for wo in wos:
        lot = lot_by_wo.get(wo.name)
        source_wh = _pool_warehouse(lot) if lot else wo.fg_warehouse
        produced = flt(wo.produced_qty)
        transferred = flt(transferred_by_wo.get(wo.name, 0.0))
        active_req = flt(active_req_by_wo.get(wo.name, 0.0))
        eligible_unrequested = max(0.0, produced - transferred - active_req)
        allocation_limit = eligible_unrequested
        if lot and lot.unsupported:
            allocation_limit = 0.0
        elif lot and not lot.batchless:
            allocation_limit = max(0.0, flt(get_batch_qty(lot.batch, source_wh) or 0) - active_req)
        groups[(wo.production_item, source_wh)].append({
            "work_order": wo.name,
            "produced_qty": produced,
            "transferred_qty": transferred,
            "active_requested_qty": active_req,
            "unrequested_qty": eligible_unrequested,
            "allocation_limit": allocation_limit,
            "target_warehouse": target_wh,
            "company": wo.company,
            "stock_uom": lot.stock_uom if lot else wo.stock_uom,
            "display_uom": lot.display_uom if lot else None,
            "qty_in_pack": lot.qty_in_pack if lot else 1,
            "batch": lot.batch if lot else None,
            "source_warehouse": source_wh,
            "item_code": wo.production_item,
        })

    allocations_out = []
    group_summaries = []

    for (item_code, source_wh), members in groups.items():
        physical = _item_stock(item_code, source_wh)
        reserved = _pool_reserved_now(item_code, source_wh)
        available = max(0.0, physical - reserved)

        allocs, remaining_budget = _allocate_pool_budget(members, available)

        ext_res_query = frappe.db.sql(
            """select mr.name, mr.schedule_date, mri.warehouse as target_warehouse,
                      coalesce(nullif(mri.from_warehouse, ''), nullif(mr.set_from_warehouse, '')) as source_warehouse,
                      greatest(0.0, mri.stock_qty - coalesce((
                          select sum(sed.transfer_qty)
                            from `tabStock Entry Detail` sed
                           where sed.material_request = mr.name
                             and sed.material_request_item = mri.name
                             and sed.docstatus = 1
                      ), 0.0)) as outstanding_qty
                 from `tabMaterial Request Item` mri
                 join `tabMaterial Request` mr on mr.name = mri.parent
                where mri.item_code = %s
                  and (coalesce(nullif(mri.from_warehouse, ''), nullif(mr.set_from_warehouse, '')) = %s
                       or coalesce(nullif(mri.from_warehouse, ''), nullif(mr.set_from_warehouse, '')) is null)
                  and mr.docstatus = 1
                  and mr.status not in ('Stopped', 'Transferred', 'Issued')
                  and mr.material_request_type = 'Material Transfer'
                  and (mri.custom_work_order is null or mri.custom_work_order = '' or mri.custom_work_order not in %s)""",
            (item_code, source_wh, tuple(work_orders)),
            as_dict=True,
        )
        ext_reservations = []
        unresolved_reservations = []
        can_read_mr = frappe.has_permission("Material Request", "read")
        for er in ext_res_query:
            if flt(er["outstanding_qty"]) > 0:
                can_read_doc = can_read_mr and frappe.has_permission("Material Request", "read", doc=er["name"])
                unresolved = "source_warehouse" in er and not er["source_warehouse"]
                details = {
                    "material_request": er["name"] if can_read_doc else "Restricted",
                    "target_warehouse": er["target_warehouse"] if can_read_doc else "Restricted",
                    "source_warehouse": None if unresolved else source_wh,
                    "quantity": flt(er["outstanding_qty"]),
                }
                (unresolved_reservations if unresolved else ext_reservations).append(details)

        group_summaries.append({
            "item_code": item_code,
            "source_warehouse": source_wh,
            "physical_stock": physical,
            "stock_uom": frappe.db.get_value("Item", item_code, "stock_uom"),
            "outstanding_reservations": reserved,
            "available_pool": available,
            "remaining_budget": remaining_budget,
            "external_reservations": ext_reservations,
            "unresolved_reservations": unresolved_reservations,
        })

        for m in members:
            al = allocs[m["work_order"]]
            item_summary = {
                "work_order": m["work_order"],
                "item_code": m["item_code"],
                "source_warehouse": m["source_warehouse"],
                "target_warehouse": m["target_warehouse"],
                "company": m["company"],
                "stock_uom": m["stock_uom"],
                "display_uom": m["display_uom"],
                "qty_in_pack": m["qty_in_pack"],
                "batch": m["batch"],
                "produced_qty": m["produced_qty"],
                "transferred_qty": m["transferred_qty"],
                "active_requested_qty": m["active_requested_qty"],
                "allocated_qty": al["allocated_qty"],
                "unrequested_remainder": al["unrequested_remainder"],
            }
            item_summary["fingerprint"] = _compute_preview_fingerprint([item_summary], [group_summaries[-1]])
            allocations_out.append(item_summary)

    global_fingerprint = _compute_preview_fingerprint(allocations_out, group_summaries)
    return {
        "ok": True,
        "fingerprint": global_fingerprint,
        "allocations": allocations_out,
        "groups": group_summaries,
    }


@frappe.whitelist()
@_retry_on_deadlock
def create_request(work_order, requested_qty=None, company=None, preview_fingerprint=None):
    """Gudang side (Stock User / Stock Manager / Gudang Barang Jadi): submit a Material Transfer
    request for the Work Order's produced or confirmed allocation qty. The source warehouse
    is the handover source setting when set, else the SE-derived lot warehouse (R2). One ACTIVE
    (unshipped, unstopped) request per Work Order; a duplicate throws.

    FU96: the box payload is RETIRED — this is the only (qty-only) contract.
    Legacy callers that still send box args are accepted: frappe's get_newargs
    filters unknown kwargs before the function is invoked. The native MR is
    inserted + submitted, then the Work Order summary (Link + status) is
    written atomically — one transaction, zero writes on any failure."""
    _require_role(
        ROLES_GUDANG,
        _("Hanya peran gudang (Stock User / Stock Manager / Gudang Barang Jadi) yang dapat membuat permintaan serah terima."),
    )
    frappe.has_permission("Material Request", "create", throw=True)

    frappe.db.get_value("Work Order", work_order, "name", for_update=True)  # row lock
    wo = frappe.get_doc("Work Order", work_order)
    target = _target_warehouse_or_throw(wo.company)
    target_wh = target
    transferred = flt(frappe.db.sql(
        """select coalesce(sum(sed.transfer_qty), 0)
             from `tabStock Entry Detail` sed
             join `tabMaterial Request Item` mri on mri.name = sed.material_request_item
            where mri.custom_work_order = %s
              and sed.docstatus = 1
              and coalesce(sed.t_warehouse, '') = %s""",
        (work_order, target_wh),
    )[0][0])
    active_req = flt(frappe.db.sql(
        """select coalesce(sum(
               greatest(0.0, mri.stock_qty - coalesce((
                   select sum(sed.transfer_qty)
                     from `tabStock Entry Detail` sed
                    where sed.material_request = mr.name
                      and sed.material_request_item = mri.name
                      and sed.docstatus = 1
               ), 0.0))
           ), 0.0)
              from `tabMaterial Request Item` mri
              join `tabMaterial Request` mr on mr.name = mri.parent
             where mri.custom_work_order = %s
               and mr.docstatus = 1
               and mr.status not in ('Stopped', 'Transferred', 'Issued')
               and mr.material_request_type = 'Material Transfer'""",
        (work_order,),
    )[0][0])
    eligible_unrequested = max(0.0, flt(wo.produced_qty) - transferred - active_req)

    if preview_fingerprint:
        # Re-derive preview for this work order under lock to verify context binding
        preview_data = preview_handover_request([work_order], company=wo.company)
        alloc = next((a for a in preview_data.get("allocations", []) if a["work_order"] == work_order), None)
        valid_fps = {preview_data.get("fingerprint")}
        if alloc:
            valid_fps.add(alloc.get("fingerprint"))
        if preview_fingerprint not in valid_fps:
            frappe.throw(
                _("Status alokasi atau stok telah berubah sejak preview. Muat ulang halaman.")
            )
    if requested_qty is not None:
        try:
            amount = flt(requested_qty)
        except Exception:
            amount = None
        if amount is None or not math.isfinite(amount):
            frappe.throw(
                _("Kuantitas yang diminta ({0}) tidak valid.").format(requested_qty),
                frappe.ValidationError,
            )
        if amount <= 0:
            frappe.throw(
                _("Kuantitas yang diminta ({0}) harus lebih besar dari 0.").format(amount),
                frappe.ValidationError,
            )
        if amount > eligible_unrequested:
            frappe.throw(
                _("Kuantitas yang diminta ({0}) melebihi sisa hasil Work Order {1} ({2}). Muat ulang halaman.").format(
                    amount, work_order, eligible_unrequested
                ),
                frappe.ValidationError,
            )
    else:
        amount = eligible_unrequested

    if amount <= 0 or not math.isfinite(amount):
        frappe.throw(
            _("Work Order {0} tidak memiliki sisa hasil yang dapat diminta.").format(work_order),
            frappe.ValidationError,
        )
    lot = _checked_lot(work_order)
    if lot.batchless:
        frappe.db.get_value("Item", wo.production_item, "name", for_update=True)
        lot = _checked_lot(work_order)  # re-derive under the pool lock

    # R3: one active request per WO — re-derived under the lock so racing
    # creates serialize on the row lock (stopped/draft/cancelled never block)
    for r in _requests([lot], wo_names=[work_order]):
        if r["lane"] == LANE_REQUEST and not r["flag"]:
            frappe.throw(
                _("Work Order {0} sudah punya permintaan aktif ({1}).").format(work_order, r["mr"])
            )

    link_now = frappe.db.get_value(
        "Work Order", wo.name, "custom_handover_material_request", for_update=True
    )
    if link_now and _active_mr_now(link_now):
        frappe.throw(
            _("Work Order {0} sudah punya permintaan aktif ({1}).").format(work_order, link_now)
        )

    expected_units = _expected_unit_count(wo, lot, amount)
    unit = lot.display_uom or lot.stock_uom

    stock_uom = lot.stock_uom or frappe.db.get_value("Item", wo.production_item, "stock_uom")
    _enforce_whole_uom(amount, stock_uom, "Qty")
    available = flt(lot.available_qty)
    source = _pool_warehouse(lot)
    if lot.batchless:
        available = min(available, flt(lot.physical_qty) - _pool_reserved_now(wo.production_item, source, for_update=True))
    if amount > available:
        frappe.throw(
            _("Qty melebihi stok tersedia: diminta {0}, tersedia {1}. Muat ulang halaman.").format(amount, available)
        )

    mr = _insert_submitted_handover_mr([(wo, amount, stock_uom, source)], target, wo.company)
    return {
        "ok": True,
        "material_request": mr.name,
        "qty": amount,
        "unit": unit,
        "expected_unit_count": expected_units,
        "board": _build_board(company),  # FU95: papan balik ikut filter company klien
    }


def _cancel_unsent_request(material_request):
    """Shared cancel body (cancel_request + cancel_group_request): lock the
    bound Work Order FIRST (no MR->WO lock inversion), re-read the MR under
    the lock, refuse abnormal docstatus / submitted-SE evidence, native-cancel
    and clear the summary through document-derived synchronization in the same
    transaction. Returns the bound Work Order names (bulk MR: all of them)."""
    wo_names = sorted(set(frappe.get_all(
        "Material Request Item",
        filters={"parent": material_request, "custom_work_order": ("is", "set")},
        pluck="custom_work_order",
    )))
    if wo_names:
        # the summary gate reads + writes these Work Orders below, and neither
        # get_doc nor db reads check permissions — verify the WO read grant
        # explicitly (same policy as the board: no read, no handover access)
        frappe.has_permission("Work Order", "read", throw=True)
        for wo_name in wo_names:  # lock WOs first, sorted (deadlock-safe)
            frappe.db.get_value("Work Order", wo_name, "name", for_update=True)
    mr = frappe.get_doc("Material Request", material_request)  # re-read under the lock
    frappe.has_permission("Material Request", "cancel", doc=mr, throw=True)
    if mr.docstatus != 1:
        frappe.throw(_("Permintaan {0} belum terkirim, jadi tidak bisa dibatalkan.").format(material_request))
    sent = _sent_se_by_mr([material_request])
    if sent:
        frappe.throw(
            _("Permintaan {0} sudah terkirim ({1}); tidak bisa dibatalkan.").format(
                material_request,
                get_link_to_form("Stock Entry", sent[material_request].name),
            )
        )
    mr.cancel()  # native; permission-checked as session user
    _sync_handover_summary(wo_names)  # fail-honest: clears Link/status
    return wo_names


@frappe.whitelist()
@_retry_on_deadlock
def cancel_request(material_request, company=None):
    """Gudang side (Stock User / Stock Manager / Gudang Barang Jadi): cancel an UNSENT request
    (native cancel; audit history stays, reservation is released). The Work
    Order lock is taken FIRST (no MR->WO lock inversion), then the MR is
    re-read and its submitted-SE evidence re-checked; the summary (Link +
    status) clears through document-derived synchronization in the same
    transaction. W19: a member of a shared plan group may only be cancelled
    through cancel_group_request while any sibling member is still active."""
    _require_role(
        ROLES_GUDANG,
        _("Hanya peran gudang (Stock User / Stock Manager / Gudang Barang Jadi) yang dapat membatalkan permintaan serah terima."),
    )
    plan = frappe.db.get_value("Material Request", material_request, "custom_handover_box_plan")
    if plan:
        siblings = frappe.db.count(
            "Material Request",
            {
                "custom_handover_box_plan": plan,
                "docstatus": 1,
                "name": ("!=", material_request),
            },
        )
        if siblings:
            frappe.throw(_("MR ini bagian grup serah terima ({0}); batalkan seluruh grup.").format(plan))
    _cancel_unsent_request(material_request)
    return {"ok": True, "material_request": material_request, "board": _build_board(company)}


def _json_list(value, label):
    """Whitelisted endpoints receive JSON strings over HTTP; direct calls may
    pass parsed lists. Everything else is rejected before any read/write."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            frappe.throw(_("{0} harus JSON array yang valid.").format(label))
    if not isinstance(value, list):
        frappe.throw(_("{0} harus JSON array yang valid.").format(label))
    return value


@frappe.whitelist()
@_retry_on_deadlock
def create_group_request(work_orders, allocations=None, company=None, preview_fingerprint=None):
    """Gudang side: request a GROUP of Work Orders of the SAME item as ONE
    Material Request with one row per Work Order.
    Supports optional explicit per-WO allocations dict/JSON {work_order: qty}.
    When allocations are provided, rows with 0 allocation are skipped;
    if all rows are 0, throws an error.
    Without explicit allocations, falls back to full produced_qty for each member.

    Contract: role gate + every validation under member-WO locks and pool locks
    BEFORE any write; then ONE transaction inserts the submitted MR."""
    _require_role(
        ROLES_GUDANG,
        _("Hanya peran gudang (Stock User / Stock Manager / Gudang Barang Jadi) yang dapat membuat permintaan serah terima."),
    )
    frappe.has_permission("Material Request", "create", throw=True)

    wo_names = sorted({str(n).strip() for n in _json_list(work_orders, "Work Orders") if str(n or "").strip()})
    if len(wo_names) < 2:
        frappe.throw(_("Grup serah terima butuh minimal 2 Work Order."))

    alloc_map = None
    if allocations:
        if isinstance(allocations, str):
            try:
                alloc_map = json.loads(allocations)
            except Exception:
                alloc_map = None
        elif isinstance(allocations, dict):
            alloc_map = allocations

    # lock every member WO first, sorted-name order (deadlock-safe)
    wos = []
    for name in wo_names:
        frappe.db.get_value("Work Order", name, "name", for_update=True)  # row lock
        wo = frappe.get_doc("Work Order", name)
        if wo.docstatus != 1:
            frappe.throw(_("Work Order {0} belum aktif.").format(name))
        if flt(wo.produced_qty) <= 0:
            frappe.throw(
                _("Work Order {0} belum punya hasil barang jadi (produced qty 0).").format(name)
            )
        wos.append(wo)

    items = sorted({wo.production_item for wo in wos})
    if len(items) > 1:
        frappe.throw(
            _("Semua Work Order dalam grup harus satu item (ditemukan {0} item: {1}).").format(
                len(items), ", ".join(items)
            )
        )
    companies = sorted({wo.company for wo in wos})
    if len(companies) > 1:
        frappe.throw(
            _("Semua Work Order dalam grup harus satu company (ditemukan: {0}).").format(", ".join(companies))
        )
    target = _target_warehouse_or_throw()
    item_code = items[0]
    if not frappe.db.get_value("Item", item_code, "has_batch_no"):
        frappe.db.get_value("Item", item_code, "name", for_update=True)

    if preview_fingerprint:
        preview_data = preview_handover_request(wo_names, company=wos[0].company)
        expected_fp = preview_data.get("fingerprint")
        if preview_fingerprint != expected_fp:
            frappe.throw(
                _("Status alokasi atau stok telah berubah sejak preview. Muat ulang halaman.")
            )

    members = []
    expected_total = 0
    claimed_by_source = defaultdict(float)

    for wo in wos:
        link_now = frappe.db.get_value(
            "Work Order", wo.name, "custom_handover_material_request", for_update=True
        )
        if link_now and _active_mr_now(link_now):
            frappe.throw(
                _("Work Order {0} sudah punya permintaan aktif ({1}).").format(wo.name, link_now)
            )

        target_wh = _target_warehouse(wo.company) or target
        transferred = flt(frappe.db.sql(
            """select coalesce(sum(sed.transfer_qty), 0)
                 from `tabStock Entry Detail` sed
                 join `tabMaterial Request Item` mri on mri.name = sed.material_request_item
                where mri.custom_work_order = %s
                  and sed.docstatus = 1
                  and coalesce(sed.t_warehouse, '') = %s""",
            (wo.name, target_wh),
        )[0][0])
        active_req = flt(frappe.db.sql(
            """select coalesce(sum(
                   greatest(0.0, mri.stock_qty - coalesce((
                       select sum(sed.transfer_qty)
                         from `tabStock Entry Detail` sed
                        where sed.material_request = mr.name
                          and sed.material_request_item = mri.name
                          and sed.docstatus = 1
                   ), 0.0))
               ), 0.0)
                  from `tabMaterial Request Item` mri
                  join `tabMaterial Request` mr on mr.name = mri.parent
                 where mri.custom_work_order = %s
                   and mr.docstatus = 1
                   and mr.status not in ('Stopped', 'Transferred', 'Issued')
                   and mr.material_request_type = 'Material Transfer'""",
            (wo.name,),
        )[0][0])
        eligible_unrequested = max(0.0, flt(wo.produced_qty) - transferred - active_req)

        if alloc_map is not None:
            raw_val = alloc_map.get(wo.name, 0.0)
            try:
                amount = flt(raw_val)
            except Exception:
                amount = None
            if amount is None or not math.isfinite(amount):
                frappe.throw(
                    _("Alokasi untuk Work Order {0} tidak valid: {1}").format(wo.name, raw_val),
                    frappe.ValidationError,
                )
            if amount <= 0:
                continue  # skip zero-allocation row
            if amount > eligible_unrequested:
                frappe.throw(
                    _("Kuantitas yang diminta ({0}) melebihi sisa hasil Work Order {1} ({2}). Muat ulang halaman.").format(
                        amount, wo.name, eligible_unrequested
                    ),
                    frappe.ValidationError,
                )
        else:
            amount = eligible_unrequested
            if amount <= 0 or not math.isfinite(amount):
                continue

        # after the skip: a member previewed at 0 may have no lot left at all
        lot = _checked_lot(wo.name)
        expected = _expected_unit_count(wo, lot, amount)
        stock_uom = lot.stock_uom or frappe.db.get_value("Item", wo.production_item, "stock_uom")
        _enforce_whole_uom(amount, stock_uom, "Qty")
        available = flt(lot.available_qty)
        source = _pool_warehouse(lot)
        if lot.batchless:
            available = min(
                available,
                flt(lot.physical_qty) - _pool_reserved_now(wo.production_item, source, for_update=True) - claimed_by_source[source],
            )
        if amount > available:
            frappe.throw(
                _("Qty melebihi lot tersedia untuk {0}: diminta {1}, tersedia {2}.").format(
                    wo.name, amount, available
                )
            )
        claimed_by_source[source] += amount
        members.append((wo, amount, stock_uom, lot))
        expected_total += expected

    if not members:
        frappe.throw(_("Semua alokasi bernilai 0; tidak ada permintaan yang dibuat."))

    mr = _insert_submitted_handover_mr(
        [(wo, amount, stock_uom, _pool_warehouse(lot)) for wo, amount, stock_uom, lot in members],
        target,
        wos[0].company,
    )
    return {
        "ok": True,
        "material_request": mr.name,
        "material_requests": [mr.name],  # compat: pre-2026-10-10 clients
        "box_plan": None,
        "expected_unit_count": expected_total,
        "board": _build_board(company),  # FU95: papan balik ikut filter company klien
    }


@frappe.whitelist()
@_retry_on_deadlock
def cancel_group_request(box_plan, company=None):
    """Gudang side: cancel EVERY still-active member Material Request of a
    Handover Box Plan in one transaction (the group guard of cancel_request
    never lets the members die one by one). Members already shipped keep their
    Stock Entry evidence and are left alone; cancelled/stopped/draft members
    are skipped; the plan document remains as the audit record of the grouped
    requests. Returns the per-member outcome."""
    _require_role(
        ROLES_GUDANG,
        _("Hanya peran gudang (Stock User / Stock Manager / Gudang Barang Jadi) yang dapat membatalkan permintaan serah terima."),
    )
    if not box_plan or not frappe.db.exists("Handover Box Plan", box_plan):
        frappe.throw(_("Handover Box Plan {0} tidak ditemukan.").format(box_plan))
    mr_names = sorted(
        frappe.get_all(
            "Material Request", filters={"custom_handover_box_plan": box_plan}, pluck="name"
        )
    )
    wo_names = sorted(
        {
            w
            for w in frappe.get_all(
                "Material Request Item",
                filters={"parent": ("in", mr_names), "custom_work_order": ("is", "set")},
                pluck="custom_work_order",
            )
            if w
        }
    )
    frappe.has_permission("Work Order", "read", throw=True)
    # lock every member WO first, sorted-name order (same order as creation)
    for wo_name in wo_names:
        frappe.db.get_value("Work Order", wo_name, "name", for_update=True)
    cancelled, skipped = [], []
    for mr_name in mr_names:
        if not _active_mr_now(mr_name):
            skipped.append(mr_name)  # shipped / cancelled / stopped: left alone
            continue
        _cancel_unsent_request(mr_name)
        cancelled.append(mr_name)
    return {
        "ok": True,
        "box_plan": box_plan,
        "cancelled": cancelled,
        "skipped": skipped,
        "board": _build_board(company),  # FU95: papan balik ikut filter company klien
    }


def _handover_mr(material_request):
    """Load the handover MR: read-gated, docstatus 1, every row Work Order-bound."""
    mr = frappe.get_doc("Material Request", material_request)
    frappe.has_permission("Material Request", "read", doc=mr, throw=True)
    if mr.docstatus != 1:
        frappe.throw(_("Material Request {0} belum aktif.").format(material_request))
    if not mr.items or not all(i.get("custom_work_order") for i in mr.items):
        frappe.throw(_("Material Request {0} bukan permintaan serah terima (tanpa Work Order).").format(material_request))
    return mr


@frappe.whitelist()
def save_post_packing(material_request):
    """Compatibility only (T35/FU96): the verify step is retired entirely
    (boxes too). Always rejects with the reload message BEFORE any lock/write
    so an old cached client can neither write retired state nor half-mutate a
    request. Legacy callers sending box_1/box_2 are filtered by
    frappe.get_newargs before invocation."""
    frappe.throw(_(
        "Verifikasi Siap Kirim sudah dipindahkan ke form Request Gudang. "
        "Muat ulang halaman sebelum melanjutkan."
    ))


@frappe.whitelist()
@_retry_on_deadlock
def send_handover(material_request, company=None):
    """Manufacturing User/Manager: create + submit the handover Stock Entry moving the
    MR's requested qty (= the WO's produced_qty at request time, R6) from the
    source warehouse to the handover target. ONE transaction: any failure rolls
    back with zero partial documents. Batch-tracked rows keep batch_no (the
    batch seam); the shortage pre-check reads the ROUTE from-warehouse (FU29),
    so a lot whose stock lives elsewhere is refused here with a clear message —
    native submit validation stays as the backstop in the same transaction.
    T35: no postpacking gate anymore — a submitted request is sendable; the
    Work Order summary (Link + boxes) is preserved and the status synchronized
    to Terkirim after the native submit.
    FU95: `company` = filter company global klien — hanya mem-scope board yang
    dibalikkan (papan tampil tetap tersaring setelah aksi)."""
    _require_role(
        (ROLE_PRODUKSI, ROLE_MANAJER_PRODUKSI),
        _("Hanya Manufacturing User atau Manufacturing Manager yang dapat mengirim serah terima."),
    )
    mr = _handover_mr(material_request)
    frappe.has_permission("Stock Entry", "create", throw=True)
    frappe.has_permission("Stock Entry", "submit", throw=True)

    wo_names = sorted({i.custom_work_order for i in mr.items if i.custom_work_order})

    # Consistent lock order across all endpoints: WO (sorted) -> MR (no MR->WO inversion)
    for wo_name in sorted(wo_names):  # row locks, sorted-name order (deadlock-safe)
        frappe.db.get_value("Work Order", wo_name, "name", for_update=True)
    frappe.db.get_value("Material Request", material_request, "name", for_update=True)

    mr = frappe.get_doc("Material Request", material_request)  # re-read under the lock
    if mr.docstatus != 1:
        frappe.throw(_("Permintaan {0} belum aktif atau sudah dibatalkan.").format(material_request))
    if mr.status in ("Stopped", "Transferred") or flt(mr.get("per_ordered") or 0.0) >= 100.0:
        frappe.throw(
            _("Permintaan {0} sudah selesai ditransfer atau dihentikan.").format(material_request)
        )

    qty_by_row = {i.name: flt(i.stock_qty or i.qty) for i in mr.items}
    if not qty_by_row or any(q <= 0 for q in qty_by_row.values()):
        frappe.throw(_("Qty permintaan {0} tidak valid.").format(material_request))

    lots = {w: _checked_lot(w) for w in wo_names}  # §4.9 unsupported error BEFORE any mutation

    # Native MR->SE mapping handles remaining unfulfilled quantities across sequential sends
    se = frappe.get_doc(make_mr_stock_entry(mr.name))
    if not getattr(se, "items", None):
        frappe.throw(
            _("Permintaan {0} tidak memiliki sisa kuantitas untuk ditransfer.").format(material_request)
        )

    mri_by_name = {i.name: i for i in mr.items}
    fulfilled_by_row = dict(frappe.db.sql(
        """select sed.material_request_item, sum(sed.transfer_qty)
             from `tabStock Entry Detail` sed
            where sed.material_request = %s and sed.docstatus = 1
            group by sed.material_request_item""",
        (mr.name,),
    ))
    outstanding_by_row = {
        name: max(0.0, qty - flt(fulfilled_by_row.get(name, 0)))
        for name, qty in qty_by_row.items()
    }
    mapped_by_row = defaultdict(float)
    for row in se.items:
        mri = mri_by_name.get(row.material_request_item)
        wo_name = mri.custom_work_order if mri else None
        lot = lots.get(wo_name) if wo_name else None
        row.transfer_qty = flt(row.qty) * flt(row.conversion_factor or 1)
        mapped_by_row[row.material_request_item] += row.transfer_qty
        if mri is None or row.transfer_qty <= 0 or mapped_by_row[row.material_request_item] > outstanding_by_row[mri.name] + 1e-9:
            frappe.throw(_("Sisa transfer native tidak sesuai bukti transfer aktual. Muat ulang dan periksa permintaan."))
        if lot and not lot.batchless:
            row.use_serial_batch_fields = 1  # v16: old batch field -> bundle at submit (T21)
            row.batch_no = lot.batch

    if any(abs(mapped_by_row.get(name, 0.0) - outstanding) > 1e-9
           for name, outstanding in outstanding_by_row.items()):
        frappe.throw(_("Sisa transfer native tidak sesuai bukti transfer aktual. Muat ulang dan periksa permintaan."))

    # FU29: pre-check against the ROUTE origin (s_warehouse)
    need = {}
    for row in se.items:
        mri = mri_by_name.get(row.material_request_item)
        wo_name = mri.custom_work_order if mri else None
        lot = lots.get(wo_name) if wo_name else None
        route_wh = row.s_warehouse or (mri.from_warehouse if mri else None) or mr.set_from_warehouse or (lot.warehouse if lot else None)
        if lot and not lot.batchless:
            key = ("b", lot.batch, route_wh)
        else:
            key = ("i", row.item_code, route_wh)
        need[key] = need.get(key, 0.0) + flt(row.transfer_qty)

    own_reservations = defaultdict(float)
    for mri in mr.items:
        source = mri.from_warehouse or mr.set_from_warehouse
        own_reservations[(mri.item_code, source)] += outstanding_by_row[mri.name]

    for (kind, ref, route_wh), qty in need.items():
        physical = _item_stock(ref, route_wh) if kind == "i" else flt(get_batch_qty(ref, route_wh) or 0)
        available = physical
        if kind == "i":
            other_reservations = max(0.0, _pool_reserved_now(ref, route_wh, for_update=True) - own_reservations[(ref, route_wh)])
            available -= other_reservations
        if available < qty:  # preserve other requests as well as native physical-stock validation
            frappe.throw(
                _("Stok {0} di gudang asal {1} hanya {2}; tidak bisa mengirim {3}.").format(
                    ref if kind == "i" else f"batch {ref}", route_wh, physical, qty
                )
            )

    se.insert()
    se.submit()  # native shortage/valuation failures roll the whole request back

    _sync_handover_summary(wo_names)
    batches = {lot.batch for lot in lots.values()}
    batch = next(iter(batches)) if len(batches) == 1 else None
    qty = sum(flt(r.transfer_qty or r.qty) for r in se.items)

    return {
        "ok": True,
        "material_request": material_request,
        "stock_entry": se.name,
        "batch": batch,
        "qty": qty,
        "work_orders": wo_names,
        "board": _build_board(company),  # FU95: papan balik ikut filter company klien
    }

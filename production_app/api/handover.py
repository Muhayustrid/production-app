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
#   Requests carry the Work Order's FULL produced_qty (R3); boxes are Float kg
#   only (R4/R8); send moves the MR's requested qty and never stops the MR (R6).

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_link_to_form, now

from erpnext.stock.doctype.batch.batch import get_batch_qty
from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
	get_available_batches,
	get_stock_ledgers_batches,
	update_available_batches,
)

from production_app.api.work_order import _enrich_units

# Sisi gudang serah terima: role kustom ATAU Stock User native (keputusan user
# 2026-09-14: Manufacturing User + Stock User = dua sisi sekaligus; Stock User
# saja = hanya halaman Stock Entry dan hanya boleh membuat request).
ROLE_GUDANG = "Gudang Barang Jadi"
ROLES_GUDANG = ("Gudang Barang Jadi", "Stock User")
ROLE_PRODUKSI = "Manufacturing User"

LANE_REQUEST = "request"
LANE_SIAP = "siap_kirim"
LANE_KIRIM = "terkirim"


def _time_str(value):
    """Zero-padded HH:MM:SS for DB Time values (arrive as timedelta; str()
    renders single-digit hours, which would mis-sort FIFO across hours)."""
    if hasattr(value, "total_seconds"):
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return str(value)


@frappe.whitelist()
def handover_board():
	"""Four-lane Serah Terima board (Cold Storage lots -> Request Gudang ->
	Siap Kirim -> Terkirim) for the session user."""
	return _build_board()


def _build_board():
	"""Board payload; T24 actions return this as the refreshed board."""
	wo_rows = _wo_lot_rows()
	requests = _requests(wo_rows)
	return {
		"target_warehouse": _target_warehouse(),
		"source_warehouse": _source_warehouse(),
		"roles": _roles(),
		"lots": _lots(wo_rows, requests),
		"requests": requests,
	}


def _target_warehouse():
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
	lot warehouse; when unset the fallback keeps current behavior (R2)."""
	return _source_warehouse() or lot_row.warehouse


def _roles():
	roles = frappe.get_roles()
	return {
		"is_gudang": any(r in roles for r in ROLES_GUDANG),
		"is_produksi": ROLE_PRODUKSI in roles,
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


def _wo_lot_rows(wo_names=None):
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
				"fg_warehouse", "creation",
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
				"item_code": w.production_item,
				"production_item": w.production_item,  # consumed by _enrich_units
				"custom_uom": None,
				"qty": flt(w.qty),
				"produced_qty": flt(w.produced_qty),
				"adonan_ke": w.custom_adonan_ke,
				"warehouse": cur["warehouse"] or w.fg_warehouse,
				"entered_at": str(cur["entered_at"]),
				"completed_at": cur["completed_at"],
				"physical_qty": None,
				"reserved_qty": None,
				"available_qty": None,
				"unsupported": False,
				"unsupported_reason": None,
				"has_older_lot_same_item": False,
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


def _requests(wo_rows, wo_names=None, item_codes=None):
	"""Handover request rows — one per Material Request bound to a Work Order
	via Material Request Item.custom_work_order (T22 field).

	Lane mapping (documents only): terkirim = a submitted Stock Entry exists
	against the MR (Stock Entry Detail `material_request` link, T21); else
	siap_kirim = submitted + postpacking confirmed; else request = submitted
	and not stopped. Edge states are never omitted and never raise: draft and
	cancelled MRs come back with lane=None plus a flag; a stopped MR without
	SE is a dead request (needs a manual desk unstop) parked in the request
	lane with flag="stopped" — visible, but reserving nothing (§4.3).
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
		mrs = frappe.get_list(
			"Material Request",
			filters={
				"name": ("in", sorted(set(mr_names))),
				"material_request_type": "Material Transfer",
			},
			fields=[
				"name", "docstatus", "status", "owner", "creation",
				"set_from_warehouse", "set_warehouse",
				"custom_box_1", "custom_box_2",
				"custom_good_qty_postpacking", "custom_reject_qty_postpacking",
				"custom_trial_qty_postpacking", "custom_sisa_qty_postpacking",
				"custom_jam_packing", "custom_qc_packing",
				"custom_postpacking_confirmed",
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
			"parent", "item_code", "item_name", "qty", "stock_qty", "stock_uom",
			"custom_work_order",
		],
		order_by="idx asc",
	):
		bound_items.setdefault(it.parent, []).append(it)
	if not bound_items:
		return []

	wo_by_name = {r.work_order: r for r in wo_rows}
	sent = _sent_se_by_mr([m.name for m in mrs])
	users = _user_names(
		{m.owner for m in mrs} | {m.custom_qc_packing for m in mrs if m.custom_qc_packing}
	)

	rows = []
	for m in mrs:
		items = bound_items.get(m.name)
		if not items:
			continue  # not a handover MR (no Work Order binding)
		first = items[0]
		se = sent.get(m.name)
		lane, flag = None, None
		if m.docstatus == 2:
			flag = "cancelled"  # leaves the lanes, stays on the board (audit)
		elif m.docstatus == 0:
			flag = "draft"  # not yet submitted — no reservation, no action
		elif se:
			lane = LANE_KIRIM
		elif m.status == "Stopped":
			lane, flag = LANE_REQUEST, "stopped"
		elif m.custom_postpacking_confirmed:
			lane = LANE_SIAP
		else:
			lane = LANE_REQUEST
		lot = wo_by_name.get(first.custom_work_order)
		qty_in_pack, adonan_ke = (lot.qty_in_pack, lot.adonan_ke) if lot else (None, None)
		if lot is None:
			# WO has no lot row (never manufactured / not submitted): the mockup
			# dialogs still read qtyInPack + adonan off the request's item, so
			# resolve it the same way instead of handing the UI a blank factor
			enriched = frappe._dict(production_item=first.item_code, custom_uom=None)
			_enrich_units([enriched])
			qty_in_pack = flt(enriched.display_conversion_factor or 1)
		rows.append(
			{
				"mr": m.name,
				"docstatus": m.docstatus,
				"status": m.status,
				"lane": lane,
				"flag": flag,
				"item_code": first.item_code,
				"item_name": first.item_name or first.item_code,
				"qty": flt(first.stock_qty or first.qty),  # stock UOM (Pcs)
				"stock_uom": first.stock_uom,
				"work_order": first.custom_work_order,
				"batch": lot.batch if lot and not lot.unsupported else None,
				"qty_in_pack": qty_in_pack,
				"adonan_ke": adonan_ke,
				"box_1": m.custom_box_1 or None,
				"box_2": m.custom_box_2 or None,
				"boxes": [b for b in (m.custom_box_1, m.custom_box_2) if b],
				"from_warehouse": m.set_from_warehouse or None,
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

	# FU29: live stock at the ROUTE origin (MR from_warehouse) so request/siap
	# cards can warn BEFORE a send is attempted; cached per (kind, key) — the
	# same quantities send_handover re-checks under the lock.
	route_cache = {}
	for r in rows:
		if r["lane"] not in (LANE_REQUEST, LANE_SIAP) or not r["from_warehouse"]:
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
	LANE_SIAP: "Siap Kirim",
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


def _handover_lanes(wo_names):
	"""FU23: lane serah terima paling maju per Work Order — SATU sumber derivasi
	untuk flag workspace dan field native. Prioritas lane identik _requests:
	terkirim (SE submitted) > siap_kirim (postpacking confirmed) > request;
	MR draft/cancelled tidak menandai apa pun. Tanpa izin baca MR/SE
	mengembalikan {} (pemanggil menampilkan tanpa flag, tanpa error)."""
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
		mrs = frappe.get_all(
			"Material Request",
			filters={
				"name": ("in", sorted({i.parent for i in items})),
				"material_request_type": "Material Transfer",
			},
			fields=["name", "docstatus", "status", "custom_postpacking_confirmed"],
			limit=0,
		)
	except frappe.PermissionError:
		return {}
	if not mrs:
		return {}
	sent = _sent_se_by_mr([m.name for m in mrs])
	wos_by_mr = {}
	for i in items:
		wos_by_mr.setdefault(i.parent, []).append(i.custom_work_order)
	rank = {LANE_REQUEST: 1, LANE_SIAP: 2, LANE_KIRIM: 3}
	best = {}
	for m in mrs:
		if m.docstatus != 1:
			continue  # draft/cancelled tidak pernah menandai WO
		if m.name in sent:
			lane = LANE_KIRIM
		elif m.custom_postpacking_confirmed:
			lane = LANE_SIAP
		else:
			lane = LANE_REQUEST  # termasuk Stopped tanpa SE — pernah diminta
		for wo_name in wos_by_mr.get(m.name, ()):
			if rank[lane] > rank.get(best.get(wo_name), 0):
				best[wo_name] = lane
	return best


def sync_handover_status(wo_names):
	"""Tulis custom_handover_status di Work Order dari derivasi dokumen.
	Dipanggil oleh doc_events (MR/SE) dan save_post_packing (db_set tanpa
	event). WO tanpa lane aktif dikosongkan (semua MR batal)."""
	wo_names = sorted({n for n in wo_names if n})
	if not wo_names:
		return
	lanes = _handover_lanes(wo_names)
	for wo_name in wo_names:
		frappe.db.set_value(
			"Work Order", wo_name, HANDOVER_STATUS_FIELD,
			HANDOVER_STATUS_LABEL.get(lanes.get(wo_name)), update_modified=False,
		)


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
	"""§4.3: reservation = Σ qty of submitted, not stopped/cancelled MRs
	without a Stock Entry, bound to the Work Order — exactly the request/siap
	lane rows carrying no edge flag (draft/cancelled have no lane, stopped is
	flagged)."""
	reserved = {}
	for r in requests:
		if r["lane"] in (LANE_REQUEST, LANE_SIAP) and not r["flag"]:
			reserved[r["work_order"]] = reserved.get(r["work_order"], 0.0) + r["qty"]
	return reserved


def _reserved_by_item(requests, wo_rows):
	"""Follow-up 8 — batchless pool reservation: batchless stock has no batch
	dimension, so every active MR of the ITEM (any WO) holds from the same
	pool. T31 (R2): the pool warehouse is the WO lot row's POOL warehouse
	(source setting overrides), NOT the MR's stored from_warehouse — so MRs
	created before the setting existed still reserve the pool after it appears.
	Fallback when the WO has no lot row: the request's own from_warehouse."""
	wo_by_name = {r.work_order: r for r in wo_rows}
	reserved = {}
	for r in requests:
		if r["lane"] in (LANE_REQUEST, LANE_SIAP) and not r["flag"]:
			lot = wo_by_name.get(r["work_order"])
			warehouse = _pool_warehouse(lot) if lot else r["from_warehouse"]
			key = (r["item_code"], warehouse)
			reserved[key] = reserved.get(key, 0.0) + r["qty"]
	return reserved


def _item_stock(item_code, warehouse):
	"""Live item+warehouse stock straight off the ledger (batchless pools have
	no batch dimension to ask get_batch_qty about)."""
	return flt(
		frappe.db.sql(
			"select sum(actual_qty) from `tabStock Ledger Entry`"
			" where item_code=%s and warehouse=%s and is_cancelled=0",
			(item_code, warehouse),
		)[0][0]
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
	lots = []
	for row in wo_rows:
		if row.unsupported:
			lots.append(row)
			continue
		if row.batchless:
			pool_wh = _pool_warehouse(row)
			key = (row.item_code, pool_wh)
			if key not in pool_stock:
				pool_stock[key] = _item_stock(row.item_code, pool_wh)
			row.physical_qty = pool_stock[key]
			row.reserved_qty = flt(reserved_item.get(key, 0.0))
		else:
			row.reserved_qty = reserved.get(row.work_order, 0.0)
		row.available_qty = row.physical_qty - row.reserved_qty
		# FU30: penanda manual "Gudang Confirmed" dipensiunkan — lot turun murni
		# dari stok (physical 0) / Status Serah Terima; kecuali masih diikat
		# permintaan aktif (dialognya butuh data lot).
		if row.physical_qty <= 0 and row.work_order not in bound:
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
            if r["lane"] in (LANE_REQUEST, LANE_SIAP) and not r["flag"]
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


def _target_warehouse_or_throw():
    target = _target_warehouse()
    if not target:
        frappe.throw(
            _("Gudang tujuan serah terima belum diatur; isi 'Gudang Serah Terima' di menu Pengaturan.")
        )
    return target


def _box_kg(value, label):
    """Box weight in kg (R8): blank -> None; else a finite, non-negative float."""
    if value is None or str(value).strip() == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        frappe.throw(_("{0} harus angka kg yang valid").format(label))
    if amount != amount or amount in (float("inf"), float("-inf")):
        frappe.throw(_("{0} harus angka kg yang valid").format(label))
    if amount < 0:
        frappe.throw(_("{0} tidak boleh negatif").format(label))
    return amount


@frappe.whitelist()
def create_request(work_order):
    """Gudang side (Gudang Barang Jadi / Stock User): submit a Material Transfer
    request for the Work Order's FULL produced qty (R3 — no qty dialog, drag is
    the direct action). The source warehouse is the handover source setting
    when set, else the SE-derived lot warehouse (R2). One ACTIVE (unshipped,
    unstopped) request per Work Order; a duplicate throws.

    Re-validates availability under the WO row lock, then inserts + submits the
    MR in this one transaction — zero writes on any validation failure."""
    return {**_create_request(work_order), "board": _build_board()}


def _create_request(work_order):
    """Boardless create_request mutation: the exact action payload minus
    board (T38 bulk dispatch + the whitelisted endpoint share it)."""
    _require_role(
        ROLES_GUDANG,
        _("Hanya peran gudang (Stock User / Gudang Barang Jadi) yang dapat membuat permintaan serah terima."),
    )
    frappe.has_permission("Material Request", "create", throw=True)
    target = _target_warehouse_or_throw()

    frappe.db.get_value("Work Order", work_order, "name", for_update=True)  # row lock
    wo = frappe.get_doc("Work Order", work_order)
    amount = flt(wo.produced_qty)
    if amount <= 0:
        frappe.throw(
            _("Work Order {0} belum punya hasil barang jadi (produced qty 0).").format(work_order)
        )
    lot = _checked_lot(work_order)
    if lot.batchless:
        # the pool is ITEM-wide: requests from every WO of this item draw from
        # it, so the Item row lock serializes them (the WO lock above cannot)
        frappe.db.get_value("Item", wo.production_item, "name", for_update=True)
        lot = _checked_lot(work_order)  # re-derive under the pool lock

    # R3: satu permintaan aktif per WO — T39-fix1 (I1): keputusan duplikat
    # memakai CURRENT read (FOR UPDATE, join MRI->MR) di bawah lock WO (dan
    # Item batchless): snapshot RR bisa luput dari MR yang di-commit
    # kompetitor selama lock wait. Paritas lane lama: submitted tanpa SE
    # menghalangi; draft/cancelled/stopped/terkirim tidak. Setiap create
    # lain harus lewat lock WO yang sama dulu, jadi tidak ada MR aktif baru
    # yang bisa muncul tanpa terlihat oleh read ini (phantom aman).
    bound = frappe.db.sql(
        "select mri.parent as mr, mr.docstatus, mr.status"
        " from `tabMaterial Request Item` mri"
        " join `tabMaterial Request` mr on mr.name = mri.parent"
        " where mri.custom_work_order = %s"
        " for update",
        (work_order,),
        as_dict=True,
    )
    seen_mr = set()
    for row in bound:
        if row.mr in seen_mr:
            continue  # MR multi-baris: putuskan sekali
        seen_mr.add(row.mr)
        if row.docstatus != 1 or row.status == "Stopped":
            continue
        if _sent_se_name_locked(row.mr):
            continue  # terkirim: request baru tetap sah (lane parity)
        frappe.throw(
            _("Work Order {0} sudah punya permintaan aktif ({1}).").format(work_order, row.mr)
        )

    stock_uom = lot.stock_uom or frappe.db.get_value("Item", wo.production_item, "stock_uom")
    _enforce_whole_uom(amount, stock_uom, "Qty")
    available = flt(lot.available_qty)
    if amount > available:
        frappe.throw(
            _("Qty melebihi lot tersedia: diminta {0}, tersedia {1}.").format(amount, available)
        )

    source = _pool_warehouse(lot)  # setting override, else SE-derived (R2)
    mr = frappe.get_doc(
        {
            "doctype": "Material Request",
            "material_request_type": "Material Transfer",
            "company": wo.company,
            "transaction_date": now(),
            "schedule_date": add_days(now(), 1),
            "set_from_warehouse": source,
            "set_warehouse": target,
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
            ],
        }
    )
    mr.insert()  # session user; submit below — one transaction, native perms
    mr.submit()
    return {"ok": True, "material_request": mr.name, "qty": amount}


@frappe.whitelist()
def cancel_request(material_request):
    """Gudang side (Gudang Barang Jadi / Stock User): cancel a request BEFORE
    Post-Packing (native cancel; audit history stays, reservation is released)."""
    return {**_cancel_request(material_request), "board": _build_board()}


def _cancel_request(material_request):
    """Boardless cancel_request mutation: the exact action payload minus
    board (T38). T39 §6.2: resolve binding read-only, lalu lock WO -> MR,
    re-read + §6.1 di bawah lock, baru recheck lane."""
    _require_role(
        ROLES_GUDANG,
        _("Hanya peran gudang (Stock User / Gudang Barang Jadi) yang dapat membatalkan permintaan serah terima."),
    )
    wo_name = _handover_binding(material_request)
    frappe.db.get_value("Work Order", wo_name, "name", for_update=True)  # 1. WO (§6.2)
    mr, current = _handover_mr(material_request, wo_name)  # 2. lock MR + re-read + §6.1
    frappe.has_permission("Material Request", "cancel", doc=mr, throw=True)
    if current.custom_postpacking_confirmed:
        frappe.throw(_("Permintaan {0} sudah diverifikasi (Post-Packing); tidak bisa dibatalkan.").format(material_request))
    sent = _sent_se_name_locked(material_request)  # current read (T39-fix1)
    if sent:
        frappe.throw(
            _("Permintaan {0} sudah terkirim ({1}); tidak bisa dibatalkan.").format(
                material_request,
                get_link_to_form("Stock Entry", sent),
            )
        )
    mr.cancel()  # native; permission-checked as session user
    return {"ok": True, "material_request": material_request}


# WO mirror: Box 1/2 ONLY (T31, R4/R8) — the kg weights entered at the
# "Verifikasi Siap Kirim" step edit the Work Order (Float kg, upgrade.py
# migrate). The WO postpacking qty/jam/qc fields are owned by the Work Order
# workspace (`confirm_postpacking`, written BEFORE manufacture, T27); this
# handover block runs AFTER manufacture, so mirroring them would fabricate the
# WO's final result (competing writer, POSTPACKING_PLAN §3). Full history
# lives on the Material Requests; the WO fields are never touched here.
WO_MIRROR_FIELDS = (
    "custom_box_1",
    "custom_box_2",
)


def _handover_binding(material_request):
    """T39 §6.2 pre-read (hanya baca, sebelum lock apa pun): resolve SATU
    binding Work Order non-kosong agar baris WO bisa di-lock lebih dulu. MR
    tanpa tepat satu binding tak mungkin permintaan serah terima yang sah —
    menolak di sini aman (nol tulis) dan menghindari lock pada input rusak."""
    bindings = {
        row.custom_work_order
        for row in frappe.get_all(
            "Material Request Item",
            filters={"parent": material_request},
            fields=["custom_work_order"],
            order_by="idx asc",
        )
        if row.custom_work_order
    }
    if len(bindings) != 1:
        frappe.throw(
            _("Material Request {0} bukan permintaan serah terima (tanpa Work Order).").format(
                material_request
            )
        )
    return bindings.pop()


def _handover_mr(material_request, wo_name, route=False):
    """T39 §6.1 invariant permintaan serah terima — pemanggil WAJIB memegang
    lock baris Work Order; fungsi ini me-lock baris Material Request dan
    mengembalikan (mr, current). T39-fix1 (I1): field keputusan
    (docstatus/konfirmasi/status) dibaca dengan locking read (SELECT ...
    FOR UPDATE) — di MariaDB REPEATABLE-READ plain read memakai snapshot
    transaksi yang dipin SEBELUM lock wait, jadi bisa melewatkan commit
    kompetitor; locking read selalu membaca data tercommit terbaru. Baris
    struktural (tipe, baris item, binding, qty, rute) immutable pada MR
    docstatus 1 di alur serah terima — plain get_doc cukup (ruling review).
    Menegakkan: izin baca; Material Transfer; docstatus 1 (current); tepat
    satu baris item; binding tunggal masih menunjuk wo_name (rebinding di
    bawah lock ditolak); qty baris valid; dan untuk aksi yang memindah stok
    (route=True) rute asal/tujuan non-kosong dan konsisten baris vs header.
    Izin tulis/cancel/submit tetap milik helper aksi."""
    current = frappe.db.get_value(
        "Material Request",
        material_request,
        ["docstatus", "custom_postpacking_confirmed", "status"],
        for_update=True,  # lock baris MR + current read untuk gerbang keputusan
        as_dict=True,
    )
    if not current:
        frappe.throw(_("Material Request {0} tidak ditemukan.").format(material_request))
    mr = frappe.get_doc("Material Request", material_request)
    frappe.has_permission("Material Request", "read", doc=mr, throw=True)
    if mr.material_request_type != "Material Transfer":
        frappe.throw(
            _("Material Request {0} bukan permintaan Material Transfer.").format(material_request)
        )
    if current.docstatus != 1:
        frappe.throw(_("Material Request {0} tidak aktif (docstatus {1}).").format(material_request, current.docstatus))
    if len(mr.items or []) != 1:
        frappe.throw(_("Material Request {0} harus satu baris item.").format(material_request))
    row = mr.items[0]
    if not row.get("custom_work_order"):
        frappe.throw(_("Material Request {0} bukan permintaan serah terima (tanpa Work Order).").format(material_request))
    if row.custom_work_order != wo_name:
        frappe.throw(
            _("Material Request {0} terikat ke {1}, bukan {2}.").format(
                material_request, row.custom_work_order, wo_name
            )
        )
    if flt(row.stock_qty or row.qty) <= 0:
        frappe.throw(_("Material Request {0} punya qty baris tidak valid.").format(material_request))
    if route:
        source = row.from_warehouse or mr.set_from_warehouse
        target = row.warehouse or mr.set_warehouse
        if not source or not target:
            frappe.throw(
                _("Material Request {0} punya rute gudang tidak lengkap (asal {1}, tujuan {2}).").format(
                    material_request, source, target
                )
            )
        if row.from_warehouse and mr.set_from_warehouse and row.from_warehouse != mr.set_from_warehouse:
            frappe.throw(
                _("Material Request {0}: gudang asal baris ({1}) berbeda dari header ({2}).").format(
                    material_request, row.from_warehouse, mr.set_from_warehouse
                )
            )
        if row.warehouse and mr.set_warehouse and row.warehouse != mr.set_warehouse:
            frappe.throw(
                _("Material Request {0}: gudang tujuan baris ({1}) berbeda dari header ({2}).").format(
                    material_request, row.warehouse, mr.set_warehouse
                )
            )
    return mr, current


def _sent_se_name_locked(material_request):
    """T39-fix1 (I1): keberadaan SE submitted untuk satu MR sebagai CURRENT
    read (FOR UPDATE) — snapshot transaksi RR tidak melihat SE yang di-commit
    kompetitor selama lock wait kita, jadi gerbang duplikat tidak boleh
    memakai plain read. `SED.material_request` berindeks native (scan murah);
    mengembalikan nama SE terakhir (posting terlama) atau None."""
    rows = frappe.db.sql(
        "select sed.parent as name"
        " from `tabStock Entry Detail` sed"
        " join `tabStock Entry` se on se.name = sed.parent"
        " where sed.material_request = %s"
        " and sed.docstatus = 1 and se.docstatus = 1"
        " and sed.parenttype = 'Stock Entry'"
        " order by se.posting_date asc, se.posting_time asc, se.creation asc"
        " limit 1 for update",
        (material_request,),
        as_dict=True,
    )
    return rows[0].name if rows else None


@frappe.whitelist()
def save_post_packing(material_request, box_1=None, box_2=None):
    """Manufacturing User: "Verifikasi Siap Kirim" (Request -> Siap Kirim) —
    records ONLY the Box 1/2 weights in kg (R4: good/reject/trial/sisa/jam/qc
    already live on the Work Order Post-Packing stage, T27) and confirms the
    request. Written via db_set behind our own write gate (a full save() of a
    submitted doc would demand submit permission, which Manufacturing User
    must not have, T22). Boxes mirror to the Work Order (kg semantics, R8);
    the MR stays a pure request document created by gudang."""
    return {
        **_save_post_packing(material_request, box_1, box_2),
        "board": _build_board(),
    }


def _save_post_packing(material_request, box_1, box_2):
    """Boardless save_post_packing mutation: the exact action payload minus
    board (T38). T39 §6.2: lock WO -> MR (inversi MR->WO lama dihapus), lalu
    re-read + §6.1 dan recheck di bawah lock."""
    _require_role(
        ROLE_PRODUKSI, _("Hanya Manufacturing User yang dapat mengisi Post-Packing.")
    )
    wo_name = _handover_binding(material_request)
    frappe.db.get_value("Work Order", wo_name, "name", for_update=True)  # 1. WO (§6.2)
    mr, current = _handover_mr(material_request, wo_name)  # 2. lock MR + re-read + §6.1
    frappe.has_permission("Material Request", "write", doc=mr, throw=True)
    if current.custom_postpacking_confirmed:
        frappe.throw(_("Post-Packing untuk {0} sudah dikonfirmasi sebelumnya.").format(material_request))
    sent = _sent_se_name_locked(material_request)  # current read (T39-fix1)
    if sent:
        frappe.throw(_("Permintaan {0} sudah terkirim; Post-Packing tidak bisa diisi.").format(material_request))

    box1 = _box_kg(box_1, "Box 1")
    box2 = _box_kg(box_2, "Box 2")
    # kolom box kini NOT NULL (schema canonical Frappe) — kosong disimpan 0;
    # display "belum diisi" tetap truthiness (0/null sama, catatan T33/FU25)
    values = {
        "custom_box_1": flt(box1),
        "custom_box_2": flt(box2),
        "custom_postpacking_confirmed": 1,
    }
    for fieldname, value in values.items():
        mr.db_set(fieldname, value)

    wo = mr.items[0].custom_work_order
    frappe.has_permission("Work Order", "write", doc=wo, throw=True)
    frappe.db.set_value(
        "Work Order", wo, {f: values[f] for f in WO_MIRROR_FIELDS}
    )
    # db_set tidak memicu doc_events — sinkronkan field penanda WO manual (FU23)
    sync_handover_status([wo])
    return {
        "ok": True,
        "material_request": material_request,
        "box_1": box1,
        "box_2": box2,
    }


@frappe.whitelist()
def send_handover(material_request):
    """Manufacturing User: create + submit the handover Stock Entry moving the
    MR's requested qty (= the WO's produced_qty at request time, R6) from the
    source warehouse to the handover target. ONE transaction: any failure rolls
    back with zero partial documents. Batch-tracked rows keep batch_no (the
    batch seam); the shortage pre-check reads the ROUTE from-warehouse (FU29),
    so a lot whose stock lives elsewhere is refused here with a clear message —
    native submit validation stays as the backstop in the same transaction."""
    return {**_send_handover(material_request), "board": _build_board()}


def _send_handover(material_request):
    """Boardless send_handover mutation: the exact action payload minus
    board (T38). T39 §6.2: resolve binding read-only, lock WO -> MR ->
    (batchless) Item, re-read + §6.1, lalu recheck konfirmasi/stopped/duplikat
    SE/stok rute di bawah lock."""
    _require_role(
        ROLE_PRODUKSI, _("Hanya Manufacturing User yang dapat mengirim serah terima.")
    )
    frappe.has_permission("Stock Entry", "create", throw=True)
    frappe.has_permission("Stock Entry", "submit", throw=True)

    wo_name = _handover_binding(material_request)
    frappe.db.get_value("Work Order", wo_name, "name", for_update=True)  # 1. WO (§6.2)
    mr, current = _handover_mr(material_request, wo_name, route=True)  # 2. lock MR + §6.1
    qty = flt(mr.items[0].stock_qty or mr.items[0].qty)
    lot = _checked_lot(wo_name)  # §4.9 unsupported error BEFORE any mutation
    if lot.batchless:
        # the pool is ITEM-wide: sends from every WO of this item draw from it,
        # so the Item row lock serializes them (the WO/MR locks above cannot)
        frappe.db.get_value("Item", lot.item_code, "name", for_update=True)  # 3. Item (§6.2)
        lot = _checked_lot(wo_name)  # re-derive under the pool lock
    batch = lot.batch
    if not current.custom_postpacking_confirmed:
        frappe.throw(_("Post-Packing belum dikonfirmasi untuk {0}.").format(material_request))
    if current.status == "Stopped":
        frappe.throw(_("Permintaan {0} berstatus Stopped; aktifkan kembali lewat Desk.").format(material_request))
    sent = _sent_se_name_locked(material_request)  # current read (T39-fix1)
    if sent:
        frappe.throw(
            _("Pengiriman duplikat: Stock Entry {0} sudah ada untuk {1}.").format(
                get_link_to_form("Stock Entry", sent), material_request
            )
        )
    # FU29: pre-check against the ROUTE origin (the same warehouse
    # make_mr_stock_entry will use for s_warehouse) — NOT the lot's SE-derived
    # warehouse. A legacy lot whose stock sits elsewhere is refused HERE with a
    # clear Indonesian message instead of dying at native submit.
    route_wh = mr.items[0].from_warehouse or mr.set_from_warehouse or lot.warehouse
    physical = (
        _item_stock(lot.item_code, route_wh)
        if lot.batchless
        else flt(get_batch_qty(batch, route_wh) or 0)
    )
    if physical < qty:  # fail atomically here; NegativeStockError is the backstop
        frappe.throw(
            _("Stok {0} di gudang asal {1} hanya {2}; tidak bisa mengirim {3}.").format(
                lot.item_code if lot.batchless else f"batch {batch}",
                route_wh,
                physical,
                qty,
            )
        )

    se = frappe.get_doc(make_mr_stock_entry(mr.name))
    if len(se.items) != 1:
        frappe.throw(_("Material Request {0} harus satu baris item.").format(material_request))
    row = se.items[0]
    row.qty = qty
    row.transfer_qty = qty * flt(row.conversion_factor or 1)
    if not lot.batchless:
        row.use_serial_batch_fields = 1  # v16: old batch field -> bundle at submit (T21)
        row.batch_no = batch
    se.insert()
    se.submit()  # native shortage/valuation failures roll the whole request back

    return {
        "ok": True,
        "material_request": material_request,
        "stock_entry": se.name,
        "batch": batch,
        "qty": qty,
    }


# --------------------------------------- T38 bulk: single-card dispatch endpoint
#
# ONE card per HTTP request (spec §4.2): the browser orchestrator provides the
# bulk behavior, this endpoint only strictly validates one action + one entry
# and dispatches to the allowlisted boardless helper. It never calls
# _build_board, never calls another whitelisted endpoint over HTTP, never uses
# ignore_permissions, and never catches action exceptions (expected failures
# surface as their native Frappe exceptions; schema refusals happen BEFORE any
# mutation because helpers are only reached after validation passes).

BULK_ACTION_KEYS = {
    "create_request": ("work_order",),
    "cancel_request": ("material_request",),
    "save_post_packing": ("material_request", "box_1", "box_2"),
    "send_handover": ("material_request",),
}


@frappe.whitelist()
def bulk_handover_item(action, entry):
    """Single-card bulk dispatch: returns the action payload minus `board`
    (the board is reloaded once by the client after the whole run)."""
    if not isinstance(action, str) or action not in BULK_ACTION_KEYS:
        frappe.throw(_("Aksi bulk {0} tidak dikenal.").format(action))
    if not isinstance(entry, dict):
        frappe.throw(_("Entry harus satu objek JSON."))
    keys = BULK_ACTION_KEYS[action]
    missing = [k for k in keys if k not in entry]
    unknown = [k for k in entry if k not in keys]
    if missing:
        frappe.throw(
            _("Kunci {0} wajib ada untuk aksi {1}.").format(", ".join(missing), action)
        )
    if unknown:
        frappe.throw(
            _("Kunci tidak dikenal untuk aksi {0}: {1}.").format(action, ", ".join(unknown))
        )
    for key in keys:
        if key in ("box_1", "box_2"):
            continue  # kg floats: blank/None valid, validated by _box_kg in the helper
        value = entry[key]
        if not isinstance(value, str) or not value.strip():
            frappe.throw(_("{0} wajib teks tidak kosong.").format(key))

    if action == "create_request":
        return _create_request(entry["work_order"])
    if action == "cancel_request":
        return _cancel_request(entry["material_request"])
    if action == "save_post_packing":
        return _save_post_packing(entry["material_request"], entry["box_1"], entry["box_2"])
    return _send_handover(entry["material_request"])

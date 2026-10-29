# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Unit tests for partial production handover and warehouse-scoped reservations.

Tests the mathematical model, deterministic sorted allocation, 43-WO characterization,
preview fingerprint context binding, deadlock-free lock order, and multi-SE state
derivations using mocked Frappe database interfaces so they can run without live database mutations.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace

try:
    import frappe
except ImportError:
    from pathlib import Path

    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[2]))
    sys.path.insert(0, str(_here.parent))
    sys.path.insert(0, str(_here.parents[3] / "warehouse_app"))
    import frappe_stub
    import frappe

# Prevent logger from attempting to write to nonexistent /home/frappe/logs/cssutils.log
frappe.logger = MagicMock()


class TestPartialHandoverUnit(unittest.TestCase):
    def _stock(self, qty):
        # batchless pool stock comes from Bin via _item_stock; pin it at that boundary
        p = patch("production_app.api.handover._item_stock", return_value=qty)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        frappe.session = frappe._dict(user="Administrator")
        frappe.get_roles = MagicMock(return_value=["Stock User", "Stock Manager", "Manufacturing User", "Manufacturing Manager"])
        frappe.has_permission = MagicMock(return_value=True)
        frappe.get_all = MagicMock(return_value=[])
        frappe.get_list = MagicMock(return_value=[])
        frappe.get_doc = MagicMock()
        frappe.new_doc = MagicMock()
        frappe.db = MagicMock()
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")
        frappe.db.get_value = MagicMock(return_value=1)

        def _default_sql(query, values=None, as_dict=False, as_list=False):
            q = str(query)
            if "sum(" in q.lower() and not as_dict and not as_list and "group by" not in q.lower():
                return [(0.0,)]
            return []

        frappe.db.sql = MagicMock(side_effect=_default_sql)
        frappe.db.has_column = MagicMock(return_value=True)
        frappe.db.exists = MagicMock(return_value=True)
        frappe.db.set_value = MagicMock()

    def test_fingerprint_binds_route_units_and_row_pool_context(self):
        from production_app.api.handover import _compute_preview_fingerprint

        row = dict(work_order="WO", item_code="FG", source_warehouse="SOURCE",
                   target_warehouse="GBJ", stock_uom="Nos", display_uom="Pack",
                   qty_in_pack=6, batch=None, allocated_qty=12, unrequested_remainder=0)
        group = dict(item_code="FG", source_warehouse="SOURCE", physical_stock=100,
                     available_pool=96, outstanding_reservations=4)
        fingerprint = _compute_preview_fingerprint([row], [group])
        for field, value in [("target_warehouse", "OTHER"), ("stock_uom", "Kg"),
                             ("display_uom", "Box"), ("qty_in_pack", 12), ("batch", "BATCH")]:
            with self.subTest(field=field):
                self.assertNotEqual(fingerprint, _compute_preview_fingerprint([{**row, field: value}], [group]))
        self.assertNotEqual(fingerprint, _compute_preview_fingerprint([row], [{**group, "physical_stock": 101}]))

    def test_lot_history_never_counts_unknown_destination_as_gbj(self):
        from production_app.api.handover import _lots

        frappe.db.get_single_value.return_value = None
        lot = frappe._dict(work_order="WO", produced_qty=25, unsupported=False,
                          batchless=True, warehouse="SOURCE", item_code="FG", entered_at="2026-10-28")
        def sql(query, values=None, **kwargs):
            if "group by mri.custom_work_order" in query:
                return [("WO", 21)]
            return [(0,)]
        frappe.db.sql.side_effect = sql
        with patch("production_app.api.handover._item_stock", return_value=25):
            result = _lots([lot], [])
        self.assertEqual(result[0].transferred_qty, 0)

    def test_row_fingerprint_changes_with_surplus_pool_even_when_allocation_does_not(self):
        from production_app.api.handover import preview_handover_request

        wo = frappe._dict(name="WO", production_item="FG", produced_qty=5,
                          company="COMPANY", fg_warehouse="SOURCE", stock_uom="Nos")
        frappe.get_doc.return_value = wo
        with patch("production_app.api.handover._item_stock", return_value=100) as stock:
            first = preview_handover_request(["WO"])
            stock.return_value = 101
            second = preview_handover_request(["WO"])
        self.assertEqual(first["allocations"][0]["allocated_qty"], second["allocations"][0]["allocated_qty"])
        self.assertNotEqual(first["allocations"][0]["fingerprint"], second["allocations"][0]["fingerprint"])

    def test_batch_allocation_cannot_borrow_another_batch_stock(self):
        from production_app.api.handover import preview_handover_request

        wos = [frappe._dict(name=f"WO-{i}", production_item="FG", produced_qty=5,
                           company="COMPANY", fg_warehouse="SOURCE", stock_uom="Nos") for i in (1, 2)]
        lots = [frappe._dict(work_order=w.name, warehouse="SOURCE", batchless=False,
                            unsupported=False, batch=f"BATCH-{i}", stock_uom="Nos",
                            display_uom=None, qty_in_pack=1) for i, w in enumerate(wos, 1)]
        frappe.get_doc.side_effect = lambda dt, name: next(w for w in wos if w.name == name)
        with patch("production_app.api.handover._wo_lot_rows", return_value=lots), \
             patch("production_app.api.handover._pool_warehouse", return_value="SOURCE"), \
             patch("production_app.api.handover._item_stock", return_value=10), \
             patch("production_app.api.handover.get_batch_qty", side_effect=lambda b, wh: 0 if b == "BATCH-1" else 10):
            result = preview_handover_request([w.name for w in wos])
        self.assertEqual([r["allocated_qty"] for r in result["allocations"]], [0, 5])
        self.assertEqual(result["allocations"][0]["unrequested_remainder"], 5)

    def test_pool_source_falls_back_from_empty_row_and_reports_unresolved(self):
        from production_app.api.handover import _pool_reserved_now, preview_handover_request

        _pool_reserved_now("FG", "SOURCE")
        self.assertIn("nullif(mri.from_warehouse, '')", frappe.db.sql.call_args.args[0])
        wo = frappe._dict(name="WO", production_item="FG", produced_qty=5,
                          company="COMPANY", fg_warehouse="SOURCE", stock_uom="Nos")
        frappe.get_doc.return_value = wo
        def sql(query, values=None, **kwargs):
            if "as source_warehouse" in query:
                return [dict(name="MR-UNKNOWN", target_warehouse="RD", source_warehouse=None,
                             outstanding_qty=4)]
            return [] if kwargs.get("as_dict") or kwargs.get("as_list") else [(0,)]
        frappe.db.sql.side_effect = sql
        self._stock(0)
        result = preview_handover_request(["WO"])
        unresolved = result["groups"][0]["unresolved_reservations"]
        self.assertEqual(unresolved[0]["quantity"], 4)
        self.assertEqual(result["groups"][0]["available_pool"], 0)

    def test_43_work_orders_characterization(self):
        """Historical incident characterization:
        43 WOs produced 1,096 Pcs.
        Physical source stock is 1,096 Pcs.
        Unlinked R&D Material Request reserves 4 Pcs in the same source warehouse.
        Available pool is 1,092 Pcs.
        Deterministic allocation gives 1,071 Pcs to the first 42 WOs and 21 Pcs
        to the 43rd WO (which produced 25 Pcs), leaving 4 Pcs unrequested.
        21/25 must NOT be interpreted as a UOM conversion factor.
        """
        from production_app.api.handover import _allocate_pool_budget

        wos = []
        for i in range(1, 43):
            qty = 26 if i <= 21 else 25  # 21*26 + 21*25 = 546 + 525 = 1,071 Pcs
            wos.append({
                "work_order": f"PRO-WO-2026-{i:04d}",
                "produced_qty": float(qty),
                "unrequested_qty": float(qty),
                "source_warehouse": "Gudang Produksi - RR",
                "item_code": "PROD-001",
            })
        self.assertEqual(sum(w["produced_qty"] for w in wos), 1071.0)

        # 43rd WO produced 25 Pcs
        wos.append({
            "work_order": "PRO-WO-2026-0043",
            "produced_qty": 25.0,
            "unrequested_qty": 25.0,
            "source_warehouse": "Gudang Produksi - RR",
            "item_code": "PROD-001",
        })
        self.assertEqual(len(wos), 43)
        self.assertEqual(sum(w["produced_qty"] for w in wos), 1096.0)

        physical_stock = 1096.0
        external_reservations = 4.0  # Unlinked R&D MR
        pool_available = physical_stock - external_reservations
        self.assertEqual(pool_available, 1092.0)

        allocations, remaining_budget = _allocate_pool_budget(wos, pool_available)

        # First 42 WOs receive their full eligible unrequested output: 1,071 Pcs
        first_42_sum = sum(allocations[w["work_order"]]["allocated_qty"] for w in wos[:42])
        self.assertEqual(first_42_sum, 1071.0)
        for w in wos[:42]:
            self.assertEqual(allocations[w["work_order"]]["unrequested_remainder"], 0.0)

        # 43rd WO receives exactly 21 Pcs, leaving 4 Pcs unrequested
        wo43_alloc = allocations["PRO-WO-2026-0043"]
        self.assertEqual(wo43_alloc["allocated_qty"], 21.0)
        self.assertEqual(wo43_alloc["unrequested_remainder"], 4.0)
        self.assertEqual(wo43_alloc["produced_qty"], 25.0)

        # Remaining pool budget is 0
        self.assertEqual(remaining_budget, 0.0)

        # Total allocated is exactly 1,092 Pcs
        total_allocated = sum(a["allocated_qty"] for a in allocations.values())
        self.assertEqual(total_allocated, 1092.0)

    def test_allocation_remainder_excludes_prior_transfers_and_commitments(self):
        from production_app.api.handover import _allocate_pool_budget

        for available, allocated, remainder in [(0, 0, 4), (4, 4, 0)]:
            with self.subTest(available=available):
                result, _ = _allocate_pool_budget([
                    {"work_order": "WO-PARTIAL", "produced_qty": 25, "unrequested_qty": 4}
                ], available)
                self.assertEqual(result["WO-PARTIAL"]["allocated_qty"], allocated)
                self.assertEqual(result["WO-PARTIAL"]["unrequested_remainder"], remainder)

    def test_warehouse_scoped_reservation_deducts_fulfilled_sed(self):
        """Outstanding reservation for an MRI must be max(0, stock_qty - fulfilled_transfer_qty).
        When SED transfers stock, inventory leaves physical stock and must NOT be double deducted
        as an outstanding reservation.
        """
        from production_app.api.handover import _compute_outstanding_reservation

        # Case 1: MR of 25 Pcs, no SE yet -> reservation is 25 Pcs
        res1 = _compute_outstanding_reservation(stock_qty=25.0, fulfilled_qty=0.0)
        self.assertEqual(res1, 25.0)

        # Case 2: MR of 25 Pcs, partially transferred 21 Pcs -> reservation is 4 Pcs
        res2 = _compute_outstanding_reservation(stock_qty=25.0, fulfilled_qty=21.0)
        self.assertEqual(res2, 4.0)

        # Case 3: MR of 25 Pcs, fully transferred 25 Pcs -> reservation is 0 Pcs
        res3 = _compute_outstanding_reservation(stock_qty=25.0, fulfilled_qty=25.0)
        self.assertEqual(res3, 0.0)

        # Case 4: Over-transfer or cancelled edge -> never negative
        res4 = _compute_outstanding_reservation(stock_qty=25.0, fulfilled_qty=30.0)
        self.assertEqual(res4, 0.0)

    def test_wo_handover_status_derivation(self):
        """A Work Order is fully transferred (LANE_KIRIM) only when cumulative GBJ
        transfers cover produced_qty.
        """
        from production_app.api.handover import _derive_wo_handover_state

        # Case 1: Produced 25, 0 transferred, 0 active MR -> lane None
        s1 = _derive_wo_handover_state(produced_qty=25.0, cumulative_transferred=0.0, active_mr=None)
        self.assertIsNone(s1["lane"])
        self.assertEqual(s1["remaining_unrequested"], 25.0)

        # Case 2: Produced 25, 0 transferred, active MR of 21 Pcs -> LANE_REQUEST
        s2 = _derive_wo_handover_state(produced_qty=25.0, cumulative_transferred=0.0, active_mr="MR-001", active_mr_qty=21.0)
        self.assertEqual(s2["lane"], "request")
        self.assertEqual(s2["remaining_unrequested"], 4.0)

        # Case 3: Produced 25, 21 transferred, MR-001 completed, no active MR -> lane None, remaining 4
        s3 = _derive_wo_handover_state(produced_qty=25.0, cumulative_transferred=21.0, active_mr=None)
        self.assertIsNone(s3["lane"])
        self.assertEqual(s3["remaining_unrequested"], 4.0)
        self.assertTrue(s3["is_partial"])

        # Case 4: Produced 25, 25 transferred -> LANE_KIRIM (fully transferred)
        s4 = _derive_wo_handover_state(produced_qty=25.0, cumulative_transferred=25.0, active_mr="MR-002")
        self.assertEqual(s4["lane"], "terkirim")
        self.assertEqual(s4["remaining_unrequested"], 0.0)
        self.assertFalse(s4["is_partial"])

    def test_allocate_pool_budget_multiple_warehouses_separately(self):
        """Pool allocations for different warehouses must be budgeted independently."""
        from production_app.api.handover import _allocate_pool_budget

        wos_wh_a = [
            {"work_order": "WO-A1", "produced_qty": 50.0, "unrequested_qty": 50.0},
            {"work_order": "WO-A2", "produced_qty": 50.0, "unrequested_qty": 50.0},
        ]
        wos_wh_b = [
            {"work_order": "WO-B1", "produced_qty": 100.0, "unrequested_qty": 100.0},
        ]

        # Warehouse A has 75 available (less than 100 needed)
        alloc_a, rem_a = _allocate_pool_budget(wos_wh_a, 75.0)
        self.assertEqual(alloc_a["WO-A1"]["allocated_qty"], 50.0)
        self.assertEqual(alloc_a["WO-A2"]["allocated_qty"], 25.0)
        self.assertEqual(alloc_a["WO-A2"]["unrequested_remainder"], 25.0)
        self.assertEqual(rem_a, 0.0)

        # Warehouse B has 100 available (exact match)
        alloc_b, rem_b = _allocate_pool_budget(wos_wh_b, 100.0)
        self.assertEqual(alloc_b["WO-B1"]["allocated_qty"], 100.0)
        self.assertEqual(alloc_b["WO-B1"]["unrequested_remainder"], 0.0)
        self.assertEqual(rem_b, 0.0)

    def test_reserved_by_wo_uses_outstanding_qty(self):
        """_reserved_by_wo must use outstanding_qty rather than initial requested qty."""
        from production_app.api.handover import _reserved_by_wo, LANE_REQUEST, LANE_KIRIM

        requests = [
            {
                "work_order": "WO-001",
                "lane": LANE_REQUEST,
                "flag": None,
                "qty": 25.0,
                "outstanding_qty": 4.0,  # 21 Pcs already transferred via SE
            },
            {
                "work_order": "WO-002",
                "lane": LANE_REQUEST,
                "flag": None,
                "qty": 50.0,
                "outstanding_qty": 50.0,  # untransferred
            },
            {
                "work_order": "WO-003",
                "lane": LANE_KIRIM,  # already in done lane
                "flag": None,
                "qty": 30.0,
                "outstanding_qty": 0.0,
            },
            {
                "work_order": "WO-004",
                "lane": LANE_REQUEST,
                "flag": "stopped",  # stopped MR
                "qty": 20.0,
                "outstanding_qty": 20.0,
            },
        ]
        res = _reserved_by_wo(requests)
        self.assertEqual(res.get("WO-001"), 4.0)  # NOT 25.0!
        self.assertEqual(res.get("WO-002"), 50.0)
        self.assertNotIn("WO-003", res)
        self.assertNotIn("WO-004", res)

    def test_reserved_by_item_warehouse_scoping(self):
        """_reserved_by_item must scope by MR row's from_warehouse and use outstanding_qty."""
        from production_app.api.handover import _reserved_by_item, LANE_REQUEST

        requests = [
            {
                "work_order": "WO-001",
                "item_code": "ITEM-A",
                "from_warehouse": "Warehouse Produksi 1",
                "lane": LANE_REQUEST,
                "flag": None,
                "qty": 25.0,
                "outstanding_qty": 4.0,
            },
            {
                "work_order": "WO-002",
                "item_code": "ITEM-A",
                "from_warehouse": "Warehouse Produksi 2",
                "lane": LANE_REQUEST,
                "flag": None,
                "qty": 30.0,
                "outstanding_qty": 30.0,
            },
        ]
        res = _reserved_by_item(requests, [])
        self.assertEqual(res.get(("ITEM-A", "Warehouse Produksi 1")), 4.0)
        self.assertEqual(res.get(("ITEM-A", "Warehouse Produksi 2")), 30.0)

    def test_sync_handover_summary_prevents_key_error_on_partial(self):
        """_sync_handover_summary must map state['lane'] safely without KeyError when lane is None."""
        from production_app.api.handover import _sync_handover_summary

        with patch("production_app.api.handover._handover_state") as mock_state:
            mock_state.return_value = {
                "WO-PARTIAL": {"lane": None, "mr": "MAT-MR-2026-0001", "partial": True}
            }
            fake_row = {
                "name": "WO-PARTIAL",
                "custom_handover_material_request": None,
                "custom_handover_status": None,
            }
            frappe.get_all.return_value = [frappe._dict(fake_row)]
            frappe.db.set_value = MagicMock()

            written = _sync_handover_summary(["WO-PARTIAL"])
            self.assertIn("WO-PARTIAL", written)
            frappe.db.set_value.assert_called_once()
            args = frappe.db.set_value.call_args[0]
            self.assertEqual(args[0], "Work Order")
            self.assertEqual(args[1], "WO-PARTIAL")
            self.assertEqual(args[2]["custom_handover_status"], "Diminta Gudang")
            self.assertEqual(args[2]["custom_handover_material_request"], "MAT-MR-2026-0001")

    def test_active_mr_now_lifecycle(self):
        """_active_mr_now returns True when remaining unfulfilled qty > 0, False when complete or stopped."""
        from production_app.api.handover import _active_mr_now

        # Case 1: Stopped MR -> False
        frappe.db.get_value.return_value = (1, "Stopped", 0.0)
        self.assertFalse(_active_mr_now("MR-STOPPED"))

        # Case 2: Transferred MR -> False
        frappe.db.get_value.return_value = (1, "Transferred", 100.0)
        self.assertFalse(_active_mr_now("MR-TRANSFERRED"))

        # Case 3: Submitted MR with 100% per_ordered -> False
        frappe.db.get_value.return_value = (1, "Submitted", 100.0)
        self.assertFalse(_active_mr_now("MR-100PCT"))

        # Case 4: Submitted MR with 4 Pcs outstanding -> True
        frappe.db.get_value.return_value = (1, "Submitted", 84.0)
        frappe.db.sql = MagicMock(return_value=[(4.0,)])
        self.assertTrue(_active_mr_now("MR-PARTIAL"))

        # Case 5: Submitted MR with 0 Pcs outstanding -> False
        frappe.db.sql = MagicMock(return_value=[(0.0,)])
        self.assertFalse(_active_mr_now("MR-COMPLETED-SQL"))

    def test_preview_handover_request_43_wo_e2e_characterization(self):
        """E2E characterization of preview_handover_request:
        43 WOs producing 1,096 Pcs, physical stock 1,096 Pcs, unlinked R&D MR reserving 4 Pcs.
        Available pool = 1,092 Pcs.
        Returns 1,071 Pcs across first 42 WOs and 21 Pcs for 43rd WO with 4 Pcs unrequested remainder.
        Deterministic fingerprint generated.
        """
        from production_app.api.handover import preview_handover_request

        wo_names = [f"PRO-WO-2026-{i:04d}" for i in range(1, 44)]
        wos_map = {}
        for i, name in enumerate(wo_names, start=1):
            qty = 26.0 if i <= 21 else 25.0
            wos_map[name] = frappe._dict({
                "name": name,
                "production_item": "PROD-001",
                "produced_qty": qty,
                "company": "Roti Ropi",
                "fg_warehouse": "Gudang Produksi - RR",
                "stock_uom": "Pcs",
            })

        frappe.get_doc = MagicMock(side_effect=lambda dt, name=None: wos_map.get(name))
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")

        # Mock DB queries:
        # 1. transferred_by_wo: empty []
        # 2. active_mrs for WOs: empty []
        # 3. physical stock: 1096.0
        # 4. external_mrs: [("MAT-MR-RD-001", "PROD-001", 4.0, "R&D Transfer")]
        # 5. live_handover_res: 0.0
        def fake_sql(query, values=None, as_dict=False, as_list=False, **kwargs):
            q = str(query)
            if "custom_work_order not in" in q:
                return [{"name": "MAT-MR-RD-001", "schedule_date": "2026-10-30", "target_warehouse": "Gudang R&D", "outstanding_qty": 4.0}]
            if "coalesce(sum(" in q and "mri.item_code = %s" in q:
                return [(4.0,)]
            if as_dict or "group by" in q.lower():
                return []
            return [(0.0,)]

        frappe.db.sql = MagicMock(side_effect=fake_sql)
        self._stock(1096.0)

        res = preview_handover_request(wo_names)
        self.assertTrue(res.get("ok"))
        allocations = res.get("allocations", [])
        self.assertEqual(len(allocations), 43)

        first_42_qty = sum(a["allocated_qty"] for a in allocations[:42])
        self.assertEqual(first_42_qty, 1071.0)
        for a in allocations[:42]:
            self.assertEqual(a["unrequested_remainder"], 0.0)

        wo43 = allocations[42]
        self.assertEqual(wo43["work_order"], "PRO-WO-2026-0043")
        self.assertEqual(wo43["allocated_qty"], 21.0)
        self.assertEqual(wo43["unrequested_remainder"], 4.0)

        # Check deterministic fingerprint
        fp = res.get("fingerprint")
        self.assertTrue(fp and len(fp) == 16)
        self.assertTrue(all(a.get("fingerprint") for a in allocations))

    def test_preview_handover_request_permission_enforcement(self):
        """preview_handover_request must enforce read permission on selected Work Orders."""
        from production_app.api.handover import preview_handover_request

        def fake_perm(doctype, ptype, doc=None, throw=False):
            if doctype == "Work Order" and doc == "PRO-WO-RESTRICTED":
                if throw:
                    raise frappe.PermissionError("Forbidden Work Order")
                return False
            return True

        frappe.has_permission = MagicMock(side_effect=fake_perm)

        with self.assertRaises(frappe.PermissionError):
            preview_handover_request(["PRO-WO-RESTRICTED"])

    def test_preview_handover_request_masks_unauthorized_external_mr(self):
        """When user lacks read permission on an external MR, preview masks the document name
        as 'Restricted' without changing pool availability deduction.
        """
        from production_app.api.handover import preview_handover_request

        wo = frappe._dict({
            "name": "PRO-WO-0001",
            "production_item": "PROD-001",
            "produced_qty": 25.0,
            "company": "Roti Ropi",
            "fg_warehouse": "Gudang Produksi - RR",
            "stock_uom": "Pcs",
        })
        frappe.get_doc = MagicMock(return_value=wo)
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")

        def fake_perm(doctype, ptype, doc=None, throw=False):
            if doctype == "Material Request" and doc == "MAT-MR-RD-SECRET":
                return False
            return True

        frappe.has_permission = MagicMock(side_effect=fake_perm)

        def fake_sql(query, values=None, as_dict=False, as_list=False, **kwargs):
            q = str(query)
            if "custom_work_order not in" in q:
                return [{"name": "MAT-MR-RD-SECRET", "schedule_date": "2026-10-30", "target_warehouse": "Gudang R&D", "outstanding_qty": 10.0}]
            if "coalesce(sum(" in q and "mri.item_code = %s" in q:
                return [(10.0,)]
            if as_dict or "group by" in q.lower():
                return []
            return [(0.0,)]

        frappe.db.sql = MagicMock(side_effect=fake_sql)
        self._stock(100.0)

        res = preview_handover_request(["PRO-WO-0001"])
        self.assertTrue(res.get("ok"))
        groups = res.get("groups", [])
        self.assertEqual(len(groups), 1)
        ext_res = groups[0].get("external_reservations", [])
        self.assertEqual(len(ext_res), 1)
        self.assertEqual(ext_res[0]["material_request"], "Restricted")
        self.assertEqual(ext_res[0]["quantity"], 10.0)
        # Pool deduction still occurred: 100 - 10 = 90
        self.assertEqual(groups[0]["available_pool"], 90.0)

    def test_preview_handover_request_fail_closed_unset_target_wh(self):
        """When target warehouse is unset, preview_handover_request fails closed (0 transfers counted)."""
        from production_app.api.handover import preview_handover_request

        wo = frappe._dict({
            "name": "PRO-WO-0001",
            "production_item": "PROD-001",
            "produced_qty": 25.0,
            "company": "Roti Ropi",
            "fg_warehouse": "Gudang Produksi - RR",
            "stock_uom": "Pcs",
        })
        frappe.get_doc = MagicMock(return_value=wo)
        frappe.db.get_single_value = MagicMock(return_value=None)  # Unset target warehouse

        res = preview_handover_request(["PRO-WO-0001"])
        self.assertTrue(res.get("ok"))
        alloc = res.get("allocations", [])[0]
        self.assertEqual(alloc["transferred_qty"], 0.0)

    def test_create_request_preview_fingerprint_binding(self):
        """create_request verifies preview_fingerprint under row lock:
        matching fingerprint proceeds; mismatched fingerprint throws ValidationError.
        """
        from production_app.api.handover import create_request

        wo = frappe._dict({
            "name": "PRO-WO-0001",
            "production_item": "PROD-001",
            "produced_qty": 25.0,
            "company": "Roti Ropi",
            "fg_warehouse": "Gudang Produksi - RR",
            "stock_uom": "Pcs",
            "precision": MagicMock(return_value=3),
        })
        frappe.get_doc = MagicMock(return_value=wo)
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")

        def fake_sql(query, values=None, **kwargs):
            return [(0.0,)]

        frappe.db.sql = MagicMock(side_effect=fake_sql)

        with patch("production_app.api.handover.preview_handover_request") as mock_preview:
            mock_preview.return_value = {
                "ok": True,
                "fingerprint": "valid_fingerprint",
                "allocations": [{"work_order": "PRO-WO-0001", "fingerprint": "row_fingerprint"}],
            }
            # Mismatched fingerprint raises ValidationError
            with self.assertRaises(frappe.ValidationError) as ctx:
                create_request("PRO-WO-0001", 25.0, preview_fingerprint="stale_fingerprint")
            self.assertIn("Status alokasi atau stok telah berubah", str(ctx.exception))

    def test_create_request_replay_after_completion_rejected(self):
        """A replayed create_request confirmation when an active request already exists is rejected."""
        from production_app.api.handover import create_request

        wo = frappe._dict({
            "name": "PRO-WO-0001",
            "production_item": "PROD-001",
            "produced_qty": 25.0,
            "company": "Roti Ropi",
            "fg_warehouse": "Gudang Produksi - RR",
            "stock_uom": "Pcs",
            "precision": MagicMock(return_value=3),
        })
        frappe.get_doc = MagicMock(return_value=wo)
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")

        # Mock DB showing 25 Pcs already actively requested
        frappe.db.sql = MagicMock(side_effect=[
            [(0.0,)],   # transferred
            [(25.0,)],  # active_req = 25.0 -> eligible_unrequested = 0.0
        ])

        with self.assertRaises(frappe.ValidationError) as ctx:
            create_request("PRO-WO-0001", requested_qty=None)
        err = str(ctx.exception)
        self.assertTrue(
            "tidak memiliki sisa hasil yang dapat diminta" in err
            or "sudah memiliki permintaan" in err
            or "sudah punya permintaan" in err,
            f"Unexpected error: {err}",
        )

    def test_create_group_request_preview_fingerprint_binding(self):
        """create_group_request rejects mismatched preview_fingerprint."""
        from production_app.api.handover import create_group_request

        wos = [
            frappe._dict({
                "name": f"PRO-WO-{i}",
                "docstatus": 1,
                "status": "Submitted",
                "production_item": "PROD-001",
                "produced_qty": 25.0,
                "company": "Roti Ropi",
                "fg_warehouse": "Gudang Produksi - RR",
                "stock_uom": "Pcs",
                "precision": MagicMock(return_value=3),
            })
            for i in (1, 2)
        ]
        frappe.get_doc = MagicMock(side_effect=lambda dt, name=None: next((w for w in wos if w.name == name), None))
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")
        frappe.db.get_value = MagicMock(return_value=1)
        frappe.db.sql = MagicMock(return_value=[(0.0,)])

        with patch("production_app.api.handover.preview_handover_request") as mock_preview:
            mock_preview.return_value = {
                "ok": True,
                "fingerprint": "valid_group_hash",
                "allocations": [],
            }
            with self.assertRaises(frappe.ValidationError) as ctx:
                create_group_request(["PRO-WO-1", "PRO-WO-2"], preview_fingerprint="mismatched_hash")
            self.assertIn("Status alokasi atau stok telah berubah", str(ctx.exception))

    def test_send_handover_lock_order_wo_then_mr(self):
        """send_handover must acquire locks in strictly consistent order:
        sorted Work Order names FIRST, then Material Request (eliminating MR->WO lock inversion).
        """
        from production_app.api.handover import send_handover

        mr_items = [
            frappe._dict({"name": "MRI-2", "custom_work_order": "PRO-WO-2026-0002", "stock_qty": 25.0, "qty": 25.0, "item_code": "ITEM-1", "from_warehouse": "Gudang Produksi - RR"}),
            frappe._dict({"name": "MRI-1", "custom_work_order": "PRO-WO-2026-0001", "stock_qty": 25.0, "qty": 25.0, "item_code": "ITEM-1", "from_warehouse": "Gudang Produksi - RR"}),
        ]
        mr = frappe._dict({
            "name": "MAT-MR-2026-0001",
            "docstatus": 1,
            "status": "Submitted",
            "per_ordered": 0.0,
            "items": mr_items,
            "set_from_warehouse": "Gudang Produksi - RR",
            "set_warehouse": "Gudang Barang Jadi - RR",
            "company": "Roti Ropi",
        })

        actual_transfers = [("MRI-2", 25.0)]
        lock_calls = []
        def record_get_value(doctype, name, fieldname=None, for_update=False):
            if for_update:
                lock_calls.append((doctype, name))
            if fieldname == "docstatus":
                return 1
            return name

        frappe.db.get_value = MagicMock(side_effect=record_get_value)

        def fake_sql(query, values=None, as_dict=False, as_list=False, **kwargs):
            q = str(query)
            if "group by sed.material_request_item" in q:
                return actual_transfers
            if as_dict or "group by" in q.lower():
                return []
            return [(0.0,)]

        frappe.db.sql = MagicMock(side_effect=fake_sql)
        self._stock(100.0)

        fake_se = frappe._dict({
            "name": "MAT-STE-2026-0001",
            "items": [
                frappe._dict({
                    "name": "SEI-1",
                    "material_request_item": "MRI-1",
                    "qty": 25.0,
                    "conversion_factor": 1.0,
                    "s_warehouse": "Gudang Produksi - RR",
                })
            ],
            "insert": MagicMock(),
            "submit": MagicMock(),
        })

        def fake_get_doc(*args, **kwargs):
            if args:
                if args[0] == "Material Request" or args[0] == mr.name:
                    return mr
                if args[0] == fake_se or (isinstance(args[0], dict) and args[0].get("name") == fake_se.name):
                    return fake_se
            return mr

        with patch("production_app.api.handover._handover_mr", return_value=mr), \
             patch("production_app.api.handover._checked_lot") as mock_lot, \
             patch("production_app.api.handover.make_mr_stock_entry", return_value=fake_se):
            mock_lot.return_value = frappe._dict({
                "work_order": "WO",
                "batchless": True,
                "batch": None,
                "stock_uom": "Pcs",
                "warehouse": "Gudang Produksi - RR",
            })
            frappe.get_doc = MagicMock(side_effect=fake_get_doc)

            send_handover("MAT-MR-2026-0001")

        # Verify lock order: WO-0001, WO-0002 (sorted order), then MAT-MR-2026-0001
        self.assertEqual(len(lock_calls), 3)
        self.assertEqual(lock_calls[0], ("Work Order", "PRO-WO-2026-0001"))
        self.assertEqual(lock_calls[1], ("Work Order", "PRO-WO-2026-0002"))
        self.assertEqual(lock_calls[2], ("Material Request", "MAT-MR-2026-0001"))

    def test_send_handover_partially_fulfilled_uses_remainder(self):
        """send_handover for a partially fulfilled MR (e.g. 21 of 25 Pcs transferred)
        uses remaining unfulfilled quantity (4 Pcs) via make_mr_stock_entry.
        """
        from production_app.api.handover import send_handover

        mr_items = [
            frappe._dict({
                "name": "MRI-1",
                "custom_work_order": "PRO-WO-2026-0001",
                "stock_qty": 25.0,
                "qty": 25.0,
                "item_code": "ITEM-1",
                "from_warehouse": "Gudang Produksi - RR",
            }),
        ]
        mr = frappe._dict({
            "name": "MAT-MR-2026-0001",
            "docstatus": 1,
            "status": "Submitted",
            "per_ordered": 84.0,  # 21 / 25 = 84% transferred
            "items": mr_items,
            "set_from_warehouse": "Gudang Produksi - RR",
            "set_warehouse": "Gudang Barang Jadi - RR",
            "company": "Roti Ropi",
        })

        # Actual submitted SED, not the mapper's ordered_qty counter, proves fulfillment.
        actual_transfers = [("MRI-1", 21.0)]

        # make_mr_stock_entry returns SE with remainder 4 Pcs
        se_item = frappe._dict({
            "name": "SEI-1",
            "material_request_item": "MRI-1",
            "qty": 4.0,  # remainder
            "conversion_factor": 1.0,
            "s_warehouse": "Gudang Produksi - RR",
            "t_warehouse": "Gudang Barang Jadi - RR",
        })
        fake_se = frappe._dict({
            "name": "MAT-STE-2026-0002",
            "items": [se_item],
            "insert": MagicMock(),
            "submit": MagicMock(),
        })

        def record_get_value(doctype, name, fieldname=None, for_update=False):
            if fieldname == "docstatus":
                return 1
            return name

        frappe.db.get_value = MagicMock(side_effect=record_get_value)

        def fake_sql(query, values=None, as_dict=False, as_list=False, **kwargs):
            q = str(query)
            if "group by sed.material_request_item" in q:
                return actual_transfers
            if as_dict or "group by" in q.lower():
                return []
            return [(0.0,)]

        frappe.db.sql = MagicMock(side_effect=fake_sql)
        self._stock(100.0)

        def fake_get_doc(*args, **kwargs):
            if args:
                if args[0] == "Material Request" or args[0] == mr.name:
                    return mr
                if args[0] == fake_se or (isinstance(args[0], dict) and args[0].get("name") == fake_se.name):
                    return fake_se
            return mr

        with patch("production_app.api.handover._handover_mr", return_value=mr), \
             patch("production_app.api.handover._checked_lot") as mock_lot, \
             patch("production_app.api.handover.make_mr_stock_entry", return_value=fake_se):
            mock_lot.return_value = frappe._dict({
                "work_order": "PRO-WO-2026-0001",
                "batchless": True,
                "batch": None,
                "stock_uom": "Pcs",
                "warehouse": "Gudang Produksi - RR",
            })
            frappe.get_doc = MagicMock(side_effect=fake_get_doc)

            res = send_handover("MAT-MR-2026-0001")
            self.assertTrue(res.get("ok"))
            self.assertEqual(se_item.transfer_qty, 4.0)
            frappe.get_doc = MagicMock(side_effect=lambda *args, **kwargs: fake_se if args and (args[0] == fake_se or isinstance(args[0], dict)) else mr)

            res = send_handover("MAT-MR-2026-0001")
            self.assertTrue(res.get("ok"))
            # An outdated native ordered_qty must not turn four remaining units into 25.
            for mapped_qty in (25.0, 3.0):
                se_item.qty = mapped_qty
                with self.subTest(mapped_qty=mapped_qty), self.assertRaises(frappe.ValidationError):
                    send_handover("MAT-MR-2026-0001")

    def test_handover_state_status_matrix(self):
        """_handover_state excludes 'Issued', 'Stopped', and 'Cancelled' from active candidates."""
        from production_app.api.handover import _handover_state

        wo_names = ["WO-ISSUED", "WO-STOPPED", "WO-CANCELLED", "WO-ACTIVE"]

        def fake_get_all(dt, filters=None, **kwargs):
            if dt == "Material Request Item":
                return [
                    frappe._dict({"parent": "MR-ISSUED", "custom_work_order": "WO-ISSUED"}),
                    frappe._dict({"parent": "MR-STOPPED", "custom_work_order": "WO-STOPPED"}),
                    frappe._dict({"parent": "MR-CANCELLED", "custom_work_order": "WO-CANCELLED"}),
                    frappe._dict({"parent": "MR-ACTIVE", "custom_work_order": "WO-ACTIVE"}),
                ]
            if dt == "Material Request":
                return [
                    frappe._dict({"name": "MR-ISSUED", "docstatus": 1, "status": "Issued", "creation": "2026-10-28"}),
                    frappe._dict({"name": "MR-STOPPED", "docstatus": 1, "status": "Stopped", "creation": "2026-10-28"}),
                    frappe._dict({"name": "MR-CANCELLED", "docstatus": 2, "status": "Cancelled", "creation": "2026-10-28"}),
                    frappe._dict({"name": "MR-ACTIVE", "docstatus": 1, "status": "Submitted", "creation": "2026-10-28"}),
                ]
            if dt == "Work Order":
                return [
                    ("WO-ISSUED", 25.0),
                    ("WO-STOPPED", 25.0),
                    ("WO-CANCELLED", 25.0),
                    ("WO-ACTIVE", 25.0),
                ]
            return []

        frappe.get_all = MagicMock(side_effect=fake_get_all)
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")
        frappe.db.sql = MagicMock(return_value=[])  # 0 transferred

        with patch("production_app.api.handover._sent_se_by_mr", return_value={}):
            state = _handover_state(wo_names)

        # WO-ISSUED must NOT be in lane request
        self.assertIsNone(state["WO-ISSUED"]["lane"])
        # WO-STOPPED must NOT be in lane request
        self.assertIsNone(state["WO-STOPPED"]["lane"])
        # WO-CANCELLED must NOT be in lane request
        self.assertNotIn("WO-CANCELLED", state)
        # WO-ACTIVE is in lane request
        self.assertEqual(state["WO-ACTIVE"]["lane"], "request")

    def test_cancelled_remainder_never_owns_transferred_summary_link(self):
        from production_app.api.handover import _handover_state

        cancelled = frappe._dict(name="MR-NEW", docstatus=2, status="Cancelled")
        fulfilled = frappe._dict(name="MR-OLD", docstatus=1, status="Transferred")

        def fake_get_all(dt, **kwargs):
            if dt == "Material Request Item":
                return [frappe._dict(parent=m.name, custom_work_order="WO-PARTIAL") for m in (cancelled, fulfilled)]
            if dt == "Material Request":
                return [cancelled, fulfilled]
            if dt == "Work Order":
                return [("WO-PARTIAL", 60.0)]
            return []

        frappe.get_all = MagicMock(side_effect=fake_get_all)
        with patch("production_app.api.handover._sent_se_by_mr", return_value={"MR-OLD": frappe._dict(name="SE-OLD")}):
            for transferred in (30.0, 60.0):
                frappe.db.sql = MagicMock(return_value=[("WO-PARTIAL", transferred)])
                with self.subTest(transferred=transferred):
                    state = _handover_state(["WO-PARTIAL"])["WO-PARTIAL"]
                    self.assertEqual(state["mr"], "MR-OLD")
                    self.assertEqual(state["lane"], "terkirim" if transferred == 60.0 else None)

    def test_source_warehouse_scope_configured_vs_historical(self):
        """New requests follow current configured source warehouse; stored old MR reservations
        stay actual recorded source warehouse from MRI.from_warehouse.
        """
        from production_app.api.handover import _reserved_by_item, _pool_warehouse

        # 1. Historical reservation retains recorded source warehouse
        reqs = [{
            "lane": "request",
            "flag": None,
            "item_code": "PROD-001",
            "from_warehouse": "Historical Warehouse - RR",
            "qty": 15.0,
            "outstanding_qty": 15.0,
        }]
        res = _reserved_by_item(reqs, [])
        self.assertEqual(res.get(("PROD-001", "Historical Warehouse - RR")), 15.0)

        # 2. New request uses configured source warehouse
        lot = frappe._dict({
            "warehouse": "Old Lot Warehouse - RR",
            "company": "Roti Ropi",
        })
        frappe.db.get_single_value = MagicMock(return_value="Newly Configured Warehouse - RR")
        src = _pool_warehouse(lot)
        self.assertEqual(src, "Newly Configured Warehouse - RR")

    def test_requests_issued_mr_terminal_treatment(self):
        """_requests around lines 496-505 must treat MR status 'Issued' as terminal (LANE_KIRIM),
        not LANE_REQUEST, even when outstanding > 0, so it never reserves batch/pool stock.
        """
        from production_app.api.handover import _requests, LANE_KIRIM, LANE_REQUEST, _reserved_by_item, _reserved_by_wo

        wo_lot = frappe._dict({
            "work_order": "WO-ISSUED-1",
            "qty_in_pack": 1,
            "adonan_ke": 1,
            "display_uom": "Pcs",
            "stock_uom": "Pcs",
            "produced_qty": 25.0,
        })
        m = frappe._dict({
            "name": "MR-ISSUED-1",
            "docstatus": 1,
            "status": "Issued",
            "set_from_warehouse": "Gudang Produksi - RR",
            "owner": "Administrator",
            "custom_qc_packing": None,
            "custom_handover_box_plan": None,
        })
        mri = frappe._dict({
            "name": "MRI-ISSUED-1",
            "parent": "MR-ISSUED-1",
            "custom_work_order": "WO-ISSUED-1",
            "stock_qty": 25.0,
            "qty": 25.0,
            "stock_uom": "Pcs",
            "item_code": "PROD-001",
            "item_name": "Product 001",
            "from_warehouse": "Gudang Produksi - RR",
        })

        def fake_get_all(dt, filters=None, pluck=None, **kwargs):
            if dt == "Material Request Item":
                if pluck == "parent":
                    return ["MR-ISSUED-1"]
                return [mri]
            if dt == "Material Request":
                return [m]
            return []

        frappe.get_all = MagicMock(side_effect=fake_get_all)
        frappe.get_list = MagicMock(return_value=[m])
        frappe.has_permission = MagicMock(return_value=True)
        frappe.db.sql = MagicMock(return_value=[])  # 0 transferred -> outstanding = 25.0 > 0

        reqs = _requests([wo_lot])
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        # Must be terminal (LANE_KIRIM), NOT LANE_REQUEST
        self.assertEqual(r["lane"], LANE_KIRIM)
        self.assertNotEqual(r["lane"], LANE_REQUEST)

        # Must NOT reserve stock in _reserved_by_wo or _reserved_by_item
        res_wo = _reserved_by_wo(reqs)
        res_item = _reserved_by_item(reqs, [wo_lot])
        self.assertEqual(res_wo.get("WO-ISSUED-1", 0.0), 0.0)
        self.assertEqual(res_item.get(("PROD-001", "Gudang Produksi - RR"), 0.0), 0.0)

    def test_create_request_rejects_nonfinite_requested_qty(self):
        """create_request must validate math.isfinite on requested_qty and reject
        NaN, Inf, -Inf, 0, or negative values with frappe.ValidationError.
        """
        from production_app.api.handover import create_request

        wo = frappe._dict({
            "name": "WO-FINITE-1",
            "docstatus": 1,
            "status": "Submitted",
            "production_item": "PROD-001",
            "produced_qty": 25.0,
            "company": "Roti Ropi",
            "fg_warehouse": "Gudang Produksi - RR",
            "stock_uom": "Pcs",
            "precision": MagicMock(return_value=3),
            "custom_handover_material_request": None,
        })
        frappe.get_doc = MagicMock(return_value=wo)
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")

        def fake_get_value(dt, name=None, fieldname=None, for_update=False):
            if fieldname == "custom_handover_material_request":
                return None
            if isinstance(fieldname, list):
                return (1, "Submitted", 0.0)
            return name or 1

        frappe.db.get_value = MagicMock(side_effect=fake_get_value)
        frappe.db.sql = MagicMock(return_value=[(0.0,)])

        with patch("production_app.api.handover._checked_lot") as mock_lot:
            mock_lot.return_value = frappe._dict({
                "work_order": "WO-FINITE-1",
                "batchless": True,
                "batch": None,
                "stock_uom": "Pcs",
                "warehouse": "Gudang Produksi - RR",
            })

            # Test string 'nan'
            with self.assertRaises(frappe.ValidationError):
                create_request("WO-FINITE-1", requested_qty="nan")

            # Test float('nan')
            with self.assertRaises(frappe.ValidationError):
                create_request("WO-FINITE-1", requested_qty=float("nan"))

            # Test string 'inf'
            with self.assertRaises(frappe.ValidationError):
                create_request("WO-FINITE-1", requested_qty="inf")

            # Test float('inf')
            with self.assertRaises(frappe.ValidationError):
                create_request("WO-FINITE-1", requested_qty=float("inf"))

            # Test float('-inf')
            with self.assertRaises(frappe.ValidationError):
                create_request("WO-FINITE-1", requested_qty=float("-inf"))

            # Test negative quantity
            with self.assertRaises(frappe.ValidationError):
                create_request("WO-FINITE-1", requested_qty=-5.0)

            # Test zero quantity
            with self.assertRaises(frappe.ValidationError):
                create_request("WO-FINITE-1", requested_qty=0.0)

    def test_create_group_request_rejects_nonfinite_allocations(self):
        """create_group_request must reject nonfinite allocation amounts (NaN, Inf, -Inf)
        with frappe.ValidationError.
        """
        from production_app.api.handover import create_group_request

        wos = [
            frappe._dict({
                "name": f"WO-GRP-{i}",
                "docstatus": 1,
                "status": "Submitted",
                "production_item": "PROD-001",
                "produced_qty": 25.0,
                "company": "Roti Ropi",
                "fg_warehouse": "Gudang Produksi - RR",
                "stock_uom": "Pcs",
                "precision": MagicMock(return_value=3),
                "custom_handover_material_request": None,
            })
            for i in (1, 2)
        ]
        frappe.get_doc = MagicMock(side_effect=lambda dt, name=None: next((w for w in wos if w.name == name), None))
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")

        def fake_get_value(dt, name=None, fieldname=None, for_update=False):
            if fieldname == "custom_handover_material_request":
                return None
            if isinstance(fieldname, list):
                return (1, "Submitted", 0.0)
            return name or 1

        frappe.db.get_value = MagicMock(side_effect=fake_get_value)
        frappe.db.sql = MagicMock(return_value=[(0.0,)])

        with patch("production_app.api.handover._checked_lot") as mock_lot:
            mock_lot.return_value = frappe._dict({
                "work_order": "WO-GRP-1",
                "batchless": True,
                "batch": None,
                "stock_uom": "Pcs",
                "warehouse": "Gudang Produksi - RR",
                "available_qty": 100.0,
                "physical_qty": 100.0,
            })

            # Test NaN in allocations
            with self.assertRaises(frappe.ValidationError):
                create_group_request(["WO-GRP-1", "WO-GRP-2"], allocations={"WO-GRP-1": "nan", "WO-GRP-2": 20.0})

            # Test Inf in allocations
            with self.assertRaises(frappe.ValidationError):
                create_group_request(["WO-GRP-1", "WO-GRP-2"], allocations={"WO-GRP-1": float("inf"), "WO-GRP-2": 20.0})

            # Test -Inf in allocations
            with self.assertRaises(frappe.ValidationError):
                create_group_request(["WO-GRP-1", "WO-GRP-2"], allocations={"WO-GRP-1": float("-inf"), "WO-GRP-2": 20.0})

    def test_create_group_request_skips_zero_allocation_member_without_lot(self):
        """A member previewed at 0 (depleted batch) is skipped before its lot is
        checked, so the rest of the group is still requested."""
        from production_app.api.handover import create_group_request

        wos = [
            frappe._dict({
                "name": f"WO-GRP-{i}",
                "docstatus": 1,
                "production_item": "PROD-001",
                "produced_qty": 5.0,
                "company": "Roti Ropi",
                "custom_handover_material_request": None,
            })
            for i in (1, 2)
        ]
        frappe.get_doc = MagicMock(side_effect=lambda dt, name=None: next((w for w in wos if w.name == name), None))
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")
        frappe.db.get_value = MagicMock(side_effect=lambda dt, name=None, fieldname=None, for_update=False: None if fieldname == "custom_handover_material_request" else (name or 1))
        frappe.db.sql = MagicMock(return_value=[(0.0,)])

        def fake_lot(wo_name):
            if wo_name == "WO-GRP-1":
                raise frappe.ValidationError("no lot available")
            return frappe._dict({"work_order": wo_name, "batchless": False, "batch": "B2", "stock_uom": "Pcs", "warehouse": "Cold - RR", "available_qty": 5.0, "physical_qty": 5.0})

        with patch("production_app.api.handover._checked_lot", side_effect=fake_lot), \
             patch("production_app.api.handover._insert_submitted_handover_mr", return_value=frappe._dict({"name": "MR-1"})) as insert, \
             patch("production_app.api.handover._build_board", return_value={}), \
             patch("production_app.api.handover._expected_unit_count", return_value=5), \
             patch("production_app.api.handover._enforce_whole_uom"):
            res = create_group_request(["WO-GRP-1", "WO-GRP-2"], allocations={"WO-GRP-1": 0, "WO-GRP-2": 5})

        self.assertEqual(res["material_request"], "MR-1")
        rows = insert.call_args[0][0]
        self.assertEqual([(wo.name, amount) for wo, amount, _uom, _src in rows], [("WO-GRP-2", 5.0)])


if __name__ == "__main__":
    unittest.main()

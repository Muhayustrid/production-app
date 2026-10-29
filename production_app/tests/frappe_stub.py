# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""In-process Frappe and ERPNext test stub harness.

Enables unit testing of Frappe and ERPNext endpoint functions without requiring
an active Frappe site or installed Frappe package in the host environment.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

def setup_frappe_stub():
    if "frappe" in sys.modules and hasattr(sys.modules["frappe"], "_is_test_stub"):
        return sys.modules["frappe"]

    def make_stub(name):
        if name in sys.modules:
            return sys.modules[name]
        m = ModuleType(name)
        m.__path__ = []
        sys.modules[name] = m
        return m

    f = make_stub("frappe")
    f._is_test_stub = True

    class ValidationError(Exception):
        pass

    class PermissionError(Exception):
        pass

    class QueryDeadlockError(Exception):
        pass

    f.ValidationError = ValidationError
    f.PermissionError = PermissionError
    f.QueryDeadlockError = QueryDeadlockError

    class DictLike(dict):
        def __getattr__(self, k):
            return self.get(k)
        def __setattr__(self, k, v):
            self[k] = v
        def __getattribute__(self, k):
            if k != "__dict__" and dict.__contains__(self, k):
                return dict.__getitem__(self, k)
            return super().__getattribute__(k)

    f._dict = DictLike
    f._ = lambda msg, *args: msg if not args else msg.format(*args)
    f.bold = lambda msg: msg
    f.whitelist = lambda *args, **kwargs: (lambda fn: fn)

    def _throw(msg, exc=ValidationError):
        raise exc(str(msg))

    f.throw = MagicMock(side_effect=_throw)
    f.logger = MagicMock()
    f.session = DictLike(user="Administrator")
    f.has_permission = MagicMock(return_value=True)
    f.get_roles = MagicMock(return_value=["Stock User", "Stock Manager", "Manufacturing User"])

    f.db = MagicMock()
    f.db.get_single_value = MagicMock(return_value=None)
    f.db.get_value = MagicMock(return_value=None)

    def _default_sql(query, values=None, as_dict=False, as_list=False):
        q = str(query)
        if "sum(" in q.lower() and not as_dict and not as_list and "group by" not in q.lower():
            return [(0.0,)]
        return []

    f.db.sql = MagicMock(side_effect=_default_sql)
    f.db.has_column = MagicMock(return_value=True)
    f.db.exists = MagicMock(return_value=True)
    f.db.set_value = MagicMock()
    f.db.commit = MagicMock()
    f.db.rollback = MagicMock()

    f.get_all = MagicMock(return_value=[])
    f.get_list = MagicMock(return_value=[])
    f.get_doc = MagicMock()
    f.new_doc = MagicMock()
    f.get_meta = MagicMock()

    fu = make_stub("frappe.utils")
    fu.cint = lambda v, d=0: int(v) if v is not None and str(v).isdigit() else d
    fu.flt = lambda v, p=None: float(v or 0)
    fu.get_datetime = MagicMock()
    fu.now_datetime = MagicMock()
    fu.add_days = MagicMock()
    fu.now = MagicMock()
    fu.get_link_to_form = MagicMock(return_value="")

    fd = make_stub("frappe.defaults")
    fd.get_user_default = MagicMock(return_value=None)
    fd.set_user_default = MagicMock()

    en = make_stub("erpnext")
    ens = make_stub("erpnext.stock")
    ensd = make_stub("erpnext.stock.doctype")

    ensdb = make_stub("erpnext.stock.doctype.batch")
    ensdbb = make_stub("erpnext.stock.doctype.batch.batch")
    ensdbb.get_batch_qty = MagicMock(return_value=0)

    ensd_sbb = make_stub("erpnext.stock.doctype.serial_and_batch_bundle")
    ensd_sbbb = make_stub("erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle")
    ensd_sbbb.get_available_batches = MagicMock(return_value=[])
    ensd_sbbb.get_stock_ledgers_batches = MagicMock(return_value=[])
    ensd_sbbb.update_available_batches = MagicMock()

    ensd_mr = make_stub("erpnext.stock.doctype.material_request")
    ensd_mrmr = make_stub("erpnext.stock.doctype.material_request.material_request")
    ensd_mrmr.make_stock_entry = MagicMock()

    return f

setup_frappe_stub()

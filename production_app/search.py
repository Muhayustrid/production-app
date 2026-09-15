# Extra Awesome Bar (⌘K) results — registered via hooks.awesomebar_search.
#
# Contract (frappe/desk/search.py::awesomebar_search): each hooked method receives
# the raw query text and returns dicts with label/value, description, route
# (string path, route list, or URL), and optional index (higher ranks first;
# built-in search is 100). The method itself must filter by txt.

import frappe

# "production app" harus cocok juga dengan kata kunci bahasa Indonesia.
HAYSTACKS = {
    "Production App": "production app produksi workspace produksi",
    "Work Orders": "work orders produksi daftar work order produksi",
}

ENTRIES = [
    {
        "label": "Production App",
        "description": "Buka Production Workspace",
        "route": "/production_workspace",
        "index": 105,
    },
    {
        "label": "Work Orders",
        "description": "Daftar Work Order produksi",
        "route": ["List", "Work Order"],
        "index": 60,
    },
]


def awesomebar_results(txt: str) -> list[dict]:
    query = frappe.utils.cstr(txt).strip().lower()
    if not query:
        return []
    results = []
    for entry in ENTRIES:
        haystack = HAYSTACKS.get(entry["label"], entry["label"]).lower()
        if query in haystack or haystack in query:
            results.append(entry)
    return results

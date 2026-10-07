# FU100: helper bersama rollout filter multi-value — satu sumber untuk semua
# modul api halaman. Terima list asli (JSON body), string JSON, atau skalar
# lama; kembalikan list bersih. Modul api lain (material_usage dst) mengimpor
# dari sini, bukan menyalin.

import json

import frappe


def filter_list(value, name, limit=100):
	"""FU100: nilai filter multi-value — terima list asli (JSON body), string
	JSON, atau skalar lama (pemanggil FU72 dst tak berubah); kembalikan
	list[str] bersih (trim, buang kosong, dedupe). [] = tanpa filter — JANGAN
	pernah membangun IN (). Nilai dikirim sebagai bound parameter, bukan
	f-string, jadi tidak ada celah injeksi; identifier tetap milik server
	(pola whitelist token `order` FU94). Melebihi `limit` → ValidationError."""
	if value is None:
		return []
	if isinstance(value, str):
		text = value.strip()
		if not text:
			return []
		try:
			parsed = json.loads(text)
		except ValueError:
			parsed = [text]
		if not isinstance(parsed, list):
			parsed = [parsed]
	elif isinstance(value, (list, tuple)):
		parsed = list(value)
	else:
		frappe.throw(f"Filter {name} tidak valid.", exc=frappe.ValidationError)
	out, seen = [], set()
	for item in parsed:
		item = str(item or "").strip()
		if item and item not in seen:
			seen.add(item)
			out.append(item)
	if len(out) > limit:
		frappe.throw(f"Filter {name} maksimal {limit} nilai.", exc=frappe.ValidationError)
	return out

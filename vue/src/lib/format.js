// Operator-facing number/date formatting (id-ID, spec 9 "angka besar" data).
export function formatQty(value) {
	return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 3 }).format(Number(value) || 0);
}

export function formatDate(value) {
	if (!value) return "-";
	const date = new Date(value);
	return Number.isNaN(date.getTime())
		? String(value)
		: date.toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
}

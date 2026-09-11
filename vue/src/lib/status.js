// Work Order status -> Indonesian dictionary (task 20). The server sends the
// English status values; the mapping lives in the SPA. Unknown values pass
// through unchanged so a future core status never renders blank.

const WO_STATUS_ID = {
	"Not Started": "Belum Mulai",
	"In Process": "Berjalan",
	Stopped: "Dihentikan",
	Closed: "Ditutup",
	Completed: "Selesai",
	// both reserved variants share one operator label (the blocked reason,
	// if any, carries the detail)
	"Stock Reserved": "Reservasi Stok",
	"Stock Partially Reserved": "Reservasi Stok",
	Cancelled: "Dibatalkan",
	Submitted: "Disetujui",
	Draft: "Draft",
};

const STOPPED_STATUSES = new Set(["Stopped", "Cancelled"]);
const FINISHED_STATUSES = new Set(["Completed", "Closed"]);

export function woStatusId(status) {
	return WO_STATUS_ID[status] || status || "";
}

// Chip color per status group (detail header): amber while stopped/cancelled,
// green once finished, neutral otherwise.
export function woStatusClass(status) {
	if (STOPPED_STATUSES.has(status)) return "bg-amber-100 text-amber-700";
	if (FINISHED_STATUSES.has(status)) return "bg-green-100 text-green-700";
	return "bg-gray-100 text-gray-700";
}

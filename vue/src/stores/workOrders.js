// Work Order state (spec 9): the open list + a detail cache per WO, with
// centralized refresh. A plain reactive module - two screens do not need a
// state library.
import { reactive } from "vue";

// Relative imports with extensions so `node --test` can exercise this module
// without the Vite "@" alias (same convention as api/).
import { ApiError, reportError } from "../api/client.js";
import { getWorkOrderDetail, getWorkOrders } from "../api/workOrders.js";

export const workOrderStore = reactive({
	// List filters (task 24): ISO date strings from <input type="date"> plus
	// the combined search box (item name/code or the WO number). Shared here
	// so error retries and reloads keep them.
	filters: { dateFrom: "", dateTo: "", item: "" },
	list: [],
	listLoading: false,
	listError: null,
	// name -> { loading, error, data } (Vue 3 makes nested Maps reactive)
	details: new Map(),
});

let currentDetailName = null;

export async function loadList() {
	workOrderStore.listLoading = true;
	workOrderStore.listError = null;
	try {
		const result = await getWorkOrders(workOrderStore.filters);
		workOrderStore.list = result.work_orders;
	} catch (error) {
		workOrderStore.listError = errorMessage(error);
		// One surface (task 22): the banner (listError + "Coba Lagi") covers the
		// no-rows case; the toast fires only when stale rows stay on screen
		// (no banner then).
		if (workOrderStore.list.length) reportError(error);
	} finally {
		workOrderStore.listLoading = false;
	}
}

// Synchronous reactive entry per WO (pages bind to it immediately; the async
// fetch below fills it in).
export function detailEntry(name) {
	let entry = workOrderStore.details.get(name);
	if (!entry) {
		entry = reactive({ loading: false, error: null, data: null });
		workOrderStore.details.set(name, entry);
	}
	return entry;
}

// Stale-while-revalidate: cached data renders instantly and stays visible
// while a fresh copy loads; concurrent loads for the same WO are collapsed.
export async function loadDetail(name, { force = false } = {}) {
	currentDetailName = name;
	const entry = detailEntry(name);
	if (entry.loading) {
		return entry;
	}
	entry.loading = true;
	entry.error = null;
	if (force) {
		entry.data = null;
	}
	try {
		entry.data = await getWorkOrderDetail(name);
	} catch (error) {
		entry.error = errorMessage(error);
		// Same one-surface rule: the full-screen error banner covers the
		// no-data case; toast only when stale cached data stays on screen.
		if (entry.data) reportError(error);
	} finally {
		entry.loading = false;
	}
	return entry;
}

// STATE_CHANGED auto-reload (9.3): main.js's central api error handler calls
// this after toasting, so a lost race refreshes the confirmed state.
export function reloadCurrentDetail() {
	if (currentDetailName) {
		loadDetail(currentDetailName, { force: true });
	}
}

// Post-action refresh (tab mutations): swap in the fresh detail without the
// skeleton flash - stale data stays on screen if the refresh fails (error is
// toasted centrally).
export async function refreshDetail(name) {
	try {
		detailEntry(name).data = await getWorkOrderDetail(name);
	} catch (error) {
		reportError(error);
	}
}

function errorMessage(error) {
	return error instanceof ApiError ? error.message : "Terjadi kesalahan tak terduga.";
}

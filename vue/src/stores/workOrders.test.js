// One-surface rule for the list error (task 22, polish e): the banner
// (listError + "Coba Lagi") is THE surface when no rows are shown; the toast
// fires ONLY when stale rows stay on screen (no banner then). Regression pin:
// the condition used to be inverted (toast + banner together on empty, and a
// silent failure with stale rows). Run with: yarn test
import assert from "node:assert/strict";
import test from "node:test";

// minimal document stub: cookie for the api client, createElement so vue's
// module init (templateContainer) can run outside a browser
globalThis.document = { cookie: "csrf_token=t22", createElement: () => ({}) };

const { ApiError, setApiErrorHandler } = await import("../api/client.js");
const { workOrderStore, loadList } = await import("./workOrders.js");

function failingServer() {
	const originalFetch = globalThis.fetch;
	globalThis.fetch = async () => ({
		ok: false,
		status: 500,
		json: async () => ({
			_server_messages: JSON.stringify([JSON.stringify({ message: "server rusak" })]),
		}),
	});
	return () => {
		globalThis.fetch = originalFetch;
	};
}

function reset(toasts) {
	workOrderStore.list = [];
	workOrderStore.listLoading = false;
	workOrderStore.listError = null;
	setApiErrorHandler((error) => toasts.push(error instanceof ApiError ? error.message : "?"));
}

test("empty list failure: banner only - no toast", async () => {
	const toasts = [];
	const restore = failingServer();
	try {
		reset(toasts);
		await loadList("");
	} finally {
		restore();
	}
	assert.equal(workOrderStore.listError, "server rusak");
	assert.deepEqual(toasts, []);
});

test("stale rows failure: toast only - rows stay, no banner", async () => {
	const toasts = [];
	const restore = failingServer();
	try {
		reset(toasts);
		workOrderStore.list = [{ name: "PDTC-WO-0001", item: "PDTC-FG" }];
		await loadList("");
	} finally {
		restore();
	}
	assert.equal(workOrderStore.listError, "server rusak");
	assert.equal(workOrderStore.list.length, 1); // stale rows remain visible
	assert.deepEqual(toasts, ["server rusak"]);
});

// Wire-payload pins for the mutation wrappers (task 19, lesson from task 18):
// createMutation appends the idempotency key AFTER the caller's arguments, so
// every wrapper must keep `key` as its LAST parameter. These tests execute the
// committed wrappers with a stubbed fetch and assert the exact wire body, so
// an argument can never silently drift into the wrong payload field again.
// Run with: yarn test
import assert from "node:assert/strict";
import test from "node:test";

globalThis.document = { cookie: "csrf_token=t19" };

const { cancelLastStep, cancelProduction, closeWorkOrder, finishProduction } = await import(
	"./workOrders.js"
);

async function capture(action, ...args) {
	const bodies = [];
	const originalFetch = globalThis.fetch;
	globalThis.fetch = async (url, options) => {
		bodies.push({ url, body: JSON.parse(options.body) });
		return { ok: true, json: async () => ({ message: {} }) };
	};
	try {
		await action(...args);
	} finally {
		globalThis.fetch = originalFetch;
	}
	const first = bodies[0];
	assert.equal(first.url.startsWith("/api/method/production_app.api."), true);
	assert.match(first.body.idempotency_key, /^[0-9a-f-]{36}$/);
	return first;
}

test("finishProduction maps (workOrder, packing) to the wire payload", async () => {
	const packing = {
		good: 100,
		reject: 2,
		trial: 1,
		sisa: 0,
		loss_eksplisit: 0,
		is_final: true,
		petugas_packing: "pdtc.operator@example.com",
		bahan_dipakai: { "PDTC-RM1": 9.5 },
	};
	const { url, body } = await capture(finishProduction, "PDTC-WO-1", packing);
	assert.equal(url, "/api/method/production_app.api.finish_production");
	assert.equal(body.work_order, "PDTC-WO-1");
	assert.deepEqual(body.packing, packing); // passed through as one object
	assert.equal(body.packing.bahan_dipakai["PDTC-RM1"], 9.5);
	assert.equal(body.packing.is_final, true);
});

test("cancelLastStep maps expectedTarget to expected_target", async () => {
	const { url, body } = await capture(cancelLastStep, "PDTC-WO-1", "MAT-STE-2026-00099");
	assert.equal(url, "/api/method/production_app.api.cancel_last_step");
	assert.equal(body.work_order, "PDTC-WO-1");
	assert.equal(body.expected_target, "MAT-STE-2026-00099");
});

test("cancelProduction maps expectedFingerprint to expected_fingerprint", async () => {
	const fingerprint = "a".repeat(64);
	const { url, body } = await capture(cancelProduction, "PDTC-WO-1", fingerprint);
	assert.equal(url, "/api/method/production_app.api.cancel_production");
	assert.equal(body.work_order, "PDTC-WO-1");
	assert.equal(body.expected_fingerprint, fingerprint);
});

test("closeWorkOrder maps reason to reason", async () => {
	const { url, body } = await capture(closeWorkOrder, "PDTC-WO-1", "hasil kurang, sisa 5");
	assert.equal(url, "/api/method/production_app.api.close_work_order");
	assert.equal(body.work_order, "PDTC-WO-1");
	assert.equal(body.reason, "hasil kurang, sisa 5");
});

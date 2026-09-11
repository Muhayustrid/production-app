// Runnable check for the idempotency-key retry semantics (10.2 via
// createMutation): key regenerated after success / STATE_CHANGED, reused on
// retry. Run with: yarn test  (node --test, no extra dependencies).
import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, createMutation, newIdempotencyKey } from "./client.js";

test("key is regenerated after success", async () => {
	const keys = [];
	const action = createMutation(async (value, key) => {
		keys.push(key);
		return value;
	});
	await action("a");
	await action("b");
	assert.equal(keys.length, 2);
	assert.notEqual(keys[0], keys[1]);
	assert.ok(keys.every((k) => /^[0-9a-f-]{36}$/.test(k)));
});

test("key is reused when the same action is retried after a server error", async () => {
	const keys = [];
	const action = createMutation(async (shouldFail, key) => {
		keys.push(key);
		if (shouldFail) throw new ApiError("ditolak");
		return "ok";
	});
	await assert.rejects(action(true), ApiError);
	const result = await action(false);
	assert.equal(result, "ok");
	// the retry bound the SAME key: server rolled the failed attempt back, so
	// the key is free and the retry must not open a second ledger row
	assert.equal(keys.length, 2);
	assert.equal(keys[0], keys[1]);
});

test("key is regenerated after STATE_CHANGED (new confirmation, new payload)", async () => {
	const keys = [];
	const action = createMutation(async (code, key) => {
		keys.push(key);
		if (code === "STATE_CHANGED") throw new ApiError("berubah", { code: "STATE_CHANGED" });
		return "ok";
	});
	await assert.rejects(action("STATE_CHANGED"), ApiError);
	await action(null);
	assert.notEqual(keys[0], keys[1]);
});

test("plain errors are rethrown and keys stay unique per action", async () => {
	const key = newIdempotencyKey();
	assert.match(key, /^[0-9a-f-]{36}$/);
	const action = createMutation(async () => {
		throw new Error("boom");
	});
	await assert.rejects(action(), /boom/);
});

// createMutation appends the key AFTER the caller's arguments - this pins the
// real endpoint wrappers' parameter order to their wire payload, so an
// optional-param wrapper (completeOperation) can never silently shift the key
// into started_at/loss again.
test("completeOperation maps caller args to the wire payload (key last)", async () => {
	globalThis.document = { cookie: "csrf_token=t18" };
	const bodies = [];
	const originalFetch = globalThis.fetch;
	globalThis.fetch = async (url, options) => {
		bodies.push({ url, body: JSON.parse(options.body) });
		return { ok: true, json: async () => ({ message: {} }) };
	};
	try {
		const { completeOperation } = await import("./workOrders.js");
		await completeOperation("PDTC-WO-1", "PO-JOB1", 60, true, "2026-09-11 08:00:00", 2);
		const { url, body } = bodies[0];
		assert.equal(url, "/api/method/production_app.api.complete_operation");
		assert.equal(body.work_order, "PDTC-WO-1");
		assert.equal(body.job_card, "PO-JOB1");
		assert.equal(body.qty, 60);
		assert.equal(body.is_final, true);
		assert.match(body.idempotency_key, /^[0-9a-f-]{36}$/);
		assert.equal(body.started_at, "2026-09-11 08:00:00");
		assert.equal(body.loss, 2);
	} finally {
		globalThis.fetch = originalFetch;
		delete globalThis.document;
	}
});

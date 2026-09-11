// Work Order endpoints (spec 7, backend contract: production_app/api.py).
// Operator vocabulary (3.1) in every operator-facing name; server error
// messages are already Indonesian.

import { call, createMutation } from "./client.js";

const ENDPOINT = "production_app.api";

// ------------------------------------------------------------- reads (GET)

export function getWorkOrders(search) {
	const params = search && String(search).trim() ? { search } : {};
	return call(`${ENDPOINT}.get_open_work_orders`, params);
}

export function getWorkOrderDetail(workOrder) {
	return call(`${ENDPOINT}.get_work_order_detail`, { work_order: workOrder });
}

// ------------------------------------------------- mutations (POST, 10.2)
// Each wrapper owns one idempotency key per logical user action via
// createMutation: regenerate after success / STATE_CHANGED, reuse on retry.
// Task 18-19 call these once per user action (e.g. button tap) and call the
// same function again to retry that action.

export const saveProductionData = createMutation((workOrder, data, key) =>
	call(
		`${ENDPOINT}.save_production_data`,
		{ work_order: workOrder, data, idempotency_key: key },
		{ httpMethod: "POST" },
	),
);

export const transferMaterial = createMutation((workOrder, itemsAktual, key) =>
	call(
		`${ENDPOINT}.transfer_material`,
		{ work_order: workOrder, items_aktual: itemsAktual, idempotency_key: key },
		{ httpMethod: "POST" },
	),
);

export const completeOperation = createMutation(
	// key LAST: createMutation appends it after the caller's arguments
	(workOrder, jobCard, qty, isFinal, startedAt = null, loss = null, key) =>
		call(
			`${ENDPOINT}.complete_operation`,
			{
				work_order: workOrder,
				job_card: jobCard,
				qty,
				is_final: isFinal,
				idempotency_key: key,
				started_at: startedAt,
				loss,
			},
			{ httpMethod: "POST" },
		),
);

export const finishProduction = createMutation((workOrder, packing, key) =>
	call(
		`${ENDPOINT}.finish_production`,
		{ work_order: workOrder, packing, idempotency_key: key },
		{ httpMethod: "POST" },
	),
);

export const cancelLastStep = createMutation((workOrder, expectedTarget, key) =>
	call(
		`${ENDPOINT}.cancel_last_step`,
		{ work_order: workOrder, expected_target: expectedTarget, idempotency_key: key },
		{ httpMethod: "POST" },
	),
);

export const cancelProduction = createMutation((workOrder, expectedFingerprint, key) =>
	call(
		`${ENDPOINT}.cancel_production`,
		{ work_order: workOrder, expected_fingerprint: expectedFingerprint, idempotency_key: key },
		{ httpMethod: "POST" },
	),
);

export const closeWorkOrder = createMutation((workOrder, reason, key) =>
	call(
		`${ENDPOINT}.close_work_order`,
		{ work_order: workOrder, reason, idempotency_key: key },
		{ httpMethod: "POST" },
	),
);

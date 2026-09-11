// Frappe API client (frappe.call semantics over fetch) + central error
// surface. Relative imports only so `node --test` can exercise this module
// without the Vite "@" alias.

import { getCookie } from "../lib/cookies.js";

// Server exception class names (production_app/exceptions.py) mapped to the
// machine-readable codes the SPA keys its behavior off (spec 7).
export const STATE_CHANGED = "STATE_CHANGED";
export const NEEDS_ALLOWANCE = "NEEDS_ALLOWANCE";

const EXC_TYPE_CODES = {
	StateChangedError: STATE_CHANGED,
	NeedsAllowanceError: NEEDS_ALLOWANCE,
};

const NETWORK_MESSAGE = "Tidak dapat terhubung ke server - periksa koneksi lalu coba lagi.";

export class ApiError extends Error {
	constructor(message, { code = null, httpStatus = 0 } = {}) {
		super(message);
		this.name = "ApiError";
		this.code = code;
		this.httpStatus = httpStatus;
	}
}

/**
 * Call a whitelisted method, e.g. `call("frappe.auth.get_logged_user")`.
 * Returns the `message` payload. GET by default; pass
 * `{ httpMethod: "POST" }` for mutations.
 */
export async function call(method, params = {}, { httpMethod = "GET" } = {}) {
	const url = `/api/method/${method}`;
	if (httpMethod === "GET") {
		const query = new URLSearchParams(params).toString();
		return unwrap(await fetch(query ? `${url}?${query}` : url));
	}

	const response = await fetch(url, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": getCookie("csrf_token") || "",
		},
		body: JSON.stringify(params),
	});
	return unwrap(response);
}

async function unwrap(response) {
	let data = null;
	try {
		data = await response.json();
	} catch {
		// non-JSON body (proxy error page etc.) - handled as a generic error
	}
	if (!response.ok) {
		throw toApiError(data, response.status);
	}
	return data.message;
}

function toApiError(data, httpStatus) {
	// _server_messages is a JSON array of JSON-encoded {message} objects.
	let message = "";
	try {
		const messages = JSON.parse(data?._server_messages || "[]");
		message = messages.map((m) => JSON.parse(m).message).join(" ");
	} catch {
		message = "";
	}
	if (!message) {
		// coded errors (e.g. STATE_CHANGED) carry no _server_messages - their
		// text is the LAST traceback line: "pkg.mod.ErrorName: the message"
		const last = (data?.exception || "").split("\n").filter(Boolean).pop() || "";
		message = last.includes(": ") ? last.split(": ").slice(1).join(": ") : "";
	}
	message = message || "Terjadi kesalahan tak terduga.";
	return new ApiError(message, {
		code: EXC_TYPE_CODES[data?.exc_type] || null,
		httpStatus,
	});
}

/**
 * UUID key for Production Request Log idempotency (spec 10.2).
 */
export function newIdempotencyKey() {
	return crypto.randomUUID();
}

/**
 * Idempotency-key lifecycle for one logical user action (10.2): the key is
 * generated once per action, REUSED when the user retries (network error or
 * server rejection - both roll back, so the key stays free and, in the
 * crash-only "Processing" window, reuse is required), and REGENERATED after
 * success (the ledger row is Done; a different payload with the same key
 * would be a binding violation) and after STATE_CHANGED (nothing mutated,
 * but the re-confirmation carries a different payload).
 *
 * `run` receives the managed key as its last argument.
 */
export function createMutation(run) {
	let key = newIdempotencyKey();
	return async (...args) => {
		try {
			const result = await run(...args, key);
			key = newIdempotencyKey();
			return result;
		} catch (error) {
			if (error instanceof ApiError && error.code === STATE_CHANGED) {
				key = newIdempotencyKey();
			}
			throw error;
		}
	};
}

// Central error surface: pages/stores call reportError(); main.js installs a
// handler that toasts and triggers the STATE_CHANGED auto-reload.
let errorHandler = null;

export function setApiErrorHandler(fn) {
	errorHandler = fn;
}

export function reportError(error) {
	const apiError =
		error instanceof ApiError ? error : new ApiError(NETWORK_MESSAGE, { code: "NETWORK" });
	errorHandler?.(apiError);
}

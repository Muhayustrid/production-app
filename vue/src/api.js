// Minimal Frappe API client (frappe.call semantics over fetch).
// POST uses the session csrf_token cookie (set by Frappe for logged-in
// sessions) — no new backend endpoints required.

function getCookie(name) {
	const cookies = new URLSearchParams(document.cookie.split("; ").join("&"));
	return cookies.get(name);
}

async function handleResponse(response) {
	const data = await response.json();
	if (!response.ok) {
		handleError(data);
		throw new Error(data?._server_messages || data?.exception || response.statusText);
	}
	return data.message;
}

/**
 * Call a whitelisted method, e.g. `call("frappe.auth.get_logged_user")`.
 * Returns the `message` payload. GET by default; pass
 * `{ method: "POST" }` for mutations.
 */
export async function call(method, params = {}, { method: httpMethod = "GET" } = {}) {
	const url = `/api/method/${method}`;
	if (httpMethod === "GET") {
		const query = new URLSearchParams(params).toString();
		return handleResponse(await fetch(query ? `${url}?${query}` : url));
	}

	const response = await fetch(url, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": getCookie("csrf_token") || "",
		},
		body: JSON.stringify(params),
	});
	return handleResponse(response);
}

/**
 * UUID key for Production Request Log idempotency (spec 10.2): generate once
 * per logical request and reuse it across retries.
 */
export function newIdempotencyKey() {
	return crypto.randomUUID();
}

// Placeholder — the real toast/error surface lands in Tahap 4.
export function handleError(error) {
	console.error("[production_app]", error);
}

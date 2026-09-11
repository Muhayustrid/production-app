// Shared cookie helper (used by the api client for the CSRF token and by the
// router guard for the session check).
export function getCookie(name) {
	const cookies = new URLSearchParams(document.cookie.split("; ").join("&"));
	return cookies.get(name);
}

// Minimal toast queue (spec 9.3 error surface). No frappe-ui dependency:
// three fields and a timer cover info/warning/error.
import { reactive } from "vue";

export const toasts = reactive([]);
let sequence = 0;

export function showToast(message, kind = "info") {
	const id = ++sequence;
	toasts.push({ id, message, kind });
	setTimeout(() => {
		const index = toasts.findIndex((toast) => toast.id === id);
		if (index !== -1) toasts.splice(index, 1);
	}, 5000);
}

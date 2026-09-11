// MULAI timestamps per open job card (7.5, honest duration P13c). Module
// level: survives tab switches. ponytail: lost on a full page reload - the
// duration simply stays unrecorded, which the UI says out loud.
import { reactive } from "vue";

export const operationStarts = reactive({});

// Server rejects timezone-aware datetimes (MySQL naive column) and its frame
// is the site timezone - so MULAI is sent as the DEVICE's naive local time.
// ponytail: duration skews by the device-vs-site tz difference; real floor
// devices share the site tz. Send UTC instead only if the API ever converts.
export function formatNaiveLocal(date) {
	const pad = (n) => String(n).padStart(2, "0");
	return (
		`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
		`${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
	);
}

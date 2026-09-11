<template>
	<div class="md:col-span-2">
		<p v-if="locked" class="rounded-xl bg-amber-50 p-3 text-sm text-amber-700">
			Work Order selesai - data produksi terkunci.
		</p>

		<!-- metadata form (8.2 whitelist, frontend mirror of the server's
		     editable fields); fields absent on the site are hidden (8.3) -->
		<template v-else>
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
				<div v-for="field in editableFields" :key="field.fieldname">
					<label class="text-sm font-medium" :for="`prod-${field.fieldname}`">{{ field.label }}</label>
					<input
						v-if="field.type === 'int'"
						:id="`prod-${field.fieldname}`"
						v-model.number="form[field.fieldname]"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="number"
						inputmode="numeric"
						step="1"
						min="0"
					/>
					<input
						v-else-if="field.type === 'float'"
						:id="`prod-${field.fieldname}`"
						v-model.number="form[field.fieldname]"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="number"
						inputmode="decimal"
						step="any"
						min="0"
					/>
					<input
						v-else-if="field.type === 'time'"
						:id="`prod-${field.fieldname}`"
						v-model="form[field.fieldname]"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="time"
					/>
					<input
						v-else-if="field.type === 'datetime'"
						:id="`prod-${field.fieldname}`"
						v-model="form[field.fieldname]"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="datetime-local"
					/>
					<input
						v-else
						:id="`prod-${field.fieldname}`"
						v-model="form[field.fieldname]"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						:type="field.type === 'user' ? 'email' : 'text'"
						:placeholder="field.type === 'user' ? 'email pengguna' : ''"
					/>
				</div>
			</div>
			<p class="mt-2 text-xs text-gray-500">Perubahan tersimpan otomatis.</p>
		</template>

		<!-- read-only display fields (8.2), when the site defines them -->
		<dl v-if="displayFields.length" class="mt-4 space-y-1 rounded-xl border border-gray-200 bg-white p-3 text-sm">
			<div v-for="field in displayFields" :key="field.fieldname" class="flex justify-between gap-2">
				<dt class="text-gray-500">{{ field.label }}</dt>
				<dd class="text-right font-medium">{{ form[field.fieldname] || "-" }}</dd>
			</div>
		</dl>
	</div>
</template>

<script setup>
import { computed, reactive, watch } from "vue";

import { saveProductionData } from "@/api/workOrders";
import { reportError } from "@/api/client";
import { getCookie } from "@/lib/cookies";
import { showToast } from "@/composables/toast";

// Frontend mirror of api.EDITABLE_METADATA_FIELDS (7.3): labels in operator
// language, input type per the site's fieldtypes (Int/Data/Time/Float/Link
// User/Datetime - verified on the metadata). Link User defaults to the login
// user and stays free-text; the server validates the link (7.3).
const FIELD_CONFIG = [
	{ fieldname: "custom_adonan_ke", label: "Adonan ke", type: "int" },
	{ fieldname: "custom_adonan", label: "Adonan", type: "text" },
	{ fieldname: "custom_jam_adonan", label: "Jam Adonan", type: "time" },
	{ fieldname: "custom_suhu_adonan", label: "Suhu Adonan", type: "float" },
	{ fieldname: "custom_nama_penimbang", label: "Nama Penimbang", type: "user" },
	{ fieldname: "custom_jam_pembekuan", label: "Jam Pembekuan", type: "datetime" },
	{ fieldname: "custom_qc_produksi", label: "QC Produksi", type: "user" },
	{ fieldname: "custom_jumlah_kru", label: "Jumlah Kru", type: "int" },
	{ fieldname: "custom_leader_produksi", label: "Leader Produksi", type: "user" },
];
const DISPLAY_CONFIG = [
	{ fieldname: "custom_qty_in_uom", label: "Qty (dalam UOM)" },
	{ fieldname: "custom_uom", label: "UOM" },
	{ fieldname: "custom_conversion_factor", label: "Faktor Konversi" },
	{ fieldname: "custom_item_name_information", label: "Info Nama Item" },
];

const props = defineProps({
	name: { type: String, default: "" },
	detail: { type: Object, default: null },
});

const metadata = computed(() => props.detail?.production_metadata || {});
// 8.3: only fields the site actually has
const editableFields = computed(() => FIELD_CONFIG.filter((f) => f.fieldname in metadata.value));
const displayFields = computed(() => DISPLAY_CONFIG.filter((f) => f.fieldname in metadata.value));
const locked = computed(() =>
	["Completed", "Closed", "Cancelled"].includes(props.detail?.work_order?.status),
);

// Datetimes arrive as "YYYY-MM-DD HH:MM:SS" - the native inputs want
// "T"-separated / second-less values; both directions normalized.
function toInputValue(field, value) {
	if (value == null || value === "") return "";
	if (field.type === "time") return String(value).slice(0, 5);
	if (field.type === "datetime") return String(value).replace(" ", "T").slice(0, 16);
	return value;
}

const form = reactive({});
const baseline = reactive({});

function initForm() {
	const login = getCookie("user_id") || "";
	for (const field of editableFields.value) {
		let value = toInputValue(field, metadata.value[field.fieldname]);
		if (!value && field.type === "user") {
			value = login; // petugas default = user login, boleh diganti (8.2)
		}
		form[field.fieldname] = value;
		baseline[field.fieldname] = value;
	}
	for (const field of displayFields.value) {
		form[field.fieldname] = metadata.value[field.fieldname];
	}
}

function isDirty() {
	return editableFields.value.some((f) => form[f.fieldname] !== baseline[f.fieldname]);
}

watch(
	() => props.detail?.production_metadata,
	() => {
		// a reload (e.g. STATE_CHANGED) resyncs only when nothing is unsaved
		if (!isDirty()) initForm();
	},
	{ immediate: true },
);

// Autosave (7.3): debounced 800 ms, payload = ONLY the changed fields.
let timer = null;
let saving = false;

function scheduleSave() {
	clearTimeout(timer);
	timer = setTimeout(saveChanged, 800);
}

watch(form, scheduleSave, { deep: true });

async function saveChanged() {
	if (saving) return scheduleSave(); // change landed mid-save: run again
	const data = {};
	for (const field of editableFields.value) {
		const value = form[field.fieldname];
		if (value !== baseline[field.fieldname]) {
			data[field.fieldname] = value === "" ? null : value;
		}
	}
	if (!Object.keys(data).length) return;
	saving = true;
	try {
		await saveProductionData(props.name, data);
		Object.assign(baseline, data);
		showToast("Tersimpan", "info");
	} catch (error) {
		// toast shown centrally; edits stay and retry on the next change
		reportError(error);
	} finally {
		saving = false;
		if (isDirty()) scheduleSave();
	}
}
</script>

<template>
	<div class="md:col-span-2 space-y-4">
		<!-- ringkasan kumulatif per kategori (8.1 aggregation) + petugas/jam
		     terakhir - only fields the site actually has (8.3) -->
		<section v-if="summaryRows.length || lastPacking" class="rounded-xl border border-gray-200 bg-white p-3">
			<p class="text-sm font-semibold">Ringkasan Kumulatif</p>
			<dl class="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
				<div v-for="row in summaryRows" :key="row.key" class="flex justify-between gap-2">
					<dt class="text-gray-500">{{ row.label }}</dt>
					<dd class="font-medium">{{ formatQty(row.value) }}</dd>
				</div>
				<template v-if="lastPacking">
					<div class="flex justify-between gap-2">
						<dt class="text-gray-500">Petugas Packing terakhir</dt>
						<dd class="font-medium">{{ lastPacking.petugas }}</dd>
					</div>
					<div class="flex justify-between gap-2">
						<dt class="text-gray-500">Jam Packing terakhir</dt>
						<dd class="font-medium">{{ formatTime(lastPacking.time) }}</dd>
					</div>
				</template>
			</dl>
		</section>

		<!-- sisa bahan di WIP per material (9.2) -->
		<section v-if="materials.length" class="rounded-xl border border-gray-200 bg-white p-3">
			<p class="text-sm font-semibold">Sisa Bahan di WIP</p>
			<dl class="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
				<div v-for="material in materials" :key="material.item_code" class="flex justify-between gap-2">
					<dt class="text-gray-500">{{ material.item_code }}</dt>
					<dd class="font-medium">{{ formatQty(material.sisa_wip) }}</dd>
				</div>
			</dl>
		</section>

		<!-- kronologi: SE transfer/manufacture/consumption + job cards (9.2) -->
		<section class="rounded-xl border border-gray-200 bg-white p-3">
			<p class="text-sm font-semibold">Kronologi</p>
			<p v-if="!entries.length && !cards.length" class="mt-2 text-sm text-gray-500">
				Belum ada transaksi produksi.
			</p>
			<ul class="mt-2 divide-y divide-gray-100">
				<li v-for="event in chronology" :key="event.key" class="flex items-start gap-3 py-2">
					<component :is="event.icon" class="mt-0.5 h-5 w-5 shrink-0 text-gray-500" />
					<div class="min-w-0 flex-1">
						<p class="truncate text-sm font-medium">{{ event.title }}</p>
						<p class="truncate text-xs text-gray-500">
							{{ event.name }}
							<template v-if="event.qty != null"> - {{ formatQty(event.qty) }}</template>
							<template v-if="event.time"> - {{ formatTime(event.time) }}</template>
							<template v-if="event.petugas"> - {{ event.petugas }}</template>
						</p>
					</div>
					<span
						class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
						:class="event.done ? 'bg-green-50 text-green-700' : event.draft ? 'bg-gray-100 text-gray-600' : 'bg-red-50 text-red-700'"
					>
						{{ event.status }}
					</span>
				</li>
			</ul>
		</section>

		<!-- cancel actions (7.7, supervisor-only; server re-checks the role) -->
		<section class="rounded-xl border border-gray-200 bg-white p-3">
			<button
				class="min-h-[44px] w-full rounded-lg border border-blue-600 px-4 font-medium text-blue-700 active:bg-blue-50 disabled:border-gray-300 disabled:font-normal disabled:text-gray-400"
				:disabled="!isSupervisor || !nextTarget || busy"
				@click="openCancelStep"
			>
				Batalkan Langkah Terakhir
			</button>
			<p v-if="!isSupervisor" class="mt-1 text-xs text-gray-500">
				Hanya Supervisor yang dapat membatalkan.
			</p>
			<p v-else-if="!nextTarget" class="mt-1 text-xs text-gray-500">
				Tidak ada langkah yang dapat dibatalkan.
			</p>

			<button
				class="mt-2 min-h-[44px] w-full rounded-lg bg-red-600 px-4 font-semibold text-white active:bg-red-700 disabled:bg-gray-300"
				:disabled="!isSupervisor || busy"
				@click="cancelStage = 1"
			>
				Batalkan Produksi
			</button>
			<p v-if="!isSupervisor" class="mt-1 text-xs text-gray-500">
				Hanya Supervisor yang dapat membatalkan.
			</p>
		</section>

		<!-- Batalkan Langkah Terakhir: names the CONCRETE server-provided target -->
		<div v-if="cancelStepOpen" class="fixed inset-0 z-30 flex items-end justify-center bg-black/40 sm:items-center">
			<div
				class="w-full max-w-md rounded-t-2xl bg-white p-4 sm:rounded-2xl"
				role="dialog"
				aria-modal="true"
				aria-label="Batalkan Langkah Terakhir"
			>
				<div class="flex items-center justify-between">
					<h2 class="text-lg font-semibold">Batalkan Langkah Terakhir</h2>
					<button
						class="flex h-11 w-11 items-center justify-center rounded-lg active:bg-gray-100"
						aria-label="Tutup"
						@click="cancelStepOpen = false"
					>
						<X class="h-5 w-5" />
					</button>
				</div>
				<p class="mt-2 text-sm text-gray-700">{{ targetDescription }}</p>
				<button
					class="mt-4 min-h-[48px] w-full rounded-xl bg-blue-600 font-semibold text-white active:bg-blue-700 disabled:bg-gray-300"
					:disabled="busy"
					@click="cancelStep"
				>
					Batalkan
				</button>
			</div>
		</div>

		<!-- Batalkan Produksi: 2x confirm + ketik nomor WO (9.2) -->
		<div v-if="cancelStage" class="fixed inset-0 z-30 flex items-end justify-center bg-black/40 sm:items-center">
			<div
				class="w-full max-w-md rounded-t-2xl bg-white p-4 sm:rounded-2xl"
				role="dialog"
				aria-modal="true"
				aria-label="Batalkan Produksi"
			>
				<div class="flex items-center justify-between">
					<h2 class="flex items-center gap-2 text-lg font-semibold text-red-700">
						<AlertTriangle class="h-5 w-5" />
						Batalkan Produksi
					</h2>
					<button
						class="flex h-11 w-11 items-center justify-center rounded-lg active:bg-gray-100"
						aria-label="Tutup"
						@click="cancelStage = 0"
					>
						<X class="h-5 w-5" />
					</button>
				</div>
				<template v-if="cancelStage === 1">
					<p class="mt-2 text-sm text-gray-700">
						Seluruh Stock Entry dan kartu operasi pada Work Order {{ name }} akan dibatalkan,
						lalu Work Order itu sendiri. Tindakan ini tidak dapat dibatalkan.
					</p>
					<button
						class="mt-4 min-h-[48px] w-full rounded-xl bg-red-600 font-semibold text-white active:bg-red-700"
						@click="cancelStage = 2"
					>
						Lanjut
					</button>
				</template>
				<template v-else>
					<p class="mt-2 text-sm text-gray-700">
						Ketik nomor Work Order ({{ name }}) untuk mengonfirmasi.
					</p>
					<input
						v-model="cancelTyping"
						class="mt-2 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="text"
						aria-label="Nomor Work Order"
					/>
					<button
						class="mt-4 min-h-[48px] w-full rounded-xl bg-red-600 font-semibold text-white active:bg-red-700 disabled:bg-gray-300"
						:disabled="cancelTyping.trim() !== name || busy"
						@click="cancelProductionNow"
					>
						Batalkan Produksi
					</button>
				</template>
			</div>
		</div>
	</div>
</template>

<script setup>
import { ArrowLeftRight, Factory, Hammer, PackageMinus, AlertTriangle, X } from "lucide-vue-next";
import { computed, ref } from "vue";

import { cancelLastStep, cancelProduction } from "@/api/workOrders";
import { reportError } from "@/api/client";
import { showToast } from "@/composables/toast";
import { formatDate, formatQty } from "@/lib/format";
import { refreshDetail } from "@/stores/workOrders";

const props = defineProps({
	name: { type: String, default: "" },
	detail: { type: Object, default: null },
});

// purpose -> icon + operator label (kamus 3.1)
const SE_KINDS = {
	"Material Transfer for Manufacture": { icon: ArrowLeftRight, label: "Transfer Bahan" },
	Manufacture: { icon: Factory, label: "Packing / Hasil" },
	"Material Consumption for Manufacture": { icon: PackageMinus, label: "Pemakaian Bahan" },
};

const materials = computed(() => props.detail?.materials || []);
const isSupervisor = computed(() => Boolean(props.detail?.is_supervisor));
// the server is the sole authority on cancel intent (poka-yoke): the UI only
// renders cancel_fingerprint / cancel_next_target, never computes them
const nextTarget = computed(() => props.detail?.cancel_next_target || null);

// packing_summary keys are SITE-OWNED (8.3): render only what the server sent
const SUMMARY_LABELS = [
	["custom_good_qty_postpacking", "Hasil Baik"],
	["custom_reject_qty_postpacking", "Reject"],
	["custom_trial_qty_postpacking", "Trial"],
	["custom_sisa_qty_postpacking", "Sisa"],
	["custom_good_qty_prepacking", "Hasil Baik (Pre)"],
	["custom_reject_qty_prepacking", "Reject (Pre)"],
	["custom_trial_qty_prepacking", "Trial (Pre)"],
	["custom_sisa_qty_prepacking", "Sisa (Pre)"],
];
const summaryRows = computed(() => {
	const summary = props.detail?.packing_summary || {};
	return SUMMARY_LABELS.filter(([key]) => key in summary).map(([key, label]) => ({
		key,
		label,
		value: summary[key],
	}));
});
const lastPacking = computed(() => {
	// exactly what the server aggregated (petugas/jam of the last packing
	// session); a Desk-only WO leaves both empty -> section hidden
	const summary = props.detail?.packing_summary || {};
	if (!summary.custom_qc_packing && !summary.custom_jam_packing) return null;
	return { petugas: summary.custom_qc_packing || "-", time: summary.custom_jam_packing };
});

function formatTime(value) {
	if (!value) return "-";
	const text = String(value);
	const date = formatDate(text.slice(0, 10));
	return `${date} ${text.slice(11, 16)}`;
}

// chronology: submitted SEs (oldest first, with time + petugas) then the
// job cards (the detail payload carries no JC timestamps - shown undated)
const entries = computed(() => props.detail?.stock_entries || []);
const cards = computed(() => props.detail?.job_cards || []);

const chronology = computed(() => {
	const list = entries.value.map((entry) => {
		const kind = SE_KINDS[entry.purpose] || { icon: Factory, label: entry.purpose };
		// Manufacture shows the app-recorded good; Desk-made Manufacture rows
		// (good 0) and Transfer/Consumption fall back to the core-maintained
		// WO coverage (fg_completed_qty)
		const qty =
			entry.purpose === "Manufacture" && entry.good > 0 ? entry.good : entry.fg_completed_qty || null;
		return {
			key: `SE-${entry.name}`,
			icon: kind.icon,
			title: kind.label,
			name: entry.name,
			qty,
			time: entry.posting_datetime,
			petugas: entry.petugas_packing,
			done: entry.docstatus === 1,
			draft: entry.docstatus === 0,
			status: entry.docstatus === 1 ? "Selesai" : entry.docstatus === 0 ? "Draft" : "Dibatalkan",
		};
	});
	list.push(
		...cards.value.map((card) => ({
			key: `JC-${card.name}`,
			icon: Hammer,
			title: `Operasi ${card.operation}`,
			name: card.name,
			qty: card.total_completed_qty > 0 ? card.total_completed_qty : null,
			time: null,
			petugas: null,
			done: card.docstatus === 1,
			draft: card.docstatus === 0,
			status: card.docstatus === 1 ? "Selesai" : card.docstatus === 0 ? "Draft" : "Dibatalkan",
		})),
	);
	return list;
});

// confirmation names the concrete target document (9.2): enrich the
// server-provided doctype/name with the entry's own recorded details
const targetDescription = computed(() => {
	const target = nextTarget.value;
	if (!target) return "";
	const entry = entries.value.find((candidate) => candidate.name === target.name);
	if (target.doctype === "Job Card") {
		const card = cards.value.find((candidate) => candidate.name === target.name);
		return `Batalkan kartu operasi ${target.name}${card ? ` - operasi ${card.operation}` : ""}?`;
	}
	const what = entry ? (entry.purpose === "Manufacture" ? "packing" : "transfer bahan") : "";
	const qtyText = entry && entry.good > 0 ? ` ${formatQty(entry.good)} pcs` : "";
	const byText = entry ? ` oleh ${entry.petugas_packing} jam ${formatTime(entry.posting_datetime).split(" ").pop()}` : "";
	return `Batalkan SE ${target.name}${what ? ` - ${what}${qtyText}${byText}` : ""}?`;
});

const cancelStepOpen = ref(false);
const cancelStage = ref(0);
const cancelTyping = ref("");
const busy = ref(false);

function openCancelStep() {
	cancelStepOpen.value = true;
}

async function cancelStep() {
	const target = nextTarget.value;
	if (!target || busy.value) return;
	busy.value = true;
	try {
		const result = await cancelLastStep(props.name, target.name);
		cancelStepOpen.value = false;
		showToast(`Dibatalkan: ${result.cancelled.name}`);
		await refreshDetail(props.name);
	} catch (error) {
		// STATE_CHANGED (target moved on) auto-reloads; pre-check blocks arrive
		// as Indonesian toasts - both land via the central handler
		reportError(error);
	} finally {
		busy.value = false;
	}
}

async function cancelProductionNow() {
	if (busy.value || cancelTyping.value.trim() !== props.name) return;
	busy.value = true;
	try {
		await cancelProduction(props.name, props.detail.cancel_fingerprint);
		cancelStage.value = 0;
		cancelTyping.value = "";
		showToast(`Produksi ${props.name} dibatalkan`);
		await refreshDetail(props.name);
	} catch (error) {
		reportError(error);
	} finally {
		busy.value = false;
	}
}
</script>

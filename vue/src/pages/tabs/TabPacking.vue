<template>
	<div class="md:col-span-2">
		<!-- honest no-op states (server re-checks everything anyway) -->
		<p
			v-if="blockedReason"
			class="flex items-center gap-2 rounded-xl bg-amber-50 p-4 text-sm text-amber-700"
		>
			<AlertTriangle class="h-5 w-5 shrink-0" />
			{{ blockedReason }}
		</p>
		<template v-else-if="!canPack">
			<p class="flex items-center justify-center gap-2 rounded-xl bg-green-50 p-4 font-medium text-green-700">
				<CheckCircle2 class="h-6 w-6" />
				Target produksi sudah tercapai - tidak ada sesi packing yang perlu dibuat.
			</p>
		</template>

		<!-- packing form (7.6 / 9.2): good + kategori hasil, pre opsional,
		     loss hanya di mode rinci, bahan dipakai default = sisa WIP net -->
		<template v-else>
			<div class="rounded-xl border border-gray-200 bg-white p-3">
				<label class="text-sm font-medium" for="pack-good">Hasil Baik</label>
				<input
					id="pack-good"
					v-model.number="form.good"
					class="mt-1 min-h-[48px] w-full rounded-lg border border-gray-300 px-3 text-lg font-semibold focus:border-blue-500 focus:outline-none"
					type="number"
					inputmode="decimal"
					min="0"
					step="any"
				/>
				<p class="mt-1 text-xs text-gray-500">Default: belum diproduksi ({{ formatQty(belum) }}).</p>

				<div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
					<div>
						<label class="text-sm font-medium" for="pack-reject">Reject</label>
						<input
							id="pack-reject"
							v-model.number="form.reject"
							class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
							type="number"
							inputmode="decimal"
							min="0"
							step="any"
						/>
					</div>
					<div>
						<label class="text-sm font-medium" for="pack-trial">Trial</label>
						<input
							id="pack-trial"
							v-model.number="form.trial"
							class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
							type="number"
							inputmode="decimal"
							min="0"
							step="any"
						/>
					</div>
					<div>
						<label class="text-sm font-medium" for="pack-sisa">Sisa</label>
						<input
							id="pack-sisa"
							v-model.number="form.sisa"
							class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
							type="number"
							inputmode="decimal"
							min="0"
							step="any"
						/>
					</div>
				</div>
				<p class="mt-1 text-xs text-gray-500">Reject / Trial / Sisa hanya dicatat - tidak menjadi stok.</p>

				<!-- pre-packing readings: opsional, default tertutup -->
				<details class="mt-3 rounded-lg border border-gray-200">
					<summary class="min-h-[44px] cursor-pointer px-3 py-2.5 text-sm font-medium text-gray-600">
						Data Pre-Packing (opsional)
					</summary>
					<div class="grid grid-cols-1 gap-3 p-3 pt-0 sm:grid-cols-4">
						<div>
							<label class="text-xs font-medium" for="pack-good-pre">Hasil Baik</label>
							<input
								id="pack-good-pre"
								v-model.number="form.good_pre"
								class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
								type="number"
								inputmode="decimal"
								min="0"
								step="any"
							/>
						</div>
						<div>
							<label class="text-xs font-medium" for="pack-reject-pre">Reject</label>
							<input
								id="pack-reject-pre"
								v-model.number="form.reject_pre"
								class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
								type="number"
								inputmode="decimal"
								min="0"
								step="any"
							/>
						</div>
						<div>
							<label class="text-xs font-medium" for="pack-trial-pre">Trial</label>
							<input
								id="pack-trial-pre"
								v-model.number="form.trial_pre"
								class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
								type="number"
								inputmode="decimal"
								min="0"
								step="any"
							/>
						</div>
						<div>
							<label class="text-xs font-medium" for="pack-sisa-pre">Sisa</label>
							<input
								id="pack-sisa-pre"
								v-model.number="form.sisa_pre"
								class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
								type="number"
								inputmode="decimal"
								min="0"
								step="any"
							/>
						</div>
					</div>
				</details>

				<!-- loss eksplisit: hanya di mode rinci (default 0) -->
				<label class="mt-3 flex min-h-[44px] items-center gap-2 text-sm font-medium">
					<input v-model="detailMode" type="checkbox" class="h-5 w-5" />
					Mode rinci
				</label>
				<div v-if="detailMode">
					<label class="text-sm font-medium" for="pack-loss">Loss Eksplisit</label>
					<input
						id="pack-loss"
						v-model.number="form.loss"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="number"
						inputmode="decimal"
						min="0"
						step="any"
					/>
					<p class="mt-1 text-xs text-gray-500">Loss nyata yang tercatat sebagai kehilangan produksi.</p>
				</div>

				<label class="mt-3 flex min-h-[44px] items-center gap-2 text-sm font-medium">
					<input v-model="form.isFinal" type="checkbox" class="h-5 w-5" />
					Selesai (final)
				</label>
				<p class="text-xs text-gray-500">
					Final berarti sesi ini menutup sisa target; bila masih ada sisa, diputuskan setelah sesi.
				</p>
			</div>

			<!-- Bahan Dipakai (3.2): default = sisa WIP net; hanya angka yang
			     diUBAH dikirim sebagai pemakaian eksplisit (INV5) -->
			<div v-if="materials.length" class="rounded-xl border border-gray-200 bg-white p-3">
				<p class="text-sm font-semibold">Bahan Dipakai</p>
				<p v-if="skipTransfer" class="mt-1 text-xs text-gray-500">
					Tanpa pengambilan bahan: bahan dikonsumsi langsung dari gudang asal (default = resep).
				</p>
				<div v-for="material in materials" :key="material.item_code" class="mt-2">
					<label class="text-sm font-medium" :for="`pakai-${material.item_code}`">
						{{ material.item_code }} - sisa di WIP {{ formatQty(material.sisa_wip) }}
					</label>
					<input
						:id="`pakai-${material.item_code}`"
						v-model.number="edits[material.item_code]"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="number"
						inputmode="decimal"
						min="0"
						step="any"
					/>
					<p class="mt-0.5 text-xs text-gray-500">
						Sisa bahan di WIP setelah sesi: {{ formatQty(sisaAfter(material)) }}
					</p>
				</div>
			</div>

			<!-- live ringkasan (9.2) -->
			<dl class="rounded-xl border border-gray-200 bg-white p-3 text-sm">
				<div class="flex justify-between gap-2 py-0.5">
					<dt class="text-gray-500">Diproses sesi ini (hasil baik + loss)</dt>
					<dd class="font-semibold">{{ formatQty(diproses) }}</dd>
				</div>
				<div class="flex justify-between gap-2 py-0.5">
					<dt class="text-gray-500">Belum diproduksi setelah sesi</dt>
					<dd class="font-semibold" :class="after < 0 ? 'text-red-600' : ''">
						{{ formatQty(after) }}
						<span v-if="after < 0">- melebihi target, perlu toleransi dari admin</span>
					</dd>
				</div>
			</dl>

			<button
				class="mt-3 min-h-[48px] w-full rounded-xl bg-blue-600 font-semibold text-white active:bg-blue-700 disabled:bg-gray-300"
				:disabled="!valid"
				@click="confirmOpen = true"
			>
				<template v-if="valid">Selesaikan Produksi</template>
				<template v-else>Isi Hasil Baik lebih besar dari 0</template>
			</button>
		</template>

		<!-- konfirmasi ringkas: angka final + petugas (9.2) -->
		<div v-if="confirmOpen" class="fixed inset-0 z-30 flex items-end justify-center bg-black/40 sm:items-center">
			<div
				class="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-4 sm:rounded-2xl"
				role="dialog"
				aria-modal="true"
				aria-label="Konfirmasi Sesi Packing"
			>
				<div class="flex items-center justify-between">
					<h2 class="text-lg font-semibold">Konfirmasi Sesi Packing</h2>
					<button
						class="flex h-11 w-11 items-center justify-center rounded-lg active:bg-gray-100"
						aria-label="Tutup"
						@click="confirmOpen = false"
					>
						<X class="h-5 w-5" />
					</button>
				</div>
				<dl class="mt-2 space-y-1 text-sm">
					<div class="flex justify-between gap-2">
						<dt class="text-gray-500">Hasil Baik</dt>
						<dd class="font-semibold">{{ formatQty(form.good) }}</dd>
					</div>
					<div v-if="form.reject > 0" class="flex justify-between gap-2">
						<dt class="text-gray-500">Reject</dt>
						<dd class="font-medium">{{ formatQty(form.reject) }}</dd>
					</div>
					<div v-if="form.trial > 0" class="flex justify-between gap-2">
						<dt class="text-gray-500">Trial</dt>
						<dd class="font-medium">{{ formatQty(form.trial) }}</dd>
					</div>
					<div v-if="form.sisa > 0" class="flex justify-between gap-2">
						<dt class="text-gray-500">Sisa</dt>
						<dd class="font-medium">{{ formatQty(form.sisa) }}</dd>
					</div>
					<div v-if="form.loss > 0" class="flex justify-between gap-2">
						<dt class="text-gray-500">Loss Eksplisit</dt>
						<dd class="font-medium">{{ formatQty(form.loss) }}</dd>
					</div>
					<div class="flex justify-between gap-2">
						<dt class="text-gray-500">Sesi final</dt>
						<dd class="font-medium">{{ form.isFinal ? "Ya" : "Tidak" }}</dd>
					</div>
					<div v-for="change in bahanChanges" :key="change.item" class="flex justify-between gap-2">
						<dt class="text-gray-500">Bahan Dipakai {{ change.item }}</dt>
						<dd class="font-medium">{{ formatQty(change.value) }}</dd>
					</div>
					<div class="flex justify-between gap-2">
						<dt class="text-gray-500">Petugas Packing</dt>
						<dd class="font-medium">{{ form.petugas }}</dd>
					</div>
				</dl>
				<button
					class="mt-4 min-h-[48px] w-full rounded-xl bg-blue-600 font-semibold text-white active:bg-blue-700 disabled:bg-gray-300"
					:disabled="submitting"
					@click="submit"
				>
					SELESAIKAN PRODUKSI
				</button>
			</div>
		</div>

		<!-- 3.4: final short of target -> explicit close decision, no auto action -->
		<div v-if="closeDecision" class="fixed inset-0 z-30 flex items-end justify-center bg-black/40 sm:items-center">
			<div
				class="w-full max-w-md rounded-t-2xl bg-white p-4 sm:rounded-2xl"
				role="dialog"
				aria-modal="true"
				aria-label="Keputusan Penutupan"
			>
				<h2 class="flex items-center gap-2 text-lg font-semibold">
					<AlertTriangle class="h-5 w-5 text-amber-500" />
					Sisa target {{ formatQty(closeDecision.remaining_target) }}
				</h2>
				<p class="mt-1 text-sm text-gray-600">
					Sesi tercatat, tetapi target belum tercapai penuh. Tutup Work Order, atau biarkan terbuka.
				</p>
				<template v-if="isSupervisor">
					<label class="mt-3 block text-sm font-medium" for="close-reason">Alasan penutupan</label>
					<input
						id="close-reason"
						v-model="closeReason"
						class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
						type="text"
					/>
					<button
						class="mt-3 min-h-[48px] w-full rounded-xl bg-blue-600 font-semibold text-white active:bg-blue-700 disabled:bg-gray-300"
						:disabled="!closeReason.trim() || submitting"
						@click="closeWorkOrderNow"
					>
						Tutup WO (Supervisor)
					</button>
				</template>
				<p v-else class="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-700">
					Penutupan hanya oleh Supervisor - minta Supervisor menutup Work Order ini.
				</p>
				<button
					class="mt-2 min-h-[44px] w-full rounded-xl border border-gray-300 font-medium text-gray-700 active:bg-gray-100"
					@click="closeDecision = null"
				>
					Biarkan terbuka
				</button>
			</div>
		</div>
	</div>
</template>

<script setup>
import { AlertTriangle, CheckCircle2, X } from "lucide-vue-next";
import { computed, reactive, ref, watch } from "vue";

import { closeWorkOrder, finishProduction } from "@/api/workOrders";
import { reportError } from "@/api/client";
import { getCookie } from "@/lib/cookies";
import { showToast } from "@/composables/toast";
import { formatQty } from "@/lib/format";
import { refreshDetail } from "@/stores/workOrders";

const props = defineProps({
	name: { type: String, default: "" },
	detail: { type: Object, default: null },
});

const wo = computed(() => props.detail?.work_order);
const belum = computed(() => Number(wo.value?.belum_diproduksi) || 0);
const materials = computed(() => props.detail?.materials || []);
const isSupervisor = computed(() => Boolean(props.detail?.is_supervisor));
const skipTransfer = computed(() => Boolean(wo.value?.skip_transfer));
const blockedReason = computed(() => {
	const reasons = props.detail?.blocked_reasons || [];
	return reasons.length ? reasons[0] : "";
});
const canPack = computed(() => !blockedReason.value && belum.value > 0);

const detailMode = ref(false);
const form = reactive({
	good: 0,
	reject: 0,
	trial: 0,
	sisa: 0,
	good_pre: 0,
	reject_pre: 0,
	trial_pre: 0,
	sisa_pre: 0,
	loss: 0,
	isFinal: false,
	petugas: "",
});
const edits = reactive({});

function initForm() {
	form.good = belum.value;
	form.reject = 0;
	form.trial = 0;
	form.sisa = 0;
	form.good_pre = 0;
	form.reject_pre = 0;
	form.trial_pre = 0;
	form.sisa_pre = 0;
	form.loss = 0;
	form.isFinal = false;
	form.petugas = getCookie("user_id") || "";
	detailMode.value = false;
	Object.keys(edits).forEach((key) => delete edits[key]);
	for (const material of materials.value) {
		edits[material.item_code] = material.sisa_wip;
	}
}

watch(() => props.detail, initForm, { immediate: true });

// poka-yoke reuses the detail's own defaults when the detail reloads (e.g.
// STATE_CHANGED); unsaved inputs reset to the fresh server truth.
const diproses = computed(() => (Number(form.good) || 0) + (Number(form.loss) || 0));
const after = computed(() => belum.value - diproses.value);

// auto-on when the session exactly covers the remaining target (9.2); the
// operator can still untick it (a partial session is legal)
watch(diproses, (value) => {
	if (belum.value > 0 && value === belum.value) form.isFinal = true;
});

// only items the operator actually CHANGED count as pemakaian eksplisit;
// a cleared input is not a zero intent - the item is omitted entirely
const changed = (material) => {
	const raw = edits[material.item_code];
	return raw !== "" && raw != null && Number(raw) !== material.sisa_wip;
};

function sisaAfter(material) {
	const used = changed(material) ? Number(edits[material.item_code]) || 0 : material.sisa_wip;
	return (Number(material.sisa_wip) || 0) - used;
}

const bahanChanges = computed(() =>
	materials.value
		.filter(changed)
		.map((material) => ({ item: material.item_code, value: Number(edits[material.item_code]) })),
);

// over-target is NOT blocked client-side: the server may still allow it via
// the site's allowance (NEEDS_ALLOWANCE only when that falls short, 3.4)
const valid = computed(() => (Number(form.good) || 0) > 0);

const confirmOpen = ref(false);
const submitting = ref(false);

function payload() {
	const packing = {
		good: Number(form.good) || 0,
		reject: Number(form.reject) || 0,
		trial: Number(form.trial) || 0,
		sisa: Number(form.sisa) || 0,
		good_pre: Number(form.good_pre) || 0,
		reject_pre: Number(form.reject_pre) || 0,
		trial_pre: Number(form.trial_pre) || 0,
		sisa_pre: Number(form.sisa_pre) || 0,
		loss_eksplisit: detailMode.value ? Number(form.loss) || 0 : 0,
		is_final: Boolean(form.isFinal),
		petugas_packing: form.petugas,
	};
	if (bahanChanges.value.length) {
		packing.bahan_dipakai = Object.fromEntries(
			bahanChanges.value.map((change) => [change.item, change.value]),
		);
	}
	return packing;
}

async function submit() {
	if (submitting.value) return;
	submitting.value = true;
	try {
		const result = await finishProduction(props.name, payload());
		confirmOpen.value = false;
		showToast(`Sesi packing tercatat (${result.stock_entry})`);
		if (result.needs_close_decision) {
			closeDecision.value = result;
		} else {
			await refreshDetail(props.name);
		}
	} catch (error) {
		// NEEDS_ALLOWANCE / gate messages are Indonesian; the central handler
		// toasts them and STATE_CHANGED auto-reloads the detail
		reportError(error);
	} finally {
		submitting.value = false;
	}
}

const closeDecision = ref(null);
const closeReason = ref("");

async function closeWorkOrderNow() {
	if (submitting.value) return;
	submitting.value = true;
	try {
		await closeWorkOrder(props.name, closeReason.value.trim());
		closeDecision.value = null;
		closeReason.value = "";
		showToast("Work Order ditutup");
		await refreshDetail(props.name);
	} catch (error) {
		reportError(error);
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<!-- one card per material (9.2: Perlu / Diambil / Dipakai / Sisa di WIP) -->
	<div v-for="material in materials" :key="material.item_code" class="rounded-xl border border-gray-200 bg-white p-3">
		<p class="font-medium">{{ material.item_code }}</p>

		<div class="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
			<div>
				<p class="text-xs text-gray-500">Perlu (resep)</p>
				<p class="text-lg font-semibold">{{ formatQty(material.required_qty) }}</p>
			</div>
			<div>
				<p class="text-xs text-gray-500">Diambil</p>
				<p class="text-lg font-semibold">{{ formatQty(material.transferred_net) }}</p>
			</div>
			<div>
				<p class="text-xs text-gray-500">Dipakai</p>
				<p class="text-lg font-semibold">{{ formatQty(material.dipakai) }}</p>
			</div>
			<div>
				<p class="text-xs text-gray-500">Sisa di WIP</p>
				<p class="text-lg font-semibold">{{ formatQty(material.sisa_wip) }}</p>
			</div>
		</div>

		<!-- indicative stock + batches (7.2); expired flagged red, excluded from tersedia -->
		<div v-if="material.stok_gudang_asal?.warehouse" class="mt-2 space-y-1 text-xs text-gray-500">
			<p>
				Stok {{ material.stok_gudang_asal.warehouse }} (indikatif):
				{{ formatQty(material.stok_gudang_asal.bin_qty) }}
				<template v-if="material.stok_gudang_asal.tersedia != null">
					- tersedia {{ formatQty(material.stok_gudang_asal.tersedia) }}
				</template>
			</p>
			<ul v-if="visibleBatches(material).length" class="space-y-0.5">
				<li
					v-for="batch in visibleBatches(material)"
					:key="batch.batch_no"
					class="flex items-center gap-1"
					:class="batch.expired ? 'font-medium text-red-600' : ''"
				>
					<template v-if="batch.expired"><AlertTriangle class="h-3.5 w-3.5 shrink-0" /></template>
					<span>{{ batch.batch_no }} - {{ formatQty(batch.qty) }}</span>
					<span v-if="batch.expired">kedaluwarsa ({{ formatDate(batch.expiry_date) }})</span>
				</li>
			</ul>
		</div>
	</div>

	<!-- big action (9.2): hidden on skip_transfer; green note once everything is picked -->
	<div class="md:col-span-2">
		<p
			v-if="allPicked"
			class="flex items-center justify-center gap-2 rounded-xl bg-green-50 p-4 font-medium text-green-700"
		>
			<CheckCircle2 class="h-6 w-6" />
			Semua bahan sudah diambil
		</p>
		<p v-else-if="skipTransfer" class="rounded-xl bg-gray-100 p-4 text-center text-sm text-gray-600">
			Work Order ini tidak memerlukan pengambilan bahan.
		</p>
		<button
			v-else
			class="flex min-h-[48px] w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 font-semibold text-white active:bg-blue-700"
			@click="openDialog"
		>
			<Package class="h-5 w-5" />
			Ambil Bahan
		</button>
	</div>

	<!-- AMBIL BAHAN dialog: qty aktual per material, default = sisa perlu;
	     only items the operator CHANGED are sent as items_aktual (7.4) -->
	<div v-if="dialogOpen" class="fixed inset-0 z-30 flex items-end justify-center bg-black/40 sm:items-center">
		<div
			class="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-4 sm:rounded-2xl"
			role="dialog"
			aria-modal="true"
			aria-label="Ambil Bahan"
		>
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-semibold">Ambil Bahan</h2>
				<button
					class="flex h-11 w-11 items-center justify-center rounded-lg active:bg-gray-100"
					aria-label="Tutup"
					@click="dialogOpen = false"
				>
					<X class="h-5 w-5" />
				</button>
			</div>
			<p class="mt-1 text-sm text-gray-500">Jumlah yang benar-benar diambil dari gudang.</p>

			<div v-for="material in pendingMaterials" :key="material.item_code" class="mt-3">
				<label class="text-sm font-medium" :for="`ambil-${material.item_code}`">
					{{ material.item_code }} - sisa perlu {{ formatQty(material.sisa_perlu) }}
				</label>
				<input
					:id="`ambil-${material.item_code}`"
					v-model.number="edits[material.item_code]"
					class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
					type="number"
					inputmode="decimal"
					min="0"
					step="any"
				/>
			</div>

			<button
				class="mt-4 min-h-[48px] w-full rounded-xl bg-blue-600 font-semibold text-white active:bg-blue-700 disabled:bg-gray-300"
				:disabled="!hasChanges"
				@click="submit"
			>
				Ambil Bahan
			</button>
		</div>
	</div>
</template>

<script setup>
import { AlertTriangle, CheckCircle2, Package, X } from "lucide-vue-next";
import { computed, reactive, ref } from "vue";

import { transferMaterial } from "@/api/workOrders";
import { reportError } from "@/api/client";
import { showToast } from "@/composables/toast";
import { formatDate, formatQty } from "@/lib/format";
import { refreshDetail } from "@/stores/workOrders";

const props = defineProps({
	name: { type: String, default: "" },
	detail: { type: Object, default: null },
});

const materials = computed(() => props.detail?.materials || []);
const skipTransfer = computed(() => Boolean(props.detail?.work_order?.skip_transfer));
const allPicked = computed(() => materials.value.length > 0 && materials.value.every((m) => m.sisa_perlu <= 0));

const pendingMaterials = computed(() => materials.value.filter((m) => m.sisa_perlu > 0));

// expired batches stay listed (flagged) but are excluded from "tersedia" -
// showing zero-qty live batches again is noise, so they are dropped here.
function visibleBatches(material) {
	return (material.stok_gudang_asal?.batches || []).filter((b) => b.qty > 0 || b.expired);
}

const dialogOpen = ref(false);
const edits = reactive({});

function openDialog() {
	Object.keys(edits).forEach((key) => delete edits[key]);
	for (const material of pendingMaterials.value) {
		edits[material.item_code] = material.sisa_perlu;
	}
	dialogOpen.value = true;
}

// items_aktual semantics: only items whose qty the operator actually changed
// (default per material = sisa perlu is what the server picks otherwise).
// A CLEARED input is not a zero intent - the item is omitted entirely.
const changed = (material) => {
	const raw = edits[material.item_code];
	return raw !== "" && raw != null && Number(raw) !== material.sisa_perlu;
};

const hasChanges = computed(() => pendingMaterials.value.some(changed));

const submitting = ref(false);

async function submit() {
	if (submitting.value) return;
	submitting.value = true;
	try {
		const itemsAktual = {};
		for (const material of pendingMaterials.value) {
			if (changed(material)) {
				itemsAktual[material.item_code] = Number(edits[material.item_code]);
			}
		}
		const result = await transferMaterial(props.name, itemsAktual);
		dialogOpen.value = false;
		showToast(`Bahan berhasil diambil (${result.stock_entry})`);
		await refreshDetail(props.name);
	} catch (error) {
		// dialog stays open so the operator can adjust; server message is
		// already Indonesian (6.8 gate / NEEDS_ALLOWANCE / stock)
		reportError(error);
	} finally {
		submitting.value = false;
	}
}
</script>

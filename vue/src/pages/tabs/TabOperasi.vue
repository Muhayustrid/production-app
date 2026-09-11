<template>
	<p v-if="!hasOperations" class="rounded-xl border border-dashed border-gray-300 bg-white p-6 text-center text-gray-500 md:col-span-2">
		Work Order ini tidak memiliki operasi.
	</p>
	<!-- operations in sequence (server-sorted): progress = completed + loss / qty -->
	<div
		v-for="(operation, index) in operations"
		:key="index"
		class="rounded-xl border bg-white p-3"
		:class="isDone(operation) ? 'border-gray-200' : isActive(index) ? 'border-blue-300' : 'border-gray-200 opacity-70'"
	>
		<div class="flex items-start justify-between gap-2">
			<div class="min-w-0">
				<p class="truncate font-medium">{{ operation.operation }}</p>
				<p class="text-sm text-gray-500">
					Selesai {{ formatQty(progress(operation)) }} dari {{ formatQty(operation.qty) }}
				</p>
			</div>
			<span v-if="isDone(operation)" class="flex items-center gap-1 text-sm font-medium text-green-600">
				<CheckCircle2 class="h-5 w-5" />
				Selesai
			</span>
			<span v-else-if="!isActive(index)" class="flex items-center gap-1 text-sm text-gray-400">
				<Lock class="h-4 w-4" />
			</span>
		</div>

		<div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-100">
			<div
				class="h-full rounded-full"
				:class="isDone(operation) ? 'bg-green-600' : 'bg-blue-600'"
				:style="{ width: progressWidth(operation) }"
			></div>
		</div>

		<!-- kartu tambahan badge (7.5): sisa > 0 without an open card -->
		<p v-if="operation.perlu_kartu_tambahan" class="mt-2 flex items-center gap-1 text-xs text-amber-600">
			<Info class="h-3.5 w-3.5 shrink-0" />
			Perlu kartu operasi tambahan - hubungi Supervisor.
		</p>

		<!-- next operation only (9.2): MULAI optional + SELESAIKAN OPERASI -->
		<template v-if="isActive(index) && operation.open_job_card">
			<div class="mt-3 flex flex-col gap-2 sm:flex-row">
				<button
					v-if="!startedAt[operation.open_job_card]"
					class="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg border border-blue-600 px-4 font-medium text-blue-700 active:bg-blue-50"
					@click="mulai(operation)"
				>
					<Play class="h-5 w-5" />
					Mulai
				</button>
				<button
					class="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 font-medium text-white active:bg-blue-700"
					@click="openDialog(operation)"
				>
					<CheckCircle2 class="h-5 w-5" />
					Selesaikan Operasi
				</button>
			</div>
			<p class="mt-1 text-xs text-gray-500">
				<template v-if="startedAt[operation.open_job_card]">
					Dimulai {{ startTime(operation.open_job_card) }} - durasi dicatat dari waktu ini.
				</template>
				<template v-else> Mulai opsional - durasi dicatat hanya bila Mulai ditekan. </template>
			</p>
		</template>
	</div>

	<!-- SELESAIKAN OPERASI dialog: qty aktual wajib, loss aktual optional
	     (default 0), final toggle with honest copy (7.5) -->
	<div v-if="dialogOperation" class="fixed inset-0 z-30 flex items-end justify-center bg-black/40 sm:items-center">
		<div
			class="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-4 sm:rounded-2xl"
			role="dialog"
			aria-modal="true"
			aria-label="Selesaikan Operasi"
		>
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-semibold">Selesaikan Operasi</h2>
				<button
					class="flex h-11 w-11 items-center justify-center rounded-lg active:bg-gray-100"
					aria-label="Tutup"
					@click="dialogOperation = null"
				>
					<X class="h-5 w-5" />
				</button>
			</div>
			<p class="mt-1 text-sm text-gray-500">{{ dialogOperation.operation }} - kartu {{ dialogOperation.open_job_card }}</p>

			<label class="mt-3 block text-sm font-medium" for="op-qty">Jumlah Selesai</label>
			<input
				id="op-qty"
				v-model.number="form.qty"
				class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
				type="number"
				inputmode="decimal"
				min="0"
				step="any"
			/>

			<label class="mt-3 block text-sm font-medium" for="op-loss">Loss Operasi (opsional)</label>
			<input
				id="op-loss"
				v-model.number="form.loss"
				class="mt-1 min-h-[44px] w-full rounded-lg border border-gray-300 px-3 text-base focus:border-blue-500 focus:outline-none"
				type="number"
				inputmode="decimal"
				min="0"
				step="any"
			/>

			<label class="mt-3 flex min-h-[44px] items-center gap-2 text-sm font-medium">
				<input v-model="form.isFinal" type="checkbox" class="h-5 w-5" />
				Selesai final
			</label>
			<p class="text-xs text-gray-500">Final tidak menaikkan angka; sisa tercatat pending.</p>
			<p v-if="over" class="mt-1 text-xs text-red-600">
				Jumlah selesai + loss melebihi jumlah kartu operasi ({{ formatQty(dialogOperation.sisa) }}).
			</p>

			<button
				class="mt-4 min-h-[48px] w-full rounded-xl bg-blue-600 font-semibold text-white active:bg-blue-700 disabled:bg-gray-300"
				:disabled="!valid"
				@click="submit"
			>
				Selesaikan Operasi
			</button>
		</div>
	</div>
</template>

<script setup>
import { CheckCircle2, Info, Lock, Play, X } from "lucide-vue-next";
import { computed, reactive, ref } from "vue";

import { completeOperation } from "@/api/workOrders";
import { reportError } from "@/api/client";
import { formatNaiveLocal, operationStarts as startedAt } from "@/lib/operationStarts";
import { showToast } from "@/composables/toast";
import { formatQty } from "@/lib/format";
import { refreshDetail } from "@/stores/workOrders";

const props = defineProps({
	name: { type: String, default: "" },
	detail: { type: Object, default: null },
});

const operations = computed(() => props.detail?.operations || []);

// a WO made from a BOM without operations has no operation rows at all
const hasOperations = computed(() => operations.value.length > 0);

function isDone(operation) {
	return operation.sisa <= 0;
}

// only the NEXT operation (first with sisa > 0) is active (9.2)
const nextIndex = computed(() => operations.value.findIndex((op) => op.sisa > 0));
function isActive(index) {
	return index === nextIndex.value;
}

function progress(operation) {
	return Number(operation.completed_qty) + Number(operation.process_loss_qty || 0);
}

function progressWidth(operation) {
	const qty = Number(operation.qty) || 0;
	if (qty <= 0) return "0%";
	return `${Math.min(100, Math.round((progress(operation) / qty) * 100))}%`;
}

function mulai(operation) {
	startedAt[operation.open_job_card] = new Date();
}

function startTime(jobCard) {
	return new Date(startedAt[jobCard]).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

const dialogOperation = ref(null);
const form = reactive({ qty: 0, loss: 0, isFinal: false });

function openDialog(operation) {
	form.qty = operation.sisa;
	form.loss = 0;
	form.isFinal = false;
	dialogOperation.value = operation;
}

const over = computed(
	() =>
		dialogOperation.value != null &&
		Number(form.qty || 0) + Number(form.loss || 0) > Number(dialogOperation.value.sisa),
);
const valid = computed(() => Number(form.qty) > 0 && !over.value);

async function submit() {
	const operation = dialogOperation.value;
	if (!operation || !valid.value) return;
	try {
		const result = await completeOperation(
			props.name,
			operation.open_job_card,
			Number(form.qty),
			form.isFinal,
			startedAt[operation.open_job_card] ? formatNaiveLocal(startedAt[operation.open_job_card]) : null,
			Number(form.loss || 0),
		);
		dialogOperation.value = null;
		showToast(`Operasi ${result.operation} tercatat selesai (${formatQty(result.operation_completed)})`);
		if (result.kartu_tambahan) {
			showToast(`Kartu operasi tambahan dibuat: ${result.kartu_tambahan}`);
		}
		if (result.needs_close_decision) {
			showToast(`Sisa target ${formatQty(result.remaining_target)} masih pending.`, "warning");
		}
		await refreshDetail(props.name);
	} catch (error) {
		// dialog stays open; server message (sequence / docstatus) is Indonesian
		reportError(error);
	}
}
</script>

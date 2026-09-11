<template>
	<div class="mx-auto flex min-h-screen w-full max-w-3xl flex-col bg-gray-50">
		<header class="sticky top-0 z-10 border-b border-gray-200 bg-white px-4 py-3">
			<h1 class="text-xl font-semibold">Work Order</h1>
			<div class="relative mt-2">
				<Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
				<input
					v-model="search"
					type="search"
					placeholder="Cari item atau no. Work Order..."
					aria-label="Cari Work Order"
					class="min-h-[44px] w-full rounded-lg border border-gray-300 bg-gray-50 pl-9 pr-3 text-base focus:border-blue-500 focus:outline-none"
				/>
			</div>
		</header>

		<main class="flex-1 space-y-3 p-4">
			<!-- loading skeleton (9.3) -->
			<template v-if="store.listLoading && !store.list.length">
				<div v-for="index in 4" :key="index" class="animate-pulse rounded-xl border border-gray-200 bg-white p-4">
					<div class="flex gap-3">
						<div class="h-10 w-10 rounded-lg bg-gray-200"></div>
						<div class="flex-1 space-y-2">
							<div class="h-4 w-2/3 rounded bg-gray-200"></div>
							<div class="h-3 w-1/3 rounded bg-gray-200"></div>
						</div>
					</div>
					<div class="mt-3 h-2 w-full rounded bg-gray-200"></div>
				</div>
			</template>

			<!-- error + manual retry (9.3) -->
			<div v-else-if="store.listError && !store.list.length" class="flex flex-col items-center gap-3 py-10 text-center">
				<AlertTriangle class="h-10 w-10 text-amber-500" />
				<p class="text-gray-700">{{ store.listError }}</p>
				<button
					class="min-h-[44px] rounded-lg bg-blue-600 px-6 font-medium text-white active:bg-blue-700"
					@click="loadList(search)"
				>
					Coba Lagi
				</button>
			</div>

			<!-- empty state -->
			<div v-else-if="!store.list.length" class="flex flex-col items-center gap-2 py-10 text-center text-gray-500">
				<PackageOpen class="h-10 w-10" />
				<p>Tidak ada Work Order aktif.</p>
			</div>

			<!-- work order cards (9.1) -->
			<router-link
				v-for="wo in store.list"
				:key="wo.name"
				:to="`/work-orders/${encodeURIComponent(wo.name)}`"
				class="block rounded-xl border border-gray-200 bg-white p-4 active:bg-gray-100"
			>
				<div class="flex items-start gap-3">
					<div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50">
						<Package class="h-5 w-5 text-blue-600" />
					</div>
					<div class="min-w-0 flex-1">
						<p class="truncate font-semibold">{{ wo.item_name || wo.item }}</p>
						<p class="truncate text-sm text-gray-500">{{ wo.item }}</p>
						<!-- the WO number is the operator's handle: own line, wraps
						     instead of truncating - it must always be readable -->
						<p class="break-all text-xs font-medium text-gray-600">{{ wo.name }}</p>
					</div>
					<span class="flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium" :class="badgeClass(wo)">
						<component :is="badgeIcon(wo)" class="h-3.5 w-3.5" />
						{{ chipLabel(wo) }}
					</span>
				</div>

				<div class="mt-3">
					<div class="flex items-baseline justify-between">
						<p class="text-sm text-gray-600">
							Hasil Baik <span class="text-lg font-semibold text-gray-900">{{ formatQty(wo.produced) }}</span>
							dari {{ formatQty(wo.qty) }}
						</p>
						<p class="text-sm text-gray-600">
							Belum diproduksi: <span class="font-semibold">{{ formatQty(wo.belum_diproduksi) }}</span>
						</p>
					</div>
					<div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-gray-100">
						<div
							class="h-full rounded-full bg-blue-600"
							:style="{ width: progressWidth(wo) }"
						></div>
					</div>
				</div>

				<!-- skip the row entirely when nothing is set (empty Target, no block) -->
				<div v-if="wo.expected_delivery_date || blockedReason(wo)" class="mt-2 flex items-center justify-between text-sm">
					<span v-if="wo.expected_delivery_date" class="text-gray-500">Target: {{ formatDate(wo.expected_delivery_date) }}</span>
					<span v-if="blockedReason(wo)" class="flex items-center gap-1 text-amber-600">
						<AlertTriangle class="h-3.5 w-3.5" />
						{{ blockedReason(wo) }}
					</span>
				</div>
			</router-link>
		</main>
	</div>
</template>

<script setup>
import { AlertTriangle, CheckCircle2, CircleDot, Package, PackageOpen, Search } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";

import { workOrderStore as store, loadList } from "@/stores/workOrders";
import { formatDate, formatQty } from "@/lib/format";
import { woStatusId } from "@/lib/status";

const search = ref(store.search);
let debounce = null;

// server-side search (7.1), debounced while typing
watch(search, (value) => {
	clearTimeout(debounce);
	debounce = setTimeout(() => loadList(value), 300);
});

onMounted(() => loadList(search.value));

function progressWidth(wo) {
	const target = Number(wo.qty) || 0;
	const produced = Number(wo.produced) || 0;
	if (target <= 0) return "0%";
	return `${Math.min(100, Math.round((produced / target) * 100))}%`;
}

function blockedReason(wo) {
	if (wo.status === "Stopped") return "Work Order dihentikan";
	return wo.blocked_reasons?.[0] || "";
}

// The card chip is the server's Indonesian step badge ("Menunggu Bahan",
// "Operasi k/N", ...). A Stopped WO's step badge would still read "Menunggu
// Bahan" - the mapped status tells the truth there (amber styling already
// applies via isBlocked).
function chipLabel(wo) {
	return wo.status === "Stopped" ? woStatusId(wo.status) : wo.badge;
}

function isBlocked(wo) {
	return wo.status === "Stopped" || Boolean(wo.blocked_reasons?.length);
}

function badgeIcon(wo) {
	if (isBlocked(wo)) return AlertTriangle;
	if (wo.badge === "Selesai") return CheckCircle2;
	return CircleDot;
}

function badgeClass(wo) {
	if (isBlocked(wo)) return "bg-amber-100 text-amber-700";
	if (wo.badge === "Selesai") return "bg-green-100 text-green-700";
	return "bg-blue-100 text-blue-700";
}
</script>

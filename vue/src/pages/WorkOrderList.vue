<template>
	<div class="mx-auto flex min-h-screen w-full max-w-3xl flex-col bg-gray-50">
		<header class="sticky top-0 z-10 border-b border-gray-200 bg-white px-4 py-3">
			<div class="flex items-baseline justify-between">
				<h1 class="text-xl font-semibold">Work Order</h1>
				<span class="text-sm text-gray-500">{{ store.list.length }} Work Order</span>
			</div>

			<!-- filter bar (task 24): collapsible on mobile, native inputs -->
			<div class="mt-2 flex items-center gap-2">
				<button
					class="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg border px-3 text-base"
					:class="
						activeFilters
							? 'border-blue-500 bg-blue-50 font-medium text-blue-700'
							: 'border-gray-300 bg-gray-50 text-gray-700'
					"
					:aria-expanded="filtersOpen"
					@click="filtersOpen = !filtersOpen"
				>
					<SlidersHorizontal class="h-4 w-4" />
					{{ activeFilters ? "Filter aktif" : "Filter" }}
					<span v-if="activeFilters" class="rounded-full bg-blue-600 px-2 py-0.5 text-xs font-medium text-white">
						{{ activeFilters }}
					</span>
				</button>
				<button
					v-if="activeFilters"
					class="min-h-[44px] rounded-lg px-4 text-base font-medium text-blue-700 active:bg-blue-50"
					@click="resetFilters"
				>
					Reset
				</button>
			</div>
			<div v-if="filtersOpen" class="mt-2 space-y-2">
				<div class="grid grid-cols-2 gap-2">
					<label class="block">
						<span class="text-xs text-gray-500">Dari</span>
						<input
							v-model="store.filters.dateFrom"
							type="date"
							aria-label="Target dari tanggal"
							class="min-h-[44px] w-full rounded-lg border border-gray-300 bg-gray-50 px-3 text-base focus:border-blue-500 focus:outline-none"
						/>
					</label>
					<label class="block">
						<span class="text-xs text-gray-500">Sampai</span>
						<input
							v-model="store.filters.dateTo"
							type="date"
							aria-label="Target sampai tanggal"
							class="min-h-[44px] w-full rounded-lg border border-gray-300 bg-gray-50 px-3 text-base focus:border-blue-500 focus:outline-none"
						/>
					</label>
				</div>
				<div class="relative">
					<Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
					<input
						v-model="store.filters.item"
						type="search"
						placeholder="Cari nama item / kode..."
						aria-label="Cari nama item atau kode item"
						class="min-h-[44px] w-full rounded-lg border border-gray-300 bg-gray-50 pl-9 pr-3 text-base focus:border-blue-500 focus:outline-none"
					/>
				</div>
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
					@click="loadList()"
				>
					Coba Lagi
				</button>
			</div>

			<!-- empty BECAUSE of filters (task 24): offer the reset -->
			<div v-else-if="!store.list.length && activeFilters" class="flex flex-col items-center gap-3 py-10 text-center text-gray-500">
				<PackageOpen class="h-10 w-10" />
				<p>Tidak ada hasil untuk filter ini.</p>
				<button
					class="min-h-[44px] rounded-lg border border-gray-300 bg-white px-6 font-medium text-blue-700 active:bg-blue-50"
					@click="resetFilters"
				>
					Reset
				</button>
			</div>

			<!-- empty without filters (task 24): explain the flow -->
			<div v-else-if="!store.list.length" class="flex flex-col items-center gap-2 py-10 text-center text-gray-500">
				<PackageOpen class="h-10 w-10" />
				<p>Belum ada Work Order aktif.</p>
				<p class="text-sm">Alur: Ambil Bahan → Operasi (bila ada) → Catat Produksi → Packing → Selesai.</p>
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
						<!-- the item NAME is the primary identity (task 24); the code
						     shows only when it differs from the name -->
						<p class="break-all text-base font-semibold">{{ wo.item_name || wo.item }}</p>
						<p
							v-if="wo.item && wo.item !== (wo.item_name || wo.item)"
							class="break-all text-sm text-gray-500"
						>
							{{ wo.item }}
						</p>
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

				<!-- skip the row entirely when nothing is set (empty Target, no block);
				     the target date is prominent and turns red once its day passed -->
				<div v-if="wo.expected_delivery_date || blockedReason(wo)" class="mt-2 flex items-center justify-between gap-2 text-sm">
					<span
						v-if="wo.expected_delivery_date"
						class="flex items-center gap-1 font-medium"
						:class="isOverdue(wo) ? 'text-red-600' : 'text-gray-700'"
					>
						<Calendar class="h-4 w-4" />
						Target: {{ formatDate(wo.expected_delivery_date) }}
					</span>
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
import {
	AlertTriangle,
	Calendar,
	CheckCircle2,
	CircleDot,
	Package,
	PackageOpen,
	Search,
	SlidersHorizontal,
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import { workOrderStore as store, loadList } from "@/stores/workOrders";
import { formatDate, formatQty } from "@/lib/format";
import { woStatusId } from "@/lib/status";

const filtersOpen = ref(false);

let debounce = null;

// server-side filters (task 24): debounced 400ms while typing / picking dates
watch(
	() => [store.filters.dateFrom, store.filters.dateTo, store.filters.item],
	() => {
		clearTimeout(debounce);
		debounce = setTimeout(() => loadList(), 400);
	},
);

const activeFilters = computed(
	() =>
		[store.filters.dateFrom, store.filters.dateTo, store.filters.item].filter(
			(value) => value && String(value).trim(),
		).length,
);

function resetFilters() {
	clearTimeout(debounce);
	store.filters.dateFrom = "";
	store.filters.dateTo = "";
	store.filters.item = "";
	loadList();
}

onMounted(() => loadList());

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
// Bahan" - the mapped status tells the truth there (gray styling already
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

// Consistent step colors (task 24): blue = waiting for materials, amber =
// operations, purple = packing, green = done, gray = blocked/stopped.
function badgeClass(wo) {
	if (isBlocked(wo)) return "bg-gray-100 text-gray-600";
	if (wo.badge === "Selesai") return "bg-green-100 text-green-700";
	if (wo.badge === "Menunggu Packing") return "bg-purple-100 text-purple-700";
	if (wo.badge.startsWith("Operasi")) return "bg-amber-100 text-amber-700";
	return "bg-blue-100 text-blue-700"; // Menunggu Bahan
}

// Overdue once the target DAY has fully passed (end-of-day, local time).
function isOverdue(wo) {
	if (!wo.expected_delivery_date) return false;
	return new Date(`${wo.expected_delivery_date}T23:59:59`) < new Date();
}
</script>

<template>
	<div class="mx-auto flex min-h-screen w-full max-w-3xl flex-col bg-gray-50">
		<!-- header (9.2) -->
		<header class="sticky top-0 z-10 border-b border-gray-200 bg-white px-2 py-2">
			<div class="flex items-center gap-1">
				<router-link
					to="/"
					aria-label="Kembali ke daftar"
					class="flex h-11 w-11 items-center justify-center rounded-lg active:bg-gray-100"
				>
					<ArrowLeft class="h-6 w-6" />
				</router-link>
				<div class="min-w-0 flex-1">
					<p v-if="wo" class="truncate font-semibold">{{ wo.item_name || wo.item }}</p>
					<p v-else class="h-5 w-2/3 animate-pulse rounded bg-gray-200"></p>
					<!-- subtitle = item code (when it differs from the name) + WO no. -->
					<p class="truncate text-sm text-gray-500">
						<span v-if="wo && wo.item && wo.item !== (wo.item_name || wo.item)">{{ wo.item }} · </span>{{ name }}
					</p>
				</div>
				<span
					v-if="wo"
					class="rounded-full px-2.5 py-1 text-xs font-medium"
					:class="woStatusClass(wo.status)"
				>
					{{ woStatusId(wo.status) }}
				</span>
			</div>
		</header>

		<!-- loading skeleton -->
		<template v-if="entry.loading && !entry.data">
			<div class="space-y-3 p-4">
				<div class="h-24 animate-pulse rounded-xl bg-gray-200"></div>
				<div class="h-12 animate-pulse rounded-lg bg-gray-200"></div>
				<div class="h-40 animate-pulse rounded-xl bg-gray-200"></div>
			</div>
		</template>

		<!-- error + manual retry (9.3) -->
		<div v-else-if="entry.error && !entry.data" class="flex flex-1 flex-col items-center justify-center gap-3 p-4 text-center">
			<AlertTriangle class="h-10 w-10 text-amber-500" />
			<p class="text-gray-700">{{ entry.error }}</p>
			<button
				class="min-h-[44px] rounded-lg bg-blue-600 px-6 font-medium text-white active:bg-blue-700"
				@click="loadDetail(name, { force: true })"
			>
				Coba Lagi
			</button>
		</div>

		<template v-else-if="wo">
			<!-- summary: hasil baik / belum diproduksi + progress (9.2) -->
			<section class="p-4 pb-0">
				<div class="grid grid-cols-2 gap-3">
					<div class="rounded-xl border border-gray-200 bg-white p-3">
						<p class="text-sm text-gray-600">Hasil Baik</p>
						<p class="text-2xl font-semibold md:text-3xl">
							{{ formatQty(wo.produced) }}
							<span class="text-sm font-normal text-gray-500">dari {{ formatQty(wo.qty) }}</span>
						</p>
					</div>
					<div class="rounded-xl border border-gray-200 bg-white p-3">
						<p class="text-sm text-gray-600">Belum diproduksi</p>
						<p class="text-2xl font-semibold md:text-3xl">{{ formatQty(wo.belum_diproduksi) }}</p>
					</div>
				</div>
				<div class="mt-3 h-2 w-full overflow-hidden rounded-full bg-gray-200">
					<div class="h-full rounded-full bg-blue-600" :style="{ width: progressWidth }"></div>
				</div>
			</section>

			<!-- 5-tab bar (9.2): <768px = 5 columns -->
			<nav class="mt-4 border-y border-gray-200 bg-white" aria-label="Tab detail">
				<div class="grid grid-cols-5">
					<button
						v-for="(tab, index) in TABS"
						:key="tab.label"
						class="flex min-h-[52px] flex-col items-center justify-center gap-0.5 px-1 text-xs"
						:class="activeTab === index ? 'border-b-2 border-blue-600 font-semibold text-blue-700' : 'text-gray-600'"
						:aria-current="activeTab === index ? 'page' : undefined"
						@click="activeTab = index"
					>
						<component :is="tab.icon" class="h-5 w-5" />
						<span>{{ tab.label }}</span>
						<CircleDot v-if="index === actionTargetTab" class="h-3 w-3 text-blue-600" />
					</button>
				</div>
			</nav>

			<!-- tab content (9.3: 1 column <768px, 2 columns >=768px); all five
			     tabs are real (tasks 18-19) -->
			<main class="flex-1 p-4 pb-24">
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<TabBahan v-if="activeTab === 0" :name="name" :detail="entry.data" />
					<TabOperasi v-else-if="activeTab === 1" :name="name" :detail="entry.data" />
					<TabProduksi v-else-if="activeTab === 2" :name="name" :detail="entry.data" />
					<TabPacking v-else-if="activeTab === 3" :name="name" :detail="entry.data" />
					<TabRiwayat v-else :name="name" :detail="entry.data" />
				</div>
			</main>

			<!-- smart action bar (9.2) -->
			<footer class="fixed inset-x-0 bottom-0 z-20 border-t border-gray-200 bg-white p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
				<div class="mx-auto flex w-full max-w-3xl items-center gap-3">
					<template v-if="action.blocked">
						<AlertTriangle class="h-5 w-5 shrink-0 text-amber-500" />
						<p class="min-w-0 flex-1 text-sm text-amber-700">{{ action.blocked }}</p>
					</template>
					<template v-else-if="action.done">
						<CheckCircle2 class="h-6 w-6 shrink-0 text-green-600" />
						<p class="flex-1 font-medium text-green-700">Produksi Selesai</p>
					</template>
					<template v-else>
						<button
							class="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 font-medium text-white active:bg-blue-700"
							@click="activeTab = actionTargetTab"
						>
							{{ action.label }}
							<ArrowRight class="h-5 w-5" />
						</button>
					</template>
				</div>
			</footer>
		</template>
	</div>
</template>

<script setup>
import {
	ArrowLeft,
	ArrowRight,
	AlertTriangle,
	CheckCircle2,
	CircleDot,
	ClipboardList,
	History,
	Package,
	PackageCheck,
	Wrench,
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import { detailEntry, loadDetail } from "@/stores/workOrders";
import { formatQty } from "@/lib/format";
import { woStatusClass, woStatusId } from "@/lib/status";
import TabBahan from "@/pages/tabs/TabBahan.vue";
import TabOperasi from "@/pages/tabs/TabOperasi.vue";
import TabPacking from "@/pages/tabs/TabPacking.vue";
import TabProduksi from "@/pages/tabs/TabProduksi.vue";
import TabRiwayat from "@/pages/tabs/TabRiwayat.vue";

const props = defineProps({
	name: { type: String, default: "" },
});

const TABS = [
	{ label: "Bahan", icon: Package },
	{ label: "Operasi", icon: Wrench },
	{ label: "Produksi", icon: ClipboardList },
	{ label: "Packing", icon: PackageCheck },
	{ label: "Riwayat", icon: History },
];

const activeTab = ref(0);
const entry = ref({ loading: false, error: null, data: null });

const wo = computed(() => entry.value.data?.work_order);

// next_action (7.2) -> smart bar button "Lanjut: X" (9.2)
const ACTIONS = {
	transfer_material: { tab: 0, label: "Lanjut: Ambil Bahan" },
	complete_operation: { tab: 1, label: "Lanjut: Selesaikan Operasi" },
	finish_production: { tab: 3, label: "Lanjut: Packing" },
};

const action = computed(() => {
	const nextAction = entry.value.data?.next_action || "";
	if (nextAction.startsWith("blocked:")) {
		return { blocked: nextAction.slice("blocked:".length) };
	}
	if (nextAction === "done") {
		return { done: true };
	}
	const mapped = ACTIONS[nextAction.split(":")[0]];
	return mapped || {};
});

const actionTargetTab = computed(() => action.value.tab ?? -1);

const progressWidth = computed(() => {
	const target = Number(wo.value?.qty) || 0;
	const produced = Number(wo.value?.produced) || 0;
	if (target <= 0) return "0%";
	return `${Math.min(100, Math.round((produced / target) * 100))}%`;
});

onMounted(() => {
	entry.value = detailEntry(props.name);
	loadDetail(props.name);
});

// navigating to another WO reuses this component: reload + reset the tab
watch(
	() => props.name,
	(newName, oldName) => {
		if (newName !== oldName) {
			activeTab.value = 0;
			entry.value = detailEntry(newName);
			loadDetail(newName);
		}
	},
);
</script>

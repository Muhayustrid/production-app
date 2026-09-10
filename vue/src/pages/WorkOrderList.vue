<template>
	<div class="flex min-h-screen flex-col items-center justify-center gap-2 p-8">
		<Factory class="h-10 w-10 text-gray-500" />
		<h1 class="text-2xl font-semibold">Production App</h1>
		<p v-if="user" class="text-gray-600">Logged in as {{ user }}</p>
		<p v-else class="text-gray-400">Loading session…</p>
		<p class="text-sm text-gray-400">Phase 2 placeholder — work order list arrives in Tahap 4.</p>
	</div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { Factory } from "lucide-vue-next";

import { call } from "@/api";

const user = ref("");

onMounted(async () => {
	try {
		user.value = await call("frappe.auth.get_logged_user");
	} catch {
		// already surfaced via the api client error handler
	}
});
</script>

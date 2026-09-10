<template>
	<div class="flex min-h-screen flex-col items-center justify-center gap-2 p-8">
		<h1 class="text-xl font-semibold">Work Order detail</h1>
		<p class="text-gray-500">{{ name }}</p>
		<p class="text-sm text-gray-400">Phase 2 placeholder — detail screen arrives in Tahap 4.</p>
	</div>
</template>

<script setup>
defineProps({
	name: { type: String, default: "" },
});
</script>

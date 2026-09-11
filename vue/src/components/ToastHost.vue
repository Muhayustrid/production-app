<template>
	<div class="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4">
		<div
			v-for="toast in toasts"
			:key="toast.id"
			role="status"
			aria-live="polite"
			class="pointer-events-auto flex max-w-md items-center gap-2 rounded-lg px-4 py-3 text-sm text-white shadow-lg"
			:class="{
				'bg-red-600': toast.kind === 'error',
				'bg-amber-600': toast.kind === 'warning',
				'bg-gray-800': toast.kind === 'info',
			}"
		>
			<AlertTriangle v-if="toast.kind !== 'info'" class="h-4 w-4 shrink-0" />
			<span>{{ toast.message }}</span>
		</div>
	</div>
</template>

<script setup>
import { AlertTriangle } from "lucide-vue-next";

import { toasts } from "@/composables/toast";
</script>

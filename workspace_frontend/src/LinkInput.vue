<script setup>
import { ref, watch } from 'vue'
import { call } from './store.js'
const props = defineProps({ modelValue: String, displayLabel: String, doctype: { type: String, default: 'User' }, disabled: Boolean, id: String })
const emit = defineEmits(['update:modelValue'])
const query = ref('')
const results = ref([])
const error = ref('')
let sequence = 0
watch(() => [props.modelValue, props.displayLabel], () => { if (props.modelValue) query.value = props.displayLabel || props.modelValue }, { immediate: true })
async function search() {
  const current = ++sequence
  error.value = ''
  try {
    const filters = props.doctype === 'User'
      ? { enabled: 1 }
      : props.doctype === 'Employee'
        ? { status: 'Active' }
        : props.doctype === 'Warehouse'
          ? { disabled: 0 }
          : undefined
    const rows = await call('frappe.desk.search.search_link', {
      doctype: props.doctype, txt: query.value, page_length: 10,
      reference_doctype: props.doctype === 'User' ? 'Work Order' : 'Job Card',
      filters
    })
    if (current === sequence) results.value = rows
  } catch (e) { if (current === sequence) error.value = e.message }
}
function edit(event) {
  query.value = event.target.value
  emit('update:modelValue', '')
  search()
}
function select(row) {
  sequence++
  emit('update:modelValue', row.value)
  query.value = row.label || row.value
  results.value = []
}
function description(row) {
  return new DOMParser().parseFromString(row.description || '', 'text/html').body.textContent
}
</script>
<template>
  <div>
    <input :id="id" :value="query" @input="edit" @focus="search" class="input" :disabled="disabled"
      autocomplete="off" placeholder="Cari lalu pilih dari daftar" />
    <div v-if="!disabled && results.length" class="link-results" aria-label="Hasil pencarian">
      <button v-for="row in results" :key="row.value" type="button" class="btn" @click="select(row)">
        {{ row.label || row.value }} <small>{{ description(row) }}</small>
      </button>
    </div>
    <div v-if="error" class="err" role="alert">{{ error }}</div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { call } from './store.js'
const props = defineProps({ modelValue: String, displayLabel: String, doctype: { type: String, default: 'User' }, disabled: Boolean, id: String })
const emit = defineEmits(['update:modelValue'])
const query = ref('')
const results = ref([])
const error = ref('')
const inputEl = ref(null)
const dropDir = ref('up')
const dropMaxHeight = ref(220)
let sequence = 0

// FU58: arah dropdown diukur sekali saat daftar dibuka — default ke ATAS
// (permintaan user), turun hanya bila ruang atas kurang. Ruang dibatasi
// viewport DAN clipping-ancestor terdekat (rantai parentElement dengan
// computed overflow auto|scroll|hidden — mis. .tbl-wrap.fo-grid-wrap
// overflow-x:auto pada ≤820px ), lalu max-height adaptif
// min(220px, ruang sisi terpilih − 8px) agar daftar tidak terpotong.
function measureDrop() {
  const el = inputEl.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  let top = 0
  let bottom = window.innerHeight
  let node = el.parentElement
  while (node && node !== document.documentElement) {
    const style = getComputedStyle(node)
    if (/(auto|scroll|hidden)/.test(style.overflow + style.overflowX + style.overflowY)) {
      const r = node.getBoundingClientRect()
      top = Math.max(top, r.top)
      bottom = Math.min(bottom, r.bottom)
    }
    node = node.parentElement
  }
  const up = rect.top - top
  const down = bottom - rect.bottom
  const NEED = 240 // 220 max-height + gap 4 + buffer
  dropDir.value = up >= NEED || down < up ? 'up' : 'down'
  const space = dropDir.value === 'up' ? up : down
  // Rumus persis §7: min(220px, ruang sisi terpilih − 8px) — daftar tidak
  // pernah melebihi ruang efektif sehingga tidak terpotong clipping-ancestor.
  // Math.max(0, …) bukan lantai tampilan, hanya penjaga CSS valid
  // (max-height negatif diabaikan browser → daftar jadi tak terbatas).
  dropMaxHeight.value = Math.max(0, Math.min(220, Math.floor(space - 8)))
}
watch(() => results.value.length, n => { if (n) nextTick(measureDrop) })
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
  <div class="linkinput">
    <input ref="inputEl" :id="id" :value="query" @input="edit" @focus="search" class="input" :disabled="disabled"
      autocomplete="off" placeholder="Cari lalu pilih dari daftar" />
    <div v-if="!disabled && results.length" class="link-results" :class="dropDir"
      :style="{ maxHeight: dropMaxHeight + 'px' }" aria-label="Hasil pencarian">
      <button v-for="row in results" :key="row.value" type="button" class="btn" @click="select(row)">
        {{ row.label || row.value }} <small>{{ description(row) }}</small>
      </button>
    </div>
    <div v-if="error" class="err" role="alert">{{ error }}</div>
  </div>
</template>

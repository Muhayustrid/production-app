<script setup>
// FU100: baris filter ala ERPNext TANPA kolom operator — [Label][Nilai][×].
// Banyak nilai selalu digabung di SATU baris (IN di server), antar baris
// di-AND; tidak ada baris kembar untuk field yang sama. Perubahan dalam
// panel = DRAFT: "Terapkan" (commit) atau menutup panel — parent memicu
// commitIfChanged() saat panel ditutup. Komponen tidak tahu endpoint
// maupun company (kontrak rollout FU100): key = nama param halaman,
// options dari pemilik halaman.
import { computed, ref, watch } from 'vue'
import MultiSelect from 'primevue/multiselect'
import RangeField from './RangeField.vue'
import { Plus, X } from 'lucide-vue-next'
import { sameFilters } from './filter-rows.js'

const props = defineProps({
  fields: { type: Array, required: true },
  modelValue: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:modelValue'])

const draft = ref({ ...props.modelValue })
watch(() => props.modelValue, (v) => { draft.value = { ...v } })
// Commit saat panel ditutup TIDAK bisa lewat watcher prop `open` di sini:
// komponen hidup di dalam v-if panel, jadi ia ter-unmount bersamaan dengan
// perubahan prop (watcher tak pernah jalan). Parent yang memicu lewat
// commitIfChanged() (watcher parent berjalan pre-flush, sebelum unmount).
function commitIfChanged() {
  if (!sameFilters(draft.value, props.modelValue)) commit()
}
defineExpose({ commitIfChanged })

const activeRows = computed(() => props.fields.filter((f) => draft.value[f.key] !== undefined))
const addable = computed(() => props.fields.filter((f) => draft.value[f.key] === undefined))
const addOpen = ref(false)
// panel tanpa baris: menu tambah terbuka sendiri (affordance, pola ERPNext)
watch(activeRows, (rows) => { if (!rows.length) addOpen.value = true }, { immediate: true })

function addField(key) {
  const f = props.fields.find((x) => x.key === key)
  draft.value = { ...draft.value, [key]: f.type === 'range' ? { dari: '', sampai: '' } : [] }
  addOpen.value = false
}
function removeRow(key) {
  const d = { ...draft.value }
  delete d[key]
  draft.value = d
}
function commit() {
  emit('update:modelValue', { ...draft.value })
}
function clearAll() {
  draft.value = {}
  commit()
}
</script>

<template>
  <div class="frows">
    <div v-for="f in activeRows" :key="f.key" class="frow">
      <div class="frow-head">
        <span class="frow-label">{{ f.label }}</span>
        <button type="button" class="frow-x" :aria-label="'Hapus filter ' + f.label" @click="removeRow(f.key)">
          <X :size="13" :stroke-width="2.2" />
        </button>
      </div>
      <MultiSelect
        v-if="f.type === 'multi'"
        v-model="draft[f.key]"
        :options="f.options || []"
        optionLabel="label"
        optionValue="value"
        :filter="!!f.filter"
        :placeholder="f.placeholder || 'Pilih satu atau lebih'"
        selectedItemsLabel="{0} dipilih"
        :maxSelectedLabels="3"
        class="fmulti"
        :aria-label="f.label"
      />
      <RangeField
        v-else-if="f.type === 'range'"
        v-model:dari="draft[f.key].dari"
        v-model:sampai="draft[f.key].sampai"
        :placeholder="f.placeholder || ''"
      />
    </div>

    <div class="frows-addwrap">
      <div v-if="addOpen" class="frows-addmenu" role="menu">
        <button
          v-for="f in addable"
          :key="f.key"
          type="button"
          role="menuitem"
          class="frows-additem"
          @click="addField(f.key)"
        >
          {{ f.label }}
        </button>
        <p v-if="!addable.length" class="frows-none">Semua field sudah dipakai</p>
      </div>
      <button type="button" class="linkbtn frows-addbtn" :aria-expanded="addOpen ? 'true' : 'false'" @click="addOpen = !addOpen">
        <Plus :size="13" :stroke-width="2.4" />
        Tambah filter
      </button>
    </div>

    <div class="frows-foot">
      <button type="button" class="linkbtn filter-clear frows-clear" @click="clearAll">Hapus semua</button>
      <button type="button" class="btn btn-sm btn-primary" @click="commit">Terapkan</button>
    </div>
  </div>
</template>

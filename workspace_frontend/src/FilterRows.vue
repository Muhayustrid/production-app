<script setup>
// FU100: baris filter ala ERPNext TANPA kolom operator — [Label][Nilai][×].
// Banyak nilai selalu digabung di SATU baris (IN di server), antar baris
// di-AND; tidak ada baris kembar untuk field yang sama. Perubahan dalam
// panel = DRAFT: "Terapkan" (commit) atau menutup panel — parent memicu
// commitIfChanged() saat panel ditutup. Komponen tidak tahu endpoint
// maupun company (kontrak rollout FU100): key = nama param halaman,
// options dari pemilik halaman.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import MultiSelect from 'primevue/multiselect'
import RangeField from './RangeField.vue'
import { Plus, X } from 'lucide-vue-next'
import { cloneFilters, rangeFieldError, sameFilters } from './filter-rows.js'

const props = defineProps({
  fields: { type: Array, required: true },
  modelValue: { type: Object, default: () => ({}) },
  // FU102: panel yang di atas barisnya sudah punya kontrol utama (mis.
  // daftar preset Dashboard) mematikan menu tambah auto-terbuka — menu
  // mengapung NAIK dari tombolnya dan akan menutupi kontrol itu.
  // FU107: menu kini IN-FLOW, prop dipertahankan untuk kompatibilitas.
  autoAdd: { type: Boolean, default: true },
  // FU107: nilai baris "immediate" — kontrol TUNGGAL milik parent (mis.
  // Company: filter global FU95 yang tersimpan per-user di server dan
  // diterapkan SEGERA, bukan draft). Baris immediate selalu tampil dan
  // tidak ikut menu Tambah filter / commit draft.
  immediate: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:modelValue', 'immediate-change', 'clear'])

// FU102: draft = salinan lepas dari modelValue (klon satu level — lihat
// cloneFilters) supaya suntingan baris rentang tidak bocor ke applied.
const draft = ref(cloneFilters(props.modelValue))
watch(() => props.modelValue, (v) => { draft.value = cloneFilters(v) })
// Commit saat panel ditutup TIDAK bisa lewat watcher prop `open` di sini:
// komponen hidup di dalam v-if panel, jadi ia ter-unmount bersamaan dengan
// perubahan prop (watcher tak pernah jalan). Parent yang memicu lewat
// commitIfChanged() (watcher parent berjalan pre-flush, sebelum unmount).
function commitIfChanged() {
  if (blocked.value) return // nilai tak sah (mis. rentang separuh) jangan pernah masuk applied
  if (!sameFilters(draft.value, props.modelValue)) commit()
}
// FU102: pemilik halaman bisa membuka baris tertentu dari luar (mis. token
// preset 'Kustom' Dashboard yang pintunya kini baris Rentang)
function addRow(key) {
  if (props.fields.some((f) => f.key === key)) addField(key)
}
defineExpose({ addRow, commitIfChanged })

const activeRows = computed(() => props.fields.filter((f) => f.immediate || draft.value[f.key] !== undefined))
const addable = computed(() => props.fields.filter((f) => !f.immediate && draft.value[f.key] === undefined))
// FU107: baris DRAFT saja (immediate tidak dihitung) — dasar affordance menu
// tambah auto-terbuka; baris immediate selalu hadir sehingga tanpa pemisahan
// ini panel tak pernah "kosong" dan menu tak akan pernah menyala
const draftActive = computed(() => props.fields.filter((f) => !f.immediate && draft.value[f.key] !== undefined))
// FU108: panel tanpa field draft (mis. mini-panel kanban yang hanya berisi
// baris Company immediate) tidak butuh chrome tambah/terapkan/hapus —
// menyembunyikannya mencegah menu "Semua field sudah dipakai" nyangkut
const hasDraftFields = computed(() => props.fields.some((f) => !f.immediate))
// FU102: validasi nilai baris sebelum commit (mis. Rentang Dashboard wajib
// dari+sampai dan maksimal 366 hari — perilaku lama: tombol Terapkan mati).
// Draft tetap boleh tidak sah; yang ditahan hanya commit-nya.
const rowErrors = computed(() => {
  const out = {}
  for (const f of props.fields) {
    if (f.type !== 'range') continue
    const err = rangeFieldError(draft.value[f.key], f)
    if (err) out[f.key] = err
  }
  return out
})
const blocked = computed(() => Object.keys(rowErrors.value).length > 0)
const addOpen = ref(false)
// panel tanpa baris DRAFT: menu tambah terbuka sendiri (affordance, pola
// ERPNext); autoAdd false utk panel yang kontrol utamanya ada di atas baris (FU102)
watch(draftActive, (rows) => { if (!rows.length && props.autoAdd) addOpen.value = true }, { immediate: true })

function addField(key) {
  const f = props.fields.find((x) => x.key === key)
  if (!f || f.immediate || draft.value[key] !== undefined) return // jangan menimpa baris yang sudah ada
  const empty = f.type === 'range'
    ? { dari: f.resetDari || '', sampai: f.resetSampai || '' }
    : f.type === 'select' ? '' : []
  draft.value = { ...draft.value, [key]: empty }
  addOpen.value = false
}
function removeRow(key) {
  const f = props.fields.find((x) => x.key === key)
  if (f?.immediate) { emit('immediate-change', key, ''); return } // mis. Company → "Semua company"
  const d = { ...draft.value }
  delete d[key]
  draft.value = d
}
function commit() {
  if (blocked.value) return // nilai di luar batas tidak pernah dikomit
  addOpen.value = false
  // lepas dari draft juga saat keluar — parent memegang salinan sendiri
  emit('update:modelValue', cloneFilters(draft.value))
}
// FU108: "Hapus semua" = bersih TOTAL — draft dikomit kosong (baris hilang)
// DAN parent diminta melepas filter di luar draft (kotak cari, company
// immediate, preset/rentang/gudang halaman) lewat event clear; komponen
// tidak tahu field mana milik siapa, parent yang membersihkan sisanya.
function clearAll() {
  draft.value = {}
  commit()
  emit('clear')
}
// FU107: klik di luar blok tambah menutup menu (sebelumnya menu lengket
// terbuka sampai tombol/opsi diklik); listener dokumen dilepas saat unmount
function onDocClick(e) {
  if (addOpen.value && !e.target.closest('.frows-addwrap')) addOpen.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div class="frows">
    <div v-for="f in activeRows" :key="f.key" class="frow">
      <div class="frow-head">
        <span class="frow-label">{{ f.label }}</span>
        <button v-if="!f.immediate" type="button" class="frow-x" :aria-label="'Hapus filter ' + f.label" @click="removeRow(f.key)">
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
        :first-to="f.firstTo || 'clear'"
        :reset-dari="f.resetDari || ''"
        :reset-sampai="f.resetSampai || ''"
        :placeholder="f.placeholder || ''"
      />
      <!-- FU107: baris nilai TUNGGAL milik parent (mis. Company) — opsi dari
           parent, diterapkan SEGERA lewat immediate-change (bukan draft);
           nilai kosong = "Semua company" -->
      <select
        v-else-if="f.type === 'select'"
        class="select"
        :value="props.immediate[f.key] ?? ''"
        :aria-label="f.ariaLabel || f.label"
        @change="emit('immediate-change', f.key, $event.target.value)"
      >
        <option v-for="o in (f.options || [])" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <p v-if="rowErrors[f.key]" class="frow-hint" role="status">{{ rowErrors[f.key] }}</p>
    </div>

    <div v-if="hasDraftFields" class="frows-addwrap">
      <!-- FU107: menu IN-FLOW di bawah tombol (sebelumnya absolute mengapung
           NAIK keluar panel, menutupi toolbar/kontrol lain — laporan user).
           Urutan DOM: tombol dulu, menu menyusul agar mendorong footer turun. -->
      <button type="button" class="linkbtn frows-addbtn" :aria-expanded="addOpen ? 'true' : 'false'" @click="addOpen = !addOpen">
        <Plus :size="13" :stroke-width="2.4" />
        Tambah filter
      </button>
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
    </div>

    <div v-if="hasDraftFields" class="frows-foot">
      <button type="button" class="linkbtn filter-clear frows-clear" @click="clearAll">Hapus semua</button>
      <button type="button" class="btn btn-sm btn-primary" :disabled="blocked" @click="commit">Terapkan</button>
    </div>
  </div>
</template>

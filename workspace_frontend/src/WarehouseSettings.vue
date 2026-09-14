<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Warehouse } from 'lucide-vue-next'
import { call, loadSuggestionPreferences, saveSuggestionPreferences, suggestionPreferences } from './store.js'
import LinkInput from './LinkInput.vue'

const fields = [
  { key: 'source_warehouse', label: 'Source Warehouse', desc: 'Lokasi bahan baku tersedia.' },
  { key: 'wip_warehouse', label: 'Work-in-Progress Warehouse', desc: 'Lokasi operasi produksi dijalankan.' },
  { key: 'fg_warehouse', label: 'Target Warehouse', desc: 'Lokasi barang jadi disimpan.' },
  { key: 'scrap_warehouse', label: 'Scrap Warehouse', desc: 'Lokasi material scrap disimpan.' },
  { key: 'handover_warehouse', label: 'Gudang serah terima / barang jadi', desc: 'Tujuan pengiriman serah terima (halaman Stock Entry).' }
]

const form = reactive({
  source_warehouse: '',
  wip_warehouse: '',
  fg_warehouse: '',
  scrap_warehouse: '',
  handover_warehouse: ''
})
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const savedAt = ref('')
const suggestionSaving = ref(false)

onMounted(async () => {
  try {
    await Promise.all([
      call('production_app.api.work_order.warehouse_defaults').then(values => Object.assign(form, values)),
      loadSuggestionPreferences()
    ])
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

async function toggleSuggestions() {
  suggestionSaving.value = true
  error.value = ''
  try {
    await saveSuggestionPreferences(suggestionPreferences.enabled)
  } catch (e) {
    suggestionPreferences.enabled = !suggestionPreferences.enabled
    error.value = e.message
  } finally {
    suggestionSaving.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  savedAt.value = ''
  try {
    Object.assign(form, await call('production_app.api.work_order.warehouse_defaults_save', { ...form }))
    savedAt.value = new Date().toLocaleTimeString('id-ID')
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><Warehouse :size="15" :stroke-width="1.9" /></span>
      <h2>Pengaturan Gudang</h2>
      <span class="lead">Gudang default untuk setiap Work Order di workspace ini.</span>
    </div>

    <div class="panel-body">
      <div class="callout ok" style="margin-bottom: 14px">
        Nilai di bawah dipakai Work Order yang kolom gudangnya masih kosong saat
        Persiapan disimpan — nilai yang sudah terisi di Work Order tidak pernah ditimpa.
      </div>

      <div v-if="loading" class="empty">Memuat pengaturan…</div>
      <template v-else>
        <div class="settings-block">
          <div class="settings-block-head">
            <div>
              <h3>Saran isian berulang</h3>
              <p class="hint">Gunakan nilai dari Work Order sebelumnya dengan produk yang sama untuk nama tim, jumlah kru, dan QC.</p>
            </div>
            <label class="toggle-control">
              <input v-model="suggestionPreferences.enabled" type="checkbox" :disabled="suggestionSaving" @change="toggleSuggestions" />
              <span>{{ suggestionPreferences.enabled ? 'Aktif' : 'Nonaktif' }}</span>
            </label>
          </div>
        </div>

        <div class="form-grid cols2">
          <div v-for="f in fields" :key="f.key" class="field">
            <label :for="`wh-${f.key}`">{{ f.label }}</label>
            <LinkInput :id="`wh-${f.key}`" v-model="form[f.key]" doctype="Warehouse" />
            <div class="hint">{{ f.desc }}</div>
          </div>
        </div>

        <p v-if="error" class="err" role="alert">{{ error }}</p>

        <div class="panel-foot" style="padding-left: 0">
          <button class="btn btn-primary" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan…' : 'Simpan Pengaturan' }}
          </button>
          <span v-if="savedAt" class="why">Tersimpan di ERPNext pada {{ savedAt }}.</span>
        </div>
      </template>
    </div>
  </section>
</template>

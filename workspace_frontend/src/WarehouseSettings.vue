<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Warehouse } from 'lucide-vue-next'
import { call, loadSuggestionPreferences, saveSuggestionPreferences, suggestionPreferences, uiTopLoading } from './store.js'
import LinkInput from './LinkInput.vue'

// FU40: label konsisten Indonesia (istilah ERPNext dipertahankan di keterangan),
// grid dipecah dua blok: default Work Order vs default serah terima.
const woFields = [
  { key: 'source_warehouse', label: 'Gudang Sumber', desc: 'Source Warehouse — lokasi bahan baku tersedia.' },
  { key: 'wip_warehouse', label: 'Gudang Work in Progress', desc: 'WIP Warehouse — lokasi operasi produksi dijalankan.' },
  { key: 'fg_warehouse', label: 'Gudang Target', desc: 'Target Warehouse — lokasi barang jadi disimpan.' },
  { key: 'scrap_warehouse', label: 'Gudang Scrap', desc: 'Scrap Warehouse — lokasi material scrap disimpan.' }
]
const handoverFields = [
  { key: 'handover_warehouse', label: 'Gudang Tujuan Serah Terima', desc: 'Tujuan pengiriman barang jadi (halaman Serah Terima).' },
  { key: 'handover_source_warehouse', label: 'Gudang Asal Serah Terima', desc: 'Asal pengiriman — biasanya Cold Storage (halaman Serah Terima).' }
]
// FO 2026-09-18: rute default Form Order (produksi minta barang dari gudang).
const formOrderFields = [
  { key: 'form_order_source_warehouse', label: 'Gudang Asal Form Order', desc: 'Gudang yang diminta produksi (mis. Gudang Bahan Baku).' },
  { key: 'form_order_target_warehouse', label: 'Gudang Tujuan Form Order', desc: 'Tujuan pemindahan stok saat gudang memproses (mis. WIP).' }
]

const form = reactive({
  source_warehouse: '',
  wip_warehouse: '',
  fg_warehouse: '',
  scrap_warehouse: '',
  handover_warehouse: '',
  handover_source_warehouse: '',
  form_order_source_warehouse: '',
  form_order_target_warehouse: ''
})
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const savedAt = ref('')
const suggestionSaving = ref(false)

onMounted(async () => {
  uiTopLoading.active = true
  try {
    await Promise.all([
      call('production_app.api.work_order.warehouse_defaults').then(values => Object.assign(form, values)),
      loadSuggestionPreferences()
    ])
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    uiTopLoading.active = false
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
      <span class="lead">Gudang default untuk Work Order dan serah terima di workspace ini.</span>
    </div>

    <div class="panel-body">
      <!-- FU20: loading ditandai spinner global di tepi atas (App.vue) -->
      <div v-if="loading" aria-hidden="true"></div>
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

        <div class="settings-block">
          <div class="settings-block-head">
            <div>
              <h3>Default Work Order</h3>
            </div>
          </div>
          <div class="callout ok" style="margin-bottom: 14px">
            Dipakai Work Order yang kolom gudangnya masih kosong saat Persiapan
            disimpan — nilai yang sudah terisi di Work Order tidak pernah ditimpa.
          </div>
          <div class="form-grid cols2">
            <div v-for="f in woFields" :key="f.key" class="field">
              <label :for="`wh-${f.key}`">{{ f.label }}</label>
              <LinkInput :id="`wh-${f.key}`" v-model="form[f.key]" doctype="Warehouse" />
              <div class="hint">{{ f.desc }}</div>
            </div>
          </div>
        </div>

        <div class="settings-block">
          <div class="settings-block-head">
            <div>
              <h3>Serah Terima</h3>
              <p class="hint">Asal dan tujuan default pengiriman di papan Serah Terima.</p>
            </div>
          </div>
          <div class="form-grid cols2" style="margin-top: 12px">
            <div v-for="f in handoverFields" :key="f.key" class="field">
              <label :for="`wh-${f.key}`">{{ f.label }}</label>
              <LinkInput :id="`wh-${f.key}`" v-model="form[f.key]" doctype="Warehouse" />
              <div class="hint">{{ f.desc }}</div>
            </div>
          </div>
        </div>

        <div class="settings-block">
          <div class="settings-block-head">
            <div>
              <h3>Form Order</h3>
              <p class="hint">Rute default permintaan produksi ke gudang — wajib diisi sebelum Form Order bisa dibuat.</p>
            </div>
          </div>
          <div class="form-grid cols2" style="margin-top: 12px">
            <div v-for="f in formOrderFields" :key="f.key" class="field">
              <label :for="`wh-${f.key}`">{{ f.label }}</label>
              <LinkInput :id="`wh-${f.key}`" v-model="form[f.key]" doctype="Warehouse" />
              <div class="hint">{{ f.desc }}</div>
            </div>
          </div>
        </div>

        <p v-if="error" class="err" role="alert">{{ error }}</p>

        <div class="panel-foot" style="padding-left: 0">
          <button class="btn btn-primary" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan…' : 'Simpan Pengaturan' }}
          </button>
          <span v-if="savedAt" class="why">Tersimpan pada {{ savedAt }}.</span>
        </div>
      </template>
    </div>
  </section>
</template>

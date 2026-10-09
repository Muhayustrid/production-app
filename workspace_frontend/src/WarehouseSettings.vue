<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { SlidersHorizontal, Warehouse, X } from 'lucide-vue-next'
import { call, loadSuggestionPreferences, saveSuggestionPreferences, suggestionPreferences, uiState, uiTopLoading, saveUiPreferences } from './store.js'
import LinkInput from './LinkInput.vue'

// FU40: label konsisten Indonesia (istilah ERPNext dipertahankan di keterangan),
// grid dipecah dua blok: default Work Order vs default serah terima.
const woFields = [
  { key: 'source_warehouse', label: 'Gudang Sumber' },
  { key: 'wip_warehouse', label: 'Gudang Work in Progress' },
  { key: 'fg_warehouse', label: 'Gudang Target' },
  { key: 'scrap_warehouse', label: 'Gudang Scrap' }
]
const handoverFields = [
  { key: 'handover_warehouse', label: 'Gudang Tujuan' },
  { key: 'handover_source_warehouse', label: 'Gudang Asal' }
]
// FO 2026-09-18: rute default Form Order (produksi minta barang dari gudang).
const formOrderFields = [
  { key: 'form_order_source_warehouse', label: 'Gudang Asal' },
  { key: 'form_order_target_warehouse', label: 'Gudang Tujuan' }
]

// FU61: 8 kunci flat kontrak API — payload simpan dikirim eksplisit dari
// daftar ini dan hanya kunci ini yang disalin balik dari response, agar kunci
// propagated/skipped/failed tidak pernah terkirim balik / menempel di form.
const FLAT_KEYS = [
  'source_warehouse',
  'wip_warehouse',
  'fg_warehouse',
  'scrap_warehouse',
  'handover_warehouse',
  'handover_source_warehouse',
  'form_order_source_warehouse',
  'form_order_target_warehouse',
  'production_item_group'
]

const form = reactive({
  source_warehouse: '',
  wip_warehouse: '',
  fg_warehouse: '',
  scrap_warehouse: '',
  handover_warehouse: '',
  handover_source_warehouse: '',
  form_order_source_warehouse: '',
  form_order_target_warehouse: '',
  production_item_group: ''
})
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const prefError = ref('') // galat preferensi pribadi (tersimpan otomatis) — terpisah dari galat tombol Simpan
const savedAt = ref('')
const savedInfo = ref('')
const saveFailed = ref([])
const suggestionSaving = ref(false)

// FU114: item Tanpa Pre-Packing — tersimpan langsung per item (bukan lewat
// tombol Simpan yang ikut mempropagasi gudang ke WO berjalan).
const skipItems = ref([])
const skipPick = ref('')
const skipSaving = ref(false)
const skipError = ref('')
const skipPickKey = ref(0) // remount LinkInput agar teks pencarian bersih setelah item ditambah
async function setSkip(item, enabled) {
  skipSaving.value = true
  skipError.value = ''
  try {
    skipItems.value = await call('production_app.api.work_order.skip_prepacking_set', { item, enabled: enabled ? 1 : 0 })
  } catch (e) {
    skipError.value = e.message
  } finally {
    skipSaving.value = false
  }
}
watch(skipPick, (item) => {
  if (!item) return
  setSkip(item, true)
  skipPick.value = ''
  skipPickKey.value++
})

onMounted(async () => {
  uiTopLoading.active = true
  try {
    await Promise.all([
      call('production_app.api.work_order.warehouse_defaults').then(values => Object.assign(form, values)),
      loadSuggestionPreferences(),
      call('production_app.api.work_order.skip_prepacking_items').then(rows => { skipItems.value = rows })
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
  prefError.value = ''
  try {
    await saveSuggestionPreferences(suggestionPreferences.enabled)
  } catch (e) {
    suggestionPreferences.enabled = !suggestionPreferences.enabled
    prefError.value = e.message
  } finally {
    suggestionSaving.value = false
  }
}

// FU70: ukuran font per-user — tersimpan saat digeser, berlaku langsung
// FU112: preferensi dimuat TIDAK di-await saat boot (App onMounted); bila
// halaman ini di-refresh langsung, salinan lokal di atas masih nilai default
// saat respons server tiba — ikuti uiState agar slider tak menampilkan angka
// basi (zoom sudah benar; hanya tampilan slider yang salah). Saat menyimpan
// (fontSaving) jangan timpa nilai yang sedang digeser.
const fontScale = ref(uiState.fontScale)
const fontSaving = ref(false)
watch(() => uiState.fontScale, (v) => { if (!fontSaving.value) fontScale.value = v })
async function onFontScaleChange() {
  fontSaving.value = true
  prefError.value = ''
  try {
    fontScale.value = await saveUiPreferences(fontScale.value)
  } catch (e) {
    prefError.value = e.message
    fontScale.value = uiState.fontScale // kembalikan ke nilai tersimpan
  } finally {
    fontSaving.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  savedAt.value = ''
  savedInfo.value = ''
  saveFailed.value = []
  try {
    // FU58 §9.4: payload eksplisit 9 field (bukan {...form}) — lihat FLAT_KEYS.
    const payload = {}
    for (const key of FLAT_KEYS) payload[key] = form[key]
    const saved = await call('production_app.api.work_order.warehouse_defaults_save', payload)
    for (const key of FLAT_KEYS) if (key in saved) form[key] = saved[key] ?? ''
    savedAt.value = new Date().toLocaleTimeString('id-ID')
    const propagated = saved.propagated || []
    if (propagated.length) {
      const names = propagated.map(p => p.name).slice(0, 5).join(', ')
      savedInfo.value = propagated.length > 5
        ? `${propagated.length} Work Order berjalan diperbarui (${names} …)`
        : `${propagated.length} Work Order berjalan diperbarui: ${names}`
    }
    // Kegagalan per-WO tidak menggagalkan tersimpannya pengaturan (§4.5).
    saveFailed.value = (saved.failed || []).map(f => `${f.name}: ${f.error}`)
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Pengaturan</h1>
    </div>
  </div>

  <!-- FU20: loading ditandai spinner global di tepi atas (App.vue) -->
  <div v-if="loading" aria-hidden="true"></div>
  <template v-else>
    <section class="panel settings-panel">
      <div class="panel-head">
        <span class="p-ico"><SlidersHorizontal :size="15" :stroke-width="1.9" /></span>
        <h2>Preferensi Saya</h2>
        <span class="lead">Khusus akun ini, tersimpan otomatis.</span>
      </div>
      <div class="panel-body">
        <div class="settings-block">
          <div class="settings-block-head">
            <h3>Tampilan</h3>
          </div>
          <div class="settings-control">
            <div class="field settings-range">
              <label for="ui-font-scale">Ukuran font: <strong>{{ fontScale }}%</strong></label>
              <input id="ui-font-scale" v-model.number="fontScale" type="range" min="90" max="125" step="5" :disabled="fontSaving" @change="onFontScaleChange" />
              <div class="hint">Rentang 90–125%.</div>
            </div>
          </div>
        </div>

        <div class="settings-block">
          <div class="settings-block-head">
            <h3>Saran isian berulang</h3>
            <p class="hint">Isi tim, jumlah kru, dan QC dari Work Order sebelumnya untuk produk yang sama.</p>
          </div>
          <div class="settings-control">
            <label class="switch">
              <input v-model="suggestionPreferences.enabled" type="checkbox" role="switch" :disabled="suggestionSaving" @change="toggleSuggestions" />
              <span>{{ suggestionPreferences.enabled ? 'Aktif' : 'Nonaktif' }}</span>
            </label>
          </div>
        </div>

        <p v-if="prefError" class="err" role="alert">{{ prefError }}</p>
      </div>
    </section>

    <section class="panel settings-panel">
      <div class="panel-head">
        <span class="p-ico"><Warehouse :size="15" :stroke-width="1.9" /></span>
        <h2>Default Workspace</h2>
        <span class="lead">Berlaku untuk semua pengguna.</span>
      </div>

      <div class="panel-body">
        <div class="settings-block">
          <div class="settings-block-head">
            <h3>Default Work Order</h3>
            <p class="hint">Dipakai saat gudang di Work Order masih kosong.</p>
          </div>
          <div class="settings-control">
            <p class="settings-note">
              Ubah langsung ke nilai baru, jangan dikosongkan dulu. Work Order yang sedang
              berjalan ikut diperbarui selama nilainya belum diubah manual. Yang gagal
              diperbarui perlu disinkronkan admin.
            </p>
            <div class="form-grid cols2">
              <div v-for="f in woFields" :key="f.key" class="field">
                <label :for="`wh-${f.key}`">{{ f.label }}</label>
                <LinkInput :id="`wh-${f.key}`" v-model="form[f.key]" doctype="Warehouse" />
              </div>
            </div>
          </div>
        </div>

        <div class="settings-block">
          <div class="settings-block-head">
            <h3>Stock Entry</h3>
            <p class="hint">Asal dan tujuan default pengiriman.</p>
          </div>
          <div class="settings-control">
            <div class="form-grid cols2">
              <div v-for="f in handoverFields" :key="f.key" class="field">
                <label :for="`wh-${f.key}`">{{ f.label }}</label>
                <LinkInput :id="`wh-${f.key}`" v-model="form[f.key]" doctype="Warehouse" />
              </div>
            </div>
          </div>
        </div>

        <div class="settings-block">
          <div class="settings-block-head">
            <h3>Form Order</h3>
            <p class="hint">Wajib diisi sebelum Form Order bisa dibuat.</p>
          </div>
          <div class="settings-control">
            <div class="form-grid cols2">
              <div v-for="f in formOrderFields" :key="f.key" class="field">
                <label :for="`wh-${f.key}`">{{ f.label }}</label>
                <LinkInput :id="`wh-${f.key}`" v-model="form[f.key]" doctype="Warehouse" />
              </div>
            </div>
          </div>
        </div>

        <div class="settings-block">
          <div class="settings-block-head">
            <h3>Tanpa Pre-Packing</h3>
            <p class="hint">Produk yang langsung ke Post-Packing. Tersimpan otomatis.</p>
          </div>
          <div class="settings-control">
            <ul v-if="skipItems.length" class="skip-list">
              <li v-for="it in skipItems" :key="it.name">
                <span>{{ it.item_name || it.name }} <small class="mono">{{ it.name }}</small></span>
                <button type="button" class="btn btn-sm" :disabled="skipSaving" :aria-label="`Hapus ${it.item_name || it.name}`" @click="setSkip(it.name, false)">
                  <X :size="14" :stroke-width="2" />
                </button>
              </li>
            </ul>
            <div class="field settings-range">
              <label for="skip-prepacking-item">Tambah item</label>
              <LinkInput id="skip-prepacking-item" :key="skipPickKey" v-model="skipPick" doctype="Item" :disabled="skipSaving" />
            </div>
            <p v-if="skipError" class="err" role="alert">{{ skipError }}</p>
          </div>
        </div>

        <!-- FU93: filter Item Group wizard Tambah Plan (bukan gudang — LinkInput Item Group) -->
        <div class="settings-block">
          <div class="settings-block-head">
            <h3>Production Plan</h3>
            <p class="hint">Filter item di wizard Tambah Plan.</p>
          </div>
          <div class="settings-control">
            <div class="form-grid cols2">
              <div class="field">
                <label for="wh-production_item_group">Item Group Produk</label>
                <LinkInput id="wh-production_item_group" v-model="form.production_item_group" doctype="Item Group" />
                <div class="hint">Kosong = tanpa filter.</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="error || saveFailed.length" class="settings-alerts">
        <p v-if="error" class="err" role="alert">{{ error }}</p>
        <!-- FU58 §9.4: kegagalan per-WO saat propagasi — pengaturan tetap tersimpan. -->
        <div v-if="saveFailed.length" class="err" role="alert">
          <div>Pengaturan tersimpan, tetapi Work Order berikut gagal diperbarui:</div>
          <div v-for="item in saveFailed" :key="item">{{ item }}</div>
        </div>
      </div>

      <div class="panel-foot">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? 'Menyimpan…' : 'Simpan Pengaturan' }}
        </button>
        <span v-if="savedAt" class="why">Tersimpan pada {{ savedAt }}<template v-if="savedInfo"> — {{ savedInfo }}</template>.</span>
      </div>
    </section>
  </template>
</template>

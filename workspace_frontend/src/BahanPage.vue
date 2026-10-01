<script setup>
// FU74: halaman "Bahan baku" (#/bahan) — pemakaian material vs rencana BOM
// yang diskalakan ke hasil produksi nyata. Data dari satu endpoint whitelisted
// (store.loadBahan); server memutuskan urutan baris (terburuk dulu) — frontend
// tidak mengurut ulang. Baris bisa dibuka (expander) untuk rincian per WO.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import Tag from 'primevue/tag'
import { Search, SearchX } from 'lucide-vue-next'
import { bahanState, loadBahan } from './store.js'
import { fmtId } from './format.js'
import { variancePctText } from './dashboard.js'

const props = defineProps({
  initialBahan: { type: String, default: '' }, // prefilled search dari query ?bahan=
  initialDari: { type: String, default: '' },
  initialSampai: { type: String, default: '' },
  initialCompany: { type: String, default: '' }
})

const q = ref(props.initialBahan)
const dari = ref(props.initialDari)
const sampai = ref(props.initialSampai)
// sentinel ALL — PrimeVue Select memperlakukan '' sebagai "tidak ada pilihan"
const product = ref('ALL')
const company = ref(props.initialCompany || 'ALL')
const overOnly = ref(false)
const expanded = ref([])
let reloadTimer
let echoingDates = false

const companies = computed(() => bahanState.data?.companies || [])
const showCompany = computed(() => companies.value.length > 1)
const companyOptions = computed(() => [
  { label: 'Semua company', value: 'ALL' },
  ...companies.value.map((c) => ({ label: c, value: c }))
])
const productOptions = computed(() => [
  { label: 'Semua produk', value: 'ALL' },
  ...(bahanState.data?.products || []).map((p) => ({ label: p.item_name || p.item_code, value: p.item_code }))
])
const rows = computed(() => bahanState.data?.rows || [])
const rangeInvalid = computed(() => !!dari.value && !!sampai.value && dari.value > sampai.value)

function payload() {
  return {
    dari: dari.value,
    sampai: sampai.value,
    company: company.value === 'ALL' ? '' : company.value,
    productionItem: product.value === 'ALL' ? '' : product.value,
    search: q.value.trim(),
    overOnly: overOnly.value
  }
}
async function reload() {
  if (rangeInvalid.value) return // inline hint tampil; API tidak dipanggil
  const firstLoad = !bahanState.loaded
  await loadBahan(payload())
  // muat pertama tanpa tanggal: isi input dari jawaban server (server
  // otoritatif atas "hari ini"); setelahnya isian user tak pernah ditimpa
  const data = bahanState.data
  if (firstLoad && data && (!dari.value || !sampai.value)) {
    echoingDates = true
    if (!dari.value && data.dari) dari.value = data.dari
    if (!sampai.value && data.sampai) sampai.value = data.sampai
    await nextTick()
    echoingDates = false
  }
}
function scheduleReload() {
  clearTimeout(reloadTimer)
  reloadTimer = setTimeout(reload, 180)
}
watch(q, scheduleReload)
watch([dari, sampai], () => { if (!echoingDates) scheduleReload() })
watch(overOnly, scheduleReload)
// deep link saat halaman sudah terbuka (hash berubah tanpa remount — goto
// dalam SPA hanya hashchange): ikuti perubahan props awal dari router
watch(
  () => props.initialBahan,
  (v) => {
    if (v && v !== q.value) {
      q.value = v
      scheduleReload()
    }
  }
)
onMounted(reload)

// sel "Selisih %": over → tag merah; di bawah rencana → tag netral;
// variance_pct null → 'tanpa dasar' (tetap merah bila row.over — baris ini
// muncul di filter "hanya di atas rencana", review FU74 #3)
function pctTag(row) {
  const raw = row?.variance_pct
  if (raw == null || !Number.isFinite(Number(raw))) return { text: 'tanpa dasar', over: !!row?.over }
  return { text: variancePctText(row), over: !!row?.over }
}
function noPlan(w) { return !Number(w?.planned) }
function woHref(wo) { return '#/wo/' + encodeURIComponent(wo) }
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Bahan baku</h1>
      <p class="sub">Pemakaian bahan baku dibanding rencana BOM, diskalakan ke hasil produksi nyata.</p>
    </div>
    <div class="ph-right">
      <Select
        v-if="showCompany"
        v-model="company"
        :options="companyOptions"
        optionLabel="label"
        optionValue="value"
        inputId="bahan-company"
        aria-label="Filter company"
        class="ph-pselect"
        @change="reload"
      />
    </div>
  </div>

  <div class="toolbar bahan-toolbar">
    <input v-model="dari" class="input bahan-date" type="date" aria-label="Dari tanggal" />
    <input v-model="sampai" class="input bahan-date" type="date" aria-label="Sampai tanggal" />
    <Select
      v-model="product"
      :options="productOptions"
      optionLabel="label"
      optionValue="value"
      inputId="bahan-product"
      aria-label="Filter produk"
      class="ph-pselect"
      @change="reload"
    />
    <div class="searchbox">
      <Search :size="15" :stroke-width="2" class="search-ico" />
      <input
        v-model="q"
        class="input"
        type="search"
        placeholder="Cari bahan"
        aria-label="Cari bahan"
      />
    </div>
    <label class="bahan-check" for="bahan-over">
      <Checkbox v-model="overOnly" binary inputId="bahan-over" />
      <span>Hanya di atas rencana</span>
    </label>
  </div>

  <p v-if="rangeInvalid" class="callout bahan-range-warn" role="status">
    Rentang tanggal tidak valid: "dari" melebihi "sampai". Perbaiki tanggal untuk memuat data.
  </p>

  <div v-if="bahanState.error" class="callout bad dash-error" role="alert">
    <p>Gagal memuat: {{ bahanState.error }}</p>
    <Button label="Coba lagi" size="small" severity="secondary" variant="outlined" @click="reload" />
  </div>

  <template v-if="bahanState.loading && !bahanState.loaded">
    <section class="panel" aria-hidden="true">
      <div class="panel-body dash-skel-stack">
        <Skeleton v-for="m in 6" :key="m" width="100%" height="34px" borderRadius="6px" />
      </div>
    </section>
  </template>

  <template v-else-if="bahanState.loaded && !bahanState.error && !rangeInvalid">
    <section class="panel dash-tablewrap" aria-label="Tabel pemakaian bahan">
      <DataTable
        :value="rows"
        dataKey="item_code"
        v-model:expandedRows="expanded"
        class="dash-table bahan-table"
      >
        <Column expander style="width: 36px" />
        <Column header="Bahan">
          <template #body="{ data }">
            <span class="wo-prod bahan-name">
              {{ data.item_name || data.item_code }}
              <small v-if="data.item_code" class="mono">{{ data.item_code }}</small>
              <span v-if="data.unlisted" class="chip chip-off bahan-noplan">tanpa rencana</span>
            </span>
          </template>
        </Column>
        <Column field="uom" header="UOM" style="width: 84px" />
        <Column header="Rencana" style="width: 110px" headerStyle="text-align: right" bodyStyle="text-align: right">
          <template #body="{ data }">{{ fmtId(data.planned) }}</template>
        </Column>
        <Column header="Sesuai hasil" style="width: 120px" headerStyle="text-align: right" bodyStyle="text-align: right">
          <template #body="{ data }">{{ fmtId(data.expected) }}</template>
        </Column>
        <Column header="Terpakai" style="width: 110px" headerStyle="text-align: right" bodyStyle="text-align: right">
          <template #body="{ data }">{{ fmtId(data.consumed) }}</template>
        </Column>
        <Column header="Selisih" style="width: 110px" headerStyle="text-align: right" bodyStyle="text-align: right">
          <template #body="{ data }">{{ fmtId(data.variance) }}</template>
        </Column>
        <Column header="Selisih %" style="width: 130px" headerStyle="text-align: right" bodyStyle="text-align: right">
          <template #body="{ data }">
            <Tag
              :value="pctTag(data).text"
              :severity="pctTag(data).over ? 'danger' : undefined"
              :class="pctTag(data).over ? 'bahan-tag over' : 'bahan-tag'"
            />
          </template>
        </Column>
        <template #empty>
          <div class="empty-inset">
            <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
            <p class="etitle">Tidak ada pemakaian bahan pada rentang ini</p>
          </div>
        </template>
        <template #expansion="{ data }">
          <div class="bahan-expansion">
            <table class="bahan-sub">
              <thead>
                <tr>
                  <th>WO</th>
                  <th>Produk</th>
                  <th class="num">Rencana</th>
                  <th class="num">Sesuai hasil</th>
                  <th class="num">Terpakai</th>
                  <th class="num">Selisih</th>
                  <th class="num">%</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="w in data.work_orders" :key="w.wo">
                  <td>
                    <a class="linklike" :href="woHref(w.wo)">{{ w.wo }}</a>
                    <span v-if="noPlan(w)" class="chip chip-off bahan-noplan">tanpa rencana</span>
                  </td>
                  <td>{{ w.produk }}</td>
                  <td class="num">{{ fmtId(w.planned) }}</td>
                  <td class="num">{{ fmtId(w.expected) }}</td>
                  <td class="num">{{ fmtId(w.consumed) }}</td>
                  <td class="num">{{ fmtId(w.variance) }}</td>
                  <td class="num">
                    <Tag
                      :value="pctTag(w).text"
                      :severity="pctTag(w).over ? 'danger' : undefined"
                      :class="pctTag(w).over ? 'bahan-tag over' : 'bahan-tag'"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </DataTable>
    </section>
    <p class="srcnote">
      Lingkup: Work Order dengan tanggal rencana dalam rentang terpilih. Konsumsi = Stock Entry
      Manufacture/Konsumsi dari WIP — retur membalik transfer, bukan konsumsi. "Sesuai hasil" =
      rencana BOM proporsional terhadap hasil produksi nyata (produced_qty). Ambang di atas rencana
      5%. Bahan yang dipakai tanpa rencana BOM ditandai "tanpa rencana"; selisih tanpa dasar
      ekspektasi ditandai "tanpa dasar". Pemakaian di bawah ekspektasi tidak ditandai merah.
    </p>
  </template>
</template>

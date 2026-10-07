<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { call, HANDOVER_LABELS, listPreferencesState, loadList, listPrefs, listState, normalizePageSize, PAGE_SIZE_OPTIONS, pendingStageFilter, saveListPreferences, savedListPreferences, STAGE_LABELS, workOrders } from './store.js'
import { fmtDate, qtyStack } from './format.js'
import { buildWorkOrderPreferences, normalizeWorkOrderPreferences } from './work-order-preferences.js'
import { countFilters, normalizeFilters } from './filter-rows.js'
import { nextSortDir } from './table-sort.js'
import { Search, Filter, ChevronRight, SearchX, Table, Kanban, X, ArrowDown } from 'lucide-vue-next'
import WorkOrderKanban from './WorkOrderKanban.vue'
import FilterRows from './FilterRows.vue'

const q = ref('')
// FU100: filter halaman = objek baris ala ERPNext (key = field, nilai array
// multi-value / objek rentang). FU109: company BUKAN filter halaman ini —
// kontrolnya hanya di Dashboard; loader store tetap menerapkan scope global
// (companyFilterState) dan "Hapus semua" di sini tidak menyentuhnya.
// Draft ada di dalam FilterRows; `applied` baru berubah saat Terapkan/panel
// ditutup → satu fetch lewat watcher di bawah.
const applied = ref({})
const frowsRef = ref(null) // FilterRows — commit draft saat panel ditutup (FU100)
const pageSize = computed(() => listState.pageSize)
const filterOpen = ref(false)
const restoring = ref(true)
let reloadTimer
// FU72: filter satu-shot dari Dashboard (tahap/tanggal) — override runtime
// saja. FU95: company satu-shot DIHAPUS (kini filter global tersimpan).
let oneShotStage = false
const STAGE_FILTER_MAP = { pre_packing: 'prepacking', post_packing: 'postpacking', selesai_hari_ini: 'selesai' }
function consumePendingStage() {
  const pending = pendingStageFilter
  if (!pending.stage && !pending.from) return
  const { stage, from, to } = pending
  pendingStageFilter.stage = '' // one-shot: langsung dikosongkan
  pendingStageFilter.from = ''
  pendingStageFilter.to = ''
  const patch = {}
  if (stage) {
    const value = STAGE_FILTER_MAP[stage] || stage
    if (['persiapan', 'material', 'operasi', 'prepacking', 'postpacking', 'finish', 'selesai'].includes(value)) {
      patch.tahap = [value]
      oneShotStage = true
    }
  }
  if (from) { patch.jadwal = { dari: from, sampai: to || from }; oneShotStage = true }
  if (Object.keys(patch).length) applied.value = { ...applied.value, ...patch }
}

const products = computed(() => [...new Map(workOrders.map((w) => [w.itemCode, w.product]))].sort((a, b) => a[1].localeCompare(b[1])))
// FU100: opsi produk MultiSelect = distinct production_item dari WO yang
// terlihat user (server); dimuat sekali saat panel pertama dibuka, fallback
// daftar dari halaman ter-muat bila endpoint gagal
const productOptions = ref([])
const productOptionsLoaded = ref(false)
async function ensureProductOptions() {
  if (productOptionsLoaded.value) return
  productOptionsLoaded.value = true
  try {
    productOptions.value = (await call('production_app.api.work_order.wo_product_options')) || []
  } catch {
    productOptions.value = []
  }
  if (!productOptions.value.length) {
    productOptions.value = products.value.map(([code, name]) => ({ value: code, label: name }))
  }
}
// deskriptor untuk normalize (key+type stabil); options dilampirkan di computed
const WO_FILTER_SHAPE = [
  { key: 'produk', type: 'multi' },
  { key: 'status', type: 'multi' },
  { key: 'tahap', type: 'multi' },
  { key: 'jadwal', type: 'range' }
]
const filterFields = computed(() => [
  {
    key: 'produk', label: 'Produk', type: 'multi', filter: true,
    placeholder: 'Pilih satu atau lebih produk',
    options: productOptions.value.length
      ? productOptions.value
      : products.value.map(([code, name]) => ({ value: code, label: name }))
  },
  {
    key: 'status', label: 'Status', type: 'multi',
    options: [
      { value: 'Draft', label: 'Draft' },
      { value: 'In Process', label: 'In Process' },
      { value: 'Completed', label: 'Completed' }
    ]
  },
  {
    key: 'tahap', label: 'Tahap', type: 'multi',
    options: [
      { value: 'persiapan', label: 'Persiapan' },
      { value: 'material', label: 'Material' },
      { value: 'operasi', label: 'Operasi' },
      { value: 'prepacking', label: 'Pre-Packing' },
      { value: 'postpacking', label: 'Post-Packing' },
      { value: 'finish', label: 'Finish' },
      { value: 'selesai', label: 'Selesai' }
    ]
  },
  { key: 'jadwal', label: 'Jadwal', type: 'range', placeholder: 'Semua jadwal' }
])
const todayLabel = new Date().toLocaleDateString('id-ID', {
  weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
})
const totalPages = computed(() => Math.max(1, Math.ceil(listState.total / pageSize.value)))
const currentPage = computed(() => listState.page)
// FU109: badge = baris panel saja (company tidak lagi kontrol halaman ini)
const activeFilters = computed(() => countFilters(applied.value))

function filterPayload() {
  const f = applied.value
  return {
    search: q.value.trim(),
    productionItem: f.produk?.length ? f.produk : '',
    status: f.status?.length ? f.status : '',
    stage: f.tahap?.length ? f.tahap : '',
    startDate: f.jadwal?.dari || '',
    endDate: f.jadwal?.sampai || '',
    start: 0, pageLen: pageSize.value,
    order: orderToken.value
  }
}
// FU94: sort 3-klik di header (naik → turun → normal) — daftar WO
// server-paginated, jadi urutan dikirim sebagai token whitelist wo_list.
const WO_SORT_TOKENS = { wo: 'name', adonan: 'adonan', produk: 'item', jadwal: 'date', status: 'status', rencana: 'qty' }
const sortKey = ref('')
const sortDir = ref('')
const orderToken = computed(() =>
  (sortKey.value && sortDir.value) ? `${WO_SORT_TOKENS[sortKey.value]}_${sortDir.value}` : ''
)
function setSort(key) {
  if (sortKey.value !== key) { sortKey.value = key; sortDir.value = 'asc' }
  else {
    sortDir.value = nextSortDir(sortDir.value)
    if (!sortDir.value) sortKey.value = '' // klik ke-3 = normal: ikon header ikut hilang
  }
  reload()
}
function saveWoPreferences() {
  if (restoring.value) return Promise.resolve()
  return saveListPreferences({
    workOrder: buildWorkOrderPreferences({
      q: q.value,
      products: applied.value.produk || [],
      statuses: applied.value.status || [],
      stages: applied.value.tahap || [],
      from: applied.value.jadwal?.dari || '',
      to: applied.value.jadwal?.sampai || '',
      pageSize: pageSize.value,
      filterOpen: filterOpen.value,
      view: listPrefs.view
    }),
    handover: savedListPreferences.handover || {}
  })
}
async function reload() {
  listState.page = 1
  await loadList(filterPayload())
  // FU72: pemuatan pertama setelah one-shot stage jangan menimpa preferensi
  if (oneShotStage) oneShotStage = false
  else await saveWoPreferences()
}
function setPageSize(value) {
  listState.pageSize = normalizePageSize(value)
  reload()
}
function scheduleReload() {
  clearTimeout(reloadTimer)
  reloadTimer = setTimeout(reload, 180)
}
// FU108/FU109: "Hapus semua" panel = bersih TOTAL filter MILIK halaman ini —
// baris draft sudah dikosongkan commit FilterRows; di sini kotak cari.
// Company TIDAK disentuh (kontrolnya hanya di Dashboard; scope tetap
// berlaku). Watcher q/applied yang menjadwalkan muat ulang.
function clearFilters() {
  q.value = ''
}
function goPage(page) { listState.page = page; loadList({ ...filterPayload(), start: (page - 1) * pageSize.value, pageLen: pageSize.value }) }
const filtered = computed(() => {
  const f = applied.value
  return workOrders
    .filter(w => !f.produk?.length || f.produk.includes(w.itemCode))
    .filter(w => !f.status?.length || f.status.includes(w.status))
    .filter(w => !f.tahap?.length || f.tahap.some((s) => (s === 'selesai' ? w.stage === 'completed' : w.stage === s)))
    .filter(w => !f.jadwal?.dari || w.plannedDate >= f.jadwal.dari)
    .filter(w => !f.jadwal?.sampai || w.plannedDate <= f.jadwal.sampai)
    .filter(w => { const t = q.value.trim().toLowerCase(); return !t || w.id.toLowerCase().includes(t) || w.product.toLowerCase().includes(t) || w.itemCode.toLowerCase().includes(t) })
})
const pagedFiltered = computed(() => filtered.value)
watch(applied, () => {
  if (restoring.value) return
  listState.page = 1
  scheduleReload()
}, { deep: true })
watch([q], () => {
  if (restoring.value) return
  listState.page = 1
  scheduleReload()
})
watch(filterOpen, (open, sebelum) => {
  if (!open && sebelum) frowsRef.value?.commitIfChanged() // tutup panel = commit draft (FU100)
  if (open) ensureProductOptions()
  saveWoPreferences()
})
watch(() => listPrefs.view, saveWoPreferences)
onMounted(() => {
  const apply = async () => {
    const p = normalizeWorkOrderPreferences(savedListPreferences.workOrder)
    q.value = p.q
    applied.value = normalizeFilters({
      produk: p.products,
      status: p.statuses,
      tahap: p.stages,
      jadwal: { dari: p.from, sampai: p.to }
    }, WO_FILTER_SHAPE)
    listState.pageSize = normalizePageSize(p.pageSize)
    filterOpen.value = p.filterOpen
    listPrefs.view = p.view
    consumePendingStage() // override runtime sebelum fetch awal; tidak disimpan
    await nextTick()
    restoring.value = false
    reload()
  }
  if (listPreferencesState.loaded) apply()
  else {
    let appliedPrefs = false
    const run = () => { if (appliedPrefs) return; appliedPrefs = true; apply() }
    const timer = setInterval(() => { if (listPreferencesState.loaded) { clearInterval(timer); run() } }, 25)
    setTimeout(() => { clearInterval(timer); run() }, 2000)
  }
})
function open(id) { window.location.hash = '#/wo/' + id }
function statusClass(s) { return s === 'Draft' ? 'b-draft' : s === 'Completed' ? 'b-done' : 'b-run' }
function stageLabel(w) { return w.stage === 'completed' ? 'Selesai' : STAGE_LABELS[w.stage] }
// FU72/FU100: chip tahap tunggal (hasil one-shot dari Dashboard atau pilihan
// satu tahap); lebih dari satu tahap cukup diwakili badge panel
const stageChipKey = computed(() => (applied.value.tahap?.length === 1 ? applied.value.tahap[0] : ''))
const stageChipLabel = computed(() => (stageChipKey.value === 'selesai' ? 'Selesai' : STAGE_LABELS[stageChipKey.value]))
function removeStageChip() {
  const d = { ...applied.value }
  delete d.tahap
  applied.value = d
}
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Work Order</h1>
      <p class="sub">Siapkan material, jalankan produksi, dan catat hasil dalam satu alur.</p>
    </div>
    <div class="ph-date">{{ todayLabel }}</div>
  </div>

  <div class="toolbar">
    <div class="searchbox">
      <Search :size="15" :stroke-width="2" class="search-ico" />
      <input
        v-model="q"
        class="input"
        type="search"
        placeholder="Cari No. WO atau produk"
        aria-label="Cari perintah kerja"
      />
    </div>
    <div class="filterwrap">
      <button class="btn filterbtn" :class="{ active: activeFilters }" aria-label="Filter" @click="filterOpen = !filterOpen">
        <Filter :size="14" :stroke-width="2" />
        <span class="btext">Filter</span>
        <span v-if="activeFilters" class="filtercount">{{ activeFilters }}</span>
      </button>
      <div v-if="filterOpen" class="popoverlay" @click="filterOpen = false"></div>
      <Transition name="pop">
        <div v-if="filterOpen" class="filterpanel">
        <!-- FU100: baris filter ERPNext-style (multi-value, tambah/hapus
             baris, Terapkan/Hapus semua) — pilot halaman Work Order;
             FU109: Company tidak lagi dikontrol di sini (hanya Dashboard) -->
        <FilterRows
          ref="frowsRef"
          :fields="filterFields"
          v-model="applied"
          @clear="clearFilters"
          @apply="filterOpen = false"
        />
        </div>
      </Transition>
    </div>
    <div class="viewswitch" role="group" aria-label="Tampilan daftar">      <button
        type="button"
        aria-label="Tampilan tabel"
        :class="{ on: listPrefs.view === 'tabel' }"
        :aria-pressed="listPrefs.view === 'tabel'"
        @click="listPrefs.view = 'tabel'"
      >
        <Table :size="14" :stroke-width="2" />
        <span class="btext">Tabel</span>
      </button>
      <button
        type="button"
        aria-label="Tampilan kanban"
        :class="{ on: listPrefs.view === 'kanban' }"
        :aria-pressed="listPrefs.view === 'kanban'"
        @click="listPrefs.view = 'kanban'"
      >
        <Kanban :size="14" :stroke-width="2" />
        <span class="btext">Kanban</span>
      </button>
    </div>
  </div>

  <!-- FU72: chip filter tahap aktif (satu-shot dari Dashboard atau satu
       tahap terpilih); FU109: company bukan chip/filter halaman ini (kontrolnya
       hanya di Dashboard) -->
  <div v-if="stageChipKey" class="filterchips">
    <button type="button" class="chip chip-filter" @click="removeStageChip">
      Tahap: {{ stageChipLabel }}
      <X :size="12" :stroke-width="2.2" />
    </button>
  </div>

  <template v-if="listPrefs.view === 'kanban'">
    <WorkOrderKanban :list="pagedFiltered" />
    <div class="pagination-bar pagination-footer kanban-pagination">
      <label class="page-size-control">
        <span>Tampilkan</span>
        <select class="select" :value="pageSize" aria-label="Jumlah Work Order Kanban per halaman" @change="setPageSize($event.target.value)">
          <option v-for="size in PAGE_SIZE_OPTIONS" :key="size" :value="size">{{ size }}</option>
        </select>
      </label>
    </div>
  </template>

  <div class="wo-body" v-else>
    <div class="wo-thead" v-if="pagedFiltered.length">
      <button type="button" class="th-sort" :class="{ on: sortKey === 'wo', asc: sortDir === 'asc' }" @click="setSort('wo')">
        No. WO<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <button type="button" class="th-sort" :class="{ on: sortKey === 'adonan', asc: sortDir === 'asc' }" @click="setSort('adonan')">
        Adonan ke<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <button type="button" class="th-sort" :class="{ on: sortKey === 'produk', asc: sortDir === 'asc' }" @click="setSort('produk')" title="Urut kode produk">
        Produk<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <button type="button" class="th-sort" :class="{ on: sortKey === 'jadwal', asc: sortDir === 'asc' }" @click="setSort('jadwal')">
        Jadwal<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <button type="button" class="th-sort" :class="{ on: sortKey === 'status', asc: sortDir === 'asc' }" @click="setSort('status')">
        Status<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <span>Tahap Aktif</span>
      <span>Gudang</span>
      <button type="button" class="th-sort kanan" :class="{ on: sortKey === 'rencana', asc: sortDir === 'asc' }" @click="setSort('rencana')">
        Rencana<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <span></span>
    </div>

    <button
      v-for="w in pagedFiltered"
      :key="w.id"
      class="wo-row"
      @click="open(w.id)"
    >
      <span class="wo-id c-id">{{ w.id }}</span>
      <span class="c-adonan"><span class="mlabel">Adonan ke</span> {{ w.persiapan.adonanKe ?? '-' }}</span>
      <span class="wo-prod c-prod">
        {{ w.product }}
        <small class="mono">{{ w.itemCode }}</small>
      </span>
      <span class="c-date">{{ fmtDate(w.plannedDate) }}</span>
      <span class="c-status"><span class="badge" :class="statusClass(w.status)">{{ w.status }}</span></span>
      <span class="c-stage"><span class="chip">{{ stageLabel(w) }}</span></span>
      <span class="c-gudang">
        <span v-if="w.handover" class="chip-gudang" :class="w.handover">{{ HANDOVER_LABELS[w.handover] }}</span>
      </span>
      <span class="wo-qty c-qty">
        <span class="qmain">{{ qtyStack(w.plannedStockQty, w).main }}</span>
        <span class="qsub">{{ qtyStack(w.plannedStockQty, w).sub }}</span>
      </span>
      <span class="c-arrow"><ChevronRight :size="16" :stroke-width="2" /></span>
    </button>

    <div v-if="!pagedFiltered.length" class="empty-inset">
      <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
      <p class="etitle">Tidak ada perintah kerja</p>
      <p class="ehint">Tidak ada Work Order untuk filter saat ini. Ubah filter atau kata pencarian.</p>
    </div>
    <div class="pagination-bar pagination-footer">
      <label class="page-size-control">
        <span>Tampilkan</span>
        <select class="select" :value="pageSize" aria-label="Jumlah Work Order per halaman" @change="setPageSize($event.target.value)">
          <option v-for="size in PAGE_SIZE_OPTIONS" :key="size" :value="size">{{ size }}</option>
        </select>
      </label>
      <div class="pagination-buttons">
        <button class="btn btn-sm" :disabled="currentPage <= 1" @click="goPage(currentPage - 1)">‹ Sebelumnya</button>
        <button class="btn btn-sm" :disabled="currentPage >= totalPages" @click="goPage(currentPage + 1)">Berikutnya ›</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { listPreferencesState, loadList, listPrefs, listState, normalizePageSize, PAGE_SIZE_OPTIONS, saveListPreferences, savedListPreferences, STAGE_LABELS, workOrders } from './store.js'
import { fmtDate, qtyStack } from './format.js'
import { Search, Filter, ChevronRight, SearchX, Table, Kanban } from 'lucide-vue-next'
import WorkOrderKanban from './WorkOrderKanban.vue'

const q = ref('')
const fProduct = ref('all')
const fStatus = ref('all')
const fStage = ref('all')
const fFrom = ref('')
const fTo = ref('')
const pageSize = computed(() => listState.pageSize)
const filterOpen = ref(false)
let reloadTimer

const products = computed(() => [...new Map(workOrders.map((w) => [w.itemCode, w.product]))].sort((a, b) => a[1].localeCompare(b[1])))
function normalizeProduct(value) {
  if (!value || value === 'all') return 'all'
  if (products.value.some(([code]) => code === value)) return value
  return products.value.find(([, name]) => name === value)?.[0] || 'all'
}
const todayLabel = new Date().toLocaleDateString('id-ID', {
  weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
})
const totalPages = computed(() => Math.max(1, Math.ceil(listState.total / pageSize.value)))
const currentPage = computed(() => listState.page)
const activeFilters = computed(() =>
  (fProduct.value !== 'all') + (fStatus.value !== 'all') + (fStage.value !== 'all') +
  (fFrom.value ? 1 : 0) + (fTo.value ? 1 : 0)
)

function selectedProductCode() {
  return normalizeProduct(fProduct.value)
}
function filterPayload() {
  return {
    search: q.value.trim(), productionItem: selectedProductCode() === 'all' ? '' : selectedProductCode(),
    status: fStatus.value === 'all' ? '' : fStatus.value,
    stage: fStage.value === 'all' ? '' : (fStage.value === 'done' ? 'selesai' : fStage.value),
      startDate: fFrom.value, endDate: fTo.value, start: 0, pageLen: pageSize.value
  }
}
async function reload() {
  listState.page = 1
  await loadList(filterPayload())
  await saveListPreferences({
    workOrder: { q: q.value, product: fProduct.value, status: fStatus.value, stage: fStage.value, from: fFrom.value, to: fTo.value, pageSize: pageSize.value },
    handover: savedListPreferences.handover || {}
  })
}
function setPageSize(value) {
  listState.pageSize = normalizePageSize(value)
  reload()
}
function scheduleReload() {
  clearTimeout(reloadTimer)
  reloadTimer = setTimeout(reload, 180)
}
function clearFilters() {
  q.value = ''; fProduct.value = 'all'; fStatus.value = 'all'; fStage.value = 'all'; fFrom.value = ''; fTo.value = ''
  filterOpen.value = false
  reload()
}
function allDates() { fFrom.value = ''; fTo.value = ''; scheduleReload() }
function todayISO() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function today() { fFrom.value = todayISO(); fTo.value = todayISO(); scheduleReload() }
function goPage(page) { listState.page = page; loadList({ ...filterPayload(), start: (page - 1) * pageSize.value, pageLen: pageSize.value }) }
const filtered = computed(() => workOrders
    .filter(w => selectedProductCode() === 'all' || w.itemCode === selectedProductCode())
  .filter(w => fStatus.value === 'all' || w.status === fStatus.value)
  .filter(w => fStage.value === 'all' || (fStage.value === 'done' ? w.stage === 'completed' : w.stage === fStage.value))
  .filter(w => !fFrom.value || w.plannedDate >= fFrom.value)
  .filter(w => !fTo.value || w.plannedDate <= fTo.value)
  .filter(w => { const t = q.value.trim().toLowerCase(); return !t || w.id.toLowerCase().includes(t) || w.product.toLowerCase().includes(t) || w.itemCode.toLowerCase().includes(t) }))
const pagedFiltered = computed(() => filtered.value)
watch([q, fProduct, fStatus, fStage, fFrom, fTo], () => { listState.page = 1; scheduleReload() })
onMounted(() => {
  const apply = () => {
    const p = savedListPreferences.workOrder || {}
    q.value = p.q || ''; fProduct.value = normalizeProduct(p.product); fStatus.value = p.status || 'all'; fStage.value = p.stage || 'all'; fFrom.value = p.from || ''; fTo.value = p.to || ''
    listState.pageSize = normalizePageSize(p.pageSize)
    reload()
  }
  if (listPreferencesState.loaded) apply()
  else {
    const timer = setInterval(() => { if (listPreferencesState.loaded) { clearInterval(timer); apply() } }, 25)
    setTimeout(() => clearInterval(timer), 2000)
  }
})
function open(id) { window.location.hash = '#/wo/' + id }
function statusClass(s) { return s === 'Draft' ? 'b-draft' : s === 'Completed' ? 'b-done' : 'b-run' }
function stageLabel(w) { return w.stage === 'completed' ? 'Selesai' : STAGE_LABELS[w.stage] }
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
        <div class="ffield">
          <label>Produk</label>
          <select v-model="fProduct" class="select">
            <option value="all">Semua produk</option>
            <option v-for="([code, name]) in products" :key="code" :value="code">{{ name }}</option>
          </select>
        </div>
        <div class="ffield">
          <label>Status</label>
          <select v-model="fStatus" class="select">
            <option value="all">Semua status</option>
            <option value="Draft">Draft</option>
            <option value="In Process">In Process</option>
            <option value="Completed">Completed</option>
          </select>
        </div>
          <div class="ffield">
            <label>Tahap</label>
            <select v-model="fStage" class="select">
              <option value="all">Semua tahap</option>
              <option value="persiapan">Persiapan</option>
              <option value="material">Material</option>
              <option value="operasi">Operasi</option>
              <option value="prepacking">Pre-Packing</option>
              <option value="postpacking">Post-Packing</option>
              <option value="finish">Finish</option>
              <option value="done">Selesai</option>
            </select>
          </div>
        <div class="frow2">
          <div class="ffield">
            <label>Jadwal dari</label>
            <input v-model="fFrom" class="input" type="date" />
          </div>
          <div class="ffield">
            <label>Jadwal s.d.</label>
            <input v-model="fTo" class="input" type="date" />
          </div>
        </div>
        <div class="frow2 filter-actions">
          <button class="linkbtn" type="button" @click="today">Hari ini</button>
          <button class="linkbtn" type="button" @click="allDates">Semua tanggal</button>
        </div>
        <button class="linkbtn filter-clear" type="button" @click="clearFilters">Hapus semua filter</button>
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
      <span>No. WO</span>
      <span>Adonan ke</span>
      <span>Produk</span>
      <span>Jadwal</span>
      <span>Status</span>
      <span>Tahap Aktif</span>
      <span style="text-align: right">Rencana</span>
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
      <span class="wo-qty c-qty">
        <span class="qmain">{{ qtyStack(w.plannedStockQty, w).main }}</span>
        <span class="qsub">{{ qtyStack(w.plannedStockQty, w).sub }}</span>
      </span>
      <span class="c-arrow"><ChevronRight :size="16" :stroke-width="2" /></span>
    </button>

    <div v-if="!pagedFiltered.length" class="empty-inset">
      <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
      <p class="etitle">Tidak ada perintah kerja</p>
      <p class="ehint">Tidak ada Work Order untuk filter saat ini. Pilih Semua tanggal atau ubah filter.</p>
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

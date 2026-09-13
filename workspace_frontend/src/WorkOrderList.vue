<script setup>
import { computed, ref } from 'vue'
import { workOrders, STAGE_LABELS, listPrefs } from './store.js'
import { fmtDate, qtyStack } from './format.js'
import { Search, Filter, ChevronRight, SearchX, Table, Kanban } from 'lucide-vue-next'
import WorkOrderKanban from './WorkOrderKanban.vue'

const q = ref('')
const fProduct = ref('all')
const fStatus = ref('all')
const fStage = ref('all')
const fFrom = ref('')
const fTo = ref('')
const filterOpen = ref(false)

const products = computed(() => [...new Set(workOrders.map((w) => w.product))])
const today = new Date().toLocaleDateString('id-ID', {
  weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
})

const activeFilters = computed(() =>
  (fProduct.value !== 'all') +
  (fStatus.value !== 'all') +
  (fStage.value !== 'all') +
  (fFrom.value ? 1 : 0) +
  (fTo.value ? 1 : 0)
)

function clearFilters() {
  fProduct.value = 'all'
  fStatus.value = 'all'
  fStage.value = 'all'
  fFrom.value = ''
  fTo.value = ''
}

const filtered = computed(() =>
  workOrders
    .filter((w) => fProduct.value === 'all' || w.product === fProduct.value)
    .filter((w) => fStatus.value === 'all' || w.status === fStatus.value)
    .filter((w) =>
      fStage.value === 'all' ||
      (fStage.value === 'done' ? w.stage === 'completed' : w.stage === fStage.value)
    )
    .filter((w) => (!fFrom.value || w.plannedDate >= fFrom.value))
    .filter((w) => (!fTo.value || w.plannedDate <= fTo.value))
    .filter((w) => {
      const t = q.value.trim().toLowerCase()
      if (!t) return true
      return (
        w.id.toLowerCase().includes(t) ||
        w.product.toLowerCase().includes(t) ||
        w.itemCode.toLowerCase().includes(t)
      )
    })
)

function open(id) {
  window.location.hash = '#/wo/' + id
}

function statusClass(s) {
  return s === 'Draft' ? 'b-draft' : s === 'Completed' ? 'b-done' : 'b-run'
}

function stageLabel(w) {
  return w.stage === 'completed' ? 'Selesai' : STAGE_LABELS[w.stage]
}
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Work Order</h1>
      <p class="sub">Siapkan material, jalankan produksi, dan catat hasil dalam satu alur.</p>
    </div>
    <div class="ph-date">{{ today }}</div>
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
            <option v-for="p in products" :key="p" :value="p">{{ p }}</option>
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
        <button class="linkbtn" @click="clearFilters">Hapus semua filter</button>
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

  <WorkOrderKanban v-if="listPrefs.view === 'kanban'" :list="filtered" />

  <div class="wo-body" v-else>
    <div class="wo-thead" v-if="filtered.length">
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
      v-for="w in filtered"
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
      <span class="c-date">{{ fmtDate(w.plannedDate, true) }}</span>
      <span class="c-status"><span class="badge" :class="statusClass(w.status)">{{ w.status }}</span></span>
      <span class="c-stage"><span class="chip">{{ stageLabel(w) }}</span></span>
      <span class="wo-qty c-qty">
        <span class="qmain">{{ qtyStack(w.plannedStockQty, w).main }}</span>
        <span class="qsub">{{ qtyStack(w.plannedStockQty, w).sub }}</span>
      </span>
      <span class="c-arrow"><ChevronRight :size="16" :stroke-width="2" /></span>
    </button>

    <div v-if="!filtered.length" class="empty-inset">
      <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
      <p class="etitle">Tidak ada perintah kerja</p>
      <p class="ehint">Coba ubah kata kunci pencarian atau hapus filter aktif.</p>
    </div>
  </div>
</template>

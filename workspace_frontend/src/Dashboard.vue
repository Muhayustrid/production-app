<script setup>
// FU72: Dashboard "Hari Ini" — ringkasan atas ke bawah: head + company,
// ringkasan 3 angka, papan 7 tahap, panel serah terima/form order, tabel WO.
import { computed, onMounted, ref } from 'vue'
import { ChevronRight, SearchX } from 'lucide-vue-next'
import { dashboardState, handoverBoard, loadDashboard, pendingStageFilter, STAGE_LABELS } from './store.js'
import { fmtId } from './format.js'
import { STAGES, outputTotalsText, woQtyText } from './dashboard.js'

const summary = computed(() => dashboardState.summary)
const company = ref('')
const companies = computed(() => summary.value?.companies || [])
const showCompany = computed(() => companies.value.length > 1)

const dateLabel = computed(() => {
  const iso = summary.value?.today
  const d = iso ? new Date(iso + 'T00:00:00') : new Date() // server-otoritatif bila ada
  return d.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
})
const outputText = computed(() => outputTotalsText(summary.value?.output_today))
const adonanText = computed(() => {
  const a = summary.value?.adonan_terakhir
  return a ? fmtId(a) : '-'
})
const stageList = computed(() => STAGES.map((s) => ({ ...s, count: Number(summary.value?.stages?.[s.key]) || 0 })))
// tabel hari ini dibatasi 20 baris server; bila total lebih besar, tawarkan
// daftar lengkap — angka ringkasan dan isi tabel tidak saling menyangkal
const rowsTruncated = computed(() => (dashboardState.total || 0) > dashboardState.rows.length)

// pola App.vue: panel Form Order hanya produksi/manager; gudang-only tetap
// melihat panel serah terima. Guard otoritatif tetap di server.
const canFormOrder = computed(() =>
  !!(handoverBoard.roles.is_produksi || handoverBoard.roles.is_manajer_produksi)
)

function reload() { loadDashboard(company.value) }
function onCompany() { reload() }
// klik kartu tahap membawa konteks dashboard ke daftar WO (review FU72):
// company terpilih, dan kartu "Selesai hari ini" dibatasi tanggal server
function openStage(stage) {
  pendingStageFilter.stage = stage.key
  pendingStageFilter.company = company.value
  if (stage.key === 'selesai_hari_ini') {
    pendingStageFilter.from = summary.value?.today || ''
    pendingStageFilter.to = pendingStageFilter.from
  }
  window.location.hash = '#/wo'
}
// tabel hari ini terpotong 20 baris — satu-shot "WO hari ini" tanpa tahap
function openAllToday() {
  pendingStageFilter.stage = ''
  pendingStageFilter.company = company.value
  pendingStageFilter.from = summary.value?.today || ''
  pendingStageFilter.to = pendingStageFilter.from
  window.location.hash = '#/wo'
}
function open(id) { window.location.hash = '#/wo/' + id }
function stageLabel(w) { return w.stage === 'completed' ? 'Selesai' : STAGE_LABELS[w.stage] }
onMounted(reload)
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Dashboard</h1>
      <p class="sub">Ringkasan produksi hari ini.</p>
    </div>
    <div class="ph-right">
      <select
        v-if="showCompany"
        v-model="company"
        class="select ph-select"
        aria-label="Filter company"
        @change="onCompany"
      >
        <option value="">Semua company</option>
        <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
      </select>
      <div class="ph-date">{{ dateLabel }}</div>
    </div>
  </div>

  <div v-if="dashboardState.error" class="callout bad dash-error" role="alert">
    <p>Gagal memuat, coba lagi</p>
    <button class="btn" type="button" @click="reload">Coba lagi</button>
  </div>

  <template v-else>
    <section class="panel dash-summary" aria-label="Ringkasan hari ini">
      <div class="dash-stat">
        <span class="k">WO direncanakan</span>
        <span class="v">{{ fmtId(summary?.wo_planned_today ?? 0) }}</span>
      </div>
      <div class="dash-stat">
        <span class="k">Hasil produksi hari ini</span>
        <span class="v">{{ outputText }}</span>
        <span class="s">produk jadi</span>
      </div>
      <div class="dash-stat">
        <span class="k">Adonan terakhir</span>
        <span class="v">{{ adonanText }}</span>
      </div>
    </section>

    <section class="dash-stages" aria-label="Tahap berjalan">
      <button
        v-for="s in stageList"
        :key="s.key"
        type="button"
        class="dash-stage"
        :class="{ on: s.count > 0 }"
        @click="openStage(s)"
      >
        <span class="n">{{ s.count }}</span>
        <span class="l">{{ s.label }}</span>
      </button>
    </section>

    <section class="dash-panels" aria-label="Serah terima dan form order">
      <div class="panel dash-panel">
        <div class="panel-body dash-panel-body">
          <span class="k">Serah terima menunggu</span>
          <span class="v">{{ fmtId(summary?.handover_menunggu ?? 0) }}</span>
        </div>
        <div class="panel-foot">
          <a class="btn btn-primary" href="#/handover">Buka papan serah terima</a>
        </div>
      </div>
      <div v-if="canFormOrder" class="panel dash-panel">
        <div class="panel-body dash-panel-body">
          <span class="k">Form order menunggu</span>
          <span class="v">{{ fmtId(summary?.form_order_menunggu ?? 0) }}</span>
        </div>
        <div class="panel-foot">
          <a class="btn btn-primary" href="#/form-order">Buka form order</a>
        </div>
      </div>
    </section>

    <section aria-label="Work Order hari ini">
      <h2 class="dash-sec-title">Work Order hari ini</h2>
      <div class="wo-body dash-wo">
        <div class="wo-thead" v-if="dashboardState.rows.length">
          <span>WO</span>
          <span>Produk</span>
          <span>Tahap</span>
          <span class="num">Rencana</span>
          <span class="num">Hasil</span>
          <span></span>
        </div>

        <button
          v-for="w in dashboardState.rows"
          :key="w.id"
          type="button"
          class="wo-row"
          @click="open(w.id)"
        >
          <span class="wo-id c-id">{{ w.id }}</span>
          <span class="wo-prod c-prod">
            {{ w.product }}
            <small class="mono">{{ w.itemCode }}</small>
          </span>
          <span class="c-stage"><span class="chip">{{ stageLabel(w) }}</span></span>
          <span class="wo-qty c-plan">
            <span class="qmain">{{ woQtyText(w.plannedStockQty, w).main }}</span>
            <span class="qsub">{{ woQtyText(w.plannedStockQty, w).sub }}</span>
          </span>
          <span class="wo-qty c-hasil">
            <span class="qmain">{{ woQtyText(w.producedStockQty, w).main }}</span>
            <span class="qsub">{{ woQtyText(w.producedStockQty, w).sub }}</span>
          </span>
          <span class="c-arrow"><ChevronRight :size="16" :stroke-width="2" /></span>
        </button>

        <div v-if="!dashboardState.rows.length && !dashboardState.loading" class="empty-inset">
          <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
          <p class="etitle">Belum ada WO hari ini</p>
        </div>
      </div>
      <p v-if="rowsTruncated" class="dash-more">
        <button type="button" class="btn" @click="openAllToday">Tampilkan semua WO hari ini</button>
      </p>
    </section>
  </template>
</template>

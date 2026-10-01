<script setup>
// FU73/FU76: Dashboard — rombak tampilan dengan PrimeVue 4 (komponen diimpor
// LOKAL di sini, tidak register global). Urutan layar: head + filter rentang
// + company, ringkasan 3 angka, papan 7 tahap, grid panel "Hasil per produk"
// + "Perlu perhatian", panel "Penggunaan bahan baku" (FU74), tabel WO dalam
// rentang (FU76: preset tanggal server-resolved + kustom). Perilaku klik
// tahap/tabel/seret konteks (pendingStageFilter) tetap seperti FU72.
import { computed, onMounted, ref } from 'vue'
import { ChevronRight, SearchX } from 'lucide-vue-next'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import MeterGroup from 'primevue/metergroup'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import Tag from 'primevue/tag'
import { dashboardState, loadDashboard, pendingStageFilter, STAGE_LABELS } from './store.js'
import { fmtId } from './format.js'
import {
  STAGES, YIELD_LEGEND, RANGE_PRESETS, attentionText, bahanHref, materialRowText, materialSummaryText,
  outputTotalsText, variancePctText, woQtyText, yieldPctText, yieldSegments,
  rangeParams, rangeLabel, selesaiTileLabel
} from './dashboard.js'

const summary = computed(() => dashboardState.summary)
// "Semua company" pakai sentinel ALL, bukan '' — PrimeVue Select memperlakukan
// modelValue string kosong sebagai "tidak ada pilihan" (label tampil kosong,
// status "No selected item"); '' hanya dipakai saat memanggil API.
const company = ref('ALL')
const companies = computed(() => summary.value?.companies || [])
const showCompany = computed(() => companies.value.length > 1)
const companyOptions = computed(() => [
  { label: 'Semua company', value: 'ALL' },
  ...companies.value.map((c) => ({ label: c, value: c }))
])
const companyParam = () => (company.value === 'ALL' ? '' : company.value)

// FU76: filter rentang — preset di-resolve server; kustom memakai 2 input
// tanggal dan reload menunggu isian valid (dari≤sampai, ≤366 hari)
const preset = ref('hari_ini')
const customDari = ref('')
const customSampai = ref('')
const rangeOptions = RANGE_PRESETS
const rangeInvalid = computed(() =>
  preset.value === 'kustom' && customDari.value && customSampai.value &&
  customDari.value > customSampai.value
)
const rangeTooLong = computed(() => {
  if (preset.value !== 'kustom' || !customDari.value || !customSampai.value) return false
  const span = (new Date(customSampai.value) - new Date(customDari.value)) / 86400000
  return span > 366
})
const rangeReady = computed(() =>
  preset.value !== 'kustom' ||
  (customDari.value && customSampai.value && !rangeInvalid.value && !rangeTooLong.value)
)

const dateLabel = computed(() =>
  rangeLabel(summary.value?.preset, summary.value?.dari, summary.value?.sampai)
)
const outputText = computed(() => outputTotalsText(summary.value?.output_today))
const adonanText = computed(() => {
  const a = summary.value?.adonan_terakhir
  return a ? fmtId(a) : '-'
})
const stageList = computed(() => STAGES.map((s) => ({
  ...s,
  count: Number(summary.value?.stages?.[s.key]) || 0,
  // tile terakhir ikut rentang terpilih (server); label dinamis
  label: s.key === 'selesai_hari_ini'
    ? selesaiTileLabel(summary.value?.preset)
    : s.label
})))
// judul tabel & tombol "tampilkan semua" mengikuti rentang
const rangeScoped = computed(() => summary.value?.preset && summary.value.preset !== 'hari_ini')
const tableTitle = computed(() => (rangeScoped.value ? 'Work Order dalam rentang' : 'Work Order hari ini'))
const showAllLabel = computed(() => (rangeScoped.value ? 'Tampilkan semua WO dalam rentang' : 'Tampilkan semua WO hari ini'))
// tabel hari ini dibatasi 20 baris server; bila total lebih besar, tawarkan
// daftar lengkap — angka ringkasan dan isi tabel tidak saling menyangkal
const rowsTruncated = computed(() => (dashboardState.total || 0) > dashboardState.rows.length)

// FU73: dua panel baru — kontrak summary.product_yield / summary.attention
const productYield = computed(() => summary.value?.product_yield || [])
const attentionRows = computed(() =>
  (summary.value?.attention || []).map((item) => ({
    ...attentionText(item),
    link: item.link || '#',
    bad: item.severity !== 'warn'
  }))
)

// FU74: panel penggunaan bahan baku — null = user tanpa izin Stock Entry,
// panel disembunyikan seluruhnya (jujur terhadap izin, bukan pesan error)
const mu = computed(() => summary.value?.material_usage || null)
const muRows = computed(() => (Array.isArray(mu.value?.rows) ? mu.value.rows : []))
const muUsed = computed(() => muRows.value.some((r) => (Number(r?.consumed) || 0) > 0))
// over sudah urut terburuk dari server (variance_pct null paling atas)
const muOver = computed(() => muRows.value.filter((r) => !!r?.over))
const muOverExtra = computed(() => Math.max(0, muOver.value.length - 3))

function reload() {
  if (!rangeReady.value) return // kustom belum lengkap/valid — hint tampil
  loadDashboard(companyParam(), rangeParams(preset.value, customDari.value, customSampai.value))
}
function onCompany() { reload() }
function onPreset() {
  // kustom menunggu kedua tanggal terisi (watch di bawah yang memuat);
  // preset lain langsung memuat ulang
  if (preset.value === 'kustom' && !(customDari.value && customSampai.value)) return
  reload()
}
// FU76: isian tanggal kustom memuat saat lengkap & valid
function onCustomDate() { if (preset.value === 'kustom') reload() }
// klik kartu tahap membawa konteks dashboard ke daftar WO (review FU72):
// company terpilih, dan kartu "Selesai" dibatasi rentang resolved server
function openStage(stage) {
  pendingStageFilter.stage = stage.key
  pendingStageFilter.company = companyParam()
  if (stage.key === 'selesai_hari_ini') {
    pendingStageFilter.from = summary.value?.dari || summary.value?.today || ''
    pendingStageFilter.to = summary.value?.sampai || pendingStageFilter.from
  }
  window.location.hash = '#/wo'
}
// tabel terpotong 20 baris — satu-shot seluruh WO rentang tanpa tahap
function openAllToday() {
  pendingStageFilter.stage = ''
  pendingStageFilter.company = companyParam()
  pendingStageFilter.from = summary.value?.dari || summary.value?.today || ''
  pendingStageFilter.to = summary.value?.sampai || pendingStageFilter.from
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
      <p class="sub">Ringkasan produksi.</p>
    </div>
    <div class="ph-right">
      <Select
        v-model="preset"
        :options="rangeOptions"
        optionLabel="label"
        optionValue="key"
        inputId="dash-range"
        aria-label="Filter rentang tanggal"
        class="ph-pselect"
        @change="onPreset"
      />
      <Select
        v-if="showCompany"
        v-model="company"
        :options="companyOptions"
        optionLabel="label"
        optionValue="value"
        inputId="dash-company"
        aria-label="Filter company"
        class="ph-pselect"
        @change="onCompany"
      />
      <div class="ph-date">{{ dateLabel }}</div>
    </div>
  </div>

  <div v-if="preset === 'kustom'" class="dash-custom-range">
    <div class="ffield">
      <label for="dash-dari">Dari</label>
      <input id="dash-dari" v-model="customDari" class="input" type="date" @change="onCustomDate" />
    </div>
    <div class="ffield">
      <label for="dash-sampai">s.d.</label>
      <input id="dash-sampai" v-model="customSampai" class="input" type="date" @change="onCustomDate" />
    </div>
    <p v-if="rangeInvalid" class="dash-range-hint" role="status">
      Tanggal tidak valid: "dari" melebihi "sampai".
    </p>
    <p v-else-if="rangeTooLong" class="dash-range-hint" role="status">
      Rentang maksimal 366 hari.
    </p>
    <p v-else-if="!(customDari && customSampai)" class="dash-range-hint" role="status">
      Pilih tanggal awal dan akhir untuk memuat data.
    </p>
  </div>

  <div v-if="dashboardState.error" class="callout bad dash-error" role="alert">
    <p>Gagal memuat, coba lagi</p>
    <Button label="Coba lagi" size="small" severity="secondary" variant="outlined" @click="reload" />
  </div>

  <template v-else-if="dashboardState.loading">
    <Skeleton class="dash-skel-strip" height="76px" borderRadius="8px" aria-hidden="true" />
    <div class="dash-grid">
      <section v-for="n in 2" :key="n" class="panel dash-card" aria-hidden="true">
        <div class="panel-body dash-skel-stack">
          <Skeleton width="45%" height="14px" borderRadius="4px" />
          <Skeleton v-for="m in 4" :key="m" width="100%" height="14px" borderRadius="4px" />
        </div>
      </section>
    </div>
    <section class="panel" aria-hidden="true">
      <div class="panel-body dash-skel-stack">
        <Skeleton v-for="m in 4" :key="m" width="100%" height="34px" borderRadius="6px" />
      </div>
    </section>
  </template>

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

    <div class="dash-grid">
      <section class="panel dash-card" aria-label="Hasil per produk">
        <div class="panel-head">
          <div>
            <h2>Hasil per produk</h2>
            <p class="lead">% hasil bagus vs rencana WO</p>
          </div>
        </div>
        <div class="panel-body">
          <!-- legend TERBACA screen reader: label-list bawaan MeterGroup
             disembunyikan visual (display:none) — satu-satunya sumber makna
             rincian bar bagi pembaca layar (review FU73 #3) -->
          <div class="dash-legend">
            <span v-for="m in YIELD_LEGEND" :key="m.key" class="dash-leg">
              <i class="dot" :style="{ background: m.color }"></i>{{ m.label }}
            </span>
          </div>
          <ul v-if="productYield.length" class="dash-yield">
            <li v-for="row in productYield" :key="row.item_code" class="dash-yield-row">
              <span class="yname">{{ row.item_name }}</span>
              <MeterGroup class="dash-meter" :value="yieldSegments(row).segments" :max="yieldSegments(row).max" />
              <span class="ypct" :class="{ over: row.over }">{{ yieldPctText(row.yield_pct) }}</span>
            </li>
          </ul>
          <p v-else class="dash-none">Belum ada hasil post-packing hari ini</p>
          <p class="dash-foot">Hanya WO dengan post-packing terkonfirmasi dalam rentang terpilih. Yield bisa di atas 100% (overproduksi ERPNext).</p>
        </div>
      </section>

      <section class="panel dash-card" aria-label="Perlu perhatian">
        <div class="panel-head">
          <div>
            <h2>Perlu perhatian</h2>
            <p class="lead">{{ attentionRows.length }} item</p>
          </div>
        </div>
        <div class="panel-body">
          <ul v-if="attentionRows.length" class="dash-att">
            <li v-for="(a, i) in attentionRows" :key="i">
              <a :href="a.link" class="dash-att-item">
                <i class="dot" :class="a.bad ? 'bad' : 'warn'" aria-hidden="true"></i>
                <span class="txt">
                  <span class="ttl">{{ a.title }}</span>
                  <span v-if="a.detail" class="dtl">{{ a.detail }}</span>
                </span>
              </a>
            </li>
          </ul>
          <p v-else class="dash-none">Tidak ada yang perlu perhatian</p>
        </div>
      </section>
    </div>

    <!-- FU74: penggunaan bahan baku hari ini — panel lebar penuh, ringkas -->
    <section v-if="mu" class="panel dash-mu" aria-label="Penggunaan bahan baku">
      <div class="panel-head">
        <div>
          <h2>Penggunaan bahan baku</h2>
          <p v-if="muUsed" class="lead">{{ materialSummaryText(mu) }}</p>
        </div>
        <a href="#/bahan" class="dash-mu-link">Lihat semua</a>
      </div>
      <div class="panel-body">
        <div v-if="muUsed" class="dash-mu-rows">
          <template v-if="muOver.length">
            <a
              v-for="row in muOver.slice(0, 3)"
              :key="row.item_code"
              class="dash-mu-row"
              :href="bahanHref(row.item_code)"
            >
              <span class="mtxt">
                <span class="ttl">{{ row.item_name }}<small v-if="row.item_code">{{ row.item_code }}</small></span>
                <span class="dtl">{{ materialRowText(row) }}</span>
              </span>
              <!-- pct null = tanpa dasar — jangan pill merah kosong (review FU74 #3) -->
              <Tag :value="variancePctText(row) || 'tanpa dasar'" severity="danger" class="bahan-tag over" />
            </a>
            <a v-if="muOverExtra" href="#/bahan" class="dash-mu-extra">
              +{{ muOverExtra }} lainnya · buka halaman bahan baku
            </a>
          </template>
          <p v-else class="dash-none">Semua pemakaian sesuai rencana (ambang 5%)</p>
        </div>
        <div v-else class="empty-inset dash-mu-empty">
          <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
          <p class="etitle">Belum ada pemakaian bahan hari ini</p>
        </div>
      </div>
    </section>

    <section aria-label="Work Order hari ini">
      <h2 class="dash-sec-title">{{ tableTitle }}</h2>
      <div class="panel dash-tablewrap">
        <DataTable :value="dashboardState.rows" dataKey="id" class="dash-table" @row-click="(e) => open(e.data.id)">
          <Column field="id" header="WO" style="width: 150px">
            <template #body="{ data }">
              <button type="button" class="linklike" @click.stop="open(data.id)">{{ data.id }}</button>
            </template>
          </Column>
          <Column field="product" header="Produk">
            <template #body="{ data }">
              <span class="wo-prod">
                {{ data.product }}
                <small v-if="data.itemCode" class="mono">{{ data.itemCode }}</small>
              </span>
            </template>
          </Column>
          <Column field="stage" header="Tahap" style="width: 132px">
            <template #body="{ data }">
              <Tag :value="stageLabel(data)" class="dash-tag" />
            </template>
          </Column>
          <Column header="Rencana" style="width: 150px" headerStyle="text-align: right" bodyStyle="text-align: right">
            <template #body="{ data }">
              <span class="wo-qty">
                <span class="qmain">{{ woQtyText(data.plannedStockQty, data).main }}</span>
                <span v-if="woQtyText(data.plannedStockQty, data).sub" class="qsub">{{ woQtyText(data.plannedStockQty, data).sub }}</span>
              </span>
            </template>
          </Column>
          <Column header="Hasil" style="width: 150px" headerStyle="text-align: right" bodyStyle="text-align: right">
            <template #body="{ data }">
              <span class="wo-qty">
                <span class="qmain">{{ woQtyText(data.producedStockQty, data).main }}</span>
                <span v-if="woQtyText(data.producedStockQty, data).sub" class="qsub">{{ woQtyText(data.producedStockQty, data).sub }}</span>
              </span>
            </template>
          </Column>
          <Column headerStyle="width: 36px; text-align: right" bodyStyle="text-align: right; width: 36px">
            <template #body>
              <ChevronRight :size="16" :stroke-width="2" class="tchev" aria-hidden="true" />
            </template>
          </Column>
          <template #empty>
            <div class="empty-inset">
              <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
              <p class="etitle">{{ rangeScoped ? 'Belum ada WO dalam rentang ini' : 'Belum ada WO hari ini' }}</p>
            </div>
          </template>
        </DataTable>
      </div>
      <p v-if="rowsTruncated" class="dash-more">
        <Button :label="showAllLabel" size="small" severity="secondary" variant="outlined" @click="openAllToday" />
      </p>
    </section>
  </template>
</template>

<script setup>
// FU78: rombak gaya dashboard mengikuti referensi — 4 kartu KPI ber-chip
// ikon, bar chart "rencana vs hasil" + donut tahap (PrimeVue Chart/chart.js),
// tabel antrean dgn progress bar + pill status + target telat, kualitas per
// UOM, perlu perhatian, bahan baku, aktivitas terakhir. Warna dasar app
// dipertahankan (token CSS); semua qty tampil Default Inventory UOM — server
// yang mengonversi dan mematok satu UOM dominan utk chart/KPI (dominant_uom),
// beda UOM tidak pernah dijumlahkan (kualitas dikelompokkan per UOM).
// Perilaku FU72-FU77 dipertahankan: filter rentang preset+kustom (popover),
// company, pagination 10/halaman (FU77), klik tahap → #/wo, klik baris → #/wo.
import { computed, onMounted, ref, watch } from 'vue'
import Chart from 'primevue/chart'
import ProgressBar from 'primevue/progressbar'
import { Activity, Check, ChevronRight, Filter, Gauge, Layers, Package, SearchX, TriangleAlert } from 'lucide-vue-next'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import MeterGroup from 'primevue/metergroup'
import Paginator from 'primevue/paginator'
import Select from 'primevue/select'
import Skeleton from 'primevue/skeleton'
import Tag from 'primevue/tag'
import { companyFilterState, dashboardState, DASH_PAGE_SIZE, loadDashboard, loadDashboardDaily, loadDashboardPage, pendingStageFilter, saveCompanyFilter, STAGE_LABELS } from './store.js'
import { companySelectOptions, showCompanyPicker } from './company-filter.js'
import { countFilters, normalizeFilters } from './filter-rows.js'
import { fmtId } from './format.js'
import {
  STAGES, YIELD_LEGEND, RANGE_PRESETS, DAILY_MODES, achievementPct, activeTotal, activityText,
  activityTime, attentionText, chartDaily, deltaPctText, donutData, isOverdue,
  materialRowText, materialSummaryText, materialUsageHref, qualityPerUom, rangeParams, rangeLabel,
  selesaiTileLabel, targetText, topMaterialRows, uomPrimaryText, variancePctText, woProgressPct,
  woQtyText, yieldPctText, yieldSegments
} from './dashboard.js'
import FilterRows from './FilterRows.vue'

const summary = computed(() => dashboardState.summary)
// FU95: company kini filter GLOBAL (companyFilterState — tersimpan per-user
// di server, dibagi ke semua halaman). "Semua company" pakai sentinel ALL,
// bukan '' — PrimeVue Select memperlakukan modelValue string kosong sebagai
// "tidak ada pilihan" (gotcha FU73). Daftar company: preferensi dulu (termuat
// sebelum summary), fallback daftar dari summary saat endpoint preferensi
// gagal — keduanya sama-sama permission-scoped User Permission.
const companies = computed(() =>
  companyFilterState.companies.length ? companyFilterState.companies : (summary.value?.companies || [])
)
const showCompany = computed(() => showCompanyPicker(companies.value))
// FU107: baris Company (immediate) memakai sentinel '' = "Semua company"
// (native select) — berbeda dari head Select lama yang butuh 'ALL'
const companyRowOptions = computed(() => companySelectOptions(companies.value))
// FU107: setter tunggal company (nilai tetap filter GLOBAL FU95, tersimpan
// per-user di server; '' = Semua company)
async function setCompany(v) {
  const val = v || ''
  if (val === companyFilterState.company) return
  companyFilterState.company = val
  await saveCompanyFilter(val)
  reload()
}
// FU107: nilai baris immediate (bukan draft) — dari state global FU95
const immediateValues = computed(() => ({ company: companyFilterState.company }))
function onImmediate(key, value) {
  if (key === 'company') setCompany(value)
}

// FU102: panel filter ala Work Order (filterbtn + popoverlay + filterpanel +
// FilterRows) — dimensi filter halaman Dashboard tetap SATU: RENTANG. Enam
// preset FU76 dipertahankan sebagai tombol token DI ATAS baris 'Rentang'
// (nilai preset di-resolve server, bukan nilai kolom — bentuknya bukan baris);
// baris 'Rentang' = jalur kustom (first-to 'same' seperti FU79e: pilihan
// pertama = satu hari, langsung layak diterapkan). Perubahan baris = DRAFT;
// parent memicu commitIfChanged saat panel ditutup (komponen hidup di v-if).
// FU107: company kini BARIS pertama di panel (immediate) — head select dihapus.
const preset = ref('hari_ini')
const applied = ref({})
const frowsRef = ref(null)
const frowsKey = ref(0) // remount = draft FilterRows ikut kosong saat preset dipilih
const filterOpen = ref(false)
const rangeOptions = RANGE_PRESETS
const DASH_FILTER_SHAPE = [
  // requireBoth = endpoint kustom wajib dari+sampai; maxSpan = batas server
  // (DASHBOARD_MAX_DAYS 366): nilai tak sah ditahan FilterRows + petunjuk,
  // bukan dikirim ke endpoint lalu ditolak (perilaku lama: Terapkan mati)
  { key: 'rentang', label: 'Rentang', type: 'range', firstTo: 'same', requireBoth: true, maxSpan: 366, placeholder: 'Pilih rentang' }
]
// FU107: fields = baris company (immediate) + baris rentang — key company
// TIDAK masuk DASH_FILTER_SHAPE (nilai immediate tidak pernah jadi draft)
const dashFilterFields = computed(() => [
  ...(showCompany.value
    ? [{
        key: 'company', label: 'Company', type: 'select', immediate: true,
        ariaLabel: 'Filter company',
        options: companyRowOptions.value
      }]
    : []),
  ...DASH_FILTER_SHAPE
])

const rangeRow = computed(() =>
  applied.value.rentang?.dari && applied.value.rentang?.sampai ? applied.value.rentang : null
)
// badge = jumlah baris (+ company) seperti pilot FU100 (rentang lewat preset
// token bukan baris — keaktifannya tampil sebagai label tanggal .ph-date)
const activeFilters = computed(() =>
  countFilters(applied.value) +
  (showCompany.value && companyFilterState.company ? 1 : 0)
)
// payload rentang: baris kustom bila ada, selain itu preset token. Preset
// 'kustom' tanpa baris lengkap tak mungkin tersimpan (onFilters menjaga),
// tapi tetap dijaga di sini agar tak pernah mengirim kustom kosong ke server.
const rangeParamsNow = computed(() => {
  if (rangeRow.value) return rangeParams('kustom', rangeRow.value.dari, rangeRow.value.sampai)
  return rangeParams(preset.value === 'kustom' ? 'hari_ini' : preset.value)
})

// commit baris (Terapkan atau panel ditutup): rentang lengkap → preset kustom;
// baris rentang dibuang (Hapus semua) → kembali ke default hari ini. Preset
// token yang tidak berkaitan dengan baris (mis. bulan_ini) TIDAK diubah commit
// baris kosong — pilihan preset-nya tetap.
function onFilters(value) {
  const next = normalizeFilters(value, DASH_FILTER_SHAPE)
  const same = JSON.stringify(next) === JSON.stringify(applied.value)
  applied.value = next
  if (next.rentang?.dari && next.rentang?.sampai) preset.value = 'kustom'
  else if (preset.value === 'kustom') preset.value = 'hari_ini'
  if (!same) reload()
}
// FU108: "Hapus semua" = bersih TOTAL — baris kustom dikomit kosong oleh
// FilterRows (onFilters mengembalikan preset ke hari_ini bila kustom);
// di sini token preset non-default dikembalikan ke "Hari ini" dan company
// GLOBAL dilepas. Panel tetap terbuka. Halaman ini tidak punya kotak cari.
function onClearDash() {
  preset.value = 'hari_ini'
  if (companyFilterState.company) setCompany('')
  else reload()
}

const dateLabel = computed(() =>
  rangeLabel(summary.value?.preset, summary.value?.dari, summary.value?.sampai)
)
// FU78: satu UOM utama dari server — chart & KPI memakai nilai yang sama
const dominant = computed(() => summary.value?.dominant_uom || null)

// ---- 4 kartu KPI
const plannedKpi = computed(() => uomPrimaryText(summary.value?.planned_qty, dominant.value))
const outputKpi = computed(() => uomPrimaryText(summary.value?.output_today, dominant.value))
const uomQty = (list, uom) =>
  (Array.isArray(list) ? list : []).find((e) => e.uom === uom)?.qty ?? null
// chip "+x% vs kemarin": hanya preset hari ini yang punya window pembanding
// (server mengirim output_prev kosong utk preset lain) — slot tetap di-reserve
const deltaChip = computed(() => {
  if (summary.value?.preset !== 'hari_ini') return ''
  return deltaPctText(uomQty(summary.value?.output_today, dominant.value), uomQty(summary.value?.output_prev, dominant.value))
})
const achievement = computed(() =>
  achievementPct(summary.value?.planned_qty, summary.value?.output_today, dominant.value)
)
const woAktif = computed(() => activeTotal(summary.value?.stages))
const attCount = computed(() => (summary.value?.attention || []).length)

// ---- kartu grafik: filter LOKAL kartu (FU78b, lepas dari rentang halaman) —
// "Minggu ini" berlabel Senin s.d. Minggu, "Bulan ini" berlabel tanggal.
// Server mengirim series PER UOM (krim kopi Pcs vs dough Pack tidak pernah
// dijumlahkan): chart menampilkan satu UOM terpilih, default = dominan
// window versi server; pemilih UOM menyatu dengan caption di kaki chart dan
// hanya tampil bila >1 seri (FU99 — header kartu stabil, pola kontrol di
// tempat satuan diumumkan).
const chartMode = ref('minggu')
const chartUom = ref('')
const daily = computed(() => dashboardState.daily)
const chartSeriesList = computed(() => daily.value?.series || [])
// FU100a: opsi UOM = UOM window; pekan kosong jatuh ke kandidat fallback
// server (`uoms` — UOM bulan berjalan) agar pemilih tetap tampil di KEDUA
// mode, bukan cuma bulan
const chartUomOptions = computed(() => {
  const list = chartSeriesList.value.map((s) => ({ label: s.uom, value: s.uom }))
  if (list.length || !daily.value) return list
  return (daily.value.uoms || []).map((u) => ({ label: u, value: u }))
})
const seri = computed(() => {
  const list = chartSeriesList.value
  if (!list.length) {
    // window tanpa kejadian: seri sintetis nol — caption + pemilih UOM tetap
    // tampil; chart disembunyikan (nyata=false → pesan kosong di tempatnya)
    const uom = chartUom.value || daily.value?.uoms?.[0] || ''
    return uom ? { uom, nyata: false, rows: [] } : null
  }
  const found =
    list.find((s) => s.uom === chartUom.value) ||
    list.find((s) => s.uom === daily.value?.dominant_uom) ||
    list[0]
  return { ...found, nyata: true }
})
// pilihan UOM ganti tidak valid (hasil fetch baru / ganti mode) → dominan /
// kandidat fallback pertama
watch(chartSeriesList, (list) => {
  if (!list.some((s) => s.uom === chartUom.value)) {
    chartUom.value =
      daily.value?.dominant_uom || list[0]?.uom || daily.value?.uoms?.[0] || ''
  }
})
const barData = computed(() => {
  const s = chartDaily(seri.value, chartMode.value)
  return {
    labels: s.labels,
    datasets: [
      { label: 'Rencana', data: s.planned, backgroundColor: '#9bbdd8', borderRadius: 4, maxBarThickness: 24 },
      { label: 'Hasil', data: s.produced, backgroundColor: '#3368a0', borderRadius: 4, maxBarThickness: 24 }
    ]
  }
})
const barOptions = {
  responsive: true, // wrapper .dchart-box tinggi tetap — responsive:false bikin overflow 390
  maintainAspectRatio: false,
  plugins: {
    legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 7, boxHeight: 7, padding: 14 } }
  },
  scales: {
    x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 8 } },
    y: { beginAtZero: true, grid: { color: '#e3e9ee' }, ticks: { maxTicksLimit: 6 } }
  }
}
function pilihChartMode(mode) {
  if (mode === chartMode.value) return
  chartMode.value = mode
  loadDashboardDaily(mode)
}
function retryDaily() {
  loadDashboardDaily(chartMode.value)
}

// ---- kartu donut: distribusi tahap (klik legend = filter #/wo, kontrak FU72)
// label segmen terakhir ikut preset (kontrak FU76: "Selesai dalam rentang")
const donut = computed(() => {
  const d = donutData(summary.value?.stages)
  return {
    ...d,
    segments: d.segments.map((s) =>
      s.key === 'selesai_hari_ini' ? { ...s, label: selesaiTileLabel(summary.value?.preset) } : s
    )
  }
})
const doughnutData = computed(() => ({
  labels: donut.value.segments.map((s) => s.label),
  datasets: [{
    data: donut.value.segments.map((s) => s.value),
    backgroundColor: donut.value.segments.map((s) => s.color),
    borderWidth: 2,
    hoverOffset: 3,
    borderColor: '#ffffff'
  }]
}))
const doughnutOptions = {
  responsive: true,
  maintainAspectRatio: false,
  cutout: '72%',
  plugins: { legend: { display: false } } // legend custom klikabel di samping donut
}
const stageByKey = (key) => STAGES.find((s) => s.key === key) || { key }
// rata-rata yield per produk (tak tertimbang — yield_pct unitless, aman lintas
// UOM); bisa >100 saat overproduksi → bar dibatasi 100, angka apa adanya
const avgYield = computed(() => {
  const rows = summary.value?.product_yield || []
  if (!rows.length) return null
  const n = rows.reduce((t, r) => t + (Number(r.yield_pct) || 0), 0)
  return Math.round((n / rows.length) * 10) / 10
})

// ---- judul tabel mengikuti rentang (kontrak FU76)
const rangeScoped = computed(() => summary.value?.preset && summary.value.preset !== 'hari_ini')
const tableTitle = computed(() => (rangeScoped.value ? 'Work Order dalam rentang' : 'Work Order hari ini'))
const adonanText = computed(() => {
  const a = summary.value?.adonan_terakhir
  return a ? fmtId(a) : ''
})

// FU77: tabel dipaginasi DASH_PAGE_SIZE baris/halaman — lazy via wo_list
const pageSize = DASH_PAGE_SIZE
const dashFirst = ref(0)
function onPage(e) { loadDashboardPage(e.page) }
function retryPage() {
  dashboardState.rowsError = ''
  loadDashboardPage(dashboardState.page)
}
// FU94: sort 3-klik antrean (sortMode custom) — tabel lazy server-paginated,
// klik header menerjemahkan event sort bawaan PrimeVue jadi token order
// wo_list dan kembali ke halaman 1; klik ke-3 (removableSort) = normal.
// CATATAN: JANGAN sortMode="custom" — di mode itu PrimeVue tidak mengisi
// state sort internal sehingga event membawa nilai stale.
const DASH_SORT_TOKENS = { id: 'name', product: 'item', plannedEnd: 'target', plannedStockQty: 'qty', producedStockQty: 'produced' }
function onDashSort(e) {
  const base = DASH_SORT_TOKENS[e.sortField]
  dashboardState.order = base && e.sortOrder ? `${base}_${e.sortOrder === 1 ? 'asc' : 'desc'}` : ''
  dashFirst.value = 0
  loadDashboardPage(0)
}
// telat = target selesai lewat saat data dimuat & WO belum selesai
const loadedAtMs = ref(Date.now())
const overdue = (row) => isOverdue(row, loadedAtMs.value)
// pill status: hijau selesai, amber belum mulai (draft), merah dibatalkan,
// biru proses — warna token app, pola referensi
function pillSeverity(w) {
  if (w.stage === 'completed') return 'success'
  if (w.stage === 'persiapan') return 'warn'
  if (w.stage === 'cancelled') return 'danger'
  return 'info'
}
function stageLabel(w) { return w.stage === 'completed' ? 'Selesai' : STAGE_LABELS[w.stage] }

// ---- panel kualitas & hasil: dijumlahkan PER UOM saja (aturan inti FU78)
const qualityGroups = computed(() => qualityPerUom(summary.value?.product_yield))
const qualityMain = computed(() => qualityGroups.value[0] || null)
const qualityRestText = computed(() =>
  qualityGroups.value.slice(1).map((g) => `${fmtId(g.good)} ${g.uom}`).join(' · ')
)
const mainRejectPct = computed(() => {
  const g = qualityMain.value
  if (!g || !(g.planned > 0)) return null
  return Math.round((g.reject / g.planned) * 1000) / 10
})
const productYield = computed(() => summary.value?.product_yield || [])

// ---- panel perlu perhatian (kontrak FU73 utuh)
const attentionRows = computed(() =>
  (summary.value?.attention || []).map((item) => ({
    ...attentionText(item),
    link: item.link || '#',
    bad: item.severity !== 'warn'
  }))
)

// ---- panel bahan baku: baris teratas by |variance %| (FU78, konversi
// inventory UOM datang dari server; fallback stock UOM apa adanya)
const mu = computed(() => summary.value?.material_usage || null)
const muRows = computed(() => (Array.isArray(mu.value?.rows) ? mu.value.rows : []))
const muUsed = computed(() => muRows.value.some((r) => (Number(r?.consumed) || 0) > 0))
const muTop = computed(() => topMaterialRows(muRows.value, 6))
const muOverCount = computed(() => muRows.value.filter((r) => !!r?.over).length)

// ---- timeline aktivitas (FU78): SE Manufacture + serah terima bahan
const activityRows = computed(() =>
  (summary.value?.recent_activity || []).map((e) => ({
    ...activityText(e),
    ...activityTime(e.ts),
    link: e.link || null
  }))
)

function reload() {
  dashFirst.value = 0 // ganti rentang/company = kembali ke halaman pertama
  loadedAtMs.value = Date.now()
  // FU95: company dibaca store dari companyFilterState (filter global)
  loadDashboard(rangeParamsNow.value)
  // grafik mengikuti company (rentang halaman tidak mempengaruhinya — filter
  // lokal minggu/bulan), dimuat ringan terpisah (pola wo_list FU77)
  loadDashboardDaily(chartMode.value)
}
// FU102: preset token = tombol cepat DI ATAS baris (perilaku FU76: langsung
// terapkan); memilih preset mengosongkan baris rentang kustom. Token 'Kustom'
// membuka baris Rentang (pintunya kini baris FilterRows itu sendiri).
function pickPreset(key) {
  if (key === 'kustom') {
    frowsRef.value?.addRow('rentang')
    return
  }
  applied.value = {}
  preset.value = key
  frowsKey.value++ // draft baris (mis. rentang separuh terisi) ikut direset
  reload()
}
// tutup panel = commit draft baris (commitIfChanged dipicu parent karena
// komponen hidup di v-if dan ter-unmount bersamaan dengan perubahan prop)
watch(filterOpen, (open, sebelum) => {
  if (!open && sebelum) frowsRef.value?.commitIfChanged()
})
// klik kartu tahap/legend membawa konteks dashboard ke daftar WO (FU72);
// FU95: company TIDAK lagi satu-shot — filter #/wo memakai company global
// yang sama (tersimpan), jadi hanya tahap/tanggal yang dioper
function openStage(stage) {
  pendingStageFilter.stage = stage.key
  if (stage.key === 'selesai_hari_ini') {
    pendingStageFilter.from = summary.value?.dari || summary.value?.today || ''
    pendingStageFilter.to = summary.value?.sampai || pendingStageFilter.from
  }
  window.location.hash = '#/wo'
}
function open(id) { window.location.hash = '#/wo/' + id }
onMounted(reload)
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <p class="ph-eye">Data produksi live</p>
      <h1>Dashboard</h1>
      <p class="sub">Ringkasan produksi.</p>
    </div>
    <div class="ph-right">
      <div class="filterwrap">
        <button
          type="button"
          class="btn filterbtn"
          :class="{ active: activeFilters }"
          aria-label="Filter"
          :aria-expanded="filterOpen ? 'true' : 'false'"
          @click="filterOpen = !filterOpen"
        >
          <Filter :size="14" :stroke-width="2" />
          <span class="btext">Filter</span>
          <span v-if="activeFilters" class="filtercount">{{ activeFilters }}</span>
        </button>
        <div v-if="filterOpen" class="popoverlay" @click="filterOpen = false"></div>
        <Transition name="pop">
          <div v-if="filterOpen" class="filterpanel">
            <!-- FU76 dipertahankan: daftar preset (nilai server-resolved, bukan
               bentuk baris) sebagai tombol token DI ATAS baris FilterRows -->
            <div class="ffield">
              <label>Preset rentang</label>
              <div class="dash-rlist" role="listbox" aria-label="Preset rentang tanggal">
                <button
                  v-for="p in rangeOptions"
                  :key="p.key"
                  type="button"
                  class="dash-ropt"
                  :class="{ on: p.key === preset }"
                  :aria-selected="p.key === preset ? 'true' : 'false'"
                  @click="pickPreset(p.key)"
                >
                  <span>{{ p.label }}</span>
                  <Check v-if="p.key === preset" :size="15" :stroke-width="2.2" aria-hidden="true" />
                </button>
              </div>
            </div>
            <!-- FU102: baris filter [Label][Nilai][x] — 'Rentang' = jalur kustom;
               draft dikomit saat Terapkan atau saat panel ditutup. FU107:
               Company kini baris pertama (immediate — nilai tetap global FU95). -->
            <FilterRows
              ref="frowsRef"
              :key="frowsKey"
              :fields="dashFilterFields"
              :auto-add="false"
              :immediate="immediateValues"
              :model-value="applied"
              @update:model-value="onFilters"
              @immediate-change="onImmediate"
              @clear="onClearDash"
            />
          </div>
        </Transition>
      </div>
      <!-- FU107: select company page-head dipindah ke baris 'Company' panel -->
      <div class="ph-date">{{ dateLabel }}</div>
    </div>
  </div>

  <div v-if="dashboardState.error" class="callout bad dash-error" role="alert">
    <p>Gagal memuat, coba lagi</p>
    <Button label="Coba lagi" size="small" severity="secondary" variant="outlined" @click="reload" />
  </div>

  <template v-else-if="dashboardState.loading">
    <div class="dash-kpis" aria-hidden="true">
      <Skeleton v-for="n in 4" :key="n" class="dash-skel-kpi" height="108px" borderRadius="14px" />
    </div>
    <div class="dash-row2">
      <section v-for="n in 2" :key="n" class="panel dash-card" aria-hidden="true">
        <div class="panel-body dash-skel-stack">
          <Skeleton width="45%" height="14px" borderRadius="4px" />
          <Skeleton v-for="m in 4" :key="m" width="100%" height="14px" borderRadius="4px" />
        </div>
      </section>
    </div>
    <section class="panel dash-queue" aria-hidden="true">
      <div class="panel-body dash-skel-stack">
        <Skeleton v-for="m in 4" :key="m" width="100%" height="34px" borderRadius="6px" />
      </div>
    </section>
  </template>

  <template v-else>
    <!-- ===== 4 kartu KPI ===== -->
    <section class="dash-kpis" aria-label="Ringkasan produksi">
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kblue"><Layers :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Produksi direncanakan</span>
        </div>
        <p class="knum">{{ plannedKpi.main }}</p>
        <p class="ksub">dari {{ fmtId(summary?.wo_planned_today ?? 0) }} work order</p>
        <p v-if="plannedKpi.rest" class="krest">{{ plannedKpi.rest }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kgreen"><Package :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Hasil produksi</span>
        </div>
        <p class="knum">{{ outputKpi.main }}</p>
        <!-- slot delta di-reserve agar kartu tak reflow antar-preset -->
        <p class="ksub kdelta-slot">
          <span v-if="deltaChip" class="kdelta" :class="{ up: !deltaChip.startsWith('−'), down: deltaChip.startsWith('−') }">{{ deltaChip }}</span>
          <span v-if="deltaChip"> vs kemarin</span>
          <template v-else>produk jadi</template>
        </p>
        <p v-if="outputKpi.rest" class="krest">{{ outputKpi.rest }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kamber"><Gauge :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Pencapaian</span>
        </div>
        <p class="knum">{{ achievement != null ? yieldPctText(achievement) : '-' }}</p>
        <p class="ksub">{{ dominant ? `dari rencana ${dominant}` : 'tanpa rencana' }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kviolet"><Activity :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">WO aktif</span>
        </div>
        <p class="knum">{{ fmtId(woAktif) }}</p>
        <p class="ksub">{{ attCount }} perlu perhatian</p>
      </div>
    </section>

    <!-- ===== grafik: rencana vs hasil + distribusi tahap ===== -->
    <div class="dash-row2">
      <section class="panel dash-card" aria-label="Rencana vs hasil">
        <div class="dcard-head">
          <div>
            <p class="deye">Kinerja output</p>
            <h2>Rencana vs hasil</h2>
          </div>
          <div class="dhead-tools">
            <!-- filter LOKAL kartu (FU78b): minggu = Senin s.d. Minggu,
               bulan = 1 s.d. akhir bulan (tanggal server) -->
            <div class="dseg" role="group" aria-label="Periode grafik">
              <button
                v-for="m in DAILY_MODES"
                :key="m.key"
                type="button"
                class="dseg-btn"
                :class="{ on: chartMode === m.key }"
                :aria-pressed="chartMode === m.key ? 'true' : 'false'"
                @click="pilihChartMode(m.key)"
              >
                {{ m.label }}
              </button>
            </div>
          </div>
        </div>
        <div class="panel-body dchart-body">
          <div v-if="dashboardState.dailyLoading && !seri" class="dchart-box" aria-hidden="true">
            <Skeleton width="100%" height="100%" borderRadius="8px" />
          </div>
          <div v-else-if="dashboardState.dailyError && !seri" class="callout bad dash-page-error" role="alert">
            <p>Gagal memuat grafik.</p>
            <Button label="Coba lagi" size="small" severity="secondary" variant="outlined" @click="retryDaily" />
          </div>
          <template v-else-if="seri">
            <div v-if="seri.nyata" class="dchart-box">
              <Chart type="bar" :data="barData" :options="barOptions" aria-label="Grafik rencana vs hasil per periode" />
            </div>
            <!-- FU100a: window kosong tetap menampilkan caption + pemilih UOM
               di bawah pesan kosong — filter konsisten di kedua mode -->
            <p v-else class="dash-none">Belum ada rencana maupun hasil dalam periode ini</p>
            <p class="dcap">
              Dalam
              <!-- UOM campuran (krim kopi Pcs vs dough Pack): satu chart satu
                 satuan — pindah seri, tidak pernah menjumlahkan. FU99: selector
                 menyatu dengan kalimat caption (kata satuan itulah kontrolnya);
                 header kartu tinggal tab. Satu UOM → teks biasa tanpa kontrol. -->
              <Select
                v-if="chartUomOptions.length > 1"
                v-model="chartUom"
                :options="chartUomOptions"
                optionLabel="label"
                optionValue="value"
                aria-label="Satuan grafik"
                class="dcap-uom"
              />
              <template v-else>{{ seri.uom }}</template>
              · hasil = tanggal posting, rencana = tanggal mulai WO
            </p>
          </template>
          <p v-else class="dash-none">Belum ada rencana maupun hasil dalam periode ini</p>
        </div>
      </section>

      <section class="panel dash-card" aria-label="Distribusi tahap work order">
        <div class="dcard-head">
          <div>
            <p class="deye">Distribusi live</p>
            <h2>Tahap work order</h2>
          </div>
        </div>
        <div class="panel-body donut-body">
          <div class="donut-flex">
            <div class="donut-wrap">
              <Chart type="doughnut" :data="doughnutData" :options="doughnutOptions" aria-label="Distribusi work order per tahap" />
              <!-- angka pusat overlay (bukan plugin) — pointer-events none agar
                 hover tooltip donut tetap hidup; translateY agar ANGKA pas
                 di tengah lubang (label di bawahnya ikut seimbang) -->
              <div class="dcenter" aria-hidden="true">
                <strong>{{ fmtId(donut.total) }}</strong>
                <span>Total WO</span>
              </div>
            </div>
            <!-- legend klikabel = navigasi papan FU72 yang sama dgn tile lama;
               SEMUA 7 tahap tampil (kosong = pudar), di kanan donut (FU78b) -->
            <ul class="dleg-list">
              <li v-for="s in donut.segments" :key="s.key">
                <button type="button" class="dleg-row" :class="{ zero: !s.value }" @click="openStage(stageByKey(s.key))">
                  <i class="dot" :style="{ background: s.color }" aria-hidden="true"></i>
                  <span class="lname">{{ s.label }}</span>
                  <span class="lval">{{ fmtId(s.value) }}</span>
                </button>
              </li>
            </ul>
          </div>
          <div v-if="avgYield != null" class="dyield">
            <div class="dyield-head">
              <span>Rata-rata yield per produk</span>
              <strong>{{ yieldPctText(avgYield) }}</strong>
            </div>
            <ProgressBar :value="Math.min(100, avgYield)" :showValue="false" class="dyield-prog" />
          </div>
        </div>
      </section>
    </div>

    <!-- ===== antrean produksi: tabel WO ===== -->
    <section class="panel dash-queue" aria-label="Antrean produksi">
      <div class="dcard-head">
        <div>
          <p class="deye">Antrean produksi</p>
          <h2>{{ tableTitle }}</h2>
        </div>
        <span v-if="adonanText" class="dchip">Adonan terakhir ke-{{ adonanText }}</span>
      </div>
      <DataTable
        :value="dashboardState.rows"
        dataKey="id"
        class="dash-table"
        :loading="dashboardState.rowsLoading"
        @row-click="(e) => e?.data && open(e.data.id)"
        removableSort
        @sort="onDashSort"
      >
        <Column field="id" header="WO" sortable headerClass="col-wo" bodyClass="col-wo">
          <template #body="{ data }">
            <button type="button" class="linklike" @click.stop="open(data.id)">{{ data.id }}</button>
          </template>
        </Column>
        <Column field="product" header="Produk" sortable headerClass="col-prod" bodyClass="col-prod">
          <template #body="{ data }">
            <span class="wo-prod">
              {{ data.product }}
              <small v-if="data.itemCode" class="mono">{{ data.itemCode }}</small>
            </span>
          </template>
        </Column>
        <Column header="Progres" headerClass="col-prog" bodyClass="col-prog">
          <template #body="{ data }">
            <span class="dprog">
              <ProgressBar :value="woProgressPct(data)" :showValue="false" class="dash-prog" />
              <span class="dpct">{{ yieldPctText(woProgressPct(data)) }}</span>
            </span>
          </template>
        </Column>
        <Column field="stage" header="Status" headerClass="col-status" bodyClass="col-status">
          <template #body="{ data }">
            <Tag :value="stageLabel(data)" :severity="pillSeverity(data)" class="dash-tag" />
          </template>
        </Column>
        <Column field="plannedEnd" header="Target selesai" sortable headerClass="col-target" bodyClass="col-target">
          <template #body="{ data }">
            <span class="dtarget" :class="{ late: overdue(data) }">
              <TriangleAlert v-if="overdue(data)" :size="14" :stroke-width="2" aria-hidden="true" />
              {{ targetText(data?.plannedEnd, summary?.today) }}
            </span>
          </template>
        </Column>
        <Column field="plannedStockQty" header="Rencana" sortable headerClass="col-rencana" bodyClass="col-rencana" headerStyle="text-align: right" bodyStyle="text-align: right">
          <template #body="{ data }">
            <span class="wo-qty">
              <span class="qmain">{{ woQtyText(data.plannedStockQty, data).main }}</span>
              <span v-if="woQtyText(data.plannedStockQty, data).sub" class="qsub">{{ woQtyText(data.plannedStockQty, data).sub }}</span>
            </span>
          </template>
        </Column>
        <Column field="producedStockQty" header="Hasil" sortable headerClass="col-hasil" bodyClass="col-hasil" headerStyle="text-align: right" bodyStyle="text-align: right">
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
      <div v-if="dashboardState.rowsError" class="callout bad dash-page-error" role="alert">
        <p>Gagal memuat halaman tabel.</p>
        <Button label="Coba lagi" size="small" severity="secondary" variant="outlined" @click="retryPage" />
      </div>
      <!-- FU77: lazy pagination 10/halaman — pindah halaman memanggil wo_list
         ringan, bukan menghitung ulang seluruh summary -->
      <Paginator
        v-if="dashboardState.total > pageSize"
        :rows="pageSize"
        :totalRecords="dashboardState.total || 0"
        v-model:first="dashFirst"
        template="PrevPageLink PageLinks NextPageLink"
        class="dash-pager"
        @page="onPage"
      />
    </section>

    <!-- ===== kualitas & hasil + perlu perhatian ===== -->
    <div class="dash-grid">
      <section class="panel dash-card" aria-label="Kualitas dan hasil">
        <div class="dcard-head">
          <div>
            <p class="deye">Output hari ini</p>
            <h2>Kualitas &amp; hasil</h2>
          </div>
        </div>
        <div class="panel-body">
          <template v-if="qualityMain">
            <div class="qnums">
              <div class="qnum">
                <strong>{{ fmtId(qualityMain.good + qualityMain.reject + qualityMain.trial + qualityMain.sisa) }}</strong>
                <span>Total dihasilkan <em>{{ qualityMain.uom }}</em></span>
              </div>
              <div class="qnum ok">
                <strong>{{ fmtId(qualityMain.good) }}</strong>
                <span>Bagus</span>
              </div>
              <div class="qnum bad">
                <strong>{{ fmtId(qualityMain.reject) }}</strong>
                <span>{{ mainRejectPct != null ? `Reject ${yieldPctText(mainRejectPct)} · ambang 3%` : 'Reject' }}</span>
              </div>
            </div>
            <p v-if="qualityRestText" class="qrest">UOM lain: {{ qualityRestText }}</p>
          </template>
          <p v-else class="dash-none">Belum ada hasil post-packing hari ini</p>
          <template v-if="productYield.length">
            <div class="dash-legend">
              <span v-for="m in YIELD_LEGEND" :key="m.key" class="dash-leg">
                <i class="dot" :style="{ background: m.color }"></i>{{ m.label }}
              </span>
            </div>
            <ul class="dash-yield">
              <li v-for="row in productYield" :key="row.item_code" class="dash-yield-row">
                <span class="yname">{{ row.item_name }}</span>
                <MeterGroup class="dash-meter" :value="yieldSegments(row).segments" :max="yieldSegments(row).max" />
                <span class="ypct" :class="{ over: row.over }">{{ yieldPctText(row.yield_pct) }}</span>
              </li>
            </ul>
          </template>
          <p class="dash-foot">Hanya WO dengan post-packing terkonfirmasi dalam rentang terpilih. Yield bisa di atas 100% (overproduksi ERPNext).</p>
        </div>
      </section>

      <section class="panel dash-card" aria-label="Perlu perhatian">
        <div class="dcard-head">
          <div>
            <p class="deye">Status operasional</p>
            <h2>Perlu perhatian</h2>
          </div>
          <span class="dchip">{{ attentionRows.length }} item</span>
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

    <!-- ===== bahan baku + aktivitas (row disembunyikan bila dua-duanya kosong:
       gate izin SE membuat keduanya null bersama) ===== -->
    <div v-if="mu || activityRows.length" class="dash-grid">
      <section v-if="mu" class="panel dash-card" aria-label="Penggunaan bahan baku">
        <div class="dcard-head">
          <div>
            <p class="deye">Konsumsi bahan</p>
            <h2>Penggunaan bahan baku</h2>
            <p v-if="muUsed" class="dlead">{{ materialSummaryText(mu) }}</p>
          </div>
          <a href="#/penggunaan-bahan" class="dash-mu-link">Lihat semua</a>
        </div>
        <div class="panel-body">
          <div v-if="muUsed" class="dash-mu-rows">
            <a
              v-for="row in muTop"
              :key="row.item_code"
              class="dash-mu-row"
              :href="materialUsageHref(row.item_code)"
            >
              <span class="mtxt">
                <span class="ttl">{{ row.item_name }}<small v-if="row.item_code">{{ row.item_code }}</small></span>
                <span class="dtl">{{ materialRowText(row) }}</span>
              </span>
              <!-- pct null = tanpa dasar — jangan pill merah kosong (review FU74) -->
              <Tag
                :value="variancePctText(row) || 'tanpa dasar'"
                :severity="row.over ? 'danger' : 'success'"
                class="mu-tag"
                :class="{ over: row.over }"
              />
            </a>
            <a v-if="muOverCount > muTop.filter((r) => r.over).length" href="#/penggunaan-bahan" class="dash-mu-extra">
              Lihat semua bahan di atas ambang di halaman Penggunaan bahan baku
            </a>
          </div>
          <div v-else class="empty-inset dash-mu-empty">
            <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
            <p class="etitle">Belum ada pemakaian bahan hari ini</p>
          </div>
        </div>
      </section>

      <section v-if="activityRows.length" class="panel dash-card" aria-label="Aktivitas terakhir">
        <div class="dcard-head">
          <div>
            <p class="deye">Live timeline</p>
            <h2>Aktivitas terakhir</h2>
          </div>
        </div>
        <div class="panel-body">
          <ul class="dact">
            <li v-for="(a, i) in activityRows" :key="i">
              <span class="atime">{{ a.time }}<small v-if="a.date"> · {{ a.date }}</small></span>
              <span class="adot" :class="a.title === 'Hasil diposting' ? 'ok' : 'blue'" aria-hidden="true"></span>
              <component :is="a.link ? 'a' : 'div'" :href="a.link || undefined" class="abody" :class="{ link: !!a.link }">
                <span class="attl">{{ a.title }}</span>
                <span v-if="a.detail" class="adtl">{{ a.detail }}</span>
              </component>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </template>
</template>

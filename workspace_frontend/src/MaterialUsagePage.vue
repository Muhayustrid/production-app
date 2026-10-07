<script setup>
// FU79: rombak halaman "Bahan baku" (#/bahan) gaya referensi dengan komponen
// PrimeVue — 5 kartu KPI (barang jadi diproduksi, order produksi, bahan
// dipakai, deviasi bahan tertimbang, efisiensi), kartu "Perbandingan konsumsi
// bahan" (bar ganda teoritis vs aktual + % selisih), kartu "Tren produksi"
// (bar hasil per tanggal posting + puncak output), kartu "Analisis penggunaan"
// (klik baris → tab Transaksi terfilter bahan) dan kartu "Traceability
// produksi" 3 tab + panel "Cara ini dihitung". Data satu endpoint
// (store.loadMaterialUsage, include_trace); aturan inti FU74/FU78 terwarisi: konsumsi
// bruto Manufacture/Konsumsi (retur = balik transfer, bukan konsumsi), teoritis
// proporsional produced_qty, beda UOM tidak pernah dijumlahkan/dirata-ratakan
// (deviasi & efisiensi pada UOM utama saja). Filter lama dipertahankan;
// expander per-WO FU74 diganti tab Transaksi (per baris SE lebih halus).
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Chart from 'primevue/chart'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Paginator from 'primevue/paginator'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import Skeleton from 'primevue/skeleton'
import Tag from 'primevue/tag'
import {
  Boxes, ChevronRight, ClipboardList, ExternalLink, Factory, Filter, FileSpreadsheet, FlaskConical,
  Gauge, HelpCircle, Search, SearchX, TrendingUp, X
} from 'lucide-vue-next'
import { companyFilterState, materialUsageState, loadMaterialUsage, saveCompanyFilter, whenCompanyReady } from './store.js'
import { companySelectOptions, showCompanyPicker } from './company-filter.js'
import { fmtId } from './format.js'
import {
  materialUsageXlsxFilename, barPct, chartTrend, comparisonRows, efficiencyPct, harusKeLogin,
  loginRedirectUrl, materialCounts,
  peakDay, peakText, signedQtyText, tanggalDmy, tanggalPendek, txnOfMaterial, uomTotals,
  variancePctText, varianceTone, weightedVarPct, woStatusSummary, woStatusText, woYieldPct,
  yieldPctText, yieldTone
} from './dashboard.js'
import RangeField from './RangeField.vue'

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
// FU95: company = filter GLOBAL (companyFilterState, tersimpan per-user di
// server). Param lama ?company= (tautan era FU74) tetap dihormati: diadopsi
// ke GLOBAL setelah preferensi tersimpan termuat — tunggu whenCompanyReady
// supaya nilai tersimpan tidak dilawan balapan waktu load (lihat onMounted).
const companies = computed(() => companyFilterState.companies)
const showCompany = computed(() => showCompanyPicker(companies.value))
const companyOptions = computed(() => companySelectOptions(companies.value, 'ALL'))
const companyValue = computed(() => companyFilterState.company || 'ALL')
async function onCompany(e) {
  const raw = e && e.value !== undefined ? e.value : (e?.target?.value ?? 'ALL')
  const v = raw === 'ALL' ? '' : String(raw)
  if (v === companyFilterState.company) return
  companyFilterState.company = v
  await saveCompanyFilter(v)
  reload()
}
const overOnly = ref(false)
// FU79b: filter panel gaya WorkOrderList — popover dari tombol Filter;
// tanggal BAHAN tidak bisa kosong (server default hari ini), jadi "bersih"
// = kembali ke rentang dasar milik server (di-catat saat muat pertama)
const filterOpen = ref(false)
const basis = ref({ dari: '', sampai: '' })
// FU79d: field rentang tunggal kini komponen RangeField (dipakai bersama WO +
// Stock Entry); bahan memakai first-to 'same' — endpoint wajib dari+sampai,
// jadi pilihan pertama langsung terfilter satu hari
let reloadTimer
let echoingDates = false

const data = computed(() => materialUsageState.data)
const rows = computed(() => data.value?.rows || [])
const workOrders = computed(() => data.value?.work_orders || [])
const transactions = computed(() => data.value?.transactions || [])
const seriesList = computed(() => data.value?.series || [])
const rangeInvalid = computed(() => !!dari.value && !!sampai.value && dari.value > sampai.value)

function payload() {
  return {
    dari: dari.value,
    sampai: sampai.value,
    productionItem: product.value === 'ALL' ? '' : product.value,
    search: q.value.trim(),
    overOnly: overOnly.value
  }
}
async function reload() {
  if (rangeInvalid.value) return // inline hint tampil; API tidak dipanggil
  const firstLoad = !materialUsageState.loaded
  await loadMaterialUsage(payload())
  // muat pertama tanpa tanggal: isi input dari jawaban server (server
  // otoritatif atas "hari ini"); setelahnya isian user tak pernah ditimpa.
  // Rentang dasar di-catat utk "Hapus semua filter" & hitungan badge Filter
  const d = materialUsageState.data
  if (firstLoad && d) {
    echoingDates = true
    if (!dari.value && d.dari) dari.value = d.dari
    if (!sampai.value && d.sampai) sampai.value = d.sampai
    basis.value = { dari: dari.value, sampai: sampai.value }
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
watch(product, scheduleReload)
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
onMounted(async () => {
  // FU95: tunggu preferensi global termuat DULU; baru adopsi ?company= lama
  // bila ada dan berbeda (tautan eksplisit menang atas preferensi), lalu reload
  await whenCompanyReady()
  if (props.initialCompany && props.initialCompany !== companyFilterState.company) {
    companyFilterState.company = props.initialCompany
    await saveCompanyFilter(props.initialCompany)
  }
  await reload()
})

// ---- 5 kartu KPI — beda UOM tidak pernah dijumlahkan: angka utama milik
// UOM terbesar, UOM lain jujur di baris kecil di bawahnya
const fgTotals = computed(() => uomTotals(workOrders.value, 'produced_qty'))
const fgMain = computed(() => fgTotals.value[0] || null)
const fgRest = computed(() =>
  fgTotals.value.slice(1).map((e) => `${fmtId(e.qty)} ${e.uom}`).join(' · ')
)
const fgCount = computed(() => workOrders.value.length)
const orderSummary = computed(() => woStatusSummary(workOrders.value))

const bahanTotals = computed(() => uomTotals(rows.value, 'consumed'))
const bahanMain = computed(() => bahanTotals.value[0] || null)
const bahanRest = computed(() =>
  bahanTotals.value.slice(1).map((e) => `${fmtId(e.qty)} ${e.uom}`).join(' · ')
)
const jenisCount = computed(() => materialCounts({ rows: rows.value }).used)
// deviasi & efisiensi SATU UOM (utama) — rata-rata lintas satuan tidak bermakna
const uomUtama = computed(() => bahanMain.value?.uom || '')
const deviasi = computed(() => weightedVarPct(rows.value, uomUtama.value))
const efisiensi = computed(() => efficiencyPct(rows.value, uomUtama.value))
// "+2,7%" / "−1,9%" / "-" (minus asli, pola deltaPctText)
function pctTanda(v) {
  if (v == null || !Number.isFinite(Number(v))) return '-'
  const n = Number(v)
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${fmtId(Math.abs(n))}%`
}

// ---- kartu perbandingan: bar ganda per bahan, skala bersama baris tampil
const cmp = computed(() => comparisonRows(rows.value, 8))
const cmpMax = computed(() =>
  cmp.value.list.reduce((m, r) => Math.max(m, Number(r.expected) || 0, Number(r.consumed) || 0), 0)
)
function pctCell(row) {
  const text = variancePctText(row)
  return text || 'tanpa dasar'
}

// ---- kartu tren: seri pertama = dominan milik server (hasil terbesar)
const seriTren = computed(() => seriesList.value[0] || null)
const tren = computed(() => chartTrend(seriTren.value))
const hariBadge = computed(() => {
  const n = seriTren.value?.rows?.length || 0
  return n ? `${n} hari` : ''
})
const puncak = computed(() => peakDay(seriTren.value?.rows))
const puncakText = computed(() => peakText(puncak.value, seriTren.value?.uom || ''))
const trenData = computed(() => ({
  labels: tren.value.labels,
  datasets: [
    { label: 'Hasil', data: tren.value.data, backgroundColor: '#9bbdd8', borderRadius: 4, maxBarThickness: 26 }
  ]
}))
const trenOptions = {
  responsive: true, // wrapper .dchart-box tinggi tetap (pelajaran FU78/FU78b)
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 8 } },
    y: { beginAtZero: true, grid: { color: '#e3e9ee' }, ticks: { maxTicksLimit: 6 } }
  }
}

// ---- traceability: 3 tab; klik baris analisis mendarat di Transaksi terfilter
const TRACE_TABS = [
  { label: 'Penggunaan bahan', value: 'usage' },
  { label: 'Work order', value: 'wo' },
  { label: 'Transaksi', value: 'transaksi' }
]
const traceTab = ref('usage')
const txnMaterial = ref('')
const TXN_PAGE = 10
const txnFirst = ref(0)
const txnTerfilter = computed(() =>
  txnMaterial.value ? txnOfMaterial(transactions.value, txnMaterial.value) : transactions.value
)
// FU94: paginasi tab Transaksi pindah ke paginator bawaan DataTable (list
// penuh supaya sort mencakup semua baris) — slice `txnHalaman` tidak lagi dipakai
// FU94: tab "Penggunaan bahan" (kartu) ikut dibatasi 10/halaman
const USAGE_PAGE = 10
const usageFirst = ref(0)
const usageHalaman = computed(() =>
  workOrders.value.slice(usageFirst.value, usageFirst.value + USAGE_PAGE)
)
// FU98c: kartu Analisis penggunaan ikut 10/halaman (DataTable paginator)
const analisisFirst = ref(0)
watch(data, () => { usageFirst.value = 0; analisisFirst.value = 0 })
const bahanTerpilih = computed(() =>
  txnMaterial.value ? rows.value.find((r) => r.item_code === txnMaterial.value) : null
)
function pilihBahan(row) {
  if (!row?.item_code) return
  txnMaterial.value = row.item_code
  traceTab.value = 'transaksi'
  txnFirst.value = 0
  document.getElementById('bahan-trace')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function bersihkanBahan() {
  txnMaterial.value = ''
  txnFirst.value = 0
}
function statusSeverity(status) {
  if (status === 'Completed') return 'success'
  if (status === 'Stopped' || status === 'Cancelled') return 'danger'
  if (status === 'In Process') return 'info'
  return undefined
}
function woHref(wo) { return '#/wo/' + encodeURIComponent(wo) }
function noPlan(w) { return !Number(w?.planned) }

// badge tombol Filter (pola WorkOrderList): produk/over-only/tanggal
// menyimpang dari dasar masing-masing dihitung 1; FU95: company GLOBAL ikut
// dihitung (select-nya di head, di luar panel — tetap jujur di badge)
const activeFilters = computed(
  () =>
    (product.value !== 'ALL') +
    (overOnly.value ? 1 : 0) +
    (dari.value !== basis.value.dari || sampai.value !== basis.value.sampai ? 1 : 0) +
    (showCompany.value && companyFilterState.company ? 1 : 0)
)
// satu aksi bersih (konvensi FU75): reset ke kondisi awal halaman — watcher
// q/tanggal/over-only/product me-lebur lewat debounce jadi SATU reload;
// FU95: company global juga dilepas (simpan dulu, reload lewat onCompany)
function clearFilters() {
  q.value = ''
  product.value = 'ALL'
  overOnly.value = false
  dari.value = basis.value.dari
  sampai.value = basis.value.sampai
  filterOpen.value = false
  if (companyFilterState.company) onCompany({ value: 'ALL' })
}

// FU80c: unduh .xlsx = laporan tampilan aktif (rentang + semua filter) yang
// dibangun SERVER (4 sheet: Info/Ringkasan per Bahan/Work Order/Transaksi —
// angka mentah numerik, bisa dihitung ulang di Excel/Sheets); pilih Produk di
// filter = laporan pemakaian bahan satu produk dalam rentang (nama file ikut
// produk). Gagal unduh ditandai kecil di samping tombol, layar tak dibongkar
const exportGagal = ref(false)
async function exportXlsx() {
  const d = dari.value || data.value?.dari || ''
  const s = sampai.value || data.value?.sampai || ''
  const produk = product.value === 'ALL'
    ? ''
    : ((data.value?.products || []).find((p) => p.item_code === product.value)?.item_name || product.value)
  const params = new URLSearchParams({
    dari: d || '',
    sampai: s || '',
    // FU95: company GLOBAL (sumber yang sama dgn tabel — angka file = angka layar)
    company: companyFilterState.company || '',
    production_item: product.value === 'ALL' ? '' : product.value,
    search: q.value.trim(),
    over_only: overOnly.value ? '1' : '0'
  })
  exportGagal.value = false
  try {
    const r = await fetch(`/api/method/production_app.api.material_usage.material_usage_xlsx?${params}`)
    if (!r.ok) {
      // FU81: sesi terkick saat mengekspor → ke login, bukan sekadar gagal
      const teks = await r.text().catch(() => '')
      if (harusKeLogin(r.status, teks)) {
        window.location.href = loginRedirectUrl(window.location.pathname, window.location.hash)
        return
      }
      throw new Error(String(r.status))
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = materialUsageXlsxFilename(d, s, produk)
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch {
    exportGagal.value = true
  }
}
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <p class="ph-eye">Konsumsi bahan</p>
      <h1>Penggunaan bahan baku</h1>
      <p class="sub">Konsumsi nyata dibanding rencana BOM, diskalakan ke hasil produksi.</p>
    </div>
    <div class="ph-right">
      <Select
        v-if="showCompany"
        :modelValue="companyValue"
        :options="companyOptions"
        optionLabel="label"
        optionValue="value"
        inputId="bahan-company"
        aria-label="Filter company"
        class="ph-pselect"
        @change="onCompany"
      />
    </div>
  </div>

  <div class="toolbar mu-toolbar">
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
            <select v-model="product" class="select">
              <option value="ALL">Semua produk</option>
              <option v-if="product !== 'ALL' && !(data?.products || []).some((p) => p.item_code === product)" :value="product">{{ product }}</option>
              <option v-for="p in data?.products || []" :key="p.item_code" :value="p.item_code">{{ p.item_name || p.item_code }}</option>
            </select>
          </div>
          <div class="ffield">
            <label>Cakupan</label>
            <label class="mu-check" for="bahan-over">
              <Checkbox v-model="overOnly" binary inputId="bahan-over" />
              <span>Hanya di atas rencana</span>
            </label>
          </div>
          <div class="ffield">
            <label>Rentang</label>
            <RangeField
              v-model:dari="dari"
              v-model:sampai="sampai"
              :reset-dari="basis.dari"
              :reset-sampai="basis.sampai"
              first-to="same"
            />
          </div>
          <button class="linkbtn filter-clear" type="button" @click="clearFilters">Hapus semua filter</button>
        </div>
      </Transition>
    </div>
    <button class="btn exportbtn" type="button" aria-label="Export XLSX" @click="exportXlsx">
      <FileSpreadsheet :size="14" :stroke-width="2" />
      <span class="btext">Export</span>
    </button>
    <span v-if="exportGagal" class="export-gagal" role="alert">Export gagal — coba lagi</span>
  </div>

  <div v-if="materialUsageState.error" class="callout bad dash-error" role="alert">
    <p>Gagal memuat: {{ materialUsageState.error }}</p>
    <Button label="Coba lagi" size="small" severity="secondary" variant="outlined" @click="reload" />
  </div>

  <template v-if="materialUsageState.loading && !materialUsageState.loaded">
    <section class="panel" aria-hidden="true">
      <div class="panel-body dash-skel-stack">
        <Skeleton v-for="m in 6" :key="m" width="100%" height="34px" borderRadius="6px" />
      </div>
    </section>
  </template>

  <template v-else-if="materialUsageState.loaded && !materialUsageState.error && !rangeInvalid">
    <!-- ===== 5 kartu KPI ===== -->
    <section class="mu-kpis" aria-label="Ringkasan pemakaian bahan">
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kblue"><Boxes :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Barang jadi diproduksi</span>
        </div>
        <p class="knum">
          {{ fgMain ? fmtId(fgMain.qty) : '0' }}<span v-if="fgMain?.uom" class="kuom"> {{ fgMain.uom }}</span>
        </p>
        <p class="ksub">{{ fmtId(fgCount) }} work order</p>
        <p v-if="fgRest" class="krest">{{ fgRest }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kgreen"><ClipboardList :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Order produksi</span>
        </div>
        <p class="knum">{{ fmtId(fgCount) }}</p>
        <p class="ksub">{{ orderSummary }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kviolet"><FlaskConical :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Bahan dipakai</span>
        </div>
        <p class="knum">
          {{ bahanMain ? fmtId(bahanMain.qty) : '0' }}<span v-if="bahanMain?.uom" class="kuom"> {{ bahanMain.uom }}</span>
        </p>
        <p class="ksub">{{ fmtId(jenisCount) }} jenis bahan</p>
        <p v-if="bahanRest" class="krest">{{ bahanRest }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kamber"><TrendingUp :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Deviasi bahan</span>
        </div>
        <p class="knum">{{ pctTanda(deviasi) }}</p>
        <p class="ksub">Rata-rata tertimbang{{ uomUtama ? ` · ${uomUtama}` : '' }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kblue"><Gauge :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Efisiensi bahan</span>
        </div>
        <p class="knum">{{ efisiensi != null ? `${fmtId(efisiensi)}%` : '-' }}</p>
        <p class="ksub">Teoritis / aktual{{ uomUtama ? ` · ${uomUtama}` : '' }}</p>
      </div>
    </section>

    <!-- ===== perbandingan konsumsi + tren produksi ===== -->
    <div class="mu-row2">
      <section class="panel dash-card" aria-label="Perbandingan konsumsi bahan">
        <div class="dcard-head">
          <div>
            <p class="deye">Konsumsi vs rencana</p>
            <h2>Perbandingan konsumsi bahan</h2>
            <p class="dsub">Jumlah BOM teoritis (× hasil nyata) vs konsumsi aktual</p>
          </div>
        </div>
        <div class="panel-body mu-cmp-body">
          <ul v-if="cmp.list.length" class="mu-cmp">
            <li v-for="r in cmp.list" :key="r.item_code" class="bcm-row">
              <span class="bcm-name" :title="r.item_name || r.item_code">
                {{ r.item_name || r.item_code }}
              </span>
              <span class="bcm-bars">
                <span class="bcm-track teo" aria-hidden="true">
                  <span class="bcm-fill" :style="{ width: barPct(r.expected, cmpMax) + '%' }" />
                </span>
                <span class="bcm-track akt" aria-hidden="true">
                  <span class="bcm-fill" :style="{ width: barPct(r.consumed, cmpMax) + '%' }" />
                </span>
              </span>
              <span class="bcm-pct" :class="`tone-${varianceTone(r)}`">{{ pctCell(r) }}</span>
            </li>
          </ul>
          <p v-else class="dash-none">Belum ada pemakaian bahan dalam rentang ini</p>
          <div class="bcm-foot">
            <span class="bcm-legend">
              <span class="lg"><i class="dot teo" aria-hidden="true" /> Teoritis</span>
              <span class="lg"><i class="dot akt" aria-hidden="true" /> Aktual</span>
            </span>
            <span v-if="cmp.extra" class="bcm-extra">+{{ cmp.extra }} bahan lainnya</span>
          </div>
        </div>
      </section>

      <section class="panel dash-card" aria-label="Tren produksi">
        <div class="dcard-head">
          <div>
            <p class="deye">Hasil produksi</p>
            <h2>Tren produksi</h2>
            <p class="dsub">Barang jadi per tanggal produksi</p>
          </div>
          <span v-if="hariBadge" class="badge-hari">{{ hariBadge }}</span>
        </div>
        <div class="panel-body dchart-body">
          <div v-if="seriTren" class="dchart-box">
            <Chart type="bar" :data="trenData" :options="trenOptions" aria-label="Grafik hasil produksi per tanggal" />
          </div>
          <p v-else class="dash-none">Belum ada hasil produksi dalam rentang ini</p>
          <p v-if="seriTren" class="dcap">Dalam {{ seriTren.uom }} · per tanggal posting Manufacture</p>
          <p v-if="puncakText" class="mu-peak"><strong>Puncak output</strong> {{ puncakText.replace('Puncak output ', '') }}</p>
        </div>
      </section>
    </div>

    <!-- ===== analisis penggunaan (klik baris → transaksi) ===== -->
    <section class="panel mu-card" aria-label="Analisis penggunaan bahan">
      <div class="dcard-head an-head">
        <div>
          <p class="deye">Rincian per bahan</p>
          <h2>Analisis penggunaan</h2>
          <p class="dsub">Klik satu bahan untuk melihat transaksi sumbernya.</p>
        </div>
      </div>
      <div class="panel-body mu-tbody">
        <DataTable
          :value="rows"
          dataKey="item_code"
          class="dash-table mu-table"
          :rowHover="true"
          @row-click="(e) => pilihBahan(e.data)"
          removableSort
          :paginator="rows.length > USAGE_PAGE"
          :rows="USAGE_PAGE"
          v-model:first="analisisFirst"
        >
          <Column field="item_name" header="Bahan" sortable headerClass="col-bahan" bodyClass="col-bahan">
            <template #body="{ data: r }">
              <span class="wo-prod mu-name">
                {{ r.item_name || r.item_code }}
                <small v-if="r.item_code" class="mono">{{ r.item_code }}</small>
                <span v-if="r.unlisted" class="chip chip-off mu-noplan">tanpa rencana</span>
              </span>
            </template>
          </Column>
          <Column field="uom" header="UOM" sortable headerClass="col-uom" bodyClass="col-uom" />
          <Column field="expected" header="Teoritis" sortable headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">{{ fmtId(r.expected) }}</template>
          </Column>
          <Column field="consumed" header="Aktual" sortable headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">{{ fmtId(r.consumed) }}</template>
          </Column>
          <Column field="variance" header="Selisih" sortable headerClass="col-selisih" bodyClass="col-selisih">
            <template #body="{ data: r }">
              <span :class="`tone-${varianceTone(r)}`">{{ signedQtyText(r.variance, r.uom) }}</span>
            </template>
          </Column>
          <Column header="Selisih %" headerClass="col-pct" bodyClass="col-pct">
            <template #body="{ data: r }">
              <span :class="`tone-${varianceTone(r)}`">{{ pctCell(r) }}</span>
            </template>
          </Column>
          <Column header="Status" headerClass="col-status2" bodyClass="col-status2">
            <template #body="{ data: r }">
              <Tag
                v-if="r.over"
                value="Over"
                severity="danger"
                class="mu-pill"
              />
              <Tag v-else value="Normal" severity="success" class="mu-pill" />
            </template>
          </Column>
          <Column headerClass="col-chev" bodyClass="col-chev">
            <template #body><ChevronRight :size="15" :stroke-width="2" class="mu-chev" aria-hidden="true" /></template>
          </Column>
          <template #empty>
            <div class="empty-inset">
              <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
              <p class="etitle">Tidak ada pemakaian bahan pada rentang ini</p>
            </div>
          </template>
        </DataTable>
      </div>
      <div class="an-foot">
        <span>Total {{ rows.length }} bahan</span>
        <span class="an-threshold"><i class="dot ambang" aria-hidden="true" /> Ambang: ±5%</span>
      </div>
    </section>

    <!-- ===== traceability produksi: 3 tab + info perhitungan ===== -->
    <section id="bahan-trace" class="panel mu-card" aria-label="Traceability produksi">
      <div class="dcard-head an-head">
        <div>
          <p class="deye">Telusuri sumber</p>
          <h2>Traceability produksi</h2>
          <p class="dsub">Ikuti tiap angka kembali ke dokumen sumbernya.</p>
        </div>
        <SelectButton
          v-model="traceTab"
          :options="TRACE_TABS"
          optionLabel="label"
          optionValue="value"
          :allowEmpty="false"
          aria-label="Jenis traceability"
          class="trace-tabs"
        />
      </div>
      <div class="panel-body mu-tbody">
        <!-- tab 1: kartu WO + panel cara hitung -->
        <div v-if="traceTab === 'usage'" class="trace-grid">
          <div class="trace-list">
            <p v-if="!workOrders.length" class="dash-none">Belum ada work order dalam rentang ini</p>
            <a v-for="w in usageHalaman" :key="w.wo" class="trace-wo" :href="woHref(w.wo)">
              <span class="trace-ico" aria-hidden="true"><Factory :size="17" :stroke-width="2" /></span>
              <span class="two">
                <span class="t1">{{ w.wo }}</span>
                <span class="t2">{{ tanggalPendek(w.tanggal) }} · <span class="mono">{{ w.bom || '-' }}</span></span>
              </span>
              <span class="tmetrics">
                <span class="tm">
                  <label>Produksi</label>
                  <b>{{ fmtId(w.produced_qty) }} <small>{{ w.uom }}</small></b>
                </span>
                <span class="tm">
                  <label>Yield</label>
                  <b :class="`ytext-${yieldTone(woYieldPct(w))}`">{{ yieldPctText(woYieldPct(w)) }}</b>
                </span>
                <Tag :value="woStatusText(w.status)" :severity="statusSeverity(w.status)" class="mu-pill" />
                <ChevronRight :size="15" :stroke-width="2" class="mu-chev" aria-hidden="true" />
              </span>
            </a>
            <Paginator
              v-if="workOrders.length > USAGE_PAGE"
              :rows="USAGE_PAGE"
              :totalRecords="workOrders.length"
              v-model:first="usageFirst"
              class="dash-pager"
              aria-label="Halaman penggunaan bahan"
            />
          </div>
          <aside class="trace-info">
            <h3><HelpCircle :size="15" :stroke-width="2" aria-hidden="true" /> Cara ini dihitung</h3>
            <p>
              Jumlah teoritis memakai BOM yang ditetapkan di tiap Work Order dan diskalakan ke
              hasil produksi nyata. Material Transfer for Manufacture tidak dihitung konsumsi agar
              tidak terhitung ganda — konsumsi dibaca langsung dari Stock Entry
              Manufacture/Konsumsi ke WIP. Retur bahan membalik transfer, bukan konsumsi.
            </p>
            <a class="trace-link" href="/app/stock-entry" target="_blank" rel="noopener">
              Lihat Stock Entry di ERPNext
              <ExternalLink :size="13" :stroke-width="2" aria-hidden="true" />
            </a>
          </aside>
        </div>

        <!-- tab 2: tabel work order -->
        <template v-else-if="traceTab === 'wo'">
          <DataTable
            :value="workOrders"
            dataKey="wo"
            class="dash-table mu-table"
            removableSort
            :paginator="workOrders.length > USAGE_PAGE"
            :rows="USAGE_PAGE"
            v-model:first="usageFirst"
          >
            <Column field="wo" header="Work order" sortable headerClass="col-wo2" bodyClass="col-wo2">
              <template #body="{ data: w }">
                <a class="linklike" :href="woHref(w.wo)">{{ w.wo }}</a>
              </template>
            </Column>
            <Column field="produk" header="Produk" sortable headerClass="col-prod2" bodyClass="col-prod2">
              <template #body="{ data: w }">{{ w.produk }}</template>
            </Column>
            <Column field="bom" header="BOM" sortable headerClass="col-bom" bodyClass="col-bom">
              <template #body="{ data: w }"><span class="mono">{{ w.bom || '-' }}</span></template>
            </Column>
            <Column field="planned_qty" header="Rencana" sortable headerClass="col-angka" bodyClass="col-angka">
              <template #body="{ data: w }">{{ fmtId(w.planned_qty) }} <small class="kuom">{{ w.uom }}</small></template>
            </Column>
            <Column field="produced_qty" header="Hasil" sortable headerClass="col-angka" bodyClass="col-angka">
              <template #body="{ data: w }">{{ fmtId(w.produced_qty) }} <small class="kuom">{{ w.uom }}</small></template>
            </Column>
            <Column field="status" header="Status" sortable headerClass="col-status2" bodyClass="col-status2">
              <template #body="{ data: w }">
                <Tag :value="woStatusText(w.status)" :severity="statusSeverity(w.status)" class="mu-pill" />
              </template>
            </Column>
            <template #empty>
              <div class="empty-inset">
                <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
                <p class="etitle">Belum ada work order dalam rentang ini</p>
              </div>
            </template>
          </DataTable>
        </template>

        <!-- tab 3: transaksi konsumsi per SE (+filter bahan dari klik analisis) -->
        <template v-else>
          <div class="txn-chips">
            <button v-if="bahanTerpilih" type="button" class="chip chip-filter" @click="bersihkanBahan">
              Bahan: {{ bahanTerpilih.item_name || bahanTerpilih.item_code }}
              <X :size="13" :stroke-width="2.2" aria-hidden="true" />
            </button>
            <span class="txn-count">{{ fmtId(txnTerfilter.length) }} transaksi</span>
          </div>
          <DataTable
            :value="txnTerfilter"
            dataKey="se"
            class="dash-table mu-table"
            removableSort
            :paginator="txnTerfilter.length > TXN_PAGE"
            :rows="TXN_PAGE"
            v-model:first="txnFirst"
          >
            <Column field="se" header="Stock entry" sortable headerClass="col-se" bodyClass="col-se">
              <template #body="{ data: t }"><span class="mono mu-se">{{ t.se }}</span></template>
            </Column>
            <Column field="tanggal" header="Tanggal" sortable headerClass="col-tgl" bodyClass="col-tgl">
              <template #body="{ data: t }">{{ tanggalPendek(t.tanggal) }}</template>
            </Column>
            <Column field="wo" header="Work order" sortable headerClass="col-wo2" bodyClass="col-wo2">
              <template #body="{ data: t }">
                <a class="linklike" :href="woHref(t.wo)">{{ t.wo }}</a>
              </template>
            </Column>
            <Column field="item_name" header="Bahan" sortable headerClass="col-bahan" bodyClass="col-bahan">
              <template #body="{ data: t }">
                <span class="wo-prod mu-name">
                  {{ t.item_name }}
                  <small v-if="t.item_code" class="mono">{{ t.item_code }}</small>
                </span>
              </template>
            </Column>
            <Column field="qty" header="Qty" sortable headerClass="col-angka" bodyClass="col-angka">
              <template #body="{ data: t }">{{ fmtId(t.qty) }} <small class="kuom">{{ t.uom }}</small></template>
            </Column>
            <Column field="batch" header="Batch" sortable headerClass="col-batch" bodyClass="col-batch">
              <template #body="{ data: t }"><span class="mono">{{ t.batch || '-' }}</span></template>
            </Column>
            <template #empty>
              <div class="empty-inset">
                <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
                <p class="etitle">Tidak ada transaksi konsumsi pada rentang ini</p>
              </div>
            </template>
          </DataTable>
        </template>
      </div>
    </section>

    <p class="srcnote">
      Lingkup: Work Order dengan tanggal rencana dalam rentang terpilih. Konsumsi = Stock Entry
      Manufacture/Konsumsi dari WIP — retur membalik transfer, bukan konsumsi. Teoritis = rencana
      BOM proporsional terhadap hasil produksi nyata (produced_qty). Ambang di atas rencana 5%.
      Bahan tanpa rencana BOM ditandai "tanpa rencana"; selisih tanpa dasar ekspektasi ditandai
      "tanpa dasar". Deviasi & efisiensi dihitung pada UOM utama saja (beda satuan tidak pernah
      dirata-ratakan). Transaksi dibatasi 1.000 baris terbaru.
    </p>
  </template>
</template>

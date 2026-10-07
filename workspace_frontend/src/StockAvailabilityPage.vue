<script setup>
// FU83: halaman "Ketersediaan Stock" (#/ketersediaan-stock) — monitoring bahan
// baku produksi untuk PPIC/Produksi/Gudang; pertanyaan inti: apakah
// bahan tersedia dan cukup untuk kebutuhan produksi? FU90: data dari endpoint
// server (store.loadStockAvailability — Bin ERPNext: stok/reserved; Item
// Reorder: minimum; BOM aktif: kapasitas batch). Pilih gudang = fetch ulang
// server-side (data lama tampil sampai respons); pencarian/grup/status tetap
// client-side. Movement drawer dimuat lazy per gudang|item (cache di store).
// FU90: status diturunkan SERVER (habis ≤ 0, menipis < minimum, sisanya aman)
// — mock dashboard.stockStatus/stockMockDataset sudah dipensiunkan (arsip di
// backup/dashboard-stock-mock FU83-89.mjs). Tersedia (available) = stok −
// reserved, ditonjolkan.
import { computed, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Drawer from 'primevue/drawer'
import Skeleton from 'primevue/skeleton'
import Tag from 'primevue/tag'
import {
  Boxes, CheckCircle2, ChevronRight, FileSpreadsheet, Filter, PackageX, Search, SearchX, TriangleAlert
} from 'lucide-vue-next'
import {
  companyFilterState, loadStockAvailability, loadStockMovements, saveCompanyFilter,
  stockAvailabilityState, stockMovementsState
} from './store.js'
import { companySelectOptions, showCompanyPicker } from './company-filter.js'
import { fmtId, fmtStampShort } from './format.js'
import { harusKeLogin, loginRedirectUrl, stockXlsxFilename, tanggalPendek, woQtyText } from './dashboard.js'
import { countFilters, normalizeFilters } from './filter-rows.js'
import FilterRows from './FilterRows.vue'

const q = ref('')
// FU104: grup + status kini baris filter ala ERPNext (multi-nilai); Gudang
// tetap kontrol TUNGGAL di luar baris (server-side: ganti gudang = fetch
// ulang — dimensi konteks halaman, sejajar posisi company FU95).
const applied = ref({})
const frowsRef = ref(null)
const AVAIL_FILTER_SHAPE = [
  { key: 'grup', type: 'multi' },
  { key: 'status', type: 'multi' }
]
const AVAIL_STATUS_OPTIONS = [
  { value: 'aman', label: 'Aman' },
  { value: 'menipis', label: 'Menipis' },
  { value: 'habis', label: 'Habis' }
]
const gudang = ref('')
// FU86: pola filter WorkOrderList — satu tombol Filter ber-badge + popover;
// gudang/grup/status masuk panel, pencarian tetap di toolbar. "Basis" =
// kondisi awal halaman (gudang pertama dari data) untuk hitungan badge &
// "Hapus semua filter" (konvensi FU75: satu aksi bersih)
const basis = ref({ gudang: '' })
const filterOpen = ref(false)
const diperbarui = ref('')

const data = computed(() => stockAvailabilityState.data)
const items = computed(() => data.value?.items || [])
const summary = computed(() => data.value?.summary || { total: 0, aman: 0, menipis: 0, habis: 0 })
const gudangOptions = computed(() => data.value?.warehouses || [])
const grupOptions = computed(() =>
  [...new Set(items.value.map((r) => r.item_group))].sort()
)
const amanPct = computed(() =>
  summary.value.total ? Math.round((summary.value.aman / summary.value.total) * 100) : 0
)

// FU95: filter company GLOBAL — pilihan tersimpan per-user di server; daftar
// gudang & kapasitas resep ikut tersaring (server-side). Ganti company =
// gudang di-reset (default DALAM scope company) lalu fetch ulang.
const companies = computed(() => companyFilterState.companies)
const showCompany = computed(() => showCompanyPicker(companies.value))
const companyOptions = computed(() => companySelectOptions(companies.value))
async function applyCompany(value) {
  const v = value || ''
  if (v === companyFilterState.company) return
  companyFilterState.company = v
  await saveCompanyFilter(v)
  gudang.value = '' // gudang lama mungkin di luar company baru → default server
  await reload()
}

// filter klien FU104: kode ATAU nama (cari), baris grup + status (multi:
// IN dalam field, AND antar baris — pola FU100); item per gudang kecil
const terfilter = computed(() => {
  const kata = q.value.trim().toLowerCase()
  const grup = applied.value.grup || []
  const status = applied.value.status || []
  return items.value.filter((r) => {
    if (kata && !(`${r.item_code} ${r.item_name}`.toLowerCase().includes(kata))) return false
    if (grup.length && !grup.includes(r.item_group)) return false
    if (status.length && !status.includes(r.status)) return false
    return true
  })
})

const PAGE = 10
const first = ref(0)
watch([q, applied, gudang], () => { first.value = 0 }, { deep: true })
// FU94: paginasi pindah ke paginator bawaan DataTable (sort mencakup semua
// baris terfilter, bukan per halaman) — slice `halaman` tidak lagi dipakai

// FU90: gudang server-side — pilih di popover memicu fetch ulang (data lama
// tampil sampai respons); respons default saat load/clear tidak memicu ulang
watch(gudang, (val) => {
  if (val && val !== (data.value?.warehouse || '')) loadStockAvailability(val)
})

// FU104: commit baris saat Terapkan atau panel ditutup (pola FU100 —
// komponen hidup di v-if panel, parent yang memicu sebelum unmount)
function onFilters(value) {
  const next = normalizeFilters(value, AVAIL_FILTER_SHAPE)
  if (JSON.stringify(next) === JSON.stringify(applied.value)) return
  applied.value = next
}
// FU108: "Hapus semua" = bersih TOTAL — baris draft sudah dikomit kosong
// oleh FilterRows; di sini kotak cari, gudang (dikembalikan ke default
// server — watcher gudang tidak memuat untuk nilai kosong, jadi reload
// eksplisit), dan company GLOBAL dilepas. Panel tetap terbuka.
function onClearFilters() {
  q.value = ''
  gudang.value = ''
  if (companyFilterState.company) applyCompany('')
  else reload()
}
watch(filterOpen, (open, sebelum) => {
  if (!open && sebelum) frowsRef.value?.commitIfChanged()
})
const avFilterFields = computed(() => [
  // FU107: Company = baris TUNGGAL (immediate) — nilai tetap filter GLOBAL
  // FU95 tersimpan per-user, diterapkan segera; Gudang tetap kontrol tunggal
  // server-side di bawahnya (ganti = fetch ulang)
  ...(showCompany.value
    ? [{
        key: 'company', label: 'Company', type: 'select', immediate: true,
        ariaLabel: 'Filter company',
        options: companyOptions.value
      }]
    : []),
  { key: 'grup', label: 'Item Group', type: 'multi', filter: true, placeholder: 'Pilih satu atau lebih grup', options: grupOptions.value.map((g) => ({ value: g, label: g })) },
  { key: 'status', label: 'Stock Status', type: 'multi', options: AVAIL_STATUS_OPTIONS }
])
// FU107: nilai baris immediate (bukan draft) — dari state global FU95
const immediateValues = computed(() => ({ company: companyFilterState.company }))
function onImmediate(key, value) {
  if (key === 'company') applyCompany(value)
}
// badge = baris + gudang (bila bukan default server) + company global FU95
const activeFilters = computed(() =>
  countFilters(applied.value) +
  (gudang.value !== basis.value.gudang ? 1 : 0) +
  (showCompany.value && companyFilterState.company ? 1 : 0)
)

// FU87: unduh .xlsx = laporan tampilan aktif — seluruh baris TERFILTER (bukan
// hanya 10 baris halaman) + ringkasan KPI dikirim ke endpoint server yang
// membungkusnya jadi workbook 3 sheet (angka file = angka layar). Gagal sesi
// → ke login (FU81); gagal lain ditandai kecil di samping tombol (pola FU80c)
const exportGagal = ref(false)
async function exportXlsx() {
  exportGagal.value = false
  try {
    const r = await fetch('/api/method/production_app.api.stock_availability.export_xlsx', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Frappe-CSRF-Token': window.csrf_token || ''
      },
      body: JSON.stringify({
        items: terfilter.value.map((it) => {
          // FU88: file mengikuti layar — 4 kolom qty dalam UOM tampilan (DIU,
          // 2 desimal); stok mentah stock UOM tetap dikirim utk kolom terakhir
          const f = Number(it.qty_in_pack)
          const ada = Number.isFinite(f) && f > 0 && it.display_uom && it.display_uom !== it.stock_uom
          const conv = (q) => (q == null ? null : ada ? Math.round((q / f) * 100) / 100 : q)
          return {
            item_code: it.item_code,
            item_name: it.item_name,
            item_group: it.item_group,
            stock_uom: it.stock_uom,
            uom_tampilan: ada ? it.display_uom : it.stock_uom,
            actual_qty: it.actual_qty,
            stok_diu: conv(it.actual_qty),
            reserved_diu: conv(it.reserved_qty),
            tersedia_diu: conv(it.available),
            minimum_diu: conv(it.min_stock),
            status: it.status,
            capacity_batch: it.capacity_batch,
            capacity_detail: it.capacity_detail
          }
        }),
        summary: summary.value,
        warehouse: gudang.value || data.value?.warehouse || ''
      })
    })
    if (!r.ok) {
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
    a.download = stockXlsxFilename(
      gudang.value || data.value?.warehouse,
      new Date().toISOString()
    )
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch {
    exportGagal.value = true
  }
}

// FU90: reload memakai gudang terpilih bila ada (ulang setelah gagal);
// respons tanpa argumen = gudang default server → menjadi basis badge filter
async function reload() {
  await loadStockAvailability(gudang.value)
  if (!gudang.value && data.value?.warehouse) {
    gudang.value = data.value.warehouse
    basis.value = { gudang: data.value.warehouse }
  }
  diperbarui.value = new Date().toISOString()
}
onMounted(reload)

// ---- drawer detail item (klik baris / chevron) ----
const drawerOpen = ref(false)
const itemTerpilih = ref(null)
// FU90: movement lazy per gudang|item — dimuat saat drawer dibuka bila cache
// belum ada (atau percobaan sebelumnya gagal); teks kecil selama memuat/gagal
const mvKey = (it) => `${it.warehouse || data.value?.warehouse || ''}|${it.item_code}`
const mvEntry = computed(() => (itemTerpilih.value ? stockMovementsState[mvKey(itemTerpilih.value)] || null : null))
function bukaItem(row) {
  if (!row?.item_code) return
  itemTerpilih.value = row
  drawerOpen.value = true
  const cache = stockMovementsState[mvKey(row)]
  if (!cache || cache.error) loadStockMovements(row.item_code, row.warehouse || data.value?.warehouse || '')
}

const STATUS_LABEL = { aman: 'Aman', menipis: 'Menipis', habis: 'Habis' }
const STATUS_SEVERITY = { aman: 'success', menipis: 'warn', habis: 'danger' }

// FU88: UOM tampilan = Default Inventory UOM (konvensi FU78) — qty dirender
// main(DIU)+sub(stock UOM) lewat woQtyText; tanpa DIU → stock UOM apa adanya
const unitsOf = (it) => ({
  qtyInPack: it.qty_in_pack,
  displayUom: it.display_uom,
  stockUom: it.stock_uom
})
const qtyText = (it, key) => woQtyText(it[key], unitsOf(it))
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <p class="ph-eye">Ketersediaan stock</p>
      <h1>Ketersediaan Stock</h1>
      <p class="sub">Monitoring ketersediaan stok pada {{ data?.warehouse || '…' }}.</p>
    </div>
    <div class="ph-right">
      <span v-if="diperbarui" class="ph-date">Diperbarui {{ fmtStampShort(diperbarui) }}</span>
    </div>
  </div>

  <!-- FU86: filter satu tombol gaya WorkOrderList/Stock Entry — gudang, grup,
       dan status di popover; pencarian tetap di toolbar -->
  <div class="toolbar">
    <div class="searchbox">
      <Search :size="15" :stroke-width="2" class="search-ico" />
      <input
        v-model="q"
        class="input"
        type="search"
        placeholder="Cari item code atau nama…"
        aria-label="Cari item code atau nama"
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
          <!-- FU107: Company kini baris pertama di dalam daftar filter
               (immediate — nilai tetap global FU95); Gudang menyusul sebagai
               kontrol tunggal server-side (ganti = fetch ulang) -->
          <FilterRows
            ref="frowsRef"
            :fields="avFilterFields"
            :immediate="immediateValues"
            :model-value="applied"
            @update:model-value="onFilters"
            @immediate-change="onImmediate"
            @clear="onClearFilters"
          />
          <div class="ffield" style="margin-top: 10px">
            <label>Gudang</label>
            <!-- FU104: gudang tetap kontrol TUNGGAL server-side (ganti = fetch
                 ulang) — dimensi konteks halaman, di luar baris filter -->
            <select v-model="gudang" class="select" aria-label="Filter gudang">
              <option v-for="g in gudangOptions" :key="g" :value="g">{{ g }}</option>
            </select>
          </div>
        </div>
      </Transition>
    </div>
    <button class="btn exportbtn" type="button" aria-label="Export" @click="exportXlsx">
      <FileSpreadsheet :size="14" :stroke-width="2" />
      <span class="btext">Export</span>
    </button>
    <span v-if="exportGagal" class="export-gagal" role="alert">Export gagal — coba lagi</span>
  </div>

  <div v-if="stockAvailabilityState.error" class="callout bad dash-error" role="alert">
    <p>Gagal memuat: {{ stockAvailabilityState.error }}</p>
    <Button label="Coba lagi" size="small" severity="secondary" variant="outlined" @click="reload" />
  </div>

  <template v-if="stockAvailabilityState.loading && !stockAvailabilityState.loaded">
    <section class="panel" aria-hidden="true">
      <div class="panel-body dash-skel-stack">
        <Skeleton v-for="m in 6" :key="m" width="100%" height="34px" borderRadius="6px" />
      </div>
    </section>
  </template>

  <template v-else-if="stockAvailabilityState.loaded && !stockAvailabilityState.error">
    <!-- ===== 4 kartu KPI ===== -->
    <section class="sa-kpis" aria-label="Ringkasan ketersediaan stock">
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kblue"><Boxes :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Total item</span>
        </div>
        <p class="knum">{{ fmtId(summary.total) }}</p>
        <p class="ksub">item di {{ data?.warehouse || 'gudang ini' }}</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kgreen"><CheckCircle2 :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Stock aman</span>
        </div>
        <p class="knum">{{ fmtId(summary.aman) }}</p>
        <p class="ksub">{{ amanPct }}% dari total item</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kamber"><TriangleAlert :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Stock menipis</span>
        </div>
        <p class="knum">{{ fmtId(summary.menipis) }}</p>
        <p class="ksub">Perlu perhatian</p>
      </div>
      <div class="panel dash-kpi">
        <div class="khead">
          <span class="kico kred"><PackageX :size="17" :stroke-width="2" aria-hidden="true" /></span>
          <span class="klabel">Stock habis</span>
        </div>
        <p class="knum">{{ fmtId(summary.habis) }}</p>
        <p class="ksub">Perlu segera diisi</p>
      </div>
    </section>

    <!-- ===== tabel stock bahan baku ===== -->
    <section class="panel mu-card" aria-label="Stock item">
      <div class="dcard-head an-head">
        <div>
          <p class="deye">Stock Item</p>
          <h2>Daftar Item</h2>
          <p class="dsub">{{ fmtId(terfilter.length) }} item ditampilkan dari {{ fmtId(items.length) }} total item</p>
        </div>
      </div>
      <div class="panel-body mu-tbody">
        <DataTable
          :value="terfilter"
          dataKey="item_code"
          class="dash-table mu-table sa-table"
          :rowHover="true"
          @row-click="(e) => bukaItem(e.data)"
          removableSort
          paginator
          :rows="PAGE"
          v-model:first="first"
          @sort="first = 0"
        >
          <Column field="item_code" header="Kode Item" sortable headerClass="col-kode" bodyClass="col-kode">
            <template #body="{ data: r }"><span class="mono">{{ r.item_code }}</span></template>
          </Column>
          <Column field="item_name" header="Nama Item" sortable headerClass="col-nama" bodyClass="col-nama">
            <template #body="{ data: r }">
              <span class="wo-prod">{{ r.item_name }}</span>
            </template>
          </Column>
          <Column field="item_group" header="Grup Item" sortable headerClass="col-grup" bodyClass="col-grup">
            <template #body="{ data: r }">{{ r.item_group }}</template>
          </Column>
          <Column field="actual_qty" header="Stok" sortable headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">
              <span class="wo-qty sa-qty">
                <span class="qmain">{{ qtyText(r, 'actual_qty').main }}</span>
                <span v-if="qtyText(r, 'actual_qty').sub" class="qsub">{{ qtyText(r, 'actual_qty').sub }}</span>
              </span>
            </template>
          </Column>
          <Column field="reserved_qty" header="Reserved" sortable headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">
              <span class="sa-res wo-qty sa-qty">
                <span class="qmain">{{ qtyText(r, 'reserved_qty').main }}</span>
                <span v-if="qtyText(r, 'reserved_qty').sub" class="qsub">{{ qtyText(r, 'reserved_qty').sub }}</span>
              </span>
            </template>
          </Column>
          <Column field="available" header="Tersedia" sortable headerClass="col-tersedia" bodyClass="col-tersedia">
            <template #body="{ data: r }">
              <b class="sa-avail wo-qty sa-qty">
                <span class="qmain">{{ qtyText(r, 'available').main }}</span>
                <span v-if="qtyText(r, 'available').sub" class="qsub">{{ qtyText(r, 'available').sub }}</span>
              </b>
            </template>
          </Column>
          <Column field="min_stock" header="Minimum" sortable headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">
              <span class="wo-qty sa-qty">
                <span class="qmain">{{ qtyText(r, 'min_stock').main }}</span>
                <span v-if="qtyText(r, 'min_stock').sub" class="qsub">{{ qtyText(r, 'min_stock').sub }}</span>
              </span>
            </template>
          </Column>
          <Column field="status" header="Status" sortable headerClass="col-status2" bodyClass="col-status2">
            <template #body="{ data: r }">
              <Tag :value="STATUS_LABEL[r.status]" :severity="STATUS_SEVERITY[r.status]" class="mu-pill" />
            </template>
          </Column>
          <Column field="capacity_batch" header="Kapasitas" sortable headerClass="col-kapas" bodyClass="col-kapas">
            <template #body="{ data: r }">
              <span v-if="r.capacity_batch == null">-</span>
              <span v-else :class="{ 'tone-bad': !r.capacity_batch }">{{ fmtId(r.capacity_batch) }} <small class="kuom">Batch</small></span>
            </template>
          </Column>
          <Column headerClass="col-chev" bodyClass="col-chev">
            <template #body><ChevronRight :size="15" :stroke-width="2" class="mu-chev" aria-hidden="true" /></template>
          </Column>
          <template #empty>
            <div class="empty-inset">
              <span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
              <p class="etitle">Tidak ada item yang cocok dengan filter</p>
            </div>
          </template>
        </DataTable>
      </div>
    </section>

    <p class="srcnote">
      Sumber data: Bin ERPNext (stok dan reserved; tersedia = stok − reserved), Item Reorder
      (stok minimum), BOM aktif (kapasitas batch per resep), dan Stock Ledger Entry untuk
      movement di drawer detail item. Status: habis bila tersedia ≤ 0, menipis di bawah stok
      minimum, sisanya aman. Stok, reserved, tersedia, dan minimum tampil dalam Default
      Inventory UOM item (FU78 — fallback stock UOM bila DIU kosong; angka kecil = stock UOM);
      tabel movement memakai stock UOM (ledger SLE).
    </p>
  </template>

  <!-- ===== drawer detail item ===== -->
  <Drawer v-model:visible="drawerOpen" position="right" class="sa-drawer">
    <template #header>
      <div v-if="itemTerpilih" class="sa-dhead">
        <h3>{{ itemTerpilih.item_name }}</h3>
        <p class="sa-dcode"><span class="mono">{{ itemTerpilih.item_code }}</span> · {{ itemTerpilih.warehouse }}</p>
      </div>
    </template>
    <template v-if="itemTerpilih">
      <div class="sa-tiles">
        <div class="sa-tile">
          <label>Stok saat ini</label>
          <b>
            <span class="qmain">{{ qtyText(itemTerpilih, 'actual_qty').main }}</span>
            <small v-if="qtyText(itemTerpilih, 'actual_qty').sub" class="qsub">{{ qtyText(itemTerpilih, 'actual_qty').sub }}</small>
          </b>
        </div>
        <div class="sa-tile">
          <label>Reserved</label>
          <b class="sa-res">
            <span class="qmain">{{ qtyText(itemTerpilih, 'reserved_qty').main }}</span>
            <small v-if="qtyText(itemTerpilih, 'reserved_qty').sub" class="qsub">{{ qtyText(itemTerpilih, 'reserved_qty').sub }}</small>
          </b>
        </div>
        <div class="sa-tile utama">
          <label>Tersedia</label>
          <b>
            <span class="qmain">{{ qtyText(itemTerpilih, 'available').main }}</span>
            <small v-if="qtyText(itemTerpilih, 'available').sub" class="qsub">{{ qtyText(itemTerpilih, 'available').sub }}</small>
          </b>
        </div>
        <div class="sa-tile">
          <label>Stok minimum</label>
          <b>
            <span class="qmain">{{ qtyText(itemTerpilih, 'min_stock').main }}</span>
            <small v-if="qtyText(itemTerpilih, 'min_stock').sub" class="qsub">{{ qtyText(itemTerpilih, 'min_stock').sub }}</small>
          </b>
        </div>
      </div>

      <p class="deye sa-sect">Production capacity</p>
      <div class="sa-cap">
        <div v-for="c in itemTerpilih.capacity_detail || []" :key="c.product" class="sa-cap-row">
          <span>{{ c.product }}</span>
          <b :class="{ 'tone-bad': !c.batches }">{{ fmtId(c.batches) }} Batch</b>
        </div>
      </div>
      <p v-if="itemTerpilih.capacity_batch === 0" class="sa-cap-note">
        Tidak ada bahan tersedia untuk produksi — segera ajukan pengisian ulang.
      </p>

      <p class="deye sa-sect">Stock movement</p>
      <p v-if="!mvEntry || mvEntry.loading" class="sa-cap-note">Memuat movement…</p>
      <p v-else-if="mvEntry.error" class="sa-cap-note">Gagal memuat movement</p>
      <DataTable v-else :value="mvEntry.data || []" dataKey="referensi" class="dash-table sa-mv">
        <Column header="Tanggal" headerClass="col-tgl" bodyClass="col-tgl">
          <template #body="{ data: m }">{{ tanggalPendek(m.tanggal) }}</template>
        </Column>
        <Column header="Transaksi" headerClass="col-mvjenis" bodyClass="col-mvjenis">
          <template #body="{ data: m }">{{ m.jenis }}</template>
        </Column>
        <Column header="Referensi" headerClass="col-se" bodyClass="col-se">
          <template #body="{ data: m }"><span class="mono">{{ m.referensi }}</span></template>
        </Column>
        <Column header="Masuk" headerClass="col-angka" bodyClass="col-angka">
          <template #body="{ data: m }">{{ m.masuk ? `${fmtId(m.masuk)} ${itemTerpilih.stock_uom}` : '-' }}</template>
        </Column>
        <Column header="Keluar" headerClass="col-angka" bodyClass="col-angka">
          <template #body="{ data: m }">{{ m.keluar ? `${fmtId(m.keluar)} ${itemTerpilih.stock_uom}` : '-' }}</template>
        </Column>
        <Column header="Saldo" headerClass="col-angka" bodyClass="col-angka">
          <template #body="{ data: m }"><b>{{ fmtId(m.saldo) }} <small class="kuom">{{ itemTerpilih.stock_uom }}</small></b></template>
        </Column>
        <template #empty>
          <p class="dash-none">Belum ada transaksi stock untuk item ini</p>
        </template>
      </DataTable>
    </template>
  </Drawer>
</template>

<script setup>
// FU83: halaman "Ketersediaan Stock" (#/ketersediaan-stock) — monitoring bahan
// baku di Gudang Produksi untuk PPIC/Produksi/Gudang; pertanyaan inti: apakah
// bahan tersedia dan cukup untuk kebutuhan produksi? Data MASIH MOCK (FU83)
// dari store.loadStockAvailability dengan struktur item = respons ERPNext
// nanti (Bin actual/reserved + Item grup/uom + Stock Ledger Entry movement) —
// penukaran ke endpoint server tidak mengubah halaman. Status diturunkan dari
// angka di dataset (dashboard.stockStatus): habis ≤ 0, menipis < minimum,
// sisanya aman. Tersedia (available) = stok − reserved, ditonjolkan di tabel.
// Kapasitas produksi = estimasi batch per resep dari data (belum kalkulasi BOM).
import { computed, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Drawer from 'primevue/drawer'
import Paginator from 'primevue/paginator'
import Skeleton from 'primevue/skeleton'
import Tag from 'primevue/tag'
import {
  Boxes, CheckCircle2, ChevronRight, Filter, PackageX, Search, SearchX, TriangleAlert
} from 'lucide-vue-next'
import { stockAvailabilityState, loadStockAvailability } from './store.js'
import { fmtId, fmtStampShort } from './format.js'
import { tanggalPendek } from './dashboard.js'

const q = ref('')
const grup = ref('ALL')
const status = ref('ALL')
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

// filter klien (mock): kode ATAU nama, grup, status — saat integrasi nanti
// parameter yang sama dikirim ke endpoint
const terfilter = computed(() => {
  const kata = q.value.trim().toLowerCase()
  return items.value.filter((r) => {
    if (kata && !(`${r.item_code} ${r.item_name}`.toLowerCase().includes(kata))) return false
    if (grup.value !== 'ALL' && r.item_group !== grup.value) return false
    if (status.value !== 'ALL' && r.status !== status.value) return false
    return true
  })
})

const PAGE = 10
const first = ref(0)
watch([q, grup, status, gudang], () => { first.value = 0 })
const halaman = computed(() => terfilter.value.slice(first.value, first.value + PAGE))

function clearFilters() {
  q.value = ''
  grup.value = 'ALL'
  status.value = 'ALL'
  gudang.value = basis.value.gudang
  filterOpen.value = false
}

const activeFilters = computed(() =>
  (grup.value !== 'ALL') +
  (status.value !== 'ALL') +
  (gudang.value !== basis.value.gudang)
)

async function reload() {
  await loadStockAvailability()
  if (!gudang.value && data.value?.warehouses?.length) {
    gudang.value = data.value.warehouses[0]
    basis.value = { gudang: gudang.value }
  }
  diperbarui.value = new Date().toISOString()
}
onMounted(reload)

// ---- drawer detail item (klik baris / chevron) ----
const drawerOpen = ref(false)
const itemTerpilih = ref(null)
function bukaItem(row) {
  if (!row?.item_code) return
  itemTerpilih.value = row
  drawerOpen.value = true
}

const STATUS_LABEL = { aman: 'Aman', menipis: 'Menipis', habis: 'Habis' }
const STATUS_SEVERITY = { aman: 'success', menipis: 'warn', habis: 'danger' }
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <p class="ph-eye">Ketersediaan stock</p>
      <h1>Ketersediaan Stock Bahan Baku</h1>
      <p class="sub">Monitoring ketersediaan bahan baku pada {{ data?.warehouse || 'Gudang Produksi' }}.</p>
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
          <div class="ffield">
            <label>Gudang</label>
            <select v-model="gudang" class="select" aria-label="Filter gudang">
              <option v-for="g in gudangOptions" :key="g" :value="g">{{ g }}</option>
            </select>
          </div>
          <div class="ffield">
            <label>Item Group</label>
            <select v-model="grup" class="select" aria-label="Filter item group">
              <option value="ALL">Semua Item Group</option>
              <option v-for="g in grupOptions" :key="g" :value="g">{{ g }}</option>
            </select>
          </div>
          <div class="ffield">
            <label>Stock Status</label>
            <select v-model="status" class="select" aria-label="Filter status stock">
              <option value="ALL">Semua Status</option>
              <option value="aman">Aman</option>
              <option value="menipis">Menipis</option>
              <option value="habis">Habis</option>
            </select>
          </div>
          <button class="linkbtn filter-clear" type="button" @click="clearFilters">Hapus semua filter</button>
        </div>
      </Transition>
    </div>
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
          <span class="klabel">Total bahan baku</span>
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
    <section class="panel mu-card" aria-label="Stock bahan baku">
      <div class="dcard-head an-head">
        <div>
          <p class="deye">Stock bahan baku</p>
          <h2>Daftar Bahan Baku</h2>
          <p class="dsub">{{ fmtId(terfilter.length) }} item ditampilkan dari {{ fmtId(items.length) }} total item</p>
        </div>
      </div>
      <div class="panel-body mu-tbody">
        <DataTable
          :value="halaman"
          dataKey="item_code"
          class="dash-table mu-table sa-table"
          :rowHover="true"
          @row-click="(e) => bukaItem(e.data)"
        >
          <Column header="Kode Item" headerClass="col-kode" bodyClass="col-kode">
            <template #body="{ data: r }"><span class="mono">{{ r.item_code }}</span></template>
          </Column>
          <Column header="Nama Item" headerClass="col-nama" bodyClass="col-nama">
            <template #body="{ data: r }">
              <span class="wo-prod">{{ r.item_name }}</span>
            </template>
          </Column>
          <Column header="Grup Item" headerClass="col-grup" bodyClass="col-grup">
            <template #body="{ data: r }">{{ r.item_group }}</template>
          </Column>
          <Column header="Stok" headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">{{ fmtId(r.actual_qty) }} <small class="kuom">{{ r.stock_uom }}</small></template>
          </Column>
          <Column header="Reserved" headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">
              <span class="sa-res">{{ fmtId(r.reserved_qty) }} <small class="kuom">{{ r.stock_uom }}</small></span>
            </template>
          </Column>
          <Column header="Tersedia" headerClass="col-tersedia" bodyClass="col-tersedia">
            <template #body="{ data: r }">
              <b class="sa-avail">{{ fmtId(r.available) }} <small class="kuom">{{ r.stock_uom }}</small></b>
            </template>
          </Column>
          <Column header="UOM" headerClass="col-uom" bodyClass="col-uom">
            <template #body="{ data: r }">{{ r.stock_uom }}</template>
          </Column>
          <Column header="Minimum" headerClass="col-angka" bodyClass="col-angka">
            <template #body="{ data: r }">{{ fmtId(r.min_stock) }} <small class="kuom">{{ r.stock_uom }}</small></template>
          </Column>
          <Column header="Status" headerClass="col-status2" bodyClass="col-status2">
            <template #body="{ data: r }">
              <Tag :value="STATUS_LABEL[r.status]" :severity="STATUS_SEVERITY[r.status]" class="mu-pill" />
            </template>
          </Column>
          <Column header="Kapasitas" headerClass="col-kapas" bodyClass="col-kapas">
            <template #body="{ data: r }">
              <span :class="{ 'tone-bad': !r.capacity_batch }">{{ fmtId(r.capacity_batch) }} <small class="kuom">Batch</small></span>
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
        <Paginator
          v-if="terfilter.length > PAGE"
          :rows="PAGE"
          :totalRecords="terfilter.length"
          v-model:first="first"
          class="dash-pager"
          aria-label="Halaman daftar bahan baku"
        >
          <template #start><span /></template>
          <template #end><span /></template>
          <template #previcon><span aria-hidden="true">‹</span></template>
          <template #nexticon><span aria-hidden="true">›</span></template>
        </Paginator>
      </div>
    </section>

    <p class="srcnote">
      Sumber data: mock FU83 — saat integrasi ERPNext dibaca dari Bin (actual/reserved), Item
      (grup, UOM), dan Stock Ledger Entry (movement) per gudang. Tersedia = stok − reserved.
      Status: habis bila tersedia ≤ 0, menipis di bawah stok minimum, sisanya aman. Kapasitas
      produksi = estimasi batch dari resep terdaftar (belum kalkulasi BOM nyata).
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
          <b>{{ fmtId(itemTerpilih.actual_qty) }} <small>{{ itemTerpilih.stock_uom }}</small></b>
        </div>
        <div class="sa-tile">
          <label>Reserved</label>
          <b class="sa-res">{{ fmtId(itemTerpilih.reserved_qty) }} <small>{{ itemTerpilih.stock_uom }}</small></b>
        </div>
        <div class="sa-tile utama">
          <label>Tersedia</label>
          <b>{{ fmtId(itemTerpilih.available) }} <small>{{ itemTerpilih.stock_uom }}</small></b>
        </div>
        <div class="sa-tile">
          <label>Stok minimum</label>
          <b>{{ fmtId(itemTerpilih.min_stock) }} <small>{{ itemTerpilih.stock_uom }}</small></b>
        </div>
      </div>

      <p class="deye sa-sect">Production capacity</p>
      <div class="sa-cap">
        <div v-for="c in itemTerpilih.capacity_detail" :key="c.product" class="sa-cap-row">
          <span>{{ c.product }}</span>
          <b :class="{ 'tone-bad': !c.batches }">{{ fmtId(c.batches) }} Batch</b>
        </div>
      </div>
      <p v-if="!itemTerpilih.capacity_batch" class="sa-cap-note">
        Tidak ada bahan tersedia untuk produksi — segera ajukan pengisian ulang.
      </p>

      <p class="deye sa-sect">Stock movement</p>
      <DataTable :value="itemTerpilih.movements" dataKey="referensi" class="dash-table sa-mv">
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

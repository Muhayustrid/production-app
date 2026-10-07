<script setup>
// Halaman riwayat Form Order (FU52): form buat pindah ke halaman sendiri
// (#/form-order/baru, FormOrderCreate.vue) — tombol toolbar menavigasi ke
// sana; pesan sukses ber-nama MR ditinggalkan formCreate via
// formOrderState.justSaved dan dibaca di sini saat mount.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ArrowDown, Filter, Inbox, Plus } from 'lucide-vue-next'
import { PAGE_SIZE_OPTIONS, cancelFormOrder, companyFilterState, formOrders, formOrderState, loadFormOrders, normalizePageSize, retryFormOrderAttachment, saveCompanyFilter, uiTopLoading } from './store.js'
import { companySelectOptions, showCompanyPicker } from './company-filter.js'
import { foItemsText, foStatusMeta } from './form-order.js'
import { countFilters, normalizeFilters } from './filter-rows.js'
import FilterRows from './FilterRows.vue'
import { nextSortDir, sortRows } from './table-sort.js'

const savedMsg = ref('')

// FU105: filter riwayat ala ERPNext — Status & Item multi-nilai + rentang
// Dibutuhkan; sepenuhnya KLIEN (riwayat dimuat penuh). Company tetap filter
// global FU95 di luar baris.
const applied = ref({})
const frowsRef = ref(null)
const FO_FILTER_SHAPE = [
  { key: 'status', type: 'multi' },
  { key: 'item', type: 'multi' },
  { key: 'dibutuhkan', type: 'range' }
]
const FO_STATUS_OPTIONS = [
  { value: 'menunggu', label: 'Menunggu' },
  { value: 'terkirim', label: 'Terkirim' },
  { value: 'draf', label: 'Draf' },
  { value: 'batal', label: 'Dibatalkan' }
]
// opsi item dari item pesanan yang termuat (pola distinctItems SE)
const foItemOptions = computed(() => {
  const seen = new Map()
  for (const o of formOrders) {
    for (const it of o.items || []) {
      if (it.name && !seen.has(it.name)) seen.set(it.name, it.code || '')
    }
  }
  return [...seen.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, code]) => ({ value: name, label: code && code !== name ? `${code} · ${name}` : name }))
})
const foFilterFields = computed(() => [
  { key: 'status', label: 'Status', type: 'multi', options: FO_STATUS_OPTIONS },
  { key: 'item', label: 'Item', type: 'multi', filter: true, placeholder: 'Pilih satu atau lebih item', options: foItemOptions.value },
  { key: 'dibutuhkan', label: 'Dibutuhkan', type: 'range', placeholder: 'Semua tanggal' }
])
// FU95: filter company GLOBAL — panel filter gaya WorkOrderList (satu tombol
// Filter ber-badge + popover); pilihan tersimpan per-user di server sehingga
// riwayat tetap tersaring setelah refresh / pindah halaman / tutup browser
const filterOpen = ref(false)
const companies = computed(() => companyFilterState.companies)
const showCompany = computed(() => showCompanyPicker(companies.value))
const companyOptions = computed(() => companySelectOptions(companies.value))
const activeFilters = computed(() =>
  countFilters(applied.value) + (showCompany.value && companyFilterState.company ? 1 : 0)
)
async function applyCompany(value) {
  const v = value || ''
  if (v === companyFilterState.company) return
  companyFilterState.company = v
  foPage.value = 1 // FU98: daftar berganti → kembali halaman pertama
  await saveCompanyFilter(v)
  await loadFormOrders()
}
// FU105: commit baris saat Terapkan atau panel ditutup (pola FU100 —
// komponen hidup di v-if panel, parent yang memicu sebelum unmount)
function onFilters(value) {
  const next = normalizeFilters(value, FO_FILTER_SHAPE)
  if (JSON.stringify(next) === JSON.stringify(applied.value)) return
  applied.value = next
}
watch(filterOpen, (open, sebelum) => {
  if (!open && sebelum) frowsRef.value?.commitIfChanged()
})

// FU94: sort 3-klik riwayat (client-side — daftar dimuat penuh)
const foSortKey = ref('')
const foSortDir = ref('')
const foSortAccessors = {
  dokumen: (o) => o.materialRequest,
  dibutuhkan: (o) => o.scheduleDate,
  owner: (o) => o.ownerName,
  status: (o) => foStatusMeta(o.status).label,
  catatan: (o) => o.note,
}
function foSetSort(key) {
  if (foSortKey.value !== key) { foSortKey.value = key; foSortDir.value = 'asc' }
  else {
    foSortDir.value = nextSortDir(foSortDir.value)
    if (!foSortDir.value) foSortKey.value = '' // klik ke-3 = normal: ikon header ikut hilang
  }
}
// FU105: baris filter klien — status/item array (IN dalam field, AND antar
// baris); rentang Dibutuhkan dari scheduleDate, baris tanpa tanggal
// dikecualikan saat rentang aktif (pola filter SE)
const foFiltered = computed(() => {
  const status = applied.value.status || []
  const item = applied.value.item || []
  const dari = applied.value.dibutuhkan?.dari || ''
  const sampai = applied.value.dibutuhkan?.sampai || ''
  return formOrders.filter((o) => {
    if (status.length && !status.includes(o.status)) return false
    if (item.length && !(o.items || []).some((i) => item.includes(i.name))) return false
    if (dari || sampai) {
      const day = (o.scheduleDate || '').slice(0, 10)
      if (!day) return false
      if (dari && day < dari) return false
      if (sampai && day > sampai) return false
    }
    return true
  })
})
const foSorted = computed(() =>
  sortRows(foFiltered.value, foSortKey.value && foSortAccessors[foSortKey.value], foSortDir.value)
)

// FU98: pagination client-side — daftar dimuat penuh (sort FU94 tetap atas
// daftar penuh), halaman hanya memotong hasil sort. Bar ala WorkOrderList.
const foPageSize = ref(PAGE_SIZE_OPTIONS[0])
const foPage = ref(1)
const foTotalPages = computed(() => Math.max(1, Math.ceil(foSorted.value.length / foPageSize.value)))
const foPaged = computed(() => {
  const page = Math.min(foPage.value, foTotalPages.value) // daftar menyusut → halaman terakhir tetap valid
  return foSorted.value.slice((page - 1) * foPageSize.value, page * foPageSize.value)
})
function foSetPage(page) { foPage.value = Math.min(Math.max(1, page), foTotalPages.value) }
function foSetPageSize(value) {
  foPageSize.value = normalizePageSize(value)
  foPage.value = 1
}
watch([foSortKey, foSortDir, applied], () => { foPage.value = 1 }, { deep: true })
// FU105: pesan kosong membedakan "belum ada" vs "terfilter habis"
const foFilteredOut = computed(() => !foFiltered.value.length && countFilters(applied.value) > 0)

// FU98: dialog detail baca-saja — klik baris riwayat; Batalkan (status
// menunggu) membuka dialog konfirmasi yang sudah ada.
const dlgDetail = ref(null)
const detail = ref(null)
function openDetail(id) {
  detail.value = formOrders.find((o) => o.id === id) || null
  if (detail.value) nextTick(() => dlgDetail.value.showModal())
}
function closeDetail() {
  dlgDetail.value.close()
  detail.value = null
}
function cancelFromDetail() {
  const id = detail.value?.id
  closeDetail()
  if (id) openCancel(id)
}

function goCreate() {
  window.location.hash = '#/form-order/baru'
}

// ---- batalkan (pembuat / manager; guard di server) ----
const dlgCancel = ref(null)
const cancelTarget = ref(null)
const cancelError = ref('')

function openCancel(id) {
  cancelTarget.value = formOrders.find((o) => o.id === id) || null
  cancelError.value = ''
  if (cancelTarget.value) nextTick(() => dlgCancel.value.showModal())
}
function closeCancel() {
  dlgCancel.value.close()
  cancelTarget.value = null
}
async function confirmCancel() {
  cancelError.value = ''
  try {
    await cancelFormOrder(cancelTarget.value.id)
    closeCancel()
  } catch (e) {
    cancelError.value = e.message
  }
}

async function retryAttachment() {
  const issue = formOrderState.attachmentIssue
  try {
    const uploaded = await retryFormOrderAttachment()
    savedMsg.value = `${uploaded} lampiran berhasil ditambahkan ke ${issue.materialRequest}.`
  } catch { /* pesan rinci tetap tersimpan pada attachmentIssue */ }
}

onMounted(async () => {
  if (formOrderState.justSaved) {
    savedMsg.value = formOrderState.justSaved
      ? `Form Order ${formOrderState.justSaved} terkirim.`
      : 'Form Order terkirim.'
    formOrderState.justSaved = null
  }
  uiTopLoading.active = true
  try {
    await Promise.all([loadFormOrders()])
  } finally {
    uiTopLoading.active = false
  }
})
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Form Order</h1>
      <p class="sub">Permintaan barang dari gudang.</p>
    </div>
    <div class="ph-date">{{ new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }}</div>
  </div>

  <div v-if="formOrderState.error" class="appfoot" style="color:#b3261e">Gagal memuat: {{ formOrderState.error }} — <a href="#" @click.prevent="loadFormOrders()">coba lagi</a></div>

  <div v-if="formOrderState.attachmentIssue" class="callout bad fo-attachment-warning" role="alert">
    <div>
      <strong>{{ formOrderState.attachmentIssue.materialRequest }} sudah dibuat, tetapi {{ formOrderState.attachmentIssue.files.length }} lampiran masih menunggu unggah.</strong>
      <p>{{ formOrderState.attachmentIssue.message }}</p>
      <a :href="'/app/material-request/' + encodeURIComponent(formOrderState.attachmentIssue.materialRequest)" target="_blank" rel="noopener noreferrer">Buka Material Request di ERPNext</a>
    </div>
    <button class="btn btn-sm" :disabled="!!formOrderState.pending" @click="retryAttachment">
      {{ formOrderState.pending === 'attach_form_order' ? 'Mengunggah…' : 'Ulangi Unggah Lampiran' }}
    </button>
  </div>

  <!-- FU52: tombol menavigasi ke halaman buat (bukan panel toggle);
       FU95: + filter company global gaya WorkOrderList/Stock Entry -->
  <div class="toolbar fo-actions">
    <transition name="pop" mode="out-in">
      <span v-if="savedMsg" class="why fo-saved" role="status">{{ savedMsg }}</span>
    </transition>
    <div class="filterwrap">
      <button class="btn filterbtn" :class="{ active: activeFilters }" aria-label="Filter" @click="filterOpen = !filterOpen">
        <Filter :size="14" :stroke-width="2" />
        <span class="btext">Filter</span>
        <span v-if="activeFilters" class="filtercount">{{ activeFilters }}</span>
      </button>
      <div v-if="filterOpen" class="popoverlay" @click="filterOpen = false"></div>
      <Transition name="pop">
        <div v-if="filterOpen" class="filterpanel">
          <div v-if="showCompany" class="ffield">
            <label>Company</label>
            <select class="select" :value="companyFilterState.company" aria-label="Filter company" @change="applyCompany($event.target.value)">
              <option v-for="o in companyOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <!-- FU105: baris filter ala ERPNext — Status & Item multi-nilai +
               rentang Dibutuhkan; draft dikomit saat Terapkan atau panel ditutup -->
          <FilterRows ref="frowsRef" :fields="foFilterFields" :model-value="applied" @update:model-value="onFilters" />
        </div>
      </Transition>
    </div>
    <button class="btn btn-primary" @click="goCreate">
      <Plus :size="14" :stroke-width="2" />
      Buat Form Order
    </button>
  </div>

  <!-- FU51/52: riwayat memakai pola kartu Work Order (wo-body/wo-thead/wo-row,
       reuse kelas FU49); FU98: klik baris = dialog detail, aksi Batalkan di
       kolom akhir (stop propagation) -->
  <div class="wo-body fo-history">
    <div class="wo-thead" v-if="foSorted.length">
      <button type="button" class="th-sort" :class="{ on: foSortKey === 'dokumen', asc: foSortDir === 'asc' }" @click="foSetSort('dokumen')">
        Dokumen<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <span>Item</span>
      <button type="button" class="th-sort" :class="{ on: foSortKey === 'dibutuhkan', asc: foSortDir === 'asc' }" @click="foSetSort('dibutuhkan')">
        Dibutuhkan<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <button type="button" class="th-sort" :class="{ on: foSortKey === 'owner', asc: foSortDir === 'asc' }" @click="foSetSort('owner')">
        Dibuat oleh<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <button type="button" class="th-sort" :class="{ on: foSortKey === 'status', asc: foSortDir === 'asc' }" @click="foSetSort('status')">
        Status<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <button type="button" class="th-sort" :class="{ on: foSortKey === 'catatan', asc: foSortDir === 'asc' }" @click="foSetSort('catatan')">
        Catatan<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
      </button>
      <span></span>
    </div>

    <div v-for="o in foPaged" :key="o.id" class="wo-row fo-hist-row" tabindex="0"
         @click="openDetail(o.id)" @keydown.enter.self.prevent="openDetail(o.id)">
      <span class="wo-id c-doc">
        {{ o.materialRequest }}
        <small v-if="o.stockEntry" class="mono">{{ o.stockEntry }}</small>
      </span>
      <span class="wo-prod c-item">
        {{ foItemsText(o) }}
        <small>{{ o.fromWarehouse || '-' }} → {{ o.toWarehouse || '-' }}</small>
      </span>
      <span class="c-date">{{ o.scheduleDate || '-' }}</span>
      <span class="c-owner">{{ o.ownerName }}</span>
      <span class="c-status"><span class="chip" :class="foStatusMeta(o.status).cls">{{ foStatusMeta(o.status).label }}</span></span>
      <span class="c-note">{{ o.note || '-' }}</span>
      <span class="c-act">
        <button v-if="o.status === 'menunggu'" class="btn btn-sm" :disabled="!!formOrderState.pending" @click.stop="openCancel(o.id)">Batalkan</button>
      </span>
    </div>

    <div v-if="!foPaged.length" class="empty-inset">
      <span class="eico"><Inbox :size="19" :stroke-width="1.8" /></span>
      <p class="etitle">{{ foFilteredOut ? 'Tidak ada Form Order untuk filter ini' : 'Belum ada Form Order' }}</p>
      <p class="ehint">{{ foFilteredOut ? 'Ubah filter atau tekan Hapus semua filter di panel.' : 'Tekan "Buat Form Order" untuk menambah permintaan.' }}</p>
    </div>
  </div>

  <!-- FU98: pagination client-side ala WorkOrderList — disembunyikan bila
       muat dalam satu halaman -->
  <div v-if="foSorted.length > foPageSize" class="pagination-bar pagination-footer">
    <label class="page-size-control">
      <span>Tampilkan</span>
      <select class="select" :value="foPageSize" aria-label="Jumlah Form Order per halaman" @change="foSetPageSize($event.target.value)">
        <option v-for="size in PAGE_SIZE_OPTIONS" :key="size" :value="size">{{ size }}</option>
      </select>
    </label>
    <div class="pagination-buttons">
      <button class="btn btn-sm" :disabled="foPage <= 1" @click="foSetPage(foPage - 1)">‹ Sebelumnya</button>
      <button class="btn btn-sm" :disabled="foPage >= foTotalPages" @click="foSetPage(foPage + 1)">Berikutnya ›</button>
    </div>
  </div>

  <!-- FU98: detail baca-saja — klik baris riwayat; Batalkan (menunggu) lewat
       dialog konfirmasi yang sama -->
  <dialog ref="dlgDetail" class="dialog dialog-wide" aria-labelledby="fo-detail-title" @click.self="closeDetail">
    <template v-if="detail">
      <header class="dlg-head">
        <div class="dlg-hgroup">
          <h3 id="fo-detail-title">Detail Form Order</h3>
          <p class="dlg-sub fo-detail-sub">
            <strong class="mono">{{ detail.materialRequest }}</strong>
            <span class="chip" :class="foStatusMeta(detail.status).cls">{{ foStatusMeta(detail.status).label }}</span>
          </p>
        </div>
        <!-- elemen fokus pertama saat showModal (div tabel scrollable
             ikut focusable di Chromium); sekaligus jalan tutup untuk tablet -->
        <button type="button" class="btn btn-sm dlg-x" aria-label="Tutup detail" @click="closeDetail">×</button>
      </header>
      <div class="dlg-context">
        <div class="sum-row"><span class="k">Dibutuhkan</span><span class="v">{{ detail.scheduleDate || '-' }}</span></div>
        <div class="sum-row"><span class="k">Dibuat oleh</span><span class="v">{{ detail.ownerName }}</span></div>
        <div class="sum-row"><span class="k">Dibuat</span><span class="v mono">{{ (detail.createdAt || '').slice(0, 16) }}</span></div>
        <div class="sum-row"><span class="k">Rute</span><span class="v">{{ detail.fromWarehouse || '-' }} → {{ detail.toWarehouse || '-' }}</span></div>
        <div class="sum-row"><span class="k">Catatan</span><span class="v">{{ detail.note || '-' }}</span></div>
        <div v-if="detail.stockEntry" class="sum-row"><span class="k">Stock Entry</span><span class="v mono">{{ detail.stockEntry }}</span></div>
      </div>
      <div class="tbl-wrap fo-detail-wrap">
        <table class="datatable fo-grid fo-detail-items">
          <thead>
            <tr>
              <th>Item</th>
              <th class="fo-c-qty">Qty</th>
              <th class="fo-c-uom">Satuan</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(it, i) in detail.items" :key="i">
              <td>{{ it.name }} <small class="mono">{{ it.code }}</small></td>
              <td class="fo-c-qty">{{ it.qty }}</td>
              <td class="fo-c-uom">{{ it.uom || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint fo-detail-link">
        <a :href="'/app/material-request/' + encodeURIComponent(detail.id)" target="_blank" rel="noopener noreferrer">Buka Material Request di ERPNext</a>
      </p>
      <div class="dlg-actions">
        <button v-if="detail.status === 'menunggu'" class="btn" @click="cancelFromDetail">Batalkan Form Order</button>
        <button class="btn btn-primary" @click="closeDetail">Tutup</button>
      </div>
    </template>
  </dialog>

  <dialog ref="dlgCancel" class="dialog" @click.self="closeCancel">
    <template v-if="cancelTarget">
      <h3>Batalkan Form Order?</h3>
      <p>
        {{ cancelTarget.materialRequest }} — {{ foItemsText(cancelTarget) }} akan dibatalkan
        selama belum diproses gudang.
      </p>
      <p v-if="cancelError" class="err" role="alert">{{ cancelError }}</p>
      <p v-if="formOrderState.pending === 'cancel_form_order'" role="status">Menyimpan…</p>
      <div class="dlg-actions">
        <button class="btn" :disabled="!!formOrderState.pending" @click="closeCancel">Kembali</button>
        <button class="btn btn-primary" :disabled="!!formOrderState.pending" @click="confirmCancel">Ya, Batalkan</button>
      </div>
    </template>
  </dialog>
</template>

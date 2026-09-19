<script setup>
// Papan Stock Entry — produksi-only (FU48): seluruh UI aksi gudang (buat /
// batalkan request, pilih aksi multi-role, drag & drop, tab Form Order di
// tampilan tabel) dihapus. User gudang-only dialihkan ke Desk oleh server
// (www/production_workspace.py); endpoint gudang tetap hidup, SPA hanya berhenti
// memanggilnya. Lane Cold Storage kini baca-saja (konteks stok, kartu inert).
// Produksi: klik kartu/baris request → form kirim Stock Entry (FU47, satu
// jalur server: send_handover membuat + submit SE Material Transfer via mapper
// native); baris Terkirim → detail baca-saja. Default view Tabel.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  handoverBoard, handoverLots, handoverRequests, handoverState,
  listPreferencesState, loadBoard, lotAvailablePcs, lotForWo, lotRemainingPcs, lotReservedPcs,
  normalizePageSize, PAGE_SIZE_OPTIONS, saveListPreferences, savedListPreferences, sendHandover
} from './store.js'
import { fmtInt, qtyMain } from './format.js'
import { handoverCard } from './handover-card.js'
import { boardMatch } from './handover-search.js'
import { rowClickAction, seRouteLabel } from './handover-se.js'
import { boxAllocationText } from './handover-box.js'
import { laneStatusMeta } from './form-order.js'
import {
  CheckCircle2, ClipboardList, Filter, Inbox, KanbanSquare,
  Search, Snowflake, Table2, Truck
} from 'lucide-vue-next'

const isProduksi = computed(() => !!handoverBoard.roles.is_produksi)

// ---- papan: 3 lane (T35), lot Cold Storage FIFO (urutan dari server) ----
const lanes = [
  { key: 'cold', title: 'Cold Storage', icon: Snowflake, empty: 'Belum ada lot' },
  { key: 'request', title: 'Request Gudang', icon: ClipboardList, empty: 'Belum ada request' },
  { key: 'kirim', title: 'Terkirim', icon: CheckCircle2, tone: 'ok', empty: 'Belum ada terkirim' }
]

// FU29: peringatan dini — stok batch/pool di GUDANG ASAL RUTE kurang dari qty
const routeWarn = (r) => (r.routeAvailable != null && r.requestedQtyPcs > r.routeAvailable)
  ? `Stok di ${r.fromWarehouse || 'gudang asal'} tinggal ${fmtInt(r.routeAvailable)} ${r.stockUom || 'Pcs'}`
  : ''

// ---- kartu: sumber tampilan (selalu turunan payload board) ----
// FU48: semua kartu inert kecuali request aktif — lot Cold Storage konteks
// stok baca-saja, kartu Terkirim riwayat.
function lotCard(lot) {
  const base = {
    kind: 'lot', ref: lot.workOrder, key: lot.workOrder,
    live: false,
    name: lot.item
  }
  if (lot.unsupported) {
    return {
      ...base,
      workOrder: lot.workOrder,
      document: '',
      batch: '',
      adonan: '',
      quantityLabel: 'Tidak didukung',
      quantity: '—',
      timestampLabel: '',
      timestamp: '',
      box: '',
      note: lot.unsupportedReason
    }
  }
  const reserved = lotReservedPcs(lot)
  return {
    ...base,
    ...handoverCard({
      workOrder: lot.workOrder,
      batch: lot.batch,
      adonan: lot.adonanKe,
      quantity: lot.producedQty,
      quantityLabel: 'Hasil WO',
      timestampLabel: 'Selesai',
      timestamp: lot.completedAt || lot.enteredAt,
      units: lot,
      box: null
    }),
    note: lot.batchless
      ? `Stok item digabung${reserved > 0 ? ` · tertahan ${fmtInt(reserved)} PCS` : ''}`
      : reserved > 0
        ? `Fisik ${fmtInt(lotRemainingPcs(lot))} PCS · tertahan ${fmtInt(reserved)} PCS`
        : ''
  }
}

function reqCard(r) {
  const lot0 = lotForWo(r.workOrder)
  const stopped = r.flag === 'stopped'
  return {
    kind: 'request', ref: r.id, key: r.id,
    live: !stopped,
    name: r.item,
    ...handoverCard({
      workOrder: r.workOrder,
      document: r.materialRequest,
      batch: r.batch,
      adonan: r.adonanKe ?? lot0?.adonanKe,
      quantity: r.requestedQtyPcs,
      quantityLabel: 'Diminta',
      timestampLabel: 'Waktu',
      timestamp: r.createdAt,
      units: lot0 || r,
      box: boxAllocationText(r) || undefined
    }),
    note: [stopped ? 'Dihentikan di Desk. Aktifkan kembali sebelum dilanjutkan.' : '', routeWarn(r)]
      .filter(Boolean).join(' · ')
  }
}

function doneCard(r) {
  const lot0 = lotForWo(r.workOrder)
  return {
    kind: 'done', ref: r.id, key: r.id,
    live: false,
    name: r.item,
    ...handoverCard({
      workOrder: r.workOrder,
      document: r.stockEntry,
      batch: r.batch,
      adonan: r.adonanKe ?? lot0?.adonanKe,
      quantity: r.requestedQtyPcs,
      quantityLabel: 'Ditransfer',
      timestampLabel: 'Dikirim',
      timestamp: r.sentAt,
      units: lot0 || r,
      box: boxAllocationText(r) || undefined
    }),
    note: ''
  }
}

// lane null + flag draft/cancelled = riwayat Desk — tidak digambar di papan;
// stopped TANPA SE tetap terlihat di Request Gudang (kartu mati).

// Filter only Cold Storage lots; work queues remain visible regardless of date.
const todayISO = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const lotFrom = ref('')
const lotTo = ref('')
const lotFilterOpen = ref(false)
const coldPageSize = ref(PAGE_SIZE_OPTIONS[0])
const coldPage = ref(1)
// FU44: search papan (nama item / WO / dokumen / batch) — client-side karena
// papan sudah termuat penuh; sengaja tidak dipersisten agar reload selalu
// menampilkan papan utuh.
const searchQ = ref('')
const saveHandoverPreferences = () => saveListPreferences({
  workOrder: savedListPreferences.workOrder || {},
  handover: { from: lotFrom.value, to: lotTo.value, pageSize: coldPageSize.value, filterOpen: lotFilterOpen.value, viewMode: viewMode.value }
})
function setColdPageSize(value) {
  coldPageSize.value = normalizePageSize(value)
  coldPage.value = 1
  saveHandoverPreferences()
}
const lotFilterCount = computed(() => (lotFrom.value ? 1 : 0) + (lotTo.value ? 1 : 0))
const lotDateActive = computed(() => !!(lotFrom.value || lotTo.value))
const filteredLots = computed(() => handoverLots.filter((l) => {
  if (!lotDateActive.value) return true
  const day = (l.enteredAt || '').slice(0, 10)
  if (!day) return false
  return (!lotFrom.value || day >= lotFrom.value) && (!lotTo.value || day <= lotTo.value)
}))
const coldLots = computed(() => filteredLots.value.filter((l) => l.unsupported || lotAvailablePcs(l) > 0))
// FU44: cari pada kartu (bukan baris) SEBELUM pagination — searchQ mengubah
// jumlah kartu lane Cold Storage maupun halamannya.
const coldCards = computed(() => coldLots.value.map(lotCard).filter((c) => boardMatch(c, searchQ.value)))
const coldTotalPages = computed(() => Math.max(1, Math.ceil(coldCards.value.length / coldPageSize.value)))
const pagedColdLots = computed(() => coldCards.value.slice((coldPage.value - 1) * coldPageSize.value, coldPage.value * coldPageSize.value))
watch([lotFrom, lotTo], () => { coldPage.value = 1; saveHandoverPreferences() })
watch(searchQ, () => { coldPage.value = 1 })
// panel filter tetap terbuka setelah refresh (preferensi per-user, FU18)
watch(lotFilterOpen, () => saveHandoverPreferences())
function lotToday() { lotFrom.value = todayISO(); lotTo.value = todayISO() }
function lotAllDates() { lotFrom.value = ''; lotTo.value = ''; lotFilterOpen.value = false }
function lotReset() { lotFrom.value = ''; lotTo.value = ''; lotFilterOpen.value = false }

const byLane = computed(() => ({
  cold: pagedColdLots.value,
  request: handoverRequests
    .filter((r) => r.lane === 'request' && r.flag !== 'cancelled' && r.flag !== 'draft')
    .map(reqCard)
    .filter((c) => boardMatch(c, searchQ.value)),
  kirim: handoverRequests
    .filter((r) => r.lane === 'terkirim')
    .sort((a, b) => (a.sentAt || '').localeCompare(b.sentAt || ''))
    .map(doneCard)
    .filter((c) => boardMatch(c, searchQ.value))
}))

function clickCard(c) {
  if (!c.live) return
  // satu-satunya aksi kartu yang tersisa (FU48): request aktif → form kirim
  openSendDialog(c.ref)
}

// FU47: klik BARIS tabel = semantik klik kartu kanban (rowClickAction murni
// ter-test) — request tanpa flag → kirim; Terkirim → detail baca-saja.
function rowAction(r) {
  const action = rowClickAction(r, handoverBoard.roles)
  if (action === 'send') openSendDialog(r.id)
  else if (action === 'done') openSentDialog(r.id)
}

// ---- dialog (Produksi): Kirim Stock Entry — form review (FU47). Submit tetap
// SATU jalur server: send_handover membuat + submit SE Material Transfer via
// mapper native dalam satu transaksi. Panel sukses dipakai juga sebagai detail
// baca-saja untuk baris Terkirim (kirimReadonly). ----
const dlgKirim = ref(null)
const kirimReq = ref(null)
const kirimError = ref('')
const kirimDone = ref(false)
// true = dibuka dari baris Terkirim (tanpa tombol kirim, judul detail)
const kirimReadonly = ref(false)

// T32 (R6): qty kirim = qty diminta MR (== produced_qty WO); server tidak pernah stop
const kirimGood = computed(() => kirimReq.value?.requestedQtyPcs ?? 0)
const kirimRoute = computed(() => seRouteLabel(kirimReq.value, handoverBoard.targetWarehouse))
// FU29: peringatan stok rute tampil DI DALAM form review sebelum submit
const kirimRouteWarn = computed(() =>
  kirimReq.value && !kirimReadonly.value ? routeWarn(kirimReq.value) : ''
)

function openSendDialog(reqId) {
  const r = handoverRequests.find((x) => x.id === reqId)
  if (!r || r.lane !== 'request' || r.flag) return
  kirimReq.value = r
  kirimError.value = ''
  kirimDone.value = false
  kirimReadonly.value = false
  nextTick(() => dlgKirim.value.showModal())
}

// FU47: baris Terkirim → panel baca-saja (detail SE yang sudah terkirim)
function openSentDialog(reqId) {
  const r = handoverRequests.find((x) => x.id === reqId)
  if (!r || r.lane !== 'terkirim' || !r.stockEntry) return
  kirimReq.value = r
  kirimError.value = ''
  kirimDone.value = true
  kirimReadonly.value = true
  nextTick(() => dlgKirim.value.showModal())
}
function closeKirim() {
  dlgKirim.value.close()
  kirimReq.value = null
}
async function confirmKirim() {
  kirimError.value = ''
  try {
    await sendHandover(kirimReq.value.id)
    // ganti kartu dengan versi terbaru dari papan server
    const fresh = handoverRequests.find((x) => x.id === kirimReq.value.id)
    if (fresh) kirimReq.value = fresh
    kirimDone.value = true
  } catch (e) {
    kirimError.value = e.message
  }
}

// ---- FO 2026-09-18: mode tampilan Kanban|Tabel (preferensi per-user).
// FU48: default Tabel — hanya produksi yang sampai sini (antrian MR → form
// Stock Entry). Preferensi tersimpan (toggle / perubahan filter ikut
// menyimpan viewMode) selalu menang. ----
const viewMode = ref('tabel') // 'kanban' | 'tabel'
function setViewMode(mode) {
  viewMode.value = mode
  saveHandoverPreferences()
}

// baris tabel Stock Entry: seluruh request papan (status dari lane/flag),
// dicari dengan helper kartu yang sama (nama item / WO / dokumen / batch)
const serahRows = computed(() =>
  handoverRequests
    .map((r) => ({ r, meta: laneStatusMeta(r) }))
    .filter(({ r }) => boardMatch({ name: r.item, workOrder: r.workOrder, document: r.materialRequest || r.stockEntry, batch: r.batch }, searchQ.value))
)

onMounted(() => {
  const apply = () => {
    const p = savedListPreferences.handover || {}
    lotFrom.value = p.from || ''; lotTo.value = p.to || ''
    coldPageSize.value = normalizePageSize(p.pageSize)
    lotFilterOpen.value = !!p.filterOpen
    // preferensi eksplisit menang; tanpa preferensi → default Tabel
    if (p.viewMode === 'tabel' || p.viewMode === 'kanban') viewMode.value = p.viewMode
    loadBoard()
  }
  if (listPreferencesState.loaded) apply()
  else {
    let applied = false
    const run = () => { if (applied) return; applied = true; apply() }
    const timer = setInterval(() => { if (listPreferencesState.loaded) { clearInterval(timer); run() } }, 25)
    setTimeout(() => { clearInterval(timer); run() }, 2000) // preferensi gagal termuat → board tetap jalan
  }
})
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Stock Entry</h1>
      <p class="sub">Kirim barang jadi dari Cold Storage ke gudang.</p>
    </div>
    <div class="ph-date">{{ new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }}</div>
  </div>

  <div v-if="handoverState.error" class="appfoot" style="color:#b3261e">Gagal memuat: {{ handoverState.error }} — <a href="#" @click.prevent="loadBoard()">coba lagi</a></div>

  <div class="toolbar">
    <div class="searchbox">
      <Search :size="15" :stroke-width="2" class="search-ico" />
      <input
        v-model="searchQ"
        class="input"
        type="search"
        placeholder="Cari nama item, WO, atau dokumen"
        aria-label="Cari item di papan Stock Entry"
      />
    </div>
    <!-- FO: segmented control Kanban|Tabel (reuse .viewswitch ala daftar WO) —
    preferensi per-user -->
    <div class="viewswitch" role="group" aria-label="Mode tampilan">
      <button
        type="button"
        :class="{ on: viewMode === 'kanban' }"
        :aria-pressed="viewMode === 'kanban'"
        @click="setViewMode('kanban')"
      >
        <KanbanSquare :size="14" :stroke-width="2" /> Kanban
      </button>
      <button
        type="button"
        :class="{ on: viewMode === 'tabel' }"
        :aria-pressed="viewMode === 'tabel'"
        @click="setViewMode('tabel')"
      >
        <Table2 :size="14" :stroke-width="2" /> Tabel
      </button>
    </div>
    <div v-if="viewMode === 'kanban'" class="filterwrap">
      <button
        class="btn filterbtn"
        :class="{ active: lotFilterCount }"
        aria-label="Filter"
        @click="lotFilterOpen = !lotFilterOpen"
      >
        <Filter :size="14" :stroke-width="2" />
        <span class="btext">Filter</span>
        <span v-if="lotFilterCount" class="filtercount">{{ lotFilterCount }}</span>
      </button>
      <div v-if="lotFilterOpen" class="popoverlay" @click="lotFilterOpen = false"></div>
      <Transition name="pop">
        <div v-if="lotFilterOpen" class="filterpanel">
          <div class="frow2">
            <div class="ffield">
              <label>Lot masuk dari</label>
              <input v-model="lotFrom" class="input" type="date" />
            </div>
            <div class="ffield">
              <label>Lot masuk s.d.</label>
              <input v-model="lotTo" class="input" type="date" />
            </div>
          </div>
          <div class="frow2 filter-actions">
            <button class="linkbtn" type="button" @click="lotToday">Hari ini</button>
            <button class="linkbtn" type="button" @click="lotAllDates">Semua tanggal</button>
          </div>
          <button class="linkbtn filter-clear" type="button" @click="lotReset">Hapus semua filter</button>
        </div>
      </Transition>
    </div>
  </div>

  <template v-if="viewMode === 'kanban'">
  <div class="kb">
    <section
      v-for="l in lanes"
      :key="l.key"
      class="kb-lane"
      :class="l.tone ? `tone-${l.tone}` : ''"
    >
      <header class="kb-lane-head">
        <span class="kb-ico" :class="l.tone ? `ok` : ''" aria-hidden="true">
          <component :is="l.icon" :size="14" :stroke-width="1.9" />
        </span>
        <div class="kb-hgroup">
          <span class="kb-title">{{ l.title }}</span>
        </div>
        <span class="kb-count">{{ byLane[l.key].length }}</span>
      </header>
      <TransitionGroup name="kc" tag="div" class="kb-cards">
        <div
          v-for="c in byLane[l.key]"
          :key="c.key"
          class="kb-card se-kb-card"
          :class="{ live: c.live }"
          @click="clickCard(c)"
        >
          <div class="kb-top">
            <span class="kb-name">{{ c.name }}</span>
          </div>
          <div class="se-card-docs">
            <span class="kb-id">{{ c.workOrder }}</span>
            <span v-if="c.document" class="kb-id">{{ c.document }}</span>
          </div>
          <dl class="se-card-rows">
            <div v-if="c.batch" class="se-card-row se-card-batch">
              <dt>Batch</dt>
              <dd>{{ c.batch }}</dd>
            </div>
            <div v-if="c.adonan" class="se-card-row">
              <dt>Adonan</dt>
              <dd>{{ c.adonan }}</dd>
            </div>
            <div class="se-card-row se-card-qty">
              <dt>{{ c.quantityLabel }}</dt>
              <dd>{{ c.quantity }}</dd>
            </div>
            <div v-if="c.timestampLabel && c.timestamp" class="se-card-row">
              <dt>{{ c.timestampLabel }}</dt>
              <dd>{{ c.timestamp }}</dd>
            </div>
          </dl>
          <span v-if="c.note" class="kb-note">{{ c.note }}</span>
          <div v-if="c.box" class="se-card-foot">
            <span class="kb-pill">{{ c.box }}</span>
          </div>
        </div>
        <div v-if="!byLane[l.key].length" key="empty" class="kb-empty">
          <Inbox :size="16" :stroke-width="1.8" aria-hidden="true" />
          <span>{{ l.empty }}</span>
        </div>
      </TransitionGroup>
    </section>
  </div>

  <div class="pagination-bar pagination-footer cold-pagination">
    <label class="page-size-control">
      <span>Tampilkan</span>
      <select class="select" :value="coldPageSize" aria-label="Jumlah lot Cold Storage per halaman" @change="setColdPageSize($event.target.value)">
        <option v-for="size in PAGE_SIZE_OPTIONS" :key="size" :value="size">{{ size }}</option>
      </select>
    </label>
  </div>
  </template>

  <!-- ============ FU48: tampilan Tabel — hanya antrian Stock Entry ============ -->
  <template v-else>
    <section class="panel tbl-panel">
      <div class="panel-head">
        <span class="p-ico"><Truck :size="15" :stroke-width="1.9" /></span>
        <h2>Antrian Kirim Stock Entry</h2>
        <span class="lead">Klik baris untuk aksi / detail Stock Entry. Status dihitung server dari Material Request / Stock Entry.</span>
      </div>
      <div class="panel-body">
        <div class="tbl-wrap">
          <table class="datatable">
            <thead>
              <tr>
                <th>Dokumen</th><th>Item</th><th>Qty</th><th>Work Order</th><th>Batch</th>
                <th>Dibuat oleh</th><th>Status</th><th v-if="isProduksi"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="{ r, meta } in serahRows"
                :key="r.id"
                :class="{ rowlink: !!rowClickAction(r, handoverBoard.roles) }"
                @click="rowAction(r)"
              >
                <td>
                  <span class="tbl-doc">{{ r.materialRequest }}</span>
                  <span v-if="r.stockEntry" class="tbl-sub">{{ r.stockEntry }} · {{ r.sentAt }}</span>
                </td>
                <td>{{ r.item }}</td>
                <td>{{ qtyMain(r.requestedQtyPcs, lotForWo(r.workOrder) || r) }}</td>
                <td>{{ r.workOrder }}</td>
                <td>{{ r.batch || '-' }}</td>
                <td>{{ r.ownerName || '-' }}</td>
                <td><span class="chip" :class="meta.cls">{{ meta.label }}</span></td>
                <td v-if="isProduksi" @click.stop>
                  <button
                    v-if="r.lane === 'request' && !r.flag"
                    class="btn btn-sm btn-primary"
                    :disabled="!!handoverState.pending"
                    @click="openSendDialog(r.id)"
                  >Kirim</button>
                </td>
              </tr>
              <tr v-if="!serahRows.length">
                <td :colspan="8" class="tbl-empty">
                  <Inbox :size="16" :stroke-width="1.8" aria-hidden="true" />
                  <span>Belum ada request.</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </template>

  <!-- ============ dialog: Kirim Stock Entry — form review
       (Produksi, dari request; FU47 juga detail baca-saja baris Terkirim) ============ -->
  <dialog ref="dlgKirim" class="dialog" @click.self="closeKirim">
    <template v-if="kirimReq">
      <template v-if="!kirimDone">
        <header class="dlg-head">
          <span class="dlg-ico" aria-hidden="true"><Truck :size="16" :stroke-width="1.9" /></span>
          <div class="dlg-hgroup">
            <h3>Kirim Stock Entry</h3>
            <p class="dlg-sub"><strong>{{ kirimReq.workOrder }}</strong> · {{ kirimReq.item }}</p>
          </div>
        </header>
        <div class="dlg-context">
          <div class="sum-row">
            <span class="k">Material Request</span>
            <span class="v">{{ kirimReq.materialRequest }}</span>
          </div>
          <div class="sum-row">
            <span class="k">Item</span>
            <span class="v">
              {{ kirimReq.item }}
              <span v-if="kirimReq.itemCode" class="tbl-sub">{{ kirimReq.itemCode }}</span>
            </span>
          </div>
          <div class="sum-row">
            <span class="k">Rute</span>
            <span class="v"><span class="dim">{{ kirimRoute }}</span></span>
          </div>
          <div class="sum-row">
            <span class="k">Batch</span>
            <span class="v">{{ kirimReq.batch || '-' }}</span>
          </div>
          <div class="sum-row">
            <span class="k">Box</span>
            <span class="v" style="white-space: pre-line">{{ boxAllocationText(kirimReq) || '-' }}</span>
          </div>
        </div>
        <div class="boxgroup" style="margin-top: 14px">
          <div class="grouptitle">Stock Entry — Material Transfer</div>
          <div class="fgbox">
            <span>Qty Transfer</span>
            <span>{{ qtyMain(kirimGood, lotForWo(kirimReq.workOrder) || kirimReq) }}</span>
          </div>
          <p class="hint" style="margin-top: 6px">
            Qty terkunci sesuai permintaan (hasil Work Order saat request dibuat). Tanggal catat otomatis
            (sekarang). Stock Entry dibuat dan disubmit server saat dikirim — kekurangan stok ditolak apa adanya.
          </p>
          <p v-if="kirimRouteWarn" class="callout" role="alert">{{ kirimRouteWarn }}</p>
        </div>
        <p v-if="kirimError" class="err" style="margin-top: 10px" role="alert">{{ kirimError }}</p>
        <p v-if="handoverState.pending" role="status">Menyimpan…</p>
        <div class="dlg-actions">
          <button class="btn" :disabled="!!handoverState.pending" @click="closeKirim">Batal</button>
          <button class="btn btn-primary" :disabled="!!handoverState.pending" @click="confirmKirim">Buat &amp; Kirim Stock Entry</button>
        </div>
      </template>
      <template v-else>
        <header class="dlg-head">
          <span class="dlg-ico ok" aria-hidden="true"><CheckCircle2 :size="16" :stroke-width="1.9" /></span>
          <div class="dlg-hgroup">
            <h3>{{ kirimReadonly ? 'Detail Stock Entry' : 'Terkirim' }}</h3>
            <p class="dlg-sub"><strong>{{ kirimReq.workOrder }}</strong> · {{ kirimReq.item }}</p>
          </div>
        </header>
        <div class="fgbox">
          <span>Ditransfer</span>
          <span>{{ qtyMain(kirimGood, lotForWo(kirimReq.workOrder) || kirimReq) }}</span>
        </div>
        <div class="dlg-context" style="margin-top: 8px">
          <div class="sum-row">
            <span class="k">Stock Entry</span>
            <span class="v">{{ kirimReq.stockEntry }}</span>
          </div>
          <div class="sum-row">
            <span class="k">Material Request</span>
            <span class="v">{{ kirimReq.materialRequest }}</span>
          </div>
          <div class="sum-row">
            <span class="k">Rute</span>
            <span class="v"><span class="dim">{{ kirimRoute }}</span></span>
          </div>
          <div class="sum-row">
            <span class="k">Batch</span>
            <span class="v">{{ kirimReq.batch || '-' }}</span>
          </div>
          <div v-if="kirimReq.sentAt" class="sum-row">
            <span class="k">Dikirim</span>
            <span class="v">{{ kirimReq.sentAt }}</span>
          </div>
        </div>
        <div class="dlg-actions">
          <button class="btn" @click="closeKirim">Tutup</button>
        </div>
      </template>
    </template>
  </dialog>
</template>

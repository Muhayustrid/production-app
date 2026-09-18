<script setup>
// Adapted from the mockup HandoverBoard.vue (read-only source): role simulation
// strip and fail-injection removed; roles, lots, lanes and warehouses come from
// the server board payload (T23/T24) — the UI never writes lane state.
// T35/T37 three-lane cutover: Cold Storage -> Request Gudang -> Terkirim. The
// box allocation (kg + count in the item's warehouse UOM, T39 universal) is
// requested in the Cold Storage -> Request form; verification is gone (server
// create_request validates; the old postpacking call has no supported
// caller). Request cards: gudang cancels, produksi sends direct.
import { computed, nextTick, reactive, onMounted, ref, watch } from 'vue'
import {
  cancelFormOrder, cancelRequest, createRequest, fulfillFormOrder, formOrders, formOrderState,
  handoverBoard, handoverLots, handoverRequests, handoverState,
  listPreferencesState, loadBoard, loadFormOrders, lotAvailablePcs, lotForWo, lotRemainingPcs, lotReservedPcs, normalizePageSize, PAGE_SIZE_OPTIONS, saveListPreferences, savedListPreferences, sendHandover, setActionError
} from './store.js'
import { fmtInt, qtyMain } from './format.js'
import { handoverCard } from './handover-card.js'
import { boardMatch } from './handover-search.js'
import { boxAllocationText, expectedUnits, unitLabel, unitProblem, validateBoxAllocation } from './handover-box.js'
import { foItemsText, foStatusMeta, laneStatusMeta } from './form-order.js'
import {
  CheckCircle2, ClipboardList, Filter, GripVertical, Inbox, KanbanSquare,
  PackageCheck, Search, Snowflake, Table2, Truck, Undo2
} from 'lucide-vue-next'

const isGudang = computed(() => !!handoverBoard.roles.is_gudang)
const isProduksi = computed(() => !!handoverBoard.roles.is_produksi)
// multi-role (Gudang + Produksi sekaligus): klik kartu request memilih aksi;
// drag boleh ke dua lane (cold = batalkan, kirim = kirim langsung)
const isMultiRole = computed(() => isGudang.value && isProduksi.value)

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
function lotCard(lot) {
  const base = {
    kind: 'lot', ref: lot.workOrder, key: lot.workOrder,
    live: isGudang.value, draggable: isGudang.value,
    name: lot.item
  }
  if (lot.unsupported) {
    return {
      ...base,
      live: false,
      draggable: false,
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
    live: !stopped, draggable: !stopped,
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
    live: false, draggable: false,
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

// ---- drag & drop = niat bisnis: selalu buka dialog dulu ----
const drag = ref(null) // { kind, ref }
const overLane = ref(null)

function targetLanes(d) {
  if (d.kind === 'lot') return ['request']
  // request: cold = batalkan (gudang), kirim = kirim langsung (produksi)
  return isMultiRole.value ? ['cold', 'kirim'] : (isGudang.value ? ['cold'] : ['kirim'])
}
function laneDroppable(laneKey) {
  return !!drag.value && targetLanes(drag.value).includes(laneKey)
}
function onDragStart(e, c) {
  if (!c.draggable) return
  drag.value = { kind: c.kind, ref: c.ref }
  e.dataTransfer.setData('text/plain', `${c.kind}:${c.ref}`)
  e.dataTransfer.effectAllowed = 'move'
}
function onDragEnd() {
  drag.value = null
  overLane.value = null
}
function dragEnter(laneKey) {
  if (laneDroppable(laneKey)) overLane.value = laneKey
}
function dragLeave(laneKey) {
  if (overLane.value === laneKey) overLane.value = null
}
function onDrop(e, laneKey) {
  e.preventDefault()
  const d = drag.value
  drag.value = null
  overLane.value = null
  if (!d || !targetLanes(d).includes(laneKey)) return
  // drop TIDAK mengubah state: semua aksi lewat dialog (server truth tetap)
  if (d.kind === 'lot') openRequestDialog(d.ref)
  else if (d.kind === 'request') {
    laneKey === 'cold' ? openCancelDialog(d.ref) : openSendDialog(d.ref)
  }
}

function clickCard(c) {
  if (!c.live) return
  if (c.kind === 'lot') openRequestDialog(c.ref)
  else if (c.kind === 'request') {
    isMultiRole.value ? openChooseDialog(c.ref)
      : isGudang.value ? openCancelDialog(c.ref) : openSendDialog(c.ref)
  }
}

// ---- dialog (Gudang): Buat Request Gudang — alokasi box kg + jumlah (T35,
// T39 universal: satuan mengikuti UOM gudang item — Pack, Pcs, dll.) ----
const dlgRequest = ref(null)
const reqLot = ref(null)
const reqError = ref('')
const reqForm = reactive({ box1: '', box1Qty: '', box2: '0', box2Qty: '0' })

// UX check murni; kontrak & validasi tetap di server (create_request T35/T39).
// unitProblem: 'conversion' (UOM gudang = UOM alternatif tanpa konversi
// valid) vs 'fractional' (hasil Work Order tidak membentuk satuan utuh) —
// dua pesan berbeda.
const reqProblem = computed(() => (reqLot.value ? unitProblem(reqLot.value) : 'conversion'))
const reqUnit = computed(() => unitLabel(reqLot.value))
const reqExpected = computed(() => (reqLot.value && !reqProblem.value ? expectedUnits(reqLot.value) : null))
const reqFieldErrors = computed(() => validateBoxAllocation(reqForm, reqExpected.value, reqUnit.value))
const reqQtyText = computed(() =>
  reqLot.value ? qtyMain(reqLot.value.producedQty, reqLot.value) : ''
)
const reqCanSave = computed(() =>
  reqExpected.value != null && !Object.keys(reqFieldErrors.value).length && !handoverState.pending
)

function openRequestDialog(woId) {
  const lot = lotForWo(woId)
  if (!isGudang.value || !lot || lot.unsupported || lotAvailablePcs(lot) <= 0) return
  reqLot.value = lot
  reqError.value = ''
  Object.assign(reqForm, { box1: '', box1Qty: '', box2: '0', box2Qty: '0' })
  nextTick(() => dlgRequest.value.showModal())
}
function closeRequest() {
  if (handoverState.pending) return // simpanan berjalan: Batal/backdrop terkunci
  dlgRequest.value.close()
  reqLot.value = null
}
function guardRequestCancel(e) {
  if (handoverState.pending) e.preventDefault() // Escape tidak menutup saat simpan
}
async function confirmRequest() {
  if (!reqCanSave.value) return
  reqError.value = ''
  try {
    // sukses: applyBoard sudah mengganti papan dgn server truth — baru tutup
    await createRequest(reqLot.value.workOrder, { ...reqForm })
    closeRequest()
  } catch (e) {
    reqError.value = e.message // dialog + seluruh isian dipertahankan
  }
}

// ---- dialog (Produksi): Kirim ke Gudang — request langsung jadi Terkirim ----
const dlgKirim = ref(null)
const kirimReq = ref(null)
const kirimError = ref('')
const kirimDone = ref(false)

// T32 (R6): qty kirim = qty diminta MR (== produced_qty WO); server tidak pernah stop
const kirimGood = computed(() => kirimReq.value?.requestedQtyPcs ?? 0)
const kirimRoute = computed(() =>
  `${kirimReq.value?.fromWarehouse || 'Cold Storage'} → ${kirimReq.value?.toWarehouse || handoverBoard.targetWarehouse || '-'}`
)

function openSendDialog(reqId) {
  const r = handoverRequests.find((x) => x.id === reqId)
  if (!r || r.lane !== 'request' || r.flag) return
  kirimReq.value = r
  kirimError.value = ''
  kirimDone.value = false
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

// ---- dialog (Gudang): batalkan request salah input ----
const dlgCancel = ref(null)
const cancelReq = ref(null)
const cancelError = ref('')
const cancelLot = computed(() =>
  cancelReq.value ? lotForWo(cancelReq.value.workOrder) : null
)

function openCancelDialog(reqId) {
  const r = handoverRequests.find((x) => x.id === reqId)
  if (!r || r.lane !== 'request' || r.flag) return
  cancelReq.value = r
  cancelError.value = ''
  nextTick(() => dlgCancel.value.showModal())
}
function closeCancel() {
  dlgCancel.value.close()
  cancelReq.value = null
}
async function confirmCancel() {
  cancelError.value = ''
  try {
    await cancelRequest(cancelReq.value.id)
    closeCancel()
  } catch (e) {
    cancelError.value = e.message
  }
}

// ---- dialog pilih aksi request (khusus user multi-role: Gudang + Produksi) ----
const dlgChoose = ref(null)
const chooseRef = ref(null)
const chooseReq = computed(() =>
  handoverRequests.find((x) => x.id === chooseRef.value) || null
)

function openChooseDialog(reqId) {
  const r = handoverRequests.find((x) => x.id === reqId)
  if (!r || r.lane !== 'request' || r.flag) return
  chooseRef.value = reqId
  nextTick(() => dlgChoose.value.showModal())
}
function closeChoose() {
  dlgChoose.value.close()
  chooseRef.value = null
}
// id harus ditangkap SEBELUM closeChoose meng-null-kan chooseRef (computed jadi null)
function chooseSend() {
  const id = chooseRef.value
  closeChoose()
  openSendDialog(id)
}
function chooseCancel() {
  const id = chooseRef.value
  closeChoose()
  openCancelDialog(id)
}

// ---- FO 2026-09-18: mode tampilan Kanban|Tabel (preferensi per-user) + tab
// Form Order di tampilan tabel. Kanban tiga lajur tidak berubah. ----
const viewMode = ref('kanban') // 'kanban' | 'tabel'
const tableTab = ref('serah') // 'serah' | 'form-order'
function setViewMode(mode) {
  viewMode.value = mode
  saveHandoverPreferences()
}
function setTableTab(tab) {
  tableTab.value = tab
  if (tab === 'form-order' && !formOrderState.loaded && !formOrderState.loading) loadFormOrders()
}

// baris tabel Serah Terima: seluruh request papan (status dari lane/flag),
// dicari dengan helper kartu yang sama (nama item / WO / dokumen / batch)
const serahRows = computed(() =>
  handoverRequests
    .map((r) => ({ r, meta: laneStatusMeta(r) }))
    .filter(({ r }) => boardMatch({ name: r.item, workOrder: r.workOrder, document: r.materialRequest || r.stockEntry, batch: r.batch }, searchQ.value))
)
const foRows = computed(() => {
  const q = searchQ.value.trim().toLowerCase()
  if (!q) return formOrders
  return formOrders.filter((o) =>
    [o.materialRequest, o.stockEntry, o.ownerName, ...o.items.map((i) => i.name)].join(' ').toLowerCase().includes(q)
  )
})

// ---- dialog (Gudang): proses Form Order → Stock Entry Material Transfer ----
const dlgFulfill = ref(null)
const fulfillTarget = ref(null)
const fulfillError = ref('')
function openFulfillDialog(id) {
  fulfillTarget.value = formOrders.find((o) => o.id === id) || null
  fulfillError.value = ''
  if (fulfillTarget.value) nextTick(() => dlgFulfill.value.showModal())
}
function closeFulfill() {
  dlgFulfill.value.close()
  fulfillTarget.value = null
}
async function confirmFulfill() {
  fulfillError.value = ''
  try {
    await fulfillFormOrder(fulfillTarget.value.id) // daftar diganti server truth
    closeFulfill()
  } catch (e) {
    fulfillError.value = e.message
  }
}

// tabel Form Order: batalkan milik sendiri yang belum diproses (guard server)
const dlgFoCancel = ref(null)
const foCancelTarget = ref(null)
const foCancelError = ref('')
function openFoCancelDialog(id) {
  foCancelTarget.value = formOrders.find((o) => o.id === id) || null
  foCancelError.value = ''
  if (foCancelTarget.value) nextTick(() => dlgFoCancel.value.showModal())
}
function closeFoCancel() {
  dlgFoCancel.value.close()
  foCancelTarget.value = null
}
async function confirmFoCancel() {
  foCancelError.value = ''
  try {
    await cancelFormOrder(foCancelTarget.value.id)
    closeFoCancel()
  } catch (e) {
    foCancelError.value = e.message
  }
}

onMounted(() => {
  const apply = () => {
    const p = savedListPreferences.handover || {}
    lotFrom.value = p.from || ''; lotTo.value = p.to || ''
    coldPageSize.value = normalizePageSize(p.pageSize)
    lotFilterOpen.value = !!p.filterOpen
    viewMode.value = p.viewMode === 'tabel' ? 'tabel' : 'kanban'
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
      <h1>Serah Terima</h1>
      <p class="sub">Permintaan gudang dan pengiriman barang jadi dari Cold Storage.</p>
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
        aria-label="Cari item di papan serah terima"
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
  <div class="kb" :class="{ dragging: !!drag }">
    <section
      v-for="l in lanes"
      :key="l.key"
      class="kb-lane"
      :class="[l.tone ? `tone-${l.tone}` : '', { over: overLane === l.key, droppable: laneDroppable(l.key) }]"
      @dragover.prevent
      @dragenter.prevent="dragEnter(l.key)"
      @dragleave="dragLeave(l.key)"
      @drop="onDrop($event, l.key)"
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
          :class="{ live: c.live, pending: c.pending, dragging: drag && drag.kind === c.kind && drag.ref === c.ref }"
          :draggable="c.draggable"
          @dragstart="onDragStart($event, c)"
          @dragend="onDragEnd"
          @click="clickCard(c)"
        >
          <div class="kb-top">
            <span class="kb-name">{{ c.name }}</span>
            <GripVertical v-if="c.draggable" class="kb-grip" :size="15" :stroke-width="2" aria-hidden="true" />
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

  <!-- ============ FO: tampilan Tabel — antrian kerja per role ============ -->
  <template v-else>
    <div class="viewswitch vtabs" role="tablist" aria-label="Jenis antrian">
      <button
        type="button"
        role="tab"
        :class="{ on: tableTab === 'serah' }"
        :aria-selected="tableTab === 'serah'"
        @click="setTableTab('serah')"
      >
        Serah Terima
      </button>
      <button
        type="button"
        role="tab"
        :class="{ on: tableTab === 'form-order' }"
        :aria-selected="tableTab === 'form-order'"
        @click="setTableTab('form-order')"
      >
        Form Order
      </button>
    </div>

    <section v-if="tableTab === 'serah'" class="panel tbl-panel">
      <div class="panel-head">
        <span class="p-ico"><Truck :size="15" :stroke-width="1.9" /></span>
        <h2>Antrian Serah Terima</h2>
        <span class="lead">Status dihitung server dari Material Request / Stock Entry.</span>
      </div>
      <div class="panel-body">
        <div class="tbl-wrap">
          <table class="datatable">
            <thead>
              <tr>
                <th>Dokumen</th><th>Item</th><th>Qty</th><th>Work Order</th><th>Batch</th>
                <th>Dibuat oleh</th><th>Status</th><th v-if="isProduksi || isGudang"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="{ r, meta } in serahRows" :key="r.id">
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
                <td v-if="isProduksi || isGudang">
                  <template v-if="r.lane === 'request' && !r.flag">
                    <button v-if="isMultiRole" class="btn btn-sm" :disabled="!!handoverState.pending" @click="openChooseDialog(r.id)">Pilih Aksi</button>
                    <button v-else-if="isProduksi" class="btn btn-sm btn-primary" :disabled="!!handoverState.pending" @click="openSendDialog(r.id)">Kirim</button>
                    <button v-else class="btn btn-sm" :disabled="!!handoverState.pending" @click="openCancelDialog(r.id)">Batalkan</button>
                  </template>
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

    <section v-else class="panel tbl-panel">
      <div class="panel-head">
        <span class="p-ico"><PackageCheck :size="15" :stroke-width="1.9" /></span>
        <h2>Antrian Form Order</h2>
        <span class="lead">Permintaan produksi ke gudang — Proses memindahkan stok ke tujuan.</span>
      </div>
      <div class="panel-body">
        <div v-if="formOrderState.error" class="appfoot" style="color:#b3261e">Gagal memuat: {{ formOrderState.error }} — <a href="#" @click.prevent="loadFormOrders()">coba lagi</a></div>
        <div class="tbl-wrap">
          <table class="datatable">
            <thead>
              <tr>
                <th>Dokumen</th><th>Item</th><th>Dibutuhkan</th><th>Dibuat oleh</th>
                <th>Status</th><th>Catatan</th><th v-if="isGudang || isProduksi"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in foRows" :key="o.id">
                <td>
                  <span class="tbl-doc">{{ o.materialRequest }}</span>
                  <span v-if="o.stockEntry" class="tbl-sub">{{ o.stockEntry }} · {{ o.sentAt }}</span>
                </td>
                <td>
                  <span>{{ foItemsText(o) }}</span>
                  <span class="tbl-sub">{{ o.fromWarehouse || '-' }} → {{ o.toWarehouse || '-' }}</span>
                </td>
                <td>{{ o.scheduleDate || '-' }}</td>
                <td>{{ o.ownerName }}</td>
                <td><span class="chip" :class="foStatusMeta(o.status).cls">{{ foStatusMeta(o.status).label }}</span></td>
                <td class="tbl-note">{{ o.note || '-' }}</td>
                <td v-if="isGudang || isProduksi">
                  <button v-if="isGudang && o.status === 'menunggu'" class="btn btn-sm btn-primary" :disabled="!!formOrderState.pending" @click="openFulfillDialog(o.id)">Proses</button>
                  <button v-else-if="isProduksi && o.status === 'menunggu'" class="btn btn-sm" :disabled="!!formOrderState.pending" @click="openFoCancelDialog(o.id)">Batalkan</button>
                </td>
              </tr>
              <tr v-if="!foRows.length">
                <td :colspan="7" class="tbl-empty">
                  <Inbox :size="16" :stroke-width="1.8" aria-hidden="true" />
                  <span>Belum ada Form Order.</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </template>

  <!-- ============ dialog: Buat Request Gudang (Gudang, dari Cold Storage) ============ -->
  <dialog ref="dlgRequest" class="dialog" @click.self="closeRequest" @cancel="guardRequestCancel">
    <template v-if="reqLot">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><ClipboardList :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Buat Request Gudang</h3>
          <p class="dlg-sub">
            <strong>{{ reqLot.workOrder }}</strong> · {{ reqLot.item
            }}<template v-if="reqLot.batch"> · Batch {{ reqLot.batch }}</template>
          </p>
        </div>
      </header>
      <div class="dlg-context">
        <div class="sum-row">
          <span class="k">Hasil Work Order</span>
          <span class="v">{{ reqQtyText }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Material Request</span>
          <span class="v dim">dibuat setelah disimpan</span>
        </div>
      </div>
      <div class="boxgroup" style="margin-top: 14px">
        <div class="grouptitle">Box Work Order</div>
        <div class="boxrow">
          <div class="field">
            <label for="req-box-1">Box 1 (kg) <span class="req">*</span></label>
            <input id="req-box-1" v-model="reqForm.box1" class="input" type="number" step="any" min="0" />
          </div>
          <div class="field">
            <label for="req-box-1-qty">Box 1 ({{ reqUnit }}) <span class="req">*</span></label>
            <input id="req-box-1-qty" v-model="reqForm.box1Qty" class="input" type="number" step="1" min="1" />
          </div>
        </div>
        <div class="boxrow">
          <div class="field">
            <label for="req-box-2">Box 2 (kg)</label>
            <input id="req-box-2" v-model="reqForm.box2" class="input" type="number" step="any" min="0" />
          </div>
          <div class="field">
            <label for="req-box-2-qty">Box 2 ({{ reqUnit }})</label>
            <input id="req-box-2-qty" v-model="reqForm.box2Qty" class="input" type="number" step="1" min="0" />
          </div>
        </div>
      </div>
      <p class="hint" style="margin-top: 8px">Box 2 boleh kosong (0 kg / 0 jumlah). Jumlah {{ reqUnit }} Box 1 + Box 2 harus tepat {{ reqExpected ?? '—' }} {{ reqUnit }}. Material Request dibuat setelah disimpan; Stock Entry saat dikirim.</p>

      <p v-if="reqProblem === 'conversion'" class="err" style="margin-top: 8px" role="alert">
        Konversi {{ reqUnit }} item belum valid — lengkapi konversi satuan item di Desk sebelum membuat request.
      </p>
      <p v-else-if="reqProblem === 'fractional'" class="err" style="margin-top: 8px" role="alert">
        Hasil Work Order tidak membentuk {{ reqUnit }} utuh — sesuaikan hasil produksi atau konversi {{ reqUnit }} item di Desk.
      </p>
      <p v-else-if="Object.keys(reqFieldErrors).length" class="err" style="margin-top: 8px" role="alert">
        {{ Object.values(reqFieldErrors).join(' ') }}
      </p>
      <p v-if="reqError" class="err" style="margin-top: 8px" role="alert">{{ reqError }}</p>
      <p v-if="handoverState.pending" role="status">Menyimpan…</p>
      <div class="dlg-actions">
        <button class="btn" :disabled="!!handoverState.pending" @click="closeRequest">Batal</button>
        <button class="btn btn-primary" :disabled="!reqCanSave" @click="confirmRequest">Buat Request Gudang</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: Kirim ke Gudang (Produksi, dari Request) ============ -->
  <dialog ref="dlgKirim" class="dialog" @click.self="closeKirim">
    <template v-if="kirimReq">
      <template v-if="!kirimDone">
        <header class="dlg-head">
          <span class="dlg-ico" aria-hidden="true"><Truck :size="16" :stroke-width="1.9" /></span>
          <div class="dlg-hgroup">
            <h3>Kirim ke Gudang</h3>
            <p class="dlg-sub"><strong>{{ kirimReq.workOrder }}</strong> · {{ kirimReq.item }}</p>
          </div>
        </header>
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
        <div class="sum-row">
          <span class="k">Box</span>
          <span class="v" style="white-space: pre-line">{{ boxAllocationText(kirimReq) || '-' }}</span>
        </div>
        <div class="fgbox" style="margin-top: 10px">
          <span>Qty Transfer</span>
          <span>{{ qtyMain(kirimGood, lotForWo(kirimReq.workOrder) || kirimReq) }}</span>
        </div>
        <p v-if="kirimError" class="err" style="margin-top: 10px" role="alert">{{ kirimError }}</p>
        <p v-if="handoverState.pending" role="status">Menyimpan…</p>
        <div class="dlg-actions">
          <button class="btn" :disabled="!!handoverState.pending" @click="closeKirim">Batal</button>
          <button class="btn btn-primary" :disabled="!!handoverState.pending" @click="confirmKirim">Kirim Barang</button>
        </div>
      </template>
      <template v-else>
        <header class="dlg-head">
          <span class="dlg-ico ok" aria-hidden="true"><CheckCircle2 :size="16" :stroke-width="1.9" /></span>
          <div class="dlg-hgroup">
            <h3>Terkirim</h3>
            <p class="dlg-sub"><strong>{{ kirimReq.workOrder }}</strong> · {{ kirimReq.item }}</p>
          </div>
        </header>
        <div class="fgbox">
          <span>Ditransfer</span>
          <span>{{ qtyMain(kirimGood, lotForWo(kirimReq.workOrder) || kirimReq) }}</span>
        </div>
        <div class="sum-row" style="margin-top: 8px">
          <span class="k">Material Request</span>
          <span class="v">{{ kirimReq.materialRequest }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Stock Entry</span>
          <span class="v">{{ kirimReq.stockEntry }}</span>
        </div>
        <div class="dlg-actions">
          <button class="btn" @click="closeKirim">Tutup</button>
        </div>
      </template>
    </template>
  </dialog>

  <!-- ============ dialog: batalkan request (Gudang) ============ -->
  <dialog ref="dlgCancel" class="dialog" @click.self="closeCancel">
    <template v-if="cancelReq">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><Undo2 :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Batalkan Request?</h3>
          <p class="dlg-sub">
            <strong>{{ cancelReq.workOrder }} · {{ cancelReq.item }}</strong> · {{ cancelReq.materialRequest }}
          </p>
        </div>
      </header>
      <p>
        Reservasi <strong>{{ qtyMain(cancelReq.requestedQtyPcs, cancelLot || cancelReq) }}</strong>
        pada Cold Storage akan dilepas.
      </p>
      <p v-if="cancelError" class="err" role="alert">{{ cancelError }}</p>
      <p v-if="handoverState.pending" role="status">Menyimpan…</p>
      <div class="dlg-actions">
        <button class="btn" :disabled="!!handoverState.pending" @click="closeCancel">Kembali</button>
        <button class="btn btn-primary" :disabled="!!handoverState.pending" @click="confirmCancel">Ya, Batalkan</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: pilih aksi request (user multi-role) ============ -->
  <dialog ref="dlgChoose" class="dialog" @click.self="closeChoose">
    <template v-if="chooseReq">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><ClipboardList :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Pilih Aksi</h3>
          <p class="dlg-sub">
            <strong>{{ chooseReq.workOrder }} · {{ chooseReq.item }}</strong> · {{ chooseReq.materialRequest }}
          </p>
        </div>
      </header>
      <p class="hint">
        Akun Anda punya peran Gudang <em>dan</em> Produksi — pilih sisi untuk request ini.
      </p>
      <div class="dlg-actions">
        <button class="btn" @click="chooseCancel">Batalkan Request</button>
        <button class="btn btn-primary" @click="chooseSend">Kirim ke Gudang</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: Proses Form Order (Gudang, tampilan tabel) ============ -->
  <dialog ref="dlgFulfill" class="dialog" @click.self="closeFulfill">
    <template v-if="fulfillTarget">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><PackageCheck :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Proses Form Order?</h3>
          <p class="dlg-sub"><strong>{{ fulfillTarget.materialRequest }}</strong> · {{ fulfillTarget.ownerName }}</p>
        </div>
      </header>
      <div class="sum-row">
        <span class="k">Item</span>
        <span class="v">{{ foItemsText(fulfillTarget) }}</span>
      </div>
      <div class="sum-row">
        <span class="k">Rute</span>
        <span class="v"><span class="dim">{{ fulfillTarget.fromWarehouse || '-' }} → {{ fulfillTarget.toWarehouse || '-' }}</span></span>
      </div>
      <p class="hint" style="margin-top: 8px">Stock Entry Material Transfer dibuat dan disubmit — kekurangan stok ditolak apa adanya.</p>
      <p v-if="fulfillError" class="err" role="alert">{{ fulfillError }}</p>
      <p v-if="formOrderState.pending === 'fulfill_form_order'" role="status">Menyimpan…</p>
      <div class="dlg-actions">
        <button class="btn" :disabled="!!formOrderState.pending" @click="closeFulfill">Batal</button>
        <button class="btn btn-primary" :disabled="!!formOrderState.pending" @click="confirmFulfill">Ya, Proses</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: batalkan Form Order (pembuat, tampilan tabel) ============ -->
  <dialog ref="dlgFoCancel" class="dialog" @click.self="closeFoCancel">
    <template v-if="foCancelTarget">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><Undo2 :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Batalkan Form Order?</h3>
          <p class="dlg-sub"><strong>{{ foCancelTarget.materialRequest }}</strong> · {{ foItemsText(foCancelTarget) }}</p>
        </div>
      </header>
      <p>Permintaan dibatalkan selama belum diproses gudang.</p>
      <p v-if="foCancelError" class="err" role="alert">{{ foCancelError }}</p>
      <p v-if="formOrderState.pending === 'cancel_form_order'" role="status">Menyimpan…</p>
      <div class="dlg-actions">
        <button class="btn" :disabled="!!formOrderState.pending" @click="closeFoCancel">Kembali</button>
        <button class="btn btn-primary" :disabled="!!formOrderState.pending" @click="confirmFoCancel">Ya, Batalkan</button>
      </div>
    </template>
  </dialog>
</template>

<script setup>
// Adapted from the mockup HandoverBoard.vue (read-only source): role simulation
// strip and fail-injection removed; roles, lots, lanes and warehouses come from
// the server board payload (T23/T24) — the UI never writes lane state.
import { computed, nextTick, reactive, onMounted, ref, watch } from 'vue'
import {
  cancelRequest, createRequest, handoverBoard, handoverLots, handoverRequests, handoverState,
  listPreferencesState, loadBoard, lotAvailablePcs, lotForWo, lotRemainingPcs, lotReservedPcs, normalizePageSize, PAGE_SIZE_OPTIONS, saveListPreferences, savedListPreferences, savePostPacking, sendHandover, setActionError
} from './store.js'
import { fmtInt, fmtStampShort, packParts, qtyMain } from './format.js'
import {
  CheckCircle2, ClipboardList, Filter, GripVertical, Inbox,
  PackageCheck, Snowflake, Truck, Undo2
} from 'lucide-vue-next'

const isGudang = computed(() => !!handoverBoard.roles.is_gudang)
const isProduksi = computed(() => !!handoverBoard.roles.is_produksi)
// multi-role (Gudang + Produksi sekaligus): kedua sisi aksi tersedia — klik kartu
// request memilih aksi; drag boleh ke dua lane (cold = batalkan, siap = post-packing)
const isMultiRole = computed(() => isGudang.value && isProduksi.value)

// ---- papan: 4 lane, lot Cold Storage FIFO (urutan dari server) ----
const lanes = [
  { key: 'cold', title: 'Cold Storage', sub: 'Lot barang jadi · FIFO', icon: Snowflake, tone: '', empty: 'Belum ada lot' },
  { key: 'request', title: 'Request Gudang', sub: 'Menunggu verifikasi', icon: ClipboardList, tone: '', empty: 'Belum ada request' },
  { key: 'siap', title: 'Siap Kirim', sub: 'Sudah diverifikasi', icon: PackageCheck, tone: '', empty: 'Belum ada siap kirim' },
  { key: 'kirim', title: 'Terkirim', sub: 'Diterima gudang', icon: CheckCircle2, tone: 'ok', empty: 'Belum ada terkirim' }
]

function qtyPair(pcs, units) {
  if (!Number.isFinite(pcs)) return { qv: '—', qu: '—' }
  const { str, approx } = packParts(pcs, units)
  return {
    qv: hasAlternate(units) ? `${approx ? '≈ ' : ''}${str} ${units.displayUom}` : '—',
    qu: `${fmtInt(pcs)} ${units.stockUom || 'PCS'}`
  }
}
function hasAlternate(units) {
  return !!units?.displayUom && units.displayUom !== units.stockUom &&
    Number.isFinite(units.qtyInPack) && units.qtyInPack > 0
}

// T32 (R4): box = berat kg pada MR (float) — teks "Box a / b kg" bila ada isian
const boxText = (r) => (r.box1 != null || r.box2 != null)
  ? `Box ${r.box1 ?? '-'} / ${r.box2 ?? '-'} kg`
  : ''

// ---- kartu: sumber tampilan (selalu turunan payload board) ----
function lotCard(lot) {
  if (lot.unsupported) {
    // §4.9: kartu eksplisit + alasan, sebelum mutasi apa pun (angka numerik null)
    return {
      kind: 'lot', ref: lot.workOrder, key: lot.workOrder, live: false, draggable: false,
      name: lot.item, id: lot.workOrder,
      ql: 'Tidak didukung', qv: '—', qu: '—',
      note: lot.unsupportedReason, meta: '', pill: ''
    }
  }
  const reserved = lotReservedPcs(lot)
  return {
    kind: 'lot', ref: lot.workOrder, key: lot.workOrder,
    live: isGudang.value, draggable: isGudang.value,
    name: lot.item,
    // batch = identitas lot (identifikasi Work Order, keputusan user 2026-09-14)
    id: lot.batch ? `${lot.workOrder} · ${lot.batch}` : lot.workOrder,
    ql: 'Hasil WO',
    ...qtyPair(lot.producedQty, lot),
    // batchless: stok tidak bisa diatribusikan per WO — seluruh saldo item di
    // gudang ini satu pool (angka sama di semua kartu WO item ini)
    note: lot.batchless
      ? `Stok item digabung (tanpa batch)${reserved > 0 ? ` · Tertahan ${fmtInt(reserved)} PCS` : ''}`
      : reserved > 0
        ? `Fisik ${fmtInt(lotRemainingPcs(lot))} PCS · Tertahan ${fmtInt(reserved)} PCS`
        : '',
    // T32 (R7): cap selesai = posting Manufacture TERAKHIR; Masuk tetap FIFO saja
    meta: `Selesai ${fmtStampShort(lot.completedAt || lot.enteredAt)}`,
    pill: `Adonan ${lot.adonanKe ?? '-'}${lot.batchless ? ' · tanpa batch' : ''}`
  }
}

function reqCard(r) {
  const lot0 = lotForWo(r.workOrder)
  const stopped = r.flag === 'stopped'
  return {
    kind: 'request', ref: r.id, key: r.id,
    // Gudang: klik/drag balik = batalkan; Produksi: maju ke Siap Kirim
    live: !stopped, draggable: !stopped,
    name: r.item, id: `${r.workOrder} · ${r.materialRequest}`,
    ql: 'Diminta', ...qtyPair(r.requestedQtyPcs, lot0 || r),
    note: stopped ? 'Dihentikan di Desk — perlu unstop manual sebelum bisa dilanjutkan.' : '',
    meta: [r.batch ? `Batch ${r.batch}` : null, `Adonan ke ${r.adonanKe ?? lot0?.adonanKe ?? '-'}`,
      `Diminta ${fmtStampShort(r.createdAt)}`]
      .filter(Boolean).join(' · '),
    pill: boxText(r) || 'Box belum diisi'
  }
}

function siapCard(r) {
  const lot0 = lotForWo(r.workOrder)
  const p = r.postPacking
  const recorded = (p?.rejectQty ?? 0) + (p?.trialQty ?? 0) + (p?.sisaQty ?? 0)
  return {
    kind: 'siap', ref: r.id, key: r.id,
    live: isProduksi.value, draggable: isProduksi.value,
    name: r.item, id: `${r.workOrder} · ${r.materialRequest}`,
    ql: 'Qty Transfer', ...qtyPair(r.requestedQtyPcs, lot0 || r),
    note: recorded > 0
      ? `Reject ${fmtInt(p.rejectQty ?? 0)} · Trial ${fmtInt(p.trialQty ?? 0)} · Sisa ${fmtInt(p.sisaQty ?? 0)} PCS`
      : '',
    meta: [r.batch ? `Batch ${r.batch}` : null, p?.qc ? `QC ${p.qcLabel || p.qc} · ${p.jam}` : null]
      .filter(Boolean).join(' · '),
    pill: boxText(r) || 'Box belum diisi'
  }
}

function doneCard(r) {
  const lot0 = lotForWo(r.workOrder)
  return {
    kind: 'done', ref: r.id, key: r.id,
    live: false, draggable: false,
    name: r.item, id: `${r.workOrder} · ${r.stockEntry}`,
    ql: 'Ditransfer', ...qtyPair(r.requestedQtyPcs, lot0 || r),
    note: '',
    meta: [r.batch ? `Batch ${r.batch}` : null, fmtStampShort(r.sentAt)].filter(Boolean).join(' · '),
    pill: boxText(r) || 'Box belum diisi'
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
const saveHandoverPreferences = () => saveListPreferences({
  workOrder: savedListPreferences.workOrder || {},
  handover: { from: lotFrom.value, to: lotTo.value, pageSize: coldPageSize.value, filterOpen: lotFilterOpen.value }
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
const coldLots = computed(() => filteredLots.value.filter((l) => (l.unsupported || lotAvailablePcs(l) > 0) && !pendingRequests.has(l.workOrder)))
const coldTotalPages = computed(() => Math.max(1, Math.ceil(coldLots.value.length / coldPageSize.value)))
const pagedColdLots = computed(() => coldLots.value.slice((coldPage.value - 1) * coldPageSize.value, coldPage.value * coldPageSize.value))
watch([lotFrom, lotTo], () => { coldPage.value = 1; saveHandoverPreferences() })
// panel filter tetap terbuka setelah refresh (preferensi per-user, FU18)
watch(lotFilterOpen, () => saveHandoverPreferences())
function lotToday() { lotFrom.value = todayISO(); lotTo.value = todayISO() }
function lotAllDates() { lotFrom.value = ''; lotTo.value = ''; lotFilterOpen.value = false }
function lotReset() { lotFrom.value = ''; lotTo.value = ''; lotFilterOpen.value = false }

const byLane = computed(() => ({
  cold: pagedColdLots.value.map(lotCard),
  request: [
    // optimistic (FU19): kartu pindah duluan selagi create_request berjalan
    ...[...pendingRequests].map(optimisticReqCard).filter(Boolean),
    ...handoverRequests
      .filter((r) => r.lane === 'request' && r.flag !== 'cancelled' && r.flag !== 'draft')
      .map(reqCard),
  ],
  siap: handoverRequests.filter((r) => r.lane === 'siap_kirim').map(siapCard),
  kirim: handoverRequests
    .filter((r) => r.lane === 'terkirim')
    .sort((a, b) => (a.sentAt || '').localeCompare(b.sentAt || ''))
    .map(doneCard)
}))

// ---- drag & drop = niat bisnis: selalu buka dialog dulu ----
const drag = ref(null) // { kind, ref }
const overLane = ref(null)

function targetLanes(d) {
  if (d.kind === 'lot') return ['request']
  if (d.kind === 'siap') return ['kirim']
  return isMultiRole.value ? ['cold', 'siap'] : (isGudang.value ? ['cold'] : ['siap'])
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
  // drop TIDAK mengubah state: lot = request langsung (R3), lainnya buka dialog
  if (d.kind === 'lot') requestLot(d.ref)
  else if (d.kind === 'request') {
    // lane tujuan menentukan aksi: cold = batalkan (gudang), siap = verifikasi (produksi)
    laneKey === 'cold' ? openCancelDialog(d.ref) : openVerifyDialog(d.ref)
  } else if (d.kind === 'siap') openSendDialog(d.ref)
}

function clickCard(c) {
  if (!c.live) return
  if (c.kind === 'lot') requestLot(c.ref)
  else if (c.kind === 'request') {
    isMultiRole.value ? openChooseDialog(c.ref)
      : isGudang.value ? openCancelDialog(c.ref) : openVerifyDialog(c.ref)
  } else if (c.kind === 'siap') openSendDialog(c.ref)
}

// ---- request langsung (R3): drop/klik kartu Cold Storage = request qty penuh WO ----
// Tanpa dialog; qty & guard ketersediaan disimpulkan server (FIFO tetap server-side).
// Optimistic (FU19): kartu langsung pindah ke lane Request Gudang selagi server
// membuat MR; sukses -> board diganti server truth (applyBoard), gagal -> kartu
// kembali ke Cold Storage + modal error (board lokal memang tak pernah berubah).
const pendingRequests = reactive(new Set()) // woId yang create_request-nya masih berjalan

async function requestLot(woId) {
  if (handoverState.pending) return
  pendingRequests.add(woId)
  try { await createRequest(woId) }
  catch (e) { setActionError(e, 'create_request') } // modal error global (FU14)
  finally { pendingRequests.delete(woId) }
}

function optimisticReqCard(woId) {
  const lot = lotForWo(woId)
  if (!lot) return null
  return {
    kind: 'request', ref: `pending:${woId}`, key: `pending:${woId}`,
    live: false, draggable: false, pending: true,
    name: lot.item, id: lot.workOrder,
    ql: 'Diminta', ...qtyPair(lot.producedQty, lot),
    note: 'Menyimpan ke ERPNext…',
    meta: [lot.batch ? `Batch ${lot.batch}` : null, `Adonan ke ${lot.adonanKe ?? '-'}`]
      .filter(Boolean).join(' · '),
    pill: 'Box belum diisi'
  }
}

// ---- dialog (Produksi): Verifikasi Siap Kirim — box-only kg (R4) ----
const dlgVerify = ref(null)
const verReq = ref(null)
const verLot = ref(null)
const verError = ref('')
const verForm = reactive({ box1: '', box2: '' })

// required, numerik, >= 0 — '' -> null (belum diisi), non-numerik/negatif -> NaN
function boxNum(v) {
  const s = String(v ?? '').trim()
  if (s === '') return null
  const n = Number(s)
  return Number.isFinite(n) && n >= 0 ? n : NaN
}
const boxOk = (v) => { const n = boxNum(v); return n != null && !Number.isNaN(n) }
const verCanSave = computed(() => boxOk(verForm.box1) && boxOk(verForm.box2))

function openVerifyDialog(reqId) {
  const r = handoverRequests.find((x) => x.id === reqId)
  if (!r || r.lane !== 'request' || r.flag) return
  verReq.value = r
  verLot.value = lotForWo(r.workOrder)
  verError.value = ''
  verForm.box1 = ''
  verForm.box2 = ''
  nextTick(() => dlgVerify.value.showModal())
}
function closeVerify() {
  dlgVerify.value.close()
  verReq.value = null
  verLot.value = null
}
async function confirmVerify() {
  verError.value = ''
  try {
    await savePostPacking(verReq.value.id, { box1: verForm.box1, box2: verForm.box2 })
    closeVerify()
  } catch (e) {
    verError.value = e.message // input dipertahankan
  }
}

// ---- dialog 3 (Produksi): Kirim Barang ----
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
  if (!r || r.lane !== 'siap_kirim') return
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

// ---- dialog 4 (Gudang): batalkan request salah input ----
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

// ---- dialog pilih aksi (khusus user multi-role: Gudang + Produksi) ----
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
function chooseVerify() {
  const id = chooseRef.value
  closeChoose()
  openVerifyDialog(id)
}
function chooseCancel() {
  const id = chooseRef.value
  closeChoose()
  openCancelDialog(id)
}

onMounted(() => {
  const apply = () => {
    const p = savedListPreferences.handover || {}
    lotFrom.value = p.from || ''; lotTo.value = p.to || ''
    coldPageSize.value = normalizePageSize(p.pageSize)
    lotFilterOpen.value = !!p.filterOpen
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
      <p class="sub">Permintaan gudang dan pengiriman barang jadi dari Cold Storage.</p>
    </div>
    <div class="ph-date">{{ new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }}</div>
  </div>

  <div v-if="handoverState.error" class="appfoot" style="color:#b3261e">Gagal memuat: {{ handoverState.error }} — <a href="#" @click.prevent="loadBoard()">coba lagi</a></div>

  <div class="toolbar">
    <div class="filterwrap">
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
          <span class="kb-sub">{{ l.sub }}</span>
        </div>
        <span class="kb-count">{{ byLane[l.key].length }}</span>
      </header>
      <TransitionGroup name="kc" tag="div" class="kb-cards">
        <div
          v-for="c in byLane[l.key]"
          :key="c.key"
          class="kb-card"
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
          <span class="kb-id">{{ c.id }}</span>
          <div class="kb-qty">
            <span class="ql">{{ c.ql }}</span>
            <span class="qv">{{ c.qv }}</span>
            <span class="qu">{{ c.qu }}</span>
          </div>
          <span v-if="c.note" class="kb-note">{{ c.note }}</span>
          <div v-if="c.meta || c.pill" class="kb-foot">
            <span class="kb-meta">{{ c.meta }}</span>
            <span v-if="c.pill" class="kb-pill">{{ c.pill }}</span>
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

  <!-- ============ dialog: Verifikasi Siap Kirim (Produksi) ============ -->
  <dialog ref="dlgVerify" class="dialog" @click.self="closeVerify">
    <template v-if="verReq">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><PackageCheck :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Verifikasi Siap Kirim</h3>
          <p class="dlg-sub">
            <strong>{{ verReq.workOrder }}</strong> · {{ verReq.item }} · {{ verReq.materialRequest
            }}<template v-if="verReq.batch"> · Batch {{ verReq.batch }}</template>
          </p>
        </div>
      </header>
      <div class="dlg-context">
        <div class="sum-row">
          <span class="k">Diminta</span>
          <span class="v">{{ qtyMain(verReq.requestedQtyPcs, verLot || verReq) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Hasil akhir Work Order</span>
          <span class="v">{{ qtyMain(verLot?.producedQty ?? verReq.requestedQtyPcs, verLot || verReq) }}</span>
        </div>
      </div>
      <div class="boxgroup" style="margin-top: 14px">
        <div class="grouptitle">Box Work Order</div>
        <div class="boxrow">
          <div class="field">
            <label for="ver-box-1">Box 1 (kg) <span class="req">*</span></label>
            <input id="ver-box-1" v-model="verForm.box1" class="input" type="number" step="any" min="0" />
          </div>
          <div class="field">
            <label for="ver-box-2">Box 2 (kg) <span class="req">*</span></label>
            <input id="ver-box-2" v-model="verForm.box2" class="input" type="number" step="any" min="0" />
          </div>
        </div>
      </div>
      <p class="hint" style="margin-top: 8px">Box disimpan pada Work Order. Stock Entry baru dibuat saat request dipindahkan ke Terkirim.</p>

      <p v-if="verError" class="err" style="margin-top: 8px" role="alert">{{ verError }}</p>
      <p v-if="handoverState.pending" role="status">Menyimpan ke ERPNext…</p>
      <div class="dlg-actions">
        <button class="btn" :disabled="!!handoverState.pending" @click="closeVerify">Batal</button>
        <button class="btn btn-primary" :disabled="!verCanSave || !!handoverState.pending" @click="confirmVerify">Siapkan Kirim</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: Kirim Barang (Produksi) ============ -->
  <dialog ref="dlgKirim" class="dialog" @click.self="closeKirim">
    <template v-if="kirimReq">
      <template v-if="!kirimDone">
        <header class="dlg-head">
          <span class="dlg-ico" aria-hidden="true"><Truck :size="16" :stroke-width="1.9" /></span>
          <div class="dlg-hgroup">
            <h3>Kirim Barang</h3>
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
          <span class="v">{{ boxText(kirimReq) || '-' }}</span>
        </div>
        <div class="fgbox" style="margin-top: 10px">
          <span>Qty Transfer</span>
          <span>{{ qtyMain(kirimGood, lotForWo(kirimReq.workOrder) || kirimReq) }}</span>
        </div>
        <p v-if="kirimError" class="err" style="margin-top: 10px" role="alert">{{ kirimError }}</p>
        <p v-if="handoverState.pending" role="status">Menyimpan ke ERPNext…</p>
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
      <p v-if="handoverState.pending" role="status">Menyimpan ke ERPNext…</p>
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
        <button class="btn" @click="chooseCancel">Batalkan (Gudang)</button>
        <button class="btn btn-primary" @click="chooseVerify">Verifikasi Siap Kirim (Produksi)</button>
      </div>
    </template>
  </dialog>
</template>

<script setup>
// Adapted from the mockup HandoverBoard.vue (read-only source): role simulation
// strip and fail-injection removed; roles, lots, lanes and warehouses come from
// the server board payload (T23/T24) — the UI never writes lane state.
import { computed, nextTick, reactive, onMounted, ref, watch } from 'vue'
import {
  cancelRequest, createRequest, handoverBoard, handoverLots, handoverRequests, handoverState,
  listPreferencesState, loadBoard, lotAvailablePcs, lotForWo, lotRemainingPcs, lotReservedPcs, normalizePageSize, PAGE_SIZE_OPTIONS, saveListPreferences, savedListPreferences, savePostPacking, sendHandover, setActionError,
  bulkHandoverItem
} from './store.js'
import {
  BULK_LIMIT, CARD_LANE,
  bulkCardEligible, bulkEligibleRefs, bulkEntryOfCard, bulkLaneActions, bulkRequiresReload, bulkRetryAvailable,
  reconcileBulkSelection, runBulkItems, selectAllBulk, toggleBulkSelection, validateBulkEntries, validateBoxKg
} from './handover-bulk.js'
import { fmtInt, qtyMain } from './format.js'
import { handoverCard } from './handover-card.js'
import {
  CheckCircle2, ClipboardList, Filter, GripVertical, Inbox,
  ListChecks, PackageCheck, Snowflake, Truck, Undo2
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

// T32 (R4): box = berat kg pada MR (float) — teks "Box a / b kg" bila ada isian
const boxText = (r) => (r.box1 != null || r.box2 != null)
  ? `${r.box1 ?? '-'} / ${r.box2 ?? '-'} kg`
  : ''

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
      box: boxText(r) || undefined
    }),
    note: [stopped ? 'Dihentikan di Desk. Aktifkan kembali sebelum dilanjutkan.' : '', routeWarn(r)]
      .filter(Boolean).join(' · ')
  }
}

function siapCard(r) {
  const lot0 = lotForWo(r.workOrder)
  const p = r.postPacking
  return {
    kind: 'siap', ref: r.id, key: r.id,
    live: isProduksi.value, draggable: isProduksi.value,
    name: r.item,
    ...handoverCard({
      workOrder: r.workOrder,
      document: r.materialRequest,
      batch: r.batch,
      adonan: r.adonanKe ?? lot0?.adonanKe,
      quantity: r.requestedQtyPcs,
      quantityLabel: 'Qty kirim',
      timestampLabel: p?.jam ? 'Jam packing' : '',
      timestamp: p?.jam,
      units: lot0 || r,
      box: boxText(r) || undefined
    }),
    note: [p?.qc ? `QC ${p.qcLabel || p.qc}` : '', routeWarn(r)].filter(Boolean).join(' · ')
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
      box: boxText(r) || undefined
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
  if (bulk.mode || !c.draggable) return
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
  if (bulk.mode) return // mode pilih: drag dinonaktifkan (toggling via klik/checkbox)
  if (!d || !targetLanes(d).includes(laneKey)) return
  // drop TIDAK mengubah state: lot = request langsung (R3), lainnya buka dialog
  if (d.kind === 'lot') requestLot(d.ref)
  else if (d.kind === 'request') {
    // lane tujuan menentukan aksi: cold = batalkan (gudang), siap = verifikasi (produksi)
    laneKey === 'cold' ? openCancelDialog(d.ref) : openVerifyDialog(d.ref)
  } else if (d.kind === 'siap') openSendDialog(d.ref)
}

function clickCard(c) {
  if (bulk.mode) { toggleBulkCard(c); return } // mode pilih: klik = toggle, bukan dialog
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
    name: lot.item,
    ...handoverCard({
      workOrder: lot.workOrder,
      batch: lot.batch,
      adonan: lot.adonanKe,
      quantity: lot.producedQty,
      quantityLabel: 'Diminta',
      timestampLabel: '',
      units: lot
    }),
    note: 'Menyimpan…'
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

// ============================================================================
// Bulk select (T40 phase B): mode pilih + orkestrasi runBulkItems.
// Papan TIDAK pernah diubah selama run — kartu tidak berpindah optimistis,
// papan digantikan tepat sekali oleh loadBoard() final di dalam runner.
// Seleksi berupa snapshot datar (bulkEntryOfCard) sehingga tetap sah walau
// objek kartu dibuat ulang saat reload. pendingRequests tidak disentuh.
// ============================================================================
const bulk = reactive({
  mode: false, lane: null, selected: [], boxes: {},
  pending: false, progress: null, confirm: null, lastAction: null,
  notice: '', result: null, requiresReload: false
})
const bulkConfirmError = ref('')
const dlgBulk = ref(null)
const dlgBulkResult = ref(null)

const bulkSelectedRefs = computed(() => new Set(bulk.selected.map((e) => e.ref)))
const laneActions = computed(() =>
  bulk.mode && bulk.lane ? bulkLaneActions(bulk.lane, handoverBoard.roles) : []
)
const laneTitle = (key) => lanes.find((l) => l.key === key)?.title || key
// eligibility murni terhadap lane terkunci + peran; mode/pending dicek terpisah
// agar dim & checkbox stabil selama run berjalan
const bulkCanSelect = (c) => bulkCardEligible(c, { roles: handoverBoard.roles, selectedLane: bulk.lane })
const isBulkSelected = (c) => bulkSelectedRefs.value.has(c.ref)
const isBulkDim = (c) => bulk.mode && !bulkCanSelect(c)
const bulkCheckLabel = (c) =>
  `Pilih ${c.workOrder}${c.document ? ' · ' + c.document : ''} — ${laneTitle(CARD_LANE[c.kind])}`

function enterBulk() {
  Object.assign(bulk, {
    mode: true, lane: null, selected: [], boxes: {}, pending: false,
    progress: null, confirm: null, lastAction: null, notice: '', result: null, requiresReload: false
  })
}
// keluar mode membuang pilihan + nilai Box yang belum disimpan (§3.1);
// satu-satunya jalan keluar selain reload sukses saat gate stale aktif
function exitBulk() {
  if (bulk.pending) return
  dlgBulk.value?.close()
  dlgBulkResult.value?.close()
  Object.assign(bulk, {
    mode: false, lane: null, selected: [], boxes: {}, progress: null,
    confirm: null, lastAction: null, notice: '', result: null, requiresReload: false
  })
  bulkConfirmError.value = ''
}
function clearBulkSelection() {
  if (bulk.requiresReload || bulk.pending) return
  bulk.selected = []
  bulk.boxes = {}
  bulk.lane = null // pilihan kosong = kunci lane lepas (§3.1)
  bulk.notice = ''
}

// isian Box per Material Request (opsional; kosong = konvensi tersimpan 0)
function ensureBoxRow(e) {
  if (e.kind !== 'lot' && !bulk.boxes[e.ref]) bulk.boxes[e.ref] = { box1: '', box2: '' }
}

function toggleBulkCard(c) {
  if (!bulk.mode || bulk.pending || bulk.requiresReload) return
  const lane = CARD_LANE[c.kind]
  if (!bulkCanSelect(c)) {
    if (bulk.lane && lane && lane !== bulk.lane) {
      bulk.notice = `Pilihan terkunci ke ${laneTitle(bulk.lane)} — kosongkan pilihan untuk memilih lane lain.`
    }
    return
  }
  try {
    bulk.selected = toggleBulkSelection(bulk.selected, bulkEntryOfCard(c))
    ensureBoxRow(c)
    bulk.notice = ''
  } catch (e) {
    bulk.notice = e.message // kartu ke-21: pesan batas 20 kartu
  }
}

function selectAllPage() {
  if (!bulk.mode || bulk.pending || bulk.requiresReload || !bulk.lane) return
  const { entries, truncated } = selectAllBulk(byLane.value[bulk.lane], {
    roles: handoverBoard.roles, selectedLane: bulk.lane, selected: bulk.selected
  })
  bulk.selected = entries
  for (const e of entries) ensureBoxRow(e)
  bulk.notice = truncated ? `Maksimal ${BULK_LIMIT} kartu per proses massal — sisanya tidak dipilih.` : ''
}

// ---- dialog konfirmasi massal (per aksi; dual-role Request = dua tombol) ----
const BULK_CONFIRM_META = {
  create_request: { title: 'Buat Request Gudang', button: (n) => `Buat ${n} Request Gudang` },
  cancel_request: { title: 'Batalkan Request', button: (n) => `Batalkan ${n} Request` },
  save_post_packing: { title: 'Verifikasi Siap Kirim', button: (n) => `Verifikasi ${n} Request` },
  send_handover: { title: 'Kirim Barang', button: (n) => `Kirim ${n} Barang` }
}
const bulkConfirmTitle = computed(() => BULK_CONFIRM_META[bulk.confirm]?.title || 'Konfirmasi')
const bulkConfirmButton = computed(() => BULK_CONFIRM_META[bulk.confirm]?.button(bulk.selected.length) || 'Proses')
const bulkLaneIcon = computed(() => lanes.find((l) => l.key === bulk.lane)?.icon || ClipboardList)

// §7.1: seluruh isian Box divalidasi client sebelum run; tombol terkunci selama ada isian salah
const bulkBoxOk = (v) => { try { validateBoxKg(v); return true } catch { return false } }
const bulkRowBoxesOk = (e) => bulkBoxOk(bulk.boxes[e.ref]?.box1) && bulkBoxOk(bulk.boxes[e.ref]?.box2)
const bulkVerifyReady = computed(() =>
  bulk.confirm !== 'save_post_packing' || bulk.selected.every(bulkRowBoxesOk)
)

function openBulkConfirm(action) {
  if (!bulk.mode || !bulk.selected.length || bulk.pending || bulk.requiresReload) return
  for (const e of bulk.selected) ensureBoxRow(e)
  bulk.confirm = action
  bulk.lastAction = action
  bulkConfirmError.value = ''
  nextTick(() => dlgBulk.value.showModal())
}
function closeBulkConfirm() { dlgBulk.value?.close() }
function onBulkConfirmClose() {
  if (bulk.confirm && !bulk.pending) {
    bulk.confirm = null
    bulkConfirmError.value = ''
  }
}

function bulkRunEntry(e, action) {
  const entry = action === 'create_request'
    ? { lane: e.lane, action, work_order: e.ref }
    : { lane: e.lane, action, material_request: e.ref }
  if (action === 'save_post_packing') {
    const b = bulk.boxes[e.ref] || {}
    entry.box_1 = b.box1 ?? ''
    entry.box_2 = b.box2 ?? ''
  }
  return entry
}

// refs kartu yang SAAT INI dirender + eligible di lane — sumbernya byLane
// (jalur render yang sama: filter, halaman, supported, stopped, optimistic
// pending sudah termuat), dasar rekonsiliasi §8 dan validasi pra-run §7.1
const bulkEligibleRefsInLane = (laneKey) => bulkEligibleRefs(byLane.value[laneKey], handoverBoard.roles)

async function runBulk() {
  const action = bulk.confirm
  // gate stale (§3.4): run terakhir belum diikuti reload sukses — semua aksi terkunci
  if (!action || bulk.pending || bulk.requiresReload) return
  // §7.1 pra-run: kartu yang tidak lagi dirender/eligible (filter/halaman
  // berubah) dipangkas, tidak pernah diproses diam-diam
  const eligibleRefs = bulkEligibleRefsInLane(bulk.lane)
  const runnable = bulk.selected.filter((e) => eligibleRefs.has(e.ref))
  const dropped = bulk.selected.length - runnable.length
  if (!runnable.length) {
    bulkConfirmError.value = 'Tidak ada kartu yang masih bisa diproses — periksa filter/halaman papan.'
    return
  }
  const entries = runnable.map((e) => bulkRunEntry(e, action))
  // §7.1 validasi client envelope (pure, diuji Node) SEBELUM dialog ditutup —
  // isian salah membuat dialog tetap terbuka; jalur "buka ulang dialog" dihapus
  try {
    validateBulkEntries(entries, { roles: handoverBoard.roles })
  } catch (e) {
    bulkConfirmError.value = e.message
    return
  }
  bulk.notice = dropped ? `${dropped} kartu tidak lagi tersedia dan tidak diproses.` : ''
  bulk.selected = runnable
  closeBulkConfirm()
  bulk.pending = true
  try {
    const result = await runBulkItems({
      entries,
      roles: handoverBoard.roles,
      rpc: bulkHandoverItem,
      loadBoard: async () => {
        await loadBoard()
        if (handoverState.error) throw new Error(handoverState.error)
      },
      onProgress: (p) => { bulk.progress = p },
      runId: `BULK-${Date.now()}`
    })
    // satu-satunya pembaruan papan berasal dari loadBoard() final di runner;
    // seleksi direkonsiliasi ketat terhadap server truth yang dirender (§8)
    const eligible = bulkEligibleRefsInLane(bulk.lane)
    bulk.selected = reconcileBulkSelection(bulk.selected, result, (e) => eligible.has(e.ref))
    bulk.confirm = null
    bulk.result = result
    // §3.4: reload gagal = seleksi cocok dengan papan basi — kunci semua aksi
    bulk.requiresReload = bulkRequiresReload(result)
    nextTick(() => dlgBulkResult.value.showModal())
  } catch (e) {
    // jalur tak terduga (validasi sudah lolos): pilihan & isian tetap utuh
    bulk.notice = e.message
  } finally {
    bulk.pending = false
    bulk.progress = null
  }
}

// ---- dialog hasil: ringkasan + daftar gagal aman + retry + muat ulang ----
const bulkUnprocessedCount = computed(() =>
  bulk.result ? bulk.result.unprocessed.length + (bulk.result.uncertain ? 1 : 0) : 0
)
const bulkAllOk = computed(() => !!bulk.result && !bulk.result.failures.length && !bulkUnprocessedCount.value)
// §3.4: retry hanya setelah reload papan SELESAI dan masih ada kandidat —
// ketika reload gagal seleksi di-reconcile terhadap papan basi, jadi dikunci
const bulkRetryReady = computed(() => bulkRetryAvailable(bulk.result, bulk.selected.length))
const bulkFailRows = computed(() => {
  if (!bulk.result) return []
  return [
    ...bulk.result.failures.map((r) => ({ ...r })),
    ...(bulk.result.uncertain ? [{ ...bulk.result.uncertain }] : []),
    ...bulk.result.unprocessed.map((r) => ({ ...r, message: r.message || 'Belum diproses karena run dihentikan.' }))
  ]
})
function closeBulkResult() { dlgBulkResult.value?.close() }
function onBulkResultClose() {
  if (!bulk.result) return
  bulk.result = null
  if (bulk.mode && !bulk.selected.length) exitBulk()
}
function retryBulkFailed() {
  // §3.4: tanpa reload selesai, seleksi hanya cocok dengan papan basi — jangan coba ulang
  if (!bulk.mode || !bulkRetryReady.value || bulk.pending || bulk.requiresReload) return
  const action = bulk.lastAction
  closeBulkResult()
  bulk.result = null
  openBulkConfirm(action) // isian Box dipertahankan (bulk.boxes tidak dibersihkan)
}
async function reloadAfterBulk() {
  await loadBoard()
  if (handoverState.error) return // gagal muat lagi: gate stale TETAP aktif; dialog terbuka
  if (bulk.result) bulk.result.boardReloaded = true
  bulk.requiresReload = false // reload sukses: rekonsiliasi ulang, lalu buka kunci
  // rekonsiliasi ulang seleksi tersisa terhadap server truth terbaru
  const eligible = bulkEligibleRefsInLane(bulk.lane)
  bulk.selected = reconcileBulkSelection(
    bulk.selected,
    { successes: [], failures: [], uncertain: null, unprocessed: bulk.selected.map((e) => ({ ref: e.ref })) },
    (e) => eligible.has(e.ref)
  )
  if (!bulk.selected.length) closeBulkResult()
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
    <button
      v-if="isGudang || isProduksi"
      class="btn filterbtn"
      :class="{ active: bulk.mode }"
      aria-label="Pilih banyak kartu"
      :aria-pressed="bulk.mode ? 'true' : 'false'"
      :disabled="bulk.pending"
      @click="bulk.mode ? exitBulk() : enterBulk()"
    >
      <ListChecks :size="14" :stroke-width="2" />
      <span class="btext">Pilih</span>
    </button>
  </div>

  <!-- bar aksi massal: sticky, di atas navigasi bawah mobile -->
  <div v-if="bulk.mode" class="bulkbar" role="region" aria-label="Aksi massal kartu terpilih">
    <span class="bulk-count" role="status">
      <strong>{{ bulk.selected.length }}</strong> dipilih<template v-if="bulk.lane"> · {{ laneTitle(bulk.lane) }}</template><template v-if="bulk.pending && bulk.progress"> · memproses {{ bulk.progress.done + 1 }} dari {{ bulk.progress.total }} ({{ bulk.progress.ref }})…</template>
    </span>
    <span v-if="bulk.pending && !bulk.progress" class="bulk-progress" role="status">Menyiapkan…</span>
    <span class="bulk-spacer" aria-hidden="true"></span>
    <button class="btn btn-sm" :disabled="bulk.pending" @click="exitBulk">Batal</button>
    <!-- gate stale (§3.4): reload papan gagal — hanya Muat ulang / Batal -->
    <template v-if="bulk.requiresReload">
      <span class="bulk-progress bulk-stale-warn" role="alert">Papan gagal dimuat — muat ulang sebelum melanjutkan.</span>
      <button class="btn btn-sm btn-primary" :disabled="bulk.pending" @click="reloadAfterBulk">Muat ulang</button>
    </template>
    <template v-else>
      <button class="btn btn-sm" :disabled="!bulk.lane || bulk.pending" @click="selectAllPage">Pilih semua di halaman</button>
      <button class="btn btn-sm" :disabled="!bulk.selected.length || bulk.pending" @click="clearBulkSelection">Kosongkan</button>
      <button
        v-for="a in laneActions"
        :key="a"
        class="btn btn-sm btn-primary"
        :disabled="!bulk.selected.length || bulk.pending"
        @click="openBulkConfirm(a)"
      >{{ BULK_CONFIRM_META[a].button(bulk.selected.length) }}</button>
    </template>
    <p v-if="bulk.notice" class="bulk-notice" role="alert">{{ bulk.notice }}</p>
  </div>

  <div class="kb" :class="{ dragging: !!drag, selecting: bulk.mode }">
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
          class="kb-card se-kb-card"
          :class="{
            live: c.live,
            pending: c.pending,
            dragging: drag && drag.kind === c.kind && drag.ref === c.ref,
            'bulk-sel': isBulkSelected(c),
            'bulk-dim': isBulkDim(c),
            'bulk-run': bulk.pending && isBulkSelected(c)
          }"
          :draggable="bulk.mode ? false : c.draggable"
          :aria-disabled="isBulkDim(c) ? 'true' : undefined"
          @dragstart="onDragStart($event, c)"
          @dragend="onDragEnd"
          @click="clickCard(c)"
        >
          <div class="kb-top">
            <label v-if="bulk.mode && bulkCanSelect(c)" class="bulk-check">
              <input
                type="checkbox"
                :checked="isBulkSelected(c)"
                :disabled="bulk.pending || bulk.requiresReload"
                :aria-label="bulkCheckLabel(c)"
                @click.stop
                @change="toggleBulkCard(c)"
              />
            </label>
            <span class="kb-name">{{ c.name }}</span>
            <GripVertical v-if="c.draggable && !bulk.mode" class="kb-grip" :size="15" :stroke-width="2" aria-hidden="true" />
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
      <p v-if="handoverState.pending" role="status">Menyimpan…</p>
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
        <button class="btn" @click="chooseCancel">Batalkan (Gudang)</button>
        <button class="btn btn-primary" @click="chooseVerify">Verifikasi Siap Kirim (Produksi)</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog konfirmasi aksi massal (semua peran) ============ -->
  <dialog ref="dlgBulk" class="dialog dialog-wide" @click.self="closeBulkConfirm" @close="onBulkConfirmClose">
    <template v-if="bulk.confirm">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><component :is="bulkLaneIcon" :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>{{ bulkConfirmTitle }} — {{ bulk.selected.length }} kartu</h3>
          <p class="dlg-sub">{{ laneTitle(bulk.lane) }} · diproses berurutan, satu transaksi per kartu</p>
        </div>
      </header>

      <div class="bulk-rows">
        <div
          v-for="e in bulk.selected"
          :key="e.ref"
          class="bulk-row"
          :class="{ invalid: bulk.confirm === 'save_post_packing' && !bulkRowBoxesOk(e) }"
        >
          <div class="bulk-row-main">
            <span class="bulk-row-name">{{ e.name }}</span>
            <span class="bulk-row-ref">{{ e.workOrder }}<template v-if="e.materialRequest"> · {{ e.materialRequest }}</template></span>
            <span v-if="e.batch" class="bulk-row-ref">Batch {{ e.batch }}</span>
            <span v-if="e.quantity" class="bulk-row-ref">{{ e.quantity }}</span>
            <span v-if="e.note" class="bulk-row-note">{{ e.note }}</span>
          </div>
          <!-- form Box per request (§3.3): responsif, label terikat per baris -->
          <div v-if="bulk.confirm === 'save_post_packing'" class="bulk-row-boxes">
            <div class="field">
              <label :for="`bb1-${e.ref}`">Box 1 (kg)</label>
              <input :id="`bb1-${e.ref}`" v-model="bulk.boxes[e.ref].box1" class="input" type="number" step="any" min="0" inputmode="decimal" />
            </div>
            <div class="field">
              <label :for="`bb2-${e.ref}`">Box 2 (kg)</label>
              <input :id="`bb2-${e.ref}`" v-model="bulk.boxes[e.ref].box2" class="input" type="number" step="any" min="0" inputmode="decimal" />
            </div>
          </div>
        </div>
      </div>
      <p v-if="bulk.confirm === 'save_post_packing'" class="hint">Box opsional — kosong berarti 0 kg. Nilai disimpan per Material Request.</p>
      <p v-if="bulk.confirm === 'cancel_request'" class="hint">Reservasi pada Cold Storage akan dilepas untuk setiap request.</p>
      <p v-if="bulk.confirm === 'create_request'" class="hint">Satu Material Request dibuat per Work Order — tidak digabung.</p>

      <p v-if="bulkConfirmError" class="err" role="alert">{{ bulkConfirmError }}</p>
      <div class="dlg-actions">
        <button class="btn" @click="closeBulkConfirm">Kembali</button>
        <button class="btn btn-primary" :disabled="!bulkVerifyReady" @click="runBulk">{{ bulkConfirmButton }}</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog hasil proses massal ============ -->
  <dialog ref="dlgBulkResult" class="dialog dialog-wide" @click.self="closeBulkResult" @close="onBulkResultClose">
    <template v-if="bulk.result">
      <header class="dlg-head">
        <span class="dlg-ico" :class="{ ok: bulkAllOk }" aria-hidden="true"><CheckCircle2 :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Hasil Proses Massal</h3>
          <p class="dlg-sub">{{ laneTitle(bulk.lane) }}</p>
        </div>
      </header>
      <p class="bulk-summary" role="status">
        <strong>{{ bulk.result.successes.length }} berhasil</strong>, {{ bulk.result.failures.length }} gagal<template v-if="bulkUnprocessedCount">, {{ bulkUnprocessedCount }} belum diproses</template>
      </p>
      <div v-if="bulkFailRows.length" class="bulk-fails">
        <div v-for="r in bulkFailRows" :key="`${r.action}-${r.ref}`" class="bulk-fail">
          <span class="bulk-fail-ref">{{ r.ref }}</span>
          <span class="bulk-fail-msg">{{ r.message }}</span>
        </div>
      </div>
      <p v-if="!bulk.result.boardReloaded" class="callout bad bulk-reload-warn">
        Papan gagal dimuat. Muat ulang untuk melihat data terbaru.
        <button class="btn btn-sm" @click="reloadAfterBulk">Muat ulang</button>
      </p>
      <div class="dlg-actions">
        <button v-if="bulkRetryReady" class="btn" @click="retryBulkFailed">Coba lagi yang gagal</button>
        <button class="btn btn-primary" @click="closeBulkResult">Tutup</button>
      </div>
    </template>
  </dialog>
</template>

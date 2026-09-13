import { reactive } from 'vue'

// ============================================================================
// ADAPTER SERVER (T13/T14) — menggantikan mock store.
// Semua data & stage datang dari server: /api/method/production_app.api...
// Frontend TIDAK PERNAH menurunkan stage sendiri; setelah tiap aksi, state
// lokal di-update dari respons server (server = sumber kebenaran).
// Serah terima (handover) sengaja TIDAK diikutkan di rilis ini.
// ============================================================================

export const STAGE_LABELS = {
  persiapan: 'Persiapan',
  material: 'Material',
  operasi: 'Operasi',
  pre_packing: 'Pre-Packing',
  finish: 'Finish',
  selesai: 'Selesai',
  cancelled: 'Dibatalkan',
  review: 'Review'
}
// kompatibilitas panggilan lama yang memakai kunci mock
STAGE_LABELS.prepacking = 'Pre-Packing'
STAGE_LABELS.completed = 'Selesai'

// stage server -> kunci internal mockup (komponen tak perlu tahu bedanya)
const STAGE_UI = {
  persiapan: 'persiapan', material: 'material', operasi: 'operasi',
  pre_packing: 'prepacking', finish: 'finish', selesai: 'completed',
  cancelled: 'cancelled', review: 'review'
}

export const fieldUnits = reactive({})
export const listPrefs = reactive({ view: 'tabel' })

export const state = reactive({ loading: false, error: null, loaded: false })
export const workOrders = reactive([])

function hhmm(v) {
  return v ? String(v).slice(0, 5) : ''
}

export function mapDetail(d) {
  // server wo_detail -> bentuk WO yang dipakai komponen mockup
  return {
    id: d.name,
    name: d.name,
    product: d.production_item_name || d.production_item,
    itemCode: d.production_item,
    plannedDate: (d.planned_start_date || '').slice(0, 10),
    status: d.status,
    stage: STAGE_UI[d.stage] || d.stage,
    hasOperations: (d.operations || []).length > 0,
    qtyInPack: d.custom_qty_in_uom ?? 0,
    plannedStockQty: d.qty ?? 0,
    stockUom: d.stock_uom,
    conversionFactor: d.custom_conversion_factor ?? 1,
    remainingTransfer: d.remaining_transfer ?? 0,
    remainingProduce: d.remaining_produce ?? 0,
    maxAllowedQty: d.max_allowed_qty ?? 0,
    warehouse: d.fg_warehouse || '',
    wipWarehouse: d.wip_warehouse || '',
    sourceWarehouse: d.source_warehouse || '',
    persiapan: {
      adonanKe: d.custom_adonan_ke ?? null,
      jamAdonan: hhmm(d.custom_jam_adonan),
      suhuAdonan: d.custom_suhu_adonan ?? null,
      namaPenimbang: d.custom_nama_penimbang_full || d.custom_nama_penimbang || '',
      jumlahKru: d.custom_jumlah_kru ?? null,
      leaderProduksi: d.custom_leader_produksi || ''
    },
    material: {
      items: (d.required_items || []).map((i) => ({
        code: i.item_code,
        name: i.item_name || i.item_code,
        required: i.required_qty,
        transferred: i.transferred_qty,
        uom: i.stock_uom
      }))
    },
    operations: (d.operations || []).map((o) => {
      const cards = (d.job_cards || []).filter((c) => c.operation_id === o.name)
      const primary = cards.find((c) => c.docstatus === 1) || cards[0] || {}
      const times = (primary.time_logs || [])
      return {
        id: primary.name || null,
        cardIds: cards.map((c) => c.name),
        name: o.operation,
        workstation: o.workstation || primary.workstation || '',
        operator: (primary.employees || [])[0]?.employee_name || '',
        plannedPcs: primary.for_quantity ?? d.qty,
        completedPcs: primary.total_completed_qty ?? o.completed_qty ?? 0,
        status:
          o.status === 'Completed' ? 'done'
          : primary.status === 'Work In Progress' || times.some((t) => t.from_time && !t.to_time) ? 'in_progress'
          : 'pending',
        start: hhmm(times[0]?.from_time),
        end: hhmm(times[times.length - 1]?.to_time)
      }
    }),
    prepacking: {
      goodQty: d.custom_good_qty_prepacking ?? null,
      rejectQty: d.custom_reject_qty_prepacking ?? null,
      trialQty: d.custom_trial_qty_prepacking ?? null,
      sisaQty: d.custom_sisa_qty_prepacking ?? null,
      jam: hhmm(d.custom_jam_pembekuan),
      qc: d.custom_qc_produksi_full || d.custom_qc_produksi || '',
      box1: d.custom_box_1 ?? null,
      box2: d.custom_box_2 ?? null,
      confirmed: !!d.custom_prepacking_confirmed
    },
    requiredItemsLoaded: true,
    postpacking: {
      goodQty: d.custom_good_qty_postpacking ?? null,
      rejectQty: d.custom_reject_qty_postpacking ?? null,
      trialQty: d.custom_trial_qty_postpacking ?? null,
      sisaQty: d.custom_sisa_qty_postpacking ?? null,
      jam: hhmm(d.custom_jam_packing),
      qc: d.custom_qc_packing_full || d.custom_qc_packing || ''
    },
    finishedAt: d.actual_end_date ? String(d.actual_end_date).slice(0, 10) : ''
  }
}

function applyDetail(mapped) {
  const i = workOrders.findIndex((w) => w.id === mapped.id)
  if (i === -1) workOrders.push(mapped)
  else Object.assign(workOrders[i], mapped)
  return mapped
}

async function call(method, args) {
  const res = await fetch(`/api/method/${method}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Frappe-CSRF-Token': window.csrf_token || ''
    },
    body: JSON.stringify(args || {})
  })
  const data = await res.json()
  if (!res.ok) {
    const msg = data && data._server_messages
      ? JSON.parse(data._server_messages).map((m) => JSON.parse(m).message).join(' ')
      : (data && data.exc) ? 'Validasi ERPNext gagal'
        : (data && data.message) || res.statusText
    throw new Error(msg)
  }
  return data.message
}

export async function loadList() {
  state.loading = true
  state.error = null
  try {
    const rows = await call('production_app.api.work_order.wo_list', { page_len: 200 })
    // baris list dipakai untuk tabel/kanban; detail diambil saat WO dibuka
    workOrders.splice(0, workOrders.length, ...rows.map((r) => ({
      id: r.name,
      name: r.name,
      product: r.production_item_name || r.production_item,
      itemCode: r.production_item,
      plannedDate: (r.planned_start_date || '').slice(0, 10),
      status: r.status,
      stage: STAGE_UI[r.stage] || r.stage,
      hasOperations: !!r.has_operations,
      qtyInPack: r.custom_qty_in_uom ?? 0,
      plannedStockQty: r.qty ?? 0,
      stockUom: r.stock_uom,
      warehouse: r.fg_warehouse || '',
      persiapan: { adonanKe: null },
      material: { items: [] },
      prepacking: {}
    })))
    state.loaded = true
  } catch (e) {
    state.error = e.message
  } finally {
    state.loading = false
  }
}

export async function refreshWo(id) {
  const d = await call('production_app.api.work_order.wo_detail', { name: id })
  return applyDetail(mapDetail(d))
}

export function getWo(id) {
  return workOrders.find((w) => w.id === id) || null
}

export async function openWo(id) {
  if (!getWo(id)?.requiredItemsLoaded) return refreshWo(id)
  return getWo(id)
}

// ---- helper material (bentuk mapped) ----
export function materialShortages(w) {
  return (w.material?.items || []).filter((i) => i.transferred < i.required)
}
export function materialComplete(w) {
  return materialShortages(w).length === 0
}
export function opsAllDone(w) {
  return !!w.operations && w.operations.every((o) => o.status === 'done')
}
export function producedQty(w) {
  return w.prepacking?.goodQty ?? 0
}

// ---- aksi (endpoint server, state di-refresh dari respons) ----
export async function startProduction(w, data) {
  await call('production_app.api.work_order.prepare', {
    name: w.id,
    values: {
      adonan_ke: data.adonanKe,
      jam_adonan: data.jamAdonan,
      suhu_adonan: data.suhuAdonan,
      penimbang: data.penimbang,
      jumlah_kru: data.jumlahKru,
      leader: data.leaderProduksi
    },
    submit: 1
  })
  return refreshWo(w.id)
}

export async function transferAll(w) {
  await call('production_app.api.work_order.transfer_materials', { name: w.id })
  return refreshWo(w.id)
}

export async function confirmMaterial(w) {
  return refreshWo(w.id) // stage murni server-side; cukup segarkan
}

async function completeCard(w, op, qty) {
  const cardId = op.cardIds?.[op.cardIds.length - 1] || op.id
  if (!cardId) throw new Error('Job Card tidak ditemukan untuk operasi ini')
  const res = await call('production_app.api.work_order.jobcard_complete', {
    name: w.id,
    job_card: cardId,
    qty,
    auto_submit: 1
  })
  await refreshWo(w.id)
  return res
}

export async function startOperation(w, op) {
  const cardId = op.cardIds?.[0] || op.id
  if (!cardId) throw new Error('Job Card tidak ditemukan untuk operasi ini')
  await call('production_app.api.work_order.jobcard_start', { name: w.id, job_card: cardId })
  return refreshWo(w.id)
}

export function finishOperation(w, op, completedPcs) {
  return completeCard(w, op, completedPcs)
}

export async function confirmOperations(w) {
  return refreshWo(w.id)
}

export async function savePrePacking(w, data) {
  await call('production_app.api.work_order.confirm_prepacking', {
    name: w.id,
    values: {
      good: data.goodQty,
      reject: data.rejectQty,
      trial: data.trialQty,
      sisa: data.sisaQty,
      jam_pembekuan: data.jam,
      qc_produksi: data.qc,
      box_1: data.box1,
      box_2: data.box2
    }
  })
  return refreshWo(w.id)
}

export async function completeProduction(w) {
  return refreshWoAfterFinish(w)
}

async function refreshWoAfterFinish(w) {
  const res = await call('production_app.api.work_order.finish', { name: w.id })
  const mapped = await refreshWo(w.id)
  return { res, mapped, finishedAt: mapped.finishedAt }
}

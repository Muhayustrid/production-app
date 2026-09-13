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

export const state = reactive({ loading: false, error: null, loaded: false, pending: null, actionError: null })
export const workOrders = reactive([])

function hhmm(v) {
  return v ? (String(v).match(/(?:^|[ T])(\d{1,2}):([0-9]{2})/)?.slice(1).map(x => x.padStart(2, '0')).join(':') || '') : ''
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
    qtyInPack: d.display_conversion_factor ?? null,
    displayUom: d.display_uom || d.stock_uom,
    wholeNumber: !!d.stock_uom_whole_number,
    uomWarning: d.uom_warning,
    producedStockQty: d.produced_qty ?? 0,
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
      namaPenimbang: d.custom_nama_penimbang || '',
      penimbangLabel: d.custom_nama_penimbang_full || d.custom_nama_penimbang || '',
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
    operations: (d.job_cards || []).map((card) => {
      const operation = (d.operations || []).find(o => o.name === card.operation_id) || {}
      const times = card.time_logs || []
      return {
        id: card.name,
        name: card.operation,
        workstation: card.workstation || operation.workstation || '',
        employees: card.employees || [],
        operator: (card.employees || []).map(e => e.employee_name).join(', '),
        plannedPcs: card.for_quantity ?? d.qty,
        completedPcs: card.total_completed_qty ?? 0,
        lossQty: card.process_loss_qty ?? 0,
        status: card.docstatus === 1 ? 'done' : times.some(t => t.from_time && !t.to_time) ? 'in_progress' : 'pending',
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
      qc: d.custom_qc_produksi || '',
      qcLabel: d.custom_qc_produksi_full || d.custom_qc_produksi || '',
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
  return workOrders.find(w => w.id === mapped.id)
}

export async function call(method, args) {
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
    // Do not replace a detail already loaded while the initial list request was pending.
    const details = new Map(workOrders.filter(w => w.requiredItemsLoaded).map(w => [w.id, w]))
    const mapped = rows.map(r => details.get(r.name) || { ...mapDetail(r), hasOperations: !!r.has_operations, requiredItemsLoaded: false })
    for (const [id, detail] of details) if (!mapped.some(w => w.id === id)) mapped.push(detail)
    workOrders.splice(0, workOrders.length, ...mapped)
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

export async function openWo(id) { return refreshWo(id) }

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

// Shared by workspace panels and kanban dialogs. Errors remain visible in the form.
async function perform(w, method, args = {}) {
  if (state.pending) return null
  state.pending = w.id
  state.actionError = null
  try {
    await call(`production_app.api.work_order.${method}`, { name: w.id, ...args })
    return await refreshWo(w.id)
  } catch (error) {
    state.actionError = error.message
    return null
  } finally {
    state.pending = null
  }
}

export function startProduction(w, data) {
  return perform(w, 'prepare', {
    values: {
      adonan_ke: data.adonanKe, jam_adonan: data.jamAdonan,
      suhu_adonan: data.suhuAdonan, penimbang: data.namaPenimbang,
      jumlah_kru: data.jumlahKru, leader: data.leaderProduksi
    }, submit: 1
  })
}
export function transferAll(w) { return perform(w, 'transfer_materials') }
export function confirmMaterial(w) { return refreshWo(w.id) }
export function confirmOperations(w) { return refreshWo(w.id) }
export function startOperation(w, op, employee) {
  return perform(w, 'jobcard_start', {
    job_card: op.id, employees: employee ? [{ employee }] : op.employees
  })
}
export function finishOperation(w, op, qty, loss = 0) {
  return perform(w, 'jobcard_complete', { job_card: op.id, qty, process_loss_qty: loss, auto_submit: 1 })
}
export function savePrePacking(w, data) {
  return perform(w, 'confirm_prepacking', { values: {
    good: data.goodQty, reject: data.rejectQty, trial: data.trialQty, sisa: data.sisaQty,
    jam_pembekuan: data.jam, qc_produksi: data.qc
  } })
}
export function completeProduction(w) { return perform(w, 'finish') }

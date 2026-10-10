import { fmtStampShort, qtyMain } from './format.js'

// FU96: box (kg) dipensiunkan — `box` kini hanya penanda grup opsional
// ('' = tidak ada pill; request kartu lot tidak pernah mengirimnya).
export function handoverCard(values) {
  return {
    workOrder: values.workOrder || '',
    document: values.document || '',
    batch: values.batch || '',
    adonan: values.adonan ? String(values.adonan) : '', // FU69: Int — 0 = kosong
    quantityLabel: values.quantityLabel || '',
    quantity: qtyMain(values.quantity, values.units),
    timestampLabel: values.timestampLabel || '',
    timestamp: fmtStampShort(values.timestamp).replace(' · ', ', '),
    box: values.box || ''
  }
}

// 2026-10-10: a bulk MR carries one row per Work Order — the MR name alone
// is no longer unique on the board.
export function requestRowId(r) {
  return `${r.mr}|${r.work_order}`
}

// Group pill: legacy plan groups name the plan, bulk MRs name the MR.
export function groupText(r) {
  if (r.boxPlan) return `Grup ${r.boxPlan}${r.groupSize != null ? ` (${r.groupSize} WO)` : ''}`
  return r.groupSize > 1 ? `Grup ${r.materialRequest} (${r.groupSize} WO)` : undefined
}

import { reactive } from 'vue'
import { hasAlternate } from './format.js'

// FU114: item Tanpa Pre-Packing mencetak label dari hasil Post-Packing
export function labelSource(workOrder) {
  return workOrder.skipPrepacking ? workOrder.postpacking : workOrder.prepacking
}

export function labelCountForWorkOrder(workOrder) {
  const goodQty = Number(labelSource(workOrder)?.goodQty)
  const factor = hasAlternate(workOrder) ? workOrder.qtyInPack : 1
  return Math.max(1, Math.ceil(goodQty / factor - 1e-8))
}

// afterSave: nama tahap yang baru disimpan ('' = dibuka manual)
export const labelPrintPrompt = reactive({ workOrder: '', labelCount: 0, afterSave: '' })

export function offerLabelPrint(workOrder, labelCount, afterSave = '') {
  labelPrintPrompt.workOrder = workOrder
  labelPrintPrompt.labelCount = labelCount
  labelPrintPrompt.afterSave = afterSave
}

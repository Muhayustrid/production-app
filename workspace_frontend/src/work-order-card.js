import { fmtDate, qtyStack } from './format.js'

export function workOrderCard(values) {
  const quantity = qtyStack(values.quantity, values.units)
  return {
    primaryQuantity: quantity.main,
    stockQuantity: quantity.sub,
    adonan: values.adonan == null ? '' : String(values.adonan),
    dateLabel: values.completed ? 'Selesai' : 'Jadwal',
    date: fmtDate(values.completed ? values.finishedAt : values.plannedDate, true)
  }
}

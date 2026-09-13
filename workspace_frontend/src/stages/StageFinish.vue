<script setup>
import { computed, nextTick, ref } from 'vue'
import { Flag } from 'lucide-vue-next'
import { completeProduction, producedQty, state } from '../store.js'
import { fmtInt, packParts, qtyMain } from '../format.js'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const qip = props.wo
const pre = props.wo.prepacking
// Barang Jadi = Good Qty Pre-Packing (Post-Packing hanya di alur Serah Terima)
const fg = computed(() => props.wo.stage === 'completed' ? props.wo.producedStockQty : producedQty(props.wo))

const diff = computed(() => fg.value - props.wo.plannedStockQty)
const diffText = computed(() => {
  if (diff.value === 0) return `Sesuai rencana (0 ${props.wo.stockUom})`
  const sign = diff.value > 0 ? '+' : '-'
  const a = Math.abs(diff.value)
  return `${sign}${qtyMain(a, qip)}`
})
const diffCls = computed(() => (diff.value === 0 ? '' : diff.value > 0 ? 'pos' : 'neg'))

const dlg = ref(null)

function ask() {
  nextTick(() => dlg.value.showModal())
}
function closeDlg() {
  dlg.value.close()
}
async function confirmComplete() {
  if (await completeProduction(props.wo)) dlg.value.close()
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><Flag :size="15" :stroke-width="1.9" /></span>
      <h2>Finish</h2>
      <span class="lead">Periksa ringkasan sebelum menyelesaikan produksi.</span>
      <span v-if="review" class="chip chip-info" style="margin-left: auto">Tinjauan</span>
    </div>

    <div class="panel-body">
      <div class="sum-sec">
        <div class="sum-row">
          <span class="k">Rencana Work Order</span>
          <span class="v">{{ qtyMain(wo.plannedStockQty, qip) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Hasil Aktual</span>
          <span class="v">{{ qtyMain(fg, qip) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Selisih dari rencana</span>
          <span class="v" :class="diffCls">{{ diffText }}</span>
        </div>
      </div>

      <div class="sum-sec">
        <div class="sum-row">
          <span class="k">Reject</span>
          <span class="v">{{ pre.rejectQty != null ? qtyMain(pre.rejectQty, qip) : '-' }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Trial</span>
          <span class="v">{{ pre.trialQty != null ? qtyMain(pre.trialQty, qip) : '-' }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Sisa</span>
          <span class="v">{{ pre.sisaQty != null ? qtyMain(pre.sisaQty, qip) : '-' }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Jam Pembekuan · QC Produksi</span>
          <span class="v"><span class="dim">{{ pre.jam || '-' }} · {{ pre.qc || '-' }}</span></span>
        </div>
      </div>

      <div class="sum-sec">
        <div class="fgbox">
          <span>Barang Jadi (Good Qty Pre-Packing)</span>
          <span>{{ qtyMain(fg, qip) }}</span>
        </div>
        <div class="sum-row" style="margin-top: 8px">
          <span class="k">Gudang Tujuan</span>
          <span class="v">{{ wo.warehouse }}</span>
        </div>
      </div>

      <p class="note">
        Saat diselesaikan, Manufacture Stock Entry dibuat di ERPNext: bahan baku dihitung dari
        BOM dan planned qty, jumlah Barang Jadi memakai Good Qty Pre-Packing
        ({{ fmtInt(fg) }} {{ wo.stockUom }}). Barang jadi masuk Cold Storage dan menunggu serah terima ke
        Gudang Barang Jadi melalui alur Serah Terima Barang Jadi.
      </p>
    </div>

    <div v-if="!review" class="panel-foot">
      <button class="btn btn-primary" @click="ask">Selesaikan Produksi</button>
      <span class="why">Konfirmasi diperlukan sebelum Work Order diselesaikan.</span>
    </div>

    <dialog ref="dlg" class="dialog" @click.self="closeDlg">
      <h3>Selesaikan Produksi?</h3>
      <p>
        {{ wo.id }} akan diselesaikan. Barang jadi
        <strong>{{ qtyMain(fg, qip) }}</strong> akan dibuat di
        <strong>{{ wo.warehouse }}</strong> melalui Manufacture Stock Entry di ERPNext, lalu
        menunggu permintaan serah terima dari gudang.
      </p>
      <p v-if="state.actionError" class="err" role="alert">{{ state.actionError }}</p>
      <div class="dlg-actions">
        <button class="btn" @click="closeDlg">Batal</button>
        <button class="btn btn-primary" :disabled="!!state.pending" @click="confirmComplete">Ya, Selesaikan</button>
      </div>
    </dialog>
  </section>
</template>

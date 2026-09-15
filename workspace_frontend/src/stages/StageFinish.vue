<script setup>
import { computed, nextTick, ref } from 'vue'
import { Flag } from 'lucide-vue-next'
import { completeProduction, producedQty, state } from '../store.js'
import { qtyMain } from '../format.js'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const qip = props.wo
const pre = props.wo.prepacking
const post = props.wo.postpacking
// Barang Jadi = Good Qty Post-Packing; fallback Pre-Packing hanya WO completed legacy
const fg = computed(() => producedQty(props.wo))

const blockTotal = (b) => {
  const v = [b.goodQty, b.rejectQty, b.trialQty, b.sisaQty]
  return v.some((x) => x == null) ? null : v.reduce((a, c) => a + c, 0)
}
const preTotal = computed(() => blockTotal(pre))
const postTotal = computed(() => blockTotal(post))
const qtyText = (v) => (v != null ? qtyMain(v, qip) : '-')

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
      <span v-if="review" class="chip chip-info" style="margin-left: auto">Tinjauan</span>
    </div>

    <div class="panel-body">
      <div class="sum-sec">
        <div class="sum-row">
          <span class="k">Rencana</span>
          <span class="v">{{ qtyMain(wo.plannedStockQty, qip) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Hasil aktual</span>
          <span class="v">{{ qtyMain(fg, qip) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Selisih dari rencana</span>
          <span class="v" :class="diffCls">{{ diffText }}</span>
        </div>
      </div>

      <div class="sum-sec">
        <div class="sect">Pre-Packing</div>
        <div class="sum-row">
          <span class="k">Good</span>
          <span class="v">{{ qtyText(pre.goodQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Reject</span>
          <span class="v">{{ qtyText(pre.rejectQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Trial</span>
          <span class="v">{{ qtyText(pre.trialQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Sisa</span>
          <span class="v">{{ qtyText(pre.sisaQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Total hasil</span>
          <span class="v">{{ preTotal != null ? qtyMain(preTotal, qip) : '-' }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Jam Pembekuan · QC Produksi</span>
          <span class="v"><span class="dim">{{ pre.jam || '-' }} · {{ pre.qc || '-' }}</span></span>
        </div>
      </div>

      <div class="sum-sec">
        <div class="sect">Post-Packing</div>
        <div class="sum-row">
          <span class="k">Good</span>
          <span class="v">{{ qtyText(post.goodQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Reject</span>
          <span class="v">{{ qtyText(post.rejectQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Trial</span>
          <span class="v">{{ qtyText(post.trialQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Sisa</span>
          <span class="v">{{ qtyText(post.sisaQty) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Total hasil</span>
          <span class="v">{{ postTotal != null ? qtyMain(postTotal, qip) : '-' }}</span>
        </div>
      </div>

      <div class="sum-sec">
        <div class="fgbox">
          <span>Barang Jadi</span>
          <span>{{ qtyMain(fg, qip) }}</span>
        </div>
        <div class="sum-row" style="margin-top: 8px">
          <span class="k">Gudang Tujuan</span>
          <span class="v">{{ wo.warehouse }}</span>
        </div>
      </div>

    </div>

    <div v-if="!review" class="panel-foot">
      <button class="btn btn-primary" @click="ask">Selesaikan Produksi</button>
    </div>

    <dialog ref="dlg" class="dialog" @click.self="closeDlg">
      <h3>Selesaikan Produksi?</h3>
      <p>
        {{ wo.id }} akan diselesaikan dengan hasil
        <strong>{{ qtyMain(fg, qip) }}</strong> di
        <strong>{{ wo.warehouse }}</strong>.
      </p>
      <div class="dlg-actions">
        <button class="btn" @click="closeDlg">Batal</button>
        <button class="btn btn-primary" :disabled="!!state.pending" @click="confirmComplete">Ya, Selesaikan</button>
      </div>
    </dialog>
  </section>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { Cog } from 'lucide-vue-next'
import { confirmOperations, finishOperation, opsAllDone, startOperation } from '../store.js'
import { fmtInt, packParts, qtyMain } from '../format.js'
import QtyInput from '../QtyInput.vue'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const qip = props.wo.qtyInPack

function statusMeta(s) {
  if (s === 'done') return { cls: 'chip-ok', label: 'Selesai' }
  if (s === 'in_progress') return { cls: 'chip-warn', label: 'Berjalan' }
  return { cls: 'chip-off', label: 'Belum Mulai' }
}

function ratio(done, planned) {
  const d = packParts(done, qip)
  const p = packParts(planned, qip)
  return {
    main: `${d.approx ? '≈ ' : ''}${d.str} / ${p.approx ? '≈ ' : ''}${p.str} Pack`,
    sub: `${fmtInt(done)} / ${fmtInt(planned)} PCS`
  }
}

function timeText(op) {
  if (op.status === 'done') return `${op.start} - ${op.end}`
  if (op.status === 'in_progress') return `mulai ${op.start}`
  return '-'
}

// dialog selesaikan operasi: konfirmasi jumlah selesai (default = rencana)
const dlg = ref(null)
const dlgOp = ref(null)
const donePcs = ref(null)
const doneValid = ref(true)

function openFinish(op) {
  dlgOp.value = op
  donePcs.value = op.plannedPcs
  doneValid.value = true
  nextTick(() => dlg.value.showModal())
}
function closeDlg() {
  dlg.value.close()
  dlgOp.value = null
}
function confirmFinish() {
  if (!doneValid.value || donePcs.value == null) return
  finishOperation(props.wo, dlgOp.value, donePcs.value)
  closeDlg()
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><Cog :size="15" :stroke-width="1.9" /></span>
      <h2>Operasi</h2>
      <span class="lead">Eksekusi operasi per Job Card di ERPNext.</span>
      <span v-if="review" class="chip chip-info" style="margin-left: auto">Tinjauan</span>
    </div>

    <div class="panel-body">
      <div class="op-thead">
        <span>Operasi</span>
        <span style="text-align: right">Selesai</span>
        <span>Waktu</span>
        <span style="text-align: right">Status</span>
        <span></span>
      </div>

      <div v-for="op in wo.operations" :key="op.name" class="op-row">
        <div class="oname">
          {{ op.name }}
          <small>{{ op.workstation }} · {{ op.operator }}</small>
        </div>
        <div class="ostat st-done">
          <span class="slabel">Selesai</span>
          <span class="sval" :class="{ dim: op.completedPcs === 0 }">{{ ratio(op.completedPcs, op.plannedPcs).main }}</span>
          <span class="ssub">{{ ratio(op.completedPcs, op.plannedPcs).sub }}</span>
        </div>
        <div class="otimes">{{ timeText(op) }}</div>
        <div class="ostat st-stat">
          <span class="chip" :class="statusMeta(op.status).cls">{{ statusMeta(op.status).label }}</span>
        </div>
        <div class="oact">
          <button
            v-if="!review && op.status === 'pending'"
            class="btn btn-sm"
            @click="startOperation(wo, op)"
          >
            Mulai
          </button>
          <button
            v-if="!review && op.status === 'in_progress'"
            class="btn btn-sm btn-primary"
            @click="openFinish(op)"
          >
            Selesaikan
          </button>
        </div>
      </div>
    </div>

    <div v-if="!review" class="panel-foot">
      <button class="btn btn-primary" :disabled="!opsAllDone(wo)" @click="confirmOperations(wo)">
        Lanjut ke Pre-Packing
      </button>
      <span v-if="!opsAllDone(wo)" class="why">Selesaikan semua operasi terlebih dahulu.</span>
    </div>

    <dialog ref="dlg" class="dialog" @click.self="closeDlg">
      <h3 v-if="dlgOp">Selesaikan {{ dlgOp.name }}?</h3>
      <p v-if="dlgOp">
        Catat jumlah yang diselesaikan operator. Rencana:
        {{ qtyMain(dlgOp.plannedPcs, qip) }}.
      </p>
      <div v-if="dlgOp" style="margin-top: 12px; max-width: 240px">
        <QtyInput
          label="Jumlah Selesai"
          unit-key="opSelesai"
          required
          :qty-in-pack="qip"
          v-model="donePcs"
          @update:valid="doneValid = $event"
        />
      </div>
      <div class="dlg-actions">
        <button class="btn" @click="closeDlg">Batal</button>
        <button class="btn btn-primary" :disabled="!doneValid || donePcs == null" @click="confirmFinish">
          Selesaikan
        </button>
      </div>
    </dialog>
  </section>
</template>

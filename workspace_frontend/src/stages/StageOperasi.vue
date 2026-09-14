<script setup>
import { nextTick, ref, watch } from 'vue'
import { Cog } from 'lucide-vue-next'
import { confirmOperations, finishOperation, opsAllDone, startOperation, state } from '../store.js'
import { fmtInt, packParts, qtyMain } from '../format.js'
import LinkInput from '../LinkInput.vue'
import QtyInput from '../QtyInput.vue'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const qip = props.wo

function statusMeta(s) {
  if (s === 'done') return { cls: 'chip-ok', label: 'Selesai' }
  if (s === 'in_progress') return { cls: 'chip-warn', label: 'Berjalan' }
  return { cls: 'chip-off', label: 'Belum Mulai' }
}

const employee = ref('')
function ratio(done, planned) {
  return { main: qtyMain(done, qip), sub: `Rencana: ${qtyMain(planned, qip)}` }
}

function timeText(op) {
  if (op.status === 'done') return `${op.start} - ${op.end}`
  if (op.status === 'in_progress') return `mulai ${op.start}`
  return '-'
}

// dialog selesaikan operasi: konfirmasi jumlah selesai (default = rencana).
// Susut diusulkan otomatis = sisa rencana; operator dapat mengubahnya.
const dlg = ref(null)
const dlgOp = ref(null)
const donePcs = ref(null)
const doneValid = ref(true)
const lossPcs = ref(0)
const lossValid = ref(true)
const lossDirty = ref(false)

function openFinish(op) {
  dlgOp.value = op
  donePcs.value = op.plannedPcs
  doneValid.value = true
  lossPcs.value = 0
  lossValid.value = true
  lossDirty.value = false
  nextTick(() => dlg.value.showModal())
}
function closeDlg() {
  dlg.value.close()
  dlgOp.value = null
}
watch(donePcs, (qty) => {
  if (!lossDirty.value && dlgOp.value) {
    lossPcs.value = Math.max((dlgOp.value.plannedPcs || 0) - (qty || 0), 0)
  }
})
async function confirmFinish() {
  if (!doneValid.value || !lossValid.value || donePcs.value == null) return
  if (await finishOperation(props.wo, dlgOp.value, donePcs.value, lossPcs.value || 0)) closeDlg()
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
      <div v-if="!review" class="field">
        <label for="operation-employee">Karyawan untuk memulai operasi</label>
        <LinkInput id="operation-employee" v-model="employee" doctype="Employee" />
      </div>
      <div class="op-thead">
        <span>Operasi</span>
        <span style="text-align: right">Selesai</span>
        <span>Waktu</span>
        <span style="text-align: right">Status</span>
        <span></span>
      </div>

      <div v-for="op in wo.operations" :key="op.id" class="op-row">
        <div class="oname">
          {{ op.name }}
          <small>{{ op.workstation }} · {{ op.operator }}</small>
        </div>
        <div class="ostat st-done">
          <span class="slabel">Selesai</span>
          <span class="sval" :class="{ dim: op.completedPcs === 0 }">{{ ratio(op.completedPcs, op.plannedPcs).main }}</span>
          <span class="ssub">{{ ratio(op.completedPcs, op.plannedPcs).sub }}</span>
          <span v-if="op.lossQty > 0" class="ssub">Susut: {{ qtyMain(op.lossQty, qip) }}</span>
        </div>
        <div class="otimes">{{ timeText(op) }}</div>
        <div class="ostat st-stat">
          <span class="chip" :class="statusMeta(op.status).cls">{{ statusMeta(op.status).label }}</span>
        </div>
        <div class="oact">
          <button
            v-if="!review && op.status === 'pending'"
            class="btn btn-sm"
            @click="startOperation(wo, op, employee)"
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
        {{ qtyMain(dlgOp.plannedPcs, qip) }}. Selisih rencana yang tidak
        diproduksi dicatat sebagai susut agar operasi selesai.
      </p>
      <div v-if="dlgOp" style="margin-top: 12px; max-width: 240px">
        <QtyInput
          label="Jumlah Selesai"
          unit-key="opSelesai"
          required
          :units="wo"
          v-model="donePcs"
          @update:valid="doneValid = $event"
        />
      </div>
      <div v-if="dlgOp" style="margin-top: 12px; max-width: 240px">
        <QtyInput
          label="Susut / Rusak"
          unit-key="opSusut"
          :units="wo"
          v-model="lossPcs"
          @update:valid="lossValid = $event"
        />
      </div>
      <div class="dlg-actions">
        <button class="btn" @click="closeDlg">Batal</button>
        <button class="btn btn-primary" :disabled="!!state.pending || !doneValid || !lossValid || donePcs == null" @click="confirmFinish">
          Selesaikan
        </button>
      </div>
    </dialog>
  </section>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { PackageCheck } from 'lucide-vue-next'
import { savePrePacking } from '../store.js'
import { qtyMain } from '../format.js'
import QtyInput from '../QtyInput.vue'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const qip = props.wo.qtyInPack

const src = props.wo.prepacking
const form = reactive({
  goodQty: src.goodQty,
  rejectQty: src.rejectQty,
  trialQty: src.trialQty,
  sisaQty: src.sisaQty,
  jam: src.jam || '',
  qc: src.qc || '',
  box1: src.box1,
  box2: src.box2
})

const ok = reactive({ goodQty: false, rejectQty: false, trialQty: false, sisaQty: false })

const qtyFields = computed(() => [
  { key: 'goodQty', label: 'Good Qty' },
  { key: 'rejectQty', label: 'Reject Qty' },
  { key: 'trialQty', label: 'Trial Qty' },
  { key: 'sisaQty', label: 'Sisa Qty' }
])

const qtyValid = computed(() => Object.values(ok).every(Boolean))
const metaValid = computed(() => form.jam !== '' && String(form.qc).trim() !== '')
const canSave = computed(() => qtyValid.value && metaValid.value)

const total = computed(() => {
  const v = [form.goodQty, form.rejectQty, form.trialQty, form.sisaQty]
  if (v.some((x) => x == null)) return null
  return v.reduce((a, b) => a + b, 0)
})
const over = computed(() => total.value != null && total.value > props.wo.plannedStockQty)

function save() {
  if (!canSave.value) return
  savePrePacking(props.wo, {
    goodQty: form.goodQty,
    rejectQty: form.rejectQty,
    trialQty: form.trialQty,
    sisaQty: form.sisaQty,
    jam: form.jam,
    qc: String(form.qc).trim(),
    box1: form.box1,
    box2: form.box2
  })
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><PackageCheck :size="15" :stroke-width="1.9" /></span>
      <h2>Pre-Packing</h2>
      <span class="lead">Klik label satuan pada tiap kolom untuk memilih Pack / PCS secara mandiri.</span>
      <span v-if="review" class="chip chip-info" style="margin-left: auto">Tinjauan</span>
    </div>

    <div class="panel-body">
      <div class="callout ok" style="margin-bottom: 14px">
        Good Qty adalah hasil produksi aktual sebelum masuk Cold Storage dan menjadi jumlah
        Barang Jadi saat produksi diselesaikan. Hasil tidak harus sama dengan rencana.
      </div>

      <!-- kuantitas 1 baris di desktop, bertumpuk di mobile -->
      <div class="form-grid cols4">
        <QtyInput
          v-for="f in qtyFields"
          :key="f.key"
          :label="f.label"
          :unit-key="f.key"
          :qty-in-pack="qip"
          required
          :disabled="review"
          v-model="form[f.key]"
          @update:valid="ok[f.key] = $event"
        />
      </div>

      <div class="form-grid" style="margin-top: 14px">
        <div class="field">
          <label :for="`f-b1-${stageKey}`">Box 1 (kg)</label>
          <input
            :id="`f-b1-${stageKey}`"
            v-model.number="form.box1"
            class="input"
            type="number"
            min="0"
            step="0.01"
            inputmode="decimal"
            :disabled="review"
            placeholder="opsional"
          />
        </div>

        <div class="field">
          <label :for="`f-b2-${stageKey}`">Box 2 (kg)</label>
          <input
            :id="`f-b2-${stageKey}`"
            v-model.number="form.box2"
            class="input"
            type="number"
            min="0"
            step="0.01"
            inputmode="decimal"
            :disabled="review"
            placeholder="opsional"
          />
        </div>
      </div>

      <div class="form-grid" style="margin-top: 14px">
        <div class="field">
          <label :for="`f-jam-${stageKey}`">Jam Pembekuan <span class="req">*</span></label>
          <input
            :id="`f-jam-${stageKey}`"
            v-model="form.jam"
            class="input"
            type="time"
            :disabled="review"
          />
        </div>

        <div class="field">
          <label :for="`f-qc-${stageKey}`">QC Produksi <span class="req">*</span></label>
          <input
            :id="`f-qc-${stageKey}`"
            v-model="form.qc"
            class="input"
            type="text"
            :disabled="review"
          />
        </div>
      </div>

      <div style="margin-top: 14px">
        <div v-if="total != null" class="sum-row">
          <span class="k">Total hasil (Good + Reject + Trial + Sisa)</span>
          <span class="v" :class="{ neg: over }">{{ qtyMain(total, qip) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Rencana Work Order</span>
          <span class="v">{{ qtyMain(wo.plannedStockQty, qip) }}</span>
        </div>
        <p v-if="over" class="hint warn">Total melebihi rencana.</p>

        <div v-if="form.goodQty != null" class="fgbox">
          <span>Barang Jadi (Good Qty)</span>
          <span>{{ qtyMain(form.goodQty, qip) }}</span>
        </div>
      </div>
    </div>

    <div v-if="!review" class="panel-foot">
      <button class="btn btn-primary" :disabled="!canSave" @click="save">Simpan &amp; Lanjut ke Finish</button>
      <span v-if="!canSave" class="why">Lengkapi semua kolom untuk melanjutkan.</span>
    </div>
  </section>
</template>

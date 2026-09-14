<script setup>
import { computed, reactive } from 'vue'
import { PackageCheck } from 'lucide-vue-next'
import { confirmPostPacking } from '../store.js'
import { qtyMain } from '../format.js'
import LinkInput from '../LinkInput.vue'
import QtyInput from '../QtyInput.vue'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const qip = props.wo
const pre = props.wo.prepacking
const src = props.wo.postpacking
// WO completed sebelum tahap ini ada: tampilkan angka pre-packing (display
// saja — tidak ada backfill), POSTPACKING_PLAN §7.
const legacyReview = props.review && props.wo.stage === 'completed' && src.goodQty == null
const display = legacyReview ? pre : src
const form = reactive({
  goodQty: display.goodQty,
  rejectQty: display.rejectQty,
  trialQty: display.trialQty,
  jam: display.jam || '',
  qc: display.qc || ''
})

const ok = reactive({ goodQty: false, rejectQty: false, trialQty: false })

const preQty = computed(() => pre.goodQty)
const preAvailable = computed(() => preQty.value != null)

// Sisa otomatis = Good Pre-Packing − Good − Reject − Trial (server menghitung ulang)
const total = computed(() => {
  const v = [form.goodQty, form.rejectQty, form.trialQty]
  return v.some((x) => x == null) ? null : v.reduce((a, b) => a + b, 0)
})
const sisa = computed(() => {
  if (legacyReview) return display.sisaQty
  return total.value == null || !preAvailable.value ? null : preQty.value - total.value
})
const over = computed(() => sisa.value != null && sisa.value < 0)
const overGood = computed(() => preAvailable.value && form.goodQty != null && form.goodQty > preQty.value)
const metaValid = computed(() => form.jam !== '' && String(form.qc).trim() !== '')
const canSave = computed(() =>
  Object.values(ok).every(Boolean) && metaValid.value && form.goodQty > 0 && !over.value && !overGood.value
)

function save() {
  if (!canSave.value) return
  confirmPostPacking(props.wo, {
    goodQty: form.goodQty,
    rejectQty: form.rejectQty,
    trialQty: form.trialQty,
    jam: form.jam,
    qc: String(form.qc).trim()
  })
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><PackageCheck :size="15" :stroke-width="1.9" /></span>
      <h2>Post-Packing</h2>
      <span class="lead">Hasil akhir Work Order setelah packing.</span>
      <span v-if="review" class="chip chip-info" style="margin-left: auto">Tinjauan</span>
    </div>

    <div class="panel-body">
      <p v-if="legacyReview" class="hint">
        Work Order ini selesai sebelum tahap Post-Packing diperkenalkan — angka ditampilkan dari
        data Pre-Packing (data lama, tanpa backfill).
      </p>

      <div class="sum-sec">
        <div class="sum-row">
          <span class="k">Batas Good Qty Pre-Packing</span>
          <span class="v">{{ preAvailable ? qtyMain(preQty, qip) : 'Belum tersedia' }}</span>
        </div>
      </div>

      <!-- kuantitas 1 baris di desktop, bertumpuk di mobile; Sisa otomatis (disabled) -->
      <div class="form-grid cols4" style="margin-top: 14px">
        <QtyInput
          label="Good Qty"
          unit-key="postGoodQty"
          :units="wo"
          required
          :disabled="review"
          v-model="form.goodQty"
          @update:valid="ok.goodQty = $event"
        />
        <QtyInput
          label="Reject Qty"
          unit-key="postRejectQty"
          :units="wo"
          required
          :disabled="review"
          v-model="form.rejectQty"
          @update:valid="ok.rejectQty = $event"
        />
        <QtyInput
          label="Trial Qty"
          unit-key="postTrialQty"
          :units="wo"
          required
          :disabled="review"
          v-model="form.trialQty"
          @update:valid="ok.trialQty = $event"
        />
        <QtyInput
          label="Sisa Qty (otomatis)"
          unit-key="postSisaQty"
          :units="wo"
          :model-value="sisa"
          disabled
        />
      </div>

      <p v-if="overGood" class="hint warn">Good Qty melebihi batas Pre-Packing.</p>
      <p v-else-if="over" class="hint warn">Total hasil melebihi batas Pre-Packing.</p>

      <div class="form-grid" style="margin-top: 14px">
        <div class="field">
          <label :for="`f-post-jam-${stageKey}`">Jam Packing <span class="req">*</span></label>
          <input
            :id="`f-post-jam-${stageKey}`"
            v-model="form.jam"
            class="input"
            type="time"
            :disabled="review"
          />
        </div>

        <div class="field">
          <label :for="`f-post-qc-${stageKey}`">QC Packing <span class="req">*</span></label>
          <LinkInput :id="`f-post-qc-${stageKey}`" v-model="form.qc"
            :display-label="form.qc === src.qc ? src.qcLabel : undefined" :disabled="review" />
        </div>
      </div>

      <div style="margin-top: 14px">
        <div class="sum-row">
          <span class="k">Total hasil (Good + Reject + Trial)</span>
          <span class="v" :class="{ neg: over }">{{ total != null ? qtyMain(total, qip) : '-' }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Batas Pre-Packing</span>
          <span class="v">{{ preAvailable ? qtyMain(preQty, qip) : 'Belum tersedia' }}</span>
        </div>

        <div v-if="form.goodQty != null" class="fgbox">
          <span>Barang Jadi (Good Qty)</span>
          <span>{{ qtyMain(form.goodQty, qip) }}</span>
        </div>
      </div>
    </div>

    <div v-if="!review" class="panel-foot">
      <button class="btn btn-primary" :disabled="!canSave" @click="save">Simpan &amp; Lanjut ke Finish</button>
      <span v-if="!canSave" class="why">Lengkapi kuantitas dan pencatatan untuk melanjutkan.</span>
    </div>
  </section>
</template>

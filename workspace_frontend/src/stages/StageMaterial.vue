<script setup>
import { computed } from 'vue'
import { Boxes } from 'lucide-vue-next'
import { confirmMaterial, materialComplete, materialShortages, transferAll } from '../store.js'
import { fmtNum } from '../format.js'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const shortages = computed(() => materialShortages(props.wo))

function itemStatus(i) {
  if (i.transferred >= i.required) return { cls: 'chip-ok', label: 'Cukup' }
  if (i.transferred > 0) return { cls: 'chip-warn', label: 'Sebagian' }
  return { cls: 'chip-off', label: 'Belum' }
}
</script>

<template>
  <section class="panel material-panel" aria-labelledby="material-panel-title">
    <div class="panel-head">
      <span class="p-ico" aria-hidden="true"><Boxes :size="15" :stroke-width="1.9" /></span>
      <div class="material-heading">
        <h2 id="material-panel-title">Material</h2>
        <span class="lead">Material Transfer for Manufacture di ERPNext.</span>
      </div>
      <span v-if="review" class="chip chip-info material-review">Tinjauan</span>
    </div>

    <div class="panel-body">
      <div v-if="shortages.length" class="callout material-status material-status-warn" role="status">
        <strong>Kekurangan {{ shortages.length }} bahan</strong>
        <span>{{ shortages.map((i) => i.name).join(', ') }}.</span>
      </div>
      <div v-else class="callout ok material-status" role="status">
        <strong>Material lengkap</strong>
        <span>Semua material telah ditransfer.</span>
      </div>

      <div class="mat-list" role="table" aria-label="Rincian material Work Order">
        <div class="mat-thead" role="row">
          <span role="columnheader">Material</span>
          <span role="columnheader">Kebutuhan</span>
          <span role="columnheader">Ditransfer</span>
          <span role="columnheader">Kekurangan</span>
          <span role="columnheader">Status</span>
        </div>
        <div v-for="i in wo.material.items" :key="i.code" class="mat-row" role="row">
          <div class="mname" role="cell">
            {{ i.name }}
            <small class="mono">{{ i.code }}</small>
          </div>
          <div class="mnum m-req" role="cell"><span class="mlabel">Kebutuhan</span>{{ fmtNum(i.required) }} {{ i.uom }}</div>
          <div class="mnum m-trf" role="cell"><span class="mlabel">Ditransfer</span>{{ fmtNum(i.transferred) }} {{ i.uom }}</div>
          <div class="mnum m-short" role="cell" :class="{ neg: i.required - i.transferred > 0 }">
            <span class="mlabel">Kekurangan</span>{{ fmtNum(i.required - i.transferred) }} {{ i.uom }}
          </div>
          <div class="m-status" role="cell">
            <span class="chip" :class="itemStatus(i).cls">{{ itemStatus(i).label }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!review" class="panel-foot">
      <button
        v-if="shortages.length"
        class="btn"
        @click="transferAll(wo)"
      >
        Transfer Semua Material
      </button>
      <button
        class="btn btn-primary"
        :disabled="!materialComplete(wo)"
        @click="confirmMaterial(wo)"
      >
        {{ wo.hasOperations ? 'Lanjut ke Operasi' : 'Lanjut ke Pre-Packing' }}
      </button>
      <span v-if="!materialComplete(wo)" class="why">
        Selesaikan transfer semua material terlebih dahulu.
      </span>
    </div>
  </section>
</template>

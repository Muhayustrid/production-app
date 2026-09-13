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
  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><Boxes :size="15" :stroke-width="1.9" /></span>
      <h2>Material</h2>
      <span class="lead">Material Transfer for Manufacture di ERPNext.</span>
      <span v-if="review" class="chip chip-info" style="margin-left: auto">Tinjauan</span>
    </div>

    <div class="panel-body">
      <div v-if="shortages.length" class="callout">
        Kekurangan material pada {{ shortages.length }} bahan:
        {{ shortages.map((i) => i.name).join(', ') }}.
      </div>
      <div v-else class="callout ok">Semua material telah ditransfer.</div>

      <div class="mat-thead" style="margin-top: 14px">
        <span>Material</span>
        <span style="text-align: right">Kebutuhan</span>
        <span style="text-align: right">Ditransfer</span>
        <span style="text-align: right">Kekurangan</span>
        <span style="text-align: right">Status</span>
      </div>

      <div v-for="i in wo.material.items" :key="i.code" class="mat-row">
        <div class="mname">
          {{ i.name }}
          <small class="mono">{{ i.code }}</small>
        </div>
        <div class="mnum m-req"><span class="mlabel">Kebutuhan</span>{{ fmtNum(i.required) }} {{ i.uom }}</div>
        <div class="mnum m-trf"><span class="mlabel">Ditransfer</span>{{ fmtNum(i.transferred) }} {{ i.uom }}</div>
        <div class="mnum m-short" :class="{ neg: i.required - i.transferred > 0 }">
          <span class="mlabel">Kekurangan</span>{{ fmtNum(i.required - i.transferred) }} {{ i.uom }}
        </div>
        <div class="m-status" style="text-align: right">
          <span class="chip" :class="itemStatus(i).cls">{{ itemStatus(i).label }}</span>
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

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getWo, workOrders, STAGE_LABELS, openWo } from './store.js'
import { fmtDate, qtyMain, qtyStack } from './format.js'
import { ChevronLeft, Check, CheckCircle2 } from 'lucide-vue-next'
import StagePersiapan from './stages/StagePersiapan.vue'
import StageMaterial from './stages/StageMaterial.vue'
import StageOperasi from './stages/StageOperasi.vue'
import StagePacking from './stages/StagePacking.vue'
import StageFinish from './stages/StageFinish.vue'

const props = defineProps({ id: { type: String, required: true } })

const wo = computed(() => getWo(props.id))
const loading = ref(false)
async function load() {
  loading.value = true
  try { await openWo(props.id) } catch (e) { console.error(e) } finally { loading.value = false }
}
onMounted(load)

// stage aktif datang dari "server" (wo.stage). view hanya untuk meninjau tahap selesai.
const view = ref(null)
watch(() => wo.value.stage, () => { view.value = null })

const order = computed(() => [
  'persiapan',
  'material',
  ...(wo.value.hasOperations ? ['operasi'] : []),
  'prepacking',
  'finish'
])

const activeStage = computed(() =>
  wo.value.stage === 'completed' ? 'finish' : wo.value.stage
)
const displayed = computed(() => view.value || activeStage.value)
const review = computed(() => displayed.value !== activeStage.value || wo.value.stage === 'completed')

function stepState(s) {
  if (wo.value.stage === 'completed') return 'done'
  const idx = order.value.indexOf(s)
  const cur = order.value.indexOf(wo.value.stage)
  if (idx < cur) return 'done'
  if (idx === cur) return 'active'
  return 'locked'
}

function clickStep(s) {
  const st = stepState(s)
  if (st === 'locked') return
  view.value = st === 'active' ? null : s
}

const comps = {
  persiapan: StagePersiapan,
  material: StageMaterial,
  operasi: StageOperasi,
  prepacking: StagePacking,
  finish: StageFinish
}
const stageComp = computed(() => comps[displayed.value])

const statusClass = computed(() =>
  wo.value.status === 'Draft' ? 'b-draft' : wo.value.status === 'Completed' ? 'b-done' : 'b-run'
)

// Barang Jadi manufaktur = Good Qty Pre-Packing (masuk Cold Storage)
const fgQty = computed(() => wo.value.prepacking.goodQty ?? 0)
const plan = computed(() => qtyStack(wo.value.plannedStockQty, wo.value.qtyInPack))

// chip WO aktif langsung tercenter di strip switcher saat halaman dibuka
const switchEl = ref(null)
onMounted(() => {
  switchEl.value
    ?.querySelector('.wsc.on')
    ?.scrollIntoView({ inline: 'center', block: 'nearest' })
})
</script>

<template>
  <div v-if="wo">
    <a class="back" href="#/"><ChevronLeft :size="16" :stroke-width="2" /> Daftar Perintah Kerja</a>

    <nav ref="switchEl" class="wo-switch" aria-label="Pindah Work Order">
      <a
        v-for="w in workOrders"
        :key="w.id"
        class="wsc"
        :class="{ on: w.id === wo.id }"
        :href="'#/wo/' + w.id"
        :aria-current="w.id === wo.id ? 'true' : undefined"
      >
        <span class="wsc-name">{{ w.product }}</span>
        <span class="wsc-sub">Adonan ke {{ w.persiapan.adonanKe ?? '-' }}</span>
      </a>
    </nav>

    <header class="panel ws-hero">
      <div class="ws-hero-main">
        <div class="ws-eyebrow">
          <span class="ws-ref mono">{{ wo.id }}</span>
          <span class="badge" :class="statusClass">{{ wo.status }}</span>
        </div>
        <h1>{{ wo.product }}</h1>
        <p class="ws-meta">
          <span class="code mono">{{ wo.itemCode }}</span> · jadwal {{ fmtDate(wo.plannedDate) }} ·
          {{ wo.warehouse }}
        </p>
      </div>
      <div class="ws-plan">
        <span class="ws-plan-label">Rencana Produksi</span>
        <span class="ws-plan-pack">{{ plan.main }}</span>
        <span class="ws-plan-pcs">{{ plan.sub }}</span>
      </div>
    </header>

    <div v-if="wo.stage === 'completed'" class="banner-done">
      <CheckCircle2 :size="17" :stroke-width="2" />
      <div>
        Produksi selesai{{ wo.finishedAt ? ` pada ${wo.finishedAt}` : '' }} · Barang jadi
        {{ qtyMain(fgQty, wo.qtyInPack) }} di {{ wo.warehouse }}

      </div>
    </div>

    <nav class="stepper" aria-label="Tahap produksi">
      <template v-for="(s, i) in order" :key="s">
        <span v-if="i > 0" class="sep" :class="{ on: stepState(order[i - 1]) === 'done' }"></span>
        <button
          class="step"
          :class="{
            'step-active': stepState(s) === 'active',
            'step-done': stepState(s) === 'done',
            'step-locked': stepState(s) === 'locked'
          }"
          :disabled="stepState(s) === 'locked'"
          :aria-current="stepState(s) === 'active' ? 'step' : undefined"
          @click="clickStep(s)"
        >
          <span class="dot"><Check v-if="stepState(s) === 'done'" :size="12" :stroke-width="3" /></span>
          {{ STAGE_LABELS[s] }}
        </button>
      </template>
    </nav>

    <component
      :is="stageComp"
      :key="displayed"
      :wo="wo"
      :review="review"
      :stage-key="displayed"
    />

    <p class="srcnote">
      Tahap aktif dikembalikan server berdasarkan dokumen ERPNext terkini (Work Order, Stock Entry,
      Job Card). Tahap selesai dapat ditinjau dari bar tahap di atas.
    </p>
  </div>

  <div v-else class="empty">
    Perintah kerja tidak ditemukan. <a href="#/">Kembali ke daftar</a>.
  </div>
</template>

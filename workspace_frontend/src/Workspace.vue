<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getWo, workOrders, STAGE_LABELS, openWo, state, producedQty } from './store.js'
import { fmtDate, qtyMain, qtyStack } from './format.js'
import { ChevronLeft, Check, CheckCircle2 } from 'lucide-vue-next'
import StagePersiapan from './stages/StagePersiapan.vue'
import StageMaterial from './stages/StageMaterial.vue'
import StageOperasi from './stages/StageOperasi.vue'
import StagePacking from './stages/StagePacking.vue'
import StagePostPacking from './stages/StagePostPacking.vue'
import StageFinish from './stages/StageFinish.vue'

const props = defineProps({ id: { type: String, required: true } })

const wo = computed(() => getWo(props.id))
const loading = ref(true)
const error = ref('')
async function load() {
  loading.value = true
  state.actionError = null
  try { await openWo(props.id) } catch (e) { error.value = e.message } finally { loading.value = false }
}
onMounted(load)

// stage aktif datang dari "server" (wo.stage). view hanya untuk meninjau tahap selesai.
const view = ref(null)
watch(() => wo.value?.stage, () => { view.value = null })

const order = computed(() => [
  'persiapan',
  'material',
  ...(wo.value.hasOperations ? ['operasi'] : []),
  'prepacking',
  'postpacking',
  'finish'
])

const activeStage = computed(() =>
  ['completed', 'review', 'cancelled'].includes(wo.value.stage) ? 'finish' : wo.value.stage
)
const displayed = computed(() => view.value || activeStage.value)
// FU12: Pre/Post-Packing masih bisa DIPERBAIKI dari bar tahap selama WO belum
// diselesaikan (panel tahap lampau dibuka editable, bukan Tinjauan); setelah
// "Selesaikan Produksi" (stage completed) semua kembali read-only.
const finishedStage = computed(() => ['completed', 'review', 'cancelled'].includes(wo.value.stage))
const reeditable = computed(() =>
  !finishedStage.value && ['prepacking', 'postpacking'].includes(displayed.value)
)
const review = computed(() =>
  (displayed.value !== activeStage.value && !reeditable.value) || finishedStage.value
)

function stepState(s) {
  if (['completed', 'review', 'cancelled'].includes(wo.value.stage)) return 'done'
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
  postpacking: StagePostPacking,
  finish: StageFinish
}
const stageComp = computed(() => comps[displayed.value])

const statusClass = computed(() =>
  wo.value.status === 'Draft' ? 'b-draft' : wo.value.status === 'Completed' ? 'b-done' : 'b-run'
)

// Barang Jadi manufaktur = Good Qty Post-Packing (masuk Cold Storage);
// fallback Pre-Packing hanya untuk WO completed legacy
const fgQty = computed(() => producedQty(wo.value))
const plan = computed(() => qtyStack(wo.value.plannedStockQty, wo.value))

// chip WO aktif langsung tercenter di strip switcher saat halaman dibuka
const switchEl = ref(null)
onMounted(() => {
  switchEl.value
    ?.querySelector('.wsc.on')
    ?.scrollIntoView({ inline: 'center', block: 'nearest' })
})
</script>

<template>
  <div v-if="loading" class="empty" role="status">Memuat detail Work Order…</div>
  <div v-else-if="error" class="err" role="alert">{{ error }} <button class="btn" @click="load">Coba lagi</button></div>
  <div v-else-if="wo">
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
        {{ qtyMain(fgQty, wo) }} di {{ wo.warehouse }}

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

    <p v-if="wo.uomWarning" class="callout">{{ wo.uomWarning }}</p>
    <p v-if="review" class="hint">Data tersimpan di ERPNext. Kolom kosong berarti belum tercatat.</p>
    <div v-if="state.actionError" class="callout" role="alert">{{ state.actionError }}</div>
    <fieldset class="stage-form" :disabled="!!state.pending">
    <component
      :is="stageComp"
      :key="displayed"
      :wo="wo"
      :review="review"
      :stage-key="displayed"
    />

    </fieldset>
    <p v-if="state.pending" role="status">Menyimpan ke ERPNext…</p>
    <p class="srcnote">
      Tahap aktif dikembalikan server berdasarkan dokumen ERPNext terkini (Work Order, Stock Entry,
      Job Card). Tahap selesai dapat ditinjau dari bar tahap di atas.
    </p>
  </div>

  <div v-else class="empty">
    Perintah kerja tidak ditemukan. <a href="#/">Kembali ke daftar</a>.
  </div>
</template>

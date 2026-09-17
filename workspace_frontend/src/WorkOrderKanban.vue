<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { state, openWo, getWo, setActionError } from './store.js'
import { workOrderCard } from './work-order-card.js'
import { Boxes, CheckCircle2, ClipboardList, Cog, Flag, GripVertical, Inbox, PackageCheck } from 'lucide-vue-next'
import StagePersiapan from './stages/StagePersiapan.vue'
import StageMaterial from './stages/StageMaterial.vue'
import StageOperasi from './stages/StageOperasi.vue'
import StagePacking from './stages/StagePacking.vue'
import StagePostPacking from './stages/StagePostPacking.vue'
import StageFinish from './stages/StageFinish.vue'
const props = defineProps({ list: { type: Array, required: true } })

const lanes = [
  { key: 'persiapan', title: 'Persiapan', sub: '', icon: ClipboardList, tone: '' },
  { key: 'material', title: 'Material', sub: '', icon: Boxes, tone: '' },
  { key: 'operasi', title: 'Operasi', sub: '', icon: Cog, tone: '' },
  { key: 'prepacking', title: 'Pre-Packing', sub: '', icon: PackageCheck, tone: '' },
  { key: 'postpacking', title: 'Post-Packing', sub: '', icon: PackageCheck, tone: '' },
  { key: 'finish', title: 'Finish', sub: '', icon: Flag, tone: '' },
  { key: 'completed', title: 'Selesai', sub: 'Belum dikirim ke gudang', icon: CheckCircle2, tone: 'ok' }
]
const visibleLanes = computed(() =>
  props.list.some(w => w.hasOperations) ? lanes : lanes.filter(l => l.key !== 'operasi')
)

// lane berikutnya untuk satu WO — urutan sama dengan Workspace; Operasi hanya
// untuk WO dengan operations. null = sudah Selesai (tidak bisa maju).
function nextStage(w) {
  switch (w.stage) {
    case 'persiapan': return 'material'
    case 'material': return w.hasOperations ? 'operasi' : 'prepacking'
    case 'operasi': return 'prepacking'
    case 'prepacking': return 'postpacking'
    case 'postpacking': return 'finish'
    case 'finish': return 'completed'
    default: return null
  }
}

const byLane = computed(() => {
  const g = { persiapan: [], material: [], operasi: [], prepacking: [], postpacking: [], finish: [], completed: [] }
  for (const w of props.list) {
    // FU21: lane Selesai (Cold Storage) = antrean barang jadi yang BELUM masuk
    // alur serah terima; WO yang sudah diminta/terkirim ke gudang sudah
    // dilacak di papan Stock Entry dan disembunyikan dari sini.
    if (w.stage === 'completed' && w.handover) continue
    g[w.stage]?.push(w)
  }
  return g
})

// ---- drag & drop: hanya lane tahap berikutnya yang bisa menerima ----
const drag = ref(null) // WO yang sedang ditarik
const overLane = ref(null)

function laneDroppable(key) { return !!drag.value && nextStage(drag.value) === key }
function onDragStart(e, w) {
  if (!nextStage(w)) return
  drag.value = w
  e.dataTransfer.setData('text/plain', w.id)
  e.dataTransfer.effectAllowed = 'move'
}
function onDragEnd() {
  drag.value = null
  overLane.value = null
}
function dragEnter(key) {
  if (laneDroppable(key)) overLane.value = key
}
function dragLeave(key) {
  if (overLane.value === key) overLane.value = null
}
function onDrop(e, key) {
  e.preventDefault()
  const w = drag.value
  drag.value = null
  overLane.value = null
  if (!w || nextStage(w) !== key) return
  openAction(w)
}
// klik kartu = aksi yang sama dengan drop (jalur sentuh, tanpa drag);
// kartu Selesai tidak punya aksi → buka detail Workspace
function clickCard(w) {
  if (nextStage(w)) openAction(w)
  else window.location.hash = '#/wo/' + w.id
}

const dialog = ref(null)
const selectedId = ref(null)
const selected = computed(() => getWo(selectedId.value))
const opening = ref(false)
const openedStage = ref('')
const panels = { persiapan: StagePersiapan, material: StageMaterial, operasi: StageOperasi, prepacking: StagePacking, postpacking: StagePostPacking, finish: StageFinish }
async function openAction(w) {
  if (opening.value || state.pending) return
  opening.value = true
  state.actionError = null
  try {
    const detail = await openWo(w.id)
    if (!panels[detail.stage]) { window.location.hash = '#/wo/' + w.id; return }
    selectedId.value = w.id
    openedStage.value = detail.stage
    await nextTick()
    dialog.value.showModal()
  } catch (e) { setActionError(e, 'open') }
  finally { opening.value = false }
}
function close() {
  if (dialog.value?.open) dialog.value.close()
  selectedId.value = null
}
function cancelDialog(event) {
  event.preventDefault()
  close()
}
watch(() => selected.value?.stage, stage => {
  if (stage && openedStage.value && stage !== openedStage.value) close()
})
function cardInfo(w) {
  return workOrderCard({
    quantity: w.plannedStockQty,
    units: w,
    adonan: w.persiapan.adonanKe,
    plannedDate: w.plannedDate,
    completed: w.stage === 'completed',
    finishedAt: w.finishedAt
  })
}
</script>
<template>
  <p v-if="opening" role="status">Memuat detail Work Order…</p>
  <div class="kb" :class="{ dragging: !!drag }">
    <section
      v-for="l in visibleLanes"
      :key="l.key"
      class="kb-lane"
      :class="{ over: overLane === l.key, droppable: laneDroppable(l.key) }"
      @dragover.prevent
      @dragenter.prevent="dragEnter(l.key)"
      @dragleave="dragLeave(l.key)"
      @drop="onDrop($event, l.key)"
    >
      <header class="kb-lane-head">
        <span class="kb-ico" :class="l.tone ? 'ok' : ''" aria-hidden="true">
          <component :is="l.icon" :size="14" :stroke-width="1.9" />
        </span>
        <div class="kb-hgroup">
          <span class="kb-title">{{ l.title }}</span>
          <span v-if="l.sub" class="kb-sub">{{ l.sub }}</span>
        </div>
        <span class="kb-count">{{ byLane[l.key].length }}</span>
      </header>
      <TransitionGroup name="kc" tag="div" class="kb-cards">
        <div
          v-for="w in byLane[l.key]"
          :key="w.id"
          class="kb-card wo-kb-card live"
          :class="{ dragging: drag && drag.id === w.id }"
          :draggable="!!nextStage(w)"
          @dragstart="onDragStart($event, w)"
          @dragend="onDragEnd"
          @click="clickCard(w)"
        >
          <div class="kb-top">
            <span class="kb-name">{{ w.product }}</span>
            <GripVertical v-if="nextStage(w)" class="kb-grip" :size="15" :stroke-width="2" aria-hidden="true" />
          </div>
          <span class="kb-id"><a :href="'#/wo/' + w.id" draggable="false" @click.stop>{{ w.id }}</a></span>
          <dl class="wo-card-rows">
            <div class="wo-card-row wo-card-qty">
              <dt>Rencana</dt>
              <dd>
                <strong>{{ cardInfo(w).primaryQuantity }}</strong>
                <span v-if="cardInfo(w).stockQuantity">{{ cardInfo(w).stockQuantity }}</span>
              </dd>
            </div>
            <div class="wo-card-row">
              <dt>Adonan</dt>
              <dd>{{ cardInfo(w).adonan || '-' }}</dd>
            </div>
            <div class="wo-card-row">
              <dt>{{ cardInfo(w).dateLabel }}</dt>
              <dd>{{ cardInfo(w).date }}</dd>
            </div>
          </dl>
        </div>
        <div v-if="!byLane[l.key].length" key="empty" class="kb-empty">
          <Inbox :size="16" :stroke-width="1.8" aria-hidden="true" />
          <span>Tidak ada Work Order</span>
        </div>
      </TransitionGroup>
    </section>
  </div>


  <dialog
    ref="dialog"
    class="dialog kanban-dialog"
    :aria-labelledby="selected ? 'kanban-dialog-title' : undefined"
    @cancel="cancelDialog"
  >
    <template v-if="selected">
      <header class="kanban-dialog-head">
        <div class="kanban-dialog-heading">
          <span class="kanban-dialog-eyebrow">Work Order</span>
          <h2 id="kanban-dialog-title" class="mono">{{ selected.id }}</h2>
          <p>{{ selected.product }}</p>
          <p class="kanban-dialog-adonan">Adonan ke {{ selected.persiapan.adonanKe ?? '-' }}</p>
        </div>
        <button class="btn kanban-dialog-close" :disabled="!!state.pending" @click="close">Tutup</button>
      </header>
      <p v-if="selected.uomWarning" class="callout">{{ selected.uomWarning }}</p>
      <div class="kanban-dialog-content">
        <fieldset class="stage-form" :disabled="!!state.pending">
          <component :is="panels[openedStage]" :key="selected.id + openedStage" :wo="selected" :stage-key="openedStage" />
        </fieldset>
      </div>
      <p v-if="state.pending" class="kanban-dialog-pending" role="status">Menyimpan…</p>
    </template>
  </dialog>
</template>

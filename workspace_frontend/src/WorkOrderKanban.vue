<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { state, openWo, getWo } from './store.js'
import { fmtDate, qtyStack } from './format.js'
import { Boxes, CheckCircle2, ClipboardList, Cog, Flag, GripVertical, Inbox, PackageCheck } from 'lucide-vue-next'
import StagePersiapan from './stages/StagePersiapan.vue'
import StageMaterial from './stages/StageMaterial.vue'
import StageOperasi from './stages/StageOperasi.vue'
import StagePacking from './stages/StagePacking.vue'
import StagePostPacking from './stages/StagePostPacking.vue'
import StageFinish from './stages/StageFinish.vue'
const props = defineProps({ list: { type: Array, required: true } })

const lanes = [
  { key: 'persiapan', title: 'Persiapan', sub: 'Draft · belum mulai', icon: ClipboardList, tone: '' },
  { key: 'material', title: 'Material', sub: 'Transfer bahan baku', icon: Boxes, tone: '' },
  { key: 'operasi', title: 'Operasi', sub: 'Job Card per operasi', icon: Cog, tone: '' },
  { key: 'prepacking', title: 'Pre-Packing', sub: 'Catat hasil awal packing', icon: PackageCheck, tone: '' },
  { key: 'postpacking', title: 'Post-Packing', sub: 'Catat hasil akhir packing', icon: PackageCheck, tone: '' },
  { key: 'finish', title: 'Finish', sub: 'Siap diselesaikan', icon: Flag, tone: '' },
  { key: 'completed', title: 'Selesai', sub: 'Barang jadi di Cold Storage', icon: CheckCircle2, tone: 'ok' }
]

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
  for (const w of props.list) g[w.stage]?.push(w)
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
  } catch (e) { state.actionError = e.message }
  finally { opening.value = false }
}
function close() { dialog.value.close(); selectedId.value = null }
watch(() => selected.value?.stage, stage => {
  if (stage && openedStage.value && stage !== openedStage.value) close()
})
function badgeClass(status) { return status === 'Draft' ? 'b-draft' : status === 'Completed' ? 'b-done' : 'b-run' }
</script>
<template>
  <p v-if="opening" role="status">Memuat detail Work Order…</p>
  <p v-if="state.actionError && !selected" class="err" role="alert">{{ state.actionError }}</p>
  <div class="kb" :class="{ dragging: !!drag }">
    <section
      v-for="l in lanes"
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
          <span class="kb-sub">{{ l.sub }}</span>
        </div>
        <span class="kb-count">{{ byLane[l.key].length }}</span>
      </header>
      <TransitionGroup name="kc" tag="div" class="kb-cards">
        <div
          v-for="w in byLane[l.key]"
          :key="w.id"
          class="kb-card live"
          :class="{ dragging: drag && drag.id === w.id }"
          :draggable="!!nextStage(w)"
          @dragstart="onDragStart($event, w)"
          @dragend="onDragEnd"
          @click="clickCard(w)"
        >
          <div class="kb-top">
            <span class="kb-name">{{ w.product }}</span>
            <span v-if="w.persiapan.adonanKe != null" class="chip chip-off kb-adonan">Adonan ke {{ w.persiapan.adonanKe }}</span>
            <GripVertical v-if="nextStage(w)" class="kb-grip" :size="15" :stroke-width="2" aria-hidden="true" />
          </div>
          <span class="kb-id"><a :href="'#/wo/' + w.id" draggable="false" @click.stop>{{ w.id }}</a></span>
          <div class="kb-qty">
            <span class="ql">Rencana Produksi</span>
            <span class="qv">{{ qtyStack(w.plannedStockQty, w).main }}</span>
            <span class="qu">{{ qtyStack(w.plannedStockQty, w).sub }}</span>
          </div>
          <div class="kb-foot">
            <span class="kb-meta">
              {{ w.stage === 'completed' ? `Selesai ${w.finishedAt || ''}` : `Jadwal ${fmtDate(w.plannedDate, true)}` }}
            </span>
            <span class="badge" :class="badgeClass(w.status)">{{ w.status }}</span>
          </div>
        </div>
        <div v-if="!byLane[l.key].length" key="empty" class="kb-empty">
          <Inbox :size="16" :stroke-width="1.8" aria-hidden="true" />
          <span>Tidak ada Work Order</span>
        </div>
      </TransitionGroup>
    </section>
  </div>


  <dialog ref="dialog" class="dialog" style="width:min(1000px, 95vw); max-height:90vh; overflow:auto" @cancel="selectedId = null">
    <template v-if="selected">
      <div class="dlg-actions"><strong>{{ selected.id }}</strong><button class="btn" :disabled="!!state.pending" @click="close">Tutup</button></div>
      <p v-if="selected.uomWarning" class="callout">{{ selected.uomWarning }}</p>
      <p v-if="state.actionError" class="err" role="alert">{{ state.actionError }}</p>
      <fieldset class="stage-form" :disabled="!!state.pending">
        <component :is="panels[openedStage]" :key="selected.id + openedStage" :wo="selected" :stage-key="openedStage" />
      </fieldset>
      <p v-if="state.pending" role="status">Menyimpan ke ERPNext…</p>
    </template>
  </dialog>
</template>

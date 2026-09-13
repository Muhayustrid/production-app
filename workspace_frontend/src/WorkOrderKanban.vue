<script setup>
import { computed, nextTick, reactive, ref } from 'vue'
import {
  completeProduction, confirmMaterial, confirmOperations, finishOperation,
  materialComplete, materialShortages, opsAllDone, producedQty, savePrePacking,
  startOperation, startProduction, transferAll
} from './store.js'
import { fmtDate, qtyMain, qtyStack } from './format.js'
import {
  Boxes, CheckCircle2, ClipboardList, Cog, Flag, GripVertical, Inbox, PackageCheck
} from 'lucide-vue-next'
import QtyInput from './QtyInput.vue'

// Tampilan kanban alternatif daftar Work Order: lane = tahap aktif yang
// dikembalikan server. Drag kartu ke lane tahap BERIKUTNYA = niat
// menyelesaikan tahap sekarang → dialog aksi dengan input yang sama dengan
// panel tahap di Workspace. Drop tidak pernah mengubah state langsung;
// stage hanya berubah lewat aksi store yang memvalidasi ulang.
const props = defineProps({ list: { type: Array, required: true } })

const lanes = [
  { key: 'persiapan', title: 'Persiapan', sub: 'Draft · belum mulai', icon: ClipboardList, tone: '' },
  { key: 'material', title: 'Material', sub: 'Transfer bahan baku', icon: Boxes, tone: '' },
  { key: 'operasi', title: 'Operasi', sub: 'Job Card per operasi', icon: Cog, tone: '' },
  { key: 'prepacking', title: 'Pre-Packing', sub: 'Catat hasil packing', icon: PackageCheck, tone: '' },
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
    case 'prepacking': return 'finish'
    case 'finish': return 'completed'
    default: return null
  }
}

const byLane = computed(() => {
  const g = { persiapan: [], material: [], operasi: [], prepacking: [], finish: [], completed: [] }
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
function openAction(w) {
  switch (w.stage) {
    case 'persiapan': openStart(w); break
    case 'material': openMat(w); break
    case 'operasi': openOps(w); break
    case 'prepacking': openPak(w); break
    case 'finish': openDone(w); break
  }
}

function badgeClass(s) {
  return s === 'Draft' ? 'b-draft' : s === 'Completed' ? 'b-done' : 'b-run'
}

function nowHHMM() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// ---- dialog 1: Mulai Produksi (tahap Persiapan) ----
const dlgStart = ref(null)
const startWo = ref(null)
const startForm = reactive({ adonanKe: '', jamAdonan: '', suhuAdonan: '', namaPenimbang: '', jumlahKru: '', leaderProduksi: '' })
const startErrors = reactive({ adonanKe: '', jamAdonan: '', suhuAdonan: '', namaPenimbang: '', jumlahKru: '', leaderProduksi: '' })
const startTried = ref(false)

function openStart(w) {
  startWo.value = w
  Object.assign(startForm, {
    adonanKe: '', jamAdonan: nowHHMM(), suhuAdonan: '',
    namaPenimbang: '', jumlahKru: '', leaderProduksi: ''
  })
  Object.assign(startErrors, {
    adonanKe: '', jamAdonan: '', suhuAdonan: '', namaPenimbang: '', jumlahKru: '', leaderProduksi: ''
  })
  startTried.value = false
  nextTick(() => dlgStart.value.showModal())
}
function validateStart() {
  startErrors.adonanKe = !(Number(startForm.adonanKe) >= 1) ? 'Isi nomor adonan (min. 1).' : ''
  startErrors.jamAdonan = !startForm.jamAdonan ? 'Isi jam adonan.' : ''
  startErrors.suhuAdonan = startForm.suhuAdonan === '' || startForm.suhuAdonan == null ? 'Isi suhu adonan.' : ''
  startErrors.namaPenimbang = !String(startForm.namaPenimbang).trim() ? 'Isi nama penimbang.' : ''
  startErrors.jumlahKru = !(Number(startForm.jumlahKru) >= 1) ? 'Isi jumlah kru (min. 1).' : ''
  startErrors.leaderProduksi = !String(startForm.leaderProduksi).trim() ? 'Isi leader produksi.' : ''
  return Object.values(startErrors).every((e) => !e)
}
function confirmStart() {
  startTried.value = true
  if (!validateStart()) return
  startProduction(startWo.value, {
    adonanKe: Number(startForm.adonanKe),
    jamAdonan: startForm.jamAdonan,
    suhuAdonan: Number(startForm.suhuAdonan),
    namaPenimbang: String(startForm.namaPenimbang).trim(),
    jumlahKru: Number(startForm.jumlahKru),
    leaderProduksi: String(startForm.leaderProduksi).trim()
  })
  closeStart()
}
function closeStart() {
  dlgStart.value.close()
  startWo.value = null
}

// ---- dialog 2: Material (tahap Material) ----
const dlgMat = ref(null)
const matWo = ref(null)
const matShortages = computed(() => (matWo.value ? materialShortages(matWo.value) : []))
const matDone = computed(() => (matWo.value ? materialComplete(matWo.value) : false))
const matDoneCount = computed(() =>
  matWo.value ? matWo.value.material.items.filter((i) => i.transferred >= i.required).length : 0
)

function openMat(w) {
  matWo.value = w
  nextTick(() => dlgMat.value.showModal())
}
function confirmMat() {
  confirmMaterial(matWo.value)
  closeMat()
}
function closeMat() {
  dlgMat.value.close()
  matWo.value = null
}

// ---- dialog 3: Operasi (tahap Operasi) ----
const dlgOps = ref(null)
const opsWo = ref(null)
const opsQty = reactive({}) // nama operasi → jumlah selesai (PCS)
const opsOk = reactive({})

function opMeta(s) {
  if (s === 'done') return { cls: 'chip-ok', label: 'Selesai' }
  if (s === 'in_progress') return { cls: 'chip-warn', label: 'Berjalan' }
  return { cls: 'chip-off', label: 'Belum Mulai' }
}
const opsDoneCount = computed(() =>
  opsWo.value ? opsWo.value.operations.filter((o) => o.status === 'done').length : 0
)

function openOps(w) {
  opsWo.value = w
  Object.keys(opsQty).forEach((k) => delete opsQty[k])
  Object.keys(opsOk).forEach((k) => delete opsOk[k])
  // operasi yang sedang berjalan dapat default jumlah = rencana (sama dgn panel)
  for (const op of w.operations) {
    if (op.status === 'in_progress') opsQty[op.name] = op.plannedPcs
  }
  nextTick(() => dlgOps.value.showModal())
}
function startOp(op) {
  startOperation(opsWo.value, op)
  opsQty[op.name] = op.plannedPcs
}
function finishOp(op) {
  if (opsQty[op.name] == null || !opsOk[op.name]) return
  finishOperation(opsWo.value, op, opsQty[op.name])
}
function confirmOps() {
  confirmOperations(opsWo.value)
  closeOps()
}
function closeOps() {
  dlgOps.value.close()
  opsWo.value = null
}

// ---- dialog 4: Pre-Packing (tahap Pre-Packing) ----
const dlgPak = ref(null)
const pakWo = ref(null)
const pakForm = reactive({ goodQty: null, rejectQty: null, trialQty: null, sisaQty: null, jam: '', qc: '' })
const pakOk = reactive({ goodQty: false, rejectQty: false, trialQty: false, sisaQty: false })
const pakFields = [
  { key: 'goodQty', label: 'Good Qty' },
  { key: 'rejectQty', label: 'Reject Qty' },
  { key: 'trialQty', label: 'Trial Qty' },
  { key: 'sisaQty', label: 'Sisa Qty' }
]
const pakTotal = computed(() => {
  const v = [pakForm.goodQty, pakForm.rejectQty, pakForm.trialQty, pakForm.sisaQty]
  if (v.some((x) => x == null)) return null
  return v.reduce((a, b) => a + b, 0)
})
const pakOver = computed(() => pakTotal.value != null && pakTotal.value > pakWo.value?.plannedStockQty)
const pakCanSave = computed(() =>
  Object.values(pakOk).every(Boolean) &&
  pakForm.jam !== '' && String(pakForm.qc).trim() !== ''
)

function openPak(w) {
  pakWo.value = w
  Object.assign(pakForm, { goodQty: null, rejectQty: null, trialQty: null, sisaQty: null, jam: '', qc: '' })
  Object.keys(pakOk).forEach((k) => { pakOk[k] = false })
  nextTick(() => dlgPak.value.showModal())
}
function confirmPak() {
  if (!pakCanSave.value) return
  savePrePacking(pakWo.value, {
    goodQty: pakForm.goodQty,
    rejectQty: pakForm.rejectQty,
    trialQty: pakForm.trialQty,
    sisaQty: pakForm.sisaQty,
    jam: pakForm.jam,
    qc: String(pakForm.qc).trim()
  })
  closePak()
}
function closePak() {
  dlgPak.value.close()
  pakWo.value = null
}

// ---- dialog 5: Selesaikan Produksi (tahap Finish) ----
const dlgDone = ref(null)
const doneWo = ref(null)
const doneFg = computed(() => (doneWo.value ? producedQty(doneWo.value) : 0))

function openDone(w) {
  doneWo.value = w
  nextTick(() => dlgDone.value.showModal())
}
function confirmDone() {
  completeProduction(doneWo.value)
  closeDone()
}
function closeDone() {
  dlgDone.value.close()
  doneWo.value = null
}
</script>

<template>
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
            <GripVertical v-if="nextStage(w)" class="kb-grip" :size="15" :stroke-width="2" aria-hidden="true" />
          </div>
          <span class="kb-id"><a :href="'#/wo/' + w.id" draggable="false" @click.stop>{{ w.id }}</a></span>
          <div class="kb-qty">
            <span class="ql">Rencana Produksi</span>
            <span class="qv">{{ qtyStack(w.plannedStockQty, w.qtyInPack).main }}</span>
            <span class="qu">{{ qtyStack(w.plannedStockQty, w.qtyInPack).sub }}</span>
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

  <!-- ============ dialog: Mulai Produksi (Persiapan) ============ -->
  <dialog ref="dlgStart" class="dialog dialog-wide" @click.self="closeStart">
    <template v-if="startWo">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><ClipboardList :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Mulai Produksi</h3>
          <p class="dlg-sub"><strong>{{ startWo.id }}</strong> · {{ startWo.product }}</p>
        </div>
      </header>

      <div class="fieldgroup">
        <div class="grouptitle">Data Adonan</div>
        <div class="form-grid cols3">
          <div class="field">
            <label for="k-adonanke">Adonan ke <span class="req">*</span></label>
            <input id="k-adonanke" v-model="startForm.adonanKe" class="input" type="number" min="1" step="1" />
            <div v-if="startTried && startErrors.adonanKe" class="err">{{ startErrors.adonanKe }}</div>
          </div>
          <div class="field">
            <label for="k-jamadonan">Jam Adonan <span class="req">*</span></label>
            <input id="k-jamadonan" v-model="startForm.jamAdonan" class="input" type="time" />
            <div v-if="startTried && startErrors.jamAdonan" class="err">{{ startErrors.jamAdonan }}</div>
          </div>
          <div class="field">
            <label for="k-suhu">Suhu Adonan <span class="req">*</span></label>
            <div class="inputwrap">
              <input id="k-suhu" v-model="startForm.suhuAdonan" class="input" type="number" step="0.1" min="0" />
              <span class="unitmark">°C</span>
            </div>
            <div v-if="startTried && startErrors.suhuAdonan" class="err">{{ startErrors.suhuAdonan }}</div>
          </div>
        </div>
      </div>

      <div class="fieldgroup">
        <div class="grouptitle">Tim Produksi</div>
        <div class="form-grid cols3">
          <div class="field">
            <label for="k-penimbang">Nama Penimbang <span class="req">*</span></label>
            <input id="k-penimbang" v-model="startForm.namaPenimbang" class="input" type="text" />
            <div v-if="startTried && startErrors.namaPenimbang" class="err">{{ startErrors.namaPenimbang }}</div>
          </div>
          <div class="field">
            <label for="k-kru">Jumlah Kru <span class="req">*</span></label>
            <input id="k-kru" v-model="startForm.jumlahKru" class="input" type="number" min="1" step="1" />
            <div v-if="startTried && startErrors.jumlahKru" class="err">{{ startErrors.jumlahKru }}</div>
          </div>
          <div class="field">
            <label for="k-leader">Leader Produksi <span class="req">*</span></label>
            <input id="k-leader" v-model="startForm.leaderProduksi" class="input" type="text" />
            <div v-if="startTried && startErrors.leaderProduksi" class="err">{{ startErrors.leaderProduksi }}</div>
          </div>
        </div>
      </div>

      <div class="dlg-actions">
        <button class="btn" @click="closeStart">Batal</button>
        <button class="btn btn-primary" @click="confirmStart">Mulai Produksi</button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: Material ============ -->
  <dialog ref="dlgMat" class="dialog" @click.self="closeMat">
    <template v-if="matWo">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><Boxes :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Material</h3>
          <p class="dlg-sub"><strong>{{ matWo.id }}</strong> · {{ matWo.product }}</p>
        </div>
      </header>

      <div class="dlg-context">
        <div class="sum-row">
          <span class="k">Material ditransfer</span>
          <span class="v">{{ matDoneCount }} dari {{ matWo.material.items.length }} bahan</span>
        </div>
      </div>
      <div v-if="matShortages.length" class="callout">
        Kekurangan material pada {{ matShortages.length }} bahan:
        {{ matShortages.map((i) => i.name).join(', ') }}.
      </div>
      <div v-else class="callout ok">Semua material telah ditransfer.</div>

      <div class="dlg-actions">
        <button v-if="matShortages.length" class="btn" @click="transferAll(matWo)">
          Transfer Semua Material
        </button>
        <button class="btn btn-primary" :disabled="!matDone" @click="confirmMat">
          {{ nextStage(matWo) === 'operasi' ? 'Lanjut ke Operasi' : 'Lanjut ke Pre-Packing' }}
        </button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: Operasi ============ -->
  <dialog ref="dlgOps" class="dialog" @click.self="closeOps">
    <template v-if="opsWo">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><Cog :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Operasi</h3>
          <p class="dlg-sub"><strong>{{ opsWo.id }}</strong> · {{ opsWo.product }}</p>
        </div>
      </header>

      <div class="dlg-context">
        <div class="sum-row">
          <span class="k">Operasi selesai</span>
          <span class="v">{{ opsDoneCount }} dari {{ opsWo.operations.length }}</span>
        </div>
      </div>

      <div v-for="op in opsWo.operations" :key="op.name" class="opmini">
        <div class="opmini-head">
          <div class="opmini-main">
            {{ op.name }}
            <small>{{ op.workstation }} · {{ op.operator }}</small>
          </div>
          <span class="chip" :class="opMeta(op.status).cls">{{ opMeta(op.status).label }}</span>
        </div>
        <div v-if="op.status === 'pending'" class="opmini-act">
          <button class="btn btn-sm" @click="startOp(op)">Mulai</button>
        </div>
        <div v-else-if="op.status === 'in_progress'" class="opmini-act">
          <QtyInput
            label="Jumlah Selesai"
            unit-key="opSelesai"
            required
            :qty-in-pack="opsWo.qtyInPack"
            v-model="opsQty[op.name]"
            @update:valid="opsOk[op.name] = $event"
          />
          <button
            class="btn btn-sm btn-primary"
            :disabled="opsQty[op.name] == null || !opsOk[op.name]"
            @click="finishOp(op)"
          >
            Selesaikan
          </button>
        </div>
      </div>

      <p v-if="!opsAllDone(opsWo)" class="hint" style="margin-top: 8px">
        Selesaikan semua operasi untuk melanjutkan.
      </p>
      <div class="dlg-actions">
        <button class="btn" @click="closeOps">Batal</button>
        <button class="btn btn-primary" :disabled="!opsAllDone(opsWo)" @click="confirmOps">
          Lanjut ke Pre-Packing
        </button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: Pre-Packing ============ -->
  <dialog ref="dlgPak" class="dialog dialog-wide" @click.self="closePak">
    <template v-if="pakWo">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><PackageCheck :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Pre-Packing</h3>
          <p class="dlg-sub"><strong>{{ pakWo.id }}</strong> · {{ pakWo.product }}</p>
        </div>
      </header>

      <div class="form-grid cols4" style="margin-top: 4px">
        <QtyInput
          v-for="f in pakFields"
          :key="f.key"
          :label="f.label"
          :unit-key="f.key"
          required
          :qty-in-pack="pakWo.qtyInPack"
          v-model="pakForm[f.key]"
          @update:valid="pakOk[f.key] = $event"
        />
      </div>

      <div class="form-grid" style="margin-top: 14px">
        <div class="field">
          <label for="k-pak-jam">Jam Pembekuan <span class="req">*</span></label>
          <input id="k-pak-jam" v-model="pakForm.jam" class="input" type="time" />
        </div>
        <div class="field">
          <label for="k-pak-qc">QC Produksi <span class="req">*</span></label>
          <input id="k-pak-qc" v-model="pakForm.qc" class="input" type="text" />
        </div>
      </div>

      <div style="margin-top: 10px">
        <div v-if="pakTotal != null" class="sum-row">
          <span class="k">Total hasil (Good + Reject + Trial + Sisa)</span>
          <span class="v" :class="{ neg: pakOver }">{{ qtyMain(pakTotal, pakWo.qtyInPack) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Rencana Work Order</span>
          <span class="v">{{ qtyMain(pakWo.plannedStockQty, pakWo.qtyInPack) }}</span>
        </div>
        <p v-if="pakOver" class="hint warn">Total melebihi rencana.</p>
      </div>

      <div class="dlg-actions">
        <button class="btn" @click="closePak">Batal</button>
        <button class="btn btn-primary" :disabled="!pakCanSave" @click="confirmPak">
          Simpan &amp; Lanjut ke Finish
        </button>
      </div>
    </template>
  </dialog>

  <!-- ============ dialog: Selesaikan Produksi (Finish) ============ -->
  <dialog ref="dlgDone" class="dialog" @click.self="closeDone">
    <template v-if="doneWo">
      <header class="dlg-head">
        <span class="dlg-ico" aria-hidden="true"><Flag :size="16" :stroke-width="1.9" /></span>
        <div class="dlg-hgroup">
          <h3>Selesaikan Produksi?</h3>
          <p class="dlg-sub"><strong>{{ doneWo.id }}</strong> · {{ doneWo.product }}</p>
        </div>
      </header>

      <div class="dlg-context">
        <div class="sum-row">
          <span class="k">Rencana Work Order</span>
          <span class="v">{{ qtyMain(doneWo.plannedStockQty, doneWo.qtyInPack) }}</span>
        </div>
        <div class="sum-row">
          <span class="k">Hasil Aktual (Good Qty Pre-Packing)</span>
          <span class="v">{{ qtyMain(doneFg, doneWo.qtyInPack) }}</span>
        </div>
      </div>
      <p>
        Barang jadi <strong>{{ qtyMain(doneFg, doneWo.qtyInPack) }}</strong> akan dibuat di
        <strong>{{ doneWo.warehouse }}</strong> melalui Manufacture Stock Entry di ERPNext, lalu
        menunggu permintaan serah terima dari gudang.
      </p>

      <div class="dlg-actions">
        <button class="btn" @click="closeDone">Batal</button>
        <button class="btn btn-primary" @click="confirmDone">Ya, Selesaikan</button>
      </div>
    </template>
  </dialog>
</template>

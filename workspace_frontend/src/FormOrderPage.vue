<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ClipboardList, Inbox, Plus, Trash2 } from 'lucide-vue-next'
import LinkInput from './LinkInput.vue'
import { cancelFormOrder, createFormOrder, formOrders, formOrderState, loadFormOrders, uiTopLoading } from './store.js'
import { foItemsText, foStatusMeta, formCanSubmit, validateFormRows } from './form-order.js'

// FO 2026-09-18: produksi meminta barang dari gudang → MR Material Transfer
// native (custom_is_form_order). Server otoritatif: validasi baris di sini
// hanya UX; error server ditampilkan apa adanya dan isian dipertahankan.
const tomorrow = () => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const rows = reactive([{ code: '', qty: '' }])
const scheduleDate = ref(tomorrow())
const note = ref('')
const error = ref('')
const savedAt = ref('')

const rowErrors = computed(() => validateFormRows(rows))
const canSubmit = computed(() => formCanSubmit(rows, rowErrors.value) && !!scheduleDate.value && !formOrderState.pending)

function addRow() {
  rows.push({ code: '', qty: '' })
}
function removeRow(i) {
  if (rows.length > 1) rows.splice(i, 1)
}

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  savedAt.value = ''
  try {
    await createFormOrder(rows, scheduleDate.value, note.value)
    // sukses: daftar sudah diganti server truth — reset form
    rows.splice(0, rows.length, { code: '', qty: '' })
    note.value = ''
    savedAt.value = new Date().toLocaleTimeString('id-ID')
  } catch (e) {
    error.value = e.message // seluruh isian dipertahankan (pola FU14)
  }
}

// ---- batalkan (pembuat / manager; guard di server) ----
const dlgCancel = ref(null)
const cancelTarget = ref(null)
const cancelError = ref('')

function openCancel(id) {
  cancelTarget.value = formOrders.find((o) => o.id === id) || null
  cancelError.value = ''
  if (cancelTarget.value) nextTick(() => dlgCancel.value.showModal())
}
function closeCancel() {
  dlgCancel.value.close()
  cancelTarget.value = null
}
async function confirmCancel() {
  cancelError.value = ''
  try {
    await cancelFormOrder(cancelTarget.value.id)
    closeCancel()
  } catch (e) {
    cancelError.value = e.message
  }
}

onMounted(async () => {
  uiTopLoading.active = true
  try {
    await Promise.all([loadFormOrders()])
  } finally {
    uiTopLoading.active = false
  }
})
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Form Order</h1>
      <p class="sub">Produksi meminta barang dari gudang — dibuat sebagai Material Request.</p>
    </div>
    <div class="ph-date">{{ new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }}</div>
  </div>

  <div v-if="formOrderState.error" class="appfoot" style="color:#b3261e">Gagal memuat: {{ formOrderState.error }} — <a href="#" @click.prevent="loadFormOrders()">coba lagi</a></div>

  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><ClipboardList :size="15" :stroke-width="1.9" /></span>
      <h2>Buat Form Order</h2>
    </div>
    <div class="panel-body">
      <div class="fo-rows">
        <div v-for="(row, i) in rows" :key="i" class="fo-row">
          <div class="field fo-item">
            <label :for="`fo-item-${i}`">Item <span class="req">*</span></label>
            <LinkInput :id="`fo-item-${i}`" v-model="row.code" doctype="Item" />
          </div>
          <div class="field fo-qty">
            <label :for="`fo-qty-${i}`">Qty <span class="req">*</span></label>
            <input :id="`fo-qty-${i}`" v-model="row.qty" class="input" type="number" step="any" min="0" inputmode="decimal" :aria-invalid="!!rowErrors[i]" />
          </div>
          <button class="btn fo-del" :disabled="rows.length === 1" :aria-label="`Hapus baris ${i + 1}`" @click="removeRow(i)">
            <Trash2 :size="14" :stroke-width="2" />
          </button>
          <p v-if="rowErrors[i]" class="err fo-row-err" role="alert">{{ rowErrors[i] }}</p>
        </div>
      </div>
      <button class="btn fo-add" @click="addRow">
        <Plus :size="14" :stroke-width="2" /> Tambah item
      </button>

      <div class="form-grid cols2" style="margin-top: 14px">
        <div class="field">
          <label for="fo-date">Tanggal dibutuhkan <span class="req">*</span></label>
          <input id="fo-date" v-model="scheduleDate" class="input" type="date" />
          <div class="hint">Default besok. Item ber-batch belum didukung — minta lewat Desk.</div>
        </div>
        <div class="field">
          <label for="fo-note">Catatan</label>
          <input id="fo-note" v-model="note" class="input" type="text" maxlength="280" placeholder="Opsional" />
        </div>
      </div>

      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <p v-if="formOrderState.pending === 'create_form_order'" role="status">Menyimpan…</p>
      <div class="panel-foot" style="padding-left: 0">
        <button class="btn btn-primary" :disabled="!canSubmit" @click="submit">Kirim Form Order</button>
        <span v-if="savedAt" class="why">Tersimpan pada {{ savedAt }}.</span>
      </div>
    </div>
  </section>

  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><Inbox :size="15" :stroke-width="1.9" /></span>
      <h2>Riwayat Form Order</h2>
      <span class="lead">Status dihitung server dari dokumen.</span>
    </div>
    <div class="panel-body">
      <div class="tbl-wrap">
        <table class="datatable">
          <thead>
            <tr>
              <th>Dokumen</th><th>Item</th><th>Dibutuhkan</th><th>Dibuat oleh</th>
              <th>Status</th><th>Catatan</th><th v-if="formOrders.some((o) => o.status === 'menunggu')"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in formOrders" :key="o.id">
              <td>
                <span class="tbl-doc">{{ o.materialRequest }}</span>
                <span v-if="o.stockEntry" class="tbl-sub">{{ o.stockEntry }} · {{ o.sentAt }}</span>
              </td>
              <td>
                <span>{{ foItemsText(o) }}</span>
                <span class="tbl-sub">{{ o.fromWarehouse || '-' }} → {{ o.toWarehouse || '-' }}</span>
              </td>
              <td>{{ o.scheduleDate || '-' }}</td>
              <td>{{ o.ownerName }}</td>
              <td><span class="chip" :class="foStatusMeta(o.status).cls">{{ foStatusMeta(o.status).label }}</span></td>
              <td class="tbl-note">{{ o.note || '-' }}</td>
              <td v-if="formOrders.some((x) => x.status === 'menunggu')">
                <button v-if="o.status === 'menunggu'" class="btn btn-sm" :disabled="!!formOrderState.pending" @click="openCancel(o.id)">Batalkan</button>
              </td>
            </tr>
            <tr v-if="!formOrders.length">
              <td :colspan="7" class="tbl-empty">
                <Inbox :size="16" :stroke-width="1.8" aria-hidden="true" />
                <span>Belum ada Form Order.</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <dialog ref="dlgCancel" class="dialog" @click.self="closeCancel">
    <template v-if="cancelTarget">
      <h3>Batalkan Form Order?</h3>
      <p>
        {{ cancelTarget.materialRequest }} — {{ foItemsText(cancelTarget) }} akan dibatalkan
        selama belum diproses gudang.
      </p>
      <p v-if="cancelError" class="err" role="alert">{{ cancelError }}</p>
      <p v-if="formOrderState.pending === 'cancel_form_order'" role="status">Menyimpan…</p>
      <div class="dlg-actions">
        <button class="btn" :disabled="!!formOrderState.pending" @click="closeCancel">Kembali</button>
        <button class="btn btn-primary" :disabled="!!formOrderState.pending" @click="confirmCancel">Ya, Batalkan</button>
      </div>
    </template>
  </dialog>
</template>

<script setup>
// FU52: form buat Form Order jadi HALAMAN SENDIRI (#/form-order/baru) — bukan
// panel nyempil di halaman riwayat. Alur: tombol "Buat Form Order" di riwayat
// menavigasi ke sini; sukses submit menavigasi kembali + pesan sukses
// ber-nama MR disimpan di formOrderState (dibaca halaman riwayat).
// Isi form dipindah apa adanya dari FormOrderPage (FU48c: dropdown Satuan,
// default satuan terakhir user; validasi server tetap otoritatif).
import { computed, reactive, ref, watch } from 'vue'
import { ArrowLeft, ClipboardList, Plus, Trash2 } from 'lucide-vue-next'
import LinkInput from './LinkInput.vue'
import { createFormOrder, foItemInfo, formOrderState } from './store.js'
import { defaultUom, formCanSubmit, itemRowProblem, ITEM_PROBLEM_TEXT, uomOptions, uomProblem, validateFormRows } from './form-order.js'

const tomorrow = () => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const rows = reactive([{ code: '', qty: '', info: null, infoFor: '', uom: '' }])
const scheduleDate = ref(tomorrow())
const note = ref('')
const error = ref('')

// ambil info item (satuan/nama) saat kode terpilih; ber-batch/non-stok
// mendapat peringatan dini di barisnya — validasi server tetap otoritatif.
// Info termuat → satuan baris di-reset ke default item TERPILIH (last_uom
// tervalidasi → stock_uom): ganti item tak pernah menyisakan satuan lama.
watch(rows, async () => {
  for (const row of rows) {
    if (row.code && row.infoFor !== row.code) {
      row.infoFor = row.code
      row.info = await foItemInfo(row.code)
      row.uom = defaultUom(row.info)
    } else if (!row.code && (row.info || row.infoFor)) {
      row.info = null
      row.infoFor = ''
      row.uom = ''
    }
  }
}, { deep: true })

const rowErrors = computed(() => validateFormRows(rows))
const rowProblems = computed(() => rows.map((r) => itemRowProblem(r.info) || uomProblem(r)))
const rowNotes = computed(() =>
  rows.map((row, i) =>
    [rowProblems.value[i] ? ITEM_PROBLEM_TEXT[rowProblems.value[i]] : '', rowErrors.value[i]]
      .filter(Boolean)
      .join(' · ')
  )
)
const canSubmit = computed(() =>
  formCanSubmit(rows, rowErrors.value)
  && !rowProblems.value.some(Boolean)
  && !!scheduleDate.value
  && !formOrderState.pending
)

function addRow() {
  rows.push({ code: '', qty: '', info: null, infoFor: '', uom: '' })
}
function removeRow(i) {
  if (rows.length > 1) rows.splice(i, 1)
}
function goBack() {
  window.location.hash = '#/form-order'
}

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  try {
    const res = await createFormOrder(rows, scheduleDate.value, note.value)
    // sukses: daftar sudah diganti server truth — kembali ke riwayat dan
    // umumkan nama MR di sana (dibaca onMounted halaman riwayat)
    formOrderState.justSaved = res?.material_request || ''
    goBack()
  } catch (e) {
    error.value = e.message // seluruh isian dipertahankan (pola FU14)
  }
}
</script>

<template>
  <div class="page-head">
    <div class="ph-left">
      <h1>Buat Form Order</h1>
      <p class="sub">Satu form menjadi satu Material Request.</p>
    </div>
    <div class="ph-date">{{ new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }}</div>
  </div>

  <div class="toolbar fo-actions">
    <button class="btn" @click="goBack">
      <ArrowLeft :size="14" :stroke-width="2" />
      Kembali ke Riwayat
    </button>
  </div>

  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><ClipboardList :size="15" :stroke-width="1.9" /></span>
      <h2>Permintaan Barang</h2>
    </div>
    <div class="panel-body">
      <!-- field induk dulu, grid item di bawahnya — urutan ala form ERPNext -->
      <div class="form-grid cols2">
        <div class="field">
          <label for="fo-date">Tanggal dibutuhkan <span class="req">*</span></label>
          <input id="fo-date" v-model="scheduleDate" class="input" type="date" />
        </div>
        <div class="field">
          <label for="fo-note">Catatan</label>
          <input id="fo-note" v-model="note" class="input" type="text" maxlength="280" placeholder="Opsional" />
        </div>
      </div>

      <!-- grid item ala child table ERPNext -->
      <div class="tbl-wrap fo-grid-wrap">
        <table class="datatable fo-grid">
          <thead>
            <tr>
              <th class="fo-c-item">Item</th>
              <th class="fo-c-qty">Qty</th>
              <th class="fo-c-uom">Satuan</th>
              <th class="fo-c-act" aria-label="Aksi baris"></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="(row, i) in rows" :key="i">
              <tr>
                <td class="fo-c-item">
                  <LinkInput :id="`fo-item-${i}`" v-model="row.code" :display-label="row.info?.item_name" doctype="Item" />
                </td>
                <td class="fo-c-qty">
                  <input
                    :id="`fo-qty-${i}`"
                    v-model="row.qty"
                    class="input fo-qty-input"
                    type="number"
                    step="any"
                    min="0"
                    inputmode="decimal"
                    :aria-invalid="!!rowNotes[i]"
                  />
                </td>
                <td class="fo-c-uom fo-uom">
                  <select
                    v-if="row.info"
                    v-model="row.uom"
                    class="input fo-uom-select"
                    :aria-label="`Satuan baris ${i + 1}`"
                  >
                    <option v-for="u in uomOptions(row.info)" :key="u" :value="u">{{ u }}</option>
                  </select>
                  <span v-else aria-hidden="true">—</span>
                </td>
                <td class="fo-c-act">
                  <button class="btn fo-del" :disabled="rows.length === 1" :aria-label="`Hapus baris ${i + 1}`" @click="removeRow(i)">
                    <Trash2 :size="14" :stroke-width="2" />
                  </button>
                </td>
              </tr>
              <tr v-if="rowNotes[i]" class="fo-grid-err">
                <td colspan="4"><p class="err" role="alert">{{ rowNotes[i] }}</p></td>
              </tr>
            </template>
            <tr class="fo-grid-addrow">
              <td colspan="4">
                <button type="button" class="btn fo-add" @click="addRow">
                  <Plus :size="14" :stroke-width="2" /> Tambah Baris
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <p v-if="formOrderState.pending === 'create_form_order'" role="status">Menyimpan…</p>
      <div class="panel-foot" style="padding-left: 0">
        <button class="btn" :disabled="!!formOrderState.pending" @click="goBack">Batal</button>
        <button class="btn btn-primary" :disabled="!canSubmit" @click="submit">Kirim Form Order</button>
      </div>
    </div>
  </section>
</template>

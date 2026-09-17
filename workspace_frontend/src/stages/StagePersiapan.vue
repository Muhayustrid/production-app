<script setup>
import { reactive, ref } from 'vue'
import { ClipboardList } from 'lucide-vue-next'
import { startProduction, suggestionPreferences } from '../store.js'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const p = props.wo.persiapan
// FU11: jam adonan boleh kosong (server mengisi jam saat simpan);
// penimbang/leader di-suggest dari nilai tercatat terakhir (bisa diubah)
const form = reactive({
  adonanKe: p.adonanKe ?? '',
  jamAdonan: p.jamAdonan || '',
  suhuAdonan: p.suhuAdonan ?? '',
  namaPenimbang: p.namaPenimbang || (!props.review && suggestionPreferences.enabled && p.penimbangSuggested) || '',
  jumlahKru: p.jumlahKru ?? ((!props.review && suggestionPreferences.enabled) ? p.jumlahKruSuggested : '') ?? '',
  leaderProduksi: p.leaderProduksi || (!props.review && suggestionPreferences.enabled && p.leaderSuggested) || ''
})
const errors = reactive({})
const tried = ref(false)

function validate() {
  errors.adonanKe = !(Number(form.adonanKe) >= 1) ? 'Isi nomor adonan (min. 1).' : ''
  // FU38: penimbang/jumlah kru/leader opsional — kosong = tidak dicatat
  // FU39: suhu adonan opsional juga — kosong dikirim '' agar server melewatkan nilainya
  return Object.values(errors).every((e) => !e)
}

function submit() {
  tried.value = true
  if (!validate()) return
  startProduction(props.wo, {
    adonanKe: Number(form.adonanKe),
    jamAdonan: form.jamAdonan,
    // FU39: kosong → '' (server melewatkan), 0 eksplisit tetap tercatat 0.0
    suhuAdonan: form.suhuAdonan === '' || form.suhuAdonan == null ? '' : Number(form.suhuAdonan),
    namaPenimbang: String(form.namaPenimbang).trim(),
    jumlahKru: Number(form.jumlahKru),
    leaderProduksi: String(form.leaderProduksi).trim()
  })
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="p-ico"><ClipboardList :size="15" :stroke-width="1.9" /></span>
      <h2>Persiapan</h2>
      <span v-if="review" class="chip chip-info" style="margin-left: auto">Tinjauan</span>
    </div>

    <div class="panel-body">
      <div class="fieldgroup">
        <div class="grouptitle">Data Adonan</div>
        <div class="form-grid cols3">
          <div class="field">
            <label for="f-adonanke">Adonan ke <span class="req">*</span></label>
            <input id="f-adonanke" v-model="form.adonanKe" class="input" type="number" min="1" step="1" :disabled="review" />
            <div v-if="tried && errors.adonanKe" class="err">{{ errors.adonanKe }}</div>
          </div>

          <div class="field">
            <label for="f-jamadonan">Jam Adonan</label>
            <input id="f-jamadonan" v-model="form.jamAdonan" class="input" type="time" :disabled="review" />
          </div>

          <div class="field">
            <label for="f-suhu">Suhu Adonan</label>
            <div class="inputwrap">
              <input id="f-suhu" v-model="form.suhuAdonan" class="input" type="number" step="0.1" min="0" :disabled="review" />
              <span class="unitmark">°C</span>
            </div>
          </div>
        </div>
      </div>

      <div class="fieldgroup">
        <div class="grouptitle">Tim Produksi</div>
        <div class="form-grid cols3">
          <div class="field">
            <label for="f-penimbang">Nama Penimbang</label>
            <input id="f-penimbang" v-model="form.namaPenimbang" class="input" type="text" :disabled="review" />
          </div>

          <div class="field">
            <label for="f-kru">Jumlah Kru</label>
            <input id="f-kru" v-model="form.jumlahKru" class="input" type="number" min="1" step="1" :disabled="review" />
          </div>

          <div class="field">
            <label for="f-leader">Leader Produksi</label>
            <input id="f-leader" v-model="form.leaderProduksi" class="input" type="text" :disabled="review" />
          </div>
        </div>
      </div>
    </div>

    <div v-if="!review" class="panel-foot">
      <button class="btn btn-primary" @click="submit">Mulai Produksi</button>
    </div>
  </section>
</template>

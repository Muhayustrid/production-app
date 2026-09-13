<script setup>
import { reactive, ref } from 'vue'
import { ClipboardList } from 'lucide-vue-next'
import { startProduction } from '../store.js'

const props = defineProps({
  wo: { type: Object, required: true },
  review: Boolean,
  stageKey: String
})

const p = props.wo.persiapan
const nowHHMM = () => new Date().toTimeString().slice(0, 5)
const form = reactive({
  adonanKe: p.adonanKe ?? '',
  jamAdonan: p.jamAdonan || nowHHMM(),
  suhuAdonan: p.suhuAdonan ?? '',
  namaPenimbang: p.namaPenimbang || '',
  jumlahKru: p.jumlahKru ?? '',
  leaderProduksi: p.leaderProduksi || ''
})
const errors = reactive({})
const tried = ref(false)

function validate() {
  errors.adonanKe = !(Number(form.adonanKe) >= 1) ? 'Isi nomor adonan (min. 1).' : ''
  errors.jamAdonan = !form.jamAdonan ? 'Isi jam adonan.' : ''
  errors.suhuAdonan = form.suhuAdonan === '' || form.suhuAdonan == null ? 'Isi suhu adonan.' : ''
  errors.namaPenimbang = !String(form.namaPenimbang).trim() ? 'Isi nama penimbang.' : ''
  errors.jumlahKru = !(Number(form.jumlahKru) >= 1) ? 'Isi jumlah kru (min. 1).' : ''
  errors.leaderProduksi = !String(form.leaderProduksi).trim() ? 'Isi leader produksi.' : ''
  return Object.values(errors).every((e) => !e)
}

function submit() {
  tried.value = true
  if (!validate()) return
  startProduction(props.wo, {
    adonanKe: Number(form.adonanKe),
    jamAdonan: form.jamAdonan,
    suhuAdonan: Number(form.suhuAdonan),
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
      <span class="lead">Data persiapan diisi selama Work Order masih Draft.</span>
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
            <label for="f-jamadonan">Jam Adonan <span class="req">*</span></label>
            <input id="f-jamadonan" v-model="form.jamAdonan" class="input" type="time" :disabled="review" />
            <div v-if="tried && errors.jamAdonan" class="err">{{ errors.jamAdonan }}</div>
          </div>

          <div class="field">
            <label for="f-suhu">Suhu Adonan <span class="req">*</span></label>
            <div class="inputwrap">
              <input id="f-suhu" v-model="form.suhuAdonan" class="input" type="number" step="0.1" min="0" :disabled="review" />
              <span class="unitmark">°C</span>
            </div>
            <div v-if="tried && errors.suhuAdonan" class="err">{{ errors.suhuAdonan }}</div>
          </div>
        </div>
      </div>

      <div class="fieldgroup">
        <div class="grouptitle">Tim Produksi</div>
        <div class="form-grid cols3">
          <div class="field">
            <label for="f-penimbang">Nama Penimbang <span class="req">*</span></label>
            <input id="f-penimbang" v-model="form.namaPenimbang" class="input" type="text" :disabled="review" />
            <div v-if="tried && errors.namaPenimbang" class="err">{{ errors.namaPenimbang }}</div>
          </div>

          <div class="field">
            <label for="f-kru">Jumlah Kru <span class="req">*</span></label>
            <input id="f-kru" v-model="form.jumlahKru" class="input" type="number" min="1" step="1" :disabled="review" />
            <div v-if="tried && errors.jumlahKru" class="err">{{ errors.jumlahKru }}</div>
          </div>

          <div class="field">
            <label for="f-leader">Leader Produksi <span class="req">*</span></label>
            <input id="f-leader" v-model="form.leaderProduksi" class="input" type="text" :disabled="review" />
            <div v-if="tried && errors.leaderProduksi" class="err">{{ errors.leaderProduksi }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!review" class="panel-foot">
      <button class="btn btn-primary" @click="submit">Mulai Produksi</button>
      <span class="why">Mengaktifkan Work Order di ERPNext (Draft → In Process) dan membuka tahap Material.</span>
    </div>
  </section>
</template>

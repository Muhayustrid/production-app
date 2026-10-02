<script setup>
// FU79d: field rentang tunggal (from → to) — satu komponen untuk panel filter
// Bahan, Work Order, dan Stock Entry. State machine FU79c: klik → kalender
// native (showPicker), pilihan pertama = from (langsung hidup), kalender
// kedua terbuka otomatis (activation hangat di event change), pilihan kedua =
// to (ditukar bila < from), cancel to → tetap from aja. Label DD-MM-YYYY,
// rentang "01-10-2026 to 02-10-2026"; X mengembalikan nilai reset.
import { computed, ref } from 'vue'
import { Calendar, X } from 'lucide-vue-next'
import { rentangDmyText, rentangSetelahPilih } from './dashboard.js'

const props = defineProps({
  dari: { type: String, default: '' },
  sampai: { type: String, default: '' },
  // nilai yang dikembalikan tombol X (bahan: rentang dasar server; lainnya '')
  resetDari: { type: String, default: '' },
  resetSampai: { type: String, default: '' },
  // 'same' = pilihan pertama langsung satu hari (bahan — endpoint wajib
  // dari+sampai); 'clear' = from aja terbuka (WO/handover, semantik lama)
  firstTo: { type: String, default: 'clear' },
  placeholder: { type: String, default: 'Pilih rentang' },
  ariaLabel: { type: String, default: 'Rentang tanggal: klik untuk memilih awal, lalu akhir' }
})
const emit = defineEmits(['update:dari', 'update:sampai'])

const kalender = ref(null)
const mode = ref(null) // null | 'dari' | 'sampai'
const label = computed(() => rentangDmyText(props.dari, props.sampai))
const aktif = computed(() => props.dari !== props.resetDari || props.sampai !== props.resetSampai)

function bukaPicker(inp) {
  try {
    inp.showPicker()
  } catch {
    inp.focus() // webview tanpa showPicker: minimal bisa diketik manual
  }
}
function klik() {
  const inp = kalender.value
  if (!inp) return
  // to masih menunggu (kalender kedua sempat tertutup) → lanjut to, bukan ulang
  if (mode.value === 'sampai') {
    bukaPicker(inp)
    return
  }
  mode.value = 'dari'
  inp.value = '' // pilih sama = tetap fire change (nilai dibersihkan dulu)
  bukaPicker(inp)
}
function ubah() {
  const inp = kalender.value
  const v = inp.value
  if (!v) return
  if (mode.value === 'sampai') {
    // props.dari terkini sudah mengalir dari emit fase 'dari' (re-render antar pilih)
    const [d, s] = rentangSetelahPilih(props.dari, props.sampai, v, 'sampai')
    emit('update:dari', d)
    emit('update:sampai', s)
    mode.value = null
    return
  }
  const [d, s] = rentangSetelahPilih(props.dari, props.sampai, v, 'dari', props.firstTo)
  emit('update:dari', d)
  emit('update:sampai', s)
  mode.value = 'sampai'
  inp.value = ''
  // activation masih hangat di event change → kalender kedua otomatis;
  // panel tertutup = komponen unmount, timer jalan di node lepas (tak berbahaya)
  setTimeout(() => bukaPicker(inp), 60)
}
function tutup() {
  // picker ditutup tanpa memilih (cancel) → keluar dari mode to
  if (mode.value === 'sampai' && !kalender.value?.value) mode.value = null
}
function reset() {
  emit('update:dari', props.resetDari)
  emit('update:sampai', props.resetSampai)
  mode.value = null
}
</script>

<template>
  <div
    class="rangepicker"
    role="button"
    tabindex="0"
    :aria-label="ariaLabel"
    @click="klik"
    @keydown.enter.prevent="klik"
  >
    <Calendar :size="14" :stroke-width="2" class="rp-ico" aria-hidden="true" />
    <span class="rp-label" :class="{ 'rp-ph': !label }">{{ label || placeholder }}</span>
    <button
      v-if="aktif"
      type="button"
      class="rp-clear"
      aria-label="Kembalikan rentang ke awal"
      @click.stop="reset"
    >
      <X :size="13" :stroke-width="2.2" aria-hidden="true" />
    </button>
    <input
      ref="kalender"
      type="date"
      class="rp-input"
      tabindex="-1"
      aria-hidden="true"
      @change="ubah"
      @blur="tutup"
    />
  </div>
</template>

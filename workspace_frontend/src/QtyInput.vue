<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fieldUnits } from './store.js'
import { fmtInt, packParts, parseQtyText, pcsToText } from './format.js'

const props = defineProps({
  label: { type: String, required: true },
  unitKey: { type: String, required: true },
  qtyInPack: { type: Number, required: true },
  required: Boolean,
  disabled: Boolean,
  modelValue: { type: Number, default: null }
})
const emit = defineEmits(['update:modelValue', 'update:valid'])

// satuan per kolom: disimpan global per unitKey, jadi ikut settingan terakhir
const unit = computed(() => fieldUnits[props.unitKey] ?? 'pack')
const uid = `q_${Math.random().toString(36).slice(2, 8)}`

const text = ref('')
const approx = ref(false)
// teks hanya sumber nilai setelah user benar-benar mengetik;
// saat ganti satuan/dari luar, teks diturunkan dari nilai PCS tersimpan
const dirty = ref(false)

onMounted(() => {
  const r = pcsToText(props.modelValue, unit.value, props.qtyInPack)
  text.value = r.text
  approx.value = r.approx
})

const parsed = computed(() => {
  if (!dirty.value) {
    const v = props.modelValue
    if (v == null) return { value: null, error: null, warn: null }
    return {
      value: v,
      error: null,
      warn:
        v % props.qtyInPack !== 0
          ? 'Bukan kelipatan 1 Pack'
          : null
    }
  }
  return parseQtyText(text.value, unit.value, props.qtyInPack)
})

watch(parsed, (p) => {
  if (!p.error) emit('update:modelValue', p.value)
})

const valid = computed(
  () => !parsed.value.error && (!props.required || parsed.value.value != null)
)
watch(valid, (v) => emit('update:valid', v), { immediate: true })

function derive() {
  const r = pcsToText(props.modelValue, unit.value, props.qtyInPack)
  text.value = r.text
  approx.value = r.approx
  dirty.value = false
}

watch(() => props.modelValue, () => { if (!dirty.value) derive() })
watch(unit, () => derive())

function onInput() {
  dirty.value = true
  approx.value = false
}

// klik label satuan: ganti satuan kolom ini saja
function toggleUnit() {
  fieldUnits[props.unitKey] = unit.value === 'pack' ? 'pcs' : 'pack'
}

const hint = computed(() => {
  const pcs = parsed.value.value ?? 0
  const { str, approx: pa } = packParts(pcs, props.qtyInPack)
  return `= ${pa ? '≈ ' : ''}${str} Pack · ${fmtInt(pcs)} PCS`
})
</script>

<template>
  <div class="field">
    <label :for="uid">{{ label }} <span v-if="required" class="req">*</span></label>
    <div class="qtywrap" :class="{ invalid: !!parsed.error, warn: !!parsed.warn && !parsed.error, disabled }">
      <span v-if="approx" class="approx" title="Nilai PCS asli tidak terwakili eksak dalam Pack">≈</span>
      <input
        :id="uid"
        v-model="text"
        class="qtyinput"
        type="text"
        inputmode="decimal"
        placeholder="0"
        :disabled="disabled"
        :aria-invalid="!!parsed.error"
        @input="onInput"
      />
      <slot name="suffix"></slot>
      <button
        type="button"
        class="unitbtn"
        :disabled="disabled"
        :title="disabled ? 'Satuan' : 'Klik untuk ganti satuan'"
        @click="toggleUnit"
      >
        {{ unit === 'pack' ? 'Pack' : 'PCS' }}
      </button>
    </div>
    <!-- peringatan melebur ke baris hint (warna amber + field amber): tanpa baris tambahan -->
    <div v-if="!parsed.error" class="hint" :class="{ warn: !!parsed.warn }">
      {{ hint }}<template v-if="parsed.warn"> · {{ parsed.warn }}</template>
    </div>
    <div v-if="parsed.error" class="err">{{ parsed.error }}</div>
  </div>
</template>
